"""Run one Station on real audio, in real time.

The same Station that link/simulate.py drives through the channel
simulator is driven here by the clock on the wall, a sound-card input
and a sound-card output. Nothing in the link rules knows the difference.
"""

import re  # finds callsigns and levels in log lines
import time  # the real clock

from link.params import TURNAROUND_S  # pause between hearing a frame and replying
from modem.levels import level_name  # L0 to L4, or LB
from modem.params import CONTROL_BITS, FRAME_TYPE_LONG  # which frame types are control frames, and the long beacon's

from .busy import ChannelWatch, band_of  # listening before transmitting
from .listener import Listener  # the continuous receiver

KIND = {0: "message", 1: "addressed message", 2: "beacon", 3: "answer", 4: "acknowledgment", 5: "identification", 6: "long beacon", 7: "mail notice"}  # frame type -> plain name
LIVE_REPLY_MARGIN_S = 10.0  # extra time a live station waits for a reply: the receiver looks through its audio once a second, and sound cards add delay


def status_for(line):  # the station's state, as far as one log line shows it
    """Return (words, colour) for a status display if `line` marks a change of state, else None.

    The control panel shows the latest of these above its log, so the
    operator can see at a glance whether the station is listening, calling,
    locked with a partner or finished.
    """
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
    if not result.ok and result.level < 0:  # nothing was readable at all, not even the header
        return "noise briefly looked like the start of a frame; nothing decoded"  # a false alarm, said plainly
    if not result.ok:  # it failed its check
        return f"heard a {name} at {level_name(result.level)} that failed its check ({result.snr_db:+.0f} dB)"  # say so
    line = f"heard {name} at {level_name(result.level)}, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz, fading {result.fade_index:.2f}"  # the measurements
    if result.frame_type == FRAME_TYPE_LONG and (result.fields or {}).get("copies", 1) > 1:  # a long beacon read by adding copies together
        line = line.replace("heard long beacon", f"heard long beacon ({result.fields['copies']} copies added together)").replace(", fading nan", "")  # say so
    if result.frame_type in CONTROL_BITS or result.frame_type == FRAME_TYPE_LONG:  # a control frame, or a long beacon
        return line.replace(", fading nan", "") + f"  {result.fields}"  # show its fields
    who = f"{result.origin} to {result.dest}" if result.frame_type == 1 else f"link {result.link}"  # addresses, or the link number
    shown = repr(result.text) if result.frame_type == 1 and result.dest == "ALL" else f"({len(result.text or '')} characters)"  # a broadcast's text; the content of a message for a particular station is not repeated here (it appears under Messages received when it is for this station)
    return line + f"  [{who}, msg {result.msg_id}, part {result.part + 1}/{result.parts}]  {shown}"  # the addressing, and the text or its length


LOCKED_STATES = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states of a contact in progress


def near_line(result):  # one line about a near miss
    """Return a line saying a Kestrel signature was heard but could not be read."""
    return f"possible Kestrel signature heard (looks like {level_name(result.seen_level)}, about {1500.0 + result.offset_hz:.0f} Hz) but too weak or faded to read (strength {result.sync_quality:.1f})"  # likely level, audio frequency and how strongly the pattern stood out


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


def feed_from(listener, source, watch=None):  # read the source and give the audio to the listener
    """Read new audio from `source` and feed it to `listener`, with its sample numbers when the source counts them (recorder.TimedSource); return the frames completed. `watch` (a busy.ChannelWatch) hears the same audio."""
    chunk = source.read()  # the new audio
    if watch is not None and len(chunk):  # someone is listening for other signals
        watch.feed(chunk)  # let it hear this too
    count = getattr(source, "samples", None)  # the timeline's count, if the source keeps one
    return listener.feed(chunk, at=None if not isinstance(count, int) else count - len(chunk))  # numbered as the timeline numbers them


def attach_signal_log(listener, signal_log, dial_khz=None):  # connect a listener to a signal log
    """Have `listener` report its searches to `signal_log`; return a function to call with each near miss (it logs the miss with its audio)."""
    if signal_log is None or not signal_log.on:  # no log
        return lambda result: None  # nothing to do
    listener.on_search = signal_log.search  # every search
    return lambda result: signal_log.near(result, listener.near_audio, listener.near_audio_sample, dial_khz() if dial_khz else None)  # every near miss, with its audio


