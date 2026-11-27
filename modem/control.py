"""Control frames: what a beacon, an answer, an acknowledgment, an identification and a mail notice carry, as bits.

These short frames set up and run a link. This file only packs their
fields into bits and unpacks them again; frame.py turns the bits into
audio and back.
"""

from dataclasses import dataclass  # simple record type for the channel report

import numpy as np  # numerical arrays

from . import native  # the compiled library, when it is in use
from .address import bits_to_call, call_to_bits  # callsign <-> 48 bits
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .params import RIG_BITS, WATT_BITS  # a beacon's rig type and watts (since 0.40)
from .params import (  # frame format numbers
    ACK_STATUS_BITS, CALL_BITS, CONTROL_BITS, FADE_BITS, FADE_STEPS_PER_UNIT, FRAME_TYPE_ACK, FRAME_TYPE_ANSWER,  # (continued)
    FRAME_TYPE_BEACON, FRAME_TYPE_IDENT, FRAME_TYPE_NOTICE, GRID_BITS, HASH_BITS, NO_GRID, NOTICE_SLOTS, LEVEL_BITS, LEVEL_MASK_BITS, LINK_ID_BITS, MSG_ID_BITS,  # (continued)
    OFFSET_BITS, OFFSET_STEP_HZ, PART_BITS, REPORT_BITS, SNR_BITS, SNR_FLOOR_DB,  # (continued)
)  # end of the import list
from .params import AGE_BITS, AGE_STEPS_S, NOISE_BITS, NOISE_FLOOR_DB, NOISE_STEP_DB, NOISE_UNKNOWN  # a report's age and the reporter's noise reading (since 0.44)

ACK_OK = 0  # acknowledgment status: frame received correctly
ACK_RESEND = 1  # acknowledgment status: frame failed its check; send it again (the copies will be combined)
ACK_HAVE_IT = 2  # acknowledgment status: the whole of this message is already held or delivered here; stop sending it
ACK_LINK = 3  # acknowledgment status: no message is referred to; the frame confirms or keeps alive the link and carries a fresh report
FIELDS = "ABCDEFGHIJKLMNOPQR"  # the 18 letters used for the first two characters of a grid locator


@dataclass  # a plain record
class ChannelReport:  # what one station tells the other about the signal it received
    """A receiver's measurements of the last frame it heard, plus the speed level it asks the sender to use next."""

    snr_db: float = 0.0  # signal-to-noise ratio in 2.5 kHz
    fade_index: float = 0.0  # 0 = steady signal, about 1 = deep, frequent fades
    offset_hz: float = 0.0  # frequency error of the received signal
    want_level: int = 0  # the speed level the receiver asks the sender to use from now on
    age_s: float = float("nan")  # how long before the report was sent its measurement was made, in seconds; NaN = not said (since 0.44)
    noise_db: float = float("nan")  # the reporting station's own band noise, its S-meter reading in dB relative to S9; NaN = not measured (since 0.44)


def age_code(age_s):  # a report's age -> its 3-bit code (since 0.44)
    """Return the age code for `age_s` seconds: the largest step of AGE_STEPS_S it has reached (0 to 6), or 7 when the age is not said (NaN or negative)."""
    if not age_s == age_s or age_s < 0:  # not a number, or nonsense
        return (1 << AGE_BITS) - 1  # 7: not said
    return max(code for code, step in enumerate(AGE_STEPS_S) if age_s >= step)  # the last step reached


def noise_code(noise_db):  # a noise reading -> its 5-bit code (since 0.44)
    """Return the noise code for an S-meter reading of `noise_db` dB relative to S9: 3 dB steps from -60 dB (0) held to 0..30, or 31 when not measured (NaN)."""
    if not noise_db == noise_db or np.isinf(noise_db):  # not a usable number
        return NOISE_UNKNOWN  # 31: not measured
    return int(np.clip(round((noise_db - NOISE_FLOOR_DB) / NOISE_STEP_DB), 0, NOISE_UNKNOWN - 1))  # half S-units above -60 dB, held to 0..30


