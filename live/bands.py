"""Preselected Kestrel frequencies, and the operator's own.

One calling frequency per band, so stations know where to find each
other, and up to four numbered channels beside it for contacts to move
to. Each is a DIAL frequency for upper sideband: the Kestrel signal sits
from 500 Hz to 2500 Hz above it. Channels are 2.5 kHz apart: the widest
Kestrel signal is 1.4 kHz, so neighbours have about a kilohertz between
them.

From version 0.29 these sit in an area of Kestrel's own on each band,
away from the calling frequencies of FT8, FT4, JS8, WSPR, Winlink, VARA
and VarAC, as far as each band allows (20 m and 40 m well; 80 m and 30 m
have no empty space, so their areas are the least used that could be
found). They are outside the segments FCC rule 97.221(b) gives to
automatically controlled stations (that is where Winlink and VARA are),
so a station using them must have an operator at the controls.

These are suggestions for the United States, chosen in November 2026. A
frequency the operator adds must keep the whole signal inside a U.S.
amateur data segment. Kestrel uses upper sideband on every band: the
radio's data mode (USB-D) where it has one, plain USB where it has not.
Always listen first: every part of these bands is shared.
"""

import json  # the operator's own frequencies are kept in a small JSON file
from live.paths import data_dir  # where the operator's own files go  # noqa: E402
import os  # file paths

SIGNAL_LOW_HZ = 500.0  # the lowest audio frequency allowed for (the fastest level reaches down to about 800 Hz)
SIGNAL_HIGH_HZ = 2500.0  # the highest audio frequency allowed for (the fastest level reaches up to about 2200 Hz)
CHANNEL_KHZ = 2.5  # channels are this far apart

PRESETS_KHZ = {  # band name (metres) -> calling dial frequency in kHz, upper sideband
    "80": 3582.5,  # signal 3583.0 to 3585.0 kHz: just above the JS8 activity (3578), below the Winlink segment (3585 up)
    "40": 7110.0,  # signal 7110.5 to 7112.5 kHz: above the Winlink and VARA segment (7100-7105) and VarAC (7105)
    "30": 10147.0,  # signal 10147.5 to 10149.5 kHz: the top of the band, above FT8, FT4, WSPR and most RTTY
    "20": 14112.5,  # signal 14113.0 to 14115.0 kHz: above the Winlink and VARA segment (to 14112) and VarAC (14105)
}  # end of the table

WORKING_KHZ = {  # band name (metres) -> the numbered channels: dial frequencies in kHz, upper sideband, Channel 1 first
    "80": (3585.0, 3587.5, 3590.0, 3592.5),  # signals 3585.5 to 3595.0 kHz: shared with Winlink gateways and RTTY, stopping short of VarAC (3595)
    "40": (7112.5, 7115.0, 7117.5, 7120.0),  # signals 7113.0 to 7122.5 kHz, inside the U.S. data segment (to 7125)
    "30": (10144.5,),  # signal 10145.0 to 10147.0 kHz: the band is 50 kHz wide and full, so there is room for one channel only
    "20": (14115.0, 14117.5, 14120.0, 14122.5),  # signals 14115.5 to 14125.0 kHz, below where phone begins outside the U.S. (14125)
}  # end of the table

RADIO_MODES = {"PKTUSB": "USB-D", "USB": "USB"}  # the radio modes Kestrel uses, as Hamlib names them -> as operators know them (upper sideband only: data mode where the radio has one, plain USB where not)

AUTOMATIC_SEGMENTS_KHZ = (  # HF segments of 97.221(b), in kHz
    (3585.0, 3600.0), (7100.0, 7105.0), (10140.0, 10150.0), (14095.0, 14099.5), (14100.5, 14112.0),  # 80, 40, 30 and 20 metres
    (18105.0, 18110.0), (21090.0, 21100.0), (24925.0, 24930.0), (28120.0, 28189.0),  # 17, 15, 12 and 10 metres
)  # end of the table


