"""Sound-card input and output for a live Kestrel station.

The modem works at 12,000 samples per second. Sound cards prefer 48,000,
so audio is opened at 48,000 and converted by a factor of four each way.
The sounddevice package (PortAudio) does the actual input and output; it
is imported only when needed, so the rest of Kestrel runs without it.
"""

import queue  # hands audio from the sound card's thread to the main program
import threading  # a lock between the program and the sound card's output thread (since 0.41)
import time  # when a transmission began to play, for the transmit scope

import numpy as np  # numerical arrays
from scipy.signal import firwin, lfilter, resample_poly  # filter design, filtering, and rate conversion

from modem.params import FS  # the modem's sample rate (12,000)

FACTOR = 4  # sound card rate divided by modem rate
LEAD_S = 0.3  # silence played before each transmission, so the sound card is running steadily before the frame starts
TAIL_S = 0.5  # silence played after each transmission: sound cards stop a little early, and without this the last tones are cut off
CARD_RATE = FS * FACTOR  # the rate the sound card is opened at (48,000)


def list_devices():  # what sound devices does this computer have?
    """Return a list of (index, name, input channels, output channels) for every sound device."""
    import sounddevice as sd  # the sound-card library
    return [(i, d["name"], d["max_input_channels"], d["max_output_channels"]) for i, d in enumerate(sd.query_devices())]  # one entry per device


def find_device(wanted, kind):  # turn what the operator typed into a device number
    """Return the index of the device named by `wanted` (a number, or part of a name), or None for the system default.

    `kind` is "input" or "output"; only devices that can do that are considered.
    """
    if wanted is None or wanted == "":  # nothing asked for
        return None  # use the system default
    column = 2 if kind == "input" else 3  # which channel count to check
    usable = [d for d in list_devices() if d[column] > 0]  # devices that can do the job
    if str(wanted).isdigit():  # a device number
        if int(wanted) not in [d[0] for d in usable]:  # not a usable device
            raise ValueError(f"device {wanted} is not an {kind} device")  # say so
        return int(wanted)  # use it
    matches = [d for d in usable if str(wanted).lower() in d[1].lower()]  # devices whose name contains the text
    if not matches:  # none
        raise ValueError(f"no {kind} device has '{wanted}' in its name")  # say so
    return matches[0][0]  # the first match


def device_named(name, kind):  # find a device by its exact name
    """Return the index of the first input (or output) device called exactly `name`; raise ValueError if there is none."""
    column = 2 if kind == "input" else 3  # which channel count to check
    for device in list_devices():  # every device, in Windows' current numbering
        if device[1] == name and device[column] > 0:  # the right name and able to do the job
            return device[0]  # its number as of now
    raise ValueError(f"the {kind} device '{name}' is not connected")  # it has gone away


class Decimator:  # 48,000 samples per second down to 12,000, a chunk at a time
    """Low-pass filter and keep every fourth sample, remembering where it left off between chunks."""

    def __init__(self):  # set up the filter
        self.taps = firwin(129, 1.0 / FACTOR * 0.9)  # low-pass filter that removes everything above about 5.4 kHz
        self.state = np.zeros(len(self.taps) - 1)  # the filter's memory between chunks
        self.phase = 0  # how many samples into the next group of four the last chunk ended

    def process(self, chunk):  # convert one chunk
        """Return `chunk` (at 48,000 samples per second) converted to 12,000 samples per second."""
        if len(chunk) == 0:  # nothing to do
            return np.zeros(0)  # nothing back
        smooth, self.state = lfilter(self.taps, 1.0, chunk, zi=self.state)  # filter, carrying the memory forward
        out = smooth[(-self.phase) % FACTOR::FACTOR]  # every fourth sample, continuing the pattern from the last chunk
        self.phase = (self.phase + len(chunk)) % FACTOR  # remember where this chunk ended
        return out  # the converted audio


def to_card_rate(audio, gain=0.5):  # 12,000 samples per second up to 48,000, ready to play
    """Return `audio` converted to the sound card's rate and scaled by `gain` (1.0 is full scale)."""
    return (gain * resample_poly(audio, FACTOR, 1)).astype(np.float32)  # four times as many samples, as 32-bit floats


