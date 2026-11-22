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


def test_band_names_follow_the_dial():  # the Band columns of the panel's lists
    from live.bands import band_of  # the lookup under test
    assert [band_of(khz) for khz in (1840.0, 3582.5, 5357.0, 7110.0, 10147.0, 14112.5, 18100.0, 21074.0, 24915.0, 28074.0, 50313.0)] == ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]  # every HF band and 6 m
    assert band_of(0.0) == band_of(None) == band_of("") == band_of(9000.0) == ""  # no frequency, or none of the bands: nothing shown


def test_sound_output_can_be_cut_short(monkeypatch):  # the Stop calling key takes a call off the air at once
    import sys  # to stand in for the sound-card library
    import threading  # the operator's key arrives from another thread
    import time  # the clock
    import types  # a stand-in module

    import numpy as np  # numerical arrays

    from live.audio import AudioOut  # the output under test
    calls = []  # what the stand-in was asked to do

    class Stream:  # a stream that would play for two seconds
        def __init__(self):  # started now
            self.until = time.monotonic() + 2.0  # when it would end

        @property  # read like sounddevice's
        def active(self):  # still playing?
            return time.monotonic() < self.until and "stop" not in calls  # until its end, or until stopped

    stream = Stream()  # the one stream
    fake = types.SimpleNamespace(play=lambda *a, **k: calls.append("play"), get_stream=lambda: stream, stop=lambda: calls.append("stop"), wait=lambda: calls.append("wait"))  # the stand-in library
    monkeypatch.setitem(sys.modules, "sounddevice", fake)  # used by play()
    out = AudioOut()  # the output
    threading.Timer(0.2, out.abort).start()  # the operator presses Esc after a fifth of a second
    started = time.monotonic()  # when playing began
    out.play(np.zeros(12000 * 2))  # two seconds of audio
    assert time.monotonic() - started < 1.0 and calls == ["play", "stop"] and not out.playing  # back almost at once, the sound stopped, nothing playing
    out.abort()  # pressing it again with nothing playing
    assert not out.cut  # does nothing
