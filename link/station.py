"""One Kestrel station's link rules: what to send, and what to do with what it hears.

A Station never touches a radio. It is handed the audio it "heard" and
the time, and it returns the audio it wants to send next. That keeps the
rules testable: link/simulate.py connects two Stations through the
channel simulator, and a real program would connect one to a sound card.

The life of a contact:
    beacon -> answer -> acknowledgment (lock confirmed)
    message frame -> acknowledgment, repeated; the turn passes when a station has nothing left
    identification with the end-of-contact flag, from each side

Two optional extras: a station may keep the lock open after the traffic
is done (close_when_done=False, ended later with end()), and the pair
may agree to leave the calling frequency for a working frequency once
locked, returning when the contact ends.

Messages may be meant for one callsign (queue(text, to=...)); they wait
until that station is the partner. A station may call one particular
station instead of beaconing (call_station()), and may send a broadcast
to everyone, which nobody acknowledges (broadcast()).
"""

import zlib  # gives each station its own repeatable random numbers, from its callsign
from dataclasses import dataclass  # simple record type for a transmission

import numpy as np  # numerical arrays

from modem import native  # the compiled library, when it is in use

from modem import (  # the modem: frames, reports, planner
    ACK_HAVE_IT, ACK_LINK, ACK_OK, ACK_RESEND, LEVELS, ChannelReport, build_ack, build_answer, build_beacon, build_frame, build_ident, build_notice, call_hash,  # (continued)
    control_seconds, frame_seconds, join_parts, link_id, plan_at_level, receive,  # (continued)
)  # end of the import list
from modem.address import clean_call  # tidies a callsign
from modem.powersteps import build_steps  # power steps sent just before a beacon (since 0.38)
from modem.params import (  # frame type numbers and the airtime limit
    AIRTIME_POOR_CAP_S, FRAME_TYPE_ACK, FRAME_TYPE_ADDRESSED, FRAME_TYPE_ANSWER, FRAME_TYPE_BEACON, FRAME_TYPE_IDENT, FRAME_TYPE_LINK, FRAME_TYPE_NOTICE, FS,  # (continued)
    SNR_FLOOR_DB,  # (continued)
)  # end of the import list
from modem.text import pick_size_class  # which frame size a piece of text needs

from .adapt import cap_level, common_levels, supported_level, wanted_level  # speed adaptation rules
from .mail import CompiledMailroom, Mailroom  # the mail kept between contacts (store and forward)
from .params import (  # timing and retry settings
    BEACON_TRIES, BROADCAST_LEVEL, BROADCAST_LIFE_HOURS, CALL_TRIES, FINAL_TRIES, HISTORY, IDENT_EVERY_S, KEEPALIVE_S, LOCK_TIMEOUT_S, MAX_RESENDS, MISS_LIMIT, OFFER_PROBE, OFFER_REPLY,  # (continued)
    MOVE_SETTLE_S, MOVE_STEP_HZ, MOVE_TRIES, MOVE_WAIT_S, OFFER_MOVE, OFFER_TURN, OFFER_UNAVAILABLE, REPLY_SLOT_GAP_S, WIDE_SLOTS, CALLUP_LEVEL, HEARD_FOR_CALL_S, EXPECT_S,  # (continued)
    HOLD_TELL_S, HOP_LIMIT, MAIL_TIDY_S, NOTICE_L0_EVERY_S, OFFER_NO_MAIL, REACH_S, REACQUIRE_TRIES, REPLY_MARGIN_S, STEP_UP_CLEAN, TURNAROUND_S, WORKING_IDLE_S, WORKING_WARN_S,  # (continued)
)  # end of the import list

LOCKED_STATES = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states in which the station has a partner


def reply_slot(level):  # how long one reply slot lasts after a beacon at a given level
    """Return the length in seconds of a reply slot after a beacon sent at `level`: an answer at that level plus a short gap."""
    return control_seconds(FRAME_TYPE_ANSWER, level) + REPLY_SLOT_GAP_S  # 44.8 s after an L0 beacon, 11.9 s after an L2 beacon (since 0.33)


@dataclass  # a plain record
class Transmission:  # one frame the station wants on the air
    """Audio to transmit, with a description for logs."""

    audio: np.ndarray  # the samples
    kind: str  # what the frame is: beacon, answer, message, ack, offer, probe, reply, ident, final
    level: int  # the speed level it is sent at
    note: str = ""  # extra detail for the log
    delay: float = 0.0  # seconds to wait before sending (an answer waiting for its reply slot)
    lead: np.ndarray = None  # audio sent just before the frame, in the same transmission: a beacon's power steps (since 0.38); None for none

    @property  # computed from the audio
    def seconds(self):  # airtime
        """Length of the frame, in seconds (the power steps before a beacon not counted: the link rules time replies from the frame)."""
        return len(self.audio) / FS  # samples divided by the sample rate

    def on_air(self):  # everything to send
        """Return the audio to put on the air: the power steps, if any, then the frame."""
        return self.audio if self.lead is None else np.concatenate([self.lead, self.audio])  # steps first


def _with_lead(tx, steps):  # a beacon with its power steps (since 0.38)
    """Return `tx` with the power steps put before it when `steps` is true (the frame's header already says so), and a note for the log."""
    if steps and tx is not None:  # wanted
        tx.lead = build_steps()  # the four steps, at the beacon's own amplitude for the first
        tx.note = (tx.note + "; " if tx.note else "") + "power steps first"  # said in the log
    return tx  # the transmission


def _reading(result):  # one frame's measurements, as the history keeps them
    """Return (SNR, fading index, Doppler spread) of a receiver report (the spread NaN when it was not read)."""
    return (result.snr_db, result.fade_index, getattr(result, "spread_hz", float("nan")))  # the three readings


