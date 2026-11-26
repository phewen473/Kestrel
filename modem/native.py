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

ABI_VERSION = 19  # the library interface this file was written for (KES_ABI_VERSION in cpp/include/kestrel.h)
from .params import RAMP_S  # how long each transmission fades in and out (passed to the compiled transmitter)  # noqa: E402

_DOUBLE_P = ctypes.POINTER(ctypes.c_double)  # a pointer to doubles
_BYTE_P = ctypes.POINTER(ctypes.c_uint8)  # a pointer to bytes
_INT_P = ctypes.POINTER(ctypes.c_int)  # a pointer to ints
_LONG_P = ctypes.POINTER(ctypes.c_long)  # a pointer to longs


class _Fields(ctypes.Structure):  # KesFields in kestrel.h: the named fields of a control frame or an address block
    _fields_ = [("origin", ctypes.c_char * 10), ("dest", ctypes.c_char * 10), ("grid", ctypes.c_char * 5),  # addresses and the locator
                ("levels", ctypes.c_int), ("listening", ctypes.c_int), ("mail_check", ctypes.c_int), ("holds_mail", ctypes.c_int),  # level list and flags
                ("wide", ctypes.c_int), ("directed", ctypes.c_int), ("final_flag", ctypes.c_int),  # more flags
                ("link", ctypes.c_long), ("msg_id", ctypes.c_long), ("part", ctypes.c_long), ("status", ctypes.c_long),  # numbers
                ("hops", ctypes.c_long), ("life_hours", ctypes.c_long),  # an addressed message's counters
                ("snr_db", ctypes.c_double), ("fade_index", ctypes.c_double), ("offset_hz", ctypes.c_double), ("want_level", ctypes.c_int),  # a channel report
                ("held", ctypes.c_long * 3), ("receipts", ctypes.c_long * 3), ("heard", ctypes.c_long * 3),  # a mail notice's three lists
                ("nheld", ctypes.c_int), ("nreceipts", ctypes.c_int), ("nheard", ctypes.c_int),  # and their lengths
                ("rig_model", ctypes.c_long), ("watts", ctypes.c_long)]  # a beacon's rig type and power (since interface 17)


