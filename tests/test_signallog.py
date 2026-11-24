"""Tests for the signal log (live/signallog.py), the sample timeline (live/recorder.py TimedSource), the receiver's trace and tools/signal_report.py."""

import json  # the log is JSON Lines
import os  # file paths
import sys  # lets the tools folder be imported

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root
if os.path.join(ROOT, "tools") not in sys.path:  # the tools are scripts, not a package
    sys.path.insert(0, os.path.join(ROOT, "tools"))  # make them importable


def lines_of(folder):  # every line written to the log folder
    """Return every event in every .jsonl file in `folder`, as dicts."""
    events = []  # what was read
    for name in sorted(os.listdir(folder)):  # each file
        if name.endswith(".jsonl"):  # a log file
            with open(os.path.join(folder, name), encoding="utf-8") as handle:  # open it
                events += [json.loads(line) for line in handle if line.strip()]  # every line must be valid JSON
    return events  # the events


def test_signal_log_off_writes_nothing(tmp_path):  # the default: no disk space used
    from live.signallog import SignalLog  # the log

    log = SignalLog(str(tmp_path / "signal"), mode="off")  # turned off
    log.session_start("listen", call="Q1AAAA")  # a run starts
    log.note("anything")  # something happens
    log.tick(level=(-30.0, -20.0), lost=0)  # a minute passes
    assert not os.path.exists(tmp_path / "signal")  # not even the folder is made


def test_signal_log_lines_are_plain_json(tmp_path):  # every line can be read back
    from live.signallog import SignalLog  # the log

    clock = [1795280000.0]  # a fixed time, 21 November 2026
    log = SignalLog(str(tmp_path), prefix="kestrel_second", mode="on", clock=lambda: clock[0])  # a second panel's log
    log.session_start("monitor", call="Q1AAAA", dial_khz=7101.5)  # a run starts
    log.note("a value that is not a number", snr_db=float("nan"), count=np.int64(3), level=np.float32(1.25))  # numpy values and NaN
    events = lines_of(str(tmp_path))  # read it back
    assert os.path.exists(tmp_path / "kestrel_second_signal_2026-11-21.jsonl")  # one file per UTC day, with the panel's prefix
    assert [event["event"] for event in events] == ["session_start", "note"]  # both lines
    assert events[0]["signal_version"] and events[0]["utc"] == "2026-11-21T16:53:20.000Z"  # versions and the time in ISO form
    assert events[1]["snr_db"] is None and events[1]["count"] == 3 and events[1]["level"] == 1.25  # NaN as null, numpy numbers made plain


def test_search_candidates_are_logged_once_per_signal(tmp_path):  # a long frame is searched every second; the log must not repeat it
    from live.signallog import SignalLog  # the log

    log = SignalLog(str(tmp_path), mode="on")  # on
    step = {"level": 2, "start": 100, "sample": 50000, "offset_hz": 1.0, "quality": 40.0, "header": ""}  # a strong preamble with no header yet
    weak = {"level": 0, "start": 5, "sample": 9000, "offset_hz": 0.0, "quality": 2.0, "header": ""}  # noise: too weak to log
    for _ in range(5):  # five searches, one a second
        log.search(None, [dict(step), dict(weak)])  # the same candidates each time
    log.search(None, [dict(step, sample=50300, header="first", ok=True, reason="")])  # the same signal, found a little later, now decoded
    events = [event for event in lines_of(str(tmp_path)) if event["event"] == "search"]  # the search lines
    assert len(events) == 2  # once while it had no header, once when it decoded
    assert events[1]["header"] == "first" and events[1]["ok"] is True  # with the new outcome
    assert log.best == 40.0 and log.searches == 6  # the minute's counts include everything searched