def pack_report(report):  # channel report -> 26 bits
    """Return the 26 bits of a channel report: SNR (6), fading index (3), frequency offset (6), wanted level (3), and since 0.44 its age (3) and the reporter's noise (5)."""
    snr = int(np.clip(round(report.snr_db) - SNR_FLOOR_DB, 0, (1 << SNR_BITS) - 1))  # SNR in whole dB above -30, held to 0..63
    fade = report.fade_index if report.fade_index == report.fade_index else (1 << FADE_BITS)  # a missing reading (not-a-number) is sent as the largest value, "fading"
    fade = int(np.clip(round(fade * FADE_STEPS_PER_UNIT), 0, (1 << FADE_BITS) - 1))  # fading index in quarters, held to 0..7
    limit = (1 << (OFFSET_BITS - 1)) - 1  # the largest offset step that fits (31)
    offset = int(np.clip(round(report.offset_hz / OFFSET_STEP_HZ), -limit - 1, limit))  # offset in 2 Hz steps, held to -32..31
    if not 0 <= report.want_level < (1 << LEVEL_BITS):  # the wanted level must fit its field
        raise ValueError("wanted level out of range")  # refuse nonsense
    return np.concatenate([  # the six fields, in order
        int_to_bits(snr, SNR_BITS),  # signal-to-noise ratio
        int_to_bits(fade, FADE_BITS),  # fading index
        int_to_bits(offset & ((1 << OFFSET_BITS) - 1), OFFSET_BITS),  # frequency offset, negative values in two's complement
        int_to_bits(report.want_level, LEVEL_BITS),  # the level asked for
        int_to_bits(age_code(report.age_s), AGE_BITS),  # how old the measurement is (since 0.44)
        int_to_bits(noise_code(report.noise_db), NOISE_BITS),  # the reporter's own noise (since 0.44)
    ])  # end of the report


def unpack_report(bits):  # 26 bits -> channel report
    """Return the channel report carried by 26 bits. The age comes back as the start of its step (AGE_STEPS_S), NaN when not said; the noise as dB relative to S9, NaN when not measured."""
    snr = bits_to_int(bits[:SNR_BITS]) + SNR_FLOOR_DB  # back to dB
    fade = bits_to_int(bits[SNR_BITS:SNR_BITS + FADE_BITS]) / FADE_STEPS_PER_UNIT  # back to an index
    at = SNR_BITS + FADE_BITS  # where the offset field starts
    raw = bits_to_int(bits[at:at + OFFSET_BITS])  # the offset field as an unsigned number
    if raw >= 1 << (OFFSET_BITS - 1):  # the top bit is set, so the offset is negative
        raw -= 1 << OFFSET_BITS  # undo the two's complement
    at += OFFSET_BITS  # where the wanted level starts
    want = bits_to_int(bits[at:at + LEVEL_BITS])  # the level asked for
    at += LEVEL_BITS  # where the age starts (since 0.44)
    age = bits_to_int(bits[at:at + AGE_BITS])  # the age code
    at += AGE_BITS  # where the noise reading starts
    noise = bits_to_int(bits[at:at + NOISE_BITS])  # the noise code
    age_s = AGE_STEPS_S[age] if age < len(AGE_STEPS_S) else float("nan")  # the start of its step, or not said
    noise_db = float(NOISE_FLOOR_DB + noise * NOISE_STEP_DB) if noise != NOISE_UNKNOWN else float("nan")  # dB relative to S9, or not measured
    return ChannelReport(float(snr), fade, float(raw * OFFSET_STEP_HZ), want, age_s, noise_db)  # the six readings


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


