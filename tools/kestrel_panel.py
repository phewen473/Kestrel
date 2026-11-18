"""A small control panel for a live Kestrel station.

Run from the repository root:

    python tools/kestrel_panel.py

Pick a frequency from the drop-down list (Kestrel's meeting frequencies,
plus any of your own that you add), choose the sound devices, and press
Monitor (receive only), Listen (answer beacons) or Beacon (call for a
partner). Your settings and your own frequencies are kept in the local/
folder, which Git ignores.

Only transmit where your licence allows, with the published specification matching this program.
"""

import json  # settings are kept in a small JSON file
import os  # file paths
import queue  # carries log lines from the working thread to the window
import sys  # lets us add the repository root to the import path
import threading  # the station runs in its own thread so the window stays responsive
import time  # the clock, for the monitor
import tkinter as tk  # the window toolkit that comes with Python
from tkinter import messagebox, ttk  # message boxes and the themed widgets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live", "link" and "modem" importable when run as a script

from link import Station  # the link rules  # noqa: E402
from live import Listener, describe, run_station  # the continuous receiver, a one-line frame description, the live loop  # noqa: E402
from live.audio import AudioIn, AudioOut, device_named, list_devices  # sound-card input and output  # noqa: E402
from live.bands import add_user_frequency, all_frequencies, describe_frequency, remove_user_frequency, user_frequencies  # the frequency list  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.rig import RigCtl  # rig control through Hamlib's rigctld  # noqa: E402

SETTINGS_FILE = os.path.join(ROOT, "local", "panel.json")  # where the panel remembers its settings
DEFAULTS = {"call": "", "grid": "", "frequency": 0, "audio_in": "", "audio_out": "", "gain": "0.25", "rig": "", "ptt": "none", "port": ""}  # settings for a first run


