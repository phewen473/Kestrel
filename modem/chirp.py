"""The Kestrel signature: a rising sweep followed by a falling sweep.

Why two sweeps: a single sweep cannot tell "the signal arrived a little
late" from "the signal is a little off frequency" - both slide the
detection peak the same way. With one sweep up and one sweep down, a
frequency error slides the two peaks in opposite directions while a
timing error slides them together, so both can be measured.
"""

import numpy as np  # numerical arrays
from scipy.signal import correlate  # fast sliding comparison of two signals

from .params import CHIRP_F0, CHIRP_F1, CHIRP_RAMP_SECONDS, CHIRP_RATE, CHIRP_SAMPLES, FS  # chirp numbers


def _phase(up):  # the running phase angle of one sweep
    """Return the phase (in radians) at every sample of an up or down sweep."""
    t = np.arange(CHIRP_SAMPLES) / FS  # time of every sample, in seconds
    if up:  # rising sweep: starts low and climbs
        return 2 * np.pi * (CHIRP_F0 * t + 0.5 * CHIRP_RATE * t * t)  # phase of a steadily rising tone
    return 2 * np.pi * (CHIRP_F1 * t - 0.5 * CHIRP_RATE * t * t)  # falling sweep: starts high and drops


def _window():  # gentle fade at both ends of a sweep
    """Return a volume envelope that fades in and out to avoid clicks."""
    ramp = int(CHIRP_RAMP_SECONDS * FS)  # number of samples in each fade
    win = np.ones(CHIRP_SAMPLES)  # full volume in the middle
    edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # smooth rise from 0 to 1
    win[:ramp] = edge  # fade in
    win[-ramp:] = edge[::-1]  # fade out
    return win  # the finished envelope


def make_chirp_pair():  # what the transmitter sends at the start of every frame
    """Return the audio of the up sweep followed by the down sweep."""
    win = _window()  # the fade envelope
    up = np.cos(_phase(True)) * win  # rising sweep
    down = np.cos(_phase(False)) * win  # falling sweep
    return np.concatenate([up, down])  # one after the other


def _refine(curve, index):  # find the true top of a peak between samples
    """Return the peak position near `index`, to a fraction of a sample."""
    if 0 < index < len(curve) - 1:  # we need a neighbour on each side
        a, b, c = curve[index - 1], curve[index], curve[index + 1]  # the peak sample and its neighbours
        bend = a - 2 * b + c  # how sharply the three points curve
        if bend != 0:  # a flat line has no top to find
            return index + 0.5 * (a - c) / bend  # top of the parabola through the three points
    return float(index)  # at the edges just use the sample itself


def detect_chirp_pair(x, max_offset_hz=50.0, candidates=64, keep=3):  # what the receiver does first
    """Look for the chirp pair in `x`.

    Returns a list (strongest first, at most `keep` long, empty when `x` is
    too short) of dicts with:
    start (sample where the frame begins, may be fractional),
    offset_hz (how far off frequency the signal is) and
    quality (peak strength compared with the background; about 1 for pure noise).
    Several candidates are returned because, in deep noise, a noise peak can
    briefly outrank the real chirp; the receiver tries each until the header checks out.
    """
    if len(x) < 2 * CHIRP_SAMPLES:  # not even room for one chirp pair
        return []  # nothing to find
    win = _window()  # the same fade envelope the transmitter used
    ref_up = np.exp(1j * _phase(True)) * win  # complex copy of the up sweep to compare against
    ref_down = np.exp(1j * _phase(False)) * win  # complex copy of the down sweep
    match_up = np.abs(correlate(x, ref_up, mode="valid", method="fft"))  # how well the up sweep matches at every start position
    match_down = np.abs(correlate(x, ref_down, mode="valid", method="fft"))  # the same for the down sweep
    background = 0.5 * (np.median(match_up ** 2) + np.median(match_down ** 2)) / np.log(2)  # typical match power when nothing is there
    reach = int(np.ceil(2 * max_offset_hz / CHIRP_RATE * FS))  # how far a frequency error can slide the down peak
    work = match_up.copy()  # scratch copy we can cross candidates off
    pairs = []  # (score, up position, down position) for every candidate pair
    for _ in range(candidates):  # try the strongest up-sweep peaks, one by one
        i_up = int(np.argmax(work))  # strongest remaining up-sweep peak
        lo = max(i_up + CHIRP_SAMPLES - reach, 0)  # earliest place its down sweep could be
        hi = min(i_up + CHIRP_SAMPLES + reach + 1, len(match_down))  # latest place its down sweep could be
        if lo < hi:  # only if that range is inside the recording
            i_down = lo + int(np.argmax(match_down[lo:hi]))  # strongest down-sweep peak in that range
            pairs.append((match_up[i_up] ** 2 + match_down[i_down] ** 2, i_up, i_down))  # combined strength of the pair
        work[max(i_up - 60, 0):i_up + 61] = 0  # cross this peak off and look for the next
    pairs.sort(key=lambda pair: -pair[0])  # strongest pair first
    found = []  # the measurements for the best few pairs
    for score, i_up, i_down in pairs[:keep]:  # keep only the best few
        pos_up = _refine(match_up, i_up)  # up peak position to a fraction of a sample
        pos_down = _refine(match_down, i_down)  # down peak position to a fraction of a sample
        gap = pos_down - pos_up - CHIRP_SAMPLES  # how far apart the peaks are, beyond the expected one sweep
        found.append({  # the three measurements for this pair
            "start": pos_up + gap / 2,  # timing: midway between where the two peaks point
            "offset_hz": CHIRP_RATE * gap / (2 * FS),  # frequency error: from how far the peaks slid apart
            "quality": score / (2 * background),  # strength of the detection against the background
        })  # end of this candidate
    return found  # strongest first
