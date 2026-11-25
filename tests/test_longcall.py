"""The long call-up (signal version 0.41): calling, answering and "not available" in long frames, and what the live loop does with it."""
import numpy as np  # arrays
import pytest  # the test runner

from modem import longbeacon, longnote  # the frames
from modem.frame import RxResult  # a receiver's report
from modem.params import FS, REF_BANDWIDTH_HZ  # sample rate, SNR bandwidth


def _noise_for(audio, snr_db, rng):  # the frame in noise at `snr_db` (in 2.5 kHz)
    power = np.mean(audio ** 2)  # signal power
    noise = power / (10 ** (snr_db / 10)) / (REF_BANDWIDTH_HZ / (FS / 2))  # noise power over the whole band for that SNR in 2.5 kHz
    pad = int(2 * FS)  # two seconds of noise either side
    x = np.concatenate([np.zeros(pad), audio, np.zeros(pad)])  # the frame, with room around it
    return x + rng.normal(0.0, np.sqrt(noise), len(x))  # plus noise


def _read(x):  # decode the best long candidate in `x`
    for found in longbeacon.candidates(longbeacon.clean(x)):  # the long pattern's candidates
        result = longbeacon.decode_at(longbeacon.clean(x), found, RxResult(start=found["start"]), failed=[])  # try it
        if result.ok:  # decoded
            return result  # done
    return None  # nothing


def test_callup_fields_round_trip():  # packing and unpacking each phase
    for phase in longnote.PHASES:  # call, answer, away
        for traffic in (False, True):  # with and without a message waiting
            bits = longnote.pack_callup("Q1AAAA", "Q2BB", phase, traffic)  # packed
            assert len(bits) == longnote.FIELD_BITS  # 65 bits, like every note frame
            assert longnote.unpack(bits) == {"note": "callup", "origin": "Q1AAAA", "dest_code": longnote.code_for("Q2BB"), "phase": phase, "traffic": traffic, "long": True}  # every field back
    bad = longnote.pack_callup("Q1AAAA", "Q2BB", "call")  # a call...
    bad[62:64] = 1  # ...with phase 3, which is not sent
    with pytest.raises(ValueError):  # read as noise
        longnote.unpack(bad)  # refused
    with pytest.raises(ValueError):  # a call-up names one station
        longnote.pack_callup("Q1AAAA", "ALL", "call")  # refused


def test_long_call_decodes_weak():  # over the air, as weak as a long beacon
    rng = np.random.default_rng(41)  # repeatable
    audio = longnote.build_callup("Q1AAAA", "Q2BB", "call", True)  # a call with traffic waiting
    assert abs(len(audio) / FS - longbeacon.SECONDS) < 0.1  # about a minute, like the long beacon
    result = _read(_noise_for(audio, -22.0, rng))  # at -22 dB, far below what any short level reads on a fading path
    assert result is not None and result.fields["note"] == "callup" and result.fields["phase"] == "call" and result.fields["traffic"] and result.fields["origin"] == "Q1AAAA"  # read, as a call


def test_long_call_answer_and_lock():  # the exchange, without audio
    from live.notes import LONG_CALL_TRIES, LongNotes  # the note logic
    caller, called = LongNotes("Q1AAAA"), LongNotes("Q2BB")  # two stations
    caller.long_call("Q2BB", 0.0, traffic=True)  # short calls failed; call with long frames
    assert caller.due(0.0) == "note" and caller.busy()  # it waits for a clear frequency, as a note does
    frames, what = caller.next_frames(0.0)  # the call
    assert len(frames) == 1 and frames[0].kind == "long call" and what[0] == "call"  # one long frame
    caller.sent(what, 60.0)  # it has gone
    assert caller.due(61.0) is None  # now waiting for the answer
    called.heard(longnote.unpack(longnote.pack_callup("Q1AAAA", "Q2BB", "call", True)), 62.0)  # the called station reads it
    assert called.due(62.0) == "receipt"  # an answer goes at once, without waiting for a clear frequency
    frames, _ = called.next_frames(63.0)  # the answer
    assert frames[0].kind == "long call-up" and called.partner == "Q1AAAA"  # sent, and the called station's side of the contact is made
    assert ("locked", "Q1AAAA", False) in called.events  # so its waiting messages for the caller can go as long notes
    called.heard(longnote.unpack(longnote.pack_callup("Q1AAAA", "Q2BB", "call", True)), 70.0)  # the same call read again (two copies)
    assert called.due(70.0) is None  # answered once only
    caller.heard(longnote.unpack(longnote.pack_callup("Q2BB", "Q1AAAA", "answer")), 125.0)  # the caller reads the answer
    assert caller.calling is None and caller.partner == "Q2BB" and ("locked", "Q2BB", True) in caller.events  # the long contact is made
    assert LONG_CALL_TRIES >= 2  # a lost call or answer gets another try


