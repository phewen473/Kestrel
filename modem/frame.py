"""Building and receiving a complete Kestrel frame at any speed level.

Frame layout on the air (signal version 0.26):
    preamble (12 tones) | header (12 tones) | body (data tones with a pilot before every 15) | header again (12 tones)

The header is sent twice, once at each end of the frame, so a fade that
wipes out one copy almost never wipes out the other. The receiver reads
the first copy; if that fails, it reads the second copy for each length
the body could have, combines the two, and accepts only a header whose
own fields give the body length it was tried at. (Before 0.26 the two
copies were sent back to back, and one fade usually took both.)

The header and the body are both sent at the frame's own speed level. The
receiver does not need to be told the level: it tries the header at each
level and accepts the one whose check value matches and whose level field
agrees with the level it was tried at.
"""

from dataclasses import dataclass, field  # simple record types for the receiver's report and its hints
from math import ceil  # round up

import numpy as np  # numerical arrays

from .address import bits_to_call, call_to_bits  # callsign <-> bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .blanker import blank_impulses  # static-crash blanker
from .preamble import detect_preamble, pattern_tones, preamble_samples  # the signature tone pattern that starts every frame
from .crc import crc8, crc16  # check values
from .fec import TAIL, conv_encode, viterbi_decode  # error correction for the header and the control frames
from . import control, ldpc, native  # control-frame fields, error correction for the message body, and the compiled library
from .notch import remove_steady  # takes steady signals out of the band
from .interleave import deinterleave, interleave  # bit shuffler
from .levels import LEVELS  # the speed levels
from .mfsk import (  # tone waveform
    band_energies, bits_to_symbols, energies_to_llrs, known_tone_energies, noise_level, noise_profile, pilot_frequency_fit,  # (continued)
    signal_report, symbol_energies, tone_energies, tone_spread, transmission,  # (continued: tone_spread since 0.35)
)  # end of the import list
from .params import (  # frame format numbers
    ADDRESS_BITS, BITS_PER_SYMBOL, BODY_CRC_BITS, CALL_BITS, CHAR_BITS, CONTROL_BITS, FRAME_TYPE_ACK, FRAME_TYPE_ADDRESSED,  # (continued)
    FRAME_TYPE_ANSWER, FRAME_TYPE_BEACON, FRAME_TYPE_IDENT, FRAME_TYPE_LINK, FRAME_TYPE_NOTICE, FS,  # (continued)
    HEADER_CRC_BITS, HEADER_FIELD_BITS, HEADER_REPEAT, HOP_BITS, LENGTH_BITS, LEVEL_BITS, LIFE_BITS, LIFE_UNIT_HOURS, LINK_ID_BITS, M_TONES,  # (continued)
    MAX_PARTS, MSG_ID_BITS, PILOT_EVERY, PILOT_START, PILOT_STEP, PREAMBLE_TONES, REF_BANDWIDTH_HZ, SIZE_CLASSES,  # (continued)
)  # end of the import list
from .text import bits_to_text, choose_packing, text_to_bits  # message <-> bits

HEADER_CODED_BITS = 2 * (HEADER_FIELD_BITS + HEADER_CRC_BITS + TAIL)  # coded header length (60 bits)
HEADER_SYMBOLS_ONCE = ceil(HEADER_CODED_BITS / BITS_PER_SYMBOL)  # tones for one copy of the header (12)
HEADER_SYMBOLS = HEADER_SYMBOLS_ONCE * HEADER_REPEAT  # tones for both copies together (24): one after the preamble, one after the body


def _layout(info, coded):  # work out the shape of a body from its bit counts
    """Return a dict describing a body with `info` data bits and `coded` bits after error correction."""
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


def body_layout(size_class):  # the shape of a message frame's body
    """Return a dict describing a message body: bit counts, tone counts and where the pilots sit.

    Both kinds of message frame have the same body size. A fully addressed
    frame has a longer address block and correspondingly less room for text.
    """
    info = ADDRESS_BITS[FRAME_TYPE_LINK] + LENGTH_BITS + CHAR_BITS * SIZE_CLASSES[size_class] + BODY_CRC_BITS  # address block + length field + text room + check
    return _layout(info, 2 * info)  # the LDPC code doubles the bits


def control_layout(frame_type):  # the shape of a control frame's body
    """Return a dict describing the body of a beacon, answer, acknowledgment or identification frame."""
    info = CONTROL_BITS[frame_type] + BODY_CRC_BITS  # the fields + check
    return _layout(info, 2 * (info + TAIL))  # the convolutional code doubles the bits, after six tail bits


def control_seconds(frame_type, level=0):  # how long a control frame lasts on the air
    """Return the airtime of a whole control frame, in seconds."""
    return (PREAMBLE_TONES + HEADER_SYMBOLS + control_layout(frame_type)["total"]) * LEVELS[level].seconds  # preamble + header + body, all at the level's tone length


