"""Summarise Kestrel signal logs: what was heard, how well, and what was sent.

Run from the repository root:

    python tools/signal_report.py FOLDER_OR_FILES... [--since 2026-11-21] [--until 2026-11-22] [--csv-dir OUT] [--redecode]

Give it the signal log folder (Settings > Logging > Signal log; File >
Open the signal log folder in the panel) or any of its .jsonl files. It
prints a plain-text report:

  * sessions: when the station ran, in which mode, on which frequencies
  * frames received: by level, decoded or failed, with SNR, fading, audio
    offset and drift, and which header copy was read (first, both, second)
  * stations heard: frames, levels, best and median SNR for each callsign
  * near misses: Kestrel signatures heard but not readable, by level and band
  * receiver candidates: how often a strong preamble led to a header, and
    a header to a decoded body (where the receiver loses signals)
  * by UTC hour and band: decodes and near misses (when the path was open)
  * transmissions: by kind and level, airtime, drive, peak level and the
    radio's power, ALC and SWR
  * received audio: level, sound-card dropouts, and the sound card's clock
    against the computer's

--csv-dir also writes each kind of event as a CSV table (rx.csv, near.csv,
search.csv, tx.csv, tx_meter.csv, audio.csv, link.csv) for a spreadsheet.
--redecode plays every saved clip through the receiver again and says
whether it still decodes, which is how a change to the receiver is checked
against real signals.
"""

import argparse  # reads the command-line options
import csv  # writes the optional tables
import glob  # finds the log files in a folder
import json  # each line of a log is a JSON object
import os  # file paths
import statistics  # medians
import sys  # lets us add the repository root to the import path
from collections import Counter, defaultdict  # counting and grouping

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
if ROOT not in sys.path:  # when run as a script
    sys.path.insert(0, ROOT)  # make "modem" and "live" importable

from live.bands import in_data_segment  # names the band a frequency is in  # noqa: E402
from live.listener import NEAR_TONES  # how many pattern tones make a near miss "likely Kestrel" (since 0.31R2)  # noqa: E402
from modem.levels import level_name  # L0 to L4, or LB for the long beacon  # noqa: E402


def load(paths, since=None, until=None):  # read the logs
    """Return every event in the .jsonl files at `paths` (files or folders), oldest first, keeping only UTC dates from `since` up to and including `until`."""
    files = []  # the files to read
    for path in paths:  # each argument
        if os.path.isdir(path):  # a folder
            files += sorted(glob.glob(os.path.join(path, "*.jsonl")))  # every log in it
        else:  # a file
            files.append(path)  # as given
    events = []  # everything read
    for name in files:  # each file
        with open(name, encoding="utf-8") as handle:  # open it
            for number, line in enumerate(handle, 1):  # each line
                line = line.strip()  # without the line ending
                if not line:  # a blank line
                    continue  # skip it
                try:  # a line cut short by a crash is possible
                    event = json.loads(line)  # the event
                except json.JSONDecodeError:  # not whole
                    print(f"note: {os.path.basename(name)} line {number} could not be read; skipped")  # say so
                    continue  # skip it
                day = (event.get("sig_utc") or event.get("utc") or "")[:10]  # the UTC date it belongs to
                if (since and day < since) or (until and day > until):  # outside the dates asked for
                    continue  # skip it
                events.append(event)  # keep it
    events.sort(key=lambda event: event.get("t", 0))  # oldest first
    return events, files  # the events, and the files they came from


def band_of(dial_khz):  # a band's name
    """Return the band a dial frequency is in (for example "40"), or "?" when unknown."""
    if not dial_khz:  # not logged
        return "?"  # unknown
    band = in_data_segment(float(dial_khz))  # the band whose data segment it is in
    return band if band else f"{float(dial_khz):.0f} kHz"  # the band, or the frequency itself


def stats(values):  # minimum, median and maximum
    """Return 'min / median / max' of the numbers in `values`, or '-' when there are none."""
    values = [value for value in values if isinstance(value, (int, float))]  # numbers only
    if not values:  # none
        return "-"  # nothing to show
    return f"{min(values):.1f} / {statistics.median(values):.1f} / {max(values):.1f}"  # the three figures


