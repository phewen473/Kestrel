"""Run one Station on real audio, in real time.

The same Station that link/simulate.py drives through the channel
simulator is driven here by the clock on the wall, a sound-card input
and a sound-card output. Nothing in the link rules knows the difference.
"""

import re  # finds callsigns and levels in log lines
import time  # the real clock

import numpy as np  # finite-number checks (since 0.43)

from link.params import LONG_AFTER_CALLS, LONG_TRAFFIC_BELOW_DB, LONG_TRAFFIC_REPORT_S, TURNAROUND_S  # short calls before a long call, to a station heard only in long frames (since 0.41); pause between hearing a frame and replying
from modem.levels import level_name  # L0 to L4, or LB
from modem.powersteps import SECONDS as POWER_STEPS_S  # how long the power steps before a beacon last (since 0.38)
from modem.params import PREAMBLE_TONES as ALL_PATTERN_TONES, SIGNAL_VERSION  # the signature pattern's tone count, and the signal version this program reads (for the near-miss line, since 0.44)
from modem.params import CONTROL_BITS, FRAME_TYPE_ACK, FRAME_TYPE_ANSWER, FRAME_TYPE_LONG, LONG_LEVEL  # which frame types are control frames, the acknowledgment and answer frame types (since 0.43), and the long beacon's frame type and level number

from .burstwatch import BurstWatch  # listening for an acknowledgment burst (since 0.43)
from .busy import ChannelWatch, band_of  # listening before transmitting
from .listener import Listener, likely_kestrel  # the continuous receiver, and its test for a near miss that is likely a real Kestrel frame
from .notes import note_pieces  # a message cut into long notes (since 0.41)
from .idle import IDLE_S, KEEPALIVE_TEXT  # the contact's idle limit, and Keep-Alive's message (since 0.41)

KIND = {0: "message", 1: "addressed message", 2: "beacon", 3: "answer", 4: "acknowledgment", 5: "identification", 6: "long beacon", 7: "mail notice"}  # frame type -> plain name
LIVE_REPLY_MARGIN_S = 10.0  # extra time a live station waits for a reply: the receiver looks through its audio once a second, and sound cards add delay


def status_for(line):  # the station's state, as far as one log line shows it
    """Return (words, color) for a status display if `line` marks a change of state, else None.

    The control panel shows the latest of these above its log, so the
    operator can see at a glance whether the station is listening, calling,
    locked with a partner or finished.
    """
    found = re.search(r"long contact made with (\S+):", line)  # a long contact (since 0.41)
    if found:  # yes
        return f"LOCKED with {found.group(1)}  -  long frames (traffic as long notes)", "dark green"  # locked, the slow sure way
    found = re.search(r"calling (\S+) with long frames|no answer from (\S+) to the long call", line)  # a long call under way (since 0.41)
    if found:  # yes
        return f"CALLING {found.group(1) or found.group(2)} with long frames  -  about a minute each", "dark blue"  # say who
    found = re.search(r"long call from (\S+): answering", line)  # answering a long call (since 0.41)
    if found:  # yes
        return f"ANSWERING {found.group(1)} with a long frame", "dark blue"  # say who
    found = re.search(r"NO CONTACT: (\S+) did not answer", line)  # the long calls went unanswered (since 0.41)
    if found:  # yes
        return f"NO ANSWER from {found.group(1)} (long calls)", "black"  # nobody there
    if "long contact with" in line and "ended" in line:  # a long contact lapsed (since 0.41)
        return "LONG CONTACT ENDED", "black"  # finished
    found = re.search(r"locked with (\S+); told to send at L(\d)(?:, asking for L(\d))?", line)  # the lock was made
    if found:  # yes
        receive = f", receiving at L{found.group(3)}" if found.group(3) else ""  # the level asked of the partner, when the line gives it
        return f"LOCKED with {found.group(1)}  -  sending at L{found.group(2)}{receive}", "dark green"  # locked, and at what speeds
    if "returning to the calling frequency in one minute" in line:  # the working frequency has gone idle
        return "WORKING FREQUENCY IDLE  -  returning to the calling frequency in one minute", "dark orange"  # warn on the band too
    if "partner found on the working frequency" in line:  # the pair have met again after changing frequency
        return "LOCKED on the working frequency", "dark green"  # locked there
    if "reacquired" in line:  # the partner was found again after a gap
        return "LOCKED again after a gap", "dark green"  # locked once more
    if "reacquiring" in line:  # the partner has gone quiet
        return "PARTNER LOST  -  probing at the slowest level", "dark orange"  # trying to find it again
    if "stopped by a problem" in line:  # something went wrong
        return "STOPPED BY A PROBLEM  -  see the log", "red"  # send the operator to the log
    if "contact closed" in line:  # the contact ended properly
        return "CONTACT CLOSED", "black"  # finished with this partner
    if "lock given up" in line or "lock lost" in line:  # the partner went away and did not come back
        return "LOCK LOST  -  partner not heard", "red"  # the contact ended badly
    if "no answer to the beacon" in line:  # nobody answered any of the beacons
        return "NO ANSWER to the beacons", "black"  # nobody there
    found = re.search(r"heard (\S+) at .* dB; answering", line)  # a beacon was heard and is being answered
    if found:  # yes
        return f"ANSWERING {found.group(1)}", "dark blue"  # say who
    found = re.search(r": calling (\S+)", line)  # a directed call has begun
    if found:  # yes
        return f"CALLING {found.group(1)}", "dark blue"  # say who is being called
    found = re.search(r"no answer from (\S+)", line)  # a directed call was given up
    if found:  # yes
        return f"NO ANSWER from {found.group(1)}", "black"  # nobody there
    found = re.search(r"(\S+) is not available", line)  # the station being called replied that its operator is away
    if found:  # yes
        return f"NOT AVAILABLE  -  {found.group(1)} says its operator is away", "dark orange"  # say so
    found = re.search(r"called by (\S+); replying: not available", line)  # this station told a caller it is away
    if found:  # yes
        return f"UNAVAILABLE  -  told {found.group(1)} you are not available", "dark orange"  # say so
    found = re.search(r"frequency in use: holding the (.+) until it is clear", line)  # listening before transmitting, and someone is there
    if found:  # yes
        return f"WAITING  -  frequency in use; the {found.group(1)} goes when it is clear", "dark orange"  # say so
    if "presence only" in line:  # a beacon sent while unavailable
        return "UNAVAILABLE  -  presence beacon sent (not taking contacts)", "dark orange"  # say so
    if "sending broadcast" in line:  # a broadcast is going out
        return "BROADCASTING to all stations", "dark blue"  # say so
    if "on the air as beaconer" in line or "sending beacon" in line:  # this station is calling
        return "CALLING  -  beaconing for a partner", "dark blue"  # calling
    if "on the air as answerer" in line or "listening again" in line:  # this station is waiting for a beacon
        return "LISTENING for a beacon", "dark blue"  # listening
    if line.strip() in ("stopped", "finished") or line.rstrip().endswith("s  finished"):  # the run has ended
        return "STOPPED", "black"  # not running
    return None  # this line changes nothing


