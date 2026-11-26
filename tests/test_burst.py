"""Tests for acknowledgment bursts (modem/burst.py, live/burstwatch.py, and their use by the stations; since 0.43)."""

import numpy as np  # numerical arrays

from link import Path, run_link  # the simulated contact
from link.station import PythonStation, Station  # the stations
from live.burstwatch import SEARCH_AT_S, BurstWatch  # the live wait for a burst
from live.runner import traffic_too_weak  # the switch to long notes
from modem import ACK_HAVE_IT, ACK_OK, ACK_RESEND  # verdicts
from modem import burst as B  # the bursts
from modem.params import FS  # sample rate
from sim.channel import _analytic, add_noise, watterson  # the channel's parts

SAYS = B.BurstSays(1234, 56, 2, ACK_OK, 3)  # part 2 of message 56 received; send at L3
CANDS = [B.BurstSays(1234, 56, 2, s, w) for s in (ACK_OK, ACK_HAVE_IT) for w in range(5)] + [B.BurstSays(1234, 0, 2, ACK_RESEND, w) for w in range(5)]  # what the waiting station listens for


def _through(audio, delay_s, snr, rng, offset_hz=0.0, spread=0.5):  # a burst arriving
    """Return `audio` starting `delay_s` into a stretch long enough for the search, faded, shifted and noisy."""
    y = np.concatenate([np.zeros(int(delay_s * FS)), audio, np.zeros(3 * FS)])  # in its place
    a = watterson(_analytic(y), spread, 1.0, rng) if spread > 0 else _analytic(y)  # fading
    y = (a * np.exp(2j * np.pi * offset_hz * np.arange(len(a)) / FS)).real  # frequency offset
    return add_noise(y, snr, float(np.mean(audio ** 2)), rng)  # noise


def test_patterns_are_fixed_and_distinct():  # both stations make the same pattern
    """A pattern depends only on what the burst says; it never repeats a tone twice running; changing any field changes it."""
    p = B.pattern(SAYS)  # the pattern
    assert len(p) == B.BURST_TONES and np.array_equal(p, B.pattern(B.BurstSays(1234, 56, 2, ACK_OK, 3)))  # fixed
    assert np.all(p[1:] != p[:-1])  # a new tone every slot
    for other in (B.BurstSays(1235, 56, 2, 0, 3), B.BurstSays(1234, 57, 2, 0, 3), B.BurstSays(1234, 56, 3, 0, 3), B.BurstSays(1234, 56, 2, 1, 3), B.BurstSays(1234, 56, 2, 0, 2)):  # one field changed
        assert np.sum(B.pattern(other) != p) >= 18  # nearly every tone differs
    assert abs(len(B.build_burst(SAYS)) / FS - 9.6) < 1e-9  # 9.6 s on the air


def test_burst_is_recognized_weak_and_offset():  # the gain it was added for
    """A burst at -20 dB in fading, 3 s late, is recognized with what it says; 12 Hz off tune it is found only when the search is centered there."""
    rng = np.random.default_rng(1)  # repeatable
    found = 0  # recognized right
    for _ in range(6):  # a few bursts
        x = _through(B.build_burst(SAYS), 3.0, -20.0, rng)  # through the channel
        r = B.heard(x, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS))  # searched
        found += r is not None and r.fields["status"] == ACK_OK and r.fields["report"].want_level == 3  # right
    assert found >= 5  # measured: 6 of 6
    x = _through(B.build_burst(SAYS), 2.0, -14.0, rng, offset_hz=12.0)  # 12 Hz off (a radio a little off tune)
    assert B.heard(x, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS), 0.0) is None  # outside a search centered on 0
    r = B.heard(x, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS), 12.0)  # centered where the partner is
    assert r is not None and r.burst and r.link == 1234 and r.msg_id == 56 and r.part == 2  # found, as an acknowledgment
    assert abs(r.snr_db - (-14.0)) < 4.0 and abs(r.offset_hz - 12.0) <= 0.5  # measured roughly right


