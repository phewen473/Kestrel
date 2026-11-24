"""Tests for the propagation predictions (live/propagation.py) and the sunspot prediction sets (live/sunspots.py), since 0.32."""

import json  # writes test files

import pytest  # test framework

from live import propagation, sunspots  # the modules tested


@pytest.fixture
def folder(tmp_path, monkeypatch):  # a private data folder for each test
    monkeypatch.setattr(sunspots, "data_dir", lambda: str(tmp_path))  # the operator's folder is a temporary one
    return tmp_path  # for the test to use


def a_set(issued, months, kind=sunspots.KIND):  # a prediction set
    return {"kind": kind, "issued": issued, "source": "test", "months": months}  # as the files hold it


def test_bundled_set_is_present_and_valid():  # the program ships a table
    data = sunspots.read(sunspots.BUNDLED)  # read and check it
    assert data["source"].startswith("NOAA") and len(data["months"]) >= 24  # NOAA's, at least two years


def test_ssn_inside_and_outside_the_set():  # which value is used for a month
    table = a_set("2026-11-01", {"2026-11": 80.0, "2026-12": 82.0, "2027-02": 70.0})  # a set with a gap
    assert sunspots.ssn_for(2026, 11, table) == (80.0, "predicted")  # inside
    assert sunspots.ssn_for(2026, 1, table)[0] == 80.0 and "before" in sunspots.ssn_for(2026, 1, table)[1]  # before it: the first value
    assert sunspots.ssn_for(2030, 1, table)[0] == 70.0 and "after" in sunspots.ssn_for(2030, 1, table)[1]  # after it: the last
    assert sunspots.ssn_for(2027, 1, table)[0] == 82.0  # in a gap: the month before


def test_bad_sets_are_refused(folder):  # files that are not usable
    for bad in (a_set("2026-11-01", {"2026-11": 80.0}, kind="other"), a_set("not a date", {"2026-11": 80.0}), a_set("2026-11-01", {}), a_set("2026-11-01", {"2026-11": -5.0}), a_set("2026-11-01", {"November": 80.0})):  # each kind of fault
        with pytest.raises(ValueError):  # refused
            sunspots.check(bad)  # checked


def test_newest_set_is_used_and_shown(folder):  # an update file with a later date wins
    path = folder / "sunspots-test.json"  # an update file sent to the operator
    path.write_text(json.dumps(a_set("2099-01-01", {"2099-01": 55.0})), encoding="utf-8")  # dated far ahead, so it is the newest
    data = sunspots.import_file(str(path))  # loaded with the button
    assert (folder / "updates" / "sunspots-2099-01-01.json").is_file()  # copied into the updates folder, named by its date
    current = sunspots.current()  # the set in use
    assert current["issued"] == "2099-01-01" and current["file"] == data["file"]  # the newest one
    assert "issued 2099-01-01" in sunspots.describe()  # the panel shows its issue date
    (folder / "updates" / "sunspots-broken.json").write_text("{not json", encoding="utf-8")  # a damaged file beside it
    found, refused = sunspots.candidates()  # every set
    assert any(path.endswith("sunspots-broken.json") for path, _why in refused) and current["issued"] == sunspots.current()["issued"]  # the damaged one is refused, the rest still work


def test_noaa_records_become_a_set():  # an online update's format
    data = sunspots.from_noaa([{"time-tag": "2026-11", "predicted_ssn": 83.2}, {"time-tag": "2026-12", "predicted_ssn": -1}], issued="2026-11-23")  # NOAA writes -1 for none
    assert data["months"] == {"2026-11": 83.2} and data["issued"] == "2026-11-23"  # only real values, dated


TABLE = ("month,hour,frequency,distance,OPMUF,SNR,SNRXXp,BCR,DMidx,DMele,DMtau,DMLb,DMFprob,DMhr,DMPrw,DMGrw,DMEw,DMBMUF\n"  # the program's CSV heading
         "11,1,3.58,111.20,9.45,17.62,2.95,93.66,1F2,79.49,0.00,110.73,1.00,250.46,-91.33,0.00,26.95,7.27\n"  # 80 m, NVIS, strong
         "11,1,7.11,111.20,9.45,-25.0,-30.0,5.0,1F2,79.49,0.00,116.26,0.59,194.01,-96.86,0.00,27.38,7.27\n"  # 40 m, too weak for L0
         "11,14,7.11,1500.0,13.14,9.0,1.0,96.0,2F2,20.0,0.00,117.69,1.00,240.22,-98.29,0.00,25.94,10.95\n")  # 40 m in the afternoon, two hops


def test_table_is_read_and_judged():  # the program's output, made into rows
    bands = {"80 m": 3.584, "40 m": 7.1115}  # two bands
    rows = propagation.parse(TABLE, bands)  # read
    assert [(r["hour"], r["band"]) for r in rows] == [(1, "80 m"), (1, "40 m"), (14, "40 m")]  # hours and bands matched
    assert rows[0]["condition"] == "nvis" and rows[2]["condition"] == "poor"  # steep: NVIS; two hops: several hops
    assert rows[0]["level"] == 4 and rows[1]["level"] is None and rows[2]["level"] is not None  # strong: the fastest level; too weak: none
    assert propagation.best_at(rows, 1)["band"] == "80 m" and propagation.best_at(rows, 5) is None  # the best band at an hour, and none when nothing is known
    assert "80 m" in propagation.suggestion(rows, 1)  # the suggestion names it


def test_input_file_asks_for_kestrels_figures():  # the program's input
    text = propagation.input_text((33.5, -81.0), (34.5, -81.0), 2026, 11, 83, [3.584, 7.1115], 100.0, "RURAL", "data")  # one month, two bands
    assert "Path.BW 2500.0" in text and "Path.txpower -10.00" in text  # 2.5 kHz like every Kestrel figure; 100 W is -10 dB(1 kW)
    assert "Path.hour 1,2,3" in text and text.count("Path.frequency") == 1 and f"Path.SNRr {propagation.REQUIRED_SNR_DB:.1f}" in text  # every hour, the bands, L0's limit with margin


@pytest.mark.skipif(propagation.missing() is not None, reason="the ITU-R P.533 program is not built (tools/build_prop.py)")
def test_a_real_prediction():  # the ITU program itself, when built
    rows = propagation.predict("EM93", "EM94", 2026, 11, 83, 100.0)  # a short path in November
    assert len(rows) == 24 * len(propagation.band_frequencies())  # every hour, every band
    assert all(r["km"] > 40 for r in rows) and all(0 <= r["reliability"] <= 100 for r in rows)  # a sensible path and percentages
    assert any(r["level"] is not None for r in rows)  # some band works some time on a 110-mile path
    with pytest.raises(ValueError):  # a bad grid locator
        propagation.predict("EM93", "ZZ99", 2026, 11, 83)  # refused