def plain_line(line):  # a log line as an operator wants to read it
    """Return `line` without its technical detail, or None if it is detail only.

    The control panel shows these by default and the full lines on request.
    The seconds-since-start stamp, the field list of a control frame and the
    frequency offset are dropped; a false frame start is left out altogether.
    """
    if "noise briefly looked like" in line:  # a false alarm
        return None  # of no interest in the plain view
    text = re.sub(r"^\s*\d+\.\ds\s+", "", line)  # drop the seconds-since-start stamp
    text = re.sub(r"^[A-Z0-9/-]+: ", "", text)  # drop this station's own callsign in front of a note
    text = re.sub(r"\s+\{.*\}\s*$", "", text)  # drop the list of fields after a control frame
    text = re.sub(r", offset [+-]?\d+\.\d Hz", "", text)  # drop the frequency offset
    text = re.sub(r"\s+(slot \d, )?wants L\d\s*$", "", text)  # drop the reply slot and wanted level after a transmission
    return text.strip() or None  # the plain words, or nothing if none are left


def describe(result):  # one line about a received frame
    """Return a readable line describing the receiver's report `result`."""
    name = KIND.get(result.frame_type, "frame")  # what kind of frame
    note = (result.fields or {}).get("note") if result.ok else None  # a long-note frame (since 0.34): header, text or receipt
    if note:  # one of those
        fields = {key: value for key, value in result.fields.items() if key != "text"}  # its fields, without the text (shown under Messages received when the note is for this station)
        copies = f" ({result.fields['copies']} copies added together)" if result.fields.get("copies", 1) > 1 else ""  # read from several copies?
        return f"heard long note {note}{copies}, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz  {fields}"  # what it was
    if not result.ok and result.level < 0:  # nothing was readable at all, not even the header
        return "noise briefly looked like the start of a frame; nothing decoded"  # a false alarm, said plainly
    if not result.ok:  # it failed its check
        return f"heard a {name} at {level_name(result.level)} that failed its check ({result.snr_db:+.0f} dB)"  # say so
    if getattr(result, "burst", False):  # an acknowledgment burst (since 0.43)
        f = result.fields or {}  # what it says
        return f"heard acknowledgment burst, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz: link {f.get('link')}, msg {f.get('msg_id')}, part {f.get('part')}, status {f.get('status')}, wants L{f['report'].want_level if f.get('report') is not None else '?'}"  # what it said
    line = f"heard {name} at {level_name(result.level)}, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz, fading {result.fade_index:.2f}"  # the measurements
    spread = getattr(result, "spread_hz", float("nan"))  # the Doppler spread read from the tones (since 0.35)
    if spread == spread:  # read (not NaN)
        line += f", spread {spread:.1f} Hz"  # shown with the rest
    if abs(result.drift_hz_s) >= 0.005:  # a drift worth mentioning (0.3 Hz a minute or more)
        line += f", drift {result.drift_hz_s * 60:+.1f} Hz/min"  # how fast the frequency moved
    if result.frame_type == FRAME_TYPE_LONG and (result.fields or {}).get("copies", 1) > 1:  # a long beacon read by adding copies together
        line = line.replace("heard long beacon", f"heard long beacon ({result.fields['copies']} copies added together)").replace(", fading nan", "")  # say so
    if result.assisted:  # a weak control frame read only with help (since 0.31R1)
        line += f" (weak: read with help: {result.assisted})"  # say how, so the operator knows it was a hard one
    if result.frame_type in CONTROL_BITS or result.frame_type == FRAME_TYPE_LONG:  # a control frame, or a long beacon
        return line.replace(", fading nan", "") + f"  {result.fields}"  # show its fields
    who = f"{result.origin} to {result.dest}" if result.frame_type == 1 else f"link {result.link}"  # addresses, or the link number
    shown = repr(result.text) if result.frame_type == 1 and result.dest == "ALL" else f"({len(result.text or '')} characters)"  # a broadcast's text; the content of a message for a particular station is not repeated here (it appears under Messages received when it is for this station)
    return line + f"  [{who}, msg {result.msg_id}, part {result.part + 1}/{result.parts}]  {shown}"  # the addressing, and the text or its length


