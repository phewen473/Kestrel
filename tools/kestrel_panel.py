"""A small control panel for a live Kestrel station.

Run from the repository root:

    python tools/kestrel_panel.py
    python tools/kestrel_panel.py --profile second    (a second panel with its own remembered settings, for a second radio)

Enter your callsign, grid locator, sound devices and rig control once
under the menu Settings > Rig Information. Then pick a frequency from the
drop-down list (Kestrel's meeting frequencies, plus any of your own that
you add) and press Monitor (receive only), Listen (answer beacons) or
Beacon (call for a partner). Messages to send and messages received each
have a list of their own. Your settings and your own frequencies are kept
in the local/ folder, which Git ignores.

Only transmit where your licence allows, with the published specification matching this program.
"""

import argparse  # reads the command-line options
import json  # settings are kept in a small JSON file
import os  # file paths
import queue  # carries log lines from the working thread to the window
import subprocess  # asks Git which commit this is, for the About box
import sys  # lets us add the repository root to the import path
import threading  # the station runs in its own thread so the window stays responsive
import time  # the clock, for the monitor
import tkinter as tk  # the window toolkit that comes with Python

import numpy as np  # arrays, for the scope's picture
from tkinter import filedialog, messagebox, ttk  # file chooser, message boxes and the themed widgets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live", "link" and "modem" importable when run as a script

from link import Station  # the link rules  # noqa: E402
from live import KIND, Listener, describe, plain_line, run_station, status_for  # the continuous receiver, a one-line frame description, the plain form of a log line, the live loop, the state shown by a log line  # noqa: E402
from live.audio import AudioIn, AudioOut, device_named, list_devices  # sound-card input and output  # noqa: E402
from live.bands import add_user_frequency, all_frequencies, describe_frequency, remove_user_frequency, user_frequencies, working_offsets_hz  # the frequency list and the working frequencies  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.rig import RigCtl, RigServer, find_rigctld, list_models  # rig control through Hamlib's rigctld, and starting rigctld for a chosen radio  # noqa: E402
from modem.params import SPEC_VERSION  # the version of the specification the signal follows  # noqa: E402

SETTINGS_FILE = os.path.join(ROOT, "local", "panel.json")  # where the panel remembers its settings
DEFAULTS = {"call": "", "grid": "", "frequency": 0, "audio_in": "", "audio_out": "", "gain": "0.25", "rig": "", "ptt": "none", "port": "",  # (continued)
            "rig_model": "", "cat_port": "", "cat_baud": "38400", "cat_handshake": "none", "rigctld": "", "keep_open": False, "working": 0}  # settings for a first run
PTT_NAMES = {"none": "None (receive only, or VOX)", "rig": "CAT (through rig control)", "rts": "RTS line of a serial port", "dtr": "DTR line of a serial port"}  # keying methods, as the operator sees them
NO_RIG = "(no rig control)"  # the radio-type choice that means the radio is tuned by hand


def load_settings():  # read the remembered settings
    """Return the saved settings, with defaults for anything missing."""
    settings = dict(DEFAULTS)  # start from the defaults
    if os.path.exists(SETTINGS_FILE):  # something was saved
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:  # open it
            settings.update(json.load(handle))  # saved values replace the defaults
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


CONTACTS_FILE = os.path.join(ROOT, "local", "contacts.json")  # the operator's saved contacts, shared by every panel on this computer


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
    """Return the text of the About box: what Kestrel is, the signal version, the program build, and who began it."""
    return (f"Kestrel (KES)\nAn adaptive amateur HF digital mode for short messages.\n\n"  # the name and what it is
            f"Signal: specification version {SPEC_VERSION} (draft)\n"  # which version of the published description the signal follows
            f"Program: {build_info()}\n"  # which build of the program
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n\n"  # the Python it runs on
            f"Stations must run the same signal version to hear each other.\n\n"  # the practical point
            f"Originated by P. H. Ewen (KO4WSC).\nProgram under Apache License 2.0; specification under CC BY 4.0.")  # credit and licences


def device_choices(kind):  # the sound devices to offer in a drop-down list
    """Return the names of every input (or output) device, each name once.

    Names are offered, not numbers: Windows renumbers its sound devices
    whenever one is plugged in or removed.
    """
    column = 2 if kind == "input" else 3  # which channel count to check
    seen, choices = set(), []  # names already listed, and the list itself
    for index, name, inputs, outputs in list_devices():  # every device
        if (inputs, outputs)[column - 2] > 0 and name not in seen:  # it can do the job and is not a repeat
            seen.add(name)  # remember the name
            choices.append(name)  # offer it by name
    return choices  # the list


