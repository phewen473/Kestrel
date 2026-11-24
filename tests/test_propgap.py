"""Tests: each station's measured SNR against the P.533 prediction, both ways, and what the gap points to (since 0.39)."""
import csv  # the record
import os  # paths

from live import propcheck  # what is tested


def _rows(path, rows):  # write a record by hand
    with open(path, "w", newline="", encoding="utf-8") as handle:  # the file
        writer = csv.DictWriter(handle, fieldnames=propcheck.COLUMNS)  # the present columns
        writer.writeheader()  # heading
        for row in rows:  # each line
            writer.writerow({name: row.get(name, "") for name in propcheck.COLUMNS})  # written


def test_transmit_side_short(tmp_path, monkeypatch):  # the case seen on the air: they hear us far worse than predicted
    path = os.path.join(tmp_path, "prop_check.csv")  # a scratch record
    monkeypatch.setattr(propcheck, "record_file", lambda: path)  # used instead of the operator's
    _rows(path, [{"utc": "2099-01-01 17:53", "call": "Q1AA", "heard_snr_db": "9", "predicted_snr_db": "20", "direction": "in"},  # we hear them 11 dB short
                 {"utc": "2099-01-01 17:53", "call": "Q1AA", "heard_snr_db": "-11", "predicted_snr_db": "14", "direction": "out"}])  # they hear us 25 dB short
    gaps = propcheck.station_gaps("Q1AA")  # both ways (lines dated 2099 are inside any window ending now)
    assert round(gaps["in"][1]) == -11 and round(gaps["out"][1]) == -25  # the two gaps
    assert "your transmit side" in propcheck.verdict(gaps)  # points at this station's sending
    line = propcheck.describe_station("Q1AA")  # the line shown
    assert "heard here +9 dB (predicted +20; 11 dB short" in line and "they hear you -11 dB (predicted +14; 25 dB short" in line  # both ways in words


def test_both_short_points_at_the_path():  # the same shortfall both ways
    gaps = {"in": (2, -15.0, {}), "out": (2, -13.0, {})}  # both well short, by about the same
    assert "the path itself" in propcheck.verdict(gaps)  # not one station
    assert propcheck.verdict({"in": (1, -3.0, {})}) == ""  # close to the prediction: nothing said
    assert "other way" in propcheck.verdict({"in": (1, -14.0, {})})  # one way known, well short


def test_old_record_upgraded(tmp_path, monkeypatch):  # a prop_check.csv from before 0.39
    path = os.path.join(tmp_path, "prop_check.csv")  # a scratch record
    monkeypatch.setattr(propcheck, "record_file", lambda: path)  # used instead of the operator's
    old = propcheck.COLUMNS[:11]  # the columns before 0.39
    with open(path, "w", newline="", encoding="utf-8") as handle:  # the old file
        writer = csv.writer(handle)  # plain rows
        writer.writerow(old)  # its heading
        writer.writerow(["2099-01-01 10:00", "Q2BB", "40 m", "EM94", "EM93", "69", "-5", "10", "100", "80", "predicted"])  # one old line
    propcheck._write({"utc": "2099-01-01 11:00", "call": "Q2BB", "band": "40 m", "heard_snr_db": -12, "predicted_snr_db": 12, "direction": "out", "power_w": 14})  # a new line
    with open(path, newline="", encoding="utf-8") as handle:  # read back
        rows = list(csv.DictReader(handle))  # every line
    assert tuple(rows[0].keys()) == propcheck.COLUMNS and rows[0]["direction"] == "in" and rows[1]["direction"] == "out"  # upgraded, old line marked "in"
    assert propcheck.summary()[0] == 1  # the overall figure still counts stations heard here only
