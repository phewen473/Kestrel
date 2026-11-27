"""Tests: the answer frame and the directed call carry their sender's grid locator (signal version 0.33)."""
import numpy as np  # arrays
import pytest  # the test runner

from modem import build_answer, receive  # the modem
from modem.control import ChannelReport, pack_answer, unpack  # the answer's fields
from modem.params import CALL_BITS, CONTROL_BITS, FRAME_TYPE_ANSWER, GRID_BITS, NO_GRID  # its layout


def test_answer_carries_the_locator_and_none_when_unset():  # the field itself
    report = ChannelReport(-10.0, 0.25, 4.0, 2)  # any report
    for grid in ("EM93", "fn31", ""):  # a locator, one in small letters, and none
        bits = pack_answer("Q1AAAA", "Q2BB", report, (0, 1, 2), mail_check=True, directed=True, grid=grid)  # packed
        assert len(bits) == CONTROL_BITS[FRAME_TYPE_ANSWER] == 147  # the 0.44 length (139 from 0.33, before the report's age and noise reading)
        fields = unpack(FRAME_TYPE_ANSWER, bits)  # and back
        assert fields["grid"] == grid.upper() and fields["origin"] == "Q2BB" and fields["directed"] and fields["report"].want_level == 2  # everything survives


def test_damaged_locator_makes_the_answer_invalid():  # a value that is neither a locator nor "none"
    bits = pack_answer("Q1AAAA", "Q2BB", ChannelReport(), (0, ), grid="EM93").copy()  # a good answer
    place = slice(2 * CALL_BITS, 2 * CALL_BITS + GRID_BITS)  # its locator bits
    bits[place] = [int(b) for b in format(NO_GRID - 1, f"0{GRID_BITS}b")]  # a value above any locator, but not "none"
    with pytest.raises(ValueError):  # refused
        unpack(FRAME_TYPE_ANSWER, bits)  # as damage


def test_answer_and_directed_call_bring_the_locator_over_the_air():  # whole frames, through the receiver
    rng = np.random.default_rng(33)  # repeatable
    for directed in (False, True):  # an answer and a directed call
        audio = build_answer("Q1AAAA", "Q2BB", ChannelReport(-8.0, 0.0, 0.0, 2), level=2, directed=directed, grid="EM93")  # sent
        heard = receive(audio + 0.02 * rng.standard_normal(len(audio)), long_beacons=False)  # received
        assert heard.ok and heard.fields["grid"] == "EM93" and heard.fields["directed"] == directed  # the locator arrived


def test_stations_send_their_own_locator_in_answers_and_calls():  # the link rules fill it in
    from link.station import Station  # the link rules
    caller = Station("Q1AAAA", "EM93")  # a station that will call
    caller.listen()  # listening
    tx = caller.call_station("Q2BB")  # a directed call
    tx = tx if tx is not None else caller.poll(0.0)  # sent now or at the next look
    heard = receive(tx.audio, long_beacons=False)  # what goes out
    assert heard.ok and heard.fields["directed"] and heard.fields["grid"] == "EM93"  # with the caller's locator
