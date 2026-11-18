"""Turning a text message into bits and back (7-bit ASCII, up to 200 characters)."""

import numpy as np  # numerical arrays

from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .params import CHAR_BITS, LENGTH_BITS, SIZE_CLASSES  # message format numbers


def pick_size_class(n_chars):  # choose the smallest frame that fits
    """Return the index of the smallest size class that holds `n_chars` characters."""
    for index, size in enumerate(SIZE_CLASSES):  # try 50, then 100, then 200
        if n_chars <= size:  # the message fits in this class
            return index  # so use it
    raise ValueError("message is longer than 200 characters")  # nothing fits: refuse


def text_to_bits(text, size_class):  # message -> body bits (without the CRC)
    """Return the length field followed by the characters, padded to the class size."""
    codes = [ord(ch) for ch in text]  # the number behind each character
    if any(code > 127 for code in codes):  # anything outside 7-bit ASCII...
        raise ValueError("message contains a character outside 7-bit ASCII")  # ...cannot be sent
    size = SIZE_CLASSES[size_class]  # how many characters this class holds
    if len(codes) > size:  # the message must fit the chosen class
        raise ValueError("message does not fit the chosen size class")  # refuse if it does not
    parts = [int_to_bits(len(codes), LENGTH_BITS)]  # start with the true character count
    parts += [int_to_bits(code, CHAR_BITS) for code in codes]  # then 7 bits per character
    parts.append(np.zeros((size - len(codes)) * CHAR_BITS, dtype=np.uint8))  # then zero padding up to the class size
    return np.concatenate(parts)  # one flat array of bits


def bits_to_text(bits):  # body bits (without the CRC) -> message
    """Return the message carried by `bits`, using the length field to drop the padding."""
    count = bits_to_int(bits[:LENGTH_BITS])  # read the true character count
    chars = []  # characters recovered so far
    for i in range(count):  # one pass per real character
        start = LENGTH_BITS + i * CHAR_BITS  # where this character's bits begin
        chars.append(chr(bits_to_int(bits[start:start + CHAR_BITS])))  # 7 bits -> number -> character
    return "".join(chars)  # glue the characters into the message
