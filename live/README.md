# live - Kestrel on real audio

Everything in `modem/` and `link/` works on audio held in memory. This folder connects them to a sound card, a clock and a radio, so Kestrel can be heard, decoded and worked in real time.

**Before transmitting on the air:** the published specification must match this program, you must be licensed for the frequency, and an unattended station must stay within the band segments of FCC rule 97.221(b).

## What is here

| File | Contents |
|---|---|
| `listener.py` | `Listener`: a receiver that takes audio as it arrives and gives back each frame once, when it is complete |
| `audio.py` | Sound-card input and output (through the `sounddevice` package), with conversion between the card's 48,000 samples per second and the modem's 12,000 |
| `ptt.py` | `Ptt`: keys the transmitter by rigctld, a CAT command, the RTS line, the DTR line, or not at all (VOX) |
| `rig.py` | `RigCtl`: sets frequency and mode, and keys the transmitter, through Hamlib's `rigctld` |
| `bands.py` | The preselected frequency for each band, and a check that a frequency keeps the signal inside a 97.221(b) segment |
| `runner.py` | `run_station`: runs one `link.Station` on real audio, in real time |

The tools that use them are in `tools/`: `kestrel_panel.py` (a small control panel), `live_devices.py`, `live_monitor.py`, `live_send.py`, `live_station.py` and `live_frequencies.py`.

## How the listener works

The modem's receiver works on a finished recording. A live station only has a stream. The `Listener` keeps the last 100 seconds of audio (longer than the longest frame) and looks through it once a second, which takes well under half a second of computing. When it finds a whole frame it hands the frame over and cuts it out of its store, so no frame is reported twice. A frame that is still arriving is left alone until the rest comes in.

## Rig control

Kestrel controls the radio through **Hamlib's rigctld**, the same rig-control engine WSJT-X uses. Any radio Hamlib supports can be tuned and keyed, and rigctld can run on another computer on the network. Kestrel does not include Hamlib; it talks to rigctld over a network socket.

```
rigctld -m <model number> -r <serial port> -s <baud>          (start Hamlib's rig server; it listens on port 4532)
python tools/live_station.py --call KO4WSC --grid EM93 --beacon --rig 127.0.0.1:4532 --band 20 --ptt rig --in "USB Audio" --out "USB Audio"
```

## Preselected frequencies

`--band 40`, `--band 30` or `--band 20` tunes the radio to Kestrel's suggested meeting frequency for that band (it needs `--rig`):

| Band | Dial (USB) | Signal occupies |
|---|---|---|
| 40 m | 7101.5 kHz | 7102.0 to 7104.0 kHz |
| 30 m | 10144.0 kHz | 10144.5 to 10146.5 kHz |
| 20 m | 14108.5 kHz | 14109.0 to 14111.0 kHz |

Each keeps the whole signal inside a band segment that FCC rule 97.221(b) allows for automatically controlled stations, so attended stations and unattended mail holders can meet on the same frequency. The segments are shared with other data modes: listen first. `--freq` (kHz) tunes anywhere else, and the tool says whether that frequency is inside a 97.221(b) segment.

**Your own frequencies.** The control panel's frequency drop-down list shows these three followed by any you add with its "Add..." button: a band name, a dial frequency, the radio mode and a note. From the command line, `python tools/live_frequencies.py --add "17 m" 18106.0 --note "evening net"` does the same. Your entries are saved in `local/frequencies.json`. The list marks each frequency as inside a 97.221(b) segment or "attended only".

`--freq` is the dial frequency in kHz; the radio is put in `PKTUSB` (upper sideband, data) unless `--mode` says otherwise. Kestrel's tones sit between 500 and 2500 Hz above the dial frequency.

Without rigctld, the transmitter can be keyed by a CAT command on a serial port (`--ptt cat --port COM5`, which sends the Yaesu commands `TX1;` and `TX0;`), by a serial control line (`--ptt rts` or `--ptt dtr`), or by the radio's own VOX (`--ptt none`).

## Trying it without a radio

Two virtual audio cables (or two real cables between two sound cards) make a complete test bench: station A plays into cable 1 and listens on cable 2; station B does the opposite.

```
python tools/live_devices.py                                                                  (find the device numbers)
python tools/live_station.py --call W1AW --grid FN31 --listen --in <cable 1 out> --out <cable 2 in>
python tools/live_station.py --call KO4WSC --grid EM92 --beacon --in <cable 2 out> --out <cable 1 in> --send "Hello from Kestrel"
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
