"""Static-crash blanker: silences short, very loud spikes before decoding.

"Loud" is judged against the audio around each spike, a tenth of a second
at a time. A strong signal raises the level of its own neighbourhood, so
it is never mistaken for a spike, however quiet the rest of the
recording is.
"""

import numpy as np  # numerical arrays

BLOCK = 1200  # samples per neighbourhood: a tenth of a second at 12,000 samples per second


def blank_impulses(x, threshold=4.5, guard=12):  # remove loud spikes
    """Return a copy of `x` with samples far above the level of their own neighbourhood set to zero."""
    level = np.abs(x)  # size of every sample, ignoring sign
    blocks = -(-len(level) // BLOCK)  # number of neighbourhoods, rounding up
    if blocks == 0:  # an empty recording
        return x.copy()  # nothing to do
    padded = np.concatenate([level, np.full(blocks * BLOCK - len(level), np.nan)])  # fill the last neighbourhood out with blanks
    typical = np.nanmedian(padded.reshape(blocks, BLOCK), axis=1) / 0.6745  # the normal level in each neighbourhood (a median is not fooled by a brief spike)
    quiet = np.median(level[level > 0]) / 0.6745 if (level > 0).any() else 0.0  # the normal level of the whole recording
    typical = np.maximum(typical, quiet)  # a neighbourhood is never judged quieter than the recording as a whole (pure silence would make everything look loud)
    loud = level > threshold * np.repeat(typical, BLOCK)[:len(level)]  # samples much louder than their neighbourhood
    if not loud.any():  # no spikes found
        return x.copy()  # leave the signal alone
    spread = np.convolve(loud.astype(float), np.ones(2 * guard + 1), mode="same") > 0  # widen each spike by a millisecond either side
    out = x.copy()  # work on a copy
    out[spread] = 0.0  # silence the spikes and their edges
    return out  # the cleaned signal
