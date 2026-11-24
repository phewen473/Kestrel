"""Compare candidate transmit waveforms before any of them becomes part of the signal.

Run from the repository root:

    python tools/waveform_study.py --trials 40

Nothing here changes what Kestrel sends. The tool swaps parts of the
transmitter (and the matching parts of the receiver) inside its own
processes only, then measures two things for each candidate:

  1. its spectrum: how wide the signal is and how much power falls
     outside its own tone band (splatter onto neighbours);
  2. how weak a signal it still decodes on the sky-wave conditions of
     ITU-R F.1487 (sim/channel.py SKYWAVE), and with noise only.

Candidates (VARIANTS below):
  today         the signal as it is (signal version 0.30)
  ramp          today's tones, with a 10 ms fade in and out at the ends of the transmission
  shape25       ramp + each change of tone glides over a quarter of a tone length (continuous phase)
  shape50       ramp + the glide takes half a tone length
  gray          tones numbered in Gray code, so neighbouring tones differ in one bit only
  gray_shape25  gray and shape25 together
  L0_step1 / L0_step3 / L2_step1 / L3_step2   a level's tones 1, 2 or 3 FFT bins apart instead of today's spacing

The pure-Python modem is used throughout (KESTREL_NATIVE=0), because the
compiled library knows only today's waveform. Results go to
results/waveform_spectrum.csv, results/waveform_study.csv and a chart.
"""

import argparse  # reads the command-line options
import csv  # writes the results tables
import os  # file paths, folders and the environment
import sys  # lets us add the repository root to the import path
import time  # measures how long one trial takes
from multiprocessing import Pool  # runs trials on several processor cores at once

os.environ["KESTREL_NATIVE"] = "0"  # the compiled library knows only today's waveform, so every process uses the Python modem

import numpy as np  # numerical arrays  # noqa: E402
from scipy.signal import welch  # averaged spectrum of a long signal  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB, build_frame, receive  # levels, their limits, transmitter, receiver  # noqa: E402
from modem import frame, longbeacon, mfsk, preamble  # the modules whose parts are swapped  # noqa: E402
from modem.params import BITS_PER_SYMBOL, FS, M_TONES  # 5 bits a tone, 12 kHz, 32 tones  # noqa: E402
from sim import SKYWAVE, run_channel  # the sky-wave conditions and the channel simulator  # noqa: E402

VARIANTS = {  # the candidates: gray = Gray-coded tone numbers; alpha = share of a tone length spent gliding to the next tone; ramp_ms = fade at the ends; steps = tone spacing (FFT bins) per level
    "today": {},  # the signal as it is
    "ramp": {"ramp_ms": 10.0},  # fade in and out only
    "shape25": {"alpha": 0.25, "ramp_ms": 10.0},  # gentle glide between tones
    "shape50": {"alpha": 0.5, "ramp_ms": 10.0},  # slower glide between tones
    "gray": {"gray": True},  # Gray-coded tone numbers
    "gray_shape25": {"gray": True, "alpha": 0.25, "ramp_ms": 10.0},  # both
    "L0_step1": {"steps": {0: 1}},  # L0 tones 2.5 Hz apart (80 Hz wide)
    "L0_step3": {"steps": {0: 3}},  # L0 tones 7.5 Hz apart (240 Hz wide)
    "L2_step1": {"steps": {2: 1}},  # L2 tones 11 Hz apart (355 Hz wide)
    "L3_step2": {"steps": {3: 2}},  # L3 tones 44 Hz apart (1420 Hz wide)
}  # end of the table

GRAY = np.array([v ^ (v >> 1) for v in range(M_TONES)])  # Gray code: the tone that carries each 5-bit value
GRAY_VALUE = np.argsort(GRAY)  # the other way round: the 5-bit value each tone carries
PRINTABLE = [chr(c) for c in range(32, 127)]  # characters used to build random test messages
_PENDING = []  # preamble tones waiting to be joined to the rest of the frame (so the whole frame is one smooth waveform)
_CURRENT = {}  # the candidate this process is set up for


