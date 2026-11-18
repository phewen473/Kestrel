"""Tests of the link layer: two simulated stations making, running and closing a contact."""

from link import Path, Station, run_group, run_link, supported_level, wanted_level  # the link layer and its simulations
from link.params import OFFER_PROBE  # the "are you still there?" code

ENGLISH = "Good morning from South Carolina. Weather here is clear and 52 degrees with a light wind from the north. How do you copy this evening?"  # an ordinary message
ODD = "".join(chr(33 + (37 * i) % 94) for i in range(200))  # 200 characters that do not compress


def contact(path_ab, path_ba, from_a, from_b, seed=1):  # run one contact
    """Return (station A, station B, events) after A beacons, B answers, and both send their messages."""
    a = Station("KO4WSC", "EM92")  # the station that calls
    b = Station("W1AW", "FN31")  # the station that answers
    a.beacon()  # A beacons
    b.listen()  # B listens
    for text in from_a:  # A's traffic
        a.queue(text)  # into A's outbox
    for text in from_b:  # B's traffic
        b.queue(text)  # into B's outbox
    return a, b, run_link(a, b, path_ab, path_ba, seed=seed)  # run it


def test_level_requests_follow_the_measurements():  # the speed adaptation rule on its own
    allowed = [0, 1, 2, 3, 4]  # every level available
    strong = [(5.0, 0.0)] * 3  # three strong, steady frames
    weak = [(-13.5, 0.0)] * 3  # three weak, steady frames
    assert supported_level(strong, allowed) == 4 and supported_level(weak, allowed) == 1  # the fastest level each supports
    assert supported_level([(5.0, 0.0), (5.0, 0.0), (-13.5, 0.0)], allowed) == 1  # the weakest recent frame decides
    assert supported_level([(-5.0, 0.8)] * 3, allowed) < supported_level([(-5.0, 0.0)] * 3, allowed)  # fading asks for a slower level
    assert wanted_level(weak, 4, 5, False, allowed) == 1  # conditions slipped: drop at once
    assert wanted_level(strong, 0, 1, False, allowed) == 0  # better conditions, but only one clean frame: stay
    assert wanted_level(strong, 0, 2, False, allowed) == 2  # two clean frames: climb, two levels at most
    assert wanted_level(strong, 3, 2, False, allowed) == 4  # never past what is supported
    assert wanted_level(strong, 3, 9, True, allowed) == 2  # a failed frame: one level down, whatever the readings say
    assert wanted_level(strong, 0, 9, True, allowed) == 0  # and never below the slowest
    assert supported_level(strong, [0, 2]) == 2  # only levels both stations have are ever asked for


def test_contact_on_a_lopsided_path():  # B hears A well; A hears B poorly
    a, b, events = contact(Path(3.0, offset_hz=7.0), Path(-11.0, offset_hz=-4.0), [ENGLISH, "QSL?"], [ENGLISH])  # +3 dB one way, -11 dB the other
    assert b.inbox == [ENGLISH, "QSL?"] and a.inbox == [ENGLISH]  # every message arrived, in order, exactly once
    assert a.delivered == [ENGLISH, "QSL?"] and b.delivered == [ENGLISH]  # and each sender knows it
    assert a.state == "RELEASED" and b.state == "RELEASED"  # the contact was closed properly
    kinds = [e["kind"] for e in events]  # the sequence of frames
    assert kinds[:3] == ["beacon", "answer", "confirm"] and kinds[-2:] == ["final", "final"]  # lock at the start, goodbyes at the end
    assert events[1]["level"] == 0  # the answer goes out at the slowest level
    from_a = [e["level"] for e in events if e["sender"] == "KO4WSC" and e["kind"] == "message"]  # levels A sent its messages at
    from_b = [e["level"] for e in events if e["sender"] == "W1AW" and e["kind"] == "message"]  # levels B sent its messages at
    assert min(from_a) > max(from_b)  # each direction ran at its own speed: fast one way, slow the other
    assert all(e["heard"] for e in events)  # and nothing was lost


def test_lock_survives_a_gap_in_the_path():  # the path vanishes for a while, then returns
    def gap(t):  # SNR over time
        return -45.0 if 80 <= t < 160 else 2.0  # gone from 80 s to 160 s
    a, b, events = contact(Path(gap), Path(gap), [ODD, ODD, ODD], ["Got them."])  # enough traffic to be mid-message when the path goes
    assert b.inbox == [ODD, ODD, ODD] and a.inbox == ["Got them."]  # everything still arrived, once each
    assert any(e["kind"] == "probe" for e in events)  # the stations had to go looking for each other
    assert any("reacquired" in line for line in a.log + b.log)  # and one of them found the other again
    assert a.state == "RELEASED" and b.state == "RELEASED"  # then the contact closed normally
    assert any(not e["heard"] for e in events)  # frames really were lost in the gap


