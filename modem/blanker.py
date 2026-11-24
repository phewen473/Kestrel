"""Static-crash blanker: silences short, very loud spikes before decoding.

"Loud" is judged against the audio around each spike, a tenth of a second
at a time. A strong signal raises the level of its own neighborhood, so
it is never mistaken for a spike, however quiet the rest of the
recording is.
"""

import numpy as np  # numerical arrays

from . import native  # the compiled library, used when present

BLOCK = 1200  # samples per neighborhood: a tenth of a second at 12,000 samples per second


def blank_impulses(x, threshold=4.5, guard=12):  # remove loud spikes
    """Return a copy of `x` with samples far above the level of their own neighborhood set to zero."""
    done = native.blank_impulses(x, threshold, guard)  # the compiled version, when the library is in use
    if done is not None:  # it was
        return done  # its result is the same as the Python below gives
    level = np.abs(x)  # size of every sample, ignoring sign
    blocks = -(-len(level) // BLOCK)  # number of neighborhoods, rounding up
    if blocks == 0:  # an empty recording
        return x.copy()  # nothing to do
    full = len(level) // BLOCK  # neighborhoods that are whole
    typical = np.empty(blocks)  # the normal level in each neighborhood (a median is not fooled by a brief spike)
    if full:  # the whole ones, all at once
        typical[:full] = np.median(level[:full * BLOCK].reshape(full, BLOCK), axis=1) / 0.6745  # one median per neighborhood
    if blocks > full:  # the last one is short
        typical[full] = np.median(level[full * BLOCK:]) / 0.6745  # its median, from the samples it has (as the padded, NaN-skipping median gave before 0.31)
    quiet = np.median(level[level > 0]) / 0.6745 if (level > 0).any() else 0.0  # the normal level of the whole recording
    typical = np.maximum(typical, quiet)  # a neighborhood is never judged quieter than the recording as a whole (pure silence would make everything look loud)
    loud = level > threshold * np.repeat(typical, BLOCK)[:len(level)]  # samples much louder than their neighborhood
    if not loud.any():  # no spikes found
        return x.copy()  # leave the signal alone
    places = np.flatnonzero(loud)  # where the spikes are
    widened = (places[:, None] + np.arange(-guard, guard + 1)[None, :]).ravel()  # each spike widened by a millisecond either side
    widened = widened[(widened >= 0) & (widened < len(x))]  # kept inside the recording
    out = x.copy()  # work on a copy
    out[widened] = 0.0  # silence the spikes and their edges
    return out  # the cleaned signal
