"""Tests of the pieces behind the control panel: telemetry messages, the 48-hour heard log, the logbook and the themes."""

import csv  # reads the logbook's CSV file back
import os  # file paths

from live import heardlog, logbook, telemetry, theme  # the pieces under test


def test_telemetry_round_trip():  # a telemetry message can be read back exactly
    heard = [("Q1AAAA", 5.0, 3), ("Q2BB", -8.4, 1), ("Q3CCC", -15.0, 0)]  # three stations, strongest first
    text = telemetry.build("em92", 50, heard, prefix="Q5EEEE")  # the message, with a callsign in front
    assert text == "Q5EEEE TLM1 EM92 P50 N3 Q1AAAA+05L3 Q2BB-08L1 Q3CCC-15L0"  # the agreed layout
    info = telemetry.parse(text)  # read it back
    assert info == {"grid": "EM92", "power_w": 50.0, "count": 3, "stations": [("Q1AAAA", 5, 3), ("Q2BB", -8, 1), ("Q3CCC", -15, 0)]}  # every value recovered
    assert telemetry.score(info) == (3, -8)  # three heard, median -8 dB


def test_telemetry_fits_in_one_message():  # a long heard list is cut to fit, but the count stays true
    heard = [(f"Q{i % 10}X{i:03d}", -float(i), 2) for i in range(40)]  # forty stations
    text = telemetry.build("FN31", None, heard)  # power unknown
    assert len(text) <= 200 and " P? N40 " in text  # within the limit, with the full count
    assert len(telemetry.parse(text)["stations"]) < 40  # only as many entries as fit


def test_telemetry_ignores_ordinary_text():  # a message that is not telemetry
    assert telemetry.parse("Good morning, the TLM1 tag is mentioned here") is None  # the tag alone is not enough


def test_telemetry_summary_uses_the_last_half_hour():  # old receptions do not count
    now = 1_000_000.0  # a fixed clock
    records = [{"t": now - 60, "call": "Q1AAAA", "snr": -4, "level": 2}, {"t": now - 120, "call": "Q1AAAA", "snr": 0, "level": 4},  # (continued)
               {"t": now - 30, "call": "Q2BB", "snr": -10, "level": 0}, {"t": now - 4000, "call": "Q3CCC", "snr": 10, "level": 4}]  # Q3CCC was heard over an hour ago
    assert telemetry.summarize(records, now) == [("Q1AAAA", -2.0, 4), ("Q2BB", -10.0, 0)]  # median SNR, fastest level, strongest first


def test_heard_log_keeps_48_hours(tmp_path):  # receptions older than two days are dropped
    path = str(tmp_path / "heard.jsonl")  # the log file
    log = heardlog.HeardLog(path)  # a new log
    now = log.add("Q1AAAA", "EM92", -3.0, 2, "beacon", 14108.5)["t"]  # heard just now
    log.add("Q2BB", "FN31", 4.0, 1, "answer", 7101.5, t=now - 49 * 3600)  # heard 49 hours ago
    log.add("Q1AAAA", "", 1.0, 3, "message", 14108.5, t=now - 3600)  # heard an hour ago
    reopened = heardlog.HeardLog(path)  # open it again, as the panel does when it starts
    assert [r["call"] for r in reopened.records] == ["Q1AAAA", "Q1AAAA"]  # the old reception is gone
    row = reopened.summary()[0]  # the one station left
    assert (row["call"], row["count"], row["best_snr"], row["best_level"], row["grid"]) == ("Q1AAAA", 2, 1.0, 3, "EM92")  # summed up
    with open(path, encoding="utf-8") as handle:  # and the file itself was rewritten without it
        assert sum(1 for _ in handle) == 2  # two lines


def test_logbook_levels_choose_rows_and_columns(tmp_path):  # basic, advanced and verbose
    rows = {}  # what each level wrote
    for level in logbook.LEVELS:  # each level of detail
        book = logbook.Logbook(str(tmp_path / level), level=level)  # a logbook at that level
        for event in ("message", "heard", "frame"):  # one event of each kind
            book.write(event, when=0.0, station="Q5EEEE", direction="RX", text="hi", snr_db=-3.0, alc=0.2)  # with fields from every group
        with open(book.csv_path(0.0), newline="", encoding="utf-8") as handle:  # read the day's file back
            rows[level] = list(csv.DictReader(handle))  # its rows
    assert [r["event"] for r in rows["basic"]] == ["message"]  # basic: messages only
    assert [r["event"] for r in rows["advanced"]] == ["message", "heard"]  # advanced: and stations heard
    assert [r["event"] for r in rows["verbose"]] == ["message", "heard", "frame"]  # verbose: everything
    assert rows["basic"][0]["snr_db"] == "" and rows["advanced"][0]["snr_db"] == "-3.0"  # signal readings from advanced up
    assert rows["advanced"][0]["alc"] == "" and rows["verbose"][0]["alc"] == "0.2"  # meters in verbose only
    assert rows["basic"][0]["utc_date"] == "1970-01-01" and rows["basic"][0]["text"] == "hi"  # UTC date, and the message itself


def test_logbook_writes_adif_contacts(tmp_path):  # a completed contact for a logging program
    book = logbook.Logbook(str(tmp_path))  # a logbook
    text = book.contact({"call": "Q2BB", "start": 0.0, "end": 125.0, "dial_khz": 14108.5, "grid": "FN31", "my_call": "Q5EEEE", "my_grid": "EM92", "snr": -7.6, "power_w": 50, "sent": 2, "received": 1, "best_level": 3, "signal": "0.20"})  # one contact
    assert "<CALL:4>Q2BB" in text and "<BAND:3>20m" in text and "<FREQ:9>14.110000" in text and "<RST_RCVD:2>-8" in text and "<TIME_OFF:6>000205" in text  # the main fields
    with open(book.adif_path(), encoding="utf-8") as handle:  # the file itself
        content = handle.read()  # all of it
    assert content.count("<EOH>") == 1 and content.count("<EOR>") == 1  # one header, one record


def test_theme_choice_resolves():  # the look chosen
    assert theme.resolve("dark") == "dark" and theme.resolve("light") == "light" and theme.resolve("nonsense") == "light"  # a direct choice
    assert theme.resolve("system") in ("dark", "light")  # whatever the computer is set to
    assert os.name != "nt" or isinstance(theme.system_prefers_dark(), bool)  # on Windows the registry can be read


def test_installed_program_keeps_operator_files_in_the_user_profile(monkeypatch, tmp_path):  # an installed copy cannot write beside its own files
    import sys  # the "frozen" mark PyInstaller sets
    from live import paths  # the rule under test
    assert paths.data_dir().endswith("local")  # from the source folder: local/ beside the code
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # pretend to be the installed build
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # a stand-in for the user's profile (used on Windows)
    monkeypatch.setenv("HOME", str(tmp_path))  # and for the home folder (used elsewhere)
    folder = paths.data_dir()  # where the installed program keeps the operator's files
    assert folder.startswith(str(tmp_path)) and os.path.isdir(folder)  # in the profile, created when first needed
    assert os.listdir(folder) == []  # and empty: a fresh installation carries nobody's settings
