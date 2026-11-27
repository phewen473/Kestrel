"""Tests for the channel report's age and the reporting station's noise reading (signal version 0.44)."""

import numpy as np  # numerical arrays

from link import Path, run_link  # the simulated contact
from link import simulate  # its receiver step, watched below
from link.params import STALE_REPORT_S  # the age from which a report never raises the level
from link.station import PythonStation, Station  # the stations
from modem import ACK_LINK, ChannelReport, receive  # a status-3 acknowledgment, the report, and the plain receiver
from modem.params import FRAME_TYPE_ACK, FRAME_TYPE_ANSWER  # the frames that carry a report


def _heard(audio):  # a frame through a clean path
    """Return the plain receiver's report on `audio`, with a little quiet either side."""
    return receive(np.concatenate([np.zeros(6000), audio, np.zeros(6000)]))  # decoded


def test_acknowledgment_says_how_old_its_report_is():  # the age a station puts in its report
    """A report made 190 s after the partner was last heard is sent as age code 2 (2 to 4 minutes) and carries this station's noise."""
    s = PythonStation("Q1AAAA", "EM92")  # a station
    s.link, s.allowed, s.want, s.tx_level, s.bursts = 99, [0, 1, 2], 1, 2, False  # as if locked, acknowledging with frames
    partner = PythonStation("Q2BB", "FN31")  # the partner
    partner.link, partner.bursts = 99, False  # in the same contact, sending frames
    first = _heard(partner._ack(0.0, 0, 0, ACK_LINK, "ack").audio)  # any frame from the partner, for its measurements
    s.clock_now = 10.0  # it was heard at 10 s
    s._fresh_start(first)  # taken in
    assert s.heard_time == 10.0  # stamped
    s.noise_db = -30.0  # this station's S-meter noise reading
    got = _heard(s._ack(200.0, 0, 0, ACK_LINK, "ack").audio)  # the acknowledgment frame it sends at 200 s
    report = got.fields["report"]  # the report it carries
    assert got.ok and got.frame_type == FRAME_TYPE_ACK  # read
    assert report.age_s == 120.0 and report.noise_db == -30.0  # code 2 (read as 2 minutes), and the noise
    assert s._report_of(first).age_s == 0.0  # a report on a frame just heard says so


def test_old_report_never_raises_the_level():  # the rule that uses the age
    """A report 4 minutes old or more may lower the sending level but not raise it; a fresh one, or one that does not say, may do either."""
    s = PythonStation("Q1AAAA", "EM92")  # a station
    s.tx_level = 1  # sending at L1
    assert s._trusted_want(ChannelReport(-5.0, 0.0, 0.0, 3, STALE_REPORT_S)) == 1  # old: no climb
    assert s._trusted_want(ChannelReport(-5.0, 0.0, 0.0, 0, STALE_REPORT_S)) == 0  # old: a drop is still taken
    assert s._trusted_want(ChannelReport(-5.0, 0.0, 0.0, 3, 120.0)) == 3  # fresh: climb
    assert s._trusted_want(ChannelReport(-5.0, 0.0, 0.0, 3)) == 3  # age not said: as before 0.44


def test_directed_call_report_is_aged():  # a call carries how the called station was last heard
    """A directed call's report is the last reading of the called station, with how long ago it was made and this station's noise."""
    s = PythonStation("Q1AAAA", "EM92")  # a station
    s.noise_db = -24.0  # its noise reading
    s.heard_at["Q2BB"] = (100.0, ChannelReport(-8.0, 0.1, 1.0, 2))  # Q2BB heard at 100 s
    s.call_station("Q2BB")  # call it
    tx = s.poll(250.0)  # 150 s later
    got = _heard(tx.audio)  # what goes out
    assert got.ok and got.frame_type == FRAME_TYPE_ANSWER and got.fields["directed"]  # a directed call
    assert got.fields["report"].age_s == 120.0 and got.fields["report"].noise_db == -24.0  # 2 to 4 minutes old, with the noise


def test_both_stations_send_aged_reports(monkeypatch):  # the compiled station as well as the reference
    """In a whole contact every report heard says it is fresh and carries the sender's noise, from the Python and the compiled station alike."""
    for make in (PythonStation, Station):  # the reference, and the compiled station when the library is in use
        seen = []  # every report heard
        original = simulate.hear_reply  # the simulator's receiver step

        def watch(receiver, audio, *rest):  # the same, noting each report
            result = original(receiver, audio, *rest)  # heard
            if result.ok and not getattr(result, "burst", False) and result.frame_type in (FRAME_TYPE_ACK, FRAME_TYPE_ANSWER):  # a frame with a report
                seen.append(result.fields["report"])  # kept
            return result  # unchanged

        monkeypatch.setattr(simulate, "hear_reply", watch)  # watched
        a, b = make("Q1AAAA", "EM92"), make("Q2BB", "FN31")  # two stations
        a.bursts = b.bursts = False  # acknowledgment frames, so every acknowledgment carries a report
        a.noise_db, b.noise_db = -30.0, -18.0  # their noise readings
        a.beacon()  # A calls
        b.listen()  # B answers
        a.queue("FIRST MESSAGE FROM A")  # traffic
        run_link(a, b, Path(-3.0, "awgn"), Path(-3.0, "awgn"), seed=2)  # a clean contact (noise, no fading)
        monkeypatch.setattr(simulate, "hear_reply", original)  # back as it was, for the next station type
        assert b.inbox == ["FIRST MESSAGE FROM A"]  # delivered
        assert seen and all(report.age_s == 0.0 for report in seen)  # every report fresh
        assert {report.noise_db for report in seen} == {-30.0, -18.0}  # each station's own noise
