"""Static-crash blanker: silences short, very loud spikes before decoding."""

import numpy as np  # numerical arrays


def blank_impulses(x, threshold=4.5, guard=12):  # remove loud spikes
    """Return a copy of `x` with samples far above the normal level set to zero."""
    level = np.abs(x)  # size of every sample, ignoring sign
    active = level[level > 0]  # ignore pure silence when judging what is normal
    if len(active) == 0:  # nothing but silence
        return x.copy()  # nothing to blank
    sigma = np.median(active) / 0.6745  # robust estimate of the normal level (not fooled by the spikes)
    loud = level > threshold * sigma  # samples much louder than normal
    if not loud.any():  # no spikes found
        return x.copy()  # leave the signal alone
    spread = np.convolve(loud.astype(float), np.ones(2 * guard + 1), mode="same") > 0  # widen each spike by a millisecond either side
    out = x.copy()  # work on a copy
    out[spread] = 0.0  # silence the spikes and their edges
    return out  # the cleaned signal