def table(rows, headings):  # a plain-text table
    """Return `rows` (lists of values) under `headings` as aligned text lines."""
    cells = [[str(heading) for heading in headings]] + [[("" if value is None else str(value)) for value in row] for row in rows]  # everything as text
    widths = [max(len(row[column]) for row in cells) for column in range(len(headings))]  # each column's width
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in cells]  # each row
    lines.insert(1, "  ".join("-" * width for width in widths))  # a rule under the headings
    return lines  # the table


def report(events):  # the text report
    """Return the report on `events` as a list of lines."""
    by = defaultdict(list)  # events grouped by kind
    for event in events:  # each one
        by[event.get("event")].append(event)  # into its group
    out = []  # the lines

    def section(title):  # a heading
        out.extend(["", title, "=" * len(title)])  # with a rule under it

    first, last = (events[0]["utc"], events[-1]["utc"]) if events else ("-", "-")  # the span covered
    out.append(f"Kestrel signal log report: {len(events)} events, {first} to {last}")  # the title line

    section("Sessions")  # when the station ran
    rows = []  # one per session
    for start in by["session_start"]:  # each start
        end = next((event for event in by["session_end"] if event["t"] >= start["t"]), None)  # the first end after it
        minutes = round((end["t"] - start["t"]) / 60.0, 1) if end else "?"  # how long it ran
        rows.append([start["utc"][:19], start.get("mode"), start.get("call"), start.get("dial_khz") or start.get("file"), minutes, start.get("signal_version"), start.get("log_mode")])  # the row
    out += table(rows, ["started (UTC)", "mode", "call", "dial kHz / file", "minutes", "signal", "log"]) if rows else ["none"]  # the table

    section("Frames received")  # what the receiver handed over
    rx = by["rx"]  # every frame
    groups = defaultdict(list)  # frames by level and outcome
    for event in rx:  # each frame
        result = event.get("station_result") or event.get("result", {})  # the station's decode when it differs (an earlier copy combined), else the listener's
        groups[(result.get("level"), "decoded" if result.get("ok") else "failed")].append(result)  # into its group
    rows = []  # one per level and outcome
    for (level, outcome), results in sorted(groups.items(), key=lambda item: (item[0][0] if item[0][0] is not None else -1, item[0][1])):  # in order of level
        copies = Counter(result.get("header_copy") or "-" for result in results)  # which header copy was read
        rows.append([level_name(level), outcome, len(results), stats(r.get("snr_db") for r in results), stats(r.get("fade_index") for r in results),  # (continued)
                     stats(r.get("offset_hz") for r in results), stats(r.get("drift_hz_s") for r in results), " ".join(f"{name}:{count}" for name, count in sorted(copies.items()))])  # the row
    out += table(rows, ["level", "outcome", "frames", "SNR dB min/med/max", "fading", "offset Hz", "drift Hz/s", "header copy"]) if rows else ["none"]  # the table
    combined = sum(1 for event in rx if "station_result" in event)  # frames the station decoded differently by combining copies
    if combined:  # any
        out.append(f"{combined} frame(s) decoded differently by the station after combining with an earlier copy")  # say how many

    section("Stations heard")  # by callsign
    heard = defaultdict(list)  # decoded frames by sender
    for event in rx:  # each frame
        result = event.get("station_result") or event.get("result", {})  # as above
        if result.get("ok") and result.get("origin"):  # a decoded frame that names its sender
            heard[result["origin"]].append((result, event))  # into its group
    rows = [[call, len(items), " ".join(sorted({level_name(r.get('level')) for r, _ in items})), stats(r.get("snr_db") for r, _ in items),  # (continued)
             " ".join(sorted({band_of(e.get("dial_khz")) for _, e in items})), items[0][1]["utc"][:16], items[-1][1]["utc"][:16]] for call, items in sorted(heard.items())]  # one row per station
    out += table(rows, ["call", "frames", "levels", "SNR dB min/med/max", "bands", "first heard", "last heard"]) if rows else ["none (link frames inside a contact carry no callsign)"]  # the table

    section("Near misses (Kestrel signature heard, header not readable)")  # signals that got through but not well enough
    near = by["near"]  # every near miss
    likely = Counter(event.get("seen_level") for event in near if (event.get("pattern_tones") or -1) >= NEAR_TONES)  # those that were likely Kestrel by the tone test (logs from 0.31R2 on)
    rows = [[level_name(level), count, likely.get(level, 0)] for level, count in sorted(Counter(event.get("seen_level") for event in near).items(), key=lambda item: item[0] if item[0] is not None else -1)]  # by level
    out += table(rows, ["looks like", "count", "likely Kestrel"]) if rows else ["none"]  # the table
    if near:  # any
        out.append(f"strength {stats(event.get('quality') for event in near)} (min/med/max); audio offset {stats(event.get('offset_hz') for event in near)} Hz")  # how strong, and where

    section("Receiver candidates (strong preambles and what became of them)")  # where signals are lost
    outcome = Counter()  # by level and stage reached
    for event in by["search"]:  # each logged candidate
        stage = "no header" if not event.get("header") else ("decoded" if event.get("ok") else (event.get("reason") or "header only"))  # how far it got
        outcome[(event.get("level"), stage)] += 1  # count it
    rows = [[level_name(level), stage, count] for (level, stage), count in sorted(outcome.items(), key=lambda item: (item[0][0] if item[0][0] is not None else -1, item[0][1]))]  # one row each
    out += table(rows, ["level", "got as far as", "count"]) if rows else ["none logged"]  # the table

    section("By UTC hour and band")  # when the path was open
    hours = defaultdict(Counter)  # (hour, band) -> counts
    for event in rx:  # decoded and failed frames
        result = event.get("station_result") or event.get("result", {})  # as above
        hours[((event.get("sig_utc") or event["utc"])[11:13], band_of(event.get("dial_khz")))]["decoded" if result.get("ok") else "failed"] += 1  # count it
    for event in near:  # near misses
        hours[((event.get("sig_utc") or event["utc"])[11:13], band_of(event.get("dial_khz")))]["near"] += 1  # count it
    rows = [[f"{hour}00", band, counts["decoded"], counts["failed"], counts["near"]] for (hour, band), counts in sorted(hours.items())]  # one row each
    out += table(rows, ["UTC", "band", "decoded", "failed", "near misses"]) if rows else ["none"]  # the table

    section("Transmissions")  # what this station sent
    starts = by["tx_start"]  # every keying
    groups = defaultdict(list)  # by kind and level
    for event in starts:  # each transmission
        groups[(event.get("kind"), event.get("level"))].append(event)  # into its group
    rows = [[kind, level_name(level), len(items), round(sum(item.get("seconds") or 0 for item in items), 1)] for (kind, level), items in sorted(groups.items(), key=lambda item: (str(item[0][0]), item[0][1] if item[0][1] is not None else -1))]  # one row each
    out += table(rows, ["kind", "level", "count", "airtime s"]) if rows else ["none"]  # the table
    if starts:  # any
        meters = by["tx_meter"]  # the radio's readings
        ends = by["tx_end"]  # every release
        out.append(f"drive (gain) {stats(event.get('gain') for event in starts)}; peak level {stats(event.get('peak_dbfs') for event in ends)} dBFS")  # the audio going out
        out.append(f"radio: power {stats(event.get('power_w') for event in meters)} W; ALC {stats(event.get('alc') for event in meters)}; SWR {stats(event.get('swr') for event in meters)}")  # the radio's meters
        high = sum(1 for event in meters if isinstance(event.get("alc"), (int, float)) and event["alc"] >= 0.5)  # readings with ALC too high
        if high:  # any
            out.append(f"warning: {high} of {len(meters)} meter readings had ALC at half scale or more (transmit audio too strong)")  # say so

    section("Received audio and timing")  # the input and the clocks
    audio = by["audio"]  # once a minute
    if audio:  # any
        out.append(f"input RMS {stats(event.get('rms_dbfs') for event in audio)} dBFS, peak {stats(event.get('peak_dbfs') for event in audio)} dBFS (min/med/max, once a minute)")  # the level
        out.append(f"strongest candidate each minute {stats(event.get('best_quality') for event in audio)} (noise alone stays under about 3.5)")  # the background
        lost = max((event.get("lost") or 0 for event in audio), default=0)  # the dropout count at its highest
        out.append(f"sound-card dropouts: {lost}")  # dropped audio
    clock = by["clock"]  # every ten minutes
    if clock:  # any
        out.append(f"sound card against computer clock: {stats(event.get('drift_s') for event in clock)} s (min/med/max)")  # the drift
    notes = by["note"]  # warnings and problems
    if notes:  # any
        out.append(f"{len(notes)} note(s); the last: {notes[-1].get('text')}")  # how many, and the latest
    if not (audio or clock or notes):  # nothing at all
        out.append("none")  # say so
    return out  # the report