class PythonStation:  # the link rules for one station, in Python (the reference the compiled station is tested against)
    """A station's state and its rules. Use beacon() or listen() to start, queue() to add messages, then poll(), hear() and handle()."""

    def __init__(self, call, grid, levels=None, close_when_done=True):  # set up a station
        self.call = clean_call(call)  # this station's callsign
        self.rng = np.random.default_rng(zlib.crc32(self.call.encode()))  # this station's own random numbers (for choosing a reply slot)
        self.wide = False  # beaconing: ask for a wide reply window (set after a beacon goes unanswered, or when several stations answered)
        self.candidates = []  # beaconing: answers collected during a wide reply window
        self.worked = set()  # callsigns of stations already worked, so their next beacon is not answered again without new traffic
        self.grid = grid  # its grid locator
        self.levels = tuple(levels) if levels is not None else tuple(spec.number for spec in LEVELS)  # the speed levels it can use
        self.close_when_done = close_when_done  # end the contact once neither side has anything left to send
        self.keep_open = not close_when_done  # the operator's standing choice, restored for each new contact after end() has been used
        self.state = "IDLE"  # lock state: IDLE, LOCKED, DEGRADED, REACQUIRE or RELEASED
        self.role = None  # "beaconer" or "answerer"
        self.partner = ""  # the other station's callsign
        self.link = -1  # the pair's link number
        self.allowed = [0]  # speed levels both stations can use
        self.tx_level = 0  # the level the partner asked this station to send at
        self.want = 0  # the level this station asks the partner to send at
        self.history = []  # recent (SNR, fading index, Doppler spread) measurements of the partner's frames (the spread since 0.35)
        self.clean_run = 0  # clean frames in a row since the last change of wanted level
        self.good_run = 0  # clean frames in a row since the last failure (for leaving DEGRADED)
        self.last_result = None  # the receiver's report on the frame heard most recently
        self.outbox = []  # messages waiting to be sent, oldest first
        self.outbox_to = []  # for each of those, the callsign it is meant for, or None for whoever the partner is
        self.broadcasts = []  # broadcast frames waiting to be sent to everyone: (audio, level, note)
        self.long_waiting = None  # a long beacon waiting to be sent (its audio), if one was asked for
        self.busy = None  # if set, called with a speed level: True when the frequency is in use where a frame at that level would go (listen before transmitting; a live station sets it)
        self.held_since = None  # when this station began holding a transmission back because the frequency was in use
        self.held_told = -1e9  # when the operator was last told so
        self.bulletins = []  # broadcasts and other fully addressed messages received: (origin, destination, text)
        self.bulletin_parts = {}  # parts of those still arriving: (origin, message number) -> {part: report}
        self.bulletin_done = set()  # (origin, message number) of those already delivered, so a repeat is not shown twice
        self.target = ""  # the callsign being called, for a station making a directed call
        self.calls = 0  # directed calls sent without a reply
        self.leads = False  # True for the station that keeps the turn when both find themselves sending: the one that beaconed, or the one that was called
        self.delivered = []  # messages the partner has acknowledged in full
        self.inbox = []  # complete messages received
        self.plan = []  # the frames of the message being sent
        self.plan_text = ""  # the whole text of that message
        self.part_index = 0  # which frame of the plan is next
        self.current_id = 0  # the number of the message being sent
        self.pending = None  # the reply being waited for: answer, confirm, ack, offer, probe or final
        self.deadline = 0.0  # when to stop waiting for it
        self.misses = 0  # transmissions in a row that got no reply
        self.resends = 0  # times the current frame has been sent again at the partner's request
        self.probes = 0  # reacquire probes sent without a reply
        self.finals = 0  # closing identifications sent without a reply
        self.beacons = 0  # beacons sent without an answer
        self.my_turn = False  # True while this station may start a transmission
        self.peer_empty = False  # True once the partner has said it has nothing to send
        self.sent_final = False  # True once this station has sent its closing identification
        self.partial = {}  # parts received so far of messages not yet complete: message number -> {part: report}
        self.done_ids = set()  # message numbers already received in full
        self.stored = None  # soft bits of the last message frame that failed, kept for combining with its retry
        self.stored_sig = None  # (size class, part, part count) of that frame
        self.last_ident = -1e9  # when this station last sent its callsign
        self.last_activity = 0.0  # when this station last sent or heard a frame
        self.log = []  # plain-English notes on what happened, for the operator and for tests
        self.reply_margin = REPLY_MARGIN_S  # extra time to wait for a reply beyond its own length (a live station allows more)
        self.power_steps = False  # send power steps just before each beacon (since 0.38; the caller allows for their 5 s in reply_margin)
        self.quiet = False  # True while the lock is idle and the partner holds the turn (this station may then take the turn if it gets something to send)
        self.idle_told = False  # True once the partner has been offered the turn since the last message went either way (so it knows the lock is idle)
        self.can_move = False  # True when whoever runs the radio can retune it, so a move to a working frequency is possible
        self.move_to_hz = None  # the working frequency this station will propose once locked, as an offset in hertz from the calling frequency (None: stay)
        self.offset_hz = 0  # where the radio should be now, as an offset in hertz from the calling frequency
        self.tune_at = None  # when a retune that has been decided takes effect (after the frame that announces it has been sent)
        self.tune_next = 0  # the offset that retune goes to
        self.moved = False  # True once a move has been agreed, refused or given up in this contact (it is proposed only once)
        self.move_tries = 0  # times the move has been proposed without a reply
        self.settle_until = None  # after an agreed move: when to probe for the partner on the working frequency
        self.arriving = False  # True while that first probe on the working frequency is unanswered
        self.await_since = None  # after moving at the partner's request: when this station began waiting for it on the working frequency
        self.proposed_move = False  # True for the station that asked for the move (it watches for an idle working frequency)
        self.last_traffic = 0.0  # when a message frame last went either way (or when the pair arrived on the working frequency)
        self.idle_warned = False  # True once the operator has been warned that an idle working frequency is about to be given up
        self.single = False  # True while a listening station makes one beacon round or one directed call, after which it listens again
        self.answer_beacons = True  # a listening station answers beacons by itself; when False the operator chooses, and replies with a directed call
        self.available = True  # the operator is available for contacts; when False the station's beacons say so and a directed call gets one short "not available" reply
        self.answer_calls = True  # a listening station answers directed calls by itself; when False only calls it is expecting are answered, and the operator chooses for the rest
        self.last_beacon_t = -1e9  # when this station last beaconed (directed calls from anyone are expected for a while afterwards)
        self.called_t = {}  # callsign -> when this station last called it (a call back from it is expected for a while afterwards)
        self.unavailable_from = ""  # the last station that replied "not available" to this station's call
        self.callup = CALLUP_LEVEL if CALLUP_LEVEL in self.levels else 0  # the level the next beacon or directed call goes at: the middle level first, L0 if that brings no reply
        self.beacon_sent_at = 0  # the level of the beacon now waiting for answers
        self.heard_at = {}  # callsign -> (time, report) of the last frame heard from it that named it, for the report a directed call carries
        self.mail = Mailroom(self.call)  # the mail kept between contacts; whoever runs the station may hand in one loaded from a file
        self.outbox_ids = []  # for each outbox message, its message number if it is for a named station (fixed when queued, so every copy is the same message), else None
        self.carries = True  # this station holds mail for other stations when asked to (the operator's "Carry mail for others" setting)
        self.job = None  # the mail being sent in this contact, when it is not this station's own message to its partner: a dict (kind, dest, origin, id, text, hops, life)
        self.refused = set()  # partners that said they do not carry mail, not asked again this run
        self.mail_parts = {}  # parts of fully addressed messages arriving inside a lock: (origin, number) -> {part: report}
        self.expired = []  # texts of this station's messages that expired undelivered, for whoever runs the station
        self.notices = {}  # callsign -> (time, fields) of the last mail notice heard from each station
        self.notice_sent = False  # True when a mail notice has just gone out and the beacon it goes with is next
        self.last_notice_l0 = -1e9  # when a mail notice last went with an L0 beacon
        self.tidied = -1e9  # when expired mail was last looked for

    # ---- starting up ----

    def beacon(self):  # become the station that calls
        """Start beaconing for a partner."""
        self.role = "beaconer"  # this station sends beacons
        self.leads = True  # and keeps the turn in a clash

    def listen(self):  # become the station that answers
        """Wait for a beacon and answer it."""
        self.role = "answerer"  # this station answers beacons

    def call_station(self, target):  # become a station that calls one particular station
        """Call `target` by name instead of beaconing; only that station answers."""
        if clean_call(target) == self.call:  # a station cannot call itself: nobody else would answer to that name
            raise ValueError(f"{self.call} is this station's own callsign; call the other station's")  # refuse, and say why
        self.role = "caller"  # this station sends directed calls
        self.target = clean_call(target)  # to this callsign
        self.leads = False  # the station that is called keeps the turn in a clash

    def beacon_once(self):  # a listening station calls for a partner once, then listens again
        """Send one beacon (with its reply window) from a station that is otherwise listening; whatever happens, it goes back to listening afterwards."""
        self.beacon()  # become the calling station for now
        self.beacons = BEACON_TRIES - 1  # one beacon only: an unanswered one ends the round
        self.single = True  # and return to answering once this round or its contact is over

    def call_once(self, target):  # a listening station calls one station by name, then listens again
        """Call `target` from a station that is otherwise listening; after the contact, or after the calls go unanswered, it listens again."""
        self.call_station(target)  # become the calling station for now (refuses this station's own callsign)
        self.single = True  # and return to answering afterwards

    def long_beacon(self, holds_mail=None):  # announce this station as far as the path allows
        """Queue one long beacon (signal version 0.27): about a minute, heard down to about -26 dB. Nobody answers it; it goes when no contact is under way."""
        from modem.longbeacon import build_long_beacon  # the long beacon's transmitter
        self.long_waiting = build_long_beacon(self.call, self.grid, available=self.available, holds_mail=bool(self.mail.bag) if holds_mail is None else holds_mail)  # ready to send (saying whether this station holds mail for others)

    def queue(self, text, to=None):  # hand the station a message to send
        """Add a message to the outbox. With `to`, it is sent only when that callsign is the partner."""
        self.outbox.append(text)  # oldest first
        self.outbox_to.append(clean_call(to) if to else None)  # who it is for, if anyone in particular
        self.outbox_ids.append(self.mail.own_add(text, to, {number for number in self.outbox_ids if number is not None}) if to else None)  # a message to a named station gets its number now, and keeps it wherever its copies go

    def broadcast(self, text, level=BROADCAST_LEVEL):  # send a message to everyone listening
        """Queue `text` as a broadcast to ALL: fully addressed frames that nobody acknowledges, sent when no contact is in progress."""
        number = self.mail.new_number()  # the broadcast takes the next message number
        for item in plan_at_level(text, level, addressed=True):  # cut into frames that respect the airtime limits
            audio = build_frame(item["text"], level, item["part"], item["parts"], msg_id=number, dest="ALL", origin=self.call, hops=0, life_hours=BROADCAST_LIFE_HOURS)  # a fully addressed frame for everyone
            self.broadcasts.append((audio, level, f"to ALL, msg {number} part {item['part'] + 1}/{item['parts']}"))  # wait for a free moment

    def unqueue(self, text, to=None):  # take back a message that has not started to go
        """Remove the newest waiting message with this `text` and address from the outbox; return True if one was removed. A message already under way is left alone."""
        wanted = clean_call(to) if to else None  # the address as the outbox holds it
        for index in range(len(self.outbox) - 1, -1, -1):  # newest first
            if self.outbox[index] == text and self.outbox_to[index] == wanted and not (index == 0 and self.plan):  # the same message, and not the one being sent
                number = self.outbox_ids[index]  # its message number, if it has one
                del self.outbox[index], self.outbox_to[index], self.outbox_ids[index]  # take it out, with its address and number
                if number is not None:  # a message to a named station
                    self.mail.own_drop(number)  # it is no longer waiting anywhere
                return True  # removed
        return False  # nothing matched

    def _sendable(self):  # which waiting message can go to the present partner?
        """Return the position in the outbox of the first message for this partner (or for anyone), or None."""
        for index, to in enumerate(self.outbox_to):  # oldest first
            if to is None or to == self.partner:  # for anyone, or for this partner
                return index  # this one
        return None  # nothing for this partner

    def _has_for(self, call):  # is there traffic for a given callsign?
        return any(to is None or to == call for to in self.outbox_to) or bool(self.mail.held_for(call))  # a message for anyone, or for that station, or mail held for it

    def _mail_job(self):  # mail to send in this contact other than this station's own message to its partner
        """Return the next mail job for the present partner, or None: first mail held for the partner itself, then this station's messages for other stations (to hand to the partner to carry), then held mail the partner says it can get closer to its destination."""
        if not self.partner or self.state not in LOCKED_STATES:  # no contact
            return None  # nothing
        for item in self.mail.held_for(self.partner):  # mail held here for the partner
            return {"kind": "deliver", "dest": item["dest"], "origin": item["origin"], "id": item["id"], "text": item["text"], "hops": item["hops"] + 1, "life": self.mail.life_hours(item["expires"])}  # deliver it (one more hop)
        if self.partner in self.refused:  # the partner does not carry mail
            return None  # nothing more to offer it
        for text, to, number in zip(self.outbox, self.outbox_to, self.outbox_ids):  # this station's waiting messages, oldest first
            if to and to != self.partner and number is not None and self.mail.can_hand(number, self.partner):  # for another station, and not already with this partner
                expires = self.mail.own_item(number)["expires"]  # when it runs out
                return {"kind": "hand", "dest": to, "origin": self.call, "id": number, "text": text, "hops": 0, "life": self.mail.life_hours(expires)}  # hand a copy over to carry
        item = self.mail.to_pass(self.partner)  # held mail the partner hears the destination of
        if item is not None:  # there is some
            return {"kind": "pass", "dest": item["dest"], "origin": item["origin"], "id": item["id"], "text": item["text"], "hops": item["hops"] + 1, "life": self.mail.life_hours(item["expires"])}  # pass a copy on
        return None  # nothing

    def _has_traffic(self):  # does this station have anything to send in the present contact?
        return self._sendable() is not None or self._mail_job() is not None  # its own message for the partner, or mail

    def _heard_calls(self, now):  # stations heard lately, most recent first, for a mail notice
        return [call for call, (when, _) in sorted(self.heard_at.items(), key=lambda pair: -pair[1][0]) if now - when <= REACH_S]  # within the reach time

    def mail_waiting_at(self, call):  # does `call` hold mail for this station, by its last notice?
        return self.mail.holds_for_me(call)  # as the mail store remembers it

    def end(self):  # the operator wants the contact closed
        """Close the contact once any traffic under way is finished (for a lock that was being kept open)."""
        self.close_when_done = True  # from now on, close as soon as neither side has anything to send

    def cancel(self, now):  # the operator stops calling
        """Stop a directed call or a beacon round that has not made a contact, and drop a waiting long beacon and broadcast frames.

        Return a few words saying what was stopped, or "" when there was
        nothing to stop. A contact under way is left alone (end() closes
        it properly). The station goes back to listening: whoever runs it
        sees RELEASED and starts afresh, as after any contact.
        """
        if self.state != "IDLE" or (self.role == "answerer" and self.pending is not None):  # a contact under way, or an answer waiting for its confirmation
            return ""  # not this station's call-up to stop
        stopped = []  # what is being stopped
        if self.role == "caller":  # a directed call
            stopped.append(f"calling {self.target}")  # that
        elif self.role == "beaconer":  # a beacon round
            stopped.append("beaconing")  # that
        if self.long_waiting is not None:  # a long beacon waiting to go
            stopped.append("the long beacon")  # that too
        if self.broadcasts:  # broadcast frames waiting to go
            stopped.append(f"{len(self.broadcasts)} broadcast frame(s)")  # those too
        if not stopped:  # nothing under way
            return ""  # nothing to stop
        self.long_waiting, self.broadcasts = None, []  # nothing more waits to go out
        self.state, self.pending, self.partner, self.link, self.candidates = "RELEASED", None, "", -1, []  # no partner, nothing awaited
        self.role, self.single, self.leads, self.target, self.calls, self.beacons = "answerer", False, False, "", 0, 0  # back to listening afterwards
        words = "stopped " + ", ".join(stopped) + " (operator)"  # what happened
        self._say(now, words)  # in the log
        return words  # for whoever runs the station

    def tuning(self, now):  # where should the radio be tuned at this moment?
        """Return the offset from the calling frequency, in hertz, that the radio should be on at time `now`."""
        if self.tune_at is not None and now >= self.tune_at:  # a retune that was decided earlier is now due
            self.offset_hz, self.tune_at = self.tune_next, None  # it takes effect
        return self.offset_hz  # the frequency in force

    def _retune(self, when, offset_hz):  # decide to change frequency at a given time
        self.tune_at, self.tune_next = when, offset_hz  # whoever runs the radio sees it through tuning()

    # ---- hearing ----

    def hear(self, audio):  # run the modem receiver, combining a failed frame with its retry
        """Return the receiver's report for `audio`. A message frame that fails is kept, and added to its retry."""
        result = receive(audio)  # first try: this copy alone
        if result.ok:  # it decoded
            if result.frame_type in (FRAME_TYPE_LINK, FRAME_TYPE_ADDRESSED):  # a message frame got through
                self.stored = None  # so any kept copy is no longer needed
            return result  # done
        if result.reason != "body check failed" or result.frame_type not in (FRAME_TYPE_LINK, FRAME_TYPE_ADDRESSED):  # nothing usable, or not a message frame
            return result  # nothing to combine
        signature = (result.frame_type, result.size_class, result.part, result.parts)  # which frame this looks like, from its header
        if self.stored is not None and self.stored_sig == signature:  # an earlier failed copy of the same frame is on hand
            combined = receive(audio, prior_llrs=self.stored)  # second try: both copies added together
            if combined.ok:  # together they decode
                self.stored = None  # the kept copy has done its job
                return combined  # success
            if combined.body_llrs is not None:  # still not enough
                result = combined  # keep the sum of the copies for the next retry
        self.stored, self.stored_sig = result.body_llrs, signature  # remember this frame's soft bits
        return result  # report the failure

    # ---- small helpers ----

    def _say(self, now, text):  # add a line to the log
        self.log.append(f"{now:7.1f}s {self.call}: {text}")  # time, who, what

    def _report_of(self, result):  # a channel report on one frame, outside any contact
        return ChannelReport(result.snr_db if np.isfinite(result.snr_db) else float(SNR_FLOOR_DB), result.fade_index, result.offset_hz, supported_level([_reading(result)], self.levels) if np.isfinite(result.snr_db) else 0)  # how it was heard, and the level it supports

    def _report(self):  # the channel report to send back
        result = self.last_result  # the frame heard most recently
        snr_db = result.snr_db if result is not None and np.isfinite(result.snr_db) else -30.0  # its SNR, or the bottom of the scale when unknown
        fade = result.fade_index if result is not None else float("nan")  # its fading index
        offset = result.offset_hz if result is not None else 0.0  # its frequency offset
        return ChannelReport(snr_db, fade, offset, self.want)  # the measurements, and the level this station asks for

    def _note(self, result, failed):  # take in the measurements of a frame from the partner
        self.last_result = result  # keep it for the next report
        if np.isfinite(result.snr_db):  # a usable SNR reading
            self.history = (self.history + [_reading(result)])[-HISTORY:]  # add it, keep only the recent ones
        self.clean_run = 0 if failed else self.clean_run + 1  # count clean frames since the last change of level
        self.good_run = 0 if failed else self.good_run + 1  # count clean frames since the last failure
        if self.history:  # with at least one measurement
            new = wanted_level(self.history, self.want, self.clean_run, failed, self.allowed)  # decide the level to ask for
            if new != self.want:  # the decision changed
                self.clean_run = 0  # a new level starts a new run
                self.want = new  # ask for it from now on
        if failed and self.state == "LOCKED":  # a failed frame degrades a healthy lock
            self.state = "DEGRADED"  # but never drops it
        elif not failed and self.state == "DEGRADED" and self.good_run >= STEP_UP_CLEAN:  # clean again
            self.state = "LOCKED"  # healthy once more

    def _fresh_start(self, result):  # restart the measurements from one new frame
        self.history = [_reading(result)] if np.isfinite(result.snr_db) else []  # forget older readings
        self.last_result = result  # keep it for the next report
        self.clean_run = self.good_run = 0  # new runs
        self.want = supported_level(self.history, self.allowed) if self.history else min(self.allowed)  # ask for what this one reading supports

    def _send(self, now, audio, kind, level, expects=None, reply_s=0.0, note=""):  # prepare one transmission
        tx = Transmission(audio, kind, level, note)  # the frame and its description
        self.pending = expects  # what reply to wait for, if any
        self.deadline = now + tx.seconds + TURNAROUND_S + reply_s + self.reply_margin  # how long to wait for it
        self.last_activity = now + tx.seconds  # this station was last active when the frame ends
        return tx  # hand it to whoever runs the radio

    def _ack(self, now, msg_id, part, status, kind, expects=None, reply_s=0.0):  # prepare an acknowledgment frame
        audio = build_ack(self.link, msg_id, part, status, self._report(), level=self.tx_level)  # at the level the partner asked for
        return self._send(now, audio, kind, self.tx_level, expects, reply_s, f"wants L{self.want}")  # note the level being asked for

    def _ident(self, now, final):  # prepare an identification frame
        self.last_ident = now  # the callsign goes out now
        self.sent_final = self.sent_final or final  # remember a closing identification
        audio = build_ident(self.call, self.link, final=final, level=self.tx_level)  # at the level the partner asked for
        if final:  # the closing identification
            return self._send(now, audio, "final", self.tx_level, "final", control_seconds(FRAME_TYPE_IDENT, self.want))  # wait for the partner's
        return self._send(now, audio, "ident", self.tx_level)  # a routine identification needs no reply

    def _longest_reply(self):  # how long the partner's reply to a turn offer could be
        message = min(frame_seconds(3, self.want), AIRTIME_POOR_CAP_S)  # the largest message frame at the level asked for, within the airtime limit
        return max(message, control_seconds(FRAME_TYPE_ACK, self.want))  # or an acknowledgment, whichever is longer

    # ---- sending messages ----

    def _start_message(self, text, number=None, job=None):  # plan a message at the current level
        self.job = job  # mail for another station, or None for this station's own message to its partner
        self.plan = plan_at_level(text, self.tx_level, addressed=job is not None)  # cut it into frames that respect the airtime limits (mail travels in fully addressed frames)
        self.plan_text = text  # keep the whole text in case it must be planned again
        self.part_index = 0  # start with the first frame
        self.current_id = number if number is not None else self.mail.new_number()  # its number: fixed already for a message to a named station, else the next one
        self.resends = 0  # a new message starts with a clean slate

    def _send_part(self, now):  # send the next frame of the current message
        item = self.plan[self.part_index]  # the frame that is due
        if frame_seconds(pick_size_class(item["text"]), self.tx_level) > AIRTIME_POOR_CAP_S:  # the level has dropped and this frame would now run too long
            self._say(now, f"level fell to L{self.tx_level}; splitting the message again")  # explain
            self.plan = plan_at_level(self.plan_text, self.tx_level, addressed=self.job is not None)  # plan the whole message again at the new level; it keeps its number
            self.part_index = 0  # start again from its first frame (the far end drops the parts of the old split)
            item = self.plan[0]  # the frame that is now due
        job = self.job  # mail for another station, if that is what is being sent
        if job is None:  # this station's own message to its partner
            audio = build_frame(item["text"], self.tx_level, item["part"], item["parts"], link=self.link, msg_id=self.current_id, want_level=self.want)  # the message frame, carrying the level this station wants from its partner
            note = f"msg {self.current_id} part {item['part'] + 1}/{item['parts']}"  # which frame this is
        else:  # mail: a fully addressed frame, so the message carries its own origin, destination, hops and lifetime wherever it goes
            audio = build_frame(item["text"], self.tx_level, item["part"], item["parts"], msg_id=job["id"], dest=job["dest"], origin=job["origin"], hops=job["hops"], life_hours=job["life"])  # the addressed frame
            note = f"{job['kind']} mail {job['origin']}#{job['id']} for {job['dest']}, part {item['part'] + 1}/{item['parts']}"  # which frame this is
        self.idle_told = False  # traffic is moving, so the lock is not idle
        self.last_traffic, self.idle_warned = now, False  # a message frame is going out: the idle clock starts again
        return self._send(now, audio, "message", self.tx_level, "ack", control_seconds(FRAME_TYPE_ACK, self.want), note)  # wait for its acknowledgment

    def _next(self, now):  # decide what to send when the turn is this station's
        if now - self.last_ident >= IDENT_EVERY_S:  # nearly ten minutes since the callsign went out
            return self._ident(now, final=False)  # identify first
        if self.move_to_hz and self.can_move and not self.moved:  # a working frequency is wanted and has not been dealt with yet
            return self._propose_move(now)  # ask the partner to move before any traffic
        if self.plan and self.part_index < len(self.plan):  # a message is under way
            return self._send_part(now)  # send its next frame
        index = self._sendable()  # the next message that may go to this partner
        if index is not None:  # there is one
            self.outbox.insert(0, self.outbox.pop(index))  # bring it to the front of the outbox...
            self.outbox_to.insert(0, self.outbox_to.pop(index))  # ...with its address
            self.outbox_ids.insert(0, self.outbox_ids.pop(index))  # ...and its number
            self._start_message(self.outbox[0], self.outbox_ids[0])  # plan it
            return self._send_part(now)  # send its first frame
        job = self._mail_job()  # mail to deliver, hand over or pass on
        if job is not None:  # there is some
            self._say(now, {"deliver": f"delivering mail from {job['origin']} held here for {self.partner}", "hand": f"handing {self.partner} a message for {job['dest']} to carry",  # (continued)
                            "pass": f"passing {self.partner} mail for {job['dest']}, which it hears"}[job["kind"]])  # explain
            self._start_message(job["text"], job["id"], job)  # plan it
            return self._send_part(now)  # send its first frame
        if not self.peer_empty:  # nothing to send, and the partner has not said the same
            self.idle_told = True  # this offer also tells the partner that this station is idle
            return self._ack(now, 0, OFFER_TURN, ACK_LINK, "offer", "offer", self._longest_reply())  # offer the partner the turn
        if self.close_when_done:  # both sides are finished
            return self._ident(now, final=True)  # close the contact
        if not self.idle_told:  # the lock is being kept open, and the partner has not been told that the traffic is over
            self.idle_told = True  # tell it once
            return self._ack(now, 0, OFFER_TURN, ACK_LINK, "offer", "offer", self._longest_reply())  # an offer of the turn: the partner may now send whenever it has something
        return None  # stay locked and quiet

    def _propose_move(self, now):  # ask the partner to change to the working frequency
        self.move_tries += 1  # count the proposal
        steps = int(round(self.move_to_hz / MOVE_STEP_HZ)) & 0xFFFF  # the offset as a signed 16-bit count of 100 Hz steps
        self.proposed_move = True  # this station asked for the move, so it will watch for the working frequency going idle
        if self.move_tries == 1:  # the first time
            self._say(now, f"proposing a move to the working frequency ({self.move_to_hz / 1000.0:+.1f} kHz)")  # explain
        return self._ack(now, steps, OFFER_MOVE, ACK_LINK, "move", "move", control_seconds(FRAME_TYPE_ACK, self.want))  # the proposal travels in the message-number field

    def _reacquire(self, now):  # the partner has gone quiet: try to find it again
        if self.state != "REACQUIRE":  # just entering this state
            self.state = "REACQUIRE"  # note it
            self.probes = 0  # no probes sent yet
            self._say(now, "no reply; reacquiring at the slowest level")  # explain
        self.tx_level = min(self.allowed)  # probe at the slowest level
        self.want = min(self.allowed)  # and ask for the reply at the slowest level
        return self._ack(now, 0, OFFER_PROBE, ACK_LINK, "probe", "probe", control_seconds(FRAME_TYPE_ACK, self.want))  # "are you still there?"

    def new_contact(self):  # get ready for another contact after one has ended
        """Return the station to IDLE, keeping its messages, its log and what it has learned about the reply window."""
        self.state, self.pending, self.partner, self.link = "IDLE", None, "", -1  # no partner
        self.job, self.mail_parts, self.notice_sent = None, {}, False  # no mail under way or half-received, no notice just sent
        self.history, self.last_result, self.clean_run, self.good_run = [], None, 0, 0  # no measurements
        self.plan, self.part_index, self.misses, self.resends, self.probes, self.finals, self.beacons = [], 0, 0, 0, 0, 0, 0  # nothing under way, no counts
        self.my_turn = self.peer_empty = self.sent_final = False  # no turn, no goodbyes
        self.partial, self.done_ids, self.stored, self.candidates = {}, set(), None, []  # nothing half-received
        self.quiet, self.moved, self.move_tries, self.settle_until, self.arriving, self.await_since = False, False, 0, None, False, None  # no idle lock, no move under way
        self.idle_told = False  # nothing has been said about being idle
        self.proposed_move, self.idle_warned = False, False  # no move has been asked for in the next contact yet
        self.leads, self.calls = self.role == "beaconer", 0  # the beaconing station leads again; no calls outstanding
        self.close_when_done = not self.keep_open  # an earlier end() applied to that contact only
        self.callup = CALLUP_LEVEL if CALLUP_LEVEL in self.levels else 0  # the next call-up starts at the middle level again
        if self.single:  # that was a single beacon round or directed call from a listening station
            self.single, self.role, self.leads, self.target = False, "answerer", False, ""  # listen again

    def _release(self, now, why):  # the contact is over
        if self.partner:  # there was a partner
            self.worked.add(self.partner)  # remember it has been worked
        self.state = "RELEASED"  # final state
        self.pending = None  # nothing more is expected
        self.quiet, self.settle_until, self.await_since = False, None, None  # no idle lock and no move under way any more
        if self.offset_hz or self.tune_at is not None:  # the contact was on, or on its way to, a working frequency
            self._retune(now, 0)  # go back to the calling frequency
        self._say(now, why)  # say why

    # ---- acting on what was heard ----

    def handle(self, result, now):  # react to a frame (or a failed frame) just heard
        """Return the Transmission to send in reply to `result`, or None."""
        if self.state == "RELEASED":  # the contact is over
            return None  # stay silent
        if not result.ok:  # the frame did not decode
            if result.reason == "body check failed" and result.frame_type in (FRAME_TYPE_LINK, FRAME_TYPE_ADDRESSED) and self.state in LOCKED_STATES and self.pending is None:  # a message frame (or mail) arrived damaged
                self._note(result, failed=True)  # take in its measurements and ask for a slower level
                self._say(now, f"frame failed its check; asking for L{self.want} and a resend")  # explain
                return self._ack(now, 0, result.part, ACK_RESEND, "ack")  # ask for it again
            return None  # otherwise there is nothing to reply to
        self.last_activity = now  # a good frame was heard
        sender = (result.fields or {}).get("origin") or (result.origin if result.frame_type == FRAME_TYPE_ADDRESSED else "")  # the callsign it carries, if any
        if sender and np.isfinite(result.snr_db):  # it names its sender and was measured
            self.heard_at[sender] = (now, ChannelReport(result.snr_db, result.fade_index, result.offset_hz, supported_level([_reading(result)], self.levels)))  # remember the reading, for a directed call to it
        kind = result.frame_type  # what sort of frame it is
        if kind == FRAME_TYPE_ADDRESSED:  # a fully addressed message: a broadcast, or one sent without a lock
            return self._on_addressed(result, now)  # show it if it is for this station or for everyone
        if kind == FRAME_TYPE_NOTICE:  # a mail notice
            return self._on_notice(result, now)  # take in what it says
        if kind == FRAME_TYPE_BEACON:  # someone is calling
            return self._on_beacon(result, now)  # maybe answer
        if kind == FRAME_TYPE_ANSWER:  # someone answered a beacon
            return self._on_answer(result, now)  # maybe lock
        if self.state == "IDLE" and self.pending != "confirm":  # every other frame needs a partner
            return None  # ignore it
        if result.link != self.link:  # a frame from somebody else's lock
            return None  # ignore it
        self.await_since = None  # the partner has been heard, so any wait for it on a working frequency is over
        if kind == FRAME_TYPE_ACK:  # an acknowledgment
            return self._on_ack(result, now)  # act on it
        if kind == FRAME_TYPE_LINK:  # a message frame
            return self._on_message(result, now)  # store and acknowledge it
        if kind == FRAME_TYPE_IDENT:  # an identification
            return self._on_ident(result, now)  # maybe close
        return None  # anything else is not for the link layer

    def _on_beacon(self, result, now):  # a beacon was heard
        if self.role != "answerer" or self.state != "IDLE" or not result.fields["listening"]:  # not answering, already busy, or the caller takes no answers
            return None  # stay silent
        for_mail = (result.fields["mail_check"] and bool(self.mail.held_for(result.origin))) or self.mail_waiting_at(result.origin)  # mail held here for the beaconing station (it asked for it), or it holds mail for this station
        if not self.answer_beacons and not (for_mail and self.available):  # the operator answers by hand, with a directed call (mail is answered for regardless)
            return None  # stay silent; the operator has been shown the beacon
        if result.origin in self.worked and not self._has_for(result.origin):  # already worked this station, and nothing new for it
            return None  # leave the reply window to others
        slot_s = reply_slot(result.level)  # the beaconing station's reply slots are sized for the level its beacon came at
        slot = int(self.rng.integers(0, WIDE_SLOTS)) if result.fields["wide"] else 0  # a wide window: pick one of four slots at random; otherwise the only slot
        slots_left = (WIDE_SLOTS if result.fields["wide"] else 1) - slot  # slots from this station's own to the end of the window
        self.partner = result.origin  # the calling station
        self.link = link_id(self.partner, self.call)  # link number: the beaconing station first
        self.allowed = common_levels(self.levels, result.fields["levels"])  # the levels both can use
        self._fresh_start(result)  # the first measurement of the partner
        self.tx_level = result.level if result.level in self.allowed else min(self.allowed)  # answer at the beacon's own level: hearing it shows the path carries that level
        self.last_ident = now  # the answer carries this station's callsign
        self._say(now, f"heard {self.partner} at {result.snr_db:+.0f} dB; answering, asking for L{self.want}")  # explain
        audio = build_answer(self.partner, self.call, self._report(), self.levels, level=self.tx_level, grid=self.grid)  # the answer frame, with this station's locator (since 0.33)
        wait = slot * slot_s + slots_left * slot_s + control_seconds(FRAME_TYPE_ACK, 0)  # its own slot's start, the rest of the window, then the confirmation at its slowest
        tx = self._send(now, audio, "answer", self.tx_level, "confirm", wait, f"slot {slot}, wants L{self.want}")  # wait for the lock to be confirmed
        tx.delay = slot * slot_s  # hold the answer back until its slot
        return tx  # the answer, with its waiting time

    def _on_addressed(self, result, now):  # a fully addressed message frame was heard
        if result.dest != "ALL" and self.state in LOCKED_STATES and self.partner:  # inside a contact: mail from the partner (delivered, handed over or passed on)
            return self._on_mail(result, now)  # hold it, or take it in
        if result.dest not in ("ALL", self.call):  # for some other station
            return None  # not this station's business
        key = (result.origin, result.msg_id)  # which message this is
        if key in self.bulletin_done:  # already delivered (a repeat)
            return None  # nothing to do
        parts = self.bulletin_parts.setdefault(key, {})  # the parts of this message so far
        parts[result.part] = result  # add this one
        whole = join_parts(list(parts.values()))  # is the message complete?
        if whole is not None:  # yes
            self.bulletins.append((result.origin, result.dest, whole))  # deliver it to the operator
            self.bulletin_done.add(key)  # remember it is done
            del self.bulletin_parts[key]  # the parts are no longer needed
            self._say(now, f"{'broadcast' if result.dest == 'ALL' else 'message'} from {result.origin}: {whole[:40]!r}")  # explain
        return None  # nobody acknowledges these

    def _on_mail(self, result, now):  # a fully addressed message frame from the partner, inside a contact
        if not self._traffic_from_partner(now):  # this station keeps the turn
            return None  # carry on with its own exchange
        self._note(result, failed=False)  # take in the measurements
        origin, number = result.origin, result.msg_id  # the message ID
        mine = result.dest == self.call  # for this station, or to be carried for another
        if not mine and (not self.carries or result.hops + 1 > HOP_LIMIT or (not self.mail.has_room(origin) and not self.mail.holding(origin, number))):  # this station will not keep it
            self._say(now, f"declined to carry mail for {result.dest}" + ("" if self.carries else " (carrying mail for others is off)"))  # explain
            return self._ack(now, number, OFFER_NO_MAIL, ACK_LINK, "ack")  # "I do not carry mail"
        if self.mail.is_handled(origin, number) or (not mine and self.mail.holding(origin, number)):  # an earlier copy was dealt with here, or is held here
            return self._ack(now, number, result.part, ACK_HAVE_IT, "ack")  # stop sending it
        parts = self.mail_parts.setdefault((origin, number), {})  # the parts of this message so far
        if any(held.parts != result.parts for held in parts.values()):  # split differently since
            parts.clear()  # the old parts are no use
        parts[result.part] = result  # add this one
        whole = join_parts(list(parts.values()))  # is the message complete?
        if whole is not None:  # yes
            del self.mail_parts[(origin, number)]  # the parts are no longer needed
            if mine:  # mail for this station
                self.bulletins.append((origin if origin == self.partner else f"{origin} via {self.partner}", self.call, whole))  # deliver it to the operator, saying who carried it
                self.mail.mark_handled(origin, number)  # never take it again
                if origin != self.partner:  # it came through a carrier
                    self.mail.add_receipt(origin, number, self.call)  # announce the delivery, so other carriers drop their copies and the origin learns of it
                    self.mail.forget_held_for_me(self.partner)  # that carrier has delivered
                self._say(now, f"mail from {origin}{'' if origin == self.partner else ' via ' + self.partner}: {whole[:40]!r}")  # explain
            else:  # mail to carry
                self.mail.hold(result.dest, origin, number, whole, result.hops, max(1, result.life_hours), self.partner)  # keep it
                self._say(now, f"holding mail from {origin} for {result.dest} (hop {result.hops})")  # explain
        return self._ack(now, number, result.part, ACK_OK, "ack")  # acknowledge, with a report and the level wanted next

    def _on_notice(self, result, now):  # a mail notice was heard
        fields = result.fields  # what it says
        origin = fields["origin"]  # who sent it
        self.notices[origin] = (now, fields)  # remember it, for whoever runs the station
        for number in self.mail.heard_notice(origin, fields["held"], fields["receipts"], fields["heard"]):  # this station's messages it shows delivered
            if number in self.outbox_ids and not (self.outbox_ids.index(number) == 0 and self.plan and self.job is None):  # still waiting here, and not the message being sent right now
                index = self.outbox_ids.index(number)  # where it is
                self.delivered.append(self.outbox.pop(index))  # delivered
                del self.outbox_to[index], self.outbox_ids[index]  # with its address and number
                self._say(now, f"{origin} reports message {number} delivered")  # explain
        if call_hash(self.call) in fields["held"]:  # it holds mail for this station
            self._say(now, f"{origin} holds mail for this station")  # explain
        return None  # a notice needs no reply

    @staticmethod  # needs nothing from the station itself
    def _is_call(result):  # does an answer frame carry a directed call rather than a reply to a beacon?
        """Return True if the answer frame's directed-call flag is set (Section 6.11)."""
        return bool(result.fields.get("directed"))  # the flag says so

    def expects_call_from(self, call, now):  # is a directed call from this station one this station asked for?
        """Return True if this station beaconed recently, or called `call` recently, so a directed call from `call` answers something the operator started."""
        return now - self.last_beacon_t <= EXPECT_S or now - self.called_t.get(call, -1e9) <= EXPECT_S  # a recent beacon, or a recent call to that station

    def _on_answer(self, result, now):  # an answer was heard
        if not self.available and self._is_call(result) and result.dest == self.call and self.state == "IDLE" and self.role in ("answerer", None):  # called by name while the operator is not available
            self.link = link_id(self.call, result.origin)  # the link number the caller is using
            self.tx_level = result.level  # reply at the level the call came at, which the path has just carried
            self._say(now, f"called by {result.origin}; replying: not available")  # explain
            audio = build_ack(self.link, 0, OFFER_UNAVAILABLE, ACK_LINK, self._report_of(result), level=self.tx_level)  # the one short reply
            self.link = -1  # no contact is made
            return self._send(now, audio, "not available", self.tx_level, None, 0.0, f"to {result.origin}")  # sent, and nothing more expected
        wanted = self.answer_calls or self.expects_call_from(result.origin, now) or (result.fields["mail_check"] and bool(self.mail.held_for(result.origin)))  # this station takes the call by itself, or it is a reply to something its operator started, or the caller asks for mail held here
        answering_call = self.role == "answerer" and self.pending is None and self._is_call(result) and wanted  # a listening station with nothing under way
        beaconing_call = self.role == "beaconer" and self.pending == "answer" and self._is_call(result)  # or one waiting in its own reply window, called by name instead of answered
        called_back = self.role == "caller" and self._is_call(result) and result.origin == self.target  # or one calling that very station, which calls back instead of confirming (its operator chose to respond)
        if self.state == "IDLE" and result.dest == self.call and (answering_call or beaconing_call or called_back):  # a directed call to this station that it takes
            if beaconing_call:  # it was in the middle of a beacon round
                self.candidates, self.role = [], "answerer" if self.single else self.role  # the round is over (a single round from a listening station goes back to listening afterwards)
            if called_back:  # its own call has been answered by a call back
                self.pending = None  # stop waiting for a confirmation
            self._say(now, f"called by {result.origin}")  # explain
            self.leads = True  # the called station takes the beaconing station's part from here on
            self._lock_with(result, now)  # lock with the caller (the plain confirmation it prepares is replaced below)
            return self._ack(now, 0, OFFER_TURN, ACK_LINK, "confirm", "offer", self._longest_reply())  # confirm the lock and hand the caller the first turn: it called because it has something to say
        if self.role != "beaconer" or self.pending != "answer" or result.dest != self.call:  # not expecting one, or it is for someone else
            return None  # stay silent
        if self.wide:  # a wide window: other answers may still come
            self.candidates.append(result)  # keep this one
            return None  # and decide when the window closes
        return self._lock_with(result, now)  # a single slot: lock at once

    def _lock_with(self, result, now):  # make the lock with the station whose answer is `result`
        self.partner = result.origin  # the answering station
        self.link = link_id(self.call, self.partner)  # link number: the beaconing station first
        self.allowed = common_levels(self.levels, result.fields["levels"])  # the levels both can use
        self.tx_level = cap_level(result.fields["report"].want_level, self.allowed)  # send at the level the partner asked for
        self._fresh_start(result)  # the first measurement of the partner
        self.state = "LOCKED"  # the lock is made
        self.my_turn = True  # the beaconing station goes first
        self.beacons = 0  # the beacon was answered
        self._say(now, f"locked with {self.partner}; told to send at L{self.tx_level}, asking for L{self.want}")  # explain
        return self._ack(now, 0, OFFER_REPLY, ACK_LINK, "confirm")  # confirm the lock and pass on the report

    def _on_ack(self, result, now):  # an acknowledgment was heard
        fields = result.fields  # its contents
        if fields["status"] == ACK_LINK and fields["part"] == OFFER_UNAVAILABLE and self.role == "caller" and self.state == "IDLE":  # the station being called says its operator is not available
            self.unavailable_from = self.partner  # remember who, for whoever runs the station
            self._release(now, f"{self.partner} is not available")  # stop calling at once
            return None  # nothing to send
        self.tx_level = cap_level(fields["report"].want_level, self.allowed)  # from now on, send at the level the partner asks for
        if self.state == "IDLE":  # the answering (or calling) station was waiting for this
            self._fresh_start(result)  # the first frame from the partner since the lock: ask straight away for the level it supports, rather than climbing from L0
            self.state = "LOCKED"  # the lock is confirmed
            self._say(now, f"locked with {self.partner}; told to send at L{self.tx_level}")  # explain
        status = fields["status"]  # the verdict
        if status == ACK_LINK and fields["part"] == OFFER_NO_MAIL and self.job is not None and self.pending == "ack":  # the partner will not carry the mail just offered
            self.pending, self.misses, self.resends = None, 0, 0  # the wait is over
            self.refused.add(self.partner)  # do not offer it mail again
            self._say(now, f"{self.partner} does not carry mail for others")  # explain
            self.job, self.plan = None, []  # nothing under way
            return self._next(now)  # carry on with anything else
        if status == ACK_LINK:  # no message is referred to
            return self._on_link_ack(result, fields["part"], now)  # lock business
        self._note(result, failed=False)  # a clean frame from the partner: take in its measurements
        if self.pending != "ack":  # not waiting for an acknowledgment
            return None  # nothing to do
        self.pending = None  # the wait is over
        self.misses = 0  # the partner is answering
        if self.state == "DEGRADED":  # the lock is recovering
            self.state = "LOCKED"  # the partner is hearing this station again
        if status == ACK_RESEND:  # the frame failed at the far end
            self.resends += 1  # count the request
            if self.resends > MAX_RESENDS:  # too many for one frame
                return self._reacquire(now)  # check the path at the slowest level
            self._say(now, f"asked to resend at L{self.tx_level}")  # explain
            return self._send_part(now)  # send the same frame again; the far end combines the copies
        self.resends = 0  # received (or already held): this frame is done
        self.part_index = len(self.plan) if status == ACK_HAVE_IT else self.part_index + 1  # "already have it" covers the whole message; otherwise move to the next frame
        if self.part_index >= len(self.plan):  # that was the last frame of the message
            if self.job is not None:  # it was mail
                self._job_done(now, status)  # record where it went
            else:  # this station's own message to its partner
                self.delivered.append(self.outbox.pop(0))  # the whole message is delivered
                self.outbox_to.pop(0)  # and its address goes with it
                number = self.outbox_ids.pop(0)  # and its number
                if number is not None:  # a message to a named station
                    self.mail.own_done(number)  # it no longer waits anywhere (carriers are told by receipt)
                self._say(now, f"message {self.current_id} delivered")  # explain
            self.plan = []  # nothing under way
        return self._next(now)  # carry on

    def _job_done(self, now, status):  # a piece of mail has been taken in full by the partner
        job, self.job = self.job, None  # the mail, and nothing under way any more
        already = status == ACK_HAVE_IT  # the partner had it already
        if job["kind"] == "deliver":  # held mail reached its destination
            self.mail.delivered_held(job["origin"], job["id"], self.partner)  # drop the copy, remember it, announce a receipt
            self._say(now, f"mail from {job['origin']} {'was already with' if already else 'delivered to'} {self.partner}")  # explain
        elif job["kind"] == "hand":  # this station's message is now carried by the partner as well
            self.mail.own_carried(job["id"], self.partner)  # note the carrier
            self._say(now, f"{self.partner} {'already carries' if already else 'is carrying'} the message for {job['dest']}")  # explain
        else:  # held mail passed on to another carrier
            self.mail.passed(job["origin"], job["id"], self.partner)  # note it
            self._say(now, f"{self.partner} {'already had' if already else 'took'} the mail for {job['dest']}")  # explain

    def _gives_way(self, now):  # both stations are transmitting as if they held the turn: who backs off?
        """Return True when this station may carry on handling the frame it just heard; False when it should ignore it.

        The clash happens when a frame is lost and each side then waits
        for the other. The beaconing station keeps the turn and ignores
        the frame; the answering station gives way and answers it.
        """
        if self.pending not in ("ack", "offer", "probe", "move"):  # not in the middle of an exchange of its own
            return True  # no clash
        if self.leads:  # the beaconing (or called) station keeps the turn
            return False  # ignore the frame; its own retry will follow
        self._say(now, "both sides were sending; giving way")  # explain
        self.pending = None  # stop waiting for a reply
        self.my_turn = False  # hand the turn back
        self.misses = self.probes = 0  # the partner is plainly there
        return True  # now answer the partner's frame

    def _on_link_ack(self, result, code, now):  # a status-3 acknowledgment: lock confirmed, turn offered, probe, or a reply to one of those
        if code == OFFER_MOVE:  # a move to a working frequency: the partner's proposal, or its agreement to this station's
            return self._on_move(result, now)  # deal with it
        if code in (OFFER_PROBE, OFFER_TURN) and not self._gives_way(now):  # the partner is asking something while this station is mid-exchange
            return None  # the beaconing station carries on with its own exchange
        if code == OFFER_PROBE:  # the partner lost this station and is probing
            self._fresh_start(result)  # start measuring afresh
            self.state = "LOCKED"  # the partner is there
            self.stored = None  # forget any half-received frame
            self._say(now, f"probe heard; replying, asking for L{self.want}")  # explain
            return self._ack(now, 0, OFFER_REPLY, ACK_LINK, "reply")  # "still here", with a fresh report
        self._note(result, failed=False)  # a clean frame from the partner
        if code == OFFER_TURN:  # the partner has nothing to send and offers the turn
            self.peer_empty = self.pending != "confirm"  # remember the partner is empty (except when this offer is a called station confirming the lock: it may yet have traffic)
            self.pending = None  # any wait is over
            if self.plan or self._has_traffic():  # this station has traffic for the partner
                self.my_turn = True  # take the turn
                return self._next(now)  # and use it
            self.my_turn = False  # nothing here either: the partner keeps the turn
            self.quiet = True  # the lock is idle; this station may take the turn later if it gets something to send
            return self._ack(now, 0, OFFER_REPLY, ACK_LINK, "reply")  # say so
        if self.pending == "probe":  # the partner answered a probe
            self._fresh_start(result)  # start measuring afresh
            self.state = "LOCKED"  # the lock is back
            self.pending = None  # the wait is over
            self.misses = self.probes = self.resends = 0  # clean slate
            self.my_turn = True  # carry on where things stopped
            if self.arriving:  # this was the first probe after a move
                self.arriving = False  # the partner has arrived too
                self._say(now, f"partner found on the working frequency; told to send at L{self.tx_level}, asking for L{self.want}")  # explain
            else:  # an ordinary recovery
                self._say(now, f"reacquired; told to send at L{self.tx_level}, asking for L{self.want}")  # explain
            return self._next(now)  # resume
        if self.pending == "move":  # the partner answered a move proposal with a plain reply: it cannot change frequency
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
            self.moved = True  # do not ask again in this contact
            self._say(now, "partner cannot change frequency; staying on the calling frequency")  # explain
            return self._next(now)  # carry on here
        if self.pending == "offer":  # the partner declined the turn: it is empty too
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
            self.peer_empty = True  # both sides are empty
            return self._next(now)  # close the contact, or stay quiet
        if self.pending == "confirm":  # the beaconing station confirmed the lock
            self.pending = None  # the wait is over
        return None  # nothing to send

    def _on_move(self, result, now):  # a status-3 acknowledgment about moving to a working frequency
        steps = result.fields["msg_id"]  # the offset, as an unsigned 16-bit count
        offset_hz = (steps - 0x10000 if steps >= 0x8000 else steps) * MOVE_STEP_HZ  # back to a signed offset in hertz
        self._note(result, failed=False)  # a clean frame from the partner
        if self.pending == "move" and (offset_hz == self.move_to_hz or self.leads):  # the partner agrees (or both proposed at once and the beaconing station's proposal stands)
            if offset_hz != self.move_to_hz:  # the partner proposed somewhere else at the same moment
                return None  # ignore it; this station's own proposal will be repeated
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
            self.moved = True  # the move is agreed
            self._retune(now, offset_hz)  # change frequency now
            self.settle_until = now + MOVE_SETTLE_S  # then give both radios a moment before probing
            self.last_traffic, self.idle_warned = now, False  # the idle clock for the working frequency starts now
            self.my_turn = True  # this station speaks first on the new frequency
            self._say(now, f"partner agreed; moving {offset_hz / 1000.0:+.1f} kHz to the working frequency")  # explain
            return None  # nothing to send until the radios have settled
        self.pending = None  # a proposal from the partner ends any wait of this station's own
        self.my_turn = False  # the partner speaks first after the move
        self.moved = True  # one move per contact, whoever asked
        if not self.can_move:  # this station's radio cannot be retuned by the program
            self._say(now, "partner proposed a working frequency; this station cannot change frequency, staying")  # explain
            return self._ack(now, 0, OFFER_REPLY, ACK_LINK, "reply")  # a plain reply means "no"
        reply = self._ack(now, steps, OFFER_MOVE, ACK_LINK, "move-ok")  # the same value sent back means "agreed"
        self._retune(now + reply.seconds + 0.5, offset_hz)  # change frequency once the agreement has been sent
        self.await_since = now + reply.seconds  # and wait there for the partner
        self._say(now, f"partner proposed a working frequency; agreeing and moving {offset_hz / 1000.0:+.1f} kHz")  # explain
        return reply  # the agreement

    def _traffic_from_partner(self, now):  # the partner has sent a message frame (its own, or mail): take the turn bookkeeping
        """Return False if the frame should be ignored because this station keeps the turn; otherwise update the turn and idle state and return True."""
        if self.state == "IDLE":  # the confirmation was missed, but a frame with this link number proves the lock
            self.state = "LOCKED"  # so lock
        if self.pending in ("confirm", "offer"):  # the partner's message answers a pending confirmation or turn offer
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
        elif not self._gives_way(now):  # a message arrived while this station was sending its own
            return False  # the beaconing station carries on with its own exchange
        self.my_turn = False  # the partner has the turn
        self.peer_empty = False  # and has traffic
        self.quiet = False  # the lock is no longer idle
        self.idle_told = False  # and the partner will need telling when it is again
        self.last_traffic, self.idle_warned = now, False  # a message frame has come in: the idle clock starts again
        return True  # take the frame

    def _on_message(self, result, now):  # a message frame was heard
        if not self._traffic_from_partner(now):  # this station keeps the turn
            return None  # the beaconing station carries on with its own exchange
        self.tx_level = cap_level(result.want_level, self.allowed)  # every message frame says which level its sender wants back
        self._note(result, failed=False)  # take in the measurements
        status = ACK_OK  # this frame was received
        if result.msg_id in self.done_ids or self.mail.is_handled(self.partner, result.msg_id):  # the whole message is already here (in this contact, or an earlier copy of it)
            status = ACK_HAVE_IT  # tell the sender to stop sending it
        else:  # a message still being collected
            parts = self.partial.setdefault(result.msg_id, {})  # the parts of this message so far
            if any(held.parts != result.parts for held in parts.values()):  # the sender has split the message differently since
                parts.clear()  # so the parts of the old split are no use
            parts[result.part] = result  # add (or replace) this one
            whole = join_parts(list(parts.values()))  # is the message complete?
            if whole is not None:  # yes
                self.inbox.append(whole)  # deliver it to the operator
                self.done_ids.add(result.msg_id)  # remember it is done
                self.mail.mark_handled(self.partner, result.msg_id)  # and, beyond this contact, so a copy carried by another station is not delivered again
                del self.partial[result.msg_id]  # the parts are no longer needed
                self._say(now, f"received message {result.msg_id}: {whole[:40]!r}")  # explain
        return self._ack(now, result.msg_id, result.part, status, "ack")  # acknowledge, with a report and the level wanted next

    def _on_ident(self, result, now):  # an identification was heard
        if not result.fields["final"]:  # a routine identification
            return None  # needs no reply
        if self.sent_final:  # this station has already said goodbye
            self._release(now, "contact closed")  # both sides are done
            return None  # nothing more to send
        reply = self._ident(now, final=True)  # say goodbye in return
        self._release(now, "contact closed by partner")  # and leave (the reply still goes out)
        if self.tune_at is not None:  # the contact was on a working frequency
            self.tune_at = now + reply.seconds + 0.5  # go back to the calling frequency only after the goodbye has been sent
        return reply  # the closing identification

    # ---- acting on the clock ----

    def poll(self, now):  # is there something to send without having heard anything?
        """Return a Transmission if the station should transmit now (a first frame, or a retry after a timeout), else None."""
        if now - self.tidied >= MAIL_TIDY_S:  # time to look for expired mail
            self.tidied = now  # remember when
            for number in self.mail.tidy():  # this station's messages that ran out undelivered
                if number in self.outbox_ids and not (self.outbox_ids.index(number) == 0 and self.plan and self.job is None):  # still waiting here, and not being sent right now
                    index = self.outbox_ids.index(number)  # where it is
                    self.expired.append(self.outbox.pop(index))  # expired, not delivered
                    del self.outbox_to[index], self.outbox_ids[index]  # with its address and number
                    self._say(now, f"message {number} expired undelivered")  # explain
        if self.state == "RELEASED":  # the contact is over
            return None  # nothing to send
        if self._watching_idle():  # this station moved the contact to a working frequency and is keeping it open
            idle = now - self.last_traffic  # how long since a message went either way
            if idle >= WORKING_IDLE_S:  # the idle limit has been reached with no messages
                self._say(now, f"no messages for {WORKING_IDLE_S / 60:.0f} minutes on the working frequency; closing the contact and returning to the calling frequency")  # explain
                self.close_when_done = True  # close properly; both stations return when the contact ends
            elif idle >= WORKING_IDLE_S - WORKING_WARN_S and not self.idle_warned:  # one minute to go
                self.idle_warned = True  # warn once
                self._say(now, f"no messages for {(WORKING_IDLE_S - WORKING_WARN_S) / 60:.0f} minutes; returning to the calling frequency in one minute unless a message is sent")  # the operator's warning
        if self.pending is not None:  # waiting for a reply
            if now < self.deadline:  # and there is still time
                return None  # keep waiting
            return self._timed_out(now)  # the reply did not come
        if self.settle_until is not None:  # a move has been agreed and the radios are retuning
            if now < self.settle_until:  # not settled yet
                return None  # wait
            self.settle_until, self.arriving = None, True  # settled: look for the partner on the working frequency
            return self._ack(now, 0, OFFER_PROBE, ACK_LINK, "probe", "probe", control_seconds(FRAME_TYPE_ACK, self.want))  # "are you here?" at the level in use
        if self.await_since is not None and now - self.await_since >= MOVE_WAIT_S:  # moved at the partner's request, and the partner never appeared
            self._release(now, "partner not heard on the working frequency; lock given up")  # go back to the calling frequency
            return None  # nothing to send
        if self.state in LOCKED_STATES and self.quiet and not self.my_turn and now - self.last_activity >= self._quiet_gap():  # the lock is idle, the partner holds the turn and has had time to speak
            if self._has_traffic() or self.close_when_done:  # this station now has a message or mail for the partner, or wants the contact closed
                self.quiet, self.my_turn = False, True  # take the turn (if the partner starts at the same moment, the usual give-way rule settles it)
                return self._next(now)  # send the message, or the closing identification
            if now - self.last_ident >= IDENT_EVERY_S:  # nearly ten minutes since this station sent its callsign
                return self._ident(now, final=False)  # identify, turn or no turn
        if self.long_waiting is not None and self.state == "IDLE" and self.pending is None:  # a long beacon is waiting and the station is free
            from modem.params import LONG_LEVEL  # the long beacon's level number
            if self._hold(now, "long beacon", LONG_LEVEL):  # the frequency is in use
                return None  # wait for it to clear
            audio, self.long_waiting = self.long_waiting, None  # take it
            self.last_ident = now  # it carries this station's callsign
            return self._send(now, audio, "long beacon", LONG_LEVEL, None, 0.0, "nobody answers a long beacon")  # send it; it asks for no reply
        if self.broadcasts and self.state == "IDLE":  # a broadcast is waiting and no contact is in progress
            if self._hold(now, "broadcast", self.broadcasts[0][1]):  # the frequency is in use
                return None  # wait for it to clear
            audio, level, note = self.broadcasts.pop(0)  # its next frame
            self.last_ident = now  # a fully addressed frame carries this station's callsign
            return self._send(now, audio, "broadcast", level, None, 0.0, note)  # send it; nobody replies
        if self.role == "beaconer" and self.state == "IDLE":  # looking for a partner
            if self._hold(now, "beacon", self.callup):  # the frequency is in use
                return None  # wait for it to clear
            return self._beacon(now)  # call
        if self.role == "caller" and self.state == "IDLE":  # calling one particular station
            if self._hold(now, "call", self.callup if self.calls == 0 else min(self.levels)):  # the frequency is in use
                return None  # wait for it to clear
            return self._call(now)  # call it
        if self.state in LOCKED_STATES and self.my_turn:  # locked, and it is this station's turn
            if self.peer_empty and not self.plan and not self._has_traffic() and not self.close_when_done:  # both sides idle, lock kept open
                if now - self.last_activity < KEEPALIVE_S:  # not silent for long enough yet
                    return None  # stay quiet
                self.peer_empty = False  # time to check on the partner: offer the turn again
            return self._next(now)  # send whatever is due
        if self.state in LOCKED_STATES and now - self.last_activity >= LOCK_TIMEOUT_S:  # locked, waiting for the partner, and nothing heard for a long time
            self._release(now, "partner not heard for five minutes; lock given up")  # stop waiting
        return None  # nothing to do

    def _quiet_gap(self):  # how long an idle station waits before taking the turn for itself
        return control_seconds(FRAME_TYPE_IDENT, self.want) + TURNAROUND_S + self.reply_margin  # long enough for a closing identification from the partner to arrive first

    def _watching_idle(self):  # is this station the one that gives up an idle working frequency?
        return bool(self.offset_hz) and self.proposed_move and self.state in LOCKED_STATES and not self.close_when_done  # on a working frequency it asked for, locked, and keeping the contact open

    def next_wake(self):  # when should poll() be called again?
        """Return the time at which this station next needs attention, or None if it is waiting to hear something."""
        usual = self._usual_wake()  # the next moment the ordinary rules need attention
        if not self._watching_idle():  # no idle working frequency to watch
            return usual  # nothing to add
        idle_at = self.last_traffic + (WORKING_IDLE_S if self.idle_warned else WORKING_IDLE_S - WORKING_WARN_S)  # when the warning, or the closing, falls due
        return idle_at if usual is None else min(usual, idle_at)  # whichever comes first

    def _usual_wake(self):  # the next moment the ordinary rules need attention
        if self.state == "RELEASED":  # the contact is over
            return None  # never
        if self.pending is not None:  # waiting for a reply
            return self.deadline  # until the deadline
        if self.settle_until is not None:  # waiting for the radios to retune after a move
            return self.settle_until  # until they have settled
        if self.state in LOCKED_STATES and self.quiet and not self.my_turn and (self._has_traffic() or self.close_when_done):  # idle without the turn, but with something to send or a contact to close
            return self.last_activity + self._quiet_gap()  # until the partner has had its chance to speak
        if self.await_since is not None:  # waiting for the partner on a working frequency
            return self.await_since + MOVE_WAIT_S  # until that wait runs out
        if self.state in LOCKED_STATES and self.my_turn and self.peer_empty and not self.close_when_done:  # idle with the lock kept open
            return self.last_activity + KEEPALIVE_S  # until the keep-alive is due
        if self.state in LOCKED_STATES and not self.my_turn:  # locked and waiting for the partner
            return self.last_activity + LOCK_TIMEOUT_S  # until the silence has lasted too long
        return None  # nothing scheduled

    def _call(self, now):  # send a directed call
        if self.calls >= CALL_TRIES:  # tried enough
            self._release(now, f"no answer from {self.target}")  # give up
            return None  # nothing to send
        self.calls += 1  # count the call
        self.called_t[self.target] = now  # a call back from that station is expected for a while
        self.partner = self.target  # the station being called
        self.link = link_id(self.partner, self.call)  # link number: the called station takes the beaconing station's place, so it comes first
        self.allowed = list(self.levels)  # the called station's levels are not known yet; assume it has the same
        self.tx_level = self.callup if self.calls == 1 else min(self.allowed)  # the first call at the middle level, the rest at the slowest
        self.last_ident = now  # the call carries this station's callsign
        if self.calls == 1:  # the first call
            self._say(now, f"calling {self.target}")  # explain
        heard = self.heard_at.get(self.target)  # the last reading of the called station, if it was heard lately
        if heard is not None and now - heard[0] <= HEARD_FOR_CALL_S:  # recent enough to be useful
            report = heard[1]  # it goes with the call, so the called station can start at the right level
        else:  # never heard, or long ago
            report = ChannelReport(float(SNR_FLOOR_DB), float("nan"), 0.0, 0)  # no measurement, asking for L0
        audio = build_answer(self.partner, self.call, report, self.levels, mail_check=True, level=self.tx_level, directed=True, grid=self.grid)  # an answer frame marked as a directed call, asking for any mail the called station holds for this one
        return self._send(now, audio, "call", self.tx_level, "confirm", control_seconds(FRAME_TYPE_ACK, 0), f"to {self.target}")  # wait for the called station to confirm the lock

    def _notice(self, now):  # a mail notice to send just before a beacon, or None
        if self.notice_sent:  # one has just gone: the beacon is next
            self.notice_sent = False  # and the next beacon may have its own
            return None  # send the beacon
        if not self.available or (self.callup == 0 and now - self.last_notice_l0 < NOTICE_L0_EVERY_S):  # not taking contacts, or an L0 beacon soon after the last L0 notice
            return None  # no notice
        held, receipts, heard = self.mail.notice_lists(self._heard_calls(now))  # what it would say
        if not held and not receipts:  # nothing held and nothing delivered lately
            return None  # no notice
        if self.callup == 0:  # going with an L0 beacon
            self.last_notice_l0 = now  # remember when
        self.notice_sent = True  # the beacon follows
        self.last_ident = now  # the notice carries the callsign
        audio = build_notice(self.call, held, receipts, heard, level=self.callup)  # the notice, at the beacon's level
        return self._send(now, audio, "mail notice", self.callup, None, 0.0, f"holds mail for {len(held)}, {len(receipts)} receipt(s)")  # no reply is expected; the beacon comes next

    def _beacon(self, now):  # send a beacon
        notice = self._notice(now)  # a mail notice first, if there is anything to tell
        if notice is not None:  # there is
            return notice  # send it; the beacon goes at the next look
        self.beacons += 1  # count it
        self.last_beacon_t = now  # directed calls from anyone are expected for a while
        self.last_ident = now  # a beacon carries the callsign
        self.candidates = []  # a new reply window starts empty
        if not self.available:  # the operator is not available: a presence beacon, taking no answers
            self.beacon_sent_at = self.callup  # at the middle level (nobody will answer, so there is no L0 retry)
            audio = build_beacon(self.call, self.grid, self.levels, listening=False, level=self.beacon_sent_at, steps=self.power_steps)  # "here I am, not taking contacts" (with power steps before it, if wanted)
            tx = _with_lead(self._send(now, audio, "beacon", self.beacon_sent_at, None, 0.0, "not available: presence only"), self.power_steps)  # no reply window
            self._release(now, "presence beacon sent; not taking contacts")  # the round is over
            return tx  # send it
        self.beacon_sent_at = self.callup  # the middle level first; L0 after that brings no answer
        audio = build_beacon(self.call, self.grid, self.levels, listening=True, mail_check=True, holds_mail=bool(self.mail.bag), level=self.beacon_sent_at, wide=self.wide, steps=self.power_steps)  # the beacon: asking for any mail held for this station, and saying whether it holds mail for others (and power steps before it, if wanted)
        window = (WIDE_SLOTS if self.wide else 1) * reply_slot(self.beacon_sent_at)  # how long to listen for answers: slots sized for this level
        return _with_lead(self._send(now, audio, "beacon", self.beacon_sent_at, "answer", window - REPLY_MARGIN_S, "wide window" if self.wide else ""), self.power_steps)  # then listen for the whole window (plus any extra margin a live station allows)

    def _hold(self, now, what, level):  # listen before transmitting
        """Return True when the frequency is in use where a `what` at `level` would go, so it must wait (spec Section 6.14). Replies inside an exchange are never held: only what this station starts unasked."""
        if self.busy is None or not self.busy(level):  # no check is made, or the frequency is clear
            if self.held_since is not None:  # something was being held
                self._say(now, f"frequency clear after {now - self.held_since:.0f} s; sending the {what}")  # explain
                self.held_since = None  # no longer holding
            return False  # go ahead
        if self.held_since is None:  # just begun to hold
            self.held_since = now  # remember when
        if now - self.held_told >= HOLD_TELL_S:  # the operator has not been told lately
            self.held_told = now  # remember when
            self._say(now, f"frequency in use: holding the {what} until it is clear")  # explain
        return True  # wait

    def _timed_out(self, now):  # the reply being waited for did not come
        waited_for = self.pending  # what was expected
        self.pending = None  # stop waiting
        if waited_for == "answer" and self.candidates:  # a wide window has closed with at least one answer in it
            best = max(self.candidates, key=lambda r: r.snr_db)  # choose the strongest
            self.wide = len(self.candidates) > 1  # several stations are waiting: keep the window wide for the next call
            self._say(now, f"{len(self.candidates)} answer(s) in the window; choosing {best.origin}")  # explain
            return self._lock_with(best, now)  # lock with it
        if waited_for == "answer" and self.beacon_sent_at > 0:  # nobody answered the faster beacon: perhaps the path is too weak for it
            self.callup, self.beacons = 0, self.beacons - 1  # call again at once at L0; the faster try does not count against the tries
            self._say(now, f"no answer at L{self.beacon_sent_at}; calling again at L0")  # explain
            return self._beacon(now)  # the L0 beacon
        if waited_for == "answer":  # nobody answered the beacon (or the answers collided)
            self.wide = True  # ask for a wide window from now on
            if self.beacons >= BEACON_TRIES:  # enough tries
                self._release(now, "no answer to the beacon")  # give up
                return None  # nothing to send
            return self._beacon(now)  # call again
        if waited_for == "confirm" and self.role == "caller":  # a directed call went unanswered
            self.state = "IDLE"  # still looking
            return self._call(now)  # call again, or give up after enough tries
        if waited_for == "confirm":  # the lock was never confirmed
            self.state = "IDLE"  # go back to listening
            self._say(now, "lock not confirmed; listening again")  # explain
            return None  # nothing to send
        if waited_for == "final":  # the partner did not say goodbye
            self.finals += 1  # count it
            if self.finals >= FINAL_TRIES:  # tried enough
                self._release(now, "contact closed (no closing reply heard)")  # leave anyway
                return None  # nothing to send
            return self._ident(now, final=True)  # say goodbye once more
        if waited_for == "move":  # a proposal to move got no reply
            if self.move_tries < MOVE_TRIES:  # try once more here
                return self._propose_move(now)  # the same proposal again
            self.moved = True  # the partner may have agreed without being heard, in which case it has already moved
            self._retune(now, self.move_to_hz)  # so go and look for it on the working frequency
            self.settle_until = now + MOVE_SETTLE_S  # after the radio has settled
            self.last_traffic, self.idle_warned = now, False  # the idle clock for the working frequency starts now
            self._say(now, "no reply to the move; looking for the partner on the working frequency")  # explain
            return None  # the probe follows
        if waited_for == "probe":  # a reacquire probe went unanswered
            self.probes += 1  # count it
            if self.probes >= REACQUIRE_TRIES:  # tried enough
                self._release(now, f"lock lost; {len(self.outbox)} message(s) not delivered")  # give up the lock
                return None  # nothing to send
            return self._reacquire(now)  # probe again
        self.misses += 1  # a message frame or a turn offer got no reply
        if self.state == "LOCKED":  # a missed reply degrades the lock
            self.state = "DEGRADED"  # but does not drop it
        if self.misses >= MISS_LIMIT:  # too many in a row
            return self._reacquire(now)  # go and find the partner again
        self.tx_level = cap_level(self.tx_level - 1, self.allowed)  # try one level slower
        self._say(now, f"no reply; trying again at L{self.tx_level}")  # explain
        if waited_for == "ack":  # it was a message frame
            return self._send_part(now)  # send it again
        return self._ack(now, 0, OFFER_TURN, ACK_LINK, "offer", "offer", self._longest_reply())  # it was a turn offer: offer again


