"""Tests for 0.35: the Doppler-spread reading, the fast-fading level table, the band-activity and ionosonde helpers, and the PSK Reporter datagram."""

import struct  # reading the datagram back

import numpy as np  # arrays


def test_spread_reading_matches_the_channel():  # an L0 frame through 1 Hz of spread reads about 1 Hz; a steady one about 0
    from modem import build_frame, receive  # the transmitter and receiver
    from sim.channel import _analytic, add_noise, watterson  # the channel's parts

    audio = build_frame("SPREAD TEST " * 4, 0)  # an L0 message
    y = np.concatenate([np.zeros(12000), audio, np.zeros(12000)])  # silence either side
    for spread, low, high, seed in ((0.0, 0.0, 0.15, 1), (1.0, 0.7, 1.4, 2)):  # steady, then spread
        rng = np.random.default_rng(seed)  # repeatable
        a = _analytic(y)  # complex form
        if spread:  # fading wanted
            a = watterson(a, spread, 0.0, rng, second_db=-60.0)  # one path in practice
        x = add_noise(a.real, 10.0, float(np.mean(audio ** 2)), rng)  # a strong signal
        r = receive(x, long_beacons=False)  # read it
        assert r.ok and low <= r.spread_hz <= high, (spread, r.spread_hz)  # read as about the true spread


def test_fast_fading_table_needs_every_reading_fast():  # one slow or unread frame keeps the careful table
    from link.adapt import supported_level  # the rule

    allowed = [0, 1, 2, 3, 4]  # every level
    slow = [(-12.5, 0.5, 0.2)] * 3  # fading, slow
    fast = [(-12.5, 0.5, 1.0)] * 3  # fading, fast
    assert supported_level(slow, allowed) == 1  # -12.5 dB in slow fading: L1 from -14, L2 only from -12 (the next-frame tables of 0.43)
    assert supported_level(fast, allowed) == 2  # in fast fading L2 from -13
    assert supported_level(fast[:2] + [(-12.5, 0.5, float("nan"))], allowed) == 1  # one unread spread: careful again
    assert supported_level([(-12.5, 0.5)] * 3, allowed) == 1  # two-value readings (older callers) keep the general fading table


def test_short_path_muf_and_nearest_sounding():  # the secant law, and which sounding is used
    import time  # clocks
    from live import skywatch as sw  # the helpers

    assert abs(sw.short_path_muf(5.0, 300.0, 0.0) - 5.0) < 1e-9  # straight up: foF2
    assert abs(sw.short_path_muf(5.0, 300.0, 600.0) - 5.0 * np.sqrt(2.0)) < 1e-9  # 600 km at 300 km height: 45 degrees
    now = time.time()  # now
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 600))  # ten minutes ago, UTC
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 7200))  # two hours ago
    soundings = [{"fof2": 7.0, "cs": 90, "hmf2": 280, "time": stamp, "station": {"name": "Near", "latitude": "33.0", "longitude": "279.0"}},  # near, fresh
                 {"fof2": 7.0, "cs": 90, "hmf2": 280, "time": old, "station": {"name": "Stale", "latitude": "33.5", "longitude": "279.0"}},  # nearer, stale
                 {"fof2": 8.0, "cs": 90, "hmf2": 280, "time": stamp, "station": {"name": "Far", "latitude": "-3.0", "longitude": "299.0"}}]  # fresh, far
    w = sw.nvis_window("EM93", "EM95", bands={"80 m": 3.584, "40 m": 7.11, "20 m": 14.114}, soundings=soundings, now=now)  # the window
    assert w["station"] == "Near" and w["open"] == ["80 m", "40 m"] and w["closed"] == ["20 m"]  # the fresh near one: 80 and 40 m open
    assert sw.nvis_window("EM93", None, soundings=soundings[1:2], now=now) is None  # only a stale one: unknown


def test_wspr_query_asks_both_ways_and_the_bands():  # the SQL
    from live import skywatch as sw  # the helpers

    q = sw.wspr_query((33.5, -81.0), (41.5, -73.0))  # Southeast to Northeast
    assert "INTERVAL 60 MINUTE" in q and "band IN (3, 7, 10, 14, 18, 21, 28, 50)" in q and q.count("greatCircleDistance") == 4  # last hour, Kestrel's bands, both ends both ways
    assert sw.busiest({"40 m": (10, -15.0, -5.0)}, {"20 m": 3, "40 m": 1}) == "40 m"  # the band with the most spots


def test_prediction_check_summary(tmp_path, monkeypatch):  # the record and its summary
    from live import propcheck  # the check

    monkeypatch.setattr(propcheck, "record_file", lambda: str(tmp_path / "prop_check.csv"))  # a private record
    assert propcheck.summary() == (0, None, None)  # nothing yet
    import time  # clocks
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())  # now
    for heard, predicted in ((-10.0, -14.0), (-20.0, -18.0)):  # two stations
        propcheck._write({"utc": stamp, "call": "Q2BB", "band": "40 m", "from_grid": "FN31", "to_grid": "EM93", "miles": 700, "heard_snr_db": heard, "predicted_snr_db": predicted,
                          "predicted_reliability": 80, "ssn": 34, "ssn_source": "test"})  # written
    n, bias, err = propcheck.summary()  # the figures
    assert n == 2 and abs(bias - 1.0) < 1e-9 and abs(err - 3.0) < 1e-9  # +4 and -2: on average +1, typically 3 apart
    assert "2 stations heard" in propcheck.describe_summary()  # said


def test_psk_reporter_datagram_shape():  # the IPFIX message holds what PSK Reporter expects
    from live import pskspot  # the spotter

    d = pskspot.datagram("Q1AAAA", "EM93", "0.35", [("Q2BB", 7112000, -12, "FN31", 1795500000)], 7, 0x1234, True, now=1795500100)  # one spot, with descriptions
    version, length, when, seq, domain = struct.unpack("!HHIII", d[:16])  # the header
    assert (version, length, when, seq, domain) == (10, len(d), 1795500100, 7, 0x1234)  # as built
    at, ids = 16, []  # walk the sets
    while at < len(d):  # each set
        set_id, set_len = struct.unpack("!HH", d[at:at + 4])  # its id and length
        assert set_len >= 4 and set_len % 4 == 0 or set_id in (2, 3)  # data sets padded to four bytes
        ids.append(set_id)  # noted
        at += set_len  # next
    assert at == len(d) and ids == [3, 2, pskspot.RX_TEMPLATE, pskspot.TX_TEMPLATE]  # the two descriptions, this station, the spot
    s = pskspot.Spotter("Q1AAAA", "EM93", "0.35")  # a spotter (nothing is sent in this test)
    assert s.add("Q2BB", 7112000, -12) and s.add("Q2BB", 7112000, -10)  # queued, then replaced by the newer spot
    s.reported["Q2BB"] = __import__("time").time()  # as if just sent
    s.pending.clear()  # nothing waiting
    assert not s.add("Q2BB", 7112000, -10)  # not again within five minutes
    assert not pskspot.Spotter("", "EM93", "0.35").add("Q2BB", 7112000, -12)  # nothing without this station's callsign
