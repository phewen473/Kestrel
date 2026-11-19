"""A receiver that listens continuously: audio goes in as it arrives, decoded frames come out.

The modem's receive() works on a finished recording. A live station has
no finished recording, only a stream. The Listener keeps the last 100
seconds of audio and looks through it once a second. When it finds a
whole frame it hands the frame over and cuts it out of its store, so
the same frame is never reported twice.
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from modem import LEVELS, MIN_SNR_DB, body_layout, control_layout, receive  # the speed levels, their limits, frame shapes and the receiver
from modem.frame import HEADER_SYMBOLS  # tones in a header
from modem.params import CONTROL_BITS, FS, PREAMBLE_TONES  # control frame types, the sample rate and the preamble's length in tones

WINDOW_S = 100.0  # how much audio is kept: longer than the longest frame (90 s)
STEP_S = 1.0  # how often the stored audio is searched
PAD_S = 0.5  # audio kept either side of a frame when it is handed over
FAILED_SNR_SLACK_DB = 4.0  # a frame that fails its check is only reported if its pilots read within this many dB of its level's limit


@dataclass  # a plain record
class Heard:  # one frame taken out of the stream
    """A frame the Listener found: the receiver's report, and the stretch of audio holding the frame."""

    result: object  # the receiver's report (an RxResult)
    audio: np.ndarray  # the frame's audio, with a little either side


def frame_samples(result):  # how long is the frame this report describes?
    """Return the length in samples of the frame whose header `result` came from."""
    if result.frame_type in CONTROL_BITS:  # a beacon, answer, acknowledgment or identification
        body = control_layout(result.frame_type)["total"]  # its body tones
    else:  # a message frame
        body = body_layout(result.size_class)["total"]  # its body tones
    return (PREAMBLE_TONES + HEADER_SYMBOLS + body) * LEVELS[result.level].samples  # preamble + header + body


class Listener:  # the continuous receiver
    """Feed it audio at 12,000 samples per second with feed(); it returns the frames that have completed."""

    def __init__(self, window_s=WINDOW_S, step_s=STEP_S):  # set up an empty store
        self.window = int(window_s * FS)  # most samples kept
        self.step = int(step_s * FS)  # new samples needed before the next search
        self.store = np.zeros(0)  # the audio kept so far
        self.fresh = 0  # samples added since the last search

    def clear(self):  # forget everything heard so far
        """Empty the store (used after transmitting, so the station does not decode itself)."""
        self.store = np.zeros(0)  # nothing kept
        self.fresh = 0  # nothing new

    def feed(self, samples):  # take in more audio
        """Add `samples` to the store and return a list of Heard frames that are now complete."""
        self.store = np.concatenate([self.store, np.asarray(samples, dtype=float)])[-self.window:]  # append, keep only the last 100 seconds
        self.fresh += len(samples)  # count the new audio
        if self.fresh < self.step:  # not enough new audio to be worth a search
            return []  # nothing yet
        self.fresh = 0  # start counting again
        found = []  # frames found in this search
        for _ in range(4):  # a search can turn up more than one frame; four is plenty
            heard = self._search()  # look for one whole frame
            if heard is None:  # none left
                break  # done
            found.append(heard)  # keep it
        return found  # everything that completed

    def _search(self):  # look for one whole frame in the store
        """Return a Heard for the strongest complete frame in the store, cutting it out; None if there is none."""
        if len(self.store) < FS:  # less than a second of audio: too little to be worth searching
            return None  # nothing to find
        result = receive(self.store)  # run the modem receiver over everything kept
        if result.level < 0:  # no header was read
            return None  # nothing there (or only noise)
        start = int(round(result.start))  # where the frame begins in the store
        end = start + frame_samples(result)  # where it ends
        if end > len(self.store):  # the frame is still arriving
            return None  # wait for the rest
        if not result.ok:  # the whole frame is here but it failed its check
            believable = np.isfinite(result.snr_db) and result.snr_db >= MIN_SNR_DB[result.level] - FAILED_SNR_SLACK_DB  # do its pilots look like a real signal?
            if result.reason != "body check failed" or not believable:  # noise that happened to pass a header check
                return None  # ignore it
        pad = int(PAD_S * FS)  # a little audio either side
        audio = self.store[max(start - pad, 0):end + pad].copy()  # the frame's own stretch of audio
        self.store = np.concatenate([self.store[:max(start, 0)], self.store[end:]])  # cut the frame out so it is not found again
        return Heard(result, audio)  # hand it over
