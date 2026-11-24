"""Long notes (signal version 0.34): a short message sent in long-beacon frames, for reach.

A long note uses the long beacon's frame exactly (longbeacon.py): the same
twelve-tone pattern, 1.167-second tones, and a body of 66 field bits with a
CRC-16, about a minute in all, heard down to about -26 dB. In a long beacon
the last field bit is a spare that is always 0; a long-note frame sets it
to 1, and its other 65 bits are laid out as one of three kinds:

    note header  kind 0 (2) | origin callsign (48) | destination code (12) | text frames - 1 (2) | spare (1)
    note text    kind 1 (2) | origin code (12) | part 0-3 (2) | 7 characters of 7-bit ASCII (49)
    receipt      kind 2 (2) | origin callsign, the receiving station (48) | destination code, the note's sender (12) | spare (3)

A code is 12 bits standing for a callsign (the low 12 bits of the CRC-16
of its 48 address bits; 0 is kept for ALL). A note is a header and one to
four text frames, so it carries up to 28 characters in two to five minutes.
A station addressed by a note answers with a receipt; a note to ALL gets
none. Older receivers (0.33 and before) treat these frames as noise.
"""

import numpy as np  # numerical arrays

from .address import bits_to_call, call_to_bits, clean_call  # callsign <-> bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .crc import crc16  # the check value that codes are made from

KIND_BITS = 2  # bits of the frame kind
CODE_BITS = 12  # bits of a callsign code
PART_BITS = 2  # bits of a text frame's number (and of the header's count of text frames, less one)
CHAR_BITS = 7  # bits per character (7-bit ASCII)
CHARS = 7  # characters per text frame
MOST_PARTS = 4  # text frames in a note at most
MOST_CHARS = CHARS * MOST_PARTS  # the longest note: 28 characters
HEADER, TEXT, RECEIPT = 0, 1, 2  # the three kinds (3 is not used)
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
    """Return the field bits of a note header from `origin` to `dest` (a callsign or ALL) announcing `parts` text frames (1 to 4)."""
    if not 1 <= parts <= MOST_PARTS:  # one to four text frames
        raise ValueError("a long note has one to four text frames")  # refuse
    return np.concatenate([int_to_bits(HEADER, KIND_BITS), call_to_bits(origin), int_to_bits(code_for(dest), CODE_BITS), int_to_bits(parts - 1, PART_BITS), np.zeros(1, dtype=np.uint8)])  # kind, origin, destination, count, spare


def pack_text(origin, part, text):  # one text frame -> 65 bits
    """Return the field bits of text frame `part` (0 to 3) of a note from `origin`, carrying up to 7 characters of `text` (padded with spaces)."""
    text = text.ljust(CHARS)[:CHARS]  # exactly seven characters
    if any(not 32 <= ord(c) <= 126 for c in text):  # only printable 7-bit ASCII
        raise ValueError("a long note carries printable ASCII only")  # refuse
    chars = np.concatenate([int_to_bits(ord(c), CHAR_BITS) for c in text])  # 49 bits
    return np.concatenate([int_to_bits(TEXT, KIND_BITS), int_to_bits(code_for(origin), CODE_BITS), int_to_bits(part, PART_BITS), chars])  # kind, origin code, part, characters


def pack_receipt(origin, dest):  # a receipt -> 65 bits
    """Return the field bits of a receipt from `origin` (the station that received a note) to `dest` (the note's sender)."""
    return np.concatenate([int_to_bits(RECEIPT, KIND_BITS), call_to_bits(origin), int_to_bits(code_for(dest), CODE_BITS), np.zeros(3, dtype=np.uint8)])  # kind, origin, destination code, spare


def unpack(bits):  # 65 field bits -> a dict, or raise ValueError
    """Return the fields of a long-note frame: {"note": kind name, ...}; raise ValueError when the bits are not a plausible note frame."""
    kind = bits_to_int(bits[:KIND_BITS])  # which kind
    rest = bits[KIND_BITS:]  # what follows
    if kind == HEADER:  # a note header
        if rest[-1]:  # the spare bit must be 0
            raise ValueError("spare bit set")  # noise
        return {"note": "header", "origin": bits_to_call(rest[:48]), "dest_code": bits_to_int(rest[48:60]), "parts": bits_to_int(rest[60:62]) + 1, "long": True}  # who, to whom, how many text frames
    if kind == TEXT:  # a text frame
        code, part = bits_to_int(rest[:CODE_BITS]), bits_to_int(rest[CODE_BITS:CODE_BITS + PART_BITS])  # whose, and which
        chars = rest[CODE_BITS + PART_BITS:]  # the 49 character bits
        text = "".join(chr(bits_to_int(chars[n * CHAR_BITS:(n + 1) * CHAR_BITS])) for n in range(CHARS))  # the seven characters
        if code == ALL_CODE or any(not 32 <= ord(c) <= 126 for c in text):  # a text frame always names a station, and carries printable characters
            raise ValueError("not a text frame")  # noise
        return {"note": "text", "origin": "", "origin_code": code, "part": part, "text": text, "long": True}  # whose, which part, what it says
    if kind == RECEIPT:  # a receipt
        if any(rest[60:]):  # the spare bits must be 0
            raise ValueError("spare bits set")  # noise
        return {"note": "receipt", "origin": bits_to_call(rest[:48]), "dest_code": bits_to_int(rest[48:60]), "long": True}  # who received it, and whose note it was
    raise ValueError("unused note kind")  # kind 3 is not sent


def note_fields(origin, dest, text):  # a whole note -> the field bits of each of its frames
    """Return the list of 65-bit field arrays for a note from `origin` to `dest`: the header, then one text frame per seven characters (up to 28)."""
    text = text.rstrip()  # no trailing spaces
    if not text:  # nothing to say
        raise ValueError("a long note needs some text")  # refuse
    if len(text) > MOST_CHARS:  # too long
        raise ValueError(f"a long note holds at most {MOST_CHARS} characters")  # refuse
    pieces = [text[n:n + CHARS] for n in range(0, len(text), CHARS)]  # seven characters to a frame
    return [pack_header(origin, dest, len(pieces))] + [pack_text(origin, part, piece) for part, piece in enumerate(pieces)]  # header first, then the text


def build_note(origin, dest, text):  # a whole note -> audio, frame by frame
    """Return the audio of each frame of a note (header first), each about a minute long."""
    from .longbeacon import build_from_fields  # the long beacon's transmitter (imported here: longbeacon.py imports this module)
    return [build_from_fields(np.concatenate([bits, np.ones(1, dtype=np.uint8)])) for bits in note_fields(origin, dest, text)]  # each frame's 65 bits, the note flag, then the long beacon's frame


def build_receipt(origin, dest):  # a receipt -> audio
    """Return the audio of a receipt from `origin` for a note sent by `dest`, about a minute long."""
    from .longbeacon import build_from_fields  # the long beacon's transmitter
    return build_from_fields(np.concatenate([pack_receipt(origin, dest), np.ones(1, dtype=np.uint8)]))  # its 65 bits, the note flag, then the long beacon's frame
