"""Tests for chained messages (live/chain.py, since 0.42), including a 1,000-character message through a simulated contact."""
from link import Path, Station, run_link  # two simulated stations
from live import chain  # the module tested

LONG = ("Good evening from South Carolina. The band has been up and down tonight, with deep fades every minute or so, "  # a long, ordinary message
        "but the long beacons came through all night. Antenna is the same inverted vee at thirty feet. ") * 5  # about 1,000 characters


def test_short_message_is_not_chained():  # 200 characters or fewer go as they are
    assert chain.split("Hello there") == ["Hello there"]  # unchanged
    assert chain.split("x" * 200) == ["x" * 200]  # exactly one frame's worth


def test_long_message_cut_at_spaces_with_prefixes():  # the pieces
    text = LONG[:1000].strip()  # the message
    pieces = chain.split(text)  # cut up
    assert 5 <= len(pieces) <= 6 and all(len(piece) <= 200 for piece in pieces)  # each fits one message
    assert all(piece.startswith(f"({k}/{len(pieces)}) ") for k, piece in enumerate(pieces, start=1))  # numbered
    bodies = [chain.parse(piece)[2] for piece in pieces]  # the text of each piece
    assert " ".join(bodies) == " ".join(text.split())  # nothing lost but the spaces at the cuts
    assert all(not body.startswith(" ") and not body.endswith(" ") for body in bodies)  # cut at spaces


def test_word_longer_than_a_piece_is_cut_where_it_must_be():  # no space to cut at
    pieces = chain.split("y" * 450)  # one long "word"
    assert all(len(piece) <= 200 for piece in pieces) and "".join(chain.parse(p)[2] for p in pieces) == "y" * 450  # cut, nothing lost


def test_joiner_in_order_out_of_order_and_with_a_gap():  # putting it back together
    pieces = chain.split(LONG[:1000])  # the pieces
    joiner = chain.Joiner()  # the receiver's side
    whole = None  # nothing yet
    for piece in reversed(pieces):  # last piece first
        whole, so_far, held, expected = joiner.feed("N0ABC", piece)  # one piece
    assert whole == " ".join(chain.parse(p)[2] for p in pieces) and held == expected  # complete
    joiner.feed("N0ABC", pieces[0])  # a new chain begins
    whole, so_far, held, expected = joiner.feed("N0ABC", pieces[2])  # piece 3, with 2 missing
    assert whole is None and "[...]" in so_far and (held, expected) == (2, len(pieces)) and joiner.waiting("N0ABC")  # incomplete, gap shown
    assert joiner.feed("N0DEF", "plain text") == ("plain text", "plain text", 1, 1)  # an ordinary message passes straight through


def test_odd_prefixes_are_ordinary_text():  # not a piece
    assert chain.parse("(3/2) nonsense") is None and chain.parse("(1/1) one") is None and chain.parse("no prefix") is None  # all ordinary


def test_a_1000_character_message_crosses_a_simulated_contact():  # end to end, through the link layer and the HF simulator
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.beacon()  # A calls
    b.listen()  # B listens
    pieces = chain.split(LONG[:1000])  # the chained message
    for piece in pieces:  # each piece
        a.queue(piece)  # queued in order
    run_link(a, b, Path(0.0), Path(0.0), seed=3)  # a steady path at 0 dB
    joiner = chain.Joiner()  # B's side of the chain
    results = [joiner.feed("Q1AAAA", text) for text in b.inbox]  # every message B received
    assert results[-1][0] == " ".join(chain.parse(p)[2] for p in pieces)  # the whole message arrived, in one piece
