"""Wide-spacing long frame study (after 0.35): would tones further apart help the long frame in fast fading?

Today's long frame (long beacon and long notes) sends 1.1667 s tones 3 bins (2.57 Hz) apart, about
82 Hz in all. This study builds the same frame with tones 5 bins (4.29 Hz) apart, about 137 Hz in
all, and decodes both, at the known start, after two-path fading (1 ms between the paths) at Doppler
spreads from 0 to 6 Hz and noise from -30 to -12 dB, three ways:
  own      each tone's own bin only;
  three    own bin first, then the bin either side added (the 0.34R1 receiver);
  five     (5-bin spacing only) own bin, then three bins, then the two bins either side as well.
Prints the weakest SNR at which nine frames in ten decode (every stronger point too).
Results: results/wide_spacing_study.csv.  Run: python tools/wide_spacing_study.py [--trials 40]
"""

import argparse  # options
import csv  # the results table
import os  # paths
import sys  # import path
from multiprocessing import Pool  # many frames at once

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository

import numpy as np  # arrays

from modem import longbeacon  # the long frame's parts
from modem.levels import Level  # a level's numbers
from modem.longbeacon import LAYOUT, _normalized, decode_energies, pack  # the body layout, normalizing, decoding, the fields
from modem.crc import crc16  # the check value
from modem.fec import conv_encode  # the convolutional code
from modem.interleave import interleave  # the bit shuffler
from modem.mfsk import band_energies, bits_to_symbols, pilot_frequency_fit, transmission  # tones and their measurement
from modem.params import FS, LONG_LEVEL, LONG_SAMPLES, M_TONES, PREAMBLE_TONES  # numbers
from modem.preamble import pattern_tones  # the twelve-tone pattern
from sim.channel import _analytic, add_noise, watterson  # the channel's parts

SPREADS = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0)  # Doppler spreads, Hz
SNRS = tuple(np.arange(-30.0, -9.0, 2.0))  # -30 to -10 dB in 2.5 kHz
LEVELS = {3: Level(LONG_LEVEL, LONG_SAMPLES, 3), 5: Level(LONG_LEVEL, LONG_SAMPLES, 5)}  # today's spacing and the wide one
AUDIO = {}  # the frame's audio for each spacing, made once per worker


def audio_for(step):  # the long beacon sent with tones `step` bins apart
    """Return the audio of a long beacon from Q1AAAA at EM93 with its tones `step` bins apart (same pattern, body, coding)."""
    if step not in AUDIO:  # not made yet
        fields = pack("Q1AAAA", "EM93")  # the fields
        data = np.concatenate([fields, crc16(fields)])  # and the check value
        coded = np.concatenate([conv_encode(data), np.zeros(LAYOUT["padded"] - LAYOUT["coded"], dtype=np.uint8)])  # coded, padded
        body = np.zeros(LAYOUT["total"], dtype=np.int64)  # the body's tones
        body[LAYOUT["data_pos"]] = bits_to_symbols(interleave(coded))  # data tones
        body[LAYOUT["pilot_pos"]] = LAYOUT["pilot_tones"]  # pilots
        AUDIO[step] = transmission(np.concatenate([pattern_tones(LONG_LEVEL), body]), LEVELS[step])  # the waveform
    return AUDIO[step]  # the audio


def readings(x, step):  # the body read every way
    """Return the normalized tone energies of the body at 1 s: own bin, then own plus one bin either side, then plus two either side."""
    level = LEVELS[step]  # the spacing
    start = FS + PREAMBLE_TONES * LONG_SAMPLES  # the body follows the pattern
    extra, drift = pilot_frequency_fit(x, start, LAYOUT["pilot_pos"], LAYOUT["pilot_tones"], level, 0.0)  # frequency and drift from the pilots
    band = band_energies(x, start, LAYOUT["total"], level, extra, drift)  # every bin from one below the lowest tone to one above the highest
    fill = np.median(band, axis=1, keepdims=True) / np.log(2)  # a noise-like value for bins outside the band kept
    band = np.concatenate([fill, band, fill], axis=1)  # one more bin each end (the second neighbor of the edge tones)
    centers = 2 + step * np.arange(M_TONES)  # each tone's column now
    own = band[:, centers]  # own bins
    three = own + band[:, centers - 1] + band[:, centers + 1]  # and the bin either side
    five = three + band[:, centers - 2] + band[:, centers + 2]  # and two either side (only distinct bins when the tones are 5 apart)
    return _normalized(own), _normalized(three), _normalized(five)  # in units of the noise


