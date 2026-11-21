"""The signal log: a detailed, machine-readable record of everything the receiver and transmitter do.

The logbook (logbook.py) is for people: one row per contact, message or
beacon. The signal log is for analysis and debugging afterwards. It is a
JSON Lines file per UTC day (one JSON object per line, easy to load into
Python, a spreadsheet or a database), in a "signal" folder beside the
logbook. Every line has:

    utc     the time it was written, ISO 8601 with milliseconds, UTC
    t       the same time as seconds since 1970
    event   what happened (the list below)

and the other fields that event carries. Times of signals are given as
sample numbers on the receive timeline (see recorder.TimedSource): sample
n arrived at t0 + n / 12000 seconds, and the same numbers place the
signal in the recordings (each "recording_file" line says which sample
a file starts at). Where the timeline is known, a "sig_utc" field gives
the signal's own time as well.

Events:

    session_start   a run began: mode, versions, the station's settings
    session_end     a run ended
    clock           every 10 minutes: sample number and wall-clock time together, to check the sound card's clock against the computer's
    audio           every minute: received audio level (RMS and peak, dBFS), sound-card dropouts, how many searches ran and the strongest candidate seen
    search          a preamble candidate that stood out (strength 6 or more): level, sample, audio offset, strength, which header copy was read, and the outcome of the body (logged once per signal, and again only if the outcome changes)
    rx              a frame taken from the stream: everything the receiver reported (level, type, SNR, fading, offset, drift, header copy, text, addresses ...), and, when the station decoded it again with an earlier copy combined, that result too
    near            a Kestrel signature heard whose header could not be read
    tx_start        the transmitter was keyed: frame kind, level, airtime, note, transmit drive and peak level, frequency
    tx_end          it was released
    tx_meter        the radio's meters during a transmission: power, ALC, SWR
    tune            the radio's frequency changed (or a move to a working frequency)
    link            a line from the link rules (lock, level changes, retries, release ...)
    note            anything else worth keeping (warnings, problems)
    recording_file  a recording file began, at this sample

With clips turned on, the audio of every frame and near miss is also saved
as a short WAV file in signal/clips/<date>/, named in the "clip" field,
so a single frame can be played back or decoded again without the hourly
recording.

Disk space. The log is off unless the operator turns it on. The text log
alone is small: a line a minute when the band is quiet, a few more for
each signal, typically a few megabytes a day, so day files are kept and
never removed by the program. Clips are larger (a long frame at L0 is
about 6 MB), so they are capped twice: folders older than KEEP_DAYS are
removed, and whenever the clips together pass CLIPS_MAX_MB the oldest are
removed until they are back under it. The full-time recordings
(recorder.py) are a separate setting and the largest of all, about 86 MB
an hour.

tools/signal_report.py reads these files and summarises them.
"""

import json  # one JSON object per line
import math  # tells numbers that are not finite
import os  # file paths
import shutil  # removes old clip folders
import threading  # the station's thread and the window's thread both write
import time  # dates and times
import wave  # clips are WAV files

import numpy as np  # numerical arrays

from modem.params import FS, SIGNAL_VERSION, SPEC_VERSION  # sample rate and the versions this program follows

MODES = ("off", "on", "clips")  # off; on; on, with each frame's audio saved too
SEARCH_MIN_QUALITY = 6.0  # a preamble candidate is logged only from this strength (noise alone stays below about 3.5)
QUALITY_MAX = 10000.0  # above this the strength measure has broken down (digital silence), so it is not logged
AUDIO_EVERY_S = 60.0  # how often the received audio level is logged
CLOCK_EVERY_S = 600.0  # how often the sample number and the clock are logged together
SEEN_FOR_S = 400.0  # how long a logged candidate is remembered, so it is not logged again every second (longer than the longest frame)
KEEP_DAYS = 14  # clip folders older than this are removed
CLIPS_MAX_MB = 500  # clips together are kept below this many megabytes: the oldest go first
CHECK_EVERY = 20  # the clips' total size is checked after this many new clips
RESULT_SKIP = ("body_llrs",)  # report fields that are not logged (soft bits: large, and of no use in a log)