def shaped_audio(symbols, spec, alpha=0.0, ramp_ms=0.0):  # tone numbers -> sound, with optional glides and end fades
    """Return the audio of `symbols` at level `spec`: one continuous-phase waveform whose frequency glides over alpha x tone length at each change, faded in and out over ramp_ms."""
    freqs = spec.tone_bins[np.asarray(symbols, dtype=np.int64)] * spec.bin_hz  # frequency of every tone, in Hz
    f = np.repeat(freqs, spec.samples).astype(float)  # the wanted frequency, sample by sample (sudden steps)
    glide = int(round(alpha * spec.samples))  # length of each glide, in samples
    if glide > 1:  # a glide is wanted
        kernel = np.hanning(glide + 2)[1:-1]  # a smooth bump (raised cosine) without its zero end points
        kernel /= kernel.sum()  # scaled so the average frequency, and so the phase at each tone's centre, is kept
        before = glide // 2  # samples of padding needed before the start
        padded = np.concatenate([np.full(before, f[0]), f, np.full(glide - 1 - before, f[-1])])  # hold the first and last frequency at the ends
        f = np.convolve(padded, kernel, mode="valid")  # smooth the steps into glides (same length as before)
    phase = 2 * np.pi * np.concatenate([[0.0], np.cumsum(f[:-1])]) / FS  # running phase: the frequency added up, so the waveform never jumps
    x = np.cos(phase)  # the waveform (identical to today's when alpha and ramp_ms are 0, because every tone holds whole cycles)
    ramp = int(round(ramp_ms * FS / 1000))  # length of each end fade, in samples
    if ramp > 1 and 2 * ramp < len(x):  # a fade is wanted and fits
        edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # smooth rise from 0 to 1
        x[:ramp] *= edge  # fade in
        x[-ramp:] *= edge[::-1]  # fade out
    return x  # the audio


def use_variant(name):  # swap this process's transmitter (and matching receiver parts) to a candidate
    """Set up the modem in this process for candidate `name`. Called once per worker process, before any trial."""
    v = VARIANTS[name]  # the candidate's settings
    _CURRENT.clear()  # forget any earlier setting
    _CURRENT.update(name=name, **v)  # remember this one
    for number, step in v.get("steps", {}).items():  # tone spacing changes
        object.__setattr__(LEVELS[number], "step", step)  # the level record is frozen, so set the field directly (every module shares this one record)
    if v.get("gray"):  # Gray-coded tone numbers
        mfsk._TONE_BITS = np.array([[(GRAY_VALUE[m] >> (BITS_PER_SYMBOL - 1 - j)) & 1 for j in range(BITS_PER_SYMBOL)] for m in range(M_TONES)])  # receiver: the bits each tone stands for
        plain = mfsk.bits_to_symbols  # today's grouping of bits into 5-bit values

        def gray_symbols(bits):  # transmitter: 5-bit values -> Gray-coded tone numbers
            return GRAY[plain(bits)]  # look each value up in the Gray table

        mfsk.bits_to_symbols = frame.bits_to_symbols = longbeacon.bits_to_symbols = gray_symbols  # every module that turns bits into tones
    if v.get("alpha", 0.0) > 0 or v.get("ramp_ms", 0.0) > 0:  # a shaped waveform

        def later_preamble(spec):  # the preamble is held back and sent with the rest, as one waveform
            _PENDING[:] = list(preamble.pattern_tones(spec.number))  # remember its tones
            return np.zeros(0)  # nothing yet

        def whole_frame(symbols, spec):  # preamble + header + body as one smooth waveform
            tones = np.concatenate([np.asarray(_PENDING, dtype=np.int64), np.asarray(symbols, dtype=np.int64)])  # the held-back preamble, then these tones
            _PENDING.clear()  # used up
            return shaped_audio(tones, spec, v.get("alpha", 0.0), v.get("ramp_ms", 0.0))  # one waveform

        frame.make_preamble = longbeacon.make_preamble = later_preamble  # the transmitters call this first ...
        frame.symbols_to_audio = longbeacon.symbols_to_audio = whole_frame  # ... and this straight after


