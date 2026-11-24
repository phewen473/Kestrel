"""Compare two ways of marking the start of a Kestrel frame.

Run from the repository root:

    python tools/preamble_study.py                (the full study; several minutes)
    python tools/preamble_study.py --trials 20    (a quick look)

The signal on the air today starts every frame with the same two-second
chirp pair, 2 kHz wide, whatever the speed level. This study asks whether
a short, fixed pattern of the level's own tones would do the job instead.
Such a pattern would get shorter as the level gets faster, would keep a
slow frame as narrow as its data, and would tell the receiver the level.

For each speed level, at the weakest signals that level is meant to work
at, many test frames are sent through the simulated channel with a random
start time and a random frequency error. Each kind of preamble is then
searched for, and the study records how often the true start is among the
receiver's three best guesses (the receiver tries three and lets the
header's check value decide), and how exact the timing and frequency are.

Nothing here changes the modem. Results go to results/preamble_study.csv.
"""

import argparse  # reads the command-line options
import csv  # writes the results table
import os  # file paths
import sys  # lets us add the repository root to the import path

import numpy as np  # numerical arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem.chirp import detect_chirp_pair, make_chirp_pair  # today's preamble and its detector  # noqa: E402
from modem.levels import LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB  # the speed levels and their weakest working signals  # noqa: E402
from modem.mfsk import symbols_to_audio  # turns tone numbers into sound  # noqa: E402
from modem.params import FS, M_TONES  # the sample rate and the number of tones  # noqa: E402
from sim import run_channel  # the HF channel simulator  # noqa: E402

PATTERN_SEED = 0x4B455300  # "KES" and a zero: the seed that fixes each level's tone pattern
PAD = 2  # the pattern search looks at frequencies half a bin apart
HOPS = 4  # and at start times a quarter of a tone apart
MAX_OFFSET_HZ = 50.0  # the largest frequency error searched for, the same as the chirp detector's
DATA_TONES = 12  # random data tones sent after the preamble, as a real frame would have
KEEP = 3  # how many candidate starts the receiver keeps


def pattern_tones(level, length):  # the fixed tone pattern for a level
    """Return `length` tone numbers, all different, in an order fixed for ever by the level number."""
    return np.random.default_rng(PATTERN_SEED + level).permutation(M_TONES)[:length]  # the first few of a fixed shuffle of the 32 tones