_FIELDS_P = ctypes.POINTER(_Fields)  # a pointer to the fields
_BUSY = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int)  # KesBusy: the station's listen-before-transmit check


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
        lib.kes_viterbi_decode_known.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int8), ctypes.c_size_t, _BYTE_P]  # llrs, n, known bits, how many, bits
        lib.kes_viterbi_decode_known.restype = ctypes.c_long  # bits written, or -1
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
        lib.kes_read_header.restype = ctypes.c_int  # 1 first, 2 both, 3 second, 4 end, 5 end both, 6 end first, 0 none, -1 bad arguments
        lib.kes_ldpc_decode.argtypes = [_DOUBLE_P, ctypes.c_long, _LONG_P, _LONG_P, ctypes.c_long, _LONG_P, ctypes.c_double, ctypes.c_int, _BYTE_P]  # llrs, k, edge bits, edge checks, edges, starts, scale, rounds, bits
        lib.kes_ldpc_decode.restype = ctypes.c_int  # 1 all checks satisfied, 0 gave up, -1 bad arguments
        lib.kes_noise_profile.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, _DOUBLE_P]  # tone energies, rows, span, tracking, level
        lib.kes_noise_profile.restype = ctypes.c_int  # 0, or -1
        lib.kes_tone_spread.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_size_t, _LONG_P, ctypes.c_int, _DOUBLE_P, _DOUBLE_P]  # band, rows, columns, tones sent, step, noise per row, answers (since ABI 14)
        lib.kes_tone_spread.restype = ctypes.c_int  # 0, or -1
        lib.kes_pilot_fit.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, _LONG_P, _INT_P, ctypes.c_size_t, ctypes.c_size_t,
                                      _INT_P, ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_int, _DOUBLE_P, _DOUBLE_P]  # x, n, start, positions, tones, pilots, samples, tone bins, pad, span, offset, backward (since interface 18), extra, drift
        lib.kes_pilot_fit.restype = ctypes.c_int  # 0, or -1
        lib.kes_remove_steady.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_double, ctypes.c_size_t, _DOUBLE_P]  # x, n, block, windowed, low, high, times, neighborhood, most, half width, size, out
        lib.kes_remove_steady.restype = ctypes.c_int  # steps notched, or -1
        lib.kes_decode_body.argtypes = [_DOUBLE_P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int,  # x, n, body start, offset, samples, lo, hi, step
                                        ctypes.c_size_t, _LONG_P, _INT_P, ctypes.c_size_t, _LONG_P, ctypes.c_size_t,  # tones, pilot places, pilot tones, pilots, data places, data tones
                                        ctypes.c_size_t, ctypes.c_int, ctypes.c_long, _LONG_P, _LONG_P, ctypes.c_long,  # coded bits, control?, LDPC data bits, edge bits, edge checks, edges
                                        _LONG_P, ctypes.c_double, ctypes.c_int, _DOUBLE_P, ctypes.c_size_t, ctypes.c_int, ctypes.c_int,  # check starts, scale, rounds, prior, prior length, pad, fine span
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, _BYTE_P, _DOUBLE_P, _DOUBLE_P, _DOUBLE_P]  # noise span, tracking, found from its end (since interface 18), data out, soft bits out, band out, figures out
        lib.kes_decode_body.restype = ctypes.c_long  # data bits written, or -1
        lib.kes_crc16.argtypes = [_BYTE_P, ctypes.c_size_t]  # bits, count
        lib.kes_crc16.restype = ctypes.c_int  # the check value
        lib.kes_crc8.argtypes = [_BYTE_P, ctypes.c_size_t]  # bits, count
        lib.kes_crc8.restype = ctypes.c_int  # the check value
        lib.kes_call_to_bits.argtypes = [ctypes.c_char_p, _BYTE_P]  # address, 48 bits
        lib.kes_call_to_bits.restype = ctypes.c_int  # 0, or -1
        lib.kes_bits_to_call.argtypes = [_BYTE_P, ctypes.c_char_p]  # 48 bits, address
        lib.kes_bits_to_call.restype = ctypes.c_int  # 0, or -1
        lib.kes_call_hash.argtypes = [ctypes.c_char_p]  # address
        lib.kes_call_hash.restype = ctypes.c_long  # the code, or -1
        lib.kes_message_hash.argtypes = [ctypes.c_char_p, ctypes.c_long]  # origin, message number
        lib.kes_message_hash.restype = ctypes.c_long  # the code, or -1
        lib.kes_link_id.argtypes = [ctypes.c_char_p, ctypes.c_char_p]  # the two addresses
        lib.kes_link_id.restype = ctypes.c_long  # the link number, or -1
        lib.kes_choose_packing.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, _INT_P, _INT_P]  # text, length, frame type, size class, compressed
        lib.kes_choose_packing.restype = ctypes.c_int  # 0, or -1
        lib.kes_text_to_bits.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, _BYTE_P]  # text, length, size class, compressed, frame type, bits
        lib.kes_text_to_bits.restype = ctypes.c_long  # bits written, or -1
        lib.kes_bits_to_text.argtypes = [_BYTE_P, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]  # bits, count, compressed, text, room
        lib.kes_bits_to_text.restype = ctypes.c_long  # characters, or -1
        lib.kes_header_bits.argtypes = [ctypes.c_int] * 6 + [_BYTE_P]  # type, level, size class, part, parts, compressed, 24 bits
        lib.kes_header_bits.restype = None  # returns nothing
        lib.kes_address_block.argtypes = [ctypes.c_int, ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_long, _BYTE_P]  # type, link, level, message, dest, origin, hops, hours, bits
        lib.kes_address_block.restype = ctypes.c_long  # bits written, or -1
        lib.kes_read_address_block.argtypes = [ctypes.c_int, _BYTE_P, _FIELDS_P]  # type, bits, fields
        lib.kes_read_address_block.restype = ctypes.c_int  # 0, or -1
        lib.kes_levels_mask.argtypes = [_LONG_P, ctypes.c_size_t]  # levels, count
        lib.kes_levels_mask.restype = ctypes.c_int  # the mask, or -1
        lib.kes_pack_control.argtypes = [ctypes.c_int, _FIELDS_P, _BYTE_P]  # type, fields, bits
        lib.kes_pack_control.restype = ctypes.c_long  # bits written, or -1
        lib.kes_unpack_control.argtypes = [ctypes.c_int, _BYTE_P, ctypes.c_size_t, _FIELDS_P]  # type, bits, count, fields
        lib.kes_unpack_control.restype = ctypes.c_int  # 0, or -1
        lib.kes_mail_new.argtypes = []  # nothing
        lib.kes_mail_new.restype = ctypes.c_void_p  # the store
        lib.kes_mail_free.argtypes = [ctypes.c_void_p]  # the store
        lib.kes_mail_free.restype = None  # returns nothing
        lib.kes_mail_request.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]  # store, request, time
        lib.kes_mail_request.restype = ctypes.c_long  # the reply's length, or -1
        lib.kes_mail_reply.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]  # store, room, its size
        lib.kes_mail_reply.restype = ctypes.c_long  # the reply's length, or -1
        lib.kes_station_new.argtypes = []  # nothing
        lib.kes_station_new.restype = ctypes.c_void_p  # the station
        lib.kes_station_free.argtypes = [ctypes.c_void_p]  # the station
        lib.kes_station_free.restype = None  # returns nothing
        lib.kes_station_set_mail.argtypes = [ctypes.c_void_p, ctypes.c_void_p]  # station, mail store
        lib.kes_station_set_mail.restype = None  # returns nothing
        lib.kes_station_set_busy.argtypes = [ctypes.c_void_p, _BUSY, ctypes.c_void_p]  # station, check, context
        lib.kes_station_set_busy.restype = None  # returns nothing
        lib.kes_station_request.argtypes = [ctypes.c_void_p, ctypes.c_char_p]  # station, request
        lib.kes_station_request.restype = ctypes.c_long  # the reply's length, or -1
        lib.kes_station_reply.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]  # station, room, its size
        lib.kes_station_reply.restype = ctypes.c_long  # the reply's length, or -1
        lib.kes_encode_frame.argtypes = [_BYTE_P, _BYTE_P, ctypes.c_size_t, ctypes.c_int, _LONG_P, ctypes.c_size_t, _LONG_P, ctypes.c_size_t, _LONG_P, _INT_P, ctypes.c_size_t,
                                         ctypes.c_size_t, _INT_P, ctypes.c_size_t, ctypes.c_size_t, _INT_P, ctypes.c_double, ctypes.c_size_t, _DOUBLE_P]  # header, data, data length, control?, LDPC rows, tones, data places, data tones, pilot places, pilot tones, pilots, coded, preamble, its length, samples, tone bins, glide (share of a tone), fade (samples), audio (interface 12)
        lib.kes_encode_frame.restype = ctypes.c_long  # samples written, or -1
        lib.kes_listener_new.argtypes = [_DOUBLE_P, ctypes.c_size_t]  # settings, how many
        lib.kes_listener_new.restype = ctypes.c_void_p  # the listener (a handle)
        lib.kes_listener_free.argtypes = [ctypes.c_void_p]  # the listener
        lib.kes_listener_free.restype = None  # returns nothing
        lib.kes_listener_set_pattern.argtypes = [ctypes.c_void_p, ctypes.c_int, _DOUBLE_P, _INT_P, ctypes.c_size_t]  # listener, slot, values, bins, how many
        lib.kes_listener_set_pattern.restype = ctypes.c_int  # 0, or -1
        lib.kes_listener_set_tables.argtypes = [ctypes.c_void_p, _INT_P, _INT_P, ctypes.c_size_t]  # listener, totals by type, body totals, how many
        lib.kes_listener_set_tables.restype = ctypes.c_int  # 0, or -1
        lib.kes_listener_clear.argtypes = [ctypes.c_void_p]  # the listener
        lib.kes_listener_clear.restype = None  # returns nothing
        lib.kes_listener_feed.argtypes = [ctypes.c_void_p, _DOUBLE_P, ctypes.c_size_t, ctypes.c_longlong, ctypes.c_int]  # listener, samples, how many, first number, numbered?
        lib.kes_listener_feed.restype = ctypes.c_int  # 1 when a search is due
        lib.kes_listener_begin.argtypes = [ctypes.c_void_p, ctypes.c_int]  # listener, near misses wanted
        lib.kes_listener_begin.restype = ctypes.c_int  # 1 when there is something to search
        lib.kes_listener_next.argtypes = [ctypes.c_void_p, _DOUBLE_P]  # listener, event
        lib.kes_listener_next.restype = ctypes.c_int  # the event's kind (0 when done)
        for name, kind in (("kes_listener_size", ctypes.c_size_t), ("kes_listener_x_size", ctypes.c_size_t), ("kes_listener_near_size", ctypes.c_size_t),
                           ("kes_listener_searches", ctypes.c_long), ("kes_listener_pending", ctypes.c_size_t)):  # the simple questions
            getattr(lib, name).argtypes = [ctypes.c_void_p]  # the listener
            getattr(lib, name).restype = kind  # the answer
        for name in ("kes_listener_x", "kes_listener_near_audio"):  # the arrays it shows
            getattr(lib, name).argtypes = [ctypes.c_void_p]  # the listener
            getattr(lib, name).restype = _DOUBLE_P  # the first value's address
        lib.kes_listener_number.argtypes = [ctypes.c_void_p, ctypes.c_long]  # listener, store position
        lib.kes_listener_number.restype = ctypes.c_longlong  # the stream number
        lib.kes_listener_cut.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_long]  # listener, start, end
        lib.kes_listener_cut.restype = None  # returns nothing
        lib.kes_listener_copy.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_long, _DOUBLE_P]  # listener, from, to, out
        lib.kes_listener_copy.restype = ctypes.c_size_t  # how many copied
        lib.kes_listener_candidates.argtypes = [ctypes.c_void_p, _DOUBLE_P, ctypes.c_size_t]  # listener, out, most (since ABI 15)
        lib.kes_listener_candidates.restype = ctypes.c_size_t  # how many written
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