def one_trial(job):  # a single send-and-receive attempt
    """Send one random 40-character message at `level` through `condition` at `snr_db`; return True if it came back exactly."""
    level, condition, snr_db, seed = job  # unpack what to test
    rng = np.random.default_rng(seed)  # a repeatable random source for this trial (the same for every candidate)
    text = "".join(rng.choice(PRINTABLE, size=40))  # a random message that fits the 50-character frame
    heard = run_channel(build_frame(text, level), snr_db, rng, condition, offset_hz=float(rng.uniform(-20, 20)))  # transmit with a random frequency error
    result = receive(heard)  # try to decode it
    return bool(result.ok and result.text == text and result.level == level)  # success only if the exact message and level came back


def spectrum(name, level):  # one candidate's spectrum at one level
    """Return (frequencies, power density as a share of the total per Hz, measures) of a 200-character frame sent as candidate `name` at `level`."""
    spec = LEVELS[level]  # the level's numbers (after any spacing change)
    rng = np.random.default_rng(4242)  # the same message for every candidate
    x = build_frame("".join(rng.choice(PRINTABLE, size=190)), level)  # a long frame, so the averaged spectrum is smooth
    seg = min(len(x), 8 * spec.samples)  # analysis length: eight tones, for a resolution of an eighth of a bin
    freqs, psd = welch(x, fs=FS, window="hann", nperseg=seg, noverlap=seg // 2, detrend=False)  # averaged spectrum
    step_hz = freqs[1] - freqs[0]  # width of one analysis step
    share = psd * step_hz / np.sum(psd * step_hz)  # each step's share of the total power
    cum = np.cumsum(share)  # power below each frequency
    obw = freqs[np.searchsorted(cum, 0.995)] - freqs[np.searchsorted(cum, 0.005)]  # occupied bandwidth: 99 % of the power lies inside it (ITU definition)
    low = spec.tone_bins[0] * spec.bin_hz  # lowest tone, Hz
    high = spec.tone_bins[-1] * spec.bin_hz  # highest tone, Hz

    def outside(margin_hz):  # power further than margin_hz outside the tone band, in dB below the total
        part = np.sum(share[(freqs < low - margin_hz) | (freqs > high + margin_hz)])  # share of the power out there
        return 10 * np.log10(max(part, 1e-15))  # in dB (a very small floor keeps the logarithm finite)

    quiet = np.zeros(FS // 2)  # half a second of silence, as before and after a real transmission (so a click at either end is measured, not hidden by the analysis window)
    short = np.concatenate([quiet, frame.build_ident("Q1AAAA", 1, level=level), quiet])  # a short frame (identification), where the start and end of the transmission weigh most
    sf, sp = welch(short, fs=FS, window="hann", nperseg=min(len(short), 4 * spec.samples), detrend=False)  # its spectrum
    s_share = sp / np.sum(sp)  # each step's share of its total power

    def short_outside(margin_hz):  # the same splatter figure for the short frame
        part = np.sum(s_share[(sf < low - margin_hz) | (sf > high + margin_hz)])  # share of the power out there
        return round(10 * np.log10(max(part, 1e-15)), 1)  # in dB

    peak = np.max(psd)  # the strongest point of the spectrum
    loud = freqs[psd >= peak * 1e-4]  # every frequency within 40 dB of the peak
    measures = {  # the numbers recorded for this candidate and level
        "variant": name, "level": level, "tone_low_hz": round(low, 2), "tone_high_hz": round(high, 2),  # which candidate, and where its tones lie
        "occupied_bw_hz": round(float(obw), 1), "bw_40db_hz": round(float(loud[-1] - loud[0]), 1),  # how wide it is
        "outside_25hz_db": round(outside(25.0), 1), "outside_100hz_db": round(outside(100.0), 1), "outside_300hz_db": round(outside(300.0), 1),  # how much splatters beyond the tones
        "short_outside_100hz_db": short_outside(100.0), "short_outside_300hz_db": short_outside(300.0),  # the same for a short frame (clicks at the ends show here)
    }  # end of the measures
    return freqs, share / step_hz, measures  # the spectrum and its measures


def limit_90(points):  # the weakest SNR at which nine frames in ten decode
    """Given (snr, rate) points sorted by SNR, return the SNR where the rate last rises through 0.9 (interpolated), or None if it never reaches 0.9."""
    if not points or max(r for _, r in points) < 0.9:  # never good enough
        return None  # no limit inside the range tested
    for (s0, r0), (s1, r1) in zip(points[::-1][1:], points[::-1]):  # walk down from the strongest point
        if r0 < 0.9 <= r1:  # the rate crosses 0.9 between these two points
            return s0 + (0.9 - r0) / (r1 - r0) * (s1 - s0)  # straight-line estimate between them
    return points[0][0]  # 0.9 or better everywhere tested: the weakest point tested (the true limit is lower)


def snr_grid(level, condition):  # which SNR values to test
    """Return the SNR values (2 dB apart) tested at `level` under `condition`: around today's noise-only limit, or a wide span around today's fading limit."""
    if condition == "awgn":  # noise only
        first = int(MIN_SNR_DB[level]) - 4  # 4 dB below today's limit
        return list(range(first, first + 8, 2))  # four points
    first = int(MIN_SNR_FADING_DB[level]) - 10  # well below today's fading limit
    return list(range(first, first + 22, 2))  # eleven points, up to 10 dB above today's fading limit (the long echo of NVIS may need more)


def main():  # the script itself
    """Measure every candidate's spectrum, then its decoding on noise and on the sky-wave conditions; save the tables and a chart."""
    parser = argparse.ArgumentParser(description="Compare Kestrel transmit waveform candidates: spectrum and decoding on sky-wave paths")  # describe the tool
    parser.add_argument("--trials", type=int, default=40, help="frames sent at each SNR value")  # how many tries per point
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="processor cores to use")  # how many cores to use
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS), help="candidates to test")  # which candidates
    parser.add_argument("--levels", nargs="+", type=int, default=[0, 1, 2, 3, 4], help="speed levels to test")  # which levels
    parser.add_argument("--conditions", nargs="+", default=["awgn", *SKYWAVE], help="channel conditions to test")  # which conditions
    parser.add_argument("--spectrum-only", action="store_true", help="measure the spectra and stop")  # quick look
    args = parser.parse_args()  # read the options
    out_dir = os.path.join(ROOT, "results")  # where the results go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed

    spectra, measures = {}, []  # spectra kept for the chart, and their measures
    for name in args.variants:  # one candidate at a time
        for level in args.levels:  # one level at a time
            if VARIANTS[name].get("steps") and level not in VARIANTS[name]["steps"]:  # a spacing candidate changes only its own level
                continue  # nothing new to measure here
            with Pool(1, initializer=use_variant, initargs=(name,)) as pool:  # a fresh process, so one candidate's swaps never leak into another's
                freqs, density, m = pool.apply(spectrum, (name, level))  # measure it
            spectra[(name, level)] = (freqs, density)  # keep it for the chart
            measures.append(m)  # keep its measures
            print(f"{name:13s} L{level}  99% width {m['occupied_bw_hz']:7.1f} Hz  40 dB width {m['bw_40db_hz']:7.1f} Hz  outside +25 Hz {m['outside_25hz_db']:6.1f} dB  +100 Hz {m['outside_100hz_db']:6.1f} dB  +300 Hz {m['outside_300hz_db']:6.1f} dB", flush=True)  # show it
    with open(os.path.join(out_dir, "waveform_spectrum.csv"), "w", newline="") as handle:  # the spectrum table
        writer = csv.DictWriter(handle, fieldnames=list(measures[0]))  # columns from the measures
        writer.writeheader()  # column headings
        writer.writerows(measures)  # one row per candidate and level
    _chart_spectra(spectra, args, out_dir)  # draw them
    if args.spectrum_only:  # only the spectra were wanted
        return  # done

    rows, summary = [], []  # every point, and each curve's nine-in-ten limit
    for name in args.variants:  # one candidate at a time
        with Pool(args.workers, initializer=use_variant, initargs=(name,)) as pool:  # worker processes set up for this candidate only
            for level in args.levels:  # one level at a time
                if VARIANTS[name].get("steps") and level not in VARIANTS[name]["steps"]:  # a spacing candidate changes only its own level
                    continue  # skip the others
                for c_index, condition in enumerate(args.conditions):  # one channel condition at a time
                    points = []  # (SNR, rate) along this curve
                    began = time.time()  # when this curve started
                    for snr_db in snr_grid(level, condition):  # one SNR value at a time
                        jobs = [(level, condition, snr_db, 900000 + 50000 * level + 5000 * c_index + 100 * (snr_db + 40) + trial) for trial in range(args.trials)]  # the same seeds for every candidate, so they meet the same noise and fades
                        decoded = sum(pool.map(one_trial, jobs))  # run the trials in parallel and count the successes
                        points.append((snr_db, decoded / args.trials))  # store the point
                        rows.append((name, level, condition, snr_db, args.trials, decoded))  # and the row
                    lim = limit_90(points)  # this curve's nine-in-ten limit
                    summary.append((name, level, condition, None if lim is None else round(lim, 1)))  # store it
                    shown = "not reached" if lim is None else f"{lim:6.1f} dB"  # how to show it
                    print(f"{name:13s} L{level} {condition:9s} 9 in 10 at {shown}  ({' '.join(f'{int(100 * r)}' for _, r in points)} % from {points[0][0]} dB)  {time.time() - began:5.0f} s", flush=True)  # show progress
    with open(os.path.join(out_dir, "waveform_study.csv"), "w", newline="") as handle:  # every point
        writer = csv.writer(handle)  # CSV writer
        writer.writerow(["variant", "level", "condition", "snr_db", "trials", "decoded"])  # column headings
        writer.writerows(rows)  # the rows
    with open(os.path.join(out_dir, "waveform_summary.csv"), "w", newline="") as handle:  # the limits, side by side with today's
        writer = csv.writer(handle)  # CSV writer
        writer.writerow(["variant", "level", "condition", "limit_90_db", "change_from_today_db"])  # column headings (negative change = decodes weaker signals = better)
        today = {(lv, c): lim for n, lv, c, lim in summary if n == "today"}  # today's limits, to compare against
        for n, lv, c, lim in summary:  # every curve
            base = today.get((lv, c))  # today's limit for the same level and condition
            writer.writerow([n, lv, c, lim, "" if lim is None or base is None else round(lim - base, 1)])  # the row
    print("wrote", os.path.join(out_dir, "waveform_summary.csv"))  # say where the results went


