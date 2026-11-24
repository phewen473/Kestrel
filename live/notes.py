"""Long notes on the air (signal version 0.34): sending them, receipts, resending, and putting received ones together.

A long note (modem/longnote.py) is a header and one to eight text frames (four before signal 0.39),
each a long-beacon frame of about a minute, sent one after another when no
contact is under way. The station it is for answers with a receipt, one more
long frame. With no receipt within RECEIPT_WAIT_S of the note's last frame,
the note is sent again (up to MOST_TRIES times in all); the receiver adds a
copy that fails to the copies it kept (longbeacon.LongCombiner), so each try
reaches further than the one before. A note to ALL is sent once and gets no
receipt.

This lives beside the station's link rules, which do not deal with long
frames; live/runner.py drives it. Everything here takes the time as an
argument, so it can be tested without a clock or a sound card.
"""

import time  # the computer's clock, for the countdown shown to the operator
from dataclasses import dataclass, field  # simple record types

from link.station import Transmission  # a frame to send, as the runner sends it
from modem.address import clean_call  # callsigns tidied the way they are sent
from modem.longnote import ALL_CODE, MOST_CHARS, build_note, build_receipt, code_for, note_fields  # the frames
from modem.params import LONG_LEVEL  # the long frame's level number

RECEIPT_WAIT_S = 150.0  # after a note's last frame, wait this long for the receipt (the receiver finishes reading, checks the frequency is clear, and sends a minute-long receipt)
MOST_TRIES = 3  # a note to a station is sent at most this many times without a receipt
KEEP_S = 2400.0  # parts of a note heard are kept this long while the rest is awaited (40 minutes: a nine-frame note and two resends, each with its receipt wait; 20 minutes before 0.39)
SEEN_S = 3600.0  # a note shown is not shown again for this long (a resend after a lost receipt); its receipt is still sent
RECEIPT_GAP_S = 90.0  # at most one receipt to a station in this long (the same note heard twice in quick succession)


@dataclass  # a plain record
class Outgoing:  # a note this station is sending
    dest: str  # to whom (a callsign, or ALL)
    text: str  # what it says
    tries: int = 0  # how many times it has been sent
    due: float = 0.0  # when it may next be sent
    waiting_until: float = -1.0  # while waiting for a receipt: when to give up waiting (-1: not waiting)
    frame: tuple = None  # while it is on the air: (this frame's number, counting the header as 1, frames in all)
    receipt_by: float = 0.0  # while waiting for a receipt: when it is due, on the computer's monotonic clock (for the countdown shown)


@dataclass  # a plain record
class Incoming:  # a note being heard, part by part
    code: int  # the sender's code (text frames carry only this)
    origin: str = ""  # the sender's callsign, once its header is heard
    dest_code: int = -1  # whom it is for, once the header is heard (-1: not yet)
    parts: int = 0  # how many text frames it has, once the header is heard
    texts: dict = field(default_factory=dict)  # part number -> eight characters
    when: float = 0.0  # when anything of it was last heard


