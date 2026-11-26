"""Tests for the frame's second signature pattern (signal version 0.43).

Every frame is now: pattern, header, body, pattern again, header again (its
check value marked). A frame whose first pattern fades away is found from
its second pattern and read backwards from there. These tests take each end
of a frame away in turn and check that the receiver, the compiled library
and the continuous receiver all still read it.
"""

import numpy as np  # numerical arrays
import pytest  # test parameters

from live import Listener  # the continuous receiver
from modem import LEVELS, build_ack, build_beacon, build_frame, native, receive  # speed levels, transmitters, the compiled library, the receiver
from modem.frame import (  # the frame's shape and its header reader
    END_TONES, FRAME_TONES, HEADER_SYMBOLS_ONCE, _end_header, _header_bits, _read_header_how, body_layout, frame_seconds, from_end,  # (continued)
)  # end of the import list
from modem.mfsk import pilot_frequency_fit  # the pilots' frequency and drift fit
from modem.params import FS, HEADER_END_MARK, PREAMBLE_TONES  # sample rate, the second header copy's mark, tones in a pattern
from sim import run_channel  # the channel simulator

TEXT = "Q1AAAA DE Q2BB SPREAD SYNC TEST"  # a short message (made-up callsigns)
LEAD = FS  # a second of quiet before each frame


def _framed(audio, noise=0.01, seed=1):  # a frame with quiet either side and a little noise
    """Return `audio` with a second of quiet before and after, in light noise."""
    rng = np.random.default_rng(seed)  # repeatable noise
    return np.concatenate([np.zeros(LEAD), audio, np.zeros(LEAD)]) + rng.standard_normal(len(audio) + 2 * LEAD) * noise  # the recording


def _spans(level, size_class=0):  # where each piece of a message frame lies
    """Return a dict of (first sample, last sample + 1) for the pieces of a message frame at `level`."""
    tone = LEVELS[level].samples  # one tone, in samples
    body = body_layout(size_class)["total"]  # body tones
    edges = np.cumsum([0, PREAMBLE_TONES, HEADER_SYMBOLS_ONCE, body, PREAMBLE_TONES, HEADER_SYMBOLS_ONCE]) * tone  # where each piece starts
    names = ("pattern1", "header1", "body", "pattern2", "header2")  # the five pieces, in sending order
    return {name: (int(edges[i]), int(edges[i + 1])) for i, name in enumerate(names)}  # each piece's stretch


def _without(audio, spans, *names):  # a frame with some pieces faded right out
    """Return a copy of `audio` with the named pieces silenced."""
    out = audio.copy()  # not the caller's
    for name in names:  # each piece to lose
        first, last = spans[name]  # its stretch
        out[first:last] = 0.0  # gone
    return out  # the damaged frame


