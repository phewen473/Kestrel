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
        station.leads = role == "beaconer"  # the beaconing station is the one that keeps the turn in a clash
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
    paths_in = {call: Path(2.0, offset_hz=-7.5 * i) for i, call in enumerate(calls)}  # each station to the caller: equally strong, a few hertz apart
    events = run_group(caller, others, paths_out, paths_in, seed=1)  # run it
    assert sorted(caller.inbox) == sorted(f"Check-in from {call}." for call in calls)  # every station's message arrived, once
    assert all(s.state == "RELEASED" and len(s.delivered) == 1 for s in others)  # each contact was completed and closed
    beacons = [e for e in events if e["kind"] == "beacon"]  # the caller's beacons
    first_window = [e for e in events if e["kind"] == "answer" and e["t"] < beacons[1]["t"]]  # answers to the first beacon
    assert len(first_window) == 3 and len({e["t"] for e in first_window}) == 1  # all three landed in the single slot, on top of each other
    assert sum(e["heard"] for e in first_window) == 1  # and the caller still read one of them: narrow signals a few hertz apart do not all spoil one another
    assert caller.worked == set(calls)  # the caller knows it has worked all three


def pair(keep_open=False):  # two fresh stations, ready to meet
    """Return (calling station, answering station); with `keep_open` neither closes the contact when the traffic runs out."""
    a = Station("KO4WSC", "EM92", close_when_done=not keep_open)  # the station that calls
    b = Station("W1AW", "FN31", close_when_done=not keep_open)  # the station that answers
    a.beacon()  # A beacons
    b.listen()  # B listens
    return a, b  # the pair


def test_contact_moves_to_a_working_frequency_and_returns():  # the pair leave the calling frequency once locked
    a, b = pair()  # two stations
    a.can_move = b.can_move = True  # both radios can be retuned
    a.move_to_hz = 2500  # the calling station wants to work 2.5 kHz higher
    a.queue("Message on the working frequency.")  # A's traffic
    b.queue("And one back.")  # B's traffic
    events = run_link(a, b, Path(5.0), Path(5.0), seed=3)  # run the contact
    kinds = [e["kind"] for e in events]  # what was sent, in order
    assert kinds.index("move") < kinds.index("move-ok") < kinds.index("probe") < kinds.index("message")  # proposal, agreement, a probe on the new frequency, then the traffic
    assert a.delivered == ["Message on the working frequency."] and b.delivered == ["And one back."]  # both messages got through after the move
    assert a.state == b.state == "RELEASED"  # the contact closed properly
    assert a.tuning(1e9) == 0 and b.tuning(1e9) == 0  # and both radios are back on the calling frequency
    assert any("moving +2.5 kHz" in line for line in a.log) and any("moving +2.5 kHz" in line for line in b.log)  # each side says where it went


def test_partner_that_cannot_move_keeps_the_contact_where_it_is():  # one radio has no rig control
    a, b = pair()  # two stations
    a.can_move, a.move_to_hz = True, -2500  # the calling station wants to move
    a.queue("Staying put.")  # A's traffic
    events = run_link(a, b, Path(5.0), Path(5.0), seed=4)  # run the contact (B cannot retune)
    assert all(e["heard"] for e in events)  # nothing was lost: the stations never parted
    assert a.delivered == ["Staying put."] and a.tuning(1e9) == 0 and b.tuning(1e9) == 0  # the message went through on the calling frequency
    assert any("cannot change frequency" in line for line in a.log)  # and the calling station says why it stayed


def test_lock_kept_open_carries_later_traffic_and_closes_on_request():  # a conversation that goes on
    a, b = pair(keep_open=True)  # neither closes when the traffic runs out
    a.queue("First message.")  # A's opening traffic
    run_link(a, b, Path(5.0), Path(5.0), seed=5, limit_s=400.0)  # the contact, then some idle time
    assert a.delivered == ["First message."] and a.state == b.state == "LOCKED"  # delivered, and the lock is still held
    b.queue("A later thought from the answering station.")  # the station without the turn gets something to say
    run_link(a, b, Path(5.0), Path(5.0), seed=6, limit_s=800.0, start_s=400.0)  # carry on
    assert b.delivered == ["A later thought from the answering station."] and a.inbox[-1].startswith("A later thought")  # it took the turn and delivered it
    assert a.state == b.state == "LOCKED"  # still locked
    b.end()  # the answering station's operator ends the contact
    run_link(a, b, Path(5.0), Path(5.0), seed=7, limit_s=1300.0, start_s=800.0)  # carry on
    assert a.state == b.state == "RELEASED"  # both sides closed
    assert any("contact closed" in line for line in a.log) and any("contact closed" in line for line in b.log)  # with a proper goodbye


def test_message_for_one_callsign_waits_for_that_station():  # a targeted message is not handed to anyone else
    a, b = pair()  # KO4WSC calls, W1AW answers
    a.queue("For whoever answers.")  # an ordinary message
    a.queue("Only for N0XYZ.", to="N0XYZ")  # a message for a station that is not here
    a.queue("Only for W1AW.", to="w1aw")  # a message for the station that will answer (typed in lower case)
    run_link(a, b, Path(5.0), Path(5.0), seed=8)  # the contact
    assert a.delivered == ["For whoever answers.", "Only for W1AW."]  # the two that were for this partner went, in order
    assert a.outbox == ["Only for N0XYZ."] and a.outbox_to == ["N0XYZ"]  # the other is still waiting, with its address
    assert b.inbox == ["For whoever answers.", "Only for W1AW."]  # and W1AW received exactly those two


