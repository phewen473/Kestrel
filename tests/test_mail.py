"""Tests of store and forward (spec Section 8, since 0.30): mail handed to a carrying station, delivered when the destination asks, and receipts that close the loop."""

import os  # temporary files
import tempfile  # a folder for the saved mail

import numpy as np  # numerical arrays

from link import Path, Station, run_link  # the link layer and its simulation
from link.mail import Mailroom  # the mail store
from link.params import HOP_LIMIT, MAIL_LIFE_HOURS  # the hop limit and the mail lifetime
from modem import build_notice, call_hash, message_hash, receive  # the mail notice frame and its short codes

GOOD = Path(snr_db=0.0)  # an easy path, so these tests are about the rules, not the modem
TEXT = "Hello C, this is A by way of B."  # the message carried


def three_stations(clock):  # an origin, a carrier and a destination sharing one wall clock
    """Return stations A (origin), B (carrier) and C (destination), with their mail kept on the clock in `clock` (a one-item list of seconds)."""
    stations = Station("Q1AAAA", "EM92"), Station("Q2BB", "FN31"), Station("Q3CCC", "EM73")  # the three
    for station in stations:  # each one
        station.mail.clock = lambda: clock[0]  # reads the shared clock
    return stations  # A, B, C


def meet(caller, answerer, seed):  # one contact: `caller` beacons, `answerer` listens
    """Run one contact between the two stations, each starting afresh, and return its events."""
    caller.new_contact()  # ready for another contact
    answerer.new_contact()  # and this one too
    caller.beacon()  # the caller beacons
    answerer.listen()  # the other listens
    return run_link(caller, answerer, GOOD, GOOD, seed=seed)  # run it


def test_notice_frame_carries_its_three_lists():  # the new frame type (signal 0.30)
    audio = build_notice("Q2BB", [call_hash("Q3CCC")], [message_hash("Q1AAAA", 7)], [call_hash("Q1AAAA"), call_hash("Q3CCC")], level=2)  # a notice at L2
    noisy = np.concatenate([np.zeros(2000), audio, np.zeros(2000)]) + np.random.default_rng(0).normal(0.0, 0.05, len(audio) + 4000)  # with a little noise
    result = receive(noisy)  # the receiver
    assert result.ok and result.frame_type == 7  # decoded, as a mail notice
    assert result.fields == {"origin": "Q2BB", "held": [call_hash("Q3CCC")], "receipts": [message_hash("Q1AAAA", 7)], "heard": [call_hash("Q1AAAA"), call_hash("Q3CCC")]}  # every list as sent


def test_message_is_carried_delivered_and_the_receipt_comes_back():  # the whole loop: A -> B (carrier) -> C, receipt back to A
    clock = [1.8e9]  # the wall clock
    a, b, c = three_stations(clock)  # the three stations
    a.queue(TEXT, to="Q3CCC")  # A writes to C, who is not on the air
    number = a.outbox_ids[0]  # the message's number, fixed when it was queued
    meet(a, b, 1)  # A works B
    assert [(item["dest"], item["origin"], item["id"], item["text"]) for item in b.mail.bag] == [("Q3CCC", "Q1AAAA", number, TEXT)]  # B now carries the message
    assert a.outbox == [TEXT] and a.mail.own[str(number)]["carriers"] == ["Q2BB"]  # A keeps its own copy, knowing B carries one
    assert b.inbox == [] and b.bulletins == []  # B's operator is not shown mail for someone else
    clock[0] += 3600.0  # an hour later
    meet(c, b, 2)  # C comes on and beacons; B, listening, answers because it holds mail for C
    assert c.bulletins == [("Q1AAAA via Q2BB", "Q3CCC", TEXT)]  # C has the message, and knows who carried it
    assert b.mail.bag == [] and "Q1AAAA#%d" % number in b.mail.receipts  # B dropped its copy and announces the delivery
    clock[0] += 600.0  # ten minutes later
    events = meet(b, a, 3)  # B beacons, with a mail notice first; A listens
    assert events[0]["kind"] == "mail notice" and events[0]["heard"]  # the notice went out ahead of the beacon, and A heard it
    assert a.delivered == [TEXT] and a.outbox == [] and a.mail.own == {}  # A now knows its message was delivered


