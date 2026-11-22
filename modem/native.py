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

ABI_VERSION = 1  # the library interface this file was written for (KES_ABI_VERSION in cpp/include/kestrel.h)

_DOUBLE_P = ctypes.POINTER(ctypes.c_double)  # a pointer to doubles
_BYTE_P = ctypes.POINTER(ctypes.c_uint8)  # a pointer to bytes


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
        lib.kes_blank_impulses.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_int, _DOUBLE_P]  # x, n, threshold, guard, out
        lib.kes_blank_impulses.restype = None  # returns nothing
        lib.kes_viterbi_decode.argtypes = [_DOUBLE_P, ctypes.c_size_t, _BYTE_P]  # llrs, n, bits
        lib.kes_viterbi_decode.restype = ctypes.c_long  # bits written, or -1
        lib.kes_band_energies.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t,
                                          ctypes.c_double, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t, _DOUBLE_P]  # x, n, start, nsym, samples, offset, drift, lo, hi, out
        lib.kes_band_energies.restype = ctypes.c_int  # 0, or -1 on bad arguments
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
    return "compiled modem library in use" if _lib is not None else f"pure Python modem ({why})"  # either way, in plain words


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
