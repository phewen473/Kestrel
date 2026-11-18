"""Control frames: what a beacon, an answer, an acknowledgment and an identification carry, as bits.

These short frames set up and run a link. This file only packs their
fields into bits and unpacks them again; frame.py turns the bits into
audio and back.
"""

from dataclasses import dataclass  # simple record type for the channel report

import numpy as np  # numerical arrays

from .address import bits_to_call, call_to_bits  # callsign <-> 48 bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .params import (  # frame format numbers
    ACK_STATUS_BITS, CALL_BITS, CONTROL_BITS, FADE_BITS, FADE_STEPS_PER_UNIT, FRAME_TYPE_ACK, FRAME_TYPE_ANSWER,  # (continued)
    FRAME_TYPE_BEACON, FRAME_TYPE_IDENT, GRID_BITS, LEVEL_BITS, LEVEL_MASK_BITS, LINK_ID_BITS, MSG_ID_BITS,  # (continued)
    OFFSET_BITS, OFFSET_STEP_HZ, PART_BITS, REPORT_BITS, SNR_BITS, SNR_FLOOR_DB,  # (continued)
)  # end of the import list

ACK_OK = 0  # acknowledgment status: frame received correctly
ACK_RESEND = 1  # acknowledgment status: frame failed its check; send it again (the copies will be combined)
ACK_HAVE_IT = 2  # acknowledgment status: this message was already received or delivered; do not send it again
ACK_LINK = 3  # acknowledgment status: no message is referred to; the frame confirms or keeps alive the link and carries a fresh report
FIELDS = "ABCDEFGHIJKLMNOPQR"  # the 18 letters used for the first two characters of a grid locator


@dataclass  # a plain record
class ChannelReport:  # what one station tells the other about the signal it received
    """A receiver's measurements of the last frame it heard, plus the speed level it asks the sender to use next."""

    snr_db: float = 0.0  # signal-to-noise ratio in 2.5 kHz
    fade_index: float = 0.0  # 0 = steady signal, about 1 = deep, frequent fades
    offset_hz: float = 0.0  # frequency error of the received signal
    want_level: int = 0  # the speed level the receiver asks the sender to use from now on


def pack_report(report):  # channel report -> 18 bits
    """Return the 18 bits of a channel report: SNR (6), fading index (3), frequency offset (6), wanted level (3)."""
    snr = int(np.clip(round(report.snr_db) - SNR_FLOOR_DB, 0, (1 << SNR_BITS) - 1))  # SNR in whole dB above -30, held to 0..63
    fade = report.fade_index if report.fade_index == report.fade_index else (1 << FADE_BITS)  # a missing reading (not-a-number) is sent as the largest value, "fading"
    fade = int(np.clip(round(fade * FADE_STEPS_PER_UNIT), 0, (1 << FADE_BITS) - 1))  # fading index in quarters, held to 0..7
    limit = (1 << (OFFSET_BITS - 1)) - 1  # the largest offset step that fits (31)
    offset = int(np.clip(round(report.offset_hz / OFFSET_STEP_HZ), -limit - 1, limit))  # offset in 2 Hz steps, held to -32..31
    if not 0 <= report.want_level < (1 << LEVEL_BITS):  # the wanted level must fit its field
        raise ValueError("wanted level out of range")  # refuse nonsense
    return np.concatenate([  # the four fields, in order
        int_to_bits(snr, SNR_BITS),  # signal-to-noise ratio
        int_to_bits(fade, FADE_BITS),  # fading index
        int_to_bits(offset & ((1 << OFFSET_BITS) - 1), OFFSET_BITS),  # frequency offset, negative values in two's complement
        int_to_bits(report.want_level, LEVEL_BITS),  # the level asked for
    ])  # end of the report


