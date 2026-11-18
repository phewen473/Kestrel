"""List this computer's sound devices, so the right ones can be named to the other live tools.

Run from the repository root:

    python tools/live_devices.py
"""

import os  # file paths
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live" importable when run as a script

from live.audio import list_devices  # the device lister  # noqa: E402


def main():  # the script itself
    """Print every sound device with its number and what it can do."""
    print("  #  in out  name")  # column headings
    for index, name, inputs, outputs in list_devices():  # one line per device
        print(f"{index:3d}  {'yes' if inputs else ' - '} {'yes' if outputs else ' - '}  {name}")  # number, can record?, can play?, name


if __name__ == "__main__":  # only when run as a script
    main()  # go
