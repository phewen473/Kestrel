# Kestrel (KES)

Kestrel is an adaptive amateur-radio HF digital mode for short text messages, up to 200 characters per transmission. Two stations measure the radio path as they talk and settle on the fastest speed that conditions allow, stepping down before the link fails and back up when the band improves. Holding a solid signal lock in poor conditions is the main design goal.

**Status: draft design, not yet on the air.** This repository holds the public technical description of the mode, as called for by FCC rule 97.309(a)(4). The specification is versioned so that what is published always matches what is transmitted.

## What Kestrel does

- **Short messages:** free text, up to 200 characters of 7-bit ASCII, control characters included, sent in 50-, 100- or 200-character frames.
- **Adaptive speed:** a family of waveforms, from a slow, very robust level for weak signals up to a fast level for strong ones. The two stations negotiate the level automatically from measured noise, fading, multipath and band.
- **Beacon, answer, lock:** a station beacons its presence; a listener answers; the pair negotiate a level and lock for messaging. Every frame is acknowledged, and failed frames are combined with their retries rather than thrown away.
- **Self-describing frames:** every frame starts with a short frequency sweep (a chirp) and a robust header that states its speed level and size, so a receiver needs no shared clock slot to decode it.
- **Nets:** optional nets with a net control station, turn-taking slots and an automatic backup net control.
- **Store and forward for disconnected operation:** no always-on station or infrastructure is needed. Senders keep their messages, other stations carry copies, and mail moves whenever two stations hear each other, with message IDs, hop limits, expiry and delivery receipts.
- **Plain text only:** no encryption, as Part 97 requires.

## What is in this repository

| Path | Contents |
|---|---|
| `docs/spec/kestrel-spec.md` | The technical description (draft) |
| `docs/spec/CHANGELOG.md` | What changed in each version of the spec |
| `LICENSE`, `docs/LICENSE-CC-BY-4.0.txt`, `NOTICE` | License texts and the attribution notice |

Software (channel simulator, modem and operator program) will be added here as it is built.

## Where things stand

- Design decisions are being drafted; numbers marked **TBD** in the spec are placeholders.
- Next: complete the written spec, then build an HF channel simulator, then a modem prototype.
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
