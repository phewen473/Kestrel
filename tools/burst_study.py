"""Measure acknowledgment bursts as a station uses them: the threshold, how often they are recognized, and how often wrongly (since 0.43).

The waiting station searches from BURST_EARLIEST_S to BURST_LATEST_S after its
own frame ends, +-3 Hz, for any of the things the burst could say: after a
message frame, three verdicts times five levels (15 patterns). Three runs:

    python tools/burst_study.py noise --trials 5000 --noise real
        noise alone: the score that one search in 1,000 beats (THRESHOLD in modem/burst.py)
    python tools/burst_study.py sweep --trials 100 --noise real
        bursts through fading at a range of SNRs: recognized, wrong verdict, missed
    python tools/burst_study.py wav recording.wav ...
        real recordings searched every 3 s as if a burst were awaited: what beats the threshold
        (strong Kestrel frames and other signals included)

--noise real uses your noise pool (tools/make_noise_pool.py). Results go to results/.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
import time  # timing
import wave  # reads recordings
from multiprocessing import Pool  # runs trials on several processor cores at once

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import burst as B  # the bursts  # noqa: E402
from sim.channel import FS, NoisePool, _analytic, add_noise, add_pool_noise, watterson  # the channel's parts  # noqa: E402

TRUE = B.BurstSays(4321, 17, 1, 0, 2)  # the burst sent in the sweep: "part 1 of message 17 received; send at L2"
CANDS = [B.BurstSays(4321, 17, 1, s, w) for s in (0, 1, 2) for w in range(5)]  # what the waiting station listens for: three verdicts, five levels
SPAN = int((B.BURST_LATEST_S + B.BURST_TONES * B.SPEC.seconds + 1.0) * FS)  # audio a search needs
_POOL = None  # the noise pool, opened once per worker


def _noise(y, snr, power, rng, real):  # add the trial's noise
    """Return `y` with noise at `snr` dB against `power`: real band noise from the pool, or white noise."""
    global _POOL  # opened once per process
    if real:  # real band noise
        if _POOL is None:  # first use in this worker
            _POOL = NoisePool()  # the operator's pool
        return add_pool_noise(y, snr, power, rng, _POOL)  # from it
    return add_noise(y, snr, power, rng)  # white


def _search(y):  # one search, as the waiting station makes it
    """Return the recognized burst (or None) and the best score found, searching y from BURST_EARLIEST_S to BURST_LATEST_S."""
    saved = B.THRESHOLD, B.MARGIN  # the real settings
    B.THRESHOLD, B.MARGIN = -1.0, 0.0  # take anything, to see the best score
    try:  # whatever happens
        raw = B.recognize(y, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS))  # the best fit
    finally:  # put the settings back
        B.THRESHOLD, B.MARGIN = saved  # restored
    return B.recognize(y, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS)), raw  # with the real settings, and the best fit


def noise_trial(job):  # noise alone
    """Return the best score and runner-up of one search through noise alone."""
    seed, real = job  # which trial
    rng = np.random.default_rng(seed)  # random numbers
    y = _noise(np.zeros(SPAN), 0.0, 1.0, rng, real)  # noise at the level of a 0 dB signal of power 1
    _, raw = _search(y)  # searched
    return raw.score, raw.runner_up  # the scores


def sweep_trial(job):  # one burst through the channel
    """Return (spread, snr, recognized right, wrong verdict, wrong level)."""
    spread, snr, seed, real = job  # what to try
    rng = np.random.default_rng(seed)  # random numbers
    audio = B.build_burst(TRUE)  # the burst
    delay = rng.uniform(B.BURST_EARLIEST_S + 0.5, B.BURST_LATEST_S - 0.5)  # where it starts
    y = np.concatenate([np.zeros(int(delay * FS)), audio, np.zeros(SPAN)])[:SPAN + len(audio)]  # in its place
    if spread > 0:  # fading
        y = watterson(_analytic(y), spread, 1.0, rng).real  # two paths 1 ms apart
    y = _noise(y, snr, float(np.mean(audio ** 2)), rng, real)  # noise
    found, _ = _search(y)  # searched
    if found is None:  # nothing taken
        return spread, snr, 0, 0, 0  # missed
    right = found.says.status == TRUE.status  # the verdict
    return spread, snr, int(right and found.says.want == TRUE.want), int(not right), int(right and found.says.want != TRUE.want)  # the outcome


def wav_scan(paths):  # real recordings
    """Search every recording every 3 s as a waiting station would; return the best scores (muted stretches skipped)."""
    out = []  # (file, second, score)
    for path in paths:  # each recording
        with wave.open(path) as w:  # open it
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768.0  # the samples
        for at in range(0, len(x) - SPAN, 3 * FS):  # every 3 s
            y = x[at:at + SPAN]  # one search's audio
            if np.mean(y ** 2) < 1e-10:  # muted (the receiver was off, or the station was transmitting)
                continue  # skip
            _, raw = _search(y)  # searched
            out.append((os.path.basename(path), at / FS, raw.score))  # kept
    return out  # every search


def main():  # the command line
    """Run one of the three studies."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # options
    ap.add_argument("mode", choices=("noise", "sweep", "wav"))  # which study
    ap.add_argument("wavs", nargs="*", help="recordings, for wav")  # recordings
    ap.add_argument("--trials", type=int, default=100)  # trials
    ap.add_argument("--noise", choices=("white", "real"), default="real")  # which noise
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))  # cores
    args = ap.parse_args()  # read them
    real = args.noise == "real"  # which noise
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)  # the results folder
    t0 = time.time()  # timing
    if args.mode == "noise":  # the threshold
        with Pool(args.workers) as pool:  # several cores
            rows = pool.map(noise_trial, [(700000 + i, real) for i in range(args.trials)], chunksize=4)  # run
        best = np.array([r[0] for r in rows])  # best scores
        for q in (0.99, 0.999):  # the quantiles
            print(f"{args.noise} noise, {len(best)} searches: {q:.1%} of best scores below {np.quantile(best, q):.2f}")  # shown
        print(f"searches over THRESHOLD {B.THRESHOLD}: {int(np.sum(best > B.THRESHOLD))}")  # with today's setting
    elif args.mode == "sweep":  # recognition
        jobs = [(sp, s, 800000 + 1000 * i + int((s + 40) * 10) + int(sp * 100), real) for sp in (0.1, 0.5, 2.0) for s in range(-26, -13, 2) for i in range(args.trials)]  # every trial
        with Pool(args.workers) as pool:  # several cores
            rows = pool.map(sweep_trial, jobs, chunksize=2)  # run
        out = os.path.join(ROOT, "results", f"burst_sweep_{args.noise}.csv")  # the table
        with open(out, "w", newline="") as f:  # written
            w = csv.writer(f)  # rows
            w.writerow(["spread_hz", "snr_db", "trials", "recognized", "wrong_verdict", "wrong_level"])  # heading
            for sp in (0.1, 0.5, 2.0):  # each spread
                for s in range(-26, -13, 2):  # each SNR
                    mine = [r for r in rows if r[0] == sp and r[1] == s]  # this point
                    row = [sp, s, len(mine), sum(r[2] for r in mine), sum(r[3] for r in mine), sum(r[4] for r in mine)]  # counts
                    w.writerow(row)  # saved
                    print(*row, flush=True)  # shown
    else:  # real recordings
        rows = wav_scan(args.wavs)  # searched
        scores = np.array([r[2] for r in rows])  # best scores
        print(f"{len(scores)} searches of real recordings: 99.9% below {np.quantile(scores, 0.999):.2f}, highest {scores.max():.2f}, over THRESHOLD {B.THRESHOLD}: {int(np.sum(scores > B.THRESHOLD))}")  # shown
        for r in sorted(rows, key=lambda r: -r[2])[:5]:  # the highest
            print(f"   {r[0]} at {r[1]:.0f} s: {r[2]:.2f}")  # where
    print(f"done in {time.time() - t0:.0f} s")  # timing
    return 0  # done


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # the command line
