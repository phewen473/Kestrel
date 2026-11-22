"""The bridge to libkestrel, the compiled (C++) part of the modem.

The library does the heaviest sums faster than Python can. Each function
here hands its work to the library when the library is present and
working, and returns None when it is not, so the caller falls back to its
own Python code, which stays the reference that the library is tested
against.

Where the library is looked for, in order:
  1. the file named by the environment variable KESTREL_NATIVE_PATH;
  2. modem/_native/ beside this file (where tools/build_native.py puts it,
     and where the Windows installer places it).
Set KESTREL_NATIVE=0 to ignore the library and run pure Python.
"""

import ctypes  # calling C functions from Python
import os  # environment variables and file paths
import sys  # which platform this is

import numpy as np  # numerical arrays

ABI_VERSION = 3  # the library interface this file was written for (KES_ABI_VERSION in cpp/include/kestrel.h)

_DOUBLE_P = ctypes.POINTER(ctypes.c_double)  # a pointer to doubles
_BYTE_P = ctypes.POINTER(ctypes.c_uint8)  # a pointer to bytes
_INT_P = ctypes.POINTER(ctypes.c_int)  # a pointer to ints
_LONG_P = ctypes.POINTER(ctypes.c_long)  # a pointer to longs


def _file_name():  # what the library file is called on this platform
    """Return the library's file name on this platform."""
    if sys.platform.startswith("win"):  # Windows
        return "kestrel.dll"  # a DLL
    if sys.platform == "darwin":  # macOS
        return "kestrel.dylib"  # a dynamic library
    return "kestrel.so"  # Linux, the Raspberry Pi and other Unix systems


def _places():  # where to look for the library, best first
    """Return the paths at which the library may be found."""
    places = []  # none yet
    named = os.environ.get("KESTREL_NATIVE_PATH")  # a path given by the user, if any
    if named:  # one was given
        places.append(named)  # look there first
    here = os.path.dirname(os.path.abspath(__file__))  # this file's folder (inside a frozen program, the unpacked modem folder)
    places.append(os.path.join(here, "_native", _file_name()))  # the usual place
    return places  # the list


def _load():  # find, open and check the library
    """Return the opened library, or None (with the reason in `why`)."""
    global why  # the reason the library is not in use, for the About box and the tests
    if os.environ.get("KESTREL_NATIVE", "1") == "0":  # the user switched it off
        why = "switched off by KESTREL_NATIVE=0"  # say so
        return None  # pure Python
    for place in _places():  # each candidate
        if not os.path.isfile(place):  # nothing there
            continue  # try the next
        try:  # opening can fail (wrong platform, missing runtime)
            lib = ctypes.CDLL(place)  # open it
        except OSError as err:  # it would not open
            why = f"could not open {os.path.basename(place)}: {err}"  # remember why
            continue  # try the next
        try:  # an old library may lack the version function
            version = lib.kes_abi_version()  # the interface it offers
        except AttributeError:  # no version function at all
            why = "the library is too old"  # say so
            continue  # try the next
        if version != ABI_VERSION:  # a different interface from the one this file expects
            why = f"the library offers interface {version}, not {ABI_VERSION}"  # say so
            continue  # try the next
        lib.kes_set_threads.argtypes = [ctypes.c_int]  # the thread count (0 = the computer's own)
        lib.kes_set_threads.restype = None  # returns nothing
        lib.kes_threads.restype = ctypes.c_int  # the thread count in use
        lib.kes_blank_impulses.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_int, _DOUBLE_P]  # x, n, threshold, guard, out
        lib.kes_blank_impulses.restype = None  # returns nothing
        lib.kes_viterbi_decode.argtypes = [_DOUBLE_P, ctypes.c_size_t, _BYTE_P]  # llrs, n, bits
        lib.kes_viterbi_decode.restype = ctypes.c_long  # bits written, or -1
        lib.kes_band_energies.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t,
                                          ctypes.c_double, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t, _DOUBLE_P]  # x, n, start, nsym, samples, offset, drift, lo, hi, out
        lib.kes_band_energies.restype = ctypes.c_int  # 0, or -1 on bad arguments
        lib.kes_detect_preamble.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_size_t, _INT_P, ctypes.c_size_t, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_int, _LONG_P, _INT_P, _DOUBLE_P]  # x, n, samples, bins, ntones, pad, hops, reach, whiten, keep, rows, shifts, quality
        lib.kes_detect_preamble.restype = ctypes.c_int  # how many found, or -1
        lib.kes_fine_time.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_size_t, _INT_P, ctypes.c_size_t, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_double, _DOUBLE_P, _DOUBLE_P]  # x, n, samples, bins, ntones, pad, hops, shift, coarse start, start out, steps out
        lib.kes_fine_time.restype = ctypes.c_int  # 0 refined, 1 too short, -1 bad arguments
        lib.kes_read_header.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t,
                                        ctypes.c_int, ctypes.c_int, _INT_P, _INT_P, ctypes.c_size_t, ctypes.c_double, _BYTE_P]  # x, n, start, offset, samples, lo, hi, step, level, totals by type, body totals, count, since, bits
        lib.kes_read_header.restype = ctypes.c_int  # 1 first, 2 both, 3 second, 0 none, -1 bad arguments
        why = ""  # in use: no reason to give
        return lib  # ready
    if not why:  # nothing was found at all
        why = "not installed"  # say so
    return None  # pure Python


