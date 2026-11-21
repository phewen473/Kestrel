"""Listen before transmitting: is the frequency in use?

Before a station starts something nobody asked for (a beacon, a long
beacon, a directed call, a broadcast) it should know the frequency is
clear. The ChannelWatch here listens along with the receiver. It does not
need to know what a signal is: any energy standing well above the band's
own noise, in the part of the audio band the transmission would occupy,
counts as the frequency being in use.

How it decides. The received audio is cut into half-second blocks, and
the energy of each block is measured in strips 50 Hz wide from 300 to
2900 Hz. For each strip the noise floor is the level it stays above nine
tenths of the time over the last two minutes: other stations come and go,
the noise is always there. A strip is "occupied" in a block when its
energy is BUSY_TIMES that floor. The frequency is in use when, in the
last LOOK_S seconds, the strips the transmission would cover were
occupied BUSY_CELLS times or more.

Limits, by design: a signal weaker than about -10 dB (in 2.5 kHz) may not
be noticed; a signal that has been on without a break for the whole two
minutes becomes the "floor" and is not noticed either; and nothing is
heard while this station transmits. The operator remains responsible for
the frequency.
"""

import numpy as np  # numerical arrays

from modem.params import FS  # the modem's sample rate (12,000)

BLOCK_S = 0.5  # the audio is judged in blocks this long
STRIP_HZ = 50.0  # and in strips this wide
LOW_HZ, HIGH_HZ = 300.0, 2900.0  # the part of the audio band watched
KEEP_S = 120.0  # how much history the noise floor is taken from
FLOOR_PERCENT = 10  # the floor is the level a strip stays above nine tenths of the time
BUSY_TIMES = 4.0  # a strip this many times its floor is occupied (plain noise stays under 2)
LOOK_S = 2.0  # the frequency must have been clear for this long
BUSY_CELLS = 2  # this many occupied strip-blocks in that time means the frequency is in use
MIN_HISTORY_S = 8.0  # with less history than this the watch cannot judge, and says the frequency is clear
GUARD_HZ = 75.0  # the transmission's band is widened by this much each side


class ChannelWatch:  # watches the received audio for other signals
    """Feed it the received audio with feed(); ask busy(low_hz, high_hz) before transmitting."""

    def __init__(self):  # set up with no history
        self.block = int(BLOCK_S * FS)  # samples in a block
        self.pending = np.zeros(0)  # audio not yet making a whole block
        self.bins = np.fft.rfftfreq(self.block, 1.0 / FS)  # the frequency of each transform bin
        self.edges = np.arange(LOW_HZ, HIGH_HZ + STRIP_HZ, STRIP_HZ)  # the strips' edges
        self.history = []  # the energy in each strip, block by block, oldest first
        self.window = np.hanning(self.block)  # a smooth window, so a strong signal does not spill across the whole band

    def clear(self):  # forget everything (after this station transmits or retunes)
        """Drop the audio waiting to be judged and the recent blocks, keeping the noise floor's older history."""
        self.pending = np.zeros(0)  # nothing waiting
        look = int(LOOK_S / BLOCK_S)  # the blocks a busy check looks at
        self.history = self.history[:-look] if len(self.history) > look else []  # what was heard just before transmitting must not count as "now"

    def reset(self):  # a new frequency: nothing known about it
        """Forget everything, the noise floor included."""
        self.pending, self.history = np.zeros(0), []  # start again

    def feed(self, samples):  # take in received audio
        """Add `samples` (12,000 a second) and measure every whole block."""
        self.pending = np.concatenate([self.pending, np.asarray(samples, dtype=float)])  # add to what is waiting
        while len(self.pending) >= self.block:  # a whole block is there
            piece, self.pending = self.pending[:self.block], self.pending[self.block:]  # take it
            power = np.abs(np.fft.rfft(piece * self.window)) ** 2  # its energy at each frequency
            strips = np.add.reduceat(power, np.searchsorted(self.bins, self.edges[:-1]))  # summed into the strips (the last sum runs on past 2900 Hz and is dropped below)
            last = np.searchsorted(self.bins, self.edges[-1])  # where the watched band ends
            strips[-1] = power[np.searchsorted(self.bins, self.edges[-2]):last].sum()  # the last strip, ended properly
            self.history.append(strips)  # keep it
        self.history = self.history[-int(KEEP_S / BLOCK_S):]  # two minutes at most

    def levels(self):  # what the watch sees now
        """Return (strip edges in Hz, each strip's highest energy over the last LOOK_S seconds as a multiple of its floor), or None with too little history."""
        if len(self.history) * BLOCK_S < MIN_HISTORY_S:  # too little heard to judge
            return None  # cannot say
        table = np.array(self.history)  # blocks x strips
        floor = np.percentile(table, FLOOR_PERCENT, axis=0) + 1e-30  # each strip's noise floor
        recent = table[-int(LOOK_S / BLOCK_S):] / floor  # the last few blocks, against it
        return self.edges, recent  # for the caller to judge

    def busy(self, low_hz=500.0, high_hz=2500.0):  # is the frequency in use?
        """Return True when something other than noise has been heard between `low_hz` and `high_hz` (audio) in the last LOOK_S seconds."""
        seen = self.levels()  # the recent blocks against the floor
        if seen is None:  # too little history
            return False  # cannot judge: do not hold the station up
        edges, recent = seen  # the strips and their recent levels
        inside = (edges[1:] > low_hz - GUARD_HZ) & (edges[:-1] < high_hz + GUARD_HZ)  # the strips the transmission would touch
        return int((recent[:, inside] >= BUSY_TIMES).sum()) >= BUSY_CELLS  # occupied often enough to count


def band_of(level):  # the audio band a transmission at a level occupies
    """Return (low, high) in Hz of the tones of speed level `level` (the long beacon included)."""
    from modem.levels import LEVELS  # the speed levels
    from modem.longbeacon import LONG  # the long beacon's tones
    from modem.params import LONG_LEVEL  # the long beacon's level number
    spec = LONG if level == LONG_LEVEL else LEVELS[max(0, min(level, len(LEVELS) - 1))]  # the level's description
    tones = spec.tone_bins * spec.bin_hz  # its 32 tone frequencies
    return float(tones[0]), float(tones[-1])  # lowest and highest
