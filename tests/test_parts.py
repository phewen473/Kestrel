"""Tests of the individual building blocks of the modem."""

import numpy as np  # numerical arrays
import pytest  # test framework

from modem.chirp import make_chirp_pair, detect_chirp_pair  # signature chirp
from modem.crc import crc8, crc16  # check values
from modem.fec import conv_encode, viterbi_decode  # error correction
from modem.interleave import deinterleave, interleave, permutation  # bit shuffler
from modem import ldpc  # LDPC error correction
from modem.compress import LENGTHS, compress, compressed_bits, decompress  # text compression
from modem.text import bits_to_text, choose_packing, pick_size_class, text_to_bits  # message <-> bits
from sim import run_channel  # channel simulator


def _bytes_to_bits(data):  # helper for the CRC test
    """Return the bits of `data`, most significant bit of each byte first."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))  # numpy does the unpacking


def test_text_roundtrip_keeps_control_characters():  # 7-bit ASCII must survive, control characters included
    text = "Bell\x07 Tab\t Newline\n Escape\x1b Null\x00 DEL\x7f end"  # a message full of control characters
    bits = text_to_bits(text, 0, False)  # message -> plain bits in the smallest frame
    assert len(bits) == 8 + 7 * 50  # character count plus fifty 7-bit characters
    assert bits_to_text(bits, False) == text  # bits -> the very same message


def test_size_class_is_smallest_that_fits():  # 50, 100, 150 or 200 plain characters
    assert [pick_size_class("#" * n) for n in (0, 50, 51, 100, 101, 150, 151, 200)] == [0, 0, 1, 1, 2, 2, 3, 3]  # boundaries land in the right class
    with pytest.raises(ValueError):  # 201 characters is too many
        pick_size_class("#" * 201)  # must be refused


def test_text_rejects_non_ascii():  # only 7-bit ASCII is allowed
    with pytest.raises(ValueError):  # an accented letter is outside 7-bit ASCII
        choose_packing("caf\u00e9")  # must be refused


def test_compression_table_is_a_complete_code():  # the code lengths must form a full, unambiguous code
    assert len(LENGTHS) == 128  # one length for every ASCII character
    assert sum(2.0 ** -length for length in LENGTHS) == 1.0  # Kraft equality: no wasted codes and no clashes


def test_compression_roundtrip_for_every_character():  # every character must survive
    text = "".join(chr(c) for c in range(128))  # all 128 ASCII characters once each
    bits = compress(text)  # squeeze
    assert len(bits) == compressed_bits(text)  # the bit count matches the prediction
    assert decompress(bits, len(text)) == text  # and it unsqueezes to the same text


def test_compression_is_used_only_when_it_saves_a_size_class():  # compress only when it shortens the frame
    english = "arrived safe, will call sunday after church. love to all"  # 56 characters of plain English
    assert compressed_bits(english) < 0.8 * 7 * len(english)  # plain English shrinks by more than a fifth
    assert choose_packing(english) == (0, True)  # compressed, it fits the 50-character frame
    assert choose_packing("Q1AAAA DE N1CALL") == (0, False)  # a short text already fits the smallest frame: sent plain
    bits = text_to_bits(english, 0, True)  # pack it compressed
    assert bits_to_text(bits, True) == english  # and it comes back unchanged


def test_ldpc_codeword_satisfies_every_check():  # the encoder and the check table must agree
    rng = np.random.default_rng(3)  # repeatable random source
    for k in (402, 752, 1102, 1452):  # the four body sizes
        data = rng.integers(0, 2, k)  # random data bits
        word = ldpc.encode(data)  # encode them
        assert len(word) == 2 * k and np.array_equal(word[:k], data)  # data first, then as many parity bits
        sums = np.zeros(k, dtype=np.int64)  # ones feeding each check
        for row in ldpc.info_checks(k):  # the three checks of every data bit
            np.add.at(sums, row, data)  # add the data bits in
        sums += word[k:]  # each check also includes its own parity bit...
        sums[1:] += word[k:-1]  # ...and the parity bit before it
        assert not (sums & 1).any()  # every check must come out even
        assert sorted(ldpc.info_checks(k)[0]) == list(range(k))  # each shuffle uses every check exactly once


def test_ldpc_corrects_noisy_input():  # the decoder must fix a noisy codeword
    rng = np.random.default_rng(4)  # repeatable random source
    data = rng.integers(0, 2, 752)  # random data bits
    soft = (1.0 - 2.0 * ldpc.encode(data)) + 0.7 * rng.standard_normal(1504)  # codeword as +1/-1 with strong noise added
    assert (soft < 0).astype(int)[:752].tolist() != data.tolist()  # the noise really did flip some data bits
    decoded, converged = ldpc.decode(soft, 752)  # decode
    assert converged and np.array_equal(decoded, data)  # every check satisfied and the data recovered


def test_crc_matches_published_check_values():  # compare with the standard test message
    bits = _bytes_to_bits(b"123456789")  # the message every CRC catalogue uses
    assert int("".join(map(str, crc16(bits))), 2) == 0x29B1  # CRC-16/CCITT-FALSE check value
    assert int("".join(map(str, crc8(bits))), 2) == 0xF4  # CRC-8 check value


def test_fec_roundtrip_and_error_correction():  # the code must fix scattered errors
    rng = np.random.default_rng(7)  # repeatable random source
    data = rng.integers(0, 2, 300).astype(np.uint8)  # 300 random data bits
    coded = conv_encode(data)  # encode them
    assert len(coded) == 2 * (300 + 6)  # two coded bits per data bit, plus the tail
    soft = 1.0 - 2.0 * coded  # perfect soft bits: +1 for 0, -1 for 1
    assert np.array_equal(viterbi_decode(soft), data)  # clean input decodes exactly
    soft[::25] *= -1  # flip every 25th coded bit (about 4 percent errors)
    assert np.array_equal(viterbi_decode(soft), data)  # the decoder must still recover the data


def test_interleaver_is_a_true_shuffle_and_reverses():  # nothing lost, nothing doubled
    for n in (45, 760, 2860):  # the frame sizes the modem uses, roughly
        perm = permutation(n)  # where each bit goes
        assert sorted(perm) == list(range(n))  # every position used exactly once
        values = np.arange(n)  # something easy to recognise
        assert np.array_equal(deinterleave(interleave(values)), values)  # shuffle then unshuffle gives the original
    assert abs(int(permutation(760)[1]) - int(permutation(760)[0])) > 200  # neighbours end up far apart


def test_chirp_measures_timing_and_frequency_in_noise():  # the chirp pair must find both
    rng = np.random.default_rng(11)  # repeatable random source
    heard = run_channel(make_chirp_pair(), -15.0, rng, offset_hz=15.0, lead_s=0.5, tail_s=0.5)  # chirp 15 dB below the noise, 15 Hz off frequency
    found = detect_chirp_pair(heard)[0]  # look for it and take the strongest candidate
    assert abs(found["start"] - 6000) < 4  # timing within a third of a millisecond (0.5 s lead = sample 6000)
    assert abs(found["offset_hz"] - 15.0) < 0.5  # frequency within half a hertz
    assert found["quality"] > 10  # clearly stronger than the background


def test_callsign_coding_roundtrip_and_limits():  # addresses <-> 48 bits
    from modem.address import bits_to_call, call_to_bits, is_group  # the address helpers
    for call in ("Q1AAAA", "Q2BB", "Q7/Q6FFF", "Q1AAAA/MM", "ALL", "SC-NET", "A"):  # ordinary, compound and group addresses
        bits = call_to_bits(call)  # encode
        assert len(bits) == 48 and bits_to_call(bits) == call  # 48 bits, and it comes back unchanged
    assert bits_to_call(call_to_bits(" q1aaaa ")) == "Q1AAAA"  # spaces around it and lower case are tidied
    assert is_group("ALL") and is_group("SC-NET") and not is_group("Q1AAAA")  # names without a digit are groups
    for bad in ("", "TOOLONGCALL", "KO4 WSC", "Q1AAAA!"):  # empty, too long, a space inside, a character outside the alphabet
        with pytest.raises(ValueError):  # each must be refused
            call_to_bits(bad)  # try to encode it
    with pytest.raises(ValueError):  # 48 one-bits are a number too big to be an address
        bits_to_call(np.ones(48, dtype=np.uint8))  # try to decode them


def test_addressed_frames_hold_less_text():  # the longer address block takes room from the text
    from modem.text import capacity_bits, choose_packing  # the packing helpers
    assert [capacity_bits(c, 0) for c in range(4)] == [350, 700, 1050, 1400]  # link frames
    assert [capacity_bits(c, 1) for c in range(4)] == [258, 608, 958, 1308]  # fully addressed frames: 92 bits fewer
    with pytest.raises(ValueError):  # 200 characters that do not compress...
        choose_packing("~" * 200, 1)  # ...do not fit one addressed frame


def test_channel_report_and_locator_coding():  # the small fields inside control frames
    from modem import control  # the control-frame field packer
    report = control.ChannelReport(snr_db=-7.4, fade_index=0.62, offset_hz=-13.0, want_level=3)  # an ordinary report
    back = control.unpack_report(control.pack_report(report))  # pack it and unpack it
    assert (back.snr_db, back.fade_index, back.offset_hz, back.want_level) == (-7.0, 0.5, -12.0, 3)  # rounded to 1 dB, a quarter, and 2 Hz
    wild = control.unpack_report(control.pack_report(control.ChannelReport(99.0, float("nan"), 500.0, 0)))  # readings far outside the fields
    assert (wild.snr_db, wild.fade_index, wild.offset_hz) == (33.0, 1.75, 62.0)  # each is held to the end of its range; a missing fading reading reads as fading
    assert len(control.pack_report(report)) == 18  # a report is 18 bits
    for grid in ("EM92", "AA00", "RR99", "fn31"):  # corners of the locator range, and lower case
        assert control.bits_to_grid(control.grid_to_bits(grid)) == grid.upper()  # it comes back in capitals
    for bad in ("EM9", "SM92", "EMX2", "EM92AB"):  # too short, a letter past R, a letter for a digit, too long
        with pytest.raises(ValueError):  # each must be refused
            control.grid_to_bits(bad)  # try to encode it
    assert control.bits_to_levels(control.levels_to_bits((0, 2, 4))) == (0, 2, 4)  # the list of levels survives
