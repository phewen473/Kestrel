"""One Kestrel station's link rules: what to send, and what to do with what it hears.

A Station never touches a radio. It is handed the audio it "heard" and
the time, and it returns the audio it wants to send next. That keeps the
rules testable: link/simulate.py connects two Stations through the
channel simulator, and a real program would connect one to a sound card.

The life of a contact:
    beacon -> answer -> acknowledgment (lock confirmed)
    message frame -> acknowledgment, repeated; the turn passes when a station has nothing left
    identification with the end-of-contact flag, from each side
"""

from dataclasses import dataclass  # simple record type for a transmission

import numpy as np  # numerical arrays

from modem import (  # the modem: frames, reports, planner
    ACK_HAVE_IT, ACK_LINK, ACK_OK, ACK_RESEND, LEVELS, ChannelReport, build_ack, build_answer, build_beacon, build_frame, build_ident,  # (continued)
    control_seconds, frame_seconds, join_parts, link_id, plan_at_level, receive,  # (continued)
)  # end of the import list
from modem.address import clean_call  # tidies a callsign
from modem.params import (  # frame type numbers and the airtime limit
    AIRTIME_POOR_CAP_S, FRAME_TYPE_ACK, FRAME_TYPE_ANSWER, FRAME_TYPE_BEACON, FRAME_TYPE_IDENT, FRAME_TYPE_LINK, FS, MSG_ID_BITS,  # (continued)
)  # end of the import list
from modem.text import pick_size_class  # which frame size a piece of text needs

from .adapt import cap_level, common_levels, supported_level, wanted_level  # speed adaptation rules
from .params import (  # timing and retry settings
    BEACON_TRIES, FINAL_TRIES, HISTORY, IDENT_EVERY_S, KEEPALIVE_S, MAX_RESENDS, MISS_LIMIT, OFFER_PROBE, OFFER_REPLY, OFFER_TURN,  # (continued)
    REACQUIRE_TRIES, REPLY_MARGIN_S, STEP_UP_CLEAN, TURNAROUND_S,  # (continued)
)  # end of the import list

LOCKED_STATES = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states in which the station has a partner


@dataclass  # a plain record
class Transmission:  # one frame the station wants on the air
    """Audio to transmit, with a description for logs."""

    audio: np.ndarray  # the samples
    kind: str  # what the frame is: beacon, answer, message, ack, offer, probe, reply, ident, final
    level: int  # the speed level it is sent at
    note: str = ""  # extra detail for the log

    @property  # computed from the audio
    def seconds(self):  # airtime
        """Length of the transmission, in seconds."""
        return len(self.audio) / FS  # samples divided by the sample rate


