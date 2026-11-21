"""Study for roadmap step 2: how slow must a level below L0 be to reach WSPR-like sensitivity?

Run from the repository root:

    python tools/bottom_study.py [--trials 20] [--quick]

The candidates are today's L0 waveform stretched: the same 32 tones, the same
12-tone preamble, the same beacon (a control frame with the K=7 code), but
each tone held longer, and the tones set further apart where fading needs it.
For each candidate it sends beacons through the channel simulator in noise
only and in light, moderate and heavy fading, with a random frequency error
of up to 2 Hz (an older radio a little off, as WSPR allows), and counts how
many decode at each SNR. Nothing here changes the signal; it measures.

Writes results/bottom_study.csv.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths
import sys  # lets us add the repository root to the import path
import time  # how long each point takes

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
if ROOT not in sys.path:  # when run as a script
    sys.path.insert(0, ROOT)  # make "modem" and "sim" importable

import modem.frame as frame  # noqa: E402  # the frame builder and receiver (its level table is swapped for each candidate)
import modem.levels as levels  # noqa: E402  # the level table
from modem.levels import Level  # noqa: E402  # one level's numbers
from sim import run_channel  # noqa: E402  # the channel simulator

CANDIDATES = (  # (name, samples per tone, tone spacing in bins): the waveforms compared
    ("L0 today (0.4 s, 5 Hz apart)", 4800, 2),  # the baseline
    ("0.8 s tones, 2.5 Hz apart", 9600, 2),  # twice as long
    ("1.6 s tones, 1.25 Hz apart", 19200, 2),  # four times as long, tones close together
    ("1.6 s tones, 2.5 Hz apart", 19200, 4),  # four times as long, tones spread for fading
    ("3.2 s tones, 2.5 Hz apart", 38400, 8),  # eight times as long
    ("long beacon (0.27): compact frame, 1.17 s tones, 2.57 Hz apart", 14000, 3),  # the frame chosen for 0.27: modem/longbeacon.py, sent and received by the full receiver
)  # end of the table
LONG = len(CANDIDATES) - 1  # the number of the last candidate, the real long beacon


def use(candidate):  # make the modem send and receive one candidate only
    """Swap the level table so the modem has only `candidate`, numbered 0 (the header and preamble of L0)."""
    _, samples, step = candidate  # its numbers
    table = (Level(0, samples, step),)  # a one-level table
    levels.LEVELS = frame.LEVELS = table  # the builder and the receiver both look here
    return table[0]  # the level


def trial(spec, snr_db, condition, rng, long=False):  # one beacon through the channel
    """Return True when a beacon sent at `snr_db` through `condition` decodes correctly (`long`: the real long beacon, through the full receiver)."""
    if long:  # the 0.27 long beacon
        from modem.longbeacon import build_long_beacon  # its transmitter
        heard = run_channel(build_long_beacon("Q1AAAA", "EM93"), snr_db, rng, condition, offset_hz=float(rng.uniform(-2, 2)), lead_s=float(rng.uniform(2, 8)), tail_s=5.0)  # through the channel
        result = frame.receive(heard)  # the full receiver, every level and the long pattern
        return bool(result.ok and result.origin == "Q1AAAA")  # decoded, and correctly
    sent = frame.build_beacon("Q1AAAA", "EM93", level=0)  # a beacon
    heard = run_channel(sent, snr_db, rng, condition, offset_hz=float(rng.uniform(-2, 2)), lead_s=float(rng.uniform(2, 8)), tail_s=5.0)  # through the channel, at a random time and frequency error
    result = frame.receive(heard)  # decode it
    return bool(result.ok and result.origin == "Q1AAAA")  # decoded, and correctly


def main(argv=None):  # the study itself
    """Run every candidate at every SNR and condition; print and save the decode counts."""
    parser = argparse.ArgumentParser(description="Sensitivity of slower levels below L0")  # describe the tool
    parser.add_argument("--trials", type=int, default=20, help="beacons per point (default 20)")  # how many
    parser.add_argument("--quick", action="store_true", help="fewer SNR points, for a first look")  # a short run
    parser.add_argument("--only", type=int, nargs="*", help="candidate numbers to run (0 = today's L0)")  # a subset
    parser.add_argument("--snrs", type=float, nargs="*", help="run only these SNRs (dB), instead of the usual range")  # a subset of points, so one point can run per process
    parser.add_argument("--conditions", nargs="*", default=["awgn", "good", "moderate", "poor"], help="channel conditions to run")  # a subset of channels
    args = parser.parse_args(argv)  # read the options
    rows = []  # the results
    name = "bottom_study.csv" if args.only is None and not args.snrs else "bottom_study_" + "_".join(str(n) for n in (args.only or [])) + "_" + "_".join(args.conditions) + "_snr" + "_".join(f"{snr:g}" for snr in args.snrs) + ".csv" if args.snrs else "bottom_study_" + "_".join(str(n) for n in args.only) + "_" + "_".join(args.conditions) + ".csv"  # one file, or one per subset run (so subsets can run side by side)
    path = os.path.join(ROOT, "results", name)  # where they go
    for number, candidate in enumerate(CANDIDATES):  # each waveform
        if args.only is not None and number not in args.only:  # not wanted this run
            continue  # skip it
        if number == LONG:  # the real long beacon: leave the level table alone
            from modem import longbeacon  # its numbers
            spec, seconds = longbeacon.LONG, longbeacon.SECONDS  # its level and airtime
        else:  # a stretched L0
            spec = use(candidate)  # make it the only level
            seconds = frame.control_seconds(2, 0)  # a beacon's airtime
        width = spec.step * 32 * spec.bin_hz  # how wide the tones spread
        print(f"{candidate[0]}: beacon {seconds:.0f} s, about {width:.0f} Hz wide", flush=True)  # what is being tested
        expected = 10 * np.log10(spec.samples / 4800.0)  # the gain over L0 from longer tones alone
        top = -18.0 - expected  # start near where it should be perfect
        for condition in args.conditions:  # each channel
            high = top if condition == "awgn" else top + 12.0  # fading needs a stronger signal, so its range starts higher
            points = np.array(args.snrs) if args.snrs else np.arange(high, top - 13.0, -2.0 if args.quick or condition != "awgn" else -1.0)  # the SNRs tried, stronger first (2 dB steps in fading, to keep the run short), or those asked for
            for snr in points:  # each SNR
                started = time.time()  # the clock
                rng = np.random.default_rng(int(1000 * number + 10 * abs(snr)) + len(condition))  # repeatable
                ok = sum(trial(spec, float(snr), condition, rng, long=number == LONG) for _ in range(args.trials))  # how many decoded
                rows.append({"candidate": candidate[0], "tone_s": spec.seconds, "spacing_hz": spec.step * spec.bin_hz, "width_hz": round(width, 1), "beacon_s": round(seconds, 1),  # (continued)
                             "condition": condition, "snr_db": float(snr), "decoded": ok, "trials": args.trials})  # the row
                print(f"  {condition:9s} {snr:6.1f} dB  {ok:3d}/{args.trials}  ({time.time() - started:.0f} s)", flush=True)  # report it
                if ok == 0 and not args.snrs:  # nothing decodes any more (unless the points were chosen by hand)
                    break  # weaker points will not either
        with open(path, "w", newline="", encoding="utf-8") as handle:  # save after each candidate, so a long run can be watched
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))  # one column per field
            writer.writeheader()  # the headings
            writer.writerows(rows)  # everything so far
    print(f"wrote {path}")  # say where
    return 0  # success


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # study and exit
