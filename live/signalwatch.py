"""Recognizing the signals in the receiver's passband (since 0.37).

Twice a second the newest second of received audio is turned into a
spectrum with 1 Hz steps from 200 to 3000 Hz. Anything standing 10 dB or
more above the noise (the median of the spectrum) is a signal there;
neighboring hertz are joined into one signal. Signals seen in a row on the
same frequency are followed as one "track": when it started, how long it
lasted, its frequency, width and strength.

Each track is given a type from its width, length, timing and steadiness,
the way an operator recognizes signals on a waterfall:

  Kestrel   a frame the Kestrel receiver decoded or nearly decoded there (its level, and callsign when read)
  FT8       about 50 Hz wide, about 13 s, starting on a 15-second boundary
  FT4       about 80 Hz wide, about 5 s, starting on a 7.5-second boundary
  JS8       as FT8, on a JS8 calling frequency
  WSPR      about 6 Hz wide, about 111 s, starting on an even minute
  CW        narrow, keyed on and off (strength jumps about)
  Carrier   narrow and steady
  RTTY      two narrow tones 170 Hz apart, starting and ending together
  PSK       25 to 80 Hz wide, on for a while, not on a time boundary
  Other     anything else, with its width and length

These are guesses from what is visible, like an operator's: a signal that
breaks most of the rules is "Other". The operator chooses which types are
listed and labeled on the waterfall.
"""

import time  # clocks

import numpy as np  # arrays

RATE = 48000  # the sound card's rate (live.audio.CARD_RATE)
WINDOW = 48000  # one second of audio per spectrum: 1 Hz steps
LOW_HZ, HIGH_HZ = 200, 3000  # the part of the passband watched
ABOVE_DB = 10.0  # a hertz this far above the noise (the median, after averaging over SMOOTH_HZ) is occupied: averaged noise reaches 7 dB a few times a second across the band, 10 dB very seldom
SMOOTH_HZ = 5  # the spectrum is averaged over this many hertz before looking for signals
JOIN_HZ = 4  # occupied hertz this close together are one signal
SKIRT_DB = 20.0  # a signal's faint skirts (key clicks, sidebands) more than this far below its peak are not counted in its width
FRAGMENT_DB = 10.0  # a piece this much weaker than a signal close by is that signal's sideband, not a signal of its own
SKIRT_HZ = 150.0  # how far from a strong signal its sidebands may reach
MATCH_HZ = 6  # a signal within this of a track's edges continues it
GAP_S = 2.5  # a track not seen for this long has ended
MIN_SIGHTINGS = 3  # a track seen fewer times than this is not reported (noise that happened to stand out)
KEEP = 400  # how many finished signals are kept for the list
LINGER_S = 15.0  # a signal that has just ended stays highlighted on the scope this long (FT8 and FT4 pause a moment between transmissions)
TYPES = ("Kestrel", "FT8", "FT4", "JS8", "WSPR", "CW", "Carrier", "RTTY", "PSK", "Other")  # every type, in the order offered
_N = np.arange(WINDOW) / WINDOW  # the window's sample positions, 0 to 1
_BLACKMAN_HARRIS = 0.35875 - 0.48829 * np.cos(2 * np.pi * _N) + 0.14128 * np.cos(4 * np.pi * _N) - 0.01168 * np.cos(6 * np.pi * _N)  # the four-term Blackman-Harris window
JS8_KHZ = (1842.0, 3578.0, 7078.0, 10130.0, 14078.0, 18104.0, 21078.0, 24922.0, 28078.0, 50318.0)  # JS8's calling dial frequencies


