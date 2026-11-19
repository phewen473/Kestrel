# tools - scripts to run by hand

Run them from the repository root. All of them write into `results/`.

## demo.py - send one message and look at it

```
python tools/demo.py --text "CQ CQ de Q1AAAA" --snr -15 --condition moderate
```

Builds one frame, passes it through the simulated channel, and decodes it. It prints what the receiver found and writes:

- `results/demo.wav` - what the receiver heard. Play it, or feed it to any waterfall program.
- `results/demo_waterfall.png` - a picture of the signature tone pattern and the tones that follow.

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
python tools/live_devices.py                                           (list the sound devices; give the other tools part of a NAME, since Windows renumbers devices)
python tools/live_monitor.py --in "USB Audio"                          (receive only: print every Kestrel frame heard)
python tools/live_send.py --call Q1AAAA --grid EM92 --out "USB Audio"  (transmit one beacon)
python tools/live_station.py --call Q1AAAA --grid EM92 --beacon --send "Hello"   (a whole contact, in real time)
```

```
python tools/kestrel_panel.py                                          (a small control panel: the same things, with drop-down lists)
python tools/kestrel_panel.py --profile second                         (a second panel with its own settings, for a second radio on the same computer)
python tools/live_frequencies.py                                       (show the frequency list; --add and --remove your own)
python tools/preamble_study.py                                         (compare the chirp pair with a tone-pattern preamble; several minutes)
```

`kestrel_panel.py` is the control panel. How it is laid out:

- **Settings > Rig Information** (menu): callsign and grid locator; the radio type (from Hamlib's list of several hundred), the CAT serial port, its speed and handshake; how the transmitter is keyed (CAT, RTS, DTR or none) and the serial port for RTS or DTR; the sound devices to and from the radio and the transmit audio level. The panel starts and stops Hamlib's `rigctld` itself for the radio chosen, so there is nothing else to run. It looks for `rigctld` on the search path and in a WSJT-X installation; the dialog can also be pointed at the file, or at a rigctld already running.
- **Frequency list:** Kestrel's meeting frequencies plus your own ("Add..." and "Remove"). Choosing a frequency tunes the radio to it at once, with a 3000 Hz receive filter. A change is refused while a station is on the air.
- **Status band:** the station's state in large letters. A lock shows as a solid green band naming the partner; trouble holding the link turns it amber, a failure red. Under it, one line gives the partner's signal strength, whether it is steady or fading, the speed level in each direction, and how many messages are waiting and received.
- **Keep contact open / End contact / Once locked:** tick "Keep contact open" to hold the lock after the traffic is done, so either station can send whenever a message is typed; "End contact" closes it properly. "Once locked" chooses whether the pair stay on the calling frequency or move to a working frequency and return at the end (needs rig control; a partner that cannot retune simply declines).
- **Idle working frequency:** if no message passes for two minutes on a working frequency, the station that proposed the move shows a warning; a minute later the contact is closed and both radios return to the calling frequency. OK only takes the warning away. Sending a message keeps the contact where it is.
- **Stations heard:** every callsign decoded on the frequency, with grid, signal strength and time, whether or not this station is in a contact. Beacons, answers and identifications carry callsigns; message frames between other stations do not.
- **To / Call station / Broadcast to ALL:** put a callsign in the To box and a queued message is sent only to that station (blank means whoever the partner is). "Call station (To)" calls that callsign by name instead of beaconing; only that station answers. "Broadcast to ALL" sends the typed message to every station listening, at the slowest level and with no acknowledgment; it goes out when no contact is in progress. Broadcasts received appear in "Messages received" as "CALLSIGN to ALL", in Monitor too.
- **Contacts and waiting messages:** "Save as contact" keeps a callsign from the stations-heard list for later (marked `*`, kept in `local/contacts.json`). The To box is a drop-down of saved contacts and stations heard; double-clicking a callsign in the list fills it in. A message queued for a callsign waits until that station is the partner: when it answers your beacon, when you answer its beacon while listening, or when you call it. Waiting messages are kept in `local/` and come back when the panel is reopened.
- **Messages to send / Messages received:** two lists. A message to send shows as waiting, sending, then delivered with the time. A message typed while the station is running goes into the contact in progress.
- **Scope:** a spectrum trace and waterfall of the receive audio from 0 to 3000 Hz, running whenever Monitor, Listen or Beacon is on. Dashed lines mark 500 and 2500 Hz, the edges of a Kestrel signal, so a receive filter that is too narrow or off-centre shows at a glance.
- **Activity:** the log in plain words; "Show technical details" shows every measurement and field. The full log is also kept in `local/panel.log` (or `local/panel_NAME.log` for a named profile).

Settings, your own frequencies and the log are kept in `local/`, which Git ignores.

`live_station.py` also takes `--call-station CALLSIGN` (in place of `--beacon` or `--listen`), `--to CALLSIGN` (the `--send` messages go only to that station) and `--broadcast TEXT` (sent to ALL first, unacknowledged). It takes `--keep-open` (hold the lock after the traffic), `--end-after SECONDS` (then close it properly) and `--move KHZ` (once locked, propose a working frequency that many kHz away; needs `--rig`).

`live_send.py` and `live_station.py` take `--ptt none|rig|cat|rts|dtr`, `--rig host:port`, `--band 40|30|20` (Kestrel's preselected frequency for that band), `--freq` (kHz), `--mode`, `--port`, `--baud` and `--gain`. Only transmit where your licence allows, with the published specification matching the program.

## make_spec_tables.py - write the specification's tables

```
python tools/make_spec_tables.py
```

Writes the tables that the specification refers to into `docs/spec/tables/`: the LDPC check lists for each frame size (`ldpc_checks_k402.txt` and so on) and the compression code of every character (`compression_codes.txt`). The tables come straight from the modem code, so the published description and the program cannot drift apart. Run it again whenever `modem/ldpc.py` or `modem/compress.py` changes.

## Preamble study

`preamble_study.py` compares the two-second chirp pair that starts every frame today with a short fixed pattern of each level's own tones. It changes nothing in the modem. For every level, at that level's weakest working signals (noise only, and moderate and heavy fading), it sends test frames with a random start and a random frequency error and records how often the true start is among the receiver's three best guesses, and how exact the timing and frequency are. Results go to `results/preamble_study.csv`.

First results (200 frames per point, 18 November 2026): a 12-tone pattern was found in 98 to 100 percent of frames at every level and condition, against 100 percent for the chirp pair (98 percent for the chirp 2 dB beyond L0's limit). The pattern would last 4.8 s at L0, 1.6 s at L1, 1.1 s at L2, 0.54 s at L3 and 0.27 s at L4, against 2 s for the chirp at every level, and would be as narrow as the level's data (160 Hz at L0) instead of 2 kHz. Not yet tested: telling the five patterns apart, false starts in long recordings and beside other signals, and whole frames decoded from the pattern's timing.
