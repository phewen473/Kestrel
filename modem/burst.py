"""Acknowledgment bursts: an acknowledgment the waiting station recognizes instead of decoding (since 0.43, signal version 0.43).

A station that has just sent a message frame knows almost everything the
acknowledgment can say: the link, the message number and the part are its
own; only the verdict (received, send again, already have it) and the level
the partner asks for are open. So instead of a 31-second L0 acknowledgment
frame that has to be found and decoded, the partner can send a burst of
BURST_TONES L0 tones (9.6 s) in an order fixed by everything the
acknowledgment says. The waiting station tries each thing it could say
against what it hears where the burst can start, and takes the one that fits,
if any fits well enough.

The burst is recognized by rank: in each of its tone slots, is the tone the
pattern expects the strongest of the 32 tones there (1 point), or the second
strongest (0.1 point)? Ranks ignore how loud anything is, so a strong
signal that is not the burst (another Kestrel frame, another mode) scores no
more than noise does: its tones land on the expected one about one slot in 32.

Measured (study of November 26, 2026, real band noise from the author's
recordings, 100 trials a point, 4 verdicts, search +-1.5 s and +-3 Hz):
the 24-tone burst was recognized 95 times in 100 at -20 dB in slow fading
and 94 at -22 dB in typical fading, where today's L0 acknowledgment frame
was read 46 and 9 times; one wrong verdict in 1,200. In use the search is
wider (BURST_EARLIEST_S to BURST_LATEST_S after the waiting station's own
frame ends, and up to 15 things the burst could say), so the threshold is
set for that search (tools/burst_study.py): 10,000 searches each of real
band noise and white noise put 99.9 % of best scores below 8.1 and 8.2. As
built, in real noise: slow fading 90 in 100 at -20 dB, moderate 82 at -22 dB
and 95 at -20 dB, fast (2 Hz) 90 at -22 dB; one wrong verdict in 2,100.

The same burst confirms a lock (the last step of a call-up), keyed by both
stations' link number. Every burst carries the level the sender asks for;
the fuller channel report still goes in an acknowledgment frame when the
last one sent is older than REPORT_EVERY_S (link/params.py).
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from .levels import LEVELS  # the speed levels (a burst is sent at L0)
from .mfsk import band_energies, symbols_to_audio, fade_ends  # tones <-> audio
from .params import FS, M_TONES  # sample rate, number of tones

SPEC = LEVELS[0]  # bursts use L0's tones: 0.4 s each, 5 Hz apart
BURST_TONES = 24  # tones in a burst (9.6 s at L0)
SEARCH_HOP_S = 0.05  # the start is searched in steps of this many seconds
SEARCH_HZ = 3.0  # and the frequency within this many hertz of where it should be (on the air every frame from a partner 69 miles away arrived within -0.7..+1.4 Hz)
SEARCH_STEP_HZ = 0.5  # in steps of this many hertz
PAD = 5  # each tone-length window is transformed with this much padding (0.5 Hz bins)
SECOND_POINTS = 0.1  # points for a slot whose expected tone is the second strongest (so close calls between patterns are rare)
THRESHOLD = 8.6  # score a burst must beat: about one false recognition in 1,000 searches of noise alone (BURST_EARLIEST_S..BURST_LATEST_S, 15 patterns; tools/burst_study.py, real and white noise)
MARGIN = 2.0  # the best pattern must beat the best pattern saying something different by this many points, or nothing is taken (a missed acknowledgment costs a retry; a wrong verdict could lose a part)
BURST_EARLIEST_S = 0.5  # a burst starts no sooner than this after the waiting station's own frame ends (the partner's turnaround alone is 1 s)
BURST_LATEST_S = 7.0  # nor later than this (the partner hears the frame end, searches about once a second, decodes, waits 1 s and keys up; sound cards add delay)


@dataclass(frozen=True)  # a fixed record
class BurstSays:  # one thing a burst can say
    """Everything an acknowledgment burst says: which frame it answers, the verdict, and the level asked for."""

    link: int  # the link number
    msg_id: int  # the message number (0 for a lock confirmation)
    part: int  # the part number (for a lock confirmation: its code, OFFER_REPLY or OFFER_TURN)
    status: int  # the verdict: ACK_OK, ACK_RESEND, ACK_HAVE_IT, or ACK_LINK for a lock confirmation
    want: int  # the level the sender asks for (0-4)


def _xorshift32(state):  # the random-number routine (as modem/ldpc.py)
    """Return the next 32-bit value of the xorshift32 generator."""
    state ^= (state << 13) & 0xFFFFFFFF  # mix: shift left 13, keep 32 bits
    state ^= state >> 17  # mix: shift right 17
    state ^= (state << 5) & 0xFFFFFFFF  # mix: shift left 5, keep 32 bits
    return state  # the new value


def seed_of(says):  # the burst's seed
    """Return the 32-bit seed of a burst: its fields packed as link (16 bits) | message (10) | part (3) | status (2) | level (3), mixed with the constant 0x4B455342 ("KESB")."""
    word = (says.link & 0xFFFF) << 18 | (says.msg_id & 0x3FF) << 8 | (says.part & 0x7) << 5 | (says.status & 0x3) << 3 | (says.want & 0x7)  # 34 bits of fields
    seed = (word ^ (word >> 32) ^ 0x4B455342) & 0xFFFFFFFF  # folded to 32 bits and mixed with the constant
    return seed or 0x4B455342  # never zero (xorshift would stay at zero)


def pattern(says):  # the burst's tones
    """Return the BURST_TONES tone numbers (0-31) of the burst that says `says`; no tone repeats the one before it."""
    state = seed_of(says)  # the generator's starting value
    for _ in range(8):  # stir it a little first
        state = _xorshift32(state)  # next value
    tones, last = [], -1  # tones chosen, and the previous one
    while len(tones) < BURST_TONES:  # until the burst is full
        state = _xorshift32(state)  # next value
        tone = (state >> 11) % M_TONES  # a tone from the generator's upper bits
        if tone != last:  # a change of tone every slot (a steady tone could be taken for a carrier and notched out)
            tones.append(tone)  # keep it
            last = tone  # remember it
    return np.array(tones, dtype=np.int64)  # the pattern


def build_burst(says):  # the transmitter
    """Return the audio of the burst that says `says`: BURST_TONES L0 tones, faded in and out like a frame."""
    return fade_ends(symbols_to_audio(pattern(says), SPEC))  # the tones, as one continuous waveform


def burst_seconds():  # airtime
    """Return a burst's length on the air, in seconds (9.6)."""
    return BURST_TONES * SPEC.seconds  # tones times tone length