def frame_seconds(size_class, level=0):  # how long a frame lasts on the air
    """Return the airtime of a whole frame, in seconds."""
    return (PREAMBLE_TONES + HEADER_SYMBOLS + body_layout(size_class)["total"]) * LEVELS[level].seconds  # preamble + header + body, all at the level's tone length


def _header_bits(frame_type, level, size_class, part, parts, compressed):  # the self-describing header
    """Return the 24 header bits: the six fields and their check value."""
    done = native.header_bits(frame_type, level, size_class, part, parts, compressed)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
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


def _body_symbols(data_bits, layout, is_control=False):  # body bits -> the tones of the body
    """Return the tone number of every body symbol for the given body bits (check value included).

    Message bodies use the LDPC code; the short control bodies use the
    same convolutional code as the header.
    """
    coded = conv_encode(data_bits) if is_control else ldpc.encode(data_bits)  # add error correction
    coded = np.concatenate([coded, np.zeros(layout["padded"] - layout["coded"], dtype=np.uint8)])  # round up to whole tones
    body_syms = np.zeros(layout["total"], dtype=np.int64)  # room for every body tone
    body_syms[layout["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    body_syms[layout["pilot_pos"]] = layout["pilot_tones"]  # known tones go in the pilot positions
    return body_syms  # pilots and data tones, in sending order


def _address_block(frame_type, link, want_level, msg_id, dest, origin, hops, life_hours):  # the addressing at the start of the body
    """Return the address block bits: 28 for a link frame, 120 for a fully addressed frame."""
    done = native.address_block(frame_type, link, want_level, msg_id, dest, origin, hops, life_hours)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    if not 0 <= msg_id < (1 << MSG_ID_BITS):  # the message number must fit its field
        raise ValueError("message number out of range")  # refuse nonsense
    if frame_type == FRAME_TYPE_LINK:  # a message between two locked stations
        if not 0 <= link < (1 << LINK_ID_BITS) or not 0 <= want_level < (1 << LEVEL_BITS):  # both numbers must fit their fields
            raise ValueError("link number or wanted level out of range")  # refuse nonsense
        return np.concatenate([int_to_bits(link, LINK_ID_BITS), int_to_bits(want_level, LEVEL_BITS), int_to_bits(msg_id, MSG_ID_BITS)])  # link number, wanted level, message number
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


def build_frame(text, level=0, part=0, parts=1, link=0, msg_id=0, dest=None, origin=None, hops=0, life_hours=48, want_level=0):  # the transmitter
    """Return the audio (floats between -1 and 1) of a frame carrying `text`.

    `part` and `parts` say which piece of a split message this frame is;
    leave them alone for a message sent whole. `msg_id` is the origin's
    number for the message. With no `dest`, the frame is a link frame and
    carries the short `link` number of the two locked stations and
    `want_level`, the speed level the sender asks its partner to use. With
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
    header_syms = bits_to_symbols(conv_encode(_header_bits(frame_type, level, size_class, part, parts, compressed)))  # coded header as tones (one copy)
    data_bits = np.concatenate([_address_block(frame_type, link, want_level, msg_id, dest, origin, hops, life_hours), text_to_bits(text, size_class, compressed, frame_type)])  # address block, character count, text bits, padding
    data_bits = np.concatenate([data_bits, crc16(data_bits)])  # add the body check value
    done = native.encode_frame(_header_bits(frame_type, level, size_class, part, parts, compressed), data_bits, False, layout, spec, pattern_tones(spec.number))  # the compiled transmitter, when the library is in use
    if done is not None:  # it was
        return done  # the same audio, to rounding
    body_syms = _body_symbols(data_bits, layout)  # error correction, shuffling and pilots
    return transmission(np.concatenate([pattern_tones(spec.number), header_syms, body_syms, header_syms]), spec)  # the level's preamble, the header, the body, then the header again: one waveform with faded ends (since 0.32)


def build_control(frame_type, fields, level=0):  # the transmitter for control frames
    """Return the audio of a control frame of the given type carrying the packed `fields` (see control.py)."""
    if len(fields) != CONTROL_BITS[frame_type]:  # each control frame has a fixed length
        raise ValueError("wrong number of bits for this control frame")  # refuse nonsense
    layout = control_layout(frame_type)  # shape of this frame's body
    header_syms = bits_to_symbols(conv_encode(_header_bits(frame_type, level, 0, 0, 1, False)))  # header: type and level; the other fields are zero (one copy)
    data_bits = np.concatenate([fields, crc16(fields)])  # the fields and their check value
    done = native.encode_frame(_header_bits(frame_type, level, 0, 0, 1, False), data_bits, True, layout, LEVELS[level], pattern_tones(level))  # the compiled transmitter, when the library is in use
    if done is not None:  # it was
        return done  # the same audio, to rounding
    body_syms = _body_symbols(data_bits, layout, is_control=True)  # error correction, shuffling and pilots
    return transmission(np.concatenate([pattern_tones(level), header_syms, body_syms, header_syms]), LEVELS[level])  # the level's preamble, the header, the body, then the header again: one waveform with faded ends (since 0.32)


def build_beacon(call, grid, levels=tuple(range(len(LEVELS))), listening=True, mail_check=False, holds_mail=False, level=0, wide=False):  # "here I am"
    """Return the audio of a beacon from `call` at grid locator `grid`; `wide` asks answering stations to spread over four reply slots."""
    return build_control(FRAME_TYPE_BEACON, control.pack_beacon(call, grid, levels, listening, mail_check, holds_mail, wide), level)  # pack the fields and send


def build_answer(dest, origin, report, levels=tuple(range(len(LEVELS))), mail_check=False, level=0, directed=False, grid=""):  # "I hear you" (or, with directed, "I am calling you")
    """Return the audio of `origin`'s answer to a beacon from `dest`, carrying a report of how the beacon was received; with `directed`, a directed call to `dest`. `grid` is the sender's locator (since 0.33; "" if none is set)."""
    return build_control(FRAME_TYPE_ANSWER, control.pack_answer(dest, origin, report, levels, mail_check, directed, grid), level)  # pack the fields and send


def build_ack(link, msg_id, part, status, report, level=0):  # "got it" / "send it again" / "already have it"
    """Return the audio of an acknowledgment for part `part` of message `msg_id` on link `link`."""
    return build_control(FRAME_TYPE_ACK, control.pack_ack(link, msg_id, part, status, report), level)  # pack the fields and send


def build_notice(call, held=(), receipts=(), heard=(), level=0):  # "I hold mail for ..., these were delivered, I hear ..."
    """Return the audio of a mail notice (frame type 7, since 0.30): short codes for the stations `call` holds mail for, the delivery receipts it reports and the stations it hears."""
    return build_control(FRAME_TYPE_NOTICE, control.pack_notice(call, held, receipts, heard), level)  # pack the fields and send


def build_ident(call, link, final=False, level=0):  # "this is ..."
    """Return the audio of a station identification; `final` marks the end of the contact."""
    return build_control(FRAME_TYPE_IDENT, control.pack_ident(call, link, final), level)  # pack the fields and send


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
    spread_hz: float = float("nan")  # Doppler spread read from how far the tones smeared into the bins beside them (since 0.35; NaN = too weak to tell)
    sync_quality: float = 0.0  # strength of the preamble detection
    level: int = -1  # speed level read from the header
    size_class: int = -1  # size class read from the header
    part: int = 0  # which part of a split message this frame is (0 = first)
    parts: int = 1  # how many parts the message has
    compressed: bool = False  # True when the text was sent compressed
    frame_type: int = -1  # kind of frame read from the header (0 = link frame, 1 = fully addressed)
    msg_id: int = -1  # the origin's number for the message
    link: int = -1  # short link number (link frames only)
    want_level: int = -1  # the speed level the sender asks its partner to use (link frames only)
    dest: str = ""  # destination callsign or group name (fully addressed frames only)
    origin: str = ""  # originating callsign (fully addressed frames only)
    hops: int = 0  # relays so far (fully addressed frames only)
    life_hours: int = 0  # hours the message may still be kept (fully addressed frames only)
    seen_level: int = -1  # when no header could be read: the level whose signature pattern stood out most (a "near miss"); -1 otherwise
    header_copy: str = ""  # which header copy was read: "first", "both" (the two combined) or "second"; empty when none was
    sample: int = -1  # where the frame began in a continuous stream, counted in samples from the start of listening (set by live.Listener; -1 otherwise)
    fields: dict = None  # the decoded fields of a control frame (beacon, answer, acknowledgment, identification); None for a message frame
    body_llrs: np.ndarray = None  # soft bits of the body, kept so a retry can be combined with them
    assisted: str = ""  # how a control frame that failed alone was read after all (copies added together, an expected callsign); empty when it read alone (since 0.31R1)
    pattern_tones: int = -1  # for a signature whose header could not be read: how many of the 12 pattern tones stood out in their slots (a real Kestrel frame shows most of them; another mode's signal only one or two); -1 when not measured (since 0.31R2)


COMBINE_OFFSET_HZ = 4.0  # earlier failed copies of a control frame are added to a new one only if their frequency offsets agree this closely (the same station)
COMBINE_MOST = 4  # at most this many earlier copies are tried, the most recent first
RESCUE_AGREE = 0.74  # a frame read only with help must still agree with this share of its own soft bits (real weak frames measured 0.78 and up; noise that happens to pass the check, mostly 0.62-0.68)
CALL_SLOTS = {FRAME_TYPE_BEACON: ("origin", ), FRAME_TYPE_IDENT: ("origin", ), FRAME_TYPE_NOTICE: ("origin", ), FRAME_TYPE_ANSWER: ("dest", "origin")}  # the callsign fields of each control frame, in order from the first body bit


@dataclass  # a plain record
class Prior:  # a control frame's body that failed its check, kept so a later copy can be added to it
    """The soft bits of one failed control-frame body, and enough about it to know which later copies may be the same frame."""

    frame_type: int  # beacon, answer, identification, ...
    llrs: np.ndarray  # its soft bits, in the order the decoder takes them
    offset_hz: float  # its frequency offset: copies from one station agree
    sample: int = -1  # where it began in the continuous stream (so a frame is never added to itself)


@dataclass  # a plain record
class Hints:  # what the receiver may assume when a control frame fails alone (since 0.31R1)
    """Help for reading weak control frames: this station's callsign, the callsigns it expects to hear, and earlier failed copies."""

    own: str = ""  # this station's callsign (calls and answers addressed to it)
    calls: tuple = ()  # callsigns it expects: the station it called, its partner, saved contacts, stations heard recently
    priors: list = field(default_factory=list)  # earlier failed control-frame bodies (Prior), most recent last
    base: int = 0  # the stream sample at the start of the audio being decoded (to tell a frame's earlier copies from itself)


def _known_bits(frame_type, assignment):  # data bits fixed by expected callsigns
    """Return the known-bit list (0/1 known, -1 unknown) for a control frame with callsign fields set as in `assignment` (name -> callsign)."""
    known = -np.ones(CONTROL_BITS[frame_type] + BODY_CRC_BITS, dtype=np.int8)  # nothing known yet
    for index, name in enumerate(CALL_SLOTS.get(frame_type, ())):  # each callsign field, in order
        if name in assignment:  # this one is assumed
            known[index * CALL_BITS:(index + 1) * CALL_BITS] = call_to_bits(assignment[name])  # its 48 bits
    return known  # the list


def _assignments(frame_type, hints):  # which callsigns to try in which fields
    """Return the field assignments (name -> callsign) to try for a failed control frame, most likely first."""
    slots = CALL_SLOTS.get(frame_type, ())  # its callsign fields
    others = [call for call in dict.fromkeys(hints.calls) if call and call != hints.own]  # the expected stations, without repeats or this station
    tries = []  # the list
    if slots == ("origin", ):  # a beacon, identification or mail notice: who sent it
        tries = [{"origin": call} for call in others]  # each expected station
    elif slots == ("dest", "origin") and hints.own:  # an answer or call: addressed to this station?
        tries = [{"dest": hints.own, "origin": call} for call in others] + [{"dest": hints.own}]  # from an expected station, or from anyone
    return tries  # the list


def _plausible(frame_type, data, llrs):  # is a frame read with help believable?
    """True when the body `data` passes its check, unpacks, carries callsign-shaped callsigns and agrees with enough of its soft bits."""
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the check value
        return False  # fails
    try:  # the fields must make sense
        fields = control.unpack(frame_type, data[:-BODY_CRC_BITS])  # unpacked
    except ValueError:  # a field that cannot be (a bad grid, say)
        return False  # not a frame
    from .longbeacon import CALL_SHAPE  # the shape every callsign has
    for name in CALL_SLOTS.get(frame_type, ()):  # each callsign it carries
        if not CALL_SHAPE.match(fields.get(name, "")):  # not shaped like a callsign
            return False  # not a frame
    coded = 1.0 - 2.0 * conv_encode(data)  # what it would have sent, as +1 / -1
    agree = float(np.mean(np.sign(llrs[:len(coded)]) == coded[:len(llrs)]))  # the share of soft bits that agree with it
    return agree >= RESCUE_AGREE  # a real frame agrees well beyond chance


def _rescue_control(llrs, frame_type, offset_hz, sample, hints):  # read a failed control frame with help
    """Return (data bits, how) for a control frame that failed alone, using earlier copies and expected callsigns, or (None, "")."""
    copies = [p for p in reversed(hints.priors) if p.frame_type == frame_type and len(p.llrs) == len(llrs)
              and abs(p.offset_hz - offset_hz) <= COMBINE_OFFSET_HZ and (sample < 0 or p.sample < 0 or abs(p.sample - sample) > FS)][:COMBINE_MOST]  # earlier copies that may be the same frame, most recent first
    sets = [(llrs, 1)] + [(llrs + p.llrs, 2) for p in copies]  # this copy alone, and with each earlier one
    if len(copies) > 1:  # several earlier copies
        sets.append((llrs + sum(p.llrs for p in copies), len(copies) + 1))  # all of them together
    tries = _assignments(frame_type, hints)  # expected callsigns to try
    for soft, count in sets:  # each set of soft bits
        together = f"{count} copies added together" if count > 1 else ""  # how it was put together
        if count > 1:  # added copies, with nothing assumed
            data = viterbi_decode(soft)  # decode
            if _plausible(frame_type, data, soft):  # it reads
                return data, together  # done
        for assignment in tries:  # each expected callsign (or pair)
            data = viterbi_decode(soft, _known_bits(frame_type, assignment))  # decode with those bits known
            if _plausible(frame_type, data, soft):  # it reads
                expected = ", ".join(f"{name} {call}" for name, call in assignment.items())  # what was assumed
                return data, (together + "; " if together else "") + f"expecting {expected}"  # done
    return None, ""  # no help was enough


def pattern_seen(x, found, spec):  # how much of a level's signature pattern is really there
    """Return how many of the 12 pattern tones at `found` are the strongest of all the level's tones in their own slots.

    A real Kestrel frame shows most of them (all 12 when it is clear; 5 to 9
    at the edge of decoding). Another mode's signal that happens to match
    the pattern's total shows only one or two. The strongest chance matches
    in plain noise show 2 to 5, and 7 about once in two thousand (since
    0.31R2; see live/listener.py NEAR_TONES).
    """
    if found["start"] < 0 or found["start"] + PREAMBLE_TONES * spec.samples > len(x):  # the pattern is not all in the audio
        return 0  # nothing to count
    energies = tone_energies(band_energies(x, found["start"], PREAMBLE_TONES, spec, found["offset_hz"]), spec)  # every tone's energy in each of the 12 slots
    return int(np.sum(np.argmax(energies, axis=1) == np.asarray(pattern_tones(spec.number))))  # slots where the pattern's tone is the strongest


def _body_total(bits):  # how many body tones a header says follow it
    """Return the number of body tones (data and pilots) of the frame described by header `bits`, or None for a frame type that does not exist."""
    frame_type = bits_to_int(bits[0:3])  # first field: frame type
    if frame_type in CONTROL_BITS:  # a beacon, answer, acknowledgment or identification
        return control_layout(frame_type)["total"]  # its fixed body
    if frame_type in ADDRESS_BITS:  # a message frame
        return body_layout(bits_to_int(bits[6:8]))["total"]  # the body for its size class
    return None  # no such frame type


_BODY_TOTALS = []  # every body length a frame can have (worked out on first use, then kept: it never changes)


def _body_totals():  # every body length a frame can have
    """Return the distinct body lengths, in tones, of every kind and size of frame (the places the second header copy can be)."""
    if not _BODY_TOTALS:  # not worked out yet
        _BODY_TOTALS.extend(_work_out_body_totals())  # work it out once
    return _BODY_TOTALS  # the list


def _work_out_body_totals():  # every body length a frame can have, worked out
    """Return the distinct body lengths, sorted, from the layouts of every control frame and message size."""
    return sorted({control_layout(t)["total"] for t in CONTROL_BITS} | {body_layout(c)["total"] for c in range(len(SIZE_CLASSES))})  # control frames and every message size


_TOTALS_BY_TYPE = []  # body length for every frame type and size class (filled on first use: the layouts are defined above)


def _totals_by_type():  # the table the compiled header reader uses
    """Return a list of 32 body lengths, frame type * 4 + size class, -1 where there is no such frame (as _body_total gives them)."""
    if not _TOTALS_BY_TYPE:  # not worked out yet
        for frame_type in range(8):  # every value the 3-bit field can hold
            for size_class in range(4):  # every value the 2-bit field can hold
                bits = np.concatenate([int_to_bits(frame_type, 3), np.zeros(3, dtype=np.uint8), int_to_bits(size_class, 2), np.zeros(8, dtype=np.uint8)])  # a header with just those fields
                total = _body_total(bits)  # its body length
                _TOTALS_BY_TYPE.append(-1 if total is None else int(total))  # kept (-1: no such frame)
    return _TOTALS_BY_TYPE  # the table


def _header_llrs(x, start, offset, spec):  # soft bits of one header copy
    """Return the soft bits of the header copy whose first tone begins at sample `start`."""
    tone_e = symbol_energies(x, start, HEADER_SYMBOLS_ONCE, spec, offset)  # measure the copy's tones
    return energies_to_llrs(tone_e, noise_level(tone_e))[:HEADER_CODED_BITS]  # soft bits, padding dropped


def _check_header(llrs, spec):  # decode soft header bits and check them
    """Return the header bits if `llrs` decode to a header that passes its check and names `spec`'s level; otherwise None."""
    bits = viterbi_decode(llrs)  # correct errors
    check_ok = np.array_equal(crc8(bits[:HEADER_FIELD_BITS]), bits[HEADER_FIELD_BITS:])  # does the check value match?
    if check_ok and bits_to_int(bits[3:6]) == spec.number and bits[15] == 0:  # and does the header name the preamble's level, with the spare bit clear?
        return bits  # yes: this may be a frame
    return None  # no


def _read_header(x, header_start, offset, spec):  # read the header that follows a preamble
    """Return the header bits found after a preamble of level `spec`, or None when no header checks out (see _read_header_how)."""
    return _read_header_how(x, header_start, offset, spec)[0]  # the bits alone


def _read_header_how(x, header_start, offset, spec, since=None):  # read the header, and say which copy gave it
    """Return (header bits, which copy) after a preamble of level `spec`; (None, "") when no header checks out. Which copy is "first", "both" or "second".

    The first copy follows the preamble. If it does not check out, the
    second copy is read at the end of each possible body, combined with the
    first, and tried alone too; a header found this way is accepted only
    if its own fields give the body length it was read at. Noise that
    looks like a preamble will now and then pass the header check (a few
    times in a thousand), which is why the caller goes on to check the body
    before believing a header.

    `since`, if given, is the length `x` had at an earlier try that found
    nothing: the first copy alone is not tried again, and the second copy is
    tried only at places that have arrived since (the continuous receiver
    tries each candidate again as audio arrives; since 0.31).
    """
    if header_start < 0 or header_start + HEADER_SYMBOLS_ONCE * spec.samples > len(x):  # the first copy is not (yet) wholly inside the recording
        return None, ""  # nothing to read
    done = native.read_header(x, header_start, offset, spec.samples, spec.tone_bins[0] - 1, spec.tone_bins[-1] + 1, spec.step, spec.number,
                              _totals_by_type(), _body_totals(), since)  # the compiled reader, when the library is in use
    if done is not None:  # it was
        return done  # the same answer as the Python below
    first = _header_llrs(x, header_start, offset, spec)  # soft bits of the first copy
    bits = _check_header(first, spec) if since is None else None  # try it alone (unless it was tried before)
    if bits is not None:  # it checked out
        return bits, "first"  # the usual case
    for total in _body_totals():  # every place the second copy could be
        second_start = header_start + (HEADER_SYMBOLS_ONCE + total) * spec.samples  # just after a body of that length
        if second_start + HEADER_SYMBOLS_ONCE * spec.samples > len(x) + spec.samples // 4:  # not (yet) inside the recording
            continue  # cannot try this length yet
        if since is not None and second_start + HEADER_SYMBOLS_ONCE * spec.samples <= since:  # tried at the earlier try already, with the whole copy there (a copy up to a quarter tone short is tried, but tried again once it is all in)
            continue  # nothing new here
        second = _header_llrs(x, second_start, offset, spec)  # soft bits of the second copy
        for llrs, how in ((first + second, "both"), (second, "second")):  # both copies together, then the second alone (in case the first was badly faded)
            bits = _check_header(llrs, spec)  # try it
            if bits is not None and _body_total(bits) == total:  # it checked out and agrees with where it was found
                return bits, how  # found it, and which copy it came from
    return None, ""  # no header here


def _decode_body_python(x, body_start, offset, spec, layout, is_control, prior_llrs, result):  # the numerical part of _decode_body, in Python
    """Return (data bits, soft bits, band energies, noise) for the body at `body_start`, filling in the offset, drift, SNR and fading of `result`.

    This is the reference that cpp/ kes_decode_body must match.
    """
    extra, drift = pilot_frequency_fit(x, body_start, layout["pilot_pos"], layout["pilot_tones"], spec, offset)  # fine frequency and drift from the pilots
    result.offset_hz = offset + extra  # best estimate of the offset at the start of the body
    result.drift_hz_s = drift  # best estimate of the drift
    band = band_energies(x, body_start, layout["total"], spec, result.offset_hz, drift)  # measure every bin of the tone band, for every body tone
    tone_e = tone_energies(band, spec)  # the 32 tone positions
    noise = noise_level(tone_e)  # average noise energy per tone position
    _measure(result, band[layout["pilot_pos"]], layout["pilot_tones"], noise, spec)  # first reading of SNR and fading, from the pilots alone
    level = noise_profile(tone_e)  # the noise level tone by tone through the frame (it is not always steady)
    llrs = deinterleave(energies_to_llrs(tone_e[layout["data_pos"]] / level[layout["data_pos"], None], 1.0))[:layout["coded"]]  # soft bits back in original order, padding dropped, each tone judged against the noise around it
    if is_control:  # short frames: the convolutional code
        data = viterbi_decode(llrs)  # correct errors in the body
    else:  # message frames: the LDPC code, with retries combined
        if prior_llrs is not None and len(prior_llrs) == len(llrs):  # an earlier copy of this frame is available
            llrs = llrs + prior_llrs  # combine the two copies
        data, _ = ldpc.decode(llrs, layout["info"])  # correct errors in the body
    result.body_llrs = llrs  # the soft bits, kept for a retry (message frames) or a later copy (control frames, since 0.31R1)
    return data, llrs, band, noise  # what the rest of _decode_body needs


def _decode_body(x, found, spec, header, prior_llrs, hints=None):  # read the rest of a frame once its header is known
    """Return the receiver's report for the frame that `header` describes."""
    result = RxResult(start=found["start"], sync_quality=found["quality"], level=spec.number)  # start the report with what the preamble and header told us
    result.frame_type = bits_to_int(header[0:3])  # first field: frame type
    result.size_class = bits_to_int(header[6:8])  # third field: size class
    result.part = bits_to_int(header[8:11])  # fourth field: part number
    result.parts = bits_to_int(header[11:14]) + 1  # fifth field: part count
    result.compressed = bool(header[14])  # sixth field: is the text compressed?
    is_control = result.frame_type in CONTROL_BITS  # a beacon, answer, acknowledgment or identification?
    if not is_control and (result.frame_type not in ADDRESS_BITS or result.part >= result.parts):  # neither a control frame nor a sensible message frame
        result.reason = "unsupported frame"  # say why we stopped
        return result  # give up on this reading of the header
    offset = found["offset_hz"]  # frequency error measured from the preamble
    layout = control_layout(result.frame_type) if is_control else body_layout(result.size_class)  # the header told us the body's shape
    body_start = found["start"] + preamble_samples(spec) + HEADER_SYMBOLS_ONCE * spec.samples  # the body follows the preamble and the first header copy
    if body_start + layout["total"] * spec.samples > len(x) + spec.samples // 4:  # the body is not inside the recording, give or take a quarter of a tone (the frame is still arriving, or this is noise near the end)
        result.reason = "frame incomplete"  # say why we stopped
        return result  # the caller may look again when more audio has arrived
    done = native.decode_body(x, body_start, offset, spec, layout, is_control, prior_llrs if not is_control else None)  # the compiled decoder, when the library is in use (since interface 6)
    if done is not None:  # it was: the same steps as the Python below, in one call
        data, llrs, band, (result.offset_hz, result.drift_hz_s, result.snr_db, result.fade_index, _passed, noise) = done  # its results
        result.body_llrs = llrs  # the soft bits (after any combining), kept for a retry or a later copy
    else:  # pure Python
        data, llrs, band, noise = _decode_body_python(x, body_start, offset, spec, layout, is_control, prior_llrs, result)  # the reference
    if is_control and hints is not None and not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # a control frame that failed alone, and help is offered
        sample = hints.base + int(found["start"]) if hints.base >= 0 else -1  # where it began in the stream
        rescued, result.assisted = _rescue_control(llrs, result.frame_type, result.offset_hz, sample, hints)  # earlier copies, expected callsigns
        if rescued is not None:  # it read with help
            data = rescued  # use that
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the body check must match
        result.reason = "body check failed"  # say why we stopped
        return result  # the caller may retry and combine
    block = ADDRESS_BITS.get(result.frame_type, 0)  # length of the address block at the start of a message body
    try:  # the check passed, so this should always work
        if is_control:  # a beacon, answer, acknowledgment or identification
            result.fields = control.unpack(result.frame_type, data[:-BODY_CRC_BITS])  # its named fields
            result.origin = result.fields.get("origin", "")  # copy the common fields to their usual places...
            result.dest = result.fields.get("dest", "")  # ...so callers can treat all frames alike
            result.link = result.fields.get("link", -1)  # the link number, when the frame carries one
            result.msg_id = result.fields.get("msg_id", -1)  # the message number, when the frame carries one
            result.part = result.fields.get("part", 0)  # the part number, when the frame carries one
        else:  # a message
            _read_address_block(result, data[:block])  # who the frame is for, and which message it is
            result.text = bits_to_text(data[block:-BODY_CRC_BITS], result.compressed)  # turn the rest back into text
    except ValueError:  # a damaged frame slipped past the check (very rare)
        result.reason = "body could not be read"  # say why we stopped
        return result  # give up on this copy
    result.ok = True  # success
    _measure(result, band, _body_symbols(data, layout, is_control), noise, spec)  # better reading: now every tone of the body is known, not just the pilots
    return result  # the finished report


def _read_address_block(result, bits):  # unpack the addressing at the start of the body
    """Put the address fields carried by `bits` into `result`; raise ValueError when an address is not valid."""
    done = native.read_address_block(result.frame_type, bits)  # compiled, when the library is in use
    if done is not None:  # it was
        if result.frame_type == FRAME_TYPE_LINK:  # a link frame
            result.link, result.want_level, result.msg_id = done.link, done.want_level, done.msg_id  # its three numbers
        else:  # a fully addressed frame
            result.dest, result.origin = done.dest.decode("ascii"), done.origin.decode("ascii")  # the two addresses
            result.msg_id, result.hops, result.life_hours = done.msg_id, done.hops, done.life_hours  # and the counters
        return  # done
    if result.frame_type == FRAME_TYPE_LINK:  # a message between two locked stations
        result.link = bits_to_int(bits[:LINK_ID_BITS])  # the short link number
        result.want_level = bits_to_int(bits[LINK_ID_BITS:LINK_ID_BITS + LEVEL_BITS])  # the level the sender asks its partner to use
        result.msg_id = bits_to_int(bits[LINK_ID_BITS + LEVEL_BITS:])  # the message number
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
    result.spread_hz = tone_spread(band, tones, spec, noise)[0]  # how far the tones were smeared: the Doppler spread (since 0.35; NaN when too weak to tell)


def _score(result):  # how believable a failed attempt is
    """Return a number that is higher for the failed attempt most likely to be the real frame."""
    return result.snr_db if result.reason == "body check failed" and np.isfinite(result.snr_db) else -1e9  # the pilots of the real frame show the highest SNR


def receive(x, blank=True, prior_llrs=None, trace=None, long_beacons=True, long_failed=None, candidates=None, notch=True, hints=None):  # the receiver
    """Find and decode one frame in the audio `x`.

    `prior_llrs` may hold the body_llrs of an earlier failed copy of the
    same frame; they are added to this copy's soft bits before decoding
    (this is the "combine retries" feature, HARQ).

    `trace`, if a list, receives one dict per preamble candidate tried, in
    the order tried: level, start (sample in `x`), offset_hz, quality,
    header ("first", "both", "second" or "" when none checked out), and,
    when a body was tried, ok, reason, snr_db and fade_index. It is for
    signal logs and debugging; the result does not depend on it.

    With `long_beacons` (the default) the long beacon's pattern is searched
    for too (see longbeacon.py); a long beacon comes back with level
    LONG_LEVEL and frame type FRAME_TYPE_LONG. `long_failed`, if a list,
    receives (candidate, Soft) for each long-beacon candidate that was all
    there but did not decode, for longbeacon.LongCombiner.

    `candidates`, if given, is a list of (found, level) pairs to try instead
    of searching `x` for signature patterns: found is a dict like those of
    preamble.detect_preamble (start, offset_hz, quality). The continuous
    receiver uses it to decode a frame it has already found (since 0.31).

    With `notch` (the default) steady signals in the band are notched out
    first (notch.py, since 0.31R1); the continuous receiver does that
    itself, once for all its searches, and passes notch=False.

    `hints` (a Hints, since 0.31R1) helps with control frames that fail
    alone: earlier failed copies are added to them, and the callsigns the
    station expects are tried in their callsign fields. What is read that
    way says so in the result's `assisted`.
    """
    x = np.asarray(x, dtype=float)  # make sure we have floating-point audio
    if blank:  # optional first step
        x = blank_impulses(x)  # silence static crashes
    if notch:  # the next step
        x = remove_steady(x)  # carriers and other steady signals out of the band
    from . import longbeacon  # the long beacon (imported here: it uses this module's body layout)
    long_x = None  # the audio with steady carriers removed, made only if a long beacon is to be read
    if candidates is not None:  # the caller already knows where to look
        candidates = list(candidates)  # a copy, to sort
    else:  # search for them
        candidates = [(found, spec) for spec in LEVELS for found in detect_preamble(x, spec)]  # look for every level's signature pattern (best few candidates of each)
        if long_beacons:  # the long beacon's pattern too (signal version 0.27)
            long_x = longbeacon.clean(x)  # the audio with any steady carrier near the long beacon's tones removed
            candidates += [(found, longbeacon.LONG) for found in longbeacon.candidates(long_x)]  # its best few
    if not candidates:  # recording too short to hold any preamble
        return RxResult(reason="no preamble found")  # give up
    candidates.sort(key=lambda pair: -pair[0]["quality"])  # try the candidate that stands furthest above the background first
    best = None  # the most believable failed attempt so far
    for found, spec in candidates:  # each candidate, at the level its pattern belongs to
        if spec is longbeacon.LONG:  # a long beacon has no header: its body follows the pattern
            long_x = longbeacon.clean(x) if long_x is None else long_x  # the audio with carriers removed (made now, when candidates were given)
            attempt = longbeacon.decode_at(long_x, found, RxResult(start=found["start"], sync_quality=found["quality"]), failed=long_failed)  # read it (a copy that fails is handed to the caller for combining)
            step = {"level": spec.number, "start": int(found["start"]), "offset_hz": float(found["offset_hz"]), "quality": float(found["quality"]), "header": "long", "ok": attempt.ok, "reason": attempt.reason, "snr_db": float(attempt.snr_db), "fade_index": float(attempt.fade_index)}  # for the trace
            if trace is not None:  # someone wants the details
                trace.append(step)  # record it
            if attempt.ok:  # a long beacon
                return attempt  # this is the frame
            continue  # a long beacon that fails is not kept as a failure: it is never retried or combined, and chance matches of its pattern would hide near misses of other frames
        header, how = _read_header_how(x, found["start"] + preamble_samples(spec), found["offset_hz"], spec)  # the header follows the preamble
        step = {"level": spec.number, "start": int(found["start"]), "offset_hz": float(found["offset_hz"]), "quality": float(found["quality"]), "header": how}  # what this candidate was (for the trace)
        if trace is not None:  # someone wants the details
            trace.append(step)  # record it now; the body's outcome is added below
        if header is None:  # no header there
            continue  # not a frame
        attempt = _decode_body(x, found, spec, header, prior_llrs, hints)  # try to read the body (with help, if offered, for a control frame that fails alone)
        attempt.header_copy = how  # which header copy was read
        step.update(ok=attempt.ok, reason=attempt.reason, snr_db=float(attempt.snr_db), fade_index=float(attempt.fade_index))  # the body's outcome, for the trace
        if attempt.ok:  # the body checked out too
            return attempt  # this is the frame
        if best is None or _score(attempt) > _score(best):  # otherwise remember the most believable failure
            best = attempt  # keep it
    if best is not None:  # a header was found but no body decoded
        return best  # report that failure (its soft bits can be combined with a retry)
    top, top_spec = candidates[0]  # the strongest signature found
    return RxResult(reason="header check failed", start=top["start"], sync_quality=top["quality"], offset_hz=top["offset_hz"], seen_level=top_spec.number)  # no header at all, but say where the strongest signature was and at which level
