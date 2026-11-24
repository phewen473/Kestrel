"""Level choice against Doppler spread (0.35): the weakest SNR at which each speed level decodes, by spread.

Today the receiving station picks a level from the SNR and one fading table (the worst of light,
moderate and heavy fading). Since 0.35 each frame also reports its Doppler spread. This study
measures each level's nine-in-ten threshold in two-path fading (1 ms between the paths) at three
spreads, so the level choice can use the table for the spread actually measured.

Results: results/level_spread_study.csv and a table printed at the end.
Run: python tools/level_spread_study.py [--trials 20]
"""

import argparse  # options
import csv  # the results table
import os  # paths
import sys  # import path
from multiprocessing import Pool  # many frames at once

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository

import numpy as np  # arrays

from modem import build_frame, receive  # the transmitter and receiver
from sim.channel import _analytic, add_noise, watterson  # the channel's parts

SPREADS = (0.1, 0.5, 2.0)  # Doppler spreads tried, Hz: slow, moderate and fast fading
SNRS = tuple(np.arange(-16.0, 9.0, 2.0))  # -16 to +8 dB in 2.5 kHz
TEXT = "LEVEL SPREAD STUDY " * 5  # a 95-character message


def one(job):  # one frame
    level, spread, snr, seed = job  # what to try
    rng = np.random.default_rng(seed)  # its own numbers
    audio = build_frame(TEXT, level)  # the frame
    y = np.concatenate([np.zeros(12000), audio, np.zeros(12000)])  # silence either side
    faded = watterson(_analytic(y), spread, 1.0, rng).real  # two paths, 1 ms apart, at this spread
    x = add_noise(faded, snr, float(np.mean(audio ** 2)), rng)  # and noise
    r = receive(x, long_beacons=False)  # the full receiver
    return level, spread, snr, bool(r.ok and r.text == TEXT)  # read correctly?


def main():  # every point
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])  # options
    parser.add_argument("--trials", type=int, default=20)  # frames a point
    args = parser.parse_args()  # read them
    jobs = [(level, s, snr, 100000 * level + 10000 * i + 100 * j + t) for level in range(5) for i, s in enumerate(SPREADS) for j, snr in enumerate(SNRS) for t in range(args.trials)]  # every frame
    with Pool(max(1, (os.cpu_count() or 2) - 2)) as pool:  # all cores
        out = pool.map(one, jobs, chunksize=2)  # run them
    rows = []  # for the table
    print("weakest SNR (2.5 kHz) at which nine frames in ten decode, and every stronger point too")  # heading
    print("spread  " + "  ".join(f"L{n:<5}" for n in range(5)))  # columns
    for s in SPREADS:  # each spread
        cells = []  # one per level
        for level in range(5):  # each level
            best = None  # the threshold
            for snr in sorted(SNRS, reverse=True):  # strongest first
                rate = np.mean([r[3] for r in out if r[0] == level and r[1] == s and r[2] == snr])  # its share
                rows.append([level, s, snr, rate])  # kept
                if rate >= 0.9:  # good enough
                    best = snr  # so far
                else:  # a weaker point failed
                    break  # stop
            cells.append(f"{best:+5.0f} " if best is not None else " >+8  ")  # shown
        print(f"{s:4.1f}    " + "  ".join(cells))  # the line
    results = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")  # where results go
    with open(os.path.join(results, "level_spread_study.csv"), "w", newline="") as handle:  # the table
        csv.writer(handle).writerows([["level", "spread_hz", "snr_db", "share"]] + rows)  # every point


if __name__ == "__main__":  # run as a program
    main()  # go
