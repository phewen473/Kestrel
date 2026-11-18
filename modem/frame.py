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

from .address import bits_to_call, call_to_bits  # callsign <-> bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .blanker import blank_impulses  # static-crash blanker
from .chirp import detect_chirp_pair, make_chirp_pair  # signature chirp
from .crc import crc8, crc16  # check values
from .fec import TAIL, conv_encode, viterbi_decode  # error correction for the header
from . import ldpc  # error correction for the body
from .interleave import deinterleave, interleave  # bit shuffler
from .levels import LEVELS  # the speed levels
from .mfsk import (  # tone waveform
    band_energies, bits_to_symbols, energies_to_llrs, known_tone_energies, noise_level, pilot_frequency_fit,  # (continued)
    signal_report, symbol_energies, symbols_to_audio, tone_energies,  # (continued)
)  # end of the import list
from .params import (  # frame format numbers
    ADDRESS_BITS, BITS_PER_SYMBOL, BODY_CRC_BITS, CALL_BITS, CHAR_BITS, CHIRP_SAMPLES, FRAME_TYPE_ADDRESSED, FRAME_TYPE_LINK, FS,  # (continued)
    HEADER_CRC_BITS, HEADER_FIELD_BITS, HEADER_REPEAT, HOP_BITS, LENGTH_BITS, LIFE_BITS, LIFE_UNIT_HOURS, LINK_ID_BITS, M_TONES,  # (continued)
    MAX_PARTS, MSG_ID_BITS, PILOT_EVERY, PILOT_START, PILOT_STEP, REF_BANDWIDTH_HZ, SIZE_CLASSES,  # (continued)
)  # end of the import list
from .text import bits_to_text, choose_packing, text_to_bits  # message <-> bits

HEADER_CODED_BITS = 2 * (HEADER_FIELD_BITS + HEADER_CRC_BITS + TAIL)  # coded header length (60 bits)
HEADER_SYMBOLS_ONCE = ceil(HEADER_CODED_BITS / BITS_PER_SYMBOL)  # tones for one copy of the header (12)
HEADER_SYMBOLS = HEADER_SYMBOLS_ONCE * HEADER_REPEAT  # tones for both copies (24)


def body_layout(size_class):  # work out the shape of the body for a size class
    """Return a dict describing the body: bit counts, tone counts and where the pilots sit.

    Both kinds of frame have the same body size. A fully addressed frame
    has a longer address block and correspondingly less room for text.
    """
    info = ADDRESS_BITS[FRAME_TYPE_LINK] + LENGTH_BITS + CHAR_BITS * SIZE_CLASSES[size_class] + BODY_CRC_BITS  # address block + length field + text room + check
    coded = 2 * info  # bits after error-correction coding (the LDPC code doubles them)
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


def _header_bits(frame_type, level, size_class, part, parts, compressed):  # the self-describing header
    """Return the 24 header bits: the six fields and their check value."""
    fields = np.concatenate([  # the fields, in order
        int_to_bits(frame_type, 3),  # frame type
        int_to_bits(level, 3),  # speed level
        int_to_bits(size_class, 2),  # size class
        int_to_bits(part, 3),  # which part of the message this is (0 = first)
        int_to_bits(parts - 1, 3),  # how many parts the message has, minus one
        int_to_bits(int(compressed), 1),  # 1 when the text is compressed
        int_to_bits(0, 1),  # one spare bit for later use
    ])  # end of the fields
    return np.concatenate([fields, crc8(fields)])  # fields followed by their check value


