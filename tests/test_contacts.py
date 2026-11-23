"""Tests for the contact book (live/contacts.py, since 0.31R3): records, the file, history rules, and the logbook feeding it."""

import json  # reading the file back
import os  # file paths
import sys  # the import path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root, so live/ can be imported

from live.contacts import HISTORY_MAX, HISTORY_MIN, MERGE_S, ContactBook, clamp_limit, distance_bearing  # noqa: E402  the module under test
from live.logbook import Logbook  # noqa: E402  the logbook that feeds it

T0 = 1795390000.0  # a moment to start the stories at


def heard(book, call, when, kind="beacon", dial=7110.0, snr=-17.0, level="L0", report=None):  # a reception, as the logbook reports it
    fields = {"direction": "RX", "from": call, "text": kind, "dial_khz": dial, "level": level, "snr_db": snr, "offset_hz": 14.0}  # the fields
    if report is not None:  # it said how it heard this station
        fields["report_db"] = report  # as note_heard passes it
    book.observe("heard", when, fields)  # tell the book


def test_old_file_is_read_and_made_whole(tmp_path):  # a contacts.json from before 0.31R3
    path = tmp_path / "contacts.json"  # the file
    path.write_text(json.dumps({"qb2kes": {"grid": "FM05", "band": "40m"}}))  # only grid and band, as before
    book = ContactBook(str(path))  # open it
    record = book["QB2KES"]  # the callsign in capitals
    assert record["grid"] == "FM05" and record["band"] == "40m"  # kept
    assert record["name"] == "" and record["history"] == [] and record["last_heard"] == {}  # the new fields, empty


def test_put_save_reload_and_delete(tmp_path):  # add, change and delete
    path = str(tmp_path / "contacts.json")  # the file
    book = ContactBook(path)  # an empty book
    book.put("qb2kes", name="Hank", location="Raleigh, NC", grid="FM05", radio="FT-991A", power_w="50", antenna="dipole", notes="sked 1500Z", junk="ignored")  # a new contact
    again = ContactBook(path)  # read it back
    assert again["QB2KES"]["name"] == "Hank" and again["QB2KES"]["notes"] == "sked 1500Z"  # saved
    assert "junk" not in again["QB2KES"]  # unknown fields are not kept
    again.put("QB2KES", name="Henry")  # change one field
    assert ContactBook(path)["QB2KES"]["name"] == "Henry" and ContactBook(path)["QB2KES"]["radio"] == "FT-991A"  # changed, the rest kept
    assert again.delete("QB2KES") and not again.delete("QB2KES")  # deleted once
    assert "QB2KES" not in ContactBook(path)  # and gone from the file


def test_all_traffic_one_entry_per_stretch(tmp_path):  # a beacon, a call, a contact: one history line
    book = ContactBook(str(tmp_path / "c.json"), mode="all")  # recording all traffic
    book.put("QB2KES")  # a saved contact
    heard(book, "QB2KES", T0)  # its beacon heard
    entry = book["QB2KES"]["history"][-1]  # the history entry
    assert entry["outcome"] == "Heard beacon" and entry["heard_db"] == -17.0 and entry["band"] == "40m"  # as heard
    assert book["QB2KES"]["last_heard"]["snr_db"] == -17.0 and book["QB2KES"]["last_heard"]["dial_khz"] == 7110.0  # the last reading
    book.observe("call", T0 + 30, {"direction": "TX", "from": "QA1AAA", "to": "QB2KES", "dial_khz": 7110.0, "level": "L2"})  # this station calls it
    assert entry["outcome"] == "Called, no answer"  # so far
    heard(book, "QB2KES", T0 + 60, kind="answer", snr=-15.0, report=-19.0)  # it answers, reporting -19 dB
    book.observe("contact start", T0 + 61, {"direction": "--", "to": "QB2KES", "dial_khz": 7110.0})  # locked
    book.observe("message", T0 + 90, {"direction": "TX", "to": "QB2KES", "dial_khz": 7110.0})  # a message sent
    book.observe("message", T0 + 120, {"direction": "RX", "from": "QB2KES", "dial_khz": 7110.0, "snr_db": -14.0})  # one received
    book.observe("call", T0 + 130, {"direction": "TX", "to": "QB2KES", "dial_khz": 7110.0})  # a resend inside the contact
    book.observe("contact end", T0 + 150, {"direction": "--", "to": "QB2KES", "dial_khz": 7110.0})  # done
    history = book["QB2KES"]["history"]  # the history
    assert len(history) == 1  # one line for the whole stretch
    assert history[0]["outcome"] == "Contact, ended" and history[0]["msgs_in"] == 1 and history[0]["msgs_out"] == 1  # what happened
    assert history[0]["their_db"] == -19.0 and history[0]["heard_db"] == -14.0 and history[0]["level"] == "L2"  # the readings, and the fastest level
    heard(book, "QB2KES", T0 + 200)  # heard again after the contact ended
    assert len(book["QB2KES"]["history"]) == 2  # a new line
    saved = json.loads(open(book.path, encoding="utf-8").read())  # the file
    assert len(saved["QB2KES"]["history"]) == 2  # kept up to date