def _plain(value):  # a value as JSON can hold it
    """Return `value` with numpy numbers made plain, and NaN or infinity made None."""
    if isinstance(value, dict):  # a dictionary
        return {str(key): _plain(item) for key, item in value.items()}  # each item
    if isinstance(value, (list, tuple)):  # a list
        return [_plain(item) for item in value]  # each item
    if isinstance(value, np.ndarray):  # an array
        return [_plain(item) for item in value.tolist()]  # as a list
    if isinstance(value, (np.integer,)):  # a numpy whole number
        return int(value)  # a plain one
    if isinstance(value, (float, np.floating)):  # a number with a fraction
        value = float(value)  # a plain one
        return round(value, 3) if math.isfinite(value) else None  # three places are plenty; NaN and infinity become null
    if isinstance(value, (bool, int, str)) or value is None:  # already plain
        return value  # as it is
    return str(value)  # anything else, as text


def result_fields(result):  # a receiver's report as a dictionary
    """Return the fields of an RxResult (modem.frame) as plain values, without the soft bits."""
    names = getattr(result, "__dataclass_fields__", {})  # the report's field names
    return {name: _plain(getattr(result, name)) for name in names if name not in RESULT_SKIP}  # every field but the soft bits


def utc_text(seconds):  # a time as text
    """Return `seconds` since 1970 as an ISO 8601 UTC time with milliseconds, e.g. 2026-11-21T16:40:05.123Z."""
    whole = int(seconds)  # the whole seconds
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(whole)) + f".{int((seconds - whole) * 1000):03d}Z"  # date, time, milliseconds


