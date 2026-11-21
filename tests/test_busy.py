"""Tests for listening before transmitting: live/busy.py and the station's hold rule (spec Section 6.14)."""

import numpy as np  # numerical arrays


def test_watch_says_clear_on_noise_and_busy_on_a_signal():  # the channel watch itself
    from live.busy import ChannelWatch, band_of  # the watch, and the band a level occupies
    from modem import build_beacon  # a signal to hear
    from modem.params import FS  # 12,000 samples per second

    rng = np.random.default_rng(2)  # repeatable noise
    watch = ChannelWatch()  # a fresh watch
    assert not watch.busy()  # with no history it does not hold the station up
    for _ in range(60):  # a minute of band noise
        watch.feed(rng.standard_normal(FS) * 0.05)  # one second at a time
        assert not watch.busy()  # never mistaken for a signal
    beacon = build_beacon("Q2BB", "FN31", level=2)  # another station's beacon, about 7 seconds
    scale = np.sqrt(0.05 ** 2 * 2500 / 6000 * 10 ** (-8 / 10) / np.mean(beacon ** 2))  # at -8 dB in 2.5 kHz
    heard = rng.standard_normal(len(beacon)) * 0.05 + scale * beacon  # as received
    for begin in range(0, 4 * FS, FS):  # the first four seconds of it
        watch.feed(heard[begin:begin + FS])  # one second at a time
    assert watch.busy(*band_of(2))  # in use where an L2 frame would go
    assert not watch.busy(2500.0, 2800.0)  # but clear well away from it
    for _ in range(4):  # the beacon ends; four seconds of noise
        watch.feed(rng.standard_normal(FS) * 0.05)  # one second at a time
    assert not watch.busy(*band_of(2))  # clear again


def test_station_holds_a_beacon_while_the_frequency_is_in_use():  # the link rule
    from link import Station  # the link rules

    in_use = [True]  # whether the frequency is in use (the test's stand-in for the watch)
    station = Station("Q1AAAA", "EM93")  # a station
    station.listen()  # listening
    station.busy = lambda level: in_use[0]  # its listen-first check
    station.beacon_once()  # the operator asks for a beacon
    assert station.poll(0.0) is None and station.poll(5.0) is None  # held while the frequency is in use
    assert any("frequency in use" in line for line in station.log)  # and the operator is told why
    in_use[0] = False  # the other signal ends
    tx = station.poll(6.0)  # the next look
    assert tx is not None and tx.kind == "beacon"  # the beacon goes
    assert any("frequency clear" in line for line in station.log)  # and the log says so


def test_replies_are_never_held():  # an answer in its reply slot must go on time
    from link import Station  # the link rules
    from modem import build_beacon, receive  # a beacon to answer

    station = Station("Q1AAAA", "EM93")  # a station
    station.listen()  # listening
    station.answer_beacons = True  # set to answer beacons by itself
    station.busy = lambda level: True  # the check says the frequency is always in use
    result = receive(np.concatenate([np.zeros(6000), build_beacon("Q2BB", "FN31", level=2), np.zeros(6000)]))  # a beacon is heard
    reply = station.handle(result, 10.0)  # the link rules answer it
    assert reply is not None and reply.kind == "answer"  # at once, whatever the check says