class Station:  # the link rules for one station
    """A station's state and its rules. Use beacon() or listen() to start, queue() to add messages, then poll(), hear() and handle()."""

    def __init__(self, call, grid, levels=None, close_when_done=True):  # set up a station
        self.call = clean_call(call)  # this station's callsign
        self.grid = grid  # its grid locator
        self.levels = tuple(levels) if levels is not None else tuple(spec.number for spec in LEVELS)  # the speed levels it can use
        self.close_when_done = close_when_done  # end the contact once neither side has anything left to send
        self.state = "IDLE"  # lock state: IDLE, LOCKED, DEGRADED, REACQUIRE or RELEASED
        self.role = None  # "beaconer" or "answerer"
        self.partner = ""  # the other station's callsign
        self.link = -1  # the pair's link number
        self.allowed = [0]  # speed levels both stations can use
        self.tx_level = 0  # the level the partner asked this station to send at
        self.want = 0  # the level this station asks the partner to send at
        self.history = []  # recent (SNR, fading index) measurements of the partner's frames
        self.clean_run = 0  # clean frames in a row since the last change of wanted level
        self.good_run = 0  # clean frames in a row since the last failure (for leaving DEGRADED)
        self.last_result = None  # the receiver's report on the frame heard most recently
        self.outbox = []  # messages waiting to be sent, oldest first
        self.delivered = []  # messages the partner has acknowledged in full
        self.inbox = []  # complete messages received
        self.plan = []  # the frames of the message being sent
        self.plan_text = ""  # the whole text of that message
        self.part_index = 0  # which frame of the plan is next
        self.next_id = 0  # the number the next new message will get
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

    # ---- starting up ----

    def beacon(self):  # become the station that calls
        """Start beaconing for a partner."""
        self.role = "beaconer"  # this station sends beacons

    def listen(self):  # become the station that answers
        """Wait for a beacon and answer it."""
        self.role = "answerer"  # this station answers beacons

    def queue(self, text):  # hand the station a message to send
        """Add a message to the outbox."""
        self.outbox.append(text)  # oldest first

    # ---- hearing ----

    def hear(self, audio):  # run the modem receiver, combining a failed frame with its retry
        """Return the receiver's report for `audio`. A message frame that fails is kept, and added to its retry."""
        result = receive(audio)  # first try: this copy alone
        if result.ok:  # it decoded
            if result.frame_type == FRAME_TYPE_LINK:  # a message frame got through
                self.stored = None  # so any kept copy is no longer needed
            return result  # done
        if result.reason != "body check failed" or result.frame_type != FRAME_TYPE_LINK:  # nothing usable, or not a message frame
            return result  # nothing to combine
        signature = (result.size_class, result.part, result.parts)  # which frame this looks like, from its header
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

    def _report(self):  # the channel report to send back
        result = self.last_result  # the frame heard most recently
        snr_db = result.snr_db if result is not None and np.isfinite(result.snr_db) else -30.0  # its SNR, or the bottom of the scale when unknown
        fade = result.fade_index if result is not None else float("nan")  # its fading index
        offset = result.offset_hz if result is not None else 0.0  # its frequency offset
        return ChannelReport(snr_db, fade, offset, self.want)  # the measurements, and the level this station asks for

    def _note(self, result, failed):  # take in the measurements of a frame from the partner
        self.last_result = result  # keep it for the next report
        if np.isfinite(result.snr_db):  # a usable SNR reading
            self.history = (self.history + [(result.snr_db, result.fade_index)])[-HISTORY:]  # add it, keep only the recent ones
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
        self.history = [(result.snr_db, result.fade_index)] if np.isfinite(result.snr_db) else []  # forget older readings
        self.last_result = result  # keep it for the next report
        self.clean_run = self.good_run = 0  # new runs
        self.want = supported_level(self.history, self.allowed) if self.history else min(self.allowed)  # ask for what this one reading supports

    def _send(self, now, audio, kind, level, expects=None, reply_s=0.0, note=""):  # prepare one transmission
        tx = Transmission(audio, kind, level, note)  # the frame and its description
        self.pending = expects  # what reply to wait for, if any
        self.deadline = now + tx.seconds + TURNAROUND_S + reply_s + REPLY_MARGIN_S  # how long to wait for it
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

    def _start_message(self, text):  # plan a message at the current level
        self.plan = plan_at_level(text, self.tx_level)  # cut it into frames that respect the airtime limits
        self.plan_text = text  # keep the whole text in case it must be planned again
        self.part_index = 0  # start with the first frame
        self.current_id = self.next_id  # give the message its number
        self.next_id = (self.next_id + 1) % (1 << MSG_ID_BITS)  # the next message gets the next number
        self.resends = 0  # a new message starts with a clean slate

    def _send_part(self, now):  # send the next frame of the current message
        item = self.plan[self.part_index]  # the frame that is due
        if frame_seconds(pick_size_class(item["text"]), self.tx_level) > AIRTIME_POOR_CAP_S:  # the level has dropped and this frame would now run too long
            self._say(now, f"level fell to L{self.tx_level}; splitting the message again")  # explain
            self.plan = plan_at_level(self.plan_text, self.tx_level)  # plan the whole message again at the new level; it keeps its number
            self.part_index = 0  # start again from its first frame (the far end drops the parts of the old split)
            item = self.plan[0]  # the frame that is now due
        audio = build_frame(item["text"], self.tx_level, item["part"], item["parts"], link=self.link, msg_id=self.current_id, want_level=self.want)  # the message frame, carrying the level this station wants from its partner
        note = f"msg {self.current_id} part {item['part'] + 1}/{item['parts']}"  # which frame this is
        return self._send(now, audio, "message", self.tx_level, "ack", control_seconds(FRAME_TYPE_ACK, self.want), note)  # wait for its acknowledgment

    def _next(self, now):  # decide what to send when the turn is this station's
        if now - self.last_ident >= IDENT_EVERY_S:  # nearly ten minutes since the callsign went out
            return self._ident(now, final=False)  # identify first
        if self.plan and self.part_index < len(self.plan):  # a message is under way
            return self._send_part(now)  # send its next frame
        if self.outbox:  # another message is waiting
            self._start_message(self.outbox[0])  # plan it
            return self._send_part(now)  # send its first frame
        if not self.peer_empty:  # nothing to send, and the partner has not said the same
            return self._ack(now, 0, OFFER_TURN, ACK_LINK, "offer", "offer", self._longest_reply())  # offer the partner the turn
        if self.close_when_done:  # both sides are finished
            return self._ident(now, final=True)  # close the contact
        return None  # stay locked and quiet

    def _reacquire(self, now):  # the partner has gone quiet: try to find it again
        if self.state != "REACQUIRE":  # just entering this state
            self.state = "REACQUIRE"  # note it
            self.probes = 0  # no probes sent yet
            self._say(now, "no reply; reacquiring at the slowest level")  # explain
        self.tx_level = min(self.allowed)  # probe at the slowest level
        self.want = min(self.allowed)  # and ask for the reply at the slowest level
        return self._ack(now, 0, OFFER_PROBE, ACK_LINK, "probe", "probe", control_seconds(FRAME_TYPE_ACK, self.want))  # "are you still there?"

    def _release(self, now, why):  # the contact is over
        self.state = "RELEASED"  # final state
        self.pending = None  # nothing more is expected
        self._say(now, why)  # say why

    # ---- acting on what was heard ----

    def handle(self, result, now):  # react to a frame (or a failed frame) just heard
        """Return the Transmission to send in reply to `result`, or None."""
        if self.state == "RELEASED":  # the contact is over
            return None  # stay silent
        if not result.ok:  # the frame did not decode
            if result.reason == "body check failed" and result.frame_type == FRAME_TYPE_LINK and self.state in LOCKED_STATES and self.pending is None:  # a message frame arrived damaged
                self._note(result, failed=True)  # take in its measurements and ask for a slower level
                self._say(now, f"frame failed its check; asking for L{self.want} and a resend")  # explain
                return self._ack(now, 0, result.part, ACK_RESEND, "ack")  # ask for it again
            return None  # otherwise there is nothing to reply to
        self.last_activity = now  # a good frame was heard
        kind = result.frame_type  # what sort of frame it is
        if kind == FRAME_TYPE_BEACON:  # someone is calling
            return self._on_beacon(result, now)  # maybe answer
        if kind == FRAME_TYPE_ANSWER:  # someone answered a beacon
            return self._on_answer(result, now)  # maybe lock
        if self.state == "IDLE" and self.pending != "confirm":  # every other frame needs a partner
            return None  # ignore it
        if result.link != self.link:  # a frame from somebody else's lock
            return None  # ignore it
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
        self.partner = result.origin  # the calling station
        self.link = link_id(self.partner, self.call)  # link number: the beaconing station first
        self.allowed = common_levels(self.levels, result.fields["levels"])  # the levels both can use
        self._fresh_start(result)  # the first measurement of the partner
        self.tx_level = min(self.allowed)  # answer at the slowest level: nothing is known yet about the path in this direction
        self.last_ident = now  # the answer carries this station's callsign
        self._say(now, f"heard {self.partner} at {result.snr_db:+.0f} dB; answering, asking for L{self.want}")  # explain
        audio = build_answer(self.partner, self.call, self._report(), self.levels, level=self.tx_level)  # the answer frame
        return self._send(now, audio, "answer", self.tx_level, "confirm", control_seconds(FRAME_TYPE_ACK, self.want), f"wants L{self.want}")  # wait for the lock to be confirmed

    def _on_answer(self, result, now):  # an answer was heard
        if self.role != "beaconer" or self.pending != "answer" or result.dest != self.call:  # not expecting one, or it is for someone else
            return None  # stay silent
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
        self.tx_level = cap_level(fields["report"].want_level, self.allowed)  # from now on, send at the level the partner asks for
        if self.state == "IDLE":  # the answering station was waiting for this
            self.state = "LOCKED"  # the lock is confirmed
            self._say(now, f"locked with {self.partner}; told to send at L{self.tx_level}")  # explain
        status = fields["status"]  # the verdict
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
            self.delivered.append(self.outbox.pop(0))  # the whole message is delivered
            self.plan = []  # nothing under way
            self._say(now, f"message {self.current_id} delivered")  # explain
        return self._next(now)  # carry on

    def _gives_way(self, now):  # both stations are transmitting as if they held the turn: who backs off?
        """Return True when this station may carry on handling the frame it just heard; False when it should ignore it.

        The clash happens when a frame is lost and each side then waits
        for the other. The beaconing station keeps the turn and ignores
        the frame; the answering station gives way and answers it.
        """
        if self.pending not in ("ack", "offer", "probe"):  # not in the middle of an exchange of its own
            return True  # no clash
        if self.role == "beaconer":  # the beaconing station keeps the turn
            return False  # ignore the frame; its own retry will follow
        self._say(now, "both sides were sending; giving way")  # explain
        self.pending = None  # stop waiting for a reply
        self.my_turn = False  # hand the turn back
        self.misses = self.probes = 0  # the partner is plainly there
        return True  # now answer the partner's frame

    def _on_link_ack(self, result, code, now):  # a status-3 acknowledgment: lock confirmed, turn offered, probe, or a reply to one of those
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
            self.peer_empty = True  # remember the partner is empty
            self.pending = None  # any wait is over
            if self.plan or self.outbox:  # this station has traffic
                self.my_turn = True  # take the turn
                return self._next(now)  # and use it
            self.my_turn = False  # nothing here either: the partner keeps the turn
            return self._ack(now, 0, OFFER_REPLY, ACK_LINK, "reply")  # say so
        if self.pending == "probe":  # the partner answered a probe
            self._fresh_start(result)  # start measuring afresh
            self.state = "LOCKED"  # the lock is back
            self.pending = None  # the wait is over
            self.misses = self.probes = self.resends = 0  # clean slate
            self.my_turn = True  # carry on where things stopped
            self._say(now, f"reacquired; told to send at L{self.tx_level}, asking for L{self.want}")  # explain
            return self._next(now)  # resume
        if self.pending == "offer":  # the partner declined the turn: it is empty too
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
            self.peer_empty = True  # both sides are empty
            return self._next(now)  # close the contact, or stay quiet
        if self.pending == "confirm":  # the beaconing station confirmed the lock
            self.pending = None  # the wait is over
        return None  # nothing to send

    def _on_message(self, result, now):  # a message frame was heard
        if self.state == "IDLE":  # the confirmation was missed, but a frame with this link number proves the lock
            self.state = "LOCKED"  # so lock
        if self.pending in ("confirm", "offer"):  # the partner's message answers a pending confirmation or turn offer
            self.pending = None  # the wait is over
            self.misses = 0  # the partner is answering
        elif not self._gives_way(now):  # a message arrived while this station was sending its own
            return None  # the beaconing station carries on with its own exchange
        self.my_turn = False  # the partner has the turn
        self.peer_empty = False  # and has traffic
        self.tx_level = cap_level(result.want_level, self.allowed)  # every message frame says which level its sender wants back
        self._note(result, failed=False)  # take in the measurements
        status = ACK_OK  # this frame was received
        if result.msg_id in self.done_ids:  # the whole message is already here
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
        return reply  # the closing identification

    # ---- acting on the clock ----

    def poll(self, now):  # is there something to send without having heard anything?
        """Return a Transmission if the station should transmit now (a first frame, or a retry after a timeout), else None."""
        if self.state == "RELEASED":  # the contact is over
            return None  # nothing to send
        if self.pending is not None:  # waiting for a reply
            if now < self.deadline:  # and there is still time
                return None  # keep waiting
            return self._timed_out(now)  # the reply did not come
        if self.role == "beaconer" and self.state == "IDLE":  # looking for a partner
            return self._beacon(now)  # call
        if self.state in LOCKED_STATES and self.my_turn:  # locked, and it is this station's turn
            if self.peer_empty and not self.plan and not self.outbox and not self.close_when_done:  # both sides idle, lock kept open
                if now - self.last_activity < KEEPALIVE_S:  # not silent for long enough yet
                    return None  # stay quiet
                self.peer_empty = False  # time to check on the partner: offer the turn again
            return self._next(now)  # send whatever is due
        return None  # nothing to do

    def next_wake(self):  # when should poll() be called again?
        """Return the time at which this station next needs attention, or None if it is waiting to hear something."""
        if self.state == "RELEASED":  # the contact is over
            return None  # never
        if self.pending is not None:  # waiting for a reply
            return self.deadline  # until the deadline
        if self.state in LOCKED_STATES and self.my_turn and self.peer_empty and not self.close_when_done:  # idle with the lock kept open
            return self.last_activity + KEEPALIVE_S  # until the keep-alive is due
        return None  # nothing scheduled

    def _beacon(self, now):  # send a beacon
        self.beacons += 1  # count it
        self.last_ident = now  # a beacon carries the callsign
        audio = build_beacon(self.call, self.grid, self.levels, level=0)  # at the slowest level, to reach the furthest
        return self._send(now, audio, "beacon", 0, "answer", control_seconds(FRAME_TYPE_ANSWER, 0))  # then listen for an answer

    def _timed_out(self, now):  # the reply being waited for did not come
        waited_for = self.pending  # what was expected
        self.pending = None  # stop waiting
        if waited_for == "answer":  # nobody answered the beacon
            if self.beacons >= BEACON_TRIES:  # enough tries
                self._release(now, "no answer to the beacon")  # give up
                return None  # nothing to send
            return self._beacon(now)  # call again
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
