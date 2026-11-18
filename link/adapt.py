"""Speed adaptation: how a receiving station decides which level to ask its partner for.

The station that hears the signal is the one that knows how good it is,
so it makes the decision and sends it back in every channel report.
"""

from modem import LEVELS, is_fading, pick_level  # the speed levels, the fading test and the level-choice rule

from .params import SNR_LOOKBACK, STEP_UP_CLEAN, STEP_UP_LEVELS  # how far back to look, how many clean frames earn a faster level, and how far to climb at once


def common_levels(mine, theirs):  # which levels can both stations use?
    """Return the sorted speed levels that appear in both lists; level 0 is always included."""
    known = {spec.number for spec in LEVELS}  # levels this program can send and receive
    return sorted(({0} | (set(mine) & set(theirs))) & known)  # shared levels, never without the slowest


def cap_level(level, allowed):  # keep a level inside what both stations can use
    """Return the fastest allowed level that is not faster than `level`."""
    usable = [n for n in allowed if n <= level]  # allowed levels at or below the one wanted
    return max(usable) if usable else min(allowed)  # the fastest of them; the slowest allowed if none is low enough


def supported_level(history, allowed):  # what the recent measurements can carry
    """Return the fastest level the recent measurements support.

    `history` is a list of (SNR in dB, fading index) pairs, newest last.
    The weakest of the last few SNR readings is used, and the signal
    counts as fading if any recent frame looked like fading.
    """
    recent = history[-SNR_LOOKBACK:]  # the last few frames
    snr_db = min(entry[0] for entry in recent)  # be guided by the weakest of them
    fading = any(is_fading(entry[1]) for entry in history)  # one fading frame is enough to be careful
    return cap_level(pick_level(snr_db, fading=fading), allowed)  # the level-choice rule of the specification, held to shared levels


def wanted_level(history, current, clean_run, failed, allowed):  # the decision sent back in the channel report
    """Return the level to ask the partner for.

    `current` is the level asked for last time, `clean_run` the number of
    frames in a row received correctly, and `failed` says whether the
    frame just heard failed its check.
    - After a failure: one level below the lower of the current level and what the measurements support.
    - When measurements support less than the current level: drop to that at once.
    - When they support more: go up, at most two levels at a time, but only after a run of clean frames.
    """
    target = supported_level(history, allowed)  # what the measurements say
    if failed:  # the frame just heard did not decode
        return cap_level(min(current, target) - 1, allowed)  # step down below both
    if target < current:  # conditions have slipped
        return target  # step down before frames start failing
    if target > current and clean_run >= STEP_UP_CLEAN:  # conditions are better and have stayed good
        faster = [n for n in allowed if current < n <= target]  # the allowed levels between here and what is supported
        return faster[min(STEP_UP_LEVELS, len(faster)) - 1]  # climb towards it, at most two levels at once
    return current  # otherwise stay put