def load_settings():  # read the remembered settings
    """Return the saved settings, with defaults for anything missing."""
    settings = dict(DEFAULTS)  # start from the defaults
    if os.path.exists(SETTINGS_FILE):  # something was saved
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:  # open it
            settings.update(json.load(handle))  # saved values replace the defaults
    return settings  # the settings to use


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
        self.settings = load_settings()  # remembered settings
        self.lines = queue.Queue()  # log lines waiting to be shown
        self.stop = threading.Event()  # set when the operator presses Stop
        self.worker = None  # the thread running the station, when there is one
        self.outbox = []  # messages queued for the partner
        self.entries = []  # the frequency entries behind the drop-down list
        root.title("Kestrel")  # window title
        root.columnconfigure(1, weight=1)  # the middle column stretches with the window
        self.call = self._entry(0, "Callsign", self.settings["call"], 12)  # callsign box
        self.grid = self._entry(1, "Grid locator", self.settings["grid"], 8)  # grid locator box
        ttk.Label(root, text="Frequency").grid(row=2, column=0, sticky="w", padx=6, pady=3)  # label for the frequency list
        self.frequency = ttk.Combobox(root, state="readonly", width=92, font=("Consolas", 9))  # the frequency drop-down list
        self.frequency.grid(row=2, column=1, sticky="ew", padx=6, pady=3)  # place it
        buttons = ttk.Frame(root)  # a strip of buttons beside the list
        buttons.grid(row=2, column=2, sticky="e", padx=6)  # place the strip
        ttk.Button(buttons, text="Add...", command=self.add_frequency).pack(side="left")  # add a frequency of your own
        ttk.Button(buttons, text="Remove", command=self.remove_frequency).pack(side="left")  # remove one of your own
        ttk.Button(buttons, text="Tune radio", command=self.tune).pack(side="left")  # send the selected frequency to the radio
        self.audio_in = self._choice(3, "Audio from radio", device_choices("input"), self.settings["audio_in"])  # input device list
        self.audio_out = self._choice(4, "Audio to radio", device_choices("output"), self.settings["audio_out"])  # output device list
        self.gain = self._entry(5, "Transmit level (0 to 1)", self.settings["gain"], 6)  # transmit audio level box
        self.rig = self._entry(6, "Rig control (rigctld host:port)", self.settings["rig"], 22)  # rigctld address box
        self.ptt = self._choice(7, "Key the transmitter by", ["none", "rig", "cat", "rts", "dtr"], self.settings["ptt"])  # keying method list
        self.port = self._entry(8, "Serial port (for cat, rts, dtr)", self.settings["port"], 10)  # serial port box
        self.message = self._entry(9, "Message for the partner", "", 70)  # message box
        ttk.Button(root, text="Queue message", command=self.queue_message).grid(row=9, column=2, sticky="e", padx=6)  # add the message to the outbox
        actions = ttk.Frame(root)  # the row of main buttons
        actions.grid(row=10, column=0, columnspan=3, pady=6)  # place it
        for text, mode in (("Monitor (receive only)", "monitor"), ("Listen (answer beacons)", "listen"), ("Beacon (call)", "beacon")):  # the three ways to run
            ttk.Button(actions, text=text, command=lambda m=mode: self.start(m)).pack(side="left", padx=4)  # one button each
        ttk.Button(actions, text="Stop", command=self.stop_station).pack(side="left", padx=12)  # the Stop button
        self.log = tk.Text(root, height=20, width=120, font=("Consolas", 9), state="disabled")  # the running log
        self.log.grid(row=11, column=0, columnspan=3, sticky="nsew", padx=6, pady=6)  # place it
        root.rowconfigure(11, weight=1)  # the log stretches with the window
        self.refresh_frequencies(self.settings["frequency"])  # fill the frequency list
        root.protocol("WM_DELETE_WINDOW", self.close)  # save and stop cleanly when the window is closed
        root.after(100, self.show_lines)  # start passing log lines to the window

    # ---- building blocks ----

    def _entry(self, row, label, value, width):  # a labelled text box
        ttk.Label(self.root, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)  # the label
        box = ttk.Entry(self.root, width=width)  # the box
        box.insert(0, value)  # its starting text
        box.grid(row=row, column=1, sticky="w", padx=6, pady=3)  # place it
        return box  # so its text can be read later

    def _choice(self, row, label, values, value):  # a labelled drop-down list
        ttk.Label(self.root, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)  # the label
        box = ttk.Combobox(self.root, state="readonly", values=values, width=60)  # the list
        box.set(value if value in values else (values[0] if values else ""))  # the remembered choice, else the first
        box.grid(row=row, column=1, sticky="w", padx=6, pady=3)  # place it
        return box  # so the choice can be read later

    def say(self, text):  # add a line to the log (safe to call from any thread)
        self.lines.put(text)  # the window picks it up shortly

    def show_lines(self):  # move waiting log lines into the window
        while not self.lines.empty():  # every waiting line
            self.log.configure(state="normal")  # allow writing
            self.log.insert("end", self.lines.get() + "\n")  # add the line
            self.log.see("end")  # keep the newest line in view
            self.log.configure(state="disabled")  # back to read-only
        self.root.after(100, self.show_lines)  # look again in a tenth of a second

    # ---- frequencies ----

    def refresh_frequencies(self, select=0):  # (re)fill the frequency drop-down list
        self.entries = all_frequencies()  # the presets and the operator's own
        self.frequency["values"] = [describe_frequency(entry) for entry in self.entries]  # one line each
        self.frequency.current(min(max(select, 0), len(self.entries) - 1))  # select the wanted line

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

    def tune(self):  # send the selected frequency to the radio
        if not self.rig.get().strip():  # no rig control address
            messagebox.showinfo("Kestrel", "Enter the rig control address first (for example 127.0.0.1:4532).")  # say what is needed
            return  # nothing to do
        try:  # the radio may not answer
            rig = RigCtl(self.rig.get().strip())  # connect to rigctld
            self._tune(rig, self.selected())  # set mode and frequency
            rig.close()  # hang up
        except (OSError, RuntimeError) as problem:  # no connection, or the radio refused
            messagebox.showerror("Kestrel", f"Could not tune the radio: {problem}")  # say what went wrong

    def _tune(self, rig, entry):  # set the radio to a frequency entry
        rig.set_mode(entry["mode"])  # the mode first
        rig.set_frequency(entry["dial_khz"] * 1000.0)  # then the frequency
        self.say(f"radio tuned to {rig.frequency() / 1000.0:.1f} kHz {entry['mode']}  ({entry['band']})")  # confirm what the radio reports

    # ---- running ----

    def queue_message(self):  # add the typed message to the outbox
        text = self.message.get().strip()  # what was typed
        if text:  # something was
            self.outbox.append(text)  # queue it
            self.message.delete(0, "end")  # clear the box
            self.say(f"queued for the partner: {text}")  # confirm

    def save_settings(self):  # remember the current settings
        self.settings = {"call": self.call.get().strip(), "grid": self.grid.get().strip(), "frequency": self.frequency.current(), "audio_in": self.audio_in.get(),  # (continued)
                         "audio_out": self.audio_out.get(), "gain": self.gain.get().strip(), "rig": self.rig.get().strip(), "ptt": self.ptt.get(), "port": self.port.get().strip()}  # every box and list
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)  # create local/ if needed
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:  # open the settings file
            json.dump(self.settings, handle, indent=2)  # save, readably

    def start(self, mode):  # one of the three main buttons
        if self.worker is not None and self.worker.is_alive():  # already running
            messagebox.showinfo("Kestrel", "Already running. Press Stop first.")  # say so
            return  # nothing to do
        if mode != "monitor" and not (self.call.get().strip() and self.grid.get().strip()):  # transmitting needs a callsign and a locator
            messagebox.showinfo("Kestrel", "Enter your callsign and grid locator first.")  # say so
            return  # nothing to do
        if mode != "monitor" and not messagebox.askokcancel("Kestrel", "This station will TRANSMIT on the radio's frequency. Continue?"):  # a last check before transmitting
            return  # the operator backed out
        self.worker = threading.Thread(target=self.run, args=(mode, self.prepare()), daemon=True)  # the working thread, with everything it needs
        self.worker.start()  # go

    def prepare(self):  # gather what the working thread needs (it must not read the window's controls itself)
        """Save the settings and return a dict of everything a run needs."""
        self.save_settings()  # remember the settings
        self.stop.clear()  # not stopping yet
        job = dict(self.settings)  # callsign, grid, level, rig address, keying method, port
        job["entry"] = self.selected()  # the frequency chosen
        job["in"] = device_named(self.audio_in.get(), "input") if self.audio_in.get() else None  # the input device, looked up by name at this moment
        job["out"] = device_named(self.audio_out.get(), "output") if self.audio_out.get() else None  # the output device, likewise
        job["messages"], self.outbox = self.outbox, []  # the queued messages now belong to this run
        return job  # ready for the working thread

    def stop_station(self):  # the Stop button
        self.stop.set()  # the working thread sees this within a tenth of a second
        self.say("stopping...")  # confirm

    def run(self, mode, job):  # the working thread: runs the monitor or the station
        source = rig = ptt = None  # nothing opened yet
        try:  # anything that goes wrong is reported in the log
            source = AudioIn(job["in"])  # start recording from the chosen device
            if mode == "monitor":  # receive only
                listener = Listener()  # the continuous receiver
                self.say("monitoring: receive only, nothing will be transmitted")  # opening line
                while not self.stop.is_set():  # until Stop
                    for heard in listener.feed(source.read()):  # every frame that has completed
                        self.say(f"{time.strftime('%H:%M:%S')}  {describe(heard.result)}")  # show it
                    time.sleep(0.1)  # a tenth of a second between looks
                return  # done
            if job["rig"]:  # rig control is set up
                rig = RigCtl(job["rig"])  # connect to rigctld
                self._tune(rig, job["entry"])  # go to the selected frequency
            ptt = Ptt(job["ptt"], job["port"] or None, rig=rig)  # the transmit switch
            sink = AudioOut(job["out"], float(job["gain"]))  # the playing side
            station = Station(job["call"], job["grid"])  # the link rules for this station
            station.beacon() if mode == "beacon" else station.listen()  # call, or wait to be called
            for text in job["messages"]:  # the queued messages
                station.queue(text)  # into the station's outbox
            run_station(station, source, sink, ptt, say=self.say, stay_on=(mode == "listen"), should_stop=self.stop.is_set)  # the live loop
            self.say(f"delivered {len(station.delivered)} message(s); {len(station.outbox)} still waiting")  # the outcome for sent traffic
            for text in station.inbox:  # everything received
                self.say(f"received: {text}")  # show it
        except Exception as problem:  # report any failure instead of dying silently
            self.say(f"stopped by a problem: {problem}")  # what went wrong
        finally:  # always tidy up
            if ptt is not None:  # a transmit switch was opened
                ptt.close()  # make sure the transmitter is off
            if rig is not None:  # rig control was opened
                rig.close()  # hang up
            if source is not None:  # recording was started
                source.close()  # release the sound device
            self.say("stopped")  # closing line

    def close(self):  # the window is being closed
        self.stop.set()  # stop the station
        self.save_settings()  # remember the settings
        self.root.destroy()  # close the window


def main():  # the script itself
    """Open the panel."""
    root = tk.Tk()  # the window
    Panel(root)  # its contents
    root.mainloop()  # run until closed


if __name__ == "__main__":  # only when run as a script
    main()  # go
