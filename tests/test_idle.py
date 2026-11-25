"""The contact's idle timeout, Keep-Alive and the 10-second warning (since 0.41)."""
from types import SimpleNamespace  # a stand-in station

from live.idle import IDLE_S, KEEPALIVE_AHEAD_S, WARN_S, IdleWatch  # the watcher under test


def _station(moved=False, last=0.0, state="LOCKED"):  # what the watcher reads of a station
    return SimpleNamespace(state=state, partner="Q2BB", link=7, moved=moved, last_traffic=last)  # a locked contact with Q2BB


def test_calling_frequency_warns_then_ends():  # standard rule, no Keep-Alive on the calling frequency
    watch = IdleWatch(keep_alive=lambda: True)  # Keep-Alive on, but it does not apply here
    station = _station(moved=False)  # locked on the calling frequency
    assert watch.check(station, 0.0) is None  # just locked
    assert watch.check(station, IDLE_S - WARN_S - 1.0) is None  # quiet, not yet
    action = watch.check(station, IDLE_S - WARN_S)  # ten seconds to go
    assert action[0] == "warn" and action[1] == "Q2BB" and abs(action[2] - WARN_S) < 1e-6  # the operator is warned
    assert watch.check(station, IDLE_S - 5.0) is None  # warned once only
    assert watch.check(station, IDLE_S) == ("end", "Q2BB")  # then the contact ends
    assert watch.check(station, IDLE_S + 1.0) is None  # once


def test_traffic_starts_the_clock_again():  # a message either way resets everything
    watch = IdleWatch()  # Keep-Alive off
    station = _station()  # locked
    watch.check(station, 0.0)  # following it
    assert watch.check(station, IDLE_S - WARN_S)[0] == "warn"  # warned
    station.last_traffic = IDLE_S - 5.0  # Keep going sent a message (or one came in)
    assert watch.check(station, IDLE_S) is None  # no longer ending
    assert abs(watch.left(station, IDLE_S) - (IDLE_S - 5.0)) < 1e-6  # the countdown starts again
    assert watch.check(station, 2 * IDLE_S - 5.0 - WARN_S)[0] == "warn"  # and the next quiet stretch is warned too


def test_keep_alive_extends_once_on_a_working_channel():  # +180 s, only on a working frequency, only once per quiet stretch
    on = [True]  # the setting
    watch = IdleWatch(keep_alive=lambda: on[0])  # Keep-Alive on
    station = _station(moved=True)  # locked on a working channel
    watch.check(station, 0.0)  # following it
    assert watch.check(station, IDLE_S - KEEPALIVE_AHEAD_S) == ("extend", "Q2BB")  # KEEP-ALIVE goes out before the limit
    station.last_traffic = IDLE_S - KEEPALIVE_AHEAD_S + 30.0  # it was sent: both timers start again
    later = station.last_traffic + IDLE_S - KEEPALIVE_AHEAD_S  # the next limit draws near
    assert watch.check(station, later) is None  # no second extension: the KEEP-ALIVE was Keep-Alive's own traffic
    assert watch.check(station, station.last_traffic + IDLE_S - WARN_S)[0] == "warn"  # so the warning comes, about six minutes after the last real message
    station.last_traffic = 1000.0  # a real message
    assert watch.check(station, 1000.0 + IDLE_S - KEEPALIVE_AHEAD_S) == ("extend", "Q2BB")  # earns a fresh extension
    partner = IdleWatch(keep_alive=lambda: True)  # the other station, Keep-Alive on too
    theirs = _station(moved=True)  # its side of the contact
    partner.check(theirs, 0.0)  # following it
    partner.keepalive_seen(165.0)  # our KEEP-ALIVE arrives
    theirs.last_traffic = 165.0  # and counts as traffic there
    assert partner.check(theirs, 165.0 + IDLE_S - KEEPALIVE_AHEAD_S) is None  # it does not answer with a KEEP-ALIVE of its own (no ping-pong)
    assert partner.check(theirs, 165.0 + IDLE_S - WARN_S)[0] == "warn"  # its operator is warned at the same time as ours
    off = IdleWatch(keep_alive=lambda: False)  # Keep-Alive off
    working = _station(moved=True)  # on a working channel
    off.check(working, 0.0)  # following it
    assert off.check(working, IDLE_S - KEEPALIVE_AHEAD_S) is None and off.check(working, IDLE_S - WARN_S)[0] == "warn"  # no extension, just the warning
    assert off.check(working, IDLE_S + 1.0) is None  # on a working channel the link rules close it, not the watcher


def test_no_contact_no_action():  # nothing to do while not locked
    watch = IdleWatch()  # the watcher
    assert watch.check(_station(state="IDLE"), 500.0) is None and watch.left(_station(state="IDLE"), 500.0) is None  # nothing