def write_tables(events, folder):  # the optional CSV tables
    """Write each kind of event to its own CSV file in `folder`; return the files written."""
    os.makedirs(folder, exist_ok=True)  # make sure the folder is there
    by = defaultdict(list)  # events by kind
    for event in events:  # each one
        flat = {}  # the event with nested results flattened
        for name, value in event.items():  # each field
            if isinstance(value, dict):  # a nested result
                flat.update({f"{name}.{key}": (json.dumps(item) if isinstance(item, (dict, list)) else item) for key, item in value.items()})  # its fields, prefixed
            else:  # a plain field
                flat[name] = value  # as it is
        by[event.get("event")].append(flat)  # into its group
    written = []  # the files made
    for kind in ("rx", "near", "search", "tx_start", "tx_end", "tx_meter", "audio", "clock", "link", "tune", "note", "session_start", "session_end", "recording_file"):  # each kind
        rows = by.get(kind)  # its events
        if not rows:  # none
            continue  # no file
        columns = []  # every field any of them has, in order of first appearance
        for row in rows:  # each event
            columns += [name for name in row if name not in columns]  # new fields
        path = os.path.join(folder, f"{kind}.csv")  # the file
        with open(path, "w", newline="", encoding="utf-8") as handle:  # open it
            writer = csv.DictWriter(handle, fieldnames=columns)  # one column per field
            writer.writeheader()  # the headings
            writer.writerows(rows)  # the events
        written.append(path)  # note it
    return written  # the files


