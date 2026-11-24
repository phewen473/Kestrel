"""Tests for each contact's traffic log and learning its radio and power from its messages (since 0.38R2)."""

import os  # file paths
import sys  # the import path
import tempfile  # a scratch folder for the book's file
import unittest  # the test runner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # the repository root

from live.contacts import ContactBook, rig_power_from  # what is tested  # noqa: E402


class RigPowerTest(unittest.TestCase):  # reading "RIG <radio> <n>W" out of a message
    def test_reads_radio_and_watts(self):  # the quick message "Rig and power"
        self.assertEqual(rig_power_from("Q1AA HANK FM05 RIG FT-991A 50W"), ("FT-991A", "50"))  # both read

    def test_radio_with_spaces(self):  # a radio name of more than one word
        self.assertEqual(rig_power_from("Q1AA RIG IC 7300 100 W"), ("IC 7300", "100"))  # the whole name, and the watts

    def test_unknowns(self):  # "?" for what the sender did not fill in
        self.assertEqual(rig_power_from("Q1AA RIG ? ?W"), ("", ""))  # nothing learned

    def test_no_rig(self):  # an ordinary message
        self.assertEqual(rig_power_from("good morning"), (None, None))  # not that message


class TrafficLogTest(unittest.TestCase):  # each beacon and message gets a row
    def setUp(self):  # a fresh book with one saved contact
        self.folder = tempfile.TemporaryDirectory()  # scratch space
        self.book = ContactBook(os.path.join(self.folder.name, "contacts.json"))  # the book
        self.book.put("Q1AA", name="Hank")  # a saved contact

    def tearDown(self):  # tidy up
        self.folder.cleanup()  # the scratch space goes

    def what(self):  # the kinds of row logged, oldest first
        return [row["what"] for row in self.book["Q1AA"]["log"]]  # in order

    def test_beacons_and_messages_logged_one_row_each(self):  # each reception, not one merged session
        self.book.observe("heard", 1000.0, {"direction": "RX", "from": "Q1AA", "text": "beacon", "dial_khz": 7105.0, "snr_db": -12})  # a beacon
        self.book.observe("heard", 1600.0, {"direction": "RX", "from": "Q1AA", "text": "long beacon", "dial_khz": 7105.0, "snr_db": -20})  # a long beacon ten minutes later
        self.book.observe("heard", 1601.0, {"direction": "RX", "from": "Q1AA", "text": "ack", "dial_khz": 7105.0})  # an acknowledgment: not a row of its own
        self.book.observe("message", 1700.0, {"direction": "RX", "from": "Q1AA", "to": "Q2BB", "text": "hello", "dial_khz": 7105.0})  # a message
        self.book.observe("broadcast", 1800.0, {"direction": "RX", "from": "Q1AA", "to": "ALL", "text": "QST", "dial_khz": 7105.0})  # a bulletin to everyone
        self.assertEqual(self.what(), ["beacon", "long beacon", "message", "broadcast"])  # four rows
        self.assertEqual(len(self.book["Q1AA"]["history"]), 1)  # still one merged session
        self.assertEqual(self.book["Q1AA"]["history"][0]["msgs_in"], 2)  # the broadcast counts as a message in
        self.assertEqual(self.book["Q1AA"]["log"][2]["text"], "hello")  # the words are kept

    def test_long_note_named(self):  # a long note says what it was
        self.book.observe("message", 1000.0, {"direction": "RX", "from": "Q1AA", "to": "Q2BB", "text": "a long one", "long_note": True})  # a long note
        self.assertEqual(self.what(), ["long note"])  # named for what it was

    def test_telemetry_one_row(self):  # telemetry arrives as a message and then as telemetry: one row
        text = "Q1AA TLM1 FM05 P50 N0"  # a telemetry message
        self.book.observe("message", 1000.0, {"direction": "RX", "from": "Q1AA", "to": "Q2BB", "text": text})  # as a message
        self.book.observe("telemetry", 1000.5, {"direction": "RX", "from": "Q1AA", "text": text})  # then as telemetry
        self.assertEqual(self.what().count("telemetry"), 1)  # one telemetry row
        self.assertNotIn("message", self.what())  # and not a second row for the same words

    def test_learns_radio_and_power(self):  # the record fills in from the station's own message
        self.book.observe("message", 1000.0, {"direction": "RX", "from": "Q1AA", "to": "Q2BB", "text": "Q1AA HANK FM05 RIG FT-991A 50W"})  # it says what it runs
        self.assertEqual(self.book["Q1AA"]["radio"], "FT-991A")  # the radio
        self.assertEqual(self.book["Q1AA"]["power_w"], "50")  # the watts
        self.assertEqual(self.book.learned, [("Q1AA", {"radio": "FT-991A", "power_w": "50"})])  # news for the panel
        self.assertEqual(self.what()[-1], "details")  # and a row saying so

    def test_learns_power_from_telemetry(self):  # telemetry carries the power
        self.book.observe("telemetry", 1000.0, {"direction": "RX", "from": "Q1AA", "text": "Q1AA TLM1 FM05 P25 N0"})  # 25 watts
        self.assertEqual(self.book["Q1AA"]["power_w"], "25")  # learned

    def test_unsaved_station_not_logged(self):  # only saved contacts get a log
        self.book.observe("heard", 1000.0, {"direction": "RX", "from": "Q3CC", "text": "beacon"})  # a stranger
        self.assertNotIn("Q3CC", self.book)  # not added

    def test_seeding_from_heard_log(self):  # receptions from before the station was saved
        rows = [{"t": 900.0, "dir": "RX", "what": "beacon"}, {"t": 950.0, "dir": "RX", "what": "beacon"}]  # two earlier receptions
        self.assertEqual(self.book.add_log("Q1AA", rows), 2)  # both added
        self.assertEqual(self.book.add_log("Q1AA", rows), 0)  # and not twice

    def test_log_survives_reload(self):  # kept in the file
        self.book.observe("heard", 1000.0, {"direction": "RX", "from": "Q1AA", "text": "beacon"})  # a beacon
        again = ContactBook(self.book.path)  # read the file back
        self.assertEqual([row["what"] for row in again["Q1AA"]["log"]], ["beacon"])  # still there


if __name__ == "__main__":  # run directly
    unittest.main()  # the tests