def note_line(event):  # one line about a long note's progress (since 0.34)
    """Return a plain line for an event from live.notes.LongNotes."""
    kind, *rest = event  # what happened, and its details
    if kind == "received":  # a note arrived
        origin, dest, text = rest  # from whom, to whom, what
        return f"long note received from {origin}" + (" to ALL" if dest == "ALL" else "") + f": {text}"  # with its text (it is for this station or for everyone)
    if kind == "link":  # a long call-up's progress (since 0.41)
        return rest[1]  # its words
    if kind == "locked":  # a long contact was made (since 0.41)
        return f"long contact made with {rest[0]}: traffic goes as long notes (about a minute a frame)"  # say so (status_for shows LOCKED)
    if kind == "moved":  # a waiting message handed over as long notes (since 0.41)
        partner, _to, text, pieces = rest  # to whom, the old address, the text, and the notes it became
        return f"message for {partner} goes as {len(pieces)} long note(s): {text}"  # say so
    dest, text, tries = rest  # to whom, what, and how many tries
    words = {"delivered": f"long note to {dest} delivered (receipt received; {tries} tr{'y' if tries == 1 else 'ies'})",  # (continued)
             "resending": f"no receipt from {dest} for the long note; sending it again (try {tries}; copies are added together at the other end)",  # (continued)
             "failed": f"long note to {dest} NOT delivered: no receipt after {tries} tries",  # (continued)
             "sent": f"long note sent to {dest}"}  # what each event says
    return words.get(kind, f"long note: {event}")  # the line


def has_traffic_for(station, call):  # is a message waiting for a station? (since 0.41)
    """Return True if `station` has a waiting message for `call` or for whoever its partner is (works for the compiled station too)."""
    return any(to is None or to == call for to in (station.outbox_to or []))  # an address that fits


def short_calls_failing(station, notes, now):  # stop short calls early? (since 0.41)
    """Return the callsign being called when the short calls should give way to a long call now, else None.

    That is when this station is making a directed call, has sent at least
    LONG_AFTER_CALLS of them (L2, then L0), the wait for the last one's reply
    is over, and the called station has lately been heard only in long frames
    (on a fading path the short levels need about -8 dB; the long frame reads
    down to about -22 dB). A waiting broadcast or long beacon keeps the
    short calls going (stopping them would drop those frames too).
    """
    if station.role != "caller" or station.pending != "confirm" or (station.calls or 0) < LONG_AFTER_CALLS:  # not calling, or not yet tried enough
        return None  # carry on
    if now <= (station.deadline or 0.0):  # still waiting for a reply to the last call
        return None  # carry on
    target = station.target  # the station being called
    if not target or not notes.heard_recently(target, now) or station.broadcasts or station.long_waiting is not None:  # not heard in long frames lately, or frames that a stop would drop
        return None  # the short calls run their course
    return target  # give way to a long call


def their_report(station, result, own_call):  # the partner's report of this station, if `result` carries one (since 0.43)
    """Return (SNR, level asked for, age in seconds) from an acknowledgment frame of this station's contact or an answer to this station; None for anything else (a burst carries no SNR). The age (since 0.44) is how long before the frame was sent the partner made its measurement, 0 when the report does not say."""
    fields = getattr(result, "fields", None) or {}  # a control frame's fields
    report = fields.get("report") if result.ok and not getattr(result, "burst", False) else None  # its full report
    if report is None or not np.isfinite(report.snr_db):  # none, or no reading
        return None  # nothing
    mine = (result.frame_type == FRAME_TYPE_ACK and station.partner and fields.get("link") == station.link) or (result.frame_type == FRAME_TYPE_ANSWER and fields.get("dest") == own_call)  # about this station
    age = float(getattr(report, "age_s", float("nan")))  # how old the measurement was when sent (since 0.44)
    return (float(report.snr_db), int(report.want_level), age if np.isfinite(age) else 0.0) if mine else None  # the reading, the level asked for, and its age


def s_meter_text(noise_db):  # an S-meter reading in words (since 0.44)
    """Return an S-meter reading given in dB relative to S9 as S-units ("S7", "S9", "S9+10"), or "" when it is NaN (not measured). One S-unit is 6 dB."""
    if noise_db is None or not np.isfinite(noise_db):  # not measured
        return ""  # nothing to say
    if noise_db >= 0.5:  # above S9
        return f"S9+{noise_db:.0f}"  # S9 and the dB over it
    return f"S{max(0, int(round(9 + noise_db / 6.0)))}"  # S0 to S9


def report_extras(report):  # the age and noise a channel report carries, in words (since 0.44)
    """Return ", 2 min old, their noise S7" style words for a channel report's age and the reporter's noise reading ("" for either that is not said)."""
    words = ""  # nothing yet
    age = getattr(report, "age_s", float("nan"))  # how old the measurement was
    if age == age and age >= 60:  # said, and a minute or more
        words += f", {age / 60:.0f}+ min old"  # at least that old (the code gives the start of its step)
    noise = s_meter_text(getattr(report, "noise_db", float("nan")))  # the reporter's noise
    if noise:  # measured
        words += f", their noise {noise}"  # said
    return words  # the words


