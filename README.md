# Kestrel (KES)

Kestrel is an adaptive amateur-radio HF digital mode for short text messages, up to 200 characters per transmission. Two stations measure the radio path as they talk and settle on the fastest speed that conditions allow, stepping down before the link fails and back up when the band improves. Holding a solid signal lock in poor conditions is the main design goal.

**Status: draft design, not yet on the air.** This repository holds the public technical description of the mode, as called for by FCC rule 97.309(a)(4). The specification is versioned so that what is published always matches what is transmitted.

## What Kestrel does

- **Short messages:** free text, up to 200 characters of 7-bit ASCII, control characters included, sent in 50-, 100-, 150- or 200-character frames. Ordinary English text is compressed when that lets it fit a smaller frame.
- **Adaptive speed:** a family of waveforms, from a slow, very robust level for weak signals up to a fast level for strong ones. The two stations negotiate the level automatically from measured noise, fading, multipath and band.
- **Beacon, answer, lock:** a station beacons its presence; a listener answers; the pair negotiate a level and lock for messaging. Every frame is acknowledged, and failed frames are combined with their retries rather than thrown away.
- **Self-describing frames:** every frame starts with a signature chirp pair (a one-second sweep up, then a one-second sweep down) and a robust header that states its speed level and size, so a receiver needs no shared clock slot to decode it.
- **Nets:** optional nets with a net control station, turn-taking slots and an automatic backup net control.
- **Store and forward for disconnected operation:** no always-on station or infrastructure is needed. Senders keep their messages, other stations carry copies, and mail moves whenever two stations hear each other, with message IDs, hop limits, expiry and delivery receipts.
- **Plain text only:** no encryption, as Part 97 requires.

## What is in this repository

| Path | Contents |
|---|---|
| `docs/spec/kestrel-spec.md` | The technical description (draft) |
| `docs/spec/CHANGELOG.md` | What changed in each version of the spec |
| `docs/spec/tables/` | Tables the spec refers to: the error-correction check lists and the compression codes |
| `sim/` | HF channel simulator: noise, fading, multipath, offset, drift, static crashes |
| `modem/` | Modem prototype (Python reference): chirp, speed levels, header, LDPC error correction, text compression, receiver |
| `tests/` | Automated tests |
| `tools/` | Scripts to run by hand: a one-frame demo, the SNR sweeps and the spec table writer |
| `results/` | Measured results: decode rate against SNR, and a picture of the signal |
| `LICENSE`, `docs/LICENSE-CC-BY-4.0.txt`, `NOTICE` | License texts and the attribution notice |

Each folder has its own README.

## Try it

Works the same on Linux, Windows and Raspberry Pi OS (Python 3.10 or newer).

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt        (Windows: .venv\Scripts\pip install -r requirements.txt)
.venv/bin/python -m pytest -q                    (runs the tests; takes a few seconds)
.venv/bin/python tools/demo.py --text "CQ CQ de KO4WSC" --snr -15 --condition moderate
```

The demo sends one message through the simulated channel, decodes it, and writes a sound file and a waterfall picture into `results/`.

## Where things stand

- **Milestone 1 is done (18 November 2026):** the channel simulator and the first modem slice work end to end in simulation.
- **Milestone 2 is done (18 November 2026):** five speed levels (L0 to L4), automatic level choice, the 60- and 90-second airtime limits, and message splitting. In noise alone, a 200-character message goes as one 16-second frame at -7 dB or better, one 59-second frame down to -12 dB, one 88-second frame down to -14 dB, and four 77-second parts below that; the slowest level decoded every test frame at -21 dB. Fading costs about 9 dB or more. Details and charts are in `modem/README.md` and `results/`.
- **Milestone 3 is done (18 November 2026):** the LDPC error-correcting code, text compression, a 150-character frame size, and the exact level table written into the spec (v0.8). The receiver now decodes about a decibel deeper, and heavy fading costs 4 dB less than before. A 200-character English message goes as one 13-second frame at -7 dB or better, one 45-second frame down to -13 dB, one 67-second frame down to -14 dB, and three 76-second parts below that.
- The waveform of levels L0 to L4, the header, the error correction and the compression are now fully described in the spec. Items still open are marked **TBD** there.
- **Milestone 4 is done (18 November 2026):** the receiver now measures fading as well as signal strength, and the level choice has a second, more careful set of limits for fading signals (spec v0.9). On a fading path a 200-character message goes as one 16-second frame at -1 dB or better, one 30-second frame at -2 dB, one 59-second frame down to -7 dB, and four 76-second parts below that.
- Next: addresses and message IDs, then the link layer (beacon, answer, negotiation, acknowledgments).
- No on-air testing will happen until the spec describing that version of the signal is published here.

## Development

Kestrel is being built for Linux, Windows and Raspberry Pi alike.

- **Design and testing:** Python (NumPy, SciPy, matplotlib) for the HF channel simulator and modem prototypes. Python stays as the test bench for everything that follows.
- **Modem core:** a portable C++ library built with CMake, with a plain C interface.
- **Operator program:** Qt, so one program runs on all platforms.
- **Radio and audio:** Hamlib for rig control, PortAudio for sound.

## License and attribution

- **Software:** Apache License 2.0 (`LICENSE`).
- **Specification and documents (`docs/`):** Creative Commons Attribution 4.0 International (`docs/LICENSE-CC-BY-4.0.txt`).

Both licenses require credit to the original. Anyone redistributing or modifying Kestrel must keep the `NOTICE` file, credit the original Kestrel project at https://github.com/phewen473/Kestrel, and state clearly what they changed.

## Contact

Questions and comments are welcome through this repository's Issues.

---

# Project notes (for picking the work back up)

_README last updated 2026-11-18._ The sections above are the public description and were left as they were; the notes below are for the project owner.

## What it is
Kestrel (KES) is a new adaptive amateur digital mode: up to 200 characters per transmission, with the two stations negotiating speed automatically from noise, conditions and band. This repo holds the spec (draft v0.9) and a Python prototype of the modem and an HF channel simulator.

## Where it lives
- Folder: the author's development PC.
- Git remotes:
  - a backup copy on a second drive
  - a private local Git server
  - `origin` = `https://github.com/phewen473/Kestrel.git` (public GitHub; the README and NOTICE point to it).
