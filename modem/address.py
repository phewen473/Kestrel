"""Addresses: turning callsigns into bits and back, and the short link number two locked stations share.

A callsign (or a group name such as ALL) is up to 9 characters from a
40-symbol alphabet. Nine symbols of 40 choices fit in 48 bits, so every
address costs 48 bits on the air.
"""

import numpy as np  # numerical arrays

from .bits import bits_to_int, int_to_bits  # number <-> bits helpers
from .crc import crc16  # check-value calculator, reused to make the link number
from .params import CALL_BITS, CALL_CHARS, LINK_ID_BITS  # address format numbers

ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-"  # symbol values 0 to 38 (space, letters, digits, slash, dash); value 39 is unused
BASE = 40  # number of symbol values the coding allows for


def clean_call(call):  # tidy an address the way it will be sent
    """Return `call` in capitals without surrounding spaces, or raise ValueError when it cannot be sent."""
    call = call.strip().upper()  # addresses are sent in capitals, with no padding of their own
    if not 1 <= len(call) <= CALL_CHARS:  # empty or too long
        raise ValueError(f"an address must be 1 to {CALL_CHARS} characters")  # refuse it
    if " " in call or any(ch not in ALPHABET for ch in call):  # a space inside, or a character outside the alphabet
        raise ValueError("an address may hold only letters, digits, '/' and '-'")  # refuse it
    return call  # ready to encode


def call_to_bits(call):  # address -> 48 bits
    """Return the 48 bits that stand for the callsign or group name `call`."""
    call = clean_call(call).ljust(CALL_CHARS)  # pad on the right with spaces to 9 characters
    value = 0  # running total starts at zero
    for ch in call:  # first character first, so it carries the most weight
        value = value * BASE + ALPHABET.index(ch)  # shift what we have by one symbol and add the next
    return int_to_bits(value, CALL_BITS)  # the number as 48 bits, most significant first


def bits_to_call(bits):  # 48 bits -> address
    """Return the callsign or group name spelled by 48 address bits, or raise ValueError when they are not a valid address."""
    value = bits_to_int(bits)  # the bits as one number
    symbols = []  # the symbol values, last character first
    for _ in range(CALL_CHARS):  # peel off nine symbols
        value, symbol = divmod(value, BASE)  # the lowest symbol, and what is left
        symbols.append(symbol)  # keep it
    if value != 0 or any(s >= len(ALPHABET) for s in symbols):  # a number too big for nine symbols, or the unused symbol value
        raise ValueError("not a valid address")  # the bits were damaged or never an address
    return clean_call("".join(ALPHABET[s] for s in reversed(symbols)))  # back in reading order, padding removed (this also rejects spaces inside)


def is_group(call):  # callsign or group name?
    """Return True when `call` is a group or net name (it holds no digit) and False when it is a station callsign."""
    return not any(ch.isdigit() for ch in clean_call(call))  # every amateur callsign contains a digit; names such as ALL do not


def call_hash(call):  # the short code that stands for a callsign in a mail notice
    """Return a 16-bit code (1 to 65535) for `call`: the CRC-16 of its 48 address bits, with 0 kept to mean "empty"."""
    return bits_to_int(crc16(call_to_bits(call))) or 1  # never 0, which marks an unused entry


def message_hash(origin, msg_id):  # the short code that stands for a message ID in a mail notice
    """Return a 16-bit code (1 to 65535) for the message numbered `msg_id` by `origin`: the CRC-16 of the origin's 48 address bits followed by the 16-bit number."""
    from .bits import int_to_bits  # number -> bits
    return bits_to_int(crc16(np.concatenate([call_to_bits(origin), int_to_bits(msg_id, 16)]))) or 1  # never 0, which marks an unused entry


def link_id(first, second):  # the short number two locked stations put in every frame
    """Return the link number for the pair of stations: `first` is the one that beaconed, `second` the one that answered.

    It is the lowest 9 bits of the CRC-16 of the two addresses' 96 bits.
    The same pair always gets the same number, so nothing extra has to be
    agreed when the link is set up.
    """
    check = crc16(np.concatenate([call_to_bits(first), call_to_bits(second)]))  # 16 check bits over both addresses
    return bits_to_int(check) & ((1 << LINK_ID_BITS) - 1)  # keep the lowest 9 bits