def log_tick(signal_log, source):  # the signal log's regular lines
    """Give `signal_log` the input level and dropout count, for its once-a-minute line."""
    if signal_log is None or not signal_log.on:  # no log
        return  # nothing to do
    level = source.level() if hasattr(source, "level") else None  # the input level, if the source can say
    signal_log.tick(level=level, lost=getattr(source, "lost", None))  # the log decides whether a line is due


def run_station(station, source, sink, ptt, say=print, limit_s=None, stay_on=False, should_stop=None, retune=None, on_heard=None, on_frame=None, on_transmit=None, on_tick=None, on_near=None, signal_log=None, dial_khz=None, listen_first=True):  # the live loop
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
    """
    station.can_move = retune is not None  # the station may agree to change frequency only if the radio can be retuned
    tuned = 0  # the offset from the calling frequency the radio is on now
    station.reply_margin = LIVE_REPLY_MARGIN_S  # allow for real-world delays when waiting for replies
    listener = Listener()  # the continuous receiver
    started = time.monotonic()  # the moment the clock starts
    watch = ChannelWatch() if listen_first else None  # listens for other signals on the frequency
    if watch is not None:  # listening before transmitting
        station.busy = lambda level: watch.busy(*band_of(level))  # the station asks before it starts anything unasked
    log_near = attach_signal_log(listener, signal_log, dial_khz)  # searches and near misses go to the signal log, if there is one
    logging = signal_log is not None and signal_log.on  # whether there is a signal log to write

    def dial():  # the dial frequency, for the signal log
        return dial_khz() if dial_khz is not None else None  # if the caller can say

    def near(result):  # a Kestrel signature too weak or faded to read
        stamp(near_line(result))  # always tell the operator: it shows a signal is getting through
        log_near(result)  # and the signal log
        if on_near is not None:  # someone keeps a record
            on_near(result)  # pass it on

    listener.on_near = near  # the listener reports near misses here
    told = 0  # how many lines of the station's own log have been passed on
    last_sent = [-1e9]  # when this station's last transmission ended (in a list so the inner function can change it)
    lost = 0  # how many times the sound card has reported losing audio, as of the last look

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
            sink.play(tx.audio)  # send the audio
        finally:  # ...the transmitter must come off
            ptt.unkey()  # transmitter off
            if logging:  # a signal log is kept
                signal_log.tx(tx, False, dial_khz=dial(), gain=getattr(sink, "gain", None), peak_dbfs=getattr(sink, "last_peak_db", None))  # and off again, with the peak level it reached
            if on_transmit is not None:  # someone wants to know it is off again
                on_transmit(tx, False)  # tell them
        last_sent[0] = now()  # remember when this transmission ended
        source.flush()  # throw away whatever was received meanwhile (it was this station's own signal)
        listener.clear()  # and forget it
        if watch is not None:  # listening before transmitting
            watch.clear()  # what was heard just before this transmission is not "now" any more

    stamp(f"{station.call} on the air as {station.role or 'broadcaster'}")  # opening line (a station with no role is only sending a broadcast)
    while (limit_s is None or now() < limit_s) and not (should_stop and should_stop()):  # until the time limit, or until told to stop
        for heard in feed_from(listener, source, watch):  # every frame that has completed
            result = heard.result if heard.result.ok and heard.result.frame_type == FRAME_TYPE_LONG else station.hear(heard.audio)  # the station's own decode (which also combines a failed frame with its retry); a long beacon is already decoded, perhaps from several copies added together
            if logging:  # a signal log is kept
                signal_log.rx(heard, station_result=result, dial_khz=dial())  # both decodes, and the clip if clips are kept
            stamp(describe(result))  # tell the operator
            if on_frame is not None:  # someone keeps a detailed log
                on_frame(result)  # pass on every report, decoded or not
            if on_heard is not None and result.ok:  # somebody was heard clearly
                on_heard(result)  # let the caller note who
            reply = station.handle(result, now())  # what the link rules say to do
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
        tx = station.poll(now())  # anything to send without having heard something?
        if tx is not None:  # yes
            transmit(tx)  # send it
        for line in station.log[told:]:  # the station's own notes since last time
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