# ---- The compiled station (library interface 10) ----

_RESULT_SKIP = ("body_llrs", "steps", "power_steps")  # receiver report fields the station never needs (soft bits stay in Python; the power steps are for the operator, since 0.38)


def _result_json(result):  # a receiver report as plain data for the library
    """Return the fields of an RxResult as a dict (the control fields' channel report as a dict, level lists as lists)."""
    data = {}  # the fields
    for name in result.__dataclass_fields__:  # each field of the report
        if name in _RESULT_SKIP:  # not needed
            continue  # skipped
        value = getattr(result, name)  # its value
        if name == "fields" and value is not None:  # a control frame's fields
            value = {key: (vars(item) if isinstance(item, ChannelReport) else list(item) if isinstance(item, tuple) else item) for key, item in value.items()}  # made plain
        data[name] = value  # kept
    return data  # the report


def _result_back(data):  # plain data -> a receiver report again (for the attributes that hold reports)
    """Return an RxResult built from the dict _result_json made."""
    from modem import RxResult  # the report type
    data = dict(data)  # a copy
    fields = data.get("fields")  # a control frame's fields
    if fields is not None:  # there are some
        fields = dict(fields)  # a copy
        if isinstance(fields.get("report"), dict):  # a channel report
            fields["report"] = ChannelReport(**fields["report"])  # as a record
        if isinstance(fields.get("levels"), list):  # a level list
            fields["levels"] = tuple(fields["levels"])  # as Python keeps it
        data["fields"] = fields  # put back
    return RxResult(**data)  # the report


