# live - Kestrel on real audio

Everything in `modem/` and `link/` works on audio held in memory. This folder connects them to a sound card, a clock and a radio, so Kestrel can be heard, decoded and worked in real time.

**Before transmitting on the air:** the published specification must match this program, you must be licensed for the frequency, and an unattended station must stay within the band segments of FCC rule 97.221(b).

## What is here

| File | Contents |
|---|---|
| `listener.py` | `Listener`: a receiver that takes audio as it arrives and gives back each frame once, when it is complete; it can also report a Kestrel preamble whose header could not be read (a "near miss": the other station is there but too weak or faded). Since 0.31R2 a near miss carries `pattern_tones`, how many of its 12 pattern tones stood out; `likely_kestrel` (7 or more) tells a real Kestrel frame from another mode's signal, and only those are shown to the operator (runner.py `NearFilter`, once a minute per signal) |
| `audio.py` | Sound-card input and output (through the `sounddevice` package), with conversion between the card's 48,000 samples per second and the modem's 12,000 |
| `ptt.py` | `Ptt`: keys the transmitter by rigctld, a CAT command, the RTS line, the DTR line, or not at all (VOX) |
| `rig.py` | `RigCtl`: sets frequency and mode, and keys the transmitter, through Hamlib's `rigctld` |
| `bands.py` | The preselected frequency for each band (80, 40, 30 and 20 m), a check that a frequency keeps the signal inside a 97.221(b) segment, and a check that it is inside the U.S. data segments at all |
| `runner.py` | `run_station`: runs one `link.Station` on real audio, in real time, with hooks the control panel uses to ask for a beacon or call and to log every frame |
| `contacts.py` | `ContactBook`: the operator's contact book (`contacts.json`): each saved station's details, last reading and a history of traffic with it (30 to 200 entries, default 120; all traffic or completed contacts only), fed by the logbook's events; grid locator distance and bearing (since 0.31R3) |
| `heardlog.py` | `HeardLog`: every station decoded in the last 48 hours, kept on disk |
| `logbook.py` | `Logbook` (its `observers`, such as the contact book, are told of every event at any level of detail): a CSV file per UTC day at three levels of detail (basic, advanced, verbose) and an ADIF file of completed contacts |
| `telemetry.py` | Telemetry messages (TLM1, spec Section 6.12): build one from the heard log, read one back, and compare stations |
| `theme.py` | Light and dark looks for the control panel, and following Windows' own setting |
| `recorder.py` | `TimedSource`: numbers every received sample, so the listener, the signal log and the recordings share one timeline (sample n arrived at t0 + n / 12000); `Recorder` and `RecordingSource`: save the received audio to hourly 16-bit WAV files (12,000 samples per second, kept 7 days); `read_wav` reads any WAV file back at the modem's rate |
| `busy.py` | `ChannelWatch`: listening before transmitting. It hears the same audio as the receiver and says whether anything other than noise is on the part of the band a transmission would use (half-second blocks, 50 Hz strips, each against its own noise floor of the last two minutes) |
| `signallog.py` | `SignalLog`: the signal log, a JSON Lines file per UTC day for analysis and debugging (every strong preamble candidate and what became of it, every frame with all the receiver's measurements, near misses, transmissions, the radio's meters, frequency changes, link decisions, input level and clock checks), with optional WAV clips of each frame under a size cap. Off unless turned on |
| `mixer.py` | Windows' recording level for a sound device, through the `pycaw` package, for the panel's receive-level slider |

The tools that use them are in `tools/`: `kestrel_panel.py` (the control panel), `live_devices.py`, `live_monitor.py`, `live_send.py`, `live_station.py` and `live_frequencies.py`.

## How the listener works

The modem's receiver works on a finished recording. A live station only has a stream. The `Listener` keeps the last 100 seconds of audio (longer than the longest frame) and looks at it once a second. When it finds a whole frame it hands the frame over and cuts it out of its store, so no frame is reported twice. A frame that is still arriving is left alone until the rest comes in.

**Incremental search (since 0.31).** Before 0.31 the listener searched the whole 100 seconds again every second. That cost about 1.5 seconds of computing per second of audio on a 2014 Xeon, so on older computers it fell behind and decoded frames late. Now it:

