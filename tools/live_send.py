"""Transmit one Kestrel frame through a sound device, keying the transmitter if asked. Nothing is received.

Run from the repository root:

    python tools/live_send.py --call KO4WSC --grid EM92                      (a beacon at the slowest level)
    python tools/live_send.py --call KO4WSC --to ALL --text "Kestrel test"  (a fully addressed message)

Useful options: --out (device number or part of its name), --level 0..4, --gain 0..1,
--ptt none|rig|cat|rts|dtr; --rig host:port with --freq (kHz) and --mode tunes the radio through
Hamlib's rigctld; --port and --baud are for the serial methods. See tools/README.md.

Only transmit where your licence allows, with the published specification matching this program.
"""

import argparse  # reads the command-line options
import os  # file paths
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live" and "modem" importable when run as a script

from live.audio import AudioOut, find_device  # sound-card output  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.bands import dial_khz, in_automatic_segment, signal_khz  # the preselected frequencies  # noqa: E402
from live.rig import RigCtl  # rig control through Hamlib's rigctld  # noqa: E402
from modem import build_beacon, build_frame  # frame builders  # noqa: E402
from modem.params import FS  # audio sample rate  # noqa: E402


def main():  # the script itself
    """Build one frame and send it."""
    parser = argparse.ArgumentParser(description="Kestrel: transmit one frame")  # describe the tool
    parser.add_argument("--call", required=True, help="your callsign")  # who is sending
    parser.add_argument("--grid", default="AA00", help="your four-character grid locator (for a beacon)")  # where from
    parser.add_argument("--to", default=None, help="destination callsign or group name; with --text sends a message instead of a beacon")  # who to
    parser.add_argument("--text", default=None, help="message text (up to 186 characters in one frame)")  # what to say
    parser.add_argument("--level", type=int, default=0, help="speed level 0 (slowest) to 4 (fastest)")  # how fast
    parser.add_argument("--out", dest="sink", default=None, help="output device: a number, or part of its name")  # which device to play on
    parser.add_argument("--gain", type=float, default=0.5, help="audio level, 0 to 1")  # how loud
    parser.add_argument("--ptt", default="none", choices=["none", "rig", "cat", "rts", "dtr"], help="how to key the transmitter (rig = through rigctld)")  # keying method
    parser.add_argument("--rig", default=None, help="address of Hamlib's rigctld, host:port (for example 127.0.0.1:4532)")  # rig control
    parser.add_argument("--band", default=None, help="tune to Kestrel's preselected frequency for this band: 40, 30 or 20 (needs --rig)")  # a preset
    parser.add_argument("--freq", type=float, default=None, help="dial frequency to tune the radio to, in kHz (needs --rig); overrides --band")  # where to tune
    parser.add_argument("--mode", default="PKTUSB", help="radio mode to select when --freq is given (default PKTUSB: upper sideband, data)")  # which mode
    parser.add_argument("--port", default=None, help="serial port for --ptt cat, rts or dtr")  # which port
    parser.add_argument("--baud", type=int, default=38400, help="serial speed for --ptt cat")  # port speed
    args = parser.parse_args()  # read the options
    if args.text is not None:  # a message
        audio = build_frame(args.text, args.level, dest=args.to or "ALL", origin=args.call)  # fully addressed, so anyone can read who it is from
        what = f"message to {args.to or 'ALL'}"  # for the printout
    else:  # a beacon
        audio = build_beacon(args.call, args.grid, level=args.level, listening=False)  # a beacon that asks for no answers
        what = "beacon"  # for the printout
    rig = RigCtl(args.rig) if args.rig else None  # connect to rigctld when asked
    dial = args.freq if args.freq is not None else (dial_khz(args.band) if args.band else None)  # an exact frequency wins over a band preset
    if dial is not None and rig is None:  # tuning was asked for but there is no rig control
        parser.error("--band and --freq need --rig host:port")  # say so and stop
    if dial is not None:  # tune the radio
        rig.set_mode(args.mode)  # the mode first
        rig.set_frequency(dial * 1000.0)  # then the frequency, given in kHz
        low, high = signal_khz(rig.frequency() / 1000.0)  # where the signal will sit, from what the radio reports
        note = "inside a 97.221(b) segment" if in_automatic_segment(rig.frequency() / 1000.0) else "NOT in a 97.221(b) segment: attended operation only"  # may an unattended station be here?
        print(f"radio tuned to {rig.frequency() / 1000.0:.1f} kHz {args.mode}; signal {low:.1f} to {high:.1f} kHz ({note})", flush=True)  # confirm
    ptt = Ptt(args.ptt, args.port, args.baud, rig=rig)  # the transmit switch
    sink = AudioOut(find_device(args.sink, "output"), args.gain)  # the sound device
    print(f"Sending {what} from {args.call} at L{args.level}: {len(audio) / FS:.1f} s", flush=True)  # say what is about to happen
    ptt.key()  # transmitter on
    try:  # whatever happens...
        sink.play(audio)  # send the audio
    finally:  # ...the transmitter must come off
        ptt.unkey()  # transmitter off
        ptt.close()  # release the serial port
    print("Done.", flush=True)  # finished


if __name__ == "__main__":  # only when run as a script
    main()  # go