def test_directed_call_reaches_only_the_station_named():  # calling one station instead of beaconing
    a = Station("KO4WSC", "EM92")  # the calling station
    b = Station("W1AW", "FN31")  # the station being called
    c = Station("N0XYZ", "EN34")  # a bystander
    a.call_station("W1AW")  # A calls B by name
    b.listen()  # B is listening
    c.listen()  # so is the bystander
    a.queue("A message just for you.", to="W1AW")  # A's traffic for B
    call = a.poll(0.0)  # the directed call
    assert call.kind == "call"  # it is a call, not a beacon
    assert c.handle(c.hear(call.audio), call.seconds + 1.0) is None and c.state == "IDLE"  # the bystander hears it and stays silent
    a2 = Station("KO4WSC", "EM92")  # start again for the contact itself
    a2.call_station("W1AW")  # the same call
    a2.queue("A message just for you.", to="W1AW")  # the same traffic
    run_link(a2, b, Path(5.0), Path(5.0), seed=9)  # the contact
    assert a2.delivered == ["A message just for you."] and b.inbox == ["A message just for you."]  # delivered and acknowledged
    assert a2.state == b.state == "RELEASED"  # and closed properly
    assert any("called by KO4WSC" in line for line in b.log)  # the called station knew it was called


def test_directed_call_gives_up_when_nobody_is_there():  # the station named never answers
    a = Station("KO4WSC", "EM92")  # the calling station
    b = Station("W1AW", "FN31")  # a different station, listening
    a.call_station("N0XYZ")  # A calls somebody who is not on the air
    b.listen()  # B hears the calls but they are not for it
    events = run_link(a, b, Path(5.0), Path(5.0), seed=10)  # let it run
    assert [e["kind"] for e in events] == ["call"] * 5  # five calls, no replies
    assert a.state == "RELEASED" and any("no answer from N0XYZ" in line for line in a.log)  # then it gives up and says so
    assert b.state == "IDLE"  # the other station never transmitted


def test_broadcast_to_all_is_received_without_a_lock():  # a message to everyone
    a = Station("KO4WSC", "EM92")  # the broadcasting station
    b = Station("W1AW", "FN31")  # one listener
    c = Station("N0XYZ", "EN34")  # another
    b.listen()  # both are listening
    c.listen()  # and neither is in a contact
    text = "Net tonight at 0100 UTC on 7101.5. All stations welcome, please check in with your grid."  # too long for one frame at the slowest level
    a.broadcast(text)  # queue it for everyone
    frames, t = [], 0.0  # the frames sent, and the clock
    while a.broadcasts:  # until every part has gone
        tx = a.poll(t)  # the next part
        frames.append(tx)  # keep it
        t += tx.seconds + 2.0  # the time it takes, and a gap
    assert len(frames) > 1 and all(tx.kind == "broadcast" for tx in frames)  # it was split into parts
    for station in (b, c):  # each listener
        for tx in frames:  # hears every part
            assert station.handle(station.hear(tx.audio), t) is None  # and sends nothing back
        assert station.bulletins == [("KO4WSC", "ALL", text)]  # the whole broadcast, once, with who sent it
        for tx in frames:  # hearing it all again (a repeat)
            station.handle(station.hear(tx.audio), t + 100.0)  # is harmless
        assert len(station.bulletins) == 1  # and is not shown twice
    assert a.state == "IDLE"  # the broadcaster never left the idle state


def test_idle_working_frequency_is_given_up_after_three_minutes():  # nobody is using the working frequency any more
    a, b = pair(keep_open=True)  # a conversation that is kept open
    a.can_move = b.can_move = True  # both radios can be retuned
    a.move_to_hz = 2500  # the calling station takes the contact to a working frequency
    a.queue("One message, then silence.")  # the only traffic
    events = run_link(a, b, Path(5.0), Path(5.0), seed=11, limit_s=900.0)  # the contact, then a long silence
    sent_at = max(e["t"] for e in events if e["kind"] == "message")  # when the message went
    warned = [line for line in a.log if "returning to the calling frequency in one minute" in line]  # the operator's warning
    closed = [line for line in a.log if "no messages for 3 minutes" in line]  # the decision to close
    assert len(warned) == 1 and len(closed) == 1  # warned once, then closed
    assert 115.0 <= float(warned[0].split("s")[0]) - sent_at <= 130.0  # the warning came two minutes after the message
    assert 175.0 <= float(closed[0].split("s")[0]) - sent_at <= 190.0  # and the closing three minutes after it
    assert not any("one minute" in line for line in b.log)  # only the station that asked for the move is warned
    assert a.state == b.state == "RELEASED" and a.tuning(1e9) == 0 and b.tuning(1e9) == 0  # both closed properly and are back on the calling frequency


def test_unanswered_beacon_is_followed_by_a_wide_reply_window():  # the caller's side of the reply window
    caller = Station("KO4WSC", "EM92")  # the station that calls
    caller.beacon()  # it beacons
    first = caller.poll(0.0)  # the first beacon
    assert first.kind == "beacon" and first.note == "" and not caller.wide  # one reply slot to begin with
    second = caller.poll(caller.deadline + 0.1)  # nobody answered (or the answers spoiled one another), so it calls again
    assert second.kind == "beacon" and second.note == "wide window" and caller.wide  # this time asking for four reply slots
    assert second.seconds == first.seconds  # the same length of beacon; only its window flag differs