class Track:  # one signal followed through time
    """A signal seen on one frequency, from its first sighting to its last."""

    def __init__(self, lo, hi, db, now):  # first seen
        self.lo, self.hi = lo, hi  # its edges, Hz (the widest seen, used to follow it)
        self.los, self.his = [lo], [hi]  # its edges in each sighting
        self.start = self.last = now  # first and last seen (seconds since 1970)
        self.levels = [db]  # its peak strength above the noise in each sighting
        self.centers = [(lo + hi) / 2.0]  # its middle in each sighting
        self.pairs = []  # the spacing of two nearly equal peaks in each sighting (RTTY's two tones), 0 when there were not two
        self.kind = ""  # its type, once judged
        self.detail = ""  # more about it (Kestrel level and callsign)

    @property  # worked out from the sightings
    def center(self):  # its frequency
        """Return the middle of the signal, Hz (the median of its sightings)."""
        return float(np.median(self.centers))  # steady against odd sightings

    @property  # worked out from the edges
    def width(self):  # how wide it is
        """Return its width, Hz."""
        return int(np.median(self.his) - np.median(self.los)) + 1  # the typical sighting (the moments it starts and stops splash wider)

    @property  # worked out from the times
    def seconds(self):  # how long it has lasted
        """Return its length, seconds (a sighting is a second of audio, so half a second is added at each end)."""
        return self.last - self.start + 1.0  # from the first audio to the last

    @property  # worked out from the levels
    def strength(self):  # how strong it is
        """Return its typical strength above the noise, dB."""
        return float(np.median(self.levels))  # the middle sighting


def occupied(spectrum_db):  # one spectrum -> the signals in it
    """Return [(low Hz, high Hz, peak dB above the noise, spacing of two nearly equal peaks or 0)] for every signal in a spectrum of 1 Hz steps starting at LOW_HZ."""
    power = 10.0 ** (np.asarray(spectrum_db) / 10.0)  # back to power
    smooth = np.convolve(power, np.ones(SMOOTH_HZ) / SMOOTH_HZ, mode="same")  # averaged over a few hertz: the noise steadies, and a signal hopping between tones a few hertz apart (FT8, WSPR) reads as one
    over = 10.0 * np.log10(smooth / max(float(np.median(smooth)), 1e-30) + 1e-30)  # every hertz against the noise (the median)
    on = np.flatnonzero(over >= ABOVE_DB)  # the occupied hertz
    if len(on) == 0:  # nothing
        return []  # no signals
    groups = np.split(on, np.flatnonzero(np.diff(on) > JOIN_HZ) + 1)  # runs of occupied hertz, joined across small gaps
    peaks = [float(over[g].max()) for g in groups]  # each run's peak
    trim = SMOOTH_HZ // 2  # the averaging widens every signal by this much each side
    out = []  # the signals
    for g, peak in zip(groups, peaks):  # each run
        middle = (g[0] + g[-1]) / 2.0  # where it is
        if any(p - peak > FRAGMENT_DB and abs((h[0] + h[-1]) / 2.0 - middle) <= SKIRT_HZ for h, p in zip(groups, peaks)):  # far weaker than a strong signal close by: its sideband or key clicks, not a signal of its own
            continue  # left out
        strong = g[over[g] >= peak - SKIRT_DB]  # the part within SKIRT_DB of its own peak (a strong signal's faint skirts are not its width)
        lo, hi = int(strong[0]) + trim, int(strong[-1]) - trim  # its edges, the widening taken off
        if hi < lo:  # narrower than the averaging
            lo = hi = (int(strong[0]) + int(strong[-1])) // 2  # one hertz, in the middle
        out.append([lo + LOW_HZ, hi + LOW_HZ, peak, 0])  # edges, peak, and (below) the spacing to a twin
    for a in out:  # look for RTTY's two tones: two pieces nearly equal in strength 150 to 220 Hz apart
        for b in out:  # each other piece
            gap = abs((b[0] + b[1]) - (a[0] + a[1])) / 2.0  # between their middles
            if b is not a and 150.0 <= gap <= 220.0 and abs(a[2] - b[2]) <= 10.0:  # a twin
                a[3] = gap  # noted
    return [tuple(a) for a in out]  # each signal


