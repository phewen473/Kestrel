"""Building and receiving a complete Kestrel frame at any speed level.

Frame layout on the air:
    chirp pair (2 s) | header (24 tones) | body (data tones with a pilot before every 15)

The header and the body are both sent at the frame's own speed level. The
receiver does not need to be told the level: it tries the header at each
level and accepts the one whose check value matches and whose level field
agrees with the level it was tried at.
"""

from dataclasses import dataclass  # simple record type for the receiver's report
from math import ceil  # round up

import numpy as np  # numerical arrays

from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .blanker import blank_impulses  # static-crash blanker
from .chirp import detect_chirp_pair, make_chirp_pair  # signature chirp
from .crc import crc8, crc16  # check values
from .fec import TAIL, conv_encode, viterbi_decode  # error correction
from .interleave import deinterleave, interleave  # bit shuffler
from .levels import LEVELS  # the speed levels
from .mfsk import bits_to_symbols, energies_to_llrs, noise_level, pilot_frequency_fit, symbol_energies, symbols_to_audio  # tone waveform
from .params import (  # frame format numbers
    BITS_PER_SYMBOL, BODY_CRC_BITS, CHAR_BITS, CHIRP_SAMPLES, FRAME_TYPE_MESSAGE, FS, HEADER_CRC_BITS,  # (continued)
    HEADER_FIELD_BITS, HEADER_REPEAT, LENGTH_BITS, M_TONES, MAX_PARTS, PILOT_EVERY, PILOT_START, PILOT_STEP,  # (continued)
    REF_BANDWIDTH_HZ, SIZE_CLASSES,  # (continued)
)  # end of the import list
from .text import bits_to_text, pick_size_class, text_to_bits  # message <-> bits

HEADER_CODED_BITS = 2 * (HEADER_FIELD_BITS + HEADER_CRC_BITS + TAIL)  # coded header length (60 bits)
HEADER_SYMBOLS_ONCE = ceil(HEADER_CODED_BITS / BITS_PER_SYMBOL)  # tones for one copy of the header (12)
HEADER_SYMBOLS = HEADER_SYMBOLS_ONCE * HEADER_REPEAT  # tones for both copies (24)


def body_layout(size_class):  # work out the shape of the body for a size class
    """Return a dict describing the body: bit counts, tone counts and where the pilots sit."""
    info = LENGTH_BITS + CHAR_BITS * SIZE_CLASSES[size_class] + BODY_CRC_BITS  # length field + characters + check
    coded = 2 * (info + TAIL)  # bits after error-correction coding
    ndata = ceil(coded / BITS_PER_SYMBOL)  # data tones needed
    npilot = ceil(ndata / PILOT_EVERY)  # one pilot per 15 data tones
    total = ndata + npilot  # all body tones
    pilot_pos = np.arange(npilot) * (PILOT_EVERY + 1)  # pilots sit at tones 0, 16, 32, ...
    is_pilot = np.zeros(total, dtype=bool)  # marks which body tones are pilots
    is_pilot[pilot_pos] = True  # flag the pilot positions
    return {  # everything the transmitter and receiver need
        "info": info,  # data bits before coding
        "coded": coded,  # bits after coding
        "padded": ndata * BITS_PER_SYMBOL,  # coded bits rounded up to whole tones
        "total": total,  # body tones including pilots
        "pilot_pos": pilot_pos,  # where the pilots are
        "data_pos": np.flatnonzero(~is_pilot),  # where the data tones are
        "pilot_tones": (PILOT_STEP * np.arange(npilot) + PILOT_START) % M_TONES,  # which tone each pilot uses
    }  # end of the layout


def frame_seconds(size_class, level=0):  # how long a frame lasts on the air
    """Return the airtime of a whole frame, in seconds."""
    return 2 * CHIRP_SAMPLES / FS + (HEADER_SYMBOLS + body_layout(size_class)["total"]) * LEVELS[level].seconds  # chirps + header + body