def test_a_frame_has_a_pattern_and_a_header_at_each_end():  # the layout itself
    assert FRAME_TONES == 48 and END_TONES == 24  # twelve pattern tones and twelve header tones at each end
    for level in range(len(LEVELS)):  # every speed level
        audio = build_frame(TEXT, level)  # a message frame
        assert len(audio) == (FRAME_TONES + body_layout(0)["total"]) * LEVELS[level].samples  # the body plus both ends
        assert abs(len(audio) / FS - frame_seconds(0, level)) < 1e-9  # as long as the airtime sum says
    spans, tone = _spans(2), LEVELS[2].samples  # an L2 frame's pieces
    audio = build_frame(TEXT, 2)  # the frame
    a, b = audio[slice(*spans["pattern1"])], audio[slice(*spans["pattern2"])]  # its two patterns
    middle = slice(tone // 4, -tone // 4)  # away from the ends (the frame fades in, and the tone before each pattern differs)
    spectrum = lambda piece: np.abs(np.fft.rfft(piece.reshape(PREAMBLE_TONES, tone)[:, middle], axis=1)).argmax(axis=1)  # the strongest frequency in each tone
    assert np.array_equal(spectrum(a), spectrum(b))  # the same twelve tones at both ends


def test_second_header_copy_is_the_first_with_its_check_value_marked():  # how a receiver tells the ends apart
    header = _header_bits(0, 2, 1, 0, 1, False)  # any header
    marked = _end_header(header)  # as the second copy carries it
    assert np.array_equal(marked[:16], header[:16])  # the same fields
    assert int("".join(str(int(b)) for b in (marked[16:] ^ header[16:])), 2) == HEADER_END_MARK  # the check value differs by exactly the mark
    assert not np.array_equal(marked, header)  # so the two copies can never be mistaken for one another


@pytest.mark.parametrize("level", range(len(LEVELS)))  # every speed level
def test_frame_is_read_whichever_end_fades_away(level):  # the point of the second pattern
    spans, audio = _spans(level), build_frame(TEXT, level)  # a frame and where its pieces lie
    cases = {  # which pieces are lost -> how the header must have been read
        (): ("first", "end"),  # nothing lost: from whichever pattern stood out more
        ("pattern1",): ("end",),  # the first pattern gone: found from the second
        ("pattern1", "header1"): ("end",),  # the whole front end gone
        ("pattern2",): ("first",),  # the second pattern gone: found from the first, as before 0.43
        ("pattern2", "header2"): ("first",),  # the whole back end gone
        ("pattern1", "header2"): ("end both", "end first"),  # found from the second pattern, its header copy lost: the first copy, found a body earlier (alone, or added to the noise where the lost copy was)
        ("header1", "pattern2"): ("both", "second"),  # found from the first pattern, its header copy lost: the second copy, found a body later
    }  # end of the cases
    for lost, hows in cases.items():  # each
        result = receive(_framed(_without(audio, spans, *lost)), long_beacons=False)  # decode what is left
        assert result.ok and result.text == TEXT, (level, lost, result.reason)  # the message is read
        assert result.header_copy in hows, (level, lost, result.header_copy)  # the way expected
        assert abs(result.start - LEAD) < LEVELS[level].samples / 8, (level, lost, result.start)  # and the frame is placed where it began, whichever end it was found from


def test_frame_with_neither_pattern_is_not_read():  # nothing to find it by
    spans, audio = _spans(2), build_frame(TEXT, 2)  # an L2 frame
    result = receive(_framed(_without(audio, spans, "pattern1", "pattern2")), long_beacons=False)  # both patterns gone
    assert not result.ok  # nothing decodes


def test_control_frames_are_found_from_their_end_too():  # beacons and acknowledgments
    from modem import ChannelReport  # a channel report for the acknowledgment
    for level in (0, 2, 4):  # slow, middle and fast
        tone = LEVELS[level].samples  # one tone
        beacon = build_beacon("Q1AAAA", "EM93", level=level)  # a beacon
        beacon[:(PREAMBLE_TONES + HEADER_SYMBOLS_ONCE) * tone] = 0.0  # its whole front end lost
        result = receive(_framed(beacon), long_beacons=False)  # decode it
        assert result.ok and result.origin == "Q1AAAA" and from_end(result.header_copy), (level, result.reason)  # read from its end
        ack = build_ack(77, 1234, 2, 0, ChannelReport(-9.0, 0.5, 2.0, 1), level=level)  # an acknowledgment
        ack[:PREAMBLE_TONES * tone] = 0.0  # its first pattern lost
        result = receive(_framed(ack), long_beacons=False)  # decode it
        assert result.ok and (result.link, result.msg_id, result.part) == (77, 1234, 2) and from_end(result.header_copy), (level, result.reason)  # read from its end


def test_weak_frame_found_from_its_end_in_noise():  # at the level's working SNR, not just on a clean path
    spans, audio = _spans(0), build_frame(TEXT, 0)  # an L0 frame
    damaged = _without(audio, spans, "pattern1", "header1")  # its front end faded out
    heard = run_channel(damaged, -17.0, np.random.default_rng(5), offset_hz=3.0)  # 17 dB below the noise and 3 Hz off frequency
    result = receive(heard, long_beacons=False)  # decode it
    assert result.ok and result.text == TEXT and from_end(result.header_copy)  # read from its end
    assert abs(result.offset_hz - 3.0) < 0.5  # with the mistuning measured


def test_drifting_frame_found_from_its_end_is_tracked_backwards():  # the frequency is measured at the end and followed back
    spans, audio = _spans(0, 1), build_frame("DRIFT " * 15, 0)  # a 148-second L0 frame
    damaged = _without(audio, spans, "pattern1", "header1")  # found from its end only
    heard = run_channel(damaged, -10.0, np.random.default_rng(6), offset_hz=-4.0, drift_hz_s=0.012)  # drifting 1.8 Hz over the frame: more than the half-bin reach of one tracking step
    result = receive(heard, long_beacons=False)  # decode it
    assert result.ok and from_end(result.header_copy)  # read from its end
    assert abs(result.drift_hz_s - 0.012) < 0.003  # the pilots measured the drift
    assert abs(result.offset_hz - (-4.0 + 0.012 * (PREAMBLE_TONES + HEADER_SYMBOLS_ONCE) * LEVELS[0].seconds)) < 0.6  # and the frequency where the body starts


def test_pilot_fit_backwards_agrees_with_forwards_on_a_steady_signal():  # the same pilots either way
    layout, spec = body_layout(0), LEVELS[1]  # an L1 body
    audio = _framed(build_frame(TEXT, 1), noise=0.05, seed=3)  # a frame in some noise
    body = LEAD + (PREAMBLE_TONES + HEADER_SYMBOLS_ONCE) * spec.samples  # where its body starts
    forward = pilot_frequency_fit(audio, body, layout["pilot_pos"], layout["pilot_tones"], spec, 0.7)  # followed from the start
    backward = pilot_frequency_fit(audio, body, layout["pilot_pos"], layout["pilot_tones"], spec, 0.7, backward=True)  # and from the end
    assert abs(forward[0] - backward[0]) < 0.3 and abs(forward[0] + 0.7) < 0.3  # both find the 0.7 Hz given in error
    assert abs(forward[1]) < 0.02 and abs(backward[1]) < 0.02  # and no drift to speak of


def test_compiled_header_reader_and_pilot_fit_match_python(monkeypatch):  # the library against the reference, for the new cases
    if not native.available():  # no library on this computer
        pytest.skip("the compiled library is not built")  # nothing to compare
    spans, audio = _spans(3), build_frame(TEXT, 3)  # an L3 frame
    spec, tone = LEVELS[3], LEVELS[3].samples  # its level
    cases = [(), ("header1",), ("header2",), ("pattern1", "header2"), ("header1", "header2")]  # which pieces are lost
    places = [LEAD + spans["header1"][0], LEAD + spans["header2"][0]]  # the header copy after each pattern
    layout = body_layout(0)  # the body's shape
    for lost in cases:  # each damaged frame
        x = _framed(_without(audio, spans, *lost), seed=11)  # the recording
        for place in places:  # read from each end
            compiled = _read_header_how(x, place, 0.0, spec)  # with the library
            fit_c = pilot_frequency_fit(x, LEAD + spans["body"][0], layout["pilot_pos"], layout["pilot_tones"], spec, 0.4, backward=True)  # the backward fit, compiled
            with monkeypatch.context() as patch:  # the library switched off
                patch.setattr(native, "_lib", None)  # pure Python
                reference = _read_header_how(x, place, 0.0, spec)  # the reference
                fit_p = pilot_frequency_fit(x, LEAD + spans["body"][0], layout["pilot_pos"], layout["pilot_tones"], spec, 0.4, backward=True)  # the backward fit, in Python
            assert compiled[1] == reference[1], (lost, place, compiled[1], reference[1])  # the same copy
            assert (compiled[0] is None) == (reference[0] is None) and (compiled[0] is None or np.array_equal(compiled[0], reference[0]))  # and the same bits
            assert np.allclose(fit_c, fit_p, atol=1e-9)  # the same fit, to rounding
    assert tone > 0  # (keeps the level's tone length in view for anyone reading the cases)


@pytest.mark.parametrize("compiled", [False, True])  # the Python listener and the library's
def test_continuous_receiver_hears_a_frame_whose_first_pattern_faded(compiled):  # the live receiver
    if compiled and not native.available():  # no library on this computer
        pytest.skip("the compiled library is not built")  # nothing to test
    rng = np.random.default_rng(21)  # repeatable noise
    spans, frame = _spans(2), build_frame(TEXT, 2)  # an L2 frame
    damaged = _without(frame, spans, "pattern1", "header1")  # its front end faded out
    audio = rng.standard_normal(45 * FS) * 0.02  # forty-five seconds of noise
    at = 4 * FS  # where the frame begins
    audio[at:at + len(damaged)] += damaged * 0.1  # the frame, well above the noise
    listener, found = Listener(compiled=compiled), []  # a receiver and what it hears
    for begin in range(0, len(audio), FS):  # a second at a time, as it would arrive
        found += listener.feed(audio[begin:begin + FS])  # fed
    assert [heard.result.ok for heard in found] == [True]  # heard once
    result = found[0].result  # the frame
    assert result.text == TEXT and from_end(result.header_copy)  # read from its end
    assert abs(result.sample - at) <= LEVELS[2].samples // 8  # and numbered from where the frame began, not from the pattern that found it
    assert len(found[0].audio) >= len(frame)  # with the whole frame's audio handed over


@pytest.mark.parametrize("compiled", [False, True])  # the Python listener and the library's
def test_clean_frame_is_heard_once_though_both_patterns_are_found(compiled):  # two patterns, one frame
    if compiled and not native.available():  # no library on this computer
        pytest.skip("the compiled library is not built")  # nothing to test
    rng = np.random.default_rng(22)  # repeatable noise
    frame = build_frame(TEXT, 3)  # an L3 frame
    audio = rng.standard_normal(30 * FS) * 0.02  # thirty seconds of noise
    for at in (3 * FS, 16 * FS):  # two frames
        audio[at:at + len(frame)] += frame * 0.1  # each well above the noise
    listener, found = Listener(compiled=compiled), []  # a receiver and what it hears
    for begin in range(0, len(audio), FS):  # a second at a time
        found += listener.feed(audio[begin:begin + FS])  # fed
    assert [heard.result.ok for heard in found] == [True, True]  # each frame once, neither twice


@pytest.mark.parametrize("compiled", [False, True])  # the Python listener and the library's
def test_frame_that_fails_its_check_is_handed_over_once(compiled):  # found from both ends, failing both times
    if compiled and not native.available():  # no library on this computer
        pytest.skip("the compiled library is not built")  # nothing to test
    rng = np.random.default_rng(23)  # repeatable noise
    spans, frame = _spans(2), build_frame(TEXT, 2)  # an L2 frame
    first, last = spans["body"]  # its body
    damaged = frame.copy()  # to be spoiled
    damaged[first + (last - first) // 4:first + 3 * (last - first) // 4] = 0.0  # the middle half of the body lost: far too much to correct, though the pilots that remain read strong
    audio = rng.standard_normal(45 * FS) * 0.02  # forty-five seconds of noise
    audio[4 * FS:4 * FS + len(damaged)] += damaged * 0.1  # the frame
    listener, found = Listener(compiled=compiled), []  # a receiver and what it hears
    for begin in range(0, len(audio), FS):  # a second at a time
        found += listener.feed(audio[begin:begin + FS])  # fed
    assert len(found) == 1 and not found[0].result.ok and found[0].result.reason == "body check failed"  # handed to the station once, for adding to a retry, not once per pattern


def test_station_takes_the_continuous_receivers_decode_as_read():  # no second decode from scratch (since 0.43)
    from link import Station  # a station's link rules
    station = Station("Q2BB", "EM93")  # the receiving station
    frame = build_frame(TEXT, 2)  # a frame
    decoded = receive(_framed(frame), long_beacons=False)  # as the continuous receiver read it
    assert decoded.ok  # read
    silence = np.zeros(FS)  # audio in which nothing could be found again
    assert station.hear(silence, decoded, 0.0) is decoded  # its report stands, and the audio is not searched a second time


def test_station_adds_a_retry_to_a_failed_frame_where_the_receiver_found_it():  # combining, without searching the clip afresh
    from link import Station  # a station's link rules
    from modem.levels import LEVELS as levels  # the speed levels
    station = Station("Q2BB", "EM93")  # the receiving station
    frame = build_frame("RETRIES ADD UP " * 6, 2, link=5, msg_id=9)  # a 90-character message frame at L2
    spec = levels[2]  # its level
    tries, results = [], []  # the copies as received, and the station's verdicts
    for seed in (31, 32, 33, 34):  # up to four copies, each too weak to read alone
        heard = run_channel(frame, -17.5, np.random.default_rng(seed))  # 3.5 dB below the level's limit
        start = float(FS)  # the channel puts the frame a second in
        decoded = receive(heard, long_beacons=False, candidates=[({"start": start, "offset_hz": 0.0, "quality": 1.0}, spec)])  # the continuous receiver's own try, at the place it found the frame
        tries.append(decoded.ok)  # whether it read alone
        results.append(station.hear(heard, decoded, start))  # the station's verdict, with any kept copy added
        if results[-1].ok:  # read
            break  # no more copies needed
    assert not any(tries)  # no copy read alone
    assert results[-1].ok and results[-1].text == "RETRIES ADD UP " * 6  # but the copies added together did
    assert 2 <= len(results) <= 4  # after a retry or three


def test_heard_frame_says_where_it_begins_in_its_audio():  # so the station can read it again there
    rng = np.random.default_rng(24)  # repeatable noise
    frame = build_frame(TEXT, 3)  # an L3 frame
    audio = rng.standard_normal(20 * FS) * 0.02  # twenty seconds of noise
    audio[5 * FS:5 * FS + len(frame)] += frame * 0.1  # the frame
    listener, found = Listener(), []  # a receiver and what it hears
    for begin in range(0, len(audio), FS):  # a second at a time
        found += listener.feed(audio[begin:begin + FS])  # fed
    assert len(found) == 1 and found[0].result.ok  # heard once
    heard = found[0]  # the frame
    assert abs(heard.start - 0.5 * FS) < LEVELS[3].samples / 8  # half a second into its audio, as the listener pads it
    again = receive(heard.audio, long_beacons=False, candidates=[({"start": heard.start, "offset_hz": heard.result.offset_hz, "quality": 1.0}, LEVELS[3])])  # read again there
    assert again.ok and again.text == TEXT  # the same frame