def pack_beacon(call, grid, levels, listening=True, mail_check=False, holds_mail=False, wide=False, rig=0, watts=0):  # beacon fields -> 101 bits
    """Return the body bits of a beacon: who is calling, where from, what it can do, what it wants, and (since 0.40) its rig type (Hamlib model number) and power in watts, 0 for either when not known."""
    rig, watts = beacon_rig(rig), beacon_watts(watts)  # held to what the fields carry
    done = native.pack_control(FRAME_TYPE_BEACON, origin=call, grid=grid, levels=levels, listening=listening, mail_check=mail_check, holds_mail=holds_mail, wide=wide, rig_model=rig, watts=watts)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    flags = [int(listening), int(mail_check), int(holds_mail), int(wide)]  # will take answers / wants its mail / holds mail for others / wide reply window (four slots instead of one)
    return np.concatenate([call_to_bits(call), grid_to_bits(grid), levels_to_bits(levels), np.array(flags, dtype=np.uint8), int_to_bits(rig, RIG_BITS), int_to_bits(watts, WATT_BITS)])  # callsign, locator, levels, flags, rig type, watts


def beacon_rig(rig):  # a rig type as a beacon carries it (since 0.40)
    """Return `rig` (a Hamlib model number, or text starting with one, such as "1035  Yaesu FT-991") as a whole number 0 to 65535; 0 when it is not one."""
    try:  # it may be text
        number = int(str(rig).split()[0]) if str(rig).strip() else 0  # the number at its start
    except (ValueError, IndexError):  # not a number
        return 0  # not known
    return number if 0 <= number < (1 << RIG_BITS) else 0  # in range, or not known


def beacon_watts(watts):  # a power as a beacon carries it (since 0.40)
    """Return `watts` rounded to whole watts and held to 0 to 1023; 0 when it is not a number."""
    try:  # it may be missing
        number = int(round(float(watts or 0)))  # whole watts
    except (TypeError, ValueError, OverflowError):  # not a number
        return 0  # not known
    return max(0, min((1 << WATT_BITS) - 1, number))  # held to what the field carries


def answer_grid_bits(grid):  # the sender's locator in an answer -> 15 bits
    """Return the 15 locator bits of an answer: the locator, or all ones when the sender has none set."""
    return grid_to_bits(grid) if (grid or "").strip() else int_to_bits(NO_GRID, GRID_BITS)  # a locator, or "none"


def answer_bits_grid(bits):  # 15 bits of an answer -> the sender's locator
    """Return the locator carried by an answer, "" when it says none, or raise ValueError when the bits are neither."""
    return "" if bits_to_int(bits) == NO_GRID else bits_to_grid(bits)  # none, or a locator (anything else is damage)


def pack_answer(dest, origin, report, levels, mail_check=False, directed=False, grid=""):  # answer fields -> 147 bits (139 before 0.44)
    """Return the body bits of an answer frame: who is answering (or calling) whom, from where, how the other station was last received, what the sender can do.

    With `directed` the frame is a directed call (Section 6.11) rather than a reply to a beacon.
    `grid` is the sender's four-character locator (since 0.33), or "" if it has none set.
    """
    done = native.pack_control(FRAME_TYPE_ANSWER, dest=dest, origin=origin, grid=grid, report=report, levels=levels, mail_check=mail_check, directed=directed)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    flags = [int(mail_check), int(directed)]  # wants its mail / a directed call
    return np.concatenate([call_to_bits(dest), call_to_bits(origin), answer_grid_bits(grid), pack_report(report), levels_to_bits(levels), np.array(flags, dtype=np.uint8)])  # addresses, locator, report, levels, flags


def pack_ack(link, msg_id, part, status, report):  # acknowledgment fields -> 56 bits (48 before 0.44)
    """Return the body bits of an acknowledgment for one frame of one message."""
    done = native.pack_control(FRAME_TYPE_ACK, link=link, msg_id=msg_id, part=part, status=status, report=report)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    if not (0 <= link < (1 << LINK_ID_BITS) and 0 <= msg_id < (1 << MSG_ID_BITS) and 0 <= part < (1 << PART_BITS) and 0 <= status < (1 << ACK_STATUS_BITS)):  # every number must fit its field
        raise ValueError("acknowledgment field out of range")  # refuse nonsense
    return np.concatenate([int_to_bits(link, LINK_ID_BITS), int_to_bits(msg_id, MSG_ID_BITS), int_to_bits(part, PART_BITS), int_to_bits(status, ACK_STATUS_BITS), pack_report(report)])  # link, message, part, status, report