def _header_bits(level, size_class, part, parts):  # the self-describing header
    """Return the 24 header bits: the six fields and their check value."""
    fields = np.concatenate([  # the fields, in order
        int_to_bits(FRAME_TYPE_MESSAGE, 3),  # frame type
        int_to_bits(level, 3),  # speed level
        int_to_bits(size_class, 2),  # size class
        int_to_bits(part, 3),  # which part of the message this is (0 = first)
        int_to_bits(parts - 1, 3),  # how many parts the message has, minus one
        int_to_bits(0, 2),  # two spare bits for later use
    ])  # end of the fields
    return np.concatenate([fields, crc8(fields)])  # fields followed by their check value


def build_frame(text, level=0, part=0, parts=1):  # the transmitter
    """Return the audio (floats between -1 and 1) of a frame carrying `text`.

    `part` and `parts` say which piece of a split message this frame is;
    leave them alone for a message sent whole.
    """
    if not 0 <= part < parts <= MAX_PARTS:  # the part numbers must make sense
        raise ValueError("bad part number")  # refuse nonsense
    spec = LEVELS[level]  # the numbers for this speed level
    size_class = pick_size_class(len(text))  # smallest frame that fits the text
    layout = body_layout(size_class)  # shape of the body for that size
    header_syms = bits_to_symbols(conv_encode(_header_bits(level, size_class, part, parts)))  # coded header as tones
    header_syms = np.tile(header_syms, HEADER_REPEAT)  # send the header twice
    data_bits = text_to_bits(text, size_class)  # length field + characters + padding
    data_bits = np.concatenate([data_bits, crc16(data_bits)])  # add the body check value
    coded = conv_encode(data_bits)  # add error correction
    coded = np.concatenate([coded, np.zeros(layout["padded"] - layout["coded"], dtype=np.uint8)])  # round up to whole tones
    body_syms = np.zeros(layout["total"], dtype=np.int64)  # room for every body tone
    body_syms[layout["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    body_syms[layout["pilot_pos"]] = layout["pilot_tones"]  # known tones go in the pilot positions
    return np.concatenate([make_chirp_pair(), symbols_to_audio(np.concatenate([header_syms, body_syms]), spec)])  # chirps, then all the tones


@dataclass  # a plain record of what the receiver found
class RxResult:  # the receiver's report
    """Everything the receiver learned from one frame."""

    ok: bool = False  # True when the frame passed its check
    text: str = ""  # the decoded text (empty when not ok)
    reason: str = ""  # why decoding stopped, when not ok
    start: float = 0.0  # sample where the frame began
    offset_hz: float = 0.0  # measured frequency offset at the start of the body
    drift_hz_s: float = 0.0  # measured frequency drift, in Hz per second
    snr_db: float = float("nan")  # measured signal-to-noise ratio in 2.5 kHz
    chirp_quality: float = 0.0  # strength of the chirp detection
    level: int = -1  # speed level read from the header
    size_class: int = -1  # size class read from the header
    part: int = 0  # which part of a split message this frame is (0 = first)
    parts: int = 1  # how many parts the message has
    body_llrs: np.ndarray = None  # soft bits of the body, kept so a retry can be combined with them


def _read_header(x, header_start, offset):  # find out which level the frame uses
    """Try the header at every speed level; return (level record, header bits) or (None, None)."""
    for spec in LEVELS:  # one speed level at a time
        tone_e = symbol_energies(x, header_start, HEADER_SYMBOLS, spec, offset)  # measure the header tones as if sent at this level
        llrs = energies_to_llrs(tone_e, noise_level(tone_e))  # turn them into soft bits
        llrs = llrs.reshape(HEADER_REPEAT, -1).sum(axis=0)[:HEADER_CODED_BITS]  # add the two copies together, drop the padding
        bits = viterbi_decode(llrs)  # correct errors
        check_ok = np.array_equal(crc8(bits[:HEADER_FIELD_BITS]), bits[HEADER_FIELD_BITS:])  # does the check value match?
        if check_ok and bits_to_int(bits[3:6]) == spec.number:  # and does the header name the level we tried?
            return spec, bits  # yes: this is the frame's level
    return None, None  # no level produced a valid header


def receive(x, blank=True, prior_llrs=None):  # the receiver
    """Find and decode one frame in the audio `x`.

    `prior_llrs` may hold the body_llrs of an earlier failed copy of the
    same frame; they are added to this copy's soft bits before decoding
    (this is the "combine retries" feature, HARQ).
    """
    result = RxResult()  # start with an empty report
    x = np.asarray(x, dtype=float)  # make sure we have floating-point audio
    if blank:  # optional first step
        x = blank_impulses(x)  # silence static crashes
    candidates = detect_chirp_pair(x)  # look for the signature chirp (best few candidates)
    if not candidates:  # recording too short to hold a chirp
        result.reason = "no chirp found"  # say why we stopped
        return result  # give up
    spec = None  # the frame's speed level, once a header passes its check
    for found in candidates:  # try the strongest candidate first
        offset = found["offset_hz"]  # frequency error measured from the chirp
        header_start = found["start"] + 2 * CHIRP_SAMPLES  # the header follows the two sweeps
        spec, header = _read_header(x, header_start, offset)  # try to read the header
        if spec is not None:  # this candidate is a real frame
            break  # stop looking
    result.start = found["start"]  # when the frame began (the last candidate tried)
    result.chirp_quality = found["quality"]  # how strong the detection was
    if spec is None:  # no candidate produced a valid header
        result.reason = "header check failed"  # say why we stopped
        return result  # give up: we cannot know the frame's shape
    frame_type = bits_to_int(header[0:3])  # first field: frame type
    result.level = spec.number  # second field: speed level (already confirmed)
    result.size_class = bits_to_int(header[6:8])  # third field: size class
    result.part = bits_to_int(header[8:11])  # fourth field: part number
    result.parts = bits_to_int(header[11:14]) + 1  # fifth field: part count
    if frame_type != FRAME_TYPE_MESSAGE or result.size_class >= len(SIZE_CLASSES) or result.part >= result.parts:  # only sensible message frames are accepted
        result.reason = "unsupported frame"  # say why we stopped
        return result  # give up
    layout = body_layout(result.size_class)  # the header told us the body's shape
    body_start = header_start + HEADER_SYMBOLS * spec.samples  # the body follows the header
    extra, drift = pilot_frequency_fit(x, body_start, layout["pilot_pos"], layout["pilot_tones"], spec, offset)  # fine frequency and drift from the pilots
    result.offset_hz = offset + extra  # best estimate of the offset at the start of the body
    result.drift_hz_s = drift  # best estimate of the drift
    tone_e = symbol_energies(x, body_start, layout["total"], spec, result.offset_hz, drift)  # measure every body tone
    noise = noise_level(tone_e)  # average noise energy per tone position
    pilot_e = tone_e[layout["pilot_pos"], layout["pilot_tones"]].mean()  # average energy of the known pilot tones
    ratio = max(pilot_e - noise, 1e-12) / noise  # signal energy compared with noise energy
    result.snr_db = 10 * np.log10(ratio / (spec.seconds * REF_BANDWIDTH_HZ))  # convert to SNR in 2.5 kHz
    llrs = deinterleave(energies_to_llrs(tone_e[layout["data_pos"]], noise))[:layout["coded"]]  # soft bits back in original order, padding dropped
    if prior_llrs is not None:  # an earlier copy of this frame is available
        llrs = llrs + prior_llrs  # combine the two copies
    result.body_llrs = llrs  # keep the soft bits in case another retry follows
    data = viterbi_decode(llrs)  # correct errors in the body
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the body check must match
        result.reason = "body check failed"  # say why we stopped
        return result  # the caller may retry and combine
    result.text = bits_to_text(data[:-BODY_CRC_BITS])  # turn the bits back into text
    result.ok = True  # success
    return result  # the finished report
