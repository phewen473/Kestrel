"""Long notes (since signal version 0.34; 64 characters since 0.39): a short message sent in long-beacon frames, for reach.

A long note uses the long beacon's frame exactly (longbeacon.py): the same
twelve-tone pattern, 1.167-second tones, and a body of 66 field bits with a
CRC-16, about a minute in all, heard down to about -26 dB. In a long beacon
the last field bit is a spare that is always 0; a long-note frame sets it
to 1, and its other 65 bits are laid out as one of three kinds:

    note header  kind 0 (2) | origin callsign (48) | destination code (12) | text frames - 1 (3)
    note text    kind 1 (2) | origin code (12) | part 0-7 (3) | 8 characters of 6 bits (48)
    receipt      kind 2 (2) | origin callsign, the receiving station (48) | destination code, the note's sender (12) | spare (3)
    long call-up kind 3 (2) | origin callsign (48) | destination code (12) | phase (2) | traffic waiting (1)   (since signal 0.41)

A long call-up is a directed call, its answer, or an "operator away" reply,
sent as a long frame so that two stations can make contact on a fading path
too weak for the short levels (which need about -8 dB when the signal fades;
the long frame reads down to about -22 dB). Phase 0 is a call, 1 an answer
(the called station accepts), 2 "not available"; phase 3 is not used. The
traffic bit says the caller has a message waiting for the called station.

A code is 12 bits standing for a callsign (the low 12 bits of the CRC-16
of its 48 address bits; 0 is kept for ALL). A note is a header and one to
eight text frames, so it carries up to 64 characters in two to nine
minutes: enough for a telemetry message with about four stations. The
characters come from a set of 64 (space, capitals, figures and common
punctuation; small letters are sent as capitals). A station addressed by
a note answers with a receipt; a note to ALL gets none.

Signal 0.38 and earlier used up to four text frames of seven 7-bit ASCII
characters (28 in all); those stations misread 0.39 notes, and 0.39
stations theirs. Stations before 0.34 treat these frames as noise.
"""

import numpy as np  # numerical arrays

from .address import bits_to_call, call_to_bits, clean_call  # callsign <-> bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .crc import crc16  # the check value that codes are made from

KIND_BITS = 2  # bits of the frame kind
CODE_BITS = 12  # bits of a callsign code
PART_BITS = 3  # bits of a text frame's number (and of the header's count of text frames, less one) (2 before 0.39)
CHAR_BITS = 6  # bits per character: one of the 64 in CHARSET (7-bit ASCII before 0.39)
CHARS = 8  # characters per text frame (7 before 0.39)
MOST_PARTS = 8  # text frames in a note at most (4 before 0.39)
MOST_CHARS = CHARS * MOST_PARTS  # the longest note: 64 characters (28 before 0.39)
CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?!'\"/:;-+=()@#&*%$<>_[]^|"  # the 64 characters a note can carry, in code order (space is 0, so padding is spaces)
assert len(CHARSET) == 1 << CHAR_BITS and len(set(CHARSET)) == len(CHARSET)  # exactly 64, all different
HEADER, TEXT, RECEIPT, CALLUP = 0, 1, 2, 3  # the four kinds (CALLUP since signal 0.41; before that 3 was not used)
PHASE_BITS = 2  # bits of a long call-up's phase (since 0.41)
PHASES = ("call", "answer", "away")  # a long call-up's phases in code order: a call, the called station's answer, its "operator not available" reply (since 0.41)
FIELD_BITS = 65  # the field bits a note frame uses (the 66th, the long beacon's spare, is 1)
ALL_CODE = 0  # the code that means every station


def code_for(call):  # a callsign -> its 12-bit code
    """Return the 12-bit code standing for `call` (0 for ALL; never 0 for a callsign)."""
    call = clean_call(call)  # tidied, in capitals
    if call == "ALL":  # everyone
        return ALL_CODE  # the code kept for ALL
    value = bits_to_int(crc16(call_to_bits(call))) & ((1 << CODE_BITS) - 1)  # the low 12 bits of the callsign's check value
    return value or 1  # 0 is kept for ALL


