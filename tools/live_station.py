"""Run a live Kestrel station on a sound device: beacon or listen, lock, pass messages, close.

Run from the repository root:

    python tools/live_station.py --call KO4WSC --grid EM92 --beacon --send "Hello from Kestrel"
    python tools/live_station.py --call W1AW --grid FN31 --listen

--beacon calls for a partner; --listen waits for a beacon and answers it.
--send (may be repeated) queues messages for the partner.
--in and --out name the sound devices (a number, or part of a name; see tools/live_devices.py).
--ptt none|rig|cat|rts|dtr keys the transmitter; --rig host:port with --freq (kHz) and --mode tunes the
radio through Hamlib's rigctld; --port and --baud are for the serial methods.
--stay-on keeps a listening station running for further contacts.

Only transmit where your licence allows, with the published specification matching this program.
"""

import time  # the clock, for --end-after
import argparse  # reads the command-line options
import os  # file paths
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live", "link" and "modem" importable when run as a script

from link import Station  # the link rules  # noqa: E402
from live import run_station  # the live loop  # noqa: E402
from live.audio import AudioIn, AudioOut, find_device  # sound-card input and output  # noqa: E402
from live.ptt import Ptt  # transmitter keying  # noqa: E402
from live.bands import dial_khz, in_automatic_segment, signal_khz  # the preselected frequencies  # noqa: E402
from live.rig import RigCtl  # rig control through Hamlib's rigctld  # noqa: E402


def main():  # the script itself
    """Set up the station and run it."""
    parser = argparse.ArgumentParser(description="Kestrel live station")  # describe the tool
    parser.add_argument("--call", required=True, help="your callsign")  # who you are
    parser.add_argument("--grid", required=True, help="your four-character grid locator")  # where you are
    role = parser.add_mutually_exclusive_group(required=True)  # exactly one of the two roles
    role.add_argument("--beacon", action="store_true", help="call for a partner")  # the calling station
    role.add_argument("--listen", action="store_true", help="wait for a beacon and answer it")  # the answering station
    role.add_argument("--call-station", default=None, metavar="CALLSIGN", help="call one station by name instead of beaconing")  # a directed call
    parser.add_argument("--send", action="append", default=[], help="a message for the partner (may be repeated)")  # traffic
    parser.add_argument("--to", default=None, metavar="CALLSIGN", help="send the --send messages only to this callsign")  # targeted traffic
    parser.add_argument("--broadcast", action="append", default=[], help="a message to send to ALL stations, unacknowledged, before anything else (may be repeated)")  # a broadcast
    parser.add_argument("--in", dest="source", default=None, help="input device: a number, or part of its name")  # where to listen
    parser.add_argument("--out", dest="sink", default=None, help="output device: a number, or part of its name")  # where to play
    parser.add_argument("--gain", type=float, default=0.5, help="transmit audio level, 0 to 1")  # how loud
    parser.add_argument("--ptt", default="none", choices=["none", "rig", "cat", "rts", "dtr"], help="how to key the transmitter (rig = through rigctld)")  # keying method
    parser.add_argument("--rig", default=None, help="address of Hamlib's rigctld, host:port (for example 127.0.0.1:4532)")  # rig control
    parser.add_argument("--band", default=None, help="tune to Kestrel's preselected frequency for this band: 40, 30 or 20 (needs --rig)")  # a preset
    parser.add_argument("--freq", type=float, default=None, help="dial frequency to tune the radio to, in kHz (needs --rig); overrides --band")  # where to tune
    parser.add_argument("--mode", default="PKTUSB", help="radio mode to select when --freq is given (default PKTUSB: upper sideband, data)")  # which mode
    parser.add_argument("--port", default=None, help="serial port for --ptt cat, rts or dtr")  # which port
    parser.add_argument("--baud", type=int, default=38400, help="serial speed for --ptt cat")  # port speed
    parser.add_argument("--stay-on", action="store_true", help="after a contact, go back to listening")  # keep running
    parser.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")  # optional time limit
    parser.add_argument("--keep-open", action="store_true", help="hold the lock after the traffic is done (stop with Ctrl+C or --end-after)")  # a conversation that goes on
    parser.add_argument("--end-after", type=float, default=None, help="with --keep-open: close the contact properly this many seconds after starting")  # when to say goodbye
    parser.add_argument("--move", type=float, default=None, help="once locked, propose moving this many kHz from the calling frequency to a working frequency (needs --rig)")  # leave the calling frequency
    args = parser.parse_args()  # read the options
    station = Station(args.call, args.grid, close_when_done=not args.keep_open)  # the link rules for this station, holding the lock open if asked
    if args.beacon:  # the calling station
        station.beacon()  # it beacons
    elif args.call_station:  # calling one station by name
        station.call_station(args.call_station)  # only that station answers
    else:  # the answering station
        station.listen()  # it listens
    for text in args.broadcast:  # the operator's broadcasts
        station.broadcast(text)  # queued for everyone; they go out first, while no contact is in progress
    for text in args.send:  # the operator's messages
        station.queue(text, to=args.to)  # into the outbox, addressed if --to was given
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
    source = AudioIn(find_device(args.source, "input"))  # start recording
    sink = AudioOut(find_device(args.sink, "output"), args.gain)  # the playing side
    base_hz = rig.frequency() if rig is not None else 0.0  # the calling frequency, as the radio reports it
    retune = (lambda offset: rig.set_frequency(base_hz + offset)) if rig is not None else None  # how to move to a working frequency and back
    station.move_to_hz = int(round(args.move * 1000.0)) if args.move and rig is not None else None  # the working frequency to propose, as an offset in hertz
    began = time.monotonic()  # when the station started
    def should_stop():  # looked at ten times a second by the live loop
        if args.end_after is not None and time.monotonic() - began >= args.end_after:  # time to say goodbye
            station.end()  # close the contact once the current exchange is done
        return False  # never stop the loop itself; it ends when the contact does
    try:  # until the contact ends or Ctrl+C
        run_station(station, source, sink, ptt, say=lambda line: print(line, flush=True), limit_s=args.seconds, stay_on=args.stay_on, should_stop=should_stop, retune=retune)  # the live loop
    except KeyboardInterrupt:  # Ctrl+C
        print("stopped by operator", flush=True)  # say so
    finally:  # always
        ptt.close()  # make sure the transmitter is off
        source.close()  # release the sound device
    print(f"delivered {len(station.delivered)} message(s); {len(station.outbox)} still waiting", flush=True)  # the outcome for sent traffic
    for text in station.inbox:  # everything received
        print(f"received: {text}", flush=True)  # show it


if __name__ == "__main__":  # only when run as a script
    main()  # go
