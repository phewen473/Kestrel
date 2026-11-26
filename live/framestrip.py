"""The frame strip under the receive scope (since 0.37): a Kestrel frame as it arrives.

The listener reports, after each search, the frames it is following and
those that have finished (Listener.progress). FrameStrip keeps the one to
show and the parts of the message it belongs to, and turns them into what
the panel draws: four segments (pattern, header, body, and the pattern and
header again that end every frame since signal version 0.43),
each waiting, arriving, passed, weak, failed or never arrived; the body's
clarity tone by tone; a note under each segment; and a box for each part
of the message. It draws nothing itself, so it can be tested without a
window.

What the strip can know, and when:
- nothing until a frame's preamble has all arrived and stands out (or its
  header has been read): no receiver can tell a frame is starting sooner;
- the body's length only once the header has been read (until then the
  body is drawn dashed);
- whether the body passed its check only when all of it is in (while it
  arrives, the colors show how clearly each tone stood out, not the
  verdict).
"""

import threading  # the station's thread updates it while the window's thread draws it
import time  # wall-clock time, to move the arriving frame smoothly between searches

from modem.params import FS, PREAMBLE_TONES  # the sample rate and the preamble's length in tones

KINDS = {0: "Message", 1: "Addressed message", 2: "Beacon", 3: "Answer", 4: "Acknowledgment", 5: "Identification", 6: "Long beacon", 7: "Mail notice"}  # frame type -> name, as the strip shows it
MESSAGE_TYPES = (0, 1)  # the frame types that carry parts of a message
HEADER_TONES = 12  # tones in one header copy
GOOD_DB, FAIR_DB = 6.0, 3.0  # a body tone whose strongest slot stands this far over the next is clear (green), or readable (amber); below, lost (red)
TAIL_SHARE = 0.2  # a failed body whose last fifth (or more) came through lost is shown as cut off where the signal went
MESSAGE_KEEP_S = 600.0  # a message's parts are kept together for ten minutes after its last part was heard
STATION_MATCH_S = 5.0  # the station's own decode of a frame comes within this many seconds of the listener's
STEPS_KEEP_S = 300.0  # power steps read before a beacon stay shown five minutes, unless a message comes in meanwhile (since 0.38)


def tone_state(db):  # how one body tone came through
    """Return "good", "fair" or "bad" for a body tone's clarity in dB (strongest slot over the next)."""
    return "good" if db >= GOOD_DB else "fair" if db >= FAIR_DB else "bad"  # three bands


def cut_point(clarity):  # where a failed body's signal went, if it went
    """Return the share (0 to 1) of the body after which every tone was lost, when that last stretch is at least TAIL_SHARE of the body; None otherwise."""
    if not clarity:  # nothing measured
        return None  # nothing to say
    last = len(clarity)  # one past the last tone that came through
    while last > 0 and clarity[last - 1] < FAIR_DB:  # lost tones at the end
        last -= 1  # step back over them
    return last / len(clarity) if (len(clarity) - last) >= TAIL_SHARE * len(clarity) else None  # cut there, if the lost stretch is long enough


