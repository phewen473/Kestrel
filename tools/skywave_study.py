"""Sky-wave study (0.34R1): tests the recommendations of the sky-wave research before any is built.

Four parts, each run many times in noise and fading on all the computer's cores:
  A  long frame (long beacon / long note) against Doppler spread and the realistic conditions:
     the receiver's present reading of each tone (its center bin) against the sum of the tone's
     three bins (center and one each side, for energy that fading smears sideways), and trying
     the center first and the sum only if that fails ("either");
  B  two weak copies of a long frame added together when the second arrives on another
     frequency (transmitter chirp, sunrise shift): does adding still work?
  C  the fast levels L2, L3, L4 on a strong signal (+10 dB) in each condition: do the short
     tones fail on the long echoes of near vertical paths whatever the signal strength?
  D  a long frame found by the real search with a 4 Hz offset and drift, and in the "dawn" condition.

Results: results/skywave_study.csv (every point) and a summary printed at the end.
Run: python tools/skywave_study.py [--trials 40] [--workers 32]
"""

import argparse  # command-line options
import csv  # the results table
import os  # paths
import sys  # import path
from multiprocessing import Pool  # many trials at once

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository

import numpy as np  # arrays

from modem import longbeacon  # the long frame
from modem.frame import build_frame, receive  # ordinary frames
from modem.longbeacon import LAYOUT, LONG, build_long_beacon, decode_energies  # the long frame's parts
from modem.mfsk import band_energies, noise_level, noise_profile, pilot_frequency_fit, tone_energies  # tone measurements
from modem.params import FS, PREAMBLE_TONES  # numbers
from sim.channel import CONDITIONS, PATH_EXTRAS, _analytic, add_noise, run_channel, watterson  # the channel simulator

LEAD = FS  # one second of silence before each frame
AUDIO = None  # the long frame's audio, made once per worker


def _long_audio():  # the long frame, made once
    global AUDIO  # kept between trials in this worker
    if AUDIO is None:  # not made yet
        AUDIO = build_long_beacon("Q1AAAA", "EM93")  # a long beacon (a long note's frame is the same shape)
    return AUDIO  # the audio


def _channel(audio, snr_db, rng, spread_hz, delay_ms, second_db=0.0, shift2_hz=0.0, offset_hz=0.0, drift_hz_s=0.0):  # a custom channel
    """Return `audio` through two-path fading with the given numbers, a frequency offset and drift, and noise."""
    power = float(np.mean(audio ** 2))  # the signal's power
    y = np.concatenate([np.zeros(LEAD), audio, np.zeros(FS)])  # silence either side
    a = _analytic(y)  # complex form
    if spread_hz > 0 or delay_ms > 0:  # fading wanted
        a = watterson(a, spread_hz, delay_ms, rng, FS, second_db, shift2_hz)  # two paths
    t = np.arange(len(a)) / FS  # time of each sample
    a = a * np.exp(2j * np.pi * (offset_hz * t + 0.5 * drift_hz_s * t * t))  # offset and drift
    return add_noise(a.real, snr_db, power, rng, FS)  # and noise


def _readings(x, start, offset_hz=0.0):  # the long frame's body, read three ways
    """Return the normalized tone energies of the body at `start`: (center bins, three-bin sums)."""
    body = start + PREAMBLE_TONES * LONG.samples  # the body follows the pattern
    extra, drift = pilot_frequency_fit(x, body, LAYOUT["pilot_pos"], LAYOUT["pilot_tones"], LONG, offset_hz)  # frequency and drift from the pilots
    band = band_energies(x, body, LAYOUT["total"], LONG, offset_hz + extra, drift)  # every bin of every body tone
    center = tone_energies(band, LONG)  # the tone bins (the receiver's present reading)
    wide = center + band[:, 0:96:3] + band[:, 2:96:3]  # each tone with the bin either side of it
    out = []  # both, in units of the noise
    for tone_e in (center, wide):  # each reading
        noise = noise_level(tone_e)  # the noise per position
        own = np.median(tone_e, axis=0) / np.log(2) / noise  # each position's own level
        weight = np.where(own > longbeacon.BUSY_TONE, own, 1.0)  # busy positions counted down, as the receiver does
        out.append(tone_e / noise_profile(tone_e)[:, None] / weight)  # normalized
    return out  # center, wide