SCOPE_SAMPLES = 16384  # how much recent audio the scope looks at (a third of a second at the card's rate: frequency steps of 2.9 Hz, fine enough to separate the slowest level's tones)
CLIP_LEVEL = 0.98  # a sample this close to full scale means the input is being driven too hard


def level_dbfs(samples):  # how loud a stretch of audio is
    """Return (RMS level, peak level) of `samples` in dB relative to full scale (0 dBFS is the loudest the sound card can record)."""
    if len(samples) == 0:  # nothing to measure
        return -120.0, -120.0  # silence
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))  # the average power, as an amplitude
    peak = float(np.max(np.abs(samples)))  # the largest sample
    return 20.0 * np.log10(max(rms, 1e-6)), 20.0 * np.log10(max(peak, 1e-6))  # both in decibels, floored at -120


SCOPE_LONG = 65536  # the longer stretch used when the scope is zoomed in (1.4 seconds: frequency steps of 0.73 Hz, fine enough to separate the long beacon's tones)
SCOPE_ZOOM_HZ = 600.0  # a view this narrow or narrower uses the longer stretch


def scope_length(low_hz, top_hz):  # how much audio a view of this width should be made from
    """Return the number of samples at the card's rate that a scope showing `low_hz` to `top_hz` should use."""
    return SCOPE_LONG if top_hz - low_hz <= SCOPE_ZOOM_HZ else SCOPE_SAMPLES  # the longer stretch for a narrow view, where finer frequency steps are worth the slower response


def scope_spectrum(samples, rate=CARD_RATE, top_hz=3000.0, points=512, low_hz=0.0):  # the spectrum a scope display draws
    """Return `points` levels in decibels covering `low_hz` to `top_hz`, from a stretch of audio at `rate` samples per second.

    The audio is windowed so that a strong tone does not smear across the
    display, and the levels are relative to full scale.
    """
    window = np.hanning(len(samples))  # a smooth window
    power = np.abs(np.fft.rfft(samples * window)) ** 2 / (np.sum(window) ** 2 / 4.0)  # power at each frequency, where a full-scale tone reads 1
    hz = np.arange(len(power)) * rate / len(samples)  # the frequency of each bin
    wanted = np.linspace(low_hz, top_hz, points)  # the frequencies the display shows
    half = 0.5 * (top_hz - low_hz) / (points - 1)  # half the width one point covers
    first, inside = int(np.searchsorted(hz, low_hz - half)), int(np.searchsorted(hz, top_hz + half))  # the bins that lie within the display
    if inside - first > points:  # more bins than points: each point shows the strongest bin it covers, so a narrow tone is never lost between two points
        edges = np.clip(np.searchsorted(hz, wanted - half), first, inside - 1)  # the first bin each point covers
        return 10.0 * np.log10(np.maximum.reduceat(power[:inside], edges) + 1e-12)  # the strongest in each span, in decibels
    return 10.0 * np.log10(np.interp(wanted, hz, power) + 1e-12)  # fewer bins than points: the level at each, read between bins, in decibels


