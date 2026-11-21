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

## decode_wav.py - decode a recording

```
python tools/decode_wav.py local/recordings/rx_20261121_010000Z_Q1AAAA.wav --csv found.csv
```

Plays a WAV file (any sample rate, mono or stereo) through the same receiver the panel uses and lists every frame decoded and every Kestrel signature heard but too weak or faded to read, with the time into the recording, level, signal strength and audio offset. `--csv` also saves the list as a table. It runs at about twice real time: an hour's recording takes about half an hour. The panel offers the same thing as File > Decode a recording, which saves the table beside the WAV file.

Recordings come from the panel's Settings > Logging > Record received audio. Turn it on for every on-air test: if two stations hear nothing, the recordings show whether a signal arrived at all.

## bottom_study.py - how slow must a level below L0 be? (roadmap step 2)

```
python tools/bottom_study.py --trials 40 [--only 0 1 2] [--conditions awgn good] [--snrs -24 -26]
```

Sends beacons through the channel simulator in noise and in light, moderate and heavy fading, with up to 2 Hz of frequency error, and counts how many decode. Candidates 0 to 4 are today's L0 beacon with each tone held longer (0.4, 0.8, 1.6 and 3.2 s) and the tones 1.25 to 5 Hz apart; candidate 5 is the real long beacon of signal version 0.27, received by the full receiver. Writes results/bottom_study*.csv. `--only`, `--conditions` and `--snrs` split the work so many processes can run side by side (a full run is several hours on one core).

Results (21 November 2026, 40 beacons a point): longer tones gain the expected 3 dB per doubling on a steady path (1.6 s tones: -28 dB, 125 s); tones 1.25 Hz apart lose about 6 dB in heavy fading against 2.5 Hz apart; no timed slots were needed. The long beacon chosen for 0.27 (59.5 s) decodes every time down to -25.6 dB on a steady path and nine in ten down to -18.6 dB in the worst fading, against -21 and -14 dB for an L0 beacon.

## combine_study.py - how much further do repeated long beacons reach when added together?

```
python tools/combine_study.py --condition poor --snrs -24 -26 --trials 40
python tools/combine_study.py --noise 600        (false alarms on an empty band)
```

Each trial sends four copies of one station's long beacon through the channel simulator, each with its own noise and fading, and gives them one at a time to the receiver's combiner, recording after how many copies the beacon decoded. Results (21 November 2026, results/combine_study.csv): on a steady path one copy always decodes at -26 dB, two at -28 (39 of 40), three at -28, four at -29; in the worst of the three fading conditions nine in ten decode at -20 dB with one copy, -24 with two or three, and -26 with four. 9,600 stretches of noise alone produced no decode.

## signal_report.py - summarise the signal logs

```
python tools/signal_report.py %LOCALAPPDATA%\Kestrel\logs\signal --since 2026-11-21 --csv-dir report --redecode
```

Reads the signal logs (Settings > Logging > Signal log in the panel; File > Open the signal log folder) and prints a report: sessions; frames received by level with SNR, fading, offset, drift and which header copy was read; stations heard; near misses; how far strong preamble candidates got (no header, header but the body failed, decoded); decodes and near misses by UTC hour and band; transmissions with drive, peak level and the radio's power, ALC and SWR; received audio level, sound-card dropouts and clock drift. `--csv-dir` writes each kind of event as a CSV table for a spreadsheet; `--redecode` decodes every saved clip again and says which now decode or no longer do, to check a receiver change against real signals.

The signal log itself is described at the top of `live/signallog.py`. It is off by default. "On" writes text only: about a line a minute on a quiet band and a few more per signal, a few megabytes a day. "On, with each frame's audio" also saves a WAV clip of every frame and near miss (an L0 frame is about 6 MB); clips are removed after 14 days and kept under 500 MB in total, oldest first. The hourly recordings are a separate setting and the largest, about 86 MB an hour.

