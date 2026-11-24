"""Power steps before a beacon (signal version 0.38): four tones at falling power, so a listener can see its margin.

Like the NCDXF beacons' dashes at 100, 10, 1 and 0.1 W, a station may send,
just before a beacon, four steady tones at the center of the band, each a
tenth of the power of the one before:

    step 0 dB | gap | step -10 dB | gap | step -20 dB | gap | step -30 dB | gap | the beacon

    each step 1 s, each gap 0.25 s: 5 s in all, at CENTER_HZ (1500 Hz).

Step 0 has the beacon's own amplitude, so on a linear transmitter it
arrives at the beacon's strength, and each later step 10 dB weaker. The
beacon's header says the steps came (its spare bit set), so a receiver
that decodes the beacon looks back in the audio it keeps and measures
each step: how far it stood above the noise, as SNR in 2.5 kHz like every
other reading, and which steps were heard at all. The differences between
steps also show whether the sending station's power really fell 10 dB a
step: a transmitter driven into its ALC flattens them.

The steps go before the beacon, not after it, so a station answering the
beacon keeps the reply slots it has always used.
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from .params import CENTER_HZ, FS, REF_BANDWIDTH_HZ  # the band's center, the sample rate and the 2.5 kHz reference

STEP_DB = (0.0, -10.0, -20.0, -30.0)  # each step's power against the beacon's, in dB
STEP_S = 1.0  # each step lasts this long
GAP_S = 0.25  # with this much quiet after it
RAMP_S = 0.02  # each step fades in and out over this long, so it does not click
SECONDS = len(STEP_DB) * (STEP_S + GAP_S)  # the whole sounding: 5 s
SAMPLES = int(round(SECONDS * FS))  # and in samples
READ_S = 0.8  # the middle 0.8 s of each step is measured (timing may be a little off)
SEARCH_HZ = 1.5  # the step's tone is looked for this far either side of where the beacon's frequency error puts it
NOISE_NEAR_HZ = 6.0  # the noise is measured from this far away...
NOISE_FAR_HZ = 60.0  # ...to this far, either side of the tone
HEARD_DB = 8.0  # a step whose tone stands this many dB above the noise in its own bin is heard (plain noise reaches it about once in a thousand)
EVEN_DB = (7.0, 13.0)  # steps that fall between these many dB apart are even: the transmitter's power followed the drive


@dataclass  # a plain record
class Reading:  # what a receiver read of the power steps
    """One reading of a station's power steps."""

    snr_db: tuple  # each step's strength as SNR in 2.5 kHz (NaN when not heard)
    heard: tuple  # whether each step was heard
    apart_db: tuple  # how far apart each pair of neighboring steps, both clearly heard, measured (dB)
    lowest_db: float  # the weakest step heard, in dB against the beacon (NaN when none)
    even: object  # True when the steps fell evenly (about 10 dB each), False when not, None when too few were heard to tell

    def describe(self):  # one line for the operator
        """Return the reading in a few words: each step's strength, then how evenly they fell."""
        parts = [f"{db:+.0f} dB {'at ' + format(snr, '+.0f') + ' dB' if ok else 'not heard'}" for db, snr, ok in zip(STEP_DB, self.snr_db, self.heard)]  # each step
        if self.even is True:  # about 10 dB apart
            tail = f"steps {', '.join(f'{a:.1f}' for a in self.apart_db)} dB apart: power follows the drive"  # good
        elif self.even is False:  # not
            tail = f"steps {', '.join(f'{a:.1f}' for a in self.apart_db)} dB apart: uneven (transmitter in ALC, or fading)"  # a warning
        else:  # too few
            tail = "too few steps heard to judge how evenly they fall"  # said
        return "power steps: " + "; ".join(parts) + f"  ({tail})"  # the line


