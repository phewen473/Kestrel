"""Measure how often a frame decodes at each SNR, for every speed level, with and without fading.

Run from the repository root:

    python tools/fading_sweep.py --trials 40

It writes results/levels_fading_sweep.csv and results/levels_fading_sweep.png.
For each level and channel condition it also records what the receiver
itself measured: the SNR it reported and its fading index. The lowest SNR
at which nine frames in ten decode under fading is what modem/levels.py
records as MIN_SNR_FADING_DB.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
from multiprocessing import Pool  # runs trials on several processor cores at once

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import LEVELS, MIN_SNR_DB, build_frame, receive  # levels, their noise-only limits, transmitter, receiver  # noqa: E402
from sim import run_channel  # channel simulator  # noqa: E402

CONDITIONS = ("awgn", "good", "moderate", "poor")  # noise only, then light, moderate and heavy fading
NAMES = {"awgn": "noise only", "good": "light fading", "moderate": "moderate fading", "poor": "heavy fading"}  # plain names for the chart
BELOW = 4  # the sweep starts this many dB below the level's noise-only limit
POINTS = 12  # SNR values tested per level and condition
STEP = 2  # dB between SNR values
PRINTABLE = [chr(c) for c in range(32, 127)]  # characters used to build random test messages


def one_trial(job):  # a single send-and-receive attempt
    """Send one random 40-character message; return (decoded?, SNR the receiver measured, its fading index)."""
    level, condition, snr_db, seed = job  # unpack what to test
    rng = np.random.default_rng(seed)  # a repeatable random source for this trial
    text = "".join(rng.choice(PRINTABLE, size=40))  # a random message that fits the 50-character frame
    heard = run_channel(build_frame(text, level), snr_db, rng, condition, offset_hz=float(rng.uniform(-20, 20)))  # transmit with a random frequency error
    result = receive(heard)  # try to decode it
    good = result.ok and result.text == text and result.level == level  # success only if the exact message and level came back
    return good, result.snr_db, result.fade_index  # the outcome and the receiver's own measurements


def main():  # the script itself
    """Sweep every level under every condition, then save the table and the chart."""
    parser = argparse.ArgumentParser(description="Kestrel decode rate against SNR for every speed level, with fading")  # describe the tool
    parser.add_argument("--trials", type=int, default=40, help="frames sent at each SNR value")  # how many tries per point
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="processor cores to use")  # how many cores to use
    parser.add_argument("--conditions", nargs="+", default=list(CONDITIONS), choices=CONDITIONS, help="channel conditions to test")  # which conditions to run
    args = parser.parse_args()  # read the options
    out_dir = os.path.join(ROOT, "results")  # where the results go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    rows = []  # one result row per (level, condition, SNR)
    with Pool(args.workers) as pool:  # start the worker processes
        for spec in LEVELS:  # one speed level at a time
            first = int(MIN_SNR_DB[spec.number]) - BELOW  # where this level's sweep starts
            for c_index, condition in enumerate(args.conditions):  # one channel condition at a time
                for snr_db in range(first, first + POINTS * STEP, STEP):  # one SNR value at a time
                    jobs = [(spec.number, condition, snr_db, 700000 + 50000 * spec.number + 10000 * c_index + 100 * (snr_db + 40) + trial) for trial in range(args.trials)]  # a different, repeatable seed for every trial
                    outcomes = pool.map(one_trial, jobs)  # run the trials in parallel
                    decoded = [o for o in outcomes if o[0]]  # the trials that decoded
                    snr_error = float(np.mean([o[1] for o in decoded])) - snr_db if decoded else float("nan")  # how far the receiver's SNR reading was from the truth, on average
                    fade = float(np.mean([o[2] for o in decoded])) if decoded else float("nan")  # the receiver's average fading index
                    flagged = float(np.mean([o[2] > 0.15 for o in decoded])) if decoded else float("nan")  # share of decoded frames the receiver would call "fading"
                    rows.append((spec.number, condition, snr_db, args.trials, len(decoded), len(decoded) / args.trials, snr_error, fade, flagged))  # store the row
                    print(f"L{spec.number} {condition:9s} {snr_db:4d} dB  {len(decoded):3d}/{args.trials}  snr error {snr_error:5.1f} dB  fade index {fade:4.2f}  flagged {flagged:4.2f}", flush=True)  # show progress
    csv_path = os.path.join(out_dir, "levels_fading_sweep.csv")  # the table file
    with open(csv_path, "w", newline="") as handle:  # open it for writing
        writer = csv.writer(handle)  # CSV writer
        writer.writerow(["level", "condition", "snr_db", "trials", "decoded", "success_rate", "snr_reading_error_db", "mean_fade_index", "share_flagged_fading"])  # column headings
        writer.writerows(rows)  # all the result rows

    import matplotlib  # plotting library (imported here so the trials do not need it)
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface

    fig, axes = plt.subplots(1, len(args.conditions), figsize=(4.6 * len(args.conditions), 4.6), sharey=True)  # one panel per condition, side by side
    for ax, condition in zip(np.atleast_1d(axes), args.conditions):  # fill each panel
        for spec in LEVELS:  # one line per level
            pts = [(r[2], 100 * r[5]) for r in rows if r[0] == spec.number and r[1] == condition]  # (SNR, percent decoded) points
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", markersize=3, label=f"L{spec.number}")  # draw the line
        ax.axhline(90, color="grey", linewidth=0.8, linestyle="--")  # the nine-in-ten line
        ax.set_title(NAMES[condition])  # panel title
        ax.set_xlabel("SNR in 2.5 kHz (dB)")  # x-axis title
        ax.set_ylim(-2, 102)  # a little room above 100 and below 0
        ax.grid(True, alpha=0.3)  # light grid lines
    np.atleast_1d(axes)[0].set_ylabel("Frames decoded (%)")  # y-axis title, on the left panel only
    np.atleast_1d(axes)[-1].legend(loc="lower right")  # legend in the empty corner of the last panel
    fig.suptitle(f"Kestrel speed levels with fading, 50-character frame, {args.trials} trials per point")  # overall title
    fig.tight_layout()  # trim the margins
    fig.savefig(os.path.join(out_dir, "levels_fading_sweep.png"), dpi=130)  # save the chart
    print("wrote", csv_path)  # say where the results went


if __name__ == "__main__":  # only when run as a script
    main()  # go
