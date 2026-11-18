"""The tone waveform: 32 tones, one tone at a time (MFSK), used by every speed level.

Tone signalling does not depend on the phase of the radio wave, which is
the first thing fading and multipath destroy. The receiver only asks
"which tone has the most energy?", so it keeps working in rough conditions.
"""

import numpy as np  # numerical arrays

from .params import BITS_PER_SYMBOL, FS, M_TONES  # waveform numbers shared by all levels

_TONE_BITS = np.array([[(m >> (BITS_PER_SYMBOL - 1 - j)) & 1 for j in range(BITS_PER_SYMBOL)] for m in range(M_TONES)])  # the 5 bits each tone stands for
_WEIGHTS = 1 << np.arange(BITS_PER_SYMBOL - 1, -1, -1)  # place values 16, 8, 4, 2, 1
PAD = 8  # zero-padding factor for fine frequency measurement (8x finer than one bin)
FINE_SPAN = 4  # fine search reaches 4 fine steps each side (plus or minus half a bin)


def bits_to_symbols(bits):  # coded bits -> tone numbers
    """Group `bits` in fives (padding with zeros) and return one tone number per group."""
    bits = np.asarray(bits, dtype=np.int64)  # work in whole numbers
    extra = (-len(bits)) % BITS_PER_SYMBOL  # zeros needed to fill the last group
    padded = np.concatenate([bits, np.zeros(extra, dtype=np.int64)])  # add them
    return padded.reshape(-1, BITS_PER_SYMBOL) @ _WEIGHTS  # each row of 5 bits becomes a number 0..31


def symbols_to_audio(symbols, level):  # tone numbers -> sound
    """Return the audio for a run of tones at the given speed level."""
    n = np.arange(level.samples)  # sample counter within one tone
    freqs = level.tone_bins[np.asarray(symbols)] * level.bin_hz  # frequency of every tone to send, in Hz
    return np.cos(2 * np.pi * freqs[:, None] * n[None, :] / FS).reshape(-1)  # one cosine burst per tone, joined end to end


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
    two neighbouring bins collects the energy that fast fading or a small
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


def noise_level(tone_e):  # how strong the background noise is
    """Return the average noise energy per tone position.

    In every symbol 31 of the 32 positions hold only noise, so the middle
    value (median) of all the energies is set by the noise, not the signal.
    """
    floor = 1e-12 * float(tone_e.max()) + 1e-300  # a tiny floor tied to the strongest energy, so the result is never zero
    return max(float(np.median(tone_e)) / np.log(2), floor)  # median of noise energy is ln(2) times its average


def energies_to_llrs(tone_e, noise_level):  # tone energies -> soft bits
    """Return 5 soft bits per symbol (positive = probably 0, negative = probably 1)."""
    llrs = np.zeros((tone_e.shape[0], BITS_PER_SYMBOL))  # room for 5 soft bits per symbol
    for j in range(BITS_PER_SYMBOL):  # one bit position at a time
        zero = tone_e[:, _TONE_BITS[:, j] == 0].max(axis=1)  # strongest tone whose bit j is 0
        one = tone_e[:, _TONE_BITS[:, j] == 1].max(axis=1)  # strongest tone whose bit j is 1
        llrs[:, j] = (zero - one) / noise_level  # the difference, scaled by the noise, is the confidence
    return llrs.reshape(-1)  # flatten to one long run of soft bits


def pilot_frequency_fit(x, start, positions, tones, level, offset_hz):  # track drift using the known pilot tones
    """Return (extra offset at the first symbol in Hz, drift in Hz per second) measured from the pilots.

    The pilots are handled in stretches of about eight. Each stretch is
    searched around where the previous stretch found the signal, so the
    tracker follows a drifting signal step by step.
    """
    positions = np.asarray(positions)  # which symbols are pilots
    tones = np.asarray(tones)  # which tone each pilot used
    groups = max(1, len(positions) // 8)  # split the frame into stretches of about 8 pilots
    track = 0.0  # frequency error found so far, on top of the chirp's estimate
    times = []  # middle time of each stretch
    errors = []  # frequency error measured in each stretch
    for idx in np.array_split(np.arange(len(positions)), groups):  # one stretch at a time, in order
        avg = np.zeros(2 * FINE_SPAN + 1)  # running sum of fine spectra for this stretch
        for pos, tone in zip(positions[idx], tones[idx]):  # look at every pilot in the stretch
            block = _mixed_blocks(x, start + pos * level.samples, 1, level, offset_hz + track, 0.0)[0]  # that pilot's audio, corrected by the best estimate so far
            spec = np.abs(np.fft.fft(block, PAD * level.samples)) ** 2  # fine-grained power spectrum
            centre = level.tone_bins[tone] * PAD  # where the pilot should be on the fine grid
            avg += spec[centre - FINE_SPAN:centre + FINE_SPAN + 1]  # add the few fine steps either side
        peak = int(np.argmax(avg))  # fine step with the most energy
        frac = 0.0  # fraction-of-a-step correction
        if 0 < peak < len(avg) - 1:  # only if the peak has a neighbour on each side
            a, b, c = avg[peak - 1], avg[peak], avg[peak + 1]  # the peak and its neighbours
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
