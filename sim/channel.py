"""HF channel simulator: makes a clean signal sound like it crossed a real HF path.

It can add:
  * noise at a chosen signal-to-noise ratio (SNR, quoted in 2.5 kHz like WSJT-X),
  * fading and multipath (the Watterson two-path model used in ITU-R F.1487),
  * a frequency offset and a steady frequency drift,
  * static crashes (short, very loud bursts).
The noise can be the simulator's own white noise, or real band noise cut from
the operator's own receive recordings (a noise pool, since 0.43, see
NoisePool and tools/make_noise_pool.py): real band noise has measured about
1 to 1.5 dB harder on Kestrel frames than white noise of the same power.
Every random choice comes from a seeded generator, so any test can be repeated exactly.
"""

import glob  # finds the noise pool's stretch files
import os  # file paths

import numpy as np  # numerical arrays
from scipy.fft import next_fast_len  # finds a nearby length the FFT handles quickly
from scipy.signal import hilbert  # builds the complex (analytic) form of a real signal

FS = 12000  # audio sample rate, in samples per second
REF_BANDWIDTH_HZ = 2500.0  # bandwidth that SNR figures are quoted in

CONDITIONS = {  # named channel conditions: (Doppler spread in Hz, delay between paths in ms), all from ITU-R F.1487 Annex 3
    "awgn": None,  # noise only: no fading at all
    "good": (0.1, 0.5),  # mid-latitude quiet (sky wave, the old names kept for the existing tools)
    "moderate": (0.5, 1.0),  # mid-latitude moderate
    "poor": (1.0, 2.0),  # mid-latitude disturbed
    "nvis": (1.0, 7.0),  # mid-latitude disturbed, near vertical incidence (short sky-wave hops on 80 and 40 m): the longest echo a mid-latitude station meets
    "low_quiet": (0.5, 0.5),  # low latitude, quiet (for paths towards the tropics)
    "low_moderate": (1.5, 2.0),  # low latitude, moderate
    "low_disturbed": (10.0, 6.0),  # low latitude, disturbed
    "high_quiet": (0.5, 1.0),  # high latitude, quiet (for paths across the auroral zone)
    "high_moderate": (10.0, 3.0),  # high latitude, moderate
    "high_disturbed": (30.0, 7.0),  # high latitude, disturbed
    "nvis_real": (0.3, 0.8),  # realistic near vertical incidence (since 0.34R1, not in F.1487): measured NVIS delay spreads are about 0.3 ms with peaks near 3 ms, and quiet mid-latitude Doppler spreads 0.03-0.3 Hz; second path weaker and shifted, see PATH_EXTRAS
    "dawn": (0.5, 1.0),  # mid-latitude moderate at sunrise or sunset (since 0.34R1): the two paths' frequencies move apart as the layers rise or fall, see PATH_EXTRAS
}  # end of the table

PATH_EXTRAS = {  # what F.1487 leaves out (since 0.34R1): condition -> (second path's power in dB against the first, second path's frequency shift in Hz against the first)
    "nvis_real": (-4.0, 0.2),  # the second path (another hop or magneto-ionic mode) 4 dB weaker and 0.2 Hz away
    "dawn": (-3.0, 0.3),  # the paths 0.3 Hz apart while the layers move
}  # end of the table (every other condition: equal paths, no shift between them, as F.1487)

SKYWAVE = ("good", "moderate", "poor", "nvis")  # the sky-wave conditions a mid-latitude station (the south-eastern United States) meets on its own paths, mildest first (the F.1487 set; "nvis_real" and "dawn" are the realistic additions of 0.34R1)


def _analytic(x):  # real signal -> complex signal
    """Return the complex (analytic) form of `x`, which lets us fade and shift it cleanly."""
    return hilbert(x, N=next_fast_len(len(x)))[:len(x)]  # pad to a fast length, convert, trim back