def traffic_too_weak(station, notes, report, now):  # short frames cannot carry the traffic: use long notes? (since 0.43)
    """Return the partner's callsign when the waiting messages for it should go as long notes instead: this station is in a short-frame contact with traffic for the partner, and the partner's latest full report (`report`: time, SNR, level asked for), no older than LONG_TRAFFIC_REPORT_S, is at or below LONG_TRAFFIC_BELOW_DB at L0. Otherwise None."""
    if notes is None or report is None or station.state not in LOCKED_STATES or not station.partner:  # no long notes, no report, or no contact
        return None  # carry on
    when, snr, want = report  # the report
    if now - when > LONG_TRAFFIC_REPORT_S or snr > LONG_TRAFFIC_BELOW_DB or want != 0:  # stale, or strong enough
        return None  # carry on
    return station.partner if has_traffic_for(station, station.partner) else None  # only with messages waiting for it


def hand_to_notes(station, notes, partner, now):  # a long contact was made: send waiting messages as long notes (since 0.41)
    """Take `station`'s waiting messages for `partner` (or for whoever its partner is) out of its outbox and queue them as long notes; return ("moved", ...) events."""
    events = []  # what was handed over
    for text, to in list(zip(station.outbox or [], station.outbox_to or [])):  # each waiting message, oldest first
        if to not in (None, partner):  # for another station
            continue  # stays where it is
        pieces = note_pieces(text)  # the long notes it becomes (64 characters each, capitals)
        if not pieces or not station.unqueue(text, to):  # nothing a note can carry, or already under way
            continue  # left alone
        for piece in pieces:  # each piece
            notes.queue(partner, piece, now)  # a long note to the partner
        events.append(("moved", partner, to, text, pieces))  # for the operator and the panel's list
    return events  # what happened


LOCKED_STATES = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states of a contact in progress


NEAR_MERGE_S = 60.0  # near misses of the same signal within this many seconds are shown as one line (since 0.31R2)
NEAR_MERGE_HZ = 5.0  # "the same signal": the same level, within this many hertz


def strong_unreadable(result):  # a near miss whose whole signature pattern stood out (since 0.44)
    """Return True when every one of a near miss's 12 pattern tones stood out: the signal is strong, so a header it cannot read more likely means a different Kestrel signal version than a weak or faded one."""
    return getattr(result, "pattern_tones", -1) >= ALL_PATTERN_TONES  # the whole pattern


def near_line(result):  # one line about a near miss
    """Return a line saying a Kestrel signature was heard but could not be read; when its whole pattern stood out (since 0.44), say it may be from a different signal version, since a signal that strong is seldom too weak to read."""
    tones = getattr(result, "pattern_tones", -1)  # how much of its pattern stood out, if counted
    shown = f", {tones} of 12 pattern tones" if tones >= 0 else ""  # said when known
    head = f"possible Kestrel signature heard (looks like {level_name(result.seen_level)}, about {1500.0 + result.offset_hz:.0f} Hz{shown})"  # what was heard
    if strong_unreadable(result):  # strong, yet unreadable (since 0.44: older decoders said "too weak" of strong frames from another signal version)
        return head + f" but not readable although strong (strength {result.sync_quality:.1f}): possibly a station on a different Kestrel signal version (this one reads signal version {SIGNAL_VERSION})"  # the likelier cause
    return head + f" but too weak or faded to read (strength {result.sync_quality:.1f})"  # the usual case


class NearFilter:  # which near misses the operator is shown (since 0.31R2)
    """Pass on only near misses likely to be a real Kestrel frame, and only one line per signal per minute.

    Every near miss still goes to the signal log; this decides only what
    the Activity log and the logbook show. A near miss is shown when most
    of its signature pattern stood out (listener.likely_kestrel); another
    one at the same level within NEAR_MERGE_HZ of a signal shown in the last
    NEAR_MERGE_S seconds is the same signal again, and is not shown.
    """

    def __init__(self, clock=time.monotonic):  # `clock` gives the time in seconds (a stand-in in tests)
        self.clock = clock  # the clock
        self.shown = []  # (level, offset in hertz, when) of the signals shown lately

    def show(self, result):  # should this near miss be shown?
        """Return True if `result` should be shown to the operator, and remember it."""
        if not likely_kestrel(result):  # most of its pattern did not stand out: probably another mode's signal, or noise
            return False  # the signal log has it; nobody else needs to see it
        now = self.clock()  # the time now
        self.shown = [item for item in self.shown if now - item[2] < NEAR_MERGE_S]  # forget signals shown more than a minute ago
        if any(level == result.seen_level and abs(offset - result.offset_hz) <= NEAR_MERGE_HZ for level, offset, _ in self.shown):  # the same signal, shown lately
            return False  # once a minute is enough
        self.shown.append((result.seen_level, result.offset_hz, now))  # remembered
        return True  # show it  # likely level, audio frequency and how strongly the pattern stood out


