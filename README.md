# Kestrel (KES)

Kestrel is an adaptive amateur-radio HF digital mode for short text messages, up to 200 characters per transmission. Two stations measure the radio path as they talk and settle on the fastest speed that conditions allow, stepping down before the link fails and back up when the band improves. Holding a solid signal lock in poor conditions is the main design goal.

**Status: draft design, not yet on the air.** This repository holds the public technical description of the mode, as called for by FCC rule 97.309(a)(4). The specification is versioned so that what is published always matches what is transmitted.

## Installing on Windows

For a PC with nothing on it, build the setup program described in `packaging/README.md` (`packaging\windows\build_windows.ps1`) and run it: it installs Kestrel with its own Python and Hamlib's rig control program.

## What Kestrel does

- **Short messages:** free text, up to 200 characters of 7-bit ASCII, control characters included, sent in 50-, 100-, 150- or 200-character frames. Ordinary English text is compressed when that lets it fit a smaller frame.
- **Adaptive speed:** a family of waveforms, from a slow, very robust level for weak signals up to a fast level for strong ones. The two stations negotiate the level automatically from measured noise, fading, multipath and band.
- **Beacon, answer, lock:** a station beacons its presence; a listener answers; the pair negotiate a level and lock for messaging. Every frame is acknowledged, and failed frames are combined with their retries rather than thrown away.
- **Addresses:** frames between two locked stations carry a short link number; traffic outside a lock and held mail carry full destination and origin callsigns (up to 9 characters, so portable and maritime suffixes fit). A name with no digit, such as ALL, addresses a group.
- **Self-describing frames:** every frame starts with a short signature pattern of tones that belongs to its speed level, then a robust header that states its level and size, so a receiver needs no shared clock slot to decode it.
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
| `modem/` | Modem prototype (Python reference): preamble, speed levels, header, LDPC error correction, text compression, receiver |
| `cpp/` | libkestrel: the heaviest modem routines compiled (C++17, plain C interface), checked against the Python reference; optional (the modem runs in pure Python without it) |
| `link/` | Link layer (Python reference): the rules that make, run and close a contact, and a two-station simulation |
| `live/` | Kestrel on real audio: a continuous receiver, sound-card input and output, rig control through Hamlib's rigctld, and a live station |
| `tests/` | Automated tests |
| `tools/` | Scripts to run by hand: a one-frame demo, a two-station contact demo, the live sound-card tools, the SNR sweeps and the spec table writer |
| `results/` | Measured results: decode rate against SNR, and a picture of the signal |
| `LICENSE`, `docs/LICENSE-CC-BY-4.0.txt`, `NOTICE` | License texts and the attribution notice |

Each folder has its own README.

## Try it