def test_noise_and_strong_frames_are_not_bursts():  # no false acknowledgments
    """Noise alone, and a strong Kestrel frame where the burst could be, are not taken for a burst."""
    from modem import build_frame  # a frame
    rng = np.random.default_rng(2)  # repeatable
    for _ in range(20):  # searches of noise
        assert B.heard(rng.standard_normal(20 * FS), CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS)) is None  # nothing
    frame = build_frame("A STRONG FRAME OVER THE BURST", 0)  # a strong L0 frame instead
    x = add_noise(np.concatenate([np.zeros(FS), frame[:18 * FS]]), 20.0, float(np.mean(frame ** 2)), rng)  # at +20 dB
    assert B.heard(x, CANDS, int(B.BURST_EARLIEST_S * FS), int(B.BURST_LATEST_S * FS)) is None  # ranks ignore loudness


def test_burst_watch_searches_once_after_enough_audio():  # the live wait
    """Armed by a frame that awaits a burst, the watch searches once the audio is in, hands back the acknowledgment, and is then done."""
    class Tx:  # a transmission awaiting a burst
        listen, listen_hz = CANDS, 0.0  # what it awaits, and where
    rng = np.random.default_rng(3)  # repeatable
    x = _through(B.build_burst(SAYS), 2.5, -10.0, rng)  # the burst after the frame
    x = np.concatenate([x, np.zeros(int(SEARCH_AT_S * FS))])  # and quiet after
    watch = BurstWatch()  # the watch
    watch.arm(Tx())  # a frame went
    watch.feed(x[:5 * FS])  # some audio
    assert watch.check() is None and watch.waiting  # too early
    watch.feed(x[5 * FS:])  # the rest
    r = watch.check()  # searched
    assert r is not None and r.fields["status"] == ACK_OK and not watch.waiting  # found, and the wait is over
    watch.arm(type("NoTx", (), {"listen": None})())  # a frame that awaits nothing
    watch.feed(x)  # audio
    assert watch.check() is None and not watch.waiting  # nothing searched


def _contact(make, bursts=True):  # one simulated contact
    """Return (a, b, events) for A beaconing, B answering, and a message each way at a middling SNR."""
    a, b = make("Q1AAAA", "EM92"), make("Q2BB", "FN31")  # two stations
    a.bursts = b.bursts = bursts  # bursts on or off
    a.beacon()  # A calls
    b.listen()  # B answers
    a.queue("FIRST MESSAGE FROM A")  # traffic
    b.queue("REPLY FROM B")  # and back
    return a, b, run_link(a, b, Path(-6.0, "moderate", offset_hz=2.0), Path(-6.0, "moderate", offset_hz=-1.5), seed=4)  # through moderate fading


def test_contact_runs_on_bursts():  # both stations, both implementations
    """With bursts the lock is confirmed and every message acknowledged by a 9.6 s burst; without them by frames; the messages arrive either way."""
    for make in (PythonStation, Station):  # the reference, and the compiled station when the library is in use
        a, b, events = _contact(make)  # with bursts
        assert b.inbox == ["FIRST MESSAGE FROM A"] and a.inbox == ["REPLY FROM B"]  # delivered
        acks = [e for e in events if e["kind"] in ("ack", "confirm")]  # acknowledgments and the confirmation
        assert acks and all(e["note"].startswith("burst") and abs(e["seconds"] - 9.6) < 1e-6 for e in acks[:2])  # the confirmation and the first acknowledgment are bursts
        a, b, events = _contact(make, bursts=False)  # without
        assert b.inbox == ["FIRST MESSAGE FROM A"] and a.inbox == ["REPLY FROM B"]  # delivered
        assert not any(e["note"].startswith("burst") for e in events)  # no bursts at all