def call_request(target, after_contact, say=print):  # a directed call the operator asked for, to be made in the station's own thread
    """Return a request for run_station's on_tick: call `target` once the station is free.

    The request returns True when it is finished with (the call made, or
    dropped) and False while it is still waiting. `after_contact` is True
    when the operator asked during a contact, meaning "call once this
    contact is over". A call that is waiting is dropped if the station
    locks with `target` some other way, or if a contact starts that was
    not under way when the call was asked for: the operator can ask again
    afterwards, and an old request is never carried out by surprise.
    """
    def request(station):  # looked at once every loop
        if station.state in LOCKED_STATES and station.partner == target:  # already in a contact with the station to be called
            say(f"call to {target} dropped: already in contact with {target}")  # say so
            return True  # finished with
        if station.state in LOCKED_STATES and not after_contact:  # a contact began while the call was waiting
            say(f"call to {target} dropped: a contact with {station.partner} started first; press Call station again to call {target}")  # say so
            return True  # finished with
        if station.state != "IDLE" or station.pending is not None or station.role != "answerer":  # busy: a beacon round, an answer, or the contact the operator wants to finish first
            return False  # look again shortly
        station.call_once(target)  # call, then go back to listening
        return True  # done

    request.kind = "call"  # so a change of mode can find and cancel waiting calls
    request.target = target  # and say whom they were for
    return request  # ready to hand to the station thread


def feed_from(listener, source, watch=None, bursts=None):  # read the source and give the audio to the listener
    """Read new audio from `source` and feed it to `listener`, with its sample numbers when the source counts them (recorder.TimedSource); return the frames completed. `watch` (a busy.ChannelWatch) and `bursts` (a burstwatch.BurstWatch, since 0.43) hear the same audio."""
    chunk = source.read()  # the new audio
    if watch is not None and len(chunk):  # someone is listening for other signals
        watch.feed(chunk)  # let it hear this too
    if bursts is not None:  # an acknowledgment burst may be awaited
        bursts.feed(chunk)  # it hears this too
    count = getattr(source, "samples", None)  # the timeline's count, if the source keeps one
    return listener.feed(chunk, at=None if not isinstance(count, int) else count - len(chunk))  # numbered as the timeline numbers them


def attach_signal_log(listener, signal_log, dial_khz=None):  # connect a listener to a signal log
    """Have `listener` report its searches to `signal_log`; return a function to call with each near miss (it logs the miss with its audio)."""
    if signal_log is None:  # no log at all
        return lambda result: None  # nothing to do
    listener.on_search = lambda result, trace: signal_log.search(result, trace) if signal_log.on else None  # every search, while the log is on (it may be turned on or off during a run)
    return lambda result: signal_log.near(result, listener.near_audio, listener.near_audio_sample, dial_khz() if dial_khz else None) if signal_log.on else None  # every near miss, with its audio, likewise


def log_tick(signal_log, source):  # the signal log's regular lines
    """Give `signal_log` the input level and dropout count, for its once-a-minute line."""
    if signal_log is None or not signal_log.on:  # no log
        return  # nothing to do
    level = source.level() if hasattr(source, "level") else None  # the input level, if the source can say
    signal_log.tick(level=level, lost=getattr(source, "lost", None))  # the log decides whether a line is due