def test_clips_stay_under_the_size_cap(tmp_path):  # long sessions must not fill the disk
    from live.signallog import SignalLog  # the log

    clock = [1795280000.0]  # 21 November 2026
    log = SignalLog(str(tmp_path), mode="clips", clock=lambda: clock[0])  # keeping clips
    old = tmp_path / "clips" / "2026-10-01"  # a day folder far older than 14 days
    old.mkdir(parents=True)  # make it
    (old / "000000_ok_L0_s0.wav").write_bytes(b"x" * 1000)  # with a file in it
    log.clips_max_mb = 1  # a cap of one megabyte, for the test
    names = []  # the clips saved
    for number in range(12):  # twelve clips of 0.24 MB each (10 seconds at 12,000 16-bit samples a second)
        clock[0] += 1.0  # a second apart, so each has its own name
        names.append(log.clip(np.zeros(10 * 12000), "ok", 2, number))  # save one
    assert all(name and name.startswith("clips/2026-11-21/") for name in names)  # each saved, named from the log folder
    removed = log.prune_clips()  # apply the limits
    assert removed >= 1 and not old.exists()  # the old day went
    total = sum(os.path.getsize(os.path.join(tmp_path, "clips", "2026-11-21", name)) for name in os.listdir(tmp_path / "clips" / "2026-11-21"))  # what is left
    assert total <= 1024 * 1024  # under the cap
    assert os.path.exists(tmp_path / names[-1])  # and the newest clip was kept


def test_timed_source_numbers_every_sample(tmp_path):  # the timeline that ties the log, the listener and the recordings together
    from live.recorder import Recorder, RecordingSource, TimedSource  # the wrappers

    class Fake:  # a sound card that delivers one second each time it is asked
        def read(self):  # the newest audio
            return np.zeros(12000)  # one second
        def flush(self):  # nothing to drop
            pass  # nothing

    source = TimedSource(Fake(), clock=lambda: 1795280001.0)  # counting
    source.read()  # one second
    source.flush()  # a second second, read while transmitting
    assert source.samples == 24000  # both counted
    assert source.utc_of(0) == 1795280000.0 and source.utc_of(12000) == 1795280001.0  # sample 0 arrived a second before the first read returned
    recorder = Recorder(str(tmp_path), label="Q1AAAA", clock=lambda: 1795280000.0)  # a recording
    opened = []  # where files started
    recorder.on_open = lambda path, sample: opened.append(sample)  # note them
    recording = RecordingSource(Fake(), recorder)  # counting and recording
    recording.read()  # one second
    recording.flush()  # another, while transmitting
    recorder.close()  # finish
    assert recording.samples == recorder.total == 24000 and opened == [0]  # the recording's timeline is the source's timeline


def test_listener_numbers_frames_in_the_stream():  # where a frame began, in samples since listening started
    from live.listener import Listener  # the continuous receiver
    from modem import build_beacon  # a short frame
    from modem.params import FS  # 12,000 samples per second

    rng = np.random.default_rng(5)  # repeatable noise
    frame = build_beacon("Q1AAAA", "EM93", level=4)  # a beacon at L4, under two seconds
    audio = rng.standard_normal(30 * FS) * 0.02  # thirty seconds of noise
    first, second = 3 * FS, 15 * FS  # where two copies go
    audio[first:first + len(frame)] += frame * 0.1  # the first copy
    audio[second:second + len(frame)] += frame * 0.1  # the second
    listener, found, traces = Listener(), [], []  # a receiver, the frames found and the searches seen
    listener.on_search = lambda result, trace: traces.append(trace)  # collect the receiver's candidate lists
    offset = 7_000_000  # the stream did not start at 0: listening began long before
    for begin in range(0, len(audio), FS):  # one second at a time
        found += listener.feed(audio[begin:begin + FS], at=offset + begin)  # numbered as a TimedSource would number them
    assert [heard.result.ok for heard in found] == [True, True]  # both decoded
    assert abs(found[0].result.sample - (offset + first)) <= 2 and abs(found[1].result.sample - (offset + second)) <= 2  # each placed where it was, though the first was cut out of the store before the second was found
    assert found[0].result.header_copy == "first"  # a clean frame is read from its first header copy
    assert any(step.get("ok") for trace in traces for step in trace)  # the traces show the decodes
    assert all("sample" in step for trace in traces for step in trace)  # every candidate has its place in the stream


def test_receiver_reads_the_second_header_copy_when_the_first_is_lost():  # the 0.26 header at both ends, seen in the trace
    from modem import build_frame, receive  # the transmitter and receiver
    from modem.frame import HEADER_SYMBOLS_ONCE  # tones in one header copy
    from modem.levels import LEVELS  # level sizes
    from modem.params import FS, PREAMBLE_TONES  # sample rate and preamble length

    rng = np.random.default_rng(8)  # repeatable noise
    frame = build_frame("Q1AAAA DE Q2BB TEST", 3)  # a message at L3
    tone = LEVELS[3].samples  # one tone length
    head = PREAMBLE_TONES * tone  # where the first header copy starts
    frame[head:head + HEADER_SYMBOLS_ONCE * tone] = 0.0  # the first header copy faded right out
    audio = np.concatenate([np.zeros(FS), frame, np.zeros(FS)]) + rng.standard_normal(len(frame) + 2 * FS) * 0.01  # a little noise round it
    trace = []  # the receiver's candidate list
    result = receive(audio, trace=trace)  # decode it
    assert result.ok and result.header_copy in ("both", "second")  # decoded, from the copy at the end
    assert any(step["header"] in ("both", "second") and step.get("ok") for step in trace)  # and the trace says so


