"""The L0 waveform: 32 tones, one tone at a time (MFSK).

Tone signalling does not depend on the phase of the radio wave, which is
the first thing fading and multipath destroy. The receiver only asks
"which tone has the most energy?", so it keeps working in rough conditions.
"""

import numpy as np  # numerical arrays

from .params import BASE_BIN, BIN_HZ, BITS_PER_SYMBOL, FS, M_TONES, SYMBOL_SAMPLES, SYMBOL_SECONDS, TONE_STEP_BINS  # waveform numbers

TONE_BINS = BASE_BIN + TONE_STEP_BINS * np.arange(M_TONES)  # FFT bin of each of the 32 tones
NOISE_BINS = TONE_BINS + 1  # the quiet bins between tones, used to measure the noise
_TONE_BITS = np.array([[(m >> (BITS_PER_SYMBOL - 1 - j)) & 1 for j in range(BITS_PER_SYMBOL)] for m in range(M_TONES)])  # the 5 bits each tone stands for
_WEIGHTS = 1 << np.arange(BITS_PER_SYMBOL - 1, -1, -1)  # place values 16, 8, 4, 2, 1
PAD = 8  # zero-padding factor for fine frequency measurement (8x finer than one bin)
FINE_SPAN = 4  # fine search reaches 4 fine steps each side (plus or minus 1.25 Hz)


def bits_to_symbols(bits):  # coded bits -> tone numbers
    """Group `bits` in fives (padding with zeros) and return one tone number per group."""
    bits = np.asarray(bits, dtype=np.int64)  # work in whole numbers
    extra = (-len(bits)) % BITS_PER_SYMBOL  # zeros needed to fill the last group
    padded = np.concatenate([bits, np.zeros(extra, dtype=np.int64)])  # add them
    return padded.reshape(-1, BITS_PER_SYMBOL) @ _WEIGHTS  # each row of 5 bits becomes a number 0..31


def symbols_to_audio(symbols):  # tone numbers -> sound
    """Return the audio for a run of tones, 0.4 seconds each."""
    n = np.arange(SYMBOL_SAMPLES)  # sample counter within one tone
    freqs = TONE_BINS[np.asarray(symbols)] * BIN_HZ  # frequency of every tone to send, in Hz
    return np.cos(2 * np.pi * freqs[:, None] * n[None, :] / FS).reshape(-1)  # one cosine burst per tone, joined end to end


def _mixed_blocks(x, start, nsym, offset_hz, drift_hz_s):  # cut out tones and correct their frequency
    """Return `nsym` tone-length blocks from `x`, shifted down by the frequency error."""
    first = int(round(start))  # first sample of the first tone
    need = nsym * SYMBOL_SAMPLES  # samples required for all the tones
    seg = x[max(first, 0):first + need]  # the part of the recording that holds them
    if first < 0:  # the frame starts before the recording does
        seg = np.concatenate([np.zeros(-first), seg])  # fill the missing start with silence
    if len(seg) < need:  # the recording ends early
        seg = np.concatenate([seg, np.zeros(need - len(seg))])  # fill the missing end with silence
    t = np.arange(need) / FS  # time of every sample, counted from the first tone
    mixer = np.exp(-2j * np.pi * (offset_hz * t + 0.5 * drift_hz_s * t * t))  # spinning correction that cancels offset and drift
    return (seg * mixer).reshape(nsym, SYMBOL_SAMPLES)  # corrected audio, one row per tone


def symbol_energies(x, start, nsym, offset_hz=0.0, drift_hz_s=0.0):  # measure every tone slot
    """Return (tone energies, noise energies), each with one row per symbol and 32 columns."""
    spec = np.fft.fft(_mixed_blocks(x, start, nsym, offset_hz, drift_hz_s), axis=1)  # spectrum of each tone-length block
    tone_e = np.abs(spec[:, TONE_BINS]) ** 2  # energy in each of the 32 tone positions
    noise_e = np.abs(spec[:, NOISE_BINS]) ** 2  # energy in the quiet bins between them
    return tone_e, noise_e  # both measurements


def energies_to_llrs(tone_e, noise_level):  # tone energies -> soft bits
    """Return 5 soft bits per symbol (positive = probably 0, negative = probably 1)."""
    llrs = np.zeros((tone_e.shape[0], BITS_PER_SYMBOL))  # room for 5 soft bits per symbol
    for j in range(BITS_PER_SYMBOL):  # one bit position at a time
        zero = tone_e[:, _TONE_BITS[:, j] == 0].max(axis=1)  # strongest tone whose bit j is 0
        one = tone_e[:, _TONE_BITS[:, j] == 1].max(axis=1)  # strongest tone whose bit j is 1
        llrs[:, j] = (zero - one) / noise_level  # the difference, scaled by the noise, is the confidence
    return llrs.reshape(-1)  # flatten to one long run of soft bits


def pilot_frequency_fit(x, start, positions, tones, offset_hz):  # track drift using the known pilot tones
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
            block = _mixed_blocks(x, start + pos * SYMBOL_SAMPLES, 1, offset_hz + track, 0.0)[0]  # that pilot's audio, corrected by the best estimate so far
            spec = np.abs(np.fft.fft(block, PAD * SYMBOL_SAMPLES)) ** 2  # fine-grained power spectrum
            centre = TONE_BINS[tone] * PAD  # where the pilot should be on the fine grid
            avg += spec[centre - FINE_SPAN:centre + FINE_SPAN + 1]  # add the few fine steps either side
        peak = int(np.argmax(avg))  # fine step with the most energy
        frac = 0.0  # fraction-of-a-step correction
        if 0 < peak < len(avg) - 1:  # only if the peak has a neighbour on each side
            a, b, c = avg[peak - 1], avg[peak], avg[peak + 1]  # the peak and its neighbours
            bend = a - 2 * b + c  # how sharply they curve
            if bend != 0:  # a flat line has no top
                frac = 0.5 * (a - c) / bend  # top of the parabola through the three points
        track += (peak + frac - FINE_SPAN) * BIN_HZ / PAD  # move the estimate to where this stretch found the signal
        errors.append(track)  # record it
        times.append(positions[idx].mean() * SYMBOL_SECONDS)  # and when this stretch happened
    if groups >= 2:  # with two or more stretches we can see a trend
        slope, intercept = np.polyfit(times, errors, 1)  # straight line through the measurements
        return float(intercept), float(slope)  # error at the start, and how fast it changes
    return float(errors[0]), 0.0  # one stretch only: a fixed correction, no drift