def detect_pattern(x, spec, tones):  # look for a tone pattern in a recording
    """Return up to KEEP candidates, strongest first, as dicts with start (samples) and offset_hz.

    The recording is cut into tone-length blocks a quarter of a tone
    apart. For every possible start and frequency error, the energy found
    where each tone of the pattern ought to be is added up; the largest
    totals are the candidates. Each is then placed more exactly by trying
    start times a sixteenth of a tone apart around it.
    """
    n, hop = spec.samples, spec.samples // HOPS  # block length and step between blocks, in samples
    count = (len(x) - n) // hop + 1  # how many blocks fit
    if count < HOPS * len(tones):  # the recording is too short to hold the pattern
        return []  # nothing to find
    blocks = np.lib.stride_tricks.sliding_window_view(x, n)[::hop][:count]  # every block, without copying
    power = np.abs(np.fft.rfft(blocks, PAD * n, axis=1)) ** 2  # the energy at every frequency in every block
    bins = PAD * spec.tone_bins[tones]  # where each tone of the pattern sits, in half-bin steps
    reach = int(np.ceil(MAX_OFFSET_HZ / (spec.bin_hz / PAD)))  # how many half-bin steps the frequency error may be
    starts = count - HOPS * (len(tones) - 1)  # how many start positions leave room for the whole pattern
    shifts = np.arange(-reach, reach + 1)  # the frequency errors tried
    total = np.zeros((starts, len(shifts)))  # the energy total for every start and every frequency error
    for k, center in enumerate(bins):  # one tone of the pattern at a time
        total += power[HOPS * k:HOPS * k + starts][:, center + shifts]  # the energy where that tone should be, k tones after the start
    found, work = [], total.copy()  # the candidates, and a scratch copy to cross them off
    for _ in range(KEEP):  # the strongest few
        row, col = np.unravel_index(int(np.argmax(work)), work.shape)  # the largest total left
        work[max(row - HOPS, 0):row + HOPS + 1, :] = 0  # cross off everything within a tone of it
        best_start, best_sum = row * hop, -1.0  # the fine search starts from the coarse answer
        for start in range(max(row * hop - hop, 0), min(row * hop + hop, len(x) - n * len(tones)) + 1, n // 16):  # a sixteenth of a tone at a time, a quarter of a tone each way
            pieces = x[start:start + n * len(tones)].reshape(len(tones), n)  # the recording cut exactly into the pattern's tones
            energy = np.abs(np.fft.rfft(pieces, PAD * n, axis=1)) ** 2  # the energy at every frequency in each
            here = float(energy[np.arange(len(tones)), bins + shifts[col]].sum())  # the total where the pattern's tones should be
            if here > best_sum:  # the best alignment so far
                best_start, best_sum = start, here  # remember it
                below = float(energy[np.arange(len(tones)), bins + shifts[col] - 1].sum())  # the total half a bin lower in frequency
                above = float(energy[np.arange(len(tones)), bins + shifts[col] + 1].sum())  # and half a bin higher
        bend = below - 2 * best_sum + above  # how sharply the total peaks across frequency
        nudge = 0.5 * (below - above) / bend if bend < 0 else 0.0  # where between the half-bin steps the true peak lies
        found.append({"start": float(best_start), "offset_hz": float((shifts[col] + nudge) * spec.bin_hz / PAD)})  # this candidate's timing and frequency error
    return found  # strongest first


def trial(spec, kind, length, snr_db, condition, rng):  # send one test frame and look for its start
    """Return (found, timing error in tones, frequency error in tone spacings) for one frame; the errors are None when it was not found."""
    data = rng.integers(0, M_TONES, DATA_TONES)  # random data tones to follow the preamble
    if kind == "chirp":  # today's preamble
        frame = np.concatenate([make_chirp_pair(), symbols_to_audio(data, spec)])  # the chirp pair, then data
    else:  # a tone pattern
        tones = pattern_tones(spec.number, length)  # this level's pattern
        frame = np.concatenate([symbols_to_audio(tones, spec), symbols_to_audio(data, spec)])  # the pattern, then data
    lead = int(rng.integers(0, FS // 2))  # a random extra wait before the frame, up to half a second
    offset = float(rng.uniform(-20.0, 20.0))  # a random frequency error
    heard = run_channel(np.concatenate([np.zeros(lead), frame]), snr_db, rng, condition, offset_hz=offset)  # through the channel (which adds a second of silence each end)
    truth = FS + lead  # the sample where the frame really starts
    guesses = detect_chirp_pair(heard, keep=KEEP) if kind == "chirp" else detect_pattern(heard, spec, tones)  # the receiver's best guesses
    spacing_hz = spec.step * spec.bin_hz  # the distance between neighboring tones
    for guess in guesses:  # any of the three will do: the header's check value picks the right one
        time_error = (guess["start"] - truth) / spec.samples  # how far out the timing is, in tones
        freq_error = (guess["offset_hz"] - offset) / spacing_hz  # how far out the frequency is, in tone spacings
        if abs(time_error) <= 0.25 and abs(freq_error) <= 0.5:  # close enough for the tones that follow to be read
            return True, time_error, freq_error  # found
    return False, None, None  # not found


def main():  # the script itself
    """Run the study and write the results."""
    parser = argparse.ArgumentParser(description="Kestrel preamble study: chirp pair against tone patterns")  # describe the tool
    parser.add_argument("--trials", type=int, default=100, help="test frames per point (default 100)")  # how thorough
    parser.add_argument("--lengths", type=int, nargs="+", default=[8, 12, 16], help="tone-pattern lengths to try, in tones")  # which patterns
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "preamble_study.csv"), help="where to write the table")  # the results file
    args = parser.parse_args()  # read the options
    rows = []  # the results table
    print(f"{'level':5s} {'channel':9s} {'SNR':>5s}  {'preamble':10s} {'seconds':>7s} {'width Hz':>8s} {'found':>6s} {'timing':>7s} {'freq':>6s}")  # the column headings
    for spec in LEVELS:  # each speed level
        width_hz = (M_TONES - 1) * spec.step * spec.bin_hz + 2 * spec.bin_hz  # how wide the level's tones are
        points = [("awgn", MIN_SNR_DB[spec.number]), ("awgn", MIN_SNR_DB[spec.number] - 2.0),  # noise only: at the level's limit, and 2 dB beyond it
                  ("moderate", MIN_SNR_FADING_DB[spec.number]), ("poor", MIN_SNR_FADING_DB[spec.number])]  # fading: at the level's fading limit
        for condition, snr_db in points:  # each test condition
            for kind, length in [("chirp", 0)] + [("pattern", n) for n in args.lengths]:  # today's preamble, then each tone pattern
                rng = np.random.default_rng(1000 * spec.number + 17 * length + len(condition))  # repeatable random numbers for this point
                results = [trial(spec, kind, length, snr_db, condition, rng) for _ in range(args.trials)]  # the test frames
                hits = [r for r in results if r[0]]  # those whose start was found
                seconds = 2.0 if kind == "chirp" else length * spec.seconds  # how long the preamble lasts
                width = 2000.0 if kind == "chirp" else width_hz  # how wide it is
                timing = float(np.sqrt(np.mean([r[1] ** 2 for r in hits]))) if hits else float("nan")  # typical timing error, in tones
                freq = float(np.sqrt(np.mean([r[2] ** 2 for r in hits]))) if hits else float("nan")  # typical frequency error, in tone spacings
                name = "chirp pair" if kind == "chirp" else f"{length} tones"  # what to call it
                rows.append([spec.number, condition, snr_db, name, round(seconds, 3), round(width), len(hits) / args.trials, round(timing, 4), round(freq, 4)])  # one row of the table
                print(f"L{spec.number:<4d} {condition:9s} {snr_db:+5.0f}  {name:10s} {seconds:7.2f} {width:8.0f} {len(hits) / args.trials:6.0%} {timing:7.3f} {freq:6.3f}", flush=True)  # show it as it is measured
    os.makedirs(os.path.dirname(args.out), exist_ok=True)  # make sure the results folder exists
    with open(args.out, "w", newline="", encoding="utf-8") as handle:  # open the results file
        writer = csv.writer(handle)  # a CSV writer
        writer.writerow(["level", "channel", "snr_db", "preamble", "seconds", "width_hz", "found", "timing_rms_tones", "freq_rms_spacings"])  # the headings
        writer.writerows(rows)  # the measurements
    print(f"written: {os.path.relpath(args.out, ROOT)}")  # say where the table went


if __name__ == "__main__":  # only when run as a script
    main()  # go