def part_a(job):  # one trial of part A
    name, spread, delay, second_db, shift2, snr, seed = job  # what to try
    rng = np.random.default_rng(seed)  # its own random numbers
    x = _channel(_long_audio(), snr, rng, spread, delay, second_db, shift2)  # through the channel
    center, wide = _readings(x, LEAD)  # read at the known start (timing is not what is being tested)
    c = decode_energies(center)[0] is not None  # the present receiver
    w = decode_energies(wide)[0] is not None  # three-bin sums
    return name, snr, c, w, c or w  # the outcomes


def part_b(job):  # one trial of part B
    shift, drift, snr, seed = job  # the second copy's frequency change, and the signal
    rng = np.random.default_rng(seed)  # its own random numbers
    energies = []  # each copy's center-bin energies
    for offset, rate in ((0.0, 0.0), (shift, drift)):  # the first copy, then the shifted one
        x = _channel(_long_audio(), snr, rng, 0.0, 0.0, offset_hz=offset, drift_hz_s=rate)  # noise only, at its frequency
        found = longbeacon.candidates(longbeacon.clean(x), keep=1)  # the real search
        if not found:  # nothing found
            return shift, snr, False, False  # failed
        soft = longbeacon.soft_at(longbeacon.clean(x), found[0])  # the receiver's own measurement, at the frequency it found
        if soft is None:  # incomplete
            return shift, snr, False, False  # failed
        energies.append(soft.energies)  # kept
    alone = decode_energies(energies[1])[0] is not None  # the second copy alone
    both = decode_energies(energies[0] + energies[1])[0] is not None  # the two added
    return shift, snr, alone, both  # the outcomes


def part_c(job):  # one trial of part C
    condition, level, seed = job  # where and how fast
    rng = np.random.default_rng(seed)  # its own random numbers
    audio = build_frame("SKYWAVE STUDY " * 7, level)  # a 98-character message
    x = run_channel(audio, 10.0, rng, condition)  # strong signal, through the condition
    return condition, level, receive(x, long_beacons=False).ok  # read?


def part_d(job):  # one trial of part D
    case, snr, seed = job  # which case
    rng = np.random.default_rng(seed)  # its own random numbers
    if case == "offset 4 Hz, drift 0.01 Hz/s":  # a big offset and a steady drift (0.6 Hz over the frame)
        x = _channel(_long_audio(), snr, rng, 0.0, 0.0, offset_hz=4.0, drift_hz_s=0.01)  # noise only
    else:  # the dawn condition with a moving offset
        x = run_channel(_long_audio(), snr, rng, "dawn", offset_hz=1.0, drift_hz_s=0.005)  # fading with paths moving apart
    clean = longbeacon.clean(x)  # carriers removed, as the receiver does
    for found in longbeacon.candidates(clean):  # the real search
        if longbeacon.decode_at(clean, found, __import__("modem.frame", fromlist=["RxResult"]).RxResult(start=found["start"])).ok:  # read
            return case, snr, True  # yes
    return case, snr, False  # no


def threshold(rows, column, share):  # the weakest SNR at which at least `share` of trials decoded, with every stronger point too
    """Return the lowest SNR from which every stronger point reached `share`, or None."""
    rates = sorted(rows.items())  # (snr, [outcomes]) weakest first
    best = None  # nothing yet
    for snr, outcomes in reversed(rates):  # strongest first
        if np.mean([o[column] for o in outcomes]) >= share:  # good enough
            best = snr  # so far
        else:  # a weaker point failed
            break  # stop
    return best  # the threshold


