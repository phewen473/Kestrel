"""The long beacon: a compact, slow frame for being heard at the edge of what the path allows (signal version 0.27).

A normal beacon (31 seconds at L0) is heard down to about -21 dB on a steady
path. The long beacon trades everything but the essentials for reach: it
carries only the callsign, the four-character grid and two flags, and it
has no header, because its own twelve-tone pattern says what it is. That
leaves room in about a minute for tones three times as long as L0's:

    preamble (12 tones, the long pattern) | body (36 data tones with 3 pilots)

    51 tones x 1.167 s = 59.5 s, 32 tones 2.57 Hz apart (about 82 Hz wide), centred near 1500 Hz.

The body is 66 field bits (callsign 48, grid 15, available 1, holds mail 1,
spare 1) and a CRC-16, coded with the same K=7 rate-1/2 convolutional code
as the header and the control frames, shuffled and sent as 5-bit tones with
a pilot before every 15 data tones, exactly as a control frame's body.

A long beacon asks for nothing: no station answers it. Receiving stations
show it to their operator (spec Section 6.13).
"""

import re  # checks a decoded callsign's shape
from dataclasses import dataclass  # simple record type
from itertools import combinations  # every choice of a few copies

import numpy as np  # numerical arrays
from scipy.fft import next_fast_len  # finds a nearby length the transform handles quickly

from .address import bits_to_call, call_to_bits  # callsign <-> bits
from .control import bits_to_grid, grid_to_bits  # grid locator <-> bits
from .crc import crc16  # the body's check value
from .fec import TAIL, conv_encode, viterbi_decode  # the convolutional code
from .interleave import deinterleave, interleave  # bit shuffler
from .levels import Level  # one level's numbers
from .mfsk import band_energies, bits_to_symbols, energies_to_llrs, known_tone_energies, noise_level, noise_profile, pilot_frequency_fit, signal_report, symbols_to_audio, tone_energies  # the tone waveform
from .params import BODY_CRC_BITS, CALL_BITS, CENTRE_HZ, FRAME_TYPE_LONG, FS, GRID_BITS, LONG_LEVEL, LONG_SAMPLES, LONG_STEP, PREAMBLE_TONES, REF_BANDWIDTH_HZ  # the numbers that define it
from .preamble import detect_preamble, make_preamble  # its twelve-tone pattern

LONG = Level(LONG_LEVEL, LONG_SAMPLES, LONG_STEP)  # the long beacon's tone length and spacing, as a level
FIELD_BITS = CALL_BITS + GRID_BITS + 3  # callsign, grid and three flag bits (available, holds mail, spare)
CALL_SHAPE = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](/[A-Z0-9]{1,4})?$")  # the shape of an amateur callsign: what passes the check value must also look like one (noise that passes the 16-bit check almost never does, which matters when many combinations of copies are tried)
CLEAN_HALF_HZ = 100.0  # carriers are looked for this far either side of 1500 Hz (the beacon's 82 Hz, the 50 Hz of frequency error allowed, and a margin)
CARRIER_TIMES = 4.0  # a frequency whose quietest-tenth energy is this many times the band's is a steady carrier (plain noise stays under 2)
CARRIER_MOST = 12  # more occupied bins than this (about 10 Hz in all) is not a few carriers, and nothing is removed
NOTCH_HALF_HZ = 0.65  # half the width of the notch that removes a carrier, in hertz (three quarters of a bin)
BUSY_TONE = 2.0  # a tone position whose typical energy is this many times the band's is treated as occupied by something else, and its energies are scaled down to match the rest 
OFFSET_MATCH_HZ = 3.0  # copies are combined only when their audio frequencies agree this closely
COMBINE_KEEP_S = 2700.0  # a copy that did not decode is kept this long (45 minutes: four rounds at the shortest interval)
COMBINE_APART_S = 120.0  # copies closer in time than this are the same transmission found twice, not a repeat
COMBINE_MOST = 4  # at most this many copies are added together
COMBINE_PARTNERS = 6  # a new copy is tried with at most this many kept copies (the clearest on its frequency)
COMBINE_MEMORY = 200  # at most this many copies are kept
MIN_SNR_DB = -25.6  # weakest SNR (2.5 kHz, noise only) at which every test long beacon decoded (40 a point, 21 November 2026; nine in ten at -26.6, nine in ten at -18.6 in the worst fading)


def _layout():  # the body's shape
    """Return the body layout: the same rules as a control frame's body (frame._layout)."""
    from .frame import _layout as layout  # imported here: frame.py imports this module
    info = FIELD_BITS + BODY_CRC_BITS  # the fields and their check
    return layout(info, 2 * (info + TAIL))  # the convolutional code doubles the bits, after six tail bits


