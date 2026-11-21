"""Decode a recording: play a WAV file through Kestrel's receiver and list what it finds.

Run from the repository root:

    python tools/decode_wav.py recording.wav [more.wav ...] [--csv results.csv]

Any common WAV file works (any sample rate, 8/16/32-bit, mono or stereo):
a recording made by the panel, one saved from an SDR such as a KiwiSDR or
WebSDR, or one from another program. The audio is fed to the same
continuous receiver the panel uses, one second at a time, so the results
are what a live station would have seen.

For each file it lists:
  * every frame that decoded (time into the file, level, SNR, fading, what it said),
  * every frame whose header was read but whose body failed its check,
  * every "near miss": a Kestrel signature clearly above the noise whose
    header could not be read (a signal that was there but too weak or faded).

With --signal-log FOLDER it also writes a signal log of the decode (see
live/signallog.py and tools/signal_report.py), with every candidate the
receiver looked at; add --clips to save each frame's audio too. Times in
that log come from the file's name when the panel made it
(rx_YYYYmmdd_HHMMSSZ_...), otherwise from the file's modification time.
"""

import argparse  # reads the command-line options
import csv  # writes the optional results table
import os  # file paths
import sys  # lets us add the repository root to the import path
import calendar  # turns a UTC date and time into seconds since 1970
import re  # reads the start time from a recording's name
import time  # reads it as a date and time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
if ROOT not in sys.path:  # when run as a script
    sys.path.insert(0, ROOT)  # make "modem" and "live" importable

from live.listener import Listener  # the continuous receiver  # noqa: E402
from live.recorder import read_wav  # loads WAV files at the modem's rate  # noqa: E402
from live.runner import attach_signal_log, describe, near_line  # one-line descriptions of a frame and of a near miss, and the signal log hook-up  # noqa: E402
from live.signallog import SignalLog  # the detailed signal log  # noqa: E402
from modem.params import FS  # the modem's sample rate (12,000)  # noqa: E402

CHUNK_S = 1.0  # audio is fed to the receiver this many seconds at a time, as it would arrive live
FIELDS = ("file", "seconds", "kind", "level", "snr_db", "fade", "offset_hz", "quality", "detail")  # the columns of the results table


class FileTimeline:  # sample numbers and times for a recording, as recorder.TimedSource gives them live
    """Sample n of the file arrived at t0 + n / 12000 (UTC seconds)."""

    def __init__(self, t0):  # the time of the file's first sample
        self.t0 = t0  # seconds since 1970, UTC
        self.samples = 0  # samples fed so far

    def utc_of(self, sample):  # when a numbered sample arrived
        """Return the UTC time of sample number `sample`."""
        return self.t0 + sample / FS  # from the start time and the sample rate


def file_start(path, seconds):  # when a recording began
    """Return the UTC start of the recording at `path`: from its name if the panel made it, else its modification time less its length."""
    match = re.search(r"rx_(\d{8}_\d{6})Z", os.path.basename(path))  # rx_20261121_160000Z_... as the panel names them
    if match:  # the panel's name
        return float(calendar.timegm(time.strptime(match.group(1), "%Y%m%d_%H%M%S")))  # that time, UTC
    return os.path.getmtime(path) - seconds  # the file was finished when it was last written


