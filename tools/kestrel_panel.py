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

Only transmit where your licence allows, with the published specification matching this program.
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
from live import KIND, Listener, call_request, describe, near_line, plain_line, run_station, status_for  # the continuous receiver, a directed call to make when free, a one-line frame description, a near-miss line, the plain form of a log line, the live loop, the state shown by a log line  # noqa: E402
from live import heardlog, logbook, mixer, telemetry, theme  # the 48-hour heard log, the CSV and ADIF logbook, Windows' device levels, telemetry messages, light and dark looks  # noqa: E402
from live.audio import AudioIn, AudioOut, device_named, list_devices  # sound-card input and output  # noqa: E402
from live.bands import add_user_frequency, all_frequencies, describe_frequency, in_data_segment, remove_user_frequency, user_frequencies, working_offsets_hz  # the frequency list, the data-segment check and the working frequencies  # noqa: E402
from live.recorder import Recorder, RecordingSource, TimedSource, recordings_dir  # recording the received audio to WAV files, and numbering every sample received  # noqa: E402
from live.runner import attach_signal_log, feed_from, log_tick  # the listener fed with numbered audio, and the signal log connected to it  # noqa: E402
from live.signallog import CLIPS_MAX_MB, KEEP_DAYS, SignalLog  # the detailed signal log for analysis and debugging  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.rig import RigCtl, RigServer, find_rigctld, list_models, list_models_why, models_for  # rig control through Hamlib's rigctld, and starting rigctld for a chosen radio  # noqa: E402
from modem.levels import LEVELS, level_name  # the speed levels, for how wide each signal is on the scope, and their names (L0 to L4, LB)  # noqa: E402
from modem.longbeacon import LONG  # the long beacon's tone length and spacing  # noqa: E402
from modem.params import LONG_LEVEL, M_TONES, SIGNAL_VERSION, SPEC_VERSION  # tones per frame, the signal's version and the document's version  # noqa: E402

PROFILE = ""  # the name given with --profile, if any (set in main)
SETTINGS_FILE = os.path.join(data_dir(), "panel.json")  # where the panel remembers its settings (local/ from the source folder; the user's profile when installed)
LOG_FOLDER = os.path.join(data_dir(), "logs")  # where the CSV and ADIF logbook files go
BEACON_MIN, BEACON_MAX = 5, 60  # the repeating beacon may be set to no less than 5 and no more than 60 minutes
AUTOSTOP_MIN, AUTOSTOP_MAX = 15, 720  # the beacon's automatic stop, when used, is between 15 minutes and 12 hours (0 turns it off)
DEFAULTS = {"call": "", "grid": "", "name": "", "rig_text": "", "max_power_w": "100",  # (continued: the station)
            "frequency": 0, "audio_in": "", "audio_out": "", "gain": "0.25", "rig": "", "ptt": "none", "port": "",  # (continued: frequency, audio, keying)
            "rig_model": "", "cat_port": "", "cat_baud": "38400", "cat_handshake": "none", "rigctld": "", "keep_open": False, "working": 0,  # (continued: rig control, contacts)
            "start_mode": "listen", "beacon_every_min": 5, "beacon_type": "short", "listen_first": True, "beacon_autostop_min": 120, "auto_answer": False, "available": True,  # (continued: operating)
            "log_level": "basic", "record_rx": False, "signal_log": "off", "theme": "system",  # (continued: logging, recording and looks)
            "quick1": "{call} {name} {grid}", "quick2": "{call} {name} {grid} RIG {rig} {power}W", "quick3": "{call} {telemetry}"}  # the quick messages
PTT_NAMES = {"none": "None (receive only, or VOX)", "rig": "CAT (through rig control)", "rts": "RTS line of a serial port", "dtr": "DTR line of a serial port"}  # keying methods, as the operator sees them
START_NAMES = {"listen": "Listen", "monitor": "Monitor (receive only)", "off": "Nothing (start switched off)"}  # what the panel does when it opens
ANSWER_NAMES = {False: "Just listen: show me beacons and calls; I choose whether to respond", True: "Answer every beacon and call automatically"}  # whether Listen transmits by itself
CALLING_KEEP_S = 300.0  # a station that beaconed stays highlighted in the Stations heard list this long
LOG_NAMES = {"basic": "Basic: messages and contacts", "advanced": "Advanced: adds signal readings, power, stations heard, beacons", "verbose": "Verbose: everything, every frame and meter"}  # logging levels, as the operator sees them
SIGNAL_NAMES = {"off": "Off", "on": "On: text only (a few MB a day)",  # the signal log, as the operator sees it (continued)
                "clips": f"On, with each frame's audio (clips kept {KEEP_DAYS} days, at most {CLIPS_MAX_MB} MB)"}  # (continued)
LISTEN_FIRST_NAMES = {True: "On: hold beacons, calls and broadcasts while the frequency is in use", False: "Off: transmit regardless (you check the frequency yourself)"}  # listen before transmitting, as the operator sees it
BEACON_TYPE_NAMES = {"short": "Short: a call-up others can answer (7 to 31 s)",  # the two kinds of repeating beacon (continued)
                     "long": "Long: about 60 s, heard much further; nobody answers (every 10 min at most)"}  # (continued)
LONG_EVERY_MIN = 10  # long beacons repeat no more often than this, in minutes (each holds the frequency for a minute)
ALC_HIGH = 0.5  # an ALC reading at or above this share of the radio's scale means the transmit audio is too strong (data modes want ALC near zero)
RECORD_NAMES = {False: "Off", True: "On: save everything received to WAV files (about 86 MB an hour, kept 7 days)"}  # recording the received audio, as the operator sees it
CALL_PATTERN = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](/[A-Z0-9]{1,4})?$")  # the general shape of an amateur callsign, with an optional prefix or suffix such as /P or /1
THEME_NAMES = {"system": "System (follow Windows)", "light": "Light", "dark": "Dark"}  # looks, as the operator sees them
NO_RIG = "(no rig control)"  # the radio-type choice that means the radio is tuned by hand
LOCKED = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states of a contact in progress
SHORTCUTS = (  # the keyboard shortcuts, for Help > Keyboard shortcuts
    ("F1", "this list"), ("F2", "Listen (nothing is sent unless you start it)"), ("F3", "Monitor (receive only)"), ("F4", "Off (stop receiving and transmitting)"),  # (continued)
    ("Ctrl+U", "Available / Unavailable for contacts"), ("F5", "Beacon (call anyone) on or off"), ("F6", "Call the station in the To box"), ("F7", "End the contact"), ("F8", "Stations heard in the last 48 hours"),  # (continued)
    ("F9", "Telemetry received"), ("F11", "Broadcast the message to ALL"), ("F12", "Settings"),  # (continued)
    ("Ctrl+Y", "Respond: call the station selected in the Stations heard list"),  # (continued)
    ("Ctrl+L", "go to the To box (callsign)"), ("Ctrl+M", "go to the Message box"), ("Enter", "in the Message box: queue the message; in a list: put the callsign in To"),  # (continued)
    ("Ctrl+1, 2, 3", "put quick message 1, 2 or 3 in the Message box"), ("Ctrl+4", "send telemetry to the station in To"), ("Ctrl+5", "broadcast telemetry to ALL"),  # (continued)
    ("Ctrl+R", "go to the frequency list"), ("Ctrl+Up / Ctrl+Down", "previous / next frequency"), ("Ctrl+G", "go to the stations list"),  # (continued)
    ("Ctrl+J", "go to the level sliders"), ("Tab / Shift+Tab", "move between controls"), ("Alt + underlined letter", "open a menu"), ("Esc", "close a window"))  # the rest


