"""Tests for signal recognition (since 0.37): live/signalwatch.py, fed with made-up signals of each kind."""

import numpy as np  # arrays

RATE = 48000  # the sound card's rate
T0 = 1795500000.0  # an even minute (a multiple of 120 s), as seconds since 1970


def run(audio, start, dial_khz=14112.5, rng_seed=1):  # feed audio to a watch as the panel does, twice a second
    """Return the SignalWatch after hearing `audio` (at RATE) that began at time `start`, with a little noise added, and two seconds of silence after."""
    from live.signalwatch import SignalWatch  # the watcher

    rng = np.random.default_rng(rng_seed)  # repeatable noise
    audio = np.concatenate([np.zeros(RATE), audio, np.zeros(4 * RATE)])  # a second before, four after (so every track ends)
    audio = audio + 0.01 * rng.standard_normal(len(audio))  # the band's noise
    w = SignalWatch()  # the watcher
    for end in range(RATE, len(audio), RATE // 2):  # every half second
        w.feed(audio[:end], now=start - 1.0 + end / RATE, dial_khz=dial_khz)  # the newest second, at its time
    return w  # what it found


def tones(freqs, seconds_each, total, level=0.03):  # an FSK signal
    """Return `total` seconds of a signal hopping through `freqs` (Hz), each held `seconds_each`, phase continuous."""
    n = int(total * RATE)  # samples
    which = (np.arange(n) / (seconds_each * RATE)).astype(int) % len(freqs)  # the tone at each sample
    f = np.asarray(freqs, dtype=float)[which]  # its frequency
    return level * np.sin(2 * np.pi * np.cumsum(f) / RATE)  # phase continuous


def test_ft8_wspr_carrier_and_cw_are_recognized():  # the main kinds
    rng = np.random.default_rng(2)  # for the tone sequences
    ft8 = tones(1000 + 6.25 * rng.integers(0, 8, 79), 0.16, 12.64)  # 8 tones 6.25 Hz apart, 79 symbols of 0.16 s
    w = run(ft8, T0 + 0.5)  # starts half a second after a 15-second boundary
    assert [t.kind for t in w.done] == ["FT8"], [(t.kind, t.width, t.seconds) for t in w.done]  # one FT8 signal
    assert abs(w.done[0].center - 1022) < 10 and 11.0 <= w.done[0].seconds <= 14.5  # about where and how long
    assert run(ft8, T0 + 0.5, dial_khz=14078.0).done[0].kind == "JS8"  # the same on a JS8 frequency
    wspr = tones(1500 + 1.4648 * rng.integers(0, 4, 162), 0.6827, 110.6)  # 4 tones 1.46 Hz apart, 162 symbols
    assert [t.kind for t in run(wspr, T0 + 1.0).done] == ["WSPR"]  # an even minute, two minutes long
    carrier = 0.03 * np.sin(2 * np.pi * 800 * np.arange(10 * RATE) / RATE)  # a steady tone for 10 s
    assert [t.kind for t in run(carrier, T0 + 3.3).done] == ["Carrier"]  # steady
    gate = np.repeat(rng.integers(0, 2, 40), RATE // 4)[:10 * RATE].astype(float)  # keyed on and off in quarter seconds
    gate = np.convolve(gate, np.hanning(480) / np.hanning(480).sum(), mode="same")  # each edge shaped over 10 ms, as a transmitter's keying is
    keyed = carrier * gate  # keyed
    kinds = [t.kind for t in run(keyed, T0 + 3.3).done]  # what it made of it
    assert kinds and all(k == "CW" for k in kinds), kinds  # keyed


def test_noise_alone_shows_nothing_and_weak_ft8_is_found():  # no false signals, and a weaker one still seen
    w = run(np.zeros(30 * RATE), T0, rng_seed=9)  # thirty seconds of band noise
    assert w.done == [], [(t.kind, t.lo, t.width, len(t.levels)) for t in w.done]  # nothing reported
    rng = np.random.default_rng(4)  # tone sequence
    weak = tones(1500 + 6.25 * rng.integers(0, 8, 79), 0.16, 12.64, level=0.004)  # about -2 dB in 2.5 kHz
    assert [t.kind for t in run(weak, T0 + 15.4).done] == ["FT8"]  # still recognized


def test_rtty_pair_and_kestrel_label():  # two tones 170 Hz apart, and a Kestrel decode naming a track
    rng = np.random.default_rng(3)  # random keying
    bits = rng.integers(0, 2, 200)  # 200 bits of 22 ms
    keyed = np.repeat(bits, int(0.022 * RATE))  # each bit held 22 ms
    rtty = 0.03 * np.sin(2 * np.pi * np.cumsum(np.where(keyed, 1445.0, 1275.0)) / RATE)  # mark and space 170 Hz apart, randomly keyed
    w = run(rtty, T0 + 7.2)  # off any boundary
    assert w.done and all(t.kind == "RTTY" for t in w.done), [(t.kind, t.lo, t.hi) for t in w.done]  # one signal, or its two halves, all RTTY
    kes = tones(1500 + 22.2 * np.arange(32), 0.09, 8.0)  # a Kestrel-like L2 signal, 710 Hz wide
    from live.signalwatch import SignalWatch  # the watcher
    w = run(kes, T0 + 3.0)  # heard
    w.kestrel_heard(1844.0, 710.0, "L2 Q1AAAA", when=T0 + 11.5)  # the receiver decoded it as it ended
    assert w.done[-1].kind == "Kestrel" and w.done[-1].detail == "L2 Q1AAAA"  # renamed
    live, finished = w.rows(("Kestrel",))  # the window's list
    assert finished and finished[0].detail == "L2 Q1AAAA"  # listed
    assert w.rows(("FT8",))[1] == []  # filtered out when Kestrel is not chosen
    assert len(bits) == 200 and SignalWatch  # (names used)
