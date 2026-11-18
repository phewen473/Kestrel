"""Send one message through the simulated channel, save what it sounds and looks like, and decode it.

Run from the repository root, for example:
    python tools/demo.py --text "CQ CQ de KO4WSC" --snr -15 --condition moderate
    python tools/demo.py --text "CQ CQ de KO4WSC" --level 3 --snr -5
It writes results/demo.wav (play it, or feed it to any waterfall program)
and results/demo_waterfall.png (a picture of the signal).
"""

import argparse  # reads the command-line options
import os  # file paths and folders
import sys  # lets us add the repository root to the import path

import numpy as np  # numerical arrays
from scipy.io import wavfile  # writes WAV sound files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" and "sim" importable when run as a script

from modem import LEVELS, build_frame, receive  # levels, transmitter and receiver  # noqa: E402
from modem.params import FS  # audio sample rate  # noqa: E402
from sim import CONDITIONS, run_channel  # channel simulator  # noqa: E402


def main():  # the script itself
    """Build, transmit, save and decode one frame."""
    parser = argparse.ArgumentParser(description="Kestrel one-frame demonstration")  # describe the tool
    parser.add_argument("--text", default="CQ CQ de KESTREL test", help="message to send (up to 200 characters)")  # the message
    parser.add_argument("--level", type=int, default=0, choices=[spec.number for spec in LEVELS], help="speed level (0 is the slowest)")  # which speed level to send at
    parser.add_argument("--snr", type=float, default=-10.0, help="SNR in 2.5 kHz, in dB")  # how noisy the channel is
    parser.add_argument("--condition", default="awgn", choices=list(CONDITIONS), help="fading condition")  # which fading to apply
    parser.add_argument("--offset", type=float, default=0.0, help="frequency offset in Hz")  # how far off frequency
    parser.add_argument("--seed", type=int, default=1, help="random seed, so a run can be repeated")  # repeatability
    args = parser.parse_args()  # read the options
    out_dir = os.path.join(ROOT, "results")  # where the files go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    clean = build_frame(args.text, args.level)  # the transmitted audio
    spec = LEVELS[args.level]  # the numbers for the chosen level
    low = spec.tone_bins[0] * spec.bin_hz  # lowest tone frequency, in Hz
    high = spec.tone_bins[-1] * spec.bin_hz  # highest tone frequency, in Hz
    heard = run_channel(clean, args.snr, np.random.default_rng(args.seed), args.condition, offset_hz=args.offset)  # what the receiver hears
    scaled = np.int16(np.clip(heard / np.max(np.abs(heard)), -1, 1) * 32000)  # scale to 16-bit sound
    wavfile.write(os.path.join(out_dir, "demo.wav"), FS, scaled)  # save the sound
    import matplotlib  # plotting library
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [1, 2]})  # two panels: the chirp close up, and the whole frame
    axes[0].specgram(clean[:int(2.6 * FS)], NFFT=512, Fs=FS, noverlap=384, cmap="viridis")  # the clean chirp pair and first tones
    axes[0].set_ylim(300, 2700)  # show the part of the audio band Kestrel uses
    axes[0].set_title("Signature chirp (clean)")  # panel title
    axes[0].set_xlabel("Time (s)")  # x-axis title
    axes[0].set_ylabel("Audio frequency (Hz)")  # y-axis title
    nfft = max(256, min(4096, spec.samples))  # analysis window about one tone long
    axes[1].specgram(heard, NFFT=nfft, Fs=FS, noverlap=nfft // 2, cmap="viridis")  # the whole frame as received
    axes[1].set_ylim(low - 0.75 * (high - low), high + 0.75 * (high - low))  # zoom in on the tones
    axes[1].set_title(f"L{args.level} tones as received ({args.condition}, {args.snr:g} dB)")  # panel title
    axes[1].set_xlabel("Time (s)")  # x-axis title
    fig.tight_layout()  # trim the margins
    fig.savefig(os.path.join(out_dir, "demo_waterfall.png"), dpi=130)  # save the picture
    result = receive(heard)  # try to decode
    print("decoded:     ", result.ok, result.reason, "  level found: L" + str(result.level))  # did it work, and if not why
    print("text:        ", repr(result.text))  # the message that came out
    print("measured SNR:", round(result.snr_db, 1), "dB")  # the receiver's own SNR reading
    print("offset:      ", round(result.offset_hz, 2), "Hz   drift:", round(result.drift_hz_s, 4), "Hz/s")  # frequency error and drift
    print("airtime:     ", round(len(clean) / FS, 1), "s")  # how long the frame took


if __name__ == "__main__":  # only when run as a script
    main()  # go
