"""A receiver that listens continuously: audio goes in as it arrives, decoded frames come out.

The modem's receive() works on a finished recording. A live station has
no finished recording, only a stream. The Listener keeps the last 100
seconds of audio and looks at it once a second. When it finds a whole
frame it hands the frame over and cuts it out of its store, so the same
frame is never reported twice.

Since 0.31 the search is incremental. Each second it looks for signature
patterns only in the audio that has arrived since the last look (with
enough audio before it to hold a whole pattern, and a few seconds more
for a fair measure of the background). Each pattern found is kept on a
short list of candidates, by its place in the stream, and decoded once
its frame has fully arrived. Before 0.31 the whole 100 seconds was
searched again every second, which cost about 1.5 seconds of computing
per second of audio on an older computer. The old way is kept
(Listener(incremental=False)) as the reference the new one is tested
against.
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from modem import LEVELS, MIN_SNR_DB, body_layout, control_layout, receive  # the speed levels, their limits, frame shapes and the receiver
from modem import native  # the compiled modem library (when present, the patterns are searched side by side)
from modem.blanker import blank_impulses  # removes static crashes before searching
from modem.notch import remove_steady  # notches steady signals (carriers) out of the band
from modem.frame import Hints, Prior  # help for reading weak control frames (since 0.31R1)
from modem.frame import pattern_seen  # how much of a signature pattern is really there (since 0.31R2)
from modem.frame import _body_total, _read_header_how  # how long a frame is by its header, and reading a header
from modem.preamble import detect_preamble, fine_time, preamble_samples  # the signature-pattern search, the fine timing of a candidate, and a pattern's length
from modem import longbeacon  # the long beacon's length and limit
from modem.params import FRAME_TYPE_LONG, LONG_LEVEL  # the long beacon's frame type and level number
from modem.frame import HEADER_SYMBOLS, RxResult, _body_totals  # tones in the two header copies together, and every body length a frame can have
from modem.params import CONTROL_BITS, FS, PREAMBLE_TONES  # control frame types, the sample rate and the preamble's length in tones

WINDOW_S = 100.0  # how much audio is kept: longer than the longest frame (90 s)
STEP_S = 1.0  # how often the stored audio is searched
PAD_S = 0.5  # audio kept either side of a frame when it is handed over
FAILED_SNR_SLACK_DB = 4.0  # a frame that fails its check is only reported if its pilots read within this many dB of its level's limit
NEAR_QUALITY = 6.0  # a signature whose header cannot be read, standing this far above the background, is reported (for the signal log) even when it is not likely Kestrel by the tone test below; before 0.31R2 this alone made a "near miss" (noise alone stays below about 3.5 in simulation)
NEAR_TONES = 7  # a signature whose header cannot be read is "likely Kestrel" when at least this many of its 12 pattern tones stand out in their own slots (since 0.31R2). Measured in simulation: a real frame at the edge of decoding shows 5 to 9, another mode's signal 1 or 2, and the strongest chance matches in plain noise 2 to 5 (7 about once in two thousand, 8 never in 4,500)
LONGEST_FRAME = (PREAMBLE_TONES + HEADER_SYMBOLS + max(_body_totals())) * LEVELS[0].samples  # samples in the longest frame there is (the largest message at the slowest level)
LONG_EVERY = 4  # the long beacon's pattern is looked for on every fourth search only: it costs about 0.4 s a search, and a long beacon lasts a minute, so finding it a few seconds later loses nothing
NEAR_QUALITY_MAX = 10000.0  # above this the measure has broken down (stretches of digital silence), so it is not a signal
PRIOR_KEEP_S = 1800  # failed control frames are kept this long (half an hour), for adding to a later copy
PRIOR_MOST = 16  # and at most this many of them
CONTEXT_S = 4.0  # incremental search: audio searched before the newest, beyond what one pattern needs, so the background is measured fairly
GATE = (0.002, 0.002, 0.003, 0.010, 0.012)  # incremental search: a pattern scoring below this (by level) is not followed up. Measured on simulated noise and frames, the strongest chance match scored 0.001, 0.001, 0.002, 0.005 and 0.008, and real frames 1 dB below each level's decoding limit (steady and fading) at least 0.004, 0.006, 0.005, 0.028 and 0.032 (one L4 frame in 40 was not found at all). The long beacon has no gate: copies too weak to read alone are kept for adding together


def likely_kestrel(result):  # is a near miss likely a real Kestrel frame?
    """Return True when most of a near miss's signature pattern stood out (at least NEAR_TONES of its 12 tones): a real Kestrel frame too weak or faded to read, not another mode's signal (since 0.31R2)."""
    return getattr(result, "pattern_tones", -1) >= NEAR_TONES  # the tone test


def worth_reporting(result):  # should a near miss be reported at all?
    """Return True for a near miss worth handing to on_near: likely Kestrel, or a signature standing well above the background (kept for the signal log, though the Activity log shows only likely ones)."""
    return likely_kestrel(result) or NEAR_QUALITY <= result.sync_quality <= NEAR_QUALITY_MAX  # either test


@dataclass  # a plain record
class Heard:  # one frame taken out of the stream
    """A frame the Listener found: the receiver's report, and the stretch of audio holding the frame."""

    result: object  # the receiver's report (an RxResult); its sample field says where the frame began in the stream
    audio: np.ndarray  # the frame's audio, with a little either side
    audio_sample: int = -1  # the stream's number for the first sample of `audio`