class FrameStrip:  # what the strip shows
    """Keeps the frame to show and its message's parts; view() gives what to draw."""

    def __init__(self, clock=time.monotonic):  # `clock` gives seconds (a stand-in in tests)
        self.clock = clock  # the clock
        self.lock = threading.Lock()  # updated from the station's thread, read from the window's
        self.frame = None  # the frame shown: a dict (see _new_frame), or None while nothing has been heard
        self.message = None  # the message the frame belongs to: {"parts", "status", "origin", "when"}, or None
        self.steps = None  # the latest power steps read before a beacon: {"reading", "origin", "when"}, or None (since 0.38)

    # ---- from the receiver ----

    def update(self, progress):  # a listener's report (Listener.progress)
        """Take a listener's report: the frames arriving and those finished since the last one."""
        with self.lock:  # one thread at a time
            now = self.clock()  # when
            frames = progress.get("frames") or []  # arriving
            for outcome in progress.get("outcomes") or []:  # finished, oldest first
                self._finish(outcome, now)  # shown as finished
            chosen = self._choose(frames)  # the frame to show now, if any
            if chosen is None:  # none arriving
                return  # the last one stays shown
            same = self.frame is not None and self._same(self.frame["stream"], chosen["stream"], chosen["tone_s"])  # the frame shown already?
            if same and self.frame["outcome"] is not None:  # it finished in this very report
                return  # its outcome stands
            if not same:  # a new frame
                self.frame = self._new_frame(chosen)  # shown from now on
            self.frame.update(level=chosen["level"], long=chosen["long"], offset_hz=chosen["offset_hz"], tone_s=chosen["tone_s"], total_s=chosen["total_s"],  # (continued)
                              header=chosen["header"], tried=chosen["tried"], clarity=list(chosen["clarity"]), arrived_s=chosen["arrived_s"], at=now)  # brought up to date

    def station_result(self, result):  # the station's own decode of a frame (it may add an earlier copy, so it can pass where the listener's try failed)
        """Take the station's report on a frame: a decode that passed corrects a failed frame shown, and names the message's sender."""
        if result is None or not getattr(result, "ok", False):  # nothing better than what is shown
            return  # nothing to do
        with self.lock:  # one thread at a time
            now = self.clock()  # when
            if getattr(result, "power_steps", None) is not None:  # power steps were read before this beacon (since 0.38)
                self.steps = {"reading": result.power_steps, "origin": (result.fields or {}).get("origin", ""), "when": now}  # shown beside the frame
            frame = self.frame  # the frame shown
            if frame is not None and frame["outcome"] is not None and now - frame["done_at"] <= STATION_MATCH_S and frame["level"] == result.level:  # the frame just finished
                if not frame["outcome"]["ok"]:  # it failed alone
                    frame["outcome"] = dict(frame["outcome"], ok=True, reason="", combined=True)  # but passed with an earlier copy added
                    self._part(result.frame_type, result.part, result.parts, True, now)  # its part too
            if result.frame_type in MESSAGE_TYPES and self.message is not None and getattr(result, "origin", ""):  # a message with a named sender
                self.message["origin"] = result.origin  # named

    # ---- inside ----

    @staticmethod
    def _same(a, b, tone_s):  # two stream places, the same frame?
        """Return True when two stream samples are within two tones of each other."""
        return abs(a - b) <= 2 * tone_s * FS  # the same frame, give or take the timing

    @staticmethod
    def _choose(frames):  # the frame to show among those arriving
        """Return the frame to show: one whose header has been read, else the strongest; the latest of either."""
        if not frames:  # none
            return None  # nothing
        read = [f for f in frames if f["header"] is not None or f["long"]]  # known frames
        pool = read or frames  # those, or the rest
        return max(pool, key=lambda f: (f["stream"], f["quality"]))  # the newest (then the strongest)

    @staticmethod
    def _new_frame(f):  # a frame newly shown
        """Return the dict kept for a frame now shown."""
        return {"stream": f["stream"], "level": f["level"], "long": f["long"], "offset_hz": f["offset_hz"], "tone_s": f["tone_s"], "total_s": f["total_s"], "header": f["header"],  # (continued)
                "tried": f["tried"], "clarity": [], "arrived_s": 0.0, "at": 0.0, "outcome": None, "done_at": 0.0}  # nothing finished yet

    def _finish(self, outcome, now):  # a frame finished
        """Mark the frame shown as finished with `outcome` (or show a frame that finished between two reports)."""
        frame = self.frame  # the frame shown
        tone_s = frame["tone_s"] if frame is not None else 1.0  # its tone length
        if frame is None or not self._same(frame["stream"], outcome["stream"], tone_s):  # not the frame shown
            if outcome.get("reason") == "header unreadable" or outcome.get("ok") or outcome.get("frame_type", -1) >= 0:  # worth showing on its own
                frame = self.frame = {"stream": outcome["stream"], "level": outcome.get("level", -1), "long": outcome.get("frame_type") == 6, "offset_hz": 0.0, "tone_s": tone_s,  # (continued)
                                      "total_s": None, "header": None, "tried": False, "clarity": [], "arrived_s": 0.0, "at": now, "outcome": None, "done_at": 0.0}  # shown, with what is known
            else:  # nothing to show
                return  # skipped
        frame["outcome"] = dict(outcome)  # finished
        frame["done_at"] = now  # when
        if frame["header"] is None and outcome.get("frame_type", -1) >= 0 and outcome.get("reason") != "header unreadable":  # the header was read after all (from the second copy)
            frame["header"] = {"frame_type": outcome["frame_type"], "part": outcome.get("part", 0), "parts": outcome.get("parts", 1), "how": outcome.get("header_copy", "")}  # as the receiver read it
        if outcome.get("frame_type") in MESSAGE_TYPES and outcome.get("reason") != "header unreadable":  # a part of a message
            self._part(outcome["frame_type"], outcome.get("part", 0), outcome.get("parts", 1), bool(outcome.get("ok")), now)  # counted

    def _part(self, frame_type, part, parts, ok, now):  # one part of a message, passed or failed
        """Record part `part` (0-based) of a `parts`-part message as passed or failed."""
        if frame_type not in MESSAGE_TYPES or parts < 1 or not 0 <= part < parts:  # not a part of a message
            return  # nothing
        m = self.message  # the message being followed
        fresh = m is None or m["parts"] != parts or now - m["when"] > MESSAGE_KEEP_S or (m["status"][part] == "good" and all(s == "good" for s in m["status"]))  # a different message
        if fresh or (m["status"][part] == "good" and part == 0):  # a new message (or a new one starting again at part 1)
            m = self.message = {"parts": parts, "status": [None] * parts, "origin": "", "when": now}  # started
        if m["status"][part] != "good":  # a passed part stays passed (a later copy that fails changes nothing)
            m["status"][part] = "good" if ok else "bad"  # marked
        m["when"] = now  # heard now

    # ---- for the panel ----

    def view(self):  # what to draw now
        """Return the strip's picture as plain values: title, right, segs (4 states), notes (4), clarity (list of states), progress (0-1 or None), parts (states), done, done_tone."""
        with self.lock:  # one thread at a time
            return self._view(self.clock())  # worked out

    def _parts_view(self):  # the message's parts, as boxes
        """Return (part states, done text, done tone) for the message being followed."""
        m = self.message  # the message
        if m is None:  # none
            return [], "", ""  # nothing to show
        status = list(m["status"])  # each part
        latest = max((i for i, s in enumerate(status) if s is not None), default=-1)  # the furthest part heard
        boxes = [("missing" if s is None and i < latest else s or "wait") for i, s in enumerate(status)]  # a part before the furthest one heard, never heard, is missing
        who = f" from {m['origin']}" if m["origin"] else ""  # the sender, when known
        if all(s == "good" for s in status):  # all in
            return boxes, f"Message complete{who}: all {m['parts']} part{'s' if m['parts'] > 1 else ''} in", "good"  # done
        missing = [str(i + 1) for i, b in enumerate(boxes) if b == "missing"]  # parts never heard
        if missing:  # some
            return boxes, f"Part{'s' if len(missing) > 1 else ''} {', '.join(missing)} not heard yet", "fair"  # said
        return boxes, "", ""  # still coming

    def _steps_view(self, now):  # the latest power steps, for the place where a message's parts go (since 0.38)
        """Return the steps to draw: {"steps": [(dB, heard, SNR)], "note", "tone"}, or {} when none were read lately or a message is newer."""
        s = self.steps  # the latest
        if s is None or now - s["when"] > STEPS_KEEP_S or (self.message is not None and self.message["when"] > s["when"]):  # none, too old, or a message came since
            return {}  # nothing
        r = s["reading"]  # what was read
        lowest = "none heard" if r.lowest_db != r.lowest_db else f"heard to {r.lowest_db:.0f} dB"  # NaN when none was heard
        judged = {True: "even", False: "UNEVEN (ALC?)", None: ""}[r.even]  # how evenly they fell
        who = f"{s['origin']}: " if s["origin"] else ""  # whose
        return {"steps": [(db, ok, snr) for db, ok, snr in zip((0, -10, -20, -30), r.heard, r.snr_db)], "steps_note": f"{who}{lowest}" + (f", {judged}" if judged else ""),  # (continued)
                "steps_tone": "good" if r.even is True else "fair" if r.even is False else ""}  # the picture

    def _view(self, now):  # what to draw, worked out
        """See view()."""
        out = self._view_frame(now)  # the frame and its message
        out.update(self._steps_view(now))  # and the latest power steps, if any (since 0.38)
        return out  # the picture

    def _view_frame(self, now):  # the frame and its message, worked out
        """The frame and its message's parts (see view())."""
        parts, done, tone = self._parts_view()  # the message's parts
        f = self.frame  # the frame shown
        if f is None:  # nothing heard yet
            return {"title": "Listening - no Kestrel frame yet", "right": "", "segs": ["wait", "wait", "unknown", "wait"], "notes": ["", "", "", ""], "clarity": [], "progress": None, "parts": parts, "done": done, "done_tone": tone}  # waiting
        level = "LB" if f["long"] else (f"L{f['level']}" if f["level"] >= 0 else "")  # its level's name
        where = f"{f['offset_hz']:+.0f} Hz" if f["outcome"] is None or f["offset_hz"] else ""  # its frequency error
        pre_s = PREAMBLE_TONES * f["tone_s"]  # the preamble's length
        hdr_s = HEADER_TONES * f["tone_s"]  # one header copy's
        header = f["header"]  # its fields, when read
        kind = "Long beacon" if f["long"] else KINDS.get(header["frame_type"], "Frame") if header else "Kestrel frame"  # what it is
        part = f", part {header['part'] + 1} of {header['parts']}" if header and header.get("frame_type") in MESSAGE_TYPES and header.get("parts", 1) > 1 else ""  # which part
        clarity = [tone_state(db) for db in f["clarity"]]  # each body tone received
        o = f["outcome"]  # how it ended, if it has
        if f["long"]:  # no header to show
            hdr_state, hdr_note, again_state, again_note = "none", "none (long beacon)", "none", ""  # both copies
        if o is None:  # still arriving
            arrived = min(f["arrived_s"] + max(0.0, now - f["at"]), f["total_s"] or 1e9)  # moved on since the last report, at the speed sound arrives
            segs, notes = ["good", "now", "unknown", "wait"], [f"{level}, {where}", "arriving...", "length known after the header", ""]  # the preamble is in
            fill = None  # how far the header is in
            if f["long"]:  # a long beacon: preamble and body only
                segs[1], notes[1], segs[3], notes[3] = hdr_state, hdr_note, again_state, again_note  # no header
                segs[2], notes[2] = "now", "arriving (60 s; decoded at the end)"  # its body
            elif header is not None:  # read
                segs[1] = "good" if header.get("how", "first") in ("first", "") else "fair"  # read cleanly, or from the second copy
                notes[1] = f"{kind.lower()}{part}"  # what it says
                segs[2], notes[2] = "now", ""  # the body is arriving
                notes[3] = f"due at {f['total_s']:.0f} s" if f["total_s"] else ""  # when the frame ends
                fades = clarity.count("bad")  # tones lost so far
                notes[2] = f"{fades} tone{'s' if fades != 1 else ''} lost so far (red)" if fades else "coming through clearly"  # how it is going
            elif f["tried"]:  # the first copy could not be read
                segs[1], notes[1] = "fair", "first copy unreadable - waiting for the second copy"  # not lost yet
                notes[2] = "length unknown until a header is read"  # said
            else:  # the header is arriving
                fill = max(0.0, min(1.0, (arrived - pre_s) / hdr_s))  # how much of it
            body_s = (f["total_s"] - 2 * pre_s - 2 * hdr_s) if f["total_s"] else None  # the body's length: the frame less the pattern and header copy at each end (since 0.43)
            progress = max(0.0, min(1.0, (arrived - pre_s - (0 if f["long"] else hdr_s)) / body_s)) if body_s else None  # how much of the body is in
            right = f"{level}   {where}   {arrived:.1f} s" + (f" of {f['total_s']:.0f} s" if f["total_s"] else "")  # level, offset, time
            return {"title": f"{kind} arriving{part}", "right": right, "segs": segs, "notes": notes, "clarity": clarity, "progress": progress, "header_fill": fill,  # (continued)
                    "parts": parts, "done": done, "done_tone": tone}  # the picture
        snr = f"   {o['snr_db']:+.0f} dB" if o.get("snr_db") is not None else ""  # its strength, when measured
        right = f"{level}{snr}   {where}".rstrip()  # level, strength, offset
        if o.get("reason") == "header unreadable":  # never read
            return {"title": "Kestrel signal heard, but neither header copy could be read", "right": right, "segs": ["good", "bad", "unknown", "bad"],  # (continued)
                    "notes": [f"{level}", "check failed", "length unknown, so the body could not be read", "check failed too"], "clarity": [], "progress": None,  # (continued)
                    "parts": parts, "done": "Frame lost - listed as a near miss in the Activity log", "done_tone": "fair"}  # the picture
        how = (header or {}).get("how", "") or o.get("header_copy", "")  # which header copy was read
        ended = how.startswith("end")  # the frame was found from the pattern at its end: its first pattern had faded (since 0.43)
        second = how in ("both", "second", "end", "end both")  # the second header copy was used
        segs = ["fair" if ended else "good", "good" if how in ("first", "") else "fair", "good", "good" if second or o.get("ok") else "wait"]  # as received
        notes = [f"{level}, {where}".strip(", ") + (" (faded; frame found from its second pattern)" if ended else ""), f"{kind.lower()}{part}" + ("" if how in ("first", "") else " (first copy faded; read with the second)"), "check passed", "frame found here" if ended else "used for the header" if second else "matches"]  # what was found
        if f["long"]:  # no header
            segs[1], notes[1], segs[3], notes[3] = hdr_state, hdr_note, again_state, again_note  # none
        progress = 1.0  # all of it arrived
        if o.get("ok"):  # passed
            title = f"{kind}{part} received"  # said
            if o.get("combined"):  # with an earlier copy
                notes[2] = "check passed with an earlier copy added"  # said
        else:  # failed
            stop = cut_point(f["clarity"])  # where the signal went, if it went
            if stop is not None:  # cut off
                segs[2], progress = "cut", stop  # hatched after the cut
                clarity = clarity[:round(len(clarity) * stop)]  # the blocks drawn are the tones before it
                notes[2] = f"signal faded or stopped {stop * 100:.0f}% of the way through - not enough to decode"  # said
                title = f"{kind}{part} incomplete - the signal stopped part way"  # said
            else:  # came through but too damaged
                segs[2] = "bad"  # failed
                notes[2] = "check failed: too many tones lost" if o.get("reason") in ("", "body check failed", None) else f"check failed: {o['reason']}"  # said (in a contact the sender repeats a part that fails)
                title = f"{kind}{part} - the body failed its check"  # said
            if segs[3] == "wait":  # the second header copy was not needed
                segs[3], notes[3] = "good", "matches"  # it was there
        return {"title": title, "right": right, "segs": segs, "notes": notes, "clarity": clarity, "progress": progress, "parts": parts, "done": done, "done_tone": tone}  # the picture