def decode_file(path, say=print, progress=None, signal_log=None):  # one recording
    """Feed the WAV file at `path` through the receiver; return a list of result rows (dicts with FIELDS) and report each as it is found. `signal_log`, a SignalLog, also gets everything the receiver did."""
    audio, seconds = read_wav(path)  # the recording, at 12,000 samples per second
    say(f"{os.path.basename(path)}: {seconds / 60.0:.1f} minutes of audio")  # what is being decoded
    listener = Listener()  # a fresh receiver
    rows = []  # what was found
    fed = [0]  # samples fed so far (in a list so the inner function can see the latest value)
    timeline = FileTimeline(file_start(path, seconds))  # sample numbers and times for the signal log
    log_near = attach_signal_log(listener, signal_log)  # searches and near misses to the signal log, if one is kept
    if signal_log is not None:  # a signal log is kept
        signal_log.session_start("decode", timeline=timeline, file=os.path.basename(path), seconds=round(seconds, 1))  # the decode's starting point

    def near(result):  # a signature too weak or faded to read
        log_near(result)  # the signal log, if one is kept
        where = result.sample / FS  # its time into the file
        rows.append({"file": os.path.basename(path), "seconds": round(where, 1), "kind": "near miss", "level": result.seen_level,  # (continued)
                     "snr_db": "", "fade": "", "offset_hz": round(result.offset_hz, 1), "quality": round(result.sync_quality, 1), "detail": near_line(result)})  # the row
        say(f"  {where:8.1f}s  {near_line(result)}")  # report it

    listener.on_near = near  # near misses come here
    step = int(CHUNK_S * FS)  # samples per chunk
    import numpy as np  # numerical arrays (only needed here)
    quiet = float(np.std(audio[-10 * FS:])) if len(audio) else 1e-3  # the level of the recording's last ten seconds
    tail = np.random.default_rng(0).standard_normal(int(100 * FS)) * max(quiet, 1e-4)  # 100 seconds of matching background noise after the end, so a frame at the very end still completes (pure silence would confuse the receiver)
    for begin in range(0, len(audio) + len(tail), step):  # one chunk at a time
        chunk = audio[begin:begin + step] if begin < len(audio) else tail[:step]  # the recording, then the silence
        timeline.samples = fed[0] + len(chunk)  # the timeline's count, as a live source would keep it
        heard_now = listener.feed(chunk, at=fed[0])  # feed it, numbered from the start of the file
        fed[0] += len(chunk)  # count it
        for heard in heard_now:  # every frame that completed
            result = heard.result  # the receiver's report
            if signal_log is not None:  # a signal log is kept
                signal_log.rx(heard)  # the frame, with its clip if clips are kept
            where = result.sample / FS  # where it began in the file
            kind = "decoded" if result.ok else "failed"  # what happened
            rows.append({"file": os.path.basename(path), "seconds": round(max(where, 0.0), 1), "kind": kind, "level": result.level,  # (continued)
                         "snr_db": round(result.snr_db, 1), "fade": round(result.fade_index, 2), "offset_hz": round(result.offset_hz, 1), "quality": round(result.sync_quality, 1), "detail": describe(result)})  # the row
            say(f"  {max(where, 0.0):8.1f}s  {describe(result)}")  # report it
        if progress is not None and begin % (60 * step) == 0:  # once a minute of audio
            progress(min(begin / max(len(audio), 1), 1.0))  # tell the caller how far through it is
    decoded = sum(1 for row in rows if row["kind"] == "decoded")  # frames that decoded
    failed = sum(1 for row in rows if row["kind"] == "failed")  # frames whose body failed
    near_count = sum(1 for row in rows if row["kind"] == "near miss")  # signatures seen but not read
    say(f"{os.path.basename(path)}: {decoded} decoded, {failed} failed their check, {near_count} near miss(es)")  # the summary
    if signal_log is not None:  # a signal log is kept
        signal_log.session_end(decoded=decoded, failed=failed, near=near_count)  # close the decode in it
    return rows  # everything found


def write_csv(rows, path):  # save the results
    """Write `rows` to a CSV file at `path`."""
    with open(path, "w", newline="", encoding="utf-8") as handle:  # open the file
        writer = csv.DictWriter(handle, fieldnames=FIELDS)  # one column per field
        writer.writeheader()  # the column names
        writer.writerows(rows)  # the results


def main(argv=None):  # the script itself
    """Decode each file named on the command line; optionally save a CSV of everything found."""
    parser = argparse.ArgumentParser(description="Decode Kestrel frames from WAV recordings")  # describe the tool
    parser.add_argument("files", nargs="+", help="WAV files to decode")  # the recordings
    parser.add_argument("--csv", help="also save the results to this CSV file")  # optional table
    parser.add_argument("--signal-log", metavar="FOLDER", help="also write a signal log of the decode into FOLDER")  # optional signal log
    parser.add_argument("--clips", action="store_true", help="with --signal-log: save each frame's audio as a clip too")  # optional clips
    args = parser.parse_args(argv)  # read the options
    log = SignalLog(args.signal_log, prefix="decode", mode="clips" if args.clips else "on") if args.signal_log else None  # the signal log, if asked for
    rows = []  # results from every file
    for path in args.files:  # one recording at a time
        rows += decode_file(path, signal_log=log)  # decode it
    if args.csv:  # a table was asked for
        write_csv(rows, args.csv)  # save it
        print(f"results saved to {args.csv}")  # say where
    return 0  # success


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # decode and exit