def pack_ident(call, link, final=False):  # identification fields -> 61 bits
    """Return the body bits of a station identification; `final` marks the end of the contact."""
    done = native.pack_control(FRAME_TYPE_IDENT, origin=call, link=link, final_flag=final)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    if not 0 <= link < (1 << LINK_ID_BITS):  # the link number must fit its field
        raise ValueError("link number out of range")  # refuse nonsense
    flags = [int(final), 0, 0, 0]  # end of contact / three spare bits
    return np.concatenate([call_to_bits(call), int_to_bits(link, LINK_ID_BITS), np.array(flags, dtype=np.uint8)])  # callsign, link number, flags


def pack_notice(call, held=(), receipts=(), heard=()):  # mail notice fields -> 192 bits
    """Return the body bits of a mail notice: who sends it, then up to three short codes each for the stations it holds mail for, the delivery receipts it reports, and the stations it hears (0 marks an unused entry)."""
    done = native.pack_control(FRAME_TYPE_NOTICE, origin=call, held=held, receipts=receipts, heard=heard)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    codes = []  # the three lists, each padded to its full length
    for entries in (held, receipts, heard):  # in that order
        entries = [int(code) for code in entries][:NOTICE_SLOTS]  # at most three
        if any(not 0 < code < (1 << HASH_BITS) for code in entries):  # every code must fit its field, and 0 is kept for "empty"
            raise ValueError("notice code out of range")  # refuse nonsense
        codes += entries + [0] * (NOTICE_SLOTS - len(entries))  # pad with empty entries
    return np.concatenate([call_to_bits(call)] + [int_to_bits(code, HASH_BITS) for code in codes])  # callsign, then the nine codes


def unpack(frame_type, bits):  # body bits -> named fields
    """Return a dict of the fields carried by a control frame's body bits; raise ValueError when they make no sense."""
    done = native.unpack_control(frame_type, bits)  # compiled, when the library is in use
    if done is not None:  # it was: name its fields as below
        return _named(frame_type, done)  # the same fields
    if len(bits) != CONTROL_BITS[frame_type]:  # every control frame has a fixed length
        raise ValueError("wrong length for this control frame")  # refuse
    if frame_type == FRAME_TYPE_BEACON:  # a beacon
        rest = bits[CALL_BITS:]  # what follows the callsign
        flags = rest[GRID_BITS + LEVEL_MASK_BITS:GRID_BITS + LEVEL_MASK_BITS + 4]  # the four flag bits
        rig = rest[GRID_BITS + LEVEL_MASK_BITS + 4:]  # the rig type and watts (since 0.40)
        return {"origin": bits_to_call(bits[:CALL_BITS]), "grid": bits_to_grid(rest[:GRID_BITS]), "levels": bits_to_levels(rest[GRID_BITS:GRID_BITS + LEVEL_MASK_BITS]),  # (continued)
                "listening": bool(flags[0]), "mail_check": bool(flags[1]), "holds_mail": bool(flags[2]), "wide": bool(flags[3]),  # who, where, what it can do, what it wants
                "rig": bits_to_int(rig[:RIG_BITS]), "watts": bits_to_int(rig[RIG_BITS:RIG_BITS + WATT_BITS])}  # what it runs (0: not said)
    if frame_type == FRAME_TYPE_ANSWER:  # an answer to a beacon
        grid = answer_bits_grid(bits[2 * CALL_BITS:2 * CALL_BITS + GRID_BITS])  # the sender's locator, after the two callsigns
        rest = bits[2 * CALL_BITS + GRID_BITS:]  # what follows the callsigns and the locator
        return {"dest": bits_to_call(bits[:CALL_BITS]), "origin": bits_to_call(bits[CALL_BITS:2 * CALL_BITS]), "grid": grid, "report": unpack_report(rest[:REPORT_BITS]),  # (continued)
                "levels": bits_to_levels(rest[REPORT_BITS:REPORT_BITS + LEVEL_MASK_BITS]), "mail_check": bool(rest[REPORT_BITS + LEVEL_MASK_BITS]),  # (continued)
                "directed": bool(rest[REPORT_BITS + LEVEL_MASK_BITS + 1])}  # who to whom, the report, the levels, the two flags
    if frame_type == FRAME_TYPE_ACK:  # an acknowledgment
        rest = bits[LINK_ID_BITS + MSG_ID_BITS:]  # what follows the link and message numbers
        return {"link": bits_to_int(bits[:LINK_ID_BITS]), "msg_id": bits_to_int(bits[LINK_ID_BITS:LINK_ID_BITS + MSG_ID_BITS]), "part": bits_to_int(rest[:PART_BITS]),  # (continued)
                "status": bits_to_int(rest[PART_BITS:PART_BITS + ACK_STATUS_BITS]), "report": unpack_report(rest[PART_BITS + ACK_STATUS_BITS:])}  # which frame, the verdict, the report
    if frame_type == FRAME_TYPE_IDENT:  # a station identification
        return {"origin": bits_to_call(bits[:CALL_BITS]), "link": bits_to_int(bits[CALL_BITS:CALL_BITS + LINK_ID_BITS]), "final": bool(bits[CALL_BITS + LINK_ID_BITS])}  # who, which link, end of contact?
    if frame_type == FRAME_TYPE_NOTICE:  # a mail notice
        codes = [bits_to_int(bits[CALL_BITS + n * HASH_BITS:CALL_BITS + (n + 1) * HASH_BITS]) for n in range(3 * NOTICE_SLOTS)]  # the nine codes
        lists = [[code for code in codes[n * NOTICE_SLOTS:(n + 1) * NOTICE_SLOTS] if code] for n in range(3)]  # the three lists, empty entries left out
        return {"origin": bits_to_call(bits[:CALL_BITS]), "held": lists[0], "receipts": lists[1], "heard": lists[2]}  # who, and the three lists
    raise ValueError("not a control frame type")  # anything else is not handled here