_POOL = []  # the worker threads that search the patterns side by side (made on first use, kept for the life of the program)


def _pool():  # the worker threads
    """Return the thread pool used to search several patterns at once."""
    if not _POOL:  # not made yet
        from concurrent.futures import ThreadPoolExecutor  # Python's own thread pool
        _POOL.append(ThreadPoolExecutor(max_workers=len(LEVELS) + 1, thread_name_prefix="kestrel-search"))  # one thread per pattern (five levels and the long beacon)
    return _POOL[0]  # the pool


def frame_samples(result):  # how long is the frame this report describes?
    """Return the length in samples of the frame whose header `result` came from."""
    if result.level == LONG_LEVEL:  # a long beacon: a fixed length
        return longbeacon.SAMPLES  # pattern and body
    if result.frame_type in CONTROL_BITS:  # a beacon, answer, acknowledgment or identification
        body = control_layout(result.frame_type)["total"]  # its body tones
    else:  # a message frame
        body = body_layout(result.size_class)["total"]  # its body tones
    return (PREAMBLE_TONES + HEADER_SYMBOLS + body) * LEVELS[result.level].samples  # preamble + header + body


def _core_settings(window, step):  # what the compiled listener needs to know
    """Return (settings, patterns, totals by type, body totals) for native.compiled_listener, from the same constants the Python listener uses."""
    from math import ceil  # rounding up
    from modem import blanker, notch  # the blanker's and the notch's settings
    from modem.frame import _totals_by_type  # body length by frame type and size class
    from modem.preamble import HOPS, PAD, pattern_tones  # the pattern search's settings and each pattern's tones
    cfg = [0.0] * native.CFG_COUNT  # in the KES_CFG_ order of kestrel.h
    cfg[0:10] = [window, step, LONGEST_FRAME, CONTEXT_S, LONG_EVERY, 3, HEADER_SYMBOLS, PREAMBLE_TONES, NEAR_QUALITY, NEAR_QUALITY_MAX]  # the store, the rhythm, the frame shapes, near misses
    cfg[10:12] = list(blanker.blank_impulses.__defaults__)  # the blanker's threshold and guard, as blank_impulses uses them
    cfg[12:19] = [notch.BLOCK, notch.BAND_LOW_HZ, notch.BAND_HIGH_HZ, notch.CARRIER_TIMES, notch.LOCAL_STEPS, notch.CARRIER_MOST, notch.NOTCH_HALF_HZ]  # the steady-signal notch
    cfg[19:25] = [longbeacon.SAMPLES, longbeacon.CENTER_HZ - longbeacon.CLEAN_HALF_HZ, longbeacon.CENTER_HZ + longbeacon.CLEAN_HALF_HZ, longbeacon.CARRIER_TIMES, longbeacon.CARRIER_MOST, longbeacon.NOTCH_HALF_HZ]  # the long beacon and its carrier notch
    cfg[25:28] = [PAD, HOPS, (PREAMBLE_TONES + HEADER_SYMBOLS // 2) * LEVELS[0].samples]  # the search's steps, and what a near miss cuts out
    patterns = {}  # slot -> (values, bins)
    for slot, spec in enumerate(list(LEVELS) + [longbeacon.LONG]):  # the five levels, then the long beacon
        reach = int(ceil(50.0 / (spec.bin_hz / PAD)))  # fine steps of frequency error searched (50 Hz, as detect_preamble's default)
        gate = GATE[spec.number] if spec.number < len(GATE) else 0.0  # the follow-up gate (none for the long beacon)
        values = [spec.number, spec.samples, reach, 1 if spec is longbeacon.LONG else 0, gate, preamble_samples(spec), int(spec.tone_bins[0]) - 1, int(spec.tone_bins[-1]) + 1, spec.step]  # its figures
        patterns[slot] = (values, PAD * spec.tone_bins[pattern_tones(spec.number)])  # and its tones, in fine steps
    return cfg, patterns, _totals_by_type(), _body_totals()  # everything


class Listener:  # the continuous receiver
    """Feed it audio at 12,000 samples per second with feed(); it returns the frames that have completed."""

    def __init__(self, window_s=WINDOW_S, step_s=STEP_S, incremental=True, compiled=None):  # set up an empty store
        self.window = int(window_s * FS)  # most samples kept
        self.step = int(step_s * FS)  # new samples needed before the next search
        self.store = np.zeros(0)  # the audio kept so far
        self.index = np.zeros(0, dtype=np.int64)  # the stream's number for each sample in the store (cutting frames out leaves gaps, so the numbers are kept, not worked out)
        self.total = 0  # the number the next sample fed will get, when the caller does not say
        self.fresh = 0  # samples added since the last search
        self.searches = 0  # searches so far (the long beacon is looked for on every LONG_EVERY-th)
        self.combiner = longbeacon.LongCombiner()  # adds up copies of the same long beacon heard minutes apart (receiver version 0.28)
        self.offered = {}  # long-beacon candidates already given to the combiner: place in the stream -> sample
        self.combined = []  # long beacons decoded by combining, waiting to be handed over
        self.on_near = None  # if set, called with the receiver's report whenever a Kestrel signature is seen but its header cannot be read
        self.near_audio, self.near_audio_sample = None, -1  # the audio of the latest near miss, while on_near is being called
        self.near_strong = []  # stream samples where strong near misses that were not likely Kestrel began (not cut out, so the stretch after each is not reported again; since 0.31R2)
        self.on_search = None  # if set, called after every search with (result, trace): the receiver's report and its list of candidates tried, with "sample" (stream numbers) added to each
        self.incremental = incremental  # search only the new audio (since 0.31), or the whole store every time (the reference)
        self.pending = []  # incremental search: candidates found, as dicts: level, stream (sample number where the pattern starts), offset_hz, quality
        self.unsearched = 0  # incremental search: samples not yet searched for the patterns of the speed levels
        self.unsearched_long = 0  # and for the long beacon's pattern (looked for on every fourth search)
        self.expect = None  # if set, called with no arguments for (this station's callsign, callsigns it expects to hear), to help read weak control frames (since 0.31R1)
        self.priors = []  # control frames whose bodies failed their check, kept so a later copy can be added to them (frame.Prior; since 0.31R1)
        use_core = incremental and (native.available() if compiled is None else compiled)  # the compiled store and candidate list (library interface 7), unless asked not to
        self.core = native.compiled_listener(*_core_settings(self.window, self.step)) if use_core else None  # the library's listener, or None for the Python one (the reference)

    def clear(self):  # forget everything heard so far
        """Empty the store (used after transmitting, so the station does not decode itself)."""
        self.store = np.zeros(0)  # nothing kept
        self.index = np.zeros(0, dtype=np.int64)  # and no numbers for it
        self.fresh = 0  # nothing new
        self.pending, self.unsearched, self.unsearched_long = [], 0, 0  # no candidates, and nothing to search
        if self.core is not None:  # the compiled listener keeps its own
            self.core.clear()  # emptied too

    def feed(self, samples, at=None):  # take in more audio
        """Add `samples` to the store and return a list of Heard frames that are now complete.

        `at` is the stream's number for the first of `samples` (see
        recorder.TimedSource); without it the listener counts for itself,
        from 0, which is right as long as every sample read is fed.
        """
        samples = np.asarray(samples, dtype=float)  # make sure it is an array of numbers
        if self.core is not None:  # the compiled listener stores the audio
            due = self.core.feed(samples, at)  # stored (and numbered)
            self.total = (self.total if at is None else int(at)) + len(samples)  # the number the next sample will get
            if not due:  # not enough new audio to be worth a search
                return []  # nothing yet
            found = []  # frames found in this search
            for _ in range(4):  # a search can turn up more than one frame; four is plenty
                heard = self._search_compiled()  # look for one whole frame
                if heard is None:  # none left
                    break  # done
                found.append(heard)  # keep it
            found, self.combined = found + self.combined, []  # and any long beacon that decoded by adding copies together
            return found  # everything that completed
        at = self.total if at is None else int(at)  # the number of the first new sample
        self.total = at + len(samples)  # the number the next one will get
        self.store = np.concatenate([self.store, samples])[-self.window:]  # append, keep only the last 100 seconds
        self.index = np.concatenate([self.index, np.arange(at, at + len(samples), dtype=np.int64)])[-self.window:]  # and their numbers, kept in step
        self.fresh += len(samples)  # count the new audio
        self.unsearched += len(samples)  # not yet searched for patterns
        self.unsearched_long += len(samples)  # nor for the long beacon's
        if self.fresh < self.step:  # not enough new audio to be worth a search
            return []  # nothing yet
        self.fresh = 0  # start counting again
        found = []  # frames found in this search
        for _ in range(4):  # a search can turn up more than one frame; four is plenty
            heard = self._search()  # look for one whole frame
            if heard is None:  # none left
                break  # done
            found.append(heard)  # keep it
        found, self.combined = found + self.combined, []  # and any long beacon that decoded by adding copies together
        return found  # everything that completed

    def _search(self):  # look for one whole frame in the store
        """Return a Heard for the strongest complete frame in the store, cutting it out; None if there is none."""
        return self._search_new() if self.incremental else self._search_whole()  # the incremental search, or the reference

    # ---- the incremental search (since 0.31) ----

    def _position(self, stream):  # where a stream sample is in the store
        """Return the store position of stream sample `stream`, or None if it is no longer there (slid out, or cut out with a frame)."""
        at = int(np.searchsorted(self.index, stream))  # where it would be
        return at if at < len(self.index) and int(self.index[at]) == stream else None  # there, or gone

    def _detect(self, x):  # look for new signature patterns in the newest audio
        """Add to the pending list the patterns found in the audio not yet searched; `x` is the store with static crashes removed."""
        end = len(x)  # the newest sample
        long_now = self.searches % LONG_EVERY == 0  # the long beacon's pattern is looked for on every fourth search
        levels = list(LEVELS) + ([longbeacon.LONG] if long_now else [])  # the patterns to look for this time
        jobs = []  # (pattern, where its piece begins) for every pattern with new audio to search
        for spec in levels:  # each one
            new = self.unsearched_long if spec is longbeacon.LONG else self.unsearched  # how much audio this pattern has not been looked for in
            if new <= 0:  # none
                continue  # nothing to do
            span = preamble_samples(spec)  # one whole pattern (twelve tones, the long beacon's too)
            jobs.append((spec, max(0, end - min(new, end) - span - 2 * spec.samples - int(CONTEXT_S * FS))))  # the pattern may have begun this far back, and some background besides

        def look(job):  # search one pattern's piece
            """Return the strongest few patterns found in the piece of `x` that `job` (pattern, start) names."""
            spec, begin = job  # the pattern, and where its piece begins
            piece = x[begin:end]  # the audio to search
            return detect_preamble(longbeacon.clean(piece), spec, whiten=True, fine=False) if spec is longbeacon.LONG else detect_preamble(piece, spec, fine=False)  # timed only coarsely (fine timing is done later for the few kept)

        if native.available() and len(jobs) > 1:  # the compiled search lets Python run the patterns side by side (it releases Python's lock while it works)
            results = list(_pool().map(look, jobs))  # all patterns at once, results in the same order as the jobs
        else:  # pure Python: one after another (side by side would gain little)
            results = [look(job) for job in jobs]  # in order
        for (spec, begin), found in zip(jobs, results):  # each pattern's candidates, in the usual order
            for candidate in found:  # each
                if spec is not longbeacon.LONG and candidate["quality"] < GATE[spec.number]:  # no stronger than chance matches in noise
                    continue  # not worth following up
                stream = self._number(begin + candidate["start"])  # its place in the stream
                same = [old for old in self.pending if old["level"] == spec.number and abs(old["stream"] - stream) < spec.samples]  # the same pattern found before (within a tone)
                if same:  # already on the list
                    if candidate["quality"] > same[0]["quality"]:  # better measured now
                        same[0].update(stream=stream, offset_hz=candidate["offset_hz"], quality=candidate["quality"])  # keep the better reading
                    continue  # nothing new
                self.pending.append({"level": spec.number, "stream": stream, "offset_hz": candidate["offset_hz"], "quality": candidate["quality"], "coarse": True, "since": None})  # a new candidate, timed coarsely, its header not yet tried
        self.unsearched = 0  # all searched now
        if long_now:  # and for the long pattern
            self.unsearched_long = 0  # too
        # Every candidate is kept until its frame has passed (see _search_new): one whose first header copy failed waits for its second copy at the end of the frame.

    def _search_new(self):  # the incremental search
        """Return a Heard for the strongest complete frame among the candidates, cutting it out; None if there is none."""
        if len(self.store) < FS:  # less than a second of audio: too little to be worth searching
            return None  # nothing to find
        trace = [] if self.on_search is not None else None  # the candidates tried, if anyone wants them
        self.searches += 1  # count it
        x = remove_steady(blank_impulses(self.store))  # the store with static crashes removed, and steady signals (carriers) notched out
        if self.unsearched > 0 or (self.unsearched_long > 0 and self.searches % LONG_EVERY == 0):  # new audio to look at
            self._detect(x)  # look for patterns in it
        wait = min(LONGEST_FRAME, self.window - 2 * self.step)  # how long a candidate whose header cannot be read is kept (its second header copy, at the end of the frame, may yet arrive)
        result, heard = RxResult(reason="no frame ready"), None  # what this search found
        for item in sorted(list(self.pending), key=lambda item: -item["quality"]):  # strongest first
            start = self._position(item["stream"])  # where it is in the store now
            if start is None:  # slid out, or cut out with a frame
                self.pending.remove(item)  # forget it
                continue  # next
            long = item["level"] == LONG_LEVEL  # a long beacon?
            spec = longbeacon.LONG if long else LEVELS[item["level"]]  # its level
            if long:  # a long beacon: no header; read it once it has all arrived
                if start + longbeacon.SAMPLES + spec.samples > len(self.store):  # still arriving (with a tone to spare for the fine timing)
                    continue  # wait
                self.pending.remove(item)  # read once only
                first = max(start - FS, 0)  # a second of audio before it, for the carrier check
                piece = longbeacon.clean(x[first:start + longbeacon.SAMPLES + FS])  # its stretch, with carriers removed
                refined = fine_time(piece, spec, {"start": float(start - first), "offset_hz": item["offset_hz"], "quality": item["quality"]})  # its start and frequency, finely
                start = first + int(round(refined["start"]))  # in store positions
                found = dict(refined, start=float(start))  # in the form the receiver takes
                long_failed = []  # its soft values, if it does not decode
                attempt = longbeacon.decode_at(piece, refined, RxResult(start=refined["start"], sync_quality=item["quality"]), failed=long_failed)  # read it
                attempt.start = float(start)  # in store positions
                if trace is not None:  # someone wants the details
                    trace.append({"level": LONG_LEVEL, "start": start, "offset_hz": item["offset_hz"], "quality": item["quality"], "header": "long", "ok": attempt.ok, "reason": attempt.reason, "snr_db": float(attempt.snr_db)})  # this try
                for candidate, soft in long_failed:  # not readable alone
                    self._combine(dict(candidate, start=float(start)), soft)  # try it with the copies kept
                if attempt.ok:  # a long beacon
                    result = attempt  # this search's result
                    heard = self._take(attempt, start, start + longbeacon.SAMPLES)  # hand it over
                    break  # one frame per search
                continue  # next candidate
            if item["coarse"]:  # not yet finely timed
                if start + preamble_samples(spec) + spec.samples > len(self.store):  # its pattern (and a tone to spare) has not all arrived
                    continue  # wait
                refined = fine_time(x, spec, {"start": float(start), "offset_hz": item["offset_hz"], "quality": item["quality"]})  # its start and frequency, finely
                start = int(round(refined["start"]))  # the store position, refined
                item.update(stream=self._number(start), offset_hz=refined["offset_hz"], coarse=False, start_fine=refined["start"] - start)  # kept, with the part of a sample the timing found
            found = {"start": float(start) + item.get("start_fine", 0.0), "offset_hz": item["offset_hz"], "quality": item["quality"]}  # in the form the receiver takes
            header, how = item.get("header"), item.get("how", "")  # the header, if it has been read already
            if header is None:  # not yet
                since = self._position(item["since"]) if item["since"] is not None else None  # where the store ended at the last try, if there was one (None if that sample has gone)
                header, how = _read_header_how(x, found["start"] + preamble_samples(spec), item["offset_hz"], spec, since=None if since is None else since + 1)  # its header, if one can be read yet (only new places are tried again)
                if header is not None:  # read: keep it, so it need not be read again while the rest of the frame arrives
                    item["header"], item["how"] = header, how  # kept with the candidate
                elif found["start"] + preamble_samples(spec) + HEADER_SYMBOLS // 2 * spec.samples <= len(x):  # the first header copy had all arrived, so it was really tried
                    item["since"] = int(self.index[-1])  # remember how far the store reached at this try
            if header is None:  # none yet
                if trace is not None:  # someone wants the details
                    trace.append({"level": item["level"], "start": start, "offset_hz": item["offset_hz"], "quality": item["quality"], "header": ""})  # this try
                if start + wait <= len(self.store):  # its whole frame has passed and no header was ever read
                    self.pending.remove(item)  # let it go
                    self._near_miss(RxResult(reason="header check failed", start=float(start), sync_quality=item["quality"], offset_hz=item["offset_hz"], seen_level=item["level"]), x=x, found=found)  # but report a clear signature that could not be read
                continue  # next candidate
            body = _body_total(header)  # its body length (None for a frame type that does not exist: a chance header from noise)
            if body is None:  # no such frame
                self.pending.remove(item)  # let it go
                continue  # next candidate
            end = start + (PREAMBLE_TONES + HEADER_SYMBOLS + body) * spec.samples  # where its frame ends
            if end > len(self.store):  # still arriving
                continue  # wait for the rest
            self.pending.remove(item)  # decoded once only
            attempt = receive(x, blank=False, notch=False, trace=trace, candidates=[(found, spec)], hints=self._hints(start))  # read the whole frame (already blanked and notched), with help for a weak control frame
            self._remember_failure(attempt, start)  # a control frame that failed is kept, to add to its next copy
            if attempt.ok:  # it decoded
                result, heard = attempt, self._take(attempt, start, end)  # hand it over
                break  # one frame per search
            limit = MIN_SNR_DB[attempt.level] if attempt.level >= 0 else 0.0  # the weakest signal its level decodes
            believable = attempt.reason == "body check failed" and np.isfinite(attempt.snr_db) and attempt.snr_db >= limit - FAILED_SNR_SLACK_DB  # do its pilots look like a real signal?
            if believable:  # a real frame that failed its check: hand it over, so the station can combine it with a retry
                result, heard = attempt, self._take(attempt, start, end)  # as the whole-store search did
                break  # one frame per search
        if trace is not None:  # someone keeps a signal log
            for step in trace:  # every candidate tried
                step["sample"] = self._number(step["start"])  # its place in the stream
            result.sample = heard.result.sample if heard is not None else -1  # where the frame began, if one was found
            self.on_search(result, trace)  # hand it over
        return heard  # the frame, or None

    # ---- the incremental search with the compiled store and candidate list (library interface 7) ----

    def _search_compiled(self):  # the incremental search, its bookkeeping in the library
        """Return a Heard for the strongest complete frame among the candidates, as _search_new does; None if there is none."""
        core = self.core  # the library's listener
        if not core.begin(self.on_near is not None):  # blank, notch and search the newest audio (False: too little audio yet)
            return None  # nothing to find
        self.searches = core.searches()  # kept in step, for anyone who asks
        trace = [] if self.on_search is not None else None  # the candidates tried, if anyone wants them
        x = core.x()  # the processed store the frames are read from (the library's memory, valid until the next search)
        result, heard = RxResult(reason="no frame ready"), None  # what this search found
        while True:  # the candidates, strongest first, as the library hands them over
            kind, ev = core.next()  # the next event
            if kind == 0:  # no more
                break  # this search is done
            level, start, found_start, offset, quality = int(ev[1]), int(ev[2]), float(ev[3]), float(ev[4]), float(ev[5])  # the candidate
            if kind == 3:  # a candidate whose header could not be read (yet)
                if trace is not None:  # someone wants the details
                    trace.append({"level": level, "start": start, "offset_hz": offset, "quality": quality, "header": ""})  # this try
                if ev[6] == 1 and self.on_near is not None:  # also a signature whose frame has passed without a header: perhaps a near miss
                    near = RxResult(reason="header check failed", start=float(start), sync_quality=quality, offset_hz=offset, seen_level=level)  # what was seen
                    self._near_miss(near, x=x, found={"start": found_start, "offset_hz": offset}, audio=core.near_audio(), audio_sample=int(ev[7]))  # reported if worth it, as the Python bookkeeping does
                continue  # next candidate
            if kind == 2:  # a long beacon, all arrived
                spec = longbeacon.LONG  # its pattern and tone length
                first = max(start - FS, 0)  # a second of audio before it, for the carrier check
                piece = longbeacon.clean(x[first:start + longbeacon.SAMPLES + FS])  # its stretch, with carriers removed
                refined = fine_time(piece, spec, {"start": float(start - first), "offset_hz": offset, "quality": quality})  # its start and frequency, finely
                start = first + int(round(refined["start"]))  # in store positions
                long_failed = []  # its soft values, if it does not decode
                attempt = longbeacon.decode_at(piece, refined, RxResult(start=refined["start"], sync_quality=quality), failed=long_failed)  # read it
                attempt.start = float(start)  # in store positions
                if trace is not None:  # someone wants the details
                    trace.append({"level": LONG_LEVEL, "start": start, "offset_hz": offset, "quality": quality, "header": "long", "ok": attempt.ok, "reason": attempt.reason, "snr_db": float(attempt.snr_db)})  # this try
                for candidate, soft in long_failed:  # not readable alone
                    self._combine(dict(candidate, start=float(start)), soft)  # try it with the copies kept
                if attempt.ok:  # a long beacon
                    result = attempt  # this search's result
                    heard = self._take(attempt, start, start + longbeacon.SAMPLES)  # hand it over
                    break  # one frame per search
                continue  # next candidate
            spec = LEVELS[level]  # a frame at this level, all arrived, its header read
            end = int(ev[6])  # where it ends
            found = {"start": found_start, "offset_hz": offset, "quality": quality}  # in the form the receiver takes
            attempt = receive(x, blank=False, notch=False, trace=trace, candidates=[(found, spec)], hints=self._hints(start))  # read the whole frame (already blanked and notched), with help for a weak control frame
            self._remember_failure(attempt, start)  # a control frame that failed is kept, to add to its next copy
            if attempt.ok:  # it decoded
                result, heard = attempt, self._take(attempt, start, end)  # hand it over
                break  # one frame per search
            limit = MIN_SNR_DB[attempt.level] if attempt.level >= 0 else 0.0  # the weakest signal its level decodes
            believable = attempt.reason == "body check failed" and np.isfinite(attempt.snr_db) and attempt.snr_db >= limit - FAILED_SNR_SLACK_DB  # do its pilots look like a real signal?
            if believable:  # a real frame that failed its check: hand it over, so the station can combine it with a retry
                result, heard = attempt, self._take(attempt, start, end)  # as the whole-store search did
                break  # one frame per search
        if trace is not None:  # someone keeps a signal log
            for step in trace:  # every candidate tried
                step["sample"] = self._number(step["start"])  # its place in the stream
            result.sample = heard.result.sample if heard is not None else -1  # where the frame began, if one was found
            self.on_search(result, trace)  # hand it over
        return heard  # the frame, or None

    def _size(self):  # samples kept
        """Return how many samples the store holds (the library's, when it keeps it)."""
        return self.core.size() if self.core is not None else len(self.store)  # either way

    def _slice(self, start, end):  # a copy of a stretch of the store
        """Return a copy of store positions start (not below 0) to end."""
        start = max(int(start), 0)  # not before the beginning
        return self.core.copy(start, end) if self.core is not None else self.store[start:end].copy()  # either way

    def _hints(self, start):  # help for reading weak control frames
        """Return the frame.Hints for a candidate at store position `start`: expected callsigns, and earlier failed copies (never the frame itself)."""
        own, calls = ("", ())  # nothing expected unless the station says
        if self.expect is not None:  # the station can say
            try:  # it is called from the receiving thread
                own, calls = self.expect()  # its callsign, and those it expects
            except Exception:  # whatever went wrong there, keep receiving
                own, calls = ("", ())  # carry on without
        here = self._number(start) if 0 <= start < self._size() else -1  # this candidate's place in the stream
        priors = [p for p in self.priors if here < 0 or abs(p.sample - here) > FS]  # earlier copies, not this frame itself
        return Hints(own=own or "", calls=tuple(calls or ()), priors=priors, base=-1)  # the hints (positions already handled here)

    def _remember_failure(self, attempt, start):  # keep a failed control frame for combining
        """Keep the soft bits of a control frame that failed its check, so a later copy can be added to them."""
        if attempt.frame_type not in CONTROL_BITS or attempt.body_llrs is None or attempt.reason != "body check failed":  # not a control frame that failed its check
            return  # nothing to keep
        here = self._number(start) if 0 <= start < self._size() else -1  # where it began in the stream
        newest = self._number(self._size() - 1) if self._size() else here  # the latest sample heard
        self.priors = [p for p in self.priors if p.sample < 0 or newest - p.sample <= PRIOR_KEEP_S * FS]  # drop copies too old to be the same transmission round
        if any(p.sample >= 0 and abs(p.sample - here) <= FS for p in self.priors):  # this frame is kept already
            return  # once is enough
        self.priors.append(Prior(attempt.frame_type, attempt.body_llrs, float(attempt.offset_hz), here))  # kept
        self.priors = self.priors[-PRIOR_MOST:]  # only the most recent

    def _take(self, result, start, end):  # hand a frame over (and cut it out of the store if it decoded)
        """Return a Heard for the frame from store position `start` to `end`.

        A frame that decoded is cut out of the store, so it is not found again.
        A frame that failed its check is handed over (the station may add it to
        a retry) but left in place (since 0.32): a chance match inside another,
        stronger frame can pass a header check, and cutting it out would take
        that real frame with it. The incremental search does not search the
        same audio twice, so it is not reported again.
        """
        result.sample = self._number(start)  # where it began in the stream
        pad = int(PAD_S * FS)  # a little audio either side
        audio = self._slice(start - pad, end + pad)  # the frame's own stretch of audio
        first = self._number(max(start - pad, 0))  # the stream's number for its first sample
        if result.ok:  # decoded
            self._cut(start, end)  # cut the frame out so it is not found again
        return Heard(result, audio, first)  # hand it over

    # ---- the whole-store search (before 0.31; kept as the reference) ----

    def _search_whole(self):  # look for one whole frame, searching the whole store
        """Return a Heard for the strongest complete frame in the store, cutting it out; None if there is none."""
        if len(self.store) < FS:  # less than a second of audio: too little to be worth searching
            return None  # nothing to find
        trace = [] if self.on_search is not None else None  # the receiver's candidate list, if anyone wants it
        self.searches += 1  # count it
        long_failed = []  # long-beacon candidates that were all there but did not decode alone
        result = receive(self.store, trace=trace, long_beacons=self.searches % LONG_EVERY == 0, long_failed=long_failed, hints=self._hints(-1))  # run the modem receiver over everything kept (the long pattern too, every fourth time), with help for weak control frames
        self._remember_failure(result, int(round(result.start)))  # a control frame that failed is kept, to add to its next copy
        for candidate, soft in long_failed:  # each may be one copy of a beacon heard before, or to be heard again
            self._combine(candidate, soft)  # try it with the copies kept
        result.sample = self._number(result.start)  # where it began in the stream
        if trace is not None:  # someone keeps a signal log
            for step in trace:  # every candidate tried
                step["sample"] = self._number(step["start"])  # its place in the stream
            self.on_search(result, trace)  # hand it over
        if result.level < 0:  # no header was read
            self._near_miss(result)  # but a signature may still have been seen: report that
            return None  # nothing there (or only noise)
        start = int(round(result.start))  # where the frame begins in the store
        end = start + frame_samples(result)  # where it ends
        if end > len(self.store):  # the frame is still arriving
            return None  # wait for the rest
        if not result.ok:  # the whole frame is here but it failed its check
            limit = longbeacon.MIN_SNR_DB if result.level == LONG_LEVEL else MIN_SNR_DB[result.level]  # the weakest signal its level decodes
            believable = np.isfinite(result.snr_db) and result.snr_db >= limit - FAILED_SNR_SLACK_DB  # do its pilots look like a real signal?
            if result.reason != "body check failed" or not believable:  # noise that happened to pass a header check
                return None  # ignore it
        pad = int(PAD_S * FS)  # a little audio either side
        audio = self.store[max(start - pad, 0):end + pad].copy()  # the frame's own stretch of audio
        first = self._number(max(start - pad, 0))  # the stream's number for its first sample
        self._cut(start, end)  # cut the frame out so it is not found again
        return Heard(result, audio, first)  # hand it over

    def _combine(self, candidate, soft):  # a long-beacon candidate that did not decode alone
        """Give `soft` to the combiner once; if it decodes with earlier copies, queue the long beacon to be handed over."""
        start = int(round(candidate["start"]))  # where it begins in the store
        soft.sample = self._number(start)  # and in the stream
        place = soft.sample // (2 * longbeacon.LONG.samples)  # the same candidate found again lands in the same place, give or take
        if any(key in self.offered for key in (place - 1, place, place + 1)):  # given to the combiner already
            return  # once is enough
        self.offered[place] = soft.sample  # remember it
        for key in [key for key, sample in self.offered.items() if soft.sample - sample > 4 * self.window]:  # places long gone from the store
            del self.offered[key]  # forget them
        out = self.combiner.offer(soft, soft.sample / FS)  # try it with the copies kept (the stream's own clock)
        if out is None:  # not readable yet
            return  # kept for the next copy
        fields, margin, copies = out  # the beacon, how clearly it stood out, and how many copies it took
        result = RxResult(start=float(start), sync_quality=soft.quality, offset_hz=soft.offset_hz, drift_hz_s=soft.drift_hz_s, level=LONG_LEVEL, frame_type=FRAME_TYPE_LONG, header_copy="none (long beacon)", sample=soft.sample)  # a report for it, placed at the newest copy
        longbeacon._fill(result, fields, margin, copies)  # the fields and the signal reading (per copy)
        self.combined.append(Heard(result, self._slice(start, start + longbeacon.SAMPLES), self._number(max(start, 0))))  # hand it over with the newest copy's audio

    def _number(self, position):  # a place in the store, as a number in the stream
        """Return the stream's number for store position `position` (worked out past either end of the store)."""
        position = int(round(position))  # whole samples
        if self.core is not None:  # the library keeps the numbers
            return self.core.number(position)  # worked out there, the same way
        if len(self.index) == 0:  # nothing stored
            return self.total + position  # count on from the newest sample
        if position < 0:  # before the first stored sample
            return int(self.index[0]) + position  # count back from it
        if position >= len(self.index):  # after the last
            return int(self.index[-1]) + 1 + position - len(self.index)  # count on from it
        return int(self.index[position])  # the number kept for it

    def _cut(self, start, end):  # take a stretch out of the store
        """Remove store positions start to end, and their numbers."""
        start = max(start, 0)  # not before the beginning
        if self.core is not None:  # the library keeps the store
            self.core.cut(start, end)  # cut there
            return  # done
        self.store = np.concatenate([self.store[:start], self.store[end:]])  # the audio
        self.index = np.concatenate([self.index[:start], self.index[end:]])  # and its numbers

    def _near_miss(self, result, x=None, found=None, audio=None, audio_sample=-1):  # a signature with no readable header
        """Call on_near once for a Kestrel signature whose header could not be read, when it is worth reporting (see worth_reporting).

        `x` is the audio the signature was found in (the store, if not
        given) and `found` its start and frequency (the result's, if not
        given); how many of its pattern tones stand out is counted there
        and kept in the result's `pattern_tones` (since 0.31R2). `audio` and
        `audio_sample` are its clip and where that began in the stream, when
        the library kept them (otherwise they are taken from the store).

        A near miss likely to be Kestrel has its stretch cut out, so neither
        it nor the chance matches inside the same signal are reported again.
        One that is only strong (another mode's signal, most likely) is
        reported for the signal log but cuts nothing, so it cannot remove a
        real Kestrel pattern near it; others within the same stretch after
        it are not reported (since 0.31R2).
        """
        if self.on_near is None or result.seen_level < 0 or result.seen_level >= len(LEVELS):  # nobody wants to know, or no level stood out
            return  # nothing to report
        start = int(round(result.start))  # where the signature begins in the store
        span = (PREAMBLE_TONES + HEADER_SYMBOLS // 2) * LEVELS[0].samples  # the longest a preamble and first header copy can be (the slowest level): the level guess from a pattern alone is not reliable
        wait = min(LONGEST_FRAME, self.window - 2 * self.step)  # the whole frame, or as long as the store can hold the signature (the longest frame outlasts the 100-second store)
        if start + wait > self._size():  # the second header copy, at the end of the frame, may not have arrived yet
            return  # look again later
        x = self.store if x is None else x  # where to count the pattern's tones
        found = found if found is not None else {"start": float(result.start), "offset_hz": result.offset_hz}  # and where in it
        result.pattern_tones = pattern_seen(x, found, LEVELS[result.seen_level])  # how much of the pattern is really there
        if not worth_reporting(result):  # neither likely Kestrel nor strong
            return  # not reported
        here = self._number(max(start, 0))  # where it began in the stream
        likely = likely_kestrel(result)  # a real Kestrel frame, by the tone test
        if not likely:  # only strong
            if any(abs(here - other) < span for other in self.near_strong):  # inside the stretch of one reported already
                return  # the same signal again
            self.near_strong = [other for other in self.near_strong if here - other < 2 * span] + [here]  # remembered (recent ones only)
        self.near_audio = audio if audio is not None else self._slice(start, start + span)  # the signature's audio, for a signal log that keeps clips
        self.near_audio_sample = audio_sample if audio is not None else here  # and where it began in the stream
        self.on_near(result)  # report it
        if likely:  # a real Kestrel pattern
            self._cut(start, start + span)  # cut that stretch out so the same signature is not reported again
