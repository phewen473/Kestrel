# Kestrel (KES)

Kestrel is an adaptive amateur-radio HF digital mode for short text messages, up to 200 characters per transmission. Two stations measure the radio path as they talk and settle on the fastest speed that conditions allow, stepping down before the link fails and back up when the band improves. Holding a solid signal lock in poor conditions is the main design goal.

**Status: draft design, not yet on the air.** This repository holds the public technical description of the mode, as called for by FCC rule 97.309(a)(4). The specification is versioned so that what is published always matches what is transmitted.

## What Kestrel does

- **Short messages:** free text, up to 200 characters of 7-bit ASCII, control characters included, sent in 50-, 100- or 200-character frames.
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
| `sim/` | HF channel simulator: noise, fading, multipath, offset, drift, static crashes |
| `modem/` | Modem prototype (Python reference): chirp, L0 waveform, header, error correction, receiver |
| `tests/` | Automated tests |
| `tools/` | Scripts to run by hand: a one-frame demo and the SNR sweep |
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
- The signature chirp pair is agreed and in the spec. The other numbers the prototype uses are test values; the spec keeps them as **TBD** until they are agreed.
- Next: text compression, the LDPC code, fading-aware level limits, then the link layer (beacon, answer, negotiation, acknowledgments).
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
