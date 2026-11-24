"""Today's measured ionosphere and space weather, for the propagation predictions (since 0.34R1).

The P.533 prediction normally uses NOAA's predicted 12-month smoothed sunspot
number for the month (live/sunspots.py). That describes a typical day of the
month; the ionosphere on a given day can be well above or below it. Two
public sources say what it is doing now, and Kestrel can use them when the
operator presses "Update online" (nothing here is fetched on its own):

  * the effective sunspot number (eSSN) of prop.kc2g.com, worked out every
    15 minutes from the world's ionosondes: the sunspot number that makes the
    ionospheric model match what is measured. Its 24-hour average stands in
    for the month's predicted number when predicting for the current month;
    the 6-hour average against the 24-hour one shows a sudden drop.
  * NOAA SWPC's space-weather scales (R radio blackouts from solar flares,
    G geomagnetic storms) and the planetary K index: the things P.533 never
    includes, shown as warnings next to the prediction.

The last answer is kept in spaceweather.json in the operator's Kestrel data
folder, so the warnings survive a restart; anything older than STALE_S is
treated as unknown, never as quiet.
"""

import json  # reads and writes the saved answer
import os  # file paths
import time  # clocks
import urllib.request  # fetches the sources

from .paths import data_dir  # the operator's Kestrel data folder

ESSN_URL = "https://prop.kc2g.com/api/essn.json"  # KC2G's effective sunspot number (24-hour and 6-hour series)
SCALES_URL = "https://services.swpc.noaa.gov/products/noaa-scales.json"  # NOAA's R, S and G scales now
KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"  # NOAA's estimated planetary K index, one value a minute
AGENT = {"User-Agent": "Kestrel (amateur radio digital mode)"}  # who asks
STALE_S = 6 * 3600  # an answer older than six hours is not used
DROP = 0.85  # the 6-hour eSSN below 85 per cent of the 24-hour one: the ionosphere has just weakened
KP_STORM = 5.0  # K index 5 or more: a geomagnetic storm (NOAA G1 or worse)


def saved_file():  # where the last answer is kept
    """Return the path of the saved answer."""
    return os.path.join(data_dir(), "spaceweather.json")  # in the operator's Kestrel data folder


def _fetch(url, timeout):  # one source
    """Return the JSON at `url`; raise OSError or ValueError on failure."""
    request = urllib.request.Request(url, headers=AGENT)  # the request, saying who asks
    with urllib.request.urlopen(request, timeout=timeout) as reply:  # fetch it
        return json.loads(reply.read().decode("utf-8"))  # its JSON


def essn_from(data):  # KC2G's answer -> (24-hour eSSN, 6-hour eSSN, its time)
    """Return the latest 24-hour and 6-hour effective sunspot numbers and the time of the 24-hour one (seconds since 1970)."""
    def latest(series):  # the newest entry of a series
        points = [p for p in series or [] if isinstance(p, dict) and p.get("ssn") is not None and p.get("time")]  # usable entries
        return max(points, key=lambda p: p["time"]) if points else None  # the newest, or none
    day, six = latest(data.get("24h")), latest(data.get("6h"))  # both series
    if day is None:  # nothing usable
        raise ValueError("the eSSN answer holds no values")  # say so
    return float(day["ssn"]), (float(six["ssn"]) if six else None), int(day["time"])  # the numbers


def scales_from(data):  # NOAA's scales -> (R, G) now
    """Return the R (radio blackout) and G (geomagnetic storm) scale levels now, 0 to 5."""
    now = data.get("0") if isinstance(data, dict) else None  # entry "0" is the present
    if not isinstance(now, dict):  # not the expected shape
        raise ValueError("the NOAA scales answer has an unexpected shape")  # say so
    def level(key):  # one scale's level
        value = (now.get(key) or {}).get("Scale")  # e.g. "2", or None / "none"
        try:  # it may be missing
            return int(value)  # the level
        except (TypeError, ValueError):  # missing or "none"
            return 0  # none
    return level("R"), level("G")  # both


def kp_from(data):  # NOAA's K index records -> the latest value
    """Return the latest estimated planetary K index from NOAA's one-minute records (either list of records or table with a heading row)."""
    rows = data if isinstance(data, list) else []  # the records
    for row in reversed(rows):  # newest last
        if isinstance(row, dict):  # a record with named fields
            value = row.get("estimated_kp", row.get("kp_index"))  # the value
        elif isinstance(row, list) and len(row) > 1:  # a table row (older format): time, value, ...
            value = row[1]  # the value
        else:  # something else
            continue  # skip it
        try:  # it may be text
            return float(value)  # the value
        except (TypeError, ValueError):  # the heading row, or blank
            continue  # keep looking
    raise ValueError("the K index answer holds no values")  # nothing usable


