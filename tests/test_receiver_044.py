"""Tests for the 0.44 receiver and panel fixes: doubtful long beacons, strong near misses, report ages in the live loop, the low-input warning, and levels kept between starts."""

import os  # paths
import sys  # the import path
from types import SimpleNamespace  # a stand-in for the panel

from live.listener import DOUBT_OFFSET_HZ, Listener  # the continuous receiver, and how far off a doubtful long beacon may be
from live.runner import near_line, s_meter_text, strong_unreadable, their_report  # the near-miss line, S-units, the strong test, the partner's report
from modem.control import ChannelReport  # a channel report
from modem.frame import RxResult  # the receiver's report
from modem.params import FRAME_TYPE_ANSWER, FRAME_TYPE_LONG, FS  # frame types and sample rate


def panel_module():  # the panel's module (its folder is not a package)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))  # the panel's folder
    import kestrel_panel as kp  # the panel
    return kp  # it


def _long(origin, offset):  # a long beacon as the combiner hands it over
    """Return a receiver's report for a long beacon from `origin` at `offset_hz`."""
    return RxResult(ok=True, frame_type=FRAME_TYPE_LONG, offset_hz=offset, fields={"origin": origin, "copies": 4})  # read from four copies


def test_doubtful_long_beacon_is_refused():  # the false CSU/HP7ZR of November 2026
    """Read only from added copies, no pattern in the newest copy, an unknown sender, far from every station read lately: refused. Any one of those not so: accepted."""
    listener = Listener(compiled=False)  # the Python receiver
    listener.expect = lambda: ("Q1AAAA", ["Q2BB"])  # this station, and the one it expects
    assert listener._doubtful(_long("CSU/HP7ZR", -22.4), 4, 0.0) == ""  # nothing read lately to compare with: accepted
    listener.known_offsets = [(0, 0.5), (FS, 1.2), (2 * FS, -0.7)]  # real stations, all within 2 Hz
    why = listener._doubtful(_long("CSU/HP7ZR", -22.4), 4, 0.0)  # the false one
    assert why and "4 copies" in why and "22 Hz" in why  # refused, saying why
    assert listener._doubtful(_long("CSU/HP7ZR", -22.4), 1, 0.0) == ""  # read from one copy: accepted
    assert listener._doubtful(_long("CSU/HP7ZR", -22.4), 4, 2.5) == ""  # its pattern stood out: accepted
    assert listener._doubtful(_long("Q2BB", -22.4), 4, 0.0) == ""  # a station expected: accepted
    assert listener._doubtful(_long("Q9ZZ", 1.2 + DOUBT_OFFSET_HZ - 0.1), 4, 0.0) == ""  # near a real station: accepted


def test_known_offsets_come_from_frames_read_alone():  # what the receiver remembers
    """Only frames that decoded on their own count as where real stations arrive; old ones are forgotten."""
    listener = Listener(compiled=False)  # the Python receiver
    listener.total = 10 * FS  # ten seconds in
    heard = [SimpleNamespace(result=RxResult(ok=True, offset_hz=1.0, sample=5 * FS, fields={})),  # read alone
             SimpleNamespace(result=RxResult(ok=True, offset_hz=-20.0, sample=6 * FS, fields={"copies": 3})),  # read from copies
             SimpleNamespace(result=RxResult(ok=False, offset_hz=9.0, sample=7 * FS))]  # failed
    listener._remember_offsets(heard)  # taken in
    assert listener.known_offsets == [(5 * FS, 1.0)]  # only the first
    listener.total = 3 * 3600 * FS  # three hours on
    listener._remember_offsets([])  # the next search
    assert listener.known_offsets == []  # forgotten


def test_strong_near_miss_points_to_another_signal_version():  # the near-miss line (since 0.44)
    """All 12 pattern tones standing out means a strong signal: the line says it may be another signal version, not that it is too weak."""
    strong = RxResult(reason="header check failed", seen_level=0, offset_hz=3.0, sync_quality=40.0, pattern_tones=12)  # every pattern tone
    weak = RxResult(reason="header check failed", seen_level=0, offset_hz=3.0, sync_quality=0.01, pattern_tones=9)  # most of them
    assert strong_unreadable(strong) and not strong_unreadable(weak)  # told apart
    assert "different Kestrel signal version" in near_line(strong) and "too weak" not in near_line(strong)  # said so
    assert "too weak or faded" in near_line(weak) and "9 of 12 pattern tones" in near_line(weak)  # as before


