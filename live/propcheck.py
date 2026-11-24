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

COLUMNS = ("utc", "call", "band", "from_grid", "to_grid", "miles", "heard_snr_db", "predicted_snr_db", "predicted_reliability", "ssn", "ssn_source")  # the record's columns
_done = {}  # (call, band, hour) -> True once recorded this hour
_lock = threading.Lock()  # one writer at a time


def record_file():  # where the record is kept
    """Return the path of prop_check.csv."""
    return os.path.join(data_dir(), "prop_check.csv")  # in the data folder


def _write(row):  # one line
    """Append `row` (a dict) to the record, with the heading if the file is new."""
    path = record_file()  # the file
    with _lock:  # one at a time
        new = not os.path.isfile(path)  # first line?
        with open(path, "a", newline="", encoding="utf-8") as handle:  # append
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)  # the columns
            if new:  # a new file
                writer.writeheader()  # the heading first
            writer.writerow(row)  # the line


def check(call, own_grid, far_grid, band, heard_snr, power_w=100.0, noise="RURAL", now=None, wait=False):  # one station heard
    """Predict the path from `far_grid` to `own_grid` on `band` ("40 m") for this hour and record it beside `heard_snr`.

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
    key = (call, band, t.tm_year, t.tm_yday, t.tm_hour)  # once per station, band and hour
    with _lock:  # one at a time
        if key in _done:  # done already
            return None  # nothing more
        _done[key] = True  # claimed

    def job():  # the prediction (a second or two)
        ssn, how = spaceweather.ssn_for(t.tm_year, t.tm_mon, now)  # today's measured number, or the month's prediction
        if ssn is None:  # no number at all
            return None  # nothing recorded
        try:  # the program may fail
            rows = propagation.predict(far_grid, own_grid, t.tm_year, t.tm_mon, ssn, power_w, noise, bands={band: propagation.band_frequencies()[band]})  # from them to here, this band only
        except Exception:  # noqa: BLE001 - a failed prediction is simply not recorded
            return None  # nothing recorded
        hit = next((r for r in rows if r["hour"] == t.tm_hour and r["band"] == band), None)  # this hour
        if hit is None:  # not there
            return None  # nothing recorded
        far = __import__("live.contacts", fromlist=["distance_bearing"]).distance_bearing(far_grid, own_grid)  # the distance
        row = {"utc": time.strftime("%Y-%m-%d %H:%M", t), "call": call, "band": band, "from_grid": far_grid, "to_grid": own_grid, "miles": round(far[0]) if far else "",  # where
               "heard_snr_db": round(heard_snr, 1), "predicted_snr_db": round(hit["snr"], 1), "predicted_reliability": round(hit["reliability"]), "ssn": round(ssn), "ssn_source": how}  # what
        _write(row)  # kept
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
                if row["utc"] >= since:  # inside the window
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
