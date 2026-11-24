"""Tests for the 0.31R1 receiver improvements for weak signals.

1. Steady signals (carriers) are notched out of the band (modem/notch.py).
2. A control frame that fails alone is added to an earlier failed copy.
3. The callsigns a station expects are tried in a failed control frame.
4. The LDPC decoder's settings (scale 0.9, 200 passes).
None of them changes the signal on the air.
"""

import numpy as np  # numerical arrays

from modem import build_answer, build_beacon, build_frame  # frames to hide in noise
from modem.control import ChannelReport  # an answer's channel report
from modem.frame import Hints, Prior, _rescue_control, control_layout, receive  # the receiver and its help
from modem.params import FRAME_TYPE_ANSWER, FRAME_TYPE_BEACON, FS  # frame types and the sample rate


def _in_noise(audio, snr_db, rng, extra_s=3.0):  # a frame in band noise
    """Return `audio` one second into noise, at `snr_db` in 2.5 kHz."""
    x = rng.normal(size=len(audio) + int(extra_s * FS))  # band noise
    x[FS:FS + len(audio)] += audio * np.sqrt(10 ** (snr_db / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # the frame at its strength
    return x  # the recording


def test_noise_alone_is_left_unchanged():  # nothing steady: nothing touched
    from modem.notch import remove_steady  # the routine under test
    x = np.random.default_rng(1).normal(size=60 * FS)  # a minute of noise
    assert np.array_equal(remove_steady(x), x)  # exactly the same audio


def test_a_carrier_is_notched_and_the_frame_decodes():  # a carrier on the frame's own tones
    from modem.levels import LEVELS  # the speed levels
    rng = np.random.default_rng(2)  # repeatable
    spec = LEVELS[2]  # L2
    audio = build_frame("Notch test message", level=2)  # a frame
    x = _in_noise(audio, -12.0, rng, extra_s=6.0)  # at -12 dB, inside L2's limit
    t = np.arange(len(x)) / FS  # time of each sample
    x += np.sqrt(2 * 10 ** (-10 / 10) * (2500 / 6000)) * np.cos(2 * np.pi * spec.tone_bins[14] * spec.bin_hz * t)  # a carrier right on one of its tones
    assert not receive(x, notch=False, long_beacons=False).ok  # the carrier spoils it
    assert receive(x, long_beacons=False).ok  # notched out, it decodes


def test_a_strong_frame_survives_the_notch():  # a strong Kestrel frame must not be taken for carriers
    rng = np.random.default_rng(3)  # repeatable
    for level in (0, 1, 2, 3, 4):  # every level
        x = _in_noise(build_frame("Strong frame", level=level), 15.0, rng)  # far above the noise
        result = receive(x, long_beacons=False)  # notch on (the default)
        assert result.ok and result.text == "Strong frame"  # read as always


def test_two_weak_copies_of_a_beacon_are_added_together():  # combining repeats
    rng = np.random.default_rng(4)  # repeatable
    audio = build_beacon("Q2BB", "EM94", level=0)  # a beacon
    for _ in range(20):  # until a pair is found where both copies fail alone (at -23.5 dB most do)
        first = receive(_in_noise(audio, -23.5, rng), long_beacons=False)  # the first copy
        second_x = _in_noise(audio, -23.5, rng)  # the second
        if first.ok or first.body_llrs is None or receive(second_x, long_beacons=False).ok:  # one read alone, or the first had no readable header
            continue  # not the case being tested
        prior = Prior(first.frame_type, first.body_llrs, first.offset_hz, -1)  # the first copy, kept
        result = receive(second_x, long_beacons=False, hints=Hints(priors=[prior], base=-1))  # the second, with the first offered
        if result.ok:  # read together
            assert result.fields["origin"] == "Q2BB" and "2 copies" in result.assisted  # the right beacon, and it says how
            return  # done
    raise AssertionError("no pair of weak copies was read together")  # combining never helped


def test_an_expected_callsign_helps_read_an_answer():  # expected callsigns
    rng = np.random.default_rng(5)  # repeatable
    audio = build_answer("Q1AAAA", "Q2BB", ChannelReport(-10, 0.1, 0, 0), level=2)  # Q2BB answering Q1AAAA
    helped = 0  # answers read only with help
    for _ in range(40):  # weak copies (40 since 0.32: the cleaner signal reads more copies alone, leaving fewer for help to rescue)
        x = _in_noise(audio, -17.0, rng)  # below L2's limit
        if receive(x, long_beacons=False).ok:  # read alone
            continue  # not the case being tested
        result = receive(x, long_beacons=False, hints=Hints(own="Q1AAAA", calls=("Q5EEEE", "Q2BB", "Q6FFF"), base=-1))  # with Q1AAAA's expectations
        if result.ok:  # read with help
            assert (result.dest, result.origin) == ("Q1AAAA", "Q2BB") and "expecting" in result.assisted  # the right answer, and it says how
            helped += 1  # counted
    assert helped >= 3  # help made a difference several times


def test_noise_is_not_read_as_an_expected_station():  # the cost of trying: false reads must stay very rare
    rng = np.random.default_rng(6)  # repeatable
    calls = ("Q2BB", "Q5EEEE", "Q6FFF", "Q3CCC", "Q4DDD", "Q7GG", "Q8HHH", "Q9JJ")  # eight expected stations (the most the panel offers)
    for frame_type in (FRAME_TYPE_BEACON, FRAME_TYPE_ANSWER):  # the frames that carry callsigns
        size = control_layout(frame_type)["coded"]  # soft bits in such a body
        for _ in range(1500):  # many noise-only bodies, each with two noise "earlier copies"
            priors = [Prior(frame_type, rng.normal(size=size) * 2.0, 0.0, -1) for _ in range(2)]  # noise kept as if it were copies
            data, _how = _rescue_control(rng.normal(size=size) * 2.0, frame_type, 0.0, -1, Hints(own="Q1AAAA", calls=calls, priors=priors, base=-1))  # every help tried
            assert data is None  # never read as a frame


def test_ldpc_settings():  # the decoder's settings since 0.31R1
    from modem import ldpc  # the decoder
    assert (ldpc.SCALE, ldpc.MAX_ITERATIONS) == (0.9, 200)  # as measured best
