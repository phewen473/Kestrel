"""Error correction for the prototype: a rate-1/2 convolutional code with a soft Viterbi decoder.

This is a stand-in. The design plans an LDPC code; this well-known code
(constraint length 7, generators 171 and 133 octal) lets the rest of the
modem be tested end to end today.
"""

import numpy as np  # numerical arrays

from . import native  # the compiled library, used when present

G1 = 0o171  # first generator: which register bits feed the first output bit
G2 = 0o133  # second generator: which register bits feed the second output bit
NSTATES = 64  # the encoder remembers 6 past bits, so it has 2**6 states
TAIL = 6  # zero bits added at the end to bring the encoder back to state 0


def _parity(value):  # helper: is the number of 1 bits odd?
    """Return 1 when `value` has an odd number of 1 bits, else 0."""
    return bin(value).count("1") & 1  # count the ones and keep the low bit


def conv_encode(bits):  # data bits -> coded bits (twice as many, plus the tail)
    """Encode `bits`; the result has 2 * (len(bits) + 6) bits."""
    state = 0  # the encoder starts with an empty memory
    out = np.zeros(2 * (len(bits) + TAIL), dtype=np.uint8)  # room for two output bits per input bit
    for i, b in enumerate(list(bits) + [0] * TAIL):  # the data, then six zeros to flush the memory
        reg = (state << 1) | int(b)  # 7-bit register: six remembered bits plus the new one
        out[2 * i] = _parity(reg & G1)  # first output bit
        out[2 * i + 1] = _parity(reg & G2)  # second output bit
        state = reg & (NSTATES - 1)  # remember the newest six bits for next time
    return out  # the coded bits


_STATES = np.arange(NSTATES)  # every possible encoder state, 0..63
_INPUT = _STATES & 1  # the input bit that must have led into each state
_PRED = np.stack([(_STATES >> 1) | (h << 5) for h in (0, 1)])  # the two states each state can be reached from
_REG = (_PRED << 1) | _INPUT  # the 7-bit register on each of those two paths
_SIGN1 = 1.0 - 2.0 * np.array([[_parity(int(r) & G1) for r in row] for row in _REG])  # first output bit per path, as +1 (bit 0) or -1 (bit 1)
_SIGN2 = 1.0 - 2.0 * np.array([[_parity(int(r) & G2) for r in row] for row in _REG])  # second output bit per path, as +1 or -1


_INPUT_BIT = np.arange(NSTATES) & 1  # the data bit that leads into each state (the newest bit of the register)


def viterbi_decode(llrs, known=None):  # soft coded bits -> best-guess data bits
    """Decode soft values (positive = probably 0, negative = probably 1).

    `known`, if given, holds one entry per data bit: 0 or 1 where that bit is
    known in advance (an expected callsign, say), -1 where it is not. Only
    paths that agree with the known bits are kept (since 0.31R1).
    """
    done = native.viterbi_decode(llrs, known)  # the compiled decoder, when the library is in use
    if done is not None:  # it was
        return done  # the same bits the Python below gives
    llrs = np.asarray(llrs, dtype=float)  # make sure we have floating-point numbers
    nsteps = len(llrs) // 2  # one decoding step per pair of coded bits
    metric = np.full(NSTATES, -1e18)  # score of the best path into each state (very low = impossible)
    metric[0] = 0.0  # the encoder always starts in state 0
    choices = np.zeros((nsteps, NSTATES), dtype=np.uint8)  # which of the two paths won, for every step and state
    for t in range(nsteps):  # move forward through the received bits
        cand = metric[_PRED] + _SIGN1 * llrs[2 * t] + _SIGN2 * llrs[2 * t + 1]  # score of both paths into every state
        pick = cand[1] > cand[0]  # true where the second path is the better one
        choices[t] = pick  # remember the winner so we can trace back later
        metric = np.where(pick, cand[1], cand[0])  # keep the better score for each state
        if known is not None and t < len(known) and known[t] >= 0:  # this data bit is known
            metric = np.where(_INPUT_BIT == known[t], metric, -1e18)  # paths that disagree with it are impossible
    state = 0  # the tail bits force the encoder to finish in state 0
    bits = np.zeros(nsteps, dtype=np.uint8)  # decoded bits, filled from the end backwards
    for t in range(nsteps - 1, -1, -1):  # walk back along the winning path
        bits[t] = state & 1  # the input bit that led into this state
        state = _PRED[choices[t, state], state]  # step back to the state we came from
    return bits[:nsteps - TAIL]  # drop the six tail bits
