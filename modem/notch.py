"""Removing steady signals (carriers) from the whole Kestrel band before decoding.

A carrier sits on one frequency all the time; a Kestrel tone is on a
frequency for a fraction of a second, then moves. So a frequency whose
energy, even in its quietest tenth of the time, stands CARRIER_TIMES
above the rest of the band, and as far above the frequencies within
25 Hz of it, is something steady and narrow: a carrier, a birdie from
the radio or computer, or a narrow signal that does not move. Left in, it
both hides weak Kestrel tones near it and matches the signature patterns
by chance, giving false "possible Kestrel signature" reports. It is cut
out with a notch a few hertz wide. (The second test keeps a strong
Kestrel frame, which raises a whole stretch of the band, from being
mistaken for a row of carriers.)

The long beacon has done this for its own band (82 Hz, 137 Hz since 0.38) since spec 0.28
(longbeacon.clean). Since 0.31R1 every level gets it, over the whole band
any level can use (L4 is 1420 Hz wide, plus 50 Hz of frequency error).
"""

import numpy as np  # numerical arrays
from scipy.fft import next_fast_len  # a transform length that is quick to compute

from . import native  # the compiled library, used when present
from .params import FS  # sample rate

BLOCK = 4800  # analysis block: 0.4 s, giving 2.5 Hz frequency steps (one L0 tone length)
BAND_LOW_HZ = 700.0  # the lowest frequency looked at (L4's lowest tone is 790 Hz, less 50 Hz of error, less a margin)
BAND_HIGH_HZ = 2300.0  # the highest (L4's highest tone is 2210 Hz, plus the same)
CARRIER_TIMES = 4.0  # a frequency whose quietest-tenth energy is this many times the band's typical is steady (plain noise stays under 2)
LOCAL_STEPS = 10  # a steady signal must also stand out from the steps around it, this many either side (25 Hz): a carrier is narrow, while a strong Kestrel frame raises a whole stretch of the band
CARRIER_MOST = 24  # more steady steps than this (60 Hz in all) is no carrier but a strong wide signal, and nothing is removed
NOTCH_HALF_HZ = 1.25  # half the width of each notch, in hertz (half an analysis step either side of its center)
MIN_BLOCKS = 8  # fewer whole blocks than this is too little audio to tell steady from brief
NO_NOISE = 1e-13  # a band whose quiet level is below this share of its strongest energy has no noise floor at all (real audio, even 16-bit, never comes near: since 0.32)


def steady_bins(x):  # which analysis steps hold something steady
    """Return (first step of the band, indices of steady steps within the band) for the audio `x`, or (0, empty) when there is too little audio."""
    blocks = len(x) // BLOCK  # whole blocks in the audio
    if blocks < MIN_BLOCKS:  # too little audio
        return 0, np.zeros(0, dtype=int)  # nothing found
    bin_hz = FS / BLOCK  # one analysis step, in hertz
    low, high = int(BAND_LOW_HZ / bin_hz), int(BAND_HIGH_HZ / bin_hz)  # the band, in steps
    window = np.hanning(BLOCK)  # a smooth window, so a strong carrier does not spill into steps far from its own
    power = np.abs(np.fft.rfft(x[:blocks * BLOCK].reshape(blocks, BLOCK) * window, axis=1)[:, low:high]) ** 2  # the energy at each step, block by block
    typical = np.percentile(power, 10, axis=0)  # each step's energy in its quietest tenth of the time: high only if something is there nearly all the time
    local = np.array([np.median(typical[max(0, c - LOCAL_STEPS):c + LOCAL_STEPS + 1]) for c in range(len(typical))])  # each step's neighborhood, at its quietest
    if not np.median(typical) > NO_NOISE * float(np.max(power)):  # no noise floor at all: audio made without noise (a simulation), where every faint leak would look steady (since 0.32)
        return low, np.zeros(0, dtype=int)  # nothing is steady
    busy = np.flatnonzero((typical > CARRIER_TIMES * np.median(typical)) & (typical > CARRIER_TIMES * local))  # the steps occupied all the time, and narrowly
    return low, busy  # where the band starts, and the steady steps


def remove_steady(x):  # take steady signals out of the band
    """Return `x` with every steady signal in the Kestrel band notched out (and `x` itself when there is none)."""
    x = np.asarray(x, dtype=float)  # floating-point audio
    blocks = len(x) // BLOCK  # whole blocks in the audio
    if blocks < MIN_BLOCKS:  # too little audio to tell
        return x  # leave it
    size = next_fast_len(len(x), real=True)  # a length the whole-audio transform handles quickly
    done = native.remove_steady(x, BLOCK, BAND_LOW_HZ, BAND_HIGH_HZ, CARRIER_TIMES, LOCAL_STEPS, CARRIER_MOST, NOTCH_HALF_HZ, size)  # the compiled version, when the library is in use
    if done is not None:  # it was
        return done  # the same audio, to rounding
    low, busy = steady_bins(x)  # what is steady
    if len(busy) == 0 or len(busy) > CARRIER_MOST:  # nothing steady; or so much that it is a strong signal, which needs no help
        return x  # nothing to do
    spectrum = np.fft.rfft(x, size)  # the whole audio at once: very fine frequency steps
    per_hz = size / FS  # steps of that transform per hertz
    bin_hz = FS / BLOCK  # one analysis step, in hertz
    for number in busy:  # each steady step
        center = (low + number) * bin_hz  # its frequency
        spectrum[int((center - NOTCH_HALF_HZ) * per_hz):int((center + NOTCH_HALF_HZ) * per_hz) + 1] = 0.0  # cut it out
    return np.fft.irfft(spectrum, size)[:len(x)]  # back to audio