class LongNotes:  # the long notes of one station
    """Send long notes, answer with receipts, and assemble notes heard. `events` lists what happened, for the operator."""

    def __init__(self, call):  # this station's callsign
        self.call = clean_call(call)  # tidied
        self.code = code_for(self.call)  # the code that stands for it
        self.outgoing = []  # notes to send, oldest first
        self.incoming = {}  # sender's code -> Incoming
        self.receipts = []  # callsigns waiting for a receipt from this station
        self.last_receipt = {}  # callsign -> when a receipt was last sent to it
        self.seen = {}  # (origin, text) -> when that note was last shown
        self.events = []  # (kind, details...) for the operator: received, delivered, resending, failed, sent

    def queue(self, dest, text, now=0.0):  # a note to send
        """Queue a note to `dest` (a callsign or ALL); raise ValueError if it cannot be sent (too long, unprintable, empty)."""
        dest = clean_call(dest or "ALL")  # whom it is for
        note_fields(self.call, dest, text)  # check it can be sent (raises if not)
        self.outgoing.append(Outgoing(dest, text.rstrip(), due=now))  # queued

    def cancel(self, dest, text):  # the operator took a note back
        """Drop the note to `dest` saying `text` (a receipt for it, if one comes later, is ignored). Return True if it was waiting."""
        for note in self.outgoing:  # the notes not yet done
            if clean_call(note.dest) == clean_call(dest) and note.text == text.rstrip():  # this one
                self.outgoing.remove(note)  # gone
                return True  # it was there
        return False  # not found (already delivered, given up, or never queued)

    def busy(self):  # anything to send or wait for?
        """Return True while a note or receipt is waiting to go, or a note is waiting for its receipt."""
        return bool(self.receipts or self.outgoing)  # receipts to send, or notes not yet done

    def heard(self, fields, now):  # a long-note frame was decoded
        """Take in the fields of a decoded long-note frame (as longnote.unpack gives them, plus "copies")."""
        kind = fields.get("note")  # header, text or receipt
        if kind == "receipt":  # someone received a note
            if fields["dest_code"] == self.code:  # it answers a note from this station
                for note in self.outgoing:  # the notes sent
                    if note.waiting_until >= 0 and clean_call(note.dest) == clean_call(fields["origin"]):  # the one to that station
                        self.outgoing.remove(note)  # done with it
                        self.events.append(("delivered", note.dest, note.text, note.tries))  # tell the operator
                        break  # one receipt, one note
            return  # nothing more
        self._forget(now)  # drop parts too old to be completed
        if kind == "header":  # the start of a note
            code = code_for(fields["origin"])  # the sender's code, which its text frames carry
            item = self.incoming.setdefault(code, Incoming(code))  # this note (text frames may already be in)
            item.origin, item.dest_code, item.parts, item.when = fields["origin"], fields["dest_code"], fields["parts"], now  # what the header says
        elif kind == "text":  # part of the text
            item = self.incoming.setdefault(fields["origin_code"], Incoming(fields["origin_code"]))  # the note it belongs to
            item.texts[fields["part"]] = fields["text"]  # its eight characters
            item.when = now  # heard now
        else:  # nothing known
            return  # ignore it
        self._complete(item, now)  # see whether the whole note is in

    def _complete(self, item, now):  # a note with all its parts in?
        if item.dest_code < 0 or any(part not in item.texts for part in range(item.parts)):  # no header yet, or a part still missing
            return  # wait
        del self.incoming[item.code]  # done with the parts
        if item.dest_code not in (self.code, ALL_CODE):  # for some other station
            return  # not shown (the frames were in the log)
        text = "".join(item.texts[part] for part in range(item.parts)).rstrip()  # the whole text
        dest = self.call if item.dest_code == self.code else "ALL"  # to this station, or to everyone
        if now - self.seen.get((item.origin, text), -1e9) > SEEN_S:  # not shown lately
            self.events.append(("received", item.origin, dest, text))  # tell the operator
        self.seen[(item.origin, text)] = now  # shown now
        if dest == self.call and now - self.last_receipt.get(item.origin, -1e9) > RECEIPT_GAP_S and item.origin not in self.receipts:  # a note to this station: answer with a receipt (once, however often it arrives at once)
            self.receipts.append(item.origin)  # to be sent

    def _forget(self, now):  # drop half-heard notes that are too old
        self.incoming = {code: item for code, item in self.incoming.items() if now - item.when <= KEEP_S}  # recent ones only

    def tick(self, now):  # the clock moves on
        """Give up waiting for receipts that have not come: send the note again, or report it undelivered."""
        for note in list(self.outgoing):  # each note
            if note.waiting_until >= 0 and now > note.waiting_until:  # no receipt in time
                note.waiting_until = -1.0  # not waiting any more
                if note.tries < MOST_TRIES:  # another try allowed
                    note.due = now  # send it again now
                    self.events.append(("resending", note.dest, note.text, note.tries + 1))  # tell the operator
                else:  # tried enough
                    self.outgoing.remove(note)  # give up
                    self.events.append(("failed", note.dest, note.text, note.tries))  # tell the operator

    def due(self, now):  # what is due to go now
        """Return "receipt" when a receipt waits, "note" when a note is due, else None."""
        if self.receipts:  # a receipt waits
            return "receipt"  # first
        if any(note.waiting_until < 0 and note.due <= now for note in self.outgoing):  # a note due, not waiting for a receipt
            return "note"  # next
        return None  # nothing

    def next_frames(self, now):  # what to send now, if anything
        """Return (transmissions, what) to send now, or ([], None): a receipt first, else the next note that is due."""
        if self.receipts:  # a receipt waits
            dest = self.receipts.pop(0)  # to whom
            self.last_receipt[dest] = now  # sent now
            return [Transmission(build_receipt(self.call, dest), "long receipt", LONG_LEVEL, note=f"to {dest}")], ("receipt", dest)  # one frame
        for note in self.outgoing:  # notes waiting
            if note.waiting_until < 0 and note.due <= now:  # due, and not waiting for a receipt
                frames = build_note(self.call, note.dest, note.text)  # header and text frames
                note.tries += 1  # one more try
                tries = "" if note.dest == "ALL" else f"try {note.tries} of {MOST_TRIES}, "  # which try (a note to ALL is sent once)
                out = [Transmission(audio, "long note", LONG_LEVEL, note=f"to {note.dest}: {tries}frame {n + 1} of {len(frames)}" + (" (header)" if n == 0 else "")) for n, audio in enumerate(frames)]  # each frame, saying which try and which frame
                return out, ("note", note)  # the whole note, frame by frame
        return [], None  # nothing

    def on_air(self, what, number, total):  # one frame of a note is about to go out
        """Note that frame `number` (0 for the header) of `total` of the note in `what` is going out now (for the progress shown)."""
        if what is not None and what[0] == "note":  # a note, not a receipt
            what[1].frame = (number + 1, total)  # counted from 1

    def status(self):  # what each note is doing, for the operator
        """Return a list of (dest, text, words): each unfinished note and its progress, with a countdown while a receipt is awaited."""
        lines = []  # one per note
        for note in list(self.outgoing):  # each unfinished note
            tries = "" if note.dest == "ALL" else f"try {max(note.tries, 1)}/{MOST_TRIES}, "  # which try (a note to ALL is sent once)
            if note.frame is not None:  # on the air
                words = f"SENDING {tries}frame {note.frame[0]}/{note.frame[1]}"  # which try and which frame
            elif note.waiting_until >= 0:  # waiting for its receipt
                left = max(0, int(note.receipt_by - time.monotonic() + 0.5))  # seconds still to wait
                words = f"receipt due {left // 60}:{left % 60:02d} ({tries}" + (f"then try {note.tries + 1}/{MOST_TRIES})" if note.tries < MOST_TRIES else "last try)")  # the countdown, and what follows
            elif note.tries == 0:  # not sent yet
                words = f"waiting to send (try 1/{MOST_TRIES})" if note.dest != "ALL" else "waiting to send"  # when the frequency is free
            else:  # due again
                words = f"no receipt; try {note.tries + 1}/{MOST_TRIES} next"  # the next try
            lines.append((note.dest, note.text, words))  # this note
        return lines  # all of them

    def sent(self, what, now):  # the frames from next_frames have all gone
        """Note that a note's frames have gone out at `now`: wait for its receipt, or, for ALL, report it sent."""
        if what is None or what[0] != "note":  # a receipt, or nothing
            return  # nothing to do
        note = what[1]  # the note
        note.frame = None  # off the air
        note.receipt_by = time.monotonic() + RECEIPT_WAIT_S  # when the receipt is due, for the countdown
        if note.dest == "ALL":  # nobody answers a note to everyone
            if note in self.outgoing:  # still listed
                self.outgoing.remove(note)  # done
            self.events.append(("sent", note.dest, note.text, note.tries))  # tell the operator
        else:  # a note to one station
            note.waiting_until = now + RECEIPT_WAIT_S  # wait for its receipt


__all__ = ["LongNotes", "MOST_CHARS", "RECEIPT_WAIT_S", "MOST_TRIES"]  # what other modules use