why = ""  # the reason the library is not in use ("" when it is)
_lib = _load()  # the library, opened once when the modem is imported
path = None if _lib is None else _lib._name  # where it was found, for the About box


def available():  # is the library in use?
    """Return True when the compiled library is loaded and will be used."""
    return _lib is not None  # loaded or not


def describe():  # one line for the About box and the log
    """Return a short description of whether the compiled modem is in use."""
    return f"compiled modem library in use ({threads()} threads)" if _lib is not None else f"pure Python modem ({why})"  # either way, in plain words


def threads():  # how many threads the library uses
    """Return the number of threads the compiled library shares its heavy work among (0 when it is not in use)."""
    return _lib.kes_threads() if _lib is not None else 0  # as the library reports it


def set_threads(count):  # limit the library's threads
    """Use at most `count` threads in the compiled library (0 = as many as the computer has, up to 8). Results do not change, only speed."""
    if _lib is not None:  # only when loaded
        _lib.kes_set_threads(int(count))  # tell it


def _doubles(a):  # a NumPy array the library can read directly
    """Return `a` as a contiguous array of doubles (copied only if it is not one already)."""
    return np.ascontiguousarray(a, dtype=np.float64)  # the library expects plain doubles, one after another


def _ptr(a):  # a pointer to an array of doubles
    """Return a ctypes pointer to the data of the double array `a`."""
    return a.ctypes.data_as(_DOUBLE_P)  # the address of its first element


