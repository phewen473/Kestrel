"""Tests of the link layer: two simulated stations making, running and closing a contact."""

from link import Path, Station, run_group, run_link, supported_level, wanted_level  # the link layer and its simulations
from link.params import OFFER_PROBE  # the "are you still there?" code
from link.station import reply_slot  # the length of a reply slot at each level

ENGLISH = "Good morning from South Carolina. Weather here is clear and 52 degrees with a light wind from the north. How do you copy this evening?"  # an ordinary message
ODD = "".join(chr(33 + (37 * i) % 94) for i in range(200))  # 200 characters that do not compress


def contact(path_ab, path_ba, from_a, from_b, seed=1):  # run one contact
    """Return (station A, station B, events) after A beacons, B answers, and both send their messages."""
    a = Station("Q1AAAA", "EM92")  # the station that calls
    b = Station("Q2BB", "FN31")  # the station that answers
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
    assert events[0]["level"] == events[1]["level"] == 2  # beacon and answer go out at the middle level first (spec 0.23)
    from_a = [e["level"] for e in events if e["sender"] == "Q1AAAA" and e["kind"] == "message"]  # levels A sent its messages at
    from_b = [e["level"] for e in events if e["sender"] == "Q2BB" and e["kind"] == "message"]  # levels B sent its messages at
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
        return 2.0 if t < 35 else -45.0  # gone for good soon after the lock is made (about 20 s in, with the call-up at L2)
    a, b, events = contact(Path(dies), Path(dies), [ODD, ODD, ODD], [])  # three messages, time for one at most
    assert a.state == "RELEASED"  # the sender gave up the lock rather than calling for ever
    assert b.state == "RELEASED" and any("not heard" in line for line in b.log)  # and the receiver stopped waiting after five minutes of silence
    assert len(a.delivered) + len(a.outbox) == 3 and a.outbox  # every message is either delivered or still in the outbox
    assert b.inbox[:len(a.delivered)] == a.delivered and len(b.inbox) <= len(a.delivered) + 1  # the sender never claims a delivery that did not happen (one message may have arrived with its acknowledgment lost)
    assert any("not delivered" in line for line in a.log)  # and the operator is told
    probes = [e for e in events if e["kind"] == "probe"]  # the reacquire attempts
    assert probes and all(e["level"] == 0 for e in probes)  # made at the slowest level


def test_answering_station_gives_way_when_both_are_sending():  # the tie-break after a lost frame
    a = Station("Q1AAAA", "EM92")  # the beaconing station
    b = Station("Q2BB", "FN31")  # the answering station
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
    caller = Station("Q1AAAA", "EM92")  # the station that calls
    caller.beacon()  # it beacons
    calls = ["Q2BB", "Q3CCC", "Q4DDD"]  # three stations that will all answer
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
    assert sum(e["heard"] for e in first_window) <= 1  # the caller reads at most one of the collided answers (with this seed it read one before 0.32 and none since); the contacts complete on later beacons either way
    assert caller.worked == set(calls)  # the caller knows it has worked all three


def pair(keep_open=False):  # two fresh stations, ready to meet
    """Return (calling station, answering station); with `keep_open` neither closes the contact when the traffic runs out."""
    a = Station("Q1AAAA", "EM92", close_when_done=not keep_open)  # the station that calls
    b = Station("Q2BB", "FN31", close_when_done=not keep_open)  # the station that answers
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
    a, b = pair()  # Q1AAAA calls, Q2BB answers
    a.queue("For whoever answers.")  # an ordinary message
    a.queue("Only for Q4DDD.", to="Q4DDD")  # a message for a station that is not here
    a.queue("Only for Q2BB.", to="q2bb")  # a message for the station that will answer (typed in lower case)
    run_link(a, b, Path(5.0), Path(5.0), seed=8)  # the contact
    assert a.delivered == ["For whoever answers.", "Only for Q2BB."]  # the two that were for this partner went, in order
    assert a.outbox == ["Only for Q4DDD."] and a.outbox_to == ["Q4DDD"]  # the other is still waiting, with its address
    assert b.inbox == ["For whoever answers.", "Only for Q2BB."]  # and Q2BB received exactly those two