def load_settings():  # read the remembered settings
    """Return the saved settings, with defaults for anything missing."""
    settings = dict(DEFAULTS)  # start from the defaults
    settings.update(read_json(SETTINGS_FILE, {}))  # saved values replace the defaults
    return settings  # the settings to use


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
            f"Signal version: {SIGNAL_VERSION}\n"  # the version of the transmitted signal
            f"Specification: version {SPEC_VERSION} (draft)\n"  # which version of the published description the program follows
            f"Program: {build_info()}\n"  # which build of the program
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n\n"  # the Python it runs on
            f"Stations must have the same signal version to hear each other.\n\n"  # the practical point
            f"Originated by P. H. Ewen (KO4WSC).\nProgram under Apache License 2.0; specification under CC BY 4.0.")  # credit and licences


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
        self.outbox = []  # messages queued while no station is running, as (text, callsign it is for or "")
        self.shown_b = 0  # how many of the tracked station's received broadcasts are already in the list
        self.station = None  # the station that is running now, when there is one, so a message can be handed straight to it
        self.tracked = None  # the station whose messages the lists are following (kept after it stops, for a last look)
        self.marked = 0  # how many of the tracked station's delivered messages are already marked in the list
        self.shown = 0  # how many of the tracked station's received messages are already in the list
        self.history = []  # every log line so far, as (time of day, line), so the log can be redrawn plain or in detail
        self.heard = queue.Queue()  # reports of stations heard, waiting to go into the list (filled by the working thread)
        self.heard_rows = {}  # callsign -> its row in the stations-heard list
        self.notice = None  # the warning window about an idle working frequency, while one is showing
        self.contacts = read_json(CONTACTS_FILE, {})  # saved contacts: callsign -> {"grid": locator}
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
        self.heardlog = heardlog.HeardLog(side_file("_heard.jsonl"))  # every station heard in the last 48 hours, kept on disk
        self.logbook = logbook.Logbook(LOG_FOLDER, name="kestrel" + (f"_{PROFILE}" if PROFILE else ""), level=self.settings["log_level"])  # the CSV and ADIF logs
        self.colours = theme.apply(root, self.settings["theme"])  # the chosen look (light or dark), and its colours
        root.title(f"Kestrel  -  signal v{SIGNAL_VERSION}")  # window title, with the signal version so two stations can be compared at a glance
        root.columnconfigure(0, weight=1)  # the single column stretches with the window
        self.mode_var = tk.StringVar(value="off")  # the mode buttons and menu items share this
        self.beacon_var = tk.BooleanVar(value=False)  # the beacon button and menu item share this
        self.beacon_type_var = tk.StringVar(value=self.settings.get("beacon_type", "short"))  # short or long beacons
        self.available_var = tk.BooleanVar(value=bool(self.settings["available"]))  # available for contacts, or not
        self.keep_open = tk.BooleanVar(value=bool(self.settings["keep_open"]))  # whether the lock is held after the traffic is done
        self.details = tk.BooleanVar(value=False)  # whether the log shows the technical detail
        self.theme_var = tk.StringVar(value=self.settings["theme"])  # the look chosen in the View menu
        self._menus()  # the menu bar
        top = ttk.Frame(root)  # the strip holding the status line and the station's own details
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))  # place it at the top
        top.columnconfigure(0, weight=1)  # the status line takes the spare width
        self.status = tk.Label(top, text="OFF", font=("Segoe UI", 15, "bold"), anchor="w", padx=8, pady=4)  # the station's state in large letters, on a band of colour
        self.status.grid(row=0, column=0, sticky="ew")  # place it on the left
        self.me = ttk.Label(top, text="", font=("Segoe UI", 10))  # this station's callsign and grid locator
        self.me.grid(row=0, column=1, sticky="e", padx=(8, 0))  # place it on the right
        self.readings = ttk.Label(root, text="", font=("Segoe UI", 10))  # the partner, the last signal reading and the two speed levels
        self.readings.grid(row=1, column=0, sticky="ew", padx=8)  # place it under the status line
        tuning = ttk.Frame(root)  # the frequency row
        tuning.grid(row=2, column=0, sticky="ew", padx=8, pady=4)  # place it
        tuning.columnconfigure(1, weight=1)  # the list takes the spare width
        ttk.Label(tuning, text="Frequency").grid(row=0, column=0, sticky="w", padx=(0, 6))  # label for the frequency list
        self.frequency = ttk.Combobox(tuning, state="readonly", width=84, font=("Consolas", 9))  # the frequency drop-down list
        self.frequency.grid(row=0, column=1, sticky="ew")  # place it
        ttk.Button(tuning, text="Add...", command=self.add_frequency).grid(row=0, column=2, padx=(6, 0))  # add a frequency of your own
        ttk.Button(tuning, text="Remove", command=self.remove_frequency).grid(row=0, column=3)  # remove one of your own
        self.frequency.bind("<<ComboboxSelected>>", lambda event: self.tune())  # choosing a frequency tunes the radio to it
        operate = ttk.Frame(root)  # the row of operating controls
        operate.grid(row=3, column=0, sticky="w", padx=8, pady=4)  # place it
        ttk.Label(operate, text="Mode:").pack(side="left", padx=(0, 4))  # label for the mode choice
        for mode, words in (("listen", "Listen  F2"), ("monitor", "Monitor (receive only)  F3"), ("off", "Off  F4")):  # the three modes
            ttk.Radiobutton(operate, text=words, value=mode, variable=self.mode_var, command=lambda m=mode: self.set_mode(m)).pack(side="left", padx=4)  # one button each
        ttk.Separator(operate, orient="vertical").pack(side="left", fill="y", padx=10)  # a divider
        self.available_button = ttk.Checkbutton(operate, text="Available  Ctrl+U", style="Toolbutton", variable=self.available_var, command=self.available_toggled)  # pushed in = available for contacts
        self.available_button.pack(side="left", padx=(0, 8))  # place it
        self.beacon_button = ttk.Checkbutton(operate, text=self.beacon_words(), style="Toolbutton", variable=self.beacon_var, command=self.beacon_toggled)  # pushed in = repeating beacon on; pushed again = off
        self.beacon_button.pack(side="left")  # place it
        self.beacon_label = ttk.Label(operate, text="off", width=30)  # what the repeating beacon is doing
        self.beacon_label.pack(side="left", padx=6)  # place it
        ttk.Button(operate, text="Call station (To)  F6", command=self.call_to).pack(side="left", padx=4)  # call the station named in the To box
        options = ttk.Frame(root)  # the row of choices about how a contact is run
        options.grid(row=4, column=0, sticky="w", padx=8, pady=2)  # place it under the buttons
        ttk.Checkbutton(options, text="Keep contact open", variable=self.keep_open).pack(side="left", padx=4)  # hold the lock until End contact is pressed
        ttk.Button(options, text="End contact  F7", command=self.end_contact).pack(side="left", padx=(4, 16))  # close the contact properly, with identification
        ttk.Label(options, text="Once locked:").pack(side="left")  # label for the working-frequency choice
        self.working = ttk.Combobox(options, state="readonly", width=46)  # stay on the calling frequency, or move to a working frequency
        self.working.pack(side="left", padx=4)  # place it
        typing = ttk.Frame(root)  # the row for typing a message
        typing.grid(row=5, column=0, sticky="ew", padx=8, pady=4)  # place it
        typing.columnconfigure(4, weight=1)  # the message box takes the spare width
        ttk.Label(typing, text="To").grid(row=0, column=0, sticky="w", padx=(0, 6))  # label for the callsign box
        self.to = ttk.Combobox(typing, width=11)  # the callsign a message is for, or the station to call: type one, or pick a saved contact or a station heard; blank means whoever the partner is
        self.to.grid(row=0, column=1, sticky="w")  # place it
        self.to.bind("<Return>", lambda event: self.message.focus_set())  # Enter in the To box moves on to the message
        self.quick_menu = tk.Menu(root, tearoff=False)  # the quick messages
        quick = ttk.Menubutton(typing, text="Quick", menu=self.quick_menu)  # the button that opens them
        quick.grid(row=0, column=2, padx=(8, 0))  # place it
        ttk.Label(typing, text="Message").grid(row=0, column=3, sticky="w", padx=(10, 6))  # label for the message box
        self.message = ttk.Entry(typing)  # the message box
        self.message.grid(row=0, column=4, sticky="ew")  # place it
        self.message.bind("<Return>", lambda event: self.queue_message())  # the Enter key queues the message
        ttk.Button(typing, text="Queue message", command=self.queue_message).grid(row=0, column=5, padx=(6, 0))  # add the message to the list to send
        ttk.Button(typing, text="Broadcast to ALL  F11", command=self.broadcast_message).grid(row=0, column=6, padx=(4, 0))  # send the message to every station listening, with no acknowledgment
        lists = ttk.Frame(root)  # the three lists, side by side
        lists.grid(row=6, column=0, sticky="nsew", padx=8, pady=4)  # place them
        for column in range(3):  # the three lists share the width
            lists.columnconfigure(column, weight=1)  # equally
        self.to_send = self._list(lists, 0, "Messages to send", (("time", "Queued", 64), ("to", "To", 70), ("text", "Message", 190), ("state", "State", 110)))  # outgoing messages, who each is for, and how far it has got
        self.received = self._list(lists, 1, "Messages received", (("time", "Time", 64), ("who", "From", 110), ("text", "Message", 230)))  # incoming messages and broadcasts
        self.stations = self._list(lists, 2, "Stations heard and saved contacts", (("saved", "*", 22), ("who", "Callsign", 84), ("grid", "Grid", 50), ("snr", "Signal", 58), ("time", "Last heard", 68), ("text", "Sending", 90), ("mail", "Status and messages", 170)))  # every callsign heard on the frequency, plus the operator's saved contacts (marked *); stations beaconing now are highlighted
        keep = ttk.Frame(self.stations.master)  # buttons under that list
        keep.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))  # place them
        ttk.Button(keep, text="Respond  Ctrl+Y", command=self.respond).pack(side="left", padx=(0, 8))  # call the selected station by name (answer its beacon by hand)
        ttk.Button(keep, text="Save as contact", command=self.save_contact).pack(side="left")  # keep the selected callsign for later
        ttk.Button(keep, text="Remove contact", command=self.remove_contact).pack(side="left", padx=4)  # forget it again
        ttk.Button(keep, text="Last 48 hours  F8", command=self.heard_window).pack(side="left", padx=4)  # the longer record
        self.stations.bind("<Double-1>", lambda event: self.pick_station())  # a double-click chooses the callsign for the next message or call
        self.stations.bind("<Return>", lambda event: self.pick_station())  # so does Enter
        for call in sorted(self.contacts):  # the saved contacts are listed from the start
            self.heard_rows[call] = self.stations.insert("", "end", values=("*", call, self.contacts[call].get("grid", ""), "", "", "saved contact"))  # one row each
        self.refresh_to()  # offer them in the To box
        for item in read_json(side_file("_outbox.json"), []):  # messages left waiting when the panel was last closed
            self.to_send.insert("", "end", values=(item.get("time", ""), item.get("to") or "partner", item.get("text", ""), "waiting"))  # back in the list
            self.outbox.append((item.get("text", ""), item.get("to", "")))  # and back in the queue for the next contact
        bottom = ttk.Frame(root)  # the bottom strip: the log on the left, the scope and the level meters on the right
        bottom.grid(row=7, column=0, sticky="nsew", padx=8, pady=(4, 8))  # place it at the bottom
        bottom.columnconfigure(0, weight=1)  # the log takes the spare width
        bottom.rowconfigure(0, weight=1)  # and the spare height
        activity = ttk.LabelFrame(bottom, text="Activity")  # the running log, in its own box
        activity.grid(row=0, column=0, sticky="nsew", padx=(0, 4))  # place it on the left
        activity.columnconfigure(0, weight=1)  # the log takes the width
        activity.rowconfigure(1, weight=1)  # and the spare height
        ttk.Checkbutton(activity, text="Show technical details", variable=self.details, command=self.redraw_log).grid(row=0, column=0, sticky="w", padx=4)  # the switch between the plain and the detailed log
        self.log = tk.Text(activity, height=14, width=70, font=("Consolas", 9), state="disabled", relief="flat", borderwidth=0)  # the running log
        self.log.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)  # place it
        scroll = ttk.Scrollbar(activity, orient="vertical", command=self.log.yview)  # a scroll bar for the log
        scroll.grid(row=1, column=1, sticky="ns")  # place it beside the log
        self.log.configure(yscrollcommand=scroll.set)  # tie the two together
        self._scope(bottom)  # build the scope
        self._meters(bottom)  # build the level meters and sliders
        root.rowconfigure(7, weight=1)  # the log stretches with the window
        self.refresh_frequencies(self.settings["frequency"])  # fill the frequency list
        self.refresh_quick()  # fill the quick-message menu
        self.show_me()  # show this station's callsign and grid
        self.colour_plain_widgets()  # colour the widgets the theme does not reach
        self._shortcuts()  # the keyboard shortcuts
        for event in ("<KeyPress>", "<ButtonPress>", "<MouseWheel>", "<Motion>"):  # anything the operator does in the window...
            root.bind_all(event, self.touched, add="+")  # ...counts as being at the station
        root.protocol("WM_DELETE_WINDOW", self.close)  # save and stop cleanly when the window is closed
        root.after(100, self.show_lines)  # start passing log lines to the window
        root.after(500, self.follow_station)  # start keeping the lists and readings up to date
        root.after(150, self.draw_scope)  # start drawing the scope
        root.after(200, self.draw_meters)  # start drawing the level meters
        root.after(300, lambda: theme.colour_window(root, self.colours))  # the title bar again, now the window is on screen
        root.after(700, self.autostart)  # start listening, once the window is up

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
        file_menu.add_command(label="Signal log report...", underline=7, command=self.signal_log_report)  # summarise the signal logs into a text file
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
        operate.add_checkbutton(label="Keep contact open", underline=0, variable=self.keep_open)  # hold the lock until End contact
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
        messages.add_separator()  # a divider
        for number in (1, 2, 3):  # the three quick messages
            messages.add_command(label=f"Quick message {number}", underline=14, accelerator=f"Ctrl+{number}", command=lambda n=number: self.use_quick(n))  # put it in the Message box
        messages.add_separator()  # a divider
        messages.add_command(label="Send telemetry to the station in To", underline=0, accelerator="Ctrl+4", command=self.send_telemetry)  # what this station hears, to one station
        messages.add_command(label="Broadcast telemetry to ALL", underline=10, accelerator="Ctrl+5", command=self.broadcast_telemetry)  # to everyone
        bar.add_cascade(label="Messages", underline=0, menu=messages)  # put the menu on the bar
        stations = tk.Menu(bar, tearoff=False)  # the Stations menu
        stations.add_command(label="Respond to the selected station (call it)", underline=0, accelerator="Ctrl+Y", command=self.respond)  # answer a beacon by hand
        stations.add_command(label="Stations heard (last 48 hours)...", underline=0, accelerator="F8", command=self.heard_window)  # the longer record
        stations.add_command(label="Telemetry received...", underline=0, accelerator="F9", command=self.telemetry_window)  # what other stations hear
        stations.add_separator()  # a divider
        stations.add_command(label="Go to the stations list", underline=6, accelerator="Ctrl+G", command=self.focus_stations)  # the list on the main window
        stations.add_command(label="Put the selected callsign in To", underline=0, accelerator="Enter", command=self.pick_station)  # use it
        stations.add_command(label="Save the selected station as a contact", underline=0, command=self.save_contact)  # keep it
        stations.add_command(label="Remove the selected contact", underline=0, command=self.remove_contact)  # forget it
        bar.add_cascade(label="Stations", underline=0, menu=stations)  # put the menu on the bar
        view = tk.Menu(bar, tearoff=False)  # the View menu
        looks = tk.Menu(view, tearoff=False)  # the Theme submenu
        for choice in theme.CHOICES:  # system, light, dark
            looks.add_radiobutton(label=THEME_NAMES[choice], underline=0, value=choice, variable=self.theme_var, command=lambda c=choice: self.set_theme(c))  # one each
        view.add_cascade(label="Theme", underline=0, menu=looks)  # put it in the View menu
        view.add_checkbutton(label="Technical details in the log", underline=0, variable=self.details, command=self.redraw_log)  # plain or detailed log
        view.add_command(label="Go to the level sliders", underline=6, accelerator="Ctrl+J", command=lambda: self.rx_slider.focus_set())  # the receive and transmit levels
        bar.add_cascade(label="View", underline=0, menu=view)  # put the menu on the bar
        settings = tk.Menu(bar, tearoff=False)  # the Settings menu
        for tab, words, key in ((0, "Station...", 0), (1, "Radio and rig control...", 0), (2, "Audio...", 0), (3, "Operating (start-up, beacon)...", 0), (4, "Logging...", 0), (5, "Quick messages...", 0), (6, "Appearance...", 1)):  # one item per tab of the Settings window
            settings.add_command(label=words, underline=key, accelerator="F12" if tab == 0 else "", command=lambda t=tab: self.settings_window(t))  # open Settings at that tab
        bar.add_cascade(label="Settings", underline=0, menu=settings)  # put the menu on the bar
        help_menu = tk.Menu(bar, tearoff=False)  # the Help menu
        help_menu.add_command(label="Keyboard shortcuts", underline=0, accelerator="F1", command=self.shortcuts_window)  # every key
        help_menu.add_command(label="About Kestrel", underline=0, command=lambda: messagebox.showinfo("About Kestrel", about_text(), parent=self.root))  # what this is, which version, and who began it
        bar.add_cascade(label="Help", underline=0, menu=help_menu)  # put the menu on the bar
        self.root.configure(menu=bar)  # give the window its menu bar

    def _shortcuts(self):  # tie the keys to their jobs
        keys = {"<F1>": self.shortcuts_window, "<F2>": lambda: self.set_mode("listen"), "<F3>": lambda: self.set_mode("monitor"), "<F4>": lambda: self.set_mode("off"),  # (continued)
                "<F5>": self.beacon_key, "<F6>": self.call_to, "<F7>": self.end_contact, "<F8>": self.heard_window, "<F9>": self.telemetry_window,  # (continued)
                "<F11>": self.broadcast_message, "<F12>": lambda: self.settings_window(0), "<Control-l>": lambda: self.to.focus_set(), "<Control-m>": lambda: self.message.focus_set(),  # (continued)
                "<Control-Key-1>": lambda: self.use_quick(1), "<Control-Key-2>": lambda: self.use_quick(2), "<Control-Key-3>": lambda: self.use_quick(3),  # (continued)
                "<Control-Key-4>": self.send_telemetry, "<Control-Key-5>": self.broadcast_telemetry, "<Control-r>": lambda: self.frequency.focus_set(),  # (continued)
                "<Control-Up>": lambda: self.step_frequency(-1), "<Control-Down>": lambda: self.step_frequency(1), "<Control-g>": self.focus_stations, "<Control-j>": lambda: self.rx_slider.focus_set(), "<Control-y>": self.respond, "<Control-u>": self.available_key}  # every shortcut
        for key, job in keys.items():  # each one
            self.root.bind(key, lambda event, j=job: (j(), "break")[1])  # on the main window: do the job, and stop the key going any further

    def _list(self, parent, column, title, columns):  # a titled list with named columns
        frame = ttk.LabelFrame(parent, text=title)  # the box around the list
        frame.grid(row=0, column=column, sticky="nsew", padx=2)  # place it
        frame.columnconfigure(0, weight=1)  # the list takes the width
        table = ttk.Treeview(frame, columns=[name for name, _, _ in columns], show="headings", height=5)  # the list itself, five rows tall
        for name, heading, width in columns:  # each column
            table.heading(name, text=heading, anchor="w")  # its heading
            table.column(name, width=width, anchor="w", stretch=(name in ("text", "mail")))  # its width; only the message columns stretch
        table.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)  # place the list
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)  # a scroll bar for it
        scroll.grid(row=0, column=1, sticky="ns")  # place it beside the list
        table.configure(yscrollcommand=scroll.set)  # tie the two together
        return table  # so rows can be added later

    # ---- the scope ----

    def _scope(self, parent):  # the scope: a spectrum trace above a waterfall of the receive audio, with scales
        self.scope_w, self.trace_h, self.fall_h, self.top_hz = 512, 90, 150, 3000.0  # width in points, heights of the trace and the waterfall, and the highest frequency shown
        self.left, self.right, self.above, self.below = 40, 40, 16, 18  # margins for the scales: dB on the left, seconds on the right, radio kHz above, audio Hz below
        steps = np.linspace(0.0, 1.0, 256)  # the 256 brightness steps of the waterfall
        self.palette = np.stack([np.interp(steps, [0, 0.35, 0.7, 1.0], channel) for channel in ([0, 0, 255, 255], [0, 40, 255, 60], [40, 200, 0, 0])], axis=1).astype("uint8")  # their colours: black, blue, yellow, red
        self.fall = np.zeros((self.fall_h, self.scope_w, 3), dtype="uint8")  # the waterfall picture, newest line at the top
        self.line_s = 0.15  # seconds between waterfall lines, measured as the scope runs
        self.last_line = None  # when the last waterfall line was drawn
        self.scale_khz = None  # the radio frequency the top scale was last drawn for
        frame = ttk.LabelFrame(parent, text="Scope  -  receive audio")  # the box around the scope
        frame.grid(row=0, column=1, sticky="ns", padx=(0, 4))  # place it beside the log
        width, height = self.left + self.scope_w + self.right, self.above + self.trace_h + self.fall_h + self.below  # the drawing area's size
        self.scope = tk.Canvas(frame, width=width, height=height, bg="#0b0e12", highlightthickness=0)  # the drawing area
        self.scope.grid(row=0, column=0, padx=4, pady=(4, 0))  # place it
        self.fall_image = tk.PhotoImage(width=self.scope_w, height=self.fall_h)  # the waterfall as a picture
        self.fall_item = self.scope.create_image(self.left, self.above + self.trace_h, anchor="nw", image=self.fall_image)  # shown under the trace
        grey, faint, font = "#a8b0ba", "#3a414a", ("Segoe UI", 7)  # scale colours and lettering
        for hz in range(0, 3001, 500):  # a mark every 500 Hz
            x = self.x_for(hz)  # where it falls across the display
            edge = hz in (500, 2500)  # the two edges of the Kestrel band
            self.scope.create_line(x, self.above, x, self.above + self.trace_h + self.fall_h, fill="#e0e0e0" if edge else faint, dash=(4, 3) if edge else (1, 4))  # a dashed line for an edge, a faint dotted one otherwise
            self.scope.create_text(x, height - self.below / 2, text=str(hz), fill=grey, font=font)  # its audio frequency underneath
        self.scope.create_text(self.left + self.scope_w + self.right / 2, height - self.below / 2, text="Hz", fill=grey, font=font)  # the unit of the bottom scale
        for db in (0, 25, 50):  # marks up the trace, in dB above the noise
            y = self.y_for(db)  # where it falls
            self.scope.create_line(self.left, y, self.left + self.scope_w, y, fill=faint, dash=(1, 4))  # a faint line across
            self.scope.create_text(self.left - 4, y, text=f"{db:+d}" if db else "noise", anchor="e", fill=grey, font=font)  # its value
        self.scope.create_text(self.left / 2, self.above / 2, text="dB", fill=grey, font=font)  # the unit of the left scale, in the top corner
        self.trace = self.scope.create_line(self.left, self.y_for(0), self.left + self.scope_w, self.y_for(0), fill="#7cfc00")  # the spectrum trace, flat until there is audio
        legend = ("Across: audio frequency in Hz (below) and the radio frequency each point is on, in kHz (above).\n"  # what the axes are
                  "Trace: signal strength above the noise, in dB.  Waterfall: the last few seconds, newest at the top.\n"  # what the two parts show
                  "Dashed lines: the Kestrel band, 500 to 2500 Hz.  Labels: stations decoded in the last minute.")  # the marks
        ttk.Label(frame, text=legend, font=("Segoe UI", 8), justify="left").grid(row=1, column=0, sticky="w", padx=4, pady=(2, 4))  # the key

    def x_for(self, hz):  # where an audio frequency falls across the scope
        return self.left + hz / self.top_hz * (self.scope_w - 1)  # left margin plus the share of the width

    def y_for(self, db):  # where a level above the noise falls on the trace
        return self.above + self.trace_h - 3 - (db + 5.0) / 55.0 * (self.trace_h - 8)  # from 5 dB under the noise at the bottom to 50 dB above it at the top

    def dial_hz(self):  # where the radio is tuned now (safe to call from any thread)
        """Return the radio's dial frequency in hertz: the chosen calling frequency, moved to a working frequency if the contact has moved."""
        station = self.station  # the running station, if any
        return self.base_khz * 1000.0 + (station.offset_hz if station is not None else 0)  # the calling frequency plus any move

    def draw_scope(self):  # redraw the scope from the newest audio
        source = self.audio  # the sound-card input, if one is open
        try:  # a hiccup in drawing must never stop the station
            dial = self.dial_hz() / 1000.0  # the radio's frequency in kHz
            if dial != self.scale_khz:  # the radio has moved since the top scale was drawn
                self.scale_khz = dial  # remember where it is now
                self.scope.delete("rf")  # remove the old labels
                for hz in (500, 1500, 2500):  # three points across
                    self.scope.create_text(self.x_for(hz), self.above / 2, text=f"{dial + hz / 1000.0:,.1f}", fill="#a8b0ba", font=("Segoe UI", 7), tags="rf")  # the radio frequency there (upper sideband: dial plus audio)
                self.scope.create_text(self.left + self.scope_w + self.right / 2, self.above / 2, text="kHz", fill="#a8b0ba", font=("Segoe UI", 7), tags="rf")  # the unit
            if source is not None:  # there is audio to show
                now = time.monotonic()  # the time of this line
                if self.last_line is not None:  # not the first line
                    self.line_s = 0.9 * self.line_s + 0.1 * (now - self.last_line)  # keep a running average of the time between lines
                self.last_line = now  # remember it
                levels = source.spectrum(self.top_hz, self.scope_w)  # the spectrum of the last sixth of a second, in decibels
                floor = float(np.median(levels))  # the noise level, taken as the middle value
                bright = np.clip((levels - (floor - 5.0)) / 55.0, 0.0, 1.0)  # each point on a scale from 5 dB under the noise to 50 dB above it
                points = np.column_stack((self.left + np.arange(self.scope_w), self.above + self.trace_h - 3 - bright * (self.trace_h - 8))).ravel().tolist()  # the trace's corners
                self.scope.coords(self.trace, *points)  # move the trace
                self.fall = np.roll(self.fall, 1, axis=0)  # push the waterfall down one line
                self.fall[0] = self.palette[(bright * 255).astype(int)]  # and paint the newest line at the top
                self.fall_image = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.scope_w, self.fall_h) + self.fall.tobytes(), format="PPM")  # the picture, rebuilt
                self.scope.itemconfigure(self.fall_item, image=self.fall_image)  # show it
            self.scope.delete("time")  # the seconds scale is redrawn each time, since the line rate is measured
            x = self.left + self.scope_w + 4  # just right of the waterfall
            for seconds in (0, 10, 20, 30, 40):  # a mark every ten seconds
                y = self.above + self.trace_h + seconds / max(self.line_s, 0.05)  # how far down that is
                if y <= self.above + self.trace_h + self.fall_h:  # it is on the waterfall
                    self.scope.create_text(x, y, text=f"{seconds} s" if seconds else "now", anchor="w", fill="#a8b0ba", font=("Segoe UI", 7), tags="time")  # label it
            self.scope.delete("mark")  # the station labels are redrawn each time
            now = time.monotonic()  # for their age
            for call, (hz, width, when) in list(self.marks.items()):  # each station decoded recently
                if now - when > 60.0:  # more than a minute ago
                    del self.marks[call]  # forget it
                    continue  # and move on
                low, high = self.x_for(max(0.0, hz - width / 2)), self.x_for(min(self.top_hz, hz + width / 2))  # the signal's edges
                self.scope.create_line(low, self.above + 14, low, self.above + 18, high, self.above + 18, high, self.above + 14, fill="#ffd166", tags="mark")  # a bracket over the signal
                self.scope.create_text((low + high) / 2, self.above + 8, text=call, fill="#ffd166", font=("Segoe UI", 8, "bold"), tags="mark")  # with the callsign above it
        except Exception:  # anything at all
            pass  # try again next time
        self.root.after(150, self.draw_scope)  # about seven times a second

    # ---- the level meters ----

    def _meters(self, parent):  # the receive and transmit level meters, each with its slider
        frame = ttk.LabelFrame(parent, text="Levels")  # the box around them
        frame.grid(row=0, column=2, sticky="ns")  # place it on the right
        self.meter_h, self.meter_w = 220, 30  # the size of each meter
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
        self.rx_text = ttk.Label(frame, text="", font=("Segoe UI", 8), justify="center", width=14, anchor="center")  # the receive readings in words
        self.rx_text.grid(row=2, column=0, columnspan=2, pady=(2, 0))  # under the receive meter
        self.tx_text = ttk.Label(frame, text="", font=("Segoe UI", 8), justify="center", width=14, anchor="center")  # the transmit readings in words
        self.tx_text.grid(row=2, column=2, columnspan=2, pady=(2, 0))  # under the transmit meter
        ttk.Label(frame, text="Aim for the green band.\nRed or CLIP: lower the\nradio's USB audio output.", font=("Segoe UI", 8), justify="center").grid(row=3, column=0, columnspan=4, pady=(4, 4))  # how to use them
        self.find_rx_level()  # find Windows' level control for the receive device

    def _meter(self, frame, column, title):  # one vertical meter, scaled -60 to 0 dBFS
        ttk.Label(frame, text=title, font=("Segoe UI", 8), justify="center").grid(row=0, column=column, columnspan=2, pady=(2, 2))  # its title
        canvas = tk.Canvas(frame, width=self.meter_w + 28, height=self.meter_h, bg="#0b0e12", highlightthickness=0)  # the drawing area: the bar plus room for the scale
        canvas.grid(row=1, column=column, padx=(6, 2))  # place it
        x0, x1 = 26, 26 + self.meter_w  # the bar's left and right edges
        for low, high, colour in ((-60, -30, "#20303a"), (-30, -15, "#16452a"), (-15, -6, "#4a4416"), (-6, 0, "#4a1c1c")):  # the zones: too low, aim here, getting loud, too loud
            canvas.create_rectangle(x0, self.meter_y(high), x1, self.meter_y(low), fill=colour, outline="")  # each zone, dimly
        canvas.create_rectangle(x0, self.meter_y(-15), x1, self.meter_y(-30), outline="#3fbf6f", width=1)  # the target band outlined
        for db in (0, -6, -15, -30, -45, -60):  # the scale
            canvas.create_line(x0 - 4, self.meter_y(db), x0, self.meter_y(db), fill="#a8b0ba")  # a tick
            canvas.create_text(x0 - 6, self.meter_y(db), text=str(db), anchor="e", fill="#a8b0ba", font=("Segoe UI", 7))  # its value in dBFS
        canvas.create_rectangle(x0 + 3, self.meter_y(-60), x1 - 3, self.meter_y(-60), fill="#3fbf6f", outline="", tags="bar")  # the level bar, empty to begin with
        canvas.create_line(x0, self.meter_y(-60), x1, self.meter_y(-60), fill="#ffffff", width=2, tags="peak")  # the peak mark
        canvas.create_text((x0 + x1) / 2, 8, text="", fill="#ff5555", font=("Segoe UI", 7, "bold"), tags="clip")  # CLIP, when the input is overdriven
        return canvas  # for drawing on

    def meter_y(self, db):  # where a level falls on a meter
        return 4 + (min(0.0, max(-60.0, db)) / -60.0) * (self.meter_h - 8)  # 0 dBFS at the top, -60 at the bottom

    def show_level(self, canvas, rms_db, peak_db, dim=False, clip=False):  # move one meter's bar and peak mark
        colour = "#3fbf6f" if rms_db < -15 else ("#e0c040" if rms_db < -6 else "#e05050")  # green while in or under the target band, yellow when getting loud, red when too loud
        if rms_db < -45:  # hardly any signal
            colour = "#5a7a8a"  # grey-blue: too low to be useful
        if dim:  # a setting, not a live reading
            colour = "#4a5560"  # shown dimly
        canvas.coords("bar", 29, self.meter_y(rms_db), 26 + self.meter_w - 3, self.meter_y(-60))  # the bar, from the bottom up to the RMS level
        canvas.itemconfigure("bar", fill=colour)  # in its colour
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
            self.rx_slider.state(["disabled"])  # the slider does nothing, so it is greyed out

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

    def colour_plain_widgets(self):  # colour the widgets the theme cannot reach
        c = self.colours  # the palette
        theme.colour_window(self.root, c)  # the window's background and title bar
        self.plain_colour = c["bg"]  # the status band's ordinary background
        self.log.configure(background=c["text_bg"], foreground=c["text_fg"], insertbackground=c["text_fg"])  # the log
        self.status.configure(background=c["bg"], foreground=c["fg"])  # the status band, until a state colours it
        self.stations.tag_configure("calling", background="#5a4a12" if c["name"] == "dark" else "#fff0a8")  # stations beaconing now: amber in the dark look, pale yellow in the light
        self.quick_menu.configure(background=c["panel"], foreground=c["fg"], activebackground=c["select"], activeforeground=c["select_fg"])  # the quick-message menu (a pop-up, which Windows lets the program colour)
        theme.recolour_comboboxes(self.root, c)  # the open lists of the drop-downs
        for window in self.windows.values():  # any extra windows that are open
            if window.winfo_exists():  # still open
                theme.colour_window(window, c)  # colour them too

    def set_theme(self, choice):  # View > Theme
        self.settings["theme"] = choice  # remember the choice
        self.theme_var.set(choice)  # tick it in the menu
        self.colours = theme.apply(self.root, choice)  # restyle every themed widget
        self.colour_plain_widgets()  # and the rest
        self.show_status(self.status.cget("text"), "plain")  # redraw the status band in the new colours
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
        theme.colour_window(top, self.colours)  # in the chosen look
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

    def show_status(self, words, colour):  # put the station's state on the band at the top
        """Show `words`; a lock is a solid green band, trouble holding it amber or red, anything else plain."""
        if colour == "dark green":  # locked with a partner
            self.status.configure(text=words, bg="#1b7f3b", fg="white")  # white on solid green: unmistakable
        elif colour in ("dark orange", "red"):  # the link is in trouble, or something failed
            self.status.configure(text=words, bg="#c0392b" if colour == "red" else "#d98200", fg="white")  # white on red or amber
        else:  # every other state
            self.status.configure(text=words, bg=self.plain_colour, fg=self.colours["accent"] if colour == "dark blue" else self.colours["fg"])  # coloured words on the ordinary background

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
            if "returning to the calling frequency in one minute" in line:  # this station moved the contact and the working frequency has gone idle
                self.show_notice("No messages have passed for two minutes on the working frequency.\n\nIn one minute this contact will be closed and both stations will return to the calling frequency.\n\nSend a message to keep the contact here.")  # warn the operator
            elif self.notice is not None and any(mark in line for mark in ("sending message", "received message", "back on the calling frequency", "contact closed")):  # traffic has resumed, or the return has happened
                self.close_notice()  # the warning no longer applies
            state = status_for(line)  # does it mark a change of state?
            if state is not None and state[0].startswith("LISTENING") and time.monotonic() < getattr(self, "hold_status", 0.0):  # back to listening just after news the operator should see
                pass  # leave the news on the band for a while
            elif state is not None and not (state[0] == "STOPPED" and self.next_mode is not None):  # yes (but a stop on the way to another mode is not worth showing)
                self.show_status(state[0], state[1])  # show the new state in its colour
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
        self.root.after(100, self.show_lines)  # look again in a tenth of a second

    # ---- what the working thread reports ----

    def power_w(self):  # the transmit power to put in the log
        """Return the power in watts: measured while transmitting if the radio says, else the radio's power setting, else None."""
        if self.tx_active and self.meters["watts"] is not None:  # measured now
            return self.meters["watts"]  # use it
        return self.meters["set_w"]  # the setting, or None if unknown

    def rig_name(self):  # the radio, for the log
        return self.settings["rig_text"] or (self.settings["rig_model"].split("  ", 1)[-1] if self.settings["rig_model"] else "")  # the operator's description, else the rig type

    def note_heard(self, result):  # a frame from some station decoded (called from the working thread)
        call = (result.fields or {}).get("origin") or (result.origin if result.frame_type == 1 else "")  # the callsign it carries: in a beacon, an answer, an identification or a fully addressed message
        station = self.station  # the running station, if any
        if not call and station is not None and result.link == station.link and station.partner:  # a frame inside the present contact carries only the link number
            call = station.partner  # it is from the partner
        if not call:  # it names nobody
            return  # nothing to note
        grid = (result.fields or {}).get("grid", "")  # its grid locator, if it carries one
        kind = KIND.get(result.frame_type, "frame")  # what it was
        self.heard.put((call, grid, result.snr_db, kind, dict(result.fields or {})))  # pass it to the window, with the frame's flags
        self.heardlog.add(call, grid, result.snr_db, result.level, kind, round(self.dial_hz() / 1000.0, 1))  # into the 48-hour log
        self.marks[call] = (1500.0 + result.offset_hz, signal_width_hz(result.level), time.monotonic())  # and onto the scope
        self.logbook.write("heard", direction="RX", station=self.settings["call"], **{"from": call}, text=kind, dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(result.level), snr_db=result.snr_db, fade=result.fade_index, offset_hz=result.offset_hz, rig=self.rig_name())  # the logbook, from the advanced level up

    def log_frame(self, result):  # every report from the receiver (called from the working thread), for the verbose log
        if not self.logbook.wants("frame"):  # not logging at that level
            return  # nothing to do
        name = KIND.get(result.frame_type, "frame")  # the kind of frame
        rx = self.audio.level()[0] if self.audio is not None else None  # the input level
        self.logbook.write("frame", direction="RX", station=self.settings["call"], text=f"{name} {'decoded' if result.ok else 'failed: ' + str(result.reason)}", dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(result.level), snr_db=result.snr_db, fade=result.fade_index, offset_hz=result.offset_hz, rig=self.rig_name(), rx_input_dbfs=rx, detail=describe(result))  # every detail

    def note_near(self, result):  # a Kestrel signature heard but not readable (called from the working thread)
        self.logbook.write("heard", direction="RX", station=self.settings["call"], text="signature heard, too weak or faded to read", dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=f"{level_name(result.seen_level)}?", offset_hz=result.offset_hz, rig=self.rig_name(), detail=near_line(result))  # the logbook, from the advanced level up

    def signal_folder(self):  # where the signal log goes
        """Return (creating it if needed) the signal log folder, beside the logbook."""
        folder = os.path.join(LOG_FOLDER, "signal")  # beside the CSV logs
        os.makedirs(folder, exist_ok=True)  # make sure it exists
        return folder  # the folder

    def signal_log_report(self):  # File > Signal log report
        """Summarise the signal logs (all of them, or from a date the operator gives) into a text file beside them, and open it."""
        from tkinter import simpledialog  # a one-line question
        since = simpledialog.askstring("Kestrel - signal log report", "Report from which UTC date? (YYYY-MM-DD; leave blank for everything)", parent=self.root)  # the start date
        if since is None:  # cancelled
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
        self.tx_active, self.tx_kind = keyed, tx.kind if keyed else ""  # note it, for the meters
        if keyed:  # a new transmission
            self.alc_warned = False  # it may be warned about once
        if not keyed:  # it has just gone off
            self.logbook.write("meters", direction="TX", station=self.settings["call"], text=f"after {tx.kind}", power_w=self.meters["watts"], alc=self.meters["alc"], swr=self.meters["swr"], tx_audio=round(self.sink.last_peak_db, 1) if self.sink else None)  # the meter readings taken during it (verbose)
            return  # nothing more
        event = {"beacon": "beacon", "long beacon": "beacon", "call": "call", "broadcast": "broadcast"}.get(tx.kind, "sent")  # beacons, calls and broadcasts are logged from advanced up; other frames only in verbose
        station = self.station  # the running station
        to = "ALL" if tx.kind in ("beacon", "long beacon", "broadcast") else (station.partner if station is not None else "")  # who it was for
        self.logbook.write(event, direction="TX", station=self.settings["call"], **{"from": self.settings["call"]}, to=to, text=f"{tx.kind} {tx.note}".strip(), dial_khz=round(self.dial_hz() / 1000.0, 1),  # (continued)
                           level=level_name(tx.level), rig=self.rig_name(), power_w=self.power_w(), tx_audio=round(20.0 * np.log10(max(float(self.settings["gain"] or 0.25), 1e-4)), 1))  # what went out

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
        while not self.heard.empty():  # every station heard since the last look
            call, grid, snr, kind, fields = self.heard.get()  # who, where, how strong, what it sent, and its flags
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
            values = ("*" if call in self.contacts else "", call, grid or (self.stations.set(self.heard_rows[call], "grid") if call in self.heard_rows else ""), f"{snr:+.0f} dB", time.strftime("%H:%M:%S"), kind)  # the row's contents (a grid learned earlier is kept)
            if call in self.heard_rows:  # already listed
                self.stations.item(self.heard_rows[call], values=values)  # bring its row up to date
                self.stations.move(self.heard_rows[call], "", 0)  # and move it to the top: most recently heard first
            else:  # a new callsign
                self.heard_rows[call] = self.stations.insert("", 0, values=values)  # add it at the top
                self.refresh_to()  # and offer it in the To box
        station = self.tracked  # the station being followed, running or just finished
        if station is not None and station.unavailable_from:  # a station we called says its operator is away
            self.availability[station.unavailable_from] = (False, time.time())  # note it
            station.unavailable_from = ""  # once
        if station is not None:  # there is one
            self.follow_contact(station)  # the logbook's view of the contact
            while self.marked < len(station.delivered):  # a message has been delivered since the last look
                text = station.delivered[self.marked]  # which one
                self._advance(text, "delivered " + time.strftime("%H:%M"))  # mark its row
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
                self.received.insert("", "end", values=(time.strftime("%H:%M:%S"), f"{origin} to {dest}", text))  # add it to the received list
                self.received.yview_moveto(1.0)  # keep the newest row in view
                self.logbook.write("broadcast" if dest == "ALL" else "message", direction="RX", station=self.settings["call"], **{"from": origin}, to=dest, text=text, dial_khz=round(self.dial_hz() / 1000.0, 1))  # the logbook
                self.note_telemetry(origin, text)  # it may be telemetry
                self.shown_b += 1  # one more shown
            while self.shown < len(station.inbox):  # a message has arrived since the last look
                text = station.inbox[self.shown]  # the message
                self.received.insert("", "end", values=(time.strftime("%H:%M:%S"), station.partner, text))  # add it to the received list
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
                    snr, fade = station.history[-1]  # the newest reading of the partner's signal
                    heard = f"partner heard at {snr:+.0f} dB, {'steady' if fade <= 0.15 else 'fading'} ({fade:.2f})"  # strength, and whether it is fading
                self.readings.configure(text=f"Link:  {heard}     |     you send at L{station.tx_level}     |     partner sends at L{station.want}     |     to send: {len(station.outbox)}     received: {len(station.inbox)}")  # the link at a glance
            else:  # not in a contact
                self.readings.configure(text="")  # nothing to report
        self.follow_beacon()  # the repeating beacon's label, and its automatic stop
        self.follow_calling()  # age the Stations calling window
        self.root.after(500, self.follow_station)  # look again in half a second

    def follow_contact(self, station):  # notice a contact starting and ending, for the logbook
        running = self.station is station  # the station is still on the air
        in_contact = running and station.state in LOCKED and bool(station.partner)  # a contact is under way
        if in_contact and (self.contact is None or self.contact["call"] != station.partner):  # a new contact
            if self.contact is not None:  # the previous one ended unseen
                self.finish_contact()  # log it
            grid = self.contacts.get(station.partner, {}).get("grid", "") or (self.stations.set(self.heard_rows[station.partner], "grid") if station.partner in self.heard_rows else "")  # its grid locator, if known
            self.contact = {"call": station.partner, "start": time.time(), "end": time.time(), "dial_khz": self.dial_hz() / 1000.0, "grid": grid, "sent": 0, "received": 0, "best_level": 0, "snr": None}  # the contact so far
            self.logbook.write("contact start", direction="--", station=self.settings["call"], **{"from": self.settings["call"]}, to=station.partner, text=f"locked; role {station.role}", dial_khz=round(self.dial_hz() / 1000.0, 1), rig=self.rig_name(), power_w=self.power_w())  # the logbook
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
        for action in waiting:  # each cancelled call
            self.say(f"call to {action.target} cancelled")  # say so

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
            self.cancel_calls()  # so any call still waiting is cancelled
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
        return "Long beacon (reach)  F5" if self.settings.get("beacon_type") == "long" else "Beacon (call anyone)  F5"  # which kind

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
            self.say("no contact in progress")  # say so
            return  # nothing to do
        station.end()  # close once any traffic under way is finished
        self.say("ending the contact: closing identification will be sent when the current exchange is done")  # confirm

    def queue_message(self):  # add the typed message to the list to send
        text = self.message.get().strip()  # what was typed
        if text and self.queue_text(text, self.to.get().strip().upper()):  # it was accepted
            self.message.delete(0, "end")  # clear the box

    def queue_text(self, text, to):  # queue a message for a station (or for whoever the partner is)
        """Queue `text` for `to` (a callsign, or "" for the partner); return True if it was accepted."""
        if to and to == self.settings["call"].strip().upper():  # the message is addressed to this station itself
            messagebox.showinfo("Kestrel", f"{to} is this station's own callsign.\n\nPut the other station's callsign in the To box, or leave it blank to send to whoever the partner is.", parent=self.root)  # say so, and what to do
            return False  # refused
        self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), to or "partner", text, "waiting"))  # show it in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        station = self.station  # the station running at this moment, if any
        if station is not None:  # one is running
            station.queue(text, to=to or None)  # hand it the message now; it goes when the right station is the partner
            self.say(f"queued{' for ' + to if to else ''}: {text}")  # confirm
        else:  # nothing is running
            self.outbox.append((text, to))  # keep it for the next time Listen runs
            self.say(f"queued for the next contact{' with ' + to if to else ''}: {text}")  # confirm
        self.save_outbox()  # a waiting message is kept even if the panel is closed
        return True  # accepted

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
        self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), "ALL", text, "broadcast when idle"))  # show it in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        self.ask_station(lambda station: station.broadcast(text) or True, f"broadcast queued: {text}")  # the station sends it as soon as no contact is in progress
        return True  # on its way

    # ---- quick messages and telemetry ----

    def telemetry_text(self, prefix=""):  # what this station hears, as a telemetry message
        heard = telemetry.summarize(self.heardlog.snapshot(), time.time())  # the last half hour
        return telemetry.build(self.settings["grid"], self.power_w(), heard, prefix=prefix)  # the message

    def expand(self, template):  # fill in a quick message
        """Return `template` with {call}, {name}, {grid}, {rig}, {power}, {to} and {telemetry} filled in."""
        power = self.power_w()  # the transmit power, if known
        values = {"call": self.settings["call"], "name": self.settings["name"], "grid": self.settings["grid"], "rig": self.rig_name(),  # (continued)
                  "power": f"{power:.0f}" if power is not None else "?", "to": self.to.get().strip().upper(), "telemetry": ""}  # the values
        if "{telemetry}" in template:  # telemetry wanted
            values["telemetry"] = self.telemetry_text()  # built now, from the latest receptions
        try:  # the template may have a mistake in it
            text = template.format(**values)  # filled in
        except (KeyError, ValueError, IndexError):  # an unknown {name}, or a stray brace
            text = template  # sent as written
        return " ".join(text.split())[:telemetry.MAX_CHARS]  # tidy spacing, and no longer than one message

    def refresh_quick(self):  # (re)fill the quick-message menu
        self.quick_menu.delete(0, "end")  # empty it
        for number in (1, 2, 3):  # each quick message
            preview = self.settings[f"quick{number}"]  # its template
            self.quick_menu.add_command(label=f"{number}:  {preview}", underline=0, accelerator=f"Ctrl+{number}", command=lambda n=number: self.use_quick(n))  # put it in the Message box
        self.quick_menu.add_separator()  # a divider
        self.quick_menu.add_command(label="Send telemetry to the station in To", accelerator="Ctrl+4", command=self.send_telemetry)  # what this station hears
        self.quick_menu.add_command(label="Broadcast telemetry to ALL", accelerator="Ctrl+5", command=self.broadcast_telemetry)  # to everyone
        self.quick_menu.add_separator()  # a divider
        self.quick_menu.add_command(label="Change the quick messages...", command=lambda: self.settings_window(5))  # Settings, at the quick-message tab

    def use_quick(self, number):  # put a quick message in the Message box
        self.message.delete(0, "end")  # clear the box
        self.message.insert(0, self.expand(self.settings[f"quick{number}"]))  # the filled-in message
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
            if self.to_send.set(row, "state") in ("waiting", "sending"):  # not yet delivered
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
        if fields.get("holds_mail"):  # its beacon says it holds mail for others
            notes.append("it holds mail (may be for you)")  # which may be for this station
        if fields.get("mail_check"):  # it is asking for its own mail
            notes.append("it is asking for its mail")  # say so
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
            self.stations.set(row, "mail", note)  # show it

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

    def sort_table(self, tree, column):  # sort a list by one column (again to reverse)
        rows = [(tree.set(row, column), row) for row in tree.get_children("")]  # the column's values
        backwards = getattr(tree, "_sorted", None) == column  # the same column twice: reverse
        tree._sorted = None if backwards else column  # remember for next time

        def key(item):  # numbers as numbers, words as words
            text = item[0].replace(" dB", "").replace("L", "").replace("W", "").strip()  # drop units
            try:  # a number?
                return (0, float(text), "")  # sorts numerically
            except ValueError:  # words
                return (1, 0.0, item[0])  # sorts alphabetically

        for index, (_, row) in enumerate(sorted(rows, key=key, reverse=backwards)):  # in the new order
            tree.move(row, "", index)  # move each row

    def heard_window(self):  # Stations > Stations heard (last 48 hours)
        top = self.window("heard", "Kestrel - stations heard in the last 48 hours")  # the window
        every = tk.BooleanVar(value=False)  # show each reception, or one row per station
        holder = ttk.Frame(top)  # holds the list, which is rebuilt when the choice changes
        holder.pack(fill="both", expand=True)  # fill the window
        tree_box = {}  # the list now shown

        def fill():  # (re)build the list
            for child in holder.winfo_children():  # the old list
                child.destroy()  # goes
            self.heardlog.prune()  # forget anything older than 48 hours
            if every.get():  # every reception
                tree = self.table(holder, (("time", "Time (UTC)", 120), ("call", "Callsign", 90), ("grid", "Grid", 60), ("snr", "Signal", 70), ("level", "Level", 50), ("kind", "Heard sending", 120), ("khz", "Frequency kHz", 100)))  # the columns
                for record in reversed(self.heardlog.snapshot()):  # newest first
                    tree.insert("", "end", values=(utc(record["t"]), record["call"], record.get("grid", ""), f"{record['snr']:+.0f} dB", level_name(record.get("level", 0)), record.get("kind", ""), f"{record.get('dial_khz', 0):.1f}"))  # one row
            else:  # one row per station
                tree = self.table(holder, (("call", "Callsign", 90), ("grid", "Grid", 60), ("last", "Last heard (UTC)", 120), ("first", "First heard (UTC)", 120), ("count", "Times", 50), ("last_snr", "Last signal", 80), ("best_snr", "Best signal", 80), ("level", "Fastest", 60), ("khz", "Frequency kHz", 100)))  # the columns
                for row in self.heardlog.summary():  # most recent first
                    tree.insert("", "end", values=(row["call"], row["grid"], utc(row["last"]), utc(row["first"]), row["count"], f"{row['last_snr']:+.0f} dB", f"{row['best_snr']:+.0f} dB", f"L{row['best_level']}", f"{row['dial_khz']:.1f}"))  # one row
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
                grid = next((row["grid"] for row in self.heardlog.summary() if row["call"] == call), "")  # its grid, if known
                self.contacts[call] = {"grid": grid}  # remember it
                write_json(CONTACTS_FILE, self.contacts)  # save the list
                if call in self.heard_rows:  # on the main list
                    self.stations.set(self.heard_rows[call], "saved", "*")  # mark it
                else:  # not yet
                    self.heard_rows[call] = self.stations.insert("", "end", values=("*", call, grid, "", "", "saved contact"))  # add it
                self.refresh_to()  # offer it in the To box
                self.say(f"{call} saved as a contact")  # confirm

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
        self.to["values"] = sorted(self.contacts) + [call for call in self.heard_rows if call not in self.contacts]  # saved contacts first, then the other stations heard

    def pick_station(self):  # a callsign in the stations list was chosen
        for row in self.stations.selection()[:1]:  # the row chosen
            self.to.set(self.stations.set(row, "who"))  # its callsign goes into the To box
            self.message.focus_set()  # ready to type a message

    def save_contact(self):  # keep the selected callsigns as contacts
        for row in self.stations.selection():  # each selected row
            call = self.stations.set(row, "who")  # its callsign
            self.contacts[call] = {"grid": self.stations.set(row, "grid")}  # remember it, with its grid locator if known
            self.stations.set(row, "saved", "*")  # mark the row
        write_json(CONTACTS_FILE, self.contacts)  # save the list
        self.refresh_to()  # and offer them first in the To box

    def remove_contact(self):  # forget the selected contacts
        for row in self.stations.selection():  # each selected row
            self.contacts.pop(self.stations.set(row, "who"), None)  # forget it
            self.stations.set(row, "saved", "")  # unmark the row
        write_json(CONTACTS_FILE, self.contacts)  # save the list
        self.refresh_to()  # and reorder the To box

    def save_outbox(self):  # remember the messages still waiting, so they survive closing the panel
        waiting = []  # the messages not yet delivered
        for row in self.to_send.get_children():  # every row of the list
            if self.to_send.set(row, "state") in ("waiting", "sending"):  # not finished (broadcasts are not kept)
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
        program, listed, why_empty = models_for(self.settings["rigctld"])  # the rig control program (the one chosen before, else the one found on this computer), its radio list, and why the list is empty if it is
        models = [f"{number}  {name}" for number, name in listed]  # every radio type it knows, as "number  name"
        if why_empty:  # no list
            self.say(f"Settings: the rig type list is empty: {why_empty}")  # keep the reason in the log too
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

        def field(frame, row, name, label, choices=None, editable=False, width=30, names=None):  # one labelled setting
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
            ttk.Label(frame, text=words, font=("Segoe UI", 8), justify="left").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 6))  # in small letters

        station = page("Station")  # who and where
        field(station, 0, "call", "Callsign", width=14)  # callsign
        field(station, 1, "grid", "Grid locator", width=10)  # grid locator
        field(station, 2, "name", "Your name (for quick messages)", width=20)  # the operator's name
        field(station, 3, "rig_text", "Rig description (for quick messages and the log)", width=30)  # the radio and antenna, as the operator wants them described
        field(station, 4, "max_power_w", "Radio's full power, watts", width=8)  # to turn the radio's power setting into watts
        note(station, 5, "The power shown and logged is read from the radio through rig control, when the radio and Hamlib allow it.")  # where the power comes from
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
        path_box = field(radio, 6, "rigctld", "rigctld program", width=52)  # the rig control program's file
        if program and path_box.get() != program:  # the program in use is not the one shown (none was chosen, or the chosen one gave no list and another was used)
            path_box.delete(0, "end")  # clear the box
            path_box.insert(0, program)  # show the one in use
        list_note = ttk.Label(radio, text=(f"The rig type list is empty: {why_empty}." if why_empty else f"{len(models)} radio types listed."), wraplength=560, justify="left", foreground="#b00020" if why_empty else "")  # how many radios, or why none
        list_note.grid(row=8, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))  # under the settings

        def reload():  # fill the rig type list again from the program in the box
            again, reason = list_models_why(path_box.get().strip())  # ask it
            models[:] = [f"{number}  {name}" for number, name in again]  # the new list, in place (the narrowing-as-you-type rule reads the same list)
            rig_box.configure(values=[NO_RIG] + models)  # into the drop-down
            list_note.configure(text=f"The rig type list is empty: {reason}." if reason else f"{len(models)} radio types listed.", foreground="#b00020" if reason else "")  # say how it went

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
        field(operating, 5, "auto_answer", "When Listen hears a beacon or a call", names=ANSWER_NAMES, width=58)  # just listen, or answer automatically
        note(operating, 6, "Just listen: nothing is sent unless you start it. A station beaconing, or calling you by name, is highlighted in the Stations\nheard list with any messages either way; select it and press Respond (Ctrl+Y). Replies to your own beacon or call are accepted.")  # how it works
        field(operating, 1, "beacon_every_min", f"Repeating beacon: minutes between beacons ({BEACON_MIN} to {BEACON_MAX})", width=6)  # the interval
        field(operating, 2, "beacon_autostop_min", f"Stop the repeating beacon after this many minutes with\nno keyboard or mouse use ({AUTOSTOP_MIN} to {AUTOSTOP_MAX}; 0 = never)", width=6)  # the automatic stop
        field(operating, 4, "beacon_type", "Beacon type", names=BEACON_TYPE_NAMES, width=62)  # short or long
        field(operating, 5, "listen_first", "Listen before transmitting", names=LISTEN_FIRST_NAMES, width=62)  # hold back while the frequency is in use
        note(operating, 3, "The repeating beacon starts only when you press its button (F5). Each round is one beacon and its reply window;\nit pauses during a contact and the interval starts again when the contact ends. Press the button again to stop.")  # how it works
        logging = page("Logging")  # the logbook
        field(logging, 0, "log_level", "Level of detail", names=LOG_NAMES, width=56)  # basic, advanced or verbose
        note(logging, 1, f"Logs are kept in {LOG_FOLDER}:\none CSV file per UTC day (opens in a spreadsheet), and an ADIF file of completed contacts for logging programs.")  # where
        ttk.Button(logging, text="Open the log folder", command=self.open_logs).grid(row=2, column=0, sticky="w", padx=8)  # look at them
        field(logging, 3, "record_rx", "Record received audio", names=RECORD_NAMES, width=56)  # save what the receiver hears
        note(logging, 4, f"Recordings go in {recordings_dir(data_dir())}, one WAV file per hour (about 86 MB an hour, kept 7 days).\nTurn this on for on-air tests: File > Decode a recording plays a file back through the receiver and lists every\nframe and every signal that was heard but could not be read. It takes effect the next time Listen or Monitor starts.")  # what it is for
        field(logging, 5, "signal_log", "Signal log (for analysis)", names=SIGNAL_NAMES, width=56)  # the detailed signal log
        note(logging, 6, f"The signal log goes in {os.path.join(LOG_FOLDER, 'signal')}, one file per UTC day: every signal the receiver\nlooked at, every frame (SNR, fading, offset, which header copy was read), every transmission and the radio's meters.\ntools/signal_report.py summarises it. Off uses no disk space. It takes effect the next time Listen or Monitor starts.")  # what it is and what it costs
        quick = page("Quick messages")  # the quick messages
        for number in (1, 2, 3):  # each one
            field(quick, number - 1, f"quick{number}", f"Quick message {number}", width=60)  # its template
        note(quick, 3, "These fill in when used: {call} {name} {grid} {rig} {power} {to} {telemetry}\nTelemetry lists the stations heard in the last 30 minutes, strongest first, with their signal and fastest level.")  # the names that fill in
        looks = page("Appearance")  # the look
        field(looks, 0, "theme", "Theme", names=THEME_NAMES, width=30)  # system, light or dark

        def save():  # the Save button
            new = dict(self.settings)  # a copy to fill in
            for name, (box, names) in boxes.items():  # every setting
                value = box.get() if name in ("audio_in", "audio_out") else box.get().strip()  # its value (device names are kept exactly, spaces and all)
                if names is not None:  # shown in words
                    value = next((key for key, words in names.items() if words == value), self.settings[name])  # back to its short form
                new[name] = value  # keep it
            if new["rig_model"] == NO_RIG:  # no rig control wanted
                new["rig_model"] = ""  # stored as blank
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
            restart = any(new[key] != self.settings[key] for key in ("call", "grid", "audio_in", "audio_out", "rig_model", "cat_port", "cat_baud", "cat_handshake", "ptt", "port", "rigctld", "rig"))  # does the running station need to start again?
            self.settings = new  # take the new settings
            self.save_settings()  # write them to the settings file
            self.logbook.level = new["log_level"]  # the logbook's level of detail
            self.beacon_type_var.set(self.settings.get("beacon_type", "short"))  # the Beacon type menu follows the setting
            self.beacon_button.configure(text=self.beacon_words())  # and the button's label
            if self.station is not None:  # a station is listening now
                self.station.answer_beacons = self.station.answer_calls = bool(new["auto_answer"])  # the change applies at once
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
        book.select(min(max(tab, 0), 6))  # open at the tab asked for
        dialog.after(50, lambda: dialog.focus_force())  # the window has the keyboard

    def settings_summary(self):  # the settings in use, for the verbose log
        keys = ("call", "grid", "rig_model", "cat_port", "ptt", "audio_in", "audio_out", "gain", "keep_open", "working", "beacon_every_min", "beacon_type", "listen_first", "beacon_autostop_min", "auto_answer", "log_level", "record_rx", "signal_log")  # the ones that bear on a transmission
        return "; ".join(f"{key}={self.settings[key]}" for key in keys)  # as one line

    def rig_address(self, settings):  # where rig control can be reached for these settings (may be called from any thread)
        """Return a rigctld address, starting rigctld for the chosen radio if needed; "" when the radio is tuned by hand."""
        if settings["rig_model"] and settings["cat_port"]:  # a radio type and its serial port are chosen
            program = settings["rigctld"] or find_rigctld()  # the rig control program
            if not program:  # there is none
                raise RuntimeError("the rig control program (rigctld) was not found; choose it under Settings > Radio")  # say what to do
            return self.rigs.ensure(program, settings["rig_model"].split()[0], settings["cat_port"], settings["cat_baud"] or 38400, settings["cat_handshake"])  # start it if it is not already running
        return settings["rig"]  # an outside rigctld, or nothing

    def save_settings(self):  # remember the current settings
        self.settings["frequency"] = self.frequency.current()  # the frequency now selected
        self.settings["keep_open"] = bool(self.keep_open.get())  # whether contacts are kept open
        self.settings["working"] = self.working.current()  # the working-frequency choice
        write_json(SETTINGS_FILE, self.settings)  # save, readably

    # ---- frequencies ----

    def refresh_frequencies(self, select=0):  # (re)fill the frequency drop-down list
        self.entries = all_frequencies()  # the presets and the operator's own
        self.frequency["values"] = [describe_frequency(entry) for entry in self.entries]  # one line each
        self.frequency.current(min(max(select, 0), len(self.entries) - 1))  # select the wanted line
        self.base_khz = self.selected()["dial_khz"]  # the calling frequency, for the station thread and the scope
        self.refresh_working(self.settings["working"])  # and offer the working frequencies that go with it

    def refresh_working(self, select=0):  # (re)fill the working-frequency choice for the selected calling frequency
        entry = self.selected()  # the calling frequency
        choices = ["stay on the calling frequency"]  # the first choice: no move
        for offset in working_offsets_hz(entry):  # each working frequency that goes with it
            choices.append(f"move to {entry['dial_khz'] + offset / 1000.0:.1f} kHz  ({offset / 1000.0:+.1f} kHz), return at the end")  # where the pair would go
        self.working["values"] = choices  # show them
        self.working.current(select if 0 <= select < len(choices) else 0)  # the remembered choice, if it still exists

    def selected(self):  # the frequency entry now selected
        return self.entries[max(0, self.frequency.current())]  # by its position in the list

    def step_frequency(self, step):  # Ctrl+Up or Ctrl+Down: the previous or next frequency in the list
        index = self.frequency.current() + step  # the neighbour
        if 0 <= index < len(self.entries):  # inside the list
            self.frequency.current(index)  # select it
            self.tune()  # and go there

    def add_frequency(self):  # ask for a frequency of the operator's own
        dialog = self.window("add", "Add a frequency")  # a small window
        boxes = []  # the four text boxes
        for row, (label, value) in enumerate((("Band (for example 17 m)", ""), ("Dial frequency in kHz (USB)", ""), ("Radio mode", "PKTUSB"), ("Note", ""))):  # the four things asked for
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
            messagebox.showinfo("Kestrel", "Kestrel's own meeting frequencies cannot be removed.", parent=self.root)  # say so
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
                    self.say(f"set the radio by hand to {entry['dial_khz']:.1f} kHz {entry['mode']}  ({entry['band']})")  # tell the operator where to go
                    return  # nothing to send
                rig = RigCtl(address)  # connect to rigctld
                self._tune(rig, entry)  # set mode and frequency
                rig.close()  # hang up
        except (OSError, RuntimeError, ValueError) as problem:  # no connection, or the radio refused
            self.say(f"could not tune the radio: {problem}")  # say what went wrong (rig control's own message says what to check)

    def _tune(self, rig, entry):  # set the radio to a frequency entry
        rig.set_mode(entry["mode"])  # the mode first
        rig.set_frequency(entry["dial_khz"] * 1000.0)  # then the frequency
        self.say(f"radio tuned to {rig.frequency() / 1000.0:.1f} kHz {entry['mode']}  ({entry['band']})")  # confirm what the radio reports

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
        offsets = working_offsets_hz(job["entry"])  # the working frequencies that go with the calling frequency
        job["move_hz"] = offsets[self.working.current() - 1] if self.working.current() > 0 else None  # the one chosen, or none
        return job  # ready for the working thread

    def run(self, mode, job):  # the working thread: runs the monitor or the listening station
        source = rig = ptt = None  # nothing opened yet
        recorder = None  # the received-audio recorder, if turned on
        poller = None  # the radio-meter thread, once started
        self.poller_stop.clear()  # the meter thread may run
        try:  # anything that goes wrong is reported in the log
            source = AudioIn(job["in"])  # start recording from the chosen device
            self.audio = source  # let the scope and the meter show what it hears
            signal_log = self.signal_log = SignalLog(self.signal_folder(), prefix=self.logbook.name, mode=job.get("signal_log", "off"))  # the detailed signal log (writes nothing when off)
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
                log_near = attach_signal_log(listener, signal_log, lambda: round(self.dial_hz() / 1000.0, 1))  # searches and near misses to the signal log, if on
                listener.on_near = lambda result: (self.say(near_line(result)), self.note_near(result), log_near(result))  # signals heard but not readable are shown too
                watcher = Station(job["call"] or "NOCALL", job["grid"])  # a station that never transmits, used to piece broadcasts together
                self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, watcher  # the received list follows it
                self.outbox = job["messages"] + self.outbox  # messages wait for the next time Listen runs
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
            station = Station(job["call"], job["grid"], close_when_done=not job["keep_open"])  # the link rules for this station, holding the lock open if asked
            station.move_to_hz = job["move_hz"] if rig is not None else None  # the working frequency to propose once locked (only when the radio can be retuned)
            base_hz = job["entry"]["dial_khz"] * 1000.0  # the calling frequency, in hertz
            retune = (lambda offset: rig.set_frequency(base_hz + offset)) if rig is not None else None  # how to move the radio to a working frequency and back
            station.listen()  # answers directed calls...
            station.answer_beacons = station.answer_calls = bool(job["auto_answer"])  # ...but only if the operator chose that; otherwise it just listens, and answers only what the operator started
            station.available = bool(job["available"])  # and whether the operator is available for contacts
            for text, to in job["messages"]:  # the queued messages
                station.queue(text, to=to or None)  # into the station's outbox, each with its address
            self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, station  # the lists follow this station from its beginning
            self.station = station  # from here on, newly queued messages go straight to this station
            run_station(station, source, self.sink, ptt, say=self.say, stay_on=True, should_stop=self.stop.is_set, retune=retune, on_heard=self.note_heard, on_frame=self.log_frame, on_transmit=self.transmitting, on_tick=self.tick, on_near=self.note_near,  # (continued)
                        signal_log=signal_log, dial_khz=lambda: round(self.dial_hz() / 1000.0, 1), listen_first=bool(job.get("listen_first", True)))  # the live loop, until stopped, with the signal log and the listen-first check
            self.station = None  # the run is over; later messages wait for the next one
            self.outbox = [(left, to or "") for left, to in zip(station.outbox, station.outbox_to)] + self.outbox  # anything it did not get to send is kept for the next run, with its address
            if rig is not None and station.offset_hz:  # the run was stopped while on a working frequency
                rig.set_frequency(base_hz)  # put the radio back on the calling frequency
                self.say("radio back on the calling frequency")  # confirm
            self.say(f"delivered {len(station.delivered)} message(s); {len(station.outbox)} still waiting (kept for the next run)")  # the outcome for sent traffic
        except Exception as problem:  # report any failure instead of dying silently
            self.say(f"stopped by a problem: {problem}")  # what went wrong
            if self.signal_log is not None:  # a signal log was started
                self.signal_log.note("stopped by a problem", problem=repr(problem))  # keep it there too
            self.mode = "off"  # nothing is running now
            self.root.after(0, lambda: self.mode_var.set("off"))  # show it (from the window's own thread)
        finally:  # always tidy up
            if self.signal_log is not None:  # a signal log was started
                self.signal_log.session_end(mode=mode)  # close the run in it
                self.signal_log = None  # no log until the next run
            if recorder is not None:  # audio was being recorded
                recorder.close()  # finish the file
                self.say(f"recording saved: {', '.join(os.path.basename(path) for path in recorder.files)}")  # say which files
            self.station = None  # no station is running any more, whatever happened
            self.poller_stop.set()  # stop reading the radio's meters
            self.tx_active = False  # the transmitter is off
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

    def close(self):  # the window is being closed
        self.stop.set()  # stop the station
        self.beacon_wanted = False  # and the repeating beacon
        if self.contact is not None:  # a contact was under way
            self.finish_contact()  # log what there is of it
        self.save_settings()  # remember the settings
        self.save_outbox()  # and the messages still waiting
        if self.worker is not None:  # a station or the monitor was running
            self.worker.join(timeout=3)  # give it a moment to unkey and release the sound card
        self.rigs.stop()  # stop the rig control program this panel started
        self.root.destroy()  # close the window


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
    try:  # the sound system
        devices = list_devices()  # every sound device
        note(bool(devices), f"sound system: {sum(1 for d in devices if d[2] > 0)} input and {sum(1 for d in devices if d[3] > 0)} output devices")  # how many
    except Exception as problem:  # no sound library or no sound system
        note(False, f"sound system: {problem}")  # say so
    try:  # the tools the File menu uses (in the installed program they must have been packed in)
        from tools import decode_wav, signal_report  # noqa: F401  # decoding recordings and summarising signal logs
        note(True, "tools: decode a recording, signal log report")  # present
    except Exception as problem:  # left out of the build
        note(False, f"tools: {problem}")  # say so
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
    root = tk.Tk()  # the window
    Panel(root)  # its contents
    if PROFILE:  # a profile was named
        root.title(f"Kestrel - {PROFILE}  -  signal v{SIGNAL_VERSION}")  # show which panel this is, and the signal version
    root.mainloop()  # run until closed


if __name__ == "__main__":  # only when run as a script
    main()  # go