def _named(frame_type, f):  # the library's fields -> the same named fields unpack() returns
    """Return the dict unpack() gives, built from the fields the compiled library unpacked."""
    levels = tuple(level for level in range(LEVEL_MASK_BITS) if f.levels & (1 << level))  # the levels, lowest first
    report = ChannelReport(f.snr_db, f.fade_index, f.offset_hz, f.want_level, f.age_s, f.noise_db)  # the channel report (its age and the reporter's noise since 0.44)
    if frame_type == FRAME_TYPE_BEACON:  # a beacon
        return {"origin": f.origin.decode("ascii"), "grid": f.grid.decode("ascii"), "levels": levels,  # (continued)
                "listening": bool(f.listening), "mail_check": bool(f.mail_check), "holds_mail": bool(f.holds_mail), "wide": bool(f.wide),  # who, where, what it can do, what it wants
                "rig": int(f.rig_model), "watts": int(f.watts)}  # what it runs (0: not said; since 0.40)
    if frame_type == FRAME_TYPE_ANSWER:  # an answer
        return {"dest": f.dest.decode("ascii"), "origin": f.origin.decode("ascii"), "grid": f.grid.decode("ascii"), "report": report, "levels": levels,  # (continued)
                "mail_check": bool(f.mail_check), "directed": bool(f.directed)}  # who to whom, the report, the levels, the two flags
    if frame_type == FRAME_TYPE_ACK:  # an acknowledgment
        return {"link": f.link, "msg_id": f.msg_id, "part": f.part, "status": f.status, "report": report}  # which frame, the verdict, the report
    if frame_type == FRAME_TYPE_IDENT:  # an identification
        return {"origin": f.origin.decode("ascii"), "link": f.link, "final": bool(f.final_flag)}  # who, which link, end of contact?
    return {"origin": f.origin.decode("ascii"), "held": list(f.held[:f.nheld]), "receipts": list(f.receipts[:f.nreceipts]), "heard": list(f.heard[:f.nheard])}  # a mail notice: who, and the three lists