def test_directed_call_reaches_only_the_station_named():  # calling one station instead of beaconing
    a = Station("Q1AAAA", "EM92")  # the calling station
    b = Station("Q2BB", "FN31")  # the station being called
    c = Station("Q4DDD", "EN34")  # a bystander
    a.call_station("Q2BB")  # A calls B by name
    b.listen()  # B is listening
    c.listen()  # so is the bystander
    a.queue("A message just for you.", to="Q2BB")  # A's traffic for B
    call = a.poll(0.0)  # the directed call
    assert call.kind == "call"  # it is a call, not a beacon
    assert c.handle(c.hear(call.audio), call.seconds + 1.0) is None and c.state == "IDLE"  # the bystander hears it and stays silent
    a2 = Station("Q1AAAA", "EM92")  # start again for the contact itself
    a2.call_station("Q2BB")  # the same call
    a2.queue("A message just for you.", to="Q2BB")  # the same traffic
    run_link(a2, b, Path(5.0), Path(5.0), seed=9)  # the contact
    assert a2.delivered == ["A message just for you."] and b.inbox == ["A message just for you."]  # delivered and acknowledged
    assert a2.state == b.state == "RELEASED"  # and closed properly
    assert any("called by Q1AAAA" in line for line in b.log)  # the called station knew it was called


def test_directed_call_gives_up_when_nobody_is_there():  # the station named never answers
    a = Station("Q1AAAA", "EM92")  # the calling station
    b = Station("Q2BB", "FN31")  # a different station, listening
    a.call_station("Q4DDD")  # A calls somebody who is not on the air
    b.listen()  # B hears the calls but they are not for it
    events = run_link(a, b, Path(5.0), Path(5.0), seed=10)  # let it run
    assert [e["kind"] for e in events] == ["call"] * 5  # five calls, no replies
    assert a.state == "RELEASED" and any("no answer from Q4DDD" in line for line in a.log)  # then it gives up and says so
    assert b.state == "IDLE"  # the other station never transmitted


def test_broadcast_to_all_is_received_without_a_lock():  # a message to everyone
    a = Station("Q1AAAA", "EM92")  # the broadcasting station
    b = Station("Q2BB", "FN31")  # one listener
    c = Station("Q4DDD", "EN34")  # another
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
        assert station.bulletins == [("Q1AAAA", "ALL", text)]  # the whole broadcast, once, with who sent it
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
    caller = Station("Q1AAAA", "EM92")  # the station that calls
    caller.beacon()  # it beacons
    first = caller.poll(0.0)  # the first beacon
    assert first.kind == "beacon" and first.level == 2 and first.note == "" and not caller.wide  # at the middle level, one reply slot (spec 0.23)
    assert abs(caller.deadline - (first.seconds + 1.0 * reply_slot(2))) < 15.0  # a short window: one slot sized for an L2 answer
    second = caller.poll(caller.deadline + 0.1)  # nobody answered at L2: perhaps the path is too weak
    assert second.kind == "beacon" and second.level == 0 and not caller.wide  # so it calls at L0, still with one slot
    third = caller.poll(caller.deadline + 0.1)  # nobody answered at L0 either (or the answers spoiled one another)
    assert third.kind == "beacon" and third.level == 0 and third.note == "wide window" and caller.wide  # this time asking for four reply slots
    assert third.seconds == second.seconds  # the same length of beacon; only its window flag differs


def test_station_refuses_to_call_itself():  # a directed call to one's own callsign can never be answered
    import pytest  # for checking that an error is raised
    station = Station("Q1AAAA", "EM92")  # a station
    with pytest.raises(ValueError):  # it must refuse
        station.call_station("q1aaaa")  # its own callsign, typed in lower case
    assert station.role is None  # and it has not become a calling station


def test_listening_station_beacons_once_and_listens_again():  # the panel's repeating beacon: one round at a time
    a = Station("Q1AAAA", "EM92")  # a station that is listening
    a.listen()  # answering beacons
    a.beacon_once()  # the operator's timer asks for one beacon round
    first = a.poll(0.0)  # the beacon
    assert first.kind == "beacon" and first.level == 2  # it goes out, at the middle level first
    second = a.poll(a.deadline + 0.1)  # nobody answers
    assert second.kind == "beacon" and second.level == 0  # so the round tries once more at L0 (spec 0.23)
    assert a.poll(a.deadline + 0.1) is None and a.state == "RELEASED"  # nobody answers that either: one round only
    assert any("no answer to the beacon" in line for line in a.log)  # and the log says so
    a.new_contact()  # the live loop gets ready for the next contact
    assert a.role == "answerer" and a.state == "IDLE" and not a.single  # listening again


def test_one_beacon_round_that_is_answered_leads_to_a_contact_then_listening():  # an answered round
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens...
    a.beacon_once()  # ...and makes one beacon round
    b.listen()  # B is listening
    a.queue("Hello from the repeating beacon.")  # A's traffic
    run_link(a, b, Path(5.0), Path(5.0), seed=11)  # the contact
    assert a.delivered == ["Hello from the repeating beacon."] and a.state == "RELEASED"  # delivered and closed
    a.new_contact()  # ready for the next
    assert a.role == "answerer" and not a.leads  # back to listening


