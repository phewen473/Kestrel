"""Build libkestrel (the compiled modem library) and put it where the modem looks for it.

Run from anywhere:  python tools/build_native.py
Needs CMake and a C++17 compiler (g++ or clang on Linux and the Raspberry
Pi; MinGW-w64 or Visual Studio on Windows). The result is copied to
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


def main():  # build and copy
    """Configure, build and install the library; return 0 on success."""
    if shutil.which("cmake") is None:  # no CMake on the path
        print("CMake was not found; install it, or run without the library (pure Python).")  # explain
        return 1  # failure
    configure = ["cmake", "-S", SOURCE, "-B", BUILD, "-DCMAKE_BUILD_TYPE=Release"]  # the configure step
    if sys.platform.startswith("win") and shutil.which("g++"):  # Windows with MinGW on the path
        configure += ["-G", "MinGW Makefiles"]  # use MinGW rather than looking for Visual Studio
    subprocess.run(configure, check=True)  # configure
    subprocess.run(["cmake", "--build", BUILD, "--config", "Release"], check=True)  # build
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
