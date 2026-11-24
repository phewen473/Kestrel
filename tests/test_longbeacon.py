"""Tests for the long beacon (signal version 0.27): modem/longbeacon.py, its place in the receiver, the listener and the link rules."""

import numpy as np  # numerical arrays


def test_long_beacon_shape():  # the numbers in the specification
    from modem import longbeacon  # the long beacon
    from modem.params import FS  # 12,000 samples per second

    assert longbeacon.TOTAL_TONES == 51  # 12 pattern tones and 39 body tones (36 data, 3 pilots)
    assert abs(longbeacon.SECONDS - 59.5) < 0.01  # just under a minute
    assert len(longbeacon.build_long_beacon("Q1AAAA", "EM93")) == longbeacon.SAMPLES == round(59.5 * FS)  # the audio is exactly that long
    spacing = longbeacon.LONG.step * longbeacon.LONG.bin_hz  # how far apart the tones are
    assert abs(spacing - 4.2857) < 0.001 and 32 * spacing < 140  # 4.29 Hz apart (five bins, since signal version 0.38), about 137 Hz for all 32


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
    assert abs(found[0].result.sample - 5 * FS) <= 30  # where it began, to within 30 samples (0.2% of one of its 14,000-sample tones; the incremental search of 0.31 times it from a slightly different coarse grid than the whole-store search did)


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


def _hear(audio, combiner=None, now=0.0):  # one reception through the long-beacon receiver
    """Return (fields or None, copies) for `audio`: alone first, then with `combiner`'s kept copies."""
    from modem import longbeacon  # the long beacon

    audio = longbeacon.clean(audio)  # steady carriers removed, as the receiver does
    for found in longbeacon.candidates(audio):  # the long pattern's best candidates
        soft = longbeacon.soft_at(audio, found)  # measure the body
        if soft is None:  # not all inside the audio
            continue  # skip it
        fields, _ = longbeacon.decode_energies(soft.energies)  # alone
        if fields is not None:  # decoded alone
            return fields, 1  # done
        out = combiner.offer(soft, now + found["start"] / 12000.0) if combiner is not None else None  # with earlier copies
        if out is not None:  # decoded together
            return out[0], out[2]  # done
    return None, 0  # nothing


def test_copies_that_fail_alone_decode_when_added_together():  # receiver version 0.28: combining repeats
    from modem import longbeacon  # the long beacon and its combiner
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(28)  # repeatable noise
    sent = longbeacon.build_long_beacon("Q1AAAA", "EM93")  # the beacon a station repeats
    combiner, decoded, alone = longbeacon.LongCombiner(), [], 0  # the memory, what decoded and how many decoded alone
    for copy in range(4):  # four rounds, ten minutes apart
        heard = run_channel(sent, -29.0, rng, offset_hz=7.0 + 0.3 * copy, lead_s=3.0, tail_s=3.0)  # 3.4 dB below where a single copy always decodes, drifting a little
        fields, copies = _hear(heard, combiner, 600.0 * copy)  # give it to the receiver
        alone += copies == 1  # count single decodes
        if fields is not None and copies > 1:  # decoded by adding copies
            decoded.append((fields["origin"], fields["grid"], copies))  # note it
    assert alone == 0  # no copy was readable alone
    assert decoded and decoded[0][:2] == ("Q1AAAA", "EM93")  # but together they were, and correctly


def test_combiner_does_not_add_copies_on_different_frequencies():  # two stations' beacons are never added together
    from modem import longbeacon  # the long beacon and its combiner
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(4)  # repeatable noise
    combiner = longbeacon.LongCombiner()  # the memory
    for copy, offset in enumerate((-20.0, 0.0, 20.0, -10.0)):  # the same beacon, but 10 Hz or more apart each time
        fields, copies = _hear(run_channel(longbeacon.build_long_beacon("Q1AAAA", "EM93"), -29.0, rng, offset_hz=offset, lead_s=3.0, tail_s=3.0), combiner, 600.0 * copy)  # give it to the receiver
        assert copies != 2 and copies != 3 and copies != 4  # never combined


def test_long_beacon_survives_a_carrier_inside_its_band():  # a steady carrier 10 dB stronger than the beacon, on one of its tones
    from modem import longbeacon  # the long beacon
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(6)  # repeatable noise
    sent = longbeacon.build_long_beacon("Q1AAAA", "EM93")  # the beacon
    heard = run_channel(sent, -22.0, rng, offset_hz=1.0, lead_s=3.0, tail_s=3.0)  # a weak beacon
    carrier = np.sqrt(2 * np.mean(sent ** 2)) * 10 ** (10 / 20) * np.cos(2 * np.pi * 1503.0 * np.arange(len(heard)) / 12000.0)  # a carrier at 1503 Hz, 10 dB above it
    fields, _ = _hear(heard + carrier)  # receive it
    assert fields is not None and fields["origin"] == "Q1AAAA"  # still read


def test_listener_adds_up_two_weak_long_beacons():  # the continuous receiver keeps the copy that failed and reads the pair
    from live.listener import Listener  # the continuous receiver
    from modem.longbeacon import build_long_beacon  # the transmitter
    from modem.params import FS, LONG_LEVEL  # the sample rate and the long beacon's level number
    from sim.channel import add_noise  # noise at a chosen SNR

    rng = np.random.default_rng(13)  # repeatable noise
    sent = build_long_beacon("Q1AAAA", "EM93")  # the beacon
    quiet = np.zeros(int(240 * FS))  # four minutes
    for begin in (5, 140):  # two copies, 135 seconds apart (a test's stand-in for ten minutes)
        quiet[begin * FS:begin * FS + len(sent)] += sent  # put it in
    audio = add_noise(quiet, -28.5, float(np.mean(sent ** 2)), rng)  # at -28.5 dB, where one copy alone rarely decodes (and with this noise, neither does)
    listener, found = Listener(step_s=2.0), []  # a receiver that searches every two seconds (to keep the test short)
    for begin in range(0, len(audio), FS):  # one second at a time
        found += listener.feed(audio[begin:begin + FS])  # feed it
    assert len(found) == 1 and found[0].result.level == LONG_LEVEL and found[0].result.ok  # one long beacon came out
    assert found[0].result.origin == "Q1AAAA" and found[0].result.fields["copies"] == 2  # read from the two copies together
