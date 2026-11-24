"""Build the ITU-R P.533 propagation engine (ITURHFProp) and put it where Kestrel looks for it.

Run from anywhere:  python tools/build_prop.py [--source FOLDER]

The engine is the ITU's own implementation of Recommendation ITU-R P.533-14
(HF circuit prediction) and P.372 (radio noise), from ITU-R Study Group 3:
https://github.com/ITU-R-Study-Group-3/ITU-R-HF . Its README says it may be
used free from any copyright assertions, as is, with no warranties. It is
not kept in Kestrel's repository (its data files alone are about 140 MB):
this script fetches the pinned version (PINNED_COMMIT) with Git, checks the
commit, compiles the three parts with gcc and copies them, with the data
files the predictions need, to live/_prop/ (git-ignored):

  live/_prop/bin/   ITURHFProp(.exe), P533.dll and P372.dll (Windows) or
                    libp533.so and libp372.so (Linux)
  live/_prop/data/  ionos01-12.bin, COEFF01W-12W.txt, P1239-3 Decile Factors.txt
  live/_prop/SOURCE.txt  where it came from and on what terms

Needs Git and gcc (on Windows MSYS2's MinGW gcc, as for the modem library).
The old C code needs -fcommon with gcc 10 and newer (shared variables are
defined in a header). Without the engine Kestrel works as before; only the
propagation window says it is missing.
"""

import argparse  # reads the command-line options
import glob  # lists files by pattern
import os  # file paths
import shutil  # copying files and finding programs
import subprocess  # running Git and gcc
import sys  # the platform and the exit code

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the top of the repository
TARGET = os.path.join(ROOT, "live", "_prop")  # where Kestrel looks for the engine (live/propagation.py)
REPO = "https://github.com/ITU-R-Study-Group-3/ITU-R-HF.git"  # the ITU's repository
PINNED_TAG = "v14.3"  # the release used
PINNED_COMMIT = "cd172be56dc04b154e5d2fa91cbaa6ecf5284305"  # its commit: checked, so a changed tag is noticed
CACHE = os.path.join(ROOT, "packaging", "cache", "ITU-R-HF")  # where the source is kept between builds (git-ignored)
P372_SOURCES = ("InitializeNoise.c", "MakeNoise.c", "Noise.c", "NoiseMemory.c")  # the noise library's files (the others are a test driver and an out-of-date copy)
PROP_SOURCES = ("ITURHFProp.c", "ReadInputConfiguration.c", "Report.c", "DumpPathData.c", "ValidateITURHFP.c")  # the command-line program's files
FLAGS = ["-std=gnu99", "-O2", "-fcommon"]  # C99 with the usual extensions, optimized; -fcommon for the shared variables in the headers


def windows_gcc():  # the MinGW gcc to use on Windows
    """Return the folder of MSYS2's MinGW gcc, or of a gcc on the PATH, or None."""
    drive = os.environ.get("SystemDrive", "C:") + os.sep  # the system drive
    for folder in [os.path.join(drive, "msys64", sub, "bin") for sub in ("mingw64", "ucrt64")] + os.environ.get("PATH", "").split(os.pathsep):  # MSYS2 first, then the PATH
        if folder and os.path.isfile(os.path.join(folder, "gcc.exe")):  # a gcc there
            return folder  # use it
    return None  # none found


