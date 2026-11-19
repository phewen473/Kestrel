"""Preselected Kestrel frequencies, and the operator's own.

One meeting frequency per band, so stations know where to find each
other. Each is a DIAL frequency for upper sideband: the Kestrel signal
sits from 500 Hz to 2500 Hz above it.

Every one keeps the whole signal inside a band segment that FCC rule
97.221(b) allows for automatically controlled stations, so the same
frequency serves an operator at the controls and a station left running
to hold and deliver mail.

These are suggestions for the United States, chosen in November 2026.
Always listen first: the segments are shared with other data modes.
"""

import json  # the operator's own frequencies are kept in a small JSON file
import os  # file paths

SIGNAL_LOW_HZ = 500.0  # the lowest audio frequency allowed for (the fastest level reaches down to about 800 Hz)
SIGNAL_HIGH_HZ = 2500.0  # the highest audio frequency allowed for (the fastest level reaches up to about 2200 Hz)

PRESETS_KHZ = {  # band name (metres) -> dial frequency in kHz, upper sideband
    "40": 7101.5,  # signal 7102.0 to 7104.0 kHz, inside 7100-7105
    "30": 10144.0,  # signal 10144.5 to 10146.5 kHz, inside 10140-10150 and clear of the FT4, WSPR and PSK activity at the bottom of that segment
    "20": 14108.5,  # signal 14109.0 to 14111.0 kHz, inside 14100.5-14112 and clear of the beacons on 14100
}  # end of the table

WORKING_KHZ = {  # band name (metres) -> working dial frequencies in kHz, upper sideband, in order of preference
    "40": (7106.5, 7109.0),  # signals 7107.0-7109.0 and 7109.5-7111.5 kHz: just above the 7100-7105 segment, so for attended stations only
    "30": (10146.5, 10141.5),  # signals 10147.0-10149.0 and 10142.0-10144.0 kHz, both inside 10140-10150; the upper one first, away from the FT4 activity
    "20": (14106.0, 14103.5, 14101.0),  # signals 14106.5-14108.5, 14104.0-14106.0 and 14101.5-14103.5 kHz, all inside 14100.5-14112
}  # end of the table

AUTOMATIC_SEGMENTS_KHZ = (  # HF segments of 97.221(b), in kHz
    (3585.0, 3600.0), (7100.0, 7105.0), (10140.0, 10150.0), (14095.0, 14099.5), (14100.5, 14112.0),  # 80, 40, 30 and 20 metres
    (18105.0, 18110.0), (21090.0, 21100.0), (24925.0, 24930.0), (28120.0, 28189.0),  # 17, 15, 12 and 10 metres
)  # end of the table


def dial_khz(band):  # look up a band's preset
    """Return the preset dial frequency in kHz for `band` ("40", "30" or "20"; "40m" and the like are accepted)."""
    key = str(band).lower().rstrip("m")  # allow "20m" as well as "20"
    if key not in PRESETS_KHZ:  # no preset for that band
        raise ValueError(f"no preset for band '{band}'; choose from {', '.join(sorted(PRESETS_KHZ, key=int))}")  # say which exist
    return PRESETS_KHZ[key]  # the dial frequency


def working_offsets_hz(entry):  # the working frequencies that go with a calling frequency
    """Return the offsets, in hertz from `entry`'s dial frequency, of the working frequencies to offer for it.

    For one of Kestrel's meeting frequencies these are the band's
    suggested working frequencies. For any other frequency they are one
    channel (2.5 kHz) above and one below.
    """
    band = entry["band"].split()[0]  # "30 m" -> "30"
    if entry.get("builtin") and band in WORKING_KHZ:  # a meeting frequency with suggested working frequencies
        return [int(round((dial - entry["dial_khz"]) * 1000.0)) for dial in WORKING_KHZ[band]]  # each as an offset in hertz
    return [2500, -2500]  # otherwise the next channel up, then the next channel down


def signal_khz(dial):  # where does the signal sit for a given dial frequency?
    """Return (lowest, highest) frequency in kHz that a Kestrel signal occupies when the radio's dial is at `dial` kHz, upper sideband."""
    return dial + SIGNAL_LOW_HZ / 1000.0, dial + SIGNAL_HIGH_HZ / 1000.0  # dial plus the audio range


