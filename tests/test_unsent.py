"""Tests: messages a run took are given back to the queue however the run ended (since 0.40R2)."""
import os  # paths
import sys  # the import path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))  # the panel lives in tools/

from kestrel_panel import unsent_messages  # what is tested  # noqa: E402


class _Holder:  # a stand-in station with messages still in its outbox
    outbox = ["HELLO BOB", "QSL 73"]  # two unsent messages
    outbox_to = ["Q2BB", None]  # one for a named station, one for whoever the partner is


def test_run_failed_before_it_had_a_station():  # the case seen on the air: rig control would not start
    job = {"messages": [("HELLO BOB", "Q2BB")]}  # the run took the queue, then failed
    assert unsent_messages(job) == [("HELLO BOB", "Q2BB")]  # given back
    assert unsent_messages(job) == []  # and only once


def test_run_stopped_with_a_problem_while_the_station_held_them():  # a fault in mid-run
    job = {"messages": [], "holder": _Holder()}  # the station had them
    assert unsent_messages(job) == [("HELLO BOB", "Q2BB"), ("QSL 73", "")]  # taken back from it, addresses kept
    assert job["holder"] is None and unsent_messages(job) == []  # once


def test_normal_end_gives_nothing_twice():  # the run took its messages back itself
    assert unsent_messages({"messages": [], "holder": None}) == []  # nothing more to give


class _Broken:  # a stand-in station that cannot say what it holds
    @property  # read like the real attribute
    def outbox(self):  # asking for its messages
        raise RuntimeError("station gone")  # fails


def test_a_station_that_cannot_answer_is_reported_not_hidden():  # since 0.40R3
    said = []  # what was reported
    job = {"messages": [("STILL HERE", "")], "holder": _Broken()}  # one message never handed over, and a broken station
    assert unsent_messages(job, said.append) == [("STILL HERE", "")]  # what can be given back is
    assert len(said) == 1 and "could not be recovered" in said[0]  # and the loss is said, once
