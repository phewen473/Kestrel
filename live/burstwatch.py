"""Listening for an acknowledgment burst after a frame that awaits one (since 0.43).

The continuous receiver (live/listener.py) finds frames by their signature
pattern; an acknowledgment burst has none. It is 24 L0 tones in an order the
waiting station already knows (modem/burst.py), so after each frame that
awaits one (Transmission.listen) the runner keeps the audio that follows, and
once enough has arrived for the latest burst the partner could send, searches
it once. A recognized burst is handed to the station as an acknowledgment.
"""

import numpy as np  # numerical arrays

from modem.burst import BURST_EARLIEST_S, BURST_LATEST_S, BURST_TONES, SPEC, heard  # the burst and its search
from modem.params import FS  # sample rate

SEARCH_AT_S = BURST_LATEST_S + BURST_TONES * SPEC.seconds + 0.5  # the search runs once this much audio has come in after the frame (17.1 s): the latest burst, all of it, and a little over


class BurstWatch:  # waits for one burst at a time
    """Arm with a transmission that awaits a burst; feed it the audio received after it; check() hands back the burst, once, as an acknowledgment."""

    def __init__(self):  # nothing awaited
        """Start with nothing awaited."""
        self.listen = None  # what the burst could say (modem.burst.BurstSays), or None
        self.center_hz = 0.0  # where to look for it
        self.kept = []  # the audio received since the frame ended, in pieces
        self.count = 0  # samples kept

    def arm(self, tx):  # a frame has just been sent
        """Await the burst `tx` asks for (its listen and listen_hz), or nothing if it asks for none; the audio kept so far is dropped."""
        listen = getattr(tx, "listen", None)  # what it awaits
        self.listen = list(listen) if listen else None  # kept, or nothing awaited
        self.center_hz = float(getattr(tx, "listen_hz", 0.0) or 0.0)  # where to look
        self.kept, self.count = [], 0  # the clock starts now

    def disarm(self):  # the wait is over another way
        """Await nothing (a frame from the partner was read, the radio moved, or the station stopped)."""
        self.listen, self.kept, self.count = None, [], 0  # forgotten

    @property  # computed
    def waiting(self):  # is a burst awaited?
        """True while a burst is awaited."""
        return self.listen is not None  # armed

    def feed(self, chunk):  # audio received
        """Keep `chunk` (received audio) while a burst is awaited."""
        if self.listen is not None and len(chunk):  # awaited, and something arrived
            self.kept.append(np.asarray(chunk, dtype=np.float64))  # kept
            self.count += len(chunk)  # counted

    def check(self):  # the search, once enough audio is in
        """Return the burst as an acknowledgment (an RxResult with burst=True) once enough audio has come in and it is there; None otherwise. The wait ends at the search, found or not."""
        if self.listen is None or self.count < SEARCH_AT_S * FS:  # nothing awaited, or not yet
            return None  # nothing yet
        x = np.concatenate(self.kept)  # the audio since the frame
        listen, center = self.listen, self.center_hz  # what to look for, and where
        self.disarm()  # searched once only
        return heard(x, listen, int(BURST_EARLIEST_S * FS), int(BURST_LATEST_S * FS), center)  # recognized, or None