def spectrum(samples):  # one second of audio -> 1 Hz steps, in dB
    """Return the power spectrum of the newest second of `samples` (at RATE), LOW_HZ to HIGH_HZ, in dB."""
    piece = np.asarray(samples[-WINDOW:], dtype=float)  # the newest second
    if len(piece) < WINDOW:  # not enough yet
        return None  # nothing
    power = np.abs(np.fft.rfft(piece * _BLACKMAN_HARRIS)) ** 2  # the power at every hertz (a window whose side lobes are 92 dB down, so a strong signal does not spill across the band)
    return 10.0 * np.log10(power[LOW_HZ:HIGH_HZ] + 1e-20)  # the band watched, in dB


def classify(track, dial_khz=0.0, partner=None):  # what kind of signal a track is
    """Return the type of a track (one of TYPES) from its width, length, start time, steadiness; `partner` is a track 170 Hz away that started with it (RTTY)."""
    if track.kind == "Kestrel":  # the Kestrel receiver said so
        return "Kestrel"  # trust it
    width, length = track.width, track.seconds  # the two main features
    second = track.start % 60.0  # where in the minute it began
    steady = float(np.std(track.levels)) if len(track.levels) > 2 else 0.0  # how much its strength jumps (dB)

    def near(value, step, slack):  # does a start time fall on a boundary?
        off = value % step  # past the last boundary
        return off <= slack or step - off <= slack / 2  # just after it (transmitters start up to a second or two late), or a little before (clock error)
    pairs = [p for p in track.pairs if p]  # sightings with two nearly equal peaks
    if partner is not None or (len(pairs) * 2 >= len(track.pairs) and pairs and 150 <= float(np.median(pairs)) <= 220):  # a twin 170 Hz away, or two peaks about 170 Hz apart most of the time
        return "RTTY"  # frequency-shift keying
    if width <= 12 and 95.0 <= length <= 125.0 and near(track.start, 120.0, 4.0):  # narrow, two minutes, on an even minute
        return "WSPR"  # weak signal propagation reporter
    if 30 <= width <= 90 and 10.0 <= length <= 15.5 and near(second, 15.0, 2.5):  # 50 Hz, 13 s, 15-second boundary
        return "JS8" if any(abs(dial_khz - f) < 1.5 for f in JS8_KHZ) else "FT8"  # JS8 on its own frequencies, else FT8
    if 60 <= width <= 125 and 3.5 <= length <= 7.0 and near(second % 7.5, 7.5, 2.0):  # 80 Hz, 5 s, 7.5-second boundary
        return "FT4"  # FT4
    if width <= 30 and length >= 3.0 and steady >= 3.0:  # narrow, lasting, strength jumping about
        return "CW"  # keyed
    if width <= 15 and length >= 3.0:  # narrow, lasting and steady
        return "Carrier"  # a steady tone
    if 20 <= width <= 90 and length >= 5.0:  # a narrow digital signal on for a while
        return "PSK"  # PSK31 and the like
    return "Other"  # not recognized