def update_online(timeout=20):  # Update online
    """Fetch every source, save the answer and return it. A source that fails is left out (its error noted); raise OSError only if all fail."""
    answer = {"fetched": int(time.time()), "errors": {}}  # the answer, timed
    try:  # KC2G
        answer["essn_24h"], answer["essn_6h"], answer["essn_time"] = essn_from(_fetch(ESSN_URL, timeout))  # the effective sunspot numbers
    except (OSError, ValueError) as error:  # no answer
        answer["errors"]["essn"] = str(error)  # noted
    try:  # NOAA's scales
        answer["r_scale"], answer["g_scale"] = scales_from(_fetch(SCALES_URL, timeout))  # flares and storms
    except (OSError, ValueError) as error:  # no answer
        answer["errors"]["scales"] = str(error)  # noted
    try:  # NOAA's K index
        answer["kp"] = kp_from(_fetch(KP_URL, timeout))  # the K index
    except (OSError, ValueError) as error:  # no answer
        answer["errors"]["kp"] = str(error)  # noted
    if len(answer["errors"]) == 3:  # nothing at all
        raise OSError("; ".join(f"{k}: {v}" for k, v in answer["errors"].items()))  # say why
    with open(saved_file(), "w", encoding="utf-8") as handle:  # keep it
        json.dump(answer, handle, indent=1, sort_keys=True)  # readable
    return answer  # the answer


def current(now=None):  # the saved answer, if fresh
    """Return the saved answer if it is younger than STALE_S, else None."""
    try:  # there may be none
        with open(saved_file(), encoding="utf-8") as handle:  # read it
            answer = json.load(handle)  # the answer
    except (OSError, ValueError):  # none, or damaged
        return None  # unknown
    age = (now or time.time()) - float(answer.get("fetched", 0))  # how old
    return answer if 0 <= age < STALE_S else None  # fresh, or unknown


def measured_ssn(answer=None):  # the sunspot number to use for the current month
    """Return the 24-hour effective sunspot number if a fresh answer holds one, else None."""
    answer = answer if answer is not None else current()  # the answer to use
    return None if not answer else answer.get("essn_24h")  # the number, or none


def ssn_for(year, month, now=None):  # the sunspot number a prediction should use
    """Return (sunspot number, how it was found) for `year`/`month`: today's measured eSSN for the current month when fresh, else the month's prediction."""
    from . import sunspots  # the predicted numbers (imported here to keep this module light)
    today = time.gmtime(now)  # this month, UTC
    measured = measured_ssn(current(now))  # today's measured number, if fresh
    if measured is not None and (year, month) == (today.tm_year, today.tm_mon):  # the current month, and measured today
        return measured, "measured today (KC2G eSSN, 24 h)"  # use it
    return sunspots.ssn_for(year, month)  # the prediction


def warnings(answer=None):  # what P.533 does not know about
    """Return a list of short warnings from the answer (empty when quiet or unknown)."""
    answer = answer if answer is not None else current()  # the answer to use
    if not answer:  # nothing fresh
        return []  # no warnings (the panel says the data is missing instead)
    out = []  # the warnings
    if answer.get("r_scale", 0) >= 1:  # a flare is blacking out the sunlit side
        out.append(f"Radio blackout R{answer['r_scale']} (solar flare): the low bands fail first on daylight paths; try the highest open band, or wait an hour")  # what to do
    kp = answer.get("kp")  # the K index
    if kp is not None and kp >= KP_STORM:  # a geomagnetic storm
        out.append(f"Geomagnetic storm (Kp {kp:.1f}): expect fading and a lower MUF than predicted, worst on northern paths")  # what to expect
    six, day = answer.get("essn_6h"), answer.get("essn_24h")  # recent and daily eSSN
    if six is not None and day and six < DROP * day:  # it has just fallen
        out.append(f"Ionosphere weakening: effective sunspot number {six:.0f} over 6 hours against {day:.0f} over 24; the higher bands may close early")  # what to expect
    return out  # the list


def describe(answer=None):  # one line for the panel
    """Return a line saying what is known now, or that nothing fresh is known."""
    answer = answer if answer is not None else current()  # the answer to use
    if not answer:  # nothing fresh
        return "Space weather: not known (press Update online)"  # say so
    parts = []  # the pieces
    if answer.get("essn_24h") is not None:  # the eSSN
        parts.append(f"measured sunspot number {answer['essn_24h']:.0f} (KC2G eSSN, 24 h)")  # shown
    if answer.get("kp") is not None:  # the K index
        parts.append(f"Kp {answer['kp']:.1f}")  # shown
    if "r_scale" in answer:  # the scales
        parts.append(f"R{answer['r_scale']} G{answer['g_scale']}")  # shown
    age = int((time.time() - answer["fetched"]) // 60)  # minutes since
    return f"Space weather ({age} min ago): " + ", ".join(parts)  # the line
