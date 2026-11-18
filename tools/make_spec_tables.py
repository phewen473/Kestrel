"""Write the reference tables that the specification points to.

Run from the repository root:
    python tools/make_spec_tables.py
It writes, under docs/spec/tables/:
  * ldpc_checks_k<N>.txt - for each body size, the three parity checks every data bit takes part in;
  * compression_codes.txt - the code length and code of each of the 128 ASCII characters.
Another implementation can either rebuild these from the rules in the
specification or simply read the files; both must give the same result.
"""

import os  # file paths and folders
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem" importable when run as a script

from modem import body_layout, ldpc  # frame facts and the LDPC code  # noqa: E402
from modem.compress import LENGTHS, _CODES  # the compression tables  # noqa: E402
from modem.params import SIZE_CLASSES  # the size classes  # noqa: E402


def main():  # the script itself
    """Write every table."""
    out_dir = os.path.join(ROOT, "docs", "spec", "tables")  # where the tables go
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    for size_class in range(len(SIZE_CLASSES)):  # one LDPC table per size class
        k = body_layout(size_class)["info"]  # number of data bits in that class's body
        rows = ldpc.info_checks(k)  # the three checks of every data bit
        path = os.path.join(out_dir, f"ldpc_checks_k{k}.txt")  # the file for this size
        with open(path, "w", newline="\n") as handle:  # open it for writing, with plain line endings
            handle.write(f"# Kestrel LDPC code, k = {k} data bits, {k} parity bits ({SIZE_CLASSES[size_class]}-character size class)\n")  # what this file is
            handle.write("# Each line: data bit number, then the three parity checks it takes part in (all counted from 0).\n")  # how to read it
            handle.write("# Parity bit i takes part in check i and check i+1 (the last parity bit only in the last check).\n")  # the rest of the code's structure
            for j in range(k):  # one line per data bit
                handle.write(f"{j} {rows[0][j]} {rows[1][j]} {rows[2][j]}\n")  # the bit and its three checks
        print("wrote", path)  # say what was written
    path = os.path.join(out_dir, "compression_codes.txt")  # the compression table file
    with open(path, "w", newline="\n") as handle:  # open it for writing, with plain line endings
        handle.write("# Kestrel text compression: character number, code length in bits, code (most significant bit first)\n")  # what this file is
        for symbol in range(128):  # one line per ASCII character
            handle.write(f"{symbol} {LENGTHS[symbol]} {_CODES[symbol]:0{LENGTHS[symbol]}b}\n")  # number, length, code as binary digits
    print("wrote", path)  # say what was written


if __name__ == "__main__":  # only when run as a script
    main()  # go