def one(job):  # one frame
    step, spread, snr, seed = job  # what to try
    rng = np.random.default_rng(seed)  # its own numbers
    audio = audio_for(step)  # the frame
    y = np.concatenate([np.zeros(FS), audio, np.zeros(FS)])  # silence either side
    a = _analytic(y)  # complex form
    if spread > 0:  # fading wanted
        a = watterson(a, spread, 1.0, rng)  # two paths, 1 ms apart
    x = add_noise(a.real, snr, float(np.mean(audio ** 2)), rng)  # and noise
    own, three, five = readings(x, step)  # read every way
    ok_own = decode_energies(own)[0] is not None  # own bin only
    ok_three = ok_own or decode_energies(three, measure=own)[0] is not None  # then three bins (0.34R1)
    ok_five = ok_three or (step == 5 and decode_energies(five, measure=own)[0] is not None)  # then five bins (wide spacing only)
    return step, spread, snr, ok_own, ok_three, ok_five  # the outcomes


def threshold(points):  # weakest SNR with nine in ten, every stronger point too
    """Return the threshold from {snr: share}, or None."""
    best = None  # nothing yet
    for snr in sorted(points, reverse=True):  # strongest first
        if points[snr] >= 0.9:  # good enough
            best = snr  # so far
        else:  # a weaker point failed
            break  # stop
    return best  # the threshold


def main():  # every point
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])  # options
    parser.add_argument("--trials", type=int, default=40)  # frames a point
    args = parser.parse_args()  # read them
    jobs = [(step, s, snr, 100000 * step + 10000 * i + 100 * j + t) for step in (3, 5) for i, s in enumerate(SPREADS) for j, snr in enumerate(SNRS) for t in range(args.trials)]  # every frame
    with Pool(max(1, (os.cpu_count() or 2) - 2)) as pool:  # all cores
        out = pool.map(one, jobs, chunksize=4)  # run them
    rows = []  # for the table
    print("weakest SNR (2.5 kHz) at which nine frames in ten decode; 'above' = not even at -10 dB")  # heading
    print(f"{'spread':>7} | {'3 bins: own':>12} {'own+3':>7} | {'5 bins: own':>12} {'own+3':>7} {'own+3+5':>8}")  # columns
    for s in SPREADS:  # each spread
        cells = []  # the five figures
        for step, col in ((3, 3), (3, 4), (5, 3), (5, 4), (5, 5)):  # spacing and reading
            points = {snr: float(np.mean([r[col] for r in out if r[0] == step and r[1] == s and r[2] == snr])) for snr in SNRS}  # share decoded at each SNR
            t = threshold(points)  # the threshold
            rows.append([step, s, ["own", "three", "five"][col - 3], t] + [points[snr] for snr in SNRS])  # kept
            cells.append(f"{t:+.0f}" if t is not None else "above")  # shown
        print(f"{s:5.1f} Hz | {cells[0]:>12} {cells[1]:>7} | {cells[2]:>12} {cells[3]:>7} {cells[4]:>8}")  # the line
    results = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")  # where results go
    with open(os.path.join(results, "wide_spacing_study.csv"), "w", newline="") as handle:  # the table
        csv.writer(handle).writerows([["step_bins", "spread_hz", "reading", "threshold_db"] + [f"share_at_{snr:+.0f}" for snr in SNRS]] + rows)  # every point


if __name__ == "__main__":  # run as a program
    main()  # go