def test_message_bursts_need_a_recent_full_report():  # the report still goes, now and then
    """A station acknowledges with a burst only while its last full report is younger than REPORT_EVERY_S; a frame (with the report) restarts the clock."""
    s = PythonStation("Q1AAAA", "EM92")  # a station
    s.link, s.allowed, s.want = 99, [0, 1, 2], 1  # as if locked
    s.report_at = 0.0  # a report went at time 0
    assert s._ack(100.0, 5, 0, ACK_OK, "ack").note.startswith("burst")  # fresh: a burst
    tx = s._ack(400.0, 5, 0, ACK_OK, "ack")  # five minutes on
    assert not tx.note.startswith("burst") and s.report_at == 400.0  # a frame, and the clock restarts
    listen = s._listen_for(7, 1)  # what a frame of message 7 part 1 awaits
    assert {(x.msg_id, x.status) for x in listen} == {(7, ACK_OK), (7, ACK_HAVE_IT), (0, ACK_RESEND)} and len(listen) == 9  # three verdicts at three levels


def test_long_notes_take_over_when_the_partner_hears_too_little():  # the switch to long notes
    """Traffic goes to long notes only for a fresh report at or below the limit, at L0, with messages waiting for the partner."""
    s = PythonStation("Q1AAAA", "EM92")  # a station
    s.state, s.partner = "LOCKED", "Q2BB"  # in a contact
    s.queue("WAITING", "Q2BB")  # traffic for the partner
    notes = object()  # long notes are available
    assert traffic_too_weak(s, notes, (100.0, -24.0, 0), 200.0) == "Q2BB"  # weak, fresh, L0: switch
    assert traffic_too_weak(s, notes, (100.0, -18.0, 0), 200.0) is None  # strong enough
    assert traffic_too_weak(s, notes, (100.0, -24.0, 0), 800.0) is None  # report too old
    assert traffic_too_weak(s, None, (100.0, -24.0, 0), 200.0) is None  # no long notes


def test_live_loop_takes_a_burst_as_the_acknowledgment():  # live/runner.py with stand-in audio
    """A locked station sends its message; the burst that follows in the received audio is recognized and the message counts as delivered."""
    from live.runner import run_station  # the live loop
    from modem import link_id  # the link number

    a = PythonStation("Q1AAAA", "EM92")  # this station
    a.role, a.state, a.partner, a.leads, a.my_turn = "beaconer", "LOCKED", "Q2BB", True, True  # as if just locked with Q2BB
    a.link, a.allowed, a.tx_level, a.want = link_id("Q1AAAA", "Q2BB"), [0, 1, 2, 3, 4], 4, 2  # its link and levels
    a.last_ident = 0.0  # its callsign just went out (no identification due)
    a.queue("HELLO BY BURST")  # its message
    sent = []  # what went out

    class Sink:  # a sound card that keeps what it is given
        def play(self, audio):  # send it
            pass  # nothing to do

    class Ptt:  # a transmit switch that does nothing
        def key(self):  # on
            pass  # nothing
        def unkey(self):  # off
            pass  # nothing

    class Source:  # received audio: quiet, then the partner's burst 2 s after each message frame
        def __init__(self):  # nothing queued
            self.queue = np.zeros(0)  # audio still to hand over
        def read(self):  # the newest audio, half a second at a time (faster than real time, so the test is quick)
            if not len(self.queue):  # nothing queued
                return np.zeros(6000)  # quiet
            out, self.queue = self.queue[:6000], self.queue[6000:]  # the next piece
            return out  # handed over
        def flush(self):  # after a transmission
            tx = sent[-1] if sent else None  # what was just sent
            if tx is not None and tx.kind == "message":  # a message frame: the partner answers with a burst
                says = next(s for s in tx.listen if s.status == ACK_OK and s.want == 1)  # "received; send at L1"
                rng = np.random.default_rng(6)  # repeatable noise
                self.queue = _through(B.build_burst(says), 2.0, -12.0, rng, spread=0.0)  # 2 s later, at -12 dB
                self.queue = np.concatenate([self.queue, np.zeros(int(20 * FS))])  # then quiet

    run_station(a, Source(), Sink(), Ptt(), say=lambda line: None, limit_s=8.0, listen_first=False, on_transmit=lambda tx, on: sent.append(tx) if on else None)  # a few seconds of running
    assert sent and sent[0].kind == "message" and sent[0].listen  # the message went, awaiting a burst
    assert a.delivered == ["HELLO BY BURST"] and a.tx_level == 1  # the burst acknowledged it, and asked for L1