- No server: it runs on the PC only (simulation, no radio yet).

## Language and tools
- Python 3.10 or newer; the local `.venv` uses Python 3.12.10.
- Packages (`requirements.txt`): numpy >= 1.26, scipy >= 1.11, matplotlib >= 3.8, pytest >= 8.0.
- Planned, not started: C++ modem core with CMake and a C interface, Qt operator program, Hamlib, PortAudio (see Development above).

## How to build
Nothing to compile yet. Create the environment once:
`python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`.

## How to run or deploy
- Tests: `.venv\Scripts\python -m pytest -q` (a few seconds).
- One-frame demo: `.venv\Scripts\python tools\demo.py --text "CQ CQ de KO4WSC" --snr -15 --condition moderate` (writes a WAV and a waterfall picture into `results\`).
- Sweeps: `tools\snr_sweep.py` (L0 decode rate against SNR) and `tools\level_sweep.py` (all levels), `tools\fading_sweep.py` (all levels with fading); results go to `results\`.
- Nothing is deployed. No on-air use until the matching spec version is published.

## Current version and status
- Spec version 0.9 (draft), 18 November 2026. Milestones 1 to 4 of the prototype done.
- Status: **in progress**.

## Where things were left
Last commits (all 2026-11-18):
- Milestone 4 and spec v0.9: fading measurement and fading-aware level limits.
- Milestone 3 and spec v0.8: LDPC code, text compression, 150-character frame, level table in the spec.
- Spec v0.7: header sent at the frame's own level.
- Milestone 2: speed levels L0-L4, airtime limits and message splitting.
- Spec v0.6: signature chirp fixed as an up/down pair.
- Spec v0.5: airtime limits (60 s, 90 s in poor conditions) and message splitting.
- Milestone 1: HF channel simulator and first modem slice (L0).
- Credit P. H. Ewen (KO4WSC) as original author; licences (Apache-2.0 code, CC BY 4.0 docs), NOTICE and toolchain added.

Next steps (from "Where things stand" above): addresses and message IDs, then the link layer (beacon, answer, negotiation, acknowledgments). Values marked TBD in the spec still need agreeing. Open items are also listed in `docs/spec/kestrel-spec.md`.

Design wishes: beacon announces presence, a listener chooses to answer, then the pair negotiate and lock; nets are optional, with a backup net control "partner" that takes over; store-and-forward considered; must keep a good lock in poor conditions.

## Important files
- `docs/spec/kestrel-spec.md` - the public technical description (FCC 97.309(a)(4)).
- `docs/spec/CHANGELOG.md` - what changed in each spec version.
- `sim/channel.py` - HF channel simulator.
- `docs/spec/tables/` - LDPC check lists and compression codes (written by `tools/make_spec_tables.py`).
- `modem/` - modem prototype (`levels.py`, `plan.py`, `frame.py`, `ldpc.py`, `compress.py`, `fec.py`, `chirp.py`, `mfsk.py` ...); `modem/README.md` has the measured results.
- `tests/` - automated tests (`test_end_to_end.py`, `test_parts.py`).
- `tools/` - `demo.py`, `snr_sweep.py`, `level_sweep.py`, `fading_sweep.py`, `make_spec_tables.py`.
- `results/` - sweep CSVs and charts.
- `LICENSE`, `NOTICE`, `docs/LICENSE-CC-BY-4.0.txt` - licences and attribution.

## Notes and gotchas
- `origin` is public GitHub. The standing rule is to push to the local Git server and the backup drive; pushing to GitHub is his decision each time.
- The spec is versioned so that what is published always matches what is transmitted. Change the spec version whenever the signal changes.
- No encryption, ever (Part 97).
- `.venv\`, `__pycache__\`, `.pytest_cache\` and `results/demo.wav` are not tracked (`.gitignore`); recreate them as needed.
- Each subfolder has its own README with more detail.