- looks for signature patterns only in the audio that arrived since the last look, plus enough before it to hold a whole pattern and 4 seconds more to measure the background;
- follows up a pattern only if it scores above a per-level gate (`GATE`) set at about twice the best chance match seen in noise, and below what real frames score 1 dB beneath each level's decoding limit (the long beacon has no gate, so weak copies still reach the combiner that adds repeats together);
- times each pattern finely once, when it is followed up, rather than every candidate every second;
- remembers each candidate by its place in the stream, reads its header once, keeps the header, and decodes the frame once it has all arrived; a candidate whose first header copy failed is tried again only at places its second copy could now be, until its frame has passed.

On simulated band noise this is about a seventh of the old computing, and on streams with frames about a quarter. On the 2014 Xeon workstation, 24 simulated six-minute streams (frames at every level, steady and fading, long beacons, mostly near their decoding limits) took the old search 1.1 to 1.8 times real time and the new one 0.2 to 0.4 times; the new search decoded 116 frames to the old one's 114 (three the old missed, one it missed itself: a frame at its level's limit whose header read depends on small timing differences). The old search is kept (`Listener(incremental=False)`) and a test checks that both decode the same frames at the same places. The static-crash blanker was also made faster without changing what it does.


With the compiled modem library (`cpp/`, loaded by `modem/native.py`) the pattern search, fine timing and header reading run in C++, and the five levels and the long beacon are searched side by side on worker threads (the library lets go of Python's lock while it works). The answers are the same as the pure Python search; only the time changes.


Since 0.31R1 the listener also helps weak control frames: it notches steady signals out of the store before searching (modem/notch.py), keeps the soft bits of control frames that fail their check for 30 minutes (`priors`), and asks the station, through `expect`, for its own callsign and the callsigns it expects; each failed control frame is then tried added to earlier copies and with those callsigns (modem/frame.py `Hints`). The panel supplies stations heard in the last 48 hours and saved contacts; run_station adds the station being called and the partner.


Since library interface 7 the listener's audio store, its stream numbers and its candidate list live in the compiled library (`modem/native.py` CompiledListener): the library blanks and notches the store, searches all levels side by side, times candidates finely, reads headers and reports near misses, and hands the listener each frame that is ready; the listener decodes it with the same Python code as before and tells the library what to cut out. `Listener(compiled=False)` keeps the whole Python version, the reference that tests compare against.

`AudioOut.abort()` cuts the transmission being played short (the panel's Stop calling key); `play()` returns within a fiftieth of a second and the runner takes the transmitter off. `bands.band_of(dial_khz)` names the amateur band of a dial frequency ("20m"), for the panel's Band columns.

`signallog.Guarded(log, say)` wraps a SignalLog so that a fault inside it is reported once (with a `signal_log_fault_...txt` file beside the log) and the station carries on; the panel uses it. (On 22 Nov 2026 a long-beacon candidate, traced at level 7, made the log index the five speed levels and stopped the station with "tuple index out of range"; fixed, and guarded against.)

## Rig control

Kestrel controls the radio through **Hamlib's rigctld**, the same rig-control engine WSJT-X uses. Any radio Hamlib supports can be tuned and keyed, and rigctld can run on another computer on the network. Kestrel does not include Hamlib; it talks to rigctld over a network socket.

```
rigctld -m <model number> -r <serial port> -s <baud>          (start Hamlib's rig server; it listens on port 4532)
python tools/live_station.py --call Q1AAAA --grid EM93 --beacon --rig 127.0.0.1:4532 --band 20 --ptt rig --in "USB Audio" --out "USB Audio"
```

## Preselected frequencies

`--band 80`, `--band 40`, `--band 30` or `--band 20` tunes the radio to Kestrel's calling frequency for that band (it needs `--rig`). From version 0.29 (spec Sections 6.9 and 6.10):

| Band | Calling (dial, USB) | Channels 1 to 4 (dial) |
|---|---|---|
| 80 m | 3582.5 kHz | 3585.0, 3587.5, 3590.0, 3592.5 |
| 40 m | 7110.0 kHz | 7112.5, 7115.0, 7117.5, 7120.0 |
| 30 m | 10147.0 kHz | 10144.5 (one channel only) |
| 20 m | 14112.5 kHz | 14115.0, 14117.5, 14120.0, 14122.5 |

Upper sideband on every band: `RigCtl.set_data_mode` asks the radio for its data mode (USB-D) and falls back to plain USB when the radio has none. Lower sideband is not used.

Each keeps the whole signal inside a band segment that FCC rule 97.221(b) allows for automatically controlled stations, so attended stations and unattended mail holders can meet on the same frequency. The segments are shared with other data modes: listen first. `--freq` (kHz) tunes anywhere else, and the tool says whether that frequency is inside a 97.221(b) segment.

**Your own frequencies.** The control panel's frequency drop-down list shows these three followed by any you add with its "Add..." button: a band name, a dial frequency, the radio mode and a note. From the command line, `python tools/live_frequencies.py --add "17 m" 18106.0 --note "evening net"` does the same. Your entries are saved in `local/frequencies.json`. The list marks each frequency as inside a 97.221(b) segment or "attended only".

`--freq` is the dial frequency in kHz; the radio is put in `PKTUSB` (upper sideband, data) unless `--mode` says otherwise. Kestrel's tones sit between 500 and 2500 Hz above the dial frequency.

Without rigctld, the transmitter can be keyed by a CAT command on a serial port (`--ptt cat --port COM5`, which sends the Yaesu commands `TX1;` and `TX0;`), by a serial control line (`--ptt rts` or `--ptt dtr`), or by the radio's own VOX (`--ptt none`).

## Trying it without a radio

Two virtual audio cables (or two real cables between two sound cards) make a complete test bench: station A plays into cable 1 and listens on cable 2; station B does the opposite.

```
python tools/live_devices.py                                                                  (find the device numbers)
python tools/live_station.py --call Q2BB --grid FN31 --listen --in <cable 1 out> --out <cable 2 in>
python tools/live_station.py --call Q1AAAA --grid EM92 --beacon --in <cable 2 out> --out <cable 1 in> --send "Hello from Kestrel"
```

## Scripts for your own station

Batch files or shell scripts that name your callsign, sound devices and serial port belong in a folder called `local/` at the top of the repository. Git ignores that folder, so station details never reach the public repository.

## What the first live test showed (18 November 2026)

Two copies of `live_station.py` on one PC, joined by two virtual audio cables, made a complete contact in real time: beacon, answer, lock, two messages one way and one the other, and the closing identifications, in 2 minutes 17 seconds. Nothing was lost.

Two things were found and fixed:

- **The sound card cut off the last fifth of a second of every transmission.** Frames still decoded, because the error correction covered the loss, but the receiver read the missing tones as fading. Each transmission is now followed by half a second of silence.
- **The static-crash blanker silenced strong signals.** It judged "loud" against the whole recording, so a strong frame in a mostly quiet recording looked like one long crash. It now judges each tenth of a second against its own surroundings.

Five lessons from testing; the first four are now built in:

- **Name sound devices, never number them.** Windows renumbers its sound devices whenever one is plugged in or removed (a Bluetooth headset connecting is enough), and a station given numbers then plays into the wrong device. The tools accept part of a device's name, and the control panel stores names.
- **A station leaves a full second between its own transmissions,** and starts each with a third of a second of silence, so the radio and sound card are settled before the chirp.
- **Ask the radio for a wide receive filter.** In the first two-radio test the tuned radio heard nothing: rig control had left it on its narrow data filter (600 Hz), which removed the signal. Tuning now asks for a 3000 Hz filter, which Kestrel's 500 to 2500 Hz chirp needs.
- **A busy computer can lose received audio.** With the control panel and the decoder sharing one computer, the sound card occasionally threw away a little audio that was not collected in time, and one acknowledgment failed its check. The sound card is now opened with generous buffering, and if it still loses audio the station says so in its log.
- **Check where the radio centres its data-mode filter.** One radio centred its data filter on 0 Hz of audio instead of 1500 Hz, so even a 3000 Hz filter passed only the lower half of the signal. Slow frames just got through and fast ones read as heavy fading. On that radio the cure was its data shift menu setting, put back to 1500 Hz. If a strong, steady signal reports a high fading index, look at the receive filter first.

## Not done yet

- **Messages between real radios, and a real distance.** Two radios in one room have locked at L4 and closed properly (18 November 2026), but no text was sent, and nothing has been tried over a path with real noise and fading.
- **Hearing while transmitting.** The station ignores its input while it transmits, and for the moment after.
- **Timing on a busy computer.** The station allows 10 seconds beyond a reply's own length before deciding it was lost.
