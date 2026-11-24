"""Measure how often a Kestrel L0 frame decodes at each signal-to-noise ratio.

Run from the repository root:
    python tools/snr_sweep.py --trials 40
It writes results/l0_snr_sweep.csv and results/l0_snr_sweep.png.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths and folders
import sys  # lets us add the repository root to the import path
from multiprocessing import Pool  # runs trials on several processor cores at once

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import build_frame, receive  # transmitter and receiver  # noqa: E402
from sim import run_channel  # channel simulator  # noqa: E402

SWEEPS = {  # which SNR values to test for each channel condition
    "awgn": list(range(-26, -13)),  # noise only: -26 to -14 dB in 1 dB steps
    "good": list(range(-24, -5, 2)),  # light fading: -24 to -6 dB in 2 dB steps
    "moderate": list(range(-22, -3, 2)),  # moderate fading: -22 to -4 dB in 2 dB steps
    "poor": list(range(-20, -1, 2)),  # heavy fading: -20 to -2 dB in 2 dB steps
}  # end of the table
PRINTABLE = [chr(c) for c in range(32, 127)]  # characters used to build random test messages


def one_trial(job):  # a single send-and-receive attempt
    """Send one random 40-character message through the channel; return (decoded correctly?, measured SNR)."""
    condition, snr_db, seed = job  # unpack what to test
    rng = np.random.default_rng(seed)  # a repeatable random source for this trial
    text = "".join(rng.choice(PRINTABLE, size=40))  # a random message that fits the 50-character frame
    heard = run_channel(build_frame(text), snr_db, rng, condition, offset_hz=float(rng.uniform(-20, 20)))  # transmit through the simulated channel with a random frequency error
    result = receive(heard)  # try to decode it
    return (result.ok and result.text == text, result.snr_db)  # success only if the exact message came back


def main():  # the script itself
    """Run every sweep, then save the table and the chart."""
    parser = argparse.ArgumentParser(description="Kestrel L0 decode rate against SNR")  # describe the tool
    parser.add_argument("--trials", type=int, default=40, help="frames sent at each SNR value")  # how many tries per point
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="processor cores to use")  # how many cores to use
    parser.add_argument("--conditions", nargs="+", default=list(SWEEPS), help="which channel conditions to test")  # which sweeps to run
    args = parser.parse_args()  # read the options
    out_dir = os.path.join(ROOT, "results")  # where the results go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    rows = []  # one result row per (condition, SNR)
    with Pool(args.workers) as pool:  # start the worker processes
        for c_index, condition in enumerate(args.conditions):  # one channel condition at a time
            for snr_db in SWEEPS[condition]:  # one SNR value at a time
                jobs = [(condition, snr_db, 100000 * c_index + 1000 * (snr_db + 40) + trial) for trial in range(args.trials)]  # a different, repeatable seed for every trial
                outcomes = pool.map(one_trial, jobs)  # run the trials in parallel
                good = sum(1 for ok, _ in outcomes if ok)  # how many decoded correctly
                measured = [snr for ok, snr in outcomes if ok]  # the receiver's own SNR readings on the good ones
                mean_measured = float(np.mean(measured)) if measured else float("nan")  # their average
                rows.append((condition, snr_db, args.trials, good, good / args.trials, mean_measured))  # store the row
                print(f"{condition:9s} {snr_db:4d} dB  {good:3d}/{args.trials}  measured {mean_measured:6.1f} dB", flush=True)  # show progress
    csv_path = os.path.join(out_dir, "l0_snr_sweep.csv")  # the table file
    with open(csv_path, "w", newline="") as handle:  # open it for writing
        writer = csv.writer(handle)  # CSV writer
        writer.writerow(["condition", "snr_db", "trials", "decoded", "success_rate", "mean_measured_snr_db"])  # column headings
        writer.writerows(rows)  # all the result rows
    import matplotlib  # plotting library (imported here so the trials do not need it)
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface
    fig, ax = plt.subplots(figsize=(8, 5))  # one chart, 8 by 5 inches
    labels = {"awgn": "Noise only", "good": "Light fading (0.1 Hz, 0.5 ms)", "moderate": "Moderate fading (0.5 Hz, 1 ms)", "poor": "Heavy fading (1 Hz, 2 ms)"}  # plain-English legend names
    for condition in args.conditions:  # one line per condition
        pts = [(r[1], 100 * r[4]) for r in rows if r[0] == condition]  # (SNR, percent decoded) points
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=labels.get(condition, condition))  # draw the line
    ax.axvline(-22, color="gray", linestyle="--", linewidth=1)  # mark the design target
    ax.text(-21.8, 3, "L0 target", color="gray", fontsize=9)  # label the target line
    ax.set_xlabel("SNR in 2.5 kHz (dB)")  # x-axis title
    ax.set_ylabel("Frames decoded (%)")  # y-axis title
    ax.set_title(f"Kestrel L0 prototype, 50-character frame, {args.trials} trials per point")  # chart title
    ax.set_ylim(-2, 102)  # a little room above 100 and below 0
    ax.grid(True, alpha=0.3)  # light grid lines
    ax.legend(loc="lower right")  # legend in the empty corner
    fig.tight_layout()  # trim the margins
    fig.savefig(os.path.join(out_dir, "l0_snr_sweep.png"), dpi=130)  # save the chart
    print("wrote", csv_path)  # say where the results went


if __name__ == "__main__":  # only when run as a script
    main()  # go