class AudioIn:  # the receiving side of the sound card
    """Opens an input device and collects what it hears; read() returns everything new, at 12,000 samples per second."""

    def __init__(self, device=None):  # start recording
        import sounddevice as sd  # the sound-card library
        self.chunks = queue.Queue()  # audio waiting to be collected
        self.decimator = Decimator()  # the rate converter
        self.lost = 0  # how many times the sound card reported that it had to drop audio
        self.recent = np.zeros(SCOPE_LONG, dtype="float32")  # the newest audio at the card's rate, for a scope display (enough for a zoomed-in view)
        self.clips = 0  # how many blocks have had a sample at or near full scale (the input is being overdriven)
        self.stream = sd.InputStream(samplerate=CARD_RATE, channels=1, dtype="float32", device=device, callback=self._arrived, latency="high")  # one channel, at the card's rate, with generous buffering so a busy program does not lose audio
        self.stream.start()  # begin recording

    def _arrived(self, data, frames, when, status):  # called by the sound card with each new block
        if status.input_overflow:  # the sound card had to throw audio away because it was not collected in time
            self.lost += 1  # count it, so the operator can be told
        self.chunks.put(data[:, 0].copy())  # keep the one channel
        if np.max(np.abs(data[:, 0])) >= CLIP_LEVEL:  # a sample reached full scale
            self.clips += 1  # count it, so the level meter can show CLIP
        self.recent = np.concatenate((self.recent, data[:, 0]))[-SCOPE_LONG:]  # and keep the newest stretch for the scope, whether or not anyone collects the rest

    def read(self):  # collect what has arrived
        """Return all audio received since the last call, at 12,000 samples per second."""
        blocks = []  # the blocks waiting
        while not self.chunks.empty():  # take them all
            blocks.append(self.chunks.get())  # oldest first
        if not blocks:  # nothing new
            return np.zeros(0)  # nothing back
        return self.decimator.process(np.concatenate(blocks))  # one stretch of audio, converted

    def spectrum(self, top_hz=3000.0, points=512, low_hz=0.0):  # what a scope display should draw right now
        """Return the spectrum of the newest audio: `points` levels in decibels from `low_hz` to `top_hz`."""
        return scope_spectrum(self.recent[-scope_length(low_hz, top_hz):], CARD_RATE, top_hz, points, low_hz)  # from the audio kept for the purpose, more of it for a narrow view

    def level(self):  # how loud the input is right now
        """Return (RMS, peak) in dBFS of the newest tenth of a second of input, before any processing."""
        return level_dbfs(self.recent[-CARD_RATE // 10:])  # the last 4800 samples

    def flush(self):  # throw away what has arrived
        """Discard everything received so far (used after transmitting)."""
        while not self.chunks.empty():  # until the queue is empty
            self.chunks.get()  # drop a block

    def close(self):  # stop recording
        """Stop and close the input device."""
        self.stream.stop()  # stop
        self.stream.close()  # release the device


class AudioOut:  # the transmitting side of the sound card
    """Plays audio on an output device."""

    def __init__(self, device=None, gain=0.5):  # remember the device and the level
        self.device = device  # which output device
        self.gain = gain  # how loud: 1.0 is full scale (may be changed between transmissions, by the panel's slider)
        self.playing = False  # True while a transmission is being played
        self.last_peak_db = -120.0  # the peak level of the last transmission, in dBFS
        self.sending = None  # the audio now being played, at the card's rate, for a transmit scope
        self.started = 0.0  # when it began to play (time.monotonic)
        self.cut = False  # set by abort(): the transmission under way stops at once
        self.stream = None  # the output stream, opened at the first transmission and kept open until close() (since 0.41)
        self.lock = threading.Lock()  # guards the hand-over of audio between play() and the sound card's thread (since 0.41)
        self.queued = None  # the audio the stream is playing, at the card's rate (since 0.41)
        self.at = 0  # how many of its samples the sound card has taken so far (since 0.41)
        self.persistent = True  # keep one stream open; set False to open a fresh stream for every transmission, as before 0.41

    def _open(self):  # open the output stream once, and keep it (since 0.41)
        """Open the output stream if it is not open. Opening and closing a stream for every transmission made some
        USB radio sound cards drop received audio on the shared input (up to 5.9 s in 90 minutes in the November 24,
        2026 logs), so the stream now stays open, playing silence between transmissions."""
        if self.stream is not None:  # already open
            return  # nothing to do
        import sounddevice as sd  # the sound-card library
        self.stream = sd.OutputStream(samplerate=CARD_RATE, channels=1, dtype="float32", device=self.device, callback=self._feed, latency="high")  # one channel at the card's rate, fed by _feed, with generous buffering
        self.stream.start()  # running from now on: silence until there is something to send

    def _feed(self, out, frames, when, status):  # called by the sound card whenever it wants more audio (since 0.41)
        """Fill `out` with the next stretch of the transmission, or with silence when nothing is being sent."""
        with self.lock:  # play() and abort() change the audio from another thread
            audio, at = self.queued, self.at  # what is playing and how far it has got
            if audio is None:  # nothing to send
                out.fill(0.0)  # silence
                return  # done
            piece = audio[at:at + frames]  # the next stretch
            out[:len(piece), 0] = piece  # into the sound card's buffer
            out[len(piece):, 0] = 0.0  # silence after the end
            self.at = at + len(piece)  # how far it has got now
            if self.at >= len(audio):  # all of it handed over
                self.queued = None  # nothing more to send

    def close(self):  # stop the output (since 0.41)
        """Stop and close the output stream, if open. Safe to call more than once."""
        stream, self.stream = self.stream, None  # take it, so a second call does nothing
        if stream is not None:  # one was open
            try:  # the device may already have gone
                stream.stop()  # stop
                stream.close()  # release the device
            except Exception:  # a sound-card error on the way out
                pass  # nothing more can be done about it

    def spectrum(self, top_hz=3000.0, points=512, low_hz=0.0):  # what is going out right now, for a transmit scope
        """Return the spectrum of the audio being played at this moment (`points` levels in dBFS from `low_hz` to `top_hz`), or None when nothing is playing."""
        length = scope_length(low_hz, top_hz)  # how much audio this view is made from
        samples = self.sending  # the transmission under way, if any
        if not self.playing or samples is None:  # nothing is being sent
            return None  # nothing to show
        at = int((time.monotonic() - self.started) * CARD_RATE)  # roughly how far the sound card has got (it runs a little behind this)
        piece = np.asarray(samples[max(0, at - length):max(at, 1)], dtype=float).reshape(-1)  # the newest stretch sent
        if len(piece) < length:  # the very start, or past the end
            piece = np.concatenate([np.zeros(length - len(piece)), piece])  # pad with silence
        return scope_spectrum(piece, CARD_RATE, top_hz, points, low_hz)  # the same measure the receive scope uses

    def play(self, audio):  # play and wait
        """Play `audio` (at 12,000 samples per second) and return when it has finished."""
        import sounddevice as sd  # the sound-card library
        padded = np.concatenate([np.zeros(int(LEAD_S * FS)), audio, np.zeros(int(TAIL_S * FS))])  # a little silence before, and more after
        samples = to_card_rate(padded, self.gain)  # converted and scaled
        self.last_peak_db = level_dbfs(samples)[1]  # how close to full scale it goes, for the transmit meter
        self.sending, self.started = samples, time.monotonic()  # let a transmit scope follow it
        self.playing, self.cut = True, False  # the transmission is on its way, not cut short
        if self.persistent:  # the stream kept open between transmissions (since 0.41)
            try:  # whatever happens...
                self._open()  # open it the first time
                with self.lock:  # hand the audio to the sound card's thread
                    self.queued, self.at = samples, 0  # from the start
                while not self.cut:  # until the operator stops it, or it has all gone
                    with self.lock:  # look at how far the sound card has got
                        done = self.queued is None  # all of it handed over
                    if done:  # yes
                        break  # stop looking
                    time.sleep(0.02)  # look fifty times a second
                if self.cut:  # stopped by the operator
                    with self.lock:  # take the rest back
                        self.queued = None  # silence from the next buffer on (the caller then takes the transmitter off)
                else:  # it ran to its end
                    time.sleep(self.stream.latency)  # the last buffer handed over is still in the sound card: let it play out before the transmitter comes off
            finally:  # ...note that it has ended
                self.playing, self.cut = False, False  # no longer playing, and ready for the next transmission
            return  # done
        try:  # whatever happens... (a fresh stream for every transmission, as before 0.41)
            sd.play(samples, CARD_RATE, device=self.device, blocking=False, latency="high")  # start playing, with generous buffering
            stream = sd.get_stream()  # the stream it plays on
            while stream.active and not self.cut:  # until it ends, or the operator stops it
                time.sleep(0.02)  # look fifty times a second
            if self.cut:  # stopped by the operator
                sd.stop()  # silence at once (the caller then takes the transmitter off)
            else:  # it ran to its end
                sd.wait()  # tidy up, and pass on any sound-card error
        finally:  # ...note that it has ended
            self.playing, self.cut = False, False  # no longer playing, and ready for the next transmission

    def abort(self):  # the operator stops the transmission on the air (safe to call from any thread)
        """Cut the transmission now being played short; play() then returns and the transmitter comes off."""
        if self.playing:  # something is going out
            self.cut = True  # play() stops it within a fiftieth of a second
