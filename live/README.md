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
| `runner.py` | `run_station`: runs one `link.Station` on real audio, in real time |

The tools that use them are in `tools/`: `live_devices.py`, `live_monitor.py`, `live_send.py` and `live_station.py`.

## How the listener works

The modem's receiver works on a finished recording. A live station only has a stream. The `Listener` keeps the last 100 seconds of audio (longer than the longest frame) and looks through it once a second, which takes well under half a second of computing. When it finds a whole frame it hands the frame over and cuts it out of its store, so no frame is reported twice. A frame that is still arriving is left alone until the rest comes in.

## Rig control

Kestrel controls the radio through **Hamlib's rigctld**, the same rig-control engine WSJT-X uses. Any radio Hamlib supports can be tuned and keyed, and rigctld can run on another computer on the network. Kestrel does not include Hamlib; it talks to rigctld over a network socket.

```
rigctld -m <model number> -r <serial port> -s <baud>          (start Hamlib's rig server; it listens on port 4532)
python tools/live_station.py --call KO4WSC --grid EM92 --beacon --rig 127.0.0.1:4532 --freq 14108.5 --ptt rig --in "USB Audio" --out "USB Audio"
```

`--freq` is the dial frequency in kHz; the radio is put in `PKTUSB` (upper sideband, data) unless `--mode` says otherwise. Kestrel's tones sit between 500 and 2500 Hz above the dial frequency.

Without rigctld, the transmitter can be keyed by a CAT command on a serial port (`--ptt cat --port COM5`, which sends the Yaesu commands `TX1;` and `TX0;`), by a serial control line (`--ptt rts` or `--ptt dtr`), or by the radio's own VOX (`--ptt none`).

## Trying it without a radio

Two virtual audio cables (or two real cables between two sound cards) make a complete test bench: station A plays into cable 1 and listens on cable 2; station B does the opposite.

```
python tools/live_devices.py                                                                  (find the device numbers)
python tools/live_station.py --call W1AW --grid FN31 --listen --in <cable 1 out> --out <cable 2 in>
python tools/live_station.py --call KO4WSC --grid EM92 --beacon --in <cable 2 out> --out <cable 1 in> --send "Hello from Kestrel"
```

## What the first live test showed (18 November 2026)

Two copies of `live_station.py` on one PC, joined by two virtual audio cables, made a complete contact in real time: beacon, answer, lock, two messages one way and one the other, and the closing identifications, in 2 minutes 17 seconds. Nothing was lost.

Two things were found and fixed:

- **The sound card cut off the last fifth of a second of every transmission.** Frames still decoded, because the error correction covered the loss, but the receiver read the missing tones as fading. Each transmission is now followed by half a second of silence.
- **The static-crash blanker silenced strong signals.** It judged "loud" against the whole recording, so a strong frame in a mostly quiet recording looked like one long crash. It now judges each tenth of a second against its own surroundings.

## Not done yet

- **A test with a real radio.** Audio levels, the radio's filters and transmitter keying have not been tried.
- **Hearing while transmitting.** The station ignores its input while it transmits, and for the moment after.
- **Timing on a busy computer.** The station allows 10 seconds beyond a reply's own length before deciding it was lost.