def main():  # run every part
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])  # options
    parser.add_argument("--trials", type=int, default=40)  # trials per point
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))  # processes
    args = parser.parse_args()  # read them
    results = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")  # where results go
    os.makedirs(results, exist_ok=True)  # make sure it exists
    rows = []  # every point, for the table
    a_cases = [("noise only", 0.0, 0.0, 0.0, 0.0)]  # the reference (two fixed paths would leave a permanent notch, so none)
    a_cases += [(f"spread {s} Hz, 1 ms", s, 1.0, 0.0, 0.0) for s in (0.25, 0.5, 1.0, 2.0, 3.0, 4.0)]  # Doppler spread, 0.25 to 4 Hz
    a_cases += [(name, *CONDITIONS[name], *PATH_EXTRAS.get(name, (0.0, 0.0))) for name in ("nvis", "nvis_real", "dawn")]  # and the near-vertical and sunrise cases
    snrs = list(np.arange(-28.0, -11.0, 2.0))  # -28 to -12 dB
    with Pool(args.workers) as pool:  # all cores
        jobs = [(name, s, d, p, h, snr, 1000 * i + t) for i, (name, s, d, p, h) in enumerate(a_cases) for snr in snrs for t in range(args.trials)]  # every trial of part A
        out_a = pool.map(part_a, jobs, chunksize=4)  # run them
        jobs = [(shift, drift, snr, 70000 + 100 * i + t) for i, (shift, drift) in enumerate(((0.0, 0.0), (1.2, 0.005), (2.0, 0.0))) for snr in (-28.5, -27.5) for t in range(args.trials)]  # part B
        out_b = pool.map(part_b, jobs, chunksize=4)  # run them
        jobs = [(cond, level, 90000 + 1000 * i + 100 * level + t) for i, cond in enumerate(("good", "moderate", "poor", "nvis", "nvis_real", "dawn")) for level in (2, 3, 4) for t in range(args.trials // 2)]  # part C
        out_c = pool.map(part_c, jobs, chunksize=2)  # run them
        jobs = [(case, snr, 99000 + 100 * i + t) for i, (case, snr) in enumerate((("offset 4 Hz, drift 0.01 Hz/s", -24.0), ("dawn, 1 Hz offset, drifting", -18.0))) for t in range(args.trials // 2)]  # part D
        out_d = pool.map(part_d, jobs, chunksize=2)  # run them
    print("A  long frame: weakest SNR (2.5 kHz) where 9 in 10 / 1 in 2 decode")  # heading
    print(f"   {'case':28} {'center bin':>16} {'three bins':>16} {'either':>16}")  # columns
    for name, *_ in a_cases:  # each case
        points = {}  # snr -> outcomes
        for row in out_a:  # every trial
            if row[0] == name:  # this case
                points.setdefault(row[1], []).append(row[2:])  # (center, wide, either)
        cells = []  # the three readings
        for column in range(3):  # center, wide, either
            t90, t50 = threshold(points, column, 0.9), threshold(points, column, 0.5)  # both thresholds
            cells.append(f"{t90 if t90 is not None else '>-12':>6} / {t50 if t50 is not None else '>-12':>6}")  # shown
            rows.append(["A", name, ["center", "three bins", "either"][column], t90, t50])  # kept
        print(f"   {name:28} {cells[0]:>16} {cells[1]:>16} {cells[2]:>16}")  # the line
    print("B  two weak copies added (second copy shifted): share decoded")  # heading
    for shift in (0.0, 1.2, 2.0):  # each shift
        for snr in (-28.5, -27.5):  # each level
            got = [r for r in out_b if r[0] == shift and r[1] == snr]  # its trials
            alone, both = np.mean([r[2] for r in got]), np.mean([r[3] for r in got])  # rates
            print(f"   shift {shift:3.1f} Hz at {snr:+.1f} dB: one copy {alone:4.0%}, two added {both:4.0%}")  # the line
            rows.append(["B", f"shift {shift} Hz", f"{snr}", alone, both])  # kept
    print("C  fast levels at +10 dB: share decoded")  # heading
    for cond in ("good", "moderate", "poor", "nvis", "nvis_real", "dawn"):  # each condition
        rates = [np.mean([r[2] for r in out_c if r[0] == cond and r[1] == level]) for level in (2, 3, 4)]  # L2, L3, L4
        print(f"   {cond:10} L2 {rates[0]:4.0%}  L3 {rates[1]:4.0%}  L4 {rates[2]:4.0%}")  # the line
        rows.append(["C", cond, "L2/L3/L4", *rates])  # kept
    print("D  long frame through the real search: share decoded")  # heading
    for case in ("offset 4 Hz, drift 0.01 Hz/s", "dawn, 1 Hz offset, drifting"):  # each case
        got = [r for r in out_d if r[0] == case]  # its trials
        print(f"   {case:32} at {got[0][1]:+.0f} dB: {np.mean([r[2] for r in got]):4.0%}")  # the line
        rows.append(["D", case, got[0][1], np.mean([r[2] for r in got]), ""])  # kept
    with open(os.path.join(results, "skywave_study.csv"), "w", newline="") as handle:  # the table
        csv.writer(handle).writerows([["part", "case", "detail", "value 1", "value 2"]] + rows)  # every point


if __name__ == "__main__":  # run as a program (the workers import this file without running it)
    main()  # go