class SignalWatch:  # follows every signal in the passband
    """Feed it the received audio twice a second; it keeps the signals on now and the ones heard lately."""

    def __init__(self):  # nothing seen yet
        self.active = []  # tracks still going
        self.done = []  # finished tracks, newest last
        self.kestrel = []  # Kestrel frames decoded or nearly decoded: (audio Hz, width Hz, when, label)
        self.dial_khz = 0.0  # where the radio is, for JS8 and the radio frequency

    def feed(self, samples, now=None, dial_khz=None):  # one look at the audio
        """Take the newest second of `samples` (at RATE) and update the tracks; return the signals seen in it."""
        now = now if now is not None else time.time()  # now
        if dial_khz is not None:  # the radio's frequency
            if self.dial_khz and abs(dial_khz - self.dial_khz) > 0.05:  # the radio moved: every track ends
                self._end_all()  # finished
            self.dial_khz = dial_khz  # kept
        spec = spectrum(samples)  # the spectrum
        if spec is None:  # not enough audio
            return []  # nothing
        seen = occupied(spec)  # the signals in it
        return self.step(seen, now)  # follow them

    def step(self, seen, now):  # update the tracks from one look
        """Continue or start a track for each (low, high, dB) in `seen` at time `now`; end tracks not seen lately. Return `seen`."""
        pieces = {}  # track -> the pieces of this look that continue it
        for piece in seen:  # each signal
            lo, hi, db = piece[0], piece[1], piece[2]  # its edges and strength
            near = [t for t in self.active if lo <= t.hi + MATCH_HZ and hi >= t.lo - MATCH_HZ]  # tracks it overlaps
            if not near:  # a new signal
                t = Track(lo, hi, db, now)  # start a track
                t.pairs.append(piece[3] if len(piece) > 3 else 0)  # two peaks?
                self.active.append(t)  # going
                pieces[id(t)] = (t, [])  # begun with this piece (already counted)
                continue  # next
            t = max(near, key=lambda k: len(k.levels))  # the longest-running of them continues
            pieces.setdefault(id(t), (t, []))[1].append((lo, hi, db, piece[3] if len(piece) > 3 else 0))  # this piece belongs to it
        for t, parts in pieces.values():  # each track continued
            if not parts:  # just begun
                continue  # nothing more
            lo, hi, db = min(p[0] for p in parts), max(p[1] for p in parts), max(p[2] for p in parts)  # its pieces together
            t.lo, t.hi, t.last = min(t.lo, lo), max(t.hi, hi), now  # wider if need be, seen now
            t.los.append(lo)  # edges this time
            t.his.append(hi)  # (both)
            t.levels.append(db)  # strength
            t.centers.append((lo + hi) / 2.0)  # middle
            t.pairs.append(max(p[3] for p in parts))  # two peaks?
        merged = []  # tracks after merging any that now overlap
        for t in sorted(self.active, key=lambda k: -len(k.levels)):  # longest-running first
            host = next((m for m in merged if t.lo <= m.hi + MATCH_HZ and t.hi >= m.lo - MATCH_HZ and abs(t.last - m.last) <= GAP_S), None)  # an overlapping track already kept
            if host is None:  # none
                merged.append(t)  # kept
            else:  # absorbed into the longer one
                host.lo, host.hi, host.start, host.last = min(host.lo, t.lo), max(host.hi, t.hi), min(host.start, t.start), max(host.last, t.last)  # its span
        self.active = merged  # the tracks going
        still = []  # tracks going on
        for t in self.active:  # each
            if now - t.last > GAP_S:  # not seen lately: it has ended
                self._finish(t)  # judged and kept
            else:  # still going
                still.append(t)  # kept going
        self.active = still  # the tracks going
        return seen  # what was seen

    def _finish(self, t):  # a track has ended
        """Judge a finished track and keep it (if long enough)."""
        if len(t.levels) < MIN_SIGHTINGS:  # a spike
            return  # forgotten
        self._label(t)  # Kestrel, if the receiver decoded something there
        twin = next((o for o in self.done[-20:] if abs(abs(o.center - t.center) - 170.0) <= 8.0 and abs(o.start - t.start) <= 2.0 and o.width <= 100 and t.width <= 100), None)  # a tone 170 Hz away that started with it
        t.kind = classify(t, self.dial_khz, twin)  # its type
        if twin is not None and twin.kind != "Kestrel":  # the pair is one RTTY signal
            twin.kind = "RTTY"  # the other half too
        self.done.append(t)  # kept
        self.done = self.done[-KEEP:]  # within the limit

    def _end_all(self):  # the radio moved
        """End every track now."""
        for t in self.active:  # each
            self._finish(t)  # judged
        self.active = []  # none going

    def _label(self, t):  # match Kestrel decodes to a track
        """Mark a track as Kestrel when a Kestrel frame was decoded on its frequency while it was on."""
        for hz, width, when, label in self.kestrel:  # each Kestrel frame
            if abs(hz - t.center) <= max(width, t.width) / 2.0 + 10.0 and t.start - 5.0 <= when <= t.last + 30.0:  # same frequency, around the same time (a frame is reported when it ends, or a little after)
                t.kind, t.detail = "Kestrel", label  # named
                return  # done

    def kestrel_heard(self, hz, width, label, when=None):  # the Kestrel receiver decoded (or nearly decoded) a frame
        """Note a Kestrel frame at audio `hz`, `width` Hz wide, described by `label` ("L2 Q1AAAA"), so the matching track is named."""
        when = when if when is not None else time.time()  # now
        self.kestrel = [k for k in self.kestrel if when - k[2] < 300.0][-50:] + [(hz, width, when, label)]  # kept a few minutes
        for t in self.done[-30:]:  # a track that already ended
            if t.kind != "Kestrel" and abs(hz - t.center) <= max(width, t.width) / 2.0 + 10.0 and t.start - 5.0 <= when <= t.last + 30.0:  # matches
                t.kind, t.detail = "Kestrel", label  # renamed
        for t in self.active:  # a track still going (a frame read while still on the air)
            if abs(hz - t.center) <= max(width, t.width) / 2.0 + 10.0:  # matches
                t.kind, t.detail = "Kestrel", label  # named

    def current(self, now=None):  # the signals on now, judged so far
        """Return the active tracks (each with a provisional type, kind_now)."""
        out = []  # the list
        for t in self.active:  # each
            if len(t.levels) < MIN_SIGHTINGS:  # too new to show
                continue  # skip
            t.kind_now = t.kind if t.kind == "Kestrel" else _provisional(t, self.dial_khz)  # a type so far
            out.append(t)  # shown
        return out  # the list

    def rows(self, kinds, now=None):  # what the Signals detected window lists
        """Return active and finished tracks whose type is in `kinds`, newest first."""
        live = [t for t in self.current(now) if t.kind_now in kinds]  # on now
        finished = [t for t in reversed(self.done) if t.kind in kinds]  # heard lately
        return live, finished  # both


