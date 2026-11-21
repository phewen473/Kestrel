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
"""

import argparse  # reads the command-line options
import csv  # writes the optional results table
import os  # file paths
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
if ROOT not in sys.path:  # when run as a script
    sys.path.insert(0, ROOT)  # make "modem" and "live" importable

from live.listener import Listener  # the continuous receiver  # noqa: E402
from live.recorder import read_wav  # loads WAV files at the modem's rate  # noqa: E402
from live.runner import describe, near_line  # one-line descriptions of a frame and of a near miss  # noqa: E402
from modem.params import FS  # the modem's sample rate (12,000)  # noqa: E402

CHUNK_S = 1.0  # audio is fed to the receiver this many seconds at a time, as it would arrive live
FIELDS = ("file", "seconds", "kind", "level", "snr_db", "fade", "offset_hz", "quality", "detail")  # the columns of the results table


def decode_file(path, say=print, progress=None):  # one recording
    """Feed the WAV file at `path` through the receiver; return a list of result rows (dicts with FIELDS) and report each as it is found."""
    audio, seconds = read_wav(path)  # the recording, at 12,000 samples per second
    say(f"{os.path.basename(path)}: {seconds / 60.0:.1f} minutes of audio")  # what is being decoded
    listener = Listener()  # a fresh receiver
    rows = []  # what was found
    fed = [0]  # samples fed so far (in a list so the inner function can see the latest value)

    def near(result):  # a signature too weak or faded to read
        where = (fed[0] - len(listener.store) + result.start) / FS  # its time into the file (approximate when frames have already been cut out of the store)
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
        fed[0] += len(chunk)  # count it
        for heard in listener.feed(chunk):  # every frame that completed
            result = heard.result  # the receiver's report
            where = (fed[0] - len(listener.store) - len(heard.audio)) / FS  # roughly where it began in the file (the frame was just cut out of the store)
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
    args = parser.parse_args(argv)  # read the options
    rows = []  # results from every file
    for path in args.files:  # one recording at a time
        rows += decode_file(path)  # decode it
    if args.csv:  # a table was asked for
        write_csv(rows, args.csv)  # save it
        print(f"results saved to {args.csv}")  # say where
    return 0  # success


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # decode and exit