def run_station(station, source, sink, ptt, say=print, limit_s=None, stay_on=False, should_stop=None, retune=None, on_heard=None, on_frame=None, on_transmit=None, on_tick=None, on_near=None, signal_log=None, dial_khz=None, listen_first=True, expect=None, notes=None, on_note=None, on_progress=None, idle=None, on_idle=None):  # the live loop (idle and on_idle since 0.41: the contact's idle timeout, Keep-Alive and the 10-second warning; see live/idle.py)
    """Run `station` until its contact ends (or for ever with `stay_on`), or until `limit_s` seconds pass.

    `source` has read() and flush() (see audio.AudioIn), `sink` has
    play(audio) (see audio.AudioOut), `ptt` keys the transmitter
    (see ptt.Ptt), and `say` is called with each line of the running log.
    `should_stop`, if given, is called ten times a second; the loop ends
    when it returns True (a Stop button, for example). `retune`, if
    given, is called with an offset in hertz from the calling frequency
    whenever the link rules move to a working frequency or back; without
    it the station declines such moves. `on_heard`, if given, is called with
    the receiver's report on every frame that decodes, whoever sent it.
    `on_frame`, if given, is called with every report, decoded or not (for
    a detailed log). `on_transmit`, if given, is called with the
    Transmission and True just after the transmitter is keyed, and with
    the Transmission and False just after it is released. `on_tick`, if
    given, is called with the station and the station's clock once every
    loop, in this thread: the safe place for another part of the program
    to ask the station to do something (beacon, call, broadcast).
    `on_near`, if given, is called with the receiver's report whenever a
    Kestrel signature is heard whose header cannot be read (a near miss);
    such signals are always mentioned in the running log.
    `signal_log`, if given (a signallog.SignalLog), gets everything: every
    search's candidates, every frame and near miss, every transmission,
    frequency change and line from the link rules. `dial_khz`, if given,
    is called for the radio's dial frequency to put in those lines.
    With `listen_first` (the default) the station holds back anything it
    starts unasked (a beacon, a long beacon, a directed call, a broadcast)
    while another signal is heard where it would transmit (busy.py; spec
    Section 6.14). Replies inside an exchange are never held.
    `expect`, if given, is called for more callsigns the station expects to
    hear (saved contacts, stations heard lately); with the station's own,
    the one it calls and its partner, they help read weak control frames.
    `notes`, if given (a live.notes.LongNotes), sends this station's long
    notes and receipts when no contact is under way, and is given every
    long-note frame heard (since 0.34); `on_note`, if given, is called with
    each of its events (received, delivered, resending, failed, sent).
    `on_progress`, if given, is called after every search with the
    listener's progress() report: the frames arriving and those just
    finished, for the panel's frame strip (since 0.37).
    """
    station.can_move = retune is not None  # the station may agree to change frequency only if the radio can be retuned
    tuned = 0  # the offset from the calling frequency the radio is on now
    station.reply_margin = LIVE_REPLY_MARGIN_S  # allow for real-world delays when waiting for replies
    margin_set = [LIVE_REPLY_MARGIN_S]  # the margin last given to the station (in a list so the loop can change it; power steps add theirs, since 0.38)
    listener = Listener()  # the continuous receiver
    bursts = BurstWatch()  # listens for an acknowledgment burst after a frame that awaits one (since 0.43)
    listener.on_progress = on_progress  # the frame strip, if the caller shows one (since 0.37)
    listener.expect = lambda: (station.call, [station.target, station.partner] + list(expect() if expect is not None else ()))  # this station's callsign, and those it expects: the one it calls, its partner, and any the caller adds (since 0.31R1)
    started = time.monotonic()  # the moment the clock starts
    watch = ChannelWatch() if listen_first else None  # listens for other signals on the frequency
    if watch is not None:  # listening before transmitting
        station.busy = lambda level: watch.busy(*band_of(level))  # the station asks before it starts anything unasked
    log_near = attach_signal_log(listener, signal_log, dial_khz)  # searches and near misses go to the signal log, if there is one
    class _Logging:  # whether the signal log is being written, asked afresh each time (it may be turned on or off during a run)
        def __bool__(self):  # true while the log is on
            return signal_log is not None and signal_log.on  # there is one, and it is on
    logging = _Logging()  # used as a yes-or-no

    def dial():  # the dial frequency, for the signal log
        return dial_khz() if dial_khz is not None else None  # if the caller can say

    shown = NearFilter()  # which near misses the operator sees (since 0.31R2)

    def near(result):  # a signature too weak or faded to read
        log_near(result)  # the signal log keeps every one
        if not shown.show(result):  # not likely Kestrel, or the same signal again within the minute
            return  # the operator is not told
        stamp(near_line(result))  # tell the operator: it shows a Kestrel signal is getting through
        if on_near is not None:  # someone keeps a record
            on_near(result)  # pass it on

    listener.on_near = near  # the listener reports near misses here
    listener.on_doubt = lambda result: stamp(f"long beacon from {(result.fields or {}).get('origin', '?')} at {result.offset_hz:+.1f} Hz {result.reason} (most likely noise)")  # a long beacon read from added copies but not believed (since 0.44)
    told = 0  # how many lines of the station's own log have been passed on
    last_sent = [-1e9]  # when this station's last transmission ended (in a list so the inner function can change it)
    lost = 0  # how many times the sound card has reported losing audio, as of the last look
    gave_up = [None]  # a callsign the short calls just failed to reach, for a long call to follow (in a list so the loop can change it; since 0.41)
    inbox_seen = [0]  # how many received messages the idle watch has looked at (since 0.41)
    reported = [None]  # the partner's latest full report of this station: (time, SNR, level asked for) (since 0.43)

    def now():  # seconds since the start
        return time.monotonic() - started  # the station's clock

    def stamp(text):  # pass a line to the operator
        say(f"{now():7.1f}s  {text}")  # with the time

    def transmit(tx):  # put one frame on the air
        waited = time.monotonic()  # when the wait for a reply slot began
        while time.monotonic() - waited < tx.delay:  # an answer waits for its slot
            source.read()  # keep the input from piling up
            time.sleep(0.05)  # a short nap
        while now() - last_sent[0] < TURNAROUND_S:  # two of this station's own frames in a row need a clear gap between them
            source.read()  # keep the input from piling up
            time.sleep(0.05)  # a short nap
        stamp(f"sending {tx.kind} at {level_name(tx.level)}, {tx.seconds:.1f} s  {tx.note}")  # tell the operator
        ptt.key()  # transmitter on
        try:  # whatever happens...
            if logging:  # a signal log is kept
                signal_log.tx(tx, True, dial_khz=dial(), gain=getattr(sink, "gain", None))  # the transmitter is on
            if on_transmit is not None:  # someone wants to know the transmitter is on
                on_transmit(tx, True)  # tell them
            sink.play(tx.on_air() if hasattr(tx, "on_air") else tx.audio)  # send the audio (a beacon's power steps first, since 0.38)
        finally:  # ...the transmitter must come off
            ptt.unkey()  # transmitter off
            if logging:  # a signal log is kept
                signal_log.tx(tx, False, dial_khz=dial(), gain=getattr(sink, "gain", None), peak_dbfs=getattr(sink, "last_peak_db", None))  # and off again, with the peak level it reached
            if on_transmit is not None:  # someone wants to know it is off again
                on_transmit(tx, False)  # tell them
        last_sent[0] = now()  # remember when this transmission ended
        gaps = getattr(source, "gaps", 0)  # how often the sample count has had to be made good so far (since 0.40R1)
        source.flush()  # throw away whatever was received meanwhile (it was this station's own signal); a counting source also brings its count back in step with the clock
        if isinstance(gaps, int) and getattr(source, "gaps", 0) > gaps and logging:  # the sound card delivered less audio than time passed during this transmission
            signal_log.note("input timeline made good after transmitting", seconds=round(source.last_gap_s, 3), total_s=round(source.gap_s, 3))  # kept in the signal log, to show how much each transmission loses
        listener.clear()  # and forget it
        bursts.arm(tx)  # an acknowledgment burst may follow: keep what comes next (since 0.43)
        if watch is not None:  # listening before transmitting
            watch.clear()  # what was heard just before this transmission is not "now" any more

    stamp(f"{station.call} on the air as {station.role or 'broadcaster'}")  # opening line (a station with no role is only sending a broadcast)
    while (limit_s is None or now() < limit_s) and not (should_stop and should_stop()):  # until the time limit, or until told to stop
        for heard in feed_from(listener, source, watch, bursts):  # every frame that has completed
            result = heard.result if heard.result.ok and heard.result.frame_type == FRAME_TYPE_LONG else station.hear(heard.audio, heard.result, heard.start)  # the continuous receiver's report, taken as read when it decoded (since 0.43; before, the clip was decoded again from scratch, without the help the continuous receiver gives weak control frames); a failed message frame is combined with its retry; a long beacon is already decoded, perhaps from several copies added together
            if getattr(heard.result, "power_steps", None) is not None and getattr(result, "power_steps", None) is None:  # the listener read power steps before this beacon (since 0.38)
                result.power_steps = heard.result.power_steps  # kept with the station's report
            if logging:  # a signal log is kept
                signal_log.rx(heard, station_result=result, dial_khz=dial())  # both decodes, and the clip if clips are kept
            stamp(describe(result))  # tell the operator
            if getattr(result, "power_steps", None) is not None:  # power steps were read before this beacon (since 0.38)
                stamp(f"{(result.fields or {}).get('origin', '')} {result.power_steps.describe()}".strip())  # tell the operator too
            if on_frame is not None:  # someone keeps a detailed log
                on_frame(result)  # pass on every report, decoded or not
            if on_heard is not None and result.ok:  # somebody was heard clearly
                on_heard(result)  # let the caller note who
            if notes is not None and result.ok and (result.fields or {}).get("note"):  # a long-note frame (since 0.34)
                notes.heard(result.fields, now())  # put it with the rest of its note, or take the receipt (or, since 0.41, a long call-up)
            elif notes is not None and result.ok and result.frame_type == FRAME_TYPE_LONG:  # a long beacon (since 0.41)
                notes.saw((result.fields or {}).get("origin", ""), now())  # its sender is reachable with long frames
            got = their_report(station, result, station.call)  # the partner's report of this station, if the frame carries one (since 0.43)
            if got is not None:  # it does
                reported[0] = (now() - got[2], got[0], got[1])  # the latest, dated when the partner made the measurement rather than when the frame arrived (since 0.44)
            if result.ok and bursts.waiting and (getattr(result, "link", -1) == station.link or (result.origin and result.origin == station.partner)):  # the partner's frame was read: the burst wait is over (since 0.43)
                bursts.disarm()  # a burst found later would be stale
            reply = station.handle(result, now())  # what the link rules say to do
            if reply is not None:  # something to send
                time.sleep(TURNAROUND_S)  # give the other station time to switch to receive
                transmit(reply)  # send it
        found = bursts.check()  # the acknowledgment burst awaited, once enough audio is in (since 0.43)
        if found is not None:  # recognized
            stamp(describe(found))  # tell the operator
            if logging:  # a signal log is kept
                signal_log.link(describe(found))  # there too
            if on_frame is not None:  # someone keeps a detailed log
                on_frame(found)  # it is a report like any other
            reply = station.handle(found, now())  # an acknowledgment, as far as the link rules go
            if reply is not None:  # something to send
                time.sleep(TURNAROUND_S)  # give the other station time to switch to receive
                transmit(reply)  # send it
        if getattr(source, "lost", 0) > lost:  # the sound card has dropped audio since the last look
            lost = source.lost  # remember the new count
            stamp(f"warning: the sound card lost some received audio ({lost} time(s) so far); a frame may fail and be asked for again")  # tell the operator
            if logging:  # a signal log is kept
                signal_log.note("sound card lost received audio", lost=lost)  # keep it there too
        log_tick(signal_log, source)  # the signal log's once-a-minute lines
        if on_tick is not None:  # another part of the program may have asked for something
            on_tick(station, now())  # let it act, here in the station's own thread
        margin = LIVE_REPLY_MARGIN_S + (POWER_STEPS_S if getattr(station, "power_steps", False) else 0.0)  # replies to a beacon sent after its power steps come that much later than the link rules time them (since 0.38)
        if margin != margin_set[0]:  # changed (the operator may turn the steps on or off while running)
            station.reply_margin = margin_set[0] = margin  # allowed for
        if idle is not None:  # the contact's idle timeout is watched here (since 0.41)
            inbox = station.inbox or []  # complete messages received
            if len(inbox) < inbox_seen[0]:  # the list was emptied (a new contact)
                inbox_seen[0] = 0  # start again
            for text in inbox[inbox_seen[0]:]:  # the new ones
                if str(text).strip().upper() == KEEPALIVE_TEXT:  # the partner's Keep-Alive
                    idle.keepalive_seen(now())  # it does not earn another extension here
            inbox_seen[0] = len(inbox)  # looked at
            action = idle.check(station, now())  # extend, warn, end, or nothing
            if action is not None and action[0] == "extend":  # Keep-Alive: one short message restarts both stations' timers
                station.queue(KEEPALIVE_TEXT, action[1])  # to the partner
                stamp(f"Keep-Alive: {KEEPALIVE_TEXT} sent to {action[1]} (the working channel is held about 3 more minutes)")  # tell the operator
            elif action is not None and action[0] == "warn":  # ten seconds to go
                stamp(f"contact with {action[1]} ends in {action[2]:.0f} s for lack of traffic: Keep going or Disconnect")  # tell the operator
                if on_idle is not None:  # the panel asks the operator
                    on_idle(action[1], action[2])  # with Keep going and Disconnect
            elif action is not None and action[0] == "end":  # the calling frequency's limit reached
                stamp(f"no messages for {IDLE_S / 60:.0f} minutes; ending the contact with {action[1]}")  # tell the operator
                station.end()  # close it properly, with identification
        tx = station.poll(now())  # anything to send without having heard something?
        if tx is not None:  # yes
            transmit(tx)  # send it
        weak = traffic_too_weak(station, notes, reported[0], now())  # short frames are not reaching the partner (since 0.43)
        if weak:  # its report says so
            moved = hand_to_notes(station, notes, weak, now())  # the waiting messages become long notes
            reported[0] = None  # acted on
            if moved:  # some were moved
                stamp(f"{weak} hears this station at {LONG_TRAFFIC_BELOW_DB:.0f} dB or less: waiting messages go as long notes; closing the short contact")  # tell the operator
                notes.events.extend(moved)  # shown like any other hand-over
                station.end()  # close the contact once the frame under way, if any, is done
        if notes is not None:  # long notes (since 0.34)
            notes.available = bool(getattr(station, "available", True))  # a long call is answered only while the operator takes contacts (since 0.41)
            target = short_calls_failing(station, notes, now())  # a station the short calls are not reaching, but heard lately in long frames (since 0.41)
            if target:  # yes: stop the short calls early...
                station.cancel(now())  # the station goes back to listening (its log says the calls were stopped)
                stamp(f"short calls to {target} stopped after {LONG_AFTER_CALLS}: {target} is heard only in long frames")  # why
                gave_up[0] = target  # ...and call it with long frames below
            if gave_up[0]:  # short calls to a station went unanswered (since 0.41)
                target, gave_up[0] = gave_up[0], None  # taken
                if notes.calling is None and notes.heard_recently(target, now()):  # no long call under way, and that station has been heard in long frames lately
                    notes.long_call(target, now(), traffic=has_traffic_for(station, target))  # call it with long frames
            notes.tick(now())  # resend notes whose receipt has not come
            free = station.state == "IDLE" and getattr(station, "pending", None) is None  # no contact under way and nothing awaited
            due = notes.due(now()) if free else None  # "receipt", "note" or None
            if due == "note" and watch is not None and watch.busy(*band_of(LONG_LEVEL)):  # a note waits while the frequency is in use (a receipt, being a reply, does not)
                due = None  # not yet
            if due is not None:  # something to send, and room to send it
                frames, what = notes.next_frames(now())  # the frames
                for number, frame in enumerate(frames):  # header, then each text frame (or one receipt)
                    notes.on_air(what, number, len(frames))  # which frame is going, for the progress shown
                    transmit(frame)  # send it
                notes.sent(what, now())  # wait for the receipt, or report a note to ALL sent
            for event in [e for e in notes.events if e[0] == "locked"]:  # a long contact was made (since 0.41)
                notes.events.extend(hand_to_notes(station, notes, event[1], now()))  # this station's waiting messages for the partner go as long notes
            for event in notes.events:  # what happened
                stamp(note_line(event))  # tell the operator
                if on_note is not None:  # someone keeps a record
                    on_note(event)  # pass it on
            notes.events.clear()  # told
        for line in station.log[told:]:  # the station's own notes since last time
            found = re.search(r"no answer from (\S+)", line)  # short calls given up (since 0.41)
            if found:  # yes
                gave_up[0] = found.group(1)  # a long call may follow, next time round
            say("          " + line)  # pass them on
            if logging:  # a signal log is kept
                signal_log.link(line)  # keep them there too
        told = len(station.log)  # remember how far we got
        wanted = station.tuning(now())  # where the link rules want the radio now
        if retune is not None and wanted != tuned:  # a move to a working frequency, or back
            retune(wanted)  # change the radio's frequency
            tuned = wanted  # remember where it is
            source.flush()  # what was received on the old frequency no longer matters
            listener.clear()  # so forget it
            bursts.disarm()  # and no burst is awaited there
            if watch is not None:  # listening before transmitting
                watch.reset()  # a new frequency: its noise and its users are not known yet
            stamp(f"radio moved to the working frequency ({wanted / 1000.0:+.1f} kHz)" if wanted else "radio back on the calling frequency")  # tell the operator
            if logging:  # a signal log is kept
                signal_log.tune(dial(), why=f"working frequency {wanted / 1000.0:+.1f} kHz" if wanted else "back to the calling frequency")  # the move
        if station.state == "RELEASED":  # the contact is over
            if not stay_on:  # one contact was all that was wanted
                break  # stop
            station.new_contact()  # otherwise get ready for the next
            stamp("listening again")  # tell the operator
        time.sleep(0.1)  # a tenth of a second between looks
    stamp("finished")  # closing line