def viterbi_decode(llrs, known=None):  # modem/fec.py viterbi_decode, compiled
    """Return the decoded data bits, or None when the library is not in use (or the input is too short). `known`: 0/1 per known data bit, -1 unknown."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    llrs = _doubles(llrs)  # plain doubles
    bits = np.empty(max(len(llrs) // 2, 0), dtype=np.uint8)  # room for every step's bit (the tail is dropped below)
    if known is None:  # nothing known in advance
        count = _lib.kes_viterbi_decode(_ptr(llrs), len(llrs), bits.ctypes.data_as(_BYTE_P))  # decode
    else:  # some bits known
        hints = np.ascontiguousarray(known, dtype=np.int8)  # -1, 0 or 1 per data bit
        count = _lib.kes_viterbi_decode_known(_ptr(llrs), len(llrs), hints.ctypes.data_as(ctypes.POINTER(ctypes.c_int8)), len(hints), bits.ctypes.data_as(_BYTE_P))  # decode
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


_C_LONG = np.int64 if ctypes.sizeof(ctypes.c_long) == 8 else np.int32  # NumPy's name for a C long (8 bytes on Linux, 4 on Windows)


def _longs(values):  # a C array of longs
    """Return `values` as a contiguous array of C longs, and a pointer to it."""
    array = np.ascontiguousarray(values, dtype=_C_LONG)  # plain C longs
    return array, array.ctypes.data_as(_LONG_P)  # the array (kept alive by the caller) and its address


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
    rows = np.zeros(keep, dtype=_C_LONG)  # room for the starts
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


_HOW = {1: "first", 2: "both", 3: "second", 4: "end", 5: "end both", 6: "end first"}  # which header copy gave the header, by the library's answer (4 to 6: the frame was found from the pattern at its end, since interface 18)


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


_GRAPHS = {}  # the LDPC wiring for each code size, converted once for the library


def ldpc_decode(llrs, k, graph, scale, rounds):  # modem/ldpc.py decode, compiled
    """Return (k data bits, True if every check is satisfied), or None when the library is not in use. `graph` is ldpc._graph(k)."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    if k not in _GRAPHS:  # this size not converted yet
        checks, bits, starts = graph  # the code's wiring
        _GRAPHS[k] = (_longs(bits), _longs(checks), _longs(starts), len(bits))  # as C arrays, kept for next time
    (_bits, bits_p), (_checks, checks_p), (_starts, starts_p), edges = _GRAPHS[k]  # the converted wiring
    llrs = _doubles(llrs)  # plain doubles
    out = np.zeros(k, dtype=np.uint8)  # room for the data bits
    ok = _lib.kes_ldpc_decode(_ptr(llrs), int(k), bits_p, checks_p, int(edges), starts_p, float(scale), int(rounds), out.ctypes.data_as(_BYTE_P))  # decode
    if ok < 0:  # the library refused the arguments
        return None  # the Python code will handle them
    return out, bool(ok)  # the bits, and whether every check held


def noise_profile(tone_e, span, tracking):  # modem/mfsk.py noise_profile, compiled
    """Return the noise level at each symbol of `tone_e` (symbols x 32), or None when the library is not in use."""
    if _lib is None or tone_e.ndim != 2 or tone_e.shape[1] != 32 or tone_e.shape[0] == 0:  # no library, or not the usual shape
        return None  # the caller uses Python
    tone_e = _doubles(tone_e)  # plain doubles, row after row
    level = np.empty(tone_e.shape[0])  # room for the answer
    if _lib.kes_noise_profile(_ptr(tone_e), tone_e.shape[0], int(span), int(bool(tracking)), _ptr(level)) < 0:  # the library refused
        return None  # the Python code will handle it
    return level  # one level per symbol


