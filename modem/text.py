"""Turning a text message into bits and back (7-bit ASCII, up to 200 characters).

A frame's body has room for 350, 700, 1050 or 1400 text bits (the four size
classes). Text can be stored plain, at 7 bits per character, or
compressed. Compression is used only when it lets the text fit a smaller
size class, because that is the only time it shortens the transmission.
"""

import numpy as np  # numerical arrays

from . import native  # the compiled library, when it is in use
from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .compress import compress, compressed_bits, decompress  # text compression
from .params import ADDRESS_BITS, CHAR_BITS, FRAME_TYPE_LINK, LENGTH_BITS, MAX_CHARS, SIZE_CLASSES  # message format numbers


def capacity_bits(size_class, frame_type=FRAME_TYPE_LINK):  # how many text bits a frame holds
    """Return the number of text bits a frame of this size class and kind can carry.

    A link frame holds 350, 700, 1050 or 1400 text bits. A fully
    addressed frame holds 92 fewer, because its address block is 92 bits longer.
    """
    return CHAR_BITS * SIZE_CLASSES[size_class] - (ADDRESS_BITS[frame_type] - ADDRESS_BITS[FRAME_TYPE_LINK])  # text room, less the extra address bits


def _class_for(nbits, frame_type):  # smallest size class with room for nbits
    """Return the index of the smallest size class holding `nbits` text bits, or None if none does."""
    for index in range(len(SIZE_CLASSES)):  # try the classes from smallest to largest
        if nbits <= capacity_bits(index, frame_type):  # the bits fit in this class
            return index  # so use it
    return None  # too big for any class


def _check(text):  # refuse text that cannot be sent
    """Raise ValueError unless `text` is 7-bit ASCII and at most 200 characters."""
    if len(text) > MAX_CHARS:  # too long
        raise ValueError("message is longer than 200 characters")  # refuse
    if any(ord(ch) > 127 for ch in text):  # anything outside 7-bit ASCII
        raise ValueError("message contains a character outside 7-bit ASCII")  # refuse


def choose_packing(text, frame_type=FRAME_TYPE_LINK):  # decide the size class and whether to compress
    """Return (size class, compressed?) for `text`, or raise ValueError when it does not fit one frame."""
    done = native.choose_packing(text, frame_type)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same choice
    _check(text)  # make sure the text can be sent at all
    plain = _class_for(CHAR_BITS * len(text), frame_type)  # size class needed without compression (None if too big)
    small = _class_for(compressed_bits(text), frame_type)  # size class needed with compression (None if too big)
    if small is not None and (plain is None or small < plain):  # compression gets the text into a smaller frame, or into a frame at all
        return small, True  # so compress
    if plain is None:  # too big either way (only possible in a fully addressed frame)
        raise ValueError("message does not fit one frame; split it into parts")  # the planner splits such messages
    return plain, False  # otherwise send it plain


def pick_size_class(text, frame_type=FRAME_TYPE_LINK):  # the smallest frame that fits the text
    """Return the index of the size class `text` will be sent in."""
    return choose_packing(text, frame_type)[0]  # only the class is wanted


def fits(text, size_class, frame_type=FRAME_TYPE_LINK):  # would this text fit in this size class?
    """Return True when `text` fits `size_class`, plain or compressed."""
    return min(CHAR_BITS * len(text), compressed_bits(text)) <= capacity_bits(size_class, frame_type)  # the smaller of the two forms must fit


def text_to_bits(text, size_class, compressed, frame_type=FRAME_TYPE_LINK):  # text -> body bits (without the address block and check value)
    """Return the character count followed by the text bits, padded to the size class."""
    done = native.text_to_bits(text, size_class, compressed, frame_type)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same bits
    _check(text)  # make sure the text can be sent at all
    payload = compress(text) if compressed else np.concatenate([int_to_bits(ord(ch), CHAR_BITS) for ch in text] + [np.zeros(0, dtype=np.uint8)])  # the text as bits, in the chosen form
    room = capacity_bits(size_class, frame_type)  # how many text bits the frame holds
    if len(payload) > room:  # the text must fit the chosen class
        raise ValueError("message does not fit the chosen size class")  # refuse if it does not
    return np.concatenate([int_to_bits(len(text), LENGTH_BITS), payload, np.zeros(room - len(payload), dtype=np.uint8)])  # count, text bits, zero padding


def bits_to_text(bits, compressed):  # body bits (without the check value) -> text
    """Return the text carried by `bits`, using the character count to drop the padding."""
    done = native.bits_to_text(bits, compressed)  # compiled, when the library is in use
    if done is not None:  # it was
        return done  # the same text
    count = bits_to_int(bits[:LENGTH_BITS])  # read the true character count
    payload = bits[LENGTH_BITS:]  # the text bits follow the count
    if compressed:  # the text was compressed
        return decompress(payload, count)  # undo the compression
    if count * CHAR_BITS > len(payload):  # the count claims more characters than there is room for
        raise ValueError("character count is too large")  # the frame is damaged
    return "".join(chr(bits_to_int(payload[i * CHAR_BITS:(i + 1) * CHAR_BITS])) for i in range(count))  # 7 bits -> number -> character, for each character
