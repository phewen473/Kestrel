"""Recording the received audio to WAV files, so a session can be replayed and decoded later.

When an on-air test fails, the question is always the same: did the other
station's signal arrive at all, and if it did, why did it not decode? A
recording answers it. The panel can save everything the receiver hears
(after the sound card's rate has been converted to the modem's 12,000
samples per second) into ordinary 16-bit mono WAV files, one per hour,
in a "recordings" folder beside the logs. tools/decode_wav.py, or the
panel's File > Decode a recording, plays a file back through the same
receiver and lists every frame and every near miss.

Twelve thousand 16-bit samples a second is about 86 MB an hour, so
recordings older than KEEP_DAYS are removed when a new one starts.
"""

import os  # file paths and folder listings
import time  # file names carry the UTC time; old files are found by age
import wave  # Python's own WAV reader and writer

import numpy as np  # numerical arrays

from modem.params import FS  # the modem's sample rate (12,000)

FILE_SECONDS = 3600  # a new file is started every hour
KEEP_DAYS = 7  # recordings older than this are deleted when a new file starts
RESYNC_S = 0.05  # after a transmission, a sample count more than this far behind the clock is made good with silence (since 0.40R1)


def recordings_dir(base):  # where the recordings go
    """Return (creating it if needed) the "recordings" folder inside `base`."""
    folder = os.path.join(base, "recordings")  # beside the logs
    os.makedirs(folder, exist_ok=True)  # make sure it exists
    return folder  # the folder


def prune(folder, keep_days=KEEP_DAYS, now=None):  # remove old recordings
    """Delete Kestrel recordings in `folder` older than `keep_days`; return how many were removed."""
    now = time.time() if now is None else now  # the time to measure age from
    removed = 0  # count of files deleted
    for name in os.listdir(folder):  # every file in the folder
        path = os.path.join(folder, name)  # its full path
        if name.startswith("rx_") and name.endswith(".wav") and now - os.path.getmtime(path) > keep_days * 86400:  # one of ours, and old
            try:  # it may be open in another program
                os.remove(path)  # delete it
                removed += 1  # count it
            except OSError:  # it could not be removed
                pass  # leave it for next time
    return removed  # how many went


class Recorder:  # writes received audio to hourly WAV files
    """Call write(samples) with audio at 12,000 samples per second; close() when done."""

    def __init__(self, folder, label="", file_seconds=FILE_SECONDS, clock=time.time):  # set up, without opening a file yet
        self.folder = folder  # where the files go
        self.label = "".join(c if c.isalnum() else "_" for c in label)  # a safe piece of text for the file names (the callsign, say)
        self.file_seconds = file_seconds  # how long each file runs
        self.clock = clock  # where the time comes from (a test can supply its own)
        self.handle = None  # the WAV file now open, if any
        self.written = 0  # samples written to the open file
        self.path = ""  # the open file's name
        self.files = []  # every file this recorder has made
        self.total = 0  # samples written so far, across all files (the recording's own timeline)
        self.on_open = None  # if set, called with (path, sample) each time a file starts: sample is where it begins on that timeline

    def _open(self):  # start a new file
        stamp = time.strftime("%Y%m%d_%H%M%SZ", time.gmtime(self.clock()))  # UTC time, as in the logbook
        name = f"rx_{stamp}{'_' + self.label if self.label else ''}.wav"  # rx_20261121_153000Z_CALL.wav
        self.path = os.path.join(self.folder, name)  # where it goes
        count = 1  # how many files have wanted this name
        while os.path.exists(self.path) or self.path in self.files:  # a file of that name already exists (two files started in the same second)
            count += 1  # try the next number
            self.path = os.path.join(self.folder, name[:-4] + f"_{count}.wav")  # rx_..._CALL_2.wav, so nothing is overwritten
        self.handle = wave.open(self.path, "wb")  # open it for writing
        self.handle.setnchannels(1)  # mono
        self.handle.setsampwidth(2)  # 16-bit samples
        self.handle.setframerate(FS)  # 12,000 samples per second
        self.written = 0  # nothing in it yet
        self.files.append(self.path)  # remember it
        if self.on_open is not None:  # someone keeps a record of where each file starts
            self.on_open(self.path, self.total)  # tell them
        prune(self.folder)  # and tidy away old recordings

    def write(self, samples):  # add audio
        """Append `samples` (floats, full scale = 1.0, at 12,000 samples per second) to the recording."""
        samples = np.asarray(samples, dtype=float)  # make sure it is an array of numbers
        while len(samples):  # until all of it is written
            if self.handle is None:  # no file open
                self._open()  # start one
            room = self.file_seconds * FS - self.written  # samples this file can still take
            part, samples = samples[:room], samples[room:]  # what goes in this file, and what is left over
            pcm = (np.clip(part, -1.0, 1.0) * 32767.0).astype("<i2")  # 16-bit little-endian integers, clipped at full scale
            self.handle.writeframes(pcm.tobytes())  # into the file
            self.written += len(part)  # count them
            self.total += len(part)  # and on the whole timeline
            if self.written >= self.file_seconds * FS:  # the file is full
                self.close()  # finish it; the next write starts another

    def close(self):  # finish the open file
        """Close the file now being written, if any."""
        if self.handle is not None:  # one is open
            self.handle.close()  # finish it (this writes the WAV header's lengths)
            self.handle = None  # no file open now


