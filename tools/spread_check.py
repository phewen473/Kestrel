"""Check the Doppler-spread reading (since 0.35): send frames through known spreads and print what the receiver reads.

For each level and each true spread, 12 frames at a strong SNR; prints the median reading and
its spread between the 10th and 90th percentile, with the compiled library and in pure Python.
Run: python tools/spread_check.py
"""

import os  # paths
import sys  # import path
from multiprocessing import Pool  # many frames at once

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository

import numpy as np  # arrays

from modem import build_frame, receive  # ordinary frames
from modem import longbeacon  # long frames
from modem.frame import RxResult  # a report to fill
from sim.channel import _analytic, add_noise, watterson  # the channel's parts

SPREADS = (0.0, 0.1, 0.3, 0.5, 1.0, 2.0, 4.0)  # true spreads, Hz
TRIALS = 12  # frames a point


def _through(audio, spread, snr, rng):  # one frame through a single fading path (no echo), at a given spread
    y = np.concatenate([np.zeros(12000), audio, np.zeros(12000)])  # silence either side
    a = _analytic(y)  # complex form
    if spread > 0:  # fading wanted
        a = watterson(a, spread, 0.0, rng, second_db=-60.0)  # one path in practice (the second 60 dB down), so only the Doppler spread acts
    return add_noise(a.real, snr, float(np.mean(audio ** 2)), rng)  # and noise


def one(job):  # one trial
    level, spread, seed = job  # what to try
    rng = np.random.default_rng(seed)  # its own numbers
    if level == "LB":  # the long frame
        x = _through(longbeacon.build_long_beacon("Q1AAAA", "EM93"), spread, -10.0, rng)  # a strong long beacon
        r = longbeacon.decode_at(x, {"start": 12000, "offset_hz": 0.0, "quality": 10.0}, RxResult(start=12000))  # read at the known start
    else:  # a speed level
        x = _through(build_frame("SPREAD CHECK " * 7, level), spread, 10.0, rng)  # a strong message
        r = receive(x, long_beacons=False)  # the full receiver
    return level, spread, (r.spread_hz if r.ok else float("nan"))  # the reading


def main():  # every point
    jobs = [(level, s, 1000 * i + 37 * j + t) for i, level in enumerate((0, 1, 2, 3, 4, "LB")) for j, s in enumerate(SPREADS) for t in range(TRIALS)]  # all trials
    with Pool(max(1, (os.cpu_count() or 2) - 2)) as pool:  # all cores
        out = pool.map(one, jobs, chunksize=2)  # run them
    print(f"{'level':>5} " + " ".join(f"{s:>14}" for s in SPREADS))  # heading: true spread
    for level in (0, 1, 2, 3, 4, "LB"):  # each level
        cells = []  # one per spread
        for s in SPREADS:  # each true spread
            got = np.array([r[2] for r in out if r[0] == level and r[1] == s], dtype=float)  # its readings
            ok = got[np.isfinite(got)]  # the ones given
            cells.append(f"{np.median(ok):5.2f} ({np.percentile(ok, 10):4.2f}-{np.percentile(ok, 90):4.2f})" if len(ok) else "     -        ")  # median and range
        print(f"{str(level):>5} " + " ".join(f"{c:>14}" for c in cells))  # the line


if __name__ == "__main__":  # run as a program
    main()  # go