LAYOUT = _layout()  # worked out once
TOTAL_TONES = PREAMBLE_TONES + LAYOUT["total"]  # tones in the whole frame (51)
SECONDS = TOTAL_TONES * LONG.seconds  # its airtime (59.5 s)
SAMPLES = TOTAL_TONES * LONG.samples  # and in samples


def pack(call, grid, available=True, holds_mail=False):  # fields -> bits
    """Return the 66 field bits of a long beacon."""
    flags = np.array([int(bool(available)), int(bool(holds_mail)), 0], dtype=np.uint8)  # available, holds mail, spare
    return np.concatenate([call_to_bits(call), grid_to_bits(grid), flags])  # callsign, grid, flags


def unpack(bits):  # bits -> fields
    """Return the fields of a long beacon as a dict: origin, grid, available, holds_mail."""
    rest = bits[CALL_BITS:]  # after the callsign
    return {"origin": bits_to_call(bits[:CALL_BITS]), "grid": bits_to_grid(rest[:GRID_BITS]), "available": bool(rest[GRID_BITS]), "holds_mail": bool(rest[GRID_BITS + 1]), "long": True}  # the fields


def build_long_beacon(call, grid, available=True, holds_mail=False):  # the transmitter
    """Return the audio of a long beacon from `call` at `grid`."""
    fields = pack(call, grid, available, holds_mail)  # the fields
    data = np.concatenate([fields, crc16(fields)])  # and their check value
    coded = conv_encode(data)  # error correction
    coded = np.concatenate([coded, np.zeros(LAYOUT["padded"] - LAYOUT["coded"], dtype=np.uint8)])  # round up to whole tones
    body = np.zeros(LAYOUT["total"], dtype=np.int64)  # room for every body tone
    body[LAYOUT["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    body[LAYOUT["pilot_pos"]] = LAYOUT["pilot_tones"]  # known tones in the pilot positions
    return np.concatenate([make_preamble(LONG), symbols_to_audio(body, LONG)])  # the long pattern, then the body


def clean(x):  # take steady carriers out of the long beacon's band
    """Return `x` with any steady carrier near the long beacon's tones removed (and `x` itself when there is none).

    A carrier is on its frequency all the time; a beacon's tone is there
    for a second or so. So a frequency that even in its quietest tenth of
    the time stands CARRIER_TIMES above the rest of the band is a carrier,
    and it is cut out with a notch a little over one hertz wide. Left in,
    even a carrier between two tone positions spills into all of them.
    """
    n = LONG.samples  # one tone length
    blocks = len(x) // n  # whole tone lengths in the audio
    if blocks < 8:  # too little audio to tell steady from brief
        return x  # leave it
    low, high = int((CENTRE_HZ - CLEAN_HALF_HZ) / LONG.bin_hz), int((CENTRE_HZ + CLEAN_HALF_HZ) / LONG.bin_hz)  # the bins from 100 Hz below the centre to 100 Hz above
    power = np.abs(np.fft.rfft(x[:blocks * n].reshape(blocks, n), axis=1)[:, low:high]) ** 2  # the energy in each bin, tone length by tone length
    typical = np.percentile(power, 10, axis=0)  # each bin's energy in its quietest tenth of the time: high only if something is there nearly all the time
    busy = np.flatnonzero(typical > CARRIER_TIMES * np.median(typical))  # bins that are occupied all the time
    if len(busy) == 0 or len(busy) > CARRIER_MOST:  # no carrier; or so many bins that it is no carrier but a strong signal (a strong beacon spills a little into every bin), which needs no help
        return x  # nothing to do
    size = next_fast_len(len(x), real=True)  # a length the transform handles quickly
    spectrum = np.fft.rfft(x, size)  # the whole audio at once: very fine frequency steps
    per_hz = size / FS  # steps of that transform per hertz
    for number in busy:  # each occupied bin
        centre = (low + number) * LONG.bin_hz  # its frequency
        spectrum[int((centre - NOTCH_HALF_HZ) * per_hz):int((centre + NOTCH_HALF_HZ) * per_hz) + 1] = 0.0  # cut it out
    return np.fft.irfft(spectrum, size)[:len(x)]  # back to audio


def candidates(x, keep=3):  # where long beacons may start
    """Return the long pattern's best candidates in `x` (as preamble.detect_preamble)."""
    return detect_preamble(x, LONG, keep=keep, whiten=True)  # the same search as every level, with the long pattern and tone length, and the band levelled first (a carrier inside 82 Hz would otherwise swamp it)


@dataclass  # a plain record
class Soft:  # what the receiver measured of one long-beacon candidate, kept so repeats can be combined
    """The body of one candidate, as energies: enough to decode it, alone or added to other copies of the same beacon."""

    energies: np.ndarray  # energy in each of the 32 tone positions for each of the 39 body tones, divided by the noise level (so copies heard at different strengths can be added)
    offset_hz: float  # the candidate's frequency offset at the start of the body
    drift_hz_s: float  # and its drift
    quality: float  # how far the pattern stood above the background
    pilot_snr_db: float  # SNR read from the three pilots alone (rough)
    sample: int = -1  # where the candidate began in a continuous stream (set by live.Listener)
    when: float = 0.0  # when it was heard, in seconds (set by whoever keeps the copies)


def soft_at(x, found):  # measure one candidate's body
    """Return a Soft for the candidate `found` in `x`, or None when its body is not all inside `x` yet."""
    body_start = int(found["start"]) + PREAMBLE_TONES * LONG.samples  # the body follows the pattern
    if body_start + LAYOUT["total"] * LONG.samples > len(x) + LONG.samples // 4:  # not all here yet
        return None  # look again later
    extra, drift = pilot_frequency_fit(x, body_start, LAYOUT["pilot_pos"], LAYOUT["pilot_tones"], LONG, found["offset_hz"])  # fine frequency and drift from the pilots
    offset = found["offset_hz"] + extra  # best estimate of the offset
    band = band_energies(x, body_start, LAYOUT["total"], LONG, offset, drift)  # every bin of the tone band, every body tone
    tone_e = tone_energies(band, LONG)  # the 32 tone positions
    noise = noise_level(tone_e)  # noise energy per tone position
    own = np.median(tone_e, axis=0) / np.log(2) / noise  # each tone position's own typical level, against the whole band's (about 1 in plain noise; a beacon's tone visits a position too briefly to raise it)
    weight = np.where(own > BUSY_TONE, own, 1.0)  # positions with a steady carrier or other signal on them are counted in units of their own level, so they cannot outvote the beacon
    ratio, _ = signal_report(known_tone_energies(band[LAYOUT["pilot_pos"]], LAYOUT["pilot_tones"], LONG), noise)  # a first reading from the pilots
    pilot_snr = 10 * np.log10(max(ratio, 1e-12) / (LONG.seconds * REF_BANDWIDTH_HZ))  # in 2.5 kHz
    return Soft(tone_e / noise_profile(tone_e)[:, None] / weight, float(offset), float(drift), float(found["quality"]), float(pilot_snr))  # energies in units of the noise


def body_tones(data):  # the tones a body's bits are sent as
    """Return the 39 tone numbers of the body carrying `data` (fields and check value)."""
    coded = conv_encode(data)  # error correction
    coded = np.concatenate([coded, np.zeros(LAYOUT["padded"] - LAYOUT["coded"], dtype=np.uint8)])  # round up to whole tones
    tones = np.zeros(LAYOUT["total"], dtype=np.int64)  # room for every body tone
    tones[LAYOUT["data_pos"]] = bits_to_symbols(interleave(coded))  # shuffled data bits become the data tones
    tones[LAYOUT["pilot_pos"]] = LAYOUT["pilot_tones"]  # known tones in the pilot positions
    return tones  # pilots and data tones, in sending order


def decode_energies(energies):  # energies -> fields
    """Decode a body from its tone energies (one copy's, or several copies' added together).

    Returns (fields, margin_db): the fields as a dict, or None when the
    check fails or the bits are not a long beacon; and how far the tones
    the decoded beacon would have used stand above the noise, in dB per
    tone (the same measure whatever number of copies was added).
    """
    llrs = deinterleave(energies_to_llrs(energies[LAYOUT["data_pos"]], 1.0))[:LAYOUT["coded"]]  # soft bits in original order (the energies are already in units of the noise)
    data = viterbi_decode(llrs)  # correct errors
    if not np.array_equal(crc16(data[:-BODY_CRC_BITS]), data[-BODY_CRC_BITS:]):  # the check must match
        return None, -99.0  # not a long beacon (or too damaged)
    try:  # the check passed, so this should work
        fields = unpack(data[:FIELD_BITS])  # the fields
    except ValueError:  # a damaged frame slipped past the check
        return None, -99.0  # give up on it
    if data[FIELD_BITS - 1] or not CALL_SHAPE.match(fields["origin"]):  # the spare bit must be 0, and the callsign must have the shape of one
        return None, -99.0  # noise that happened to pass the check
    tones = body_tones(data)  # every tone the beacon used
    used = energies[np.arange(LAYOUT["total"]), tones]  # the energy found in each of them (signal plus noise, in units of the noise)
    copies = float(np.median(energies)) / np.log(2)  # how many copies were added (the noise floor of the sum)
    margin = 10 * np.log10(max(float(np.mean(used)) / copies - 1.0, 1e-6))  # signal energy per tone against the noise, per copy
    return fields, margin  # the beacon, and how clearly it stood out


def decode_at(x, found, result, failed=None):  # read one candidate's body
    """Fill in `result` (an RxResult started for the candidate `found`) from the long beacon's body; return it.

    `failed`, if a list, receives the candidate's Soft when its body was
    all there but did not decode, so the caller can combine it with other
    copies of the same beacon (see LongCombiner).
    """
    result.level, result.frame_type, result.header_copy = LONG_LEVEL, FRAME_TYPE_LONG, "none (long beacon)"  # what it is
    soft = soft_at(x, found)  # measure the body
    if soft is None:  # not all here yet
        result.reason = "frame incomplete"  # say why
        return result  # look again later
    result.offset_hz, result.drift_hz_s, result.snr_db = soft.offset_hz, soft.drift_hz_s, soft.pilot_snr_db  # what is known so far
    fields, margin = decode_energies(soft.energies)  # try to read it
    if fields is None:  # the check failed
        result.reason = "body check failed"  # say why
        if failed is not None:  # the caller combines copies
            failed.append((found, soft))  # hand this one over
        return result  # not readable alone
    _fill(result, fields, margin)  # the finished report
    return result  # a long beacon


def _fill(result, fields, margin_db, copies=1):  # complete a report from decoded fields
    """Put the decoded `fields` and the signal reading into `result`."""
    result.fields = dict(fields, copies=copies)  # the fields, and how many copies it took
    result.origin = fields["origin"]  # the sender, where every frame keeps it
    result.ok, result.reason = True, ""  # success
    result.snr_db = margin_db - 10 * np.log10(LONG.seconds * REF_BANDWIDTH_HZ)  # energy per tone over noise density -> SNR in 2.5 kHz
    result.fade_index = float("nan")  # too few tones for a fading reading worth giving


class LongCombiner:  # adds up copies of the same long beacon heard minutes apart
    """Keep the measurements of long beacons that did not decode, and try them together.

    A station repeats the same long beacon every ten minutes or more. Two
    copies that each fail can decode when their tone energies are added:
    the signal adds up in the same tones each time and the noise does not.
    Copies are tried together only when their audio frequencies agree
    within OFFSET_MATCH_HZ (a station's signal comes back on nearly the
    same frequency), which also keeps unrelated noise from being combined.
    """

    def __init__(self, keep_s=COMBINE_KEEP_S, most=COMBINE_MOST):  # set up an empty memory
        self.keep_s = keep_s  # how long a copy is kept
        self.most = most  # the most copies added together
        self.kept = []  # the copies kept, oldest first

    def offer(self, soft, now):  # a new copy that did not decode alone
        """Add `soft` (heard at time `now`, seconds) and try it with the copies kept. Return (fields, margin_db, copies used) on success, else None."""
        soft.when = now  # note when
        self.kept = [old for old in self.kept if now - old.when <= self.keep_s]  # forget copies too old
        partners = [old for old in self.kept if abs(old.offset_hz - soft.offset_hz) <= OFFSET_MATCH_HZ and now - old.when >= COMBINE_APART_S]  # copies on the same frequency, from an earlier transmission
        partners = sorted(partners, key=lambda old: -old.quality)[:COMBINE_PARTNERS]  # the clearest few
        best = None  # the best decode found
        for count in range(1, self.most):  # with one earlier copy, then two, then three
            for group in combinations(partners, count):  # every choice of that many
                if any(abs(a.when - b.when) < COMBINE_APART_S for a, b in combinations(group, 2)):  # two of them are the same transmission found twice
                    continue  # not a real pair
                fields, margin = decode_energies(soft.energies + sum(old.energies for old in group))  # add the energies and try
                if fields is not None and (best is None or margin > best[1]):  # it decodes
                    best = (fields, margin, (soft,) + group)  # keep the clearest
            if best is not None:  # decoded with this many: no need for more
                break  # done
        if best is None:  # still not readable
            self.kept.append(soft)  # keep it for the next copy
            self.kept = self.kept[-COMBINE_MEMORY:]  # within the memory's size
            return None  # nothing yet
        self.kept = [old for old in self.kept if all(old is not used for used in best[2])]  # the copies used are done with
        return best[0], best[1], len(best[2])  # the beacon, its margin and how many copies it took
