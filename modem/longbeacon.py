"""The long beacon: a compact, slow frame for being heard at the edge of what the path allows (signal version 0.27).

A normal beacon (31 seconds at L0) is heard down to about -21 dB on a steady
path. The long beacon trades everything but the essentials for reach: it
carries only the callsign, the four-character grid and two flags, and it
has no header, because its own twelve-tone pattern says what it is. That
leaves room in about a minute for tones three times as long as L0's:

    preamble (12 tones, the long pattern) | body (36 data tones with 3 pilots)

    51 tones x 1.167 s = 59.5 s, 32 tones 2.57 Hz apart (about 82 Hz wide), centred near 1500 Hz.

The body is 66 field bits (callsign 48, grid 15, available 1, holds mail 1,
spare 1) and a CRC-16, coded with the same K=7 rate-1/2 convolutional code
as the header and the control frames, shuffled and sent as 5-bit tones with
a pilot before every 15 data tones, exactly as a control frame's body.

A long beacon asks for nothing: no station answers it. Receiving stations
show it to their operator (spec Section 6.13).
"""

import numpy as np  # numerical arrays

from .address import bits_to_call, call_to_bits  # callsign <-> bits
from .control import bits_to_grid, grid_to_bits  # grid locator <-> bits
from .crc import crc16  # the body's check value
from .fec import TAIL, conv_encode, viterbi_decode  # the convolutional code
from .interleave import deinterleave, interleave  # bit shuffler
from .levels import Level  # one level's numbers
from .mfsk import band_energies, bits_to_symbols, energies_to_llrs, known_tone_energies, noise_level, pilot_frequency_fit, signal_report, symbols_to_audio, tone_energies  # the tone waveform
from .params import BODY_CRC_BITS, CALL_BITS, FRAME_TYPE_LONG, GRID_BITS, LONG_LEVEL, LONG_SAMPLES, LONG_STEP, PREAMBLE_TONES, REF_BANDWIDTH_HZ  # the numbers that define it
from .preamble import detect_preamble, make_preamble  # its twelve-tone pattern

LONG = Level(LONG_LEVEL, LONG_SAMPLES, LONG_STEP)  # the long beacon's tone length and spacing, as a level
FIELD_BITS = CALL_BITS + GRID_BITS + 3  # callsign, grid and three flag bits (available, holds mail, spare)
MIN_SNR_DB = -25.6  # weakest SNR (2.5 kHz, noise only) at which every test long beacon decoded (40 a point, 21 November 2026; nine in ten at -26.6, nine in ten at -18.6 in the worst fading)


def _layout():  # the body's shape
    """Return the body layout: the same rules as a control frame's body (frame._layout)."""
    from .frame import _layout as layout  # imported here: frame.py imports this module
    info = FIELD_BITS + BODY_CRC_BITS  # the fields and their check
    return layout(info, 2 * (info + TAIL))  # the convolutional code doubles the bits, after six tail bits


LAYOUT = _layout()  # worked out once
TOTAL_TONES = PREAMBLE_TONES + LAYOUT["total"]  # tones in the whole frame (51)
SECONDS = TOTAL_TONES * LONG.seconds  # its airtime (59.5 s)
SAMPLES = TOTAL_TONES * LONG.samples  # and in samples


def pack(call, grid, available=True, holds_mail=False):  # fields -> bits
    """Return the 66 field bits of a long beacon."""
    flags = np.array([int(bool(available)), int(bool(holds_mail)), 0], dtype=np.uint8)  # available, holds mail, spare
    return np.concatenate([call_to_bits(call), grid_to_bits(grid), flags])  # callsign, grid, flags


def unpack(bits):  # bits -> fields
    """Return the fields of a long beacon as a dict: origin, grid, available, holds_mail."""
    rest = bits[CALL_BITS:]  # after the callsign
    return {"origin": bits_to_call(bits[:CALL_BITS]), "grid": bits_to_grid(rest[:GRID_BITS]), "available": bool(rest[GRID_BITS]), "holds_mail": bool(rest[GRID_BITS + 1]), "long": True}  # the fields


