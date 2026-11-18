"""Listen on a sound device and print every Kestrel frame heard. Receive only: nothing is transmitted.

Run from the repository root:

    python tools/live_monitor.py --in "USB Audio"

--in takes a device number or part of a device name (see tools/live_devices.py).
Leave it out to use the computer's default recording device. Stop with Ctrl+C.
"""

import argparse  # reads the command-line options
import os  # file paths
import sys  # lets us add the repository root to the import path
import time  # the clock, and short naps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live" and "modem" importable when run as a script

from live import Listener, describe  # the continuous receiver, and a one-line description of a frame  # noqa: E402
from live.audio import AudioIn, find_device  # sound-card input  # noqa: E402


def main():  # the script itself
    """Listen until stopped, printing each frame."""
    parser = argparse.ArgumentParser(description="Kestrel receive-only monitor")  # describe the tool
    parser.add_argument("--in", dest="source", default=None, help="input device: a number, or part of its name")  # which device to listen on
    parser.add_argument("--seconds", type=float, default=None, help="stop after this many seconds (default: run until Ctrl+C)")  # optional time limit
    args = parser.parse_args()  # read the options
    source = AudioIn(find_device(args.source, "input"))  # start recording
    listener = Listener()  # the continuous receiver
    started = time.monotonic()  # when listening began
    print("Listening for Kestrel frames. Ctrl+C to stop.", flush=True)  # opening line
    try:  # until stopped
        while args.seconds is None or time.monotonic() - started < args.seconds:  # until the time limit, if there is one
            for heard in listener.feed(source.read()):  # every frame that has completed
                print(f"{time.strftime('%H:%M:%S')}  {describe(heard.result)}", flush=True)  # print it with the time of day
            time.sleep(0.1)  # a tenth of a second between looks
    except KeyboardInterrupt:  # Ctrl+C
        pass  # stop quietly
    finally:  # always
        source.close()  # release the sound device


if __name__ == "__main__":  # only when run as a script
    main()  # go
