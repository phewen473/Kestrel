"""Tests for the long beacon (signal version 0.27): modem/longbeacon.py, its place in the receiver, the listener and the link rules."""

import numpy as np  # numerical arrays


def test_long_beacon_shape():  # the numbers in the specification
    from modem import longbeacon  # the long beacon
    from modem.params import FS  # 12,000 samples per second

    assert longbeacon.TOTAL_TONES == 51  # 12 pattern tones and 39 body tones (36 data, 3 pilots)
    assert abs(longbeacon.SECONDS - 59.5) < 0.01  # just under a minute
    assert len(longbeacon.build_long_beacon("Q1AAAA", "EM93")) == longbeacon.SAMPLES == round(59.5 * FS)  # the audio is exactly that long
    spacing = longbeacon.LONG.step * longbeacon.LONG.bin_hz  # how far apart the tones are
    assert abs(spacing - 2.571) < 0.001 and 32 * spacing < 85  # 2.57 Hz apart, about 82 Hz for all 32


def test_long_beacon_round_trip_in_weak_noise():  # sent, heard well below L0's limit, and read back exactly
    from modem import receive  # the full receiver, every level and the long pattern
    from modem.longbeacon import build_long_beacon  # the transmitter
    from modem.params import FRAME_TYPE_LONG, LONG_LEVEL  # how the receiver reports it
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(27)  # repeatable noise
    heard = run_channel(build_long_beacon("Q1AAAA", "EM93", available=False, holds_mail=True), -24.0, rng, offset_hz=1.5, lead_s=4.0, tail_s=2.0)  # 3 dB under L0's steady limit, 1.5 Hz off
    result = receive(heard)  # decode it
    assert result.ok and result.level == LONG_LEVEL and result.frame_type == FRAME_TYPE_LONG  # a long beacon
    assert result.origin == "Q1AAAA" and result.fields["grid"] == "EM93"  # from the right station and place
    assert result.fields["available"] is False and result.fields["holds_mail"] is True  # with its flags
    assert abs(result.snr_db - (-24.0)) < 2.0 and abs(result.offset_hz - 1.5) < 0.5  # measured close to the truth


def test_ordinary_frames_still_decode_beside_the_long_search():  # the long pattern must not get in the way
    from modem import build_beacon, build_frame, receive  # the transmitter and receiver
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(3)  # repeatable noise
    for level in (0, 2, 4):  # slow, middle and fast
        assert receive(run_channel(build_beacon("Q2BB", "FN31", level=level), -6.0, rng)).ok  # a beacon
    assert receive(run_channel(build_frame("Q1AAAA DE Q2BB", 3), -6.0, rng)).text == "Q1AAAA DE Q2BB"  # a message


def test_listener_hands_over_a_long_beacon_once():  # the continuous receiver
    from live.listener import Listener  # the continuous receiver
    from modem.longbeacon import build_long_beacon  # the transmitter
    from modem.params import FS, LONG_LEVEL  # the sample rate and the long beacon's level number

    rng = np.random.default_rng(9)  # repeatable noise
    audio = rng.standard_normal(80 * FS) * 0.02  # eighty seconds of noise
    audio[5 * FS:5 * FS + int(59.5 * FS)] += build_long_beacon("Q1AAAA", "EM93") * 0.02  # a long beacon in it, at about -10 dB
    listener, found = Listener(), []  # a receiver and what it finds
    for begin in range(0, len(audio), FS):  # one second at a time
        found += listener.feed(audio[begin:begin + FS])  # feed it
    assert len(found) == 1 and found[0].result.level == LONG_LEVEL  # handed over once
    assert abs(found[0].result.sample - 5 * FS) <= 4  # where it began


def test_long_beacon_is_sent_once_and_never_answered():  # the link rules: nobody replies to a long beacon
    from link import Station  # the link rules
    from modem import receive  # the receiver
    from modem.params import LONG_LEVEL  # the long beacon's level number

    sender = Station("Q1AAAA", "EM93")  # the station sending it
    sender.listen()  # listening, as the panel's stations are
    sender.long_beacon()  # ask for one
    tx = sender.poll(0.0)  # the station sends it at its next look
    assert tx is not None and tx.kind == "long beacon" and tx.level == LONG_LEVEL and abs(tx.seconds - 59.5) < 0.01  # the long beacon
    assert sender.poll(1.0) is None  # nothing else follows, and it waits for no reply
    hearer = Station("Q2BB", "FN31")  # a station that hears it
    hearer.listen()  # listening
    hearer.answer_beacons = hearer.answer_calls = True  # even one set to answer everything by itself
    result = receive(np.concatenate([np.zeros(12000), tx.audio, np.zeros(12000)]))  # it decodes the long beacon
    assert result.ok and result.origin == "Q1AAAA"  # heard
    assert hearer.handle(result, 70.0) is None  # and does not reply
