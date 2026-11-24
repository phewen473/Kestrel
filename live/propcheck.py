"""Checking the propagation predictions against what is actually heard (since 0.35).

Each time a station with a known grid locator is decoded, the P.533
prediction for that path, band and hour is worked out (in the background,
at most once per station, band and hour) and written beside the SNR
actually heard, in prop_check.csv in the Kestrel data folder. Over weeks
this shows how far the predictions can be trusted on this station's own
paths, and whether they run high or low. summary() gives the figures the
Propagation window shows.
"""

import csv  # the record
import math  # NaN checks
import os  # paths
import threading  # predictions run in the background
import time  # clocks

from .paths import data_dir  # the operator's Kestrel data folder

COLUMNS = ("utc", "call", "band", "from_grid", "to_grid", "miles", "heard_snr_db", "predicted_snr_db", "predicted_reliability", "ssn", "ssn_source", "direction", "power_w")  # the record's columns (direction and power since 0.39: "in" is the station heard here, "out" is this station as the other one reported hearing it)
GAP_DB = 10.0  # a station heard this much below its prediction (either way) is worth telling the operator about (since 0.39)
SIDE_DB = 8.0  # one direction this much further below its prediction than the other points to one end of the path (since 0.39)
_done = {}  # (call, band, hour) -> True once recorded this hour
_lock = threading.Lock()  # one writer at a time


def record_file():  # where the record is kept
    """Return the path of prop_check.csv."""
    return os.path.join(data_dir(), "prop_check.csv")  # in the data folder


def _upgrade(path):  # a record written before 0.39 has fewer columns (the lock is held)
    """Rewrite `path` with the present COLUMNS if its heading is an older one; old lines become direction "in" with no power."""
    try:  # it may not exist
        with open(path, newline="", encoding="utf-8") as handle:  # read it
            rows = list(csv.DictReader(handle))  # every line, by its own heading
            handle.seek(0)  # back to the start
            heading = next(csv.reader(handle), [])  # the heading as written
    except OSError:  # no file yet
        return  # nothing to do
    if tuple(heading) == COLUMNS:  # already the present layout
        return  # nothing to do
    with open(path, "w", newline="", encoding="utf-8") as handle:  # write it again
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")  # the present columns
        writer.writeheader()  # the heading
        for row in rows:  # each old line
            row.setdefault("direction", "in")  # old lines were all stations heard here
            writer.writerow({name: row.get(name) or ("in" if name == "direction" else "") for name in COLUMNS})  # kept


def _write(row):  # one line
    """Append `row` (a dict) to the record, with the heading if the file is new."""
    path = record_file()  # the file
    with _lock:  # one at a time
        _upgrade(path)  # a record from before 0.39 gets the new columns first
        new = not os.path.isfile(path)  # first line?
        with open(path, "a", newline="", encoding="utf-8") as handle:  # append
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)  # the columns
            if new:  # a new file
                writer.writeheader()  # the heading first
            writer.writerow(row)  # the line


def check(call, own_grid, far_grid, band, heard_snr, power_w=100.0, noise="RURAL", now=None, wait=False, direction="in", on_row=None):  # one station heard, or one report of how it heard this station (on_row: called with the row once written, since 0.39)
    """Predict the path from `far_grid` to `own_grid` on `band` ("40 m") for this hour and record it beside `heard_snr`.

    With direction="out" (since 0.39) the path is the other way, from
    `own_grid` to `far_grid`, and `heard_snr` is the SNR the other station
    reported for this station's signal; `power_w` is then this station's
    transmit power, and for "in" the other station's (as far as known).

    Runs in the background (or at once with wait=True); does nothing if
    this station, band and hour were already recorded, if a grid or the
    SNR is missing, or if the propagation program is not installed.
    Returns the thread (or the row when wait=True), or None.
    """
    from . import propagation, spaceweather  # the predictions and the sunspot number to use (imported here: they are heavier)
    if not call or not own_grid or not far_grid or heard_snr is None or not math.isfinite(heard_snr) or propagation.missing():  # cannot check
        return None  # nothing done
    if band not in propagation.band_frequencies():  # not a band P.533 covers (6 m)
        return None  # nothing done
    now = now or time.time()  # now
    t = time.gmtime(now)  # this hour, UTC
    key = (call, band, t.tm_year, t.tm_yday, t.tm_hour, direction)  # once per station, band, hour and direction
    with _lock:  # one at a time
        if key in _done:  # done already
            return None  # nothing more
        _done[key] = True  # claimed

    def job():  # the prediction (a second or two)
        ssn, how = spaceweather.ssn_for(t.tm_year, t.tm_mon, now)  # today's measured number, or the month's prediction
        if ssn is None:  # no number at all
            return None  # nothing recorded
        try:  # the program may fail
            sender, hearer = (own_grid, far_grid) if direction == "out" else (far_grid, own_grid)  # which way the signal went
            rows = propagation.predict(sender, hearer, t.tm_year, t.tm_mon, ssn, power_w, noise, bands={band: propagation.band_frequencies()[band]})  # from the sender to the hearer, this band only
        except Exception:  # noqa: BLE001 - a failed prediction is simply not recorded
            return None  # nothing recorded
        hit = next((r for r in rows if r["hour"] == t.tm_hour and r["band"] == band), None)  # this hour
        if hit is None:  # not there
            return None  # nothing recorded
        far = __import__("live.contacts", fromlist=["distance_bearing"]).distance_bearing(far_grid, own_grid)  # the distance
        row = {"utc": time.strftime("%Y-%m-%d %H:%M", t), "call": call, "band": band, "from_grid": sender, "to_grid": hearer, "miles": round(far[0]) if far else "",  # where
               "heard_snr_db": round(heard_snr, 1), "predicted_snr_db": round(hit["snr"], 1), "predicted_reliability": round(hit["reliability"]), "ssn": round(ssn), "ssn_source": how,  # (continued)
               "direction": direction, "power_w": round(float(power_w), 1)}  # what, which way, and at what power
        _write(row)  # kept
        if on_row is not None:  # someone wants to know
            try:  # its fault must not stop the record
                on_row(row)  # told
            except Exception:  # noqa: BLE001 - anything at all
                pass  # the record is kept regardless
        return row  # the line

    if wait:  # at once (tests)
        return job()  # the row
    thread = threading.Thread(target=job, daemon=True)  # in the background
    thread.start()  # run it
    return thread  # the thread


