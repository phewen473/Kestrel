# tools - scripts to run by hand

Run them from the repository root. Both write into `results/`.

## demo.py - send one message and look at it

```
python tools/demo.py --text "CQ CQ de KO4WSC" --snr -15 --condition moderate
```

Builds one frame, passes it through the simulated channel, and decodes it. It prints what the receiver found and writes:

- `results/demo.wav` - what the receiver heard. Play it, or feed it to any waterfall program.
- `results/demo_waterfall.png` - a picture of the signature chirp and the tones.

Options: `--text`, `--snr` (dB in 2.5 kHz), `--condition` (`awgn`, `good`, `moderate`, `poor`), `--offset` (Hz), `--seed`.

## snr_sweep.py - measure decode rate against SNR

```
python tools/snr_sweep.py --trials 40
```

Sends many random 40-character messages at each SNR value under each channel condition and counts how many decode. It writes `results/l0_snr_sweep.csv` (the numbers) and `results/l0_snr_sweep.png` (the chart). The full run takes about ten minutes on two processor cores; use `--conditions awgn` for a quick noise-only run.