def test_live_loop_dates_a_report_by_its_age():  # the partner's report, as the runner keeps it
    """their_report gives the report's age (0 when not said), so the live loop dates it when the partner measured it."""
    station = SimpleNamespace(partner="Q2BB", link=7)  # a station in a contact
    result = RxResult(ok=True, frame_type=FRAME_TYPE_ANSWER, fields={"dest": "Q1AAAA", "report": ChannelReport(-17.0, 0.5, 0.0, 0, 240.0, -30.0)})  # an answer to it
    assert their_report(station, result, "Q1AAAA") == (-17.0, 0, 240.0)  # the SNR, the level and the age
    result.fields["report"] = ChannelReport(-17.0, 0.5, 0.0, 0)  # age not said
    assert their_report(station, result, "Q1AAAA") == (-17.0, 0, 0.0)  # taken as fresh


def test_s_meter_words():  # the partner's noise, as the operator reads it
    assert s_meter_text(-54.0) == "S0" and s_meter_text(-12.0) == "S7" and s_meter_text(0.0) == "S9" and s_meter_text(12.0) == "S9+12"  # S-units, 6 dB each
    assert s_meter_text(float("nan")) == "" and s_meter_text(None) == ""  # not measured


def test_low_input_warning_once_and_recovery():  # the receive input sat 42 dB low for 42 minutes on November 25
    """Below LOW_INPUT_DBFS for LOW_INPUT_S while receiving: one warning; back to a working level: one line saying so. Transmitting does not count."""
    kp = panel_module()  # the panel
    lines = []  # what the operator is told
    panel = SimpleNamespace(tx_active=False, tx_ended=-100.0, low_since=None, low_warned=False, say=lines.append, signal_log=None)  # a stand-in
    clock = [0.0]  # a stand-in clock
    watch = lambda level: kp.Panel.watch_low_input(panel, level, clock=lambda: clock[0])  # noqa: E731 - the method on the stand-in
    for second in range(0, int(kp.LOW_INPUT_S) + 5):  # a minute and a bit of low input
        clock[0] = float(second)  # time passes
        watch(-72.0)  # very low
    assert len(lines) == 1 and lines[0].startswith("warning: the receive input has been very low (-72 dBFS)")  # warned once
    watch(-72.0)  # still low
    assert len(lines) == 1  # not again
    watch(-35.0)  # back
    assert len(lines) == 2 and "back to a working level" in lines[1]  # said so
    panel.tx_active = True  # transmitting: the radio mutes its receive audio
    for second in range(200, 400):  # a long transmission
        clock[0] = float(second)  # time passes
        watch(-90.0)  # nothing comes in
    assert len(lines) == 2  # no warning for that


def test_asked_levels_survive_a_restart(tmp_path):  # the level each station last needed (since 0.44)
    """Saved and read back; damaged entries and ones older than ASKED_KEEP_DAYS are left out."""
    kp = panel_module()  # the panel
    path = str(tmp_path / "asked_levels.json")  # a file
    now = 1_000_000.0  # a fixed clock
    kp.save_asked_levels(path, {"Q2BB": (now - 3600.0, 0), "Q3CCC": (now - 5 * 86400.0, 2)})  # one recent, one old
    assert kp.load_asked_levels(path, now) == {"Q2BB": (now - 3600.0, 0)}  # the old one is gone
    with open(path, "w", encoding="utf-8") as handle:  # damage it
        handle.write('{"Q2BB": ["x", 1], "Q4DD": [999990.0, 9], "Q5EE": [999990.0, 1]}')  # a bad time, a bad level, a good one
    assert kp.load_asked_levels(path, now) == {"Q5EE": (999990.0, 1)}  # only the good one
    assert kp.load_asked_levels(str(tmp_path / "none.json"), now) == {}  # no file: nothing
