"""The control panel for a live Kestrel station.

Run from the repository root:

    python tools/kestrel_panel.py
    python tools/kestrel_panel.py --profile second    (a second panel with its own remembered settings, for a second radio)

The panel starts listening as soon as it opens (Settings > Operating
chooses Listen, Monitor or nothing). Enter your callsign, grid locator,
radio, sound devices and the rest once under the Settings menu; the
first time, the panel opens Settings for you.

Everything the panel does can be reached from its menus, with the
keyboard alone: Alt and the underlined letter opens a menu, and the
function keys and Ctrl shortcuts are listed under Help > Keyboard
shortcuts.

Your settings, saved contacts, the stations-heard log and the logbook
are kept in the local/ folder, which Git ignores.

Only transmit where your license allows, with the published specification matching this program.
"""

import argparse  # reads the command-line options
import json  # settings are kept in a small JSON file
import os  # file paths
import queue  # carries log lines and reports from the working thread to the window
import re  # checks that a callsign has the shape of one
import subprocess  # asks Git which commit this is, for the About box
import sys  # lets us add the repository root to the import path
import threading  # the station runs in its own thread so the window stays responsive
import time  # clocks
import tkinter as tk  # the window toolkit that comes with Python

import numpy as np  # arrays, for the scope's picture
from tkinter import filedialog, messagebox, ttk  # file chooser, message boxes and the themed widgets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live", "link" and "modem" importable when run as a script
from live.paths import code_dir, data_dir  # where the program's files and the operator's files are  # noqa: E402
ROOT = code_dir()  # the program's own files: the repository root, or the installed bundle

from link import Station  # the link rules  # noqa: E402
from link.mail import Mailroom  # the mail kept between contacts and runs (store and forward)  # noqa: E402
from link.params import HOP_LIMIT, MAIL_LIFE_HOURS  # how far and how long mail travels  # noqa: E402
from modem import call_hash  # the short code a mail notice uses for a callsign  # noqa: E402
from modem import native  # the compiled modem library, to say in About and --check whether it is in use  # noqa: E402
from live import KIND, Listener, call_request, describe, near_line, plain_line, run_station, status_for  # the continuous receiver, a directed call to make when free, a one-line frame description, a near-miss line, the plain form of a log line, the live loop, the state shown by a log line  # noqa: E402
from live.contacts import HISTORY_DEFAULT, HISTORY_MAX, HISTORY_MIN, MODE_NAMES, ContactBook, describe_field, distance_bearing  # the contact book: records, history rules, grid distances (since 0.31R3)  # noqa: E402
from live import spaceweather  # today's measured sunspot number and space-weather warnings (since 0.34R1)  # noqa: E402
from live import propcheck, pskspot, skywatch  # the prediction check, PSK Reporter spotting, and the bands now from ionosondes and spots (since 0.35)  # noqa: E402
from live import signalwatch  # recognizing the signals in the passband: type, frequency, how long (since 0.37)  # noqa: E402
from theme_editor import open_theme_editor  # View > Edit themes: the operator's own themes (since 0.37)  # noqa: E402
import frame_strip  # drawing the frame strip under the receive scope (since 0.37)  # noqa: E402
from live.framestrip import FrameStrip  # what the frame strip shows (since 0.37)  # noqa: E402
from live import propagation, sunspots  # HF propagation predictions (ITU-R P.533) and the predicted sunspot numbers they need (since 0.32)  # noqa: E402
from live import antennas  # the antenna types offered in Settings > Station (since 0.39R2)  # noqa: E402
from live import power_hold  # holding the output power by the drive, and spotting a sag (since 0.40R1)  # noqa: E402
from modem.control import beacon_rig, beacon_watts  # the rig type and watts as a beacon carries them (since 0.40)  # noqa: E402
from live import chain  # chained messages: up to 1,000 characters in numbered pieces (since 0.42)  # noqa: E402
from live import updates  # checking GitHub for a newer release, and installing it when asked (since 0.42)  # noqa: E402
from live import heardlog, logbook, mixer, telemetry, theme  # the 48-hour heard log, the CSV and ADIF logbook, Windows' device levels, telemetry messages, light and dark looks  # noqa: E402
from live.audio import AudioIn, AudioOut, device_named, list_devices  # sound-card input and output  # noqa: E402
from live.bands import add_user_frequency, all_frequencies, band_of, channel_names, describe_frequency, mode_name, in_data_segment, remove_user_frequency, user_frequencies, working_offsets_hz  # the frequency list, the data-segment check and the working frequencies  # noqa: E402
from live.recorder import Recorder, RecordingSource, TimedSource, recordings_dir  # recording the received audio to WAV files, and numbering every sample received  # noqa: E402
from live.runner import NearFilter, attach_signal_log, feed_from, log_tick  # which near misses to show, the listener fed with numbered audio, and the signal log connected to it  # noqa: E402
from live.signallog import CLIPS_MAX_MB, KEEP_DAYS, Guarded, SignalLog  # the detailed signal log for analysis and debugging  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.rig import RigCtl, RigServer, find_rigctld, list_models, models_for  # rig control through Hamlib's rigctld, and starting rigctld for a chosen radio  # noqa: E402
from modem.levels import LEVELS, level_name  # the speed levels, for how wide each signal is on the scope, and their names (L0 to L4, LB)  # noqa: E402
from modem.longbeacon import LONG  # the long beacon's tone length and spacing  # noqa: E402
from modem.longnote import CHARS as LONG_NOTE_FRAME_CHARS, MOST_CHARS as LONG_NOTE_CHARS, note_fields  # long notes: characters per frame, the most in a note, and the check that a note can be sent (since 0.34)  # noqa: E402
from live.idle import IDLE_S, KEEP_GOING_TEXT, IdleWatch  # the contact's idle timeout, the warning's Keep going message, and the watcher (since 0.41)  # noqa: E402
from live.notes import MOST_TRIES as LONG_NOTE_TRIES, LongNotes  # how many tries a long note gets, and sending long notes, receipts and resends, and putting received ones together (since 0.34)  # noqa: E402
from modem.params import FRAME_TYPE_ACK, FRAME_TYPE_ANSWER  # the frames that carry the partner's report of this station (since 0.42)  # noqa: E402
from modem.params import FRAME_TYPE_BEACON, LONG_LEVEL, M_TONES, SIGNAL_VERSION, SPEC_VERSION  # (the beacon's frame type, since 0.40) tones per frame, the signal's version and the document's version  # noqa: E402

PROFILE = ""  # the name given with --profile, if any (set in main)
SETTINGS_FILE = os.path.join(data_dir(), "panel.json")  # where the panel remembers its settings (local/ from the source folder; the user's profile when installed)
LOG_FOLDER = os.path.join(data_dir(), "logs")  # where the CSV and ADIF logbook files go
BEACON_MIN, BEACON_MAX = 5, 60  # the repeating beacon may be set to no less than 5 and no more than 60 minutes
AUTOSTOP_MIN, AUTOSTOP_MAX = 15, 720  # the beacon's automatic stop, when used, is between 15 minutes and 12 hours (0 turns it off)
DEFAULTS = {"call": "", "grid": "", "name": "", "rig_text": "", "max_power_w": "100",  # (continued: the station)
            "frequency": 0, "audio_in": "", "audio_out": "", "gain": "0.25", "rig": "", "ptt": "none", "port": "",  # (continued: frequency, audio, keying)
            "rig_model": "", "cat_port": "", "cat_baud": "38400", "cat_handshake": "none", "radio_mode": "auto", "rigctld": "", "keep_open": False, "working": 0,  # (continued: rig control, contacts)
            "start_mode": "listen", "beacon_every_min": 5, "beacon_type": "short", "listen_first": True, "beacon_autostop_min": 120, "auto_answer": False, "available": True, "carry_mail": True,  # (continued: operating)
            "log_level": "basic", "record_rx": False, "signal_log": "off", "psk_spot": False, "prop_check": True, "signal_types": list(signalwatch.TYPES), "signal_labels": True, "signal_scope": True, "frame_strip": True, "scope_theme": "theme", "theme": "system", "font_family": "Segoe UI", "font_size": "9", "layout": {},
            "scope_rx_floor": -5.0, "scope_rx_range": 55.0, "scope_tx_floor": -70.0, "scope_tx_range": 70.0,  # (continued: where each scope's picture starts, and how many dB it covers)
            "scope_rx_color": 50.0, "scope_tx_color": 50.0, "scope_palette": "Classic",  # (continued: where each waterfall's colors change, and the set of colors used)  # (continued: logging, recording and looks)
            "scope_time_marks": True, "scope_time_zone": "utc",  # (continued: time marks and the seconds scale on both waterfalls, View > Time marks on the scopes, in UTC or local time, since 0.33)
            "quick": [{"name": "Call, name and grid", "text": "{call} {name} {grid}"}, {"name": "Rig and power", "text": "{call} {name} {grid} RIG {rig} {power}W"},  # (continued: the quick messages,)
                      {"name": "Telemetry", "text": "{call} {telemetry}"}]}  # (continued: each with the name the operator gave it; up to QUICK_MOST)
DEFAULTS.update({"hold_power_w": ""})  # the output power to hold, in watts, by adjusting the drive between transmissions; blank = off (since 0.40R1)
DEFAULTS.update({"update_check": "daily", "update_notify": "all", "update_test": True, "update_install": "ask", "update_last": 0.0, "update_skip": ""})  # Settings > Updates: when to check, what to report, test releases, what to do; when the last check was and the version skipped (since 0.42)
DEFAULTS.update({"keep_alive": False, "activity_window": False})  # Keep-Alive (working channels: 3 more idle minutes) and whether the Activity window opens at start (since 0.41)
DEFAULTS.update({"location": "", "antenna": ""})  # this station's location and antenna (one of the fixed list in live/antennas.py) (since 0.39R2)
DEFAULTS.update({"contact_history": HISTORY_DEFAULT, "contact_history_mode": "all"})  # how many history entries each contact keeps (30 to 200), and whether all traffic or only completed contacts go in (since 0.31R3)
QUICK_MOST = 10  # the most quick messages an operator may keep
QUICK_NAME_MOST = 40  # the longest name a quick message may have
QUICK_OLD_NAMES = ("Call, name and grid", "Rig and power", "Telemetry")  # names given to the three quick messages kept by versions before 0.30, which had no names
PTT_NAMES = {"none": "None (receive only, or VOX)", "rig": "CAT (through rig control)", "rts": "RTS line of a serial port", "dtr": "DTR line of a serial port"}  # keying methods, as the operator sees them
EXPECT_MOST = 8  # at most this many expected callsigns are tried when a weak control frame fails alone (each try is a small chance of a false read; the frame's own soft bits must also agree)
START_NAMES = {"listen": "Listen", "monitor": "Monitor (receive only)", "off": "Nothing (start switched off)"}  # what the panel does when it opens
ANSWER_NAMES = {False: "Just listen: show me beacons and calls; I choose whether to respond", True: "Answer every beacon and call automatically"}  # whether Listen transmits by itself
CALLING_KEEP_S = 300.0  # a station that beaconed stays highlighted in the Stations heard list this long
LOG_NAMES = {"basic": "Basic: messages and contacts", "advanced": "Advanced: adds signal readings, power, stations heard, beacons", "verbose": "Verbose: everything, every frame and meter"}  # logging levels, as the operator sees them
SIGNAL_NAMES = {"off": "Off", "on": "On: text only (a few MB a day)",  # the signal log, as the operator sees it (continued)
                "clips": f"On, with each frame's audio (clips kept {KEEP_DAYS} days, at most {CLIPS_MAX_MB} MB)"}  # (continued)
RADIO_MODE_NAMES = {"auto": "Automatic: USB-D if the radio has it, otherwise USB", "PKTUSB": "USB-D (upper sideband, data)", "USB": "USB (plain upper sideband)"}  # the radio's mode, as the operator sees it (Kestrel never uses lower sideband)
LISTEN_FIRST_NAMES = {True: "On: hold beacons, calls and broadcasts while the frequency is in use", False: "Off: transmit regardless (you check the frequency yourself)"}  # listen before transmitting, as the operator sees it
BEACON_TYPE_NAMES = {"short": "Short: a call-up others can answer (7 to 31 s)",  # the three kinds of repeating beacon (continued)
                     "stepped": "Short, with power steps: 5 s of tones at 0, -10, -20, -30 dB first, then the call-up",  # (continued: since 0.38)
                     "long": "Long: about 60 s, heard much further; nobody answers (every 10 min at most)"}  # (continued)
LONG_EVERY_MIN = 10  # long beacons repeat no more often than this, in minutes (each holds the frequency for a minute)
ALC_HIGH = 0.5  # an ALC reading at or above this share of the radio's scale means the transmit audio is too strong (data modes want ALC near zero)
CARRY_NAMES = {True: "Yes: hold mail for other stations and deliver it when they ask", False: "No: decline mail for other stations"}  # store and forward (since 0.30), as the operator sees it
PSK_NAMES = {False: "Off", True: "On: report the Kestrel stations I decode to PSK Reporter (every five minutes or so)"}  # spotting, as the operator sees it (since 0.35)
PROPCHECK_NAMES = {False: "Off", True: "On: compare each station heard with the prediction for its path (prop_check.csv)"}  # the prediction check (since 0.35)
RECORD_NAMES = {False: "Off", True: "On: save everything received to WAV files (about 86 MB an hour, kept 7 days)"}  # recording the received audio, as the operator sees it
CALL_PATTERN = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](/[A-Z0-9]{1,4})?$")  # the general shape of an amateur callsign, with an optional prefix or suffix such as /P or /1
THEME_NAMES = theme.NAMES  # the themes, as the operator sees them (15 and System since 0.37)
NO_RIG = "(no rig control)"  # the radio-type choice that means the radio is tuned by hand
LOCKED = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states of a contact in progress
SHORTCUTS = (  # the keyboard shortcuts, for Help > Keyboard shortcuts
    ("F1", "this list"), ("F2", "Listen (nothing is sent unless you start it)"), ("F3", "Monitor (receive only)"), ("F4", "Off (stop receiving and transmitting)"),  # (continued)
    ("Ctrl+U", "Available / Unavailable for contacts"), ("F5", "Beacon (call anyone) on or off"), ("F6", "Call the station in the To box"), ("F7", "End the contact (or, with no contact, stop calling)"), ("F8", "Stations heard in the last 48 hours"),  # (continued)
    ("F9", "Telemetry received"), ("F10", "Mail held and carried"), ("F11", "Broadcast the message to ALL"), ("F12", "Settings"),  # (continued)
    ("Ctrl+Y", "Respond: call the station selected in the Stations heard list"),  # (continued)
    ("Ctrl+L", "go to the To box (callsign)"), ("Ctrl+M", "go to the Message box"), ("Enter", "in the Message box: queue the message; in a list: put the callsign in To"),  # (continued)
    ("Alt+1 ... Alt+9, Alt+0", "put quick message 1 to 10 in the Message box"), ("Ctrl+1, 2, 3", "put quick message 1, 2 or 3 in the Message box (as before)"), ("Ctrl+4", "send telemetry to the station in To"), ("Ctrl+5", "broadcast telemetry to ALL"),  # (continued)
    ("Ctrl+R", "go to the frequency list"), ("Ctrl+Up / Ctrl+Down", "previous / next frequency"), ("Ctrl+G", "go to the stations list"),  # (continued)
    ("Ctrl+K", "Contacts: view, search, change and delete contact records"),  # (continued: since 0.39)
    ("Ctrl+P", "propagation: best band by hour to the station in To (ITU-R P.533)"),  # (continued: since 0.32)
    ("Ctrl+N", f"send the message as a long note (up to {LONG_NOTE_CHARS} characters in minute-long frames, for weak paths; a receipt comes back)"),  # (continued: since 0.34; 64 characters since 0.39)
    ("Ctrl+D", "signals detected: every signal in the passband, its type, frequency and how long it was heard"),  # (continued: since 0.37)
    ("Ctrl+T", "time marks on the scopes on or off (UTC marks across both waterfalls, and the seconds scale)"),  # (continued: since 0.33)
    ("Ctrl+J", "go to the level sliders"), ("Tab / Shift+Tab", "move between controls"), ("Alt + underlined letter", "open a menu"),  # (continued)
    ("Esc", "in the main window: stop calling (a call started with Respond or Call station, a beacon round, a long beacon, broadcasts waiting) and cut such a transmission short; in other windows: close the window"))  # the rest


def load_settings():  # read the remembered settings
    """Return the saved settings, with defaults for anything missing."""
    settings = dict(DEFAULTS)  # start from the defaults
    saved = read_json(SETTINGS_FILE, {})  # what was saved
    settings.update(saved)  # saved values replace the defaults
    for side in ("rx", "tx"):  # the two scopes' color sliders, saved under British-spelled names before 0.32
        old = f"scope_{side}_colo" + "ur"  # the old name (spelled out in two parts so a spelling sweep leaves it alone)
        if old in saved and f"scope_{side}_color" not in saved:  # kept under the old name only
            settings[f"scope_{side}_color"] = saved[old]  # carried over
        settings.pop(old, None)  # the old name is no longer used
    if "quick" not in saved and any(f"quick{number}" in saved for number in (1, 2, 3)):  # quick messages kept by a version before 0.30 (three numbered slots, no names)
        settings["quick"] = [{"name": QUICK_OLD_NAMES[number - 1], "text": saved[f"quick{number}"]} for number in (1, 2, 3) if saved.get(f"quick{number}", "").strip()]  # kept, with names
    for number in (1, 2, 3):  # the old slots
        settings.pop(f"quick{number}", None)  # are no longer used
    settings["quick"] = [{"name": str(item.get("name", "")), "text": str(item.get("text", ""))} for item in settings["quick"] if isinstance(item, dict)][:QUICK_MOST]  # a fresh copy, so the defaults are never changed by editing
    settings["antenna"] = antennas.known(settings.get("antenna"))  # one of the fixed antenna types, or none (since 0.39R2)
    return settings  # the settings to use


def unsent_messages(job, say=None):  # what a run that has ended still owes the queue (since 0.40R2)
    """Return [(text, callsign or "")] for the messages a run took and did not send: those never handed to a station (job["messages"]) and those a station still holds (job["holder"]); both are cleared, so a second call returns nothing."""
    back = []  # the messages to give back
    holder = job.get("holder")  # the station that was handed the messages, if the run got that far and did not take them back itself
    if holder is not None:  # it still holds some
        try:  # the station may be in a bad way after a problem
            back += [(left, to or "") for left, to in zip(list(holder.outbox), list(holder.outbox_to))]  # what it had not sent, each with its address
        except Exception as problem:  # noqa: BLE001 - it could not say
            if say is not None:  # there is somewhere to report it
                say(f"the messages the station still held could not be recovered: {problem!r}")  # never lose messages silently (since 0.40R3)
    back += list(job.get("messages") or [])  # and any never handed to a station at all (the run failed before it had one)
    job["holder"], job["messages"] = None, []  # given back once
    return back  # for the panel's queue


MACHINE_KEYS = ("audio_in", "audio_out", "rig", "port", "cat_port", "rigctld", "layout")  # settings that belong to one computer: its sound cards, ports, the rig program's place and the window layout (since 0.37)
SETTINGS_KIND = "kestrel-settings"  # what an exported settings file says it is (since 0.37)


def export_settings_file(settings, path, machine=False):  # File > Export settings (since 0.37)
    """Write `settings` to `path` as a file another Kestrel can import; this computer's sound cards, ports and layout only when `machine` is true. Themes are not included: they have their own export."""
    kept = {key: value for key, value in settings.items() if key in DEFAULTS and (machine or key not in MACHINE_KEYS)}  # the settings to give
    write_json(path, {"kind": SETTINGS_KIND, "version": SPEC_VERSION, "this_computer": bool(machine), "settings": kept})  # written, readably


def read_settings_file(path):  # the settings in an exported file (since 0.37)
    """Return the known settings held in an exported settings file; raise ValueError if it is not one."""
    data = read_json(path, None)  # the file
    if not isinstance(data, dict) or data.get("kind") != SETTINGS_KIND or not isinstance(data.get("settings"), dict):  # not a Kestrel settings file
        raise ValueError("That file holds no Kestrel settings.")  # said
    return {key: value for key, value in data["settings"].items() if key in DEFAULTS}  # only settings this version knows


def merged_settings(current, incoming, machine=False):  # the settings after an import (since 0.37)
    """Return `current` with each setting from `incoming` laid over it, where it has the right form; this computer's sound cards, ports and layout are kept unless `machine` is true."""
    merged = dict(current)  # a copy, so the running settings are untouched until the operator agrees
    for key, value in incoming.items():  # each imported setting
        if key not in DEFAULTS or (key in MACHINE_KEYS and not machine):  # unknown, or this computer's own and not wanted
            continue  # kept as it is
        want = DEFAULTS[key]  # what form it should have
        same = isinstance(value, bool) if isinstance(want, bool) else isinstance(value, (int, float)) and not isinstance(value, bool) if isinstance(want, (int, float)) else isinstance(value, type(want))  # the right form (a whole number will do for a decimal one)
        if same:  # it has
            merged[key] = value  # taken
    return merged  # the new settings


def side_file(suffix):  # a file kept beside this panel's settings file
    """Return the path of a companion file such as the waiting messages ("_outbox.json") for this panel's profile."""
    return os.path.splitext(SETTINGS_FILE)[0] + suffix  # the settings file's name with a different ending


def read_json(path, default):  # read a small JSON file
    """Return the contents of the JSON file at `path`, or `default` if it is missing or damaged."""
    try:  # the file may not exist yet
        with open(path, "r", encoding="utf-8") as handle:  # open it
            return json.load(handle)  # its contents
    except (OSError, ValueError):  # missing, unreadable or not JSON
        return default  # start afresh


def write_json(path, data):  # write a small JSON file
    """Save `data` as JSON at `path`, creating the folder if needed; a failure to save is not fatal."""
    try:  # the disk may refuse
        os.makedirs(os.path.dirname(path), exist_ok=True)  # make sure the folder is there
        with open(path, "w", encoding="utf-8") as handle:  # open the file
            json.dump(data, handle, indent=2)  # save, readably
    except OSError:  # it could not be written
        pass  # carry on; the window still holds the information


CONTACTS_FILE = os.path.join(data_dir(), "contacts.json")  # the operator's saved contacts, shared by every panel on this computer


def build_info():  # which build of the program this is
    """Return the commit number and date of this copy of the program, or "not recorded" when neither Git nor an archive stamp is available."""
    try:  # a copy made by "git archive" has the commit written into the VERSION file
        with open(os.path.join(ROOT, "VERSION"), "r", encoding="utf-8") as handle:  # open it
            stamp = handle.read().strip()  # its one line
        if stamp and "$Format" not in stamp:  # Git filled it in
            return stamp  # use it
    except OSError:  # no VERSION file
        pass  # try Git instead
    try:  # a working copy: ask Git itself
        asked = subprocess.run(["git", "log", "-1", "--format=commit %h of %cs"], cwd=ROOT, capture_output=True, text=True, timeout=5, **({"creationflags": 0x08000000} if sys.platform == "win32" else {}))  # the newest commit, without a console window
        if asked.returncode == 0 and asked.stdout.strip():  # Git answered
            return asked.stdout.strip()  # use its answer
    except (OSError, subprocess.SubprocessError):  # Git is not installed, or did not answer
        pass  # nothing more to try
    return "not recorded"  # neither source was available


def about_text():  # the words in Help > About
    """Return the text of the About box: what Kestrel is, the signal and document versions, the program build, and who began it."""
    return (f"Kestrel (KES)\nAn adaptive amateur HF digital mode for short messages.\n\n"  # the name and what it is
            f"Kestrel version: {SPEC_VERSION} (the specification it follows, draft)\n"  # the program's version, which is that of the published description
            f"Signal version: {SIGNAL_VERSION} (what goes on the air; a release that changes only the program leaves it alone)\n"  # the version of the transmitted signal
            f"Program: {build_info()}\n"  # which build of the program
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; {native.describe()}\n\n"  # the Python it runs on, and whether the compiled modem library is helping
            f"Stations must have the same signal version to hear each other.\n\n"  # the practical point
            f"Originated by P. H. Ewen (KO4WSC).\nThank you to KO4WZZ for doing countless rounds of testing.\nProgram under Apache License 2.0; specification under CC BY 4.0.")  # credit, thanks (since 0.35) and licenses


def device_choices(kind):  # the sound devices to offer in a drop-down list
    """Return the names of every input (or output) device, each name once.

    Names are offered, not numbers: Windows renumbers its sound devices
    whenever one is plugged in or removed.
    """
    column = 2 if kind == "input" else 3  # which channel count to check
    seen, choices = set(), []  # names already listed, and the list itself
    try:  # the sound library may be missing
        found = list_devices()  # every device
    except Exception:  # no sound library, or no sound system
        found = []  # offer nothing; a name can still be typed
    for index, name, inputs, outputs in found:  # every device
        if (inputs, outputs)[column - 2] > 0 and name not in seen:  # it can do the job and is not a repeat
            seen.add(name)  # remember the name
            choices.append(name)  # offer it by name
    return choices  # the list


def signal_width_hz(level):  # how wide a Kestrel signal is at a given level
    """Return the width in hertz of the 32 tones at speed level `level` (L0 is the narrowest)."""
    spec = LONG if level == LONG_LEVEL else LEVELS[max(0, min(level, len(LEVELS) - 1))]  # the level's description (or the long beacon's)
    return M_TONES * spec.step * spec.bin_hz  # tones times their spacing


def utc(seconds):  # a time for display
    """Return `seconds` (since 1970) as a UTC date and time, the way an amateur log shows it."""
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(seconds))  # date and time, UTC


HEARD_TIME = "%m-%d %H:%M"  # how Stations heard and Messages received show when: month-day and local time (since 0.40; the time alone before)


def heard_when(record):  # when a saved contact was last heard, for its row in Stations heard (since 0.40)
    """Return the local date and time `record` (a contact record) was last heard, as HEARD_TIME, or "" if never."""
    t = (record.get("last_heard") or {}).get("t")  # when, in seconds since 1970
    return time.strftime(HEARD_TIME, time.localtime(t)) if t else ""  # local date and time, or nothing


def utc_of_shown(text, now=None):  # the UTC time beside a local one shown in a list (since 0.41)
    """Return the UTC "HH:MM" (or "HH:MM:SS") for a local time shown as HEARD_TIME ("MM-DD HH:MM") or "HH:MM:SS" (today), or "" if `text` is neither."""
    now = time.time() if now is None else now  # the moment, for the year and today's date
    today = time.localtime(now)  # the local date now
    for form, shown in (("%Y-%m-%d %H:%M", "%H:%M"), ("%Y-%m-%d %H:%M:%S", "%H:%M:%S")):  # month-day and minute, or a time of day today
        try:  # does the text have this form?
            stamp = f"{today.tm_year}-{text}" if form == "%Y-%m-%d %H:%M" else time.strftime("%Y-%m-%d ", today) + text  # with the year, or with today's date
            when = time.mktime(time.strptime(stamp, form))  # seconds since 1970, from local time
            if when > now + 86400 * 180:  # a date late in the year read in the early months of the next (shown in December, read in January)
                when = time.mktime(time.strptime(f"{today.tm_year - 1}-{text}", form))  # last year's
            return time.strftime(shown, time.gmtime(when))  # the same moment in UTC
        except (ValueError, OverflowError):  # not this form
            continue  # try the next
    return ""  # not a time


def short_frequency(entry):  # one short line for the frequency list (since 0.41; the full line, describe_frequency, is its hover help)
    """Return "80 m \u00b7 3582.5 kHz \u00b7 Calling" for a frequency entry, with a plain warning when it lies outside the data segments."""
    from live.bands import in_data_segment  # where data modes may transmit
    note = str(entry.get("note") or "")  # what the entry says it is
    kind = "Calling" if "calling" in note.lower() else (note or "your own")  # the Kestrel calling frequencies say so; others show their note
    outside = "  (outside the data segments: will not transmit)" if entry["dial_khz"] < 30000.0 and in_data_segment(entry["dial_khz"]) is None else ""  # said plainly
    return f"{entry['band']} \u00b7 {entry['dial_khz']:.1f} kHz \u00b7 {kind}{outside}"  # band, dial, what it is


class Tooltip:  # a word of help when the pointer rests on a control (since 0.41)
    """Show `text` in a small box near `widget` while the pointer rests on it; shortcut keys are named here rather than on the buttons."""

    def __init__(self, widget, text):  # attach to a widget
        self.widget, self.text, self.tip, self.job = widget, text, None, None  # the control, its words, the box when shown, and the pending timer
        widget.bind("<Enter>", self.soon, add="+")  # the pointer arrives
        widget.bind("<Leave>", self.hide, add="+")  # and leaves
        widget.bind("<ButtonPress>", self.hide, add="+")  # a click hides it

    def soon(self, event=None):  # show it after a short rest
        self.hide()  # none left over
        self.job = self.widget.after(600, self.show)  # after six-tenths of a second

    def show(self):  # put the box up
        self.job = None  # the timer has fired
        if not self.text:  # nothing to say (yet)
            return  # no box
        x, y = self.widget.winfo_rootx() + 12, self.widget.winfo_rooty() + self.widget.winfo_height() + 4  # under the control
        self.tip = tk.Toplevel(self.widget)  # a small window
        self.tip.wm_overrideredirect(True)  # with no frame or title
        self.tip.wm_geometry(f"+{x}+{y}")  # placed
        tk.Label(self.tip, text=self.text, justify="left", wraplength=360, background="#ffffe0", foreground="#000000", relief="solid", borderwidth=1, padx=6, pady=3).pack()  # the words, on pale yellow

    def hide(self, event=None):  # take it away
        if self.job is not None:  # waiting to show
            self.widget.after_cancel(self.job)  # not now
            self.job = None  # nothing pending
        if self.tip is not None:  # showing
            self.tip.destroy()  # gone
            self.tip = None  # nothing shown


MESSAGE_MOST = 1000  # the most characters the message box takes (the chained-message limit planned for a later signal version; since 0.41)
SEND_AS = ("Normal", "Long note (reach)")  # how the typed message goes, chosen beside the To box (since 0.41)
FRAME_CHARS = 200  # characters in one transmission at most (a longer message goes as several)
KEEPALIVE_NAMES = {False: "Off: a contact ends after 3 minutes with no messages", True: "On: 3 more idle minutes on a working channel (6 in all; never on the calling frequency)"}  # Settings > Operating (since 0.41)
UPDATE_CHECK_NAMES = {"daily": "Daily: when Kestrel starts and once a day while it runs", "startup": "Only when Kestrel starts", "off": "Off: never check"}  # Settings > Updates (since 0.42)
UPDATE_NOTIFY_NAMES = {"all": "Every new release", "signal": "Only releases that change the signal (both stations must update)"}  # Settings > Updates (since 0.42)
UPDATE_TEST_NAMES = {True: "Yes: include test releases (every Kestrel release is one for now)", False: "No: finished releases only"}  # Settings > Updates (since 0.42)
UPDATE_INSTALL_NAMES = {"ask": "Tell me, and offer Install now (downloads, closes, installs, restarts)", "notify": "Only tell me (I will download it myself)"}  # Settings > Updates (since 0.42)
ACTIVITY_NAMES = {False: "Off: no Activity window (the newest line shows at the bottom of the main window)", True: "On: starts minimized and stays in the background; never pops up by itself"}  # Settings > Operating (since 0.41; on/off since 0.42R2)


class MessageBox(tk.Text):  # the message box: a few lines tall, answering to an entry's get, delete and insert (since 0.41)
    """A multi-line text box with the parts of ttk.Entry's interface the panel uses: get(), delete(0, "end"), insert(0, text), icursor("end")."""

    def get(self, first=None, last=None):  # the text
        if first is None:  # as an entry: everything
            return super().get("1.0", "end-1c")  # without the newline Tk keeps at the end
        return super().get(first, last)  # as a text box

    def delete(self, first, last=None):  # remove text
        if first == 0:  # as an entry: from the start
            first, last = "1.0", "end"  # everything
        super().delete(first, last)  # gone

    def insert(self, index, chars, *args):  # add text
        super().insert("1.0" if index == 0 else index, chars, *args)  # an entry's 0 is the text box's first character

    def icursor(self, index):  # put the cursor somewhere
        self.mark_set("insert", "end-1c" if index == "end" else index)  # at the end, as an entry would


def local_time(seconds):  # the same moment in this computer's time zone (since 0.38R2)
    """Return `seconds` (since 1970) as a local month, day and time, for the Local column beside a UTC one."""
    return time.strftime("%m-%d %H:%M", time.localtime(seconds))  # month, day and time, local


def local_zone_name(seconds=None):  # this computer's time zone, short enough for a scope's margin
    """Return the local time zone at `seconds` (now if None) as its offset from UTC, such as "UTC-5" or "UTC+5:30" (daylight saving time included)."""
    moment = time.localtime(time.time() if seconds is None else seconds)  # the local time then
    minutes = int(moment.tm_gmtoff // 60)  # its offset from UTC, in minutes
    hours, rest = divmod(abs(minutes), 60)  # whole hours, and any part hour
    return f"UTC{'+' if minutes >= 0 else '-'}{hours}" + (f":{rest:02d}" if rest else "")  # written short


FONT_MIN, FONT_MAX = 7, 16  # the smallest and largest font sizes offered
SCOPE_HELP = ("Transmit (top): the audio Kestrel is sending to the radio, in dB below full scale. Its waterfall scrolls with the receive waterfall, empty while nothing is sent, so a transmission lines up with what was received at the same moment.\n\n"  # the transmit scope
              "Time marks (View > Time marks on the scopes, or Ctrl+T, to turn them on or off): a dotted line across both waterfalls every 5, 10, 15, 30 or 60 seconds (whichever suits the waterfall's height), labeled with the time, and a seconds-ago scale to the right. View > Scope time marks in chooses UTC or this computer's local time; the corner shows which (UTC, or the local zone as its offset, such as UTC-5).\n\n"  # the time marks
              "Receive (bottom): the audio from the radio. The trace is signal strength above the noise in dB; the waterfall under it is the last few seconds, newest at the top.\n\n"  # the receive scope
              "Across both: audio frequency in Hz below, and on the receive scope the radio frequency each point is on, in kHz, above. Dashed lines mark the Kestrel band, 500 to 2500 Hz. Stations decoded in the last minute are labeled.\n\n"  # the scales
              "Floor and Range (the sliders beside each scope): Floor sets the level at the bottom of the trace and the black of the waterfall; raise it to hide noise, lower it to see weaker signals. Range sets how many dB lie between the bottom and the top; fewer dB gives more contrast. Double-click a slider to reset it.\n\n"  # the sliders
              "Color (the third slider) and View > Waterfall colors: choose a set of colors that suits your eyes (two sets are made to be read with color blindness, two are gray only), then move Color to shift where the colors change. Up: weaker signals already reach the bright colors. Down: only strong signals do. Double-click it to put it back in the middle.\n\n"  # the color controls
              "Zoom: click a signal or its label, turn the mouse wheel, or pick a width in the View box. Right click, or Full view, shows everything again.\n\n"  # zooming
              "Sizes: drag the dividers between the panels to shrink one and grow another. View > Reset the panel sizes puts them back.")  # the dividers

SCOPE_LIMITS = {"rx": ((-30.0, 30.0), (10.0, 90.0), (0.0, 100.0)), "tx": ((-110.0, -20.0), (10.0, 100.0), (0.0, 100.0))}  # the Floor, Range and Color sliders' ends: Floor and Range in dB (receive floor relative to the noise, transmit floor below full scale); Color from 0 to 100
PALETTES = {  # the waterfall color sets offered in View > Waterfall colors: name -> color stops from weakest (0) to strongest (1), as (place, (red, green, blue))
    "Classic": [(0.0, (0, 0, 40)), (0.35, (0, 40, 200)), (0.7, (255, 255, 0)), (1.0, (255, 60, 0))],  # black, blue, yellow, red (the colors used before 0.31R4)
    "Color-blind safe (blue to yellow)": [(0.0, (0, 32, 77)), (0.25, (54, 70, 107)), (0.5, (124, 123, 120)), (0.75, (196, 177, 102)), (1.0, (255, 234, 70))],  # dark blue through gray to yellow: one rising brightness, readable with red-green color blindness
    "Color-blind safe (purple to yellow)": [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)), (0.75, (94, 201, 98)), (1.0, (253, 231, 37))],  # purple, blue, green, yellow: brightness rises steadily, readable with most color blindness
    "Heat (black, red, yellow, white)": [(0.0, (0, 0, 0)), (0.4, (180, 0, 0)), (0.75, (255, 200, 0)), (1.0, (255, 255, 255))],  # a fire's colors: strong contrast, no blue
    "Gray (black to white)": [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))],  # brightness only, no color at all
    "Gray, reversed (white to black)": [(0.0, (255, 255, 255)), (1.0, (0, 0, 0))],  # dark signals on a light background
    "High contrast (black, white, yellow)": [(0.0, (0, 0, 0)), (0.5, (255, 255, 255)), (1.0, (255, 255, 0))],  # weak signals turn white quickly, strong ones yellow
    "Night red (black to red)": [(0.0, (0, 0, 0)), (0.6, (150, 0, 0)), (1.0, (255, 70, 70))],  # red only, for night vision (since 0.37)
    "Amber (black to amber)": [(0.0, (8, 5, 0)), (0.6, (170, 100, 0)), (1.0, (255, 200, 60))],  # an amber screen (since 0.37)
    "Green phosphor (black to green)": [(0.0, (0, 8, 0)), (0.6, (0, 150, 40)), (1.0, (170, 255, 120))],  # an old radar screen (since 0.37)
    "Thermal (purple, red, yellow)": [(0.0, (12, 4, 20)), (0.35, (110, 20, 140)), (0.65, (230, 60, 40)), (1.0, (255, 230, 80))],  # a thermal camera's colors (since 0.37)
    "Ice (black, blue, white)": [(0.0, (2, 10, 20)), (0.5, (40, 110, 200)), (1.0, (235, 250, 255))],  # cold blues to white (since 0.37)
    "Ocean (navy to aqua)": [(0.0, (0, 10, 30)), (0.5, (0, 90, 140)), (1.0, (120, 255, 230))],  # deep water to surf (since 0.37)
}  # end of the table


def make_palette(name, color):  # the 256 colors of one waterfall
    """Return a 256 x 3 array of colors for the color set `name`, with the Color slider at `color` (0 to 100; 50 = the set as drawn).

    The slider moves where the colors change: above 50 the brighter colors are
    reached by weaker signals (weak signals stand out), below 50 only strong
    signals reach them (a quieter picture). It does this by bending the
    brightness scale: brightness b is shown as b ** g, with g from 4 (slider at 0)
    to 1/4 (slider at 100).
    """
    stops = PALETTES.get(name, PALETTES["Classic"])  # the chosen set (the classic one if the name is unknown; "Theme's own" is turned into the theme's set by the caller)
    bend = 2.0 ** ((50.0 - float(color)) / 25.0)  # the power applied to brightness: 1 at the middle of the slider
    steps = np.linspace(0.0, 1.0, 256) ** bend  # the 256 brightness steps, bent
    places = [p for p, _ in stops]  # where each color stop sits
    return np.stack([np.interp(steps, places, [c[k] for _, c in stops]) for k in range(3)], axis=1).astype("uint8")  # red, green and blue, each interpolated between the stops


SIGNAL_LABEL_ROWS = 3  # names of recognized signals are stacked in up to three rows where they would overlap (since 0.37)
THEME_OWN = "Theme's own"  # View > Waterfall colors: use the colors that go with the theme (since 0.37)
VIEW_WIDTHS = {"Full (0-3000 Hz)": 3000.0, "1000 Hz wide": 1000.0, "500 Hz wide": 500.0, "200 Hz wide": 200.0}  # the scope widths offered, by name


class Panel:  # the control panel window
    """The window, its controls, and the thread that runs the station."""

    def __init__(self, root):  # build the window
        self.root = root  # the top-level window
        self.settings = load_settings()  # remembered settings (callsign, grid, sound devices, rig control, ...)
        self.lines = queue.Queue()  # log lines waiting to be shown
        self.stop = threading.Event()  # set to stop the working thread
        self.worker = None  # the thread running the station, when there is one
        self.mode = "off"  # what is running now: listen, monitor or off
        self.next_mode = None  # a mode to start as soon as the running one has stopped
        self.actions = []  # requests waiting for the station's own thread (a call, a broadcast), each a function that returns True once done
        self.actions_lock = threading.Lock()  # the window adds requests while the station thread takes them
        self.outbox_lock = threading.Lock()  # one thread at a time may hand the message queue between the window and a running station (since 0.40R3)
        self.outbox = []  # messages queued while no station is running, as (text, callsign it is for or "")
        self.held, self.joiner, self.chain_rows, self.move_offsets, self.move_ok, self.held_told = [], chain.Joiner(), {}, [], False, set()  # chained messages: pieces held for a working channel, the receiver's joiner, its rows, the working channels and whether the radio can move, what was said (since 0.42)
        self.shown_b = 0  # how many of the tracked station's received broadcasts are already in the list
        self.station = None  # the station that is running now, when there is one, so a message can be handed straight to it
        self.tracked = None  # the station whose messages the lists are following (kept after it stops, for a last look)
        self.marked = 0  # how many of the tracked station's delivered messages are already marked in the list
        self.shown = 0  # how many of the tracked station's received messages are already in the list
        self.history = []  # every log line so far, as (time of day, line), so the log can be redrawn plain or in detail
        self.heard = queue.Queue()  # reports of stations heard, waiting to go into the list (filled by the working thread)
        self.long_notes = None  # this station's long notes (live.notes.LongNotes, since 0.34), made for its callsign when first needed and kept between runs
        self.note_events = queue.Queue()  # long-note events from the working thread, waiting to be shown
        self.idle_calls = queue.Queue()  # the 10-second warnings from the working thread, waiting to be shown (since 0.41)
        self.idle_watch = None  # the running station's idle watch, for the contact bar's countdown (since 0.41)
        self.idle_box = None  # the 10-second warning window, while one is showing (since 0.41)
        self.note_rows = {}  # (to, text) -> the row of a long note in Messages to send
        self.heard_rows = {}  # callsign -> its row in the stations-heard list
        self.notice = None  # the warning window about an idle working frequency, while one is showing
        self.contacts = ContactBook(CONTACTS_FILE, self.settings.get("contact_history", HISTORY_DEFAULT), self.settings.get("contact_history_mode", "all"))  # the contact book: callsign -> record with name, rig, notes and history (live/contacts.py; since 0.31R3)
        self.entries = []  # the frequency entries behind the drop-down list
        self.rigs = RigServer()  # the rig control program this panel starts for the chosen radio
        self.rig_lock = threading.Lock()  # only one thread at a time may start or tune through rig control
        self.beacon_wanted = False  # the repeating beacon is switched on (read by the station thread)
        self.beacon_due = 0.0  # when the next beacon round is due, on the monotonic clock
        self.beacon_note = ""  # what the repeating beacon is doing, for the label beside its button
        self.last_input = time.monotonic()  # when the operator last pressed a key or used the mouse (for the beacon's automatic stop)
        self.audio = None  # the sound-card input, while a station or the monitor is running
        self.sink = None  # the sound-card output, while a station is running (its level follows the transmit slider)
        self.tx_active = False  # True while the transmitter is keyed
        self.station_now = 0.0  # the running station's clock at its last look (its log lines are stamped with it)
        self.tx_kind = ""  # what is being sent, while the transmitter is keyed
        self.alc_warned = False  # whether the operator has been told the ALC is high during this transmission
        self.signal_log = None  # the signal log of the run under way, if any
        self.meters = {"watts": None, "alc": None, "swr": None, "set_w": None}  # the radio's readings: power out, ALC and SWR while transmitting, and the power setting
        self.poller_stop = threading.Event()  # stops the thread that reads the radio's meters
        self.marks = {}  # stations decoded recently, for the scope: callsign -> (audio frequency, width, when)
        self.clips_seen = 0  # the input's clip count as of the last meter update
        self.clip_until = 0.0  # show CLIP on the receive meter until this time
        self.contact = None  # the contact in progress, for the logbook: a dict, or None
        self.telemetry_in = []  # telemetry received: (time, callsign, parsed message)
        self.awaiting_setup = False  # True when the panel is waiting for the first Settings to be saved before it starts
        self.rx_level = None  # Windows' level control for the receive audio device, when it can be had
        self.windows = {}  # windows of which only one may be open (stations heard, telemetry, settings), by name
        self.availability = {}  # callsign -> (True if it said it is available, when it said so), from beacons and "not available" replies
        self.calling = {}  # stations heard beaconing recently, for the Stations calling window: callsign -> {grid, snr, when, fields}
        self.base_khz = 0.0  # the calling frequency chosen, in kHz (kept here so the station thread need not read the window)
        self.level_check = 0.0  # when Windows' receive level was last read back
        self.mailroom = Mailroom.load(self.mail_file(), self.settings["call"])  # this station's mail: its own messages for named stations, mail it carries for others, receipts
        self.mail_saved = time.monotonic()  # when the mail was last written to its file
        self.mail_notices = {}  # callsign -> (time, fields) of the last mail notice heard from each station
        self.heardlog = heardlog.HeardLog(side_file("_heard.jsonl"))  # every station heard in the last 48 hours, kept on disk
        self.spotter = None  # PSK Reporter spotting, made when turned on in Settings (since 0.35)
        self.watch = signalwatch.SignalWatch()  # every signal in the passband, followed and recognized (since 0.37)
        self.frames = FrameStrip()  # the Kestrel frame arriving or last heard, and its message's parts, for the frame strip (since 0.37)
        self.steps_heard = {}  # callsign -> (time, powersteps.Reading): the last power steps read before each station's beacon (since 0.38)
        self.gap_said = {}  # callsign -> the UTC hour its prediction check was last told in the Activity log (since 0.39)
        self.tx_readings = []  # (watts, ALC) read during the transmission under way (since 0.40R1)
        self.rig_names = {}  # Hamlib model number -> "Maker Model", to name the rig a beacon carries (filled in the background; since 0.40)
        self.strip_at = 0.0  # when the frame strip was last drawn
        self.watch_at = 0.0  # when the watcher last looked
        self.logbook = logbook.Logbook(LOG_FOLDER, name="kestrel" + (f"_{PROFILE}" if PROFILE else ""), level=self.settings["log_level"])  # the CSV and ADIF logs
        self.logbook.observers.append(self.contacts.observe)  # the contact book learns of every call, reception and contact from the logbook, at any level of detail
        self.fonts = {}  # Kestrel's own named fonts (small, tiny, big ...), which follow the font chosen in Settings
        self.panes = {}  # the dividers the operator can drag, by name, so their positions can be remembered
        self.colors = theme.apply(root, self.settings["theme"], self.settings.get("scope_theme", "theme"))  # the chosen theme and scope theme, and their colors
        self.apply_fonts()  # the lettering chosen in Settings, before anything is drawn
        root.title(f"Kestrel {SPEC_VERSION}  -  signal v{SIGNAL_VERSION}")  # window title: the program's version, and the signal version so two stations can be compared at a glance (the two differ when a release changes only the program)
        root.columnconfigure(0, weight=1)  # the single column stretches with the window
        self.mode_var = tk.StringVar(value="off")  # the mode buttons and menu items share this
        self.beacon_var = tk.BooleanVar(value=False)  # the beacon button and menu item share this
        self.beacon_type_var = tk.StringVar(value=self.settings.get("beacon_type", "short"))  # short or long beacons
        self.available_var = tk.BooleanVar(value=bool(self.settings["available"]))  # available for contacts, or not
        self.keep_open = tk.BooleanVar(value=bool(self.settings["keep_open"]))  # whether the lock is held after the traffic is done
        self.details = tk.BooleanVar(value=False)  # whether the log shows the technical detail
        self.theme_var = tk.StringVar(value=self.settings["theme"])  # the look chosen in the View menu
        self._menus()  # the menu bar
        top = ttk.Frame(root)  # the strip holding the status band and the station's own details
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))  # place it at the top
        top.columnconfigure(0, weight=1)  # the status band takes the spare width
        self.status = tk.Label(top, text="OFF", font="KestrelBig", anchor="w", padx=10, pady=5)  # the station's state in large letters, on a band of color
        self.status.grid(row=0, column=0, sticky="ew")  # place it on the left
        self.me = ttk.Label(top, text="", font="KestrelMedium")  # this station's callsign and grid locator
        self.me.grid(row=0, column=1, sticky="e", padx=(8, 0))  # place it on the right
        self.contact_bar = ttk.Frame(root, padding=(0, 2))  # the contact bar: the partner and the link at a glance while a contact is under way (since 0.41)
        self.contact_bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 0))  # under the status band
        self.bar_values = {}  # the contact bar's readings, by name
        for column, (name, title) in enumerate((("partner", "Partner"), ("you_hear", "You hear them"), ("they_hear", "They hear you"), ("speed", "Speed"), ("traffic", "Traffic"), ("timer", "Back to calling in"))):  # its six readings
            self.contact_bar.columnconfigure(column, weight=1, uniform="bar")  # all the same width
            cell = ttk.Frame(self.contact_bar, padding=(8, 0))  # one reading
            cell.grid(row=0, column=column, sticky="w")  # in its place
            ttk.Label(cell, text=title.upper(), font="KestrelTinyBold").pack(anchor="w")  # its title, small
            self.bar_values[name] = ttk.Label(cell, text="-", font="KestrelMedium")  # its value
            self.bar_values[name].pack(anchor="w")  # under the title
        self.readings = self.bar_values["you_hear"]  # kept under its old name for any code that still refers to it
        tuning = ttk.Frame(root)  # the frequency and the working-channel choice, on one strip (since 0.41)
        tuning.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 2))  # place it
        ttk.Label(tuning, text="Frequency").pack(side="left", padx=(0, 6))  # label for the frequency list
        self.frequency = ttk.Combobox(tuning, state="readonly", width=34)  # the frequency drop-down list: band, dial and what it is (the details show in its hover help)
        self.frequency.pack(side="left")  # place it
        self.frequency.bind("<<ComboboxSelected>>", lambda event: (self.tune(), self.update_frequency_tip()))  # choosing a frequency tunes the radio to it
        self.frequency_tip = Tooltip(self.frequency, "")  # its details, filled in when a frequency is chosen
        ttk.Label(tuning, text="Once locked").pack(side="left", padx=(16, 4))  # label for the working-channel choice
        self.working = ttk.Combobox(tuning, state="readonly", width=34)  # stay on the calling frequency, or move to a numbered channel
        self.working.pack(side="left")  # place it
        Tooltip(self.working, "Where a contact goes once it is locked: stay on the calling frequency, or move to a working channel. Keep-Alive (Settings > Operating) applies only on working channels.")  # help
        operate = ttk.Frame(root)  # the row of operating controls
        operate.grid(row=3, column=0, sticky="w", padx=8, pady=4)  # place it
        for mode, words, tip in (("listen", "Listen", "Listen (F2): receive, and send only what you start; Respond to beacons and calls from Stations heard."), ("monitor", "Monitor", "Monitor (F3): receive only; nothing is ever sent."), ("off", "Off", "Off (F4): neither receive nor send.")):  # the three modes, as one three-way switch
            button = ttk.Radiobutton(operate, text=words, value=mode, variable=self.mode_var, style="Toolbutton", command=lambda m=mode: self.set_mode(m))  # one segment each
            button.pack(side="left")  # side by side, touching
            Tooltip(button, tip)  # help
        ttk.Separator(operate, orient="vertical").pack(side="left", fill="y", padx=10)  # a divider
        self.available_button = ttk.Checkbutton(operate, text="Available", style="Toolbutton", variable=self.available_var, command=self.available_toggled)  # pushed in = available for contacts
        self.available_button.pack(side="left", padx=(0, 6))  # place it
        Tooltip(self.available_button, "Available (Ctrl+U): pushed in, you take contacts. Out: a caller gets one short 'not available' reply, and your beacons say you are away.")  # help
        self.beacon_button = ttk.Checkbutton(operate, text=self.beacon_words(), style="Toolbutton", variable=self.beacon_var, command=self.beacon_toggled)  # pushed in = repeating beacon on; pushed again = off
        self.beacon_button.pack(side="left")  # place it
        Tooltip(self.beacon_button, "Beacon (F5): call anyone, repeating. Operate > Beacon type chooses short or long; Settings > Operating sets how often.")  # help
        self.beacon_label = ttk.Label(operate, text="off", width=18, font="KestrelSmall")  # what the repeating beacon is doing
        self.beacon_label.pack(side="left", padx=6)  # place it
        ttk.Separator(operate, orient="vertical").pack(side="left", fill="y", padx=10)  # a divider
        for words, job, tip in (("Call", self.call_to, "Call (F6): call the station in To by name. If short calls go unanswered and that station is heard in long frames, a long call follows by itself."),  # (continued)
                                ("Stop calling", self.stop_calling, "Stop calling (Esc): stop a call or beacon round, cutting it short on the air."),  # (continued)
                                ("End contact", self.end_contact, "End contact (F7): close the contact properly, with identification.")):  # the contact buttons
            button = ttk.Button(operate, text=words, command=job)  # one each
            button.pack(side="left", padx=2)  # side by side
            Tooltip(button, tip)  # help
        self.panes["split"] = split = ttk.PanedWindow(root, orient="vertical")  # everything below the controls, in two rows with a divider between them
        split.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)  # it takes the rest of the window
        self.panes["lists"] = lists = ttk.PanedWindow(split, orient="horizontal")  # the upper row: the message panel, then the lists, with a divider between them
        split.add(lists, weight=1)  # the upper row
        typing = ttk.LabelFrame(lists, text="Message")  # the message panel (since 0.41)
        lists.add(typing, weight=1)  # on the left
        typing.columnconfigure(5, weight=1)  # the spare width
        typing.rowconfigure(1, weight=1)  # the message box takes the spare height
        ttk.Label(typing, text="To").grid(row=0, column=0, sticky="w", padx=(6, 4), pady=4)  # label for the callsign box
        self.to = ttk.Combobox(typing, width=10)  # the callsign a message is for, or the station to call: type one, or pick ALL, a saved contact or a station heard; blank means whoever the partner is
        self.to.grid(row=0, column=1, sticky="w")  # place it
        self.to.bind("<Return>", lambda event: self.message.focus_set())  # Enter in the To box moves on to the message
        Tooltip(self.to, "To (Ctrl+L): a callsign, ALL for everyone, or blank for whoever the partner is. Stations > Contacts (Ctrl+K) keeps your contact records.")  # help
        ttk.Label(typing, text="As").grid(row=0, column=2, sticky="w", padx=(8, 4))  # label for how the message goes
        self.send_as = ttk.Combobox(typing, state="readonly", width=17, values=SEND_AS)  # a normal message, or a long note (since 0.41)
        self.send_as.set(SEND_AS[0])  # normal unless chosen
        self.send_as.grid(row=0, column=3, sticky="w")  # place it
        self.send_as.bind("<<ComboboxSelected>>", lambda event: self.count_message())  # the countdown says what a long note holds
        Tooltip(self.send_as, f"Normal: sent in the contact, or as a broadcast when To is ALL. Long note (reach, Ctrl+N): up to {LONG_NOTE_CHARS} characters in minute-long frames, heard about 5 dB further down.")  # help
        self.quick_menu = tk.Menu(root, tearoff=False)  # the quick messages
        quick = ttk.Menubutton(typing, text="Quick", menu=self.quick_menu)  # the button that opens them
        quick.grid(row=0, column=4, sticky="w", padx=(8, 0))  # place it
        Tooltip(quick, "Quick messages (Alt+1 to Alt+0) and telemetry; Settings > Quick messages changes them.")  # help
        self.message = MessageBox(typing, height=3, width=30, wrap="word", undo=True, relief="solid", borderwidth=1, font="TkTextFont")  # the message box, a few lines tall, in the ordinary lettering
        self.message.grid(row=1, column=0, columnspan=6, sticky="nsew", padx=6, pady=(0, 4))  # place it
        self.message.bind("<Return>", lambda event: (self.send_typed(), "break")[1])  # Enter sends
        self.message.bind("<Shift-Return>", lambda event: None)  # Shift+Enter starts a new line
        self.message.bind("<KeyRelease>", lambda event: self.count_message(), add="+")  # the countdown follows the typing
        self.message.bind("<Tab>", lambda event: (event.widget.tk_focusNext().focus_set(), "break")[1])  # Tab moves on, as in an entry
        foot = ttk.Frame(typing)  # under the message box
        foot.grid(row=2, column=0, columnspan=6, sticky="ew", padx=6, pady=(0, 6))  # place it
        foot.columnconfigure(0, weight=1)  # the countdown takes the spare width
        self.count_label = ttk.Label(foot, text=f"{MESSAGE_MOST} characters left", font="KestrelSmall")  # the character countdown (since 0.41)
        self.count_label.grid(row=0, column=0, sticky="w")  # on the left
        ttk.Button(foot, text="Clear", command=self.clear_message).grid(row=0, column=1, padx=(4, 4))  # empty the message box
        send = ttk.Button(foot, text="Send", command=self.send_typed)  # send what was typed: one button for a message, a broadcast and a long note (since 0.41)
        send.grid(row=0, column=2)  # on the right
        Tooltip(send, "Send (Enter): to the station in To, in the contact; to ALL as a broadcast (F11); or as a long note when As says so. Shift+Enter starts a new line.")  # help
        self.tabs = ttk.Notebook(lists)  # the lists, as tabs on one card (since 0.41)
        lists.add(self.tabs, weight=2)  # on the right, wider
        self.stations = self._list(self.tabs, 0, "Stations heard", (("saved", "*", 22), ("who", "Callsign", 84), ("grid", "Grid", 50), ("band", "Band", 46), ("snr", "SNR", 44), ("time", "Heard", 108), ("text", "Sending", 66), ("mail", "Status", 82), ("utc", "UTC", 48)))  # every callsign heard, plus the saved contacts (marked *); stations beaconing now are highlighted
        self.received = self._list(self.tabs, 1, "Received", (("time", "Received (local)", 110), ("who", "From", 110), ("text", "Message", 260), ("utc", "UTC", 56)))  # incoming messages and broadcasts
        self.to_send = self._list(self.tabs, 2, "To send", (("time", "Queued", 64), ("to", "To", 70), ("band", "Band", 46), ("text", "Message", 190), ("state", "State", 190), ("utc", "UTC", 64)))  # outgoing messages, who each is for, and how far each has got
        change = ttk.Frame(self.to_send.master)  # buttons under that list
        change.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))  # place them
        ttk.Button(change, text="Edit message", command=self.edit_message).pack(side="left", padx=(0, 4))  # change the selected waiting message
        ttk.Button(change, text="Delete message  Del", command=self.remove_message).pack(side="left")  # take back the selected messages
        self.to_send.bind("<Delete>", lambda event: self.remove_message())  # the Delete key does the same
        self.send_menu = tk.Menu(root, tearoff=False)  # the menu a right click on a message brings up
        self.send_menu.add_command(label="Edit message...", command=self.edit_message)  # change it
        self.send_menu.add_command(label="Delete message", accelerator="Del", command=self.remove_message)  # take it back
        self.send_menu.add_separator()  # then the list as a whole
        self.send_menu.add_command(label="Select all", accelerator="Ctrl+A", command=lambda: self.select_all_rows(self.to_send))  # every message
        self.send_menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self.copy_rows(self.to_send))  # to the clipboard
        self.send_menu.add_command(label="Clear finished messages", command=self.clear_finished)  # delivered and sent ones leave the list; waiting ones stay
        self.to_send.bind("<Control-a>", lambda event: (self.select_all_rows(self.to_send), "break")[1])  # Ctrl+A in the list
        self.to_send.bind("<Control-c>", lambda event: (self.copy_rows(self.to_send), "break")[1])  # Ctrl+C in the list
        self.to_send.bind("<Button-3>", self.send_menu_at)  # a right click selects the message under the pointer and shows the menu
        keep = ttk.Frame(self.stations.master)  # buttons under that list
        keep.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))  # place them
        ttk.Button(keep, text="Respond", command=self.respond).pack(side="left", padx=(0, 4))  # call the selected station by name (answer its beacon by hand)
        ttk.Button(keep, text="Save", command=self.save_contact).pack(side="left")  # keep the selected callsign for later
        ttk.Button(keep, text="Remove", command=self.remove_from_list).pack(side="left", padx=2)  # off this list; a contact record is kept (since 0.39; was Remove contact)
        ttk.Button(keep, text="Contacts", command=self.contacts_window).pack(side="left", padx=2)  # the contact records: view, search, change, delete (since 0.39)
        ttk.Button(keep, text="48 h", command=self.heard_window).pack(side="left", padx=2)  # the longer record (shorter label so it fits at 1024 wide, since 0.42)
        self.stations.bind("<Double-1>", lambda event: self.station_detail_window())  # a double-click opens a window with everything shown about the station, in full (since 0.40; its Contact record button opens the record, as a double-click did before)
        self.received.bind("<Double-1>", lambda event: self.message_detail_window())  # a double-click opens the message in a window of its own, to read in full (since 0.40)
        self.station_menu = tk.Menu(root, tearoff=False)  # the menu a right click on a station brings up
        self.station_menu.add_command(label="Respond (call this station)", accelerator="Ctrl+Y", command=self.respond)  # call it by name
        self.station_menu.add_command(label="Contact record...", command=self.open_station_record)  # its record (as a double-click)
        self.station_menu.add_command(label="Save as contact", command=self.save_contact)  # keep it
        self.station_menu.add_command(label="Remove from this list (a contact record is kept)", command=self.remove_from_list)  # off the list only (since 0.39)
        self.station_menu.add_command(label="Show last 48 hours", command=self.station_history)  # its receptions
        self.station_menu.add_command(label="Propagation to this station...", command=self.propagation_selected)  # best band by hour to it (since 0.32)
        self.station_menu.add_separator()  # then the list as a whole
        self.station_menu.add_command(label="Select all", accelerator="Ctrl+A", command=lambda: self.select_all_rows(self.stations))  # every station
        self.station_menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self.copy_rows(self.stations))  # to the clipboard
        self.station_menu.add_command(label="Clear stations heard (saved contacts stay)", command=self.clear_heard)  # empty the list of stations heard
        self.stations.bind("<Control-a>", lambda event: (self.select_all_rows(self.stations), "break")[1])  # Ctrl+A in the list
        self.stations.bind("<Control-c>", lambda event: (self.copy_rows(self.stations), "break")[1])  # Ctrl+C in the list
        self.stations.bind("<Button-3>", self.station_menu_at)  # a right click selects the station under the pointer and shows the menu
        self.stations.bind("<Return>", lambda event: self.pick_station())  # so does Enter
        for call in sorted(self.contacts):  # the saved contacts are listed from the start
            self.heard_rows[call] = self.stations.insert("", "end", values=("*", call, self.contacts[call].get("grid", ""), self.contacts[call].get("band", ""), "", heard_when(self.contacts[call]), "saved contact"))  # one row each, with the band it was last heard on
        self.refresh_to()  # offer them in the To box
        for item in read_json(side_file("_outbox.json"), []):  # messages left waiting when the panel was last closed
            self.to_send.insert("", "end", values=(item.get("time", ""), item.get("to") or "partner", self.band_for(item.get("to", "")), item.get("text", ""), "waiting"))  # back in the list
            self.outbox.append((item.get("text", ""), item.get("to", "")))  # and back in the queue for the next contact
        self.panes["bottom"] = bottom = ttk.PanedWindow(split, orient="horizontal")  # the lower row: the scopes and the level meters, with a divider between them (the Activity log has its own window since 0.41)
        split.add(bottom, weight=3)  # under the lists
        self._activity_window()  # the Activity log, in a window of its own (since 0.41)
        self._scope(bottom)  # build the scopes
        self._meters(bottom)  # build the level meters and sliders
        bottom.bind("<Configure>", lambda event: self.root.after_idle(self.keep_meters_visible), add="+")  # when the row changes size, the meters keep their width
        bottom.bind("<ButtonRelease-1>", lambda event: self.root.after_idle(self.keep_meters_visible), add="+")  # and when a divider is let go
        ticker = ttk.Frame(root)  # the status bar: the newest Activity line, and the way to the Activity window (since 0.41)
        ticker.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 4))  # at the bottom of the window
        ticker.columnconfigure(0, weight=1)  # the line takes the width
        self.ticker = ttk.Label(ticker, text="", font="KestrelSmall", anchor="w")  # the newest Activity line
        self.ticker.grid(row=0, column=0, sticky="ew")  # on the left
        self.activity_button = activity_button = ttk.Button(ticker, text="Activity", command=self.toggle_activity)  # open or close the Activity window (kept, so Settings can turn it off, since 0.42R2)
        activity_button.grid(row=0, column=1, sticky="e")  # on the right
        chat_button = ttk.Button(ticker, text="Chat", command=self.toggle_chat)  # open or close the Chat window (since 0.42)
        chat_button.grid(row=0, column=2, sticky="e", padx=(4, 0))  # beside Activity
        Tooltip(chat_button, "The Chat window (View > Chat window, Ctrl+Shift+C): the conversation with the station you are in contact with, both sides as a running exchange. Type a line and press Enter to send it.")  # help
        Tooltip(activity_button, "The Activity window: every line of the running log (View > Activity window). Warnings open it by themselves.")  # help
        root.rowconfigure(4, weight=1)  # the lists and the scopes stretch with the window
        root.after(250, self.restore_layout)  # once the window is up, put it and the dividers back as they were left
        self.refresh_frequencies(self.settings["frequency"])  # fill the frequency list
        self.refresh_quick()  # fill the quick-message menu
        self.show_me()  # show this station's callsign and grid
        self.color_plain_widgets()  # color the widgets the theme does not reach
        self._shortcuts()  # the keyboard shortcuts
        for event in ("<KeyPress>", "<ButtonPress>", "<MouseWheel>", "<Motion>"):  # anything the operator does in the window...
            root.bind_all(event, self.touched, add="+")  # ...counts as being at the station
        root.protocol("WM_DELETE_WINDOW", self.close)  # save and stop cleanly when the window is closed
        self.update_thread, self.update_result, self.update_offer, self.update_waiting, self.update_label = None, None, None, None, None  # the update check: its thread, its answer, the release on offer, one waiting to install, the Settings label (since 0.42)
        root.after(20000, lambda: self.update_tick(True))  # the first check, 20 seconds after start, so it never slows the start (since 0.42)
        root.after(100, self.show_lines)  # start passing log lines to the window
        root.after(500, self.follow_station)  # start keeping the lists and readings up to date
        root.after(100, self.draw_scope)  # start drawing the scope
        root.after(200, self.draw_meters)  # start drawing the level meters
        root.after(300, lambda: theme.color_window(root, self.colors))  # the title bar again, now the window is on screen
        root.after(700, self.autostart)  # start listening, once the window is up
        root.after(1500, self.load_rig_names)  # the Hamlib names, to name the rig a beacon carries (since 0.40)

    # ---- building blocks ----

    def _menus(self):  # the menu bar
        bar = tk.Menu(self.root)  # the bar itself
        file_menu = tk.Menu(bar, tearoff=False)  # the File menu
        file_menu.add_command(label="Open the log folder", underline=5, command=self.open_logs)  # where the CSV and ADIF files are
        file_menu.add_command(label="Open today's log", underline=5, command=lambda: self.open_path(self.logbook.csv_path()))  # the day's CSV file, in the spreadsheet program
        file_menu.add_command(label="Open the contact log (ADIF)", underline=9, command=lambda: self.open_path(self.logbook.adif_path()))  # the ADIF file
        file_menu.add_separator()  # a divider
        file_menu.add_command(label="Open the recordings folder", underline=9, command=lambda: self.open_path(recordings_dir(data_dir())))  # the received-audio WAV files
        file_menu.add_command(label="Decode a recording...", underline=0, command=self.decode_recording)  # play a WAV file through the receiver and list what it finds
        file_menu.add_command(label="Open the signal log folder", underline=5, command=lambda: self.open_path(self.signal_folder()))  # the detailed signal logs
        file_menu.add_command(label="Signal log report...", underline=7, command=self.signal_log_report)  # summarize the signal logs into a text file
        file_menu.add_separator()  # a divider
        file_menu.add_command(label="Export settings...", underline=1, command=self.export_settings)  # this station's settings to a file, for a backup or another computer (since 0.37)
        file_menu.add_command(label="Import settings...", underline=0, command=self.import_settings)  # settings from such a file (since 0.37)
        file_menu.add_command(label="Export themes...", underline=7, command=self.export_themes)  # every theme the operator made or changed, to a file of its own (since 0.37)
        file_menu.add_command(label="Import themes...", underline=8, command=self.import_themes)  # themes from such a file (since 0.37)
        file_menu.add_separator()  # a divider
        file_menu.add_command(label="Exit", underline=1, accelerator="Alt+F4", command=self.close)  # close the panel
        bar.add_cascade(label="File", underline=0, menu=file_menu)  # put the menu on the bar
        operate = tk.Menu(bar, tearoff=False)  # the Operate menu
        operate.add_radiobutton(label="Listen", underline=0, accelerator="F2", value="listen", variable=self.mode_var, command=lambda: self.set_mode("listen"))  # listen; send only what the operator starts
        operate.add_radiobutton(label="Monitor (receive only)", underline=0, accelerator="F3", value="monitor", variable=self.mode_var, command=lambda: self.set_mode("monitor"))  # receive only
        operate.add_radiobutton(label="Off", underline=1, accelerator="F4", value="off", variable=self.mode_var, command=lambda: self.set_mode("off"))  # neither
        operate.add_separator()  # a divider
        operate.add_checkbutton(label="Available for contacts", underline=0, accelerator="Ctrl+U", variable=self.available_var, command=self.available_toggled)  # available or not
        operate.add_checkbutton(label="Beacon (call anyone), repeating", underline=0, accelerator="F5", variable=self.beacon_var, command=self.beacon_toggled)  # the repeating beacon
        beacon_type = tk.Menu(operate, tearoff=False)  # the kind of beacon
        for value, words in BEACON_TYPE_NAMES.items():  # short and long
            beacon_type.add_radiobutton(label=words, value=value, variable=self.beacon_type_var, command=self.beacon_type_changed)  # one choice each
        operate.add_cascade(label="Beacon type", underline=7, menu=beacon_type)  # short or long
        operate.add_command(label="Call the station in To", underline=0, accelerator="F6", command=self.call_to)  # a directed call
        operate.add_command(label="End contact", underline=0, accelerator="F7", command=self.end_contact)  # close the contact
        operate.add_command(label="Stop calling (and cut the call short on the air)", underline=0, accelerator="Esc", command=self.stop_calling)  # stop a call or beacon round
        operate.add_separator()  # a divider
        operate.add_command(label="Choose frequency", underline=7, accelerator="Ctrl+R", command=lambda: self.frequency.focus_set())  # go to the frequency list
        operate.add_command(label="Previous frequency", underline=0, accelerator="Ctrl+Up", command=lambda: self.step_frequency(-1))  # one up the list
        operate.add_command(label="Next frequency", underline=0, accelerator="Ctrl+Down", command=lambda: self.step_frequency(1))  # one down the list
        operate.add_command(label="Add a frequency...", underline=0, command=self.add_frequency)  # one of the operator's own
        operate.add_command(label="Remove this frequency", underline=0, command=self.remove_frequency)  # remove one of the operator's own
        bar.add_cascade(label="Operate", underline=0, menu=operate)  # put the menu on the bar
        messages = tk.Menu(bar, tearoff=False)  # the Messages menu
        messages.add_command(label="Go to the To box", underline=10, accelerator="Ctrl+L", command=lambda: self.to.focus_set())  # who the message is for
        messages.add_command(label="Go to the Message box", underline=10, accelerator="Ctrl+M", command=lambda: self.message.focus_set())  # the message
        messages.add_command(label="Queue the message", underline=0, accelerator="Enter", command=self.queue_message)  # into the list to send
        messages.add_command(label="Broadcast the message to ALL", underline=0, accelerator="F11", command=self.broadcast_message)  # to everyone
        messages.add_command(label="Send the message as a long note (reach)...", underline=21, accelerator="Ctrl+N", command=self.long_note_message)  # up to 64 characters in long frames (28 before 0.39), with a receipt (since 0.34)
        messages.add_separator()  # a divider
        self.quick_submenu = tk.Menu(messages, tearoff=False)  # the quick messages, by name (filled by refresh_quick)
        messages.add_cascade(label="Quick messages", underline=0, menu=self.quick_submenu)  # put it in the Messages menu
        messages.add_separator()  # a divider
        messages.add_command(label="Send telemetry to the station in To", underline=0, accelerator="Ctrl+4", command=self.send_telemetry)  # what this station hears, to one station
        messages.add_command(label="Broadcast telemetry to ALL", underline=10, accelerator="Ctrl+5", command=self.broadcast_telemetry)  # to everyone
        bar.add_cascade(label="Messages", underline=0, menu=messages)  # put the menu on the bar
        stations = tk.Menu(bar, tearoff=False)  # the Stations menu
        stations.add_command(label="Respond to the selected station (call it)", underline=0, accelerator="Ctrl+Y", command=self.respond)  # answer a beacon by hand
        stations.add_command(label="Stations heard (last 48 hours)...", underline=0, accelerator="F8", command=self.heard_window)  # the longer record
        stations.add_command(label="Telemetry received...", underline=0, accelerator="F9", command=self.telemetry_window)  # what other stations hear
        stations.add_command(label="Mail held and carried...", underline=0, accelerator="F10", command=self.mail_window)  # store and forward: mail this station carries, and its own messages out with carriers
        stations.add_command(label="Signals detected...", underline=1, accelerator="Ctrl+D", command=self.signals_window)  # every signal in the passband, recognized (since 0.37)
        stations.add_command(label="Propagation (best band by hour)...", underline=0, accelerator="Ctrl+P", command=lambda: self.propagation_window())  # ITU-R P.533 predictions to the station in To (since 0.32)
        stations.add_separator()  # a divider
        stations.add_command(label="Go to the stations list", underline=6, accelerator="Ctrl+G", command=self.focus_stations)  # the list on the main window
        stations.add_command(label="Put the selected callsign in To", underline=0, accelerator="Enter", command=self.pick_station)  # use it
        stations.add_command(label="Save the selected station as a contact", underline=0, command=self.save_contact)  # keep it
        stations.add_command(label="Remove the selected stations from the list", underline=0, command=self.remove_from_list)  # off the list; contact records are kept (since 0.39)
        stations.add_separator()  # a divider
        stations.add_command(label="Contacts (view, search, change, delete)...", underline=0, accelerator="Ctrl+K", command=self.contacts_window)  # the contact records (since 0.39)
        stations.add_command(label="Add the callsign in To as a contact...", underline=4, command=self.add_contact)  # a new record (a button under the To box before 0.41)
        stations.add_command(label="Edit the contact in To...", underline=0, command=self.edit_contact)  # its record (a button under the To box before 0.41)
        bar.add_cascade(label="Stations", underline=0, menu=stations)  # put the menu on the bar
        view = tk.Menu(bar, tearoff=False)  # the View menu
        self.looks_menu = tk.Menu(view, tearoff=False)  # the Theme submenu (filled by refresh_theme_menus, again whenever the operator's themes change)
        view.add_cascade(label="Theme", underline=0, menu=self.looks_menu)  # put it in the View menu
        self.scope_theme_var = tk.StringVar(value=self.settings.get("scope_theme", "theme") if self.settings.get("scope_theme") in theme.SCOPE_THEMES else "theme")  # the scopes' own look (since 0.37)
        self.scope_looks_menu = tk.Menu(view, tearoff=False)  # the Scope theme submenu (filled the same way)
        view.add_cascade(label="Scope theme", underline=0, menu=self.scope_looks_menu)  # put it in the View menu
        view.add_command(label="Edit themes...", underline=0, command=lambda: open_theme_editor(self))  # make, change and share themes (since 0.37)
        self.refresh_theme_menus()  # fill both submenus
        self.palette_var = tk.StringVar(value=self.settings.get("scope_palette") if self.settings.get("scope_palette") in PALETTES or self.settings.get("scope_palette") == THEME_OWN else "Classic")  # the waterfall color set chosen (the classic one if the saved name is unknown)
        colors = tk.Menu(view, tearoff=False)  # the Waterfall colors submenu
        colors.add_radiobutton(label=THEME_OWN + " (follows the theme)", value=THEME_OWN, variable=self.palette_var, command=self.palette_chosen)  # the theme's own colors (since 0.37)
        colors.add_separator()  # a divider
        for name in PALETTES:  # every color set offered
            colors.add_radiobutton(label=name, value=name, variable=self.palette_var, command=self.palette_chosen)  # one each
        view.add_cascade(label="Waterfall colors", underline=0, menu=colors)  # put it in the View menu
        self.time_marks_var = tk.BooleanVar(value=bool(self.settings.get("scope_time_marks", True)))  # whether the waterfalls show time marks
        view.add_checkbutton(label="Time marks on the scopes", underline=1, accelerator="Ctrl+T", variable=self.time_marks_var, command=self.time_marks_chosen)  # the time marks and the seconds scale, on or off
        self.time_zone_var = tk.StringVar(value="local" if self.settings.get("scope_time_zone") == "local" else "utc")  # whether the marks show UTC or this computer's local time
        zones = tk.Menu(view, tearoff=False)  # the Scope time submenu
        zones.add_radiobutton(label="UTC", underline=0, value="utc", variable=self.time_zone_var, command=self.time_zone_chosen)  # coordinated universal time
        zones.add_radiobutton(label=f"Local time ({local_zone_name()})", underline=0, value="local", variable=self.time_zone_var, command=self.time_zone_chosen)  # this computer's time zone
        view.add_cascade(label="Scope time marks in", underline=6, menu=zones)  # put it in the View menu
        signals = tk.Menu(view, tearoff=False)  # the Recognized signals submenu (since 0.37)
        sv = self.signal_vars()  # the shared on/off choices
        signals.add_checkbutton(label="Highlight them on the receive scope", underline=0, variable=sv["scope"], command=self.signal_choice_changed)  # shaded bands with the mode named, on the trace
        signals.add_checkbutton(label="Label them on the waterfall", underline=0, variable=sv["fall"], command=self.signal_choice_changed)  # names at the top of the waterfall
        signals.add_separator()  # a divider
        for kind in signalwatch.TYPES:  # each mode
            signals.add_checkbutton(label=kind, variable=sv[kind], command=self.signal_choice_changed)  # shown or not
        signals.add_separator()  # a divider
        signals.add_command(label="Show every mode", underline=5, command=lambda: self.set_all_signal_types(True))  # all on
        signals.add_command(label="Hide every mode", underline=0, command=lambda: self.set_all_signal_types(False))  # all off
        signals.add_command(label="Signals detected list...", underline=8, accelerator="Ctrl+D", command=self.signals_window)  # the list
        view.add_cascade(label="Recognized signals", underline=0, menu=signals)  # put it in the View menu
        self.strip_var = tk.BooleanVar(value=bool(self.settings.get("frame_strip", True)))  # the frame strip shown or not (since 0.37)
        view.add_checkbutton(label="Frame strip under the receive scope", underline=1, variable=self.strip_var, command=self.frame_strip_toggled)  # a Kestrel frame as it arrives: preamble, header, body, header again, and its message's parts
        self.view_menu = view  # kept, so Settings can grey the Activity window item (since 0.42R2)
        view.add_command(label="Activity window", underline=0, accelerator="Ctrl+Shift+A", command=lambda: self.toggle_activity())  # the running log, in its own window (since 0.41)
        view.add_command(label="Chat window", underline=1, accelerator="Ctrl+Shift+C", command=lambda: self.toggle_chat())  # the conversation with the partner (since 0.42)
        view.add_checkbutton(label="Technical details in the log", underline=0, variable=self.details, command=self.redraw_log)  # plain or detailed log
        view.add_command(label="Reset the panel sizes", underline=0, command=self.default_layout)  # the window and its dividers back to their usual places
        view.add_command(label="Go to the level sliders", underline=6, accelerator="Ctrl+J", command=lambda: self.rx_slider.focus_set())  # the receive and transmit levels
        bar.add_cascade(label="View", underline=0, menu=view)  # put the menu on the bar
        settings = tk.Menu(bar, tearoff=False)  # the Settings menu
        for tab, words, key in ((0, "Station...", 0), (1, "Radio and rig control...", 0), (2, "Audio...", 0), (3, "Operating (start-up, beacon)...", 0), (4, "Logging...", 0), (5, "Quick messages...", 0), (6, "Appearance...", 1), (7, "Contacts...", 0), (8, "Updates...", 0)):  # one item per tab of the Settings window
            settings.add_command(label=words, underline=key, accelerator="F12" if tab == 0 else "", command=lambda t=tab: self.settings_window(t))  # open Settings at that tab
        bar.add_cascade(label="Settings", underline=0, menu=settings)  # put the menu on the bar
        help_menu = tk.Menu(bar, tearoff=False)  # the Help menu
        help_menu.add_command(label="Keyboard shortcuts", underline=0, accelerator="F1", command=self.shortcuts_window)  # every key
        help_menu.add_command(label="Reading the scopes", underline=0, command=lambda: messagebox.showinfo("Kestrel - the scopes", SCOPE_HELP, parent=self.root))  # what the two scopes show, and how to zoom and resize
        help_menu.add_command(label="Check for updates", underline=0, command=lambda: self.begin_update_check(manual=True))  # ask GitHub now (since 0.42)
        help_menu.add_command(label="About Kestrel", underline=0, command=lambda: messagebox.showinfo("About Kestrel", about_text(), parent=self.root))  # what this is, which version, and who began it
        bar.add_cascade(label="Help", underline=0, menu=help_menu)  # put the menu on the bar
        self.root.configure(menu=bar)  # give the window its menu bar

    def _shortcuts(self):  # tie the keys to their jobs
        keys = {"<F1>": self.shortcuts_window, "<F2>": lambda: self.set_mode("listen"), "<F3>": lambda: self.set_mode("monitor"), "<F4>": lambda: self.set_mode("off"),  # (continued)
                "<F5>": self.beacon_key, "<F6>": self.call_to, "<F7>": self.end_contact, "<F8>": self.heard_window, "<F9>": self.telemetry_window, "<F10>": self.mail_window,  # (continued: F10 also stops Windows' usual jump to the menu bar)
                "<F11>": self.broadcast_message, "<F12>": lambda: self.settings_window(0), "<Control-l>": lambda: self.to.focus_set(), "<Control-m>": lambda: self.message.focus_set(),  # (continued)
                "<Control-Key-1>": lambda: self.use_quick(1), "<Control-Key-2>": lambda: self.use_quick(2), "<Control-Key-3>": lambda: self.use_quick(3),  # (continued: the first three, as before 0.30)
                **{f"<Alt-Key-{number % 10}>": (lambda n=number: self.use_quick(n)) for number in range(1, QUICK_MOST + 1)},  # (continued: Alt+1 to Alt+9 and Alt+0, quick messages 1 to 10)
                "<Control-Key-4>": self.send_telemetry, "<Control-Key-5>": self.broadcast_telemetry, "<Control-r>": lambda: self.frequency.focus_set(),  # (continued)
                "<Control-Up>": lambda: self.step_frequency(-1), "<Control-Down>": lambda: self.step_frequency(1), "<Control-g>": self.focus_stations, "<Control-j>": lambda: self.rx_slider.focus_set(), "<Control-y>": self.respond, "<Control-u>": self.available_key, "<Control-p>": self.propagation_window, "<Control-k>": self.contacts_window, "<Control-t>": self.toggle_time_marks, "<Control-n>": self.long_note_message, "<Control-d>": self.signals_window, "<Escape>": self.stop_calling, "<Control-Shift-A>": self.toggle_activity, "<Control-Shift-a>": self.toggle_activity, "<Control-Shift-C>": self.toggle_chat, "<Control-Shift-c>": self.toggle_chat}  # every shortcut (Ctrl+Shift+A for the Activity window since 0.41)
        for key, job in keys.items():  # each one
            self.root.bind(key, lambda event, j=job: (j(), "break")[1])  # on the main window: do the job, and stop the key going any further

    def _list(self, parent, column, title, columns):  # a titled list with named columns
        if isinstance(parent, ttk.Notebook):  # a tab of the lists card (since 0.41)
            frame = ttk.Frame(parent)  # the tab's page
            parent.add(frame, text=title)  # its tab, titled
        else:  # a panel of its own
            frame = ttk.LabelFrame(parent, text=title)  # the box around the list
            parent.add(frame, weight=1)  # one of the panels in its row, with a divider to drag on either side
        frame.columnconfigure(0, weight=1)  # the list takes the width
        frame.rowconfigure(0, weight=1)  # and the height
        table = ttk.Treeview(frame, columns=[name for name, _, _ in columns], show="headings", height=2)  # the list itself; it asks for two rows and takes whatever height its panel is given
        for name, heading, width in columns:  # each column
            table.heading(name, text=heading, anchor="w", command=lambda n=name, t=table: self.sort_table(t, n))  # its heading; a click sorts by it, again to reverse (since 0.38R2)
            table.column(name, width=max(22, int(width * 0.6)), minwidth=20, anchor="w", stretch=(name != "saved"))  # a modest width to ask for; every column but the star stretches with the panel
        table.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)  # place the list
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)  # a scroll bar for it
        scroll.grid(row=0, column=1, sticky="ns")  # place it beside the list
        table.configure(yscrollcommand=scroll.set)  # tie the two together
        return table  # so rows can be added later

    # ---- the Activity window, the message box and the frequency's details (since 0.41) ----

    def _activity_window(self):  # the running log, in a window of its own
        self.activity = tk.Toplevel(self.root)  # the window
        self.activity.title("Kestrel - Activity")  # its title
        self.activity.withdraw()  # hidden until asked for (or a warning, or the setting, opens it)
        self.activity.protocol("WM_DELETE_WINDOW", self.hide_activity)  # its close box hides it; the log goes on filling
        self.activity.geometry(self.settings.get("activity_geometry") or "640x420")  # its size and place, as last left
        self.activity.columnconfigure(0, weight=1)  # the log takes the width
        self.activity.rowconfigure(1, weight=1)  # and the spare height
        ttk.Checkbutton(self.activity, text="Show technical details", variable=self.details, command=self.redraw_log).grid(row=0, column=0, sticky="w", padx=6, pady=(6, 0))  # the switch between the plain and the detailed log
        self.log = tk.Text(self.activity, height=12, width=60, font="TkFixedFont", state="disabled", relief="flat", borderwidth=0, wrap="word")  # the running log (whole words wrap, since 0.41)
        self.log.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)  # place it
        self.log_menu = tk.Menu(self.root, tearoff=False)  # the menu a right click on the log brings up
        self.log_menu.add_command(label="Select all", accelerator="Ctrl+A", command=self.select_all_log)  # the whole log
        self.log_menu.add_command(label="Copy", accelerator="Ctrl+C", command=self.copy_log)  # the selection (or the whole log) to the clipboard
        self.log_menu.add_command(label="Clear", command=self.clear_log)  # empty the log
        self.log.bind("<Button-3>", lambda event: (self.log.focus_set(), self.popup(self.log_menu, event)))  # a right click anywhere on the log
        self.log.bind("<Button-1>", lambda event: self.log.focus_set(), add="+")  # a click gives the log the keyboard, so Ctrl+A and Ctrl+C work on it
        self.log.bind("<Control-a>", lambda event: (self.select_all_log(), "break")[1])  # Ctrl+A in the log
        self.log.bind("<Control-c>", lambda event: (self.copy_log(), "break")[1])  # Ctrl+C in the log
        scroll = ttk.Scrollbar(self.activity, orient="vertical", command=self.log.yview)  # a scroll bar for the log
        scroll.grid(row=1, column=1, sticky="ns")  # place it beside the log
        self.log.configure(yscrollcommand=scroll.set)  # tie the two together
        self.activity_on = None  # whether the Activity window is turned on, as last applied (since 0.42R2)
        self.root.after(800, self.apply_activity_setting)  # once the main window is up: minimized in the background, or off

    def _chat_window(self):  # the Chat window, built the first time it is asked for (since 0.42)
        """A conversation with the partner: both sides' messages as a running exchange, and a line to type the next one."""
        self.chat = tk.Toplevel(self.root)  # the window
        self.chat.title("Kestrel - Chat")  # its title
        self.chat.protocol("WM_DELETE_WINDOW", self.hide_chat)  # its close box hides it; the conversation goes on filling
        self.chat.geometry(self.settings.get("chat_geometry") or "560x420")  # its size and place, as last left
        self.chat.columnconfigure(0, weight=1)  # the conversation takes the width
        self.chat.rowconfigure(1, weight=1)  # and the spare height
        self.chat_state = ttk.Label(self.chat, text="No contact.", font="KestrelSmall", anchor="w")  # who, whose turn, speed and signal
        self.chat_state.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))  # across the top
        self.chat_text = tk.Text(self.chat, height=14, width=60, state="disabled", relief="flat", borderwidth=0, wrap="word", font="TkTextFont")  # the conversation
        self.chat_text.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)  # place it
        scroll = ttk.Scrollbar(self.chat, orient="vertical", command=self.chat_text.yview)  # a scroll bar
        scroll.grid(row=1, column=1, sticky="ns")  # beside it
        self.chat_text.configure(yscrollcommand=scroll.set)  # tied together
        self.chat_text.tag_configure("when", font="KestrelSmall")  # the time of each line, small
        self.chat_text.tag_configure("me", font="KestrelSmallBold")  # this station's name on its lines
        self.chat_text.tag_configure("them", font="KestrelSmallBold")  # the partner's name on its lines
        row = ttk.Frame(self.chat)  # the typing line
        row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))  # at the bottom
        row.columnconfigure(0, weight=1)  # the entry takes the width
        self.chat_entry = ttk.Entry(row)  # the next line to send
        self.chat_entry.grid(row=0, column=0, sticky="ew")  # place it
        self.chat_entry.bind("<Return>", lambda event: self.chat_send())  # Enter sends it
        self.chat_entry.bind("<KeyRelease>", lambda event: self.chat_count(), add="+")  # the countdown follows the typing
        self.chat_left = ttk.Label(row, text=f"{chain.PIECE_MOST}", font="KestrelSmall", width=4, anchor="e")  # characters left in this line
        self.chat_left.grid(row=0, column=1, padx=(4, 4))  # beside the entry
        ttk.Button(row, text="Send", command=self.chat_send).grid(row=0, column=2)  # the same as Enter
        self.chat_marks = {}  # message text -> the mark after its line, for the delivered tick
        self.color_plain_widgets()  # in the chosen look
        self.chat_follow()  # keep the line at the top up to date

    def show_chat(self):  # open the Chat window
        if getattr(self, "chat", None) is None:  # never opened
            self._chat_window()  # build it
        self.chat.deiconify()  # shown
        self.chat.lift()  # in front
        self.chat_text.see("end")  # at the newest line
        self.chat_entry.focus_set()  # ready to type

    def hide_chat(self):  # close the Chat window (the conversation keeps filling)
        try:  # the window may be closing
            self.settings["chat_geometry"] = self.chat.geometry()  # its size and place, for next time
        except tk.TclError:  # gone
            pass  # nothing to keep
        self.chat.withdraw()  # hidden

    def toggle_chat(self):  # the Chat button, and View > Chat window
        if getattr(self, "chat", None) is not None and self.chat.state() == "normal":  # showing
            self.hide_chat()  # hide it
        else:  # hidden, or never opened
            self.show_chat()  # show it

    def chat_count(self):  # the characters left in the chat line
        left = chain.PIECE_MOST - len(self.chat_entry.get())  # what is left of one message
        if left < 0:  # too long
            self.chat_entry.delete(chain.PIECE_MOST, "end")  # a chat line is one message at most
            left = 0  # none left
        self.chat_left.configure(text=str(left))  # shown

    def chat_send(self):  # Enter in the chat line
        """Send the typed line to the partner, as an ordinary message: nothing goes until Enter or Send."""
        text = self.chat_entry.get().strip()  # what was typed
        if not text:  # nothing
            return  # nothing to send
        station = self.station  # the running station
        partner = station.partner if station is not None and station.state in LOCKED else ""  # the station in contact, if any
        to = partner or self.to.get().strip().upper()  # the partner, or the station in the main window's To box
        if not to or to == "ALL":  # nobody to send to
            messagebox.showinfo("Kestrel", "Chat sends to the station you are in contact with. Make a contact first (or put a callsign in To in the main window).", parent=self.chat)  # say so
            return  # nothing sent
        if self.queue_text(text, to):  # queued like any message
            self.chat_used = True  # replies now open the Chat window by themselves
            self.chat_entry.delete(0, "end")  # the line is cleared
            self.chat_count()  # the countdown starts again
            self.chat_line(self.settings["call"].strip().upper() or "me", text, mine=True)  # shown in the conversation

    def chat_line(self, who, text, mine):  # add one line to the conversation (since 0.42)
        """Add `text` from `who` to the Chat window; this station's own lines get a tick once delivered."""
        if getattr(self, "chat", None) is None:  # never opened
            self._chat_window()  # build it (hidden), so nothing said is missed
            self.chat.withdraw()  # and keep it hidden until asked for
        box = self.chat_text  # the conversation
        box.configure(state="normal")  # writable for a moment
        box.insert("end", time.strftime("%H:%M  "), "when")  # the time
        box.insert("end", f"{who}: ", "me" if mine else "them")  # who said it
        box.insert("end", text)  # what was said
        if mine:  # this station's own line
            name = f"chat{len(self.chat_marks)}"  # a mark of its own
            box.mark_set(name, "end-1c")  # just after the text, where the tick will go
            box.mark_gravity(name, "left")  # text added later goes after it
            self.chat_marks.setdefault(text, []).append(name)  # remembered by the message's text
        box.insert("end", "\n")  # the end of the line
        box.configure(state="disabled")  # read only again
        box.see("end")  # the newest line in view
        if not mine and self.chat.state() != "normal" and getattr(self, "chat_used", False):  # a reply, with the window closed, after the operator has chatted
            self.show_chat()  # it opens by itself, as a conversation should (never for operators who do not use Chat)

    def chat_delivered(self, text):  # the partner has acknowledged one of this station's messages (since 0.42)
        marks = getattr(self, "chat_marks", {}).get(text) or []  # its line in the conversation, if it was typed there
        if not marks:  # it was not
            return  # nothing to mark
        box = self.chat_text  # the conversation
        box.configure(state="normal")  # writable for a moment
        box.insert(marks.pop(0), "  \u2713")  # a tick after the oldest unmarked copy
        box.configure(state="disabled")  # read only again

    def chat_follow(self):  # the line at the top of the Chat window, once a second (since 0.42)
        station = self.station  # the running station
        if station is not None and station.state in LOCKED and station.partner:  # in a contact
            report = getattr(self, "their_report", None)  # the partner's report of this station
            heard = f", they hear you {report[2]:+.0f} dB" if report is not None and report[1] == station.partner else ""  # how the partner hears this station
            turn = "sending" if getattr(self, "tx_active", False) else ("your messages are going" if station.outbox else "ready")  # what is happening
            where = "working channel" if station.offset_hz else "calling frequency"  # where the contact is
            words = f"In contact with {station.partner} on the {where}  \u00b7  L{station.tx_level}{heard}  \u00b7  {turn}"  # the line
        else:  # no contact
            words = "No contact. Lines you send wait for a contact with the station in To."  # say so
        try:  # the window may have been closed with Kestrel
            self.chat_state.configure(text=words)  # shown
            self.chat.after(1000, self.chat_follow)  # again in a second
        except tk.TclError:  # gone
            pass  # stop

    def show_activity(self):  # open the Activity window
        self.activity.deiconify()  # shown
        self.activity.lift()  # in front
        self.log.see("end")  # at the newest line

    def hide_activity(self):  # close the Activity window (the log keeps filling)
        try:  # the window may be closing
            self.settings["activity_geometry"] = self.activity.geometry()  # its size and place, for next time
        except tk.TclError:  # gone
            pass  # nothing to keep
        if self.settings.get("activity_window"):  # turned on: it goes back to the background (since 0.42R2)
            self.activity.iconify()  # minimized
        else:  # turned off
            self.activity.withdraw()  # hidden

    def apply_activity_setting(self):  # Settings > Operating > Activity window, on or off (since 0.42R2)
        """On: the window exists minimized, in the background, and opens only when asked. Off: no window, and its button and menu item are greyed."""
        wanted = bool(self.settings.get("activity_window"))  # the setting
        if wanted == self.activity_on:  # nothing changed
            return  # leave the window as the operator has it
        self.activity_on = wanted  # applied
        try:  # the window may be closing
            if wanted:  # on
                self.activity.deiconify()  # it must exist on the taskbar before it can be minimized
                self.activity.iconify()  # minimized, in the background
            else:  # off
                self.activity.withdraw()  # no window
            self.activity_button.state(["!disabled"] if wanted else ["disabled"])  # the Activity button follows
            self.view_menu.entryconfigure("Activity window", state="normal" if wanted else "disabled")  # and so does View > Activity window
        except (tk.TclError, AttributeError):  # gone, or not built yet
            pass  # nothing to change

    def toggle_activity(self):  # the Activity button, and View > Activity window
        if not self.settings.get("activity_window"):  # turned off in Settings (since 0.42R2)
            return  # nothing to show
        if self.activity.state() == "normal":  # showing
            self.hide_activity()  # hide it
        else:  # hidden
            self.show_activity()  # show it

    def update_frequency_tip(self):  # the frequency list's hover help: the chosen frequency in full
        try:  # the list may be empty
            self.frequency_tip.text = describe_frequency(self.selected())  # band, dial, mode, where the signal sits, whether an unattended station may use it, and the note
        except (IndexError, KeyError):  # nothing chosen
            self.frequency_tip.text = ""  # nothing to say

    def send_typed(self):  # Send, or Enter in the message box
        """Send what was typed as the As choice says: a long note, or a normal message (a broadcast when To is ALL)."""
        if self.send_as.get() == SEND_AS[1]:  # a long note chosen
            self.long_note_message()  # asks first, then queues it
        else:  # a normal message (queue_text turns ALL into a broadcast)
            self.queue_message()  # queued for the contact
        self.count_message()  # the countdown starts again

    def count_message(self):  # the character countdown under the message box
        text = self.message.get()  # what is typed
        if len(text) > MESSAGE_MOST:  # more than the box takes
            self.message.delete(f"1.0+{MESSAGE_MOST}c", "end")  # cut to the limit
            text = text[:MESSAGE_MOST]  # what is left
        if self.send_as.get() == SEND_AS[1]:  # a long note
            words = f"{LONG_NOTE_CHARS - len(text.rstrip())} of {LONG_NOTE_CHARS} characters left in a long note"  # its own limit
        else:  # a normal message
            parts = len(chain.split(text)) if chain.needs_chain(text.strip()) else 1  # messages it takes: one, or the pieces of a chained message (since 0.42)
            words = f"{MESSAGE_MOST - len(text)} characters left  -  " + (f"{parts} parts (working channel)" if parts > 1 else "1 message")  # what is left, and how it goes
        self.count_label.configure(text=words, foreground=self.colors["warn_fg"] if self.send_as.get() == SEND_AS[1] and len(text.rstrip()) > LONG_NOTE_CHARS else "")  # in the warning color when a long note is too long

    # ---- the scopes ----

    def _scope(self, parent):  # the two scopes: transmit on top, receive below, each a spectrum trace above a waterfall; both take the size of their panels
        self.scope_w, self.trace_h, self.fall_h, self.low_hz, self.top_hz = 420, 60, 50, 0.0, 3000.0  # the receive scope's width in points, the heights of its trace and waterfall, and the lowest and highest frequencies shown
        self.tx_w, self.tx_top, self.tx_trace_h, self.tx_fall_h = 420, 14, 30, 16  # the transmit scope's width, where its trace begins (under a line of words), and the heights of its trace and waterfall
        self.left, self.right, self.above, self.below = 40, 40, 16, 18  # margins for the scales: dB on the left, seconds on the right, radio kHz above, audio Hz below
        self.palettes = {}  # each waterfall's 256 colors ("rx" or "tx" -> array), made from the color set and that scope's Color slider
        self.fall = np.zeros((self.fall_h, self.scope_w, 3), dtype="uint8")  # the receive waterfall picture, newest line at the top
        self.tx_fall = np.zeros((self.tx_fall_h, self.tx_w, 3), dtype="uint8")  # the transmit waterfall picture
        self.line_s = 0.10  # seconds between waterfall lines, measured as the scope runs
        self.last_line = None  # when the last waterfall line was drawn
        self.line_count = 0  # waterfall lines drawn so far (both waterfalls move together, a line each, since 0.33)
        self.time_marks = []  # UTC time marks on the waterfalls: (the line count when the mark was made, the UTC second it marks), newest last
        self.mark_slot = None  # the five-second UTC slot the newest line fell in, to notice when a new one begins
        self.scale_khz = None  # the radio frequency the top scale was last drawn for
        self.tx_was = False  # whether a transmission was under way at the last look
        self.scope_db = {}  # each scope's Floor and Range slider settings, as Tk variables: ("rx" or "tx", "floor" or "range") -> DoubleVar
        for which in ("rx", "tx"):  # the receive and transmit scopes
            for part in ("floor", "range", "color"):  # the bottom of the picture, how many dB it covers, and where the waterfall's colors change
                self.scope_db[which, part] = tk.DoubleVar(value=float(self.settings.get(f"scope_{which}_{part}", DEFAULTS[f"scope_{which}_{part}"])))  # as last left
        self.panes["scopes"] = scopes = ttk.PanedWindow(parent, orient="vertical")  # the two scopes, one above the other, with a divider to drag between them
        parent.add(scopes, weight=3)  # between the log and the meters
        tx_frame = ttk.LabelFrame(scopes, text="Transmit  -  audio sent to the radio")  # the box around the transmit scope
        scopes.add(tx_frame, weight=1)  # on top
        tx_frame.columnconfigure(0, weight=1)  # its picture takes the width
        tx_frame.rowconfigure(0, weight=1)  # and the height
        self.tx_canvas = tk.Canvas(tx_frame, width=self.left + self.tx_w + self.right, height=self.tx_top + self.tx_trace_h + self.tx_fall_h + self.below, bg=self.colors["scope_bg"], highlightthickness=0)  # its drawing area
        self.tx_canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)  # filling the box
        self._scope_sliders(tx_frame, "tx").grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=2)  # its Floor and Range sliders, to the right
        self.tx_image = tk.PhotoImage(width=self.tx_w, height=self.tx_fall_h)  # its waterfall as a picture
        self.tx_item = self.tx_canvas.create_image(self.left, self.tx_top + self.tx_trace_h, anchor="nw", image=self.tx_image)  # shown under the trace
        self.tx_line = self.tx_canvas.create_line(0, 0, 0, 0, fill=self.colors["tx_trace"])  # its trace, placed when the scales are drawn
        self.tx_words = self.tx_canvas.create_text(self.left, 7, anchor="w", text="nothing sent yet", fill=self.colors["tx_words"], font="KestrelSmall")  # what is being sent, or what the picture is of
        frame = ttk.LabelFrame(scopes, text="Receive  -  audio from the radio")  # the box around the receive scope
        scopes.add(frame, weight=3)  # underneath, with most of the height
        frame.columnconfigure(0, weight=1)  # its picture takes the width
        frame.rowconfigure(0, weight=1)  # and the height
        self.scope = tk.Canvas(frame, width=self.left + self.scope_w + self.right, height=self.above + self.trace_h + self.fall_h + self.below, bg=self.colors["scope_bg"], highlightthickness=0)  # its drawing area
        self.scope.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 0))  # filling the box
        self._scope_sliders(frame, "rx").grid(row=0, column=1, rowspan=2, sticky="ns", padx=(0, 4), pady=2)  # its Floor and Range sliders, to the right
        self.fall_image = tk.PhotoImage(width=self.scope_w, height=self.fall_h)  # its waterfall as a picture
        self.fall_item = self.scope.create_image(self.left, self.above + self.trace_h, anchor="nw", image=self.fall_image)  # shown under the trace
        self.trace = self.scope.create_line(0, 0, 0, 0, fill=self.colors["rx_trace"])  # its trace, placed when the scales are drawn
        self.scope.bind("<Button-1>", self.scope_click)  # a click centers the view there, zooming in on a labeled signal
        self.scope.bind("<Button-3>", self.scope_menu_at)  # a right click shows the scope's menu: the signal under the pointer, the modes shown, and Full view (since 0.37)
        self.scope.bind("<MouseWheel>", self.scope_wheel)  # the wheel zooms in and out about the pointer
        controls = ttk.Frame(frame)  # a row of zoom controls under the picture
        controls.grid(row=1, column=0, sticky="w", padx=4, pady=2)  # place it
        self.strip_canvas = tk.Canvas(frame, height=96, bg=self.colors["bg"], highlightthickness=0)  # the frame strip: a Kestrel frame as it arrives (since 0.37)
        self.strip_canvas.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))  # under the scope's controls
        if not self.settings.get("frame_strip", True):  # hidden by the operator
            self.strip_canvas.grid_remove()  # out of the way (its place is remembered)
        ttk.Label(controls, text="View:").grid(row=0, column=0)  # its label
        self.view_choice = tk.StringVar(value="Full (0-3000 Hz)")  # the width chosen
        self.view_box = ttk.Combobox(controls, textvariable=self.view_choice, values=list(VIEW_WIDTHS), state="readonly", width=15)  # the widths offered
        self.view_box.grid(row=0, column=1, padx=(4, 6))  # place it
        self.view_box.bind("<<ComboboxSelected>>", lambda event: self.set_view((self.low_hz + self.top_hz) / 2, VIEW_WIDTHS[self.view_choice.get()]))  # choosing a width keeps the center
        ttk.Button(controls, text="Center on last signal", command=self.center_on_last).grid(row=0, column=2)  # zoom in on the station decoded most recently
        ttk.Button(controls, text="Full view", command=lambda: self.set_view(1500.0, 3000.0)).grid(row=0, column=3, padx=(4, 6))  # back to everything
        self.view_note = ttk.Label(controls, text="click a signal to zoom", font="KestrelSmall")  # a word on what the view shows
        self.view_note.grid(row=0, column=4)  # place it
        self.draw_scales()  # the scales of both scopes, at their starting sizes
        self.tx_canvas.bind("<Configure>", self.tx_resized)  # the transmit scope follows the size of its panel
        self.scope.bind("<Configure>", self.scope_resized)  # and so does the receive scope

    def _scope_sliders(self, parent, which):  # the Floor and Range sliders of one scope ("rx" or "tx")
        """Return a frame holding three vertical sliders: Floor sets the level at the bottom of the trace and the black of the waterfall; Range sets how many dB lie between that and the top; Color shifts where the waterfall's colors change (since 0.31R4)."""
        box = ttk.Frame(parent)  # the three sliders side by side
        box.rowconfigure(1, weight=1)  # the sliders take the height
        words = {"floor": ("Floor", "Raise it to hide more noise (blacker waterfall); lower it to see weaker signals.\nDouble-click to reset."),  # what each slider is for
                 "range": ("Range", "Fewer dB: more contrast, weak signals stand out; more dB: strong signals are not flattened.\nDouble-click to reset."),  # (continued)
                 "color": ("Color", "Up: weaker signals reach the bright colors; down: only strong ones do. The colors themselves: View > Waterfall colors.\nDouble-click to reset.")}  # (continued)
        for column, part in enumerate(("floor", "range", "color")):  # the three sliders
            low, high = SCOPE_LIMITS[which][column]  # its ends
            ttk.Label(box, text=words[part][0], font="KestrelTiny").grid(row=0, column=column)  # its name above it
            slider = ttk.Scale(box, orient="vertical", from_=high, to=low, length=40, variable=self.scope_db[which, part], command=lambda value: self.scope_db_moved())  # up is a higher floor, or a wider range
            slider.grid(row=1, column=column, sticky="ns", padx=1)  # stretched to the scope's height
            slider.bind("<ButtonRelease-1>", lambda event: self.save_settings())  # remember the setting when the mouse lets go
            slider.bind("<Double-Button-1>", lambda event, which=which, part=part: self.reset_scope_db(which, part))  # a double click puts it back
            value = ttk.Label(box, text="", font="KestrelTiny", width=4, anchor="center")  # its setting in dB, under it
            value.grid(row=2, column=column)  # place it
            setattr(self, f"scope_{which}_{part}_text", value)  # kept so it can be updated
        self.scope_db_moved(redraw=False)  # show the starting values
        return box  # for the caller to place

    def scope_db_moved(self, redraw=True):  # a Floor, Range or Color slider has moved
        for (which, part), var in self.scope_db.items():  # every slider
            value = round(var.get())  # whole dB (or whole steps, for Color)
            self.settings[f"scope_{which}_{part}"] = float(value)  # remembered with the other settings
            label = getattr(self, f"scope_{which}_{part}_text", None)  # its value label, once made
            if label is not None:  # made already
                label.configure(text=f"{value:+d}" if part == "floor" else f"{value}")  # the floor with its sign, the range and color as plain numbers
        self.make_palettes()  # each waterfall's colors, for its Color slider and the color set chosen
        if redraw:  # the sliders exist and the scales need to follow
            self.draw_scales()  # new dB marks on both scopes

    def make_palettes(self):  # (re)make both waterfalls' colors
        """Make the 256 colors of each waterfall from the color set chosen in View > Waterfall colors and that scope's Color slider."""
        name = self.palette_var.get()  # the color set chosen
        if name == THEME_OWN:  # the theme decides (since 0.37)
            name = self.colors.get("waterfall", "Classic")  # the theme's own set
        for which in ("rx", "tx"):  # the receive and transmit waterfalls
            self.palettes[which] = make_palette(name, self.scope_db[which, "color"].get())  # its colors

    def palette_chosen(self):  # View > Waterfall colors: a color set was picked
        """Use the color set just chosen on both waterfalls, remember it, and recolor what is already on show."""
        self.settings["scope_palette"] = self.palette_var.get()  # remembered with the other settings
        self.make_palettes()  # the new colors
        self.fall[:] = self.palettes["rx"][0]  # the receive waterfall starts afresh in the new "nothing there" color, so old lines in the old colors do not linger
        self.tx_fall[:] = self.palettes["tx"][0]  # and so does the transmit waterfall
        self.save_settings()  # keep the choice

    def reset_scope_db(self, which, part):  # a double click on a slider
        self.scope_db[which, part].set(DEFAULTS[f"scope_{which}_{part}"])  # back to the usual setting
        self.scope_db_moved()  # show it
        self.save_settings()  # and remember it
        return "break"  # the slider itself does nothing more with the click

    def scope_resized(self, event):  # the receive scope's panel has changed size
        width, room = max(120, event.width - self.left - self.right), max(40, event.height - self.above - self.below)  # the points across, and the height for the trace and the waterfall together
        trace = int(min(140, max(30, 0.4 * room)))  # the trace takes two fifths of it, within limits
        if (width, trace, room - trace) == (self.scope_w, self.trace_h, self.fall_h):  # nothing has changed
            return  # leave the picture alone
        self.scope_w, self.trace_h, self.fall_h = width, trace, max(8, room - trace)  # the new sizes
        self.fall = np.full((self.fall_h, self.scope_w, 3), self.palettes["rx"][0], dtype="uint8")  # a fresh waterfall of that size, in the "nothing there" color
        self.scale_khz = None  # the radio-frequency labels must be redrawn
        self.draw_scales()  # and the scales

    def tx_resized(self, event):  # the transmit scope's panel has changed size
        width, room = max(120, event.width - self.left - self.right), max(24, event.height - self.tx_top - self.below)  # the points across, and the height for the trace and the waterfall together
        trace = int(min(90, max(18, 0.6 * room)))  # the trace takes three fifths of it, within limits
        if (width, trace, room - trace) == (self.tx_w, self.tx_trace_h, self.tx_fall_h):  # nothing has changed
            return  # leave the picture alone
        self.tx_w, self.tx_trace_h, self.tx_fall_h = width, trace, max(4, room - trace)  # the new sizes
        self.tx_fall = np.full((self.tx_fall_h, self.tx_w, 3), self.palettes["tx"][0], dtype="uint8")  # a fresh waterfall of that size, in the "nothing there" color
        self.draw_scales()  # and the scales

    def tx_y(self, db):  # where a level in dB below full scale falls on the transmit trace
        floor, span = self.scope_db["tx", "floor"].get(), self.scope_db["tx", "range"].get()  # the Floor and Range sliders
        return self.tx_top + self.tx_trace_h - 2 - (db - floor) / span * (self.tx_trace_h - 4)  # the floor at the bottom, floor plus range at the top

    def draw_scales(self):  # draw the fixed parts of both scopes for their present sizes and the view now shown
        span = self.top_hz - self.low_hz  # the width of the view
        step = next(size for size in (10, 20, 50, 100, 200, 500) if span / size <= 8 or size == 500)  # the spacing that gives at most eight frequency marks
        marks = sorted({step * n for n in range(int(np.ceil(self.low_hz / step)), int(self.top_hz // step) + 1)} | {hz for hz in (500, 2500) if self.low_hz <= hz <= self.top_hz})  # a mark at every step, and at the two edges of the Kestrel band
        gray, faint = self.colors["scale"], self.colors["scale_faint"]  # scale colors, from the theme
        for canvas, width, top, bottom in ((self.tx_canvas, self.tx_w, self.tx_top, self.tx_top + self.tx_trace_h + self.tx_fall_h), (self.scope, self.scope_w, self.above, self.above + self.trace_h + self.fall_h)):  # the transmit scope, then the receive scope
            canvas.delete("scale")  # remove the old scales
            for index, hz in enumerate(marks):  # each frequency mark
                x = self.x_for(hz, width)  # where it falls across this scope
                edge = hz in (500, 2500)  # the two edges of the Kestrel band
                canvas.create_line(x, top, x, bottom, fill=self.colors["edge"] if edge else faint, dash=(4, 3) if edge else (1, 4), tags="scale")  # a dashed line for an edge, a faint dotted one otherwise
                if width >= 46 * len(marks) or index % 2 == 0:  # room for every label, or else every other one
                    canvas.create_text(x, bottom + self.below / 2, text=str(hz), fill=gray, font="KestrelTiny", tags="scale")  # its audio frequency underneath
            canvas.create_text(self.left + width + self.right / 2, bottom + self.below / 2, text="Hz", fill=gray, font="KestrelTiny", tags="scale")  # the unit of the frequency scale
        for which, canvas, y_of, height, name in (("tx", self.tx_canvas, self.tx_y, self.tx_trace_h, "dB below full scale"), ("rx", self.scope, self.y_for, self.trace_h, "dB above the noise")):  # the dB marks up each trace
            floor, span = self.scope_db[which, "floor"].get(), self.scope_db[which, "range"].get()  # what the trace covers
            room = max(1, height // 18)  # how many labels fit up the trace
            step = next(size for size in (5, 10, 20, 30, 50) if span / size <= room or size == 50)  # the spacing that fits
            for db in range(int(np.ceil(floor / step)) * step, int(floor + span) + 1, step):  # each mark inside the trace
                y = y_of(db)  # where it falls
                if which == "rx":  # the receive scope also gets a faint line across
                    canvas.create_line(self.left, y, self.left + self.scope_w, y, fill=faint, dash=(1, 4), tags="scale")  # at that level
                canvas.create_text(self.left - 4, y, text=("noise" if which == "rx" and db == 0 else f"{db:+d}" if which == "rx" else str(db)), anchor="e", fill=gray, font="KestrelTiny", tags="scale")  # its value
        self.scope.create_text(self.left / 2, self.above / 2, text="dB", fill=gray, font="KestrelTiny", tags="scale")  # the unit of the left scale, in the top corner
        self.tx_canvas.coords(self.tx_item, self.left, self.tx_top + self.tx_trace_h)  # the transmit waterfall sits under its trace
        self.tx_canvas.coords(self.tx_line, self.left, self.tx_y(-70), self.left + self.tx_w, self.tx_y(-70))  # and its trace lies flat until something is sent
        self.scope.coords(self.fall_item, self.left, self.above + self.trace_h)  # the receive waterfall sits under its trace
        self.scope.coords(self.trace, self.left, self.y_for(0), self.left + self.scope_w, self.y_for(0))  # and its trace lies flat until there is audio
        for canvas, item in ((self.tx_canvas, self.tx_item), (self.scope, self.fall_item)):  # on each scope
            canvas.tag_lower("scale")  # the scales go behind the trace and the labels
            canvas.tag_lower(item)  # and the waterfall behind the scales

    def draw_tx_scope(self, levels, advance):  # redraw the transmit scope (called from draw_scope)
        """Draw the transmit scope. `levels` is the spectrum going out now (None when nothing is being sent); `advance` says the waterfalls move on a line this time.

        Since 0.33 the transmit waterfall moves on whenever the receive waterfall does, with an empty line while nothing is
        being sent, so the two scroll together and a transmission sits at the same height as the receive lines of that moment.
        """
        if levels is None:  # not transmitting
            if self.tx_was:  # a transmission has just ended
                self.tx_was = False  # note it
                self.tx_canvas.itemconfigure(self.tx_words, text=self.tx_canvas.itemcget(self.tx_words, "text").replace("SENDING", "last sent:"), fill=self.colors["scale"])  # labeled as the last transmission
                self.tx_canvas.coords(self.tx_line, self.left, self.tx_y(-70), self.left + self.tx_w, self.tx_y(-70))  # the trace lies flat again
            if not advance:  # the waterfalls are standing still (nothing running)
                return  # nothing new to draw
            row = np.full((self.tx_w, 3), self.palettes["tx"][0], dtype="uint8")  # an empty line, in the "nothing there" color
        else:  # something is going out
            if not self.tx_was:  # a transmission has just begun
                self.tx_was = True  # note it
                dial = self.dial_hz() / 1000.0  # the radio's frequency in kHz
                self.tx_canvas.itemconfigure(self.tx_words, text=f"SENDING {self.tx_kind or 'a frame'} on {dial + 1.5:,.1f} kHz (dial {dial:,.1f} + 1500 Hz)", fill=self.colors["tx_words"])  # what is going out, and where its center lands on the air
            floor, span = self.scope_db["tx", "floor"].get(), self.scope_db["tx", "range"].get()  # the transmit scope's Floor and Range sliders
            bright = np.clip((levels - floor) / span, 0.0, 1.0)  # each point on a scale from the floor (bottom, black) to the floor plus the range (top, red)
            points = np.column_stack((self.left + np.arange(self.tx_w), self.tx_top + self.tx_trace_h - 2 - bright * (self.tx_trace_h - 4))).ravel().tolist()  # the trace's corners
            self.tx_canvas.coords(self.tx_line, *points)  # move the trace
            row = self.palettes["tx"][(bright * 255).astype(int)]  # the newest line, in the transmit waterfall's colors
        self.tx_fall = np.roll(self.tx_fall, 1, axis=0)  # push the waterfall down one line
        self.tx_fall[0] = row  # and paint the newest line at the top
        self.tx_image = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.tx_w, self.tx_fall_h) + self.tx_fall.tobytes(), format="PPM")  # the picture, rebuilt
        self.tx_canvas.itemconfigure(self.tx_item, image=self.tx_image)  # show it

    # ---- time marks on the waterfalls (since 0.33) ----

    def time_marks_chosen(self):  # View > Time marks on the scopes was ticked or cleared
        """Remember the choice and show or hide the marks at once."""
        self.settings["scope_time_marks"] = bool(self.time_marks_var.get())  # remembered with the other settings
        self.save_settings()  # kept
        self.draw_time_marks()  # shown or cleared now, not at the next line

    def time_zone_chosen(self):  # View > Scope time marks in: UTC or local time was picked
        """Remember the choice and relabel the marks at once."""
        self.settings["scope_time_zone"] = self.time_zone_var.get()  # remembered with the other settings
        self.save_settings()  # kept
        self.draw_time_marks()  # relabeled now

    def toggle_time_marks(self):  # Ctrl+T
        self.time_marks_var.set(not self.time_marks_var.get())  # the other way
        self.time_marks_chosen()  # and act on it

    def tick_line(self):  # both waterfalls have just moved on one line
        """Count the line, measure the time between lines, and note a UTC time mark when a new five-second slot begins."""
        now = time.monotonic()  # the time of this line
        if self.last_line is not None:  # not the first line
            self.line_s = 0.9 * self.line_s + 0.1 * min(1.0, now - self.last_line)  # a running average of the time between lines (a pause does not count for more than a second)
        self.last_line = now  # remember it
        self.line_count += 1  # one more line
        utc = time.time()  # the time of day, for the marks
        slot = int(utc // 5)  # which five-second slot of UTC this line is in
        if self.mark_slot is not None and slot != self.mark_slot:  # a new slot began since the last line
            self.time_marks.append((self.line_count, slot * 5))  # mark this line with the slot's first second
        self.mark_slot = slot  # remember the slot
        longest = max(self.fall_h, self.tx_fall_h) + 2  # the most lines either waterfall shows
        self.time_marks = [(line, second) for line, second in self.time_marks if self.line_count - line < longest]  # marks scrolled off the bottom go

    def mark_every(self, lines):  # the spacing of UTC marks that suits a waterfall `lines` lines tall
        """Return the seconds between labeled marks: the shortest of 5, 10, 15, 30 and 60 seconds that puts at most four marks on the waterfall."""
        shown = lines * max(self.line_s, 0.02)  # how many seconds the waterfall covers
        return next((every for every in (5, 10, 15, 30, 60) if shown / every <= 4.0), 60)  # the spacing

    def draw_time_marks(self):  # the UTC marks and the seconds scale on both waterfalls
        """Draw, on each waterfall, a dotted line at each UTC mark with the time (HH:MM:SS UTC) beside it, and the seconds-ago scale to the right; nothing when the marks are turned off."""
        for canvas in (self.scope, self.tx_canvas):  # both scopes
            canvas.delete("time")  # the old marks
        if not self.time_marks_var.get():  # turned off
            return  # nothing to draw
        local = self.time_zone_var.get() == "local"  # local time chosen instead of UTC
        zone = local_zone_name() if local else "UTC"  # the zone's name, shown in the corner
        for canvas, top, height, width in ((self.scope, self.above + self.trace_h, self.fall_h, self.scope_w), (self.tx_canvas, self.tx_top + self.tx_trace_h, self.tx_fall_h, self.tx_w)):  # the receive waterfall, then the transmit one
            every = self.mark_every(height)  # the spacing that suits its height
            for line, second in self.time_marks:  # each mark
                age = self.line_count - line  # how many lines down it is now
                if age >= height or second % every:  # off the bottom, or not one of the marks shown at this spacing
                    continue  # skip it
                y = top + age  # its height on the canvas
                canvas.create_line(self.left, y, self.left + width, y, fill=self.colors["time_line"], dash=(2, 4), tags="time")  # a dotted line across the waterfall
                label = time.strftime("%H:%M:%S", time.localtime(second) if local else time.gmtime(second))  # the time it marks, in the zone chosen
                if height >= 12:  # room for words on this waterfall
                    words = canvas.create_text(self.left + 3, y + 1, text=label, anchor="nw" if age < height - 10 else "sw", fill=self.colors["time_text"], font="KestrelTiny", tags="time")  # the time beside it, kept on the waterfall
                    box = canvas.bbox(words)  # its size
                    canvas.tag_lower(canvas.create_rectangle(box[0] - 1, box[1], box[2] + 1, box[3], fill=self.colors["time_bg"], outline="", tags="time"), words)  # a dark patch behind it, so it reads on any color
            x = self.left + width + 4  # just right of the waterfall
            for seconds in (0, 5, 10, 15, 20, 30, 45, 60):  # the seconds-ago scale
                y = top + seconds / max(self.line_s, 0.02)  # how far down that is
                if y > top + height - 16:  # too near the bottom, where the word UTC goes
                    break  # no more
                if seconds and height < 12:  # a short waterfall
                    continue  # only "now" fits
                canvas.create_text(x, y, text=f"{seconds} s" if seconds else "now", anchor="w", fill=self.colors["scale"], font="KestrelTiny", tags="time")  # label it
            canvas.create_text(self.left + width + self.right / 2, top + height - 1, text=zone, anchor="s", fill=self.colors["scale"], font="KestrelTiny", tags="time")  # what the marks' times are in (UTC, or the local zone as its offset)

    def x_for(self, hz, width=None):  # where an audio frequency falls across a scope `width` points wide (the receive scope unless told otherwise)
        return self.left + (hz - self.low_hz) / (self.top_hz - self.low_hz) * ((self.scope_w if width is None else width) - 1)  # left margin plus the share of the width shown

    def hz_at(self, x):  # the audio frequency at a point across the scope
        return self.low_hz + (x - self.left) / (self.scope_w - 1) * (self.top_hz - self.low_hz)  # the other way round

    def set_view(self, center_hz, span_hz):  # show `span_hz` of the audio band, centered on `center_hz` as nearly as the band allows
        span = float(min(3000.0, max(100.0, span_hz)))  # between 100 Hz and the whole band
        low = min(3000.0 - span, max(0.0, center_hz - span / 2))  # keep the view inside 0 to 3000 Hz
        if (low, low + span) == (self.low_hz, self.top_hz):  # nothing has changed
            return  # leave the picture alone
        self.low_hz, self.top_hz = low, low + span  # the new view
        self.fall[:], self.tx_fall[:] = 0, 0  # the old waterfall lines were on another scale, so start again
        self.scale_khz = None  # the radio-frequency labels must be redrawn
        self.draw_scales()  # and the frequency marks
        name = next((name for name, width in VIEW_WIDTHS.items() if width == span), f"{span:.0f} Hz wide")  # the name of this width
        self.view_choice.set(name)  # shown in the box
        self.view_note.configure(text="full view" if span >= 3000.0 else f"{low:.0f} to {low + span:.0f} Hz" + ("  -  fine detail, about a second behind" if span <= 600.0 else ""))  # say what is shown

    def fit_span(self, width_hz):  # the view width that suits a signal of this width
        return next((span for span in (200.0, 500.0, 1000.0, 2000.0) if span >= 1.25 * width_hz), 3000.0)  # the narrowest that leaves a little room either side

    def scope_click(self, event):  # a click on the receive scope
        hz = self.hz_at(event.x)  # the frequency clicked
        for call, (at, width, when) in self.marks.items():  # each labeled station
            if abs(hz - at) <= width / 2:  # the click is on its signal
                self.set_view(at, self.fit_span(width))  # center on it, at a width that suits it
                return  # done
        self.set_view(hz, 500.0 if self.top_hz - self.low_hz >= 3000.0 else self.top_hz - self.low_hz)  # otherwise center where clicked, zooming to 500 Hz from the full view

    def signal_at(self, hz):  # the recognized signal at a frequency, if one is shown there (since 0.37)
        """Return (track, kind) for the narrowest shown signal covering hz, or None."""
        chosen = set(self.settings.get("signal_types") or ())  # the modes shown
        now = time.time()  # for signals that ended a moment ago
        near = [(k, k.kind_now) for k in self.watch.current()] + [(k, k.kind) for k in self.watch.done[-40:] if now - k.last < signalwatch.LINGER_S]  # on now, or just ended
        slack = max(3.0, (self.top_hz - self.low_hz) / max(self.scope_w, 1) * 4)  # a few points either side, so a narrow signal is easy to hit
        hits = [(k, kind) for k, kind in near if kind in chosen and k.lo - slack <= hz <= k.hi + slack]  # the ones under the pointer
        return min(hits, key=lambda item: item[0].width) if hits else None  # the narrowest (it lies on top), or none

    def scope_menu_at(self, event):  # a right click on the receive scope (since 0.37)
        """Show the scope's menu: what the signal under the pointer is, with Zoom, Hide and Show only for its mode; then the choice of modes shown and Full view."""
        sv = self.signal_vars()  # the tick variables, shared with View > Recognized signals and the Signals detected window
        menu = tk.Menu(self.root, tearoff=False)  # made fresh each time, for the signal under the pointer
        hit = self.signal_at(self.hz_at(event.x))  # the signal clicked on, if any
        if hit is not None:  # on a recognized signal
            track, kind = hit  # it and its type
            words = track.detail if kind == "Kestrel" and track.detail else kind  # the Kestrel level and callsign, or the mode
            menu.add_command(label=f"{words} at {track.center:,.0f} Hz, {track.width} Hz wide, heard {track.seconds:.0f} s", state="disabled")  # what it is, as a heading
            menu.add_command(label="Zoom in on it", underline=0, command=lambda: self.set_view(track.center, self.fit_span(track.width)))  # centered, at a width that suits it
            menu.add_command(label=f"Hide {kind} signals", underline=0, command=lambda: (sv[kind].set(False), self.signal_choice_changed()))  # this mode off
            menu.add_command(label=f"Show only {kind} signals", underline=5, command=lambda: ([sv[k].set(k == kind) for k in signalwatch.TYPES], self.signal_choice_changed()))  # every other mode off
            menu.add_separator()  # a line
        menu.add_command(label="Full view", underline=0, command=lambda: self.set_view(1500.0, 3000.0))  # back to everything (what a right click used to do)
        menu.add_separator()  # a line
        menu.add_checkbutton(label="Highlight signals on the receive scope", underline=0, variable=sv["scope"], command=self.signal_choice_changed)  # the shaded bands
        menu.add_checkbutton(label="Label signals on the waterfall", underline=0, variable=sv["fall"], command=self.signal_choice_changed)  # the names on the waterfall
        modes = tk.Menu(menu, tearoff=False)  # the modes, one tick each
        for kind in signalwatch.TYPES:  # each mode
            modes.add_checkbutton(label=kind, variable=sv[kind], command=self.signal_choice_changed)  # shown or not
        modes.add_separator()  # a line
        modes.add_command(label="Show every mode", underline=5, command=lambda: self.set_all_signal_types(True))  # all on
        modes.add_command(label="Hide every mode", underline=0, command=lambda: self.set_all_signal_types(False))  # all off
        menu.add_cascade(label="Modes shown", underline=0, menu=modes)  # the submenu
        menu.add_command(label="Signals detected list...", underline=8, accelerator="Ctrl+D", command=self.signals_window)  # the full list
        self.popup(menu, event)  # shown at the pointer

    def scope_wheel(self, event):  # the mouse wheel over the receive scope
        span = (self.top_hz - self.low_hz) * (0.5 if event.delta > 0 else 2.0)  # half the width when turned forward, double when turned back
        self.set_view(self.hz_at(event.x), span)  # about the pointer

    def center_on_last(self):  # zoom in on the station decoded most recently
        if not self.marks:  # none in the last minute
            self.view_note.configure(text="no station decoded in the last minute")  # say so
            return  # nothing to center on
        at, width, when = max(self.marks.values(), key=lambda mark: mark[2])  # the newest
        self.set_view(at, self.fit_span(width))  # center on it

    def y_for(self, db):  # where a level in dB above the noise falls on the receive trace
        floor, span = self.scope_db["rx", "floor"].get(), self.scope_db["rx", "range"].get()  # the Floor and Range sliders
        return self.above + self.trace_h - 3 - (db - floor) / span * (self.trace_h - 8)  # the floor at the bottom, floor plus range at the top

    def dial_hz(self):  # where the radio is tuned now (safe to call from any thread)
        """Return the radio's dial frequency in hertz: the chosen calling frequency, moved to a working frequency if the contact has moved."""
        station = self.station  # the running station, if any
        return self.base_khz * 1000.0 + (station.offset_hz if station is not None else 0)  # the calling frequency plus any move

    def draw_scope(self):  # redraw the scope from the newest audio
        source = self.audio  # the sound-card input, if one is open
        try:  # what is going out at this moment, if anything
            tx_levels = self.sink.spectrum(self.top_hz, self.tx_w, self.low_hz) if self.sink is not None else None  # the transmit spectrum, or None
        except Exception:  # a hiccup in reading it
            tx_levels = None  # treat it as nothing sent
        advance = source is not None or tx_levels is not None  # both waterfalls move on a line whenever either has something to show (since 0.33)
        if advance:  # they move
            self.tick_line()  # count the line, time it and note any UTC mark
        try:  # the transmit scope first; a hiccup in drawing must never stop the station
            self.draw_tx_scope(tx_levels, advance)  # what is being sent, on top, scrolling with the receive scope
        except Exception:  # anything at all
            pass  # try again next time
        try:  # a hiccup in drawing must never stop the station
            dial = self.dial_hz() / 1000.0  # the radio's frequency in kHz
            if dial != self.scale_khz:  # the radio has moved since the top scale was drawn
                self.scale_khz = dial  # remember where it is now
                self.scope.delete("rf")  # remove the old labels
                for hz in (self.low_hz + share * (self.top_hz - self.low_hz) for share in (1 / 6, 1 / 2, 5 / 6)):  # three points across
                    self.scope.create_text(self.x_for(hz), self.above / 2, text=f"{dial + hz / 1000.0:,.{1 if self.top_hz - self.low_hz >= 3000.0 else 2}f}", fill=self.colors["scale"], font="KestrelTiny", tags="rf")  # the radio frequency there (upper sideband: dial plus audio)
                self.scope.create_text(self.left + self.scope_w + self.right / 2, self.above / 2, text="kHz", fill=self.colors["scale"], font="KestrelTiny", tags="rf")  # the unit
            if source is not None:  # there is audio to show
                levels = source.spectrum(self.top_hz, self.scope_w, self.low_hz)  # the spectrum of the newest audio, in decibels
                floor = float(np.median(levels))  # the noise level, taken as the middle value
                low, span = floor + self.scope_db["rx", "floor"].get(), self.scope_db["rx", "range"].get()  # the receive scope's Floor and Range sliders, the floor counted from the noise
                bright = np.clip((levels - low) / span, 0.0, 1.0)  # each point on a scale from the floor (bottom, black) to the floor plus the range (top, red)
                points = np.column_stack((self.left + np.arange(self.scope_w), self.above + self.trace_h - 3 - bright * (self.trace_h - 8))).ravel().tolist()  # the trace's corners
                self.scope.coords(self.trace, *points)  # move the trace
                self.fall = np.roll(self.fall, 1, axis=0)  # push the waterfall down one line
                self.fall[0] = self.palettes["rx"][(bright * 255).astype(int)]  # and paint the newest line at the top, in the receive waterfall's colors
                self.fall_image = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.scope_w, self.fall_h) + self.fall.tobytes(), format="PPM")  # the picture, rebuilt
                self.scope.itemconfigure(self.fall_item, image=self.fall_image)  # show it
            elif advance:  # nothing received, but something is being sent: keep the receive waterfall in step
                self.fall = np.roll(self.fall, 1, axis=0)  # push it down one line
                self.fall[0] = self.palettes["rx"][0]  # an empty line, in the "nothing there" color
                self.fall_image = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.scope_w, self.fall_h) + self.fall.tobytes(), format="PPM")  # the picture, rebuilt
                self.scope.itemconfigure(self.fall_item, image=self.fall_image)  # show it
            if advance:  # the waterfalls moved
                self.draw_time_marks()  # the UTC marks and the seconds scale move with them (redrawn each line, since the line rate is measured)
            if source is not None and time.monotonic() - self.watch_at >= 0.5:  # twice a second (since 0.37)
                self.watch_at = time.monotonic()  # now
                self.watch.feed(source.recent, dial_khz=self.dial_hz() / 1000.0)  # the newest second of audio: follow every signal in it
            self.draw_signal_labels()  # the recognized signals, named on the waterfall
            self.scope.delete("mark")  # the station labels are redrawn each time
            now = time.monotonic()  # for their age
            for call, (hz, width, when) in list(self.marks.items()):  # each station decoded recently
                if now - when > 60.0:  # more than a minute ago
                    del self.marks[call]  # forget it
                    continue  # and move on
                if hz + width / 2 < self.low_hz or hz - width / 2 > self.top_hz:  # the signal is outside the view
                    continue  # nothing to draw
                low, high = self.x_for(max(self.low_hz, hz - width / 2)), self.x_for(min(self.top_hz, hz + width / 2))  # the signal's edges, as far as they are in view
                self.scope.create_line(low, self.above + 14, low, self.above + 18, high, self.above + 18, high, self.above + 14, fill=self.colors["mark"], tags="mark")  # a bracket over the signal
                self.scope.create_text((low + high) / 2, self.above + 8, text=call, fill=self.colors["mark"], font="KestrelSmallBold", tags="mark")  # with the callsign above it
        except Exception:  # anything at all
            pass  # try again next time
        try:  # the frame strip, four times a second (since 0.37)
            if self.settings.get("frame_strip", True) and time.monotonic() - self.strip_at >= 0.25:  # shown, and due
                self.strip_at = time.monotonic()  # now
                self.draw_frame_strip()  # drawn
        except Exception:  # anything at all
            pass  # try again next time
        self.root.after(100, self.draw_scope)  # ten times a second

    def draw_frame_strip(self):  # the frame strip under the receive scope (since 0.37)
        """Draw the frame arriving or last heard: preamble, header, body and header again, and its message's parts."""
        canvas = self.strip_canvas  # where
        width = canvas.winfo_width()  # how wide it is now
        if width < 400:  # not laid out yet, or squeezed
            return  # nothing drawn
        frame_strip.draw(canvas, self.frames.view(), self.colors, 6, 4, width - 12)  # drawn

    def frame_strip_toggled(self):  # View > Frame strip under the receive scope (since 0.37)
        """Show or hide the frame strip, and remember the choice."""
        self.settings["frame_strip"] = bool(self.strip_var.get())  # the choice
        self.save_settings()  # kept
        if self.settings["frame_strip"]:  # shown
            self.strip_canvas.grid()  # back in its place
            self.draw_frame_strip()  # drawn now
        else:  # hidden
            self.strip_canvas.grid_remove()  # out of the way (its place is remembered)

    def draw_signal_labels(self):  # name the recognized signals on the receive waterfall (since 0.37)
        """Draw a small label at the top of the waterfall over each signal on now whose type is chosen in the Signals detected window."""
        self.scope.delete("sig")  # the old bands and labels
        on_scope = self.settings.get("signal_scope", True)  # bands on the receive scope
        on_fall = self.settings.get("signal_labels", True)  # labels on the waterfall
        if not on_scope and not on_fall:  # both turned off
            return  # nothing more
        chosen = set(self.settings.get("signal_types") or ())  # the modes to show
        now = time.time()  # for how recently a signal ended
        shown = [(k, k.kind_now) for k in self.watch.current()] + [(k, k.kind) for k in self.watch.done[-40:] if now - k.last < signalwatch.LINGER_S]  # on now, and ended in the last few seconds (FT8 and FT4 pause between transmissions)
        shown = sorted(((k, kind) for k, kind in shown if kind in chosen and k.hi >= self.low_hz and k.lo <= self.top_hz), key=lambda item: -item[0].width)  # the ones to draw, widest first (so a narrow signal's band lies on top of a wide one's)
        rows = {"scope": [], "fall": []}  # the names placed so far, by row: (left, right) in points
        bg = self.colors.get("label_bg", "#000000")  # the patch behind names

        def place(where, x, words, color, y0, step, anchor, font):  # put a name where it collides with none already placed
            probe = self.scope.create_text(x, y0, text=words, anchor=anchor, font=font)  # measured first
            box = self.scope.bbox(probe)  # its size
            self.scope.delete(probe)  # gone again
            if not box:  # not drawable
                return  # nothing
            half = (box[2] - box[0]) / 2 + 3  # half its width, with a little room
            placed = rows[where]  # the rows so far
            for row in range(SIGNAL_LABEL_ROWS):  # the lowest free row
                if row >= len(placed):  # a new row
                    placed.append([])  # opened
                if all(x + half < a or x - half > b for a, b in placed[row]):  # clear of every name in it
                    placed[row].append((x - half, x + half))  # taken
                    y = y0 + row * step  # its height
                    name = self.scope.create_text(x, y, text=words, anchor=anchor, fill=color, font=font, tags="sig")  # the name
                    nb = self.scope.bbox(name)  # its size
                    if nb:  # drawn
                        self.scope.tag_lower(self.scope.create_rectangle(nb[0] - 2, nb[1], nb[2] + 2, nb[3], fill=bg, outline="", tags="sig"), name)  # a patch behind it, so it reads
                    return  # placed
            # every row full: the name is left off (its band still shows, and the Signals detected list has it)

        for track, kind in shown:  # each signal
            words = track.detail if kind == "Kestrel" and track.detail else kind  # the Kestrel level and callsign, or the mode
            color = self.colors.get("mode_" + kind.lower(), self.colors.get("label", "#ffffff"))  # the mode's color in this theme
            lo = self.x_for(max(track.lo, self.low_hz))  # its left edge
            hi = max(self.x_for(min(track.hi, self.top_hz)), lo + 6)  # its right edge (at least 6 points wide, so a narrow signal shows)
            if on_scope:  # a shaded band over the signal on the receive trace, with the mode named
                band = self.scope.create_rectangle(lo, self.above + 20, hi, self.above + self.trace_h - 2, fill=color, stipple="gray25", outline=color, tags="sig")  # the band, see-through
                self.scope.tag_lower(band, self.trace)  # under the trace, so the trace stays clear
                place("scope", (lo + hi) / 2, words, color, self.above + self.trace_h - 4, -12, "s", "KestrelTinyBold")  # the mode, at the foot of the band (rows go up)
            if on_fall and any(track is k for k in self.watch.active):  # labels on the waterfall only for signals on now
                place("fall", (lo + hi) / 2, words, color, self.above + self.trace_h + 2, 12, "n", "KestrelTiny")  # the name, at the top of the waterfall (rows go down)

    def signal_vars(self):  # the on/off choices for recognized signals, shared by the View menu and the Signals detected window (since 0.37)
        """Return (making them once) the tick variables: "scope", "fall", and one per mode."""
        if not hasattr(self, "_signal_vars"):  # not made yet
            chosen = set(self.settings.get("signal_types") or ())  # the modes shown
            self._signal_vars = {"scope": tk.BooleanVar(value=bool(self.settings.get("signal_scope", True))), "fall": tk.BooleanVar(value=bool(self.settings.get("signal_labels", True))),  # (continued: where they are shown)
                                 **{kind: tk.BooleanVar(value=kind in chosen) for kind in signalwatch.TYPES}}  # each mode
        return self._signal_vars  # the variables

    def signal_choice_changed(self):  # a tick changed, in the menu or the window
        """Keep the settings in step with the tick variables, and redraw."""
        sv = self.signal_vars()  # the variables
        self.settings["signal_types"] = [kind for kind in signalwatch.TYPES if sv[kind].get()]  # the modes shown
        self.settings["signal_scope"] = sv["scope"].get()  # bands on the scope
        self.settings["signal_labels"] = sv["fall"].get()  # labels on the waterfall
        self.save_settings()  # kept
        self.draw_signal_labels()  # redrawn now
        refresh = getattr(self, "_signals_fill", None)  # the open list, if any
        if refresh is not None:  # open
            refresh()  # refilled

    def set_all_signal_types(self, on):  # Show every mode / Hide every mode
        """Tick or clear every mode."""
        for kind in signalwatch.TYPES:  # each
            self.signal_vars()[kind].set(on)  # set
        self.signal_choice_changed()  # applied

    def signals_window(self):  # Stations > Signals detected (since 0.37)
        """Show every signal recognized in the passband (on now, then lately), with type, frequency, width, start and length; types to show can be chosen."""
        top = self.window("signals", "Kestrel - signals detected")  # the window
        ttk.Label(top, text="Every signal seen in the receiver's passband: what it looks like, where it is and how long it was heard. The type is a judgment from its width,\n"
                  "length, timing and steadiness, as an operator would make it from the waterfall; Kestrel frames are named by the receiver. Tick the types to list and label.", justify="left").pack(anchor="w", padx=8, pady=(8, 4))  # what it shows
        picks = ttk.Frame(top)  # the type tick boxes
        picks.pack(fill="x", padx=8)  # across the top
        sv = self.signal_vars()  # the on/off choices, shared with View > Recognized signals
        for i, kind in enumerate(signalwatch.TYPES):  # each mode
            ttk.Checkbutton(picks, text=kind, variable=sv[kind], command=self.signal_choice_changed).grid(row=0, column=i, padx=(0, 10), sticky="w")  # its box
        ttk.Checkbutton(picks, text="Highlight them on the receive scope", variable=sv["scope"], command=self.signal_choice_changed).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))  # bands on the trace
        ttk.Checkbutton(picks, text="Label them on the waterfall", variable=sv["fall"], command=self.signal_choice_changed).grid(row=1, column=4, columnspan=3, sticky="w", pady=(4, 0))  # names on the waterfall
        ttk.Button(picks, text="All", command=lambda: self.set_all_signal_types(True)).grid(row=1, column=7, sticky="e", pady=(4, 0))  # every mode on
        ttk.Button(picks, text="None", command=lambda: self.set_all_signal_types(False)).grid(row=1, column=8, sticky="w", padx=(4, 0), pady=(4, 0))  # every mode off
        tree = self.table(top, (("when", "Started", 80), ("state", "", 50), ("kind", "Type", 70), ("audio", "Audio Hz", 70), ("rf", "Frequency kHz", 100), ("width", "Width Hz", 70), ("length", "Heard for", 80), ("strength", "Strength", 70), ("detail", "Detail", 160)), height=18)  # the list

        def clock(seconds):  # a time, in the zone the scopes use
            local = self.settings.get("scope_time_zone") == "local"  # local time or UTC
            return time.strftime("%H:%M:%S", time.localtime(seconds) if local else time.gmtime(seconds))  # as hours, minutes and seconds

        def length(seconds):  # a length, readably
            return f"{seconds:.0f} s" if seconds < 100 else f"{int(seconds // 60)} min {int(seconds % 60):02d} s"  # seconds, or minutes and seconds

        def fill():  # (re)fill the list
            if not tree.winfo_exists():  # the window was closed
                return  # stop
            kinds = set(self.settings.get("signal_types") or ())  # the types chosen
            live, finished = self.watch.rows(kinds)  # on now, and heard lately
            dial = self.dial_hz() / 1000.0  # the radio's frequency, kHz
            tree.delete(*tree.get_children())  # empty it
            for track, state in [(k, "ON") for k in live] + [(k, "") for k in finished]:  # each signal
                kind = track.kind_now if state else track.kind  # its type
                tree.insert("", "end", values=(clock(track.start), state, kind, f"{track.center:.0f}", f"{dial + track.center / 1000.0:,.3f}" if dial else "", track.width, length(track.seconds), f"{track.strength:+.0f} dB", track.detail))  # one row

        def tick():  # keep it current
            if top.winfo_exists():  # still open
                fill()  # the list again
                top.after(2000, tick)  # every two seconds
            else:  # closed
                self._signals_fill = None  # nothing to refill

        self._signals_fill = fill  # refilled when a choice changes in the View menu

        tick()  # fill it now
        buttons = ttk.Frame(top)  # the row of buttons
        buttons.pack(fill="x", padx=8, pady=(0, 8))  # at the bottom
        ttk.Button(buttons, text="Clear the list", command=lambda: (self.watch.done.clear(), fill())).pack(side="left")  # forget the finished signals
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close the window

    # ---- the level meters ----

    def _meters(self, parent):  # the receive and transmit level meters, each with its slider
        self.levels_frame = frame = ttk.LabelFrame(parent, text="Levels")  # the box around them
        parent.add(frame, weight=0)  # on the right, keeping its own width when the window grows
        self.meter_h, self.meter_w = 118, 30  # the size of each meter (shorter since 0.42, so the help under them fits at 768 high)
        self.rx_meter = self._meter(frame, 0, "Receive\n(radio to PC)")  # the receive meter
        self.tx_meter = self._meter(frame, 2, "Transmit\n(PC to radio)")  # the transmit meter
        self.rx_value = tk.DoubleVar(value=0.5)  # the receive slider's position
        self.rx_slider = ttk.Scale(frame, orient="vertical", from_=1.0, to=0.0, length=self.meter_h, variable=self.rx_value, command=lambda value: self.rx_level_moved())  # Windows' recording level for the receive device
        self.rx_slider.grid(row=1, column=1, padx=(0, 6))  # beside the receive meter
        self.tx_value = tk.DoubleVar(value=float(self.settings["gain"] or 0.25))  # the transmit slider's position
        self.tx_slider = ttk.Scale(frame, orient="vertical", from_=1.0, to=0.0, length=self.meter_h, variable=self.tx_value, command=lambda value: self.tx_level_moved())  # the transmit audio level
        self.tx_slider.grid(row=1, column=3, padx=(0, 6))  # beside the transmit meter
        self.tx_slider.bind("<ButtonRelease-1>", lambda event: self.save_settings())  # remember the new level when the mouse lets go
        self.tx_slider.bind("<KeyRelease>", lambda event: self.save_settings())  # or when the arrow key is released
        self.rx_text = ttk.Label(frame, text="", font="KestrelSmall", justify="center", width=14, anchor="center")  # the receive readings in words
        self.rx_text.grid(row=2, column=0, columnspan=2, pady=(2, 0))  # under the receive meter
        self.tx_text = ttk.Label(frame, text="", font="KestrelSmall", justify="center", width=14, anchor="center")  # the transmit readings in words
        self.tx_text.grid(row=2, column=2, columnspan=2, pady=(2, 0))  # under the transmit meter
        ttk.Label(frame, text="Aim for the green band.\nRed or CLIP: lower the\nradio's USB audio.", font="KestrelSmall", justify="center").grid(row=3, column=0, columnspan=4, pady=(4, 4))  # how to use them
        self.find_rx_level()  # find Windows' level control for the receive device

    def _meter(self, frame, column, title):  # one vertical meter, scaled -60 to 0 dBFS
        ttk.Label(frame, text=title, font="KestrelSmall", justify="center").grid(row=0, column=column, columnspan=2, pady=(2, 2))  # its title
        canvas = tk.Canvas(frame, width=self.meter_w + 28, height=self.meter_h, bg=self.colors["scope_bg"], highlightthickness=0)  # the drawing area: the bar plus room for the scale
        canvas.grid(row=1, column=column, padx=(6, 2))  # place it
        x0, x1 = 26, 26 + self.meter_w  # the bar's left and right edges
        for low, high, key in ((-60, -30, "meter_low"), (-30, -15, "meter_ok"), (-15, -6, "meter_loud"), (-6, 0, "meter_hot")):  # the zones: too low, aim here, getting loud, too loud
            canvas.create_rectangle(x0, self.meter_y(high), x1, self.meter_y(low), fill=self.colors[key], outline="", tags=key)  # each zone, dimly (tagged with its color's name, so a new theme can recolor it)
        canvas.create_rectangle(x0, self.meter_y(-15), x1, self.meter_y(-30), outline=self.colors["bar_ok"], width=1, tags="target")  # the target band outlined
        for db in (0, -6, -15, -30, -45, -60):  # the scale
            canvas.create_line(x0 - 4, self.meter_y(db), x0, self.meter_y(db), fill=self.colors["scale"], tags="scale")  # a tick
            canvas.create_text(x0 - 6, self.meter_y(db), text=str(db), anchor="e", fill=self.colors["scale"], font="KestrelTiny", tags="scale")  # its value in dBFS
        canvas.create_rectangle(x0 + 3, self.meter_y(-60), x1 - 3, self.meter_y(-60), fill=self.colors["bar_ok"], outline="", tags="bar")  # the level bar, empty to begin with
        canvas.create_line(x0, self.meter_y(-60), x1, self.meter_y(-60), fill=self.colors["peak"], width=2, tags="peak")  # the peak mark
        canvas.create_text((x0 + x1) / 2, 8, text="", fill=self.colors["bar_hot"], font="KestrelTinyBold", tags="clip")  # CLIP, when the input is overdriven
        return canvas  # for drawing on

    def meter_y(self, db):  # where a level falls on a meter
        return 4 + (min(0.0, max(-60.0, db)) / -60.0) * (self.meter_h - 8)  # 0 dBFS at the top, -60 at the bottom

    def show_level(self, canvas, rms_db, peak_db, dim=False, clip=False):  # move one meter's bar and peak mark
        c = self.colors  # the theme's colors
        color = c["bar_ok"] if rms_db < -15 else (c["bar_loud"] if rms_db < -6 else c["bar_hot"])  # green while in or under the target band, yellow when getting loud, red when too loud (in the theme's colors)
        if rms_db < -45:  # hardly any signal
            color = c["bar_low"]  # too low to be useful
        if dim:  # a setting, not a live reading
            color = c["bar_dim"]  # shown dimly
        canvas.coords("bar", 29, self.meter_y(rms_db), 26 + self.meter_w - 3, self.meter_y(-60))  # the bar, from the bottom up to the RMS level
        canvas.itemconfigure("bar", fill=color)  # in its color
        canvas.coords("peak", 26, self.meter_y(peak_db), 26 + self.meter_w, self.meter_y(peak_db))  # the peak mark
        canvas.itemconfigure("clip", text="CLIP" if clip else "")  # the overload warning

    def draw_meters(self):  # bring both meters up to date
        try:  # a hiccup must never stop the panel
            source = self.audio  # the receive input, if open
            if source is not None:  # receiving
                rms, peak = source.level()  # how loud the input is
                if source.clips > self.clips_seen:  # a sample has reached full scale since the last look
                    self.clips_seen, self.clip_until = source.clips, time.monotonic() + 3.0  # show CLIP for three seconds
                clip = time.monotonic() < self.clip_until  # still showing it
                self.show_level(self.rx_meter, rms, peak, clip=clip)  # the receive meter
                level = f"Windows level {self.rx_value.get() * 100:.0f}%" if self.rx_level is not None else "level: set in Windows"  # the slider's setting, or where to set it
                self.rx_text.configure(text=f"{rms:.0f} dBFS avg\n{peak:.0f} peak\n{level}")  # in words
            else:  # not receiving
                self.show_level(self.rx_meter, -60.0, -60.0)  # empty
                self.rx_text.configure(text="not receiving")  # say so
            sink, gain = self.sink, max(self.tx_value.get(), 1e-4)  # the transmit output, and its level setting
            if sink is not None and sink.playing:  # transmitting now
                self.show_level(self.tx_meter, sink.last_peak_db - 3.0, sink.last_peak_db)  # the transmit audio's level (its average sits about 3 dB under its peak)
            else:  # not transmitting
                expected = 20.0 * np.log10(gain)  # the peak the next transmission will reach
                self.show_level(self.tx_meter, expected - 3.0, expected, dim=True)  # shown dimly, as a setting
            radio = []  # what the radio reports
            if self.meters["watts"] is not None and self.tx_active:  # power out, while transmitting
                radio.append(f"{self.meters['watts']:.0f} W out")  # in watts
            elif self.meters["set_w"] is not None:  # the power setting
                radio.append(f"power set {self.meters['set_w']:.0f} W")  # in watts
            if self.meters["alc"] is not None and self.tx_active:  # ALC, while transmitting
                radio.append(f"ALC {self.meters['alc']:.2f}")  # 0 to 1
            if self.meters["swr"] is not None and self.tx_active:  # SWR, while transmitting
                radio.append(f"SWR {self.meters['swr']:.1f}")  # standing-wave ratio
            self.tx_text.configure(text=f"drive {gain * 100:.0f}%\n" + ("\n".join(radio) if radio else ("TRANSMITTING" if self.tx_active else "")))  # in words
            if self.rx_level is not None and time.monotonic() - self.level_check > 3.0 and self.root.focus_get() is not self.rx_slider:  # every few seconds, unless the operator is using the slider
                self.level_check = time.monotonic()  # remember when
                self.rx_value.set(self.rx_level.get())  # follow any change made in Windows itself
        except Exception:  # anything at all
            pass  # try again next time
        self.root.after(100, self.draw_meters)  # ten times a second

    def find_rx_level(self):  # find Windows' level control for the receive device
        self.rx_level = mixer.find(self.settings["audio_in"], "input")  # None if it cannot be had
        if self.rx_level is not None:  # found
            self.rx_value.set(self.rx_level.get())  # the slider shows Windows' setting
            self.rx_slider.state(["!disabled"])  # and can be moved
        else:  # not available
            self.rx_slider.state(["disabled"])  # the slider does nothing, so it is grayed out

    def rx_level_moved(self):  # the receive slider was moved
        if self.rx_level is not None:  # Windows' control is available
            try:  # Windows may refuse
                self.rx_level.set(self.rx_value.get())  # set the device's recording level
            except Exception:  # it did
                pass  # the meter will show the level is unchanged

    def tx_level_moved(self):  # the transmit slider was moved
        gain = round(self.tx_value.get(), 3)  # the new level, 0 to 1
        self.settings["gain"] = f"{gain:.3f}"  # remembered with the settings
        if self.sink is not None:  # a station is running
            self.sink.gain = gain  # its next transmission uses the new level

    # ---- small helpers ----

    def apply_fonts(self):  # set every font from the family and size chosen in Settings
        """Point Tk's standard fonts, and Kestrel's own smaller and larger ones, at the chosen family and size; every widget follows at once."""
        from tkinter import font as tkfont  # Tk's fonts
        family = str(self.settings.get("font_family") or "Segoe UI")  # the family chosen
        try:  # the size may have been typed
            size = min(FONT_MAX, max(FONT_MIN, int(self.settings.get("font_size") or 9)))  # kept within sensible limits
        except ValueError:  # not a number
            size = 9  # the usual size
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):  # the fonts Tk's widgets use
            tkfont.nametofont(name, root=self.root).configure(family=family, size=size)  # all in the chosen family and size
        tkfont.nametofont("TkFixedFont", root=self.root).configure(family="Consolas", size=size)  # the log and the frequency list keep an even-width font, at the chosen size
        for name, change, weight in (("KestrelTiny", -2, "normal"), ("KestrelTinyBold", -2, "bold"), ("KestrelSmall", -1, "normal"), ("KestrelSmallBold", -1, "bold"), ("KestrelMedium", 1, "normal"), ("KestrelBig", 4, "bold")):  # Kestrel's own: scale lettering, notes, readings, the status line
            if name in self.fonts:  # made already
                self.fonts[name].configure(family=family, size=max(6, size + change), weight=weight)  # follow the new choice
            else:  # the first time
                self.fonts[name] = tkfont.Font(root=self.root, name=name, family=family, size=max(6, size + change), weight=weight)  # make it, under a name the widgets refer to
        ttk.Style(self.root).configure("Treeview", rowheight=tkfont.nametofont("TkDefaultFont", root=self.root).metrics("linespace") + 5)  # list rows as tall as the lettering needs

    # ---- the dividers and the window's size ----

    def save_layout(self):  # remember the window's size and where the dividers are
        zoomed = self.root.state() == "zoomed"  # the window fills the screen
        layout = {"zoomed": zoomed, "window": self.settings.get("layout", {}).get("window", "") if zoomed else self.root.geometry()}  # its size and place (the last unzoomed one, if it is zoomed now)
        layout["sashes"] = {name: [pane.sashpos(index) for index in range(len(pane.panes()) - 1)] for name, pane in self.panes.items()}  # each divider's position
        self.settings["layout"] = layout  # saved with the other settings

    def default_layout(self):  # a starting size that fits the screen, and the dividers in their usual places
        wide, high = self.root.winfo_screenwidth(), self.root.winfo_screenheight()  # the screen
        self.root.state("normal")  # not filling the screen
        width, height = min(1280, wide - 24), min(900, high - 120)  # room left for the window's frame, its menu and the taskbar
        self.root.geometry(f"{width}x{height}+{max(0, (wide - width) // 2)}+0")  # at the top of the screen, centered
        self.root.update_idletasks()  # let the panels take their new sizes
        for name, shares in (("split", (0.36, )), ("lists", (0.47, )), ("scopes", (0.24, ))):  # each divider's place, as a share of its row or column (the message panel and the lists side by side, the transmit scope short; since 0.41)
            pane = self.panes[name]  # the divided area
            across = pane.winfo_width() if str(pane.cget("orient")) == "horizontal" else pane.winfo_height()  # its length
            for index, share in enumerate(shares):  # each divider in turn
                pane.sashpos(index, max(int(share * across), 150 if name == "split" else 0))  # put it there (the lists keep room for a few rows on a small screen)
        bottom = self.panes["bottom"]  # the row holding the scopes and the meters
        bottom.sashpos(0, bottom.winfo_width() - self.levels_frame.winfo_reqwidth() - 6)  # the meters keep just the width they need

    def restore_layout(self):  # put the window and the dividers back as they were left
        layout = self.settings.get("layout") or {}  # what was saved
        if not layout.get("window"):  # nothing yet
            self.default_layout()  # start from the usual arrangement
            return  # done
        try:  # a saved layout from another screen may not suit this one
            size, x, y = layout["window"].replace("-", "+-").split("+", 2)  # "WxH", then where
            width, height = (int(part) for part in size.split("x"))  # its size
            wide, high = self.root.winfo_screenwidth(), self.root.winfo_screenheight()  # the screen now
            width, height = min(width, wide - 24), min(height, high - 120)  # no bigger than the screen can show
            self.root.geometry(f"{width}x{height}+{min(max(0, int(x.replace('+', ''))), max(0, wide - width))}+{min(max(0, int(y.replace('+', ''))), max(0, high - height - 100))}")  # and wholly on the screen
            if layout.get("zoomed"):  # it filled the screen
                self.root.state("zoomed")  # so it does again
            self.root.update_idletasks()  # let the panels take their sizes
            sashes = layout.get("sashes") or {}  # where the dividers were
            self.place_sashes(sashes)  # put them back now
            for delay in (400, 1500):  # and again once Windows (or Remote Desktop) has finished sizing the window, which spreads the panels out again (since 0.42R2)
                self.root.after(delay, lambda: self.place_sashes(sashes))  # the same places
        except (ValueError, KeyError, tk.TclError):  # the saved layout could not be used
            self.default_layout()  # fall back on the usual arrangement

    def place_sashes(self, sashes):  # put the dividers where they were left (since 0.42R2)
        """Move every divider to its saved place, then make sure the level meters still show."""
        try:  # the window may be closing
            for name, places in sashes.items():  # each divided area
                for index, place in enumerate(places):  # each divider in turn
                    if name in self.panes and index < len(self.panes[name].panes()) - 1:  # a divider this layout still has
                        self.panes[name].sashpos(index, int(place))  # back where it was
        except (tk.TclError, ValueError):  # gone, or a damaged entry
            return  # leave it
        self.keep_meters_visible()  # never with the level meters squeezed out of sight

    def keep_meters_visible(self, event=None):  # the level meters and sliders must always show
        """Move the divider beside the level meters back, if needed, so the meters keep the width they need.

        The meters share the bottom row with the log and the scopes, with
        draggable dividers between them. A divider dragged to the edge, or
        a window made narrower, could otherwise squeeze the meters and their
        sliders to nothing, and the saved layout would keep them hidden.
        """
        try:  # the window may be closing
            bottom = self.panes["bottom"]  # the row holding the log, the scopes and the meters
            width = bottom.winfo_width()  # its width now
            need = self.levels_frame.winfo_reqwidth() + 6  # the meters' own width, and a little room
            if width <= need + 100:  # not laid out yet (or absurdly small): leave it
                return  # nothing sensible to do
            limit = width - need  # the furthest right the divider may sit
            if bottom.sashpos(0) > limit:  # it is further right than that (the Activity log left this row in 0.41, so the meters' divider is the only one)
                bottom.sashpos(0, limit)  # bring it back
        except (tk.TclError, KeyError, AttributeError):  # the window or its panels are gone
            pass  # nothing to keep

    def color_plain_widgets(self):  # color the widgets the theme cannot reach
        c = self.colors  # the palette
        theme.color_window(self.root, c)  # the window's background and title bar
        self.plain_color = c["bg"]  # the status band's ordinary background
        self.log.configure(background=c["text_bg"], foreground=c["text_fg"], insertbackground=c["text_fg"])  # the log
        self.message.configure(background=c["field"], foreground=c["fg"], insertbackground=c["fg"], highlightbackground=c["border"], highlightcolor=c["accent"], selectbackground=c["select"], selectforeground=c["select_fg"])  # the message box (a plain text box since 0.41)
        theme.color_window(self.activity, c)  # the Activity window (since 0.41)
        if getattr(self, "chat", None) is not None:  # the Chat window has been opened (since 0.42)
            theme.color_window(self.chat, c)  # in the same look
            self.chat_text.configure(background=c["text_bg"], foreground=c["text_fg"])  # its conversation
            self.chat_text.tag_configure("them", foreground=c.get("accent", c["text_fg"]))  # the partner's lines in the accent color
        self.status.configure(background=c["bg"], foreground=c["fg"])  # the status band, until a state colors it
        self.stations.tag_configure("calling", background=c["calling_row"])  # stations beaconing now, highlighted in the theme's color
        self.quick_menu.configure(background=c["panel"], foreground=c["fg"], activebackground=c["select"], activeforeground=c["select_fg"])  # the quick-message menu (a pop-up, which Windows lets the program color)
        theme.recolor_plain(self.root, c)  # the open lists of the drop-downs, text areas, plain lists and pop-up menus (since 0.37)
        self.recolor_scopes()  # the scopes and meters (since 0.37)
        for window in self.windows.values():  # any extra windows that are open
            if window.winfo_exists():  # still open
                theme.color_window(window, c)  # color them too

    def recolor_scopes(self):  # the scopes, meters and waterfalls in the theme's colors (since 0.37)
        """Recolor both scopes (background, traces, words, scales) and both meters, and remake the waterfall colors if they follow the theme."""
        c = self.colors  # the palette
        if not hasattr(self, "scope"):  # the scopes are not built yet (the first coloring comes before them)
            return  # they are built in these colors
        for canvas in (self.scope, self.tx_canvas):  # both scopes
            canvas.configure(bg=c["scope_bg"])  # background
        if hasattr(self, "strip_canvas"):  # the frame strip (since 0.37)
            self.strip_canvas.configure(bg=c["bg"])  # on the window's background
            self.strip_at = 0.0  # redrawn in the new colors at the next look
        self.scope.itemconfigure(self.trace, fill=c["rx_trace"])  # the receive trace
        self.tx_canvas.itemconfigure(self.tx_line, fill=c["tx_trace"])  # the transmit trace
        self.tx_canvas.itemconfigure(self.tx_words, fill=c["tx_words"])  # the transmit scope's words
        self.scale_khz = None  # the radio-frequency labels are redrawn on the next look
        self.draw_scales()  # the scales, edges and time marks, redrawn in the new colors
        for meter in (self.rx_meter, self.tx_meter):  # both meters
            meter.configure(bg=c["scope_bg"])  # background
            for key in ("meter_low", "meter_ok", "meter_loud", "meter_hot"):  # the zones
                meter.itemconfigure(key, fill=c[key])  # each in its color
            meter.itemconfigure("target", outline=c["bar_ok"])  # the target band
            meter.itemconfigure("scale", fill=c["scale"])  # ticks and numbers
            meter.itemconfigure("peak", fill=c["peak"])  # the peak mark
            meter.itemconfigure("clip", fill=c["bar_hot"])  # the overload warning
        if self.palette_var.get() == THEME_OWN:  # the waterfalls follow the theme
            self.make_palettes()  # the theme's waterfall colors
            self.fall[:] = self.palettes["rx"][0]  # start afresh, so old lines in the old colors do not linger
            self.tx_fall[:] = self.palettes["tx"][0]  # both waterfalls

    def refresh_theme_menus(self):  # (re)fill View > Theme and View > Scope theme (since 0.37)
        """List every program theme and scope theme, the operator's own last, in the View menu."""
        self.looks_menu.delete(0, "end")  # empty
        built = [c for c in theme.CHOICES if c == "system" or c in theme.BUILT_IN]  # System and the themes that come with Kestrel
        mine = [c for c in theme.CHOICES if c not in built]  # the operator's own
        for group in (built, mine):  # the two groups
            if group is mine and mine:  # the operator's own follow
                self.looks_menu.add_separator()  # a divider before them
            for choice in group:  # each theme
                self.looks_menu.add_radiobutton(label=theme.NAMES[choice], value=choice, variable=self.theme_var, command=lambda c=choice: self.set_theme(c))  # one each
        self.scope_looks_menu.delete(0, "end")  # empty
        built = [k for k in theme.SCOPE_NAMES if k in theme.BUILT_IN_SCOPES]  # "follow the program theme" and the built-in scope themes
        mine = [k for k in theme.SCOPE_NAMES if k not in theme.BUILT_IN_SCOPES]  # the operator's own
        for key in built + mine:  # each scope theme
            if key == mine[0] if mine else False:  # the first of the operator's own
                self.scope_looks_menu.add_separator()  # a divider before them
            self.scope_looks_menu.add_radiobutton(label=theme.SCOPE_NAMES[key], value=key, variable=self.scope_theme_var, command=lambda k=key: self.set_scope_theme(k))  # one each
            if key == "theme":  # after "follow the program theme"
                self.scope_looks_menu.add_separator()  # a divider

    def waterfall_sets(self):  # the waterfall color sets, for the theme editor
        """Return the names of the waterfall color sets."""
        return list(PALETTES)  # every one

    def apply_look(self, program, scope):  # show a theme without keeping it as the choice (the theme editor's preview)
        """Color everything with program theme `program` and scope theme `scope`, without changing the saved settings."""
        self.colors = theme.apply(self.root, program, scope)  # the themed widgets
        self.color_plain_widgets()  # and the rest, scopes included
        self.draw_signal_labels()  # the signal bands
        self.show_status(self.status.cget("text"), "plain")  # the status band

    def set_scope_theme(self, key):  # View > Scope theme (since 0.37)
        """Give the scopes and meters their own look (or the program theme's), keep the choice, and redraw them."""
        self.settings["scope_theme"] = key  # remembered
        self.scope_theme_var.set(key)  # ticked in the menu
        if key != "theme":  # a scope theme brings its own waterfall colors
            self.palette_var.set(THEME_OWN)  # the waterfalls follow it (View > Waterfall colors can still pick another set afterwards)
            self.settings["scope_palette"] = THEME_OWN  # remembered
        self.colors = theme.palette(self.settings["theme"], key)  # the colors, with the scope theme's on the scopes
        self.recolor_scopes()  # the scopes, meters and waterfalls
        self.draw_signal_labels()  # the signal bands in the new colors
        self.save_settings()  # kept

    def set_theme(self, choice):  # View > Theme
        self.settings["theme"] = choice  # remember the choice
        self.theme_var.set(choice)  # tick it in the menu
        self.colors = theme.apply(self.root, choice, self.settings.get("scope_theme", "theme"))  # restyle every themed widget (the scopes keep their own theme if one is chosen)
        self.color_plain_widgets()  # and the rest
        self.show_status(self.status.cget("text"), "plain")  # redraw the status band in the new colors
        self.save_settings()  # keep it for next time

    def window(self, name, title):  # a window of its own, one of a kind
        """Return a new top-level window called `title`, closing any earlier one of the same `name`; Esc closes it."""
        old = self.windows.get(name)  # an earlier one
        if old is not None and old.winfo_exists():  # still open
            old.destroy()  # close it
        top = tk.Toplevel(self.root)  # the new window
        top.title(title)  # its title
        top.transient(self.root)  # it belongs to the main window
        top.bind("<Escape>", lambda event: top.destroy())  # Esc closes it
        theme.color_window(top, self.colors)  # in the chosen look
        self.windows[name] = top  # remember it
        return top  # ready to fill

    def touched(self, event=None):  # the operator pressed a key or used the mouse
        self.last_input = time.monotonic()  # the station is attended

    def open_path(self, path):  # open a file or folder in Windows' own program for it
        if not os.path.exists(path):  # nothing there yet
            messagebox.showinfo("Kestrel", f"There is nothing there yet:\n{os.path.basename(path)}\n\nIt is made when the first entry is logged.", parent=self.root)  # say so
            return  # nothing to open
        try:  # Windows may refuse
            if sys.platform == "win32":  # Windows
                os.startfile(path)  # open with the program Windows uses for it
            else:  # elsewhere
                subprocess.Popen(["xdg-open", path])  # the desktop's own choice
        except OSError as problem:  # it could not be opened
            messagebox.showerror("Kestrel", str(problem), parent=self.root)  # say why

    def open_logs(self):  # File > Open the log folder
        os.makedirs(LOG_FOLDER, exist_ok=True)  # make sure it exists
        self.open_path(LOG_FOLDER)  # open it

    def show_notice(self, words):  # put up the idle-frequency warning (it does not hold anything up)
        self.close_notice()  # only one at a time
        self.notice = self.window("notice", "Kestrel - returning to the calling frequency")  # a small window of its own
        self.notice.attributes("-topmost", True)  # in front of everything, so it is seen
        ttk.Label(self.notice, text=words, wraplength=380, justify="left").pack(padx=16, pady=(14, 8))  # the warning
        button = ttk.Button(self.notice, text="OK", command=self.close_notice)  # OK takes the window away; it does not stop the return
        button.pack(pady=(0, 12))  # place it
        button.focus_set()  # Enter or Space presses it
        self.notice.bind("<Return>", lambda event: self.close_notice())  # Enter too
        self.notice.protocol("WM_DELETE_WINDOW", self.close_notice)  # so does its close box
        self.root.bell()  # a sound to draw attention

    def close_notice(self):  # take the idle-frequency warning away
        if self.notice is not None:  # one is showing
            self.notice.destroy()  # close it
            self.notice = None  # none is showing now

    def idle_warning(self, partner, left):  # the working thread says a contact ends in ten seconds (since 0.41)
        self.idle_calls.put((partner, left))  # shown by the window's own thread

    def show_idle_box(self, partner, left):  # put up the 10-second warning: Keep going or Disconnect (since 0.41)
        self.close_idle_box()  # only one at a time
        box = self.idle_box = self.window("idle", "Kestrel - contact ending")  # a small window of its own
        box.attributes("-topmost", True)  # in front of everything, so it is seen
        words = tk.StringVar()  # the countdown line
        ttk.Label(box, textvariable=words, font="KestrelMedium", wraplength=380, justify="left").pack(padx=16, pady=(14, 4))  # the warning
        ttk.Label(box, text=f"No messages have passed for a while. {partner} sees the same warning.\nKeep going sends a short KEEP GOING message, which restarts the timer at both stations.", font="KestrelSmall", wraplength=400, justify="left").pack(padx=16, pady=(0, 10))  # what the choices do
        buttons = ttk.Frame(box)  # the two choices
        buttons.pack(pady=(0, 12))  # under the words
        ttk.Button(buttons, text="Disconnect", command=lambda: (self.close_idle_box(), self.end_contact())).pack(side="left", padx=6)  # end the contact properly now
        keep = ttk.Button(buttons, text="Keep going", command=lambda: (self.close_idle_box(), self.keep_going(partner)))  # carry on
        keep.pack(side="left", padx=6)  # beside it
        keep.focus_set()  # Enter or Space presses it
        box.bind("<Return>", lambda event: (self.close_idle_box(), self.keep_going(partner)))  # Enter too
        box.protocol("WM_DELETE_WINDOW", self.close_idle_box)  # the close box: no choice made (the contact ends when the time runs out)
        ends = time.monotonic() + left  # when the contact ends
        self.root.bell()  # a sound to draw attention

        def tick():  # the countdown, once a second
            if self.idle_box is not box or not box.winfo_exists():  # closed meanwhile
                return  # stop counting
            seconds = int(ends - time.monotonic() + 0.5)  # what is left
            if seconds <= 0:  # time is up
                self.close_idle_box()  # the contact ends by itself (the working thread does it)
                return  # done
            words.set(f"Contact with {partner} ends in {seconds} s")  # the line
            box.after(1000, tick)  # again in a second

        tick()  # start counting

    def close_idle_box(self):  # take the 10-second warning away (since 0.41)
        if self.idle_box is not None:  # one is showing
            try:  # it may already be gone
                self.idle_box.destroy()  # close it
            except tk.TclError:  # gone
                pass  # nothing to close
            self.idle_box = None  # none is showing now

    def keep_going(self, partner):  # the warning's Keep going button (since 0.41)
        """Send a short KEEP GOING message to the partner: it counts as traffic at both stations, so both timers start again."""
        self.ask_station(lambda station: station.queue(KEEP_GOING_TEXT, partner) or True, f"{KEEP_GOING_TEXT} sent to {partner}: the contact carries on")  # queued in the station's own thread

    def show_me(self):  # show this station's own details at the top right
        call, grid = self.settings["call"] or "no callsign set", self.settings["grid"]  # what is set so far
        self.me.configure(text=f"{call}   {grid}" + ("" if self.settings["available"] else "   -   UNAVAILABLE"))  # callsign, grid locator, and whether the operator is away

    def available_key(self):  # Ctrl+U: the same as pressing the Available button
        self.available_var.set(not self.available_var.get())  # push it in or out
        self.available_toggled()  # and act on it

    def available_toggled(self):  # the operator is now available, or not
        self.settings["available"] = bool(self.available_var.get())  # remember it
        if self.station is not None:  # a station is listening
            self.station.available = self.settings["available"]  # it applies at once
        self.save_settings()  # keep it for next time
        self.show_me()  # show it at the top right
        if self.settings["available"]:  # back
            self.say("available for contacts: calls are shown for you to Respond, and your beacons take answers")  # say what that means
        else:  # away
            self.say("NOT available: a station calling you by name gets one short 'not available' reply; your beacons say you are not taking contacts")  # say what that means
        self.logbook.write("run", station=self.settings["call"], text="available" if self.settings["available"] else "not available", dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook

    def show_status(self, words, color):  # put the station's state on the band at the top
        """Show `words`; a lock is a solid green band, trouble holding it amber or red, anything else plain."""
        if color == "dark green":  # locked with a partner
            self.status.configure(text=words, bg=self.colors["status_ok"], fg=self.colors["status_fg"])  # on solid green (in the theme's shade): unmistakable
        elif color in ("dark orange", "red"):  # the link is in trouble, or something failed
            self.status.configure(text=words, bg=self.colors["status_bad"] if color == "red" else self.colors["status_warn"], fg=self.colors["status_fg"])  # on red or amber (in the theme's shades)
        else:  # every other state
            self.status.configure(text=words, bg=self.plain_color, fg=self.colors["accent"] if color == "dark blue" else self.colors["fg"])  # colored words on the ordinary background

    def say(self, text):  # add a line to the log (safe to call from any thread)
        self.lines.put(text)  # the window picks it up shortly

    def _write_log(self, clock, line):  # put one line into the log box, in the form now chosen
        text = line if self.details.get() else plain_line(line)  # the full line, or its plain form
        if text is not None:  # there is something to show
            self.log.insert("end", f"{clock}  {text}\n")  # add it with the time of day

    def redraw_log(self):  # the details switch was changed: draw the whole log again
        self.log.configure(state="normal")  # allow writing
        self.log.delete("1.0", "end")  # clear it
        for clock, line in self.history:  # every line so far
            self._write_log(clock, line)  # in the form now chosen
        self.log.see("end")  # keep the newest line in view
        self.log.configure(state="disabled")  # back to read-only

    def show_lines(self):  # move waiting log lines into the window
        while not self.lines.empty():  # every waiting line
            line = self.lines.get()  # the next waiting line
            clock = time.strftime("%H:%M:%S")  # the time of day it arrived
            self.history.append((clock, line))  # remember it, so the log can be redrawn
            del self.history[:-2000]  # keep only the last two thousand lines
            if self.idle_box is not None and any(mark in line for mark in ("sending message", "received message", "back on the calling frequency", "contact closed", "ending the contact")):  # traffic has resumed, or the contact has ended (the one-minute notice was replaced by the 10-second warning in 0.41)
                self.close_idle_box()  # the warning no longer applies
            plain = plain_line(line)  # the line as the operator reads it
            if plain:  # something to show
                self.ticker.configure(text=f"{clock}  {plain}"[:160])  # the newest line, in the status bar at the bottom (since 0.41)
            urgent = any(mark in line.lower() for mark in ("warning", "stopped by a problem", "not delivered", "no contact:", "could not"))  # something the operator must not miss
            if plain:  # shown in the status bar
                self.ticker.configure(foreground=self.colors["warn_fg"] if urgent else "")  # in the warning color; the Activity window no longer pops up for it (since 0.42R2)
            state = status_for(line)  # does it mark a change of state?
            if state is not None and state[0].startswith("LISTENING") and time.monotonic() < getattr(self, "hold_status", 0.0):  # back to listening just after news the operator should see
                pass  # leave the news on the band for a while
            elif state is not None and not (state[0] == "STOPPED" and self.next_mode is not None):  # yes (but a stop on the way to another mode is not worth showing)
                self.show_status(state[0], state[1])  # show the new state in its color
                if state[0].startswith(("NOT AVAILABLE", "NO ANSWER")):  # news the operator should not miss
                    self.hold_status = time.monotonic() + 30.0  # keep it on the band for half a minute
            elif "monitoring" in line.lower():  # the receive-only monitor has started
                self.show_status("MONITORING  -  receive only", "dark blue")  # say so
            self.log.configure(state="normal")  # allow writing
            self._write_log(clock, line)  # add the line to the log box
            self.log.see("end")  # keep the newest line in view
            self.log.configure(state="disabled")  # back to read-only
            try:  # also keep the full line in a file, so a run can be studied afterwards
                with open(side_file(".log"), "a", encoding="utf-8") as handle:  # the log file sits beside this panel's settings file
                    handle.write(f"{time.strftime('%Y-%m-%d')} {clock}  {line}\n")  # the line, with the date and time of day
            except OSError:  # the file could not be written
                pass  # the window still shows the line, which is what matters
        while not self.idle_calls.empty():  # a 10-second warning from the working thread (since 0.41)
            self.show_idle_box(*self.idle_calls.get())  # Keep going or Disconnect
        self.root.after(100, self.show_lines)  # look again in a tenth of a second

    # ---- what the working thread reports ----

    def power_w(self):  # the transmit power to put in the log
        """Return the power in watts: measured while transmitting if the radio says, else the radio's power setting, else None."""
        if self.tx_active and self.meters["watts"] is not None:  # measured now
            return self.meters["watts"]  # use it
        return self.meters["set_w"]  # the setting, or None if unknown

    def rig_name(self):  # the radio, for the log
        return self.settings["rig_text"] or (self.settings["rig_model"].split("  ", 1)[-1] if self.settings["rig_model"] else "")  # the operator's description, else the rig type

    def expected_calls(self):  # callsigns this station expects to hear (called from the receiving thread)
        """Return up to EXPECT_MOST callsigns: stations heard in the last 48 hours, most recent first, then saved contacts.

        The receiver tries them in the callsign fields of a weak control frame
        that fails alone (since 0.31R1), with the station's own callsign, the
        station it is calling and its partner, which the station adds itself.
        """
        calls = [row["call"] for row in self.heardlog.summary()] + list(self.contacts)  # heard lately, then saved (both safe to read from this thread)
        return [call for call in dict.fromkeys(calls) if call and call != self.settings["call"]][:EXPECT_MOST]  # no repeats, not this station, at most a few

    def known_grid(self, call):  # the grid locator last known for a station (since 0.35)
        """Return the grid of `call` from the contact book or the stations heard, or ""."""
        saved = (self.contacts[call] or {}).get("grid", "") if call in self.contacts else ""  # the contact book
        if saved:  # known there
            return saved  # use it
        return next((row.get("grid", "") for row in self.heardlog.summary() if row.get("call") == call and row.get("grid")), "")  # the stations heard

    def after_heard(self, call, grid, result):  # spotting and the prediction check (since 0.35; called from the working thread)
        """Queue a PSK Reporter spot of `call`, and check the prediction for its path, as the settings say."""
        grid = grid or self.known_grid(call)  # where it is, if known
        dial = self.dial_hz()  # the dial frequency, Hz
        spotter = self.spotter  # the spotter, when spotting is on
        if spotter is not None and np.isfinite(result.snr_db):  # spotting, and a reading to give
            spotter.add(call, dial + 1500.0 + result.offset_hz, result.snr_db, grid)  # queued (sent within about five minutes)
        if self.settings.get("prop_check", True) and grid and self.settings["grid"]:  # checking predictions
            name = band_of(dial / 1000.0)  # e.g. "40m"
            if name:  # an amateur band
                band, noise = f"{name[:-1]} m", self.settings.get("prop_noise", "RURAL")  # the band as P.533 names it, and the noise here
                usual = float(self.settings.get("prop_power_w") or self.settings.get("max_power_w") or 100)  # the power assumed when nothing better is known
                try:  # the other station's power, when it has said (its Rig and power message or telemetry, since 0.39)
                    theirs = float((self.contacts.get(call) or {}).get("power_w") or usual)  # in watts
                except (TypeError, ValueError):  # not a number
                    theirs = usual  # the usual figure
                propcheck.check(call, self.settings["grid"], grid, band, result.snr_db, theirs, noise, on_row=self.prop_gap)  # this station hearing it, in the background
                report = getattr((result.fields or {}).get("report"), "snr_db", None)  # how it heard this station, when the frame carries a report (since 0.39)
                if report is not None:  # it does
                    mine = self.power_w()  # this station's power as the radio measured it, if it did
                    propcheck.check(call, self.settings["grid"], grid, band, float(report), float(mine) if mine else usual, noise, direction="out", on_row=self.prop_gap)  # it hearing this station, in the background

    def prop_gap(self, row):  # a prediction check was recorded (called from its background thread; since 0.39)
        """Tell the operator, at most once an hour per station, when a station's measured SNR falls well short of the prediction, and what that points to."""
        call = row["call"]  # whose
        hour = row["utc"][:13]  # this hour
        if self.gap_said.get(call) == hour:  # said already this hour
            return  # once is enough
        gaps = propcheck.station_gaps(call)  # both ways, last 30 days
        if not propcheck.verdict(gaps):  # nothing worth saying
            return  # quiet
        self.gap_said[call] = hour  # remembered
        self.say(f"prediction check, {call}: {propcheck.describe_station(call)}")  # the Activity log (say is safe from any thread)

    def follow_spotter(self):  # keep the spotter in step with the settings and send when due (since 0.35)
        """Start, stop or tick the PSK Reporter spotter; called twice a second from follow_station."""
        wanted = bool(self.settings.get("psk_spot")) and bool(self.settings["call"]) and bool(self.settings["grid"])  # spotting on, with this station known
        if wanted and (self.spotter is None or (self.spotter.call, self.spotter.grid) != (self.settings["call"], self.settings["grid"])):  # needed, or this station changed
            if self.spotter is not None:  # an old one
                self.spotter.close()  # what it holds goes first
            self.spotter = pskspot.Spotter(self.settings["call"], self.settings["grid"], SPEC_VERSION)  # a new one
        elif not wanted and self.spotter is not None:  # turned off
            self.spotter.close()  # what it holds goes first
            self.spotter = None  # gone
        if self.spotter is not None:  # on
            if self.spotter.due():  # time to send
                threading.Thread(target=self.spotter.tick, daemon=True).start()  # off the window's thread

    def send_antenna(self, partner):  # a contact has locked: this station's antenna goes to the other, once per antenna (since 0.40)
        """Queue the message "ANT <antenna>" to `partner` when an antenna is chosen in Settings and it was not sent to `partner` before (a saved contact remembers; others get it every contact)."""
        antenna = self.settings.get("antenna", "")  # the antenna chosen in Settings > Station
        if not partner or not self.contacts.antenna_to_send(partner, antenna):  # nobody, nothing chosen, or already sent
            return  # nothing to send
        words = f"ANT {antenna}"  # the message the other station's contact book reads
        self.ask_station(lambda station: station.queue(words, to=partner) or True, f"sending {partner} this station's antenna: {antenna}")  # queued in the contact, in the station's own thread
        self.contacts.antenna_sent(partner, antenna)  # remembered, so it goes once

    def load_rig_names(self):  # the Hamlib model numbers and names, to name the rig a beacon carries (since 0.40)
        """Fill self.rig_names (number -> "Maker Model") from the rig control program's list, in the background."""
        program = rigctld_program(self.settings)  # the rig control program (the saved one if it still exists, since 0.42R1)
        if not program:  # none on this computer
            return  # beacons' rigs are named by number
        def job():  # the list can take a while the first time
            try:  # it may fail
                self.rig_names = {number: name for number, name in list_models(program)}  # kept
            except Exception:  # noqa: BLE001 - anything: names by number only
                pass  # left empty
        threading.Thread(target=job, daemon=True).start()  # in the background

    def rig_called(self, number):  # a beacon's rig type in words (since 0.40)
        """Return the rig a beacon's Hamlib model `number` stands for, such as "Yaesu FT-991 (Hamlib 1035)", or "" for 0."""
        if not number:  # not said
            return ""  # nothing
        name = self.rig_names.get(int(number), "")  # from the list, when it has arrived
        return f"{name} (Hamlib {number})" if name else f"Hamlib rig {number}"  # named, or by number

    def note_heard(self, result):  # a frame from some station decoded (called from the working thread)
        call = (result.fields or {}).get("origin") or (result.origin if result.frame_type == 1 else "")  # the callsign it carries: in a beacon, an answer, an identification or a fully addressed message
        station = self.station  # the running station, if any
        if not call and station is not None and result.link == station.link and station.partner:  # a frame inside the present contact carries only the link number
            call = station.partner  # it is from the partner
        if not call:  # it names nobody
            return  # nothing to note
        grid = (result.fields or {}).get("grid", "")  # its grid locator, if it carries one
        if getattr(result, "power_steps", None) is not None:  # power steps came before its beacon (since 0.38)
            self.steps_heard[call] = (time.time(), result.power_steps)  # kept for the Stations heard list
        kind = KIND.get(result.frame_type, "frame")  # what it was
        if (result.fields or {}).get("note"):  # a long-note frame (since 0.34), not a long beacon
            kind = "long " + ("receipt" if result.fields["note"] == "receipt" else "note")  # named for what it is
        self.heard.put((call, grid, result.snr_db, kind, dict(result.fields or {}), band_of(self.dial_hz() / 1000.0)))  # pass it to the window, with the frame's flags and the band it was heard on
        self.heardlog.add(call, grid, result.snr_db, result.level, kind, round(self.dial_hz() / 1000.0, 1))  # into the 48-hour log
        self.marks[call] = (1500.0 + result.offset_hz, signal_width_hz(result.level), time.monotonic())  # and onto the scope
        self.after_heard(call, grid, result)  # PSK Reporter and the prediction check (since 0.35)
        if result.frame_type == FRAME_TYPE_BEACON and ((result.fields or {}).get("rig") or (result.fields or {}).get("watts")):  # a beacon saying what it runs (since 0.40)
            self.contacts.from_beacon(call, self.rig_called(result.fields.get("rig")), result.fields.get("watts") or 0)  # into its contact record, when it is saved
        self.watch.kestrel_heard(1500.0 + result.offset_hz, signal_width_hz(result.level), f"{level_name(result.level)} {call}")  # the recognized signal there is a Kestrel frame (since 0.37)
        self.logbook.write("heard", direction="RX", station=self.settings["call"], **{"from": call}, text=kind, dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(result.level), snr_db=result.snr_db, fade=result.fade_index, offset_hz=result.offset_hz, rig=self.rig_name(),  # (continued)
                           report_db=getattr((result.fields or {}).get("report"), "snr_db", None))  # the logbook, from the advanced level up (report_db, how the sender heard this station, goes only to the contact book)

    def log_frame(self, result):  # every report from the receiver (called from the working thread), for the verbose log
        self.frames.station_result(result)  # the frame strip: a frame that passed with an earlier copy added, and the message's sender (since 0.37)
        self.note_their_report(result)  # the partner's report of this station's signal, for the contact bar (since 0.42)
        if not self.logbook.wants("frame"):  # not logging at that level
            return  # nothing to do
        name = KIND.get(result.frame_type, "frame")  # the kind of frame
        rx = self.audio.level()[0] if self.audio is not None else None  # the input level
        self.logbook.write("frame", direction="RX", station=self.settings["call"], text=f"{name} {'decoded' if result.ok else 'failed: ' + str(result.reason)}", dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(result.level), snr_db=result.snr_db, fade=result.fade_index, offset_hz=result.offset_hz, rig=self.rig_name(), rx_input_dbfs=rx, detail=describe(result))  # every detail

    def note_their_report(self, result):  # keep the partner's report of how it hears this station (called from the working thread; since 0.42)
        """Answers addressed to this station and acknowledgments inside a contact carry the other station's measurement of this
        station's last frame (SNR, fading, the level it asks for); keep the newest, with the time and who sent it."""
        fields = getattr(result, "fields", None) or {}  # the frame's control fields, if it is a control frame
        report = fields.get("report") if result.ok else None  # its channel report
        if report is None:  # not a frame that carries one
            return  # nothing to keep
        station = self.station  # the running station
        own = self.settings["call"].strip().upper()  # this station's callsign
        if result.frame_type == FRAME_TYPE_ANSWER and (fields.get("dest") or "").upper() == own:  # an answer or directed call to this station
            sender = (fields.get("origin") or "").upper()  # who measured this station
        elif result.frame_type == FRAME_TYPE_ACK and station is not None and station.partner and fields.get("link") == self.station_link(station):  # an acknowledgment inside this station's contact
            sender = station.partner  # the partner measured this station
        else:  # someone else's
            return  # not about this station
        self.their_report = (time.time(), sender, float(report.snr_db), float(report.fade_index), int(report.want_level))  # when, who, the SNR, the fading index, the level asked for

    def station_link(self, station):  # the running contact's link number, or None (since 0.42)
        """Return the station's link number; None if the station cannot say (it is read through the compiled library when in use)."""
        try:  # the compiled station answers through its library
            return station.link  # the short link number both stations put in their frames
        except Exception:  # not available
            return None  # unknown

    def note_near(self, result):  # a Kestrel signature heard but not readable (called from the working thread)
        self.logbook.write("heard", direction="RX", station=self.settings["call"], text="signature heard, too weak or faded to read", dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=f"{level_name(result.seen_level)}?", offset_hz=result.offset_hz, rig=self.rig_name(), detail=near_line(result))  # the logbook, from the advanced level up
        self.watch.kestrel_heard(1500.0 + result.offset_hz, signal_width_hz(result.seen_level), f"{level_name(result.seen_level)}? (not readable)")  # the recognized signal there looks like Kestrel (since 0.37)

    def signal_folder(self):  # where the signal log goes
        """Return (creating it if needed) the signal log folder, beside the logbook."""
        folder = os.path.join(LOG_FOLDER, "signal")  # beside the CSV logs
        os.makedirs(folder, exist_ok=True)  # make sure it exists
        return folder  # the folder

    def signal_log_report(self):  # File > Signal log report
        """Summarize the signal logs (all of them, or from a date the operator gives) into a text file beside them, and open it."""
        from tkinter import simpledialog  # a one-line question
        since = simpledialog.askstring("Kestrel - signal log report", "Report from which UTC date? (YYYY-MM-DD; leave blank for everything)", parent=self.root)  # the start date
        if since is None:  # canceled
            return  # nothing to do
        since = since.strip() or None  # blank means everything

        def job():  # the background part
            from tools import signal_report  # the report tool (imported here, so the panel starts as fast as before)
            folder = self.signal_folder()  # where the logs are
            try:  # the logs may be unreadable
                events, files = signal_report.load([folder], since=since)  # read them
                if not files:  # nothing logged yet
                    self.say("no signal logs yet: turn on Settings > Logging > Signal log, then run Listen or Monitor")  # say how to start one
                    return  # nothing to report
                path = os.path.join(folder, time.strftime("report_%Y%m%d_%H%M%SZ.txt", time.gmtime()))  # the report file
                with open(path, "w", encoding="utf-8") as handle:  # write it
                    handle.write("\n".join(signal_report.report(events)) + "\n")  # the report
                self.say(f"signal log report ({len(events)} events from {len(files)} file(s)) saved to {path}")  # say where
                self.root.after(0, lambda: self.open_path(path))  # and open it, from the window's own thread
            except (OSError, ValueError) as problem:  # unreadable
                self.say(f"could not make the signal log report: {problem}")  # say why

        threading.Thread(target=job, daemon=True).start()  # report without freezing the window

    def decode_recording(self):  # File > Decode a recording
        """Ask for a WAV file, play it through the receiver in the background, and list what it finds in the log window."""
        path = filedialog.askopenfilename(parent=self.root, title="Choose a recording to decode", initialdir=recordings_dir(data_dir()), filetypes=[("WAV recordings", "*.wav"), ("All files", "*.*")])  # which file
        if not path:  # none chosen
            return  # nothing to do

        def job():  # the background part
            from tools.decode_wav import decode_file, write_csv  # the decoder (imported here, so the panel starts as fast as before)
            try:  # the file may not be a usable WAV
                self.say(f"decoding {os.path.basename(path)} (this takes about as long as a minute of the recording takes the receiver, roughly half its length)")  # what is happening
                rows = decode_file(path, say=self.say)  # decode it, reporting each find in the log
                table = os.path.splitext(path)[0] + "_decoded.csv"  # the results table, beside the recording
                write_csv(rows, table)  # save it
                self.say(f"decode finished; results saved to {table}")  # say where
            except (OSError, ValueError, EOFError) as problem:  # not a WAV, or unreadable
                self.say(f"could not decode {os.path.basename(path)}: {problem}")  # say why

        threading.Thread(target=job, daemon=True).start()  # decode without freezing the window

    def transmitting(self, tx, keyed):  # the transmitter went on or off (called from the working thread)
        self.tx_active, self.tx_kind = keyed, (f"{tx.kind} {tx.note}" if tx.kind.startswith("long") else tx.kind) if keyed else ""  # note it, for the meters and the transmit scope's words (a long note says which try and frame, since 0.34)
        if keyed:  # a new transmission
            self.alc_warned = False  # it may be warned about once
            self.tx_readings = []  # the power and ALC read during it, for holding the power and spotting a sag (since 0.40R1)
        if not keyed:  # it has just gone off
            self.after_transmission(tx)  # hold the power for the next one, and say if it sagged (since 0.40R1)
            self.logbook.write("meters", direction="TX", station=self.settings["call"], text=f"after {tx.kind}", power_w=self.meters["watts"], alc=self.meters["alc"], swr=self.meters["swr"], tx_audio=round(self.sink.last_peak_db, 1) if self.sink else None)  # the meter readings taken during it (verbose)
            return  # nothing more
        event = {"beacon": "beacon", "long beacon": "beacon", "call": "call", "broadcast": "broadcast"}.get(tx.kind, "sent")  # beacons, calls and broadcasts are logged from advanced up; other frames only in verbose
        station = self.station  # the running station
        to = "ALL" if tx.kind in ("beacon", "long beacon", "broadcast") else (station.partner if station is not None else "")  # who it was for
        self.logbook.write(event, direction="TX", station=self.settings["call"], **{"from": self.settings["call"]}, to=to, text=f"{tx.kind} {tx.note}".strip(), dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(tx.level), rig=self.rig_name(), power_w=self.power_w(), tx_audio=round(20.0 * np.log10(max(float(self.settings["gain"] or 0.25), 1e-4)), 1))  # what went out

    def after_transmission(self, tx):  # a transmission has ended: hold the power, and report a sag (called from the working thread; since 0.40R1)
        """From the power read during the transmission: warn if it fell with the drive unchanged, and, when Settings > Station names a power to hold, set the drive for the next transmission."""
        readings = [(watts, alc) for watts, alc in getattr(self, "tx_readings", []) if watts >= 1.0]  # the readings with the transmitter up (the first and last are often 0)
        self.tx_readings = []  # used
        if len(readings) < 3 or self.sink is None:  # too short to judge, or nothing to adjust
            return  # left alone
        watts = sorted(w for w, _ in readings)  # the powers, in order
        middle = watts[len(watts) // 2]  # the median power of the transmission
        alc_most = max((a for _, a in readings if a is not None), default=0.0)  # the highest ALC seen
        change = power_hold.sag(readings)  # how the power moved from its first third to its last
        if change is not None:  # it fell a good deal
            self.say(f"warning: output power fell from {change[0]:.0f} W to {change[1]:.0f} W during that {tx.kind} with the drive unchanged; check the radio (its power setting, heat, supply voltage)")  # tell the operator
        gain = float(self.sink.gain)  # the drive it was sent at
        new, why = power_hold.next_gain(gain, middle, alc_most, self.settings.get("hold_power_w", ""), ALC_HIGH)  # the drive for the next one
        if new is None:  # holding is off, or the power is close enough
            return  # nothing to change
        self.sink.gain = new  # the next transmission uses it
        self.settings["gain"] = f"{new:.3f}"  # remembered with the settings
        self.root.after(0, lambda: self.tx_value.set(new))  # the transmit slider follows (from the window's own thread)
        self.say(f"power hold: {middle:.0f} W out, {why}; drive {gain:.3f} -> {new:.3f}")  # say what was done

    def poll_radio(self, address):  # read the radio's power setting and meters (a thread of its own while a station runs)
        try:  # rig control may refuse
            rig = RigCtl(address)  # a connection of its own, so it never gets in the way of tuning and keying
        except (OSError, ValueError):  # no connection
            return  # no readings, then
        unsupported = set()  # readings this radio or Hamlib has refused
        last_setting = 0.0  # when the power setting was last read

        def read(name):  # one reading, or None
            if name in unsupported:  # refused before
                return None  # do not ask again
            try:  # the radio may not have it
                return rig.level(name)  # the reading
            except (OSError, RuntimeError, ValueError):  # it does not
                unsupported.add(name)  # remember that
                return None  # no reading

        try:  # until told to stop
            while not self.poller_stop.is_set():  # the station is running
                if self.tx_active:  # transmitting: read the meters
                    self.meters["watts"], self.meters["alc"], self.meters["swr"] = read("RFPOWER_METER_WATTS"), read("ALC"), read("SWR")  # power out, ALC and SWR
                    alc = self.meters["alc"]  # the ALC reading, 0 to 1 of the radio's scale
                    log = self.signal_log  # the run's signal log (read once: the run may end meanwhile)
                    if log is not None:  # one is kept
                        log.meters(self.meters["watts"], alc, self.meters["swr"])  # every reading during the transmission
                    if self.meters["watts"] is not None:  # the radio gave its power
                        self.tx_readings.append((float(self.meters["watts"]), alc))  # kept for after_transmission (since 0.40R1)
                    if alc is not None and alc >= ALC_HIGH and not self.alc_warned:  # the audio is driving the radio too hard
                        self.alc_warned = True  # once per transmission is enough
                        self.say(f"warning: the radio's ALC reads {alc:.2f} of full scale; lower the transmit slider (Ctrl+J) until ALC barely moves, or the tones will be distorted")  # tell the operator what to do
                    time.sleep(0.7)  # a little under once a second
                    continue  # and again
                if time.monotonic() - last_setting > 20.0:  # every twenty seconds while receiving
                    setting = read("RFPOWER")  # the power setting, 0 to 1 of full power
                    if setting is not None:  # the radio said
                        self.meters["set_w"] = setting * float(self.settings["max_power_w"] or 100)  # in watts
                    last_setting = time.monotonic()  # remember when
                time.sleep(0.5)  # a short nap
        finally:  # always hang up
            rig.close()  # close the connection

    # ---- keeping the window in step with the station ----

    def follow_station(self):  # keep the message lists, the readings, the beacon and the logbook in step with the station
        self.show_note_events()  # long notes received, delivered, resent or failed (since 0.34)
        self.follow_spotter()  # PSK Reporter spotting (since 0.35)
        while not self.heard.empty():  # every station heard since the last look
            call, grid, snr, kind, fields, band = self.heard.get()  # who, where, how strong, what it sent, its flags, and the band it was heard on
            if call in self.contacts and band and self.contacts[call].get("band") != band:  # a saved contact heard on another band
                self.contacts.put(call, band=band)  # remember the band (and keep it in the file)
            known = (self.contacts.get(call, {}).get("grid", "") or "").strip()  # the locator saved for a contact, if any
            if call in self.contacts and grid and known[:4].upper() != grid[:4].upper():  # a saved contact sent a locator that is new or different (the propagation window works from it)
                self.contacts.put(call, grid=grid)  # keep the locator it sent (a finer six-character one typed by hand stays while the square agrees)
                self.say(f"{call}'s grid locator is {grid}" + (f" (was {known})" if known else "") + "; saved in its contact record")  # tell the operator
            if band and any(self.to_send.set(row, "to") == call for row in self.to_send.get_children()):  # a station there are messages for
                self.refresh_send_bands()  # show the band it was just heard on
            if kind in ("beacon", "answer"):  # a beacon or an answer says whether its sender takes contacts
                self.availability[call] = (bool(fields.get("listening", True)), time.time())  # a presence beacon says not; anything else says yes
            if kind == "long beacon":  # a long beacon says so in its own flag
                self.availability[call] = (bool(fields.get("available", True)), time.time())  # available or not
                if call != self.settings["call"]:  # someone else
                    self.beacon_heard(call, grid, snr, dict(fields))  # show it to the operator (nobody answers a long beacon by itself)
            if kind == "beacon" and call != self.settings["call"] and fields.get("listening", True):  # a station calling for a partner
                self.beacon_heard(call, grid, snr, fields)  # offer it to the operator
            elif kind == "answer" and fields.get("directed") and fields.get("dest") == self.settings["call"].strip().upper():  # a station calling this one by name
                self.beacon_heard(call, grid, snr, dict(fields, you=True))  # offer it to the operator too, marked as a call to this station
            if kind == "mail notice":  # a station says whom it holds mail for
                if call_hash(self.settings["call"]) in fields.get("held", []):  # it holds mail for this station
                    self.say(f"{call} holds mail for you; it will be delivered when you work {call} (Listen answers its beacon by itself, or select it and press Respond, Ctrl+Y)")  # tell the operator
            values = ("*" if call in self.contacts else "", call, grid or (self.stations.set(self.heard_rows[call], "grid") if call in self.heard_rows else ""), band, f"{snr:+.0f} dB", time.strftime(HEARD_TIME), kind)  # the row's contents (a grid learned earlier is kept)
            if call in self.heard_rows:  # already listed
                self.stations.item(self.heard_rows[call], values=values)  # bring its row up to date
                self.stations.move(self.heard_rows[call], "", 0)  # and move it to the top: most recently heard first
            else:  # a new callsign
                self.heard_rows[call] = self.stations.insert("", 0, values=values)  # add it at the top
                self.refresh_to()  # and offer it in the To box
            if kind == "mail notice":  # its status column says whom it holds mail for
                self.mail_notices[call] = (time.time(), dict(fields))  # kept for the status column, which is refreshed every few seconds
        station = self.tracked  # the station being followed, running or just finished
        if station is not None and station.unavailable_from:  # a station we called says its operator is away
            self.availability[station.unavailable_from] = (False, time.time())  # note it
            station.unavailable_from = ""  # once
        self.follow_mail()  # mail handed on, delivered, held or expired
        if station is not None:  # there is one
            self.follow_contact(station)  # the logbook's view of the contact
            while self.marked < len(station.delivered):  # a message has been delivered since the last look
                text = station.delivered[self.marked]  # which one
                self._advance(text, "delivered " + time.strftime("%H:%M"))  # mark its row
                self.chat_delivered(text)  # a tick beside it in the Chat window (since 0.42)
                if self.contact is not None:  # in a contact
                    self.contact["sent"] += 1  # count it
                self.logbook.write("message", direction="TX", station=self.settings["call"], **{"from": self.settings["call"]}, to=station.partner, text=text, dial_khz=round(self.dial_hz() / 1000.0, 1), level=f"L{station.tx_level}", rig=self.rig_name(), power_w=self.power_w())  # the logbook
                self.marked += 1  # one more accounted for
            if station.plan and self.station is station:  # a message is on its way right now
                self._advance(station.plan_text, "sending")  # show that on its row
            if self.station is station and not station.broadcasts:  # no broadcast is waiting in the running station
                for row in self.to_send.get_children():  # look for one shown as waiting
                    if self.to_send.set(row, "state") == "broadcast when idle":  # it has gone out
                        self.to_send.set(row, "state", "sent " + time.strftime("%H:%M"))  # say so
            while self.shown_b < len(station.bulletins):  # a broadcast (or an addressed message) has arrived since the last look
                origin, dest, text = station.bulletins[self.shown_b]  # who sent it, who it was for, and what it says
                self.received.insert("", "end", values=(time.strftime(HEARD_TIME), f"{origin} to {dest}", text))  # add it to the received list
                self.received.yview_moveto(1.0)  # keep the newest row in view
                self.logbook.write("broadcast" if dest == "ALL" else "message", direction="RX", station=self.settings["call"], **{"from": origin}, to=dest, text=text, dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook
                self.note_telemetry(origin, text)  # it may be telemetry
                self.shown_b += 1  # one more shown
            while self.shown < len(station.inbox):  # a message has arrived since the last look
                text = station.inbox[self.shown]  # the message
                whole, so_far, got, expected = self.joiner.feed(station.partner, text)  # a piece of a chained message waits for the rest (since 0.42)
                if expected > 1:  # a piece of a chained message
                    shown = whole if whole is not None else f"{so_far}   [{got} of {expected} parts so far]"  # the message so far
                    row = self.chain_rows.get(station.partner)  # its row, if it has one
                    if row is not None and self.received.exists(row):  # it does
                        self.received.set(row, "text", shown)  # brought up to date
                    else:  # the first piece
                        self.chain_rows[station.partner] = self.received.insert("", "end", values=(time.strftime(HEARD_TIME), station.partner, shown))  # a row of its own
                    self.received.yview_moveto(1.0)  # keep the newest row in view
                    if whole is None:  # more to come
                        self.shown += 1  # this piece is accounted for
                        continue  # the logbook gets the whole message once it is complete
                    self.chain_rows.pop(station.partner, None)  # the chain is complete
                    text = whole  # the whole message, for the logbook
                    self.chat_line(station.partner, text, mine=False)  # into the Chat window, whole (since 0.42)
                else:  # an ordinary message
                    self.received.insert("", "end", values=(time.strftime(HEARD_TIME), station.partner, text))  # add it to the received list
                    self.chat_line(station.partner, text, mine=False)  # and into the Chat window (since 0.42)
                self.received.yview_moveto(1.0)  # keep the newest row in view
                snr = station.history[-1][0] if station.history else None  # the latest reading of the partner's signal
                if self.contact is not None:  # in a contact
                    self.contact["received"] += 1  # count it
                self.logbook.write("message", direction="RX", station=self.settings["call"], **{"from": station.partner}, to=self.settings["call"], text=text, dial_khz=round(self.dial_hz() / 1000.0, 1), level=f"L{station.want}", snr_db=snr, rig=self.rig_name())  # the logbook
                self.note_telemetry(station.partner, text)  # it may be telemetry
                self.shown += 1  # one more shown
            if self.station is station and station.state in LOCKED:  # in a contact
                where = f" on the working frequency ({station.offset_hz / 1000.0:+.1f} kHz)" if station.offset_hz else ""  # say so when the pair have left the calling frequency
                if station.state == "LOCKED":  # the link is healthy
                    self.show_status(f"LOCKED with {station.partner}{where}  -  link held, speed adjusting to keep it clear" if not where else f"LOCKED with {station.partner}{where}", "dark green")  # solid green
                elif station.state == "DEGRADED":  # frames have been failing
                    self.show_status(f"LOCKED with {station.partner}  -  signal worsening, slowing down to hold the link", "dark orange")  # amber
                else:  # the partner has gone quiet
                    self.show_status(f"LOST CONTACT with {station.partner}  -  probing at the slowest level to recover the link", "dark orange")  # amber
                heard = "no reading yet"  # until the partner's first frame is measured
                if station.history:  # there is a reading
                    snr, fade = station.history[-1][:2]  # the newest reading of the partner's signal (the third value, the spread, is shown below from the last frame)
                    heard = f"partner heard at {snr:+.0f} dB, {'steady' if fade <= 0.15 else 'fading'} ({fade:.2f})"  # strength, and whether it is fading
                    spread = getattr(getattr(station, "last_result", None), "spread_hz", float("nan"))  # the Doppler spread of the partner's last frame (since 0.35)
                    if spread == spread:  # read (not NaN)
                        heard += f", spread {spread:.1f} Hz"  # shown too
                self.fill_contact_bar(station, heard)  # the contact bar (since 0.41; one line of text before)
                self.release_held(station)  # chained messages for this partner go once on a working channel (since 0.42)
            else:  # not in a contact
                self.fill_contact_bar(None, "")  # nothing to report
        self.follow_beacon()  # the repeating beacon's label, and its automatic stop
        self.follow_calling()  # age the Stations calling window
        self.root.after(500, self.follow_station)  # look again in half a second

    def fill_contact_bar(self, station, heard):  # the contact bar's six readings (since 0.41)
        """Show the partner, how each side hears the other, the speed levels, the traffic and the idle countdown; dashes when there is no contact."""
        values = dict.fromkeys(self.bar_values, "-")  # every reading blank
        notes = self.long_notes  # a long contact, when there is one
        long_partner = notes.partner if notes is not None else None  # its partner
        if station is not None:  # a contact with the short frames
            partner = station.partner  # who
            grid = (self.contacts.get(partner) or {}).get("grid") or (self.stations.set(self.heard_rows[partner], "grid") if partner in self.heard_rows and self.stations.exists(self.heard_rows[partner]) else "")  # its grid, from the contact record or the stations heard
            far = distance_bearing(self.settings["grid"], grid) if grid else None  # how far
            values["partner"] = f"{partner}  {grid}" + (f"  {far[0]:,.0f} mi" if far else "")  # who, where, how far
            values["you_hear"] = heard.replace("partner heard at ", "") if heard else "-"  # how this station hears the partner
            report = getattr(self, "their_report", None)  # the partner's latest report of this station, if any (since 0.42)
            if report is not None and report[1] == partner and time.time() - report[0] < 600:  # from this partner, within ten minutes
                fade = report[3]  # its fading index (NaN when not measured)
                values["they_hear"] = f"{report[2]:+.0f} dB, " + ("steady" if fade == fade and fade <= 0.15 else "fading") + f"  \u00b7  asks L{report[4]}"  # how the partner hears this station, from its own report
            else:  # no report yet
                values["they_hear"] = f"asks for L{station.tx_level}"  # the level it asks for says something until the first report arrives
            values["speed"] = f"L{station.tx_level} you  \u00b7  L{station.want} them"  # the two levels
            values["traffic"] = f"{len(station.outbox)} to send  \u00b7  {len(station.inbox)} in"  # the messages
            left = self.idle_watch.remaining if self.idle_watch is not None else None  # seconds before the contact ends with no messages
            if left is not None:  # known
                extra = "  (Keep-Alive)" if station.moved and self.settings.get("keep_alive") and not self.idle_watch.extended else ""  # Keep-Alive will add three minutes on a working channel
                values["timer"] = f"{int(left) // 60}:{int(left) % 60:02d}{extra}"  # the countdown
        elif long_partner:  # a long contact (since 0.41)
            values["partner"] = f"{long_partner}  (long frames)"  # who, and how
            values["traffic"] = f"{sum(1 for note in notes.outgoing if note.dest == long_partner)} long notes to send"  # what is waiting for it
        for name, label in self.bar_values.items():  # each reading
            label.configure(text=values[name])  # shown

    def follow_contact(self, station):  # notice a contact starting and ending, for the logbook
        running = self.station is station  # the station is still on the air
        in_contact = running and station.state in LOCKED and bool(station.partner)  # a contact is under way
        if in_contact and (self.contact is None or self.contact["call"] != station.partner):  # a new contact
            if self.contact is not None:  # the previous one ended unseen
                self.finish_contact()  # log it
            grid = self.contacts.get(station.partner, {}).get("grid", "") or (self.stations.set(self.heard_rows[station.partner], "grid") if station.partner in self.heard_rows else "")  # its grid locator, if known
            self.contact = {"call": station.partner, "start": time.time(), "end": time.time(), "dial_khz": self.dial_hz() / 1000.0, "grid": grid, "sent": 0, "received": 0, "best_level": 0, "snr": None}  # the contact so far
            self.logbook.write("contact start", direction="--", station=self.settings["call"], **{"from": self.settings["call"]}, to=station.partner, text=f"locked; role {station.role}", dial_khz=round(self.dial_hz() / 1000.0, 1), rig=self.rig_name(), power_w=self.power_w())  # the logbook
            named, anyone = self.waiting_for(station.partner)  # the rows in Messages to send that could go in this contact
            held = sum(1 for to in list(station.outbox_to) if to is None or to == station.partner)  # and what the station itself holds for this partner
            self.say(f"locked with {station.partner}: {held} message(s) ready to send to it" + (f" (the list shows {named + anyone} waiting: the difference is a fault, please report it)" if named + anyone > held else ""))  # say what will go, and flag a list that disagrees with the station (since 0.40R2)
            self.send_antenna(station.partner)  # this station's antenna to the other, once (since 0.40)
        if in_contact:  # under way
            self.contact["end"] = time.time()  # it lasts at least until now
            self.contact["best_level"] = max(self.contact["best_level"], station.tx_level, station.want)  # the fastest level used
            if station.history:  # the partner has been measured
                self.contact["snr"] = station.history[-1][0]  # the latest reading
        elif self.contact is not None:  # it has ended
            self.finish_contact()  # log it

    def finish_contact(self):  # a contact has ended: the logbook and the ADIF file
        record = dict(self.contact, end=time.time(), my_call=self.settings["call"], my_grid=self.settings["grid"], power_w=self.meters["set_w"], rig=self.rig_name(), signal=SIGNAL_VERSION)  # everything the ADIF record needs
        self.contact = None  # no contact now
        self.logbook.write("contact end", direction="--", station=self.settings["call"], **{"from": self.settings["call"]}, to=record["call"], text=f"{record['sent']} sent, {record['received']} received, {record['end'] - record['start']:.0f} s", dial_khz=round(record["dial_khz"], 1), snr_db=record["snr"], level=f"L{record['best_level']}", rig=record["rig"], power_w=record["power_w"])  # the logbook
        self.logbook.contact(record)  # and the contacts file

    def follow_beacon(self):  # the label beside the beacon button, and the automatic stop
        if not self.beacon_wanted:  # off
            self.beacon_label.configure(text="off")  # say so
            return  # nothing more
        if self.mode == "off" and self.next_mode is None and (self.worker is None or not self.worker.is_alive()):  # the station has stopped (a problem, or the operator)
            self.beacon_var.set(False)  # release the button
            self.beacon_off("repeating beacon stopped: the station is not running")  # nothing can be sent
            return  # done
        every = self.beacon_every()  # minutes between rounds
        stop_after = int(self.settings["beacon_autostop_min"])  # minutes without the operator before it stops itself (0 = never)
        idle = time.monotonic() - self.last_input  # how long since a key or the mouse was used
        if stop_after and idle >= stop_after * 60:  # nobody has been at the station for too long
            self.beacon_var.set(False)  # release the button
            self.beacon_off(f"repeating beacon stopped: no keyboard or mouse use for {stop_after} minutes")  # and stop, saying why
            self.show_status("BEACON STOPPED  -  nobody at the station", "dark orange")  # on the band too
            return  # done
        note = self.beacon_note  # what the station thread says
        if note == "waiting":  # idle and waiting for the next round
            left = max(0, int(self.beacon_due - time.monotonic()))  # seconds to go
            note = f"next beacon in {left // 60}:{left % 60:02d}"  # as minutes and seconds
        self.beacon_label.configure(text=f"every {every} min: {note}")  # show it

    # ---- the station's own thread asks here what the window wants ----

    def tick(self, station, now):  # called by the live loop once every tenth of a second, in the station's own thread
        self.station_now = now  # the station's clock, for requests that write to its log
        station.power_steps = self.settings.get("beacon_type") == "stepped"  # power steps before each short beacon, when chosen (since 0.38; kept in Python by both stations)
        station.rig = beacon_rig(self.settings.get("rig_model", ""))  # this station's rig type, the Hamlib model number, for each beacon (0 with no rig chosen; since 0.40)
        station.watts = beacon_watts(self.meters["set_w"] or self.settings.get("max_power_w") or 0)  # its power: the radio's setting when rig control reads it, else the full power from Settings (since 0.40)
        with self.actions_lock:  # take the waiting requests
            waiting, self.actions = self.actions, []  # all of them
        left = [action for action in waiting if not action(station)]  # do each; keep any that cannot be done yet
        with self.actions_lock:  # put back the ones still waiting
            self.actions = left + self.actions  # ahead of any added meanwhile
        if not self.beacon_wanted:  # the repeating beacon is off
            return  # nothing more to do
        every_s = 60.0 * self.beacon_every()  # seconds between rounds
        long_type = self.settings.get("beacon_type") == "long"  # long beacons instead of call-ups
        clock = time.monotonic()  # the clock the due time is kept on
        in_contact = station.state in LOCKED or station.role == "caller" or (station.role == "answerer" and station.pending is not None)  # a contact under way, a directed call, or an answer waiting to be confirmed
        if in_contact:  # busy with another station
            self.beacon_due = clock + every_s  # the interval starts again once the contact is over
            self.beacon_note = "paused during the contact"  # say so
        elif station.role == "beaconer":  # a beacon round is under way
            self.beacon_note = "beaconing now, listening for answers"  # say so
        elif station.long_waiting is not None:  # a long beacon is about to go
            self.beacon_note = "sending a long beacon"  # say so
        elif station.state == "IDLE" and station.pending is None and not station.broadcasts and clock >= self.beacon_due:  # free, and the round is due
            if long_type:  # a long beacon: about a minute, and nobody answers
                station.long_beacon()  # queue it; the station sends it at once
                self.beacon_note = "sending a long beacon"  # say so
            else:  # a short beacon: a call-up others can answer
                station.beacon_once()  # one beacon, with its reply window, then back to listening
                self.beacon_note = "beaconing now, listening for answers"  # say so
            self.beacon_due = clock + every_s  # the next one
        else:  # waiting for the next round
            self.beacon_note = "waiting"  # the window works out the time left

    def cancel_calls(self):  # forget any directed call still waiting for the station to be free
        with self.actions_lock:  # one at a time
            waiting = [action for action in self.actions if getattr(action, "kind", "") == "call"]  # the calls
            self.actions = [action for action in self.actions if getattr(action, "kind", "") != "call"]  # everything else stays
        for action in waiting:  # each canceled call
            self.say(f"call to {action.target} canceled")  # say so

    def ask_station(self, action, words):  # hand a request to the station's own thread
        with self.actions_lock:  # one at a time
            self.actions.append(action)  # the station thread does it at its next look
        if words:  # something to tell the operator
            self.say(words)  # tell them

    # ---- operating ----

    def in_contact(self):  # is a contact under way?
        station = self.station  # the running station, if any
        return station is not None and station.state in LOCKED  # locked, or trying to keep the lock

    def autostart(self):  # the panel has just opened
        mode = self.settings["start_mode"]  # what to do on opening
        if mode == "off":  # nothing
            self.show_status("OFF  -  press F2 to listen", "plain")  # say how to start
            return  # done
        if self.missing_setup(mode):  # the settings are not filled in yet
            self.awaiting_setup = True  # start once they are saved
            self.show_status("SETTINGS NEEDED  -  fill them in to start", "dark orange")  # say so
            messagebox.showinfo("Kestrel", "Welcome to Kestrel.\n\nEnter your callsign, grid locator, radio and sound devices in Settings. The panel starts listening as soon as you save them.", parent=self.root)  # explain
            self.settings_window(0)  # open Settings
            return  # wait for the save
        self.set_mode(mode)  # start

    def missing_setup(self, mode):  # what a mode needs that has not been set
        """Return True if `mode` cannot start because the callsign, grid or receive audio device has not been set."""
        if not self.settings["audio_in"]:  # every mode needs the receive audio
            return True  # missing
        return mode == "listen" and not (self.settings["call"] and self.settings["grid"] and self.settings["audio_out"])  # listening (which may transmit) needs a callsign, a locator and the transmit audio too

    def set_mode(self, mode):  # Listen, Monitor or Off was chosen
        self.mode_var.set(mode)  # show the choice on the buttons and in the menu
        if mode == self.mode and (mode == "off" or (self.worker is not None and self.worker.is_alive())):  # already doing that
            return  # nothing to change
        if self.in_contact() and not messagebox.askyesno("Kestrel", f"A contact with {self.station.partner} is in progress. Stop it without closing it properly?", parent=self.root):  # do not drop a contact by accident
            self.mode_var.set(self.mode)  # put the buttons back
            return  # leave it running
        if mode != "listen":  # a call can only be made by a listening station
            self.cancel_calls()  # so any call still waiting is canceled
        if mode != "listen" and self.beacon_wanted:  # the repeating beacon needs a listening station
            self.beacon_var.set(False)  # release its button
            self.beacon_off("repeating beacon stopped")  # and stop it
        if self.worker is not None and self.worker.is_alive():  # something is running
            self.next_mode = mode  # start the new mode once it has stopped
            self.stop.set()  # ask it to stop
            self.root.after(100, self._when_stopped)  # and watch for that
        else:  # nothing is running
            self._begin(mode)  # start straight away

    def _when_stopped(self):  # waiting for the running mode to stop before starting another
        if self.worker is not None and self.worker.is_alive():  # not yet
            self.root.after(100, self._when_stopped)  # look again shortly
            return  # wait
        mode, self.next_mode = self.next_mode, None  # the mode to start
        if mode is not None:  # there is one
            self._begin(mode)  # start it

    def _begin(self, mode):  # start a mode, with nothing else running
        self.mode = mode  # what is running now
        self.mode_var.set(mode)  # show it
        if mode == "off":  # nothing to run
            self.show_status("OFF  -  not receiving or transmitting", "plain")  # say so
            return  # done
        if self.missing_setup(mode):  # something is not set
            self.mode = "off"  # cannot start
            self.mode_var.set("off")  # show it
            messagebox.showinfo("Kestrel", "Enter your callsign, grid locator and sound devices first, under Settings.", parent=self.root)  # say so
            self.awaiting_setup = True  # start once they are saved
            self.settings_window(0)  # and open the window
            return  # nothing started
        entry = self.selected()  # the frequency chosen
        if mode == "listen" and entry["dial_khz"] < 30000.0 and in_data_segment(entry["dial_khz"]) is None:  # Listen can transmit, and this frequency is outside the amateur data segments
            self.mode = "off"  # cannot start
            self.mode_var.set("off")  # show it
            messagebox.showerror("Kestrel", f"{entry['dial_khz']:.1f} kHz puts the signal outside the U.S. amateur data segments, so Kestrel will not transmit there.\nChoose another frequency (Operate > Choose frequency), or use Monitor to receive only.", parent=self.root)  # say why, and what to do
            return  # nothing started
        try:  # the chosen sound devices may have gone away
            job = self.prepare()  # everything the working thread needs
        except ValueError as problem:  # a device is not connected
            self.mode = "off"  # cannot start
            self.mode_var.set("off")  # show it
            messagebox.showerror("Kestrel", f"{problem}. Choose the sound devices under Settings > Audio.", parent=self.root)  # say which, and where to fix it
            return  # nothing started
        self.worker = threading.Thread(target=self.run, args=(mode, job), daemon=True)  # the working thread, with everything it needs
        self.worker.start()  # go

    def ensure_listening(self, why):  # a request needs a station that can transmit
        """Make sure Listen is running (switching to it if needed) and return True; False if it cannot be started."""
        if self.mode == "listen" and self.next_mode is None:  # already listening
            return True  # fine
        if self.missing_setup("listen"):  # cannot transmit yet
            messagebox.showinfo("Kestrel", "Enter your callsign, grid locator and sound devices first, under Settings.", parent=self.root)  # say so
            self.settings_window(0)  # open the window
            return False  # nothing started
        self.say(f"switching to Listen to {why}")  # explain
        self.set_mode("listen")  # switch
        return self.mode_var.get() == "listen"  # unless the operator backed out

    def beacon_key(self):  # F5: the same as pressing the beacon button
        self.beacon_var.set(not self.beacon_var.get())  # push it in or out
        self.beacon_toggled()  # and act on it

    def beacon_every(self):  # minutes between beacon rounds
        """Return the repeat interval in minutes: the setting, but never under LONG_EVERY_MIN for long beacons."""
        every = int(self.settings["beacon_every_min"])  # the setting
        return max(every, LONG_EVERY_MIN) if self.settings.get("beacon_type") == "long" else every  # long beacons hold the frequency a minute each, so they go less often

    def beacon_words(self):  # the beacon button's label
        """Return the label for the beacon button: short or long."""
        return "Long beacon (reach)" if self.settings.get("beacon_type") == "long" else "Beacon (call anyone)"  # which kind

    def beacon_type_changed(self):  # Operate > Beacon type
        """Switch between short and long beacons; a repeating beacon carries on with the new kind at its next round."""
        self.settings["beacon_type"] = self.beacon_type_var.get()  # remember the choice
        self.save_settings()  # keep it
        self.beacon_button.configure(text=self.beacon_words())  # relabel the button
        long_type = self.settings["beacon_type"] == "long"  # which kind now
        self.say(f"beacon type: long (about 60 s, heard much further; nobody answers; every {LONG_EVERY_MIN} min at most)" if long_type else "beacon type: short (a call-up others can answer)")  # confirm

    def beacon_toggled(self):  # the beacon button was pushed in or out
        if not self.beacon_var.get():  # pushed out
            self.beacon_off("repeating beacon stopped by the operator")  # stop
            return  # done
        if not self.ensure_listening("beacon"):  # the beacon needs a listening station
            self.beacon_var.set(False)  # release the button
            return  # nothing started
        self.settings["beacon_every_min"] = max(BEACON_MIN, min(BEACON_MAX, int(self.settings["beacon_every_min"])))  # the interval, kept within its limits, and stored that way
        every = self.beacon_every()  # the interval for this kind of beacon
        self.beacon_due = time.monotonic()  # the first round goes as soon as the station is free
        self.beacon_note = "starting"  # until the station thread takes over
        self.last_input = time.monotonic()  # the operator is here now
        self.beacon_wanted = True  # on
        stop_after = int(self.settings["beacon_autostop_min"])  # the automatic stop
        self.say(f"repeating {self.settings.get('beacon_type', 'short')} beacon on: every {every} minutes" + (f", stopping by itself after {stop_after} minutes with no keyboard or mouse use" if stop_after else ""))  # confirm
        self.logbook.write("run", station=self.settings["call"], text=f"repeating beacon on, every {every} min", dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook

    def beacon_off(self, words):  # stop the repeating beacon (a round already under way finishes)
        if self.beacon_wanted:  # it was on
            self.beacon_wanted = False  # off
            self.say(words)  # say why
            self.logbook.write("run", station=self.settings["call"], text=words, dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook
        self.beacon_note = ""  # nothing to show
        self.beacon_label.configure(text="off")  # beside the button

    def call_to(self):  # call the station named in the To box
        target = self.to.get().strip().upper()  # who to call
        if not target:  # nobody
            messagebox.showinfo("Kestrel", "Type the callsign to call in the To box first (Ctrl+L).", parent=self.root)  # say so
            return  # nothing to do
        if target == "ALL":  # every station: nobody can be called that way
            messagebox.showinfo("Kestrel", "A call goes to one station. To reach every station, use Broadcast to ALL or a long note to ALL; to call for anyone, use Beacon (F5).", parent=self.root)  # say what does that
            return  # nothing to do
        if target == self.settings["call"].strip().upper():  # this station's own callsign
            messagebox.showinfo("Kestrel", f"{target} is this station's own callsign.\n\nPut the callsign of the station you want to reach in the To box. Only a station using exactly that callsign will answer.", parent=self.root)  # say so, and what to do
            return  # nothing to do
        if not self.ensure_listening(f"call {target}"):  # a call needs a listening station
            return  # nothing started

        station = self.station  # the running station, if any
        busy = station is not None and (station.state != "IDLE" or station.pending is not None or station.role != "answerer")  # it cannot call this moment
        if self.in_contact():  # a contact is under way: the call follows it
            words = f"calling {target} when the contact with {station.partner} is over"  # say when
        elif busy or station is None:  # a beacon round, an answer, or the station still starting
            words = f"calling {target} as soon as the station is free (dropped if a contact starts first)"  # say when, and the condition
        else:  # free now
            words = ""  # the station's own log line says it is calling
        self.ask_station(call_request(target, self.in_contact(), self.say), words)  # hand it over

    def end_contact(self):  # the End contact button
        station = self.station  # the station running at this moment, if any
        if station is None or station.state not in LOCKED:  # there is no contact to end
            self.stop_calling()  # but a call or beacon round may be under way: stop that instead
            return  # nothing more to do
        station.end()  # close once any traffic under way is finished
        self.say("ending the contact: closing identification will be sent when the current exchange is done")  # confirm

    def stop_calling(self):  # Esc, the Stop calling button: stop what this station started that has not made a contact
        """Stop a directed call (Respond, Call station), a beacon round, a long beacon or waiting broadcasts, cutting such a transmission short on the air. A contact in progress is left to End contact."""
        self.cancel_calls()  # calls still waiting for the station to be free
        if self.beacon_wanted:  # the repeating beacon is on
            self.beacon_var.set(False)  # its button comes out
            self.beacon_off("repeating beacon stopped by the operator")  # and it stops
        station = self.station  # the running station, if any
        if station is None:  # nothing is running
            return  # nothing more to stop
        if station.state in LOCKED:  # a contact is under way
            self.say("a contact is in progress: End contact (F7) closes it properly")  # say how
            return  # left alone
        if self.tx_active and self.tx_kind in ("call", "beacon", "long beacon", "broadcast", "mail notice") and self.sink is not None:  # such a frame is on the air now
            self.sink.abort()  # cut it short; the transmitter comes off at once
            self.say(f"{self.tx_kind} cut short on the air")  # say so

        def stop(station):  # in the station's own thread
            words = station.cancel(self.station_now)  # stop the call-up
            if not words:  # nothing was under way
                self.say("nothing to stop: no call or beacon is under way")  # say so
            return True  # done

        self.ask_station(stop, "")  # the station stops at its next look

    def queue_message(self):  # add the typed message to the list to send
        text = self.message.get().strip()  # what was typed
        if text and self.queue_text(text, self.to.get().strip().upper()):  # it was accepted
            self.message.delete(0, "end")  # clear the box

    def queue_text(self, text, to):  # queue a message for a station (or for whoever the partner is)
        """Queue `text` for `to` (a callsign, or "" for the partner); return True if it was accepted."""
        if to == "ALL" and chain.needs_chain(text):  # a long broadcast: it would need the calling frequency (since 0.42)
            messagebox.showinfo("Kestrel", f"A broadcast to ALL can be at most {chain.PIECE_MOST} characters; this one has {len(text)}.\n\nLonger messages go only to one station, on a working channel.", parent=self.root)  # say so
            return False  # refused
        if to == "ALL":  # ALL chosen in the To box: that is a broadcast, which nobody acknowledges
            return self.broadcast_text(text)  # sent as one, after the usual check
        if to and to == self.settings["call"].strip().upper():  # the message is addressed to this station itself
            messagebox.showinfo("Kestrel", f"{to} is this station's own callsign.\n\nPut the other station's callsign in the To box, or leave it blank to send to whoever the partner is.", parent=self.root)  # say so, and what to do
            return False  # refused
        if chain.needs_chain(text):  # longer than one message: a chained message (since 0.42)
            return self.queue_chain(text, to)  # held for a working channel
        self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), to or "partner", self.band_for(to), text, "waiting"))  # show it in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        with self.outbox_lock:  # so a run that is starting or ending cannot miss this message (since 0.40R3)
            station = self.station  # the station running at this moment, if any
            if station is not None:  # one is running
                station.queue(text, to=to or None)  # hand it the message now; it goes when the right station is the partner
                self.say(f"queued{' for ' + to if to else ''}: {text}")  # confirm
            else:  # nothing is running
                self.outbox.append((text, to))  # keep it for the next time Listen runs
                self.say(f"queued for the next contact{' with ' + to if to else ''}: {text}")  # confirm
        self.save_outbox()  # a waiting message is kept even if the panel is closed
        return True  # accepted

    def queue_chain(self, text, to):  # a message longer than one frame (since 0.42)
        """Cut `text` into numbered pieces and hold them until the contact with `to` is on a working channel; return True."""
        if len(text) > chain.MOST:  # longer than a chained message may be
            messagebox.showinfo("Kestrel", f"A message can be at most {chain.MOST} characters; this one has {len(text)}.", parent=self.root)  # say so
            return False  # refused
        pieces = chain.split(text)  # the pieces, each with its "(k/n) " prefix
        for piece in pieces:  # one row each, so each piece's progress shows
            self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), to or "partner", self.band_for(to), piece, "waiting for a working channel"))  # in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        self.held.append({"to": to, "pieces": pieces})  # held here until the contact is on a working channel
        self.say(f"long message for {to or 'the partner'}: {len(pieces)} parts, sent once the contact is on a working channel")  # explain
        self.save_outbox()  # kept if the panel is closed
        return True  # accepted

    def release_held(self, station):  # hand held pieces to the station when they may go (called with the window's own thread, since 0.42)
        """Chained messages go only on a working channel: hand them over once there; on the calling frequency, ask for a move."""
        if not self.held or station.state not in LOCKED or not station.partner:  # nothing held, or no contact
            return  # nothing to do
        for item in list(self.held):  # every held chain
            if item["to"] and item["to"] != station.partner:  # for someone else
                continue  # not now
            if station.offset_hz:  # the contact is on a working channel
                with self.outbox_lock:  # the same lock as every other hand-over
                    for piece in item["pieces"]:  # in order
                        station.queue(piece, to=item["to"] or None)  # into the station
                        self._advance_held(piece)  # its row now says waiting
                self.held.remove(item)  # handed over
                self.say(f"long message: {len(item['pieces'])} parts handed over on the working channel")  # explain
            elif self.move_ok and self.move_offsets and not station.moved and not station.move_to_hz:  # on the calling frequency, and a move is possible
                station.move_to_hz = self.move_offsets[0]  # propose Channel 1 before any more traffic
                self.say(f"long message waiting: proposing a move to a working channel ({self.move_offsets[0] / 1000.0:+.1f} kHz)")  # explain
            elif not self.move_ok and station.partner not in self.held_told:  # the radio cannot be retuned
                self.held_told.add(station.partner)  # say it once per partner
                self.say(f"long message for {station.partner} waits: it goes only on a working channel, and changing frequency needs rig control (Settings > Radio)")  # explain

    def _advance_held(self, piece):  # a held piece has been handed to the station (since 0.42)
        for row in self.to_send.get_children():  # oldest first
            if self.to_send.set(row, "text") == piece and self.to_send.set(row, "state") == "waiting for a working channel":  # this piece's row
                self.to_send.set(row, "state", "waiting")  # it now waits in the station, like any message
                return  # only that one

    def send_menu_at(self, event):  # a right click anywhere in the list of messages to send
        row = self.to_send.identify_row(event.y)  # the message under the pointer, if any
        if row and row not in self.to_send.selection():  # a message that is not among those already chosen
            self.to_send.selection_set(row)  # choose it alone
        self.to_send.focus_set()  # the list has the keyboard (Del works next)
        self.popup(self.send_menu, event)  # Edit and Delete at the pointer (they say what to select if nothing is)

    def popup(self, menu, event):  # show a right-click menu at the pointer
        try:  # whatever happens...
            menu.tk_popup(event.x_root, event.y_root)  # the menu
        finally:  # ...let go of the mouse afterwards
            menu.grab_release()  # so the next click goes where it is aimed

    def select_all_rows(self, tree):  # Select all, in a list
        tree.selection_set(tree.get_children())  # every row
        tree.focus_set()  # the list has the keyboard

    def copy_rows(self, tree):  # Copy, in a list
        """Put the selected rows (every row, if none is selected) on the clipboard: a line of headings, then one line per row, columns separated by tabs (pastes into a spreadsheet)."""
        rows = tree.selection() or tree.get_children()  # the chosen rows, or all of them
        columns = tree["columns"]  # the column names
        lines = ["\t".join(tree.heading(name, "text") for name in columns)]  # the headings
        lines += ["\t".join(str(tree.set(row, name)) for name in columns) for row in rows]  # each row
        self.clip("\n".join(lines) + "\n", f"{len(rows)} row(s) copied")  # onto the clipboard

    def clip(self, text, words):  # put text on the clipboard
        self.root.clipboard_clear()  # empty it
        self.root.clipboard_append(text)  # the text
        self.say(words)  # confirm

    def clear_finished(self):  # Clear finished messages
        """Take delivered, sent and failed messages off the list; messages still waiting (or being sent) stay."""
        done = [row for row in self.to_send.get_children() if not self.to_send.set(row, "state").startswith(("waiting", "sending", "broadcast")) and row not in self.note_rows.values()]  # finished (a long note still under way stays)
        self.to_send.delete(*done)  # off the list
        self.save_outbox()  # the saved queue is unchanged in content, but kept in step
        self.say(f"cleared {len(done)} finished message(s) from the list")  # confirm

    def clear_heard(self):  # Clear stations heard
        """Empty the Stations heard list; saved contacts stay (the 48-hour record, F8, is kept)."""
        gone = [call for call in self.heard_rows if call not in self.contacts]  # the stations that are not saved contacts
        for call in gone:  # each
            self.stations.delete(self.heard_rows.pop(call))  # off the list
        for call, row in self.heard_rows.items():  # the saved contacts left
            self.stations.item(row, tags=())  # no longer highlighted as calling
        self.calling.clear()  # nobody is highlighted as calling any more
        self.refresh_to()  # the To box offers what is left
        self.say(f"cleared {len(gone)} station(s) from the list; saved contacts stay, and the 48-hour record (F8) is kept")  # confirm

    def select_all_log(self):  # Select all, in the Activity log
        self.log.tag_add("sel", "1.0", "end-1c")  # every line
        self.log.focus_set()  # the log has the keyboard

    def copy_log(self):  # Copy, in the Activity log
        """Put the selected text of the log (the whole log, if nothing is selected) on the clipboard."""
        ranges = self.log.tag_ranges("sel")  # the selection, if any
        text = self.log.get(ranges[0], ranges[1]) if ranges else self.log.get("1.0", "end-1c")  # it, or everything
        self.clip(text if text.endswith("\n") else text + "\n", f"{len(text.splitlines())} log line(s) copied")  # onto the clipboard

    def clear_log(self):  # Clear, in the Activity log
        """Empty the Activity log on the screen (the logbook and the signal log are not touched)."""
        self.history.clear()  # the lines kept for redrawing
        self.redraw_log()  # an empty log

    def refresh_send_bands(self):  # bring the Band column of Messages to send up to date
        """Show, beside each message still to go, the band its station was last heard on (the band in use, for the partner or ALL)."""
        if not hasattr(self, "to_send"):  # the list is not built yet
            return  # nothing to do
        for row in self.to_send.get_children():  # every message
            if self.to_send.set(row, "state").startswith(("waiting", "sending", "broadcast")):  # not gone yet
                to = self.to_send.set(row, "to")  # who it is for
                self.to_send.set(row, "band", self.band_for("" if to == "partner" else to))  # its band now

    def band_for(self, to):  # the band to show beside a message
        """Return the band station `to` was last heard on (or saved with); for a message to the partner or to ALL, the band the radio is on now."""
        if not to or to in ("partner", "ALL"):  # whoever the partner is, or everyone
            return band_of(self.dial_hz() / 1000.0)  # the band in use
        heard = next((row for row in self.heardlog.summary() if row["call"] == to), None)  # its latest reception, within 48 hours
        if heard is not None and band_of(heard.get("dial_khz")):  # heard on a known band
            return band_of(heard["dial_khz"])  # that band
        return self.contacts.get(to, {}).get("band", "")  # the band it was last heard on as a saved contact, if known

    def edit_message(self):  # change a message that is still waiting
        """Open a small window to change the address and text of the selected waiting message."""
        rows = self.to_send.selection()  # the rows chosen
        if len(rows) != 1 or not self.to_send.set(rows[0], "state").startswith("waiting"):  # not exactly one message that has yet to go
            messagebox.showinfo("Kestrel", "Select one message that is still waiting in the Messages to send list.\n\nA message that is being sent, or has gone, cannot be changed.", parent=self.root)  # say what can be edited
            return  # nothing to do
        row = rows[0]  # the message to change
        if "carried by" in self.to_send.set(row, "state"):  # copies are already with other stations
            messagebox.showinfo("Kestrel", "Copies of this message are already with other stations, which will deliver them as they are.\n\nTo send something different, delete it and write a new message.", parent=self.root)  # say why not
            return  # leave it alone
        old_text, shown = self.to_send.set(row, "text"), self.to_send.set(row, "to")  # what it says and who it is for, as listed
        old_to = "" if shown == "partner" else shown  # the address as the queue holds it
        top = self.window("edit", "Kestrel - edit message")  # the window
        ttk.Label(top, text="To (blank: whoever the partner is)").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))  # label of the address
        to_box = ttk.Entry(top, width=12)  # the address
        to_box.grid(row=0, column=1, sticky="w", padx=8, pady=(8, 2))  # place it
        to_box.insert(0, old_to)  # as it is now
        ttk.Label(top, text="Message").grid(row=1, column=0, sticky="w", padx=8, pady=2)  # label of the text
        text_box = ttk.Entry(top, width=70)  # the text
        text_box.grid(row=1, column=1, sticky="ew", padx=8, pady=2)  # place it
        text_box.insert(0, old_text)  # as it is now
        text_box.focus_set()  # ready to type

        def save():  # the operator accepts the change
            text, to = text_box.get().strip(), to_box.get().strip().upper()  # the new text and address
            if not text or (to and to == self.settings["call"].strip().upper()):  # nothing to send, or addressed to this station itself
                messagebox.showinfo("Kestrel", "The message needs some text, and To cannot be this station's own callsign.", parent=top)  # say so
                return  # stay in the window
            if not self.to_send.exists(row) or not self.to_send.set(row, "state").startswith("waiting"):  # the message went, or was deleted, while the window was open
                messagebox.showinfo("Kestrel", "That message is no longer waiting, so it was not changed.", parent=top)  # say so
                top.destroy()  # close the window
                return  # nothing changed
            if self.station is not None:  # a station is running and holds the queue
                self.ask_station(lambda station: (station.unqueue(old_text, old_to or None) and station.queue(text, to=to or None)) or True, f"changed{' for ' + to if to else ''}: {text}")  # swap the old message for the new, unless the old has started to go
            elif (old_text, old_to) in self.outbox:  # it waits here for the next run
                self.outbox[self.outbox.index((old_text, old_to))] = (text, to)  # replace it where it stands
                self.say(f"changed{' for ' + to if to else ''}: {text}")  # confirm
            self.to_send.set(row, "to", to or "partner")  # the list shows the new address
            self.to_send.set(row, "band", self.band_for(to))  # and the band that station was last heard on
            self.to_send.set(row, "text", text)  # and the new text
            self.save_outbox()  # the saved queue follows the list
            top.destroy()  # close the window

        buttons = ttk.Frame(top)  # Save and Cancel
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", padx=8, pady=8)  # under the boxes
        ttk.Button(buttons, text="Save", command=save).pack(side="left", padx=(0, 4))  # accept
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="left")  # back out
        top.bind("<Return>", lambda event: save())  # Enter saves

    def remove_message(self):  # take the selected messages off the list to send
        """Remove the selected rows of "Messages to send": a waiting message is taken out of the queue, a finished one is only cleared from the list."""
        rows = self.to_send.selection()  # the rows chosen
        if not rows:  # none
            messagebox.showinfo("Kestrel", "Select the message to remove in the Messages to send list first.", parent=self.root)  # say so
            return  # nothing to do
        for row in rows:  # each chosen row
            state, text, to = self.to_send.set(row, "state"), self.to_send.set(row, "text"), self.to_send.set(row, "to")  # how far it has got, what it says, who it is for
            if state == "sending":  # it is going out now
                self.say(f"not removed, it is being sent: {text}")  # leave it alone
                continue  # next row
            if state.startswith("long note") and self.note_rows.get((to, text)) == row:  # a long note not yet finished (since 0.34)
                notes = self.notes_for()  # this station's long notes
                self.ask_station(lambda station, to=to, text=text: notes.cancel(to, text) or True, f"long note to {to} taken back: {text}")  # dropped in the station's own thread (a frame already on the air finishes)
                self.note_rows.pop((to, text), None)  # no longer followed
            if state == "waiting for a working channel":  # a piece of a chained message held here (since 0.42)
                for item in self.held:  # the held chains
                    if text in item["pieces"]:  # this piece's chain
                        item["pieces"].remove(text)  # taken out
                self.held = [item for item in self.held if item["pieces"]]  # chains with nothing left are dropped
                self.say(f"removed: {text}")  # confirm
                state = ""  # nothing more to take back
            if state.startswith("waiting"):  # not yet started (it may also be with carriers, who will still deliver their copies)
                address = "" if to == "partner" else to  # the address as the queue holds it
                if self.station is not None:  # a station is running and holds the queue
                    self.ask_station(lambda station, text=text, address=address: station.unqueue(text, address or None) or True, f"removed from the queue: {text}")  # ask it to take the message back
                elif (text, address) in self.outbox:  # it waits here for the next run
                    self.outbox.remove((text, address))  # take it out
                    self.say(f"removed from the queue: {text}")  # confirm
            self.to_send.delete(row)  # off the list
        self.save_outbox()  # the saved queue follows the list

    def broadcast_message(self):  # send the typed message to every station listening
        text = self.message.get().strip()  # what was typed
        if not text:  # nothing was
            messagebox.showinfo("Kestrel", "Type the message to broadcast first (Ctrl+M).", parent=self.root)  # say so
            return  # nothing to do
        if self.broadcast_text(text):  # it was sent on its way
            self.message.delete(0, "end")  # clear the box

    def broadcast_text(self, text):  # send a message to every station listening
        """Broadcast `text` to ALL after the operator confirms; return True if it was sent on its way."""
        if not messagebox.askokcancel("Kestrel", "This will TRANSMIT the message to all stations at the slowest level, with no acknowledgment.\nCheck on the scope that the frequency is clear. Continue?", parent=self.root):  # a last check before transmitting
            return False  # the operator backed out
        if not self.ensure_listening("broadcast"):  # a broadcast needs a station that can transmit
            return False  # nothing started
        self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), "ALL", self.band_for(""), text, "broadcast when idle"))  # show it in the list (on the band the radio is on)
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        self.ask_station(lambda station: station.broadcast(text) or True, f"broadcast queued: {text}")  # the station sends it as soon as no contact is in progress
        return True  # on its way

    # ---- long notes (since 0.34) ----

    def notes_for(self):  # this station's long notes
        """Return the LongNotes for this station's callsign (made afresh if the callsign has changed)."""
        call = self.settings["call"].strip().upper()  # this station
        if self.long_notes is None or self.long_notes.call != call:  # none yet, or for another callsign
            self.long_notes = LongNotes(call)  # a fresh set
        return self.long_notes  # kept between runs, so a note waiting for its receipt survives a change of mode

    def long_note_message(self):  # Ctrl+N: send the typed message as a long note
        """Queue the typed message as a long note to the station in To (a callsign, or ALL chosen from its list), after the operator confirms."""
        text, to = self.message.get().strip(), self.to.get().strip().upper()  # what was typed, and to whom
        own = self.settings["call"].strip().upper()  # this station
        if not text:  # nothing was typed
            messagebox.showinfo("Kestrel", f"Type the note first (Ctrl+M): up to {LONG_NOTE_CHARS} characters.", parent=self.root)  # say so
            return  # nothing to do
        if not to:  # nobody named
            messagebox.showinfo("Kestrel", "Put the callsign of the station the note is for in the To box, or choose ALL from its list to send it to every station.", parent=self.root)  # say what to do
            self.to.focus_set()  # go there
            return  # nothing to do
        if to == own:  # addressed to this station itself
            messagebox.showinfo("Kestrel", "A long note cannot be sent to this station's own callsign.", parent=self.root)  # say so
            return  # nothing to do
        try:  # can it be sent as it is?
            note_fields(own or "Q0AA", to, text)  # the frames it would make (raises if too long or not plain text)
        except ValueError as problem:  # it cannot
            messagebox.showinfo("Kestrel", f"This cannot go as a long note: {problem}.\n\nA long note holds up to {LONG_NOTE_CHARS} characters: capital letters (small ones are sent as capitals), figures, spaces and ordinary punctuation.", parent=self.root)  # say why
            return  # nothing sent
        if self.queue_long_note(text, to):  # confirmed and queued (since 0.39 shared with telemetry sent as a long note)
            self.message.delete(0, "end")  # clear the box (kept if the operator backed out)

    def long_note_telemetry(self):  # Quick > Send telemetry as a long note (since 0.39)
        """Send what this station hears as a long note to the station in To (or ALL): grid, power, count and as many stations as fit in a long note."""
        to = self.to.get().strip().upper() or "ALL"  # to whom; everyone if nobody is named
        own = self.settings["call"].strip().upper()  # this station
        if to == own:  # addressed to this station itself
            messagebox.showinfo("Kestrel", "A long note cannot be sent to this station's own callsign.", parent=self.root)  # say so
            return  # nothing to do
        heard = telemetry.summarize(self.heardlog.snapshot(), time.time())  # the last half hour
        text = telemetry.build(self.settings["grid"], self.power_w(), heard, max_chars=LONG_NOTE_CHARS)  # the telemetry, cut to what a long note holds (the count still says how many were heard)
        self.queue_long_note(text, to)  # confirmed and queued

    def queue_long_note(self, text, to):  # ask, then queue a long note (the typed one, or telemetry)
        """Ask the operator to confirm sending `text` as a long note to `to`, then queue it; return True if queued."""
        frames = 1 + -(-len(text.rstrip()) // LONG_NOTE_FRAME_CHARS)  # a header, and a frame for each eight characters
        after = ("The other station answers with a one-minute receipt. With no receipt the note is sent again, up to three times; "  # (continued)
                 "the other station adds the copies together, so each try reaches further." if to != "ALL" else "Nobody answers a note to ALL; it is sent once.")  # what happens next
        if not messagebox.askokcancel("Kestrel", f"This will TRANSMIT a long note to {to}: {frames} frames of about a minute each (about {frames} minutes on the air), when no contact is under way. {after}\n\n{text.upper()}\n\n"  # (continued)
                                      "Long notes are heard down to about -26 dB, about 5 dB below the slowest normal level. Check on the scope that the frequency is clear. Continue?", parent=self.root):  # a last check before transmitting, showing what will go
            return False  # the operator backed out
        if not self.ensure_listening("send a long note"):  # a long note needs a station that can transmit
            return False  # nothing started
        notes = self.notes_for()  # this station's long notes
        self.note_rows[(to, text)] = self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), to, self.band_for("" if to == "ALL" else to), text, "long note: waiting"))  # show it in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        self.ask_station(lambda station: notes.queue(to, text) or True, f"long note queued for {to} ({frames} minutes on the air): {text}")  # queued in the station's own thread, which sends it when no contact is under way
        return True  # queued

    def note_event(self, event):  # a long-note event, from the working thread
        self.note_events.put(event)  # shown by the window's own thread

    def keep_sorted(self):  # the main lists stay in the order the operator chose as rows arrive and change (since 0.40; called with the long-note events, twice a second)
        now = time.monotonic()  # now
        if now - getattr(self, "resorted_at", 0.0) < 1.0:  # at most once a second
            return  # not yet
        self.resorted_at = now  # remembered
        self.fill_utc()  # the UTC column beside each local time (since 0.41)
        for tree in (self.to_send, self.received, self.stations):  # the three lists
            self.sort_table(tree, None)  # again, by the column and direction chosen (nothing happens to a list never sorted)

    def fill_utc(self):  # the UTC column of each list follows its local time (since 0.41)
        """Fill each row's UTC cell from the local time shown beside it, and put the counts on the tabs."""
        for tree in (self.to_send, self.received, self.stations):  # the three lists
            for row in tree.get_children():  # each row
                local, shown = tree.set(row, "time"), tree.set(row, "utc")  # its local time and the UTC shown now
                if local and getattr(tree, "_utc_of", {}).get(row) != local:  # a new or changed time
                    tree.set(row, "utc", utc_of_shown(local))  # the same moment in UTC
                    tree._utc_of = {**getattr(tree, "_utc_of", {}), row: local}  # remembered, so it is worked out once
                elif not local and shown:  # no time now
                    tree.set(row, "utc", "")  # none
        waiting = sum(1 for row in self.to_send.get_children() if not str(self.to_send.set(row, "state")).startswith(("delivered", "sent", "long note: DELIVERED", "long note: sent")))  # messages not yet done
        for index, (title, count) in enumerate((("Stations heard", len(self.stations.get_children())), ("Received", len(self.received.get_children())), ("To send", waiting))):  # each tab
            self.tabs.tab(index, text=f"{title} ({count})" if count else title)  # with its count

    def show_note_events(self):  # bring the lists up to date with long-note events
        self.keep_sorted()  # the main lists keep their chosen order (since 0.40)
        if self.long_notes is not None:  # notes may be under way
            for dest, text, words in self.long_notes.status():  # each unfinished note and its progress (which try, which frame, the receipt countdown)
                row = self.note_rows.get((dest, text))  # its row in Messages to send
                if row is not None and self.to_send.exists(row):  # still listed
                    self.to_send.set(row, "state", "long note: " + words)  # shown, twice a second
        while self.contacts.learned:  # a saved station said what radio, power or antenna it runs (since 0.38R2; from beacons and after contacts since 0.40)
            who, changes, how = self.contacts.learned.pop(0)  # the oldest news
            said = ", ".join(describe_field(name, value) for name, value in changes.items())  # in words
            self.say(f"{who}'s contact record updated {how}: {said}")  # tell the operator
        while not self.note_events.empty():  # each event since the last look
            kind, *rest = self.note_events.get()  # what happened
            if kind == "received":  # a note arrived for this station, or for everyone
                origin, dest, text = rest  # from whom, to whom, what
                self.received.insert("", "end", values=(time.strftime(HEARD_TIME), f"{origin} (long note)" + (" to ALL" if dest == "ALL" else ""), text))  # into Messages received
                self.logbook.write("broadcast" if dest == "ALL" else "message", direction="RX", station=self.settings["call"], **{"from": origin}, to=dest, text=text,  # (continued)
                                   dial_khz=round(self.dial_hz() / 1000.0, 1), long_note=True)  # into the logbook and the sender's contact history (before 0.38R2 long notes were not logged)
                self.note_telemetry(origin, text)  # a long note may carry telemetry too
                self.received.yview_moveto(1.0)  # keep it in view
                self.root.bell()  # a sound, as for other messages
                continue  # next event
            if kind in ("link", "locked"):  # a long call-up's progress or a long contact made (since 0.41): already in the Activity log and the status band
                if kind == "locked":  # a contact made
                    self.root.bell()  # a sound, so the operator knows
                continue  # next event
            if kind == "moved":  # a waiting message now goes as long notes (since 0.41)
                partner, to, text, pieces = rest  # to whom, its old address, its text, the notes it became
                for row in self.to_send.get_children():  # find its row in Messages to send
                    values = self.to_send.item(row, "values")  # time, to, band, text, state
                    if len(values) >= 5 and values[3] == text and values[1] in (to or "partner", partner, "partner") and not str(values[4]).startswith(("delivered", "sent", "long note")):  # this message, still waiting
                        self.to_send.set(row, "state", f"long note: waiting ({len(pieces)} note{'s' if len(pieces) > 1 else ''})")  # say what happens to it now
                        for piece in pieces:  # each note it became
                            self.note_rows[(partner, piece)] = row  # its progress shows on this row
                        break  # one row
                continue  # next event
            dest, text, tries = rest  # the note's address, text and tries so far
            row = self.note_rows.get((dest, text))  # its row in Messages to send
            words = {"delivered": f"long note: DELIVERED (try {tries}/{LONG_NOTE_TRIES})", "failed": f"long note: NOT delivered ({tries} tries)", "sent": "long note: sent to ALL"}.get(kind)  # its final state (progress while under way comes from status above)
            if row is not None and words and self.to_send.exists(row):  # still listed
                self.to_send.set(row, "state", words)  # show how it went
            if kind in ("delivered", "failed", "sent"):  # finished
                self.note_rows.pop((dest, text), None)  # no more to follow

    # ---- quick messages and telemetry ----

    def telemetry_text(self, prefix=""):  # what this station hears, as a telemetry message
        heard = telemetry.summarize(self.heardlog.snapshot(), time.time())  # the last half hour
        return telemetry.build(self.settings["grid"], self.power_w(), heard, prefix=prefix)  # the message

    def expand(self, template):  # fill in a quick message
        """Return `template` with {call}, {name}, {grid}, {rig}, {power}, {to}, {telemetry}, {location} and {antenna} filled in."""
        power = self.power_w()  # the transmit power, if known
        values = {"call": self.settings["call"], "name": self.settings["name"], "grid": self.settings["grid"], "rig": self.rig_name(),  # (continued)
                  "power": f"{power:.0f}" if power is not None else "?", "to": self.to.get().strip().upper(), "telemetry": "",  # (continued)
                  "location": self.settings.get("location", ""), "antenna": self.settings.get("antenna", "")}  # the values (location and antenna since 0.39R2)
        if "{telemetry}" in template:  # telemetry wanted
            values["telemetry"] = self.telemetry_text()  # built now, from the latest receptions
        try:  # the template may have a mistake in it
            text = template.format(**values)  # filled in
        except (KeyError, ValueError, IndexError):  # an unknown {name}, or a stray brace
            text = template  # sent as written
        return " ".join(text.split())[:telemetry.MAX_CHARS]  # tidy spacing, and no longer than one message

    def refresh_quick(self):  # (re)fill the quick-message menus: the Quick button's, and Messages > Quick messages
        for menu in (self.quick_menu, self.quick_submenu):  # both
            menu.delete(0, "end")  # empty it
            for number, item in enumerate(self.settings["quick"], start=1):  # each quick message, in the operator's order
                menu.add_command(label=f"{number % 10}  {item['name']}", underline=0, accelerator=f"Alt+{number % 10}", command=lambda n=number: self.use_quick(n))  # by its name; it goes into the Message box
            if not self.settings["quick"]:  # none at all
                menu.add_command(label="(no quick messages yet)", state="disabled")  # say so
            menu.add_separator()  # a divider
            menu.add_command(label="Add, edit or delete quick messages...", command=lambda: self.settings_window(5))  # Settings, at the quick-message tab
        self.quick_menu.add_separator()  # a divider
        self.quick_menu.add_command(label="Send telemetry to the station in To", accelerator="Ctrl+4", command=self.send_telemetry)  # what this station hears
        self.quick_menu.add_command(label="Broadcast telemetry to ALL", accelerator="Ctrl+5", command=self.broadcast_telemetry)  # to everyone
        self.quick_menu.add_command(label=f"Send telemetry as a long note (reach; up to {LONG_NOTE_CHARS} characters)...", command=self.long_note_telemetry)  # for weak paths: to the station in To, or ALL (since 0.39)

    def use_quick(self, number):  # put quick message `number` (counted from 1) in the Message box
        if not 1 <= number <= len(self.settings["quick"]):  # there is no such quick message
            self.say(f"there is no quick message {number}; add one in Settings > Quick messages")  # say so
            return  # nothing to put in
        self.message.delete(0, "end")  # clear the box
        self.message.insert(0, self.expand(self.settings["quick"][number - 1]["text"]))  # the filled-in message
        self.message.focus_set()  # ready for Enter (queue) or F11 (broadcast)
        self.message.icursor("end")  # with the cursor at the end, for any change

    def send_telemetry(self):  # send telemetry to the station in the To box (or to the partner)
        self.queue_text(self.telemetry_text(), self.to.get().strip().upper())  # queued like any other message

    def broadcast_telemetry(self):  # send telemetry to everyone
        self.broadcast_text(self.telemetry_text())  # broadcast like any other message

    def note_telemetry(self, sender, text):  # a received message may be telemetry
        info = telemetry.parse(text)  # read it
        if info is None:  # not telemetry
            return  # nothing to do
        self.telemetry_in.append((time.time(), sender, info))  # keep it
        self.logbook.write("telemetry", direction="RX", station=self.settings["call"], **{"from": sender}, text=text, dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook
        self.say(f"telemetry from {sender}: hears {info['count']} station(s); see Stations > Telemetry received (F9)")  # tell the operator

    # ---- beacons to respond to ----

    def waiting_for(self, call):  # how many messages are waiting that could go to a station
        """Return (messages waiting for `call` by name, messages waiting for whoever the partner is)."""
        named = anyone = 0  # the two counts
        for row in self.to_send.get_children():  # every outgoing message
            if self.to_send.set(row, "state").startswith(("waiting", "sending")):  # not yet delivered
                to = self.to_send.set(row, "to")  # who it is for
                named += to == call  # for this station by name
                anyone += to == "partner"  # for whoever the partner is
        return named, anyone  # both counts

    def mail_note(self, call, fields):  # the messages column of the Stations calling window
        named, anyone = self.waiting_for(call)  # this station's messages for it
        notes = []  # the pieces
        if named:  # messages addressed to it
            notes.append(f"{named} waiting for {call}")  # say how many
        if anyone:  # messages for whoever answers
            notes.append(f"{anyone} for any partner")  # say how many
        if fields.get("you"):  # it called this station by name
            notes.insert(0, "CALLING YOU")  # say so first
        notice = self.mail_notices.get(call)  # its last mail notice, which says whom it holds mail for
        if fields.get("holds_mail") and not (notice is not None and time.time() - notice[0] < 7200):  # its beacon says it holds mail, and no recent notice says for whom
            notes.append("it holds mail (may be for you)")  # which may be for this station
        return "; ".join(notes) or "none"  # all of them

    def beacon_heard(self, call, grid, snr, fields):  # a station beaconed: show it to the operator, who chooses whether to respond
        if self.settings["auto_answer"] and self.mode == "listen":  # the station answers beacons by itself
            return  # nothing to ask
        new = call not in self.calling  # not already highlighted
        if self.calling.get(call, {}).get("fields", {}).get("you"):  # it called this station by name earlier
            fields = dict(fields, you=True)  # keep that mark until the operator responds
        self.calling[call] = {"when": time.time(), "fields": fields}  # the latest beacon or call
        note = self.mail_note(call, fields)  # messages either way
        what = "is calling you by name" if fields.get("you") else ("sent a long beacon" if fields.get("long") else "is beaconing")  # which it was
        if fields.get("you") and not self.settings["available"]:  # called while the operator is away
            self.say(f"{call} called you by name ({snr:+.0f} dB) while you were not available; it was told so. It stays highlighted in Stations heard for five minutes")  # for when the operator is back
        else:  # the operator can respond
            self.say(f"{call} {what} ({snr:+.0f} dB): select it in Stations heard and press Respond (Ctrl+Y) to answer" + (f"; messages: {note}" if note != "none" else ""))  # in the log
        if new:  # a station not highlighted before
            self.root.bell()  # draw attention

    def follow_calling(self):  # keep the highlights and the messages column of the Stations heard list up to date
        cutoff = time.time() - CALLING_KEEP_S  # beacons older than this are no longer worth answering
        for call in [call for call, info in self.calling.items() if info["when"] < cutoff]:  # each one too old
            del self.calling[call]  # forget it
        station = self.station  # the running station, if any
        if station is not None and station.state in LOCKED and station.partner in self.calling:  # a contact with a highlighted station has started
            del self.calling[station.partner]  # it is dealt with
        for call, row in self.heard_rows.items():  # every station in the list
            info = self.calling.get(call)  # its recent beacon, if any
            self.stations.item(row, tags=("calling",) if info else ())  # highlighted while it is calling
            note = self.mail_note(call, info["fields"] if info else {}).replace("none", "")  # messages either way
            said = self.availability.get(call)  # what the station last said about its operator
            if said is not None and time.time() - said[1] < 3600:  # within the last hour
                note = ("available" if said[0] else "NOT AVAILABLE") + ("; " + note if note else "")  # put it first
            notice = self.mail_notices.get(call)  # its last mail notice, if any
            if notice is not None and time.time() - notice[0] < 7200:  # within the last two hours
                note = (note + "; " if note else "") + self.notice_words(call, notice[1])  # whom it holds mail for
            steps = self.steps_heard.get(call)  # its last power steps, if any (since 0.38)
            if steps is not None and time.time() - steps[0] < 3600:  # within the last hour
                r = steps[1]  # the reading
                words = "power steps: none heard" if r.lowest_db != r.lowest_db else f"power steps to {r.lowest_db:.0f} dB" + {True: ", even", False: ", UNEVEN", None: ""}[r.even]  # how far down they were heard, and how evenly
                note = (note + "; " if note else "") + words  # added
            self.stations.set(row, "mail", note)  # show it

    def station_menu_at(self, event):  # a right click on the Stations heard and saved contacts list
        row = self.stations.identify_row(event.y)  # the station under the pointer, if any
        if row and row not in self.stations.selection():  # one that is not among those already chosen
            self.stations.selection_set(row)  # choose it alone
            self.stations.focus(row)  # and give it the keyboard
        self.stations.focus_set()  # the list has the keyboard
        self.popup(self.station_menu, event)  # Respond, Save, Remove, Show last 48 hours at the pointer

    def station_history(self):  # right click > Show last 48 hours
        rows = self.stations.selection()  # the selected station
        if not rows:  # none
            messagebox.showinfo("Kestrel", "Select a station in the Stations heard list first.", parent=self.root)  # say so
            return  # nothing to do
        self.heard_window(self.stations.set(rows[0], "who"))  # its receptions in the last 48 hours

    def respond(self):  # Respond: call the station selected in the Stations heard list
        rows = self.stations.selection()  # the selected row
        if not rows:  # nothing selected
            messagebox.showinfo("Kestrel", "Select a station in the Stations heard list first (Ctrl+G, then the arrow keys).", parent=self.root)  # say how
            return  # nothing to do
        call = self.stations.set(rows[0], "who")  # its callsign
        self.to.set(call)  # into the To box
        self.calling.pop(call, None)  # it is being dealt with
        self.stations.item(rows[0], tags=())  # no longer highlighted as calling
        self.call_to()  # call it by name

    # ---- extra windows ----

    def table(self, parent, columns, height=14):  # a list with headings that sort when clicked
        frame = ttk.Frame(parent)  # holds the list and its scroll bar
        frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))  # fill the window
        tree = ttk.Treeview(frame, columns=[name for name, _, _ in columns], show="headings", height=height)  # the list
        for name, heading, width in columns:  # each column
            tree.heading(name, text=heading, anchor="w", command=lambda n=name: self.sort_table(tree, n))  # a click sorts by it
            tree.column(name, width=width, anchor="w", stretch=(name in ("list", "detail")))  # its width
        tree.pack(side="left", fill="both", expand=True)  # place it
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)  # a scroll bar
        scroll.pack(side="right", fill="y")  # beside it
        tree.configure(yscrollcommand=scroll.set)  # tie the two together
        return tree  # for filling

    def sort_table(self, tree, column):  # sort a list by one column (again to reverse); column None sorts again as last chosen
        state = getattr(tree, "_sort", None)  # the column and direction it is sorted by now, if any (since 0.40)
        if column is None:  # sort again as before (new rows arrived; since 0.40)
            if state is None:  # never sorted
                return  # leave the order alone
            column, backwards = state  # as before
        else:  # a heading clicked
            backwards = state is not None and state[0] == column and not state[1]  # the same column again: the other way
        tree._sort = (column, backwards)  # remembered (for the next click, and for keeping the order as rows arrive)
        rows = [(tree.set(row, column), row) for row in tree.get_children("")]  # the column's values

        def key(item):  # numbers as numbers, words as words
            text = item[0].replace(" dB", "").replace("L", "").replace("W", "").strip()  # drop units
            try:  # a number?
                return (0, float(text), "")  # sorts numerically
            except ValueError:  # words
                return (1, 0.0, item[0])  # sorts alphabetically

        for index, (_, row) in enumerate(sorted(rows, key=key, reverse=backwards)):  # in the new order
            tree.move(row, "", index)  # move each row
        titles = getattr(tree, "_titles", None)  # each heading's own words, kept the first time (since 0.40)
        if titles is None:  # the first sort of this list
            titles = tree._titles = {name: tree.heading(name, "text") for name in tree["columns"]}  # remembered
        for name, words in titles.items():  # every heading
            tree.heading(name, text=words + ((" ▼" if backwards else " ▲") if name == column else ""))  # an arrow on the sorted one: ▲ smallest first, ▼ largest first

    def heard_window(self, only=None):  # Stations > Stations heard (last 48 hours); with `only`, one station's receptions
        top = self.window("heard", f"Kestrel - {only} heard in the last 48 hours" if only else "Kestrel - stations heard in the last 48 hours")  # the window
        every = tk.BooleanVar(value=bool(only))  # show each reception, or one row per station (each reception, for one station)
        holder = ttk.Frame(top)  # holds the list, which is rebuilt when the choice changes
        holder.pack(fill="both", expand=True)  # fill the window
        tree_box = {}  # the list now shown

        def fill():  # (re)build the list
            for child in holder.winfo_children():  # the old list
                child.destroy()  # goes
            self.heardlog.prune()  # forget anything older than 48 hours
            if every.get():  # every reception
                tree = self.table(holder, (("time", "Time (UTC)", 120), ("local", f"Local ({local_zone_name()})", 96), ("call", "Callsign", 90), ("grid", "Grid", 60), ("snr", "Signal", 70), ("level", "Level", 50), ("kind", "Heard sending", 120), ("band", "Band", 50), ("khz", "Frequency kHz", 100)))  # the columns
                for record in reversed(self.heardlog.snapshot()):  # newest first
                    if only and record["call"] != only:  # another station, when only one is wanted
                        continue  # left out
                    tree.insert("", "end", values=(utc(record["t"]), local_time(record["t"]), record["call"], record.get("grid", ""), f"{record['snr']:+.0f} dB", level_name(record.get("level", 0)), record.get("kind", ""), band_of(record.get("dial_khz", 0)), f"{record.get('dial_khz', 0):.1f}"))  # one row
            else:  # one row per station
                tree = self.table(holder, (("call", "Callsign", 90), ("grid", "Grid", 60), ("last", "Last heard (UTC)", 120), ("last_local", f"Local ({local_zone_name()})", 96), ("first", "First heard (UTC)", 120), ("count", "Times", 50), ("last_snr", "Last signal", 80), ("best_snr", "Best signal", 80), ("level", "Fastest", 60), ("band", "Band", 50), ("khz", "Frequency kHz", 100)))  # the columns
                for row in self.heardlog.summary():  # most recent first
                    tree.insert("", "end", values=(row["call"], row["grid"], utc(row["last"]), local_time(row["last"]), utc(row["first"]), row["count"], f"{row['last_snr']:+.0f} dB", f"{row['best_snr']:+.0f} dB", f"L{row['best_level']}", band_of(row["dial_khz"]), f"{row['dial_khz']:.1f}"))  # one row
            tree.bind("<Double-1>", lambda event: use())  # a double-click puts the callsign in To
            tree.bind("<Return>", lambda event: use())  # so does Enter
            tree_box["tree"] = tree  # remember it
            children = tree.get_children()  # its rows
            if children:  # there are some
                tree.focus(children[0])  # the first row has the keyboard
                tree.selection_set(children[0])  # and is selected
            tree.focus_set()  # the list has the keyboard

        def chosen():  # the callsign of the selected row
            tree = tree_box["tree"]  # the list
            rows = tree.selection()  # the selected rows
            return tree.set(rows[0], "call") if rows else ""  # its callsign

        def use():  # put the selected callsign in To
            call = chosen()  # which one
            if call:  # one is selected
                self.to.set(call)  # into the To box
                top.destroy()  # close the window
                self.message.focus_set()  # ready to type a message

        def keep():  # save the selected callsign as a contact
            call = chosen()  # which one
            if call:  # one is selected
                self.contact_window(call)  # its record: a new one filled in from what was heard, or the saved one (since 0.31R3)

        buttons = ttk.Frame(top)  # the row of buttons
        buttons.pack(fill="x", padx=8, pady=(0, 8))  # at the bottom
        ttk.Checkbutton(buttons, text="Show every reception", underline=5, variable=every, command=fill).pack(side="left")  # one row per station, or every reception
        ttk.Button(buttons, text="Put in To", underline=0, command=use).pack(side="left", padx=(12, 4))  # use the selected callsign
        ttk.Button(buttons, text="Save as contact", underline=0, command=keep).pack(side="left", padx=4)  # keep it
        ttk.Button(buttons, text="Refresh", underline=0, command=fill).pack(side="left", padx=4)  # bring the list up to date
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close the window
        top.bind("<Alt-e>", lambda event: (every.set(not every.get()), fill()))  # Alt+E: every reception
        top.bind("<Alt-p>", lambda event: use())  # Alt+P: put in To
        top.bind("<Alt-s>", lambda event: keep())  # Alt+S: save as contact
        top.bind("<Alt-r>", lambda event: fill())  # Alt+R: refresh
        fill()  # fill it the first time

    def telemetry_window(self):  # Stations > Telemetry received
        top = self.window("telemetry", "Kestrel - telemetry: who hears whom")  # the window
        ttk.Label(top, text="Each station's telemetry lists the stations it heard in the half hour before it was sent. The station that hears the most stations, and hears them best,\nis the natural choice for net control. This station's own figures, from the last half hour, are on the first row. Click a heading to sort.", justify="left").pack(anchor="w", padx=8, pady=(8, 0))  # what it shows
        tree = self.table(top, (("call", "Station", 90), ("when", "Received (UTC)", 120), ("grid", "Grid", 60), ("power", "Power", 60), ("count", "Hears", 50), ("median", "Median signal", 100), ("list", "Stations it hears (signal, fastest level)", 420)))  # the columns
        rows = [(time.time(), (self.settings["call"] or "this station") + " (now)", telemetry.parse(self.telemetry_text()))]  # this station's own figures first
        rows += sorted(self.telemetry_in, key=lambda item: telemetry.score(item[2]), reverse=True)  # then what others have sent, best first
        latest = {}  # keep only the newest telemetry from each station
        for when, call, info in rows:  # each message
            if call not in latest or when > latest[call][0]:  # the newest from this station
                latest[call] = (when, info)  # keep it
        for call, (when, info) in latest.items():  # one row each
            count, median = telemetry.score(info)  # the comparison figures
            heard = ", ".join(f"{name} {snr:+d} L{level}" for name, snr, level in info["stations"])  # the stations it hears
            tree.insert("", "end", values=(call, utc(when), info["grid"], f"{info['power_w']:.0f} W" if info["power_w"] is not None else "?", count, f"{median:+.0f} dB" if info["stations"] else "", heard))  # one row
        tree.bind("<Double-1>", lambda event: use())  # a double-click puts the callsign in To
        tree.bind("<Return>", lambda event: use())  # so does Enter

        def use():  # put the selected station in To
            rows = tree.selection()  # the selected row
            if rows and not tree.set(rows[0], "call").endswith("(now)"):  # another station
                self.to.set(tree.set(rows[0], "call"))  # into the To box
                top.destroy()  # close the window

        children = tree.get_children()  # its rows
        if children:  # there are some
            tree.focus(children[0])  # the first row has the keyboard
            tree.selection_set(children[0])  # and is selected
        tree.focus_set()  # the list has the keyboard
        buttons = ttk.Frame(top)  # the row of buttons
        buttons.pack(fill="x", padx=8, pady=(0, 8))  # at the bottom
        ttk.Button(buttons, text="Send our telemetry to To", command=self.send_telemetry).pack(side="left")  # send this station's own
        ttk.Button(buttons, text="Broadcast our telemetry", command=self.broadcast_telemetry).pack(side="left", padx=4)  # to everyone
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close the window

    # ---- propagation predictions (since 0.32) ----

    def station_grid(self, call):  # the grid locator known for a callsign
        """Return the grid locator of `call` from the contact book or the Stations heard list, or "" if none is known."""
        call = (call or "").strip().upper()  # as written in capitals
        grid = self.contacts.get(call, {}).get("grid", "") if call else ""  # a saved contact's grid
        if not grid and call in self.heard_rows:  # heard instead
            grid = self.stations.set(self.heard_rows[call], "grid")  # its grid from the list
        return grid or ""  # the grid, or nothing

    def propagation_selected(self):  # right click on a station > Propagation to this station
        rows = self.stations.selection()  # the selected station
        call = self.stations.set(rows[0], "who") if rows else self.to.get()  # it, or the To box
        self.propagation_window(call)  # open the window for it

    def propagation_window(self, call=None):  # Stations > Propagation (Ctrl+P)
        """Open the propagation window: P.533 predictions from this station to a grid locator, every hour of a month, Kestrel's calling frequency on each band."""
        call = (self.to.get() if call is None else call).strip().upper()  # the station asked about (the To box unless told)
        top = self.window("propagation", "Kestrel - propagation (ITU-R P.533)")  # the window
        top.columnconfigure(0, weight=1)  # the table takes the width
        top.rowconfigure(3, weight=1)  # and the height
        form = ttk.Frame(top, padding=8)  # the settings row
        form.grid(row=0, column=0, sticky="ew")  # at the top
        ttk.Label(form, text=f"From {self.settings['grid'] or '(set your grid in Settings)'} to grid").grid(row=0, column=0, sticky="w")  # this station's grid
        to_grid = ttk.Entry(form, width=8)  # the far end's grid
        to_grid.insert(0, self.station_grid(call))  # filled in when known
        to_grid.grid(row=0, column=1, padx=(4, 10))  # place it
        ttk.Label(form, text=f"({call})" if call else "").grid(row=0, column=2, sticky="w")  # whose grid it is
        today = time.gmtime()  # this month
        months = [f"{today.tm_year + (today.tm_mon - 1 + i) // 12:04d}-{(today.tm_mon - 1 + i) % 12 + 1:02d}" for i in range(12)]  # this month and the eleven after it
        month = tk.StringVar(value=months[0])  # the month chosen
        ttk.Label(form, text="Month").grid(row=0, column=3, padx=(10, 4))  # label
        ttk.Combobox(form, textvariable=month, values=months, state="readonly", width=8).grid(row=0, column=4)  # the choice
        ttk.Label(form, text="Power (W)").grid(row=0, column=5, padx=(10, 4))  # label
        power = ttk.Entry(form, width=6)  # transmitter power
        power.insert(0, str(self.settings.get("prop_power_w") or self.settings.get("max_power_w") or "100"))  # as last used, or the radio's full power
        power.grid(row=0, column=6)  # place it
        noise_names = list(propagation.NOISE_CHOICES.values())  # the man-made noise choices, in words
        noise = tk.StringVar(value=propagation.NOISE_CHOICES.get(self.settings.get("prop_noise", "RURAL"), "Rural"))  # as last used
        ttk.Label(form, text="Noise here").grid(row=0, column=7, padx=(10, 4))  # label
        ttk.Combobox(form, textvariable=noise, values=noise_names, state="readonly", width=12).grid(row=0, column=8)  # the choice
        ttk.Label(form, text="Sunspot number").grid(row=1, column=0, sticky="w", pady=(6, 0))  # label
        ssn_box = ttk.Entry(form, width=8)  # an override (blank = the prediction)
        ssn_box.insert(0, str(self.settings.get("prop_ssn_override", "") or ""))  # as last left
        ssn_box.grid(row=1, column=1, padx=(4, 10), pady=(6, 0))  # place it
        ssn_note = ttk.Label(form, text="")  # what the prediction gives
        ssn_note.grid(row=1, column=2, columnspan=7, sticky="w", pady=(6, 0))  # place it
        set_line = ttk.Label(top, text="", font="KestrelSmall")  # which prediction set is in use, and its date
        set_line.grid(row=1, column=0, sticky="w", padx=8)  # under the settings
        now_line = ttk.Label(top, text=propcheck.describe_summary(), wraplength=900, justify="left", font="KestrelSmall")  # the bands now, and the prediction check (since 0.35)
        now_line.grid(row=6, column=0, sticky="w", padx=8, pady=(0, 6))  # under the buttons
        advice = ttk.Label(top, text="", wraplength=760, justify="left")  # the suggestion
        advice.grid(row=2, column=0, sticky="w", padx=8, pady=(6, 4))  # above the table
        bands = list(propagation.band_frequencies())  # the bands predicted
        middle = ttk.Frame(top)  # a holder for the table (which places itself by packing)
        middle.grid(row=3, column=0, sticky="nsew")  # filling the middle of the window
        tree = self.table(middle, [("utc", "UTC", 50), ("local", "Local", 50)] + [(b, b, 130) for b in bands] + [("muf", "MUF", 60), ("best", "Best", 60)], height=24)  # one row per hour
        ttk.Label(top, text="Each band: reliability (per cent of days L0 works), median SNR in 2.5 kHz, the fastest level expected, and the path (NVIS, one hop, two hops or more).\n"
                  "P.533 predicts the month's typical conditions; a flare or a geomagnetic storm on a given day is not in it.", font="KestrelSmall", justify="left").grid(row=4, column=0, sticky="w", padx=8)  # how to read it
        buttons = ttk.Frame(top, padding=8)  # the row of buttons
        buttons.grid(row=5, column=0, sticky="ew")  # at the bottom
        state = {"busy": False}  # whether a prediction is running

        def show_set():  # the prediction set line and the month's sunspot number
            warned = spaceweather.warnings()  # flares, storms, a falling ionosphere (since 0.34R1)
            set_line.configure(text=sunspots.describe() + "\n" + spaceweather.describe() + "".join("\nWARNING: " + w for w in warned), foreground=self.colors["warn_fg"] if warned else "")  # the set in use, today's space weather and any warning
            year, mon = (int(part) for part in month.get().split("-"))  # the month chosen
            value, how = spaceweather.ssn_for(year, mon)  # today's measured number for this month, else the prediction
            predicted = sunspots.ssn_for(year, mon)[0]  # the month's prediction, for comparison
            extra = f"; the month's prediction is {predicted:.0f}" if value is not None and predicted is not None and how.startswith("measured") else ""  # both, when they differ in kind
            ssn_note.configure(text=f"blank = {value:.0f} for {month.get()} ({how}{extra})" if value is not None else "no prediction set: type a number")  # say so

        def predict():  # the Predict button
            if state["busy"]:  # one already running
                return  # wait for it
            grid = to_grid.get().strip().upper()  # the far end
            if not self.settings["grid"]:  # this station's grid is not set
                messagebox.showinfo("Kestrel", "Set your own grid locator in Settings > Station first.", parent=top)  # say so
                return  # nothing to do
            year, mon = (int(part) for part in month.get().split("-"))  # the month
            try:  # the typed numbers may be nonsense
                watts = float(power.get() or 100)  # transmitter power
                ssn = float(ssn_box.get()) if ssn_box.get().strip() else spaceweather.ssn_for(year, mon)[0]  # the sunspot number: typed, measured today (current month) or predicted
            except ValueError:  # not numbers
                messagebox.showerror("Kestrel", "Power and sunspot number must be numbers.", parent=top)  # say so
                return  # nothing to do
            if ssn is None:  # no number at all
                messagebox.showerror("Kestrel", "There is no sunspot prediction; type a sunspot number.", parent=top)  # say so
                return  # nothing to do
            code = {v: k for k, v in propagation.NOISE_CHOICES.items()}.get(noise.get(), "RURAL")  # the noise setting as P.533 names it
            self.settings.update(prop_power_w=f"{watts:g}", prop_noise=code, prop_ssn_override=ssn_box.get().strip())  # remembered
            self.save_settings()  # kept
            state["busy"] = True  # running
            fetch = " (first downloading that month's ionosphere map from the ITU, 11 MB, once)" if propagation.needs_download(mon) else ""  # a month not shipped with the program (since 0.38)
            advice.configure(text=f"Predicting {self.settings['grid']} to {grid}, {month.get()}, sunspot number {ssn:.0f}{fetch}...")  # say so
            out = queue.Queue()  # the answer comes back through this

            def job():  # the background part (the ITU program takes a second or two)
                try:  # it may fail
                    out.put(propagation.predict(self.settings["grid"], grid, year, mon, ssn, watts, code))  # the rows
                except Exception as error:  # anything at all: say it in the window
                    out.put(error)  # the error instead

            def collect():  # look for the answer
                if out.empty():  # not yet
                    top.after(200, collect)  # look again soon
                    return  # wait
                state["busy"] = False  # done
                rows = out.get()  # the answer
                if isinstance(rows, Exception):  # it failed
                    advice.configure(text=f"No prediction: {rows}")  # say why
                    return  # nothing to show
                fill(rows)  # show it

            threading.Thread(target=job, daemon=True).start()  # run it
            top.after(200, collect)  # and wait for it

        def fill(rows):  # show a prediction
            tree.delete(*tree.get_children())  # empty the table
            now = time.gmtime().tm_hour  # the hour now, UTC
            names = {"nvis": "NVIS", "moderate": "1 hop", "poor": "2+ hops"}  # paths in short words
            offset = -time.timezone // 3600 if not time.localtime().tm_isdst else -time.altzone // 3600  # local time's difference from UTC, hours
            for hour in range(24):  # each hour
                here = {r["band"]: r for r in rows if r["hour"] == hour}  # its bands
                best = propagation.best_at(rows, hour)  # the best band then
                cells = []  # one cell per band
                for band in bands:  # each band
                    r = here.get(band)  # its row
                    cells.append(f"{r['reliability']:3.0f}% {r['snr']:+3.0f} {'L' + str(r['level']) if r['level'] is not None else '--'} {names[r['condition']]}" if r else "")  # reliability, SNR, level, path
                muf = next(iter(here.values()))["muf"] if here else 0.0  # the hour's MUF (the same for every band)
                item = tree.insert("", "end", values=(f"{hour:02d}00", f"{(hour + offset) % 24:02d}00", *cells, f"{muf:.1f}", best["band"] if best else "-"))  # the row
                if hour == now:  # the hour now
                    tree.selection_set(item)  # highlighted
                    tree.see(item)  # and in view
            advice.configure(text=propagation.suggestion(rows, now) + "  " + "  ".join(f"{band} best at {', '.join(f'{h:02d}' for h in propagation.best_times(rows, band))} UTC." for band in bands if propagation.best_times(rows, band)))  # the suggestion now, and each band's best hours

        def bands_now():  # the Check the bands now button (since 0.35)
            far = to_grid.get().strip().upper()  # the far end
            own = self.settings["grid"]  # this station
            if not own:  # not set
                messagebox.showinfo("Kestrel", "Set your own grid locator in Settings > Station first.", parent=top)  # say so
                return  # nothing to do
            now_line.configure(text="Checking the bands now (ionosondes, WSPR, PSK Reporter)...")  # say so

            def job():  # in the background (three web services)
                lines = []  # the answer
                try:  # the ionosondes
                    lines.append(skywatch.describe_window(skywatch.nvis_window(own, far or None)))  # the short-path window
                except Exception as error:  # noqa: BLE001 - shown, not raised
                    lines.append(f"Short-path window: could not be fetched ({error})")  # why
                if far:  # a path to look at
                    wspr, psk = {}, {}  # spots by band
                    try:  # WSPR
                        wspr = skywatch.wspr_activity(own, far)  # spots
                    except Exception as error:  # noqa: BLE001
                        lines.append(f"WSPR spots: could not be fetched ({error})")  # why
                    try:  # PSK Reporter
                        psk = skywatch.psk_activity(own, far)  # reports
                    except Exception as error:  # noqa: BLE001
                        lines.append(f"PSK Reporter: could not be fetched ({error})")  # why
                    lines.append(skywatch.describe_activity(wspr, psk))  # by band
                    busy = skywatch.busiest(wspr, psk)  # the band with most
                    if busy:  # one
                        lines.append(f"Most activity on this path now: {busy}")  # say so
                else:  # no far end
                    lines.append("Type the other station's grid to see band activity on the path.")  # what is needed
                lines.append(propcheck.describe_summary())  # how good the predictions have been
                top.after(0, lambda: now_line.configure(text="\n".join(lines)) if now_line.winfo_exists() else None)  # shown

            threading.Thread(target=job, daemon=True).start()  # run it

        def update_online():  # the Update online button
            def job():  # in the background (the internet may be slow)
                try:  # it may fail
                    data = sunspots.update_online()  # fetch NOAA's prediction
                    try:  # today's measured ionosphere and space weather (since 0.34R1); the prediction is still useful without them
                        spaceweather.update_online()  # fetch and keep them
                        extra = "Today's measured sunspot number and space weather updated too."  # said
                    except OSError as error:  # none of those sources answered
                        extra = f"Today's space weather could not be fetched ({error})."  # said
                    top.after(0, lambda: (show_set(), messagebox.showinfo("Kestrel", f"Sunspot predictions updated from NOAA (issued {data['issued']}). {extra}", parent=top)))  # say so
                except Exception as error:  # no internet, or NOAA's file changed
                    top.after(0, lambda: messagebox.showerror("Kestrel", f"Could not update online: {error}\n\nThe predictions already here are still used. An update file can also be placed in:\n{sunspots.updates_folder()}", parent=top))  # say why
            threading.Thread(target=job, daemon=True).start()  # run it

        def load_file():  # the Load update file button
            path = filedialog.askopenfilename(parent=top, title="Kestrel sunspot update file", filetypes=[("Kestrel sunspot predictions", "sunspots*.json"), ("All files", "*.*")])  # choose it
            if not path:  # none chosen
                return  # nothing to do
            try:  # it may not be one of ours
                data = sunspots.import_file(path)  # check it and copy it into the updates folder
            except (OSError, ValueError) as error:  # unusable
                messagebox.showerror("Kestrel", f"That file cannot be used: {error}", parent=top)  # say why
                return  # nothing changed
            show_set()  # the line again
            messagebox.showinfo("Kestrel", f"Update file loaded (issued {data['issued']}). The prediction set with the latest issue date is used.", parent=top)  # say so

        ttk.Button(buttons, text="Predict", command=predict).pack(side="left")  # run it
        ttk.Button(buttons, text="Update online", command=update_online).pack(side="left", padx=(8, 0))  # fetch NOAA's predictions, and today's eSSN and space weather
        ttk.Button(buttons, text="Check the bands now", command=lambda: bands_now()).pack(side="left", padx=(8, 0))  # ionosonde and spots (since 0.35)
        ttk.Button(buttons, text="Load update file...", command=load_file).pack(side="left", padx=(8, 0))  # a file sent by hand
        ttk.Button(buttons, text="Open updates folder", command=lambda: self.open_path(sunspots.updates_folder())).pack(side="left", padx=(8, 0))  # where update files go
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close the window
        month.trace_add("write", lambda *args: show_set())  # a new month: its sunspot number
        show_set()  # the line now
        why = propagation.missing()  # is the ITU program here?
        if why:  # no
            advice.configure(text=why)  # say what is missing
        elif to_grid.get():  # a grid is known
            predict()  # predict straight away
        to_grid.bind("<Return>", lambda event: predict())  # Enter predicts
        to_grid.focus_set()  # the grid box has the keyboard

    def shortcuts_window(self):  # Help > Keyboard shortcuts
        top = self.window("keys", "Kestrel - keyboard shortcuts")  # the window
        tree = self.table(top, (("key", "Key", 170), ("detail", "Does", 430)), height=len(SHORTCUTS))  # the list
        for key, job in SHORTCUTS:  # each shortcut
            tree.insert("", "end", values=(key, job))  # one row
        tree.focus_set()  # the list has the keyboard
        ttk.Button(top, text="Close", command=top.destroy).pack(pady=(0, 8))  # close the window

    def focus_stations(self):  # Ctrl+G: the stations list on the main window
        self.stations.focus_set()  # the list has the keyboard
        children = self.stations.get_children()  # its rows
        if children and not self.stations.focus():  # nothing has the keyboard's attention yet
            self.stations.focus(children[0])  # the first row
            self.stations.selection_set(children[0])  # selected

    # ---- the stations list and the outbox ----

    def refresh_to(self):  # (re)fill the To box's list
        self.to["values"] = ["ALL"] + sorted(self.contacts) + [call for call in self.heard_rows if call not in self.contacts]  # ALL first (every station: a broadcast, or a long note to everyone; since 0.34), then saved contacts, then the other stations heard

    def pick_station(self):  # a callsign in the stations list was chosen
        for row in self.stations.selection()[:1]:  # the row chosen
            self.to.set(self.stations.set(row, "who"))  # its callsign goes into the To box
            self.message.focus_set()  # ready to type a message

    def save_contact(self):  # keep the selected callsigns as contacts
        rows = self.stations.selection()  # the selected rows
        if len(rows) == 1:  # one station: open its record to fill in (since 0.31R3)
            self.open_station_record()  # as a double-click does
            return  # the window does the rest
        for row in rows:  # several: each is saved as it is
            call = self.stations.set(row, "who")  # its callsign
            if call not in self.contacts:  # not saved yet (a saved one keeps its record)
                self.contacts.put(call, grid=self.stations.set(row, "grid"), band=self.stations.set(row, "band"))  # remember it, with its grid locator and band if known
                self.seed_contact_log(call)  # and what was heard of it in the last 48 hours (since 0.38R2)
            self.stations.set(row, "saved", "*")  # mark the row
        self.refresh_to()  # and offer them first in the To box

    def remove_from_list(self):  # take the selected stations off Stations heard; contact records are kept (since 0.39)
        """Remove the selected rows from Stations heard. A saved contact's record stays in the contact book (Stations > Contacts deletes records); a station comes back on the list when it is heard again."""
        rows = list(self.stations.selection())  # the selected rows
        if not rows:  # none
            messagebox.showinfo("Kestrel", "Select a station in the Stations heard list first.", parent=self.root)  # say so
            return  # nothing to do
        calls = []  # the callsigns taken off
        for row in rows:  # each one
            call = self.stations.set(row, "who")  # its callsign
            self.stations.delete(row)  # off the list
            if self.heard_rows.get(call) == row:  # the row kept for it
                del self.heard_rows[call]  # forgotten (a new row is made when it is heard again)
            self.calling.pop(call, None)  # no longer highlighted as calling
            calls.append(call)  # counted
        kept = [call for call in calls if call in self.contacts]  # the saved contacts among them
        self.refresh_to()  # the To box offers what is left
        self.say(f"removed {', '.join(calls)} from Stations heard" + (f"; the contact record{'s' if len(kept) > 1 else ''} of {', '.join(kept)} {'are' if len(kept) > 1 else 'is'} kept (Stations > Contacts)" if kept else ""))  # confirm

    def contacts_window(self):  # Stations > Contacts: view, search, open, add and delete contact records (since 0.39)
        top = self.window("contacts", "Kestrel - Contacts")  # the window
        top.geometry("1000x480")  # a useful size
        bar = ttk.Frame(top)  # the search line
        bar.pack(fill="x", padx=8, pady=(8, 0))  # at the top
        ttk.Label(bar, text="Search").pack(side="left")  # label
        wanted = tk.StringVar()  # what is typed
        search = ttk.Entry(bar, textvariable=wanted, width=30)  # the search box
        search.pack(side="left", padx=6)  # place it
        ttk.Label(bar, text="callsign, name, location, grid, radio or notes", font="KestrelSmall").pack(side="left")  # what it looks in
        count = ttk.Label(bar, text="")  # how many are shown
        count.pack(side="right")  # at the right
        zone = local_zone_name()  # this computer's time zone, for the heading
        tree = self.table(top, (("call", "Callsign", 90), ("name", "Name", 110), ("location", "Location", 140), ("grid", "Grid", 60), ("band", "Band", 50), ("radio", "Radio", 110),  # (continued)
                                ("power", "Power W", 64), ("last", "Last heard (UTC)", 120), ("local", f"Local ({zone})", 100), ("traffic", "Traffic rows", 80)), height=16)  # the contacts, sortable by any heading

        def fill(*_):  # (re)fill the list, keeping only what matches the search
            words = wanted.get().strip().lower().split()  # the search, word by word
            tree.delete(*tree.get_children())  # empty it
            with self.contacts.lock:  # a consistent book
                records = [dict(record) for record in self.contacts.values()]  # a copy of each record
            shown = 0  # rows added
            for record in sorted(records, key=lambda r: r["call"]):  # in callsign order
                text = " ".join(str(record.get(name, "") or "") for name in ("call", "name", "location", "grid", "radio", "antenna", "notes")).lower()  # what the search looks in
                if any(word not in text for word in words):  # not every word found
                    continue  # left out
                heard_t = (record.get("last_heard") or {}).get("t")  # when it was last heard
                tree.insert("", "end", iid=record["call"], values=(record["call"], record.get("name", ""), record.get("location", ""), record.get("grid", ""), record.get("band", ""), record.get("radio", ""),  # (continued)
                                                                   record.get("power_w", ""), utc(heard_t) if heard_t else "", local_time(heard_t) if heard_t else "", len(record.get("log", []))))  # one contact
                shown += 1  # counted
            count.configure(text=f"{shown} of {len(records)} contacts")  # how many

        def chosen():  # the callsigns selected
            return list(tree.selection())  # the row ids are the callsigns

        def open_it():  # open the selected contact's record
            calls = chosen()  # the selection
            if calls:  # one is chosen
                self.contact_window(calls[0])  # its record, to view and change

        def delete_them():  # delete the selected records, after asking
            calls = [call for call in chosen() if call in self.contacts]  # the selection
            if not calls:  # none
                return  # nothing to do
            rows = sum(len(self.contacts[call].get("log", [])) + len(self.contacts[call]["history"]) for call in calls)  # the history they hold
            if messagebox.askyesno("Kestrel - Delete Contact", f"Delete {', '.join(calls)}?\n\nThe record{'s' if len(calls) > 1 else ''} and {rows} traffic and session row{'s' if rows != 1 else ''} are removed from contacts.json. This cannot be undone.\n\nLogbook entries, messages and the 48-hour list of stations heard are kept.", icon="warning", parent=top):  # ask first
                for call in calls:  # each one
                    self.forget_contact(call)  # out of the book (and its "saved" mark off the list)
                fill()  # the list again

        def call_it():  # call the selected contact
            calls = chosen()  # the selection
            if calls:  # one is chosen
                self.to.set(calls[0])  # into the To box
                self.call_to()  # call it by name

        wanted.trace_add("write", fill)  # filter as the search is typed
        tree.bind("<Double-1>", lambda event: open_it())  # a double-click opens the record
        tree.bind("<Return>", lambda event: open_it())  # so does Enter
        tree.bind("<Delete>", lambda event: delete_them())  # Delete asks, then deletes
        buttons = ttk.Frame(top)  # the buttons
        buttons.pack(fill="x", padx=8, pady=8)  # at the bottom
        ttk.Button(buttons, text="New contact...", command=lambda: self.contact_window("")).pack(side="left")  # a record for a callsign to type
        ttk.Button(buttons, text="Open / edit", command=open_it).pack(side="left", padx=4)  # view and change the selected one
        ttk.Button(buttons, text="Call  Ctrl+Y", command=call_it).pack(side="left", padx=4)  # call it by name
        ttk.Button(buttons, text="Delete...", command=delete_them).pack(side="left", padx=(16, 4))  # delete the selected records (asks first)
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close the window
        self.contacts_refresh = lambda: fill() if top.winfo_exists() else None  # the list follows changes made in a contact's own window
        fill()  # the first filling
        search.focus_set()  # ready to type a search


    def add_contact(self):  # the Add Contact button, under the To box (since 0.31R3)
        call = self.to.get().strip().upper()  # the callsign in the To box, if any
        if call and call in self.contacts:  # already a contact
            self.say(f"{call} is already a contact; opening its record")  # say so
        self.contact_window(call)  # a new record (for that callsign, or one to type), or the saved one

    def edit_contact(self):  # the Edit Contact button, under the To box (since 0.31R3)
        call = self.to.get().strip().upper()  # the callsign in the To box, if any
        if call in self.contacts:  # a saved contact
            self.contact_window(call)  # its record
            return  # done
        if not self.contacts:  # no contacts at all
            messagebox.showinfo("Kestrel", "There are no saved contacts yet. Use Add Contact, or double-click a station in Stations heard.", parent=self.root)  # say how to make one
            return  # nothing to edit
        if call:  # a callsign that is not saved
            if messagebox.askyesno("Kestrel", f"{call} is not a contact yet.\n\nAdd it as a new contact?", parent=self.root):  # offer to add it
                self.contact_window(call)  # a new record for it
            return  # done
        self.contacts_window()  # no callsign: the contacts list, to search and pick one (since 0.39)

    def clear_message(self):  # the Clear button under Queue message (since 0.40)
        self.message.delete(0, "end")  # the message box emptied
        self.message.focus_set()  # ready to type again

    def big_text(self, parent, words, height):  # a read-only text area in larger letters, for reading a message in full (since 0.40)
        """Return a Text widget in `parent` holding `words`, wrapped, read-only, in the panel's font four points larger."""
        size = int(self.settings.get("font_size") or 9) + 4  # larger than the lists
        box = tk.Text(parent, height=height, width=60, wrap="word", font=(self.settings.get("font_family") or "Segoe UI", size))  # the area
        box.configure(background=self.colors["text_bg"], foreground=self.colors["text_fg"], insertbackground=self.colors["text_fg"], padx=8, pady=6)  # in the chosen look
        box.insert("1.0", words)  # the words
        box.configure(state="disabled")  # read only (it can still be selected and copied)
        return box  # for placing

    def copy_text(self, words):  # put words on the clipboard (since 0.40)
        self.root.clipboard_clear()  # empty it
        self.root.clipboard_append(words)  # the words
        self.say("copied to the clipboard")  # confirm

    def message_detail_window(self):  # a double-click on Messages received: the message in full, in a window of its own (since 0.40)
        rows = self.received.selection()  # the chosen row
        if not rows:  # none
            return  # nothing to show
        clock, who, text = (self.received.set(rows[0], name) for name in ("time", "who", "text"))  # what the list shows
        sender = who.split()[0] if who.split() else ""  # the sender's callsign (the list may add "to ALL" or "(long note)")
        kind = "long note" if "(long note)" in who else ("broadcast to ALL" if "ALL" in who.split() else "message")  # what it was
        found = next((row for row in reversed((self.contacts.get(sender) or {}).get("log", [])) if row.get("dir") == "RX" and row.get("text", "").strip() == text.strip()), None)  # its row in the sender's traffic log, when the sender is a saved contact
        top = self.window("message", f"Kestrel - message from {sender or 'unknown'}")  # the window
        head = ttk.Frame(top, padding=(10, 10, 10, 4))  # the facts about it
        head.pack(fill="x")  # at the top
        facts = [("From", sender), ("What", kind), ("Received", f"{clock} (local)" + (f"  \u00b7  {utc(found['t'])} UTC" if found else ""))]  # always known
        if found:  # more from the traffic log
            facts.append(("Heard", "  \u00b7  ".join(part for part in (found.get("band", ""), f"{found['dial_khz']:.1f} kHz" if found.get("dial_khz") else "", found.get("level", ""), f"{found['snr_db']:+.0f} dB" if found.get("snr_db") is not None else "") if part)))  # band, frequency, level, signal
        facts.append(("Length", f"{len(text)} characters"))  # how long it is
        for row, (label, value) in enumerate(facts):  # each fact
            ttk.Label(head, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12))  # its label
            ttk.Label(head, text=value).grid(row=row, column=1, sticky="w")  # its value
        self.big_text(top, text, height=6).pack(fill="both", expand=True, padx=10, pady=6)  # the message, large and wrapped
        buttons = ttk.Frame(top, padding=(10, 4, 10, 10))  # the buttons
        buttons.pack(fill="x")  # at the bottom

        def reply():  # answer it
            self.to.set(sender)  # the sender into To
            top.destroy()  # close
            self.message.focus_set()  # ready to type

        ttk.Button(buttons, text="Reply", command=reply).pack(side="left")  # write back to the sender
        ttk.Button(buttons, text="Copy", command=lambda: self.copy_text(text)).pack(side="left", padx=4)  # the text to the clipboard
        if sender:  # a station to look up
            ttk.Button(buttons, text="Contact record...", command=lambda: self.contact_window(sender)).pack(side="left", padx=4)  # its record
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close

    def station_detail_window(self):  # a double-click on Stations heard: everything shown about the station, in full (since 0.40)
        rows = self.stations.selection()  # the chosen row
        if not rows:  # none
            return  # nothing to show
        values = {name: self.stations.set(rows[0], name) for name in ("saved", "who", "grid", "band", "snr", "time", "text", "mail")}  # what the list shows
        call = values["who"]  # its callsign
        self.to.set(call)  # into the To box, as a double-click did before
        record = self.contacts.get(call) or {}  # its contact record, if saved
        top = self.window("station detail", f"Kestrel - {call}")  # the window
        head = ttk.Frame(top, padding=(10, 10, 10, 4))  # the facts
        head.pack(fill="x")  # at the top
        apart = distance_bearing(self.settings["grid"], values["grid"]) if values["grid"] else None  # how far, which way
        heard = [r for r in self.heardlog.snapshot() if r.get("call") == call]  # its receptions in the last 48 hours
        facts = [("Callsign", call + ("   (saved contact)" if values["saved"] else "")),  # who
                 ("Name, location", ", ".join(part for part in (record.get("name", ""), record.get("location", "")) if part) or "—"),  # from its record
                 ("Grid", values["grid"] + (f"   {apart[0]:.0f} mi, bearing {apart[1]:.0f}°" if apart else "")),  # where
                 ("Rig", "  \u00b7  ".join(part for part in (record.get("radio", ""), f"{record['power_w']} W" if record.get("power_w") else "", record.get("antenna", "")) if part) or "—"),  # what it runs
                 ("Last heard", "  \u00b7  ".join(part for part in (values["time"], values["band"], values["snr"], values["text"]) if part)),  # how it was last heard
                 ("Last 48 hours", f"heard {len(heard)} time{'s' if len(heard) != 1 else ''}" + (f", best {max(r.get('snr', -99) for r in heard):+.0f} dB" if heard else ""))]  # the longer record
        checked = propcheck.describe_station(call)  # against the prediction
        if checked:  # something recorded
            facts.append(("Against prediction", checked))  # shown
        for row, (label, value) in enumerate(facts):  # each fact
            ttk.Label(head, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=1)  # its label
            ttk.Label(head, text=value, wraplength=520, justify="left").grid(row=row, column=1, sticky="w", pady=1)  # its value
        ttk.Label(top, text="Status and messages", padding=(10, 6, 10, 0)).pack(anchor="w")  # the long column, in full
        self.big_text(top, values["mail"] or "(nothing)", height=4).pack(fill="both", expand=True, padx=10, pady=4)  # large and wrapped
        buttons = ttk.Frame(top, padding=(10, 4, 10, 10))  # the buttons
        buttons.pack(fill="x")  # at the bottom
        ttk.Button(buttons, text="Respond  Ctrl+Y", command=lambda: (top.destroy(), self.respond())).pack(side="left")  # call it
        ttk.Button(buttons, text="Contact record...", command=lambda: self.contact_window(call)).pack(side="left", padx=4)  # its record (saved, or new from what was heard)
        ttk.Button(buttons, text="Last 48 hours", command=lambda: self.heard_window(call)).pack(side="left", padx=4)  # every reception
        ttk.Button(buttons, text="Propagation...", command=lambda: self.propagation_window(call)).pack(side="left", padx=4)  # best band by hour
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")  # close

    def open_station_record(self):  # a double-click on a station heard (since 0.31R3)
        for row in self.stations.selection()[:1]:  # the row chosen
            call = self.stations.set(row, "who")  # its callsign
            self.to.set(call)  # into the To box, as a double-click did before
            self.contact_window(call)  # its record: the saved one, or a new one filled in from what was heard

    def heard_details(self, call):  # what is known of a station from the 48-hour list of stations heard
        """Return the latest reception of `call` in the 48-hour heard log as a dict (t, grid, snr, level, kind, dial_khz), or None."""
        latest, grid = None, ""  # nothing yet
        for record in self.heardlog.snapshot():  # every reception, oldest first
            if record.get("call") == call:  # this station
                latest = record  # the latest so far
                grid = record.get("grid") or grid  # a grid, once one is known
        if latest is None:  # never heard (in 48 hours)
            return None  # nothing known
        return dict(latest, grid=grid)  # the latest reception, with the grid if any reception carried one

    def seed_contact_log(self, call):  # a newly saved contact gets what was heard of it in the last 48 hours (since 0.38R2)
        """Copy `call`'s receptions from the 48-hour heard log into its traffic log in the contact book (rows already there are skipped)."""
        rows = [{"t": record.get("t", 0), "dir": "RX", "what": record.get("kind") or "heard", "band": band_of(record.get("dial_khz") or 0) if record.get("dial_khz") else "",  # (continued)
                 "dial_khz": record.get("dial_khz") or 0.0, "level": f"L{record['level']}" if record.get("level") is not None else "", "snr_db": record.get("snr"), "text": ""}  # one row per reception
                for record in self.heardlog.snapshot() if record.get("call") == call]  # this station's receptions
        if rows:  # something was heard
            self.contacts.add_log(call, rows)  # into its traffic log

    def forget_contact(self, call):  # take a contact out of the book and the lists
        self.contacts.delete(call)  # out of the book and its file, history and all
        row = self.heard_rows.get(call)  # its row in Stations heard, if any
        if row is not None:  # listed
            if self.stations.set(row, "text") == "saved contact":  # listed only because it was saved (not heard this session)
                self.stations.delete(row)  # take the row away
                del self.heard_rows[call]  # and forget it
            else:  # heard this session
                self.stations.set(row, "saved", "")  # unmark it
        self.refresh_to()  # the To list
        self.say(f"{call} deleted from your contacts")  # confirm
        if getattr(self, "contacts_refresh", None):  # the Contacts window may be open (since 0.39)
            self.contacts_refresh()  # it shows the change

    def contact_window(self, call=""):  # a contact's record: add, edit or delete it (since 0.31R3)
        """Open the record of `call`: the saved one, or a new one. A new one is filled in from the 48-hour list of stations heard when the station was heard (callsign, grid locator, band, frequency, level and signal)."""
        call = (call or "").strip().upper()  # the callsign, if any
        saved = call in self.contacts  # a saved contact?
        record = dict(self.contacts[call]) if saved else {"call": call, "name": "", "location": "", "grid": "", "radio": "", "power_w": "", "antenna": "", "notes": "", "last_heard": {}, "history": []}  # a copy to show
        heard = None if saved or not call else self.heard_details(call)  # for a new contact, what was heard of it
        if heard is not None:  # it was heard
            record["grid"] = heard.get("grid", "")  # its grid, if it sent one
            record["last_heard"] = {"t": heard.get("t"), "band": band_of(heard.get("dial_khz") or 0), "dial_khz": heard.get("dial_khz"), "level": level_name(heard.get("level", 0)), "snr_db": heard.get("snr")}  # how it was heard
        top = self.window(f"contact {call}", f"Kestrel - {'Contact' if saved else 'New Contact'}{' - ' + call if call else ''}")  # the window
        top.columnconfigure(0, weight=1)  # it takes the width
        top.columnconfigure(1, weight=1)  # both halves
        top.rowconfigure(4, weight=1)  # the history takes the spare height
        if not saved and heard is not None:  # filled in from what was heard: say so
            ttk.Label(top, text=f"{call} is not in your contacts yet. The grid locator, band, frequency, level and signal were filled in from what was heard at {time.strftime('%H:%M:%S', time.gmtime(heard['t']))} UTC (Stations heard). Nothing is saved until you click Save.", wraplength=820, justify="left").grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))  # the note
        elif not saved:  # a new contact from nothing
            ttk.Label(top, text="A new contact. Nothing is saved until you click Save.", justify="left").grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))  # the note
        boxes = {}  # the text boxes, by field name

        def box(frame, row, name, label, width=28, readonly=False):  # one labeled text box
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(4, 8), pady=3)  # its label
            entry = ttk.Entry(frame, width=width)  # the box
            entry.insert(0, str(record.get(name, "") or ""))  # what is known
            if readonly:  # the callsign of a saved contact cannot change (delete it and add the new one)
                entry.configure(state="readonly")  # shown but not changed
            entry.grid(row=row, column=1, sticky="w", pady=3)  # place it
            boxes[name] = entry  # keep it
            return entry  # for wiring

        station = ttk.LabelFrame(top, text="Station", padding=8)  # who and where
        station.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(10, 0))  # the left half
        box(station, 0, "call", "Callsign", width=14, readonly=saved)  # the callsign
        box(station, 1, "name", "Name")  # the operator's name
        box(station, 2, "location", "Location")  # where
        grid_box = box(station, 3, "grid", "Grid locator", width=10)  # the grid locator
        ttk.Label(station, text=f"From {self.settings['grid'] or 'your grid'}").grid(row=4, column=0, sticky="w", padx=(4, 8), pady=3)  # distance from this station
        away = ttk.Label(station, text="")  # filled in below
        away.grid(row=4, column=1, sticky="w", pady=3)  # place it

        def show_distance(event=None):  # the distance and bearing, as the grid is typed
            found = distance_bearing(self.settings["grid"], grid_box.get())  # from this station's grid
            away.configure(text=f"{found[0]:.0f} mi, bearing {found[1]:.0f}°" if found else "(needs both grid locators)")  # or why not

        grid_box.bind("<KeyRelease>", show_distance)  # follow the typing
        show_distance()  # and show it now
        ttk.Label(station, text="Best band now").grid(row=5, column=0, sticky="nw", padx=(4, 8), pady=3)  # the propagation suggestion (since 0.32)
        hint = ttk.Label(station, text="", wraplength=300, justify="left", font="KestrelSmall")  # filled in when the prediction is ready
        hint.grid(row=5, column=1, sticky="w", pady=3)  # place it
        ttk.Button(station, text="Propagation...", command=lambda: self.propagation_window(boxes["call"].get())).grid(row=6, column=1, sticky="w")  # the full table

        def suggest():  # predict in the background and show the suggestion for this hour
            far, own = grid_box.get().strip(), self.settings["grid"]  # the two grids
            if not far or not own or propagation.missing():  # cannot predict
                hint.configure(text="(needs both grid locators)" if not (far and own) else "(propagation program not installed)")  # say why
                return  # nothing more
            now = time.gmtime()  # this hour and month
            ssn = spaceweather.ssn_for(now.tm_year, now.tm_mon)[0]  # today's measured sunspot number if fresh, else the predicted one
            if ssn is None:  # no prediction set at all
                hint.configure(text="(no sunspot prediction)")  # say so
                return  # nothing more
            hint.configure(text="predicting...")  # say so

            def job():  # the background part
                try:  # it may fail
                    words = propagation.suggestion(propagation.predict(own, far, now.tm_year, now.tm_mon, ssn, float(self.settings.get("prop_power_w") or self.settings.get("max_power_w") or 100), self.settings.get("prop_noise", "RURAL")), now.tm_hour)  # the suggestion for this hour
                except Exception as error:  # anything: say it
                    words = f"(no prediction: {error})"  # why
                top.after(0, lambda: hint.configure(text=words) if hint.winfo_exists() else None)  # shown, if the window is still open

            threading.Thread(target=job, daemon=True).start()  # run it

        grid_box.bind("<FocusOut>", lambda event: suggest())  # predict again when the grid has been typed
        suggest()  # and now
        rig = ttk.LabelFrame(top, text="Rig", padding=8)  # the other station's radio
        rig.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(10, 0))  # the right half
        box(rig, 0, "radio", "Radio")  # the radio
        box(rig, 1, "power_w", "Power (W)", width=8)  # its power
        box(rig, 2, "antenna", "Antenna")  # its antenna
        last = record.get("last_heard") or {}  # how it was last heard
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(last["t"])) if last.get("t") else "not heard yet"  # when
        parts = [when] + [part for part in (last.get("band", ""), f"{last['dial_khz']:.1f} kHz" if last.get("dial_khz") else "", f"audio {last['offset_hz']:+.0f} Hz" if last.get("offset_hz") is not None else "", last.get("level", ""), f"{last['snr_db']:+.0f} dB" if last.get("snr_db") is not None else "") if part]  # what is known
        ttk.Label(rig, text="Last heard").grid(row=3, column=0, sticky="nw", padx=(4, 8), pady=3)  # label
        ttk.Label(rig, text="  \u00b7  ".join(parts), wraplength=380, justify="left").grid(row=3, column=1, sticky="w", pady=3)  # the reading
        checked = propcheck.describe_station(call) if call else ""  # heard and reported SNR against the P.533 prediction, both ways (since 0.39)
        ttk.Label(rig, text="Against prediction").grid(row=4, column=0, sticky="nw", padx=(4, 8), pady=3)  # label
        ttk.Label(rig, text=checked or "nothing checked yet (needs a grid locator and a decoded frame; reports from the station show the other way)", wraplength=380, justify="left").grid(row=4, column=1, sticky="w", pady=3)  # the comparison
        ttk.Label(rig, text="Radio and power fill in by themselves from the station's beacons (and its \"Rig and power\" message or telemetry); the antenna after a contact with it.", font="KestrelSmall", wraplength=400, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))  # where they come from (since 0.38R2)
        notes_row = ttk.Frame(top)  # the notes
        notes_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 0))  # under both halves
        notes_row.columnconfigure(1, weight=1)  # the box takes the width
        ttk.Label(notes_row, text="Notes").grid(row=0, column=0, sticky="nw", padx=(4, 8))  # label
        notes = tk.Text(notes_row, height=3, width=60, wrap="word", font="TkDefaultFont")  # the notes box, in the panel's usual lettering
        notes.insert("1.0", record.get("notes", "") or "")  # what is known
        notes.grid(row=0, column=1, sticky="ew")  # place it
        notes.configure(background=self.colors["text_bg"], foreground=self.colors["text_fg"], insertbackground=self.colors["text_fg"])  # in the chosen look, as the log is
        history = record.get("history", [])  # the history, oldest first
        mode = MODE_NAMES.get(self.settings.get("contact_history_mode", "all"), "All traffic")  # what is recorded
        first_words = "starts with this reception once saved" if not history and heard is not None and self.settings.get("contact_history_mode", "all") == "all" else f"{len(history)} kept"  # how many entries
        traffic = record.get("log", [])  # every beacon, message and call, oldest first (since 0.38R2)
        ttk.Label(top, text=f"History: {len(traffic)} receptions and messages, and sessions {first_words}, up to {self.contacts.limit} (Settings > Contacts; recording: {mode}). Click a heading to sort; again to reverse.").grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 2))  # its heading
        tabs = ttk.Notebook(top)  # two views of the history (since 0.38R2)
        tabs.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=10)  # place them

        def sheet(title, columns, stretch):  # one tab: a sortable list with a scroll bar
            frame = ttk.Frame(tabs)  # the list and its scroll bar
            tabs.add(frame, text=title)  # as a tab
            frame.columnconfigure(0, weight=1)  # the list takes the width
            frame.rowconfigure(0, weight=1)  # and the height
            tree = ttk.Treeview(frame, columns=[name for name, _, _ in columns], show="headings", height=9)  # the list
            for name, heading, width in columns:  # each column
                tree.heading(name, text=heading, anchor="w", command=lambda n=name: self.sort_table(tree, n))  # a click sorts by it
                tree.column(name, width=width, stretch=name == stretch)  # its width (one column takes the rest)
            bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)  # its scroll bar
            tree.configure(yscrollcommand=bar.set)  # joined up
            tree.grid(row=0, column=0, sticky="nsew")  # place the list
            bar.grid(row=0, column=1, sticky="ns")  # and the bar
            return tree  # for filling

        def utc(t):  # a moment in UTC
            return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t or 0))  # as a date and time

        def local(t):  # the same moment in this computer's time zone (since 0.38R2)
            return time.strftime("%m-%d %H:%M", time.localtime(t or 0))  # month, day and time (the year is in the UTC column)

        log_view = sheet("Traffic (each beacon and message)", (("t", "UTC", 118), ("local", f"Local ({local_zone_name()})", 96), ("dir", "Dir", 34), ("what", "What", 92), ("band", "Band", 46), ("khz", "kHz", 62),  # (continued)
                                                              ("lvl", "Level", 44), ("snr", "SNR", 56), ("text", "Message", 300)), "text")  # the traffic log's columns
        for row in reversed(traffic):  # newest first
            log_view.insert("", "end", values=(utc(row.get("t")), local(row.get("t")), row.get("dir", ""), row.get("what", ""), row.get("band", ""), f"{row['dial_khz']:.1f}" if row.get("dial_khz") else "",  # (continued)
                                               row.get("level", ""), f"{row['snr_db']:+.0f} dB" if row.get("snr_db") is not None else "", row.get("text", "")))  # one row
        if not traffic and heard is not None:  # a station not saved yet: what will be copied in when it is
            for reception in reversed([r for r in self.heardlog.snapshot() if r.get("call") == call]):  # its receptions in the last 48 hours, newest first
                log_view.insert("", "end", values=(utc(reception.get("t")), local(reception.get("t")), "RX", reception.get("kind", ""), band_of(reception.get("dial_khz") or 0) if reception.get("dial_khz") else "",  # (continued)
                                                   f"{reception['dial_khz']:.1f}" if reception.get("dial_khz") else "", level_name(reception.get("level", 0)), f"{reception['snr']:+.0f} dB" if reception.get("snr") is not None else "", "(heard before it was saved)"))  # one reception
        listing = sheet("Sessions", (("t", "UTC", 118), ("local", f"Local ({local_zone_name()})", 96), ("band", "Band", 46), ("khz", "kHz", 62), ("lvl", "Level", 44), ("heard", "We heard", 70), ("them", "They heard", 76),  # (continued)
                                     ("msgs", "Msgs in/out", 84), ("out", "Outcome", 190)), "out")  # the merged stretches of traffic, as before 0.38R2
        for entry in reversed(history):  # newest first
            listing.insert("", "end", values=(utc(entry.get("start", 0)), local(entry.get("start", 0)), entry.get("band", ""), f"{entry['dial_khz']:.1f}" if entry.get("dial_khz") else "",  # (continued)
                                              entry.get("level", ""), f"{entry['heard_db']:+.0f} dB" if entry.get("heard_db") is not None else "—", f"{entry['their_db']:+.0f} dB" if entry.get("their_db") is not None else "—",  # (continued)
                                              f"{entry.get('msgs_in', 0)} / {entry.get('msgs_out', 0)}", entry.get("outcome", "")))  # one entry
        if not history and heard is not None and self.settings.get("contact_history_mode", "all") == "all":  # a new contact that was heard: its first entry, once saved
            listing.insert("", "end", values=(utc(heard["t"]), local(heard["t"]), band_of(heard.get("dial_khz") or 0), f"{heard['dial_khz']:.1f}" if heard.get("dial_khz") else "", level_name(heard.get("level", 0)),  # (continued)
                                              f"{heard['snr']:+.0f} dB" if heard.get("snr") is not None else "—", "—", "0 / 0", f"Heard {heard.get('kind', '')}".strip()))  # the reception it was made from

        def save():  # the Save button
            new_call = boxes["call"].get().strip().upper()  # the callsign
            if not CALL_PATTERN.match(new_call):  # not a callsign
                messagebox.showerror("Kestrel", f"'{new_call}' does not look like an amateur callsign. Check it and try again.", parent=top)  # say so
                return  # leave the window open
            grid = boxes["grid"].get().strip()  # the grid locator
            grid = grid[:2].upper() + grid[2:4] + grid[4:].lower()  # written the usual way
            if grid and distance_bearing(grid, grid) is None:  # not a locator
                messagebox.showerror("Kestrel", f"'{grid}' is not a grid locator (four or six characters, such as FM05 or FM05ow).", parent=top)  # say so
                return  # leave the window open
            first = new_call not in self.contacts  # a new contact?
            fields = {name: boxes[name].get().strip() for name in ("name", "location", "radio", "power_w", "antenna")}  # the operator's fields
            fields.update(grid=grid, notes=notes.get("1.0", "end").strip())  # the grid and the notes
            if first and new_call == call and record.get("last_heard"):  # new, and filled in from what was heard
                fields.update(last_heard=record["last_heard"], band=record["last_heard"].get("band", ""))  # keep how it was heard
            self.contacts.put(new_call, **fields)  # into the book and its file
            if first and new_call == call and heard is not None and self.contacts.mode == "all":  # its first history entry: the reception it was made from
                self.contacts.add_entry(new_call, {"start": heard["t"], "end": heard["t"], "band": band_of(heard.get("dial_khz") or 0), "dial_khz": heard.get("dial_khz") or 0.0, "level": level_name(heard.get("level", 0)),  # (continued)
                                                   "heard_db": heard.get("snr"), "their_db": None, "msgs_in": 0, "msgs_out": 0, "outcome": f"Heard {heard.get('kind', '')}".strip(), "rank": 0})  # as it was heard
            if first:  # a new contact
                self.seed_contact_log(new_call)  # its receptions in the last 48 hours go into its traffic log (since 0.38R2)
            if new_call in self.heard_rows:  # on the stations list
                self.stations.set(self.heard_rows[new_call], "saved", "*")  # marked as saved
            elif first:  # not on it
                self.heard_rows[new_call] = self.stations.insert("", "end", values=("*", new_call, grid, fields.get("band", ""), "", heard_when(self.contacts.get(new_call) or {}), "saved contact"))  # add it
            self.refresh_to()  # offer it in the To box
            self.say(f"{new_call} {'added to' if first else 'saved in'} your contacts")  # confirm
            if getattr(self, "contacts_refresh", None):  # the Contacts window may be open (since 0.39)
                self.contacts_refresh()  # it shows the change
            top.destroy()  # close the window

        def delete():  # the Delete Contact button
            entries = len(self.contacts[call]["history"])  # the history it holds
            if messagebox.askyesno("Kestrel - Delete Contact", f"Delete {call}{' (' + record['name'] + ')' if record.get('name') else ''}?\n\nThe record and its {entries} history entr{'ies' if entries != 1 else 'y'} are removed from contacts.json. This cannot be undone.\n\nLogbook entries, messages and the 48-hour list of stations heard are kept.", icon="warning", parent=top):  # ask first
                self.forget_contact(call)  # gone
                top.destroy()  # close the window

        def call_it():  # the Call button
            self.to.set(boxes["call"].get().strip().upper())  # the callsign into the To box
            top.destroy()  # close the window
            self.call_to()  # call it by name

        buttons = ttk.Frame(top)  # the buttons
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=10)  # at the bottom
        if saved:  # only a saved contact can be deleted
            ttk.Button(buttons, text="Delete Contact...", command=delete).pack(side="left")  # delete it
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")  # close without saving
        ttk.Button(buttons, text="Save", command=save).pack(side="right", padx=4)  # keep the changes
        if call:  # a callsign to call
            ttk.Button(buttons, text="Call  Ctrl+Y", command=call_it).pack(side="right", padx=(0, 8))  # call it by name
        top.after(50, lambda: (top.focus_force(), (boxes["name"] if saved or call else boxes["call"]).focus_set()))  # ready to type

    # ---- store and forward ----

    def mail_file(self, call=None):  # where this callsign's mail is kept
        name = "".join(ch for ch in (call if call is not None else self.settings["call"]).upper() if ch.isalnum()) or "NOCALL"  # the callsign, safe as part of a file name
        return side_file(f"_mail_{name}.json")  # beside the settings file

    def save_mail(self):  # write the mail to its file
        try:  # a full disk must not stop the panel
            self.mailroom.save(self.mail_file())  # the whole store
            self.mail_saved = time.monotonic()  # remember when
        except OSError as problem:  # it could not be written
            self.say(f"could not save the mail: {problem}")  # say so

    def follow_mail(self):  # show what has happened to mail since the last look (called from the window's own thread)
        for kind, item in self.mailroom.take_news():  # oldest first
            text, dest = item.get("text", ""), item["dest"]  # the message (only this station's own messages carry their text) and its destination
            if kind == "carried":  # a station took a copy of one of this station's messages
                carriers = (self.mailroom.own_item(item["id"]) or {}).get("carriers", [item["carrier"]])  # every station carrying it now
                self._advance(text, "waiting (carried by " + ", ".join(carriers) + ")")  # show who has it
                self.say(f"{item['carrier']} is carrying your message for {dest}")  # tell the operator
            elif kind == "delivered":  # one of this station's messages reached its destination
                if item.get("via"):  # learned from another station's receipt
                    self._advance(text, f"delivered (receipt from {item['via']}) " + time.strftime("%H:%M"))  # say how it is known
                    self.say(f"your message for {dest} has been delivered (receipt heard from {item['via']})")  # tell the operator
            elif kind == "expired":  # one of this station's messages ran out of time
                self._advance(text, "expired, not delivered")  # mark its row
                self.say(f"your message for {dest} expired after {MAIL_LIFE_HOURS} hours without being delivered")  # tell the operator
            elif kind == "held":  # mail taken in to carry
                self.say(f"holding mail from {item['origin']} for {dest} (handed over by {item['came_from']})")  # tell the operator
            elif kind == "handed over":  # held mail reached its destination
                self.say(f"delivered the mail from {item['origin']} to {dest}")  # tell the operator
            elif kind == "passed":  # held mail passed to another carrier
                self.say(f"passed the mail for {dest} to {item['carrier']}, which hears {dest}")  # tell the operator
            elif kind == "dropped":  # held mail let go
                self.say(f"dropped the mail from {item['origin']} for {dest}: " + (f"{item['via']} reports it delivered" if item.get("via") else "it expired"))  # tell the operator
            mine = kind in ("carried", "delivered", "expired")  # news of this station's own message, whose text is the operator's own
            self.logbook.write("mail", station=self.settings["call"], text=f"{kind}: {item.get('origin', self.settings['call'])} #{item['id']} to {dest}", detail=text if mine else "")  # the logbook keeps a record (the content of other stations' mail is never written)
        if time.monotonic() - self.mail_saved > 30.0:  # every half minute
            self.save_mail()  # keep the mail on disk

    def known_calls(self):  # every callsign the panel knows, by the short code a mail notice uses
        calls = set(self.heard_rows) | set(self.contacts) | {self.settings["call"].strip().upper()}  # heard, saved, and this station
        calls |= {item["dest"] for item in self.mailroom.bag} | {item["dest"] for item in self.mailroom.own.values()}  # and the stations mail is for
        return {call_hash(call): call for call in calls if call}  # code -> callsign

    def notice_words(self, call, fields):  # a mail notice, in words, for the Stations heard list
        names = self.known_calls()  # codes that can be read back as callsigns
        me = call_hash(self.settings["call"])  # this station's own code
        held = ["YOU" if code == me else names.get(code, f"#{code:04x}") for code in fields.get("held", [])]  # whom it holds mail for
        words = "holds mail for " + ", ".join(held) if held else "holds no mail"  # the main point
        if fields.get("receipts"):  # it reports deliveries
            words += f"; {len(fields['receipts'])} delivery receipt(s)"  # how many
        heard = [names.get(code, f"#{code:04x}") for code in fields.get("heard", [])]  # whom it hears
        return words + ("; hears " + ", ".join(heard) if heard else "")  # all of it

    def mail_window(self):  # Stations > Mail held and carried
        top = self.window("mail", "Kestrel - mail held and carried")  # the window
        now = time.time()  # the wall clock, for ages and time left

        def left(expires):  # time left, in words
            hours = max(0.0, (expires - now) / 3600.0)  # hours to go
            return f"{hours:.0f} h"  # whole hours

        ttk.Label(top, text="Mail this station holds for other stations (delivered automatically when the station named beacons or calls)", font="KestrelSmallBold").pack(anchor="w", padx=8, pady=(8, 0))  # the first list's title
        held = self.table(top, (("for", "For", 90), ("id", "Message ID", 130), ("came", "Handed over by", 110), ("got", "Held since (UTC)", 130), ("left", "Time left", 80), ("passed", "Also carried by", 150)), height=5)  # the list: addressing only, never the content of other stations' mail
        for item in self.mailroom.bag:  # every message held
            held.insert("", "end", values=(item["dest"], f"{item['origin']} #{item['id']}", item["came_from"], utc(item["got"]), left(item["expires"]), ", ".join(item["carriers"]) or "-"))  # one row
        ttk.Label(top, text="Your messages for stations not yet reached, and who is carrying copies", font="KestrelSmallBold").pack(anchor="w", padx=8, pady=(8, 0))  # the second list's title
        own = self.table(top, (("for", "For", 80), ("number", "Number", 60), ("carriers", "Carried by", 160), ("left", "Time left", 70), ("text", "Message", 380)), height=4)  # the list
        for number, item in self.mailroom.own.items():  # every message still waiting
            own.insert("", "end", values=(item["dest"], number, ", ".join(item["carriers"]) or "nobody yet (it goes to the next station you work)", left(item["expires"]), item["text"]))  # one row
        recent = [f"{name.split('#')[0]} message {name.split('#')[1]} to {entry['dest']}" for name, entry in self.mailroom.receipts.items()]  # receipts this station announces
        ttk.Label(top, text=("Delivery receipts your station announces: " + "; ".join(recent)) if recent else "No delivery receipts to announce.", font="KestrelSmall", wraplength=900, justify="left").pack(anchor="w", padx=8, pady=(4, 2))  # the receipts
        ttk.Label(top, text=f"Carrying mail for others is {'on' if self.settings.get('carry_mail', True) else 'off'} (Settings > Operating). Mail lives {MAIL_LIFE_HOURS} hours and is passed on at most {HOP_LIMIT} times.", font="KestrelSmall").pack(anchor="w", padx=8, pady=(0, 8))  # the rules

    def save_outbox(self):  # remember the messages still waiting, so they survive closing the panel
        waiting = []  # the messages not yet delivered
        for row in self.to_send.get_children():  # every row of the list
            if self.to_send.set(row, "state").startswith(("waiting", "sending")):  # not finished (broadcasts are not kept)
                to = self.to_send.set(row, "to")  # who it is for
                waiting.append({"time": self.to_send.set(row, "time"), "to": "" if to == "partner" else to, "text": self.to_send.set(row, "text")})  # keep it
        write_json(side_file("_outbox.json"), waiting)  # save them beside the settings

    def _advance(self, text, state):  # change the state of the oldest unfinished row carrying a given message
        for row in self.to_send.get_children():  # oldest first
            done = self.to_send.set(row, "state")  # how far this row has got
            if self.to_send.set(row, "text") == text and not done.startswith(("delivered", "sent")):  # the same message, not finished
                changed = done != state  # is this news?
                self.to_send.set(row, "state", state)  # give it the new state
                if changed:  # something moved on
                    self.save_outbox()  # keep the saved copy of the waiting messages in step
                return  # only the oldest

    # ---- settings ----

    def settings_window(self, tab=0):  # the Settings window, open at one of its tabs
        dialog = self.window("settings", "Kestrel - Settings")  # a window of its own
        program = rigctld_program(self.settings)  # the rig control program: the one chosen before if it still exists, else one found on this computer (since 0.42R1)
        models = []  # every radio type it knows, as "number  name": filled in the background below, because the first run of rigctld on a computer can take a minute while an antivirus program checks it
        try:  # the serial port list needs the pyserial package
            from serial.tools import list_ports  # lists this computer's serial ports
            ports = sorted(port.device for port in list_ports.comports())  # their names (COM3, /dev/ttyUSB0, ...)
        except ImportError:  # pyserial is not installed
            ports = []  # the operator can still type a port name
        boxes = {}  # the controls, by setting name
        book = ttk.Notebook(dialog)  # the tabs
        book.pack(fill="both", expand=True, padx=10, pady=(10, 4))  # fill the window
        book.enable_traversal()  # Ctrl+Tab moves between the tabs

        def page(title):  # one tab
            frame = ttk.Frame(book, padding=8)  # its contents
            book.add(frame, text=title, underline=0)  # add it (Alt and its first letter opens it)
            return frame  # for its rows

        def field(frame, row, name, label, choices=None, editable=False, width=30, names=None):  # one labeled setting
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)  # the label
            value = str(self.settings[name])  # the present value, as text
            if names is not None:  # a choice shown in words
                choices, value = list(names.values()), names.get(self.settings[name], list(names.values())[0])  # the words, and the present one
            if choices is None:  # a text box
                box = ttk.Entry(frame, width=width)  # the box
                box.insert(0, value)  # its present value
            else:  # a drop-down list
                box = ttk.Combobox(frame, state="normal" if editable else "readonly", values=choices, width=width)  # the list (some may also be typed into)
                box.set(value if (editable or value in choices) and value else (choices[0] if choices else ""))  # the present choice, else the first
            box.grid(row=row, column=1, sticky="w", padx=8, pady=3)  # place it
            boxes[name] = (box, names)  # keep it, with its words if any
            return box  # for any extra wiring

        def note(frame, row, words):  # a line of explanation
            ttk.Label(frame, text=words, font="KestrelSmall", justify="left").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 6))  # in small letters

        station = page("Station")  # who and where
        field(station, 0, "call", "Callsign", width=14)  # callsign
        field(station, 1, "grid", "Grid locator", width=10)  # grid locator
        field(station, 2, "name", "Your name (for quick messages)", width=20)  # the operator's name
        field(station, 3, "location", "Location (city, state; for quick messages)", width=30)  # where the station is, in words (since 0.39R2)
        field(station, 4, "rig_text", "Rig description (for quick messages and the log)", width=30)  # the radio, as the operator wants it described
        antenna_box = field(station, 5, "antenna", "Antenna", list(antennas.TYPES), width=30)  # this station's antenna, from the fixed list (Homebuilt for a homemade one; since 0.39R2)
        if not self.settings["antenna"]:  # none chosen yet
            antenna_box.set("")  # nothing chosen
        field(station, 6, "max_power_w", "Radio's full power, watts", width=8)  # to turn the radio's power setting into watts
        field(station, 8, "hold_power_w", "Hold output power at, watts (blank = off)", width=8)  # the drive is adjusted between transmissions to keep it (since 0.40R1)
        note(station, 9, "Hold output power: after each transmission Kestrel compares the power the radio measured with this figure and nudges the\ntransmit level (the slider) for the next one, by at most 2 dB a step, and never upward while ALC is high. Needs rig control.")  # what it does
        note(station, 7, "The power shown and logged is read from the radio through rig control, when the radio and Hamlib allow it.\nLocation and antenna go into quick messages as {location} and {antenna}.")  # where the power comes from, and where location and antenna are used
        radio = page("Radio")  # the radio and how the computer reaches it
        rig_box = field(radio, 0, "rig_model", "Rig type", [NO_RIG] + models, editable=True, width=44)  # the radio type, from the rig control program's own list
        if not self.settings["rig_model"]:  # none chosen yet
            rig_box.set(NO_RIG)  # start at "no rig control"
        rig_box.bind("<KeyRelease>", lambda event: rig_box.configure(values=[NO_RIG] + [model for model in models if rig_box.get().lower() in model.lower()]))  # typing part of a name narrows the list
        field(radio, 1, "cat_port", "CAT serial port", ports, editable=True, width=14)  # the serial port that carries CAT control
        field(radio, 2, "cat_baud", "CAT speed (baud)", ["4800", "9600", "19200", "38400", "57600", "115200"], width=14)  # its speed
        field(radio, 3, "cat_handshake", "CAT handshake", ["none", "hardware"], width=14)  # RTS/CTS handshaking, for radios that want it
        field(radio, 4, "ptt", "Key the transmitter (PTT) by", names=PTT_NAMES, width=30)  # how the transmitter is keyed
        field(radio, 5, "port", "PTT serial port (for RTS or DTR)", ports, editable=True, width=14)  # the port whose RTS or DTR line keys the radio
        field(radio, 9, "radio_mode", "Radio mode", names=RADIO_MODE_NAMES, width=44)  # USB-D or plain USB
        note(radio, 10, "Kestrel uses upper sideband on every band, 80 m and 40 m included. On plain USB turn the radio's speech processor,\ncompression and transmit equaliser off, and feed the audio in where the radio takes it for USB (often the microphone input).")  # what plain USB needs
        path_box = field(radio, 6, "rigctld", "rigctld program", width=52)  # the rig control program's file
        if program and program != self.settings["rigctld"]:  # none chosen, or the one chosen is gone, but one was found (since 0.42R1)
            path_box.insert(0, program)  # offer it
        list_note = ttk.Label(radio, text="Loading the rig type list... (the first time on a computer this can take a minute)", wraplength=560, justify="left")  # how many radios, or why none; filled in when the list arrives
        list_note.grid(row=8, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))  # under the settings

        def show_list(used, listed, reason):  # the rig type list has arrived (called in the window's own thread)
            if not dialog.winfo_exists():  # the Settings window was closed meanwhile
                return  # nothing to fill
            models[:] = [f"{number}  {name}" for number, name in listed]  # the list, in place (the narrowing-as-you-type rule reads the same list)
            rig_box.configure(values=[NO_RIG] + models)  # into the drop-down
            if used and path_box.get().strip() != used:  # the program that answered is not the one shown (the saved one was gone, and the installed one was used)
                path_box.delete(0, "end")  # clear the box
                path_box.insert(0, used)  # show the one in use
            list_note.configure(text=f"The rig type list is empty: {reason}." if reason else f"{len(models)} radio types listed. Choose yours from the Rig type list, or type part of its name to narrow the list.", foreground=self.colors["warn_fg"] if reason else "")  # say how it went (a problem in the theme's warning color)
            if reason:  # no list
                self.say(f"Settings: the rig type list is empty: {reason}")  # keep the reason in the log too

        def load(saved):  # fetch the list without freezing the window (a thread of its own)
            used, listed, reason = models_for(saved)  # ask the saved program, else the one found on this computer
            self.root.after(0, lambda: show_list(used, listed, reason))  # hand the answer to the window's own thread

        def reload():  # fill the rig type list again from the program in the box
            list_note.configure(text="Loading the rig type list...", foreground="")  # say it is being fetched
            threading.Thread(target=load, args=(path_box.get().strip(),), daemon=True).start()  # in the background

        reload()  # fetch the list now

        ttk.Button(radio, text="Reload rig list", command=reload).grid(row=7, column=2, padx=(0, 8), pady=(2, 0))  # try again, after fixing the path or the antivirus

        def browse():  # the Browse button
            chosen = filedialog.askopenfilename(parent=dialog, title="Find the rigctld program")  # ask for the file
            if chosen:  # one was picked
                path_box.delete(0, "end")  # clear the box
                path_box.insert(0, chosen)  # show the choice
                reload()  # and fill the rig type list from it

        ttk.Button(radio, text="Browse...", command=browse).grid(row=6, column=2, padx=(0, 8))  # find the program by hand
        field(radio, 7, "rig", "or one already running at (host:port)", width=22)  # an outside rigctld, used only when no rig type is chosen
        audio = page("Audio")  # the sound devices and level
        field(audio, 0, "audio_in", "Audio from radio", device_choices("input"), width=52)  # the receive audio device
        field(audio, 1, "audio_out", "Audio to radio", device_choices("output"), width=52)  # the transmit audio device
        note(audio, 2, "Set the levels with the two sliders beside the meters on the main window (Ctrl+J).\nThe receive slider changes Windows' recording level for the device; the transmit slider sets the drive to the radio.")  # where the levels are
        operating = page("Operating")  # what the panel does
        field(operating, 0, "start_mode", "When the panel opens", names=START_NAMES, width=30)  # listen, monitor or nothing
        field(operating, 6, "auto_answer", "When Listen hears a beacon or a call", names=ANSWER_NAMES, width=58)  # just listen, or answer automatically
        note(operating, 7, "Just listen: nothing is sent unless you start it. A station beaconing, or calling you by name, is highlighted in the Stations\nheard list with any messages either way; select it and press Respond (Ctrl+Y). Replies to your own beacon or call are accepted.")  # how it works
        field(operating, 1, "beacon_every_min", f"Repeating beacon: minutes between beacons ({BEACON_MIN} to {BEACON_MAX})", width=6)  # the interval
        field(operating, 2, "beacon_autostop_min", f"Stop the repeating beacon after this many minutes with\nno keyboard or mouse use ({AUTOSTOP_MIN} to {AUTOSTOP_MAX}; 0 = never)", width=6)  # the automatic stop
        field(operating, 4, "beacon_type", "Beacon type", names=BEACON_TYPE_NAMES, width=62)  # short or long
        field(operating, 5, "listen_first", "Listen before transmitting", names=LISTEN_FIRST_NAMES, width=62)  # hold back while the frequency is in use
        field(operating, 8, "carry_mail", "Carry mail for others", names=CARRY_NAMES, width=62)  # store and forward
        field(operating, 10, "keep_alive", "Keep-Alive", names=KEEPALIVE_NAMES, width=62)  # three more idle minutes on a working channel (since 0.41)
        note(operating, 11, "A contact with no messages either way for 3 minutes ends; both operators are warned 10 seconds before, with Keep going\nand Disconnect. Keep-Alive adds 3 minutes on a working channel only (one short KEEP-ALIVE message), never on the calling frequency.")  # what it does
        field(operating, 12, "activity_window", "Activity window", names=ACTIVITY_NAMES, width=62)  # the running log's own window (since 0.41)
        note(operating, 9, "Mail for a station that is not on the air is handed to the stations you work, which deliver it when that station\nbeacons or calls. With this on, your station does the same for others. See Stations > Mail held and carried.")  # what it means
        note(operating, 3, "The repeating beacon starts only when you press its button (F5). Each round is one beacon and its reply window;\nit pauses during a contact and the interval starts again when the contact ends. Press the button again to stop.")  # how it works
        logging = page("Logging")  # the logbook
        field(logging, 0, "log_level", "Level of detail", names=LOG_NAMES, width=56)  # basic, advanced or verbose
        note(logging, 1, f"Logs are kept in {LOG_FOLDER}:\none CSV file per UTC day (opens in a spreadsheet), and an ADIF file of completed contacts for logging programs.")  # where
        ttk.Button(logging, text="Open the log folder", command=self.open_logs).grid(row=2, column=0, sticky="w", padx=8)  # look at them
        field(logging, 3, "record_rx", "Record received audio", names=RECORD_NAMES, width=56)  # save what the receiver hears
        note(logging, 4, f"Recordings go in {recordings_dir(data_dir())}, one WAV file per hour (about 86 MB an hour, kept 7 days).\nTurn this on for on-air tests: File > Decode a recording plays a file back through the receiver and lists every\nframe and every signal that was heard but could not be read. It takes effect the next time Listen or Monitor starts.")  # what it is for
        field(logging, 5, "signal_log", "Signal log (for analysis)", names=SIGNAL_NAMES, width=56)  # the detailed signal log
        note(logging, 6, f"The signal log goes in {os.path.join(LOG_FOLDER, 'signal')}, one file per UTC day: every signal the receiver\nlooked at, every frame (SNR, fading, offset, which header copy was read), every transmission and the radio's meters.\ntools/signal_report.py summarizes it. Off uses no disk space. It takes effect the next time Listen or Monitor starts.")  # what it is and what it costs
        field(logging, 7, "psk_spot", "Report stations heard to PSK Reporter", names=PSK_NAMES, width=56)  # spotting (since 0.35)
        note(logging, 8, "Each Kestrel station decoded (callsign, locator, frequency, SNR) goes to pskreporter.info as mode KESTREL, at most once\nin five minutes per station, so operators can see where their signals reach. Needs your callsign and grid. It takes effect at once.")  # what it does
        field(logging, 9, "prop_check", "Check the propagation predictions", names=PROPCHECK_NAMES, width=56)  # the prediction check (since 0.35)
        note(logging, 10, f"For each station heard with a known grid, once an hour per band, the P.533 prediction for its path is written\nbeside the SNR heard, in {propcheck.record_file()}. The Propagation window shows how close they have been.")  # what it does
        quick = page("Quick messages")  # the quick messages
        quick_items = [dict(item) for item in self.settings["quick"]]  # a working copy, kept only if Save is pressed
        quick.columnconfigure(0, weight=1)  # the list takes the width
        listing = ttk.Treeview(quick, columns=("key", "name", "text"), show="headings", height=10, selectmode="browse")  # the quick messages, one row each
        for column, heading, width in (("key", "Key", 50), ("name", "Name", 170), ("text", "Message", 420)):  # its columns
            listing.heading(column, text=heading)  # the heading
            listing.column(column, width=width, anchor="w", stretch=column == "text")  # the width; the message column takes any spare room
        listing.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=8, pady=(4, 2))  # place it
        count = ttk.Label(quick, text="")  # how many there are, out of the most allowed
        count.grid(row=2, column=0, sticky="w", padx=8)  # under the buttons

        def show(select=None):  # (re)fill the list from the working copy
            listing.delete(*listing.get_children())  # empty it
            for number, item in enumerate(quick_items, start=1):  # each one
                listing.insert("", "end", iid=str(number - 1), values=(f"Alt+{number % 10}", item["name"], item["text"]))  # its key, name and template
            if select is not None and quick_items:  # a row to select
                row = str(max(0, min(select, len(quick_items) - 1)))  # within the list
                listing.selection_set(row)  # select it
                listing.focus(row)  # and give it the keyboard's attention
                listing.see(row)  # in view
            count.configure(text=f"{len(quick_items)} of {QUICK_MOST} quick messages")  # how many
            add_button.state(["disabled"] if len(quick_items) >= QUICK_MOST else ["!disabled"])  # no more than the most allowed

        def chosen():  # the position of the selected quick message, or None
            rows = listing.selection()  # the selected row
            return int(rows[0]) if rows else None  # its position in the working copy

        def editor(index=None):  # add (index None) or edit one quick message
            item = quick_items[index] if index is not None else {"name": "", "text": ""}  # what it is now
            top = self.window("quick_edit", "Kestrel - " + ("edit" if index is not None else "add") + " a quick message")  # the window
            top.transient(dialog)  # it belongs to the Settings window
            ttk.Label(top, text="Name").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))  # label of the name
            name_box = ttk.Entry(top, width=40)  # the name the operator gives it
            name_box.grid(row=0, column=1, sticky="w", padx=8, pady=(8, 2))  # place it
            name_box.insert(0, item["name"])  # as it is now
            ttk.Label(top, text="Message").grid(row=1, column=0, sticky="w", padx=8, pady=2)  # label of the template
            text_box = ttk.Entry(top, width=80)  # the message, with fill-ins
            text_box.grid(row=1, column=1, sticky="ew", padx=8, pady=2)  # place it
            text_box.insert(0, item["text"])  # as it is now
            ttk.Label(top, text="These fill in when used: {call} {name} {grid} {rig} {power} {to} {telemetry} {location} {antenna}", font="KestrelSmall").grid(row=2, column=1, sticky="w", padx=8)  # the fill-ins
            preview = ttk.Label(top, text="", font="KestrelSmall", wraplength=560, justify="left")  # what it would say right now
            preview.grid(row=3, column=1, sticky="w", padx=8, pady=(2, 4))  # place it
            text_box.bind("<KeyRelease>", lambda event: preview.configure(text="Now it would read: " + self.expand(text_box.get())))  # follow the typing
            preview.configure(text="Now it would read: " + self.expand(item["text"]) if item["text"] else "")  # the starting preview
            (name_box if index is None else text_box).focus_set()  # ready to type

            def keep():  # the operator accepts it
                name, text = " ".join(name_box.get().split()), text_box.get().strip()  # the name (spacing tidied) and the template
                others = {other["name"].lower() for number, other in enumerate(quick_items) if number != index}  # the names of the rest
                problem = ("Give the quick message a name." if not name else f"The name can be at most {QUICK_NAME_MOST} characters." if len(name) > QUICK_NAME_MOST  # (continued)
                           else "Another quick message already has that name." if name.lower() in others else "The message is empty." if not text  # (continued)
                           else f"The message can be at most {telemetry.MAX_CHARS} characters." if len(text) > telemetry.MAX_CHARS else "")  # what, if anything, is wrong
                if problem:  # something is wrong
                    messagebox.showinfo("Kestrel", problem, parent=top)  # say what
                    return  # stay in the window
                if index is None:  # a new one
                    quick_items.append({"name": name, "text": text})  # at the end
                else:  # a change
                    quick_items[index] = {"name": name, "text": text}  # in its place
                top.destroy()  # close the window
                show(len(quick_items) - 1 if index is None else index)  # show the list, with it selected

            buttons = ttk.Frame(top)  # OK and Cancel
            buttons.grid(row=4, column=1, sticky="e", padx=8, pady=8)  # under the boxes
            ttk.Button(buttons, text="OK", command=keep).pack(side="left", padx=(0, 4))  # accept
            ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="left")  # back out
            top.bind("<Return>", lambda event: keep())  # Enter accepts

        def edit():  # Edit...
            index = chosen()  # the selected one
            if index is None:  # none selected
                messagebox.showinfo("Kestrel", "Select a quick message in the list first.", parent=dialog)  # say so
                return  # nothing to edit
            editor(index)  # open it

        def delete():  # Delete
            index = chosen()  # the selected one
            if index is None:  # none selected
                messagebox.showinfo("Kestrel", "Select a quick message in the list first.", parent=dialog)  # say so
                return  # nothing to delete
            if messagebox.askyesno("Kestrel", f"Delete the quick message \"{quick_items[index]['name']}\"?\n\nNothing changes until you press Save.", parent=dialog):  # make sure
                del quick_items[index]  # take it out
                show(index)  # the list again, with the next one selected

        def move(step):  # Move up (-1) or Move down (+1)
            index = chosen()  # the selected one
            if index is None or not 0 <= index + step < len(quick_items):  # none selected, or already at that end
                return  # nothing to do
            quick_items[index], quick_items[index + step] = quick_items[index + step], quick_items[index]  # swap it with its neighbor
            show(index + step)  # the list again, with it still selected

        controls = ttk.Frame(quick)  # the buttons under the list
        controls.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4))  # place them
        add_button = ttk.Button(controls, text="Add...", command=lambda: editor(None))  # a new quick message
        add_button.pack(side="left", padx=(0, 4))  # place it
        ttk.Button(controls, text="Edit...", command=edit).pack(side="left", padx=(0, 4))  # change the selected one
        ttk.Button(controls, text="Delete", command=delete).pack(side="left", padx=(0, 12))  # remove the selected one
        ttk.Button(controls, text="Move up", command=lambda: move(-1)).pack(side="left", padx=(0, 4))  # earlier in the list (and a lower Alt key)
        ttk.Button(controls, text="Move down", command=lambda: move(1)).pack(side="left")  # later in the list
        listing.bind("<Double-1>", lambda event: edit())  # a double-click edits
        listing.bind("<Delete>", lambda event: delete())  # the Delete key deletes
        show(0)  # fill the list
        note(quick, 3, f"Up to {QUICK_MOST} quick messages, each with a name you choose. Alt+1 to Alt+9 and Alt+0 put them in the Message box, in this order; they are also on the Quick button\nand under Messages > Quick messages. Changes are kept when you press Save.\n" "These fill in when used: {call} {name} {grid} {rig} {power} {to} {telemetry}\nTelemetry lists the stations heard in the last 30 minutes, strongest first, with their signal and fastest level.")  # the names that fill in
        looks = page("Appearance")  # the look
        field(looks, 0, "theme", "Theme", names=THEME_NAMES, width=30)  # system, light or dark
        from tkinter import font as tkfont  # for the list of fonts on this computer
        field(looks, 1, "font_family", "Font", sorted(set(tkfont.families(self.root))), editable=True, width=30)  # the lettering's family
        field(looks, 2, "font_size", f"Font size ({FONT_MIN} to {FONT_MAX})", [str(size) for size in range(FONT_MIN, FONT_MAX + 1)], editable=True, width=6)  # and its size
        note(looks, 3, "The font applies to the whole window as soon as you save. A smaller size fits more on a small screen.\nDrag the dividers between the panels to resize them; View > Reset the panel sizes puts them back.")  # what these do

        contacts_tab = page("Contacts")  # the contact book (since 0.31R3)
        field(contacts_tab, 0, "contact_history", f"History kept for each contact ({HISTORY_MIN} to {HISTORY_MAX})", width=6)  # how many entries each contact keeps
        field(contacts_tab, 1, "contact_history_mode", "Record in history", names=MODE_NAMES, width=24)  # all traffic, or completed contacts only
        note(contacts_tab, 2, "All traffic: every time a saved contact is heard, called or worked (beacons, calls with no answer, broadcasts, contacts).\nCompleted contacts: only contacts that were made and ended. When a history is full, the oldest entry is dropped.\nLowering the number trims longer histories when you click Save (you are asked first). The logbook is not affected.")  # what they mean
        note(contacts_tab, 3, f"Contacts are kept in {CONTACTS_FILE}.")  # where
        ttk.Button(contacts_tab, text="Open the folder", command=lambda: self.open_path(os.path.dirname(CONTACTS_FILE))).grid(row=4, column=0, sticky="w", padx=8)  # look at it
        updates_tab = page("Updates")  # checking for a newer Kestrel (since 0.42)
        field(updates_tab, 0, "update_check", "Check for updates", names=UPDATE_CHECK_NAMES, width=58)  # how often
        field(updates_tab, 1, "update_notify", "Tell me about", names=UPDATE_NOTIFY_NAMES, width=58)  # every release, or signal changes only
        field(updates_tab, 2, "update_test", "Test releases", names=UPDATE_TEST_NAMES, width=58)  # pre-releases too
        field(updates_tab, 3, "update_install", "When there is one", names=UPDATE_INSTALL_NAMES, width=58)  # offer Install now, or only say so
        checked = ttk.Frame(updates_tab)  # the Check now row
        checked.grid(row=4, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))  # place it
        ttk.Button(checked, text="Check now", command=lambda: self.begin_update_check(manual=True)).pack(side="left")  # ask GitHub now, with the saved choices
        self.update_label = ttk.Label(checked, text=self.update_status_text(), font="KestrelSmall")  # when the last check was, and what it found
        self.update_label.pack(side="left", padx=(8, 0))  # beside the button
        note(updates_tab, 5, "Kestrel asks GitHub, where its releases are published, whether there is a newer version; nothing is sent about you or your station.\n"
             "Install now downloads the setup program, checks it against the SHA-256 published with it, closes Kestrel (your waiting messages are kept),\n"
             "installs it and starts Kestrel again. It waits until no contact is under way and nothing is being sent.\n"
             "A release that changes the signal is always shown: stations on different signal versions mostly cannot hear each other.\n"
             "Check now uses the saved choices; press Save first if you changed them.")  # what this does

        def save():  # the Save button
            new = dict(self.settings)  # a copy to fill in
            for name, (box, names) in boxes.items():  # every setting
                value = box.get() if name in ("audio_in", "audio_out") else box.get().strip()  # its value (device names are kept exactly, spaces and all)
                if names is not None:  # shown in words
                    value = next((key for key, words in names.items() if words == value), self.settings[name])  # back to its short form
                new[name] = value  # keep it
            if new["rig_model"] == NO_RIG:  # no rig control wanted
                new["rig_model"] = ""  # stored as blank
            if new["rig_model"] and new["rig_model"] not in models:  # something typed that is not an entry of the list (the entries are "number  name")
                close = [model for model in models if new["rig_model"].lower() in model.lower()]  # the entries it could mean
                if len(close) == 1:  # only one: that must be it
                    new["rig_model"] = close[0]  # take it
                elif not (new["rig_model"].split()[0].isdigit() and not models):  # anything else is refused (a bare Hamlib number is let through only when there is no list to choose from)
                    messagebox.showerror("Kestrel", (f"'{new['rig_model']}' matches {len(close)} radio types. Pick one from the Rig type list." if close else f"'{new['rig_model']}' is not in the Rig type list. Pick your radio from the list (type part of its name to narrow it), or choose '{NO_RIG}'."), parent=dialog)  # say what to do
                    book.select(1)  # show the Radio tab
                    return  # leave the window open
            try:  # the numbers must be numbers, within their limits
                every, stop_after, full = int(new["beacon_every_min"]), int(new["beacon_autostop_min"]), float(new["max_power_w"] or 100)  # read them
            except ValueError:  # not numbers
                messagebox.showerror("Kestrel", "The beacon minutes and the full power must be numbers.", parent=dialog)  # say so
                return  # leave the window open
            if not BEACON_MIN <= every <= BEACON_MAX:  # outside the allowed range
                messagebox.showerror("Kestrel", f"The repeating beacon can be set to no less than {BEACON_MIN} and no more than {BEACON_MAX} minutes.", parent=dialog)  # say so
                book.select(3)  # show the tab
                return  # leave the window open
            if stop_after and not AUTOSTOP_MIN <= stop_after <= AUTOSTOP_MAX:  # outside its range (0 means never)
                messagebox.showerror("Kestrel", f"The automatic stop must be between {AUTOSTOP_MIN} and {AUTOSTOP_MAX} minutes, or 0 for never.", parent=dialog)  # say so
                book.select(3)  # show the tab
                return  # leave the window open
            new["beacon_every_min"], new["beacon_autostop_min"], new["max_power_w"] = every, stop_after, f"{full:g}"  # stored as numbers
            new["call"], new["grid"] = new["call"].upper(), new["grid"][:2].upper() + new["grid"][2:4] + new["grid"][4:].lower()  # callsign in capitals; locator written the usual way
            if new["call"] and not CALL_PATTERN.match(new["call"]):  # it does not look like a callsign
                messagebox.showerror("Kestrel", f"'{new['call']}' does not look like an amateur callsign. Check it and try again.", parent=dialog)  # say so
                book.select(0)  # show the Station tab
                return  # leave the window open
            if new["call"] and new["call"] != self.settings["call"]:  # the callsign has changed: every transmission will identify with it
                if not messagebox.askyesno("Kestrel - check your callsign", f"Kestrel will identify every transmission as\n\n        {new['call']}\n\nIs that your callsign, exactly?", parent=dialog):  # make the operator look at it
                    book.select(0)  # show the Station tab
                    return  # leave the window open for a correction
            if not (str(new["contact_history"]).isdigit() and HISTORY_MIN <= int(new["contact_history"]) <= HISTORY_MAX):  # not a history length on offer
                messagebox.showerror("Kestrel", f"The history kept for each contact must be a whole number from {HISTORY_MIN} to {HISTORY_MAX}.", parent=dialog)  # say so
                book.select(7)  # show the Contacts tab
                return  # leave the window open
            new["contact_history"] = int(new["contact_history"])  # stored as a number
            dropped = self.contacts.trimmed_by(new["contact_history"])  # history entries a smaller number would drop
            if dropped and not messagebox.askyesno("Kestrel - Contact history", f"Keeping {new['contact_history']} entries for each contact drops the oldest {dropped} history entr{'ies' if dropped != 1 else 'y'} now. Go ahead?", icon="warning", parent=dialog):  # ask first
                book.select(7)  # show the Contacts tab
                return  # leave the window open
            if not (new["font_size"].isdigit() and FONT_MIN <= int(new["font_size"]) <= FONT_MAX):  # not a size on offer
                messagebox.showerror("Kestrel", f"The font size must be a whole number from {FONT_MIN} to {FONT_MAX}.", parent=dialog)  # say so
                book.select(6)  # show the Appearance tab
                return  # leave the window open
            new["quick"] = [dict(item) for item in quick_items]  # the quick messages as edited
            restart = any(new[key] != self.settings[key] for key in ("call", "grid", "audio_in", "audio_out", "rig_model", "cat_port", "cat_baud", "cat_handshake", "radio_mode", "ptt", "port", "rigctld", "rig", "carry_mail"))  # does the running station need to start again?
            if new["call"] != self.settings["call"]:  # a different callsign has different mail
                self.save_mail()  # keep the old callsign's
                self.mailroom = Mailroom.load(self.mail_file(new["call"]), new["call"])  # and use the new one's
            self.settings = new  # take the new settings
            self.save_settings()  # write them to the settings file
            self.apply_fonts()  # the lettering follows the choice at once
            self.apply_activity_setting()  # the Activity window turns on (minimized) or off at once (since 0.42R2)
            self.logbook.level = new["log_level"]  # the logbook's level of detail
            self.contacts.set_policy(new["contact_history"], new["contact_history_mode"])  # the contact history rules (a smaller length trims now)
            self.beacon_type_var.set(self.settings.get("beacon_type", "short"))  # the Beacon type menu follows the setting
            self.beacon_button.configure(text=self.beacon_words())  # and the button's label
            if self.station is not None:  # a station is listening now
                self.station.answer_beacons = self.station.answer_calls = bool(new["auto_answer"])  # the change applies at once
            log = self.signal_log  # the signal log of the run under way, if any (read once: the run may end meanwhile)
            if log is not None and log.mode != new.get("signal_log", "off"):  # turned on, off or to clips during a run
                was = log.mode  # what it was
                log.mode = new.get("signal_log", "off")  # it applies at once (it used to wait for the next start of Listen)
                if log.on:  # it is on now
                    log.note(f"signal log changed from {was} to {log.mode} during the run", settings=self.settings_summary())  # the first line, with the settings in use
                    self.say(f"signal log on ({log.mode}): {log.path()}")  # say where
                else:  # turned off
                    self.say("signal log off")  # say so
            if new["theme"] != self.theme_var.get():  # a different look
                self.set_theme(new["theme"])  # apply it
            self.show_me()  # show the callsign and grid at the top
            self.refresh_quick()  # the quick messages may have changed
            self.find_rx_level()  # the receive device may have changed
            self.logbook.write("settings", station=new["call"], text="settings saved", detail=self.settings_summary())  # the verbose log keeps a record
            dialog.destroy()  # close the window
            if self.awaiting_setup and not self.missing_setup(new["start_mode"] if new["start_mode"] != "off" else "monitor"):  # the panel was waiting for these
                self.awaiting_setup = False  # no longer waiting
                if new["start_mode"] != "off":  # it should be running
                    self.set_mode(new["start_mode"])  # start it
            elif restart and self.mode != "off":  # a running station needs the new settings
                if self.in_contact():  # but not in the middle of a contact
                    self.say("the new radio and audio settings take effect when the station next starts (F2)")  # say when
                else:  # free to restart
                    self.say("starting again with the new settings")  # say so
                    mode = self.mode  # the mode to come back to
                    self.mode = "restart"  # so set_mode does not think nothing has changed
                    self.set_mode(mode)  # restart

        buttons = ttk.Frame(dialog)  # the row of buttons
        buttons.pack(fill="x", padx=10, pady=(4, 10))  # at the bottom
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")  # drop the changes
        ttk.Button(buttons, text="Save", command=save).pack(side="right", padx=4)  # keep the changes
        dialog.bind("<Return>", lambda event: save())  # Enter saves
        book.select(min(max(tab, 0), len(book.tabs()) - 1))  # open at the tab asked for (any of them; Updates since 0.42)
        dialog.after(50, lambda: dialog.focus_force())  # the window has the keyboard

    def settings_summary(self):  # the settings in use, for the verbose log
        keys = ("call", "grid", "rig_model", "cat_port", "ptt", "audio_in", "audio_out", "gain", "keep_open", "working", "beacon_every_min", "beacon_type", "listen_first", "beacon_autostop_min", "auto_answer", "log_level", "record_rx", "signal_log")  # the ones that bear on a transmission
        return "; ".join(f"{key}={self.settings[key]}" for key in keys)  # as one line

    def rig_address(self, settings):  # where rig control can be reached for these settings (may be called from any thread)
        """Return a rigctld address, starting rigctld for the chosen radio if needed; "" when the radio is tuned by hand."""
        if settings["rig_model"] and settings["cat_port"]:  # a radio type and its serial port are chosen
            program = rigctld_program(settings)  # the rig control program (the saved one if it still exists, since 0.42R1)
            if not program:  # there is none
                raise RuntimeError("the rig control program (rigctld) was not found; choose it under Settings > Radio")  # say what to do
            if not settings["rig_model"].split()[0].isdigit():  # the rig type is not an entry of the list (entries begin with Hamlib's number)
                raise RuntimeError(f"the rig type in Settings ('{settings['rig_model']}') is not one from the list: open Settings > Radio and pick your radio")  # say what to do, in plain words
            try:  # start it if it is not already running
                return self.rigs.ensure(program, settings["rig_model"].split()[0], settings["cat_port"], settings["cat_baud"] or 38400, settings["cat_handshake"])  # its address
            finally:  # whether or not it started
                while self.rigs.news:  # a leftover rigctld from a crash was ended (since 0.38R2)
                    self.say(self.rigs.news.pop(0))  # say so in the Activity log
        return settings["rig"]  # an outside rigctld, or nothing

    def save_settings(self):  # remember the current settings
        self.settings["frequency"] = self.frequency.current()  # the frequency now selected
        self.settings["keep_open"] = bool(self.keep_open.get())  # whether contacts are kept open
        self.settings["working"] = self.working.current()  # the working-frequency choice
        write_json(SETTINGS_FILE, self.settings)  # save, readably

    # ---- frequencies ----

    def refresh_frequencies(self, select=0):  # (re)fill the frequency drop-down list
        self.entries = all_frequencies()  # the presets and the operator's own
        self.frequency["values"] = [short_frequency(entry) for entry in self.entries]  # one short line each: band, dial and what it is (the full line shows as the list's hover help; since 0.41)
        self.frequency.current(min(max(select, 0), len(self.entries) - 1))  # select the wanted line
        self.update_frequency_tip()  # its details in the hover help
        self.base_khz = self.selected()["dial_khz"]  # the calling frequency, for the station thread and the scope
        self.refresh_working(self.settings["working"])  # and offer the working frequencies that go with it
        self.refresh_send_bands()  # messages for the partner go out on this band

    def refresh_working(self, select=0):  # (re)fill the working-frequency choice for the selected calling frequency
        entry = self.selected()  # the calling frequency
        choices = ["stay on the calling frequency"]  # the first choice: no move
        for name, offset in channel_names(entry):  # each channel that goes with it
            choices.append(f"move to {name}: {entry['dial_khz'] + offset / 1000.0:.1f} kHz  ({offset / 1000.0:+.1f} kHz), return at the end")  # where the pair would go
        self.working["values"] = choices  # show them
        self.working.current(select if 0 <= select < len(choices) else 0)  # the remembered choice, if it still exists

    def selected(self):  # the frequency entry now selected
        return self.entries[max(0, self.frequency.current())]  # by its position in the list

    def step_frequency(self, step):  # Ctrl+Up or Ctrl+Down: the previous or next frequency in the list
        index = self.frequency.current() + step  # the neighbor
        if 0 <= index < len(self.entries):  # inside the list
            self.frequency.current(index)  # select it
            self.tune()  # and go there

    def add_frequency(self):  # ask for a frequency of the operator's own
        dialog = self.window("add", "Add a frequency")  # a small window
        boxes = []  # the four text boxes
        for row, (label, value) in enumerate((("Band (for example 17 m)", ""), ("Dial frequency in kHz (USB)", ""), ("Radio mode (USB-D or USB)", "USB-D"), ("Note", ""))):  # the four things asked for
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)  # the label
            box = ttk.Entry(dialog, width=28)  # the box
            box.insert(0, value)  # its starting text
            box.grid(row=row, column=1, padx=6, pady=3)  # place it
            boxes.append(box)  # keep it
        boxes[0].focus_set()  # start in the first box

        def save():  # the Save button
            try:  # the entry may be refused
                add_user_frequency(boxes[0].get(), boxes[1].get(), boxes[2].get(), boxes[3].get())  # save it to local/frequencies.json
            except ValueError as problem:  # something was missing or not a number
                messagebox.showerror("Kestrel", str(problem), parent=dialog)  # say what
                return  # leave the dialog open
            dialog.destroy()  # close the dialog
            self.refresh_frequencies(len(all_frequencies()) - 1)  # show the list with the new entry selected

        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=1, sticky="e", padx=6, pady=6)  # the Save button
        dialog.bind("<Return>", lambda event: save())  # Enter saves

    def remove_frequency(self):  # remove the selected frequency, if it is one of the operator's own
        entry = self.selected()  # what is selected
        if entry["builtin"]:  # a preset
            messagebox.showinfo("Kestrel", "Kestrel's own calling frequencies cannot be removed.", parent=self.root)  # say so
            return  # nothing to do
        remove_user_frequency(self.frequency.current() - (len(self.entries) - len(user_frequencies())))  # its position among the operator's own
        self.refresh_frequencies(0)  # show the list again

    def tune(self):  # a frequency was chosen from the list: tune the radio to it
        if self.in_contact():  # moving mid-contact would drop the partner
            messagebox.showinfo("Kestrel", "A contact is in progress. End it (F7) before changing frequency.", parent=self.root)  # say so
            self.frequency.current(self.settings["frequency"])  # put the list back
            return  # leave the radio where it is
        self.refresh_working(0)  # a new calling frequency has its own working frequencies; start at "stay"
        self.base_khz = self.selected()["dial_khz"]  # the new calling frequency
        self.refresh_send_bands()  # messages for the partner now go out on this band
        self.save_settings()  # remember the choice
        if self.worker is not None and self.worker.is_alive():  # a station or the monitor is running: start it again on the new frequency (it tunes the radio as it starts)
            mode = self.mode  # the mode to come back to
            self.mode = "restart"  # so set_mode does not think nothing has changed
            self.set_mode(mode)  # restart
            return  # done
        threading.Thread(target=self._tune_job, args=(dict(self.settings), self.selected()), daemon=True).start()  # tune in the background, so the window does not freeze while the radio answers

    def _tune_job(self, settings, entry):  # the background part of tuning
        try:  # the radio may not answer
            with self.rig_lock:  # one user of rig control at a time
                address = self.rig_address(settings)  # start or find rig control
                if not address:  # the radio is tuned by hand
                    self.say(f"set the radio by hand to {entry['dial_khz']:.1f} kHz {'USB' if settings.get('radio_mode') == 'USB' else 'USB-D (or USB if the radio has no data mode)'}  ({entry['band']})")  # tell the operator where to go
                    return  # nothing to send
                rig = RigCtl(address)  # connect to rigctld
                self._tune(rig, entry)  # set mode and frequency
                rig.close()  # hang up
        except (OSError, RuntimeError, ValueError) as problem:  # no connection, or the radio refused
            self.say(f"could not tune the radio: {problem}")  # say what went wrong (rig control's own message says what to check)

    def _tune(self, rig, entry):  # set the radio to a frequency entry
        prefer = "USB" if entry.get("mode") == "USB" else self.settings.get("radio_mode", "auto")  # a frequency the operator saved as plain USB stays plain USB; otherwise the setting decides
        mode = rig.set_data_mode(prefer)  # the mode first: upper sideband, the radio's data mode if it has one
        rig.set_frequency(entry["dial_khz"] * 1000.0)  # then the frequency
        self.say(f"radio tuned to {rig.frequency() / 1000.0:.1f} kHz {mode_name(mode)}  ({entry['band']})" + ("; this radio has no USB-D mode, so plain USB is used" if mode == "USB" and prefer == "auto" else ""))  # confirm what the radio reports

    # ---- running ----

    def prepare(self):  # gather what the working thread needs (it must not read the window's controls itself)
        """Save the settings and return a dict of everything a run needs."""
        self.save_settings()  # remember the settings
        self.stop.clear()  # not stopping yet
        job = dict(self.settings)  # callsign, grid, level, rig address, keying method, port
        job["entry"] = self.selected()  # the frequency chosen
        job["in"] = device_named(self.settings["audio_in"], "input") if self.settings["audio_in"] else None  # the input device, looked up by name at this moment
        job["out"] = device_named(self.settings["audio_out"], "output") if self.settings["audio_out"] else None  # the output device, likewise
        job["messages"], self.outbox = self.outbox, []  # the queued messages now belong to this run
        self.held += [{"to": to, "pieces": [words]} for words, to in job["messages"] if chain.parse(words)]  # pieces of chained messages are held for a working channel (since 0.42)
        job["messages"] = [(words, to) for words, to in job["messages"] if not chain.parse(words)]  # the rest go as usual
        offsets = working_offsets_hz(job["entry"])  # the working frequencies that go with the calling frequency
        job["move_hz"] = offsets[self.working.current() - 1] if self.working.current() > 0 else None  # the one chosen, or none
        self.move_offsets = list(offsets)  # every working channel, for a chained message that needs one (since 0.42)
        return job  # ready for the working thread

    def run(self, mode, job):  # the working thread: runs the monitor or the listening station
        source = rig = ptt = None  # nothing opened yet
        recorder = None  # the received-audio recorder, if turned on
        poller = None  # the radio-meter thread, once started
        self.poller_stop.clear()  # the meter thread may run
        try:  # anything that goes wrong is reported in the log
            source = AudioIn(job["in"])  # start recording from the chosen device
            self.audio = source  # let the scope and the meter show what it hears
            signal_log = self.signal_log = Guarded(SignalLog(self.signal_folder(), prefix=self.logbook.name, mode=job.get("signal_log", "off")), self.say)  # the detailed signal log (writes nothing when off)
            if job.get("record_rx"):  # the operator wants the received audio saved
                recorder = Recorder(recordings_dir(data_dir()), label=job["call"])  # hourly WAV files
                recorder.on_open = signal_log.recording_file  # the signal log notes where each file starts on the timeline
                source = RecordingSource(source, recorder)  # everything read is also written to the recording, and numbered
                self.say(f"recording received audio to {recorder.folder}")  # say where
            else:  # no recording
                source = TimedSource(source)  # still number every sample, for the signal log
            signal_log.session_start(mode, timeline=source, call=job["call"], grid=job["grid"], dial_khz=job["entry"]["dial_khz"], band=job["entry"].get("band"), rig=self.rig_name(),  # (continued)
                                     audio_in=job["audio_in"], audio_out=job["audio_out"], gain=job["gain"], recording=bool(job.get("record_rx")), settings=self.settings_summary())  # the run's starting point
            if signal_log.on:  # the operator turned it on
                self.say(f"signal log on ({signal_log.mode}): {signal_log.path()}")  # say where
            with self.rig_lock:  # one user of rig control at a time while it starts and tunes
                address = self.rig_address(job)  # start or find rig control for the chosen radio
                if address:  # rig control is set up
                    rig = RigCtl(address)  # connect to rigctld
                    self._tune(rig, job["entry"])  # go to the selected frequency
            if address:  # the radio can be read
                poller = threading.Thread(target=self.poll_radio, args=(address,), daemon=True)  # read its power setting and meters
                poller.start()  # in the background
            self.logbook.write("run", station=job["call"], text=f"{mode} started", dial_khz=job["entry"]["dial_khz"], rig=self.rig_name())  # the logbook
            self.logbook.write("settings", station=job["call"], text=f"settings at the start of {mode}", dial_khz=job["entry"]["dial_khz"], detail=self.settings_summary())  # the verbose log keeps a record
            if mode == "monitor":  # receive only
                listener = Listener()  # the continuous receiver
                listener.expect = lambda: (job["call"], self.expected_calls())  # this station's callsign and those it expects, to help read weak frames
                listener.on_progress = self.frames.update  # the frame strip follows each frame as it arrives (since 0.37)
                log_near = attach_signal_log(listener, signal_log, lambda: round(self.dial_hz() / 1000.0, 1))  # searches and near misses to the signal log, if on
                shown = NearFilter()  # which near misses the operator sees: likely Kestrel, once a minute per signal (since 0.31R2)
                listener.on_near = lambda result: (log_near(result), shown.show(result) and (self.say(near_line(result)), self.note_near(result)))  # every one to the signal log; the likely ones shown too
                watcher = Station(job["call"] or "NOCALL", job["grid"])  # a station that never transmits, used to piece broadcasts together
                watcher.mail, watcher.carries = self.mailroom, False  # it reads mail notices (a receipt for one of this station's messages still counts) but never holds mail
                self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, watcher  # the received list follows it
                with self.outbox_lock:  # the window may be queuing a message at this moment (since 0.40R3)
                    self.outbox = job["messages"] + self.outbox  # messages wait for the next time Listen runs
                    job["messages"] = []  # given back (the tidy-up below must not give them back twice; since 0.40R2)
                self.say("monitoring: receive only, nothing will be transmitted")  # opening line
                while not self.stop.is_set():  # until stopped
                    for heard in feed_from(listener, source):  # every frame that has completed
                        signal_log.rx(heard, dial_khz=round(self.dial_hz() / 1000.0, 1))  # the signal log (nothing when off)
                        self.say(describe(heard.result))  # show it
                        self.log_frame(heard.result)  # the verbose log
                        if heard.result.ok:  # it decoded
                            self.note_heard(heard.result)  # add its sender to the stations heard
                            watcher.handle(heard.result, time.monotonic())  # and let the watcher collect any broadcast
                    log_tick(signal_log, source)  # the signal log's once-a-minute lines
                    time.sleep(0.1)  # a tenth of a second between looks
                return  # done
            ptt = Ptt(job["ptt"], job["port"] or None, rig=rig)  # the transmit switch
            self.sink = AudioOut(job["out"], float(job["gain"] or 0.25))  # the playing side, at the slider's level
            station = Station(job["call"], job["grid"], close_when_done=False)  # the link rules for this station; since 0.41 a contact is held until End contact or the idle timeout (3 minutes, 6 with Keep-Alive on a working channel), which replaced Keep contact open
            self.idle_watch = IdleWatch(keep_alive=lambda: bool(self.settings.get("keep_alive")))  # the idle timeout, Keep-Alive (read from Settings each time) and the 10-second warning (since 0.41)
            station.move_to_hz = job["move_hz"] if rig is not None else None  # the working frequency to propose once locked (only when the radio can be retuned)
            self.move_ok = rig is not None  # whether a chained message can ask for a working channel (since 0.42)
            base_hz = job["entry"]["dial_khz"] * 1000.0  # the calling frequency, in hertz
            retune = (lambda offset: rig.set_frequency(base_hz + offset)) if rig is not None else None  # how to move the radio to a working frequency and back
            station.listen()  # answers directed calls...
            station.answer_beacons = station.answer_calls = bool(job["auto_answer"])  # ...but only if the operator chose that; otherwise it just listens, and answers only what the operator started
            station.available = bool(job["available"])  # and whether the operator is available for contacts
            station.mail = self.mailroom  # the mail kept between runs: this station's numbered messages, mail it carries, receipts
            station.carries = bool(job.get("carry_mail", True))  # whether it holds mail for other stations
            for text, to in job["messages"]:  # the queued messages
                station.queue(text, to=to or None)  # into the station's outbox, each with its address
            job["messages"], job["holder"] = [], station  # the station holds them now; if the run stops with a problem the tidy-up below takes them back from it (since 0.40R2)
            self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, station  # the lists follow this station from its beginning
            with self.outbox_lock:  # the window may be queuing a message at this moment (since 0.40R3)
                self.station = station  # from here on, newly queued messages go straight to this station
                late, self.outbox = self.outbox, []  # messages queued while this run was starting: before 0.40R3 they waited, unsent, for the next run
                for text, to in late:  # each of them
                    station.queue(text, to=to or None)  # into the station's outbox with the rest, with its address
            if late:  # some were
                self.say(f"{len(late)} message(s) queued while Listen was starting are ready to send")  # say so
            run_station(station, source, self.sink, ptt, say=self.say, stay_on=True, should_stop=self.stop.is_set, retune=retune, on_heard=self.note_heard, on_frame=self.log_frame, on_transmit=self.transmitting, on_tick=self.tick, on_near=self.note_near,  # (continued)
                        signal_log=signal_log, dial_khz=lambda: round(self.dial_hz() / 1000.0, 1), listen_first=bool(job.get("listen_first", True)), expect=self.expected_calls, notes=self.notes_for(), on_note=self.note_event, on_progress=self.frames.update,  # (continued)
                        idle=self.idle_watch, on_idle=self.idle_warning)  # the live loop, until stopped, with the signal log, the listen-first check, the callsigns it expects, and (since 0.41) the idle timeout with Keep-Alive and the 10-second warning
            with self.outbox_lock:  # the window may be queuing a message at this moment (since 0.40R3)
                self.station = None  # the run is over; later messages wait for the next one
                self.outbox = [(left, to or "") for left, to in zip(station.outbox, station.outbox_to)] + self.outbox  # anything it did not get to send is kept for the next run, with its address
                job["holder"] = None  # taken back (since 0.40R2)
            if rig is not None and station.offset_hz:  # the run was stopped while on a working frequency
                rig.set_frequency(base_hz)  # put the radio back on the calling frequency
                self.say("radio back on the calling frequency")  # confirm
            self.say(f"delivered {len(station.delivered)} message(s); {len(station.outbox)} still waiting (kept for the next run)" + (f"; holding {len(self.mailroom.bag)} message(s) for other stations" if self.mailroom.bag else ""))  # the outcome for sent traffic
            self.save_mail()  # keep the mail
        except Exception as problem:  # report any failure instead of dying silently
            import traceback  # where it happened
            where = os.path.join(LOG_FOLDER, time.strftime("problem_%Y%m%d_%H%M%SZ.txt", time.gmtime()))  # a file for the details, beside the logbook
            try:  # the folder may be unwritable
                os.makedirs(LOG_FOLDER, exist_ok=True)  # make sure it exists
                with open(where, "w", encoding="utf-8") as handle:  # the details
                    handle.write(f"Kestrel {SPEC_VERSION} ({native.describe()})\n{traceback.format_exc()}")  # version, library, and the traceback
            except OSError:  # it is
                where = "(could not be saved)"  # say so
            self.say(f"stopped by a problem: {problem!r} (details: {where})")  # what went wrong, and where the details are
            if self.signal_log is not None:  # a signal log was started
                self.signal_log.note("stopped by a problem", problem=repr(problem))  # keep it there too
            self.mode = "off"  # nothing is running now
            self.root.after(0, lambda: self.mode_var.set("off"))  # show it (from the window's own thread)
        finally:  # always tidy up
            with self.outbox_lock:  # the window may be queuing a message at this moment (since 0.40R3)
                self.station = None  # first: no more messages go to a station that has stopped (a message queued between the next line and this one was lost in 0.40R2)
                self.outbox = unsent_messages(job, self.say) + self.outbox  # messages this run took and did not send go back in the queue, however it ended (before 0.40R2 a run that failed to start, or stopped with a problem, lost them while their rows still said "waiting")
            if self.signal_log is not None:  # a signal log was started
                self.signal_log.session_end(mode=mode)  # close the run in it
                self.signal_log = None  # no log until the next run
            if recorder is not None:  # audio was being recorded
                recorder.close()  # finish the file
                self.say(f"recording saved: {', '.join(os.path.basename(path) for path in recorder.files)}")  # say which files
            self.station = None  # no station is running any more, whatever happened
            self.poller_stop.set()  # stop reading the radio's meters
            self.tx_active = False  # the transmitter is off
            if self.sink is not None:  # an output was set up (since 0.41 it holds its stream open for the whole run)
                self.sink.close()  # release the sound card
            self.sink = None  # nothing to transmit with
            if ptt is not None:  # a transmit switch was opened
                ptt.close()  # make sure the transmitter is off
            if poller is not None:  # the meter thread was started
                poller.join(timeout=3)  # let it hang up first
            if rig is not None:  # rig control was opened
                rig.close()  # hang up
            self.audio = None  # the scope has nothing to show any more
            if source is not None:  # recording was started
                source.close()  # release the sound device
            self.logbook.write("run", station=job["call"], text=f"{mode} stopped", dial_khz=job["entry"]["dial_khz"])  # the logbook
            self.say("stopped")  # closing line

    # ---- exporting and importing settings and themes (since 0.37) ----

    def export_settings(self):  # File > Export settings...
        """Ask whether to include this computer's sound cards, ports and layout, then write the settings to a file the operator chooses."""
        top = self.window("export_settings", "Kestrel - export settings")  # a small window
        body = ttk.Frame(top, padding=12)  # its contents
        body.pack(fill="both", expand=True)  # filling it
        ttk.Label(body, text="Your station, radio, audio levels, operating, logging, quick messages and looks\nare written to one file, for a backup or to set up Kestrel on another computer.", justify="left").pack(anchor="w")  # what goes in
        machine = tk.BooleanVar(value=False)  # this computer's own settings: left out unless asked
        ttk.Checkbutton(body, text="Include this computer's sound cards, radio ports and window layout\n(leave this off when the file is for a different computer)", variable=machine).pack(anchor="w", pady=(10, 0))  # the choice
        ttk.Label(body, text="Themes are exported on their own: File > Export themes.\nContacts and logs are not included.", justify="left", foreground=self.colors.get("muted", "")).pack(anchor="w", pady=(10, 0))  # what is not in it

        def go():  # Export...
            self.save_settings()  # the settings as they are now
            stamp = time.strftime("%Y%m%d")  # today, for the file name
            call = re.sub(r"[^A-Za-z0-9]", "", self.settings.get("call", "")) or "station"  # the callsign, safe in a file name
            path = filedialog.asksaveasfilename(parent=top, title="Export settings", defaultextension=".json", initialfile=f"kestrel-settings-{call}-{stamp}.json", filetypes=[("Kestrel settings", "*.json")])  # where
            if not path:  # none chosen
                return  # nothing done
            try:  # the folder may refuse
                export_settings_file(self.settings, path, machine=machine.get())  # written
            except OSError as problem:  # it did
                messagebox.showerror("Kestrel", f"The settings could not be written:\n{problem}", parent=top)  # said
                return  # nothing more
            top.destroy()  # done with the window
            messagebox.showinfo("Kestrel", "Settings exported. File > Import settings reads them back, here or on another computer.", parent=self.root)  # said

        buttons = ttk.Frame(body)  # the buttons
        buttons.pack(fill="x", pady=(14, 0))  # under the words
        ttk.Button(buttons, text="Export...", command=go).pack(side="left")  # go ahead
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")  # never mind

    def import_settings(self):  # File > Import settings...
        """Read settings from an exported file, keep a copy of the present ones, and use the new ones from the next start (offering to restart now)."""
        path = filedialog.askopenfilename(parent=self.root, title="Import settings", filetypes=[("Kestrel settings", "*.json"), ("All files", "*.*")])  # which file
        if not path:  # none chosen
            return  # nothing done
        try:  # it may not be a settings file
            incoming = read_settings_file(path)  # the settings in it
        except ValueError as problem:  # it is not
            messagebox.showerror("Kestrel", str(problem), parent=self.root)  # said
            return  # nothing done
        machine = any(key in incoming for key in MACHINE_KEYS) and messagebox.askyesno("Kestrel", "This file also holds a computer's sound cards, radio ports and window layout.\n\nUse those too? Choose No to keep this computer's own.", parent=self.root)  # this computer's own settings: kept unless the operator says otherwise
        call = incoming.get("call") or "(none)"  # whose they are
        if not messagebox.askyesno("Kestrel", f"Replace your settings with the ones in this file (callsign {call})?\n\nA copy of your present settings is kept in the data folder first.", parent=self.root):  # agreed?
            return  # nothing done
        self.save_settings()  # the present settings, up to date
        backup = side_file(time.strftime("_before_import_%Y%m%d_%H%M%S.json"))  # the copy's name
        write_json(backup, self.settings)  # kept
        self.pending_import = merged_settings(self.settings, incoming, machine)  # used from the next start (close writes them over what it saves)
        write_json(SETTINGS_FILE, self.pending_import)  # and written now, in case Kestrel is stopped some other way
        if messagebox.askyesno("Kestrel", f"Settings imported. Your old ones are kept as {os.path.basename(backup)}.\n\nThey take effect when Kestrel starts again. Restart Kestrel now?", parent=self.root):  # restart?
            self.restart()  # closed and started again

    def update_status_text(self):  # the words beside Check now in Settings > Updates (since 0.42)
        """Say when the last check was, in local time, and what it found."""
        last = float(self.settings.get("update_last") or 0)  # when
        if not last:  # never
            return "Not checked yet."  # say so
        found = getattr(self, "update_offer", None)  # what it found
        result = f"Kestrel {found['version']} is available." if found else "You have the newest version."  # in words
        return f"Last checked {time.strftime('%Y-%m-%d %H:%M', time.localtime(last))}. {result}"  # the line

    def update_tick(self, started=False):  # see whether a check is due (since 0.42)
        """Check now if Settings > Updates says so; look again in an hour."""
        if updates.due(self.settings.get("update_check", "daily"), self.settings.get("update_last"), time.time(), started):  # due
            self.begin_update_check(manual=False)  # check, quietly
        self.root.after(3600 * 1000, self.update_tick)  # look again in an hour

    def begin_update_check(self, manual=False):  # ask GitHub, in the background (since 0.42)
        """Start a check in its own thread; update_poll picks up the answer. `manual`: the operator asked, so always answer."""
        if self.update_thread is not None and self.update_thread.is_alive():  # one is already running
            return  # it will answer
        choices = (SPEC_VERSION, SIGNAL_VERSION, bool(self.settings.get("update_test", True)), self.settings.get("update_notify") == "signal", "" if manual else self.settings.get("update_skip", ""))  # what to ask (a manual check also shows a skipped version)

        def work():  # in the background: the network may be slow
            self.update_result = updates.check(*choices)  # the answer: (release or None, problem or None)
        self.update_result = None  # no answer yet
        self.update_thread = threading.Thread(target=work, name="update-check", daemon=True)  # the thread
        self.update_thread.start()  # started
        self.root.after(500, lambda: self.update_poll(manual))  # look for the answer

    def update_poll(self, manual):  # the check's answer, back in the window's own thread (since 0.42)
        """Show what the check found: a notice for a newer release; for a manual check, also 'up to date' or the problem."""
        if self.update_thread is not None and self.update_thread.is_alive():  # still waiting for GitHub
            self.root.after(500, lambda: self.update_poll(manual))  # look again
            return  # not yet
        offer, problem = self.update_result or (None, "no answer")  # the answer
        if problem:  # no answer from GitHub
            self.say(f"update check: GitHub not reachable ({problem})")  # in the Activity log, quietly
            if manual:  # the operator asked
                messagebox.showinfo("Kestrel", f"Kestrel could not reach GitHub to check for updates.\n\n{problem}", parent=self.root)  # say why
            return  # try again at the next check
        self.settings["update_last"] = time.time()  # when this check was
        self.save_settings()  # remembered
        self.update_offer = offer  # what was found
        if self.update_label is not None and self.update_label.winfo_exists():  # Settings > Updates is open
            self.update_label.configure(text=self.update_status_text())  # bring it up to date
        if offer is not None:  # a newer release
            self.say(f"update: Kestrel {offer['version']} is available" + (f" (new signal version {offer['signal']})" if offer["new_signal"] else ""))  # in the Activity log
            self.show_update_notice(offer)  # and in a window
        elif manual:  # the operator asked, and there is nothing newer
            messagebox.showinfo("Kestrel", f"You have the newest version, Kestrel {SPEC_VERSION}.", parent=self.root)  # say so

    def show_update_notice(self, offer):  # the window that tells the operator about a newer release (since 0.42)
        """Say what the new release is and offer Install now, the release page, Remind me later and Skip this version."""
        box = self.window("update", f"Kestrel {offer['version']} is available")  # a window of its own
        box.resizable(False, False)  # a fixed size
        frame = ttk.Frame(box, padding=12)  # its contents
        frame.pack(fill="both", expand=True)  # fill it
        ttk.Label(frame, text=f"Kestrel {offer['version']} is available. You have {SPEC_VERSION}.", font="KestrelBold").pack(anchor="w")  # the news
        if offer["new_signal"]:  # it changes what is sent
            ttk.Label(frame, text=f"New signal version {offer['signal']}: stations on signal {SIGNAL_VERSION} and {offer['signal']} mostly cannot hear each other.\nBoth stations should update before testing together.", foreground=self.colors.get("bar_hot", "red"), justify="left").pack(anchor="w", pady=(6, 0))  # the warning that matters on the air
        if offer["test"]:  # a pre-release
            ttk.Label(frame, text="This is a test release.", font="KestrelSmall").pack(anchor="w", pady=(4, 0))  # say so
        notes = "\n".join(offer["notes"].splitlines()[:12])  # the first lines of what changed
        if notes:  # there are some
            words = tk.Text(frame, height=min(12, notes.count("\n") + 1), width=86, wrap="word", relief="solid", borderwidth=1)  # room to read them
            words.insert("1.0", notes)  # the notes
            words.configure(state="disabled")  # read only
            words.pack(fill="both", pady=(8, 0))  # place it
            theme.color_window(box, self.colors)  # in the chosen look
        self.update_progress = ttk.Label(frame, text="", font="KestrelSmall")  # download progress
        self.update_progress.pack(anchor="w", pady=(6, 0))  # under the notes
        row = ttk.Frame(frame)  # the buttons
        row.pack(fill="x", pady=(10, 0))  # at the bottom
        if self.settings.get("update_install", "ask") == "ask" and getattr(sys, "frozen", False):  # the installed program, and the operator wants the offer
            install = ttk.Button(row, text="Install now", command=lambda: self.install_update(offer))  # download, close, install, restart
            install.pack(side="left")  # first
            Tooltip(install, "Downloads the setup program and checks it, waits until no contact is under way and nothing is being sent, then closes Kestrel (your waiting messages are kept), installs the update and starts Kestrel again.")  # help
        ttk.Button(row, text="Release page", command=lambda: self.open_web(offer["page"])).pack(side="left", padx=(6, 0))  # read about it, or download it by hand
        ttk.Button(row, text="Remind me later", command=box.destroy).pack(side="left", padx=(6, 0))  # ask again at the next check
        ttk.Button(row, text="Skip this version", command=lambda: self.skip_update(offer, box)).pack(side="left", padx=(6, 0))  # no more notices for this one

    def open_web(self, url):  # open a web page in the operator's browser (since 0.42)
        import webbrowser  # the standard way
        webbrowser.open(url)  # opened

    def skip_update(self, offer, box):  # Skip this version (since 0.42)
        """No more notices about this version (one that changes the signal is still shown)."""
        self.settings["update_skip"] = offer["version"]  # remembered
        self.save_settings()  # kept
        box.destroy()  # the notice closes

    def update_idle(self):  # whether an update may install now (since 0.42)
        """True when no contact is under way and nothing is being sent: Kestrel never cuts a transmission or contact short."""
        return self.contact is None and not getattr(self, "tx_active", False)  # idle

    def install_update(self, offer):  # Install now (since 0.42)
        """Download and check the setup program, then, once Kestrel is idle, hand over to the helper and close."""
        if getattr(self, "update_download", None) is not None and self.update_download.is_alive():  # already downloading
            return  # it will carry on
        self.update_path, self.update_problem = None, None  # nothing yet

        def progress(done, total):  # called as the file arrives (in the download thread)
            self.update_done = (done, total)  # read by the window's own thread

        def work():  # in the background
            try:  # the download may fail
                self.update_path = updates.download(offer, progress=progress)  # fetched and checked
            except Exception as problem:  # anything at all
                self.update_problem = str(problem) or problem.__class__.__name__  # kept to show
        self.update_done = (0, 0)  # nothing yet
        self.update_download = threading.Thread(target=work, name="update-download", daemon=True)  # the thread
        self.update_download.start()  # started
        self.say(f"update: downloading Kestrel {offer['version']}")  # in the Activity log
        self.root.after(500, lambda: self.update_install_poll(offer))  # watch it

    def update_install_poll(self, offer):  # follow the download, then wait for an idle moment (since 0.42)
        label = getattr(self, "update_progress", None)  # the notice's progress line, if the notice is open
        shown = label is not None and label.winfo_exists()  # it is
        if self.update_download.is_alive():  # still coming
            done, total = self.update_done  # how far
            if shown:  # the notice is open
                label.configure(text=f"Downloading: {done / 1e6:.1f} of {total / 1e6:.1f} MB" if total else f"Downloading: {done / 1e6:.1f} MB")  # say how far
            self.root.after(500, lambda: self.update_install_poll(offer))  # look again
            return  # not yet
        if self.update_problem:  # it failed
            self.say(f"update: download stopped by a problem: {self.update_problem}")  # in the Activity log (it opens)
            if shown:  # the notice is open
                label.configure(text=f"Not installed: {self.update_problem}")  # say why
            return  # nothing installed
        if not self.update_idle():  # a contact or a transmission is under way
            if shown:  # the notice is open
                label.configure(text="Downloaded and checked. Installing when the contact ends and nothing is being sent...")  # say what it waits for
            self.root.after(2000, lambda: self.update_install_poll(offer))  # look again shortly
            return  # not yet
        program = os.path.join(updates.install_folder(), "Kestrel.exe")  # where the new version will be
        updates.start_helper(os.getpid(), self.update_path, program, sys.argv[1:])  # the helper waits for this program to close, installs, starts it again
        self.say(f"update: installing Kestrel {offer['version']}; Kestrel will start again by itself")  # in the Activity log
        self.close()  # save everything, release the radio, close

    def restart(self):  # close Kestrel and start it again (after an import)
        """Close the panel the usual way, then start the same program with the same options."""
        command = [sys.executable] + sys.argv[1:] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]  # the installed program, or Python and this script; same profile
        self.close()  # everything saved and the radio released
        subprocess.Popen(command, close_fds=True)  # started again

    def export_themes(self):  # File > Export themes...
        """Write every theme the operator made, and every built-in theme they changed, to one file."""
        mine = theme.user_themes()  # what there is
        count = len(mine["program"]) + len(mine["scope"]) + len(mine["changed"]["program"]) + len(mine["changed"]["scope"])  # how many
        if not count:  # nothing of the operator's
            messagebox.showinfo("Kestrel", "You have no themes of your own and have not changed any built-in theme, so there is nothing to export.\n\nTo give someone one of Kestrel's themes, use View > Edit themes > Export this theme.", parent=self.root)  # said
            return  # nothing done
        path = filedialog.asksaveasfilename(parent=self.root, title="Export themes", defaultextension=".json", initialfile=f"kestrel-themes-{time.strftime('%Y%m%d')}.json", filetypes=[("Kestrel themes", "*.json")])  # where
        if not path:  # none chosen
            return  # nothing done
        try:  # the folder may refuse
            theme.export_all(path)  # written
        except OSError as problem:  # it did
            messagebox.showerror("Kestrel", f"The themes could not be written:\n{problem}", parent=self.root)  # said
            return  # nothing more
        messagebox.showinfo("Kestrel", f"{count} theme(s) exported. File > Import themes reads them back, here or on another computer.", parent=self.root)  # said

    def import_themes(self):  # File > Import themes...
        """Read themes from a file: new ones are added (renamed if the name is taken), changed built-in themes replace Kestrel's."""
        path = filedialog.askopenfilename(parent=self.root, title="Import themes", filetypes=[("Kestrel themes", "*.json"), ("All files", "*.*")])  # which file
        if not path:  # none chosen
            return  # nothing done
        count = theme.load_user(path)  # read into the tables
        if not count:  # nothing usable
            messagebox.showerror("Kestrel", "That file holds no Kestrel themes.", parent=self.root)  # said
            return  # nothing done
        theme.save_user()  # kept
        self.refresh_theme_menus()  # in View > Theme and Scope theme
        self.apply_look(self.settings.get("theme", "system"), self.settings.get("scope_theme", "theme"))  # the theme in use may have been one of them
        messagebox.showinfo("Kestrel", f"{count} theme(s) imported. Choose one under View > Theme or View > Scope theme.", parent=self.root)  # said

    def close(self):  # the window is being closed
        self.stop.set()  # stop the station
        self.beacon_wanted = False  # and the repeating beacon
        if self.contact is not None:  # a contact was under way
            self.finish_contact()  # log what there is of it
        self.save_layout()  # remember the window's size and the dividers
        self.save_settings()  # remember the settings
        if getattr(self, "pending_import", None) is not None:  # settings imported, to take effect at the next start (since 0.37)
            write_json(SETTINGS_FILE, self.pending_import)  # they replace what was just saved
        self.save_outbox()  # and the messages still waiting
        self.save_mail()  # and the mail
        if self.worker is not None:  # a station or the monitor was running
            self.worker.join(timeout=3)  # give it a moment to unkey and release the sound card
        self.rigs.stop()  # stop the rig control program this panel started
        self.root.destroy()  # close the window


def rigctld_program(settings):  # the rig control program to run (since 0.42R1)
    """Return the rigctld chosen in Settings if that file still exists, else one found on this computer (the copy installed
    with Kestrel first). A saved path can go stale when Kestrel moves, as it did from Program Files to the per-user folder in 0.42."""
    saved = settings.get("rigctld") or ""  # the one remembered
    if saved and os.path.isfile(saved):  # still there
        return saved  # use it
    return find_rigctld()  # the installed copy, or one on the search path, or WSJT-X's


def self_check():  # Kestrel.exe --check: is everything the program needs present?
    """Check the libraries, the sound system, rigctld and the data folder; write a report to kestrel_check.txt in the data folder. Return 0 if all is well, 1 if not."""
    lines, ok = [about_text().splitlines()[0], f"Signal version {SIGNAL_VERSION}, specification {SPEC_VERSION}, {build_info()}"], True  # the report so far, and whether all is well

    def note(passed, words):  # one line of the report
        nonlocal ok  # the overall result
        ok = ok and passed  # a failure spoils it
        lines.append(("OK    " if passed else "FAIL  ") + words)  # the line

    note(True, f"data folder: {data_dir()}")  # where settings and logs go
    try:  # the numerical libraries
        import scipy.signal  # noqa: F401  # filtering, used by the modem
        note(True, f"numpy {np.__version__}, scipy {scipy.__version__}")  # present
    except Exception as problem:  # missing
        note(False, f"numpy/scipy: {problem}")  # say so
    note(True, f"modem: {native.describe()}")  # compiled library or pure Python (either works; the library is faster)
    try:  # the sound system
        devices = list_devices()  # every sound device
        note(bool(devices), f"sound system: {sum(1 for d in devices if d[2] > 0)} input and {sum(1 for d in devices if d[3] > 0)} output devices")  # how many
    except Exception as problem:  # no sound library or no sound system
        note(False, f"sound system: {problem}")  # say so
    try:  # the tools the File menu uses (in the installed program they must have been packed in)
        from tools import decode_wav, signal_report  # noqa: F401  # decoding recordings and summarizing signal logs
        note(True, "tools: decode a recording, signal log report")  # present
    except Exception as problem:  # left out of the build
        note(False, f"tools: {problem}")  # say so
    why = propagation.missing()  # the ITU-R P.533 program and its data (since 0.32)
    if why is None:  # present: try one real prediction
        try:  # it may fail to run
            rows = propagation.predict("EM93", "EM95", time.gmtime().tm_year, time.gmtime().tm_mon, 80)  # a short path, this month
            note(len(rows) > 0, f"propagation: ITU-R P.533 program runs ({len(rows)} band-hours predicted)")  # it works
        except Exception as problem:  # it did not run
            note(False, f"propagation: {problem}")  # say so
    else:  # missing
        note(False, f"propagation: {why}")  # say so
    note(sunspots.current() is not None, sunspots.describe())  # the sunspot predictions and their issue date
    program = find_rigctld()  # the rig control program
    models = list_models(program) if program else []  # the radios it knows
    note(bool(program) and bool(models), f"rigctld: {os.path.basename(program) if program else 'not found'}, {len(models)} radio types")  # found and working (the name only: no folder names in the report)
    try:  # serial ports, for CAT
        from serial.tools import list_ports  # pyserial
        note(True, f"serial ports: {', '.join(sorted(p.device for p in list_ports.comports())) or 'none at present'}")  # what is plugged in
    except Exception as problem:  # pyserial missing
        note(False, f"serial ports: {problem}")  # say so
    try:  # the window toolkit
        probe = tk.Tk()  # a window
        probe.withdraw()  # never shown
        probe.destroy()  # and gone
        note(True, f"window toolkit: Tk {tk.TkVersion}")  # present
    except Exception as problem:  # no display, or Tk missing
        note(False, f"window toolkit: {problem}")  # say so
    lines.append("RESULT: " + ("everything Kestrel needs is present" if ok else "something is missing (see FAIL lines)"))  # the verdict
    report = "\n".join(lines) + "\n"  # as text
    try:  # keep a copy where the operator can find it
        with open(os.path.join(data_dir(), "kestrel_check.txt"), "w", encoding="utf-8") as handle:  # the report file
            handle.write(report)  # write it
    except OSError:  # it could not be written
        pass  # the console copy will do
    try:  # a windowed program may have no console to print to
        print(report)  # show it
    except Exception:  # no console
        pass  # the file has it
    return 0 if ok else 1  # the exit code


def main():  # the script itself
    """Open the panel."""
    global SETTINGS_FILE, PROFILE  # a named profile keeps its settings in a file of its own
    parser = argparse.ArgumentParser(description="Kestrel control panel")  # the command-line reader
    parser.add_argument("--profile", default="", help="a name for a second set of remembered settings, for running one panel per radio")  # optional profile name
    parser.add_argument("--check", action="store_true", help="check the installation (libraries, sound system, rigctld) without opening the window, and write the result to kestrel_check.txt in the data folder")  # the installation check
    args = parser.parse_args()  # read the options
    if args.check:  # just check the installation
        sys.exit(self_check())  # and stop, with 0 if everything was found
    PROFILE = "".join(c for c in args.profile if c.isalnum() or c in "-_")  # keep only characters that are safe in a file name
    if PROFILE:  # a profile was named
        SETTINGS_FILE = os.path.join(data_dir(), f"panel_{PROFILE}.json")  # its own settings file
    crash_file = None  # where a hard crash's details go (since 0.38R2)
    try:  # the folder may refuse
        import faulthandler  # Python's own record of a crash that kills the program outright (in the compiled library, say), which no ordinary error report sees
        os.makedirs(LOG_FOLDER, exist_ok=True)  # the logs folder
        crash_file = open(os.path.join(LOG_FOLDER, f"crash_{time.strftime('%Y%m%d_%H%M%SZ', time.gmtime())}.txt"), "w", encoding="utf-8")  # one file per start; left empty (and removed at a normal exit) unless the program crashes
        crash_file.write(f"Kestrel {SPEC_VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}; if more follows, the program crashed: where each thread was\n")  # what the file is
        crash_file.flush()  # on disk now
        faulthandler.enable(file=crash_file, all_threads=True)  # on a crash, every thread's place is written here
    except OSError:  # no file: go on without it
        crash_file = None  # none
    root = tk.Tk()  # the window
    Panel(root)  # its contents
    if PROFILE:  # a profile was named
        root.title(f"Kestrel {SPEC_VERSION} - {PROFILE}  -  signal v{SIGNAL_VERSION}")  # show the program's version, which panel this is, and the signal version
    root.mainloop()  # run until closed
    if crash_file is not None:  # a normal exit: no crash to report
        try:  # tidy up
            import faulthandler  # (imported above)
            faulthandler.disable()  # no longer watching
            crash_file.close()  # finished
            os.remove(crash_file.name)  # an empty record is not kept
        except OSError:  # could not
            pass  # harmless


if __name__ == "__main__":  # only when run as a script
    main()  # go