Works the same on Linux, Windows and Raspberry Pi OS (Python 3.10 or newer).

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt        (Windows: .venv\Scripts\pip install -r requirements.txt)
.venv/bin/python -m pytest -q                    (runs the tests; takes a few seconds)
.venv/bin/python tools/demo.py --text "CQ CQ de Q1AAAA" --snr -15 --condition moderate
.venv/bin/python tools/link_demo.py --scenario slip      (two stations hold a contact while conditions fall away and return)
```

The demo sends one message through the simulated channel, decodes it, and writes a sound file and a waterfall picture into `results/`.

**Windows, the short way:** copy the folder to the computer, double-click `setup_windows.bat` once (it needs Python from python.org and the internet), then double-click `kestrel_panel.bat` to open the control panel. The first time, the panel opens **Settings**: enter your callsign and grid, choose your radio type, its serial port and the sound devices that lead to and from the radio, and save. From then on the panel starts listening whenever it opens; **Monitor** (F3) only listens and never transmits. Every function is on the menus; Help > Keyboard shortcuts (F1) lists the keys.

## Where things stand

- **Milestone 1 is done (18 November 2026):** the channel simulator and the first modem slice work end to end in simulation.
- **Milestone 2 is done (18 November 2026):** five speed levels (L0 to L4), automatic level choice, the 60- and 90-second airtime limits, and message splitting. In noise alone, a 200-character message goes as one 16-second frame at -7 dB or better, one 59-second frame down to -12 dB, one 88-second frame down to -14 dB, and four 77-second parts below that; the slowest level decoded every test frame at -21 dB. Fading costs about 9 dB or more. Details and charts are in `modem/README.md` and `results/`.
- **Milestone 3 is done (18 November 2026):** the LDPC error-correcting code, text compression, a 150-character frame size, and the exact level table written into the spec (v0.8). The receiver now decodes about a decibel deeper. A 200-character English message goes as one 13-second frame at -7 dB or better, one 45-second frame down to -13 dB, one 67-second frame down to -14 dB, and three 76-second parts below that.
- The waveform of levels L0 to L4, the header, the error correction and the compression are now fully described in the spec. Items still open are marked **TBD** there.
- **Milestone 4 is done (18 November 2026):** the receiver now measures fading as well as signal strength, and the level choice has a second, more careful set of limits for fading signals (spec v0.9).
- **Milestone 5 is done (18 November 2026):** addresses and message numbers (spec v0.10). Every frame now says who it is for and which message it belongs to. Frames grew slightly. On a steady signal 200 characters now go as one 16-second frame at -7 dB or better, 31 seconds down to -10 dB, 60 seconds down to -12 dB, 89 seconds down to -14 dB, and four 80-second parts below that. On a fading signal the same steps come at +1, -2, -7 and -8 dB.
- **Milestone 6 is done (18 November 2026):** the control frames (spec v0.12): beacon, answer, acknowledgment and identification, with an 18-bit channel report that tells the sender which speed level to use next. An acknowledgment takes 3 seconds at the fastest level and 24 at the slowest.
- **Milestone 7 is done (18 November 2026):** the link rules (spec v0.13), run as two simulated stations. A contact goes beacon, answer, lock, messages both ways, close. Each direction runs at its own speed, set by the station that hears it. In simulation the link stepped from the fastest level to the slowest and back through a 19 dB slide without losing a frame, found its partner again after a 95-second gap, and delivered every message once in 36 fading contacts. See `link/README.md`.
- **Milestone 8 is done (18 November 2026):** the reply window (spec v0.14). When several stations answer one beacon and collide, the next beacon opens four reply slots and each station picks one at random; the caller works the strongest and beacons again for the rest. In simulation, groups of two to five answering stations were all worked.
- **Milestone 9 is done (18 November 2026):** Kestrel on real audio. A continuous receiver, sound-card input and output, transmitter keying, and rig control (frequency, mode, transmit) through Hamlib's rigctld, the rig-control engine WSJT-X uses. Two live stations on one PC, joined by virtual audio cables, completed a whole contact in real time. Not yet tried with a real radio. See `live/README.md`.
- **Preselected frequencies (spec v0.15; moved in v0.29, see below):** one meeting frequency each on 40, 30 and 20 metres (dial 7101.5, 10144.0 and 14108.5 kHz, upper sideband), all inside the 97.221(b) segments. A small control panel (`tools/kestrel_panel.py`) offers them in a drop-down list, and operators can add frequencies of their own.
- **First contact between two real radios (18 November 2026):** two HF transceivers in the same room, one on a dummy load, on 10144.0 kHz. Beacon, answer, lock at the fastest level (L4) in both directions, and a proper close with identification from each side, in 100 seconds. Signal readings were +27 to +33 dB with no fading. No message text was sent in that first contact. Two radio settings mattered: the receive filter must be about 3000 Hz wide, and it must be centred near 1500 Hz of audio (on some radios the data mode centres it elsewhere).
- **Conversations that go on, and working frequencies (spec v0.16):** a contact can be kept open after the traffic is done, with either side sending when it has something to say, and closed properly on request. Once locked, a pair can agree to leave the meeting frequency for a working frequency and return when the contact ends. The control panel lists every callsign heard on the frequency, in a contact or not. Proven in simulation; not yet tried between radios.
- **Calling one station, messages for one callsign, and broadcasts (spec v0.17):** a station can call another by name instead of beaconing; a message can be marked for one callsign and then waits for that station; and a broadcast to ALL reaches every station listening, with no acknowledgment. Proven in simulation; not yet tried between radios.
- **Operating panel (spec v0.21, 19 November 2026; no signal change):** the panel starts listening on its own; a repeating beacon (5 to 60 minutes, paused during contacts, stopping itself after 2 hours with nobody at the keyboard); light and dark themes; a scope with frequency, strength and time scales; receive and transmit level meters with sliders; a CSV logbook at three levels of detail and an ADIF contact log; quick messages; telemetry messages (TLM1) that show which station hears the most, as a guide to net control; a 48-hour stations-heard record; and every function on a menu with keyboard shortcuts.
- Next: try those between the two radios, a contact over a real distance, then store-and-forward.
- On-air tests use only a version of the signal whose spec is already published here.

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
Kestrel (KES) is a new adaptive amateur digital mode: up to 200 characters per transmission, with the two stations negotiating speed automatically from noise, conditions and band. This repo holds the spec (draft v0.15) and a Python prototype of the modem and an HF channel simulator.

## Where it lives
- Folder: the author's development PC.
- Git remotes:
  - a backup copy on a second drive
  - a private local Git server
  - `origin` = `https://github.com/phewen473/Kestrel.git` (public GitHub; the README and NOTICE point to it).