def summary(days=30, now=None):  # how good the predictions have been
    """Return (lines checked, mean of heard minus predicted SNR, mean absolute difference) over the last `days`, or (0, None, None)."""
    path = record_file()  # the file
    if not os.path.isfile(path):  # nothing yet
        return 0, None, None  # nothing
    since = time.strftime("%Y-%m-%d %H:%M", time.gmtime((now or time.time()) - days * 86400))  # the start of the window
    diffs = []  # heard minus predicted
    with open(path, newline="", encoding="utf-8") as handle:  # read it
        for row in csv.DictReader(handle):  # each line
            try:  # a damaged line is skipped
                if row["utc"] >= since and (row.get("direction") or "in") == "in":  # inside the window, a station heard here (as before 0.39)
                    diffs.append(float(row["heard_snr_db"]) - float(row["predicted_snr_db"]))  # the difference
            except (KeyError, ValueError):  # damaged
                continue  # next
    if not diffs:  # none in the window
        return 0, None, None  # nothing
    return len(diffs), sum(diffs) / len(diffs), sum(abs(d) for d in diffs) / len(diffs)  # count, bias, typical error


def describe_summary(days=30):  # one line for the Propagation window
    """Return a line comparing the predictions with what was heard."""
    n, bias, err = summary(days)  # the figures
    if not n:  # nothing yet
        return "Predictions against stations heard: nothing recorded yet (each decoded station with a grid is checked)"  # say so
    return f"Predictions against {n} stations heard (last {days} days): heard {bias:+.1f} dB against predicted on average, typically {err:.1f} dB apart"  # the line


def station_gaps(call, days=30, now=None):  # one station's measured SNR against its prediction, both ways (since 0.39)
    """Return {"in": (count, mean heard minus predicted, latest row), "out": (...)} for `call` over the last `days`; a direction with no lines is left out."""
    path = record_file()  # the file
    if not os.path.isfile(path):  # nothing yet
        return {}  # nothing
    since = time.strftime("%Y-%m-%d %H:%M", time.gmtime((now or time.time()) - days * 86400))  # the start of the window
    found = {}  # direction -> list of (difference, row)
    with open(path, newline="", encoding="utf-8") as handle:  # read it
        for row in csv.DictReader(handle):  # each line
            try:  # a damaged line is skipped
                if row["call"] == call and row["utc"] >= since:  # this station, inside the window
                    found.setdefault(row.get("direction") or "in", []).append((float(row["heard_snr_db"]) - float(row["predicted_snr_db"]), row))  # its difference
            except (KeyError, ValueError):  # damaged
                continue  # next
    return {way: (len(items), sum(d for d, _ in items) / len(items), items[-1][1]) for way, items in found.items()}  # count, mean difference, latest line


def verdict(gaps):  # what one station's gaps point to, in words (since 0.39)
    """Return a short sentence on what `gaps` (from station_gaps) suggest, or "" when there is nothing worth saying."""
    gap_in = gaps.get("in", (0, None, None))[1]  # how far below its prediction this station hears the other
    gap_out = gaps.get("out", (0, None, None))[1]  # how far below its prediction the other hears this station
    if gap_in is not None and gap_out is not None:  # both ways known
        if gap_out - gap_in <= -SIDE_DB:  # this station's signal falls much further short
            return "your signal falls much further short than theirs: look at your transmit side (power, antenna) or noise at their end"  # which end
        if gap_in - gap_out <= -SIDE_DB:  # their signal falls much further short
            return "their signal falls much further short than yours: look at noise or the antenna at your end, or their transmit side"  # which end
        if max(gap_in, gap_out) <= -GAP_DB:  # both well short, by about the same
            return "both ways fall short by about the same: the path itself (antennas at both ends, or the prediction) rather than one station"  # the path
        return ""  # close enough to the prediction
    one = gap_in if gap_in is not None else gap_out  # the one direction known
    if one is not None and one <= -GAP_DB:  # well short
        return "well below the prediction; a report from the other way would show which end"  # what is missing
    return ""  # nothing to say


def describe_station(call, days=30):  # one station's prediction check, for its contact window and the Activity log (since 0.39)
    """Return a line such as "heard here +9 dB (predicted +20, 11 dB short); they hear you -11 dB (predicted +14, 25 dB short): ..." or "" when nothing is recorded."""
    gaps = station_gaps(call, days)  # both ways
    parts = []  # the pieces
    for way, words in (("in", "heard here"), ("out", "they hear you")):  # each direction
        if way in gaps:  # known
            count, mean, latest = gaps[way]  # the figures
            parts.append(f"{words} {float(latest['heard_snr_db']):+.0f} dB (predicted {float(latest['predicted_snr_db']):+.0f}; {abs(mean):.0f} dB {'short' if mean < 0 else 'over'} on average, {count} check{'s' if count != 1 else ''})")  # the latest, and the average gap
    if not parts:  # nothing yet
        return ""  # nothing to say
    said = verdict(gaps)  # what it points to
    return "; ".join(parts) + (f": {said}" if said else "")  # one line