def _build(frame):  # a frame description from the library -> its audio
    """Return the audio of the frame the compiled station described (built by the compiled transmitter)."""
    kind = frame["type"]  # which frame
    if kind == "ack":  # an acknowledgment
        return build_ack(frame["link"], frame["msg_id"], frame["part"], frame["status"], ChannelReport(**frame["report"]), level=frame["level"])  # built
    if kind == "ident":  # an identification
        return build_ident(frame["call"], frame["link"], final=frame["final"], level=frame["level"])  # built
    if kind == "answer":  # an answer or a directed call
        return build_answer(frame["dest"], frame["origin"], ChannelReport(**frame["report"]), tuple(frame["levels"]), mail_check=frame["mail_check"], level=frame["level"], directed=frame["directed"], grid=frame.get("grid", ""))  # built, with the sender's locator (since 0.33)
    if kind == "beacon":  # a beacon
        return build_beacon(frame["call"], frame["grid"], tuple(frame["levels"]), listening=frame["listening"], mail_check=frame["mail_check"], holds_mail=frame["holds_mail"], level=frame["level"], wide=frame["wide"], steps=bool(frame.get("steps")))  # built (with the power-steps flag, since 0.38)
    if kind == "notice":  # a mail notice
        return build_notice(frame["call"], frame["held"], frame["receipts"], frame["heard"], level=frame["level"])  # built
    if kind == "message":  # a link message frame
        return build_frame(frame["text"], frame["level"], frame["part"], frame["parts"], link=frame["link"], msg_id=frame["msg_id"], want_level=frame["want_level"])  # built
    if kind == "addressed":  # a fully addressed frame
        return build_frame(frame["text"], frame["level"], frame["part"], frame["parts"], msg_id=frame["msg_id"], dest=frame["dest"], origin=frame["origin"], hops=frame["hops"], life_hours=frame["life_hours"])  # built
    from modem.longbeacon import build_long_beacon  # the long beacon's transmitter
    return build_long_beacon(frame["call"], frame["grid"], available=frame["available"], holds_mail=frame["holds_mail"])  # built