def tone_spread(band, tones, step, noise):  # modem/mfsk.py tone_spread, compiled (since ABI 14)
    """Return (share in the neighbors, lean, trust) for known tones, or None when the library is not in use."""
    if _lib is None or band.ndim != 2 or band.shape[0] == 0:  # no library, or nothing to measure
        return None  # the caller uses Python
    band = _doubles(band)  # plain doubles, row after row
    sent, sent_p = _longs(tones)  # the tone sent in each row
    level = _doubles(np.broadcast_to(np.asarray(noise, dtype=float), (band.shape[0],)))  # the noise per bin of each row
    out = np.empty(3)  # room for the answers
    if _lib.kes_tone_spread(_ptr(band), band.shape[0], band.shape[1], sent_p, int(step), _ptr(level), _ptr(out)) < 0:  # the library refused
        return None  # the Python code will handle it
    return float(out[0]), float(out[1]), float(out[2])  # the three readings


def pilot_fit(x, start, positions, tones, samples, tone_bins, pad, fine_span, offset_hz, backward=False):  # modem/mfsk.py pilot_frequency_fit, compiled
    """Return (extra offset at the first symbol in Hz, drift in Hz per second), or None when the library is not in use."""
    if _lib is None or len(positions) == 0:  # no library, or no pilots
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    where, where_p = _longs(positions)  # which symbols are pilots
    which, which_p = _ints(tones)  # which tone each sends
    bins, bins_p = _ints(tone_bins)  # every tone's FFT bin
    extra, drift = ctypes.c_double(), ctypes.c_double()  # room for the answers
    if _lib.kes_pilot_fit(_ptr(x), len(x), float(start), where_p, which_p, len(where), int(samples), bins_p, int(pad), int(fine_span), float(offset_hz), int(bool(backward)),
                          ctypes.byref(extra), ctypes.byref(drift)) < 0:  # the library refused
        return None  # the Python code will handle it
    return extra.value, drift.value  # the fit