def build_long_beacon(call, grid, available=True, holds_mail=False):  # the transmitter
    """Return the audio of a long beacon from `call` at `grid`."""
    fields = pack(call, grid, available, holds_mail)  # the fields
    data = np.concatenate([fields, crc16(fields)])  # and their check value
    coded = conv_encode(data)  # error correction
    coded = np.concatenate([coded, np.zeros(LAYOUT["padded"] - LAYOUT["coded"], dtype=np.uint8)])  # round up to whole tones
    body = np.zeros(LAYOUT["total"], dtype=np.int64)  # room for every body tone
    body[LAYOUT["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    body[LAYOUT["pilot_pos"]] = LAYOUT["pilot_tones"]  # known tones in the pilot positions
    return np.concatenate([make_preamble(LONG), symbols_to_audio(body, LONG)])  # the long pattern, then the body


def candidates(x, keep=3):  # where long beacons may start
    """Return the long pattern's best candidates in `x` (as preamble.detect_preamble)."""
    return detect_preamble(x, LONG, keep=keep)  # the same search as every level, with the long pattern and tone length


def decode_at(x, found, result):  # read one candidate's body
    """Fill in `result` (an RxResult started for the candidate `found`) from the long beacon's body; return it."""
    result.level, result.frame_type, result.header_copy = LONG_LEVEL, FRAME_TYPE_LONG, "none (long beacon)"  # what it is
    body_start = int(found["start"]) + PREAMBLE_TONES * LONG.samples  # the body follows the pattern
    if body_start + LAYOUT["total"] * LONG.samples > len(x) + LONG.samples // 4:  # not all here yet
        result.reason = "frame incomplete"  # say why
        return result  # look again later
    extra, drift = pilot_frequency_fit(x, body_start, LAYOUT["pilot_pos"], LAYOUT["pilot_tones"], LONG, found["offset_hz"])  # fine frequency and drift from the pilots
    result.offset_hz, result.drift_hz_s = found["offset_hz"] + extra, drift  # best estimates
    band = band_energies(x, body_start, LAYOUT["total"], LONG, result.offset_hz, drift)  # every bin of the tone band, every body tone
    tone_e = tone_energies(band, LONG)  # the 32 tone positions
    noise = noise_level(tone_e)  # noise energy per tone position
    _measure(result, band[LAYOUT["pilot_pos"]], LAYOUT["pilot_tones"], noise)  # a first reading from the pilots
    llrs = deinterleave(energies_to_llrs(tone_e[LAYOUT["data_pos"]], noise))[:LAYOUT["coded"]]  # soft bits in original order
    data = viterbi_decode(llrs)  # correct errors
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the check must match
        result.reason = "body check failed"  # say why
        return result  # not a long beacon (or too damaged)
    try:  # the check passed, so this should work
        result.fields = unpack(data[:FIELD_BITS])  # the fields
    except ValueError:  # a damaged frame slipped past the check (very rare)
        result.reason = "body could not be read"  # say why
        return result  # give up on it
    result.origin = result.fields["origin"]  # the sender, where every frame keeps it
    result.ok = True  # success
    coded = conv_encode(data)  # the coded bits, to know every body tone for a better reading
    coded = np.concatenate([coded, np.zeros(LAYOUT["padded"] - LAYOUT["coded"], dtype=np.uint8)])  # rounded up as sent
    tones = np.zeros(LAYOUT["total"], dtype=np.int64)  # every body tone
    tones[LAYOUT["data_pos"]] = bits_to_symbols(interleave(coded))  # the data tones
    tones[LAYOUT["pilot_pos"]] = LAYOUT["pilot_tones"]  # and the pilots
    _measure(result, band, tones, noise)  # better reading, from all of them
    return result  # the finished report


def _measure(result, band, tones, noise):  # SNR and fading
    """Put the SNR (in 2.5 kHz) and the fading index into `result`, from body symbols whose tones are known."""
    ratio, result.fade_index = signal_report(known_tone_energies(band, tones, LONG), noise)  # signal against noise, and fading
    result.snr_db = 10 * np.log10(max(ratio, 1e-12) / (LONG.seconds * REF_BANDWIDTH_HZ))  # in 2.5 kHz