def test_destination_answers_already_have_it_to_a_second_copy():  # first to deliver wins; the origin's own copy is not delivered twice
    clock = [1.8e9]  # the wall clock
    a, b, c = three_stations(clock)  # the three stations
    a.queue(TEXT, to="Q3CCC")  # A writes to C
    meet(a, b, 1)  # B takes a copy
    meet(c, b, 2)  # and delivers it to C
    meet(a, c, 3)  # later A and C work each other directly; A still has the message in its outbox
    assert c.bulletins == [("Q1AAAA via Q2BB", "Q3CCC", TEXT)] and c.inbox == []  # C was shown the message once only
    assert a.delivered == [TEXT] and a.outbox == []  # A was told C already has it, so it counts as delivered


def test_station_that_does_not_carry_mail_declines_and_the_message_stays_with_its_origin():  # the "Carry mail for others" setting off
    clock = [1.8e9]  # the wall clock
    a, b, _ = three_stations(clock)  # two of the stations are needed
    b.carries = False  # B's operator does not carry mail for others
    a.queue(TEXT, to="Q3CCC")  # A writes to C
    a.queue("Hello B", to="Q2BB")  # and to B itself
    meet(a, b, 1)  # A works B
    assert b.mail.bag == [] and b.inbox == ["Hello B"]  # B took its own message and declined the other
    assert a.outbox == [TEXT] and "Q2BB" in a.refused and a.mail.own[str(a.outbox_ids[0])]["carriers"] == []  # A still holds the message, and will not ask B again
    assert any("does not carry mail" in line for line in a.log) and a.state == "RELEASED"  # A was told, and the contact still closed properly


def test_a_just_listening_holder_still_answers_the_destination():  # delivery needs no operator at the holder
    clock = [1.8e9]  # the wall clock
    a, b, c = three_stations(clock)  # the three stations
    a.queue(TEXT, to="Q3CCC")  # A writes to C
    meet(a, b, 1)  # B takes a copy
    b.answer_beacons = b.answer_calls = False  # B's operator has set Listen to just listen
    meet(c, b, 2)  # C beacons, asking for its mail
    assert c.bulletins and c.bulletins[0][2] == TEXT  # B answered anyway and delivered


def test_hops_and_lifetime_travel_with_the_message():  # the address block of a carried message
    clock = [1.8e9]  # the wall clock
    a, b, c = three_stations(clock)  # the three stations
    a.queue(TEXT, to="Q3CCC")  # A writes to C
    meet(a, b, 1)  # B takes a copy
    held = b.mail.bag[0]  # what B holds
    assert held["hops"] == 0 and abs(held["expires"] - (clock[0] + MAIL_LIFE_HOURS * 3600.0)) <= 3600.0  # handed on by its origin (no hops yet), with the full lifetime
    if hasattr(b.mail, "store"):  # the compiled store: its entries are copies, so change it through its own file contents
        kept = b.mail.to_dict()  # the store as plain data
        kept["bag"][0]["hops"] = HOP_LIMIT  # pretend it has already been passed on as often as allowed
        b.mail._ask("from_dict", kept)  # put back
    else:  # the Python store: its entries are the store itself
        held["hops"] = HOP_LIMIT  # pretend it has already been passed on as often as allowed
    meet(c, b, 2)  # C beacons
    assert c.bulletins == [] and len(b.mail.bag) == 1  # B may not send it any further


def test_mail_outlasts_a_restart_and_expires_in_time():  # the store kept in a file
    clock = [1.8e9]  # the wall clock
    with tempfile.TemporaryDirectory() as folder:  # somewhere to keep the file
        path = os.path.join(folder, "mail.json")  # the file
        room = Mailroom("Q2BB", clock=lambda: clock[0])  # B's mail
        assert room.hold("Q3CCC", "Q1AAAA", 12, TEXT, 0, 62, "Q1AAAA")  # a message held for C
        number = room.own_add("Hello C", "Q3CCC")  # and one of B's own
        room.save(path)  # kept
        again = Mailroom.load(path, "Q2BB", clock=lambda: clock[0])  # read back, as after a restart
        assert again.bag[0]["text"] == TEXT and again.own_add("Hello C", "Q3CCC") == number  # the held message is there, and B's own message keeps its number
        assert Mailroom.load(path, "Q9ZZZ", clock=lambda: clock[0]).bag == []  # another callsign does not get B's mail
        clock[0] += (MAIL_LIFE_HOURS + 1) * 3600.0  # past the lifetime
        assert again.tidy() == [number] and again.bag == []  # both have expired; B's own is reported undelivered
