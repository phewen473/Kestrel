"""Sound-card input and output for a live Kestrel station.

The modem works at 12,000 samples per second. Sound cards prefer 48,000,
so audio is opened at 48,000 and converted by a factor of four each way.
The sounddevice package (PortAudio) does the actual input and output; it
is imported only when needed, so the rest of Kestrel runs without it.
"""

import queue  # hands audio from the sound card's thread to the main program

import numpy as np  # numerical arrays
from scipy.signal import firwin, lfilter, resample_poly  # filter design, filtering, and rate conversion

from modem.params import FS  # the modem's sample rate (12,000)

FACTOR = 4  # sound card rate divided by modem rate
LEAD_S = 0.3  # silence played before each transmission, so the sound card is running steadily before the chirp starts
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


class AudioIn:  # the receiving side of the sound card
    """Opens an input device and collects what it hears; read() returns everything new, at 12,000 samples per second."""

    def __init__(self, device=None):  # start recording
        import sounddevice as sd  # the sound-card library
        self.chunks = queue.Queue()  # audio waiting to be collected
        self.decimator = Decimator()  # the rate converter
        self.lost = 0  # how many times the sound card reported that it had to drop audio
        self.stream = sd.InputStream(samplerate=CARD_RATE, channels=1, dtype="float32", device=device, callback=self._arrived, latency="high")  # one channel, at the card's rate, with generous buffering so a busy program does not lose audio
        self.stream.start()  # begin recording

    def _arrived(self, data, frames, when, status):  # called by the sound card with each new block
        if status.input_overflow:  # the sound card had to throw audio away because it was not collected in time
            self.lost += 1  # count it, so the operator can be told
        self.chunks.put(data[:, 0].copy())  # keep the one channel

    def read(self):  # collect what has arrived
        """Return all audio received since the last call, at 12,000 samples per second."""
        blocks = []  # the blocks waiting
        while not self.chunks.empty():  # take them all
            blocks.append(self.chunks.get())  # oldest first
        if not blocks:  # nothing new
            return np.zeros(0)  # nothing back
        return self.decimator.process(np.concatenate(blocks))  # one stretch of audio, converted

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
        self.gain = gain  # how loud: 1.0 is full scale

    def play(self, audio):  # play and wait
        """Play `audio` (at 12,000 samples per second) and return when it has finished."""
        import sounddevice as sd  # the sound-card library
        padded = np.concatenate([np.zeros(int(LEAD_S * FS)), audio, np.zeros(int(TAIL_S * FS))])  # a little silence before, and more after
        sd.play(to_card_rate(padded, self.gain), CARD_RATE, device=self.device, blocking=True, latency="high")  # convert, play with generous buffering, wait for the end
