"""Measure the level-choice thresholds the way a station uses them: from one frame's reading, will the next frame get through? (since 0.43)

A station picks the level to ask for from the readings of a frame it has just
decoded (SNR, fading index, Doppler spread). The old limit tables were measured
frame by frame at a known true SNR, with a 2 dB margin added on top, and on
the air that proved about 4 to 5 dB too cautious in fading: an L2 frame got
through nine times in ten from an L0 reading of about -13 dB, where the rule
asked for -8 dB.

Each trial here is what a station lives through: an L0 frame (38 characters,
the 50-character class), then GAP_S seconds later a frame of the level under
test, through one continuous fading channel. The L0 frame is read with its
start known (as the continuous receiver has it); the second frame is found
and read by the full receiver. Trials are grouped by how the station would
class the L0 reading (steady, fading, fast fading: modem.plan is_fading and
is_fast), and for each level and class the threshold is the lowest reading
from which the next frame got through at least nine times in ten, with at
least eight in ten in the 2 dB just above it. The limit tables in
modem/levels.py are those thresholds less the rule's 2 dB margin.

Run from the repository root:

    python tools/next_frame_study.py --trials 60 --noise real

--noise real uses your noise pool (tools/make_noise_pool.py); white uses the
simulator's noise. It writes results/next_frame_<noise>.csv and prints the
thresholds and the table values they give.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
import time  # timing
from multiprocessing import Pool  # runs trials on several processor cores at once

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import LEVELS, build_frame, receive  # levels, transmitter, receiver  # noqa: E402
from modem.plan import is_fading, is_fast  # how a station classes a reading  # noqa: E402
from sim.channel import FS, NoisePool, _analytic, add_noise, add_pool_noise, watterson  # the channel's parts  # noqa: E402

TEXT = "NEXT FRAME STUDY 12" * 2  # 38 characters: the 50-character class, like the on-air test messages
GAP_S = 40.0  # seconds between the reading frame and the next frame (the partner's acknowledgment and turnaround)
LEAD = FS  # a second of quiet before and after
SPREADS = (0.0, 0.1, 0.5, 2.0)  # steady, slow (the worst case), typical and fast fading (Doppler spread, Hz; two paths 1 ms apart)
SNRS = {1: range(-20, -5, 2), 2: range(-18, -3, 2), 3: range(-14, 1, 2), 4: range(-12, 3, 2)}  # true SNRs tried per level (2.5 kHz)
MARGIN_DB = 2.0  # the margin modem.plan.pick_level keeps above a table value
CLASSES = ("steady", "fading", "fast")  # how a station classes a reading
_POOL = None  # the noise pool, opened once per worker


def _noise(y, snr, power, rng, real):  # add the trial's noise
    """Return `y` with noise at `snr` dB against `power`: real band noise from the pool, or white noise."""
    global _POOL  # opened once per process
    if real:  # real band noise
        if _POOL is None:  # first use in this worker
            _POOL = NoisePool()  # the operator's pool
        return add_pool_noise(y, snr, power, rng, _POOL)  # from it
    return add_noise(y, snr, power, rng)  # white


def one(job):  # one trial
    """Return a dict: the L0 frame's readings (when it decoded) and whether the next frame got through."""
    level, spread, snr, seed, real = job  # what to try
    rng = np.random.default_rng(seed)  # random numbers
    a = build_frame(TEXT, 0)  # the reading frame
    b = build_frame(TEXT, level)  # the next frame
    gap = np.zeros(int(GAP_S * FS))  # the wait between them
    y = np.concatenate([np.zeros(LEAD), a, gap, b, np.zeros(LEAD)])  # the whole stretch
    if spread > 0:  # fading
        y = watterson(_analytic(y), spread, 1.0, rng).real  # two paths 1 ms apart
    y = _noise(y, snr, float(np.mean(a ** 2)), rng, real)  # same transmit power for both frames
    cand = [({"start": float(LEAD), "offset_hz": 0.0, "quality": 1.0}, LEVELS[0])]  # where the L0 frame is
    ra = receive(y, long_beacons=False, candidates=cand)  # read as the continuous receiver has it
    b0 = LEAD + len(a) + len(gap)  # where the next frame starts
    rb = receive(y[b0 - LEAD:], long_beacons=False)  # found and read by the full receiver
    row = {"level": level, "spread": spread, "snr_true": snr, "seed": seed, "a_ok": bool(ra.ok and ra.text == TEXT), "b_ok": bool(rb.ok and rb.text == TEXT)}  # outcomes
    if row["a_ok"]:  # readings exist only for a frame that decoded
        row["snr"] = float(ra.snr_db)  # SNR reading
        row["fade"] = float(ra.fade_index)  # fading index
        row["dspread"] = float(ra.spread_hz)  # Doppler spread reading
        row["cls"] = ("fast" if is_fast(ra.spread_hz) else "fading") if is_fading(ra.fade_index) else "steady"  # how the station classes it
    return row  # the trial


