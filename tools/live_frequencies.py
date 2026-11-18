"""Show Kestrel's frequency list, and add or remove frequencies of your own.

Run from the repository root:

    python tools/live_frequencies.py                                           (show the list)
    python tools/live_frequencies.py --add "17 m" 18106.0 --note "evening net" (add your own)
    python tools/live_frequencies.py --add "40 m" 7110.0 --mode USB            (with a different radio mode)
    python tools/live_frequencies.py --remove 1                                (remove your entry number 1)

Your own entries are kept in local/frequencies.json, which Git ignores.
Frequencies are DIAL frequencies in kHz; the Kestrel signal sits 500 to 2500 Hz above.
"""

import argparse  # reads the command-line options
import os  # file paths
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "live" importable when run as a script

from live.bands import add_user_frequency, all_frequencies, describe_frequency, remove_user_frequency  # the frequency list  # noqa: E402


def main():  # the script itself
    """Change the list if asked, then print it."""
    parser = argparse.ArgumentParser(description="Kestrel frequency list")  # describe the tool
    parser.add_argument("--add", nargs=2, metavar=("BAND", "KHZ"), help="add a frequency of your own: a band name and a dial frequency in kHz")  # add an entry
    parser.add_argument("--mode", default="PKTUSB", help="radio mode for --add (default PKTUSB: upper sideband, data)")  # its mode
    parser.add_argument("--note", default="", help="a note for --add")  # its note
    parser.add_argument("--remove", type=int, default=None, metavar="N", help="remove your own entry number N (as numbered in the list)")  # remove an entry
    args = parser.parse_args()  # read the options
    if args.add:  # add an entry
        add_user_frequency(args.add[0], args.add[1], args.mode, args.note)  # save it
    if args.remove is not None:  # remove an entry
        remove_user_frequency(args.remove - 1)  # the list numbers the operator's own entries from 1
    own = 0  # how many of the operator's own entries have been printed
    for entry in all_frequencies():  # every frequency
        if entry["builtin"]:  # a preset
            print("       " + describe_frequency(entry))  # no number: presets cannot be removed
        else:  # one of the operator's own
            own += 1  # count it
            print(f"  {own:2d}.  " + describe_frequency(entry))  # numbered, so it can be removed


if __name__ == "__main__":  # only when run as a script
    main()  # go
