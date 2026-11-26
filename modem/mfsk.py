"""The tone waveform: 32 tones, one tone at a time (MFSK), used by every speed level.

Tone signaling does not depend on the phase of the radio wave, which is
the first thing fading and multipath destroy. The receiver only asks
"which tone has the most energy?", so it keeps working in rough conditions.
"""

import numpy as np  # numerical arrays

from . import native  # the compiled library, used when present
from .params import BITS_PER_SYMBOL, FS, M_TONES, RAMP_S  # waveform numbers shared by all levels

GRAY = np.array([v ^ (v >> 1) for v in range(M_TONES)])  # Gray code (since signal version 0.32): the tone that carries each 5-bit value, so neighboring tones differ in one bit only
GRAY_VALUE = np.argsort(GRAY)  # the other way round: the 5-bit value each tone carries
_TONE_BITS = np.array([[(GRAY_VALUE[m] >> (BITS_PER_SYMBOL - 1 - j)) & 1 for j in range(BITS_PER_SYMBOL)] for m in range(M_TONES)])  # the 5 bits each tone stands for
_WEIGHTS = 1 << np.arange(BITS_PER_SYMBOL - 1, -1, -1)  # place values 16, 8, 4, 2, 1
PAD = 8  # zero-padding factor for fine frequency measurement (8x finer than one bin)
FINE_SPAN = 4  # fine search reaches 4 fine steps each side (plus or minus half a bin)


def bits_to_symbols(bits):  # coded bits -> tone numbers
    """Group `bits` in fives (padding with zeros) and return one tone number per group: the Gray code of the group's value (since 0.32)."""
    bits = np.asarray(bits, dtype=np.int64)  # work in whole numbers
    extra = (-len(bits)) % BITS_PER_SYMBOL  # zeros needed to fill the last group
    padded = np.concatenate([bits, np.zeros(extra, dtype=np.int64)])  # add them
    return GRAY[padded.reshape(-1, BITS_PER_SYMBOL) @ _WEIGHTS]  # each row of 5 bits becomes a number 0..31, sent as the tone its Gray code names


def symbols_to_audio(symbols, level):  # tone numbers -> sound
    """Return the audio for a run of tones at the given speed level, as one continuous-phase waveform.

    Each tone holds a whole number of cycles, so the phase never jumps. At
    a level with a glide (L3 and L4, since 0.32) the frequency moves from one
    tone to the next smoothly, along a raised-cosine curve centered on the
    boundary and `level.glide` of a tone long, which keeps the signal narrow.
    """
    freqs = level.tone_bins[np.asarray(symbols, dtype=np.int64)] * level.bin_hz  # frequency of every tone to send, in Hz
    f = np.repeat(freqs, level.samples).astype(float)  # the wanted frequency, sample by sample (sudden steps)
    glide = int(round(level.glide * level.samples))  # length of each glide, in samples
    if glide > 1 and len(f) > 0:  # a glide is wanted
        kernel = np.hanning(glide + 2)[1:-1]  # a smooth bump (raised cosine) without its zero end points
        kernel /= kernel.sum()  # scaled so the average frequency, and so the phase at each tone's center, is kept
        before = glide // 2  # padding needed before the start
        padded = np.concatenate([np.full(before, f[0]), f, np.full(glide - 1 - before, f[-1])])  # hold the first and last frequency at the ends
        f = np.convolve(padded, kernel, mode="valid")  # smooth the steps into glides (same length as before)
    phase = 2 * np.pi * np.concatenate([[0.0], np.cumsum(f[:-1])]) / FS  # running phase: the frequency added up, starting at zero
    return np.cos(phase)  # the waveform (without a glide, sample for sample the same as separate cosine bursts, since each tone holds whole cycles)


def fade_ends(audio):  # the start and end of a transmission
    """Return `audio` with a raised-cosine fade in and out of RAMP_S seconds at its two ends (since 0.32), so the transmission starts and stops without a click."""
    ramp = int(round(RAMP_S * FS))  # length of each fade, in samples
    if ramp < 2 or 2 * ramp > len(audio):  # too short to fade
        return audio  # as it is
    out = np.array(audio, dtype=float)  # a copy
    edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # smooth rise from 0 to 1
    out[:ramp] *= edge  # fade in
    out[-ramp:] *= edge[::-1]  # fade out
    return out  # the audio


def transmission(symbols, level):  # a whole frame's tones -> its sound
    """Return the audio of a complete frame (preamble, header, body, header) from all its tone numbers: one continuous waveform with faded ends."""
    return fade_ends(symbols_to_audio(symbols, level))  # one waveform, then the fades


