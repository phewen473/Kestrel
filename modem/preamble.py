"""The signature tone pattern that starts every Kestrel frame, and how the receiver finds it.

Each speed level has its own fixed pattern: twelve of the level's 32
tones, all different, in an order that never changes. The patterns
were chosen so that every jump between tones is large and no two jumps
of the same reach are alike, which makes a pattern hard to mistake for
a shifted copy of itself. A frame at a
given level begins with that level's pattern, sent at the level's own
tone length. So the preamble is long where the signal is weak and
slow, short where it is strong and fast, never wider than the data
that follows, and it tells the receiver which level the frame uses.

The receiver cuts the audio into tone-length blocks a quarter of a tone
apart and, for every possible start time and frequency error, adds up
the energy found where each tone of the pattern ought to be. The
largest totals are its candidates; the header's check value then says
which candidate is a real frame.
"""

import numpy as np  # numerical arrays

from . import native  # the compiled library, used when present
from .mfsk import symbols_to_audio  # turns tone numbers into sound
from .params import LONG_LEVEL, LONG_PATTERN, PREAMBLE_PATTERNS, PREAMBLE_TONES  # the patterns and their length, and the long beacon's own pattern

PAD = 2  # the search looks at frequencies half a bin apart
HOPS = 4  # and at start times a quarter of a tone apart
CHUNK = 256  # blocks transformed at a time, to keep memory use modest on long recordings


def pattern_tones(level):  # the fixed tone pattern for a level
    """Return the twelve tone numbers that start every frame at speed level `level` (the table is in params.py and in the spec)."""
    return np.array(LONG_PATTERN if level == LONG_LEVEL else PREAMBLE_PATTERNS[level])  # that level's row of the table (or the long beacon's pattern)


def preamble_samples(spec):  # how long a level's preamble is
    """Return the length in samples of the preamble at the speed level `spec`."""
    return PREAMBLE_TONES * spec.samples  # twelve tones


def make_preamble(spec):  # what the transmitter sends at the start of every frame
    """Return the audio of the preamble for the speed level `spec`."""
    return symbols_to_audio(pattern_tones(spec.number), spec)  # the level's twelve tones, one after another


def detect_preamble(x, spec, max_offset_hz=50.0, keep=3, whiten=False, fine=True):  # what the receiver does first, once per level
    """Look for the preamble of level `spec` in `x`.

    Returns a list (strongest first, at most `keep` long, empty when `x`
    is too short) of dicts with: start (sample where the frame begins),
    offset_hz (how far off frequency the signal is) and quality (the
    pattern's energy compared with the background; about 1 for noise).

    With `whiten`, the energy at each frequency is first divided by its
    own typical (median) level over the whole of `x`, so a steady carrier
    or a noisy patch of the band counts for no more than quiet noise does.
    A Kestrel tone sits on any one frequency only briefly, so the typical
    level there is still the noise's. The long beacon is searched this way.

    With `fine` False the start is left at the coarse search's quarter-tone
    step and the frequency at its half-bin step (each dict also gets
    "coarse": True); fine_time() can then refine a candidate later, which
    the continuous receiver does only for the few it keeps (since 0.31).
    """
    tones = pattern_tones(spec.number)  # this level's pattern
    n, hop = spec.samples, spec.samples // HOPS  # block length and step between blocks, in samples
    reach = int(np.ceil(max_offset_hz / (spec.bin_hz / PAD)))  # how many half-bin steps the frequency error may be
    done = native.detect_preamble(x, n, PAD * spec.tone_bins[tones], PAD, HOPS, reach, whiten, keep)  # the compiled search, when the library is in use
    if done is not None:  # it was
        found = []  # the candidates, as the Python below would give them
        for row, shift, quality in done:  # strongest first
            item = {"start": float(row * hop), "offset_hz": float(shift * spec.bin_hz / PAD), "quality": quality}  # one candidate
            if fine:  # refined
                found.append(fine_time(x, spec, item))  # start and frequency found finely
            else:  # left coarse
                found.append(dict(item, coarse=True))  # marked so
        return found  # strongest first
    count = (len(x) - n) // hop + 1  # how many blocks fit
    starts = count - HOPS * (len(tones) - 1)  # how many start positions leave room for the whole pattern
    if starts < 1:  # the recording is too short to hold the pattern
        return []  # nothing to find
    bins = PAD * spec.tone_bins[tones]  # where each tone of the pattern sits, in half-bin steps
    low, high = int(bins.min()) - reach - 1, int(bins.max()) + reach + 2  # the only part of the spectrum that matters
    blocks = np.lib.stride_tricks.sliding_window_view(x, n)[::hop][:count]  # every block, without copying
    power = np.empty((count, high - low))  # the energy near the pattern's tones, block by block
    for first in range(0, count, CHUNK):  # a few hundred blocks at a time
        power[first:first + CHUNK] = np.abs(np.fft.rfft(blocks[first:first + CHUNK], PAD * n, axis=1)[:, low:high]) ** 2  # transform, keep the useful part
    if whiten:  # level out the band first
        power = power / (np.median(power, axis=0) + 1e-9 * float(power.max()) + 1e-30)  # each frequency in units of its own typical level (with a floor, so stretches of digital silence do not blow up)
    shifts = np.arange(-reach, reach + 1)  # the frequency errors tried
    total = np.zeros((starts, len(shifts)))  # the energy total for every start and every frequency error
    for k, centre in enumerate(bins):  # one tone of the pattern at a time
        total += power[HOPS * k:HOPS * k + starts][:, centre - low + shifts]  # the energy where that tone should be, k tones after the start
    background = float(np.median(total)) + 1e-30  # the typical total when nothing is there
    block_energy = power.sum(axis=1)  # all the energy near the tone band in each block
    in_blocks = sum(block_energy[HOPS * k:HOPS * k + starts] for k in range(len(tones))) + 1e-30  # the energy in the twelve blocks each start would use
    share = total / in_blocks[:, None]  # how much of that energy sits where the pattern says (near 1 for a clean preamble, small for chance matches in a frame's body)
    found, work = [], total * share ** 2  # the candidates, and a scratch copy of the ranking score (the total, weighted by how cleanly it matches) to cross them off
    for _ in range(keep):  # the strongest few
        row, col = np.unravel_index(int(np.argmax(work)), work.shape)  # the largest total left
        quality = float(work[row, col]) / background  # how far it stands above the background
        work[max(row - HOPS, 0):row + HOPS + 1, :] = 0  # cross off everything within a tone of it
        if not fine:  # the coarse answer is wanted
            found.append({"start": float(row * hop), "offset_hz": float(shifts[col] * spec.bin_hz / PAD), "quality": quality, "coarse": True})  # this candidate, unrefined
            continue  # next
        found.append(fine_time(x, spec, {"start": float(row * hop), "offset_hz": float(shifts[col] * spec.bin_hz / PAD), "quality": quality}))  # this candidate, refined
    return found  # strongest first


