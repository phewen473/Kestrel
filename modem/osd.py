"""Ordered-statistics decoding (OSD): a last try for a message body the LDPC decoder could not correct (since 0.43).

The LDPC decoder passes messages around the code's checks and sometimes gives
up on a body that is still close to a codeword. OSD looks at it another way:
take the k bits the receiver is surest of (that are independent of each
other), believe them, and work out the whole codeword from them; then try
each of those k bits flipped in turn ("order 1") and keep the codeword that
disagrees least, weighted by confidence, with what was received.

It always returns a codeword, right or wrong, so the frame's CRC-16 decides:
a wrong codeword passes that check about once in 65,536 tries. It runs only on
message bodies that failed, after the other tries.

Measured (study of November 26, 2026, 100 L0 frames a point, real band noise):
+0 to +4 frames per 100 near the limit, in every fading rate tried.
"""

from functools import lru_cache  # build each generator once

import numpy as np  # numerical arrays

from .ldpc import info_checks  # the code's wiring


@lru_cache(maxsize=8)  # one per code size in use
def generator(k):  # the code's generator matrix
    """Return the (k, 2k) generator matrix of the k-bit code as 0/1 bytes: row j is the codeword of data bit j alone.

    The code is systematic (data bits first), and its parity bit i is the XOR of
    checks 0..i, so data bit j's parity row is 1 from each of its checks onward,
    toggled again at each further check.
    """
    rows = info_checks(k)  # the three checks each data bit joins
    marks = np.zeros((k, k), dtype=np.uint8)  # 1 where data bit j feeds check i (mod 2)
    for t in range(rows.shape[0]):  # each of the three shuffles
        np.bitwise_xor.at(marks, (np.arange(k), rows[t]), 1)  # data bit j joins check rows[t][j]
    parity = np.bitwise_xor.accumulate(marks, axis=1)  # parity bit i = XOR of checks 0..i
    return np.concatenate([np.eye(k, dtype=np.uint8), parity], axis=1)  # data, then parity


def decode(llrs, k):  # the last try
    """Return the k data bits of the order-1 OSD codeword nearest the soft bits `llrs` (2k values, positive = probably 0)."""
    llrs = np.asarray(llrs, dtype=float)  # soft bits
    n = 2 * k  # codeword length
    order = np.argsort(-np.abs(llrs), kind="stable")  # positions from surest to least sure
    g = generator(k)[:, order]  # the generator, columns in that order
    packed = np.packbits(g, axis=1)  # rows as bytes (eight columns a byte), for fast row sums
    pivots = []  # the surest independent positions (in sorted order)
    row = 0  # rows settled so far
    for col in range(n):  # surest first
        if row == k:  # all k found
            break  # done
        byte, bit = col >> 3, np.uint8(0x80 >> (col & 7))  # where this column sits in a packed row
        hits = np.flatnonzero(packed[row:, byte] & bit)  # unsettled rows with a 1 in this column
        if len(hits) == 0:  # this position depends on the ones already chosen
            continue  # skip it
        r = row + int(hits[0])  # the pivot row
        if r != row:  # bring it up
            packed[[row, r]] = packed[[r, row]]  # swap
        others = np.flatnonzero(packed[:, byte] & bit)  # every row with a 1 here
        others = others[others != row]  # except the pivot itself
        packed[others] ^= packed[row]  # clear the column everywhere else
        pivots.append(col)  # remember it
        row += 1  # next row
    reduced = np.unpackbits(packed, axis=1)[:, :n].astype(bool)  # rows now an identity on the pivot columns
    hard = llrs[order] < 0  # what was received, in sorted order (True = 1)
    weight = np.abs(llrs[order])  # how much each disagreement costs
    base = np.bitwise_xor.reduce(reduced[hard[pivots]], axis=0) if hard[pivots].any() else np.zeros(n, dtype=bool)  # the codeword the surest bits give as received
    agree = np.where(base == hard, 1.0, -1.0) * weight  # flipping a position here costs +w where base agrees, saves w where it does not
    change = reduced.astype(float) @ agree  # cost change for flipping each pivot bit (order 1)
    best = int(np.argmin(change))  # the best single flip
    word = base ^ reduced[best] if change[best] < 0 else base  # keep it only if it gets nearer
    natural = np.empty(n, dtype=bool)  # back in the code's own order
    natural[order] = word  # unsorted
    return natural[:k].astype(np.uint8)  # the data bits (the code is systematic)
