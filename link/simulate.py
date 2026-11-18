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


def run_link(a, b, path_ab, path_ba, seed=0, limit_s=3600.0, start_s=0.0):  # the simulation
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
    t = start_s  # simulated time, in seconds
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
            t += tx.delay  # an answer waits for its reply slot
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
        snr = f"SNR {e['snr_db']:+5.1f} dB" if e["snr_db"] == e["snr_db"] else "to everyone "  # the path's SNR, or a note that the frame went to several stations at once
        lines.append(f"{e['t']:7.1f}s  {e['sender']:9s} {e['kind']:8s} L{e['level']}  {e['seconds']:5.1f}s  {snr}  {mark}  {e['note']}")  # time, who, what, level, length, conditions, outcome
    return lines  # ready to print


def run_group(caller, others, paths_out, paths_in, seed=0, limit_s=7200.0):  # one calling station, several answering stations
    """Let `caller` beacon and work each of `others` in turn; return the list of events.

    `paths_out[call]` is the path from the caller to that station and
    `paths_in[call]` the path back. Answers that fall in the same reply
    slot are added together, as they would be on the air, so the caller
    hears a collision. After each contact the caller beacons again for
    whoever is left.
    """
    rng = np.random.default_rng(seed)  # one repeatable random source for the whole run
    events = []  # the record of the run
    t = 0.0  # simulated time, in seconds
    waiting = list(others)  # stations not yet worked
    while waiting and t < limit_s:  # until everyone is worked or time runs out
        beacon = caller.poll(t)  # the caller's next beacon (None once it has given up)
        if beacon is None:  # the caller has stopped calling
            break  # the run is over
        t_end = t + beacon.seconds + TURNAROUND_S  # when the reply window opens
        events.append(_event(t, caller.call, beacon, float("nan"), True, caller, None))  # record the beacon
        answers = {}  # reply slot -> list of (station, answer)
        for station in waiting:  # every station still waiting hears the beacon over its own path
            path = paths_out[station.call]  # caller to this station
            heard = station.hear(run_channel(beacon.audio, path.snr_at(t), rng, path.condition, offset_hz=path.offset_hz))  # what it receives
            answer = station.handle(heard, t_end)  # does it answer?
            if answer is not None:  # yes
                answers.setdefault(round(answer.delay / _slot_length()), []).append((station, answer))  # file it under its slot
        confirm = None  # the caller's reply, once it has chosen
        for slot in sorted(answers):  # the reply slots, in time order
            t_slot = t_end + slot * _slot_length()  # when this slot starts
            mixed = None  # what the caller hears in this slot
            for station, answer in answers[slot]:  # every answer in the slot
                path = paths_in[station.call]  # this station to the caller
                arrived = run_channel(answer.audio, path.snr_at(t_slot), rng, path.condition, offset_hz=path.offset_hz)  # its signal at the caller
                mixed = arrived if mixed is None else mixed + arrived  # answers in the same slot pile on top of each other
                events.append(_event(t_slot, station.call, answer, path.snr_at(t_slot), len(answers[slot]) == 1, caller, station))  # record the answer
            result = caller.hear(mixed)  # the caller's receiver has a go at the slot
            if len(answers[slot]) > 1:  # a shared slot
                for event in events[-len(answers[slot]):]:  # mark which of the colliding answers, if any, got through
                    event["heard"] = bool(result.ok) and result.origin == event["sender"]  # only the one the caller decoded
            else:  # a slot with one answer
                events[-1]["heard"] = bool(result.ok)  # did it decode?
            confirm = caller.handle(result, t_slot + answers[slot][0][1].seconds + TURNAROUND_S) or confirm  # a single-slot window is settled at once
        t = caller.deadline if caller.pending == "answer" else t_end + _slot_length()  # the window closes
        if confirm is None:  # a wide window, or nothing decoded
            confirm = caller.poll(t)  # the caller decides: lock with the best answer, or beacon again
            if confirm is not None and confirm.kind == "beacon":  # it beaconed again
                caller.pending, caller.beacons = None, caller.beacons - 1  # hand that beacon back; the loop will send it properly
                continue  # next round
        if confirm is None:  # the caller gave up
            break  # the run is over
        events.append(_event(t, caller.call, confirm, float("nan"), True, caller, None))  # record the confirmation
        chosen = None  # the station the caller locked with
        for station in waiting:  # everyone hears the confirmation
            path = paths_out[station.call]  # caller to this station
            station.handle(station.hear(run_channel(confirm.audio, path.snr_at(t), rng, path.condition, offset_hz=path.offset_hz)), t + confirm.seconds + TURNAROUND_S)  # only the chosen station acts on it
            if station.call == caller.partner:  # this is the one
                chosen = station  # remember it
        t += confirm.seconds + TURNAROUND_S  # the confirmation takes its airtime
        contact = run_link(caller, chosen, paths_out[chosen.call], paths_in[chosen.call], seed=int(rng.integers(1 << 30)), limit_s=limit_s, start_s=t)  # the contact itself
        events.extend(contact)  # add its events
        t = max([t] + [e["t"] + e["seconds"] for e in contact]) + TURNAROUND_S  # carry on after it ends
        if chosen.state == "RELEASED":  # the contact finished
            waiting.remove(chosen)  # that station is done
        for station in waiting:  # the others gave up waiting for a confirmation long ago
            station.poll(t)  # let their timeouts run so they are listening again
        caller.new_contact()  # the caller is free for the next station
    return events  # the whole story


def _slot_length():  # the reply slot length
    """Return the length of one reply slot, in seconds."""
    from .params import REPLY_SLOT_S  # the setting
    return REPLY_SLOT_S  # as configured


def _event(t, sender, tx, snr_db, heard, a, b):  # one line of the record
    """Return an event dict in the same form run_link produces."""
    return {"t": t, "sender": sender, "kind": tx.kind, "level": tx.level, "seconds": tx.seconds, "snr_db": snr_db, "heard": heard, "note": tx.note,  # (continued)
            "states": (a.state, b.state if b is not None else ""), "wants": (a.want, b.want if b is not None else 0)}  # states and wanted levels at that moment