def threshold(rows, need=0.9, local=0.8, width=2.0, least=20):  # the lowest reading from which the next frame is reliable
    """Return the lowest reading t (0.5 dB steps) with success >= `need` over all readings >= t and >= `local` in [t, t+width); None if none."""
    if len(rows) < least:  # too few to say
        return None  # unknown
    best = None  # lowest good threshold so far
    for t in np.arange(np.floor(min(r["snr"] for r in rows)), np.ceil(max(r["snr"] for r in rows)) + 0.5, 0.5)[::-1]:  # from the top down
        above = [r["b_ok"] for r in rows if r["snr"] >= t]  # trials read at or above t
        near = [r["b_ok"] for r in rows if t <= r["snr"] < t + width]  # those just above it
        if len(above) < least:  # too few above
            continue  # go lower
        if np.mean(above) >= need and (len(near) < 5 or np.mean(near) >= local):  # reliable from here
            best = float(t)  # keep going down
        else:  # no longer reliable
            break  # stop at the last good one
    return best  # the threshold


def main():  # the command line
    """Run the trials and print the thresholds."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # options
    ap.add_argument("--trials", type=int, default=60, help="trials per level, spread and SNR")  # how many
    ap.add_argument("--noise", choices=("white", "real"), default="real", help="real: your noise pool; white: the simulator's noise")  # which noise
    ap.add_argument("--levels", default="1,2,3,4", help="levels to test")  # which levels
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2), help="processes")  # how many cores
    args = ap.parse_args()  # read them
    real = args.noise == "real"  # which noise
    if real:  # check the pool before starting
        print(f"noise pool: {NoisePool().seconds / 60:.1f} minutes")  # it exists
    levels = [int(v) for v in args.levels.split(",")]  # the levels
    jobs = [(lv, sp, s, 900000 + 1000 * i + 100 * lv + int((s + 40) * 2) + int(sp * 10), real) for lv in levels for sp in SPREADS for s in SNRS[lv] for i in range(args.trials)]  # every trial
    t0 = time.time()  # timing
    with Pool(args.workers) as pool:  # several cores
        rows = pool.map(one, jobs, chunksize=1)  # run
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)  # the results folder
    out = os.path.join(ROOT, "results", f"next_frame_{args.noise}.csv")  # the table
    keys = ["level", "spread", "snr_true", "seed", "a_ok", "b_ok", "snr", "fade", "dspread", "cls"]  # columns
    with open(out, "w", newline="") as f:  # every trial kept
        w = csv.DictWriter(f, fieldnames=keys)  # by column
        w.writeheader()  # names
        for r in rows:  # each trial
            w.writerow({k: r.get(k, "") for k in keys})  # one row
    print(f"{len(jobs)} trials in {time.time() - t0:.0f} s; {out}")  # timing
    for lv in levels:  # each level
        for cls in CLASSES:  # each class
            mine = [r for r in rows if r["level"] == lv and r["a_ok"] and r["cls"] == cls]  # readings in this class
            t = threshold(mine)  # the threshold
            text = f"reading >= {t:+.1f} dB, table {t - MARGIN_DB:+.1f}" if t is not None else "no reliable threshold"  # what it says
            print(f"L{lv} {cls:6s}: {len(mine):4d} readings, {text}")  # the result
    return 0  # done


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # the command line