- No server: it runs on the PC only (simulation, no radio yet).

## Language and tools
- Python 3.10 or newer; the local `.venv` uses Python 3.12.10.
- Packages (`requirements.txt`): numpy >= 1.26, scipy >= 1.11, matplotlib >= 3.8, pytest >= 8.0; for the live tools also sounddevice >= 0.4 and pyserial >= 3.5.
- C++17 modem library `cpp/` (CMake, C interface, loaded from Python with ctypes; FFT by pocketfft, BSD). Built with g++ on Linux and MinGW-w64 g++ 16 on Windows.
- Planned, not started: Qt operator program (see Development above).

## How to build
Optional: `python tools/build_native.py` builds the compiled modem library into `modem/_native/` (needs CMake and a C++17 compiler; the modem runs in pure Python without it). Create the environment once:
`python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`.
On Windows, `setup_windows.bat` does both steps and `kestrel_panel.bat` opens the control panel.

## How to run or deploy
- Tests: `.venv\Scripts\python -m pytest -q` (a few seconds).
- One-frame demo: `.venv\Scripts\python tools\demo.py --text "CQ CQ de Q1AAAA" --snr -15 --condition moderate` (writes a WAV and a waterfall picture into `results\`).
- Sweeps: `tools\snr_sweep.py` (L0 decode rate against SNR) and `tools\level_sweep.py` (all levels), `tools\fading_sweep.py` (all levels with fading); results go to `results\`.
- Nothing is deployed. No on-air use until the matching spec version is published.

## Current version and status
- Spec version 0.31 (draft), 22 November 2026 (0.31: a faster, incremental receiver search; nothing sent changed); signal version 0.30 (store and forward: the mail notice frame, mail carried and delivered for other stations; 0.29 moved the calling frequencies and added Channels 1 to 4; 0.27 added the long beacon). Milestones 1 to 9 of the prototype done; first contacts between two real radios made; first over-the-air test at a distance (20 November 2026) heard nothing either way, which led to 0.26.
- Roadmap (spec Section 10): 1. prove the link (0.26: recordings, near-miss reports, fading fix, setup checks); 2. a WSPR-like bottom level for reach (0.27: the long beacon); 3. nets with net-control failover and store-and-forward; 4. a VARA-like top level for throughput.
- Status: **in progress**.

## Where things were left
Last commits:
- 2026-11-22 (0.31R1, no behaviour change): compiled library interface 6: the whole body decoder in one C++ call (pilots to checked body, identical outcomes and soft bits) and the long beacon's carrier notch; about 95% of the receiver's time is now in C++.
- 2026-11-22: **0.31R1** (signal unchanged at 0.30): the receiver hears weaker signals: steady signals notched out of the band, failed control frames added to later copies, expected callsigns tried (own, called, partner, contacts, heard in 48 h), LDPC scale 0.9 / 200 passes; the signal log setting takes effect at once; compiled library interface 5. In a replay of the 22 Nov near misses (an answer at L0 under a steady signal, 3 copies) the old receiver read none of 20, 0.31R1 all 20 down to -23 dB.
- 2026-11-22 (spec unchanged at 0.31): library interface 4: the LDPC body decoder, noise tracking and pilot tracking in C++ (bit for bit, or to rounding, against Python).
- 2026-11-22 (spec unchanged at 0.31): more of the receiver compiled (library interface 3): pattern search, fine timing and the whole header reader in C++, heavy loops shared among up to 8 threads (same answers on any count), the five levels searched side by side. Simulated 6-minute stream: 52.6 s pure Python, 15-18 s now (sandbox, 2 cores), same frames decoded. Installer build script unpacks with tar.
- 2026-11-22 (spec unchanged at 0.31): the compiled modem library begins: `cpp/` builds libkestrel (kestrel.dll / kestrel.so) with a C interface; the blanker, the Viterbi decoder and the tone-band measurement run compiled when the library is present (bit-identical or equal to rounding, checked by tests/test_native.py), with pure Python as the fallback and the reference. Help > About and --check say which is in use; the installer builds the DLL with MinGW. Next: the header search and preamble detection in C++.
- 2026-11-22, spec v0.31 (no signal change): the live receiver searches incrementally. On the 2014 Xeon workstation the old search needed 1.47 s of computing per second of audio and fell behind real time; the new one needs a fraction of that, decoding the same frames (checked on simulated streams and in a new test). Next: the modem core in C++ with a C interface (Python modem kept as the reference).
- 2026-11-21 (panel only, spec unchanged at 0.30): up to 10 quick messages, each named by the operator, managed in Settings > Quick messages (Add, Edit, Delete, Move up/down); Alt+1 to Alt+0 use them; the three earlier quick messages carry over with names. F10 opens Stations > Mail held and carried.
- 2026-11-21, spec v0.30 (new signal version): store and forward, the first part of roadmap step 3. Messages for a named station get a lasting number; in any contact they are handed to the partner to carry (if its "Carry mail for others" setting is on); carriers deliver when the destination beacons or calls, and pass mail on only to stations that hear the destination; a new mail notice frame before the beacon lists whom a station holds mail for, delivery receipts and stations heard. Lifetime 62 hours, hop limit 4. Stations > Mail held and carried shows addresses, IDs and carriers only, never the content of other stations' mail. Mail kept per callsign in a file between runs. Also on the panel since 0.29: transmit scope above the receive scope with zoom; resizable panels; font choice; Floor and Range sliders on both scopes; edit and delete for queued messages.
- 2026-11-21, spec v0.29 (no frame change, new frequencies): calling frequencies moved to an area of Kestrel's own, away from FT8, FT4, JS8, WSPR, VarAC and the Winlink/VARA segments: 80 m 3582.5, 40 m 7110.0, 30 m 10147.0, 20 m 14112.5 kHz. Channels 1 to 4 at 2.5 kHz steps above the calling frequency (one channel on 30 m). Attended stations only in these areas. Radio mode: USB-D where the radio has it, plain USB where not; no lower sideband.
- 2026-11-21: fix (found on the first install of 0.28): the rig type list was empty the first time Settings opened, because rigctld's first run was slower than the 20 seconds allowed while an antivirus program checked it; a radio name typed in its place then stopped Listen with "invalid literal for int()". The list now loads in the background with up to two minutes' patience, typed text that is not a list entry is refused on Save, and the title bar shows the program's version as well as the signal's.
- 2026-11-21: fix: the rig type list in Settings > Radio could be empty with no explanation. It now falls back to the rigctld installed with Kestrel when the saved one is gone, waits longer for a slow first run, says why when the list is empty, and has a "Reload rig list" button.
- 2026-11-21, spec v0.28 (no signal change): pulling signals out of noise. The receiver adds repeated long beacons together (two copies decode at -28 dB on a steady path, four at -29 dB; in the worst fading nine in ten at -26 dB with four copies, against -20 dB for one), notches steady carriers out of the long beacon's band, and follows the noise level through every frame. Listen before transmitting: beacons, calls and broadcasts wait while the frequency is in use (Settings > Operating). Studies: tools/combine_study.py.
- 2026-11-21, spec v0.27 (new signal version): the long beacon, the first part of roadmap step 2: a compact 59.5-second frame (callsign, grid, two flags; no header; 1.17 s tones 2.57 Hz apart, about 82 Hz wide) decoded in simulation down to -25.6 dB on a steady path and -18.6 dB (nine in ten) in the worst fading, 4 to 5 dB below the short beacon. Nobody answers it; it is shown to the operator. Operate > Beacon type: Short (default) or Long (every 10 minutes at most). Study: tools/bottom_study.py.
- 2026-11-21: signal log for analysis and debugging (Settings > Logging > Signal log: off by default; text only, or with each frame's audio under a 500 MB cap), every received sample numbered on one timeline shared with the recordings, tools/signal_report.py to summarise the logs, decode_wav.py --signal-log.
- 2026-11-21, spec v0.26 (new signal version): the second header copy moved to the end of every frame and the receiver ranks preambles by how much of their energy sits on the pattern, which removed most losses in simulated fading; fading limits re-measured; 80 m meeting frequency 3590.0 kHz; frequencies outside the U.S. data segments refused; received audio can be recorded and decoded later (File > Decode a recording, tools/decode_wav.py); signals heard but too weak to read are reported; callsign confirmation; ALC warning.
- 2026-11-19: Windows setup program (packaging/): a self-contained installer with its own Python and Hamlib's rigctld, for a PC with nothing on it; installed copies keep each user's settings and logs in %LOCALAPPDATA%\Kestrel; Kestrel.exe --check.
- 2026-11-19, spec v0.25: Available / Unavailable switch (Ctrl+U): when away, beacons are presence beacons and a call by name gets one short "not available" reply; every station's status shows in Stations heard.
- 2026-11-19, spec v0.24: Listen just listens (nothing sent unless the operator starts it; calls to you are shown for Respond); a calling station takes a call back as the answer.
- 2026-11-19, spec v0.23 (new signal version): call-up at L2 first, L0 if unanswered; reply slots sized to the level; straight to the measured level at lock; directed-call flag carrying the caller's reading.
- 2026-11-19, spec v0.22 (no signal change): Listen no longer answers beacons by itself; the panel lists stations calling, marks messages waiting for them or mail they hold, and the operator responds with a call by name (or chooses automatic answering in Settings).
- 2026-11-19: fix: a directed call asked for while the station was busy no longer goes out by surprise after a later contact ends (it is dropped if a contact starts first; the log says when a call is waiting).
- 2026-11-19, spec v0.21 (no signal change): control panel reworked: starts listening; repeating beacon with interval and automatic stop; themes; labelled scope; level meters and sliders; CSV and ADIF logbook at three levels; quick messages; telemetry messages; 48-hour heard log; full menus and keyboard shortcuts.
- 2026-11-18:
- Help > About shows the signal version and the program's commit; `VERSION` is stamped with the commit when Git makes an archive.
- Spec v0.20: NEW SIGNAL. A twelve-tone preamble in each level's own pattern replaces the two-second chirp pair; earlier versions cannot read it.
- Spec v0.19: the idle limit on a working frequency is three minutes.
- Spec v0.18: an idle working frequency is given up after five minutes, with a one-minute warning to the operator who moved there.
- Spec v0.17: directed calls, messages for one callsign, broadcasts to ALL; panel scope.
- Spec v0.16: lock kept open, end on request, working frequencies; panel lists stations heard.
- First two-radio contact; control panel shows the station's state; rig control asks for a 3000 Hz receive filter; Windows setup files; panel profiles for a second radio.
- Spec v0.15: preselected frequencies for 40, 30 and 20 metres.
- Milestone 9: live sound-card tools, continuous receiver, rig control through rigctld.
- Milestone 8 and spec v0.14: reply window for several answering stations.
- Milestone 7 and spec v0.13: link rules and the two-station simulation.
- Milestone 6 and spec v0.12: control frames (beacon, answer, acknowledgment, identification).
- Spec v0.11: unattended mail holders operate under 97.221(b).
- Milestone 5 and spec v0.10: addresses and message numbers.
- Milestone 4 and spec v0.9: fading measurement and fading-aware level limits.
- Milestone 3 and spec v0.8: LDPC code, text compression, 150-character frame, level table in the spec.
- Spec v0.7: header sent at the frame's own level.
- Milestone 2: speed levels L0-L4, airtime limits and message splitting.
- Spec v0.6: signature chirp fixed as an up/down pair.
- Spec v0.5: airtime limits (60 s, 90 s in poor conditions) and message splitting.
- Milestone 1: HF channel simulator and first modem slice (L0).
- Credit P. H. Ewen (KO4WSC) as original author; licences (Apache-2.0 code, CC BY 4.0 docs), NOTICE and toolchain added.

Next steps (from "Where things stand" above): messages between the two radios and a contact over a real distance, then store-and-forward; nets and L5 after that. Values marked TBD in the spec still need agreeing. Open items are also listed in `docs/spec/kestrel-spec.md`.

Design wishes: beacon announces presence, a listener chooses to answer, then the pair negotiate and lock; nets are optional, with a backup net control "partner" that takes over; store-and-forward considered; must keep a good lock in poor conditions.

## Important files
- `docs/spec/kestrel-spec.md` - the public technical description (FCC 97.309(a)(4)).
- `docs/spec/CHANGELOG.md` - what changed in each spec version.
- `sim/channel.py` - HF channel simulator.
- `docs/spec/tables/` - LDPC check lists and compression codes (written by `tools/make_spec_tables.py`).
- `cpp/` - libkestrel, the compiled modem routines (`include/kestrel.h`, `src/kestrel.cpp`); `modem/native.py` loads it.
- `modem/` - modem prototype (`levels.py`, `plan.py`, `frame.py`, `address.py`, `control.py`, `ldpc.py`, `compress.py`, `fec.py`, `preamble.py`, `mfsk.py` ...); `modem/README.md` has the measured results.
- `link/` - link layer (`station.py`, `adapt.py`, `simulate.py`, `params.py`); `link/README.md` has the rules and what the simulation showed.
- `live/` - real audio (`listener.py`, `audio.py`, `ptt.py`, `rig.py`, `runner.py`); `live/README.md` explains the live tools and the no-radio cable test.
- `tests/` - automated tests (`test_end_to_end.py`, `test_parts.py`, `test_link.py`, `test_live.py`).
- `tools/` - `demo.py`, `snr_sweep.py`, `level_sweep.py`, `fading_sweep.py`, `link_demo.py`, `kestrel_panel.py`, `live_devices.py`, `live_frequencies.py`, `live_monitor.py`, `live_send.py`, `live_station.py`, `make_spec_tables.py`.
- `results/` - sweep CSVs and charts.
- `LICENSE`, `NOTICE`, `docs/LICENSE-CC-BY-4.0.txt` - licences and attribution.

## Notes and gotchas
- `origin` is public GitHub. Every increment is pushed to all three remotes (the local Git server, the backup drive and GitHub), after the private-word check.
- The spec is versioned so that what is published always matches what is transmitted. Change the spec version whenever the signal changes.
- No encryption, ever (Part 97).
- `.venv\`, `__pycache__\`, `.pytest_cache\` and `results/demo.wav` are not tracked (`.gitignore`); recreate them as needed.
- Each subfolder has its own README with more detail.
