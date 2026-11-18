"""Cyclic redundancy checks (CRCs): short check values that reveal damaged data."""

from .bits import int_to_bits  # helper that turns the check value into bits


def crc_bits(bits, poly, width, init):  # general bit-by-bit CRC
    """Return the CRC of `bits` as `width` bits, most significant bit first."""
    mask = (1 << width) - 1  # keeps the register to `width` bits
    reg = init  # the CRC register starts at its preset value
    for b in bits:  # feed the data in one bit at a time
        top = (reg >> (width - 1)) & 1  # the bit about to fall off the top
        reg = (reg << 1) & mask  # shift the register left by one
        if top ^ int(b):  # when the top bit and the data bit differ...
            reg ^= poly  # ...mix in the generator polynomial
    return int_to_bits(reg, width)  # hand the register back as bits


def crc16(bits):  # the body check
    """CRC-16/CCITT-FALSE (polynomial 0x1021, start value 0xFFFF)."""
    return crc_bits(bits, 0x1021, 16, 0xFFFF)  # standard, widely documented CRC


def crc8(bits):  # the header check
    """CRC-8 (polynomial 0x07, start value 0x00)."""
    return crc_bits(bits, 0x07, 8, 0x00)  # standard, widely documented CRC
