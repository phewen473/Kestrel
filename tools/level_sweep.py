"""Measure how often a frame decodes at each SNR, for every speed level (noise only).

Run from the repository root:
    python tools/level_sweep.py --trials 40
It writes results/levels_snr_sweep.csv and results/levels_snr_sweep.png.
The lowest SNR at which every frame decodes is what modem/levels.py records as MIN_SNR_DB.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
from multiprocessing import Pool  # runs trials on several processor cores at once

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import LEVELS, build_frame, frame_seconds, receive  # levels, transmitter, airtime, receiver  # noqa: E402
from sim import run_channel  # channel simulator  # noqa: E402

FIRST_SNR = (-25, -20, -18, -15, -12)  # where each level's sweep starts (a few dB below where it should begin to work)
POINTS = 8  # SNR values tested per level, 1 dB apart
PRINTABLE = [chr(c) for c in range(32, 127)]  # characters used to build random test messages


def one_trial(job):  # a single send-and-receive attempt
    """Send one random 40-character message at the given level and SNR; return True when it decodes exactly."""
    level, snr_db, seed = job  # unpack what to test
    rng = np.random.default_rng(seed)  # a repeatable random source for this trial
    text = "".join(rng.choice(PRINTABLE, size=40))  # a random message that fits the 50-character frame
    heard = run_channel(build_frame(text, level), snr_db, rng, offset_hz=float(rng.uniform(-20, 20)))  # transmit through noise with a random frequency error
    result = receive(heard)  # try to decode it
    return result.ok and result.text == text and result.level == level  # success only if the exact message and level came back


def main():  # the script itself
    """Sweep every level, then save the table and the chart."""
    parser = argparse.ArgumentParser(description="Kestrel decode rate against SNR for every speed level")  # describe the tool
    parser.add_argument("--trials", type=int, default=40, help="frames sent at each SNR value")  # how many tries per point
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="processor cores to use")  # how many cores to use
    args = parser.parse_args()  # read the options
    out_dir = os.path.join(ROOT, "results")  # where the results go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    rows = []  # one result row per (level, SNR)
    with Pool(args.workers) as pool:  # start the worker processes
        for spec in LEVELS:  # one speed level at a time
            for snr_db in range(FIRST_SNR[spec.number], FIRST_SNR[spec.number] + POINTS):  # one SNR value at a time
                jobs = [(spec.number, snr_db, 500000 + 10000 * spec.number + 100 * (snr_db + 40) + trial) for trial in range(args.trials)]  # a different, repeatable seed for every trial
                good = sum(pool.map(one_trial, jobs))  # run the trials in parallel and count the successes
                rows.append((spec.number, snr_db, args.trials, good, good / args.trials))  # store the row
                print(f"L{spec.number}  {snr_db:4d} dB  {good:3d}/{args.trials}", flush=True)  # show progress
    csv_path = os.path.join(out_dir, "levels_snr_sweep.csv")  # the table file
    with open(csv_path, "w", newline="") as handle:  # open it for writing
        writer = csv.writer(handle)  # CSV writer
        writer.writerow(["level", "snr_db", "trials", "decoded", "success_rate"])  # column headings
        writer.writerows(rows)  # all the result rows
    import matplotlib  # plotting library (imported here so the trials do not need it)
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface
    fig, ax = plt.subplots(figsize=(8, 5))  # one chart, 8 by 5 inches
    for spec in LEVELS:  # one line per level
        pts = [(r[1], 100 * r[4]) for r in rows if r[0] == spec.number]  # (SNR, percent decoded) points
        label = f"L{spec.number}: 200 characters in {frame_seconds(3, spec.number):.0f} s"  # legend text with the airtime
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=label)  # draw the line
    ax.set_xlabel("SNR in 2.5 kHz (dB)")  # x-axis title
    ax.set_ylabel("Frames decoded (%)")  # y-axis title
    ax.set_title(f"Kestrel speed levels, noise only, 50-character frame, {args.trials} trials per point")  # chart title
    ax.set_ylim(-2, 102)  # a little room above 100 and below 0
    ax.grid(True, alpha=0.3)  # light grid lines
    ax.legend(loc="lower right")  # legend in the empty corner
    fig.tight_layout()  # trim the margins
    fig.savefig(os.path.join(out_dir, "levels_snr_sweep.png"), dpi=130)  # save the chart
    print("wrote", csv_path)  # say where the results went


if __name__ == "__main__":  # only when run as a script
    main()  # go