def test_listening_station_calls_once_and_listens_again():  # a directed call from a station that is listening
    a = Station("Q1AAAA", "EM92")  # the station that calls
    a.listen()  # it was listening
    a.call_once("Q4DDD")  # it calls somebody who is not on the air
    calls = 0  # count the calls
    t = 0.0  # the clock
    while a.state != "RELEASED" and calls < 10:  # until it gives up
        tx = a.poll(t)  # anything to send?
        if tx is not None:  # a call
            calls += 1  # count it
        t = (a.next_wake() or t) + 0.1  # move on to when it next needs attention
    assert calls == 5 and a.state == "RELEASED"  # five calls, then it gives up
    a.new_contact()  # ready again
    assert a.role == "answerer" and a.target == ""  # listening, with no call outstanding


def test_station_called_during_its_own_beacon_window_answers_the_call():  # a repeating beacon must not get in the way of being called
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens...
    a.beacon_once()  # ...and is making one beacon round, with a wide reply window
    a.wide = True  # (as after an unanswered beacon)
    b.call_station("Q1AAAA")  # meanwhile B calls A by name
    b.queue("Called you while you were beaconing.", to="Q1AAAA")  # with a message for it
    run_link(a, b, Path(5.0), Path(5.0), seed=12)  # let it run
    assert a.inbox == ["Called you while you were beaconing."] and b.delivered == a.inbox  # the call was taken and the message delivered
    assert any("called by Q2BB" in line for line in a.log)  # A knew it was being called
    a.new_contact()  # afterwards
    assert a.role == "answerer"  # A listens again


def test_operator_answers_a_beacon_by_hand_with_a_directed_call():  # answering by hand (spec 0.22)
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens...
    a.beacon_once()  # ...and makes one beacon round
    a.queue("Thanks for answering.")  # with a message for whoever answers
    b.listen()  # B listens...
    b.answer_beacons = False  # ...but its operator answers by hand
    beacon = a.poll(0.0)  # A's beacon
    assert b.handle(b.hear(beacon.audio), beacon.seconds + 1.0) is None  # B stays silent: its operator is shown the beacon instead
    b.call_once("Q1AAAA")  # some seconds later the operator chooses to respond
    run_link(a, b, Path(5.0), Path(5.0), seed=13, start_s=beacon.seconds + 20.0)  # the call reaches A while A is still in its reply window
    assert b.inbox == ["Thanks for answering."] and any("called by Q2BB" in line for line in a.log)  # A took the call and delivered its message


def test_weak_path_gets_the_l0_call_up_after_the_middle_level_fails():  # the price of starting in the middle
    a, b, events = contact(Path(-18.0), Path(-18.0), ["Weak but readable."], [], seed=21)  # too weak for L2, fine for L0
    beacons = [e["level"] for e in events if e["kind"] == "beacon"]  # the beacons sent
    assert beacons[:2] == [2, 0]  # the middle level first, then L0
    answer = next(e for e in events if e["kind"] == "answer")  # the answer that made the lock
    assert answer["level"] == 0 and b.inbox == ["Weak but readable."]  # answered at L0, and the message arrived


def test_directed_call_carries_a_reading_so_the_first_message_is_fast():  # no L0 start after a call by name
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    b.listen()  # B listens...
    b.beacon_once()  # ...and beacons once
    b.queue("Straight to a fast level.")  # with a message for whoever calls
    a.listen()  # A listens, answering by hand
    a.answer_beacons = False  # (so it stays silent)
    beacon = b.poll(0.0)  # B's beacon
    a.handle(a.hear(beacon.audio), beacon.seconds + 1.0)  # A hears it, and keeps the reading
    a.call_once("Q2BB")  # A responds with a directed call
    events = run_link(a, b, Path(5.0), Path(5.0), seed=22, start_s=beacon.seconds + 5.0)  # the contact
    call = next(e for e in events if e["kind"] == "call")  # the call
    first = next(e for e in events if e["kind"] == "message")  # B's first message
    assert call["level"] == 2 and first["level"] >= 2  # the call went at the middle level, and the message at least as fast
    assert a.inbox == ["Straight to a fast level."]  # and it arrived