def _on_boundary(value, step, slack):  # does a start time fall on a boundary?
    """Return True when `value` (seconds) is just after a multiple of `step` (within `slack`) or a little before it (within half of it)."""
    off = value % step  # past the last boundary
    return off <= slack or step - off <= slack / 2  # transmitters start up to a second or two late; clocks may be a little ahead


def _provisional(t, dial_khz=0.0):  # the type of a signal still going
    """Return a best guess for a track still on the air, from its width, its start time and how it behaves so far (its length is not known yet)."""
    pairs = [p for p in t.pairs if p]  # sightings with RTTY's two tones
    if pairs and len(pairs) * 2 >= len(t.pairs) and 150 <= float(np.median(pairs)) <= 220:  # two tones about 170 Hz apart
        return "RTTY"  # frequency-shift keying
    second = t.start % 60.0  # where in the minute it began
    if t.width <= 12 and _on_boundary(t.start, 120.0, 4.0) and t.seconds <= 125.0:  # narrow, begun on an even minute, not yet longer than WSPR
        return "WSPR"  # most likely
    if 30 <= t.width <= 90 and _on_boundary(second, 15.0, 2.5) and t.seconds <= 15.5:  # FT8's width, begun on a 15-second boundary
        return "JS8" if any(abs(dial_khz - f) < 1.5 for f in JS8_KHZ) else "FT8"  # JS8 on its own frequencies, else FT8
    if 60 <= t.width <= 125 and _on_boundary(second % 7.5, 7.5, 2.0) and t.seconds <= 7.0:  # FT4's width, begun on a 7.5-second boundary
        return "FT4"  # most likely
    if t.width <= 30 and len(t.levels) > 4 and float(np.std(t.levels)) >= 3.0:  # narrow, strength jumping about
        return "CW"  # keyed
    if t.width <= 15:  # narrow and steady
        return "Carrier"  # a steady tone
    if 20 <= t.width <= 90:  # a narrow digital signal
        return "PSK"  # most likely
    return "Other"  # not recognized yet