def _fading_tap(n, spread_hz, rng, fs):  # one path's slowly wandering gain
    """Return `n` complex gain values that wander at the given Doppler spread, with average power 1."""
    if spread_hz <= 0:  # no spread means a fixed path
        return np.full(n, np.exp(2j * np.pi * rng.random()))  # constant gain with a random phase
    nfast = next_fast_len(n)  # a length the FFT handles quickly
    freqs = np.fft.fftfreq(nfast, 1 / fs)  # frequency of every FFT bin
    sigma = spread_hz / 2  # the standard defines spread as twice the Gaussian width
    shape = np.exp(-freqs ** 2 / (4 * sigma ** 2))  # Gaussian-shaped filter (square root of the wanted spectrum)
    white = rng.standard_normal(nfast) + 1j * rng.standard_normal(nfast)  # random starting spectrum
    tap = np.fft.ifft(white * shape)[:n]  # filter it and return to the time domain
    return tap * nfast / np.sqrt(2 * np.sum(shape ** 2))  # scale so the long-run average power is exactly 1


def watterson(a, spread_hz, delay_ms, rng, fs=FS, second_db=0.0, shift2_hz=0.0):  # two-path fading
    """Pass complex signal `a` through two independently fading paths, the second one delayed.

    `second_db` is the second path's average power against the first (0: equal, as in F.1487);
    `shift2_hz` moves the second path's frequency (0: none, as in F.1487). Both since 0.34R1.
    """
    delay = int(round(delay_ms * fs / 1000))  # the delay in samples
    late = np.concatenate([np.zeros(delay, dtype=complex), a[:len(a) - delay]])  # the delayed copy
    first = _fading_tap(len(a), spread_hz, rng, fs)  # wandering gain of the first path
    second = _fading_tap(len(a), spread_hz, rng, fs) * 10 ** (second_db / 20)  # wandering gain of the second path, at its own strength
    if shift2_hz:  # the second path is on a slightly different frequency
        second = second * np.exp(2j * np.pi * shift2_hz * np.arange(len(a)) / fs)  # turn it steadily
    return (first * a + second * late) / np.sqrt(1 + 10 ** (second_db / 10))  # sum the paths, keeping the average power unchanged


def add_noise(x, snr_db, signal_power, rng, fs=FS):  # background noise
    """Add white noise so the SNR in 2.5 kHz is `snr_db`, given the signal's average power."""
    noise_in_ref = signal_power / 10 ** (snr_db / 10)  # noise power allowed inside 2.5 kHz
    sigma = np.sqrt(noise_in_ref * (fs / 2) / REF_BANDWIDTH_HZ)  # matching noise level across the whole audio band
    return x + sigma * rng.standard_normal(len(x))  # add the noise


POOL_SCALE = 1000.0  # a noise pool stores band noise of power 1 as 16-bit whole numbers multiplied by this


class NoisePool:  # real band noise from the operator's own recordings (since 0.43)
    """Stretches of real receiver noise, each scaled to power 1 in the 2.5 kHz band.

    The pool is a folder of files s00.npy, s01.npy, ... (16-bit, POOL_SCALE
    per unit) made by tools/make_noise_pool.py from the operator's receive
    recordings. It lives in the operator's data folder (local/noise_pool
    when run from the source folder), never in the public repository.
    The files are memory-mapped, so many processes can share them cheaply.
    """

    def __init__(self, folder=None):  # open a pool
        """Open the pool in `folder` (default: default_pool_folder()); raise FileNotFoundError if it holds no stretches."""
        self.folder = folder or default_pool_folder()  # where the stretch files are
        paths = sorted(glob.glob(os.path.join(self.folder, "s*.npy")))  # one file per quiet stretch
        if not paths:  # nothing there
            raise FileNotFoundError(f"no noise pool in {self.folder} (make one with tools/make_noise_pool.py)")  # say how to make one
        self.stretches = [np.load(p, mmap_mode="r") for p in paths]  # memory-mapped, read only where used

    @property  # computed from the stretches
    def seconds(self):  # how much noise the pool holds
        """Total length of the pool, in seconds."""
        return sum(len(s) for s in self.stretches) / FS  # all stretches together

    def draw(self, n, rng):  # a stretch of real noise
        """Return `n` samples of real band noise (power 1 in 2.5 kHz) from a random place in a random stretch long enough to hold them."""
        usable = [s for s in self.stretches if len(s) >= n]  # stretches long enough
        if not usable:  # the request is longer than every stretch
            raise ValueError(f"noise pool has no stretch of {n / FS:.0f} s")  # say so
        seg = usable[int(rng.integers(len(usable)))]  # one stretch
        start = int(rng.integers(0, len(seg) - n + 1))  # a place in it
        return np.asarray(seg[start:start + n], dtype=np.float64) / POOL_SCALE  # the noise, converted only where used


