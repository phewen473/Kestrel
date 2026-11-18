"""Small helpers for turning whole numbers into bits and back."""

import numpy as np  # numerical arrays


def int_to_bits(value, width):  # number -> array of bits
    """Return `value` as `width` bits, most significant bit first."""
    return np.array([(value >> (width - 1 - i)) & 1 for i in range(width)], dtype=np.uint8)  # peel bits off from the top down


def bits_to_int(bits):  # array of bits -> number
    """Return the whole number spelled by `bits`, most significant bit first."""
    value = 0  # running total starts at zero
    for b in bits:  # walk the bits from the top down
        value = (value << 1) | int(b)  # shift what we have left and add the next bit
    return value  # the finished number
