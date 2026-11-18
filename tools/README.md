# tools - scripts to run by hand

Run them from the repository root. All of them write into `results/`.

## demo.py - send one message and look at it

```
python tools/demo.py --text "CQ CQ de KO4WSC" --snr -15 --condition moderate
```

Builds one frame, passes it through the simulated channel, and decodes it. It prints what the receiver found and writes:

- `results/demo.wav` - what the receiver heard. Play it, or feed it to any waterfall program.
- `results/demo_waterfall.png` - a picture of the signature chirp and the tones.

Options: `--text`, `--level` (0 to 4), `--snr` (dB in 2.5 kHz), `--condition` (`awgn`, `good`, `moderate`, `poor`), `--offset` (Hz), `--seed`.

## snr_sweep.py - measure L0 decode rate against SNR, with and without fading

```
python tools/snr_sweep.py --trials 40
```

Sends many random 40-character messages at each SNR value under each channel condition and counts how many decode. It writes `results/l0_snr_sweep.csv` (the numbers) and `results/l0_snr_sweep.png` (the chart). The full run takes about ten minutes on two processor cores; use `--conditions awgn` for a quick noise-only run.

## level_sweep.py - measure every speed level

```
python tools/level_sweep.py --trials 40
```

Does the same in noise only for each speed level, L0 to L4. It writes `results/levels_snr_sweep.csv` and `results/levels_snr_sweep.png`. The lowest SNR at which every frame decodes is what `modem/levels.py` records for each level. It takes a few minutes.

## make_spec_tables.py - write the specification's tables

```
python tools/make_spec_tables.py
```

Writes the tables that the specification refers to into `docs/spec/tables/`: the LDPC check lists for each frame size (`ldpc_checks_k374.txt` and so on) and the compression code of every character (`compression_codes.txt`). The tables come straight from the modem code, so the published description and the program cannot drift apart. Run it again whenever `modem/ldpc.py` or `modem/compress.py` changes.
