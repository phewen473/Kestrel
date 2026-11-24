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

## What is in it so far (interface version 11)

Interface 11 (0.31R2): the listener hands back every signature whose frame passed without a header (a possible near miss); Python counts its pattern tones, decides whether to report it, and cuts it out if it does.

| C function | Python reference | Agreement | Speed-up measured (sandbox) |
|---|---|---|---|
| `kes_blank_impulses` | `modem/blanker.py` `blank_impulses` | bit for bit | about 1.5x, more with threads |
| `kes_viterbi_decode` | `modem/fec.py` `viterbi_decode` | bit for bit | about 30x |
| `kes_band_energies` | `modem/mfsk.py` `band_energies` | to about 1 part in 10^13 | about 3x |
| `kes_detect_preamble` | `modem/preamble.py` `detect_preamble` (coarse search) | same candidates; quality to rounding | about 1.3x on one thread, more with threads |
| `kes_fine_time` | `modem/preamble.py` `fine_time` | start and frequency to rounding | about 8x |
| `kes_read_header` | `modem/frame.py` `_read_header_how` | bit for bit | removes almost all the Python work of the header search |
| `kes_ldpc_decode` | `modem/ldpc.py` `decode` | bit for bit (bits and verdict) | about 2.5x |
| `kes_noise_profile` | `modem/mfsk.py` `noise_profile` | bit for bit | - |
| `kes_tone_spread` (ABI 14, since 0.35) | `modem/mfsk.py` `tone_spread` (the sums behind the Doppler-spread reading) | to rounding | - |
| `kes_listener_candidates` (ABI 15, since 0.37) | `live/listener.py` `Listener.progress` (the candidates the Python listener follows, for the frame strip) | exact | - |
| `kes_read_header` spare bit (ABI 16, since 0.38) | `modem/frame.py` `_check_header`: a beacon's header may set the spare bit (power steps came first); any other frame's may not | exact | - |
| `kes_pack_control` / `kes_unpack_control` beacon rig type and watts (ABI 17, since 0.40) | `modem/control.py` `pack_beacon`, `unpack`: the beacon's 101 bits, ending with the Hamlib model number (16) and watts (10) | exact | - |
| `kes_pilot_fit` | `modem/mfsk.py` `pilot_frequency_fit` | to rounding (about 1e-13 Hz) | - |
| `kes_viterbi_decode_known` | `modem/fec.py` `viterbi_decode(llrs, known)` | bit for bit | (expected-callsign decoding, 0.31R1) |
| `kes_remove_steady` | `modem/notch.py` `remove_steady` | to rounding | (steady-signal notch, 0.31R1) |
| `kes_decode_body` | `modem/frame.py` `_decode_body_python` (pilots to checked body: pilot fit, band, noise, first SNR and fading, noise profile, soft bits, de-interleaving, Viterbi or LDPC with retries added, CRC-16) | outcome, text and soft bits identical; measurements to about 1e-13 | (one call per frame instead of a dozen) |
| `kes_remove_steady` with `windowed=0, local_steps=-1` | `modem/longbeacon.py` `clean` | identical | (the long beacon's carrier notch) |
| `kes_listener_*` (a listener object) | `live/listener.py` incremental search: the audio store with its stream numbers, blanking and notching each search, the pattern search of all levels side by side, the candidate list, fine timing, header reading, near misses | the same frames, near misses and tries, search by search | (Python keeps only the decoding of frames it is handed) |
| `kes_encode_frame` | `modem/frame.py` `build_frame`, `build_control` (after the bits are packed): header and body coding, interleaving, pilots, tones, audio | identical audio | (the transmitter) |
| `kes_crc16`, `kes_crc8`, `kes_call_to_bits`, `kes_bits_to_call`, `kes_call_hash`, `kes_message_hash`, `kes_link_id`, `kes_choose_packing`, `kes_text_to_bits`, `kes_bits_to_text`, `kes_header_bits`, `kes_address_block`, `kes_read_address_block`, `kes_pack_control`, `kes_unpack_control` (in `src/packing.cpp`) | `modem/crc.py`, `address.py`, `compress.py`, `text.py`, `control.py`, and `frame.py` `_header_bits`, `_address_block`, `_read_address_block` | the same bits, text and fields, and a refusal wherever Python raises an error | CRC-16 of a message body: 145 us -> 8 us |
| `kes_mail_new`, `kes_mail_request`, `kes_mail_reply`, `kes_mail_free` (in `src/mail.cpp`) | `link/mail.py` `Mailroom`: store and forward, every method, by a JSON request naming the method | the same answers, news and stored mail, call for call; the same mail file | (the first of the link rules) |
| `kes_station_new`, `kes_station_request`, `kes_station_reply`, `kes_station_set_mail`, `kes_station_set_busy`, `kes_station_free` (in `src/station.cpp`) | `link/station.py` `Station` with `link/adapt.py` and the planning rules of `modem/plan.py`: every link rule, by a JSON request naming the method | the same transmissions at the same moments, the same log lines word for word, the same results and stored mail, contact for contact (nine simulated contacts compared) | the reply slot is chosen with NumPy's own random generator, rebuilt in `src/rng.hpp` |
| `kes_set_threads`, `kes_threads` | - | - | - |

The heavy loops (blanker, pattern search) share their work among up to 8 threads; each piece is
worked out exactly as it would be on one thread, so the answers never depend on the thread count
(a test checks 1, 3 and 8). The continuous receiver also searches the five levels and the long
beacon side by side, since the library lets go of Python's lock while it works.

Whole receiver, a simulated 6-minute stream with 8 frames (the same 8 decoded every way):
pure Python 52.6 s; interface 1 (three routines) 39.7 s; interface 3 15-18 s (sandbox, 2 cores).

The whole modem now has a compiled version: every heavy computation of the receiver and the
transmitter, the continuous receiver's store and candidate list, and the packing and unpacking of
every bit a frame carries. The link layer is in C++ too: the station's link rules and the mail
store. Still in Python: the glue that calls the modem routines in order (frame.py: receive() and
the build_* functions), the long beacon's soft-energy combining, the help for weak control frames
(it calls the compiled Viterbi decoder), the live runner (sound card, radio), and the panel.

The packing functions refuse (return -1) wherever the Python reference raises an error, and for
any text outside 7-bit ASCII. The Python bridge then runs the Python code, which raises its own
worded error, so the program behaves the same either way.

## Files

- `include/kestrel.h` — the C interface: every function, with what it does.
- `src/kestrel.cpp` — the signal routines: blanker, notch, searches, decoders, the listener, the transmitter's audio.
- `src/packing.cpp` — packing and unpacking the bits: text (plain and compressed), addresses,
  grid locators, channel reports, the header, the address block, control-frame fields, check values.
- `src/mail.cpp` — the mail store (store and forward), `link/mail.py`'s Mailroom in C++.
- `src/station.cpp` — one station's link rules, `link/station.py`'s Station in C++ (with the
  speed-adaptation and message-planning rules).
- `src/rng.hpp` — NumPy's default random generator (SeedSequence and PCG64), so the C++ station
  picks the same reply slot as the Python one.
- `src/internal.hpp` — calls between the parts of the library.
- `src/json.hpp` — a small JSON reader and writer (the mail file, and the mail store's requests).
- `third_party/pocketfft/` — the FFT (the same algorithm NumPy uses), header-only, BSD license;
  its license (`LICENSE.md`) travels with the library.
- `CMakeLists.txt` — the build.

## Building

The easy way, from the top of the repository:

    python tools/build_native.py

That runs CMake, builds the library and copies it to `modem/_native/`
(`kestrel.dll` on Windows, `kestrel.so` on Linux), where the modem finds it.
It needs CMake and a C++17 compiler with full `<charconv>`: g++ 11 or newer on Linux and the
Raspberry Pi, MinGW-w64 g++ 11 or newer (MSYS2) on Windows. On Windows the script looks for
MSYS2's g++ first and passes over an older g++ earlier on the PATH (Strawberry Perl's g++ 8 cannot
build the library: it has no floating-point `to_chars`). With MinGW the C++ runtime is linked into the DLL,
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

Interface version 10: the receiver (front end, body decoder, the continuous receiver's store and
candidates), the transmitter's coding and audio, the packing and unpacking of every field, the mail
store and the station's link rules run compiled, tested against Python. The request and reply of
`kes_mail_*` and `kes_station_*` are two calls: a caller using one handle from several threads must
not let them interleave (the Python bridge holds a lock per handle; the station reaches its mail
store in one locked step). Next: the frame glue (receive and build) as single compiled calls, then
a C++ program around the library (the panel, after asking the operator about Qt).

Copyright 2026 P. H. Ewen (KO4WSC). Apache License 2.0 (pocketfft: BSD 3-clause, see its license).