class TimedSource:  # an audio source that keeps count of the samples read through it
    """Wraps a source with read() and flush() (see audio.AudioIn) and counts every sample that passes, so each sample has a number and a time.

    Sample number n arrived at about t0 + n / 12000 seconds (UTC, as from
    time.time()). The listener, the signal log and the recording all use
    these numbers, so an event in the signal log can be found in the
    recording and in the clock.
    """

    def __init__(self, source, clock=time.time):  # wrap a source
        self.source = source  # the real source
        self.clock = clock  # where the time comes from (a test can supply its own)
        self.samples = 0  # samples read so far: the number the next sample will get
        self.t0 = None  # the UTC time of sample 0, set by the first audio to arrive
        self.gaps = 0  # how many times the count was brought back in step with the clock (since 0.40R1)
        self.gap_s = 0.0  # seconds of audio that never arrived, in all (since 0.40R1)
        self.last_gap_s = 0.0  # the latest such stretch, in seconds (since 0.40R1)

    def _count(self, chunk):  # note audio that has passed through
        """Count `chunk` and, the first time, fix the time of sample 0."""
        if len(chunk) and self.t0 is None:  # the first audio of all
            self.t0 = self.clock() - len(chunk) / FS  # it began this long ago
        self.samples += len(chunk)  # count it

    def utc_of(self, sample):  # when a numbered sample arrived
        """Return the UTC time (seconds since 1970) of sample number `sample`, or None before any audio has arrived."""
        return None if self.t0 is None else self.t0 + sample / FS  # from the start time and the sample rate

    def read(self):  # collect audio, counting it
        """Return what the real source returns, after counting it."""
        chunk = self.source.read()  # the new audio
        self._count(chunk)  # count it
        return chunk  # and pass it on

    def flush(self):  # throw away audio received while transmitting, still counting it
        """Discard what the real source has collected, counting it so the numbers keep step with the clock."""
        self._count(self.source.read())  # take what has piled up and count it
        self.source.flush()  # and let the real source drop anything left
        self.resync()  # some sound cards deliver less audio than time passed while the transmitter was on: make the count good (since 0.40R1)

    def resync(self):  # bring the sample count back in step with the clock (since 0.40R1)
        """If the clock is more than RESYNC_S ahead of the samples counted, count the missing stretch as silence; return the seconds added (0.0 when in step).

        Called after a transmission, when what was received is thrown away
        and the listener starts afresh, so no frame is being followed
        across the join. Without it every transmission on some sound cards
        left the count a fraction of a second further behind the clock
        (5.9 s after 90 minutes in the November 24, 2026 on-air logs).
        """
        if self.t0 is None:  # no audio yet: nothing to compare
            return 0.0  # in step
        behind = (self.clock() - self.t0) - self.samples / FS  # how far the count is behind the clock, in seconds
        if behind <= RESYNC_S:  # within the usual wobble of blocks arriving
            return 0.0  # left alone
        missing = int(round(behind * FS))  # the samples that never came
        self._count(np.zeros(missing))  # counted (and recorded) as silence, so numbers, recording and clock agree again
        self.gaps += 1  # how many times this has been needed
        self.gap_s += behind  # and how much audio in all
        self.last_gap_s = behind  # the latest, for whoever reports it
        return behind  # the seconds made good

    def __getattr__(self, name):  # anything else (lost, level, spectrum, close ...) comes from the real source
        return getattr(self.source, name)  # look it up there


class RecordingSource(TimedSource):  # an audio source that records what passes through it
    """Wraps a source with read() and flush() (see audio.AudioIn): everything read is also written to a Recorder, and counted as TimedSource does."""

    def __init__(self, source, recorder, clock=time.time):  # wrap a source
        super().__init__(source, clock)  # counting, as TimedSource
        self.recorder = recorder  # where copies go

    def _count(self, chunk):  # note audio that has passed through
        """Count `chunk` and write it to the recording."""
        super()._count(chunk)  # count it
        if len(chunk):  # there is some
            self.recorder.write(chunk)  # record it, so the recording keeps the same unbroken timeline (audio heard while transmitting included)


def read_wav(path):  # load a recording for decoding
    """Return (samples at 12,000 per second as floats, seconds) from a WAV file of any common rate, width and channel count."""
    from scipy.signal import resample_poly  # rate conversion
    with wave.open(path, "rb") as handle:  # open the file
        channels, width, rate, count = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()  # its shape
        raw = handle.readframes(count)  # every sample
    if width == 1:  # 8-bit, unsigned
        data = (np.frombuffer(raw, dtype=np.uint8).astype(float) - 128.0) / 128.0  # to -1..1
    elif width == 2:  # 16-bit
        data = np.frombuffer(raw, dtype="<i2").astype(float) / 32768.0  # to -1..1
    elif width == 4:  # 32-bit integers
        data = np.frombuffer(raw, dtype="<i4").astype(float) / 2147483648.0  # to -1..1
    else:  # 24-bit and others
        raise ValueError(f"{width * 8}-bit WAV files are not supported; save it as 16-bit")  # say what to do
    if channels > 1:  # stereo or more
        data = data.reshape(-1, channels).mean(axis=1)  # mix down to one channel
    if rate != FS:  # not already at the modem's rate
        from math import gcd  # greatest common divisor, for the conversion ratio
        common = gcd(int(rate), FS)  # shared factor
        data = resample_poly(data, FS // common, int(rate) // common)  # convert to 12,000 samples per second
    return data, len(data) / FS  # the audio and its length in seconds
