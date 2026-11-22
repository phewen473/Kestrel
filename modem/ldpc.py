"""LDPC error correction for the message body.

The code is a rate-1/2 "repeat-accumulate" LDPC code: for k data bits it
sends the k data bits followed by k parity bits. Its structure makes it
simple to build, simple to encode, and easy to reproduce exactly in any
other language:

  * every data bit takes part in exactly three parity checks, chosen by
    three pseudo-random shuffles made with a tiny, fully specified
    random-number routine (xorshift32);
  * each parity bit is the running XOR ("accumulation") of the checks so far.

The decoder is the standard normalised min-sum belief-propagation decoder.
"""

from functools import lru_cache  # remembers each code after building it once

import numpy as np  # numerical arrays

from . import native  # the compiled library, used when present

SEEDS = (0x4B455301, 0x4B455302, 0x4B455303)  # starting values for the three shuffles ("KES" + 1, 2, 3)
SCALE = 0.8  # min-sum correction factor (the usual choice)
MAX_ITERATIONS = 80  # give up after this many decoding rounds


def _xorshift32(state):  # the random-number routine
    """Return the next 32-bit value of the xorshift32 generator."""
    state ^= (state << 13) & 0xFFFFFFFF  # mix: shift left 13, keep 32 bits
    state ^= state >> 17  # mix: shift right 17
    state ^= (state << 5) & 0xFFFFFFFF  # mix: shift left 5, keep 32 bits
    return state  # the new value


def _shuffle(k, seed):  # one pseudo-random ordering of 0..k-1
    """Return the numbers 0..k-1 in a shuffled order fixed by `seed` (Fisher-Yates shuffle)."""
    order = list(range(k))  # start in counting order
    state = seed  # the generator's starting value
    for i in range(k - 1, 0, -1):  # walk from the last position down to the second
        state = _xorshift32(state)  # next random value
        j = state % (i + 1)  # pick a position at or below i
        order[i], order[j] = order[j], order[i]  # swap the two entries
    return order  # the shuffled list


@lru_cache(maxsize=None)  # build each size once and keep it
def info_checks(k):  # which three checks each data bit joins
    """Return a (3, k) array: row t, column j is the t-th parity check that data bit j takes part in.

    The three shuffles are repaired as they are read so that, wherever
    possible, no data bit uses the same check twice, no data bit uses two
    neighbouring checks, and no two data bits share more than one check.
    Those rules remove the short loops that weaken an LDPC code.
    """
    rows = [_shuffle(k, seed) for seed in SEEDS]  # the three shuffles
    used = set()  # every pair of checks already shared by some data bit

    def pairs(j):  # the three pairs of checks data bit j would use
        a, b, c = sorted((rows[0][j], rows[1][j], rows[2][j]))  # its three checks, in order
        return ((a, b), (a, c), (b, c))  # the pairs

    def valid(j):  # does data bit j obey the rules?
        for lo, hi in pairs(j):  # look at each pair of its checks
            if hi - lo <= 1 or (lo, hi) in used:  # same check twice, neighbouring checks, or a pair already taken
                return False  # rule broken
        return True  # all three pairs are fine

    for j in range(k):  # settle the data bits one at a time
        if not valid(j):  # this bit breaks a rule: try to repair it
            fixed = False  # not repaired yet
            for other in range(j + 1, k):  # look at each later, still unsettled, data bit
                for t in range(3):  # and each of the three shuffles
                    rows[t][j], rows[t][other] = rows[t][other], rows[t][j]  # trade one check with the later bit
                    if valid(j):  # did that repair it?
                        fixed = True  # yes
                        break  # stop trying shuffles
                    rows[t][j], rows[t][other] = rows[t][other], rows[t][j]  # no: trade back
                if fixed:  # repaired
                    break  # stop looking at later bits
        used.update(pairs(j))  # record the pairs this bit uses (even if it could not be repaired)
    return np.array(rows, dtype=np.int64)  # the finished table


