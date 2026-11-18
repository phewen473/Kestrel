"""Tests of the individual building blocks of the modem."""

import numpy as np  # numerical arrays
import pytest  # test framework

from modem.chirp import make_chirp_pair, detect_chirp_pair  # signature chirp
from modem.crc import crc8, crc16  # check values
from modem.fec import conv_encode, viterbi_decode  # error correction
from modem.interleave import deinterleave, interleave, permutation  # bit shuffler
from modem.text import bits_to_text, pick_size_class, text_to_bits  # message <-> bits
from sim import run_channel  # channel simulator


def _bytes_to_bits(data):  # helper for the CRC test
    """Return the bits of `data`, most significant bit of each byte first."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))  # numpy does the unpacking


def test_text_roundtrip_keeps_control_characters():  # 7-bit ASCII must survive, control characters included
    text = "Bell\x07 Tab\t Newline\n Escape\x1b Null\x00 DEL\x7f end"  # a message full of control characters
    bits = text_to_bits(text, pick_size_class(len(text)))  # message -> bits
    assert len(bits) == 8 + 7 * 50  # length field plus fifty 7-bit characters
    assert bits_to_text(bits) == text  # bits -> the very same message


def test_size_class_is_smallest_that_fits():  # 50, 100 or 200 characters
    assert [pick_size_class(n) for n in (0, 50, 51, 100, 101, 200)] == [0, 0, 1, 1, 2, 2]  # boundaries land in the right class
    with pytest.raises(ValueError):  # 201 characters is too many
        pick_size_class(201)  # must be refused


def test_text_rejects_non_ascii():  # only 7-bit ASCII is allowed
    with pytest.raises(ValueError):  # an accented letter is outside 7-bit ASCII
        text_to_bits("café", 0)  # must be refused


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
