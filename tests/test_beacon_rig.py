"""Tests: the beacon carries the station's rig type (Hamlib model number) and watts (signal version 0.40), and contact records fill in from beacons and after contacts."""
import os  # paths

import numpy as np  # arrays

from modem import control, native  # the beacon's fields, and the compiled library
from modem.frame import build_beacon, control_seconds, receive  # the transmitter, frame lengths and the receiver
from modem.params import CONTROL_BITS, FRAME_TYPE_BEACON  # the beacon's size and type


def test_beacon_is_101_bits_and_round_trips():  # the layout, both ways (compiled and Python)
    assert CONTROL_BITS[FRAME_TYPE_BEACON] == 101  # 75 before 0.40, plus 16 for the rig and 10 for the watts
    bits = control.pack_beacon("Q1AA", "EM93", (0, 1, 2, 3, 4), rig="1035  Yaesu FT-991", watts=39.4)  # a beacon (the rig as Settings keeps it)
    assert len(bits) == 101  # its length
    fields = control.unpack(FRAME_TYPE_BEACON, bits)  # read back (compiled when the library is in use)
    assert fields["rig"] == 1035 and fields["watts"] == 39 and fields["origin"] == "Q1AA" and fields["grid"] == "EM93"  # what it carries
    saved, native._lib = native._lib, None  # the pure Python reference
    try:  # always put the library back
        assert np.array_equal(control.pack_beacon("Q1AA", "EM93", (0, 1, 2, 3, 4), rig=1035, watts=39), bits)  # the same bits from Python
        assert control.unpack(FRAME_TYPE_BEACON, bits) == fields  # and the same fields
    finally:  # back
        native._lib = saved  # the library again


def test_unknown_and_out_of_range():  # 0 means not said; values are held to the fields
    assert control.beacon_rig("") == 0 and control.beacon_rig("NO RIG") == 0 and control.beacon_rig(70000) == 0  # nothing, words, too large
    assert control.beacon_watts(None) == 0 and control.beacon_watts(1500) == 1023 and control.beacon_watts(-5) == 0  # nothing, too high, below zero


def test_beacon_over_the_air():  # sent and decoded at L2
    audio = build_beacon("Q1AA", "EM93", level=2, rig=1035, watts=100)  # a beacon
    assert abs(len(audio) / 12000 - control_seconds(FRAME_TYPE_BEACON, 2)) < 0.05  # as long as the timing tables say
    x = np.concatenate([np.zeros(6000), audio, np.zeros(6000)]) + np.random.default_rng(40).normal(0, 0.002, len(audio) + 12000)  # with a little noise
    result = receive(x)  # read
    assert result.ok and result.fields["rig"] == 1035 and result.fields["watts"] == 100  # what it carries


def test_contact_record_from_beacon_and_antenna(tmp_path):  # the contact book
    from live.contacts import ContactBook  # the book
    book = ContactBook(os.path.join(tmp_path, "contacts.json"))  # a scratch book
    book.put("Q1AA", name="Hank")  # a saved contact
    assert book.from_beacon("Q1AA", "Yaesu FT-991 (Hamlib 1035)", 39) == {"radio": "Yaesu FT-991 (Hamlib 1035)", "power_w": "39"}  # filled in
    assert book.from_beacon("Q1AA", "Yaesu FT-991 (Hamlib 1035)", 39) == {}  # the same again: nothing new
    assert book.from_beacon("Q9ZZ", "X", 5) == {}  # not saved: nothing kept
    book.observe("message", 1000.0, {"direction": "RX", "from": "Q1AA", "to": "Q0ZZ", "text": "ANT Vertical (ground-mounted)"})  # its antenna, after a contact
    assert book["Q1AA"]["antenna"] == "Vertical (ground-mounted)"  # filled in
    assert [row["text"] for row in book["Q1AA"]["log"] if row["what"] == "details"][-1] == "after the contact: antenna Vertical (ground-mounted)"  # and logged
    assert book.antenna_to_send("Q1AA", "Dipole") and not book.antenna_to_send("Q1AA", "")  # not sent yet; nothing chosen sends nothing
    book.antenna_sent("Q1AA", "Dipole")  # sent
    assert not book.antenna_to_send("Q1AA", "Dipole") and book.antenna_to_send("Q1AA", "Yagi")  # once, until it changes
