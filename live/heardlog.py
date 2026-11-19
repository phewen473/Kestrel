"""The stations-heard log: every station decoded in the last 48 hours, kept on disk.

Each reception is one line of JSON in a file in the local/ folder, so
the log survives closing the panel. Lines older than the keeping time
are dropped when the log is opened and from time to time while it runs.
The panel shows the log under Stations > Stations heard (last 48 hours),
and builds telemetry messages (live/telemetry.py) from it.
"""

import json  # one JSON record per line
import os  # file paths
import threading  # the working thread adds records while the window reads them
import time  # the clock

KEEP_S = 48 * 3600.0  # how long a reception is kept (48 hours)


class HeardLog:  # the log of stations heard
    """Receptions as dicts: t (seconds since 1970), call, grid, snr, level, kind, dial_khz."""

    def __init__(self, path, keep_s=KEEP_S):  # open the log
        self.path = path  # the file it lives in
        self.keep_s = keep_s  # how long a reception is kept
        self.lock = threading.Lock()  # one thread at a time changes the records
        self.records = []  # the receptions, oldest first
        try:  # the file may not exist yet
            with open(path, "r", encoding="utf-8") as handle:  # open it
                for line in handle:  # each reception
                    try:  # a line may be damaged (the program stopped while writing)
                        self.records.append(json.loads(line))  # keep it
                    except ValueError:  # not JSON
                        continue  # skip it
        except OSError:  # no file yet
            pass  # start empty
        self.prune(rewrite=True)  # drop old receptions, and the file with them

    def add(self, call, grid="", snr=0.0, level=0, kind="", dial_khz=0.0, t=None):  # note one reception
        """Add a reception (now, unless `t` is given) and append it to the file."""
        record = {"t": time.time() if t is None else t, "call": call, "grid": grid, "snr": round(float(snr), 1), "level": int(level), "kind": kind, "dial_khz": dial_khz}  # the reception
        with self.lock:  # one thread at a time
            self.records.append(record)  # keep it
            try:  # the disk may refuse
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)  # make sure the folder is there
                with open(self.path, "a", encoding="utf-8") as handle:  # append to the file
                    handle.write(json.dumps(record) + "\n")  # one line
            except OSError:  # it could not be written
                pass  # the record is still kept in memory
        return record  # what was added

    def prune(self, now=None, rewrite=False):  # forget receptions older than the keeping time
        """Drop receptions older than the keeping time; with `rewrite`, write the file again without them."""
        cutoff = (time.time() if now is None else now) - self.keep_s  # the oldest time kept
        with self.lock:  # one thread at a time
            before = len(self.records)  # how many there were
            self.records = [record for record in self.records if record.get("t", 0) >= cutoff]  # keep the recent ones
            if rewrite and (before != len(self.records) or not os.path.exists(self.path)):  # the file holds old lines (or does not exist)
                try:  # the disk may refuse
                    os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)  # make sure the folder is there
                    with open(self.path, "w", encoding="utf-8") as handle:  # write it afresh
                        handle.writelines(json.dumps(record) + "\n" for record in self.records)  # the recent receptions only
                except OSError:  # it could not be written
                    pass  # memory still holds the right records

    def snapshot(self):  # a copy of the records, safe to read from another thread
        """Return a list of the receptions, oldest first."""
        with self.lock:  # one thread at a time
            return list(self.records)  # a copy

    def summary(self):  # one row per station
        """Return dicts with call, grid, first, last, count, best_snr, last_snr, best_level and dial_khz, most recently heard first."""
        rows = {}  # callsign -> its row
        for record in self.snapshot():  # oldest first
            row = rows.setdefault(record["call"], {"call": record["call"], "grid": "", "first": record["t"], "count": 0, "best_snr": -99.0, "best_level": 0})  # the station's row
            row["count"] += 1  # one more reception
            row["last"], row["last_snr"], row["dial_khz"] = record["t"], record["snr"], record.get("dial_khz", 0.0)  # the newest reading
            row["best_snr"] = max(row["best_snr"], record["snr"])  # the strongest reading
            row["best_level"] = max(row["best_level"], record.get("level", 0))  # the fastest level decoded
            row["grid"] = record.get("grid") or row["grid"]  # a grid locator, once one is known
        return sorted(rows.values(), key=lambda row: -row["last"])  # most recent first