def test_station_that_just_listens_is_called_and_calls_back():  # Listen means just listen (spec 0.24)
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens...
    a.call_once("Q2BB")  # ...and its operator calls B by name
    a.queue("Thanks for calling back.", to="Q2BB")  # with a message for B
    b.listen()  # B listens...
    b.answer_calls = b.answer_beacons = False  # ...and does not answer anything by itself
    call = a.poll(0.0)  # A's call
    assert b.handle(b.hear(call.audio), call.seconds + 1.0) is None and b.state == "IDLE"  # B stays silent; its operator is shown the call
    b.call_once("Q1AAAA")  # B's operator presses Respond: a call back
    run_link(a, b, Path(5.0), Path(5.0), seed=23, start_s=call.seconds + 8.0)  # A, still calling B, takes the call back as the answer
    assert b.inbox == ["Thanks for calling back."]  # the message arrived


def test_station_that_just_listens_accepts_a_reply_to_its_own_beacon():  # what the operator started is still answered
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    for station in (a, b):  # both just listen
        station.listen()  # listening
        station.answer_calls = station.answer_beacons = False  # answering nothing by themselves
    a.beacon_once()  # A's operator beacons once
    a.queue("Reply to my beacon.")  # with a message for whoever responds
    beacon = a.poll(0.0)  # the L2 beacon
    assert b.handle(b.hear(beacon.audio), beacon.seconds + 1.0) is None  # B stays silent: its operator is shown the beacon
    b.call_once("Q1AAAA")  # a minute later B's operator presses Respond
    run_link(a, b, Path(5.0), Path(5.0), seed=24, start_s=beacon.seconds + 60.0)  # A's round is over by then, but it beaconed recently, so it takes the call
    assert b.inbox == ["Reply to my beacon."]  # the message arrived


def test_unavailable_station_tells_a_caller_once_and_the_caller_stops():  # availability (spec 0.25)
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens...
    a.call_once("Q2BB")  # ...and calls B by name
    b.listen()  # B listens...
    b.available = False  # ...but its operator has set it to unavailable
    events = run_link(a, b, Path(5.0), Path(5.0), seed=25)  # let it run
    assert [e["kind"] for e in events] == ["call", "not available"]  # one call, one short reply, and nothing more
    assert events[1]["level"] == events[0]["level"] == 2  # the reply goes at the call's own level
    assert a.state == "RELEASED" and a.unavailable_from == "Q2BB" and any("Q2BB is not available" in line for line in a.log)  # A stopped calling and knows why


def test_unavailable_station_sends_presence_beacons_that_nobody_answers():  # the beacon says it too
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31")  # two stations
    a.listen()  # A listens
    a.available = False  # its operator is not available
    a.beacon_once()  # the repeating beacon's round
    beacon = a.poll(0.0)  # the beacon
    assert beacon.kind == "beacon" and a.state == "RELEASED" and a.pending is None  # sent, with no reply window
    b.listen()  # B answers beacons by itself
    heard = b.hear(beacon.audio)  # B hears it
    assert heard.ok and heard.fields["listening"] is False  # the beacon says A is not taking contacts
    assert b.handle(heard, beacon.seconds + 1.0) is None  # so B does not answer


def test_a_waiting_message_can_be_taken_back():  # a queued message can be removed before it starts to go
    station = Station("Q1AAAA", "EM92")  # a station with nothing under way
    station.queue("FIRST", to="Q2BB")  # a message for one station
    station.queue("SECOND")  # and one for whoever the partner is
    assert station.unqueue("FIRST", "Q2BB") is True  # the addressed one is taken back
    assert station.outbox == ["SECOND"] and station.outbox_to == [None]  # only the other remains, with its address
    assert station.unqueue("FIRST", "Q2BB") is False  # it cannot be removed twice
    station.plan = [{"text": "SECOND", "part": 0, "parts": 1}]  # the remaining message is now under way
    assert station.unqueue("SECOND") is False and station.outbox == ["SECOND"]  # a message being sent is left alone


def test_operator_can_stop_a_call():  # Esc / Stop calling: a directed call (Respond, Ctrl+Y) stops at once
    a = Station("Q1AAAA", "EM92")  # the calling station, normally listening
    a.listen()  # listening
    a.call_once("Q2BB")  # Respond: call one station by name
    first = a.poll(0.0)  # the first call goes out
    assert first is not None and first.kind == "call" and a.pending == "confirm"  # waiting for a reply
    assert a.cancel(5.0) == "stopped calling Q2BB (operator)"  # stopped
    assert a.state == "RELEASED" and a.role == "answerer" and a.pending is None and a.target == ""  # nothing awaited, listening afterwards
    a.new_contact()  # what the live loop does next
    assert a.poll(100.0) is None and a.role == "answerer" and a.state == "IDLE"  # no more calls
    assert a.cancel(101.0) == ""  # nothing left to stop
    assert any("stopped calling Q2BB (operator)" in line for line in a.log)  # in the log


