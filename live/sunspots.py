"""Predicted sunspot numbers for the propagation predictions (since 0.31R5).

The ITU-R P.533 prediction needs the 12-month smoothed sunspot number
(R12) for the month. It changes slowly and is forecast years ahead by
NOAA's Space Weather Prediction Center (SWPC), so Kestrel carries a table
of predicted monthly values and never needs the internet to make a
prediction. A table ("prediction set") is a small JSON file:

    {"kind": "kestrel-sunspots", "issued": "2026-11-24",
     "source": "NOAA SWPC predicted solar cycle",
     "url": "https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json",
     "months": {"2026-05": 86.7, "2026-06": 86.9, ...}}

"issued" is the date the set was made (NOAA's file carries no date of its
own, so a set fetched from NOAA is dated the day it was fetched). Three
places can hold a set, and the one with the latest "issued" date is used:

  1. the set shipped with the program (live/data/sunspots.json);
  2. a set fetched from NOAA with "Update online" (sunspots.json in the
     operator's Kestrel data folder);
  3. update files placed in the "updates" folder of the Kestrel data
     folder (any file named sunspots*.json there): this is how a set can
     be handed to a station with no internet connection.

The panel always shows which set is in use and its issue date.
"""

import glob  # lists files by pattern
import json  # reads and writes the sets
import os  # file paths
import time  # today's date
import urllib.request  # fetches NOAA's file

from .paths import code_dir, data_dir  # where the program's files and the operator's files are

NOAA_URL = "https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json"  # NOAA SWPC's predicted solar cycle (public domain, United States government work)
KIND = "kestrel-sunspots"  # the marker every set carries
BUNDLED = os.path.join(code_dir(), "live", "data", "sunspots.json")  # the set shipped with the program
SSN_MOST = 400.0  # no sensible sunspot number is larger (the record smoothed value is under 300)


def updates_folder():  # where update files are dropped
    """Return (creating it if needed) the folder where a sunspots*.json update file may be placed."""
    folder = os.path.join(data_dir(), "updates")  # the "updates" folder of the operator's Kestrel data folder
    os.makedirs(folder, exist_ok=True)  # make sure it exists
    return folder  # the folder


def downloaded_file():  # where an online update is kept
    """Return the path of the set fetched with Update online."""
    return os.path.join(data_dir(), "sunspots.json")  # in the operator's Kestrel data folder


def check(data):  # is this a usable set?
    """Return `data` with its months as floats if it is a usable prediction set; raise ValueError (with the reason) if not."""
    if not isinstance(data, dict) or data.get("kind") != KIND:  # not one of ours
        raise ValueError("not a Kestrel sunspot prediction file")  # say so
    issued = str(data.get("issued", ""))  # its date
    try:  # the date must be a real one
        time.strptime(issued, "%Y-%m-%d")  # year-month-day
    except ValueError:  # it is not
        raise ValueError(f"its issue date ({issued or 'none'}) is not a date") from None  # say so
    months = data.get("months")  # the values
    if not isinstance(months, dict) or not months:  # none
        raise ValueError("it holds no months")  # say so
    clean = {}  # the checked values
    for month, value in months.items():  # each month
        time.strptime(month, "%Y-%m")  # must be a year and month (raises ValueError otherwise)
        number = float(value)  # must be a number (raises ValueError otherwise)
        if not 0.0 <= number <= SSN_MOST:  # out of any sensible range
            raise ValueError(f"the value for {month} ({number}) is out of range")  # say so
        clean[month] = number  # keep it
    return dict(data, months=clean, issued=issued)  # the set, checked


def read(path):  # one set from a file
    """Return the checked set in the file at `path` (with "file" added), or raise ValueError / OSError."""
    with open(path, encoding="utf-8") as handle:  # open it
        data = check(json.load(handle))  # read and check it
    data["file"] = path  # remember where it came from
    return data  # the set


def candidates():  # every set present
    """Return every readable set: the shipped one, the downloaded one and any update files, with the reason for each file that was refused."""
    found, refused = [], []  # usable sets, and (file, reason) for the rest
    paths = [BUNDLED, downloaded_file()] + sorted(glob.glob(os.path.join(updates_folder(), "sunspots*.json")))  # where sets may be
    for path in paths:  # each place
        if not os.path.isfile(path):  # nothing there
            continue  # next
        try:  # it may be damaged or not ours
            found.append(read(path))  # keep it
        except (OSError, ValueError) as error:  # unusable
            refused.append((path, str(error)))  # note why
    return found, refused  # both lists