def _chart_spectra(spectra, args, out_dir):  # one panel per level, one line per candidate
    """Draw every measured spectrum, in dB relative to its own peak, into results/waveform_spectrum.png."""
    import matplotlib  # plotting library (imported here so the worker processes do not need it)
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface

    fig, axes = plt.subplots(1, len(args.levels), figsize=(4.6 * len(args.levels), 4.2), sharey=True)  # one panel per level, side by side
    for ax, level in zip(np.atleast_1d(axes), args.levels):  # fill each panel
        for (name, lv), (freqs, density) in spectra.items():  # every spectrum of this level
            if lv != level:  # another level's
                continue  # not in this panel
            db = 10 * np.log10(np.maximum(density / density.max(), 1e-12))  # dB below its own peak
            ax.plot(freqs, db, linewidth=0.8, label=name)  # draw it
        spec = LEVELS[level]  # the level's numbers (today's spacing in the main process)
        centre = (spec.tone_bins[0] + spec.tone_bins[-1]) / 2 * spec.bin_hz  # the middle of the tone band
        half = (spec.tone_bins[-1] - spec.tone_bins[0]) * spec.bin_hz  # the tone band's width, used as a half-width of the view
        ax.set_xlim(centre - half - 150, centre + half + 150)  # the band and some room either side
        ax.set_ylim(-90, 3)  # 90 dB of range
        ax.set_title(f"L{level}")  # panel title
        ax.set_xlabel("audio frequency (Hz)")  # x-axis title
        ax.grid(True, alpha=0.3)  # light grid lines
    np.atleast_1d(axes)[0].set_ylabel("dB below peak")  # y-axis title, on the left panel only
    np.atleast_1d(axes)[-1].legend(loc="upper right", fontsize=7)  # legend
    fig.suptitle("Kestrel transmit waveform candidates: spectrum of a 200-character frame")  # overall title
    fig.tight_layout()  # trim the margins
    fig.savefig(os.path.join(out_dir, "waveform_spectrum.png"), dpi=130)  # save the chart
    plt.close(fig)  # free it


if __name__ == "__main__":  # only when run as a script
    main()  # go