def default_pool_folder():  # where the operator's noise pool is kept
    """Return the folder of the operator's noise pool: KESTREL_NOISE_POOL if set, else noise_pool in the operator's data folder."""
    if os.environ.get("KESTREL_NOISE_POOL"):  # set by the operator or a test
        return os.environ["KESTREL_NOISE_POOL"]  # that folder
    from live.paths import data_dir  # the operator's data folder (imported here so the simulator needs it only for this)
    return os.path.join(data_dir(), "noise_pool")  # noise_pool inside it


def add_pool_noise(x, snr_db, signal_power, rng, pool):  # real band noise
    """Add real band noise from `pool` so the SNR in 2.5 kHz is `snr_db`, given the signal's average power."""
    noise_in_ref = signal_power / 10 ** (snr_db / 10)  # noise power allowed inside 2.5 kHz
    return x + np.sqrt(noise_in_ref) * pool.draw(len(x), rng)  # the pool's noise has power 1 in that band


def add_crashes(x, rate_per_s, signal_power, rng, mean_ms=5.0, level_db=30.0, fs=FS):  # static crashes
    """Add short loud bursts: `rate_per_s` per second on average, each `level_db` above the signal."""
    y = x.copy()  # work on a copy
    count = rng.poisson(rate_per_s * len(x) / fs)  # how many crashes land in this recording
    amp = np.sqrt(signal_power) * 10 ** (level_db / 20)  # how loud each crash is
    for _ in range(count):  # place the crashes one by one
        begin = int(rng.integers(0, len(x)))  # where this crash starts
        length = max(1, int(rng.exponential(mean_ms) * fs / 1000))  # how long it lasts
        end = min(begin + length, len(x))  # do not run past the end of the recording
        y[begin:end] += amp * rng.standard_normal(end - begin)  # add the burst
    return y  # the signal with crashes


def run_channel(x, snr_db, rng, condition="awgn", offset_hz=0.0, drift_hz_s=0.0, crash_rate=0.0, lead_s=1.0, tail_s=1.0, fs=FS, pool=None):  # the whole channel in one call
    """Return `x` as a receiver would hear it.

    snr_db: SNR in 2.5 kHz (None for no noise); condition: a key of CONDITIONS;
    pool: a NoisePool for real band noise in place of white noise (since 0.43);
    offset_hz / drift_hz_s: frequency error and how fast it changes;
    crash_rate: static crashes per second; lead_s / tail_s: silence added before and after.
    """
    power = float(np.mean(np.square(x)))  # average power of the clean signal, measured before padding
    y = np.concatenate([np.zeros(int(lead_s * fs)), x, np.zeros(int(tail_s * fs))])  # add silence before and after
    fading = CONDITIONS[condition]  # look up the named condition
    if fading is not None or offset_hz != 0.0 or drift_hz_s != 0.0:  # fading or a frequency shift is wanted
        a = _analytic(y)  # switch to the complex form
        if fading is not None:  # fading is wanted
            second_db, shift2_hz = PATH_EXTRAS.get(condition, (0.0, 0.0))  # the second path's strength and shift (F.1487 conditions: equal, none)
            a = watterson(a, fading[0], fading[1], rng, fs, second_db, shift2_hz)  # apply the two-path model
        t = np.arange(len(a)) / fs  # time of every sample
        a = a * np.exp(2j * np.pi * (offset_hz * t + 0.5 * drift_hz_s * t * t))  # apply offset and drift
        y = a.real  # back to an ordinary real signal
    if snr_db is not None:  # noise is wanted
        y = add_pool_noise(y, snr_db, power, rng, pool) if pool is not None else add_noise(y, snr_db, power, rng, fs)  # add it: real band noise from the pool, or white noise
    if crash_rate > 0:  # static crashes are wanted
        y = add_crashes(y, crash_rate, power, rng, fs=fs)  # add them
    return y  # what the receiver hears