def _mixed_blocks(x, start, nsym, level, offset_hz, drift_hz_s):  # cut out tones and correct their frequency
    """Return `nsym` tone-length blocks from `x`, shifted down by the frequency error."""
    first = int(round(start))  # first sample of the first tone
    need = nsym * level.samples  # samples required for all the tones
    seg = x[max(first, 0):first + need]  # the part of the recording that holds them
    if first < 0:  # the frame starts before the recording does
        seg = np.concatenate([np.zeros(-first), seg])  # fill the missing start with silence
    if len(seg) < need:  # the recording ends early
        seg = np.concatenate([seg, np.zeros(need - len(seg))])  # fill the missing end with silence
    t = np.arange(need) / FS  # time of every sample, counted from the first tone
    mixer = np.exp(-2j * np.pi * (offset_hz * t + 0.5 * drift_hz_s * t * t))  # spinning correction that cancels offset and drift
    return (seg * mixer).reshape(nsym, level.samples)  # corrected audio, one row per tone


def band_energies(x, start, nsym, level, offset_hz=0.0, drift_hz_s=0.0):  # measure the whole tone band, bin by bin
    """Return the energy in every FFT bin from one bin below the lowest tone to one bin above the highest, one row per symbol.

    Column 1 is the lowest tone; tone m sits in column 1 + m * level.step.
    The bins beside each tone are kept because fast fading smears part of
    a tone's energy into them.
    """
    lo, hi = level.tone_bins[0] - 1, level.tone_bins[-1] + 1  # the band kept: one bin below the lowest tone to one above the highest
    done = native.band_energies(x, start, nsym, level.samples, offset_hz, drift_hz_s, lo, hi)  # the compiled version, when the library is in use
    if done is not None:  # it was
        return done  # the same energies, to within rounding
    spec = np.fft.fft(_mixed_blocks(x, start, nsym, level, offset_hz, drift_hz_s), axis=1)  # spectrum of each tone-length block
    return np.abs(spec[:, level.tone_bins[0] - 1:level.tone_bins[-1] + 2]) ** 2  # keep only the band the tones occupy, plus one bin each side


def tone_energies(band, level):  # pick the 32 tone positions out of the band
    """Return the energy in each of the 32 tone positions, one row per symbol, from the output of band_energies."""
    return band[:, 1::level.step][:, :M_TONES]  # every step-th column, starting at the lowest tone


def symbol_energies(x, start, nsym, level, offset_hz=0.0, drift_hz_s=0.0):  # measure every tone slot
    """Return the energy in each of the 32 tone positions, one row per symbol."""
    return tone_energies(band_energies(x, start, nsym, level, offset_hz, drift_hz_s), level)  # measure the band, keep the tone positions


def known_tone_energies(band, tones, level):  # energy of tones we know were sent
    """Return, for each symbol, the energy at the tone that was sent plus the bin on each side of it.

    `tones` holds the tone number sent in each row of `band`. Adding the
    two neighboring bins collects the energy that fast fading or a small
    frequency error moved off the tone itself.
    """
    first = np.asarray(tones) * level.step  # column of the bin just below each sent tone
    rows = np.arange(len(first))  # one row per symbol
    return band[rows, first] + band[rows, first + 1] + band[rows, first + 2]  # the bin below, the tone, the bin above


def signal_report(known_e, noise):  # turn known-tone energies into SNR and a fading figure
    """Return (signal-to-noise ratio per tone, fading index) from the energies of known tones.

    `known_e` comes from known_tone_energies and `noise` from noise_level.
    The fading index is 0 for a steady signal and about 1 for a signal
    that fades deeply and often during the frame. It is the spread of the
    tone energies, beyond what the noise alone would cause, compared with
    their average.
    """
    signal = float(np.mean(known_e)) - 3 * noise  # average signal energy: three bins were added, so three bins of noise come off
    if signal <= 0.05 * noise:  # no measurable signal
        return 0.0, float("nan")  # report nothing useful
    noise_spread = 2 * signal * noise + 3 * noise * noise  # how much the energies would vary from noise alone
    extra = float(np.var(known_e)) - noise_spread  # variation left over, which is fading
    return signal / noise, max(extra, 0.0) / (signal * signal)  # the ratio, and the fading index (never negative)


def _smear_table():  # Doppler spread (as a Gaussian width in bins) -> the share of a tone's energy found in the bins beside it
    """Return (widths, shares): for a tone held one symbol and spread by a Gaussian Doppler spectrum of standard deviation `width` bins,
    the expected share of its energy in the two neighboring bins out of the three. Worked out once, by numerical integration."""
    widths = np.concatenate([[0.0], np.geomspace(0.01, 3.0, 120)])  # from none to three bins
    u = np.linspace(-40.0, 40.0, 16001)  # frequency in bins, finely
    shares = [0.0]  # no spread: nothing beside the tone
    for s in widths[1:]:  # each width
        psd = np.exp(-u ** 2 / (2 * s * s))  # the spread spectrum
        e = [float(np.sum(psd * np.sinc(u - k) ** 2)) for k in (-1, 0, 1)]  # energy each bin collects (a one-symbol transform sees a sinc squared)
        shares.append((e[0] + e[2]) / sum(e))  # the share beside the tone
    return widths, np.array(shares)  # the table


