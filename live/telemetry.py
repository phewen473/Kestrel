"""Telemetry messages: what one station hears, in a short fixed form other Kestrel panels can read.

A telemetry message is ordinary message text (Section 6.12 of the
specification). It starts with the tag TLM1 and lists the sending
station's grid locator, its transmit power, how many stations it has
heard in the last 30 minutes, and, strongest first, each of those
stations with the median signal-to-noise ratio it was heard at and the
fastest speed level decoded from it:

    TLM1 EM92 P50 N3 Q1AAAA+05L3 Q2BB-08L1 Q3CCC-15L0

Comparing the telemetry of several stations shows which of them hears
the most stations, and hears them best: the natural choice for net
control. Text may come before the tag (a callsign, for example); the
receiving panel finds the tag wherever it is.
"""

import re  # reads the station entries back
import statistics  # the median of a station's readings

TAG = "TLM1"  # the tag that marks a telemetry message, version 1 of its layout
WINDOW_S = 1800.0  # stations heard in this many seconds before the message is built are counted (30 minutes)
MAX_CHARS = 200  # the longest message Kestrel carries
ENTRY = re.compile(r"^([A-Z0-9/]+)([+-]\d{1,2})L(\d)$")  # one station entry: callsign, signed SNR, L and level


def summarize(records, now, window_s=WINDOW_S):  # boil the heard log down to one line per station
    """Return [(callsign, median SNR, fastest level)] for the stations in `records` heard within `window_s` seconds of `now`, strongest first.

    `records` are dicts with at least "t" (seconds since 1970), "call",
    "snr" and "level", as kept by live.heardlog.HeardLog.
    """
    readings = {}  # callsign -> list of (SNR, level)
    for record in records:  # every reception in the log
        if now - record["t"] <= window_s and record.get("call"):  # recent enough, and it named its sender
            readings.setdefault(record["call"], []).append((float(record.get("snr", -30.0)), int(record.get("level", 0))))  # add the reading
    rows = [(call, statistics.median(snr for snr, _ in seen), max(level for _, level in seen)) for call, seen in readings.items()]  # one row per station
    rows.sort(key=lambda row: (-row[1], row[0]))  # strongest first; equal readings in callsign order
    return rows  # the summary


def build(grid, power_w, heard, max_chars=MAX_CHARS, prefix=""):  # write the telemetry message
    """Return the telemetry text for this station: `grid`, `power_w` (watts, or None if unknown) and `heard` as given by summarize().

    `prefix` (a callsign, say) goes in front of the tag. Station entries are
    added strongest first until the next one would not fit in `max_chars`;
    the count N still gives the number of stations heard.
    """
    power = f"P{int(round(power_w))}" if power_w is not None else "P?"  # the power, or a question mark if the radio did not say
    text = f"{prefix.strip() + ' ' if prefix.strip() else ''}{TAG} {grid.strip().upper() or '?'} {power} N{len(heard)}"  # the fixed part
    for call, snr, level in heard:  # each station, strongest first
        snr = max(-99, min(99, int(round(snr))))  # whole decibels, kept to two digits
        entry = f" {call}{snr:+03d}L{level}"  # callsign, SNR with its sign, and the fastest level
        if len(text) + len(entry) > max_chars:  # it would not fit
            break  # stop here
        text += entry  # add it
    return text  # the message


def parse(text):  # read a telemetry message
    """Return a dict with grid, power_w (None if unknown), count and stations [(call, snr, level)], or None if `text` holds no telemetry."""
    words = text.strip().upper().split()  # the message, word by word
    if TAG not in words:  # no telemetry tag
        return None  # not a telemetry message
    rest = words[words.index(TAG) + 1:]  # what follows the tag
    if len(rest) < 3 or not rest[1].startswith("P") or not rest[2].startswith("N"):  # the fixed part is missing
        return None  # not readable
    try:  # the numbers may be damaged
        power = None if rest[1] == "P?" else float(rest[1][1:])  # watts, if given
        count = int(rest[2][1:])  # stations heard
    except ValueError:  # not numbers
        return None  # not readable
    stations = []  # the station entries
    for word in rest[3:]:  # each remaining word
        found = ENTRY.match(word)  # is it a station entry?
        if found:  # yes
            stations.append((found.group(1), int(found.group(2)), int(found.group(3))))  # keep it
    return {"grid": rest[0], "power_w": power, "count": count, "stations": stations}  # what the sender hears


def score(info):  # a rough figure for comparing candidates for net control
    """Return (stations heard, median SNR of those listed) for a parsed telemetry message: more stations first, then stronger."""
    snrs = [snr for _, snr, _ in info["stations"]]  # the listed readings
    return info["count"], (statistics.median(snrs) if snrs else -99.0)  # the two figures
