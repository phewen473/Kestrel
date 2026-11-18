"""Choosing how to send a message: which speed level, and whether to split it.

The rules (specification section 6.8):
  1. Use the fastest level the measured conditions support.
  2. Keep each transmission within 60 seconds.
  3. If conditions are too poor for that, allow up to 90 seconds.
  4. If the message still does not fit, split it into shorter parts,
     each sent and acknowledged as a frame of its own.
"""

from .frame import build_frame, frame_seconds  # transmitter and airtime calculator
from .levels import FADE_INDEX_LIMIT, LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB  # the speed levels and the SNR each one needs, steady and fading
from .params import AIRTIME_CAP_S, AIRTIME_POOR_CAP_S, MAX_PARTS, SIZE_CLASSES  # limits and sizes
from .text import fits, pick_size_class  # which size class a text needs, and whether a text fits one


def is_fading(fade_index):  # steady signal or fading signal?
    """Return True when a receiver's fading index says the signal is fading (or the index is missing)."""
    return not fade_index <= FADE_INDEX_LIMIT  # written this way so a missing reading (not-a-number) counts as fading, the safe choice


def pick_level(snr_db, margin_db=2.0, fading=False):  # rule 1
    """Return the number of the fastest level that works at `snr_db`, keeping `margin_db` in hand.

    Set `fading` when the signal is fading: each level then needs a
    stronger signal, because fades wipe out parts of the frame.
    """
    limits = MIN_SNR_FADING_DB if fading else MIN_SNR_DB  # which table of limits applies
    usable = [spec.number for spec in LEVELS if snr_db >= limits[spec.number] + margin_db]  # every level the signal is strong enough for
    return max(usable) if usable else 0  # the fastest of them; the slowest level when none qualifies


def plan_message(text, snr_db, cap_s=AIRTIME_CAP_S, poor_cap_s=AIRTIME_POOR_CAP_S, margin_db=2.0, fading=False):  # rules 1 to 4
    """Return a list of transmissions for `text`, one dict per frame.

    Each dict has: text (what this frame carries), level, part, parts,
    seconds (airtime) and extended (True when the frame needs the 90-second allowance).
    Set `fading` when the signal is fading (see pick_level).
    """
    level = pick_level(snr_db, margin_db, fading)  # rule 1: fastest level the conditions support
    whole = frame_seconds(pick_size_class(text), level)  # airtime if the message is sent whole
    if whole <= poor_cap_s:  # rules 2 and 3: it fits in 60 seconds, or in 90 when conditions are poor
        return [{"text": text, "level": level, "part": 0, "parts": 1, "seconds": whole, "extended": whole > cap_s}]  # send it as one frame
    fitting = [c for c in range(len(SIZE_CLASSES)) if frame_seconds(c, level) <= poor_cap_s]  # size classes short enough at this level
    size_class = max(fitting) if fitting else 0  # rule 4: the largest frame that fits the limit (the smallest if none does)
    pieces = []  # the text cut into pieces, each fitting one frame
    rest = text  # the text still to be cut up
    while rest:  # until nothing is left
        take = len(rest)  # start by trying to take everything that remains
        while not fits(rest[:take], size_class):  # too big for one frame?
            take -= 1  # take one character fewer and try again
        pieces.append(rest[:take])  # that is the next piece
        rest = rest[take:]  # carry on with what is left
    if len(pieces) > MAX_PARTS:  # more pieces than the header can number
        raise ValueError("message needs too many parts")  # refuse (cannot happen with 200 characters and 50-character frames)
    plan = []  # the list of frames to send
    for part, piece in enumerate(pieces):  # one frame per piece
        seconds = frame_seconds(pick_size_class(piece), level)  # its airtime
        plan.append({"text": piece, "level": level, "part": part, "parts": len(pieces), "seconds": seconds, "extended": seconds > cap_s})  # add it to the plan
    return plan  # all the frames, in order


def build_plan(plan):  # turn a plan into audio
    """Return the audio of every frame in `plan`, as a list."""
    return [build_frame(item["text"], item["level"], item["part"], item["parts"]) for item in plan]  # one transmitter call per frame


def join_parts(results):  # put a split message back together
    """Return the whole message from a list of receiver reports, or None while any part is missing or bad."""
    good = {r.part: r for r in results if r.ok}  # the parts that decoded, by part number (a later copy replaces an earlier one)
    if not good:  # nothing decoded yet
        return None  # no message
    count = next(iter(good.values())).parts  # how many parts the message has
    if any(r.parts != count for r in good.values()) or set(good) != set(range(count)):  # parts disagree, or some are still missing
        return None  # not complete yet
    return "".join(good[i].text for i in range(count))  # glue the parts together in order