def test_new_entry_after_a_gap_or_on_another_band(tmp_path):  # when traffic is a new stretch
    book = ContactBook(str(tmp_path / "c.json"))  # recording all traffic
    book.put("QB2KES")  # a saved contact
    heard(book, "QB2KES", T0)  # heard
    heard(book, "QB2KES", T0 + MERGE_S - 1)  # within the window: the same line
    assert len(book["QB2KES"]["history"]) == 1  # merged
    heard(book, "QB2KES", T0 + 2 * MERGE_S + 10)  # long after
    assert len(book["QB2KES"]["history"]) == 2  # a new line
    heard(book, "QB2KES", T0 + 2 * MERGE_S + 20, dial=3590.0)  # on 80 m
    assert len(book["QB2KES"]["history"]) == 3 and book["QB2KES"]["history"][-1]["band"] == "80m"  # another line


def test_completed_contacts_only(tmp_path):  # Record in history: Completed contacts
    book = ContactBook(str(tmp_path / "c.json"), mode="contacts")  # only completed contacts
    book.put("QB2KES")  # a saved contact
    heard(book, "QB2KES", T0)  # a beacon
    book.observe("call", T0 + 10, {"direction": "TX", "to": "QB2KES", "dial_khz": 7110.0})  # a call with no answer
    assert book["QB2KES"]["history"] == []  # nothing recorded
    assert book["QB2KES"]["last_heard"]["t"] == T0  # but the last reading is kept
    book.observe("contact start", T0 + 30, {"direction": "--", "to": "QB2KES", "dial_khz": 7110.0})  # a contact
    book.observe("message", T0 + 40, {"direction": "RX", "from": "QB2KES", "dial_khz": 7110.0})  # a message
    book.observe("contact end", T0 + 60, {"direction": "--", "to": "QB2KES", "dial_khz": 7110.0})  # ended
    history = book["QB2KES"]["history"]  # the history
    assert len(history) == 1 and history[0]["outcome"] == "Contact, ended" and history[0]["msgs_in"] == 1  # the contact alone


def test_only_saved_stations_and_single_stations_count(tmp_path):  # what the book ignores
    book = ContactBook(str(tmp_path / "c.json"))  # recording all traffic
    book.put("QB2KES")  # one saved contact
    heard(book, "QC9RTN", T0)  # a station not in the book
    book.observe("broadcast", T0, {"direction": "TX", "from": "QA1AAA", "to": "ALL"})  # a broadcast sent to everyone
    book.observe("mail", T0, {"direction": "", "text": "held: QB2KES #3"})  # mail news (never recorded)
    book.observe("heard", T0, {"direction": "RX", "text": "signature heard"})  # a near miss names nobody
    assert "QC9RTN" not in book and book["QB2KES"]["history"] == []  # nothing recorded


def test_history_limit(tmp_path):  # 30 to 200 entries, the oldest dropped first
    assert clamp_limit(10) == HISTORY_MIN and clamp_limit(500) == HISTORY_MAX and clamp_limit("120") == 120 and clamp_limit("x") == 120  # the range
    book = ContactBook(str(tmp_path / "c.json"), limit=30)  # the smallest history
    book.put("QB2KES")  # a saved contact
    for k in range(40):  # 40 stretches of traffic
        heard(book, "QB2KES", T0 + k * 2 * MERGE_S, snr=-float(k))  # each far apart
    history = book["QB2KES"]["history"]  # the history
    assert len(history) == 30 and history[-1]["heard_db"] == -39.0 and history[0]["heard_db"] == -10.0  # the newest 30
    book.set_policy(200, "all")  # longer: nothing dropped
    assert book.trimmed_by(30) == 0 and book.trimmed_by(20) == 0  # nothing over 30 (20 counts as 30)
    for k in range(40, 60):  # 20 more
        heard(book, "QB2KES", T0 + k * 2 * MERGE_S)  # each far apart
    assert len(book["QB2KES"]["history"]) == 50 and book.trimmed_by(30) == 20  # 20 would go at 30
    book.set_policy(30, "all")  # shorter again
    assert len(ContactBook(book.path, limit=200)["QB2KES"]["history"]) == 30  # trimmed, in the file too


def test_logbook_tells_the_book_at_every_level(tmp_path):  # the logbook feeds the book whatever it writes itself
    book = ContactBook(str(tmp_path / "c.json"))  # recording all traffic
    book.put("QB2KES")  # a saved contact
    log = Logbook(str(tmp_path / "logs"), level="basic")  # basic: "heard" rows are not written
    log.observers.append(book.observe)  # as the panel joins them
    log.observers.insert(0, lambda event, when, fields: 1 / 0)  # an observer that fails must not stop anything
    assert log.write("heard", direction="RX", **{"from": "QB2KES"}, text="beacon", dial_khz=7110.0, level="L0", snr_db=-21.0, report_db=None) is None  # not written at basic
    assert book["QB2KES"]["history"][-1]["outcome"] == "Heard beacon" and book["QB2KES"]["last_heard"]["snr_db"] == -21.0  # but the book knows
    assert log.write("message", direction="RX", **{"from": "QB2KES"}, text="hello", dial_khz=7110.0) is not None  # written at basic
    assert book["QB2KES"]["history"][-1]["msgs_in"] == 1  # and counted


def test_distance_and_bearing():  # between grid locators
    miles, bearing = distance_bearing("EM92", "FM05")  # two squares
    assert round(miles) == 237 and round(bearing) == 28  # as worked by hand
    assert round(distance_bearing("EM92", "EN61")[0]) == 704  # another
    assert distance_bearing("EM92", "") is None and distance_bearing("EM92", "ZZ99") is None and distance_bearing("EM92ab", "EM92") is not None  # not a locator; six characters work
