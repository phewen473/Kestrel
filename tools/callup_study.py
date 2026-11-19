"""How often a call-up gets through at each speed level, and how long it holds the calling frequency.

Today every call-up (beacon, answer, confirmation) is sent at L0, the
slowest level: about 100 seconds on the calling frequency before any
message moves. This study measures, in the channel simulator, how often
a beacon and an answer decode at L0, L1 and L2 across signal strengths,
on a steady path and in moderate fading, and works out the expected time
the calling frequency is held under two rules:

    today:    every round at L0
    middle:   first round at L2; if it brings no lock, the next at L0

Nothing in the modem or link code is changed. Results go to
results/callup_study.csv.

    python tools/callup_study.py [--trials 30]
"""

import argparse  # reads the command-line options
import csv  # the results file
import os  # file paths
import sys  # lets us import the repository's packages
from multiprocessing import Pool  # use every processor

import numpy as np  # arrays and random numbers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root
sys.path.insert(0, ROOT)  # make the packages importable

from link.params import REPLY_MARGIN_S, TURNAROUND_S  # the gaps around a reply  # noqa: E402
from modem.control import ChannelReport  # the report an answer carries  # noqa: E402
from modem.frame import FRAME_TYPE_ACK, build_answer, build_beacon, control_seconds, receive  # control frames and the receiver  # noqa: E402
from sim.channel import run_channel  # the simulated HF path  # noqa: E402

LEVELS = (0, 1, 2)  # the levels compared
CONDITIONS = ("awgn", "moderate")  # a steady path, and moderate fading
SNRS = tuple(range(-22, 5, 2))  # signal-to-noise ratios in 2.5 kHz, in dB


def trial(job):  # one beacon and one answer through the channel
    level, condition, snr, seed = job  # what to try
    rng = np.random.default_rng(seed)  # its own random numbers
    beacon = build_beacon("Q1AAAA", "EM92", level=level)  # a beacon at this level
    answer = build_answer("Q1AAAA", "Q2BB", ChannelReport(-5.0, 0.1, 0.0, 2), level=level)  # an answer at this level
    got_beacon = receive(run_channel(beacon, snr, rng, condition)).ok  # did the beacon decode?
    got_answer = receive(run_channel(answer, snr, rng, condition)).ok  # did the answer decode?
    return level, condition, snr, got_beacon, got_answer  # the outcome


def round_seconds(level):  # how long one call-up round holds the calling frequency
    """Return (seconds when it locks, seconds when nobody answers) for a round at `level` with a one-slot reply window sized for that level."""
    beacon = control_seconds(2, level)  # the beacon (frame type 2)
    answer = control_seconds(3, level)  # the answer (frame type 3)
    confirm = control_seconds(FRAME_TYPE_ACK, level)  # the confirmation
    slot = answer + 2.0 * TURNAROUND_S  # a reply slot just long enough for the answer at this level
    return beacon + TURNAROUND_S + answer + TURNAROUND_S + confirm, beacon + slot + REPLY_MARGIN_S  # locked, or given up


def main():  # the study
    parser = argparse.ArgumentParser(description=__doc__)  # the command-line reader
    parser.add_argument("--trials", type=int, default=30, help="beacons and answers per point")  # how many
    trials = parser.parse_args().trials  # read it
    jobs = [(level, condition, snr, 1000 * i + 17 * level + snr + 100 + (500000 if condition != "awgn" else 0)) for level in LEVELS for condition in CONDITIONS for snr in SNRS for i in range(trials)]  # every trial
    with Pool() as pool:  # every processor
        outcomes = pool.map(trial, jobs, chunksize=8)  # run them
    rates = {}  # (level, condition, snr) -> (beacon rate, answer rate)
    for level in LEVELS:  # each level
        for condition in CONDITIONS:  # each path
            for snr in SNRS:  # each strength
                mine = [o for o in outcomes if o[:3] == (level, condition, snr)]  # its trials
                rates[(level, condition, snr)] = (np.mean([o[3] for o in mine]), np.mean([o[4] for o in mine]))  # the two decode rates
    rows = []  # the results table
    for condition in CONDITIONS:  # each path
        for snr in SNRS:  # each strength
            row = {"condition": condition, "snr_db": snr}  # the point
            lock = {}  # chance one round at a level ends in a lock
            for level in LEVELS:  # each level
                beacon_rate, answer_rate = rates[(level, condition, snr)]  # its decode rates
                lock[level] = beacon_rate * answer_rate * answer_rate  # beacon heard, answer heard, confirmation (about the answer's size) heard
                row[f"L{level}_beacon"], row[f"L{level}_answer"], row[f"L{level}_lock"] = round(beacon_rate, 2), round(answer_rate, 2), round(lock[level], 2)  # into the table
            ok0, miss0 = round_seconds(0)  # an L0 round: locked, or not
            p0 = max(lock[0], 1e-6)  # chance an L0 round locks
            today = ok0 + (1.0 / p0 - 1.0) * miss0  # expected seconds held until a lock, rounds repeating at L0
            ok2, miss2 = round_seconds(2)  # an L2 round
            middle = lock[2] * ok2 + (1.0 - lock[2]) * (miss2 + today)  # try L2 once; if it fails, carry on at L0
            row["today_s"], row["middle_s"] = round(min(today, 9999.0), 0), round(min(middle, 9999.0), 0)  # expected time on the calling frequency
            rows.append(row)  # keep the row
    path = os.path.join(ROOT, "results", "callup_study.csv")  # the results file
    with open(path, "w", newline="", encoding="utf-8") as handle:  # write it
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))  # the CSV writer
        writer.writeheader()  # the column names
        writer.writerows(rows)  # the rows
    for row in rows:  # print a short table
        print(f"{row['condition']:9s} {row['snr_db']:+4d} dB  lock L0 {row['L0_lock']:.2f}  L1 {row['L1_lock']:.2f}  L2 {row['L2_lock']:.2f}   held: today {row['today_s']:5.0f} s, middle-first {row['middle_s']:5.0f} s")  # one line each
    for level in LEVELS:  # the round lengths
        print(f"L{level} round: {round_seconds(level)[0]:.0f} s when it locks, {round_seconds(level)[1]:.0f} s when nobody answers")  # for reference


if __name__ == "__main__":  # only when run as a script
    main()  # go
