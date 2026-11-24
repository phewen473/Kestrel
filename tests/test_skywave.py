"""Tests for the sky-wave work of 0.34R1: the realistic channel conditions, the long frame's three-bin reading, and the space-weather parsing."""

import numpy as np  # numerical arrays


def test_unequal_shifted_second_path_keeps_power():  # the channel's new second-path options
    from sim.channel import FS, watterson  # the two-path model

    rng = np.random.default_rng(5)  # repeatable
    a = np.exp(2j * np.pi * 1500 * np.arange(20 * FS) / FS)  # a steady tone, power 1
    out = watterson(a, 0.3, 0.8, rng, FS, second_db=-4.0, shift2_hz=0.2)  # the realistic NVIS case
    assert 0.5 < float(np.mean(np.abs(out) ** 2)) < 2.0  # average power about unchanged (fading makes it wander)


def test_realistic_conditions_run():  # the named conditions work end to end
    from sim import run_channel  # the channel simulator

    rng = np.random.default_rng(6)  # repeatable
    for name in ("nvis_real", "dawn"):  # the two additions
        y = run_channel(np.sin(np.arange(FS_ := 12000) * 0.5), 0.0, rng, name)  # one second of a tone through it
        assert len(y) == FS_ + 2 * 12000 and np.all(np.isfinite(y))  # padded and sane


def test_smeared_long_beacon_reads_with_three_bins():  # 3 Hz of Doppler spread: the center bin alone fails, the three-bin reading succeeds
    from modem.frame import RxResult  # a report to fill
    from modem import longbeacon  # the long frame
    from sim.channel import _analytic, add_noise, watterson  # the channel's parts

    rng = np.random.default_rng(11)  # repeatable
    audio = longbeacon.build_long_beacon("Q1AAAA", "EM93")  # the frame
    y = np.concatenate([np.zeros(12000), audio, np.zeros(12000)])  # silence either side
    faded = watterson(_analytic(y), 3.0, 1.0, rng).real  # badly smeared
    heard = add_noise(faded, -16.0, float(np.mean(audio ** 2)), rng)  # a fair signal
    found = {"start": 12000, "offset_hz": 0.0, "quality": 10.0}  # where it is
    soft = longbeacon.soft_at(heard, found)  # measured both ways
    assert soft.wide is not None and soft.wide.shape == soft.energies.shape  # both readings kept
    fields, _ = longbeacon.decode_soft(soft.energies, soft.wide)  # center first, then three bins
    assert fields is not None and fields["origin"] == "Q1AAAA"  # read


def test_space_weather_parsing_and_warnings():  # the sources' shapes, and what is warned about
    from live import spaceweather as sw  # the module

    essn = {"24h": [{"time": 100, "ssn": 50.0, "sfi": 100.0}, {"time": 200, "ssn": 60.0, "sfi": 110.0}], "6h": [{"time": 200, "ssn": 40.0, "sfi": 90.0}]}  # KC2G's shape
    assert sw.essn_from(essn) == (60.0, 40.0, 200)  # the newest of each
    scales = {"0": {"R": {"Scale": "2"}, "S": {"Scale": "0"}, "G": {"Scale": None}}}  # NOAA's shape
    assert sw.scales_from(scales) == (2, 0)  # R2, G0
    assert sw.kp_from([{"time_tag": "x", "kp_index": 5, "estimated_kp": 5.33}]) == 5.33  # records
    assert sw.kp_from([["time_tag", "Kp"], ["2026-11-24 00:00:00", "3.67"]]) == 3.67  # the older table shape
    answer = {"fetched": 0, "essn_24h": 60.0, "essn_6h": 40.0, "kp": 6.0, "r_scale": 2, "g_scale": 2}  # a bad day
    text = " ".join(sw.warnings(answer))  # its warnings
    assert "R2" in text and "Kp 6.0" in text and "weakening" in text  # all three
    assert sw.warnings({"fetched": 0, "essn_24h": 60.0, "essn_6h": 58.0, "kp": 1.0, "r_scale": 0}) == []  # a quiet day


def test_measured_ssn_only_for_the_current_month(tmp_path, monkeypatch):  # the measured number never replaces another month's prediction
    import json  # writes the saved answer
    import time  # clocks
    from live import spaceweather as sw  # the module

    monkeypatch.setattr(sw, "saved_file", lambda: str(tmp_path / "spaceweather.json"))  # a private file
    now = time.time()  # now
    (tmp_path / "spaceweather.json").write_text(json.dumps({"fetched": now - 60, "essn_24h": 33.0}))  # fresh
    today = time.gmtime(now)  # this month
    value, how = sw.ssn_for(today.tm_year, today.tm_mon, now)  # this month
    assert value == 33.0 and how.startswith("measured")  # measured
    later = (today.tm_year + (today.tm_mon // 12), today.tm_mon % 12 + 1)  # next month
    assert not sw.ssn_for(*later, now)[1].startswith("measured")  # predicted
    assert sw.current(now + sw.STALE_S + 1) is None  # old answers are not used
