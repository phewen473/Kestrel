"""Text compression: common characters get short codes, rare ones get long codes (a fixed Huffman code).

The table below gives the code length, in bits, of each of the 128
ASCII characters. It was tuned for plain English mixed with callsigns
and numbers: a space costs 3 bits, "e" and "t" 4 bits, capitals and
digits 6 to 8 bits, rarely used characters up to 13 bits.

The codes themselves follow from the lengths by the standard "canonical"
rule, so the table of lengths is all another program needs: sort the
characters by (length, character number); the first gets code 0; each
next character gets the previous code plus one, shifted left whenever
the length grows.
"""

import numpy as np  # numerical arrays

LENGTHS = (  # code length in bits for character numbers 0 to 127
    13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 8, 13, 13, 13, 13, 13,  # 0-15: control characters (10 = new line)
    13, 13, 13, 13, 13, 13, 13, 13, 13, 12, 12, 12, 12, 12, 12, 12,  # 16-31: control characters
    3, 9, 11, 11, 11, 11, 11, 9, 11, 11, 11, 11, 8, 9, 7, 8,  # 32-47: space ! " # $ % & ' ( ) * + , - . /
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 9, 11, 11, 11, 11, 8,  # 48-63: digits 0-9 : ; < = > ?
    11, 6, 8, 7, 7, 6, 7, 7, 6, 6, 8, 8, 7, 7, 6, 6,  # 64-79: @ A-O
    7, 8, 7, 6, 6, 7, 8, 7, 8, 7, 8, 11, 11, 11, 11, 11,  # 80-95: P-Z [ \ ] ^ _
    11, 5, 7, 6, 5, 4, 6, 7, 5, 5, 10, 8, 6, 6, 5, 5,  # 96-111: ` a-o
    7, 11, 5, 5, 4, 6, 8, 6, 10, 7, 11, 11, 11, 11, 11, 12,  # 112-127: p-z { | } ~ DEL
)  # end of the table


def _build_codes():  # lengths -> actual codes
    """Return (code of each character, lookup from (length, code) back to the character)."""
    codes = [0] * 128  # the code number of each character
    lookup = {}  # (length, code) -> character number
    code = 0  # next code to hand out
    last_len = 0  # length of the previous code
    for length, symbol in sorted((LENGTHS[s], s) for s in range(128)):  # shortest codes first, then by character number
        code <<= length - last_len  # when the length grows, shift the running code left
        codes[symbol] = code  # this character's code
        lookup[(length, code)] = symbol  # remember how to decode it
        code += 1  # the next character gets the next code
        last_len = length  # remember this length
    return codes, lookup  # both tables


_CODES, _LOOKUP = _build_codes()  # built once when the module loads


def compressed_bits(text):  # how many bits the text needs when compressed
    """Return the number of bits `text` takes after compression."""
    return sum(LENGTHS[ord(ch)] for ch in text)  # add up each character's code length


def compress(text):  # text -> compressed bits
    """Return the compressed bits of `text` (7-bit ASCII only)."""
    out = []  # bits produced so far
    for ch in text:  # one character at a time
        symbol = ord(ch)  # its character number
        length = LENGTHS[symbol]  # its code length
        code = _CODES[symbol]  # its code
        out.extend((code >> (length - 1 - i)) & 1 for i in range(length))  # write the code, most significant bit first
    return np.array(out, dtype=np.uint8)  # as an array of bits


def decompress(bits, count):  # compressed bits -> text
    """Return the first `count` characters stored in `bits`."""
    chars = []  # characters recovered so far
    code = 0  # code being collected
    length = 0  # how many bits of it we have
    for b in bits:  # read one bit at a time
        if len(chars) == count:  # we already have every character
            break  # stop reading (the rest is padding)
        code = (code << 1) | int(b)  # add the bit to the code being collected
        length += 1  # one more bit
        symbol = _LOOKUP.get((length, code))  # is this a complete code?
        if symbol is not None:  # yes
            chars.append(chr(symbol))  # store its character
            code = 0  # start collecting the next code
            length = 0  # from nothing
    if len(chars) != count:  # the bits ran out before all characters were found
        raise ValueError("compressed text is incomplete")  # the frame is damaged
    return "".join(chars)  # glue the characters into the text