DATA_SEGMENTS_KHZ = (  # where U.S. amateurs may send data (RTTY and data) on HF, widest (Amateur Extra) limits, in kHz
    ("160", 1800.0, 2000.0), ("80", 3500.0, 3600.0), ("40", 7000.0, 7125.0), ("30", 10100.0, 10150.0), ("20", 14000.0, 14150.0),  # 160 to 20 metres
    ("17", 18068.0, 18110.0), ("15", 21000.0, 21200.0), ("12", 24890.0, 24930.0), ("10", 28000.0, 28300.0),  # 17 to 10 metres
)  # end of the table (General class starts 25 kHz higher on 80, 40, 20 and 15 metres)


BAND_EDGES_KHZ = (  # the amateur bands, as operators name them, with their edges in kHz (U.S. allocations; 60 m is its five channels' span)
    ("160m", 1800.0, 2000.0), ("80m", 3500.0, 4000.0), ("60m", 5330.0, 5410.0), ("40m", 7000.0, 7300.0), ("30m", 10100.0, 10150.0),  # 160 to 30 metres
    ("20m", 14000.0, 14350.0), ("17m", 18068.0, 18168.0), ("15m", 21000.0, 21450.0), ("12m", 24890.0, 24990.0), ("10m", 28000.0, 29700.0),  # 20 to 10 metres
    ("6m", 50000.0, 54000.0), ("2m", 144000.0, 148000.0), ("70cm", 420000.0, 450000.0),  # VHF and UHF
)  # end of the table


def band_of(dial_khz):  # which band a dial frequency is in
    """Return the band name ("20m", "40m" ...) for a dial frequency in kHz, or "" when it is unknown or outside the amateur bands."""
    try:  # the frequency may be missing
        khz = float(dial_khz)  # as a number
    except (TypeError, ValueError):  # not a number
        return ""  # unknown
    for name, low, high in BAND_EDGES_KHZ:  # each band
        if low <= khz <= high:  # inside it
            return name  # its name
    return ""  # outside every band (or no frequency known)


def in_data_segment(dial):  # may Kestrel transmit here at all?
    """Return the band name (such as "80") when the whole signal for dial frequency `dial` (kHz) lies inside a U.S. amateur data segment, else None."""
    low, high = signal_khz(dial)  # the signal's edges
    for band, start, end in DATA_SEGMENTS_KHZ:  # every segment
        if start <= low and high <= end:  # wholly inside this one
            return band  # its band
    return None  # outside every segment: not an amateur data frequency


def dial_khz(band):  # look up a band's preset
    """Return the preset dial frequency in kHz for `band` ("40", "30" or "20"; "40m" and the like are accepted)."""
    key = str(band).lower().rstrip("m")  # allow "20m" as well as "20"
    if key not in PRESETS_KHZ:  # no preset for that band
        raise ValueError(f"no preset for band '{band}'; choose from {', '.join(sorted(PRESETS_KHZ, key=int))}")  # say which exist
    return PRESETS_KHZ[key]  # the dial frequency


def working_offsets_hz(entry):  # the working frequencies that go with a calling frequency
    """Return the offsets, in hertz from `entry`'s dial frequency, of the working frequencies to offer for it.

    For one of Kestrel's calling frequencies these are the band's numbered
    channels, Channel 1 first. For any other frequency they are one
    channel (2.5 kHz) above and one below.
    """
    band = entry["band"].split()[0]  # "30 m" -> "30"
    if entry.get("builtin") and band in WORKING_KHZ:  # a calling frequency with numbered channels
        return [int(round((dial - entry["dial_khz"]) * 1000.0)) for dial in WORKING_KHZ[band]]  # each as an offset in hertz
    return [2500, -2500]  # otherwise the next channel up, then the next channel down


def signal_khz(dial):  # where does the signal sit for a given dial frequency?
    """Return (lowest, highest) frequency in kHz that a Kestrel signal occupies when the radio's dial is at `dial` kHz, upper sideband."""
    return dial + SIGNAL_LOW_HZ / 1000.0, dial + SIGNAL_HIGH_HZ / 1000.0  # dial plus the audio range