def redecode(events, folders):  # play the saved clips through the receiver again
    """Decode every clip named in `events` again; return report lines comparing then and now."""
    from live.recorder import read_wav  # loads WAV files  # (imported here: only this option needs the modem)
    from modem import receive  # the receiver
    lines, same, better, worse, missing = [], 0, 0, 0, 0  # the report, and counts
    for event in events:  # each event
        clip = event.get("clip")  # its clip, if one was saved
        if not clip:  # none
            continue  # nothing to do
        path = next((os.path.join(folder, clip) for folder in folders if os.path.exists(os.path.join(folder, clip))), None)  # find the file
        if path is None:  # removed, or elsewhere
            missing += 1  # count it
            continue  # next
        before = bool((event.get("station_result") or event.get("result") or {}).get("ok"))  # did it decode then?
        result = receive(read_wav(path)[0])  # decode it now
        if result.ok == before:  # the same
            same += 1  # count it
        elif result.ok:  # decodes now, did not then
            better += 1  # count it
            lines.append(f"  now decodes: {clip} (L{result.level}, SNR {result.snr_db:.1f} dB)")  # say which
        else:  # decoded then, not now
            worse += 1  # count it
            lines.append(f"  no longer decodes: {clip} ({result.reason})")  # say which
    return [f"Clips decoded again: {same} the same, {better} now decode, {worse} no longer decode, {missing} not found"] + lines  # the report


def main(argv=None):  # the script itself
    """Read the logs named, print the report, and write the tables if asked."""
    parser = argparse.ArgumentParser(description="Summarise Kestrel signal logs")  # describe the tool
    parser.add_argument("paths", nargs="+", help="signal log folder(s) or .jsonl file(s)")  # what to read
    parser.add_argument("--since", help="first UTC date to include, YYYY-MM-DD")  # optional start
    parser.add_argument("--until", help="last UTC date to include, YYYY-MM-DD")  # optional end
    parser.add_argument("--csv-dir", help="also write each kind of event as a CSV table into this folder")  # optional tables
    parser.add_argument("--redecode", action="store_true", help="decode every saved clip again and compare")  # optional re-decode
    args = parser.parse_args(argv)  # read the options
    events, files = load(args.paths, args.since, args.until)  # the events
    print(f"read {len(files)} file(s)")  # how many files
    print("\n".join(report(events)))  # the report
    if args.csv_dir:  # tables wanted
        for path in write_tables(events, args.csv_dir):  # write them
            print(f"wrote {path}")  # say where
    if args.redecode:  # re-decode wanted
        folders = sorted({os.path.dirname(os.path.abspath(name)) for name in files})  # clip names are relative to the log folders
        print("\n".join(redecode(events, folders)))  # the comparison
    return 0  # success


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # report and exit
