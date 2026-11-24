"""Interleaver: shuffles the coded bits so a fade or noise burst is spread thinly over the whole frame.

The shuffle is a simple formula (no random numbers), so any other
program can reproduce it exactly: bit i moves to position (step * i) mod n,
where step is close to n divided by the golden ratio.
"""

from math import gcd  # greatest common divisor, used to keep the shuffle one-to-one

import numpy as np  # numerical arrays

GOLDEN = 0.6180339887498949  # 1 / golden ratio: spreads neighbors far apart


def _step(n):  # choose the multiplier for a frame of n bits
    """Return a step near n * 0.618 that shares no factor with n."""
    target = int(round(n * GOLDEN))  # the ideal step
    for delta in range(n):  # search outwards from the ideal
        for cand in (target + delta, target - delta):  # try just above, then just below
            if 0 < cand < n and gcd(cand, n) == 1:  # valid only if it shares no factor with n
                return cand  # the first valid step is the one we use
    return 1  # only reached for tiny n: fall back to "no shuffle"


def permutation(n):  # where each bit goes
    """Return an array p where original bit i is sent in position p[i]."""
    return (_step(n) * np.arange(n, dtype=np.int64)) % n  # the golden-step formula


def interleave(values):  # shuffle before sending
    """Return `values` in transmit order."""
    values = np.asarray(values)  # accept lists as well as arrays
    out = np.empty_like(values)  # room for the shuffled copy
    out[permutation(len(values))] = values  # drop each value into its transmit position
    return out  # the shuffled values


def deinterleave(values):  # undo the shuffle after receiving
    """Return received `values` in their original order."""
    values = np.asarray(values)  # accept lists as well as arrays
    return values[permutation(len(values))]  # pick each value back out of its transmit position