def test_dead_path_ends_the_lock_and_reports_what_was_not_sent():  # the path never comes back
    def dies(t):  # SNR over time
        return 2.0 if t < 75 else -45.0  # gone for good soon after the lock is made
    a, b, events = contact(Path(dies), Path(dies), [ODD, ODD, ODD], [])  # three messages, time for one at most
    assert a.state == "RELEASED"  # the sender gave up the lock rather than calling for ever
    assert b.state == "RELEASED" and any("not heard" in line for line in b.log)  # and the receiver stopped waiting after five minutes of silence
    assert len(a.delivered) + len(a.outbox) == 3 and a.outbox  # every message is either delivered or still in the outbox
    assert b.inbox[:len(a.delivered)] == a.delivered and len(b.inbox) <= len(a.delivered) + 1  # the sender never claims a delivery that did not happen (one message may have arrived with its acknowledgment lost)
    assert any("not delivered" in line for line in a.log)  # and the operator is told
    probes = [e for e in events if e["kind"] == "probe"]  # the reacquire attempts
    assert probes and all(e["level"] == 0 for e in probes)  # made at the slowest level


def test_answering_station_gives_way_when_both_are_sending():  # the tie-break after a lost frame
    a = Station("KO4WSC", "EM92")  # the beaconing station
    b = Station("W1AW", "FN31")  # the answering station
    for station, role in ((a, "beaconer"), (b, "answerer")):  # put both into a lock by hand
        station.role, station.state, station.link, station.allowed = role, "LOCKED", 77, [0, 1, 2, 3, 4]  # same link, all levels
        station.my_turn, station.pending, station.deadline = True, "probe", 1e9  # each believes it holds the turn and is probing
    probe_from_a = a._ack(0.0, 0, OFFER_PROBE, 3, "probe", "probe")  # A's probe
    probe_from_b = b._ack(0.0, 0, OFFER_PROBE, 3, "probe", "probe")  # B's probe
    assert a.handle(a.hear(probe_from_b.audio), 30.0) is None and a.pending == "probe"  # the beaconing station ignores B's probe and keeps the turn
    reply = b.handle(b.hear(probe_from_a.audio), 30.0)  # the answering station hears A's probe
    assert reply is not None and reply.kind == "reply" and not b.my_turn and b.pending is None  # it gives way and answers


def test_three_stations_answering_one_beacon_are_each_worked():  # the reply window
    caller = Station("KO4WSC", "EM92")  # the station that calls
    caller.beacon()  # it beacons
    calls = ["W1AW", "K4ABC", "N0XYZ"]  # three stations that will all answer
    others = []  # their Station objects
    for call in calls:  # set each one up
        station = Station(call, "FN31")  # a listening station
        station.listen()  # it answers beacons
        station.queue(f"Check-in from {call}.")  # with one message for the caller
        others.append(station)  # keep it
    paths_out = {call: Path(3.0 - i, offset_hz=3.0 * i) for i, call in enumerate(calls)}  # caller to each station
    paths_in = {call: Path(2.0 - 2 * i, offset_hz=-4.0 * i) for i, call in enumerate(calls)}  # each station to the caller
    events = run_group(caller, others, paths_out, paths_in, seed=1)  # run it
    assert sorted(caller.inbox) == sorted(f"Check-in from {call}." for call in calls)  # every station's message arrived, once
    assert all(s.state == "RELEASED" and len(s.delivered) == 1 for s in others)  # each contact was completed and closed
    beacons = [e for e in events if e["kind"] == "beacon"]  # the caller's beacons
    assert beacons[0]["note"] == "" and beacons[1]["note"] == "wide window"  # the first asks for one slot; after the pile-up the next asks for four
    first_window = [e for e in events if e["kind"] == "answer" and e["t"] < beacons[1]["t"]]  # answers to the first beacon
    assert len(first_window) == 3 and len({e["t"] for e in first_window}) == 1  # all three landed in the single slot, on top of each other
    later = [e for e in events if e["kind"] == "answer" and e["t"] > beacons[1]["t"]]  # answers to the wide beacons
    assert len({e["note"].split(",")[0] for e in later}) > 1  # which were spread over different slots
    assert caller.worked == set(calls)  # the caller knows it has worked all three