def remove_steady(x, block, low_hz, high_hz, times, local_steps, most, half_hz, size, windowed=True):  # modem/notch.py remove_steady (and longbeacon.clean), compiled
    """Return `x` with steady signals notched out, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    x = _doubles(x)  # plain doubles
    out = np.empty_like(x)  # room for the result
    if _lib.kes_remove_steady(_ptr(x), len(x), int(block), int(bool(windowed)), float(low_hz), float(high_hz), float(times), int(local_steps), int(most), float(half_hz), int(size), _ptr(out)) < 0:  # the library refused
        return None  # the Python code will handle it
    return out  # the audio, notched where needed


def decode_body(x, body_start, offset_hz, spec, layout, is_control, prior=None, from_end=False):  # modem/frame.py _decode_body's sums, compiled (`from_end`: the frequency was measured at the frame's end, since interface 18)
    """Return (data bits, soft bits, band energies, (offset, drift, snr_db, fade, passed, noise)), or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    from . import ldpc, mfsk  # the decoder's settings and the noise-tracking settings (imported here: they import this module)
    x = _doubles(x)  # plain doubles
    lo, hi = int(spec.tone_bins[0]) - 1, int(spec.tone_bins[-1]) + 1  # the band measured: a bin either side of the tones
    pilot_pos, pilot_pos_p = _longs(layout["pilot_pos"])  # where the pilots are
    pilot_tones, pilot_tones_p = _ints(layout["pilot_tones"])  # which tone each sends
    data_pos, data_pos_p = _longs(layout["data_pos"])  # where the data tones are
    coded = int(layout["coded"])  # soft bits kept
    info = 0 if is_control else int(layout["info"])  # LDPC data bits (none for the convolutional code)
    if is_control:  # no LDPC wiring needed
        edge_bits_p = edge_checks_p = starts_p = None  # nothing
        edges = 0  # no edges
    else:  # the LDPC wiring for this size, converted once
        if info not in _GRAPHS:  # not converted yet
            checks, bits, starts = ldpc._graph(info)  # the code's wiring
            _GRAPHS[info] = (_longs(bits), _longs(checks), _longs(starts), len(bits))  # kept for next time
        (_bits, edge_bits_p), (_checks, edge_checks_p), (_starts, starts_p), edges = _GRAPHS[info]  # the converted wiring
    if prior is not None and len(prior) == coded:  # an earlier copy to add
        prior_arr = _doubles(prior)  # plain doubles
        prior_p, nprior = _ptr(prior_arr), coded  # its address and length
    else:  # none
        prior_p, nprior = None, 0  # nothing
    data = np.zeros(max(coded // 2, info), dtype=np.uint8)  # room for the data bits
    llrs = np.zeros(coded)  # room for the soft bits
    band = np.zeros((int(layout["total"]), hi - lo + 1))  # room for the band
    stats = np.zeros(6)  # room for the figures
    count = _lib.kes_decode_body(_ptr(x), len(x), float(body_start), float(offset_hz), int(spec.samples), lo, hi, int(spec.step),
                                 int(layout["total"]), pilot_pos_p, pilot_tones_p, len(pilot_pos), data_pos_p, len(data_pos),
                                 coded, int(bool(is_control)), info, edge_bits_p, edge_checks_p, edges,
                                 starts_p, float(ldpc.SCALE), int(ldpc.MAX_ITERATIONS), prior_p, nprior, int(mfsk.PAD), int(mfsk.FINE_SPAN),
                                 int(mfsk.NOISE_SPAN), int(bool(mfsk.NOISE_TRACKING)), int(bool(from_end)), data.ctypes.data_as(_BYTE_P), _ptr(llrs), _ptr(band), _ptr(stats))  # decode
    if count < 0:  # the library refused the arguments
        return None  # the Python code will handle them
    offset, drift, snr_db, fade, passed, noise = (float(value) for value in stats)  # the figures
    return data[:count], llrs, band, (offset, drift, snr_db, fade, bool(passed), noise)  # everything _decode_body needs


CFG_COUNT = 28  # how many settings the compiled listener takes (KES_CFG_COUNT in kestrel.h)


class CompiledListener:  # the compiled continuous receiver (interface 7)
    """The audio store and candidate bookkeeping of live/listener.py, kept in the library.

    live.listener.Listener drives it: it feeds audio, starts each search,
    and handles the events (frames to decode, long beacons to read, tries
    and near misses) with the same Python code as before.
    """

    def __init__(self, cfg, patterns, totals_by_type, body_totals):  # make one
        self._settings = _doubles(cfg)  # the settings, in KES_CFG_ order
        self.handle = _lib.kes_listener_new(_ptr(self._settings), len(self._settings))  # the library's listener
        if not self.handle:  # refused
            raise RuntimeError("the compiled listener did not accept its settings")  # say so
        for slot, (values, bins) in patterns.items():  # each pattern
            numbers = _doubles(values)  # its figures
            tones, tones_p = _ints(bins)  # its tones
            _lib.kes_listener_set_pattern(self.handle, int(slot), _ptr(numbers), tones_p, len(tones))  # described
        by_type, by_type_p = _ints(totals_by_type)  # body length by frame type and size class
        bodies, bodies_p = _ints(body_totals)  # every body length
        _lib.kes_listener_set_tables(self.handle, by_type_p, bodies_p, len(bodies))  # given
        self.event = np.zeros(9)  # room for one event (nine values since interface 18: a frame event also gives where the frame begins)

    def __del__(self):  # the Python object goes
        if getattr(self, "handle", None) and _lib is not None:  # it was made
            _lib.kes_listener_free(self.handle)  # so is the library's
            self.handle = None  # once only

    def feed(self, samples, at):  # add audio
        """Add `samples` (numbered from `at`, or counted on when at is None); return True when a search is due."""
        samples = _doubles(samples)  # plain doubles
        return bool(_lib.kes_listener_feed(self.handle, _ptr(samples), len(samples), 0 if at is None else int(at), 0 if at is None else 1))  # stored

    def begin(self, near_on):  # start a search
        """Blank, notch and search the newest audio; return False when there is too little audio."""
        return bool(_lib.kes_listener_begin(self.handle, int(bool(near_on))))  # done in the library

    def next(self):  # the search's next event
        """Return (kind, event array): 1 a frame to decode, 2 a long beacon to read, 3 a try with no header (and maybe a near miss); kind 0 when the search is done."""
        kind = _lib.kes_listener_next(self.handle, _ptr(self.event))  # the next
        return kind, self.event  # its kind and figures

    def x(self):  # the processed store
        """Return the blanked and notched store of the latest search, as an array that shares the library's memory (valid until the next search)."""
        size = _lib.kes_listener_x_size(self.handle)  # its length
        if size == 0:  # nothing
            return np.zeros(0)  # empty
        return np.ctypeslib.as_array(_lib.kes_listener_x(self.handle), shape=(size, ))  # a view, not a copy

    def near_audio(self):  # the latest near miss's audio
        """Return a copy of the audio of the latest near miss."""
        size = _lib.kes_listener_near_size(self.handle)  # its length
        return np.ctypeslib.as_array(_lib.kes_listener_near_audio(self.handle), shape=(size, )).copy() if size else np.zeros(0)  # a copy

    def size(self):  # samples kept
        """Return the number of samples in the store."""
        return int(_lib.kes_listener_size(self.handle))  # from the library

    def number(self, position):  # a store position as a stream number
        """Return the stream's number for store position `position`."""
        return int(_lib.kes_listener_number(self.handle, int(round(position))))  # from the library

    def copy(self, start, end):  # a stretch of the store
        """Return a copy of store positions start to end."""
        out = np.zeros(max(0, int(end) - max(int(start), 0)))  # room
        got = _lib.kes_listener_copy(self.handle, int(start), int(end), _ptr(out)) if len(out) else 0  # copied
        return out[:got]  # what there was

    def cut(self, start, end):  # take a stretch out
        """Remove store positions start to end."""
        _lib.kes_listener_cut(self.handle, int(start), int(end))  # in the library

    def clear(self):  # forget everything
        """Empty the store and the candidate list."""
        _lib.kes_listener_clear(self.handle)  # in the library

    def searches(self):  # searches so far
        """Return how many searches have been made."""
        return int(_lib.kes_listener_searches(self.handle))  # from the library

    def pending(self):  # candidates being followed
        """Return how many candidates are being followed."""
        return int(_lib.kes_listener_pending(self.handle))  # from the library

    CANDIDATE_FIELDS = 11  # values per candidate (KES_CANDIDATE_FIELDS in kestrel.h)

    def candidates(self):  # the candidates being followed, for the frame strip (since ABI 15)
        """Return a list of dicts, one per candidate: slot, stream, position, offset_hz, quality, coarse, has_header, how, fields, tried, start_fine."""
        most = max(self.pending(), 1)  # room for all of them
        out = np.zeros(most * self.CANDIDATE_FIELDS)  # the library writes here
        count = int(_lib.kes_listener_candidates(self.handle, _ptr(out), most))  # written
        rows = out[:count * self.CANDIDATE_FIELDS].reshape(count, self.CANDIDATE_FIELDS)  # one row each
        names = ("slot", "stream", "position", "offset_hz", "quality", "coarse", "has_header", "how", "fields", "tried", "start_fine")  # the values, in order
        return [dict(zip(names, row.tolist())) for row in rows]  # as dicts


def compiled_listener(cfg, patterns, totals_by_type, body_totals):  # make one, if the library is in use
    """Return a CompiledListener, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    return CompiledListener(cfg, patterns, totals_by_type, body_totals)  # made


_ROWS = {}  # the LDPC encoder's three shuffles for each code size, converted once


def encode_frame(header_bits, data_bits, is_control, layout, spec, preamble_tones):  # frame.py's transmitter, compiled
    """Return the audio of a frame (pattern, header, body, pattern, header) from its packed bits, or None when the library is not in use."""
    if _lib is None:  # no library
        return None  # the caller uses Python
    header = np.ascontiguousarray(header_bits, dtype=np.uint8)  # the 24 header bits
    data = np.ascontiguousarray(data_bits, dtype=np.uint8)  # the body bits, with the check value
    rows_p = None  # the LDPC shuffles (not needed for a control frame)
    if not is_control:  # a message frame
        if len(data) not in _ROWS:  # this size not converted yet
            from . import ldpc  # the code (imported here: it imports this module)
            _ROWS[len(data)] = _longs(np.asarray(ldpc.info_checks(len(data))).reshape(-1))  # the three shuffles, one after another
        rows_p = _ROWS[len(data)][1]  # their address
    data_pos, data_pos_p = _longs(layout["data_pos"])  # where the data tones go
    pilot_pos, pilot_pos_p = _longs(layout["pilot_pos"])  # where the pilots go
    pilot_tones, pilot_tones_p = _ints(layout["pilot_tones"])  # which tone each sends
    pattern, pattern_p = _ints(preamble_tones)  # the preamble's tones
    bins, bins_p = _ints(spec.tone_bins)  # every tone's FFT bin
    audio = np.zeros((2 * len(pattern) + 24 + int(layout["total"])) * spec.samples)  # room for the whole frame (the pattern at both ends since interface 18)
    got = _lib.kes_encode_frame(header.ctypes.data_as(_BYTE_P), data.ctypes.data_as(_BYTE_P), len(data), int(bool(is_control)), rows_p,
                                int(layout["total"]), data_pos_p, len(data_pos), pilot_pos_p, pilot_tones_p, len(pilot_pos),
                                int(layout["coded"]), pattern_p, len(pattern), int(spec.samples), bins_p, float(spec.glide), int(round(RAMP_S * 12000)), _ptr(audio))  # made (with the level's glide and the fades at the ends, since interface 12)
    if got < 0:  # the library refused
        return None  # the Python code will handle it
    return audio[:got]  # the frame's audio


# ---- Packing and unpacking the bits (interface 8) ----
# Each wrapper returns None when the library is not in use, when an argument is of a kind it does not
# take, or when the library refuses; the caller then runs its own Python code, which gives the answer
# or raises its own worded error. So the two paths always agree.

_LIMIT = 1 << 31  # numbers passed must fit a C long on every platform


def _whole(*values):  # are these whole numbers the library can take?
    """Return True when every value is a Python or NumPy whole number (or a bool) within the range of a 32-bit long."""
    return all(isinstance(v, (int, np.integer)) and -_LIMIT < int(v) < _LIMIT for v in values)  # whole and small enough


def _ascii(text, longest=None):  # text as bytes for the library
    """Return `text` as ASCII bytes, or None when it is not a string, holds a zero byte or anything outside ASCII, or is longer than `longest`."""
    if not isinstance(text, str) or "\0" in text or not text.isascii() or (longest is not None and len(text) > longest):  # not something the library takes
        return None  # Python decides
    return text.encode("ascii")  # the bytes


def _bits(bits):  # bits as bytes for the library
    """Return `bits` as a contiguous array of bytes."""
    return np.ascontiguousarray(bits, dtype=np.uint8)  # one byte per bit


def _byte_p(a):  # a pointer to an array of bytes
    """Return a ctypes pointer to the bytes of `a`."""
    return a.ctypes.data_as(_BYTE_P)  # its address


def crc(bits, width):  # crc.py crc16 and crc8, as a number
    """Return the CRC-16 (width 16) or CRC-8 (width 8) of `bits` as a number, or None."""
    if _lib is None:  # no library
        return None  # Python
    b = _bits(bits)  # as bytes
    return (_lib.kes_crc16 if width == 16 else _lib.kes_crc8)(_byte_p(b), len(b))  # the check value


def call_to_bits(call):  # address.py call_to_bits
    """Return the 48 bits of an address, or None."""
    text = _ascii(call, 9) if _lib is not None else None  # the address as bytes (Python takes longer, padded text)
    if text is None:  # nothing to hand over
        return None  # Python
    out = np.zeros(48, dtype=np.uint8)  # room
    return out if _lib.kes_call_to_bits(text, _byte_p(out)) == 0 else None  # the bits, or Python decides


def bits_to_call(bits):  # address.py bits_to_call
    """Return the address spelled by 48 bits, or None."""
    if _lib is None or len(bits) != 48:  # no library, or not one address
        return None  # Python
    out = ctypes.create_string_buffer(10)  # room
    return out.value.decode("ascii") if _lib.kes_bits_to_call(_byte_p(_bits(bits)), out) == 0 else None  # the address, or Python decides


def call_hash(call):  # address.py call_hash
    """Return the 16-bit code of an address, or None."""
    text = _ascii(call, 9) if _lib is not None else None  # as bytes
    got = _lib.kes_call_hash(text) if text is not None else -1  # the code
    return got if got >= 0 else None  # or Python decides


def message_hash(origin, msg_id):  # address.py message_hash
    """Return the 16-bit code of a message ID, or None."""
    text = _ascii(origin, 9) if _lib is not None else None  # as bytes
    got = _lib.kes_message_hash(text, int(msg_id)) if text is not None and _whole(msg_id) else -1  # the code
    return got if got >= 0 else None  # or Python decides


def link_id(first, second):  # address.py link_id
    """Return the link number of two addresses, or None."""
    a = _ascii(first, 9) if _lib is not None else None  # the first, as bytes
    b = _ascii(second, 9) if _lib is not None else None  # the second
    got = _lib.kes_link_id(a, b) if a is not None and b is not None else -1  # the number
    return got if got >= 0 else None  # or Python decides


def choose_packing(text, frame_type):  # text.py choose_packing
    """Return (size class, compressed?) for `text`, or None."""
    data = _ascii(text) if _lib is not None else None  # as bytes
    if data is None or not _whole(frame_type):  # nothing to hand over
        return None  # Python
    size_class = ctypes.c_int()  # room for the answer
    compressed = ctypes.c_int()  # and the other
    if _lib.kes_choose_packing(data, len(data), int(frame_type), ctypes.byref(size_class), ctypes.byref(compressed)) != 0:  # refused
        return None  # Python decides
    return size_class.value, bool(compressed.value)  # the answer


def text_to_bits(text, size_class, compressed, frame_type):  # text.py text_to_bits
    """Return the character count, text bits and padding, or None."""
    data = _ascii(text) if _lib is not None else None  # as bytes
    if data is None or not _whole(size_class, frame_type):  # nothing to hand over
        return None  # Python
    out = np.zeros(8 + 7 * 200, dtype=np.uint8)  # room for the largest
    got = _lib.kes_text_to_bits(data, len(data), int(size_class), int(bool(compressed)), int(frame_type), _byte_p(out))  # packed
    return out[:got] if got >= 0 else None  # the bits, or Python decides


def bits_to_text(bits, compressed):  # text.py bits_to_text
    """Return the text carried by `bits`, or None."""
    if _lib is None:  # no library
        return None  # Python
    b = _bits(bits)  # as bytes
    out = ctypes.create_string_buffer(256)  # room for any count
    got = _lib.kes_bits_to_text(_byte_p(b), len(b), int(bool(compressed)), out, 256)  # unpacked
    return out.raw[:got].decode("ascii") if got >= 0 else None  # the text, or Python decides


def header_bits(frame_type, level, size_class, part, parts, compressed):  # frame.py _header_bits
    """Return the 24 header bits, or None."""
    if _lib is None or not _whole(frame_type, level, size_class, part, parts, int(compressed)):  # no library, or not whole numbers
        return None  # Python
    out = np.zeros(24, dtype=np.uint8)  # room
    _lib.kes_header_bits(int(frame_type), int(level), int(size_class), int(part), int(parts), int(compressed), _byte_p(out))  # made
    return out  # the bits


def address_block(frame_type, link, want_level, msg_id, dest, origin, hops, life_hours):  # frame.py _address_block
    """Return the address block bits, or None."""
    try:  # the lifetime as Python reads it
        life = int(life_hours)  # whole hours
    except (TypeError, ValueError, OverflowError):  # not a number
        return None  # Python
    if _lib is None or not _whole(frame_type, link, want_level, msg_id, hops, life):  # no library, or not whole numbers
        return None  # Python
    d = _ascii(dest, 9) if dest is not None else b""  # the destination as bytes
    o = _ascii(origin, 9) if origin is not None else b""  # the origin
    if d is None or o is None:  # an address the library does not take
        return None  # Python
    out = np.zeros(120, dtype=np.uint8)  # room for the longer block
    got = _lib.kes_address_block(int(frame_type), int(link), int(want_level), int(msg_id), d, o, int(hops), life, _byte_p(out))  # made
    return out[:got] if got >= 0 else None  # the bits, or Python decides


def read_address_block(frame_type, bits):  # frame.py _read_address_block
    """Return the fields of an address block, or None."""
    if _lib is None or len(bits) < (28 if frame_type == 0 else 120):  # no library, or too short
        return None  # Python
    fields = _Fields()  # room
    return fields if _lib.kes_read_address_block(int(frame_type), _byte_p(_bits(bits)), ctypes.byref(fields)) == 0 else None  # the fields, or Python decides


def levels_mask(levels):  # control.py levels_to_bits, as a number
    """Return the level list as a number (bit n for level n), or None."""
    if _lib is None:  # no library
        return None  # Python
    levels = list(levels)  # however it was given
    if not _whole(*levels):  # not whole numbers
        return None  # Python
    arr, ptr = _longs(levels)  # as longs
    got = _lib.kes_levels_mask(ptr, len(arr))  # the mask
    return got if got >= 0 else None  # or Python decides


def pack_control(frame_type, **values):  # control.py pack_beacon, pack_answer, pack_ack, pack_ident, pack_notice
    """Return a control frame's body bits from its named fields, or None."""
    if _lib is None:  # no library
        return None  # Python
    fields = _Fields()  # all zero
    for name, value in values.items():  # each field given
        if name in ("origin", "dest", "grid"):  # text
            text = _ascii(value, 4 if name == "grid" else 9)  # as bytes
            if text is None:  # not something the library takes
                return None  # Python
            setattr(fields, name, text)  # stored
        elif name == "report":  # a channel report
            try:  # its readings must be numbers
                fields.snr_db, fields.fade_index, fields.offset_hz = float(value.snr_db), float(value.fade_index), float(value.offset_hz)  # stored
            except (TypeError, ValueError, OverflowError, AttributeError):  # they are not
                return None  # Python
            if not _whole(value.want_level):  # the level must be whole
                return None  # Python
            fields.want_level = int(value.want_level)  # stored
        elif name == "levels":  # the level list
            mask = levels_mask(value)  # as a number
            if mask is None:  # refused
                return None  # Python
            fields.levels = mask  # stored
        elif name in ("held", "receipts", "heard"):  # a mail notice list
            codes = [int(code) for code in value][:3]  # at most three (as Python converts them)
            if not _whole(*codes):  # too large for the library
                return None  # Python
            getattr(fields, name)[:len(codes)] = codes  # stored
            setattr(fields, "n" + name, len(codes))  # and how many
        elif name in ("listening", "mail_check", "holds_mail", "wide", "directed", "final_flag"):  # a flag
            flag = int(value)  # as Python converts it
            if flag not in (0, 1):  # anything else is left to Python
                return None  # Python
            setattr(fields, name, flag)  # stored
        else:  # a number
            if not _whole(value):  # not a whole number
                return None  # Python
            setattr(fields, name, int(value))  # stored
    out = np.zeros(192, dtype=np.uint8)  # room for the longest
    got = _lib.kes_pack_control(int(frame_type), ctypes.byref(fields), _byte_p(out))  # packed
    return out[:got] if got >= 0 else None  # the bits, or Python decides


def unpack_control(frame_type, bits):  # control.py unpack
    """Return the fields of a control frame's body bits, or None."""
    if _lib is None or not _whole(frame_type):  # no library
        return None  # Python
    b = _bits(bits)  # as bytes
    fields = _Fields()  # room
    return fields if _lib.kes_unpack_control(int(frame_type), _byte_p(b), len(b), ctypes.byref(fields)) == 0 else None  # the fields, or Python decides


# ---- The mail store (interface 9) ----

_ERRORS = {"ValueError": ValueError, "RuntimeError": RuntimeError, "TypeError": TypeError, "AttributeError": AttributeError, "KeyError": KeyError}  # the library's error names


class CompiledMail:  # the library's mail store (link/mail.py builds its Mailroom on this when the library is in use)
    """A handle on one mail store inside the library; request() runs one Mailroom method there."""

    def __init__(self):  # a new, empty store
        self._handle = _lib.kes_mail_new()  # made in the library
        self._lib = _lib  # kept, so the store can be freed even if the library is later switched off (as the tests do)
        self._lock = __import__("threading").Lock()  # one request-and-reply at a time from Python (the panel saves the mail from its own thread)

    def __del__(self):  # freed with this object
        if getattr(self, "_handle", None):  # made
            self._lib.kes_mail_free(self._handle)  # freed
            self._handle = None  # once

    def request(self, op, args=(), now=0.0):  # run one method
        """Return what the store's method `op` returns for `args` at time `now`, or raise the error Python's Mailroom would."""
        import json  # requests and replies are JSON
        text = json.dumps({"op": op, "args": list(args), "now": now}, default=lambda v: v.item() if hasattr(v, "item") else list(v))  # the request (NumPy numbers and tuples made plain)
        with self._lock:  # the request and its reply together
            length = self._lib.kes_mail_request(self._handle, text.encode("utf-8"), float(now))  # run
            if length < 0:  # refused outright
                raise RuntimeError("the mail store refused the request")  # should not happen
            room = ctypes.create_string_buffer(length + 1)  # space for the reply
            self._lib.kes_mail_reply(self._handle, room, length + 1)  # collected
        reply = json.loads(room.raw[:length].decode("utf-8"))  # read
        if "error" in reply:  # the method raised
            raise _ERRORS.get(reply["error"], RuntimeError)(reply.get("message", ""))  # the same kind of error
        return reply["ok"]  # the answer


def compiled_mail():  # a store, when the library is in use
    """Return a new CompiledMail, or None when the library is not in use."""
    return CompiledMail() if _lib is not None else None  # one store


# ---- One station's link rules (interface 10) ----


class CompiledStationCore:  # the library's station (link/station.py builds its CompiledStation on this)
    """A handle on one station inside the library; request() runs one of its methods there."""

    def __init__(self):  # a new station
        self._handle = _lib.kes_station_new()  # made in the library
        self._lib = _lib  # kept for freeing
        self._busy = None  # the ctypes callback in use (kept alive while the library holds it)
        self._lock = __import__("threading").RLock()  # one request-and-reply at a time from Python (the panel reads the station from its own thread; re-entrant for the listen-first check)

    def __del__(self):  # freed with this object
        if getattr(self, "_handle", None):  # made
            self._lib.kes_station_free(self._handle)  # freed
            self._handle = None  # once

    def set_mail(self, store):  # the mail store the station uses
        self._lib.kes_station_set_mail(self._handle, store._handle)  # handed over (the caller keeps it alive)

    def set_busy(self, check):  # the listen-before-transmit check (a Python callable taking a level), or None
        self._busy = _BUSY(check) if check is not None else _BUSY()  # wrapped for C (a null pointer for none)
        self._lib.kes_station_set_busy(self._handle, self._busy, None)  # handed over

    def request(self, op, args=(), mail_now=0.0):  # run one method
        """Return (answer, clear_stored) for the station's method `op`, or raise the error Python's Station would."""
        import json  # requests and replies are JSON
        text = json.dumps({"op": op, "args": list(args), "mail_now": mail_now}, default=_plain)  # the request
        with self._lock:  # the request and its reply together
            length = self._lib.kes_station_request(self._handle, text.encode("utf-8"))  # run
            if length < 0:  # refused outright
                raise RuntimeError("the station refused the request")  # should not happen
            room = ctypes.create_string_buffer(length + 1)  # space for the reply
            self._lib.kes_station_reply(self._handle, room, length + 1)  # collected
        reply = json.loads(room.raw[:length].decode("utf-8"))  # read
        if "error" in reply:  # the method raised
            raise _ERRORS.get(reply["error"], RuntimeError)(reply.get("message", ""))  # the same kind of error
        return reply["ok"], reply.get("clear_stored", False)  # the answer, and whether the receiver's kept soft bits go


def _plain(value):  # JSON for values json.dumps does not know
    """Return NumPy numbers as Python numbers, NumPy arrays and tuples and sets as lists, records as dicts."""
    if hasattr(value, "item") and getattr(value, "ndim", 1) == 0:  # a NumPy number
        return value.item()  # as a Python number
    if hasattr(value, "tolist"):  # a NumPy array
        return value.tolist()  # as a list
    if isinstance(value, (set, frozenset, tuple)):  # a set or tuple
        return list(value)  # as a list
    if hasattr(value, "__dataclass_fields__"):  # a record (a ChannelReport)
        return {name: getattr(value, name) for name in value.__dataclass_fields__}  # as a dict
    raise TypeError(f"cannot send {type(value).__name__} to the library")  # anything else


def compiled_station():  # a station, when the library is in use
    """Return a new CompiledStationCore, or None when the library is not in use."""
    return CompiledStationCore() if _lib is not None else None  # one station
