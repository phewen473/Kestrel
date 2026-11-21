"""Study: how much further are long beacons heard when repeats are added together?

Run from the repository root:

    python tools/combine_study.py --condition awgn --snrs -27 -28 -29 --trials 40
    python tools/combine_study.py --noise 2000        (false alarms: noise only)

A station repeats the same long beacon every ten minutes or more. Each
trial here sends four copies through the channel simulator, each with its
own noise and fading, a few tenths of a hertz apart in frequency, and
gives them one at a time to the receiver's combiner (modem/longbeacon.py
LongCombiner). It records after how many copies the beacon was decoded.
The noise-only run feeds the combiner stretches of noise, as a receiver
on an empty band would, and lists every decode that passes the check
value. (A decode must also carry something shaped like a callsign, which
noise passing the 16-bit check almost never does.)

Writes results/combine_study_<condition>_<snr>.csv (one file per run, so
runs can go side by side; they are merged into results/combine_study.csv).
"""

import argparse  # reads the command-line options
import csv  # writes the results
import os  # file paths
import sys  # lets us add the repository root to the import path

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
if ROOT not in sys.path:  # when run as a script
    sys.path.insert(0, ROOT)  # make "modem" and "sim" importable

from modem import longbeacon  # noqa: E402  # the long beacon and its combiner
from modem.blanker import blank_impulses  # noqa: E402  # the static-crash blanker, as the receiver uses it
from modem.params import FS  # noqa: E402  # 12,000 samples per second
from sim import run_channel  # noqa: E402  # the channel simulator

COPIES = 4  # copies sent in each trial
ROUND_S = 600.0  # seconds between copies (the shortest repeat interval)


def hear(audio, combiner, now):  # one reception, as the live receiver treats it
    """Look for a long beacon in `audio`; return (fields, margin_db, copies) or None. Failed candidates go to `combiner`."""
    audio = longbeacon.clean(blank_impulses(audio))  # as the receiver does first: static crashes blanked, steady carriers removed
    for found in longbeacon.candidates(audio):  # the long pattern's best candidates
        soft = longbeacon.soft_at(audio, found)  # measure the body
        if soft is None:  # not all inside the audio
            continue  # skip it
        fields, margin = longbeacon.decode_energies(soft.energies)  # alone first
        if fields is not None:  # decoded alone
            return fields, margin, 1  # done
        out = combiner.offer(soft, now + found["start"] / FS)  # with earlier copies
        if out is not None:  # decoded together
            return out  # done
    return None  # nothing yet


def trial(snr_db, condition, rng):  # four copies of one station's beacon
    """Return (copies needed, margin) for one trial: 1 to 4, or 0 when even four did not decode; -1 when something decoded wrongly."""
    sent = longbeacon.build_long_beacon("Q1AAAA", "EM93")  # the beacon
    base = float(rng.uniform(-20, 20))  # the station's frequency error
    combiner = longbeacon.LongCombiner()  # a fresh memory
    for copy in range(COPIES):  # each repeat
        heard = run_channel(sent, snr_db, rng, condition, offset_hz=base + float(rng.uniform(-0.5, 0.5)), lead_s=float(rng.uniform(2, 8)), tail_s=4.0)  # its own noise, fading and a little drift between rounds
        out = hear(heard, combiner, copy * ROUND_S)  # give it to the receiver
        if out is not None:  # something decoded
            return (copy + 1 if out[0]["origin"] == "Q1AAAA" and out[0]["grid"] == "EM93" else -1), out[1]  # how many copies it took (or a wrong decode)
    return 0, -99.0  # not decoded


def noise_run(count, rng):  # an empty band
    """Feed `count` stretches of noise to a combiner; return the margins of everything that passed the check value."""
    combiner = longbeacon.LongCombiner()  # the memory
    passed = []  # (margin, copies, callsign) of every false decode
    for number in range(count):  # each stretch
        out = hear(rng.standard_normal(int(75 * FS)) * 0.05, combiner, number * 65.0)  # 75 seconds of noise, a new stretch every 65 seconds
        if out is not None:  # a false decode
            passed.append((round(out[1], 2), out[2], out[0]["origin"]))  # note it
    return passed  # all of them


def main(argv=None):  # the study itself
    """Run the trials asked for and save the counts."""
    parser = argparse.ArgumentParser(description="Combining repeated long beacons")  # describe the tool
    parser.add_argument("--condition", default="awgn", help="awgn, good, moderate or poor")  # the channel
    parser.add_argument("--snrs", type=float, nargs="*", default=[-26.0, -28.0, -30.0], help="SNRs in dB")  # the points
    parser.add_argument("--trials", type=int, default=40, help="trials per point")  # how many
    parser.add_argument("--noise", type=int, default=0, help="instead: this many stretches of noise only")  # the false-alarm run
    parser.add_argument("--seed", type=int, default=1, help="random seed")  # so runs side by side differ
    args = parser.parse_args(argv)  # read the options
    if args.noise:  # the false-alarm run
        passed = noise_run(args.noise, np.random.default_rng(args.seed))  # run it
        print(f"noise only: {args.noise} stretches, {len(passed)} passed the check value: {sorted(passed, reverse=True)}", flush=True)  # report
        return 0  # done
    for snr in args.snrs:  # each point
        rng = np.random.default_rng(args.seed * 100000 + int(abs(snr) * 10))  # repeatable
        needed = [trial(snr, args.condition, rng) for _ in range(args.trials)]  # run the trials
        counts = [sum(1 for copies, _ in needed if 1 <= copies <= most) for most in range(1, COPIES + 1)]  # decoded with up to 1, 2, 3, 4 copies
        wrong = sum(1 for copies, _ in needed if copies < 0)  # wrong decodes
        margins = [margin for copies, margin in needed if copies > 1]  # margins of the combined decodes
        print(f"{args.condition:9s} {snr:6.1f} dB  with 1/2/3/4 copies: {counts} of {args.trials}  wrong {wrong}  lowest combined margin {min(margins) if margins else 0:.1f}", flush=True)  # report
        path = os.path.join(ROOT, "results", f"combine_study_{args.condition}_{snr:g}_{args.seed}.csv")  # this run's file
        with open(path, "w", newline="", encoding="utf-8") as handle:  # save it
            writer = csv.writer(handle)  # a plain table
            writer.writerow(["condition", "snr_db", "trials", "decoded_1", "decoded_2", "decoded_3", "decoded_4", "wrong", "lowest_combined_margin_db"])  # headings
            writer.writerow([args.condition, snr, args.trials] + counts + [wrong, round(min(margins), 2) if margins else ""])  # the counts
    return 0  # success


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # study and exit