class Panel:  # the control panel window
    """The window, its controls, and the thread that runs the station."""

    def __init__(self, root):  # build the window
        self.root = root  # the top-level window
        self.settings = load_settings()  # remembered settings (callsign, grid, sound devices, rig control)
        self.lines = queue.Queue()  # log lines waiting to be shown
        self.stop = threading.Event()  # set when the operator presses Stop
        self.worker = None  # the thread running the station, when there is one
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
        root.title(f"Kestrel  -  signal v{SPEC_VERSION}")  # window title, with the signal version so two stations can be compared at a glance
        root.columnconfigure(0, weight=1)  # the single column stretches with the window
        self._menus()  # the menu bar
        top = ttk.Frame(root)  # the strip holding the status line and the station's own details
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))  # place it at the top
        top.columnconfigure(0, weight=1)  # the status line takes the spare width
        self.plain_colour = root.cget("background")  # the window's ordinary background colour
        self.status = tk.Label(top, text="NOT RUNNING", font=("Segoe UI", 15, "bold"), fg="black", anchor="w", padx=8, pady=4)  # the station's state in large letters, on a band of colour
        self.status.grid(row=0, column=0, sticky="ew")  # place it on the left
        self.me = ttk.Label(top, text="", font=("Segoe UI", 10))  # this station's callsign and grid locator
        self.me.grid(row=0, column=1, sticky="e")  # place it on the right
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
        actions = ttk.Frame(root)  # the row of main buttons
        actions.grid(row=3, column=0, pady=4)  # place it
        for text, mode in (("Monitor (receive only)", "monitor"), ("Listen (answer beacons)", "listen"), ("Beacon (call anyone)", "beacon"), ("Call station (To)", "call")):  # the four ways to run
            ttk.Button(actions, text=text, command=lambda m=mode: self.start(m)).pack(side="left", padx=4)  # one button each
        ttk.Button(actions, text="Stop", command=self.stop_station).pack(side="left", padx=12)  # the Stop button
        options = ttk.Frame(root)  # the row of choices about how a contact is run
        options.grid(row=4, column=0, pady=2)  # place it under the buttons
        self.keep_open = tk.BooleanVar(value=bool(self.settings["keep_open"]))  # whether the lock is held after the traffic is done
        ttk.Checkbutton(options, text="Keep contact open", variable=self.keep_open).pack(side="left", padx=4)  # hold the lock until End contact is pressed
        ttk.Button(options, text="End contact", command=self.end_contact).pack(side="left", padx=(4, 16))  # close the contact properly, with identification
        ttk.Label(options, text="Once locked:").pack(side="left")  # label for the working-frequency choice
        self.working = ttk.Combobox(options, state="readonly", width=46)  # stay on the calling frequency, or move to a working frequency
        self.working.pack(side="left", padx=4)  # place it
        typing = ttk.Frame(root)  # the row for typing a message
        typing.grid(row=5, column=0, sticky="ew", padx=8, pady=4)  # place it
        typing.columnconfigure(1, weight=0)  # the callsign box keeps its size...
        typing.columnconfigure(3, weight=1)  # ...and the message box takes the spare width
        ttk.Label(typing, text="To").grid(row=0, column=0, sticky="w", padx=(0, 6))  # label for the callsign box
        self.to = ttk.Combobox(typing, width=11)  # the callsign a message is for, or the station to call: type one, or pick a saved contact or a station heard; blank means whoever the partner is
        self.to.grid(row=0, column=1, sticky="w")  # place it
        ttk.Label(typing, text="Message").grid(row=0, column=2, sticky="w", padx=(10, 6))  # label for the message box
        self.message = ttk.Entry(typing)  # the message box
        self.message.grid(row=0, column=3, sticky="ew")  # place it
        self.message.bind("<Return>", lambda event: self.queue_message())  # the Enter key queues the message
        ttk.Button(typing, text="Queue message", command=self.queue_message).grid(row=0, column=4, padx=(6, 0))  # add the message to the list to send
        ttk.Button(typing, text="Broadcast to ALL", command=self.broadcast_message).grid(row=0, column=5, padx=(4, 0))  # send the message to every station listening, with no acknowledgment
        lists = ttk.Frame(root)  # the two message lists, side by side
        lists.grid(row=6, column=0, sticky="nsew", padx=8, pady=4)  # place them
        lists.columnconfigure(0, weight=1)  # the two lists share the width
        lists.columnconfigure(1, weight=1)  # equally
        self.to_send = self._list(lists, 0, "Messages to send", (("time", "Queued", 64), ("to", "To", 70), ("text", "Message", 190), ("state", "State", 110)))  # outgoing messages, who each is for, and how far it has got
        self.received = self._list(lists, 1, "Messages received", (("time", "Time", 64), ("who", "From", 110), ("text", "Message", 230)))  # incoming messages and broadcasts
        lists.columnconfigure(2, weight=1)  # the third list shares the width too
        self.stations = self._list(lists, 2, "Stations heard and saved contacts", (("saved", "*", 22), ("who", "Callsign", 84), ("grid", "Grid", 50), ("snr", "Signal", 58), ("time", "Last heard", 68), ("text", "Sending", 100)))  # every callsign heard on the frequency, plus the operator's saved contacts (marked *)
        keep = ttk.Frame(self.stations.master)  # buttons under that list
        keep.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))  # place them
        ttk.Button(keep, text="Save as contact", command=self.save_contact).pack(side="left")  # keep the selected callsign for later
        ttk.Button(keep, text="Remove contact", command=self.remove_contact).pack(side="left", padx=4)  # forget it again
        ttk.Label(keep, text="double-click a callsign to put it in To").pack(side="left", padx=6)  # a hint
        self.stations.bind("<Double-1>", lambda event: self.pick_station())  # a double-click chooses the callsign for the next message or call
        for call in sorted(self.contacts):  # the saved contacts are listed from the start
            self.heard_rows[call] = self.stations.insert("", "end", values=("*", call, self.contacts[call].get("grid", ""), "", "", "saved contact"))  # one row each
        self.refresh_to()  # offer them in the To box
        for item in read_json(side_file("_outbox.json"), []):  # messages left waiting when the panel was last closed
            self.to_send.insert("", "end", values=(item.get("time", ""), item.get("to") or "partner", item.get("text", ""), "waiting"))  # back in the list
            self.outbox.append((item.get("text", ""), item.get("to", "")))  # and back in the queue for the next contact
        bottom = ttk.Frame(root)  # the bottom strip: the log on the left, the scope on the right
        bottom.grid(row=7, column=0, sticky="nsew", padx=8, pady=(4, 8))  # place it at the bottom
        bottom.columnconfigure(0, weight=1)  # the log takes the spare width
        bottom.rowconfigure(0, weight=1)  # and the spare height
        self._scope(bottom)  # build the scope
        activity = ttk.LabelFrame(bottom, text="Activity")  # the running log, in its own box
        activity.grid(row=0, column=0, sticky="nsew", padx=(0, 4))  # place it on the left
        activity.columnconfigure(0, weight=1)  # the log takes the width
        activity.rowconfigure(1, weight=1)  # and the spare height
        self.details = tk.BooleanVar(value=False)  # whether the log shows the technical detail
        ttk.Checkbutton(activity, text="Show technical details", variable=self.details, command=self.redraw_log).grid(row=0, column=0, sticky="w", padx=4)  # the switch between the plain and the detailed log
        self.log = tk.Text(activity, height=14, width=84, font=("Consolas", 9), state="disabled")  # the running log
        self.log.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)  # place it
        scroll = ttk.Scrollbar(activity, orient="vertical", command=self.log.yview)  # a scroll bar for the log
        scroll.grid(row=1, column=1, sticky="ns")  # place it beside the log
        self.log.configure(yscrollcommand=scroll.set)  # tie the two together
        root.rowconfigure(7, weight=1)  # the log stretches with the window
        self.refresh_frequencies(self.settings["frequency"])  # fill the frequency list
        self.show_me()  # show this station's callsign and grid
        root.protocol("WM_DELETE_WINDOW", self.close)  # save and stop cleanly when the window is closed
        root.after(100, self.show_lines)  # start passing log lines to the window
        root.after(500, self.follow_station)  # start keeping the lists and readings up to date
        root.after(150, self.draw_scope)  # start drawing the scope

    # ---- building blocks ----

    def _menus(self):  # the menu bar
        bar = tk.Menu(self.root)  # the bar itself
        settings = tk.Menu(bar, tearoff=False)  # the Settings menu
        settings.add_command(label="Rig Information...", command=self.rig_information)  # callsign, grid, radio type, serial ports, sound devices
        bar.add_cascade(label="Settings", menu=settings)  # put the menu on the bar
        help_menu = tk.Menu(bar, tearoff=False)  # the Help menu
        help_menu.add_command(label="About Kestrel", command=lambda: messagebox.showinfo("About Kestrel", about_text()))  # what this is, which version, and who began it
        bar.add_cascade(label="Help", menu=help_menu)  # put the menu on the bar
        self.root.configure(menu=bar)  # give the window its menu bar

    def _list(self, parent, column, title, columns):  # a titled list with named columns
        frame = ttk.LabelFrame(parent, text=title)  # the box around the list
        frame.grid(row=0, column=column, sticky="nsew", padx=2)  # place it
        frame.columnconfigure(0, weight=1)  # the list takes the width
        table = ttk.Treeview(frame, columns=[name for name, _, _ in columns], show="headings", height=5)  # the list itself, five rows tall
        for name, heading, width in columns:  # each column
            table.heading(name, text=heading, anchor="w")  # its heading
            table.column(name, width=width, anchor="w", stretch=(name == "text"))  # its width; only the message column stretches
        table.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)  # place the list
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)  # a scroll bar for it
        scroll.grid(row=0, column=1, sticky="ns")  # place it beside the list
        table.configure(yscrollcommand=scroll.set)  # tie the two together
        return table  # so rows can be added later

    def _scope(self, parent):  # the scope: a spectrum trace above a waterfall of the receive audio
        self.audio = None  # the sound-card input being shown, while a station or the monitor is running
        self.scope_w, self.trace_h, self.fall_h, self.top_hz = 512, 90, 150, 3000.0  # width in points, heights of the trace and the waterfall, and the highest frequency shown
        steps = np.linspace(0.0, 1.0, 256)  # the 256 brightness steps of the waterfall
        self.palette = np.stack([np.interp(steps, [0, 0.35, 0.7, 1.0], channel) for channel in ([0, 0, 255, 255], [0, 40, 255, 60], [40, 200, 0, 0])], axis=1).astype("uint8")  # their colours: black, blue, yellow, red
        self.fall = np.zeros((self.fall_h, self.scope_w, 3), dtype="uint8")  # the waterfall picture, newest line at the top
        frame = ttk.LabelFrame(parent, text="Scope  (receive audio, 0 to 3000 Hz; Kestrel sits between the dashed lines)")  # the box around the scope
        frame.grid(row=0, column=1, sticky="ns")  # place it on the right
        self.scope = tk.Canvas(frame, width=self.scope_w, height=self.trace_h + self.fall_h + 16, bg="black", highlightthickness=0)  # the drawing area
        self.scope.grid(row=0, column=0, padx=4, pady=4)  # place it
        self.fall_image = tk.PhotoImage(width=self.scope_w, height=self.fall_h)  # the waterfall as a picture
        self.fall_item = self.scope.create_image(0, self.trace_h, anchor="nw", image=self.fall_image)  # shown under the trace
        for hz in range(500, 3000, 500):  # a marker every 500 Hz
            x = hz / self.top_hz * (self.scope_w - 1)  # where it falls across the display
            edge = hz in (500, 2500)  # the two edges of a Kestrel signal
            self.scope.create_line(x, 0, x, self.trace_h + self.fall_h, fill="#e0e0e0" if edge else "#404040", dash=(4, 3) if edge else (1, 4))  # a dashed line for an edge, a faint dotted one otherwise
            self.scope.create_text(x, self.trace_h + self.fall_h + 8, text=str(hz), fill="#c0c0c0", font=("Segoe UI", 7))  # its frequency underneath
        self.trace = self.scope.create_line(0, self.trace_h, self.scope_w, self.trace_h, fill="#7cfc00")  # the spectrum trace, flat until there is audio

    def draw_scope(self):  # redraw the scope from the newest audio
        source = self.audio  # the sound-card input, if one is open
        if source is not None:  # there is audio to show
            try:  # the input may close while this runs
                levels = source.spectrum(self.top_hz, self.scope_w)  # the spectrum of the last sixth of a second, in decibels
                floor = float(np.median(levels))  # the noise level, taken as the middle value
                bright = np.clip((levels - (floor - 5.0)) / 55.0, 0.0, 1.0)  # each point on a scale from just under the noise to 50 dB above it
                points = np.column_stack((np.arange(self.scope_w), self.trace_h - 3 - bright * (self.trace_h - 8))).ravel().tolist()  # the trace's corners
                self.scope.coords(self.trace, *points)  # move the trace
                self.fall = np.roll(self.fall, 1, axis=0)  # push the waterfall down one line
                self.fall[0] = self.palette[(bright * 255).astype(int)]  # and paint the newest line at the top
                self.fall_image = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.scope_w, self.fall_h) + self.fall.tobytes(), format="PPM")  # the picture, rebuilt
                self.scope.itemconfigure(self.fall_item, image=self.fall_image)  # show it
            except Exception:  # a hiccup in drawing must never stop the station
                pass  # try again next time
        self.root.after(150, self.draw_scope)  # about seven times a second

    def show_notice(self, words):  # put up the idle-frequency warning (it does not hold anything up)
        self.close_notice()  # only one at a time
        self.notice = tk.Toplevel(self.root)  # a small window of its own
        self.notice.title("Kestrel - returning to the calling frequency")  # its title
        self.notice.attributes("-topmost", True)  # in front of everything, so it is seen
        ttk.Label(self.notice, text=words, wraplength=380, justify="left").pack(padx=16, pady=(14, 8))  # the warning
        ttk.Button(self.notice, text="OK", command=self.close_notice).pack(pady=(0, 12))  # OK takes the window away; it does not stop the return
        self.notice.protocol("WM_DELETE_WINDOW", self.close_notice)  # so does its close box
        self.root.bell()  # a sound to draw attention

    def close_notice(self):  # take the idle-frequency warning away
        if self.notice is not None:  # one is showing
            self.notice.destroy()  # close it
            self.notice = None  # none is showing now

    def show_me(self):  # show this station's own details at the top right
        call, grid = self.settings["call"] or "no callsign set", self.settings["grid"]  # what is set so far
        self.me.configure(text=f"{call}   {grid}")  # callsign and grid locator

    def show_status(self, words, colour):  # put the station's state on the band at the top
        """Show `words`; a lock is a solid green band, trouble holding it amber or red, anything else plain."""
        if colour == "dark green":  # locked with a partner
            self.status.configure(text=words, bg="#1b7f3b", fg="white")  # white on solid green: unmistakable
        elif colour in ("dark orange", "red"):  # the link is in trouble, or something failed
            self.status.configure(text=words, bg="#c0392b" if colour == "red" else "#d98200", fg="white")  # white on red or amber
        else:  # every other state
            self.status.configure(text=words, bg=self.plain_colour, fg=colour)  # coloured words on the ordinary background

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
            if state is not None:  # yes
                self.show_status(state[0], state[1])  # show the new state in its colour
            elif "monitoring" in line.lower():  # the receive-only monitor has started
                self.show_status("MONITORING  -  receive only", "dark blue")  # say so
            self.log.configure(state="normal")  # allow writing
            self._write_log(clock, line)  # add the line to the log box
            self.log.see("end")  # keep the newest line in view
            self.log.configure(state="disabled")  # back to read-only
            try:  # also keep the full line in a file, so a run can be studied afterwards
                with open(os.path.splitext(SETTINGS_FILE)[0] + ".log", "a", encoding="utf-8") as handle:  # the log file sits beside this panel's settings file
                    handle.write(f"{time.strftime('%Y-%m-%d')} {clock}  {line}\n")  # the line, with the date and time of day
            except OSError:  # the file could not be written
                pass  # the window still shows the line, which is what matters
        self.root.after(100, self.show_lines)  # look again in a tenth of a second

    def note_heard(self, result):  # a frame from some station decoded (called from the working thread)
        call = (result.fields or {}).get("origin") or (result.origin if result.frame_type == 1 else "")  # the callsign it carries: in a beacon, an answer, an identification or a fully addressed message
        if call:  # it names its sender
            self.heard.put((call, (result.fields or {}).get("grid", ""), result.snr_db, KIND.get(result.frame_type, "frame")))  # pass it to the window

    def follow_station(self):  # keep the message lists and the readings in step with the station
        while not self.heard.empty():  # every station heard since the last look
            call, grid, snr, kind = self.heard.get()  # who, where, how strong, and what it sent
            values = ("*" if call in self.contacts else "", call, grid or (self.stations.set(self.heard_rows[call], "grid") if call in self.heard_rows else ""), f"{snr:+.0f} dB", time.strftime("%H:%M:%S"), kind)  # the row's contents (a grid learned earlier is kept)
            if call in self.heard_rows:  # already listed
                self.stations.item(self.heard_rows[call], values=values)  # bring its row up to date
                self.stations.move(self.heard_rows[call], "", 0)  # and move it to the top: most recently heard first
            else:  # a new callsign
                self.heard_rows[call] = self.stations.insert("", 0, values=values)  # add it at the top
                self.refresh_to()  # and offer it in the To box
        station = self.tracked  # the station being followed, running or just finished
        if station is not None:  # there is one
            while self.marked < len(station.delivered):  # a message has been delivered since the last look
                self._advance(station.delivered[self.marked], "delivered " + time.strftime("%H:%M"))  # mark its row
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
                self.shown_b += 1  # one more shown
            while self.shown < len(station.inbox):  # a message has arrived since the last look
                self.received.insert("", "end", values=(time.strftime("%H:%M:%S"), station.partner, station.inbox[self.shown]))  # add it to the received list
                self.received.yview_moveto(1.0)  # keep the newest row in view
                self.shown += 1  # one more shown
            if self.station is station and station.state in ("LOCKED", "DEGRADED", "REACQUIRE"):  # in a contact
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
        self.root.after(500, self.follow_station)  # look again in half a second

    def refresh_to(self):  # (re)fill the To box's list
        self.to["values"] = sorted(self.contacts) + [call for call in self.heard_rows if call not in self.contacts]  # saved contacts first, then the other stations heard

    def pick_station(self):  # a callsign in the stations list was double-clicked
        for row in self.stations.selection()[:1]:  # the row chosen
            self.to.set(self.stations.set(row, "who"))  # its callsign goes into the To box

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

    def rig_information(self):  # the Settings > Rig Information dialog
        dialog = tk.Toplevel(self.root)  # a window of its own
        dialog.title("Rig Information")  # its title
        dialog.transient(self.root)  # it belongs to the main window
        program = self.settings["rigctld"] or find_rigctld()  # the rig control program: the one chosen before, else one found on this computer
        models = [f"{number}  {name}" for number, name in list_models(program)] if program else []  # every radio type it knows, as "number  name"
        try:  # the serial port list needs the pyserial package
            from serial.tools import list_ports  # lists this computer's serial ports
            ports = sorted(port.device for port in list_ports.comports())  # their names (COM3, /dev/ttyUSB0, ...)
        except ImportError:  # pyserial is not installed
            ports = []  # the operator can still type a port name
        boxes = {}  # the controls, by setting name

        def group(title, row):  # a titled box for one group of settings
            frame = ttk.LabelFrame(dialog, text=title)  # the box
            frame.grid(row=row, column=0, sticky="ew", padx=10, pady=6)  # place it
            return frame  # for its rows

        def field(frame, row, name, label, choices=None, editable=False, width=30):  # one labelled setting
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)  # the label
            if choices is None:  # a text box
                box = ttk.Entry(frame, width=width)  # the box
                box.insert(0, self.settings[name])  # its present value
            else:  # a drop-down list
                box = ttk.Combobox(frame, state="normal" if editable else "readonly", values=choices, width=width)  # the list (some may also be typed into)
                box.set(self.settings[name] if (editable or self.settings[name] in choices) and self.settings[name] else (choices[0] if choices else ""))  # the present choice, else the first
            box.grid(row=row, column=1, sticky="w", padx=8, pady=3)  # place it
            boxes[name] = box  # keep it
            return box  # for any extra wiring

        station = group("Station", 0)  # who and where
        field(station, 0, "call", "Callsign", width=14)  # callsign
        field(station, 1, "grid", "Grid locator", width=10)  # grid locator
        radio = group("Radio", 1)  # the radio and how the computer reaches it
        rig_box = field(radio, 0, "rig_model", "Rig type", [NO_RIG] + models, editable=True, width=44)  # the radio type, from the rig control program's own list
        if not self.settings["rig_model"]:  # none chosen yet
            rig_box.set(NO_RIG)  # start at "no rig control"
        rig_box.bind("<KeyRelease>", lambda event: rig_box.configure(values=[NO_RIG] + [model for model in models if rig_box.get().lower() in model.lower()]))  # typing part of a name narrows the list
        field(radio, 1, "cat_port", "CAT serial port", ports, editable=True, width=14)  # the serial port that carries CAT control
        field(radio, 2, "cat_baud", "CAT speed (baud)", ["4800", "9600", "19200", "38400", "57600", "115200"], width=14)  # its speed
        field(radio, 3, "cat_handshake", "CAT handshake", ["none", "hardware"], width=14)  # RTS/CTS handshaking, for radios that want it
        ptt_box = field(radio, 4, "ptt", "Key the transmitter (PTT) by", list(PTT_NAMES.values()), width=30)  # how the transmitter is keyed
        ptt_box.set(PTT_NAMES.get(self.settings["ptt"], PTT_NAMES["none"]))  # the present method, in plain words
        field(radio, 5, "port", "PTT serial port (for RTS or DTR)", ports, editable=True, width=14)  # the port whose RTS or DTR line keys the radio
        audio = group("Audio", 2)  # the sound devices and level
        field(audio, 0, "audio_in", "Audio from radio", device_choices("input"), width=52)  # the receive audio device
        field(audio, 1, "audio_out", "Audio to radio", device_choices("output"), width=52)  # the transmit audio device
        field(audio, 2, "gain", "Transmit audio level (0 to 1)", width=8)  # how loud the transmit audio is
        extra = group("Rig control program", 3)  # where rigctld is, or one already running
        path_box = field(extra, 0, "rigctld", "rigctld program", width=52)  # the rig control program's file
        if not self.settings["rigctld"] and program:  # none chosen, but one was found
            path_box.insert(0, program)  # offer it

        def browse():  # the Browse button
            chosen = filedialog.askopenfilename(parent=dialog, title="Find the rigctld program")  # ask for the file
            if chosen:  # one was picked
                path_box.delete(0, "end")  # clear the box
                path_box.insert(0, chosen)  # show the choice

        ttk.Button(extra, text="Browse...", command=browse).grid(row=0, column=2, padx=(0, 8))  # find the program by hand
        field(extra, 1, "rig", "or one already running at (host:port)", width=22)  # an outside rigctld, used only when no rig type is chosen

        def save():  # the Save button
            for name, box in boxes.items():  # every setting
                self.settings[name] = box.get() if name in ("audio_in", "audio_out") else box.get().strip()  # take its value (device names are kept exactly, spaces and all)
            if self.settings["rig_model"] == NO_RIG:  # no rig control wanted
                self.settings["rig_model"] = ""  # stored as blank
            self.settings["ptt"] = next((key for key, words in PTT_NAMES.items() if words == self.settings["ptt"]), "none")  # the keying method back in its short form
            self.save_settings()  # write them to the settings file
            self.show_me()  # show the callsign and grid at the top
            dialog.destroy()  # close the dialog

        buttons = ttk.Frame(dialog)  # the row of buttons
        buttons.grid(row=4, column=0, sticky="e", padx=10, pady=8)  # place it at the bottom right
        ttk.Button(buttons, text="Save", command=save).pack(side="left", padx=4)  # keep the changes
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left")  # drop the changes
        ttk.Label(dialog, text="Changes take effect the next time a frequency is chosen or Monitor, Listen or Beacon is pressed.").grid(row=5, column=0, sticky="w", padx=10, pady=(0, 8))  # when the settings are used

    def rig_address(self, settings):  # where rig control can be reached for these settings (may be called from any thread)
        """Return a rigctld address, starting rigctld for the chosen radio if needed; "" when the radio is tuned by hand."""
        if settings["rig_model"] and settings["cat_port"]:  # a radio type and its serial port are chosen
            program = settings["rigctld"] or find_rigctld()  # the rig control program
            if not program:  # there is none
                raise RuntimeError("the rig control program (rigctld) was not found; choose it under Settings > Rig Information")  # say what to do
            return self.rigs.ensure(program, settings["rig_model"].split()[0], settings["cat_port"], settings["cat_baud"] or 38400, settings["cat_handshake"])  # start it if it is not already running
        return settings["rig"]  # an outside rigctld, or nothing

    def save_settings(self):  # remember the current settings
        self.settings["frequency"] = self.frequency.current()  # the frequency now selected
        self.settings["keep_open"] = bool(self.keep_open.get())  # whether contacts are kept open
        self.settings["working"] = self.working.current()  # the working-frequency choice
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)  # create local/ if needed
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:  # open the settings file
            json.dump(self.settings, handle, indent=2)  # save, readably

    # ---- frequencies ----

    def refresh_frequencies(self, select=0):  # (re)fill the frequency drop-down list
        self.entries = all_frequencies()  # the presets and the operator's own
        self.frequency["values"] = [describe_frequency(entry) for entry in self.entries]  # one line each
        self.frequency.current(min(max(select, 0), len(self.entries) - 1))  # select the wanted line
        self.refresh_working(self.settings["working"])  # and offer the working frequencies that go with it

    def refresh_working(self, select=0):  # (re)fill the working-frequency choice for the selected calling frequency
        entry = self.selected()  # the calling frequency
        choices = ["stay on the calling frequency"]  # the first choice: no move
        for offset in working_offsets_hz(entry):  # each working frequency that goes with it
            choices.append(f"move to {entry['dial_khz'] + offset / 1000.0:.1f} kHz  ({offset / 1000.0:+.1f} kHz), return at the end")  # where the pair would go
        self.working["values"] = choices  # show them
        self.working.current(select if 0 <= select < len(choices) else 0)  # the remembered choice, if it still exists

    def selected(self):  # the frequency entry now selected
        return self.entries[self.frequency.current()]  # by its position in the list

    def add_frequency(self):  # ask for a frequency of the operator's own
        dialog = tk.Toplevel(self.root)  # a small window
        dialog.title("Add a frequency")  # its title
        boxes = []  # the four text boxes
        for row, (label, value) in enumerate((("Band (for example 17 m)", ""), ("Dial frequency in kHz (USB)", ""), ("Radio mode", "PKTUSB"), ("Note", ""))):  # the four things asked for
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)  # the label
            box = ttk.Entry(dialog, width=28)  # the box
            box.insert(0, value)  # its starting text
            box.grid(row=row, column=1, padx=6, pady=3)  # place it
            boxes.append(box)  # keep it

        def save():  # the Save button
            try:  # the entry may be refused
                add_user_frequency(boxes[0].get(), boxes[1].get(), boxes[2].get(), boxes[3].get())  # save it to local/frequencies.json
            except ValueError as problem:  # something was missing or not a number
                messagebox.showerror("Kestrel", str(problem), parent=dialog)  # say what
                return  # leave the dialog open
            dialog.destroy()  # close the dialog
            self.refresh_frequencies(len(all_frequencies()) - 1)  # show the list with the new entry selected

        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=1, sticky="e", padx=6, pady=6)  # the Save button

    def remove_frequency(self):  # remove the selected frequency, if it is one of the operator's own
        entry = self.selected()  # what is selected
        if entry["builtin"]:  # a preset
            messagebox.showinfo("Kestrel", "Kestrel's own meeting frequencies cannot be removed.")  # say so
            return  # nothing to do
        remove_user_frequency(self.frequency.current() - (len(self.entries) - len(user_frequencies())))  # its position among the operator's own
        self.refresh_frequencies(0)  # show the list again

    def tune(self):  # a frequency was chosen from the list: tune the radio to it
        if self.worker is not None and self.worker.is_alive() and self.station is not None:  # a station is on the air
            self.say("frequency change ignored while the station is running; press Stop first")  # moving mid-contact would drop the partner
            return  # leave the radio where it is
        self.refresh_working(0)  # a new calling frequency has its own working frequencies; start at "stay"
        self.save_settings()  # remember the choice
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

    def queue_message(self):  # add the typed message to the list to send
        text = self.message.get().strip()  # what was typed
        to = self.to.get().strip().upper()  # who it is for, if anyone in particular
        if text and to and to == self.settings["call"].strip().upper():  # the message is addressed to this station itself
            messagebox.showinfo("Kestrel", f"{to} is this station's own callsign.\n\nPut the other station's callsign in the To box, or leave it blank to send to whoever the partner is.")  # say so, and what to do
            return  # leave the message in the box
        if text:  # something was
            self.message.delete(0, "end")  # clear the box
            self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), to or "partner", text, "waiting"))  # show it in the list
            self.to_send.yview_moveto(1.0)  # keep the newest row in view
            station = self.station  # the station running at this moment, if any
            if station is not None:  # one is running
                station.queue(text, to=to or None)  # hand it the message now; it goes when the right station is the partner
                self.say(f"queued with the running station{' for ' + to if to else ''}: {text}")  # confirm
            else:  # nothing is running
                self.outbox.append((text, to))  # keep it for the next Listen, Beacon or Call
                self.say(f"queued for the next contact{' with ' + to if to else ''}: {text}")  # confirm
            self.save_outbox()  # a waiting message is kept even if the panel is closed

    def broadcast_message(self):  # send the typed message to every station listening
        text = self.message.get().strip()  # what was typed
        if not text:  # nothing was
            messagebox.showinfo("Kestrel", "Type the message to broadcast first.")  # say so
            return  # nothing to do
        station = self.station  # the station running at this moment, if any
        if station is None and self.worker is not None and self.worker.is_alive():  # the receive-only monitor is running
            messagebox.showinfo("Kestrel", "Monitor is receive only. Press Stop, then Broadcast to ALL.")  # say so
            return  # nothing to do
        if not messagebox.askokcancel("Kestrel", "This will TRANSMIT the message to all stations at the slowest level, with no acknowledgment.\nCheck on the scope that the frequency is clear. Continue?"):  # a last check before transmitting
            return  # the operator backed out
        self.message.delete(0, "end")  # clear the box
        self.to_send.insert("", "end", values=(time.strftime("%H:%M:%S"), "ALL", text, "broadcast" if station is None else "broadcast when idle"))  # show it in the list
        self.to_send.yview_moveto(1.0)  # keep the newest row in view
        if station is not None:  # a station is running
            station.broadcast(text)  # it goes out as soon as no contact is in progress
            self.say(f"broadcast queued: {text}")  # confirm
        else:  # nothing is running: start a short run that only sends the broadcast
            self.start("broadcast", confirmed=True, text=text)  # go

    def start(self, mode, confirmed=False, text=""):  # one of the main buttons (or a broadcast with nothing running)
        if self.worker is not None and self.worker.is_alive():  # already running
            messagebox.showinfo("Kestrel", "Already running. Press Stop first.")  # say so
            return  # nothing to do
        if mode != "monitor" and not (self.settings["call"] and self.settings["grid"]):  # transmitting needs a callsign and a locator
            messagebox.showinfo("Kestrel", "Enter your callsign and grid locator first, under Settings > Rig Information.")  # say so
            self.rig_information()  # and open the dialog
            return  # nothing more to do
        if mode == "call" and not self.to.get().strip():  # a directed call needs somebody to call
            messagebox.showinfo("Kestrel", "Type the callsign to call in the To box first.")  # say so
            return  # nothing to do
        if mode == "call" and self.to.get().strip().upper() == self.settings["call"].strip().upper():  # the To box holds this station's own callsign
            messagebox.showinfo("Kestrel", f"{self.settings['call']} is this station's own callsign.\n\nPut the callsign of the station you want to reach in the To box. Only a station using exactly that callsign will answer.")  # say so, and what to do
            return  # nothing to do
        if mode != "monitor" and not confirmed and not messagebox.askokcancel("Kestrel", "This station will TRANSMIT on the radio's frequency. Continue?"):  # a last check before transmitting
            return  # the operator backed out
        try:  # the chosen sound devices may have gone away
            job = self.prepare()  # everything the working thread needs
            job["target"], job["broadcast"] = self.to.get().strip().upper(), text  # the station to call, and the broadcast to send, when those are what was asked for
        except ValueError as problem:  # a device is not connected
            messagebox.showerror("Kestrel", f"{problem}. Choose the sound devices under Settings > Rig Information.")  # say which, and where to fix it
            return  # nothing started
        self.worker = threading.Thread(target=self.run, args=(mode, job), daemon=True)  # the working thread, with everything it needs
        self.worker.start()  # go

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

    def end_contact(self):  # the End contact button
        station = self.station  # the station running at this moment, if any
        if station is None or station.state not in ("LOCKED", "DEGRADED", "REACQUIRE"):  # there is no contact to end
            self.say("no contact in progress")  # say so
            return  # nothing to do
        station.end()  # close once any traffic under way is finished
        self.say("ending the contact: closing identification will be sent when the current exchange is done")  # confirm

    def stop_station(self):  # the Stop button
        self.stop.set()  # the working thread sees this within a tenth of a second
        self.say("stopping...")  # confirm

    def run(self, mode, job):  # the working thread: runs the monitor or the station
        source = rig = ptt = None  # nothing opened yet
        try:  # anything that goes wrong is reported in the log
            source = AudioIn(job["in"])  # start recording from the chosen device
            self.audio = source  # let the scope show what it hears
            if mode == "monitor":  # receive only
                listener = Listener()  # the continuous receiver
                watcher = Station(job["call"] or "NOCALL", job["grid"])  # a station that never transmits, used to piece broadcasts together
                self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, watcher  # the received list follows it
                self.say("monitoring: receive only, nothing will be transmitted")  # opening line
                while not self.stop.is_set():  # until Stop
                    for heard in listener.feed(source.read()):  # every frame that has completed
                        self.say(describe(heard.result))  # show it
                        if heard.result.ok:  # it decoded
                            self.note_heard(heard.result)  # add its sender to the stations heard
                            watcher.handle(heard.result, time.monotonic())  # and let the watcher collect any broadcast
                    time.sleep(0.1)  # a tenth of a second between looks
                return  # done
            with self.rig_lock:  # one user of rig control at a time while it starts and tunes
                address = self.rig_address(job)  # start or find rig control for the chosen radio
                if address:  # rig control is set up
                    rig = RigCtl(address)  # connect to rigctld
                    self._tune(rig, job["entry"])  # go to the selected frequency
            ptt = Ptt(job["ptt"], job["port"] or None, rig=rig)  # the transmit switch
            sink = AudioOut(job["out"], float(job["gain"]))  # the playing side
            station = Station(job["call"], job["grid"], close_when_done=not job["keep_open"])  # the link rules for this station, holding the lock open if asked
            station.move_to_hz = job["move_hz"] if rig is not None else None  # the working frequency to propose once locked (only when the radio can be retuned)
            base_hz = job["entry"]["dial_khz"] * 1000.0  # the calling frequency, in hertz
            retune = (lambda offset: rig.set_frequency(base_hz + offset)) if rig is not None else None  # how to move the radio to a working frequency and back
            if mode == "beacon":  # call for anyone
                station.beacon()  # by beaconing
            elif mode == "call":  # call one station by name
                station.call_station(job["target"])  # only that station answers
            elif mode == "listen":  # wait to be called
                station.listen()  # answers beacons and directed calls
            else:  # a broadcast and nothing else
                station.broadcast(job["broadcast"])  # queue it; the station sends it at once, since it is idle
            for text, to in job["messages"]:  # the queued messages
                station.queue(text, to=to or None)  # into the station's outbox, each with its address
            self.marked, self.shown, self.shown_b, self.tracked = 0, 0, 0, station  # the lists follow this station from its beginning
            self.station = station  # from here on, newly queued messages go straight to this station
            run_station(station, source, sink, ptt, say=self.say, stay_on=(mode == "listen"), should_stop=(lambda: self.stop.is_set() or (mode == "broadcast" and not station.broadcasts)), retune=retune, on_heard=self.note_heard)  # the live loop (a broadcast-only run ends when the broadcast has gone)
            self.station = None  # the run is over; later messages wait for the next one
            self.outbox = [(left, to or "") for left, to in zip(station.outbox, station.outbox_to)] + self.outbox  # anything it did not get to send is kept for the next run, with its address
            if mode == "broadcast":  # a broadcast-only run
                self._advance(job["broadcast"], "sent " + time.strftime("%H:%M"))  # mark the broadcast as sent
            if rig is not None and station.offset_hz:  # the run was stopped while on a working frequency
                rig.set_frequency(base_hz)  # put the radio back on the calling frequency
                self.say("radio back on the calling frequency")  # confirm
            self.say(f"delivered {len(station.delivered)} message(s); {len(station.outbox)} still waiting (kept for the next run)")  # the outcome for sent traffic
        except Exception as problem:  # report any failure instead of dying silently
            self.say(f"stopped by a problem: {problem}")  # what went wrong
        finally:  # always tidy up
            self.station = None  # no station is running any more, whatever happened
            if ptt is not None:  # a transmit switch was opened
                ptt.close()  # make sure the transmitter is off
            if rig is not None:  # rig control was opened
                rig.close()  # hang up
            self.audio = None  # the scope has nothing to show any more
            if source is not None:  # recording was started
                source.close()  # release the sound device
            self.say("stopped")  # closing line

    def close(self):  # the window is being closed
        self.stop.set()  # stop the station
        self.save_settings()  # remember the settings
        self.save_outbox()  # and the messages still waiting
        self.rigs.stop()  # stop the rig control program this panel started
        self.root.destroy()  # close the window


def main():  # the script itself
    """Open the panel."""
    global SETTINGS_FILE  # a named profile keeps its settings in a file of its own
    parser = argparse.ArgumentParser(description="Kestrel control panel")  # the command-line reader
    parser.add_argument("--profile", default="", help="a name for a second set of remembered settings, for running one panel per radio")  # optional profile name
    profile = "".join(c for c in parser.parse_args().profile if c.isalnum() or c in "-_")  # keep only characters that are safe in a file name
    if profile:  # a profile was named
        SETTINGS_FILE = os.path.join(ROOT, "local", f"panel_{profile}.json")  # its own settings file
    root = tk.Tk()  # the window
    Panel(root)  # its contents
    if profile:  # a profile was named
        root.title(f"Kestrel - {profile}  -  signal v{SPEC_VERSION}")  # show which panel this is, and the signal version
    root.mainloop()  # run until closed


if __name__ == "__main__":  # only when run as a script
    main()  # go