`decode_wav.py --signal-log FOLDER [--clips]` writes the same log for a recording decoded afterwards.

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
python tools/kestrel_panel.py                                          (the control panel: the same things, with menus, meters and a logbook)
python tools/kestrel_panel.py --profile second                         (a second panel with its own settings, for a second radio on the same computer)
python tools/live_frequencies.py                                       (show the frequency list; --add and --remove your own)
python tools/preamble_study.py                                         (compare the chirp pair with a tone-pattern preamble; several minutes)
```

`kestrel_panel.py` is the control panel. It starts listening as soon as it opens (Settings > Operating can choose Monitor or nothing instead); the first time, it opens Settings so the callsign, grid, radio and sound devices can be filled in. How it is laid out:

- **Menus and keyboard:** every function is on a menu (File, Operate, Messages, Stations, View, Settings, Help), so the panel can be run without a mouse. Alt and the underlined letter opens a menu; the function keys and Ctrl shortcuts are listed under **Help > Keyboard shortcuts** (F1). F2 Listen, F3 Monitor, F4 Off, F5 beacon on/off, F6 call the station in To, F7 end the contact, F8 stations heard in the last 48 hours, F9 telemetry received, F11 broadcast, F12 Settings, Ctrl+Y respond to the selected station; Ctrl+1 to 3 quick messages, Ctrl+4 and Ctrl+5 telemetry, Ctrl+L the To box, Ctrl+M the message box, Ctrl+R the frequency list, Ctrl+Up and Ctrl+Down the previous and next frequency, Ctrl+G the stations list, Ctrl+J the level sliders.
- **Help > About Kestrel:** the signal version (two stations must match to hear each other), the specification version, the program's commit number and date, and the Python version. The title bar shows both: "Kestrel 0.28 - signal v0.27" means program version 0.28 sending signal version 0.27 (0.28 changed only the receiver).
- **Rig type:** the list loads in the background when Settings opens (the first time on a computer it can take up to a minute while an antivirus program checks rigctld). Pick the radio from the list, or type part of its name to narrow it; text that is not an entry of the list is refused when you save.
- **Settings** (a window with tabs, F12): *Station* (callsign, grid, your name and a rig description for quick messages and the log, the radio's full power in watts); *Radio* (radio type from Hamlib's list, CAT serial port, speed and handshake, how the transmitter is keyed and the port for RTS or DTR, the rigctld program or one already running); *Audio* (the sound devices to and from the radio); *Operating* (what the panel does when it opens, the repeating beacon's interval and its automatic stop); *Logging* (level of detail, recording of the received audio, and the signal log for analysis); *Quick messages*; *Appearance* (theme). The panel starts and stops Hamlib's `rigctld` itself for the radio chosen. The Radio tab says how many radio types are listed; if the list is empty it says why in red (rigctld missing, moved, blocked by an antivirus program, or slow to answer) and the log keeps the reason. If the rigctld in the settings is gone, the copy installed with Kestrel is used instead. "Reload rig list" fills the list again after the cause is fixed, and Browse reloads it from the program chosen.
- **Mode: Listen / Monitor / Off.** Listen just listens: nothing is transmitted unless you start it (beacon, Respond, call, message or broadcast); replies to your own beacon or call are accepted, and a contact you started or accepted runs by itself. Monitor receives only; Off stops both. Beacon, Call station and Broadcast switch to Listen by themselves if needed.
- **Beacon type** (Operate > Beacon type, or Settings > Operating): *Short* (the default) is the call-up others can answer. *Long* sends the long beacon instead: about 60 seconds, heard 4 to 5 dB further down than a short beacon, answered by nobody (stations that hear it show it to their operator, who may respond). Long beacons repeat no more often than every 10 minutes. The button reads "Long beacon (reach)" while Long is chosen. A long beacon heard from another station is highlighted in Stations heard like a beacon, marked "sent a long beacon".
- **Listen before transmitting** (Settings > Operating, on by default): a beacon, long beacon, directed call or broadcast waits while another signal is heard where it would go; the status band shows "WAITING - frequency in use" and the log says when it clears. Replies inside a contact are never held. Signals weaker than about -10 dB may not be noticed, so the frequency is still yours to check. A change takes effect the next time Listen starts.
- **Long beacons heard:** a long beacon too weak to read alone is kept and added to the next ones from the same station; when they decode together the log says "heard long beacon (2 copies added together)". Steady carriers on top of a long beacon are removed automatically.
- **Beacon (call anyone):** a push-on, push-off button. Pushed in, the station sends one beacon and listens for answers, then listens normally until the next round, every 5 minutes by default (Settings > Operating: 5 to 60 minutes). Nothing goes out until the button is first pressed. Rounds pause during a contact; the interval starts again when the contact ends. Push the button again (or F5) to stop. The repeating stops by itself after 2 hours with no keyboard or mouse use (15 minutes to 12 hours, or never). The label beside the button counts down to the next round.
- **Available / Unavailable (Ctrl+U):** a push-on, push-off button, remembered between sessions. Unavailable shows at the top right. While unavailable, your beacons are presence beacons (they say you are on the air but not taking contacts, and nobody answers them), and a station calling you by name gets one short "not available" reply, after which it stops calling. The Stations heard list's "Status and messages" column shows each station's last known availability (from its beacons, or from such a reply). If you leave the station unavailable with nobody at the controls, that reply is automatic operation: keep to the 97.221(b) segments (the Kestrel calling frequencies are inside them).
- **Beacons and calls to you: you choose.** Listen does not answer anything by itself. A station heard beaconing, or calling your callsign by name (marked CALLING YOU), is highlighted in the Stations heard list for five minutes, with a bell and a line in the log. The list's Messages column shows whether you have messages waiting for that station (by name, or for any partner), and whether its beacon says it holds mail (which may be for you) or is asking for its own mail. To answer, select the station and press **Respond** (Ctrl+Y): the panel calls it by name. A station still waiting for answers to its beacon, or still calling you, accepts that call at once. Settings > Operating can switch to answering every beacon and call automatically.
- **Call station (F6):** calls the station in the To box by name. If the station is busy when you press it, the call waits, and the log says so. Pressed during a contact, it is made when that contact ends. Pressed during a beacon round or an answer, it is dropped if a contact starts first (and always if the contact is with the station you meant to call), so an old call never goes out by surprise. Switching to Monitor or Off cancels a waiting call.
- **Frequency list:** Kestrel's meeting frequencies (80, 40, 30 and 20 m) plus your own ("Add..." and "Remove"). A frequency whose signal would fall outside the U.S. amateur data segments cannot be added, and Listen will not start on one; Monitor still can. Choosing a frequency tunes the radio to it, with a 3000 Hz receive filter, and restarts the receiver there. A change is refused during a contact.
- **Status band:** the station's state in large letters. A lock shows as a solid green band naming the partner; trouble holding the link turns it amber, a failure red. Under it, one line gives the partner's signal strength, whether it is steady or fading, the speed level in each direction, and how many messages are waiting and received.
- **Keep contact open / End contact / Once locked:** tick "Keep contact open" to hold the lock after the traffic is done; "End contact" closes it properly. "Once locked" chooses whether the pair stay on the calling frequency or move to a working frequency and return at the end (needs rig control).
- **Idle working frequency:** if no message passes for two minutes on a working frequency, the station that proposed the move shows a warning; a minute later the contact is closed and both radios return to the calling frequency. OK only takes the warning away.
- **To / Quick / Message / Queue / Broadcast to ALL:** a callsign in the To box makes a queued message go only to that station (blank means whoever the partner is). "Quick" offers three ready-made messages, filled in from Settings when used ({call}, {name}, {grid}, {rig}, {power}, {to}, {telemetry}); a quick message goes into the Message box to be checked, then Enter queues it or F11 broadcasts it. "Broadcast to ALL" sends the message to every station listening, at the slowest level, with no acknowledgment.
- **Telemetry:** Messages > Send telemetry to the station in To (Ctrl+4) or Broadcast telemetry to ALL (Ctrl+5) sends what this station hears: its grid, power, and each station heard in the last 30 minutes with its median signal and fastest level, in the TLM1 layout of spec Section 6.12. Telemetry received from others is listed under Stations > Telemetry received (F9), beside this station's own figures, ranked by how many stations each hears and how well: a guide to the best-placed station for net control.
- **Checks before transmitting:** changing the callsign in Settings asks you to confirm it exactly, and something that does not look like a callsign is refused. While transmitting, if the radio's ALC reads half its scale or more, the log says so once per transmission: lower the transmit slider (Ctrl+J) until ALC barely moves.
- **Signals heard but not read:** when the receiver finds a clear Kestrel preamble but cannot read the frame, the log says "possible Kestrel signature heard" with a guess at the level and the audio frequency, and the logbook records it (advanced level and up). It means the other station is reaching you, just not strongly enough.
- **Recordings:** File > Open the recordings folder; File > Decode a recording plays one back through the receiver (see `decode_wav.py` above).
- **Signal log:** Settings > Logging > Signal log: Off (the default), On (text only, a few MB a day) or On with each frame's audio (capped at 500 MB, 14 days). File > Open the signal log folder; summarise it with `signal_report.py` above.
- **Stations heard:** the list on the main window shows every callsign decoded since the panel opened, plus saved contacts (marked `*`). **Stations > Stations heard (last 48 hours)** (F8) shows the longer record, kept in `local/panel_heard.jsonl`: one row per station (first and last heard, times heard, last and best signal, fastest level, frequency), or every reception. Click a heading to sort; Enter or a double-click puts the callsign in To.
- **Contacts and waiting messages:** "Save as contact" keeps a callsign for later (in `local/contacts.json`). A message queued for a callsign waits until that station is the partner. Waiting messages are kept in `local/` and come back when the panel is reopened.
- **Scope:** a spectrum trace above a waterfall of the receive audio. The bottom scale is the audio frequency in Hz, the top scale the radio frequency each point is on, in kHz. The left scale is the signal's strength above the noise in dB; the right scale gives the waterfall's age in seconds. Dashed lines mark 500 and 2500 Hz, the Kestrel band. Each station decoded in the last minute is labelled with its callsign, over a bracket as wide as its signal.
- **Levels:** two vertical meters, receive (radio to PC) and transmit (PC to radio), in dB relative to the sound card's full scale, with a green target band (-30 to -15 dBFS average). The receive meter shows CLIP when the input reaches full scale: turn down the radio's USB audio output level. The slider beside it changes Windows' own recording level for the receive device (needs the `pycaw` package, which `setup_windows.bat` installs). The transmit slider sets the drive to the radio; while transmitting, the power, ALC and SWR the radio reports are shown under it, when the radio and Hamlib offer them.
- **Logging:** a CSV file per UTC day in `local/logs/` (File > Open today's log) and an ADIF file of completed contacts for logging programs. Three levels under Settings > Logging: *basic* (messages, broadcasts, telemetry, start and end of each contact), *advanced* (adds beacons and calls sent, stations heard, signal readings, rig and power) and *verbose* (every frame received or sent, the radio's meters, the input level and the settings in use). ADIF records use mode MFSK, with Kestrel and the signal version in the comment.
- **Theme:** View > Theme: System (follows Windows' light or dark setting), Light or Dark.
- **Activity:** the log in plain words; "Show technical details" shows every measurement and field. The full log is also kept in `local/panel.log` (or `local/panel_NAME.log` for a named profile).

Settings, your own frequencies, saved contacts, the 48-hour heard log and the logbook are kept in `local/`, which Git ignores.

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