def encode(bits):  # data bits -> codeword
    """Return the codeword for `bits`: the data bits followed by an equal number of parity bits."""
    bits = np.asarray(bits, dtype=np.int64)  # work in whole numbers
    k = len(bits)  # number of data bits
    sums = np.zeros(k, dtype=np.int64)  # how many 1-valued data bits feed each check
    for row in info_checks(k):  # each of the three shuffles
        np.add.at(sums, row, bits)  # add every data bit into the check it joins
    parity = np.bitwise_xor.accumulate(sums & 1)  # each parity bit = XOR of all checks up to and including its own
    return np.concatenate([bits, parity]).astype(np.uint8)  # data first, then parity


@lru_cache(maxsize=None)  # build each size once and keep it
def _graph(k):  # the decoder's wiring for a code with k data bits
    """Return (check of each edge, bit of each edge, first edge of each check), with edges sorted by check."""
    rows = info_checks(k)  # checks used by the data bits
    checks = [rows[t] for t in range(3)]  # edges from data bits: their checks...
    bits = [np.arange(k)] * 3  # ...and the data bits themselves
    checks.append(np.arange(k))  # parity bit i joins check i...
    bits.append(k + np.arange(k))  # ...(parity bits are numbered after the data bits)
    checks.append(np.arange(1, k))  # ...and parity bit i also joins check i + 1
    bits.append(k + np.arange(k - 1))  # (all but the last parity bit)
    checks = np.concatenate(checks)  # one long list of edges: the check end
    bits = np.concatenate(bits)  # and the bit end
    order = np.argsort(checks, kind="stable")  # sort the edges by check
    checks, bits = checks[order], bits[order]  # apply the sort
    starts = np.searchsorted(checks, np.arange(k))  # where each check's edges begin
    return checks, bits, starts  # the wiring


def decode(llrs, k):  # soft codeword -> data bits
    """Decode 2k soft values (positive = probably 0). Returns (k data bits, True if every check is satisfied)."""
    llrs = np.asarray(llrs, dtype=float)  # make sure we have floating-point numbers
    done = native.ldpc_decode(llrs, k, _graph(k), SCALE, MAX_ITERATIONS)  # the compiled decoder, when the library is in use
    if done is not None:  # it was
        return done  # the same bits and verdict as the Python below
    checks, bits, starts = _graph(k)  # the code's wiring
    to_check = llrs[bits].copy()  # messages from bits to checks start as the received values
    total = llrs  # running belief about every bit
    for _ in range(MAX_ITERATIONS):  # repeat until the checks are satisfied or we give up
        mag = np.abs(to_check)  # confidence of each incoming message
        neg = to_check < 0  # which incoming messages say "1"
        low = np.minimum.reduceat(mag, starts)  # least confident message into each check
        is_low = mag == low[checks]  # edges that carry that least confident message
        ties = np.add.reduceat(is_low.astype(np.int64), starts)  # how many edges tie for least confident
        second = np.minimum.reduceat(np.where(is_low, np.inf, mag), starts)  # least confident among the others
        second = np.where(ties > 1, low, second)  # with a tie, the runner-up equals the minimum
        out_mag = np.where(is_low & (ties[checks] == 1), second[checks], low[checks])  # each edge hears the minimum of the *other* edges
        odd = np.add.reduceat(neg.astype(np.int64), starts) & 1  # is the number of "1" votes into each check odd?
        out_neg = odd[checks] ^ neg  # each edge hears the parity of the *other* edges
        to_bit = SCALE * out_mag * (1.0 - 2.0 * out_neg)  # messages from checks back to bits
        total = llrs + np.bincount(bits, weights=to_bit, minlength=2 * k)  # new belief: received value plus all check messages
        hard = total < 0  # current best guess of every bit
        if not (np.add.reduceat(hard[bits].astype(np.int64), starts) & 1).any():  # every check satisfied?
            return hard[:k].astype(np.uint8), True  # done: return the data bits
        to_check = total[bits] - to_bit  # next round: each bit tells a check everything except what that check said
    return (total < 0)[:k].astype(np.uint8), False  # gave up: return the best guess and say so
