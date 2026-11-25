"""Chained messages: a message of up to 1,000 characters sent as numbered pieces (since 0.42).

A frame carries at most 200 characters, so a longer message is cut into pieces at word boundaries, each
sent as an ordinary message that starts with "(k/n) " (piece k of n). The prefix is plain text, so anyone
monitoring reads the pieces in order, and a station on an older version simply shows them one by one; a 0.42
station puts them back together. Pieces go only on a working channel, never on the calling frequency
(the panel holds them until the contact is on one).
"""
import re  # reading the piece prefix

MOST = 1000  # the longest chained message, in characters typed
PIECE_MOST = 200  # the longest single message (one frame's worth of characters, modem.params.MAX_CHARS)
PREFIX = re.compile(r"^\(([1-9])/([2-9])\) ")  # "(k/n) ": piece k of n, at most 9 pieces


def needs_chain(text, most=PIECE_MOST):  # is this message too long for one message?
    """Return True when `text` is longer than one message can carry."""
    return len(text) > most  # more than one frame's worth


def split(text, most=PIECE_MOST):  # cut a long message into pieces
    """Return the pieces of `text`, each at most `most` characters including its "(k/n) " prefix.

    Cuts fall at spaces where possible (a word longer than a piece is cut where it must be). A message that
    fits one message is returned as it is, without a prefix.
    """
    text = text.strip()  # no blank ends
    if not needs_chain(text, most):  # it fits
        return [text]  # one ordinary message
    room = most - len("(9/9) ")  # characters of text each piece can carry after its prefix
    pieces, rest = [], text  # the pieces so far, and what is left to cut
    while rest:  # until nothing is left
        if len(rest) <= room:  # the rest fits one piece
            pieces.append(rest)  # the last piece
            break  # done
        cut = rest.rfind(" ", 0, room + 1)  # the last space that keeps the piece within its room
        if cut <= room // 2:  # no space in the second half: a very long word
            cut = room  # cut it where it must be
        pieces.append(rest[:cut].rstrip())  # this piece, without trailing spaces
        rest = rest[cut:].lstrip()  # carry on after the cut, without leading spaces
    if len(pieces) > 9:  # more pieces than the prefix can number
        raise ValueError("message too long to chain")  # refuse (cannot happen within 1,000 characters)
    return [f"({number}/{len(pieces)}) {piece}" for number, piece in enumerate(pieces, start=1)]  # each with its prefix


def parse(text):  # is this message a piece of a chain?
    """Return (k, n, body) for a piece "(k/n) body", or None for an ordinary message."""
    found = PREFIX.match(text or "")  # the prefix, if any
    if not found:  # none
        return None  # an ordinary message
    k, n = int(found.group(1)), int(found.group(2))  # which piece, of how many
    if k > n:  # nonsense
        return None  # treat it as ordinary text
    return k, n, text[found.end():]  # the piece


class Joiner:  # puts pieces back together, one chain at a time per sending station
    """Collects the pieces of chained messages by sender; says what has arrived so far, and the whole message once complete."""

    def __init__(self):  # nothing collected yet
        self.chains = {}  # sender -> {"n": number of pieces, "pieces": {k: body}}

    def feed(self, sender, text):  # one received message
        """Return (whole message or None, text so far, pieces held, pieces expected); (text, text, 1, 1) for an ordinary message."""
        found = parse(text)  # is it a piece?
        if found is None:  # an ordinary message
            return text, text, 1, 1  # complete as it is
        k, n, body = found  # which piece
        chain = self.chains.get(sender)  # the chain being collected from this sender
        if chain is None or chain["n"] != n or k in chain["pieces"] and chain["pieces"][k] != body:  # none yet, or a different chain has started
            chain = self.chains[sender] = {"n": n, "pieces": {}}  # start a new one
        chain["pieces"][k] = body  # keep this piece (a repeat replaces itself)
        held = len(chain["pieces"])  # how many are in hand
        so_far = " ".join(chain["pieces"].get(number, "[...]") for number in range(1, n + 1))  # the message so far, a gap marked where a piece is missing
        if held == n:  # every piece is here
            del self.chains[sender]  # finished
            return so_far, so_far, n, n  # the whole message
        return None, so_far, held, n  # not complete yet

    def waiting(self, sender):  # is a chain from this sender incomplete?
        """Return True while some pieces of a chain from `sender` are still expected."""
        return sender in self.chains  # one is being collected