def test_signal_report_summarizes_a_log(tmp_path):  # tools/signal_report.py
    import signal_report  # the report tool
    from live.signallog import SignalLog  # the log

    clock = [1795280000.0]  # 21 November 2026, 16:53 UTC
    log = SignalLog(str(tmp_path), mode="on", clock=lambda: clock[0])  # on

    class Result:  # a stand-in receiver report with the fields the log reads
        __dataclass_fields__ = {name: None for name in ("ok", "level", "snr_db", "fade_index", "offset_hz", "drift_hz_s", "header_copy", "origin", "sample", "reason")}  # its field names
        ok, level, snr_db, fade_index, offset_hz, drift_hz_s, header_copy, origin, sample, reason = True, 2, -6.5, 0.4, 3.0, 0.01, "both", "Q2BB", 1000, ""  # a decoded L2 frame from Q2BB

    class Heard:  # a stand-in for live.listener.Heard
        result, audio, audio_sample = Result(), np.zeros(12000), 0  # one second of audio

    class Tx:  # a stand-in transmission
        kind, level, seconds, note = "answer", 2, 8.9, ""  # an answer at L2

    log.session_start("listen", call="Q1AAAA", dial_khz=7101.5)  # the run
    log.rx(Heard(), dial_khz=7101.5)  # a frame heard on 40 m
    log.tx(Tx(), True, dial_khz=7101.5, gain=0.25)  # an answer sent
    log.meters(watts=20.0, alc=0.7, swr=1.3)  # with ALC too high
    log.tx(Tx(), False, peak_dbfs=-3.0)  # and released
    clock[0] += 600.0  # ten minutes later
    log.session_end()  # the run ends
    events, files = signal_report.load([str(tmp_path)])  # read it back
    text = "\n".join(signal_report.report(events))  # the report
    assert "Q2BB" in text and "L2" in text and "both:1" in text  # the station, its level and the header copy
    assert "40" in text and "answer" in text and "ALC at half scale" in text  # the band, the transmission and the ALC warning
    written = signal_report.write_tables(events, str(tmp_path / "csv"))  # the CSV tables
    assert any(path.endswith("rx.csv") for path in written)  # including the frames


def test_long_beacon_candidates_are_logged(tmp_path):  # the long beacon's level (7) is not one of the speed levels: it once stopped the station with "tuple index out of range"
    from live.signallog import SignalLog  # the log
    from modem.params import LONG_LEVEL  # the long beacon's level number

    log = SignalLog(str(tmp_path), mode="on")  # on
    step = {"level": LONG_LEVEL, "start": 0, "sample": 70000, "offset_hz": 2.0, "quality": 30.0, "header": "long", "ok": False, "reason": "body check failed"}  # a long-beacon candidate, as the listener traces it
    log.search(None, [dict(step)])  # logged
    log.search(None, [dict(step, sample=70500)])  # the same signal a moment later: not logged again
    events = [event for event in lines_of(str(tmp_path)) if event["event"] == "search"]  # the search lines
    assert len(events) == 1 and events[0]["level"] == LONG_LEVEL  # logged once, as the long beacon


def test_a_fault_in_the_signal_log_never_stops_the_station(tmp_path):  # the log helps find problems; it must not become one
    from live.signallog import Guarded, SignalLog  # the log and its guard

    said = []  # what the operator is told
    log = Guarded(SignalLog(str(tmp_path), mode="on"), said.append)  # guarded, as the panel uses it
    log.search(None, [{"level": "nonsense", "sample": 5, "quality": 30.0}])  # a trace the log cannot handle
    log.search(None, [{"level": "nonsense", "sample": 9, "quality": 30.0}])  # and again
    assert len(said) == 1 and "the station carries on" in said[0]  # reported once, nothing raised
    assert any(name.startswith("signal_log_fault_") for name in os.listdir(str(tmp_path)))  # with the details saved
    assert log.on and log.searches == 2  # attributes still read through