def pack_header(origin, dest, parts):  # a note's first frame -> 65 bits
    """Return the field bits of a note header from `origin` to `dest` (a callsign or ALL) announcing `parts` text frames (1 to 8)."""
    if not 1 <= parts <= MOST_PARTS:  # one to eight text frames
        raise ValueError(f"a long note has one to {MOST_PARTS} text frames")  # refuse
    return np.concatenate([int_to_bits(HEADER, KIND_BITS), call_to_bits(origin), int_to_bits(code_for(dest), CODE_BITS), int_to_bits(parts - 1, PART_BITS)])  # kind, origin, destination, count (65 bits; no spare since 0.39)


def unsendable(text):  # characters a note cannot carry
    """Return the characters of `text` (after small letters become capitals) that are not in CHARSET, each once, in order."""
    return "".join(dict.fromkeys(c for c in text.upper() if c not in CHARSET))  # the ones left out


def pack_text(origin, part, text):  # one text frame -> 65 bits
    """Return the field bits of text frame `part` (0 to 7) of a note from `origin`, carrying up to 8 characters of `text` (in capitals, padded with spaces)."""
    text = text.upper().ljust(CHARS)[:CHARS]  # exactly eight characters, small letters as capitals
    if unsendable(text):  # a character not in the set
        raise ValueError(f"a long note cannot carry {unsendable(text)!r}")  # refuse
    chars = np.concatenate([int_to_bits(CHARSET.index(c), CHAR_BITS) for c in text])  # 48 bits
    return np.concatenate([int_to_bits(TEXT, KIND_BITS), int_to_bits(code_for(origin), CODE_BITS), int_to_bits(part, PART_BITS), chars])  # kind, origin code, part, characters


def pack_receipt(origin, dest):  # a receipt -> 65 bits
    """Return the field bits of a receipt from `origin` (the station that received a note) to `dest` (the note's sender)."""
    return np.concatenate([int_to_bits(RECEIPT, KIND_BITS), call_to_bits(origin), int_to_bits(code_for(dest), CODE_BITS), np.zeros(3, dtype=np.uint8)])  # kind, origin, destination code, spare


def unpack(bits):  # 65 field bits -> a dict, or raise ValueError
    """Return the fields of a long-note frame: {"note": kind name, ...}; raise ValueError when the bits are not a plausible note frame."""
    kind = bits_to_int(bits[:KIND_BITS])  # which kind
    rest = bits[KIND_BITS:]  # what follows
    if kind == HEADER:  # a note header (the callsign's shape is checked by the caller, as for a long beacon)
        return {"note": "header", "origin": bits_to_call(rest[:48]), "dest_code": bits_to_int(rest[48:60]), "parts": bits_to_int(rest[60:60 + PART_BITS]) + 1, "long": True}  # who, to whom, how many text frames
    if kind == TEXT:  # a text frame
        code, part = bits_to_int(rest[:CODE_BITS]), bits_to_int(rest[CODE_BITS:CODE_BITS + PART_BITS])  # whose, and which
        chars = rest[CODE_BITS + PART_BITS:]  # the 48 character bits
        text = "".join(CHARSET[bits_to_int(chars[n * CHAR_BITS:(n + 1) * CHAR_BITS])] for n in range(CHARS))  # the eight characters
        if code == ALL_CODE:  # a text frame always names a station
            raise ValueError("not a text frame")  # noise
        return {"note": "text", "origin": "", "origin_code": code, "part": part, "text": text, "long": True}  # whose, which part, what it says
    if kind == RECEIPT:  # a receipt
        if any(rest[60:]):  # the spare bits must be 0
            raise ValueError("spare bits set")  # noise
        return {"note": "receipt", "origin": bits_to_call(rest[:48]), "dest_code": bits_to_int(rest[48:60]), "long": True}  # who received it, and whose note it was
    if kind == CALLUP:  # a long call-up (since 0.41)
        phase = bits_to_int(rest[60:60 + PHASE_BITS])  # call, answer or away
        if phase >= len(PHASES):  # phase 3 is not sent
            raise ValueError("unused call-up phase")  # noise
        return {"note": "callup", "origin": bits_to_call(rest[:48]), "dest_code": bits_to_int(rest[48:60]), "phase": PHASES[phase], "traffic": bool(rest[60 + PHASE_BITS]), "long": True}  # who calls (or answers), whom, which phase, and whether traffic waits
    raise ValueError("unused note kind")  # every kind is covered above; kept for safety