def build_steps(amplitude=1.0):  # the transmitter's part
    """Return the audio of the four steps and their gaps (5 s), the first step at `amplitude` (the beacon's own: 1.0 as modem/mfsk.py sends it)."""
    n_step, n_gap, ramp = int(round(STEP_S * FS)), int(round(GAP_S * FS)), int(round(RAMP_S * FS))  # lengths in samples
    t = np.arange(n_step) / FS  # time within a step
    edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # a smooth rise from 0 to 1
    shape = np.ones(n_step)  # the step's envelope
    shape[:ramp], shape[-ramp:] = edge, edge[::-1]  # faded in and out
    tone = np.cos(2 * np.pi * CENTER_HZ * t) * shape  # one step at full size
    pieces = []  # the steps and gaps, in order
    for db in STEP_DB:  # each step
        pieces += [amplitude * 10.0 ** (db / 20.0) * tone, np.zeros(n_gap)]  # the step at its power, then quiet
    return np.concatenate(pieces)  # the sounding


def measure(x, frame_start, offset_hz=0.0):  # the receiver's part
    """Return a Reading of the steps that end where the beacon starts, at sample `frame_start` of `x`; None when `x` does not reach back far enough.

    `offset_hz` is the beacon's frequency error (the steps are sent at
    CENTER_HZ, so they arrive that far off too).
    """
    first = int(round(frame_start)) - SAMPLES  # where the first step began
    if first < 0:  # the audio kept does not reach back that far
        return None  # nothing to read
    n_read = int(round(READ_S * FS))  # samples measured per step
    window = np.hanning(n_read)  # a smooth window keeps strong steps from spilling over the noise bins
    bin_hz = FS / n_read  # the width of each bin
    enbw = 1.5 * bin_hz  # the window's noise bandwidth (Hann: 1.5 bins)
    freqs = np.arange(n_read // 2 + 1) * bin_hz  # each bin's frequency
    target = CENTER_HZ + offset_hz  # where the tone should be
    near = np.abs(freqs - target) <= SEARCH_HZ  # bins that may hold it
    away = np.abs(freqs - target)  # each bin's distance from it
    noise_bins = (away >= NOISE_NEAR_HZ) & (away <= NOISE_FAR_HZ)  # bins for the noise, clear of the tone
    lead = int(round((STEP_S - READ_S) / 2 * FS))  # the part of each step skipped at its start
    snrs, heard = [], []  # the readings
    for k in range(len(STEP_DB)):  # each step
        begin = first + int(round(k * (STEP_S + GAP_S) * FS)) + lead  # its middle part
        piece = x[begin:begin + n_read]  # the audio
        if len(piece) < n_read:  # cut short
            return None  # cannot read
        power = np.abs(np.fft.rfft(piece * window)) ** 2  # its spectrum
        noise = float(np.median(power[noise_bins])) / np.log(2)  # the mean noise per bin (exponentially spread noise has median = mean x ln 2)
        peak = float(np.max(power[near])) if np.any(near) else 0.0  # the strongest bin where the tone should be
        in_bin = peak / noise - 1.0 if noise > 0 else 0.0  # the tone's power against the noise in one bin
        loud = noise > 0 and 10 * np.log10(max(peak / noise, 1e-12)) >= HEARD_DB  # heard?
        snr = 10 * np.log10(max(in_bin, 1e-12)) - 10 * np.log10(REF_BANDWIDTH_HZ / enbw)  # as SNR in 2.5 kHz
        snrs.append(float(snr) if loud else float("nan"))  # kept
        heard.append(bool(loud))  # and whether it was heard
    clear = [ok and np.isfinite(s) and s - (HEARD_DB - 10 * np.log10(REF_BANDWIDTH_HZ / enbw)) >= 3.0 for s, ok in zip(snrs, heard)]  # steps heard with 3 dB to spare: fit to compare
    apart = tuple(round(snrs[k] - snrs[k + 1], 1) for k in range(len(STEP_DB) - 1) if clear[k] and clear[k + 1])  # differences of neighboring clear steps
    even = None if not apart else all(EVEN_DB[0] <= a <= EVEN_DB[1] for a in apart)  # even, uneven, or cannot tell
    lowest = min((db for db, ok in zip(STEP_DB, heard) if ok), default=float("nan"))  # the weakest step heard
    return Reading(tuple(snrs), tuple(heard), apart, float(lowest), even)  # the reading