_SMEAR_WIDTHS, _SMEAR_SHARES = _smear_table()  # made once, when the modem is loaded
GLIDE_SHARE = {3: 0.0034, 4: 0.0031}  # L3 and L4 glide between tones (since 0.32), which itself leaves this share of each tone's energy beside it on a steady path (measured with tools/spread_check.py); it is taken off before the spread is read
SPREAD_TRUST = 30.0  # a spread reading needs the known tones' signal to add up to 30 times one bin's noise, or it is not given


def tone_spread(band, tones, level, noise):  # how far known tones were smeared (since 0.35)
    """Return (Doppler spread in Hz, share of the signal beside the tones, leftover frequency error in Hz) for known tones.

    `band` comes from band_energies, `tones` holds the tone sent in each row
    and `noise` the noise energy per bin (one value, or one per row). The
    spread is read from how much of each tone's energy fell into the bins
    beside it, against what a Gaussian Doppler spectrum of each width would
    leave there (spread = twice the standard deviation, as ITU-R F.1487
    measures it). It is NaN when the signal is too weak to tell.
    """
    done = native.tone_spread(band, tones, level.step, noise)  # the compiled version (since ABI 14)
    if done is None:  # not in use: the same sums in Python
        first = np.asarray(tones) * level.step  # column of the bin just below each tone
        rows = np.arange(len(first))  # one row per symbol
        n = np.broadcast_to(np.asarray(noise, dtype=float), (len(first),))  # noise per row
        own = float(np.sum(band[rows, first + 1] - n))  # the tones' own bins, less noise
        side = float(np.sum(band[rows, first] + band[rows, first + 2] - 2 * n))  # their neighbors, less noise
        lean = float(np.sum(band[rows, first + 2] - band[rows, first]))  # above minus below
        total = own + side  # the signal found
        done = (min(max(side / total, 0.0), 1.0) if total > 0 else -1.0, lean / total if total > 0 else 0.0, total / float(np.sum(n)) if np.sum(n) > 0 else 0.0)  # as the library gives them
    share, lean, trust = done  # the three readings
    if share < 0 or trust < SPREAD_TRUST:  # nothing worth reporting
        return float("nan"), float("nan"), float("nan")  # unknown
    base = GLIDE_SHARE.get(level.number, 0.0)  # what the level's own glides between tones leave beside them on a steady path
    width = float(np.interp(max(share - base, 0.0) / (1.0 - base), _SMEAR_SHARES, _SMEAR_WIDTHS))  # the Gaussian width that leaves the rest of that share beside the tones
    return 2.0 * width * level.bin_hz, share, lean * level.bin_hz / 2.0  # spread in Hz, the share, and roughly how far off the tones sat


def noise_level(tone_e):  # how strong the background noise is
    """Return the average noise energy per tone position.

    In every symbol 31 of the 32 positions hold only noise, so the middle
    value (median) of all the energies is set by the noise, not the signal.
    """
    floor = 1e-12 * float(tone_e.max()) + 1e-300  # a tiny floor tied to the strongest energy, so the result is never zero
    return max(float(np.median(tone_e)) / np.log(2), floor)  # median of noise energy is ln(2) times its average


NOISE_SPAN = 8  # the noise level at each tone is taken from that tone and this many either side of it
NOISE_TRACKING = True  # whether the receiver follows the noise level through a frame (False: one level for the whole frame, as before version 0.28; kept for comparison studies)


def noise_profile(tone_e, span=NOISE_SPAN):  # how strong the background noise is, tone by tone through the frame
    """Return the noise energy per tone position at each symbol of `tone_e` (symbols x 32), following slow changes.

    Band noise is not steady: static builds and dies away, and a
    receiver's own gain control moves the noise up and down. Each symbol's
    level is the middle value of the energies in it and its `span`
    neighbors each side (31 of every 32 positions hold only noise, so the
    signal does not disturb it), never less than a tenth of the level of
    the whole frame.
    """
    done = native.noise_profile(tone_e, span, NOISE_TRACKING)  # the compiled version, when the library is in use
    if done is not None:  # it was
        return done  # the same levels as the Python below
    whole = noise_level(tone_e)  # the level over the whole frame
    if not NOISE_TRACKING or tone_e.shape[0] < 2 * span + 1:  # tracking is off, or the frame is too short to track within
        return np.full(tone_e.shape[0], whole)  # one level throughout
    padded = np.concatenate([tone_e[span:0:-1], tone_e, tone_e[-2:-span - 2:-1]])  # mirrored at each end, so the first and last symbols have neighbors too
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * span + 1, axis=0)  # each symbol with its neighbors: symbols x 32 x (2 * span + 1)
    local = np.median(windows.reshape(tone_e.shape[0], -1), axis=1) / np.log(2)  # the middle value of each group, as an average noise energy
    return np.maximum(local, 0.1 * whole)  # never wildly below the frame's own level