def blank_impulses(x, threshold, guard):  # modem/blanker.py blank_impulses, compiled
    """Return the blanked copy of `x`, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    out = np.empty_like(x)  # room for the result
    _lib.kes_blank_impulses(_ptr(x), len(x), float(threshold), int(guard), _ptr(out))  # do it
    return out  # the cleaned audio


def viterbi_decode(llrs):  # modem/fec.py viterbi_decode, compiled
    """Return the decoded data bits, or None when the library is not in use (or the input is too short)."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    llrs = _doubles(llrs)  # plain doubles
    bits = np.empty(max(len(llrs) // 2, 0), dtype=np.uint8)  # room for every step's bit (the tail is dropped below)
    count = _lib.kes_viterbi_decode(_ptr(llrs), len(llrs), bits.ctypes.data_as(_BYTE_P))  # decode
    if count < 0:  # too short to decode
        return None  # let the Python code deal with it as it always has
    return bits[:count]  # the data bits


def band_energies(x, start, nsym, samples, offset_hz, drift_hz_s, lo, hi):  # modem/mfsk.py band_energies, compiled
    """Return the nsym x (hi - lo + 1) energies, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    out = np.empty((int(nsym), int(hi) - int(lo) + 1))  # room for the result
    if nsym <= 0:  # nothing asked for
        return out  # an empty table
    status = _lib.kes_band_energies(_ptr(x), len(x), float(start), int(nsym), int(samples), float(offset_hz), float(drift_hz_s),
                                    int(lo), int(hi), _ptr(out))  # measure
    if status != 0:  # the library refused the arguments
        return None  # the Python code will handle (or report) them
    return out  # the energies


def _ints(values):  # a C array of ints
    """Return `values` as a contiguous array of C ints, and a pointer to it."""
    array = np.ascontiguousarray(values, dtype=np.intc)  # plain C ints
    return array, array.ctypes.data_as(_INT_P)  # the array (kept alive by the caller) and its address


def detect_preamble(x, samples, bins, pad, hops, reach, whiten, keep):  # modem/preamble.py detect_preamble's coarse search, compiled
    """Return a list of (row, shift, quality) for the strongest `keep` pattern matches, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    tones, tones_p = _ints(bins)  # the pattern's tones, in fine steps
    rows = np.zeros(keep, dtype=np.int_ if ctypes.sizeof(ctypes.c_long) == 8 else np.int32)  # room for the starts (C long: 8 bytes on Linux, 4 on Windows)
    shifts = np.zeros(keep, dtype=np.intc)  # room for the frequency errors
    quality = np.zeros(keep)  # room for the qualities
    got = _lib.kes_detect_preamble(_ptr(x), len(x), int(samples), tones_p, len(tones), int(pad), int(hops), int(reach), int(bool(whiten)), int(keep),
                                   rows.ctypes.data_as(_LONG_P), shifts.ctypes.data_as(_INT_P), quality.ctypes.data_as(_DOUBLE_P))  # search
    if got < 0:  # the library refused the arguments
        return None  # the Python code will handle them
    return [(int(rows[i]), int(shifts[i]), float(quality[i])) for i in range(got)]  # strongest first


def fine_time(x, samples, bins, pad, hops, shift, coarse_start):  # modem/preamble.py fine_time, compiled
    """Return (start in samples, frequency error in fine steps), "short" when there is too little audio, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    tones, tones_p = _ints(bins)  # the pattern's tones, in fine steps
    start, steps = ctypes.c_double(), ctypes.c_double()  # room for the answers
    status = _lib.kes_fine_time(_ptr(x), len(x), int(samples), tones_p, len(tones), int(pad), int(hops), int(shift), float(coarse_start),
                                ctypes.byref(start), ctypes.byref(steps))  # refine
    if status < 0:  # the library refused the arguments
        return None  # the Python code will handle them
    if status == 1:  # too little audio
        return "short"  # the caller keeps the coarse answer
    return start.value, steps.value  # the refined start and frequency error


_HOW = {1: "first", 2: "both", 3: "second"}  # which header copy gave the header, by the library's answer


def read_header(x, header_start, offset_hz, samples, lo, hi, step, level, totals_by_type, body_totals, since):  # modem/frame.py _read_header_how, compiled
    """Return (header bits, which copy) or (None, ""), as _read_header_how does; None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    by_type, by_type_p = _ints(totals_by_type)  # body length for each frame type and size class
    bodies, bodies_p = _ints(body_totals)  # every body length
    bits = np.zeros(24, dtype=np.uint8)  # room for the header
    got = _lib.kes_read_header(_ptr(x), len(x), float(header_start), float(offset_hz), int(samples), int(lo), int(hi), int(step), int(level),
                               by_type_p, bodies_p, len(bodies), -1.0 if since is None else float(since), bits.ctypes.data_as(_BYTE_P))  # read
    if got < 0:  # the library refused the arguments
        return None  # the Python code will handle them
    if got == 0:  # no header
        return None, ""  # as the Python says it
    return bits, _HOW[got]  # the header, and which copy gave it