def in_automatic_segment(dial):  # may an unattended station use this dial frequency?
    """Return True when the whole signal for dial frequency `dial` (kHz) lies inside one 97.221(b) segment."""
    low, high = signal_khz(dial)  # the signal's edges
    return any(start <= low and high <= end for start, end in AUTOMATIC_SEGMENTS_KHZ)  # wholly inside any one segment


USER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local", "frequencies.json")  # the operator's own list: local/frequencies.json (Git ignores local/)


def builtin_frequencies():  # the presets, as list entries
    """Return the built-in meeting frequencies as a list of entries (see all_frequencies), lowest band number last."""
    return [{"band": f"{band} m", "dial_khz": dial, "mode": "PKTUSB", "note": "Kestrel meeting frequency", "builtin": True}  # one entry per preset
            for band, dial in sorted(PRESETS_KHZ.items(), key=lambda item: -int(item[0]))]  # 40 m first, then 30 m, then 20 m


def user_frequencies(path=None):  # the operator's own entries
    """Return the operator's own frequencies from `path` (default local/frequencies.json); an empty list when there is no file."""
    path = path or USER_FILE  # the default file unless told otherwise
    if not os.path.exists(path):  # nothing saved yet
        return []  # no entries
    with open(path, "r", encoding="utf-8") as handle:  # open the file
        entries = json.load(handle)  # read the list
    return [dict(entry, builtin=False) for entry in entries]  # mark each as the operator's own


def all_frequencies(path=None):  # everything a frequency drop-down list should offer
    """Return the built-in frequencies followed by the operator's own.

    Each entry is a dict: band (free text such as "20 m"), dial_khz,
    mode (the radio mode, as Hamlib names it), note, and builtin.
    """
    return builtin_frequencies() + user_frequencies(path)  # presets first


def add_user_frequency(band, dial_khz, mode="PKTUSB", note="", path=None):  # remember a frequency of the operator's own
    """Add an entry to the operator's list and save it; return the new entry."""
    band, mode, note = str(band).strip(), str(mode).strip().upper(), str(note).strip()  # tidy the text
    dial_khz = float(dial_khz)  # the frequency as a number (raises ValueError if it is not one)
    if not band or not mode or not 100.0 <= dial_khz <= 500000.0:  # a band name, a mode and a sensible frequency are needed
        raise ValueError("give a band name, a dial frequency in kHz (100 to 500000) and a mode")  # refuse anything else
    path = path or USER_FILE  # the default file unless told otherwise
    entries = [{k: e[k] for k in ("band", "dial_khz", "mode", "note")} for e in user_frequencies(path)]  # what is saved already, without the marker
    entry = {"band": band, "dial_khz": dial_khz, "mode": mode, "note": note}  # the new entry
    entries.append(entry)  # add it
    os.makedirs(os.path.dirname(path), exist_ok=True)  # create local/ if needed
    with open(path, "w", encoding="utf-8") as handle:  # open the file for writing
        json.dump(entries, handle, indent=2)  # save the list, readably
    return dict(entry, builtin=False)  # the entry as the lists present it


def remove_user_frequency(index, path=None):  # forget one of the operator's own frequencies
    """Remove entry number `index` (counting from 0) from the operator's list and save it."""
    path = path or USER_FILE  # the default file unless told otherwise
    entries = [{k: e[k] for k in ("band", "dial_khz", "mode", "note")} for e in user_frequencies(path)]  # what is saved
    del entries[index]  # drop the one asked for (raises IndexError if there is no such entry)
    with open(path, "w", encoding="utf-8") as handle:  # open the file for writing
        json.dump(entries, handle, indent=2)  # save what is left


def describe_frequency(entry):  # one line for a drop-down list
    """Return a line of text describing a frequency entry, saying whether an unattended station may use it."""
    low, high = signal_khz(entry["dial_khz"])  # where the signal would sit
    place = "97.221(b) segment" if in_automatic_segment(entry["dial_khz"]) else "attended only"  # may a station be left running here?
    note = f"  {entry['note']}" if entry["note"] else ""  # the note, when there is one
    return f"{entry['band']:<6} {entry['dial_khz']:9.1f} kHz {entry['mode']:<7} signal {low:.1f}-{high:.1f}  [{place}]{note}"  # band, dial, mode, occupancy, status, note