def energies_to_llrs(tone_e, noise_level):  # tone energies -> soft bits
    """Return 5 soft bits per symbol (positive = probably 0, negative = probably 1)."""
    llrs = np.zeros((tone_e.shape[0], BITS_PER_SYMBOL))  # room for 5 soft bits per symbol
    for j in range(BITS_PER_SYMBOL):  # one bit position at a time
        zero = tone_e[:, _TONE_BITS[:, j] == 0].max(axis=1)  # strongest tone whose bit j is 0
        one = tone_e[:, _TONE_BITS[:, j] == 1].max(axis=1)  # strongest tone whose bit j is 1
        llrs[:, j] = (zero - one) / noise_level  # the difference, scaled by the noise, is the confidence
    return llrs.reshape(-1)  # flatten to one long run of soft bits


def pilot_frequency_fit(x, start, positions, tones, level, offset_hz, backward=False):  # track drift using the known pilot tones
    """Return (extra offset at the first symbol in Hz, drift in Hz per second) measured from the pilots.

    The pilots are handled in stretches of about eight. Each stretch is
    searched around where the previous stretch found the signal, so the
    tracker follows a drifting signal step by step.

    `offset_hz` is the frequency error measured from the pattern the frame
    was found by. For a frame found from the pattern at its end (since
    signal version 0.43) that is the error at the END of the body, so
    with `backward` the stretches are followed from the last to the first
    and a drifting signal is tracked back from where it was measured. The
    answer is the same either way: the extra offset at the first symbol,
    and the drift.
    """
    positions = np.asarray(positions)  # which symbols are pilots
    tones = np.asarray(tones)  # which tone each pilot used
    done = native.pilot_fit(x, start, positions, tones, level.samples, level.tone_bins, PAD, FINE_SPAN, offset_hz, backward)  # the compiled version, when the library is in use
    if done is not None:  # it was
        return done  # the same fit, to rounding
    groups = max(1, len(positions) // 8)  # split the frame into stretches of about 8 pilots
    track = 0.0  # frequency error found so far, on top of the preamble's estimate
    times = []  # middle time of each stretch
    errors = []  # frequency error measured in each stretch
    stretches = np.array_split(np.arange(len(positions)), groups)  # the pilots shared out among the stretches
    for idx in (stretches[::-1] if backward else stretches):  # one stretch at a time: in order, or last to first when the frequency was measured at the frame's end
        avg = np.zeros(2 * FINE_SPAN + 1)  # running sum of fine spectra for this stretch
        for pos, tone in zip(positions[idx], tones[idx]):  # look at every pilot in the stretch
            block = _mixed_blocks(x, start + pos * level.samples, 1, level, offset_hz + track, 0.0)[0]  # that pilot's audio, corrected by the best estimate so far
            spec = np.abs(np.fft.fft(block, PAD * level.samples)) ** 2  # fine-grained power spectrum
            center = level.tone_bins[tone] * PAD  # where the pilot should be on the fine grid
            avg += spec[center - FINE_SPAN:center + FINE_SPAN + 1]  # add the few fine steps either side
        peak = int(np.argmax(avg))  # fine step with the most energy
        frac = 0.0  # fraction-of-a-step correction
        if 0 < peak < len(avg) - 1:  # only if the peak has a neighbor on each side
            a, b, c = avg[peak - 1], avg[peak], avg[peak + 1]  # the peak and its neighbors
            bend = a - 2 * b + c  # how sharply they curve
            if bend != 0:  # a flat line has no top
                frac = 0.5 * (a - c) / bend  # top of the parabola through the three points
        track += (peak + frac - FINE_SPAN) * level.bin_hz / PAD  # move the estimate to where this stretch found the signal
        errors.append(track)  # record it
        times.append(positions[idx].mean() * level.seconds)  # and when this stretch happened
    if groups >= 2:  # with two or more stretches we can see a trend
        slope, intercept = np.polyfit(times, errors, 1)  # straight line through the measurements
        return float(intercept), float(slope)  # error at the start, and how fast it changes
    return float(errors[0]), 0.0  # one stretch only: a fixed correction, no drift
