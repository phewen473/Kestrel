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
from modem.blanker import blank_impulses  # removes static crashes before searching
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
NEAR_QUALITY = 6.0  # a signature pattern standing this far above the background counts as a "near miss" when its header cannot be read (noise alone stays below about 3.5 in simulation; 6 leaves a margin for real band noise)
LONGEST_FRAME = (PREAMBLE_TONES + HEADER_SYMBOLS + max(_body_totals())) * LEVELS[0].samples  # samples in the longest frame there is (the largest message at the slowest level)
LONG_EVERY = 4  # the long beacon's pattern is looked for on every fourth search only: it costs about 0.4 s a search, and a long beacon lasts a minute, so finding it a few seconds later loses nothing
NEAR_QUALITY_MAX = 10000.0  # above this the measure has broken down (stretches of digital silence), so it is not a signal
CONTEXT_S = 4.0  # incremental search: audio searched before the newest, beyond what one pattern needs, so the background is measured fairly
GATE = (0.002, 0.002, 0.003, 0.010, 0.012)  # incremental search: a pattern scoring below this (by level) is not followed up. Measured on simulated noise and frames, the strongest chance match scored 0.001, 0.001, 0.002, 0.005 and 0.008, and real frames 1 dB below each level's decoding limit (steady and fading) at least 0.004, 0.006, 0.005, 0.028 and 0.032 (one L4 frame in 40 was not found at all). The long beacon has no gate: copies too weak to read alone are kept for adding together


@dataclass  # a plain record
class Heard:  # one frame taken out of the stream
    """A frame the Listener found: the receiver's report, and the stretch of audio holding the frame."""

    result: object  # the receiver's report (an RxResult); its sample field says where the frame began in the stream
    audio: np.ndarray  # the frame's audio, with a little either side
    audio_sample: int = -1  # the stream's number for the first sample of `audio`


def frame_samples(result):  # how long is the frame this report describes?
    """Return the length in samples of the frame whose header `result` came from."""
    if result.level == LONG_LEVEL:  # a long beacon: a fixed length
        return longbeacon.SAMPLES  # pattern and body
    if result.frame_type in CONTROL_BITS:  # a beacon, answer, acknowledgment or identification
        body = control_layout(result.frame_type)["total"]  # its body tones
    else:  # a message frame
        body = body_layout(result.size_class)["total"]  # its body tones
    return (PREAMBLE_TONES + HEADER_SYMBOLS + body) * LEVELS[result.level].samples  # preamble + header + body


