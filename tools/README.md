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

## fading_sweep.py - measure every speed level with fading

```
python tools/fading_sweep.py --trials 40
```

Sends random messages at every level through noise only and through light, moderate and heavy fading, across a range of SNR values. For each point it records how many frames decoded, how far the receiver's own SNR reading was from the truth, and the receiver's fading index. It writes `results/levels_fading_sweep.csv` and `results/levels_fading_sweep.png`. The lowest SNR at which nine frames in ten decode in the worst of the three fading conditions is what `modem/levels.py` records as each level's fading limit. It takes about twenty minutes on two processor cores.

## link_demo.py - watch two stations hold a contact

```
python tools/link_demo.py --scenario slip
```

Runs two simulated stations through a whole contact (beacon, answer, lock, messages both ways, close) while the radio path changes, prints every transmission and each station's decisions, and writes `results/link_<scenario>.png`. Scenarios: `steady`, `asymmetric` (one direction strong, one weak), `slip` (conditions fall away and come back), `dropout` (the path vanishes for a minute and a half), `fading`, `dead` (the path dies for good), and `group` (three stations answer one beacon and the caller works each in turn).

## live_devices.py, live_monitor.py, live_send.py, live_station.py - Kestrel on a sound card

These four work with real audio and need the `sounddevice` package (and `pyserial` for serial-port keying); both are in `requirements.txt`. See `live/README.md` for how they fit together, rig control, and a no-radio test with audio cables.

```
python tools/live_devices.py                                           (list the sound devices and their numbers)
python tools/live_monitor.py --in "USB Audio"                          (receive only: print every Kestrel frame heard)
python tools/live_send.py --call KO4WSC --grid EM92 --out "USB Audio"  (transmit one beacon)
python tools/live_station.py --call KO4WSC --grid EM92 --beacon --send "Hello"   (a whole contact, in real time)
```

`live_send.py` and `live_station.py` take `--ptt none|rig|cat|rts|dtr`, `--rig host:port`, `--freq` (kHz), `--mode`, `--port`, `--baud` and `--gain`. Only transmit where your licence allows, with the published specification matching the program.

## make_spec_tables.py - write the specification's tables

```
python tools/make_spec_tables.py
```

Writes the tables that the specification refers to into `docs/spec/tables/`: the LDPC check lists for each frame size (`ldpc_checks_k402.txt` and so on) and the compression code of every character (`compression_codes.txt`). The tables come straight from the modem code, so the published description and the program cannot drift apart. Run it again whenever `modem/ldpc.py` or `modem/compress.py` changes.
