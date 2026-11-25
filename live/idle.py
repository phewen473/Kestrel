"""The idle timeout of a contact, Keep-Alive, and the 10-second warning to both operators (since 0.41).

A locked contact with no messages either way for IDLE_S (3 minutes) ends.
On a working frequency the station's link rules close it themselves and both
stations return to the calling frequency; on the calling frequency this
watcher ends it (the station sends its closing identification).

Keep-Alive, a setting, gives a contact on a working frequency IDLE_S more
(6 minutes in all), never more than that: shortly before the first limit the
station sends one short "KEEP-ALIVE" message, which counts as traffic at both
ends, so both stations' timers start again. It does nothing on the calling
frequency, which must stay clear.

WARN_S (10 seconds) before a contact would end, the operator is warned and may
choose Keep going (a short "KEEP GOING" message, which restarts both timers) or
Disconnect (End contact). Both stations count the same silence, so both
operators see the warning at about the same moment.

Everything here takes the time as an argument and reads the station only
through attributes both station kinds have (state, partner, link, moved,
last_traffic), so it works with the compiled station and can be tested
without a clock.
"""

IDLE_S = 180.0  # a contact with no messages either way for this long ends (WORKING_IDLE_S in the link rules)
EXTRA_S = 180.0  # Keep-Alive's extra time on a working frequency (sent as one KEEP-ALIVE message, so it counts at both ends)
WARN_S = 10.0  # the operators are warned this long before a contact ends
KEEPALIVE_AHEAD_S = 20.0  # Keep-Alive's message goes this long before the limit, so it is on the air before either station's timer runs out
KEEPALIVE_TEXT = "KEEP-ALIVE"  # the message Keep-Alive sends (it shows at the other station like any message)
KEEP_GOING_TEXT = "KEEP GOING"  # the message the warning's Keep going button sends
KEEPALIVE_SPAN_S = 120.0  # traffic this close to a KEEP-ALIVE (sent or received) is taken to be that KEEP-ALIVE (it may take a minute or more to go out at a slow level)
LOCKED = ("LOCKED", "DEGRADED", "REACQUIRE")  # the states of a contact in progress


class IdleWatch:  # follows one station's contact and says when to extend, warn or end it
    """Call check(station, now) often; it returns None, ("extend", partner), ("warn", partner, seconds_left) or ("end", partner)."""

    def __init__(self, keep_alive=lambda: False, idle_s=IDLE_S, warn_s=WARN_S):  # set up
        self.keep_alive = keep_alive  # called each time: True while the Keep-Alive setting is on
        self.idle_s, self.warn_s = idle_s, warn_s  # the limit and the warning
        self.key = None  # (partner, link) of the contact being followed
        self.started = 0.0  # when it was first seen locked
        self.last = None  # the last traffic time seen, so new traffic can be noticed
        self.extended = self.warned = self.ended = False  # what has been done in this quiet stretch
        self.marks = []  # when a KEEP-ALIVE went out or came in: traffic near these is Keep-Alive's own and does not earn another extension
        self.remaining = None  # seconds before the followed contact ends for lack of traffic, as of the last check (None: no contact)

    def keepalive_seen(self, now):  # a KEEP-ALIVE message was sent or received
        """Note a KEEP-ALIVE at `now`, so the quiet stretch it starts is not extended again (two stations with Keep-Alive on must not keep each other going for ever)."""
        self.marks = [t for t in self.marks if now - t < 600.0] + [now]  # recent ones only

    def check(self, station, now):  # what, if anything, to do now
        """Return the action due for `station` at `now` (see the class description), or None."""
        if station.state not in LOCKED:  # no contact
            self.key, self.remaining = None, None  # nothing followed, nothing to count down
            return None  # nothing to do
        key = (station.partner, station.link)  # this contact
        if key != self.key:  # a new contact
            self.key, self.started, self.last = key, now, None  # follow it from now
            self.extended = self.warned = self.ended = False  # nothing done yet
        traffic = station.last_traffic  # when a message last went either way (the link rules keep it)
        last = max(self.started, traffic if isinstance(traffic, (int, float)) else self.started)  # the start of this quiet stretch
        if last != self.last:  # traffic since the last look: a fresh stretch
            self.last = last  # remembered
            own = any(abs(last - t) <= KEEPALIVE_SPAN_S for t in self.marks)  # that traffic was a KEEP-ALIVE (this station's or the partner's)
            self.extended = own  # a real message earns a new extension; a KEEP-ALIVE (either station's) uses it up, so two stations with Keep-Alive on extend once between them
            self.warned = self.ended = False  # each stretch is warned once
        idle = now - last  # how long it has been quiet
        self.remaining = max(0.0, self.idle_s - idle)  # for a countdown shown elsewhere (read by the panel's own thread)
        working = bool(station.moved)  # on a working frequency (Keep-Alive applies only there)
        if working and not self.extended and idle >= self.idle_s - KEEPALIVE_AHEAD_S and self.keep_alive():  # Keep-Alive on, the limit near, not yet extended in this stretch
            self.extended = True  # once
            self.keepalive_seen(now)  # the message about to go is Keep-Alive's own
            return ("extend", station.partner)  # send KEEP-ALIVE: both timers start again
        if not self.warned and idle >= self.idle_s - self.warn_s:  # ten seconds to go
            self.warned = True  # once
            return ("warn", station.partner, max(0.0, self.idle_s - idle))  # warn the operator
        if not working and not self.ended and idle >= self.idle_s:  # on the calling frequency the watcher ends it (on a working frequency the link rules do)
            self.ended = True  # once
            return ("end", station.partner)  # end the contact
        return None  # nothing yet

    def left(self, station, now):  # seconds until the contact ends, for a countdown shown on the panel
        """Return the seconds left before the contact followed ends for lack of traffic, or None when there is no contact."""
        if station.state not in LOCKED or self.key != (station.partner, station.link) or self.last is None:  # not following a contact
            return None  # nothing to show
        return max(0.0, self.last + self.idle_s - now)  # the countdown
