"""Make a noise pool for the simulator from your own receive recordings (since 0.43).

Real band noise is not the simulator's white noise: on the author's 80 m recordings
it measured about 1 to 1.5 dB harder on Kestrel frames than white noise of the
same power. A noise pool lets the simulator and the study tools use your own
band's noise instead (sim.NoisePool).

Run from the repository root, giving receive recordings (12 kHz mono 16-bit WAV,
such as Kestrel's own recordings):

    python tools/make_noise_pool.py recording1.wav recording2.wav ...

Only the quiet stretches are kept: seconds whose in-band power sits near the
recording's median (no transmissions, own or strong, and not muted), in runs
of at least --min-run seconds. Each stretch is scaled to power 1 in the
2.5 kHz band and written as sNN.npy (16-bit) into the pool folder: by default
noise_pool in your data folder (local/noise_pool when run from the source
folder). The pool is yours: it is never part of the public repository.
"""

import argparse  # reads the command-line options
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
import wave  # reads WAV files

import numpy as np  # numerical arrays
from scipy import signal  # band-pass filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "sim" and "live" importable when run as a script

from sim.channel import FS, POOL_SCALE, default_pool_folder  # sample rate, storage scale, default folder  # noqa: E402

BAND = (250.0, 2750.0)  # the 2.5 kHz band Kestrel's SNR figures refer to


def quiet_stretches(x, min_run_s):  # find plain-noise stretches in one recording
    """Return the stretches of `x` (floats, FS samples a second) that hold only band noise, each scaled to power 1 in the band."""
    b, a = signal.butter(4, [BAND[0] / (FS / 2), BAND[1] / (FS / 2)], "band")  # the band filter
    y = signal.lfilter(b, a, x)  # in-band audio
    sec = len(y) // FS  # whole seconds
    if sec == 0:  # too short to judge
        return []  # nothing
    power = 10 * np.log10(np.mean(y[:sec * FS].reshape(sec, FS) ** 2, axis=1) + 1e-20)  # in-band power each second, in dB
    median = np.median(power)  # the recording's usual level
    quiet = (power < median + 3) & (power > median - 6)  # plain noise: nothing transmitting over it, and not muted
    out = []  # stretches found
    i = 0  # the second being looked at
    while i < sec:  # walk through the recording
        if not quiet[i]:  # a loud or muted second
            i += 1  # skip it
            continue  # look at the next
        j = i  # the run starts here
        while j < sec and quiet[j]:  # extend it while quiet
            j += 1  # one more second
        if j - i >= min_run_s:  # long enough to use
            seg = x[(i + 1) * FS:(j - 1) * FS]  # trimmed a second at each end
            seg = seg / np.sqrt(np.mean(signal.lfilter(b, a, seg) ** 2))  # scaled to power 1 in the band
            out.append(seg)  # kept
        i = j  # carry on after the run
    return out  # every quiet stretch


def read_wav(path):  # one recording
    """Return the samples of a 12 kHz mono 16-bit WAV file as floats from -1 to 1."""
    with wave.open(path) as w:  # open it
        if w.getframerate() != FS or w.getnchannels() != 1 or w.getsampwidth() != 2:  # not the format Kestrel records
            raise ValueError(f"{path}: need {FS} Hz mono 16-bit")  # say so
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768.0  # the samples


def main():  # the command line
    """Read the recordings, cut the quiet stretches and write the pool."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # options
    ap.add_argument("wavs", nargs="+", help="receive recordings (12 kHz mono 16-bit WAV)")  # the recordings
    ap.add_argument("--out", default=None, help="pool folder (default: noise_pool in your data folder)")  # where to write
    ap.add_argument("--min-run", type=int, default=170, help="shortest quiet stretch kept, in seconds (default 170: an L0 frame, a gap and another frame)")  # shortest stretch
    args = ap.parse_args()  # read them
    folder = args.out or default_pool_folder()  # where the pool goes
    os.makedirs(folder, exist_ok=True)  # make sure it exists
    for old in [f for f in os.listdir(folder) if f.startswith("s") and f.endswith(".npy")]:  # a pool already there
        os.remove(os.path.join(folder, old))  # replaced as a whole
    count, total = 0, 0  # stretches written, and their samples
    for path in args.wavs:  # every recording
        found = quiet_stretches(read_wav(path), args.min_run)  # its quiet stretches
        for seg in found:  # each one
            np.save(os.path.join(folder, f"s{count:02d}.npy"), np.clip(np.round(seg * POOL_SCALE), -32767, 32767).astype(np.int16))  # stored 16-bit
            count += 1  # one more
            total += len(seg)  # and its length
        print(f"{os.path.basename(path)}: {len(found)} quiet stretches")  # progress
    print(f"{count} stretches, {total / FS / 60:.1f} minutes of band noise in {folder}")  # summary
    return 0 if count else 1  # failure when nothing usable was found


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # the command line