def unpack_report(bits):  # 18 bits -> channel report
    """Return the channel report carried by 18 bits."""
    snr = bits_to_int(bits[:SNR_BITS]) + SNR_FLOOR_DB  # back to dB
    fade = bits_to_int(bits[SNR_BITS:SNR_BITS + FADE_BITS]) / FADE_STEPS_PER_UNIT  # back to an index
    raw = bits_to_int(bits[SNR_BITS + FADE_BITS:SNR_BITS + FADE_BITS + OFFSET_BITS])  # the offset field as an unsigned number
    if raw >= 1 << (OFFSET_BITS - 1):  # the top bit is set, so the offset is negative
        raw -= 1 << OFFSET_BITS  # undo the two's complement
    return ChannelReport(float(snr), fade, float(raw * OFFSET_STEP_HZ), bits_to_int(bits[-LEVEL_BITS:]))  # the four readings


def grid_to_bits(grid):  # four-character grid locator -> 15 bits
    """Return the 15 bits of a four-character Maidenhead locator such as EM92."""
    grid = grid.strip().upper()  # locators are sent in capitals
    if len(grid) != 4 or grid[0] not in FIELDS or grid[1] not in FIELDS or not grid[2:].isdigit():  # two letters A-R, then two digits
        raise ValueError("a grid locator is two letters A to R followed by two digits")  # refuse anything else
    value = ((FIELDS.index(grid[0]) * 18 + FIELDS.index(grid[1])) * 10 + int(grid[2])) * 10 + int(grid[3])  # one number, 0 to 32399
    return int_to_bits(value, GRID_BITS)  # as 15 bits