def in_automatic_segment(dial):  # may an unattended station use this dial frequency?
    """Return True when the whole signal for dial frequency `dial` (kHz) lies inside one 97.221(b) segment."""
    low, high = signal_khz(dial)  # the signal's edges
    return any(start <= low and high <= end for start, end in AUTOMATIC_SEGMENTS_KHZ)  # wholly inside any one segment


USER_FILE = os.path.join(data_dir(), "frequencies.json")  # the operator's own list: local/frequencies.json from the source folder (Git ignores local/), or in the user's profile when installed


def builtin_frequencies():  # the presets, as list entries
    """Return the built-in calling frequencies as a list of entries (see all_frequencies), lowest band number last."""
    return [{"band": f"{band} m", "dial_khz": dial, "mode": "PKTUSB", "note": "Kestrel calling frequency", "builtin": True}  # one entry per preset
            for band, dial in sorted(PRESETS_KHZ.items(), key=lambda item: -int(item[0]))]  # 80 m first, then 40 m, 30 m and 20 m


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
    mode = {"USB-D": "PKTUSB", "USBD": "PKTUSB", "DATA-U": "PKTUSB", "": "PKTUSB"}.get(mode, mode)  # the names operators use for upper sideband data all mean PKTUSB
    if mode not in RADIO_MODES:  # anything but upper sideband
        raise ValueError("Kestrel uses upper sideband on every band: give the mode as USB-D (the radio's data mode) or USB")  # refuse lower sideband and the rest
    dial_khz = float(dial_khz)  # the frequency as a number (raises ValueError if it is not one)
    if not band or not mode or not 100.0 <= dial_khz <= 500000.0:  # a band name, a mode and a sensible frequency are needed
        raise ValueError("give a band name, a dial frequency in kHz (100 to 500000) and a mode")  # refuse anything else
    if dial_khz < 30000.0 and in_data_segment(dial_khz) is None:  # an HF frequency whose signal would fall outside every amateur data segment
        low, high = signal_khz(dial_khz)  # where the signal would sit
        raise ValueError(f"a dial of {dial_khz:.1f} kHz puts the signal at {low:.1f}-{high:.1f} kHz, outside the U.S. amateur data segments (for 80 m, for example, use 3500-3600 kHz)")  # refuse, and say why
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
    if entry["dial_khz"] < 30000.0 and in_data_segment(entry["dial_khz"]) is None:  # an HF frequency outside every data segment
        place = "OUTSIDE THE DATA SEGMENTS: will not transmit"  # say so plainly
    else:  # an amateur data frequency
        place = "97.221(b) segment" if in_automatic_segment(entry["dial_khz"]) else "attended only"  # may a station be left running here?
    note = f"  {entry['note']}" if entry["note"] else ""  # the note, when there is one
    return f"{entry['band']:<6} {entry['dial_khz']:9.1f} kHz {mode_name(entry['mode']):<6} signal {low:.1f}-{high:.1f}  [{place}]{note}"  # band, dial, mode, occupancy, status, note


def mode_name(mode):  # a radio mode as operators know it
    """Return "USB-D" or "USB" for a frequency entry's mode (anything that is not plain USB counts as USB-D)."""
    return RADIO_MODES.get(str(mode).upper(), "USB-D")  # upper sideband either way


def channel_names(entry):  # the choices for moving a contact off the calling frequency
    """Return [(name, offset in hertz)] for `entry`: "Channel 1" to "Channel 4" for a Kestrel calling frequency, "up 2.5 kHz" and "down 2.5 kHz" otherwise."""
    offsets = working_offsets_hz(entry)  # where a contact may move to
    if entry.get("builtin"):  # one of Kestrel's calling frequencies
        return [(f"Channel {number}", offset) for number, offset in enumerate(offsets, 1)]  # numbered from 1
    return [("up 2.5 kHz" if offset > 0 else "down 2.5 kHz", offset) for offset in offsets]  # the next channel each way