def fetch(source):  # make sure the pinned source is present
    """Return the folder holding the ITU source at PINNED_COMMIT: `source` if given, else a Git copy kept in packaging/cache."""
    folder = source or CACHE  # the folder to use
    if not os.path.isdir(os.path.join(folder, ".git")):  # not fetched yet
        print(f"Fetching {REPO} {PINNED_TAG}")  # say so
        subprocess.run(["git", "clone", "--depth", "1", "--branch", PINNED_TAG, "-c", "core.longpaths=true", REPO, folder], check=False)  # fetch it (a case-only file name clash on Windows is reported, and does not matter: that file is not used)
    head = subprocess.run(["git", "-C", folder, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()  # the commit present
    if head != PINNED_COMMIT:  # not the version Kestrel was tested with
        raise SystemExit(f"The ITU source in {folder} is at {head or 'nothing'}, not {PINNED_COMMIT}; refusing to build.")  # stop
    subprocess.run(["git", "-C", folder, "-c", "core.longpaths=true", "checkout", "-f", "HEAD", "--", "P533", "P372", "ITURHFProp"], check=False)  # make sure every file used is really there (Windows can leave some out after the clash)
    return folder  # the source


def compile_all(src, bin_dir, env):  # the three parts
    """Compile P372, P533 and ITURHFProp from `src` into `bin_dir`."""
    windows = sys.platform.startswith("win")  # which platform
    p372 = os.path.join(src, "P372", "Src", "P372")  # the noise library's source
    p533 = os.path.join(src, "P533", "Src", "P533")  # the propagation library's source
    prop = os.path.join(src, "ITURHFProp", "Src", "ITURHFProp")  # the command-line program's source
    lib372 = os.path.join(bin_dir, "P372.dll" if windows else "libp372.so")  # the noise library, by the name P533 loads it by
    lib533 = os.path.join(bin_dir, "P533.dll" if windows else "libp533.so")  # the propagation library, by the name ITURHFProp loads it by
    exe = os.path.join(bin_dir, "ITURHFProp.exe" if windows else "ITURHFProp")  # the program
    shared = ["-shared"] + ([] if windows else ["-fPIC"])  # how to make a library here
    libs = ["-lm"] + ([] if windows else ["-ldl"])  # the maths library, and on Linux the loader's
    steps = [  # the three compiler runs
        ["gcc", *FLAGS, *shared, "-o", lib372, *[os.path.join(p372, n) for n in P372_SOURCES], "-I", p372, *libs],  # the noise library
        ["gcc", *FLAGS, *shared, "-o", lib533, *sorted(glob.glob(os.path.join(p533, "*.c"))), "-I", p533, *libs],  # the propagation library (every file in its folder)
        ["gcc", *FLAGS, "-o", exe, *[os.path.join(prop, n) for n in PROP_SOURCES], "-I", prop, *libs],  # the program, which loads the propagation library by name
    ]  # end of the list
    for step in steps:  # one at a time
        step[0] = env.get("KES_GCC", "gcc")  # the compiler by its full path (Windows looks a program up on the caller's PATH, not the one given to it)
        print("Compiling", os.path.basename(step[step.index("-o") + 1]))  # say which
        result = subprocess.run(step, env=env, capture_output=True, text=True)  # compile it (the old code gives many warnings; only failures are shown)
        if result.returncode != 0:  # it failed
            print(result.stdout + result.stderr)  # show why
            raise SystemExit("compiling the ITU engine failed")  # stop


SHIP_MONTHS = 3  # an installer carries this many months' ionosphere maps, from the month it is built (live/propagation.py SHIP_MONTHS; a test checks they agree): the rest are fetched when first needed (since 0.38)


def ship_months(target, months=None, today=None):  # which months' maps to copy
    """Return the month numbers (1-12) whose ionosphere maps go to `target`: all twelve for the source folder's live/_prop, otherwise `months` (default SHIP_MONTHS) from this month on, wrapping past December."""
    import time  # the date
    if months is None:  # not said
        months = 12 if os.path.abspath(target) == os.path.abspath(TARGET) else SHIP_MONTHS  # the source folder keeps all; an installer, a few
    start = (today or time.localtime()).tm_mon  # this month
    return sorted({(start - 1 + k) % 12 + 1 for k in range(max(1, min(12, months)))})  # this month and the next ones


def main():  # fetch, build and copy
    """Fetch the pinned ITU source, build the engine and copy it and its data to live/_prop/; return 0 on success."""
    parser = argparse.ArgumentParser(description="Build the ITU-R P.533 propagation engine for Kestrel")  # describe the tool
    parser.add_argument("--source", default="", help="a Git copy of the ITU-R-HF repository already at the pinned commit")  # optional
    parser.add_argument("--target", default=TARGET, help="where to put the engine (default live/_prop)")  # optional
    parser.add_argument("--months", type=int, default=None, help=f"how many months' ionosphere maps to copy, from this month on (default: all 12 for live/_prop, {SHIP_MONTHS} for any other target, such as an installer)")  # optional (since 0.38)
    args = parser.parse_args()  # read the options
    env = dict(os.environ)  # the environment the compiler runs in
    if sys.platform.startswith("win"):  # Windows
        folder = windows_gcc()  # MSYS2's MinGW gcc
        if folder is None:  # none
            print("gcc was not found (install MSYS2's mingw-w64-x86_64-gcc).")  # explain
            return 1  # failure
        env["PATH"] = folder + os.pathsep + env.get("PATH", "")  # its tools first (the compiler finds its own helpers there)
        env["KES_GCC"] = os.path.join(folder, "gcc.exe")  # and the compiler itself, by its full path
    elif shutil.which("gcc") is None:  # no compiler
        print("gcc was not found.")  # explain
        return 1  # failure
    src = fetch(args.source)  # the source, checked
    bin_dir, data_dir = os.path.join(args.target, "bin"), os.path.join(args.target, "data")  # the two folders made
    shutil.rmtree(args.target, ignore_errors=True)  # start afresh
    os.makedirs(bin_dir)  # the program folder
    os.makedirs(data_dir)  # the data folder
    compile_all(src, bin_dir, env)  # build
    data = os.path.join(src, "P533", "Data")  # the ITU's data files
    wanted = [f"ionos{m:02d}.bin" for m in ship_months(args.target, args.months)] + [f"COEFF{m:02d}W.txt" for m in range(1, 13)] + ["P1239-3 Decile Factors.txt"]  # what the predictions read (the installer: only a few months' maps, since 0.38)
    for name in wanted:  # each one
        shutil.copy2(os.path.join(data, name), os.path.join(data_dir, name))  # copy it
    with open(os.path.join(args.target, "SOURCE.txt"), "w", encoding="utf-8") as handle:  # where it came from
        handle.write(  # the notice
            "ITURHFProp, P533 and P372: the ITU-R implementation of Recommendations ITU-R P.533-14\n"
            "(prediction of the performance of HF circuits) and ITU-R P.372 (radio noise), from\n"
            "ITU-R Study Group 3, with its data files, unchanged.\n\n"
            f"Source: {REPO.removesuffix('.git')}  (release {PINNED_TAG}, commit {PINNED_COMMIT})\n\n"
            "Terms, from the repository's README: the software may be used free from any copyright\n"
            "assertions, and is provided \"as is\" with no warranties, express or implied.\n"
            "Copyright (c) 2022 ITU-R Study Group 3.\n\n"
            "Built for Kestrel with gcc (-std=gnu99 -O2 -fcommon); Kestrel runs ITURHFProp with an input\n"
            "file it writes and reads its CSV table (live/propagation.py).\n")  # end of the notice
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fs in os.walk(args.target) for f in fs)  # how big it is
    print(f"Installed the ITU-R P.533 engine in {args.target} ({total / 1e6:.0f} MB)")  # report
    return 0  # success


if __name__ == "__main__":  # run as a program
    sys.exit(main())  # build, and pass on the result