def test_stop_leaves_a_contact_alone_and_clears_waiting_beacons():  # Stop is for call-ups only
    a = Station("Q1AAAA", "EM92")  # a station
    a.listen()  # listening
    a.broadcast("Net at 2100Z.")  # a broadcast waiting
    a.long_beacon()  # and a long beacon
    assert "the long beacon" in a.cancel(1.0) and not a.broadcasts and a.long_waiting is None  # both dropped
    b = Station("Q2BB", "FN31")  # another
    b.state, b.partner, b.link = "LOCKED", "Q1AAAA", 77  # in a contact
    assert b.cancel(2.0) == "" and b.state == "LOCKED"  # left to End contact


def test_an_unheard_move_is_dropped_and_the_message_goes_where_the_stations_are():  # since 0.42R3
    """On the air on 2026-11-25 the partner never heard a move proposal, the caller moved alone, and the contact was lost.
    Now an unanswered proposal is dropped and the message goes on the frequency both stations are on."""
    a, b = Station("Q1AAAA", "EM92", close_when_done=False), Station("Q2BB", "FN31", close_when_done=False)  # two stations that keep the contact open
    a.can_move = b.can_move = True  # both radios could be retuned
    a.beacon()  # A calls
    b.listen()  # B listens
    first = run_link(a, b, Path(3.0), Path(3.0), seed=2, limit_s=600)  # lock on the calling frequency
    assert a.state in ("LOCKED", "DEGRADED") and b.state in ("LOCKED", "DEGRADED")  # locked
    start = first[-1]["t"] + 5.0  # carry on from there
    a.move_to_hz = 2500.0  # A now wants to move
    a.queue("hello from the calling frequency")  # and has a message
    deaf = lambda t: -40.0 if t < start + 120.0 else 3.0  # B hears nothing from A for two minutes: both proposals are lost
    run_link(a, b, Path(deaf), Path(3.0), seed=3, limit_s=start + 1500, start_s=start)  # carry on
    assert "hello from the calling frequency" in b.inbox  # the message arrived
    assert a.offset_hz == 0 and b.offset_hz == 0  # nobody moved alone


def test_next_call_starts_at_the_level_the_station_last_needed():  # the call-up remembers a weak path (since 0.43)
    from link.params import ASKED_KEEP_S, CALLUP_LEVEL  # how long it is remembered, and the usual first level
    from link.station import PythonStation  # the reference rules
    for make in (PythonStation, Station):  # the reference rules, and the compiled ones when the library is in use
        a = make("Q1AAAA", "EM92")  # the calling station
        a.listen()  # idle, listening
        a.call_once("Q2BB")  # a first call, with nothing on record
        first = a.poll(0.0)  # the call
        assert first.kind == "call" and first.level == CALLUP_LEVEL  # at the usual middle level
        a.cancel(1.0)  # the operator stops calling
        a.new_contact()  # what the live loop does next
        a.asked = {"Q2BB": (100.0, 0)}  # on record: Q2BB lately asked this station for L0 (a weak path its way)
        assert a.asked == {"Q2BB": (100.0, 0)}  # kept as given (the compiled station hands it back the same)
        a.call_once("Q2BB")  # call again
        again = a.poll(200.0)  # the call
        assert again.kind == "call" and again.level == 0  # straight at L0: no airtime spent on a call it cannot read
        assert any("last needed L0" in line for line in a.log)  # and the log says why
        a.cancel(201.0)  # the operator stops calling
        a.new_contact()  # ready again
        a.call_once("Q2BB")  # much later
        late = a.poll(200.0 + ASKED_KEEP_S + 500.0)  # after the record has gone stale
        assert late.kind == "call" and late.level == CALLUP_LEVEL  # the usual level again: paths change


def test_station_remembers_the_level_its_partner_asked_for():  # where the record comes from
    a, b = Station("Q1AAAA", "EM92"), Station("Q2BB", "EM93")  # two stations
    a.beacon()  # A calls
    b.listen()  # B answers
    a.queue("REMEMBER THE LEVEL")  # something to send
    run_link(a, b, Path(-17.0), Path(5.0), seed=77)  # B hears A weakly; A hears B well
    assert "REMEMBER THE LEVEL" in b.inbox  # the message got through
    assert a.asked["Q2BB"][1] == 0  # A has it on record that Q2BB needed L0
    assert b.asked["Q1AAAA"][1] >= 2  # and B that Q1AAAA could take a faster level