def test_long_call_retries_then_gives_up_and_away_stops_it():  # no answer, and an operator who is away
    from live.notes import ANSWER_WAIT_S, LONG_CALL_TRIES, LongNotes  # the note logic
    caller = LongNotes("Q1AAAA")  # the calling station
    caller.long_call("Q2BB", 0.0)  # call
    clock = 0.0  # the time
    for _ in range(LONG_CALL_TRIES):  # every try
        frames, what = caller.next_frames(clock)  # the call
        assert frames  # sent
        caller.sent(what, clock + 60.0)  # gone
        clock += 60.0 + ANSWER_WAIT_S + 1.0  # no answer in time
        caller.tick(clock)  # the wait runs out
    assert caller.calling is None and any(e[0] == "link" and "NO CONTACT" in e[2] for e in caller.events)  # given up, and the operator told
    away = LongNotes("Q2BB")  # a station whose operator is away
    away.available = False  # marked unavailable
    away.heard(longnote.unpack(longnote.pack_callup("Q1AAAA", "Q2BB", "call")), 1.0)  # called
    frames, _ = away.next_frames(2.0)  # its reply
    assert away.partner is None and longnote.unpack(longnote.pack_callup("Q2BB", "Q1AAAA", "away"))["phase"] == "away" and frames  # "not available", and no contact
    caller.long_call("Q2BB", 10.0)  # call again
    caller.heard(longnote.unpack(longnote.pack_callup("Q2BB", "Q1AAAA", "away")), 20.0)  # told the operator is away
    assert caller.calling is None and caller.partner is None  # stops calling


def test_long_heard_and_contact_lapse():  # who is worth a long call, and how long a long contact lasts
    from live.notes import LONG_CONTACT_S, LONG_HEARD_S, LongNotes  # the note logic
    notes = LongNotes("Q1AAAA")  # this station
    notes.saw("Q2BB", 100.0)  # heard in a long beacon
    assert notes.heard_recently("Q2BB", 100.0 + LONG_HEARD_S) and not notes.heard_recently("Q2BB", 101.0 + LONG_HEARD_S) and not notes.heard_recently("Q3CCC", 100.0)  # for an hour, and only that station
    notes._lock("Q2BB", 200.0, False)  # a long contact
    notes.saw("Q2BB", 500.0)  # more long frames from the partner keep it going
    assert notes.in_contact(500.0 + LONG_CONTACT_S) == "Q2BB" and notes.in_contact(501.0 + LONG_CONTACT_S) is None  # until it has been quiet too long


def test_note_pieces():  # a waiting message cut into long notes
    from live.notes import note_pieces  # the cutter
    assert note_pieces("gm hank, 73 de pat") == ["GM HANK, 73 DE PAT"]  # capitals
    assert note_pieces("temp {20C}") == ["TEMP ?20C?"]  # characters a note cannot carry become '?'
    pieces = note_pieces("X" * 150)  # longer than one note
    assert [len(p) for p in pieces] == [64, 64, 22]  # 64 characters a note
    assert note_pieces("   ") == []  # nothing to send


class _Stand:  # stands in for the station, as the runner's helpers see it
    def __init__(self, **values):  # the attributes the helpers read
        self.__dict__.update(values)  # as given
        self.taken = []  # messages unqueued

    def unqueue(self, text, to=None):  # take a message back
        self.taken.append((text, to))  # remembered
        return True  # it was there


def test_runner_helpers():  # stopping short calls early, and handing messages over
    from live.notes import LongNotes  # the note logic
    from live.runner import hand_to_notes, has_traffic_for, short_calls_failing  # the helpers under test
    notes = LongNotes("Q1AAAA")  # this station's long notes
    calling = dict(role="caller", pending="confirm", calls=2, deadline=50.0, target="Q2BB", broadcasts=[], long_waiting=None, outbox=[], outbox_to=[])  # two calls made, the last one's wait over at 50 s
    assert short_calls_failing(_Stand(**calling), notes, 60.0) is None  # Q2BB not heard in long frames: the short calls run their course
    notes.saw("Q2BB", 10.0)  # now it has been
    assert short_calls_failing(_Stand(**calling), notes, 40.0) is None  # still waiting for the last reply
    assert short_calls_failing(_Stand(**calling), notes, 60.0) == "Q2BB"  # give way to a long call
    assert short_calls_failing(_Stand(**dict(calling, calls=1)), notes, 60.0) is None  # only one call so far
    assert short_calls_failing(_Stand(**dict(calling, broadcasts=[("b", 0, "")])), notes, 60.0) is None  # a broadcast waits: stopping would drop it
    station = _Stand(outbox=["hello there", "for someone else", "anyone"], outbox_to=["Q2BB", "Q3CCC", None])  # three waiting messages
    assert has_traffic_for(station, "Q2BB") and has_traffic_for(_Stand(outbox_to=[None]), "Q9ZZ") and not has_traffic_for(_Stand(outbox_to=["Q3CCC"]), "Q2BB")  # for it, for anyone, or not
    events = hand_to_notes(station, notes, "Q2BB", 100.0)  # a long contact with Q2BB
    assert [e[3] for e in events] == ["hello there", "anyone"] and station.taken == [("hello there", "Q2BB"), ("anyone", None)]  # its messages and the unaddressed one, not the other station's
    assert [(n.dest, n.text) for n in notes.outgoing] == [("Q2BB", "HELLO THERE"), ("Q2BB", "ANYONE")]  # now long notes to the partner