def bits_to_grid(bits):  # 15 bits -> grid locator
    """Return the four-character locator spelled by 15 bits, or raise ValueError when they are not a locator."""
    value = bits_to_int(bits)  # the bits as one number
    if value >= 18 * 18 * 100:  # larger than any locator
        raise ValueError("not a valid grid locator")  # damaged, or never a locator
    pair, digits = divmod(value, 100)  # the two letters, and the two digits
    return FIELDS[pair // 18] + FIELDS[pair % 18] + f"{digits:02d}"  # back to text


def levels_to_bits(levels):  # which speed levels a station can use -> 8 bits
    """Return the 8-bit list of speed levels: the bit for level n has the value 2**n."""
    mask = 0  # no levels yet
    for level in levels:  # every level the station supports
        if not 0 <= level < LEVEL_MASK_BITS:  # only levels 0 to 7 have a bit
            raise ValueError("level out of range")  # refuse nonsense
        mask |= 1 << level  # set that level's bit
    return int_to_bits(mask, LEVEL_MASK_BITS)  # as 8 bits, most significant first


def bits_to_levels(bits):  # 8 bits -> tuple of speed levels
    """Return the speed levels listed by 8 bits, lowest first."""
    mask = bits_to_int(bits)  # the bits as one number
    return tuple(level for level in range(LEVEL_MASK_BITS) if mask & (1 << level))  # every level whose bit is set


def pack_beacon(call, grid, levels, listening=True, mail_check=False, holds_mail=False):  # beacon fields -> 75 bits
    """Return the body bits of a beacon: who is calling, where from, what it can do and what it wants."""
    flags = [int(listening), int(mail_check), int(holds_mail), 0]  # will take answers / wants its mail / holds mail for others / spare
    return np.concatenate([call_to_bits(call), grid_to_bits(grid), levels_to_bits(levels), np.array(flags, dtype=np.uint8)])  # callsign, locator, levels, flags


def pack_answer(dest, origin, report, levels, mail_check=False):  # answer fields -> 124 bits
    """Return the body bits of an answer to a beacon: who is answering whom, how the beacon was received, what the answerer can do."""
    flags = [int(mail_check), 0]  # wants its mail / spare
    return np.concatenate([call_to_bits(dest), call_to_bits(origin), pack_report(report), levels_to_bits(levels), np.array(flags, dtype=np.uint8)])  # addresses, report, levels, flags


def pack_ack(link, msg_id, part, status, report):  # acknowledgment fields -> 51 bits
    """Return the body bits of an acknowledgment for one frame of one message."""
    if not (0 <= link < (1 << LINK_ID_BITS) and 0 <= msg_id < (1 << MSG_ID_BITS) and 0 <= part < (1 << PART_BITS) and 0 <= status < (1 << ACK_STATUS_BITS)):  # every number must fit its field
        raise ValueError("acknowledgment field out of range")  # refuse nonsense
    return np.concatenate([int_to_bits(link, LINK_ID_BITS), int_to_bits(msg_id, MSG_ID_BITS), int_to_bits(part, PART_BITS), int_to_bits(status, ACK_STATUS_BITS), pack_report(report)])  # link, message, part, status, report


def pack_ident(call, link, final=False):  # identification fields -> 64 bits
    """Return the body bits of a station identification; `final` marks the end of the contact."""
    if not 0 <= link < (1 << LINK_ID_BITS):  # the link number must fit its field
        raise ValueError("link number out of range")  # refuse nonsense
    flags = [int(final), 0, 0, 0]  # end of contact / three spare bits
    return np.concatenate([call_to_bits(call), int_to_bits(link, LINK_ID_BITS), np.array(flags, dtype=np.uint8)])  # callsign, link number, flags


def unpack(frame_type, bits):  # body bits -> named fields
    """Return a dict of the fields carried by a control frame's body bits; raise ValueError when they make no sense."""
    if len(bits) != CONTROL_BITS[frame_type]:  # every control frame has a fixed length
        raise ValueError("wrong length for this control frame")  # refuse
    if frame_type == FRAME_TYPE_BEACON:  # a beacon
        rest = bits[CALL_BITS:]  # what follows the callsign
        flags = rest[GRID_BITS + LEVEL_MASK_BITS:]  # the four flag bits
        return {"origin": bits_to_call(bits[:CALL_BITS]), "grid": bits_to_grid(rest[:GRID_BITS]), "levels": bits_to_levels(rest[GRID_BITS:GRID_BITS + LEVEL_MASK_BITS]),  # (continued)
                "listening": bool(flags[0]), "mail_check": bool(flags[1]), "holds_mail": bool(flags[2])}  # who, where, what it can do, what it wants
    if frame_type == FRAME_TYPE_ANSWER:  # an answer to a beacon
        rest = bits[2 * CALL_BITS:]  # what follows the two callsigns
        return {"dest": bits_to_call(bits[:CALL_BITS]), "origin": bits_to_call(bits[CALL_BITS:2 * CALL_BITS]), "report": unpack_report(rest[:REPORT_BITS]),  # (continued)
                "levels": bits_to_levels(rest[REPORT_BITS:REPORT_BITS + LEVEL_MASK_BITS]), "mail_check": bool(rest[REPORT_BITS + LEVEL_MASK_BITS])}  # who to whom, the report, the levels, the flag
    if frame_type == FRAME_TYPE_ACK:  # an acknowledgment
        rest = bits[LINK_ID_BITS + MSG_ID_BITS:]  # what follows the link and message numbers
        return {"link": bits_to_int(bits[:LINK_ID_BITS]), "msg_id": bits_to_int(bits[LINK_ID_BITS:LINK_ID_BITS + MSG_ID_BITS]), "part": bits_to_int(rest[:PART_BITS]),  # (continued)
                "status": bits_to_int(rest[PART_BITS:PART_BITS + ACK_STATUS_BITS]), "report": unpack_report(rest[PART_BITS + ACK_STATUS_BITS:])}  # which frame, the verdict, the report
    if frame_type == FRAME_TYPE_IDENT:  # a station identification
        return {"origin": bits_to_call(bits[:CALL_BITS]), "link": bits_to_int(bits[CALL_BITS:CALL_BITS + LINK_ID_BITS]), "final": bool(bits[CALL_BITS + LINK_ID_BITS])}  # who, which link, end of contact?
    raise ValueError("not a control frame type")  # anything else is not handled here
