"""Holding the transmitter's output power by the audio drive, and spotting a sag (since 0.40R1).

On the air (November 24, 2026) a radio's output fell from 22 W to 10 W
over five minute-long frames while Kestrel's audio level never changed.
Kestrel cannot see why a radio does that, but it reads the power the radio
measures, so it can (1) say so, and (2) when the operator names a power to
hold, raise or lower the drive for the next transmission to bring the
power back. Power goes roughly as the square of the drive while ALC is
not acting, so the drive is multiplied by the square root of
wanted / measured, at most STEP_DB a step, and never upward while ALC is
high (more drive there only distorts the tones).
"""

STEP_DB = 2.0  # the most the drive changes in one step, either way, in dB
CLOSE = 0.10  # within this share of the wanted power nothing is changed (10 %)
GAIN_LOW, GAIN_HIGH = 0.01, 1.0  # the drive's limits (1.0 is the sound card's full scale)
SAG_SHARE = 0.70  # power ending below this share of where it began is reported as a sag
SAG_MOST = 6  # a sag is judged only from at least this many readings


def wanted_watts(setting):  # the power to hold, from the setting's text
    """Return the watts in `setting` as a number, or None when it is blank, zero or not a number (holding is off)."""
    try:  # it may be blank
        watts = float(str(setting).strip())  # as a number
    except (TypeError, ValueError):  # blank or words
        return None  # off
    return watts if watts > 0 else None  # a real power, or off


def next_gain(gain, measured_w, alc, setting, alc_high=0.5):  # the drive for the next transmission
    """Return (new drive, reason) to bring `measured_w` toward the power in `setting`, or (None, "") when holding is off, the power is close enough, or the drive is at its limit."""
    wanted = wanted_watts(setting)  # the power to hold
    if wanted is None or measured_w <= 0 or gain <= 0:  # off, or nothing to work from
        return None, ""  # no change
    most = 10 ** (STEP_DB / 20.0)  # the largest step, as a ratio of drive
    if alc is not None and alc >= alc_high and measured_w <= wanted * (1 + CLOSE):  # ALC is high and the power is not over: more drive would only distort
        if measured_w >= wanted * (1 - CLOSE):  # and the power is about right
            return None, ""  # leave it
        new, why = gain / (10 ** (1.0 / 20.0)), f"wanted {wanted:g} W but ALC is {alc:.2f}: lowering the drive 1 dB (raise the radio's power setting instead)"  # back off a little, and say what would help
    else:  # ALC is quiet, or the power is over
        if abs(measured_w - wanted) <= wanted * CLOSE:  # close enough
            return None, ""  # leave it
        factor = max(1.0 / most, min(most, (wanted / measured_w) ** 0.5))  # power goes as the square of the drive; held to one step
        new, why = gain * factor, f"wanted {wanted:g} W"  # the new drive
    new = round(max(GAIN_LOW, min(GAIN_HIGH, new)), 3)  # within the limits
    return (None, "") if abs(new - gain) < 0.0005 else (new, why)  # no change at a limit


def sag(readings):  # did the power fall during one transmission?
    """Return (watts at the start, watts at the end) when the median of the last third of `readings` [(watts, ALC)] is below SAG_SHARE of the first third's, else None."""
    watts = [w for w, _ in readings]  # the powers, in time order
    if len(watts) < SAG_MOST:  # too few to judge
        return None  # nothing said
    third = len(watts) // 3  # a third of them
    first, last = sorted(watts[:third])[third // 2], sorted(watts[-third:])[third // 2]  # the medians of the first and last thirds
    return (first, last) if first > 0 and last < SAG_SHARE * first else None  # a sag, or not