def fine_time(x, spec, found):  # refine a candidate's start and frequency
    """Return a copy of the candidate `found` (start, offset_hz, quality, as detect_preamble gives) with its start found to about 1/128 of a tone and its frequency to a fraction of a half-bin, by measuring the pattern's energy in `x` around the coarse answer."""
    tones = pattern_tones(spec.number)  # this level's pattern
    n, hop = spec.samples, spec.samples // HOPS  # tone length and the coarse search's step, in samples
    bins = PAD * spec.tone_bins[tones]  # where each tone of the pattern sits, in half-bin steps
    shift = int(round(found["offset_hz"] / (spec.bin_hz / PAD)))  # the coarse frequency error, in half-bin steps
    done = native.fine_time(x, n, bins, PAD, HOPS, shift, found["start"])  # the compiled refinement, when the library is in use
    if done == "short":  # too little audio to refine
        return dict(found)  # as the Python below would return
    if done is not None:  # refined
        return {"start": done[0], "offset_hz": float(done[1] * spec.bin_hz / PAD), "quality": found["quality"]}  # the candidate, refined
    row = int(round(found["start"] / hop))  # the coarse start, in quarter tones
    last = len(x) - n * len(tones)  # the latest start that leaves room for the pattern
    rows = np.arange(len(tones))  # one row per tone
    column = bins + shift  # where the pattern's tones sit at this frequency error

    def measure(start):  # the pattern's energy when the recording is cut into tones from `start`
        pieces = x[start:start + n * len(tones)].reshape(len(tones), n)  # cut exactly into the pattern's tones
        energy = np.abs(np.fft.rfft(pieces, PAD * n, axis=1)) ** 2  # the energy at every frequency in each
        return float(energy[rows, column].sum()), float(energy[rows, column - 1].sum()), float(energy[rows, column + 1].sum())  # at the pattern's tones, and half a bin either side

    if last < 0:  # too little audio to hold the pattern
        return dict(found)  # nothing to refine
    centre, reach_samples = min(max(row * hop, 0), last), hop  # the search starts a quarter of a tone either side of the coarse answer (kept inside the audio)
    for step in (max(n // 16, 1), max(n // 128, 1)):  # first a sixteenth of a tone at a time, then an eighth of that
        span = reach_samples // step  # how many steps to look each side of the centre
        trial = [centre + k * step for k in range(-span, span + 1) if 0 <= centre + k * step <= last]  # the start times to try, always including the centre itself
        scores = [measure(t) for t in trial]  # the pattern's energy at each
        top = int(np.argmax([score[0] for score in scores]))  # the best of them
        centre, reach_samples = trial[top], step  # look more finely around it next time
    here, below, above = scores[top]  # the energy at the best start, and half a bin either side in frequency
    bend = below - 2 * here + above  # how sharply the energy peaks across frequency
    nudge = 0.5 * (below - above) / bend if bend < 0 else 0.0  # where the true peak lies between the half-bin steps
    start = float(centre)  # the best start found
    if 0 < top < len(trial) - 1:  # there is a neighbour on each side: place the start between steps
        early, late = scores[top - 1][0], scores[top + 1][0]  # the energy one step earlier and one step later
        curve = early - 2 * here + late  # how sharply the energy peaks across time
        if curve < 0:  # a true peak
            start += 0.5 * (early - late) / curve * step  # the top of the parabola through the three points
    return {"start": start, "offset_hz": float((shift + nudge) * spec.bin_hz / PAD), "quality": found["quality"]}  # the candidate, refined

