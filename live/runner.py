"""Run one Station on real audio, in real time.

The same Station that link/simulate.py drives through the channel
simulator is driven here by the clock on the wall, a sound-card input
and a sound-card output. Nothing in the link rules knows the difference.
"""

import re  # finds callsigns and levels in log lines
import time  # the real clock

from link.params import TURNAROUND_S  # pause between hearing a frame and replying
from modem.params import CONTROL_BITS  # which frame types are control frames

from .listener import Listener  # the continuous receiver

KIND = {0: "message", 1: "addressed message", 2: "beacon", 3: "answer", 4: "acknowledgment", 5: "identification"}  # frame type -> plain name
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
        return f"heard a {name} at L{result.level} that failed its check ({result.snr_db:+.0f} dB)"  # say so
    line = f"heard {name} at L{result.level}, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz, fading {result.fade_index:.2f}"  # the measurements
    if result.frame_type in CONTROL_BITS:  # a control frame
        return line + f"  {result.fields}"  # show its fields
    who = f"{result.origin} to {result.dest}" if result.frame_type == 1 else f"link {result.link}"  # addresses, or the link number
    return line + f"  [{who}, msg {result.msg_id}, part {result.part + 1}/{result.parts}]  {result.text!r}"  # show the text


def run_station(station, source, sink, ptt, say=print, limit_s=None, stay_on=False, should_stop=None, retune=None, on_heard=None):  # the live loop
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
    """
    station.can_move = retune is not None  # the station may agree to change frequency only if the radio can be retuned
    tuned = 0  # the offset from the calling frequency the radio is on now
    station.reply_margin = LIVE_REPLY_MARGIN_S  # allow for real-world delays when waiting for replies
    listener = Listener()  # the continuous receiver
    started = time.monotonic()  # the moment the clock starts
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
        stamp(f"sending {tx.kind} at L{tx.level}, {tx.seconds:.1f} s  {tx.note}")  # tell the operator
        ptt.key()  # transmitter on
        try:  # whatever happens...
            sink.play(tx.audio)  # send the audio
        finally:  # ...the transmitter must come off
            ptt.unkey()  # transmitter off
        last_sent[0] = now()  # remember when this transmission ended
        source.flush()  # throw away whatever was received meanwhile (it was this station's own signal)
        listener.clear()  # and forget it

    stamp(f"{station.call} on the air as {station.role or 'broadcaster'}")  # opening line (a station with no role is only sending a broadcast)
    while (limit_s is None or now() < limit_s) and not (should_stop and should_stop()):  # until the time limit, or until told to stop
        for heard in listener.feed(source.read()):  # every frame that has completed
            result = station.hear(heard.audio)  # the station's own decode (which also combines a failed frame with its retry)
            stamp(describe(result))  # tell the operator
            if on_heard is not None and result.ok:  # somebody was heard clearly
                on_heard(result)  # let the caller note who
            reply = station.handle(result, now())  # what the link rules say to do
            if reply is not None:  # something to send
                time.sleep(TURNAROUND_S)  # give the other station time to switch to receive
                transmit(reply)  # send it
        if getattr(source, "lost", 0) > lost:  # the sound card has dropped audio since the last look
            lost = source.lost  # remember the new count
            stamp(f"warning: the sound card lost some received audio ({lost} time(s) so far); a frame may fail and be asked for again")  # tell the operator
        tx = station.poll(now())  # anything to send without having heard something?
        if tx is not None:  # yes
            transmit(tx)  # send it
        for line in station.log[told:]:  # the station's own notes since last time
            say("          " + line)  # pass them on
        told = len(station.log)  # remember how far we got
        wanted = station.tuning(now())  # where the link rules want the radio now
        if retune is not None and wanted != tuned:  # a move to a working frequency, or back
            retune(wanted)  # change the radio's frequency
            tuned = wanted  # remember where it is
            source.flush()  # what was received on the old frequency no longer matters
            listener.clear()  # so forget it
            stamp(f"radio moved to the working frequency ({wanted / 1000.0:+.1f} kHz)" if wanted else "radio back on the calling frequency")  # tell the operator
        if station.state == "RELEASED":  # the contact is over
            if not stay_on:  # one contact was all that was wanted
                break  # stop
            station.new_contact()  # otherwise get ready for the next
            stamp("listening again")  # tell the operator
        time.sleep(0.1)  # a tenth of a second between looks
    stamp("finished")  # closing line