@dataclass  # a plain record
class Recognized:  # what the search found
    """A recognized burst: what it says, where it starts in the audio, its frequency offset, and its score."""

    says: BurstSays  # what it says
    start: int  # the sample where it starts
    offset_hz: float  # its frequency offset
    score: float  # its rank score
    runner_up: float  # the best score of a pattern saying something different


def _points(x, first, last, center_hz=0.0):  # the rank points of every window and offset
    """Return (points per offset: windows x 32, window starts) for tone-length windows every SEARCH_HOP_S from sample `first` to `last`, offsets within SEARCH_HZ of `center_hz`."""
    n, hop = SPEC.samples, int(round(SEARCH_HOP_S * FS))  # window length and step
    seg = x[first:last]  # the stretch searched
    starts = np.arange(0, len(seg) - n + 1, hop)  # every window
    win = np.lib.stride_tricks.sliding_window_view(seg, n)[::hop][:len(starts)]  # the windows
    spec = np.abs(np.fft.rfft(win * np.hanning(n), n * PAD, axis=1)) ** 2  # their spectra
    df = FS / (n * PAD)  # bin width
    tone_hz = SPEC.tone_bins * FS / n  # the 32 tone frequencies
    out = []  # one table per offset
    for f in center_hz + np.arange(-SEARCH_HZ, SEARCH_HZ + 1e-9, SEARCH_STEP_HZ):  # each frequency offset
        tones = spec[:, np.rint((tone_hz + f) / df).astype(int)]  # every window's 32 tone energies there
        rank = np.argsort(np.argsort(-tones, axis=1), axis=1)  # each tone's place, 0 for the strongest
        out.append((f, np.where(rank == 0, 1.0, np.where(rank == 1, SECOND_POINTS, 0.0))))  # its points
    return out, starts + first  # the tables, and where each window starts


