"""Run one Station on real audio, in real time.

The same Station that link/simulate.py drives through the channel
simulator is driven here by the clock on the wall, a sound-card input
and a sound-card output. Nothing in the link rules knows the difference.
"""

import time  # the real clock

from link.params import TURNAROUND_S  # pause between hearing a frame and replying
from modem.params import CONTROL_BITS  # which frame types are control frames

from .listener import Listener  # the continuous receiver

KIND = {0: "message", 1: "addressed message", 2: "beacon", 3: "answer", 4: "acknowledgment", 5: "identification"}  # frame type -> plain name
LIVE_REPLY_MARGIN_S = 10.0  # extra time a live station waits for a reply: the receiver looks through its audio once a second, and sound cards add delay


def describe(result):  # one line about a received frame
    """Return a readable line describing the receiver's report `result`."""
    name = KIND.get(result.frame_type, "frame")  # what kind of frame
    if not result.ok:  # it failed its check
        return f"heard a {name} at L{result.level} that failed its check ({result.snr_db:+.0f} dB)"  # say so
    line = f"heard {name} at L{result.level}, {result.snr_db:+.1f} dB, offset {result.offset_hz:+.1f} Hz, fading {result.fade_index:.2f}"  # the measurements
    if result.frame_type in CONTROL_BITS:  # a control frame
        return line + f"  {result.fields}"  # show its fields
    who = f"{result.origin} to {result.dest}" if result.frame_type == 1 else f"link {result.link}"  # addresses, or the link number
    return line + f"  [{who}, msg {result.msg_id}, part {result.part + 1}/{result.parts}]  {result.text!r}"  # show the text


def run_station(station, source, sink, ptt, say=print, limit_s=None, stay_on=False):  # the live loop
    """Run `station` until its contact ends (or for ever with `stay_on`), or until `limit_s` seconds pass.

    `source` has read() and flush() (see audio.AudioIn), `sink` has
    play(audio) (see audio.AudioOut), `ptt` keys the transmitter
    (see ptt.Ptt), and `say` is called with each line of the running log.
    """
    station.reply_margin = LIVE_REPLY_MARGIN_S  # allow for real-world delays when waiting for replies
    listener = Listener()  # the continuous receiver
    started = time.monotonic()  # the moment the clock starts
    told = 0  # how many lines of the station's own log have been passed on

    def now():  # seconds since the start
        return time.monotonic() - started  # the station's clock

    def stamp(text):  # pass a line to the operator
        say(f"{now():7.1f}s  {text}")  # with the time

    def transmit(tx):  # put one frame on the air
        waited = time.monotonic()  # when the wait for a reply slot began
        while time.monotonic() - waited < tx.delay:  # an answer waits for its slot
            source.read()  # keep the input from piling up
            time.sleep(0.05)  # a short nap
        stamp(f"sending {tx.kind} at L{tx.level}, {tx.seconds:.1f} s  {tx.note}")  # tell the operator
        ptt.key()  # transmitter on
        try:  # whatever happens...
            sink.play(tx.audio)  # send the audio
        finally:  # ...the transmitter must come off
            ptt.unkey()  # transmitter off
        source.flush()  # throw away whatever was received meanwhile (it was this station's own signal)
        listener.clear()  # and forget it

    stamp(f"{station.call} on the air as {station.role}")  # opening line
    while limit_s is None or now() < limit_s:  # until the time limit, if there is one
        for heard in listener.feed(source.read()):  # every frame that has completed
            result = station.hear(heard.audio)  # the station's own decode (which also combines a failed frame with its retry)
            stamp(describe(result))  # tell the operator
            reply = station.handle(result, now())  # what the link rules say to do
            if reply is not None:  # something to send
                time.sleep(TURNAROUND_S)  # give the other station time to switch to receive
                transmit(reply)  # send it
        tx = station.poll(now())  # anything to send without having heard something?
        if tx is not None:  # yes
            transmit(tx)  # send it
        for line in station.log[told:]:  # the station's own notes since last time
            say("          " + line)  # pass them on
        told = len(station.log)  # remember how far we got
        if station.state == "RELEASED":  # the contact is over
            if not stay_on:  # one contact was all that was wanted
                break  # stop
            station.new_contact()  # otherwise get ready for the next
            stamp("listening again")  # tell the operator
        time.sleep(0.1)  # a tenth of a second between looks
    stamp("finished")  # closing line