_AS_TUPLES = ("history", "bulletins", "broadcasts")  # attributes whose items Python keeps as tuples
_AS_SETS = ("worked", "refused", "done_ids", "bulletin_done")  # attributes Python keeps as sets
_OWN = ("core", "mail", "busy", "stored", "stored_sig", "_busy_error", "power_steps")  # attributes kept here in Python, not in the library (power steps since 0.38: the library's beacon is built here with them)


class CompiledStation:  # one station, its rules in the compiled library (cpp/src/station.cpp)
    """The same Station, its state and rules in C++. Methods and attributes behave as PythonStation's; the receiver and the transmitter's audio stay in Python's hands (both compiled underneath)."""

    def __init__(self, call, grid, levels=None, close_when_done=True):  # set up a station
        object.__setattr__(self, "core", native.compiled_station())  # the station in the library
        object.__setattr__(self, "busy", None)  # no listen-first check yet
        object.__setattr__(self, "stored", None)  # soft bits of the last failed message frame
        object.__setattr__(self, "stored_sig", None)  # which frame that was
        object.__setattr__(self, "_busy_error", None)  # an error raised inside the check, to pass on
        object.__setattr__(self, "power_steps", False)  # power steps before each beacon (since 0.38; added here, the library's timing allowed for in reply_margin by the caller)
        self._ask("init", call, grid, None if levels is None else list(levels), close_when_done)  # set up (refuses a bad callsign as Python does)
        self.mail = Mailroom(clean_call(call))  # the mail kept between contacts

    def _ask(self, op, *args):  # run one method in the library
        """Return the library's answer to `op`; drop the receiver's kept soft bits when it says so."""
        mail = self.__dict__.get("mail")  # the mail store
        answer, clear = self.core.request(op, args, mail.clock() if mail is not None else 0.0)  # asked, at the mail store's time
        if clear:  # the station forgot a half-received frame
            object.__setattr__(self, "stored", None)  # so do we
        error, self.__dict__["_busy_error"] = self.__dict__["_busy_error"], None  # an error inside the listen-first check
        if error is not None:  # there was one
            raise error  # passed on, as Python's station would
        return answer  # the answer

    def _tx(self, data):  # a transmission description -> a Transmission
        """Return the Transmission (with its audio) the library described, or None."""
        if data is None:  # nothing to send
            return None  # nothing
        steps = self.power_steps and data["frame"]["type"] == "beacon"  # power steps before this beacon (since 0.38)
        audio = _build(dict(data["frame"], steps=steps))  # the audio (a beacon's header saying whether steps came first)
        if len(audio) != round(data["seconds"] * FS):  # the library's idea of its length must match
            raise RuntimeError(f"frame length mismatch: {len(audio)} samples built, {data['seconds'] * FS:.0f} expected")  # a fault, never ignored
        return _with_lead(Transmission(audio, data["kind"], data["level"], data["note"], data["delay"]), steps)  # the transmission, with its power steps if wanted

    def __getattr__(self, name):  # station.<name>, read from the library
        if name.startswith("__") or name in _OWN:  # Python's own lookups, or an attribute kept here
            raise AttributeError(name)  # not in the library
        value = self._ask("get", name)  # the value
        if name in _AS_TUPLES:  # items kept as tuples
            return [tuple(item) for item in value]  # as Python has them
        if name in _AS_SETS:  # a set
            return set(value)  # as Python has it
        if name == "levels":  # a tuple
            return tuple(value)  # as Python has it
        if name in ("last_result",) and value is not None:  # a receiver report
            return _result_back(value)  # as a report
        if name == "candidates":  # receiver reports
            return [_result_back(item) for item in value]  # as reports
        if name == "heard_at":  # callsign -> (time, report)
            return {call: (when, ChannelReport(**report)) for call, (when, report) in value.items()}  # as Python has it
        if name == "notices":  # callsign -> (time, fields)
            return {call: (when, fields) for call, (when, fields) in value.items()}  # as tuples
        return value  # as it is

    def __setattr__(self, name, value):  # station.<name> = value
        if name == "mail":  # a mail store handed in
            if not isinstance(value, CompiledMailroom):  # the compiled station needs the compiled store
                raise TypeError("a compiled station needs a CompiledMailroom")  # refuse
            object.__setattr__(self, "mail", value)  # kept alive here
            self.core.set_mail(value.store)  # and used by the library
            return  # done
        if name == "busy":  # the listen-first check
            object.__setattr__(self, "busy", value)  # kept here
            self.core.set_busy(None if value is None else self._busy_call)  # the library calls it through us
            return  # done
        if name in _OWN:  # kept here
            object.__setattr__(self, name, value)  # stored
            return  # done
        self._ask("set", name, value)  # in the library

    def _busy_call(self, _context, level):  # called by the library from inside a request
        """Return 1 when the frequency is in use at `level`, else 0; keep any error to raise after the request."""
        try:  # the check is the caller's code
            return 1 if self.busy(level) else 0  # its answer
        except Exception as err:  # noqa: BLE001 - passed on after the request, as Python's station would raise it
            self.__dict__["_busy_error"] = err  # kept
            return 0  # "clear" for now

    # ---- the methods, as PythonStation's ----

    def beacon(self): self._ask("beacon")  # become the station that calls
    def listen(self): self._ask("listen")  # become the station that answers
    def call_station(self, target): self._ask("call_station", target)  # call one station by name
    def beacon_once(self): self._ask("beacon_once")  # one beacon round, then listen
    def call_once(self, target): self._ask("call_once", target)  # one call, then listen
    def long_beacon(self, holds_mail=None): self._ask("long_beacon", holds_mail)  # queue a long beacon
    def queue(self, text, to=None): self._ask("queue", text, to)  # a message to send
    def broadcast(self, text, level=BROADCAST_LEVEL): self._ask("broadcast", text, level)  # a broadcast to ALL
    def unqueue(self, text, to=None): return self._ask("unqueue", text, to)  # take a message back
    def mail_waiting_at(self, call): return self._ask("mail_waiting_at", call)  # mail waiting there?
    def end(self): self._ask("end")  # close when done
    def cancel(self, now): return self._ask("cancel", now)  # stop calling
    def tuning(self, now): return self._ask("tuning", now)  # where the radio should be
    def next_wake(self): return self._ask("next_wake")  # when to poll next
    def new_contact(self): self._ask("new_contact")  # ready for another contact
    def expects_call_from(self, call, now): return self._ask("expects_call_from", call, now)  # a call asked for?
    def poll(self, now): return self._tx(self._ask("poll", now))  # anything to send on the clock?
    def handle(self, result, now): return self._tx(self._ask("handle", _result_json(result), now))  # react to a frame
    def _ack(self, now, msg_id, part, status, kind, expects=None, reply_s=0.0): return self._tx(self._ask("_ack", now, msg_id, part, status, kind, expects, reply_s))  # an acknowledgment (tests)

    hear = PythonStation.hear  # the receiver, with a failed message frame kept for its retry: the same code as the Python station


class Station:  # one station's link rules: the compiled station when the library is in use, otherwise the Python one
    """Make a CompiledStation when the compiled library is in use, else a PythonStation; both behave the same."""

    def __new__(cls, call, grid, levels=None, close_when_done=True):  # which kind to make
        return (CompiledStation if native._lib is not None else PythonStation)(call, grid, levels, close_when_done)  # the compiled one when it can be