def recognize(x, candidates, earliest, latest, center_hz=0.0):  # the receiver
    """Return a Recognized for the burst in `x` saying one of `candidates` (BurstSays) and starting between samples `earliest` and `latest`, or None.

    The frequency is searched within SEARCH_HZ of `center_hz`: the offset at
    which the partner's frames have been arriving, when the waiting station
    knows it (a radio a few hertz off tune puts every one of its signals there).

    The best-scoring pattern must beat THRESHOLD, and beat the best pattern that
    says something different (another verdict or message) by MARGIN; a pattern
    saying the same verdict with a different level is not a rival, and of two
    close ones the lower level is taken (the safe choice).
    """
    n = SPEC.samples  # tone length
    center_hz = float(center_hz) if np.isfinite(center_hz) else 0.0  # no offset known: search around none
    earliest, latest = max(int(earliest), 0), min(int(latest), len(x) - BURST_TONES * n)  # inside the audio
    if latest < earliest or not candidates:  # not enough audio, or nothing to look for
        return None  # nothing
    tables, starts = _points(x, earliest, latest + BURST_TONES * n, center_hz)  # every window's points
    step = int(round(n / (SEARCH_HOP_S * FS)))  # windows per tone (8)
    begins = np.arange(0, len(starts) - (BURST_TONES - 1) * step)  # windows where a burst can start
    rows = begins[:, None] + step * np.arange(BURST_TONES)[None, :]  # the window of each tone, for each start
    pats = np.array([pattern(c) for c in candidates])  # every candidate's tones
    best = None  # (score, candidate index, start, offset)
    scores = np.full(len(candidates), -np.inf)  # each candidate's best score
    for f, points in tables:  # each offset
        s = points[rows[:, None, :], pats[None, :, :]].sum(axis=2)  # starts x candidates
        top = s.max(axis=0)  # each candidate's best here
        scores = np.maximum(scores, top)  # its best anywhere
        i, c = np.unravel_index(int(np.argmax(s)), s.shape)  # the best start and candidate here
        if best is None or s[i, c] > best[0]:  # the best so far
            best = (float(s[i, c]), int(c), int(starts[begins[i]]), float(f))  # kept
    score, c, start, offset = best  # the winner
    says = candidates[c]  # what it says
    close = [j for j, other in enumerate(candidates) if (other.status, other.part, other.msg_id) == (says.status, says.part, says.msg_id) and scores[j] >= score - MARGIN]  # the same verdict at other levels, nearly as good
    says = min((candidates[j] for j in close), key=lambda o: o.want)  # the lowest level among them
    rivals = [scores[j] for j, other in enumerate(candidates) if (other.status, other.part, other.msg_id) != (says.status, says.part, says.msg_id)]  # patterns saying something different
    runner_up = max(rivals) if rivals else -np.inf  # the best of them
    if score <= THRESHOLD or score - runner_up < MARGIN:  # not there, or not clear which
        return None  # nothing taken
    return Recognized(says, start, offset, score, float(runner_up))  # found


def heard(x, listen, earliest, latest, center_hz=0.0):  # recognize a burst and report it as an acknowledgment
    """Return an RxResult for the burst in `x` saying one of `listen`, as an acknowledgment frame saying the same would be reported, or None.

    The report's fields are those of an acknowledgment (link, msg_id, part,
    status, report); the channel report carries only the level asked for
    (its SNR and fading index are NaN: a burst does not carry them). The
    result's own SNR, fading index and spread are measured from the burst,
    and its `burst` flag is set.
    """
    found = recognize(x, listen, earliest, latest, center_hz)  # the search
    if found is None:  # nothing there
        return None  # nothing heard
    from .control import ChannelReport  # the report record
    from .frame import RxResult  # the receiver's report
    from .params import FRAME_TYPE_ACK  # the acknowledgment's frame type
    snr, fade, spread = measure(x, found)  # how it was heard
    says = found.says  # what it says
    fields = {"link": says.link, "msg_id": says.msg_id, "part": says.part, "status": says.status, "report": ChannelReport(float("nan"), float("nan"), 0.0, says.want)}  # as an acknowledgment's fields
    return RxResult(ok=True, frame_type=FRAME_TYPE_ACK, level=0, start=float(found.start), offset_hz=found.offset_hz, snr_db=snr, fade_index=fade, spread_hz=spread,  # (continued)
                    link=says.link, msg_id=says.msg_id, part=says.part, fields=fields, burst=True, sync_quality=found.score)  # the report


def measure(x, found):  # the channel readings of a recognized burst
    """Return (SNR in 2.5 kHz, fading index, Doppler spread in Hz) of a recognized burst, measured like a frame's known tones."""
    from .frame import RxResult, _measure  # the frames' own measurement (imported here: frame.py imports this module's neighbors)
    from .mfsk import noise_level, tone_energies  # the noise per tone position
    band = band_energies(x, found.start, BURST_TONES, SPEC, found.offset_hz)  # every bin of the band, each tone
    result = RxResult()  # a blank report to fill
    _measure(result, band, pattern(found.says), noise_level(tone_energies(band, SPEC)), SPEC)  # SNR, fading and spread, as for a frame
    return result.snr_db, result.fade_index, result.spread_hz  # the readings
