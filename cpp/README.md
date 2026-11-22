# cpp/ — libkestrel, the compiled part of the modem

This folder holds **libkestrel**, the parts of the Kestrel modem that need the most computing,
written in C++17 and offered through a plain C interface (`include/kestrel.h`).
The Python program loads it through `modem/native.py`; a later Qt program, a Raspberry Pi build
or anyone else's software can call the same functions.

The Python modem is still the **reference**. Each compiled routine does exactly what the Python
routine named beside it in `kestrel.h` does, and `tests/test_native.py` checks that they agree:
bit for bit for the blanker and the Viterbi decoder, and to the last rounding places
(about one part in 10^13) for anything that goes through sines, cosines or an FFT.
If the library is missing, or won't load, or offers a different interface version, the modem
quietly runs in pure Python, as it always has.

## What is in it so far (interface version 3)

| C function | Python reference | Agreement | Speed-up measured (sandbox) |
|---|---|---|---|
| `kes_blank_impulses` | `modem/blanker.py` `blank_impulses` | bit for bit | about 1.5x, more with threads |
| `kes_viterbi_decode` | `modem/fec.py` `viterbi_decode` | bit for bit | about 30x |
| `kes_band_energies` | `modem/mfsk.py` `band_energies` | to about 1 part in 10^13 | about 3x |
| `kes_detect_preamble` | `modem/preamble.py` `detect_preamble` (coarse search) | same candidates; quality to rounding | about 1.3x on one thread, more with threads |
| `kes_fine_time` | `modem/preamble.py` `fine_time` | start and frequency to rounding | about 8x |
| `kes_read_header` | `modem/frame.py` `_read_header_how` | bit for bit | removes almost all the Python work of the header search |
| `kes_set_threads`, `kes_threads` | - | - | - |

The heavy loops (blanker, pattern search) share their work among up to 8 threads; each piece is
worked out exactly as it would be on one thread, so the answers never depend on the thread count
(a test checks 1, 3 and 8). The continuous receiver also searches the five levels and the long
beacon side by side, since the library lets go of Python's lock while it works.

Whole receiver, a simulated 6-minute stream with 8 frames (the same 8 decoded every way):
pure Python 52.6 s; interface 1 (three routines) 39.7 s; interface 3 15-18 s (sandbox, 2 cores).

Still in Python, in the order they cost: the long beacon's carrier notch, the body decoder
(pilots, noise tracking, LDPC), and the listener's own bookkeeping. They move next.

## Files

- `include/kestrel.h` — the C interface: every function, with what it does.
- `src/kestrel.cpp` — the routines.
- `third_party/pocketfft/` — the FFT (the same algorithm NumPy uses), header-only, BSD licence;
  its licence (`LICENSE.md`) travels with the library.
- `CMakeLists.txt` — the build.

## Building

The easy way, from the top of the repository:

    python tools/build_native.py

That runs CMake, builds the library and copies it to `modem/_native/`
(`kestrel.dll` on Windows, `kestrel.so` on Linux), where the modem finds it.
It needs CMake and a C++17 compiler: g++ or clang on Linux and the Raspberry Pi,
MinGW-w64 or Visual Studio on Windows. With MinGW the C++ runtime is linked into the DLL,
so the DLL needs nothing else.

By hand:

    cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
    cmake --build cpp/build

The build uses exact IEEE arithmetic (`-fno-fast-math -ffp-contract=off`) so the results
match the Python reference.

## Switches

- `KESTREL_NATIVE=0` — ignore the library and run pure Python (for comparisons).
- `KESTREL_NATIVE_PATH=<file>` — load the library from that file instead.

## Where things were left

Interface version 3: the receiver's whole front end (blanker, pattern search, fine timing, header
reading) runs compiled and tested against Python. Next: the body decoder (pilot tracking, noise
tracking, soft bits, LDPC), then the listener loop itself, then the transmitter and the link rules,
so that Python is left only in the operator panel.

Copyright 2026 P. H. Ewen (KO4WSC). Apache License 2.0 (pocketfft: BSD 3-clause, see its licence).