def _body_symbols(data_bits, layout):  # body bits -> the tones of the body
    """Return the tone number of every body symbol for the given body bits (check value included)."""
    coded = ldpc.encode(data_bits)  # add error correction
    coded = np.concatenate([coded, np.zeros(layout["padded"] - layout["coded"], dtype=np.uint8)])  # round up to whole tones
    body_syms = np.zeros(layout["total"], dtype=np.int64)  # room for every body tone
    body_syms[layout["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    body_syms[layout["pilot_pos"]] = layout["pilot_tones"]  # known tones go in the pilot positions
    return body_syms  # pilots and data tones, in sending order


def _address_block(frame_type, link, msg_id, dest, origin, hops, life_hours):  # the addressing at the start of the body
    """Return the address block bits: 28 for a link frame, 120 for a fully addressed frame."""
    if not 0 <= msg_id < (1 << MSG_ID_BITS):  # the message number must fit its field
        raise ValueError("message number out of range")  # refuse nonsense
    if frame_type == FRAME_TYPE_LINK:  # a message between two locked stations
        if not 0 <= link < (1 << LINK_ID_BITS):  # the link number must fit its field
            raise ValueError("link number out of range")  # refuse nonsense
        return np.concatenate([int_to_bits(link, LINK_ID_BITS), int_to_bits(msg_id, MSG_ID_BITS)])  # link number, then message number
    life = -(-int(life_hours) // LIFE_UNIT_HOURS)  # remaining lifetime in two-hour steps, rounded up
    if not 0 <= hops < (1 << HOP_BITS) or not 0 <= life < (1 << LIFE_BITS):  # both counters must fit their fields
        raise ValueError("hop count or lifetime out of range")  # refuse nonsense
    return np.concatenate([  # the five fields, in order
        call_to_bits(dest),  # who the message is for
        call_to_bits(origin),  # who wrote it
        int_to_bits(msg_id, MSG_ID_BITS),  # the origin's number for this message
        int_to_bits(hops, HOP_BITS),  # how many stations have relayed it so far
        int_to_bits(life, LIFE_BITS),  # how long it may still be kept, in two-hour steps
    ])  # end of the address block


def build_frame(text, level=0, part=0, parts=1, link=0, msg_id=0, dest=None, origin=None, hops=0, life_hours=48):  # the transmitter
    """Return the audio (floats between -1 and 1) of a frame carrying `text`.

    `part` and `parts` say which piece of a split message this frame is;
    leave them alone for a message sent whole. `msg_id` is the origin's
    number for the message. With no `dest`, the frame is a link frame and
    carries the short `link` number of the two locked stations. With
    `dest` and `origin` (callsigns or group names), it is a fully
    addressed frame that also carries `hops` (relays so far) and
    `life_hours` (how long it may still be kept); its longer address
    block leaves room for 13 fewer plain characters.
    """
    if not 0 <= part < parts <= MAX_PARTS:  # the part numbers must make sense
        raise ValueError("bad part number")  # refuse nonsense
    if (dest is None) != (origin is None):  # one address without the other
        raise ValueError("give both dest and origin, or neither")  # refuse nonsense
    frame_type = FRAME_TYPE_LINK if dest is None else FRAME_TYPE_ADDRESSED  # which kind of frame this is
    spec = LEVELS[level]  # the numbers for this speed level
    size_class, compressed = choose_packing(text, frame_type)  # smallest frame that fits the text, and whether to compress it
    layout = body_layout(size_class)  # shape of the body for that size
    header_syms = bits_to_symbols(conv_encode(_header_bits(frame_type, level, size_class, part, parts, compressed)))  # coded header as tones
    header_syms = np.tile(header_syms, HEADER_REPEAT)  # send the header twice
    data_bits = np.concatenate([_address_block(frame_type, link, msg_id, dest, origin, hops, life_hours), text_to_bits(text, size_class, compressed, frame_type)])  # address block, character count, text bits, padding
    data_bits = np.concatenate([data_bits, crc16(data_bits)])  # add the body check value
    body_syms = _body_symbols(data_bits, layout)  # error correction, shuffling and pilots
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
    fade_index: float = float("nan")  # how much the signal faded during the frame: 0 = steady, about 1 = deep, frequent fades
    chirp_quality: float = 0.0  # strength of the chirp detection
    level: int = -1  # speed level read from the header
    size_class: int = -1  # size class read from the header
    part: int = 0  # which part of a split message this frame is (0 = first)
    parts: int = 1  # how many parts the message has
    compressed: bool = False  # True when the text was sent compressed
    frame_type: int = -1  # kind of frame read from the header (0 = link frame, 1 = fully addressed)
    msg_id: int = -1  # the origin's number for the message
    link: int = -1  # short link number (link frames only)
    dest: str = ""  # destination callsign or group name (fully addressed frames only)
    origin: str = ""  # originating callsign (fully addressed frames only)
    hops: int = 0  # relays so far (fully addressed frames only)
    life_hours: int = 0  # hours the message may still be kept (fully addressed frames only)
    body_llrs: np.ndarray = None  # soft bits of the body, kept so a retry can be combined with them


def _read_headers(x, header_start, offset):  # find out which level the frame uses
    """Try the header at every speed level; yield (level record, header bits) for each level whose header checks out.

    Normally exactly one level passes. Very rarely (about one frame in a
    thousand) noise makes a second level pass too, which is why the caller
    goes on to check the body before believing a header.
    """
    for spec in LEVELS:  # one speed level at a time
        tone_e = symbol_energies(x, header_start, HEADER_SYMBOLS, spec, offset)  # measure the header tones as if sent at this level
        llrs = energies_to_llrs(tone_e, noise_level(tone_e))  # turn them into soft bits
        llrs = llrs.reshape(HEADER_REPEAT, -1).sum(axis=0)[:HEADER_CODED_BITS]  # add the two copies together, drop the padding
        bits = viterbi_decode(llrs)  # correct errors
        check_ok = np.array_equal(crc8(bits[:HEADER_FIELD_BITS]), bits[HEADER_FIELD_BITS:])  # does the check value match?
        if check_ok and bits_to_int(bits[3:6]) == spec.number and bits[15] == 0:  # and does the header name the level we tried, with the spare bit clear?
            yield spec, bits  # yes: this may be the frame's level


def _decode_body(x, found, spec, header, prior_llrs):  # read the rest of a frame once its header is known
    """Return the receiver's report for the frame that `header` describes."""
    result = RxResult(start=found["start"], chirp_quality=found["quality"], level=spec.number)  # start the report with what the chirp and header told us
    result.frame_type = bits_to_int(header[0:3])  # first field: frame type
    result.size_class = bits_to_int(header[6:8])  # third field: size class
    result.part = bits_to_int(header[8:11])  # fourth field: part number
    result.parts = bits_to_int(header[11:14]) + 1  # fifth field: part count
    result.compressed = bool(header[14])  # sixth field: is the text compressed?
    if result.frame_type not in ADDRESS_BITS or result.part >= result.parts:  # only sensible message frames are accepted
        result.reason = "unsupported frame"  # say why we stopped
        return result  # give up on this reading of the header
    offset = found["offset_hz"]  # frequency error measured from the chirp
    layout = body_layout(result.size_class)  # the header told us the body's shape
    body_start = found["start"] + 2 * CHIRP_SAMPLES + HEADER_SYMBOLS * spec.samples  # the body follows the chirps and the header
    extra, drift = pilot_frequency_fit(x, body_start, layout["pilot_pos"], layout["pilot_tones"], spec, offset)  # fine frequency and drift from the pilots
    result.offset_hz = offset + extra  # best estimate of the offset at the start of the body
    result.drift_hz_s = drift  # best estimate of the drift
    band = band_energies(x, body_start, layout["total"], spec, result.offset_hz, drift)  # measure every bin of the tone band, for every body tone
    tone_e = tone_energies(band, spec)  # the 32 tone positions
    noise = noise_level(tone_e)  # average noise energy per tone position
    _measure(result, band[layout["pilot_pos"]], layout["pilot_tones"], noise, spec)  # first reading of SNR and fading, from the pilots alone
    llrs = deinterleave(energies_to_llrs(tone_e[layout["data_pos"]], noise))[:layout["coded"]]  # soft bits back in original order, padding dropped
    if prior_llrs is not None and len(prior_llrs) == len(llrs):  # an earlier copy of this frame is available
        llrs = llrs + prior_llrs  # combine the two copies
    result.body_llrs = llrs  # keep the soft bits in case another retry follows
    data, _ = ldpc.decode(llrs, layout["info"])  # correct errors in the body
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the body check must match
        result.reason = "body check failed"  # say why we stopped
        return result  # the caller may retry and combine
    block = ADDRESS_BITS[result.frame_type]  # length of the address block at the start of the body
    try:  # the check passed, so this should always work
        _read_address_block(result, data[:block])  # who the frame is for, and which message it is
        result.text = bits_to_text(data[block:-BODY_CRC_BITS], result.compressed)  # turn the rest back into text
    except ValueError:  # a damaged frame slipped past the check (very rare)
        result.reason = "body could not be read"  # say why we stopped
        return result  # give up on this copy
    result.ok = True  # success
    _measure(result, band, _body_symbols(data, layout), noise, spec)  # better reading: now every tone of the body is known, not just the pilots
    return result  # the finished report


def _read_address_block(result, bits):  # unpack the addressing at the start of the body
    """Put the address fields carried by `bits` into `result`; raise ValueError when an address is not valid."""
    if result.frame_type == FRAME_TYPE_LINK:  # a message between two locked stations
        result.link = bits_to_int(bits[:LINK_ID_BITS])  # the short link number
        result.msg_id = bits_to_int(bits[LINK_ID_BITS:])  # the message number
        return  # nothing more in a link frame
    result.dest = bits_to_call(bits[:CALL_BITS])  # who the message is for
    result.origin = bits_to_call(bits[CALL_BITS:2 * CALL_BITS])  # who wrote it
    rest = bits[2 * CALL_BITS:]  # the three counters that follow the addresses
    result.msg_id = bits_to_int(rest[:MSG_ID_BITS])  # the message number
    result.hops = bits_to_int(rest[MSG_ID_BITS:MSG_ID_BITS + HOP_BITS])  # relays so far
    result.life_hours = bits_to_int(rest[MSG_ID_BITS + HOP_BITS:]) * LIFE_UNIT_HOURS  # remaining lifetime, back in hours


def _measure(result, band, tones, noise, spec):  # fill in the channel measurements
    """Put the SNR and fading index into `result`, from body symbols whose tones are known."""
    ratio, result.fade_index = signal_report(known_tone_energies(band, tones, spec), noise)  # signal against noise, and how much it faded
    result.snr_db = 10 * np.log10(max(ratio, 1e-12) / (spec.seconds * REF_BANDWIDTH_HZ))  # convert to SNR in 2.5 kHz


def _score(result):  # how believable a failed attempt is
    """Return a number that is higher for the failed attempt most likely to be the real frame."""
    return result.snr_db if result.body_llrs is not None and np.isfinite(result.snr_db) else -1e9  # the pilots of the real frame show the highest SNR


def receive(x, blank=True, prior_llrs=None):  # the receiver
    """Find and decode one frame in the audio `x`.

    `prior_llrs` may hold the body_llrs of an earlier failed copy of the
    same frame; they are added to this copy's soft bits before decoding
    (this is the "combine retries" feature, HARQ).
    """
    x = np.asarray(x, dtype=float)  # make sure we have floating-point audio
    if blank:  # optional first step
        x = blank_impulses(x)  # silence static crashes
    candidates = detect_chirp_pair(x)  # look for the signature chirp (best few candidates)
    if not candidates:  # recording too short to hold a chirp
        return RxResult(reason="no chirp found")  # give up
    best = None  # the most believable failed attempt so far
    for found in candidates:  # try the strongest chirp candidate first
        header_start = found["start"] + 2 * CHIRP_SAMPLES  # the header follows the two sweeps
        for spec, header in _read_headers(x, header_start, found["offset_hz"]):  # every level whose header checks out
            attempt = _decode_body(x, found, spec, header, prior_llrs)  # try to read the body at that level
            if attempt.ok:  # the body checked out too
                return attempt  # this is the frame
            if best is None or _score(attempt) > _score(best):  # otherwise remember the most believable failure
                best = attempt  # keep it
    if best is not None:  # a header was found but no body decoded
        return best  # report that failure (its soft bits can be combined with a retry)
    return RxResult(reason="header check failed", start=candidates[0]["start"], chirp_quality=candidates[0]["quality"])  # no header at all
