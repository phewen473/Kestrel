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

## What is in it so far (interface version 1)

| C function | Python reference | Speed-up measured (sandbox) |
|---|---|---|
| `kes_blank_impulses` | `modem/blanker.py` `blank_impulses` | about 1.3× |
| `kes_viterbi_decode` | `modem/fec.py` `viterbi_decode` | about 30× |
| `kes_band_energies` | `modem/mfsk.py` `band_energies` | about 3× |

More follow, in the order the profile says they cost the most: the header search, preamble
detection and fine timing, medians and noise tracking, the LDPC decoder.

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

Interface version 1, three routines, all wired into the modem and tested against Python.
Next: move the header search (`_read_header_how` and the symbol reads it makes) into the
library, which the profile shows is the largest single cost.

Copyright 2026 P. H. Ewen (KO4WSC). Apache License 2.0 (pocketfft: BSD 3-clause, see its licence).
