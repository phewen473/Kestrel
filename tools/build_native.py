"""Build libkestrel (the compiled modem library) and put it where the modem looks for it.

Run from anywhere:  python tools/build_native.py
Needs CMake and a C++17 compiler with full <charconv> (g++ 11 or newer on
Linux and the Raspberry Pi; MinGW-w64 g++ 11 or newer, such as MSYS2's, on
Windows). On Windows the newest suitable MinGW g++ is looked for in MSYS2's
usual folders and then on the PATH, so an older g++ that happens to come
first on the PATH (Strawberry Perl ships g++ 8) is passed over. The result is copied to
modem/_native/, which the modem loads at start-up (see modem/native.py).
Without the library the modem still works, in pure Python.
"""

import os  # file paths
import shutil  # copying files and finding programs
import subprocess  # running CMake
import sys  # the platform and the exit code

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the top of the repository
SOURCE = os.path.join(ROOT, "cpp")  # the library's source
BUILD = os.path.join(SOURCE, "build")  # where CMake builds it (git-ignored)
TARGET = os.path.join(ROOT, "modem", "_native")  # where the modem looks for it


NEWEST_NEEDED = 11  # the oldest g++ whose library has floating-point to_chars and from_chars (exact, language-independent number text)


def gcc_major(gxx):  # the major version of a g++
    """Return the major version number of the g++ at `gxx`, or 0 if it cannot be run."""
    try:  # it may not run
        text = subprocess.run([gxx, "-dumpversion"], capture_output=True, text=True, timeout=30).stdout.strip()  # such as "16.2.0" or "8"
        return int(text.split(".")[0])  # the major number
    except (OSError, ValueError, subprocess.SubprocessError):  # not a working g++
        return 0  # unusable


def windows_compiler():  # the MinGW g++ to use on Windows
    """Return (g++ path, its folder) of a MinGW g++ new enough to build the library, or (None, None)."""
    drive = os.environ.get("SystemDrive", "C:") + os.sep  # the system drive
    folders = [os.path.join(drive, "msys64", sub, "bin") for sub in ("mingw64", "ucrt64", "clang64")]  # MSYS2's usual places first
    folders += os.environ.get("PATH", "").split(os.pathsep)  # then the PATH, in order
    for folder in folders:  # each place
        gxx = os.path.join(folder, "g++.exe")  # a g++ there?
        if folder and os.path.isfile(gxx) and gcc_major(gxx) >= NEWEST_NEEDED:  # present and new enough
            return gxx, folder  # use it
    return None, None  # none suitable


def main():  # build and copy
    """Configure, build and install the library; return 0 on success."""
    if shutil.which("cmake") is None:  # no CMake on the path
        print("CMake was not found; install it, or run without the library (pure Python).")  # explain
        return 1  # failure
    configure = ["cmake", "-S", SOURCE, "-B", BUILD, "-DCMAKE_BUILD_TYPE=Release"]  # the configure step
    env = dict(os.environ)  # the environment the build runs in
    if sys.platform.startswith("win"):  # Windows
        gxx, folder = windows_compiler()  # a MinGW g++ new enough
        if gxx is None and shutil.which("g++"):  # only an older one
            print(f"The g++ found ({shutil.which('g++')}, version {gcc_major(shutil.which('g++'))}) is too old; the library needs g++ {NEWEST_NEEDED} or newer (MSYS2's mingw-w64-x86_64-gcc).")  # explain
            return 1  # failure
        if gxx is not None:  # MinGW
            print(f"Using {gxx} (g++ {gcc_major(gxx)})")  # say which
            env["PATH"] = folder + os.pathsep + env.get("PATH", "")  # its make and tools first
            configure += ["-G", "MinGW Makefiles", f"-DCMAKE_CXX_COMPILER={gxx}"]  # MinGW, with this compiler
            cache = os.path.join(BUILD, "CMakeCache.txt")  # an earlier configuration
            if os.path.isfile(cache):  # there is one
                with open(cache, encoding="utf-8", errors="replace") as handle:  # read it
                    if f"CMAKE_CXX_COMPILER:FILEPATH={gxx.replace(os.sep, '/')}" not in handle.read().replace(os.sep, "/"):  # made with another compiler
                        shutil.rmtree(BUILD, ignore_errors=True)  # start afresh (CMake cannot change compiler in place)
    subprocess.run(configure, check=True, env=env)  # configure
    subprocess.run(["cmake", "--build", BUILD, "--config", "Release"], check=True, env=env)  # build
    names = ("kestrel.dll", "kestrel.so", "kestrel.dylib")  # what the result may be called
    found = None  # not found yet
    for folder, _dirs, files in os.walk(BUILD):  # look through the build folder
        for name in files:  # each file
            if name in names:  # the library
                found = os.path.join(folder, name)  # remember it
    if found is None:  # the build made nothing recognisable
        print("The build finished but no library file was found.")  # explain
        return 1  # failure
    os.makedirs(TARGET, exist_ok=True)  # make sure the target folder exists
    shutil.copy2(found, os.path.join(TARGET, os.path.basename(found)))  # put it in place
    print(f"Installed {os.path.basename(found)} in modem/_native/")  # report
    return 0  # success


if __name__ == "__main__":  # run as a program
    sys.exit(main())  # build, and pass on the result
