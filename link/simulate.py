"""Run two Stations against each other through the HF channel simulator.

Only one station transmits at a time (as on a real shared frequency).
Each transmission is passed through the simulated radio path for its
direction, handed to the other station's receiver, and the reply (if
any) goes back the same way. When nobody replies, time jumps forward to
the next timeout.
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from sim import run_channel  # the HF channel simulator

from .params import TURNAROUND_S  # pause between hearing and replying


@dataclass  # a plain record
class Path:  # the radio path in one direction
    """How a signal fares on its way from one station to the other."""

    snr_db: object = 0.0  # SNR in 2.5 kHz: a number, or a function of time in seconds that returns one
    condition: str = "awgn"  # fading condition: awgn (none), good (light), moderate or poor (heavy)
    offset_hz: float = 0.0  # frequency error added on the way

    def snr_at(self, t):  # the SNR at a given moment
        """Return the SNR at time `t` seconds."""
        return float(self.snr_db(t)) if callable(self.snr_db) else float(self.snr_db)  # call the function, or use the fixed number


def run_link(a, b, path_ab, path_ba, seed=0, limit_s=3600.0):  # the simulation
    """Run stations `a` and `b` until both fall silent or `limit_s` seconds pass; return a list of events.

    Each event is a dict: t (start time), sender, kind, level, seconds,
    snr_db (the true SNR on the path), heard (True when the other station
    decoded it), note, and the two stations' states and wanted levels
    after the frame was handled.
    """
    rng = np.random.default_rng(seed)  # one repeatable random source for the whole run
    paths = {a.call: path_ab, b.call: path_ba}  # the path each station's signal travels
    other = {a.call: b, b.call: a}  # who hears whom
    events = []  # the record of the run
    t = 0.0  # simulated time, in seconds
    while t < limit_s:  # until the time limit
        sender = tx = None  # nobody is transmitting yet
        for station in (a, b):  # ask each station in turn...
            tx = station.poll(t)  # ...whether it has something to send now
            if tx is not None:  # it does
                sender = station  # it gets the frequency
                break  # the other waits
        if tx is None:  # neither wants to send right now
            wakes = [w for w in (a.next_wake(), b.next_wake()) if w is not None]  # when each next needs attention
            if not wakes:  # neither ever will
                break  # the run is over
            t = max(t + 0.001, min(wakes))  # jump to the earliest of those times
            continue  # and ask again
        while tx is not None and t < limit_s:  # a frame, then its reply, then the reply to that...
            receiver = other[sender.call]  # the station at the far end
            path = paths[sender.call]  # the path in this direction
            snr_db = path.snr_at(t)  # conditions at this moment
            heard = run_channel(tx.audio, snr_db, rng, path.condition, offset_hz=path.offset_hz)  # what arrives at the far end
            result = receiver.hear(heard)  # the far end's receiver has a go
            t += tx.seconds + TURNAROUND_S  # the frame takes its airtime, then the far end turns round
            reply = receiver.handle(result, t)  # the far end decides what to do
            events.append({  # record what happened
                "t": t - tx.seconds - TURNAROUND_S, "sender": sender.call, "kind": tx.kind, "level": tx.level, "seconds": tx.seconds,  # (continued)
                "snr_db": snr_db, "heard": bool(result.ok), "note": tx.note,  # (continued)
                "states": (a.state, b.state), "wants": (a.want, b.want),  # (continued)
            })  # end of the event
            sender, tx = receiver, reply  # the far end now transmits its reply, if it has one
    return events  # the whole story


def describe(events):  # turn the events into readable lines
    """Return one line of text per event."""
    lines = []  # the output
    for e in events:  # one line each
        mark = "heard" if e["heard"] else "LOST "  # did the far end decode it?
        lines.append(f"{e['t']:7.1f}s  {e['sender']:9s} {e['kind']:8s} L{e['level']}  {e['seconds']:5.1f}s  SNR {e['snr_db']:+5.1f} dB  {mark}  {e['note']}")  # time, who, what, level, length, conditions, outcome
    return lines  # ready to print