class Listener:  # the continuous receiver
    """Feed it audio at 12,000 samples per second with feed(); it returns the frames that have completed."""

    def __init__(self, window_s=WINDOW_S, step_s=STEP_S, incremental=True):  # set up an empty store
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
        self.on_search = None  # if set, called after every search with (result, trace): the receiver's report and its list of candidates tried, with "sample" (stream numbers) added to each
        self.incremental = incremental  # search only the new audio (since 0.31), or the whole store every time (the reference)
        self.pending = []  # incremental search: candidates found, as dicts: level, stream (sample number where the pattern starts), offset_hz, quality
        self.unsearched = 0  # incremental search: samples not yet searched for the patterns of the speed levels
        self.unsearched_long = 0  # and for the long beacon's pattern (looked for on every fourth search)

    def clear(self):  # forget everything heard so far
        """Empty the store (used after transmitting, so the station does not decode itself)."""
        self.store = np.zeros(0)  # nothing kept
        self.index = np.zeros(0, dtype=np.int64)  # and no numbers for it
        self.fresh = 0  # nothing new
        self.pending, self.unsearched, self.unsearched_long = [], 0, 0  # no candidates, and nothing to search

    def feed(self, samples, at=None):  # take in more audio
        """Add `samples` to the store and return a list of Heard frames that are now complete.

        `at` is the stream's number for the first of `samples` (see
        recorder.TimedSource); without it the listener counts for itself,
        from 0, which is right as long as every sample read is fed.
        """
        samples = np.asarray(samples, dtype=float)  # make sure it is an array of numbers
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
        for spec in levels:  # each one
            new = self.unsearched_long if spec is longbeacon.LONG else self.unsearched  # how much audio this pattern has not been looked for in
            if new <= 0:  # none
                continue  # nothing to do
            span = preamble_samples(spec)  # one whole pattern (twelve tones, the long beacon's too)
            begin = max(0, end - min(new, end) - span - 2 * spec.samples - int(CONTEXT_S * FS))  # the pattern may have begun this far back, and some background besides
            piece = x[begin:end]  # the audio to search
            found = detect_preamble(longbeacon.clean(piece), spec, whiten=True, fine=False) if spec is longbeacon.LONG else detect_preamble(piece, spec, fine=False)  # the strongest few patterns there, timed only coarsely (fine timing is done later for the few kept)
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
        x = blank_impulses(self.store)  # the store with static crashes removed
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
                    self._near_miss(RxResult(reason="header check failed", start=float(start), sync_quality=item["quality"], offset_hz=item["offset_hz"], seen_level=item["level"]))  # but report a clear signature that could not be read
                continue  # next candidate
            end = start + (PREAMBLE_TONES + HEADER_SYMBOLS + _body_total(header)) * spec.samples  # where its frame ends
            if end > len(self.store):  # still arriving
                continue  # wait for the rest
            self.pending.remove(item)  # decoded once only
            attempt = receive(x, blank=False, trace=trace, candidates=[(found, spec)])  # read the whole frame
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

    def _take(self, result, start, end):  # hand a frame over and cut it out of the store
        """Return a Heard for the frame from store position `start` to `end`, and cut it out of the store."""
        result.sample = self._number(start)  # where it began in the stream
        pad = int(PAD_S * FS)  # a little audio either side
        audio = self.store[max(start - pad, 0):end + pad].copy()  # the frame's own stretch of audio
        first = self._number(max(start - pad, 0))  # the stream's number for its first sample
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
        result = receive(self.store, trace=trace, long_beacons=self.searches % LONG_EVERY == 0, long_failed=long_failed)  # run the modem receiver over everything kept (the long pattern too, every fourth time)
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
        self.combined.append(Heard(result, self.store[max(start, 0):start + longbeacon.SAMPLES].copy(), self._number(max(start, 0))))  # hand it over with the newest copy's audio

    def _number(self, position):  # a place in the store, as a number in the stream
        """Return the stream's number for store position `position` (worked out past either end of the store)."""
        position = int(round(position))  # whole samples
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
        self.store = np.concatenate([self.store[:start], self.store[end:]])  # the audio
        self.index = np.concatenate([self.index[:start], self.index[end:]])  # and its numbers

    def _near_miss(self, result):  # a signature with no readable header
        """Call on_near once for a clear Kestrel signature whose header could not be read (a frame heard but too weak or faded to decode)."""
        if self.on_near is None or result.seen_level < 0 or not NEAR_QUALITY <= result.sync_quality <= NEAR_QUALITY_MAX:  # nobody wants to know, nothing stood out, or the measure broke down (digital silence)
            return  # nothing to report
        start = int(round(result.start))  # where the signature begins in the store
        span = (PREAMBLE_TONES + HEADER_SYMBOLS // 2) * LEVELS[0].samples  # the longest a preamble and first header copy can be (the slowest level): the level guess from a pattern alone is not reliable
        wait = min(LONGEST_FRAME, self.window - 2 * self.step)  # the whole frame, or as long as the store can hold the signature (the longest frame outlasts the 100-second store)
        if start + wait > len(self.store):  # the second header copy, at the end of the frame, may not have arrived yet
            return  # look again later
        self.near_audio = self.store[max(start, 0):start + span].copy()  # the signature's audio, for a signal log that keeps clips
        self.near_audio_sample = self._number(max(start, 0))  # and where it began in the stream
        self.on_near(result)  # report it
        self._cut(start, start + span)  # and cut that stretch out so the same signature is not reported again