class SignalLog:  # writes the signal log
    """Call the methods below as things happen; each writes one line (or none, if the log is off)."""

    def __init__(self, folder, prefix="kestrel", mode="on", clock=time.time):  # set up
        self.folder = folder  # where the day files go
        self.prefix = prefix  # the start of each file's name (kestrel, or kestrel_<profile> for a second panel)
        self.mode = mode if mode in MODES else "on"  # off, on or clips
        self.clock = clock  # where the time comes from (a test can supply its own)
        self.lock = threading.Lock()  # one writer at a time
        self.timeline = None  # the TimedSource whose sample numbers the events use, once known
        self.seen = {}  # candidates already logged: (level, place) -> (outcome, sample)
        self.searches = 0  # searches since the last audio line
        self.best = 0.0  # the strongest candidate since the last audio line
        self.next_audio = 0.0  # when the next audio line is due
        self.next_clock = 0.0  # when the next clock line is due
        self.failures = 0  # lines that could not be written (a full or missing disk)
        self.pruned = False  # whether old clips have been looked for this run
        self.clips_max_mb = CLIPS_MAX_MB  # the cap on the clips' total size
        self.new_clips = 0  # clips saved since the size was last checked

    @property  # worked out when asked
    def on(self):  # is anything being logged?
        """True unless the log is turned off."""
        return self.mode != "off"  # anything but off

    def path(self, when=None):  # the day's file
        """Return the file for the UTC day of `when` (default: now)."""
        when = self.clock() if when is None else when  # the moment in question
        return os.path.join(self.folder, f"{self.prefix}_signal_{time.strftime('%Y-%m-%d', time.gmtime(when))}.jsonl")  # one file per UTC day

    def write(self, event, **fields):  # add one line
        """Write one line for `event` with `fields`; return the line as a dict, or None when the log is off or the disk refused."""
        if not self.on:  # turned off
            return None  # nothing written
        now = self.clock()  # the moment
        line = {"utc": utc_text(now), "t": round(now, 3), "event": event}  # the fields every line has
        line.update(_plain(fields))  # and this event's own
        with self.lock:  # one writer at a time
            try:  # the disk may refuse
                os.makedirs(self.folder, exist_ok=True)  # make sure the folder is there
                with open(self.path(now), "a", encoding="utf-8") as handle:  # append to the day's file
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")  # one line
            except OSError:  # a full or missing disk
                self.failures += 1  # count it; the station must keep running whatever happens to the log
                return None  # nothing written
        return line  # what was written

    def sig_utc(self, sample):  # when a numbered sample arrived, as text
        """Return the UTC time of stream sample `sample` as text, or None when the timeline is not known."""
        if self.timeline is None or sample is None or sample < 0:  # no timeline, or no sample
            return None  # cannot say
        seconds = self.timeline.utc_of(sample)  # from the timeline
        return None if seconds is None else utc_text(seconds)  # as text

    # --- runs -------------------------------------------------------------------------------------------

    def session_start(self, mode, timeline=None, **fields):  # a run began
        """Log the start of a run (`mode`: monitor or listen), with `fields` such as the callsign, frequency and settings."""
        self.timeline = timeline  # the sample numbers to use from now on
        self.seen.clear()  # nothing logged yet in this run
        self.searches, self.best = 0, 0.0  # fresh counts
        self.next_audio = self.next_clock = 0.0  # both lines due at once
        if self.mode == "clips" and not self.pruned:  # clips are being kept
            self.pruned = True  # once a run is enough
            self.prune_clips()  # remove old ones
        return self.write("session_start", mode=mode, signal_version=SIGNAL_VERSION, spec_version=SPEC_VERSION, sample_rate=FS, log_mode=self.mode, **fields)  # the line

    def session_end(self, **fields):  # a run ended
        """Log the end of a run."""
        line = self.write("session_end", sample=self._now_sample(), errors=self.failures, **fields)  # the line
        self.timeline = None  # no timeline until the next run
        return line  # what was written

    def _now_sample(self):  # the newest sample number
        """Return the number the next sample will get, or None when there is no timeline."""
        return None if self.timeline is None else self.timeline.samples  # from the timeline

    def tick(self, level=None, lost=None):  # called often, from the receiving loop
        """Write the audio line once a minute and the clock line every ten minutes. `level` is (RMS, peak) in dBFS; `lost` the sound card's dropout count."""
        if not self.on:  # turned off
            return  # nothing to do
        now = self.clock()  # the moment
        if now >= self.next_clock and self.timeline is not None and self.timeline.t0 is not None:  # the clock line is due, and there is a timeline
            self.next_clock = now + CLOCK_EVERY_S  # the next one
            sample = self.timeline.samples  # the newest sample number
            self.write("clock", sample=sample, sample_utc=self.sig_utc(sample), drift_s=round(now - self.timeline.utc_of(sample), 3))  # the sound card's clock against the computer's
        if now >= self.next_audio:  # the audio line is due
            self.next_audio = now + AUDIO_EVERY_S  # the next one
            rms, peak = level if level is not None else (None, None)  # the input level, if known
            self.write("audio", sample=self._now_sample(), rms_dbfs=rms, peak_dbfs=peak, lost=lost, searches=self.searches, best_quality=self.best)  # the line
            self.searches, self.best = 0, 0.0  # fresh counts

    # --- receiving ---------------------------------------------------------------------------------------

    def search(self, result, trace):  # a search of the store finished (Listener.on_search)
        """Log each candidate in `trace` that stood out, once per signal and again only if its outcome changes."""
        if not self.on:  # turned off
            return  # nothing to do
        self.searches += 1  # count it
        for step in trace:  # every candidate the receiver tried
            quality = step.get("quality", 0.0)  # how far it stood above the background
            if quality <= QUALITY_MAX:  # a real measurement
                self.best = max(self.best, quality)  # the strongest this minute
            if not SEARCH_MIN_QUALITY <= quality <= QUALITY_MAX:  # nothing stood out, or the measure broke down
                continue  # not logged
            sample = step.get("sample", -1)  # where it began in the stream
            from modem import LEVELS  # the speed levels (imported here: the log is often used without the modem loaded first)
            tone = LEVELS[step["level"]].samples  # one tone length at its level
            key = (step["level"], sample // (2 * tone))  # the same signal found again lands in the same place, give or take two tones
            outcome = (step.get("header", ""), step.get("ok"), step.get("reason"))  # what became of it
            known = self.seen.get(key) or self.seen.get((key[0], key[1] - 1)) or self.seen.get((key[0], key[1] + 1))  # logged already, here or in a neighbouring place
            if known is not None and known[0] == outcome:  # logged already, with the same outcome
                continue  # once is enough
            self.seen[key] = (outcome, sample)  # remember it
            self.write("search", sample=sample, sig_utc=self.sig_utc(sample), **{name: value for name, value in step.items() if name not in ("sample", "start")})  # the line
        newest = trace[-1]["sample"] if trace else None  # roughly where the stream is
        if newest is not None:  # forget candidates too old to come back
            for key in [key for key, (_, sample) in self.seen.items() if newest - sample > SEEN_FOR_S * FS]:  # older than the longest frame
                del self.seen[key]  # forget it

    def rx(self, heard, station_result=None, dial_khz=None):  # a frame taken from the stream
        """Log a frame the listener handed over (a Heard), with the station's own result when it decoded it again (combining an earlier copy)."""
        if not self.on:  # turned off
            return None  # nothing to do
        result = heard.result  # the listener's report
        fields = {"sample": result.sample, "sig_utc": self.sig_utc(result.sample), "dial_khz": dial_khz, "seconds": round(len(heard.audio) / FS, 2), "result": result_fields(result)}  # where, when and what
        if station_result is not None and (station_result.ok != result.ok or station_result.reason != result.reason):  # the station's decode differs (an earlier copy was combined)
            fields["station_result"] = result_fields(station_result)  # keep both
        fields["clip"] = self.clip(heard.audio, "ok" if result.ok else "fail", result.level, heard.audio_sample)  # the audio, if clips are kept
        return self.write("rx", **fields)  # the line

    def near(self, result, audio=None, audio_sample=-1, dial_khz=None):  # a signature that could not be read
        """Log a near miss; `audio`, if given, is saved as a clip."""
        if not self.on:  # turned off
            return None  # nothing to do
        clip = self.clip(audio, "near", result.seen_level, audio_sample) if audio is not None else None  # the audio, if clips are kept
        return self.write("near", sample=result.sample, sig_utc=self.sig_utc(result.sample), dial_khz=dial_khz, seen_level=result.seen_level, quality=result.sync_quality, offset_hz=result.offset_hz, clip=clip)  # the line

    # --- transmitting and the radio ----------------------------------------------------------------------

    def tx(self, tx, keyed, dial_khz=None, gain=None, peak_dbfs=None, power_w=None):  # the transmitter went on or off
        """Log the start (`keyed` True) or end of a transmission of `tx` (a link Transmission)."""
        event = "tx_start" if keyed else "tx_end"  # which
        return self.write(event, sample=self._now_sample(), kind=tx.kind, level=tx.level, seconds=round(tx.seconds, 2), note=tx.note, dial_khz=dial_khz, gain=gain, peak_dbfs=peak_dbfs, power_w=power_w)  # the line

    def meters(self, watts=None, alc=None, swr=None):  # the radio's meters during a transmission
        """Log one reading of the radio's meters."""
        if watts is None and alc is None and swr is None:  # nothing read
            return None  # nothing to log
        return self.write("tx_meter", power_w=watts, alc=alc, swr=swr)  # the line

    def tune(self, dial_khz, why=""):  # the radio's frequency changed
        """Log a change of frequency."""
        return self.write("tune", sample=self._now_sample(), dial_khz=dial_khz, why=why)  # the line

    def link(self, text):  # a line from the link rules
        """Log one of the station's own notes (lock, level changes, retries, release ...)."""
        return self.write("link", sample=self._now_sample(), text=text)  # the line

    def note(self, text, **fields):  # anything else
        """Log a warning, a problem or anything else worth keeping."""
        return self.write("note", sample=self._now_sample(), text=text, **fields)  # the line

    def recording_file(self, path, sample):  # a recording file began (Recorder.on_open)
        """Log where on the timeline a recording file begins."""
        return self.write("recording_file", file=os.path.basename(path), sample=sample, sig_utc=self.sig_utc(sample))  # the line

    # --- clips -------------------------------------------------------------------------------------------

    def clips_dir(self, when=None):  # the day's clip folder
        """Return the clip folder for the UTC day of `when` (default: now)."""
        when = self.clock() if when is None else when  # the moment in question
        return os.path.join(self.folder, "clips", time.strftime("%Y-%m-%d", time.gmtime(when)))  # one folder per UTC day

    def clip(self, audio, kind, level, sample=-1):  # save a frame's audio
        """Save `audio` as a 16-bit WAV clip when clips are kept; return its name relative to the log folder, or None."""
        if self.mode != "clips" or audio is None or len(audio) == 0:  # clips not wanted, or nothing to save
            return None  # nothing saved
        now = self.clock()  # the moment
        folder = self.clips_dir(now)  # the day's folder
        name = f"{time.strftime('%H%M%S', time.gmtime(now))}_{kind}_L{level}_s{max(sample, 0)}.wav"  # time, what it was, its level, where it began
        try:  # the disk may refuse
            os.makedirs(folder, exist_ok=True)  # make sure the folder is there
            with wave.open(os.path.join(folder, name), "wb") as handle:  # a new WAV file
                handle.setnchannels(1)  # mono
                handle.setsampwidth(2)  # 16-bit
                handle.setframerate(FS)  # 12,000 samples per second
                handle.writeframes((np.clip(np.asarray(audio, dtype=float), -1.0, 1.0) * 32767.0).astype("<i2").tobytes())  # the samples
        except OSError:  # a full or missing disk
            self.failures += 1  # count it
            return None  # nothing saved
        self.new_clips += 1  # count it
        if self.new_clips >= CHECK_EVERY:  # time to check the total size
            self.new_clips = 0  # start counting again
            self.prune_clips()  # keep under the cap
        return os.path.relpath(os.path.join(folder, name), self.folder).replace(os.sep, "/")  # its name, from the log folder

    def prune_clips(self, keep_days=KEEP_DAYS):  # remove old clips
        """Delete clip folders older than `keep_days`, then the oldest clips until all of them fit under the size cap; return how many folders and files were removed."""
        root = os.path.join(self.folder, "clips")  # where they are
        if not os.path.isdir(root):  # none yet
            return 0  # nothing to do
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(self.clock() - keep_days * 86400))  # the oldest day kept
        removed = 0  # how many folders went
        for name in sorted(os.listdir(root)):  # every day folder
            if len(name) == 10 and name < cutoff and os.path.isdir(os.path.join(root, name)):  # a day folder older than the cutoff
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)  # remove it
                removed += 1  # count it
        clips = []  # every clip left: (day, name, size, path)
        for day in sorted(os.listdir(root)):  # every day folder, oldest first
            folder = os.path.join(root, day)  # its path
            if os.path.isdir(folder):  # a folder
                for name in sorted(os.listdir(folder)):  # its clips, oldest first (names start with the time)
                    path = os.path.join(folder, name)  # the clip's path
                    clips.append((day, name, os.path.getsize(path), path))  # note it
        total, cap = sum(item[2] for item in clips), self.clips_max_mb * 1024 * 1024  # how much they take, and the most allowed
        for _, _, size, path in clips:  # oldest first
            if total <= cap:  # under the cap
                break  # done
            try:  # it may already be gone
                os.remove(path)  # remove it
                removed += 1  # count it
            except OSError:  # gone or locked
                pass  # carry on with the next
            total -= size  # that much less
        return removed  # how many