def current():  # the set in use
    """Return the set with the latest issue date (the shipped one wins a tie), or None if there is none at all."""
    found, _refused = candidates()  # every usable set
    if not found:  # none
        return None  # nothing to use
    return max(found, key=lambda s: s["issued"])  # the latest (max keeps the first of equals, and the shipped set comes first)


def ssn_for(year, month, table=None):  # the sunspot number for a month
    """Return (sunspot number, how it was found) for `year` and `month` (1-12) from `table` (the current set if None).

    A month inside the table is used as it is. Before the first month the
    first value is used, after the last month the last value; "how" says so,
    so the panel can warn that the set does not cover the month.
    """
    table = table or current()  # the set to use
    if table is None:  # no set at all
        return None, "no prediction set"  # nothing
    key = f"{year:04d}-{month:02d}"  # the month wanted, as the set writes it
    months = sorted(table["months"])  # the months held, in order
    if key in table["months"]:  # held
        return table["months"][key], "predicted"  # the value
    if key < months[0]:  # before the set starts
        return table["months"][months[0]], f"before the set (used {months[0]})"  # the first value
    if key > months[-1]:  # after it ends
        return table["months"][months[-1]], f"after the set (used {months[-1]})"  # the last value
    earlier = max(m for m in months if m < key)  # a gap inside the set: the nearest month before
    return table["months"][earlier], f"gap in the set (used {earlier})"  # its value


def describe(table=None):  # one line for the panel
    """Return a line saying which prediction set is in use and its issue date."""
    table = table or current()  # the set to use
    if table is None:  # none
        return "Sunspot predictions: none found"  # say so
    months = sorted(table["months"])  # the months held
    where = "shipped with Kestrel" if table.get("file") == BUNDLED else ("fetched online" if table.get("file") == downloaded_file() else f"update file {os.path.basename(table.get('file', ''))}")  # where it came from
    return f"Sunspot predictions: {table.get('source', 'unknown source')}, issued {table['issued']} ({where}; {months[0]} to {months[-1]})"  # the line


def from_noaa(records, issued=None):  # NOAA's records -> a set
    """Return a set made from the records of NOAA's predicted-solar-cycle.json, dated `issued` (today if None)."""
    months = {}  # the values
    for record in records:  # each month NOAA predicts
        tag, value = record.get("time-tag"), record.get("predicted_ssn")  # its month and predicted sunspot number
        if tag and value is not None and float(value) >= 0:  # a usable value (NOAA writes -1 for none)
            months[str(tag)] = round(float(value), 1)  # keep it
    return check({"kind": KIND, "issued": issued or time.strftime("%Y-%m-%d"), "source": "NOAA SWPC predicted solar cycle", "url": NOAA_URL, "months": months})  # the set, checked


def update_online(timeout=20):  # Update online
    """Fetch NOAA's latest prediction, save it as the downloaded set and return it; raise OSError or ValueError on failure."""
    request = urllib.request.Request(NOAA_URL, headers={"User-Agent": "Kestrel (amateur radio digital mode)"})  # the request, saying who asks
    with urllib.request.urlopen(request, timeout=timeout) as reply:  # fetch it
        records = json.loads(reply.read().decode("utf-8"))  # NOAA's records
    data = from_noaa(records)  # turn them into a set dated today
    save(data, downloaded_file())  # keep it
    data["file"] = downloaded_file()  # where it is now
    return data  # the new set


def save(data, path):  # write a set
    """Write the set `data` (without its "file" note) to `path` as JSON."""
    plain = {k: v for k, v in data.items() if k != "file"}  # the set as stored
    folder = os.path.dirname(path)  # its folder
    if folder:  # one is named
        os.makedirs(folder, exist_ok=True)  # make sure it exists
    with open(path, "w", encoding="utf-8") as handle:  # write it
        json.dump(plain, handle, indent=1, sort_keys=True)  # readable, in a fixed order
        handle.write("\n")  # end with a new line


def import_file(path):  # Load an update file...
    """Check the update file at `path` and copy it into the updates folder; return the set. Raises ValueError or OSError if it is unusable."""
    data = read(path)  # read and check it
    target = os.path.join(updates_folder(), f"sunspots-{data['issued']}.json")  # its name in the updates folder, by issue date
    save(data, target)  # copy it there
    data["file"] = target  # where it is now
    return data  # the set