def note_fields(origin, dest, text):  # a whole note -> the field bits of each of its frames
    """Return the list of 65-bit field arrays for a note from `origin` to `dest`: the header, then one text frame per eight characters (up to 64, small letters sent as capitals)."""
    text = text.upper().rstrip()  # capitals, no trailing spaces
    if unsendable(text):  # a character the set does not have
        raise ValueError(f"a long note cannot carry {unsendable(text)!r} (letters, figures, spaces and {CHARSET[37:]} only)")  # refuse, saying which
    if not text:  # nothing to say
        raise ValueError("a long note needs some text")  # refuse
    if len(text) > MOST_CHARS:  # too long
        raise ValueError(f"a long note holds at most {MOST_CHARS} characters")  # refuse
    pieces = [text[n:n + CHARS] for n in range(0, len(text), CHARS)]  # eight characters to a frame
    return [pack_header(origin, dest, len(pieces))] + [pack_text(origin, part, piece) for part, piece in enumerate(pieces)]  # header first, then the text


def build_note(origin, dest, text):  # a whole note -> audio, frame by frame
    """Return the audio of each frame of a note (header first), each about a minute long."""
    from .longbeacon import build_from_fields  # the long beacon's transmitter (imported here: longbeacon.py imports this module)
    return [build_from_fields(np.concatenate([bits, np.ones(1, dtype=np.uint8)])) for bits in note_fields(origin, dest, text)]  # each frame's 65 bits, the note flag, then the long beacon's frame


def build_receipt(origin, dest):  # a receipt -> audio
    """Return the audio of a receipt from `origin` for a note sent by `dest`, about a minute long."""
    from .longbeacon import build_from_fields  # the long beacon's transmitter
    return build_from_fields(np.concatenate([pack_receipt(origin, dest), np.ones(1, dtype=np.uint8)]))  # its 65 bits, the note flag, then the long beacon's frame


def pack_callup(origin, dest, phase, traffic=False):  # a long call-up -> 65 bits (since 0.41)
    """Return the field bits of a long call-up from `origin` to `dest` (a callsign): `phase` is "call", "answer" or "away"; `traffic` says a message waits for `dest`."""
    if phase not in PHASES:  # not one of the three
        raise ValueError(f"a long call-up's phase is one of {PHASES}")  # refuse
    if clean_call(dest) == "ALL":  # a call-up names one station
        raise ValueError("a long call-up is to one station, not ALL")  # refuse
    return np.concatenate([int_to_bits(CALLUP, KIND_BITS), call_to_bits(origin), int_to_bits(code_for(dest), CODE_BITS),  # kind, origin, destination code
                           int_to_bits(PHASES.index(phase), PHASE_BITS), np.array([1 if traffic else 0], dtype=np.uint8)])  # phase and the traffic bit (65 bits in all)


def build_callup(origin, dest, phase, traffic=False):  # a long call-up -> audio (since 0.41)
    """Return the audio of a long call-up (see pack_callup), about a minute long."""
    from .longbeacon import build_from_fields  # the long beacon's transmitter
    return build_from_fields(np.concatenate([pack_callup(origin, dest, phase, traffic), np.ones(1, dtype=np.uint8)]))  # its 65 bits, the note flag, then the long beacon's frame
