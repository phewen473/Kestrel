"""Tests of the frame strip (since 0.37): the listener's progress reports, and what the strip shows."""

import numpy as np  # numerical arrays
import pytest  # both listeners

from live import Listener  # the continuous receiver
from live.framestrip import FrameStrip, cut_point  # what the strip shows
from modem import build_frame, native  # frames, and the compiled library
from modem.params import FS  # audio sample rate


def feed_all(listener, audio, step=2400):  # feed a recording in sound-card-sized pieces
    """Feed `audio` to `listener` and return every progress report it made."""
    reports = []  # what it reported
    listener.on_progress = reports.append  # kept
    for i in range(0, len(audio), step):  # a fifth of a second at a time
        listener.feed(audio[i:i + step])  # in
    return reports  # all of them


COMPILED = [False] + ([True] if native.available() else [])  # the Python listener always; the compiled one when the library is here


@pytest.mark.parametrize("compiled", COMPILED)  # both listeners
def test_a_frame_is_followed_as_it_arrives(compiled):  # preamble, header, body as it comes, then the outcome
    rng = np.random.default_rng(3701)  # repeatable random source
    frame = build_frame("The frame strip follows this message as it arrives.", 2, link=9, msg_id=4, part=1, parts=3)  # part 2 of 3 at L2
    audio = np.concatenate([np.zeros(2 * FS), frame, np.zeros(3 * FS)])  # with quiet either side
    audio = audio + 0.05 * rng.standard_normal(len(audio))  # and noise
    listener = Listener(compiled=compiled)  # the receiver
    reports = feed_all(listener, audio)  # what it said along the way
    seen = [f for r in reports for f in r["frames"]]  # every frame shown while arriving
    assert seen, "the frame was never shown while it arrived"  # it was
    with_header = [f for f in seen if f["header"] is not None]  # once its header was read
    assert with_header and with_header[0]["arrived_s"] < with_header[0]["total_s"] - 5.0  # read well before the frame ended
    h = with_header[0]["header"]  # its fields
    assert (h["frame_type"], h["part"], h["parts"], h["how"]) == (0, 1, 3, "first")  # as sent, read from the first copy
    growth = [len(f["clarity"]) for f in with_header]  # body tones measured, report by report
    assert growth == sorted(growth) and growth[-1] > growth[0]  # measured as they came
    assert np.median(with_header[-1]["clarity"]) > 6.0  # a clean signal: the tones stood out clearly
    outcomes = [o for r in reports for o in r["outcomes"]]  # finished frames
    assert len(outcomes) == 1 and outcomes[0]["ok"] and (outcomes[0]["part"], outcomes[0]["parts"]) == (1, 3)  # decoded, once
    assert abs(outcomes[0]["stream"] - with_header[0]["stream"]) < FS // 10  # the same frame


def test_noise_shows_nothing():  # chance matches in noise are not shown
    rng = np.random.default_rng(3702)  # repeatable random source
    reports = feed_all(Listener(), rng.standard_normal(40 * FS), step=6000)  # forty seconds of noise
    assert not any(r["frames"] or r["outcomes"] for r in reports)  # nothing shown


class Clock:  # a stand-in clock
    def __init__(self):  # starts at zero
        self.t = 0.0  # seconds

    def __call__(self):  # read it
        return self.t  # now


def arriving(stream, part, parts, arrived, clarity=(), header=True):  # a progress report with one frame arriving
    """Return a progress report for a 47-second L2 message frame at `stream`, `arrived` seconds in."""
    head = {"frame_type": 0, "size_class": 2, "part": part, "parts": parts, "compressed": False, "how": "first"} if header else None  # its header
    return {"now": stream + int(arrived * FS), "outcomes": [], "frames": [{"stream": stream, "level": 2, "long": False, "offset_hz": 3.0, "quality": 1.0, "tone_s": 0.09,  # (continued)
                                                                           "arrived_s": arrived, "total_s": 47.0 if header else None, "header": head, "tried": False, "body_tones": 471 if header else None, "clarity": list(clarity)}]}  # the frame


def finished(stream, part, parts, ok, reason=""):  # a progress report with one frame finished
    """Return a progress report whose only news is the frame at `stream` finishing."""
    return {"now": stream, "frames": [], "outcomes": [{"stream": stream, "ok": ok, "reason": reason, "level": 2, "frame_type": 0, "part": part, "parts": parts, "snr_db": 5.0, "header_copy": "first"}]}  # the outcome


def test_strip_stages_and_parts():  # arriving, received, failed, missing, complete
    clock = Clock()  # time stands still unless moved
    strip = FrameStrip(clock=clock)  # the strip
    assert strip.view()["title"].startswith("Listening")  # nothing yet
    strip.update(arriving(100000, 0, 4, 2.0, header=False))  # part 1: preamble in, header arriving
    v = strip.view()  # what it shows
    assert v["segs"][:3] == ["good", "now", "unknown"] and v["header_fill"] > 0  # the preamble in, the header filling, the body's length unknown
    strip.update(arriving(100000, 0, 4, 20.0, clarity=[9.0] * 150 + [1.0] * 10))  # the body arriving, a short fade
    v = strip.view()  # what it shows
    assert v["segs"][:3] == ["good", "good", "now"] and "part 1 of 4" in v["title"] and "10 tones lost" in v["notes"][2]  # said
    strip.update(finished(100000, 0, 4, True))  # part 1 decoded
    assert strip.view()["parts"] == ["good", "wait", "wait", "wait"]  # one of four
    strip.update(arriving(900000, 2, 4, 30.0, clarity=[9.0] * 200))  # part 3 (part 2 was never heard)
    strip.update(finished(900000, 2, 4, True))  # decoded
    v = strip.view()  # what it shows
    assert v["parts"] == ["good", "missing", "good", "wait"] and "Part 2 not heard" in v["done"]  # the gap shown
    strip.update(arriving(1700000, 3, 4, 30.0, clarity=[9.0] * 200 + [0.5] * 271))  # part 4: the signal goes half way through
    strip.update(finished(1700000, 3, 4, False, "body check failed"))  # failed
    v = strip.view()  # what it shows
    assert v["segs"][2] == "cut" and 0.4 < v["progress"] < 0.45 and "stopped" in v["title"]  # shown cut off where the signal went
    assert v["parts"] == ["good", "missing", "good", "bad"]  # and the part failed
    clock.t = 1.0  # a moment later the station's own decode, with an earlier copy added, passes
    strip.update(arriving(2500000, 1, 4, 30.0, clarity=[9.0] * 200))  # part 2 at last
    strip.update(finished(2500000, 1, 4, True))  # decoded
    strip.update(arriving(3300000, 3, 4, 30.0, clarity=[9.0] * 200))  # part 4 again
    strip.update(finished(3300000, 3, 4, True))  # decoded
    v = strip.view()  # what it shows
    assert v["parts"] == ["good"] * 4 and v["done"].startswith("Message complete")  # all in


def test_unreadable_header_and_cut_point():  # a signature whose header was never read; where a signal went
    strip = FrameStrip(clock=Clock())  # the strip
    strip.update({"now": 0, "frames": [], "outcomes": [{"stream": 5000, "ok": False, "reason": "header unreadable", "level": -1, "frame_type": -1, "part": 0, "parts": 1, "snr_db": None, "header_copy": ""}]})  # a near miss
    v = strip.view()  # what it shows
    assert v["segs"] == ["good", "bad", "unknown", "bad"] and "near miss" in v["done"]  # lost, and said where it is listed
    assert cut_point([9.0] * 80 + [1.0] * 20) == 0.8 and cut_point([9.0] * 95 + [1.0] * 5) is None  # a long lost tail is a cut; a short one is a fade


@pytest.mark.parametrize("compiled", COMPILED)  # both listeners
def test_frame_found_from_its_second_pattern_is_reported_where_it_began(compiled):  # the strip and the pattern at the frame's end (since 0.43)
    from modem.frame import HEADER_SYMBOLS_ONCE  # tones in one header copy
    from modem.levels import LEVELS  # tone lengths
    from modem.params import PREAMBLE_TONES  # tones in a pattern
    rng = np.random.default_rng(3703)  # repeatable random source
    frame = build_frame("Found from the far end.", 2, link=9, msg_id=5)  # a frame at L2
    frame[:(PREAMBLE_TONES + HEADER_SYMBOLS_ONCE) * LEVELS[2].samples] = 0.0  # its first pattern and header copy faded right out
    audio = np.concatenate([np.zeros(2 * FS), frame, np.zeros(3 * FS)])  # with quiet either side
    audio = audio + 0.05 * rng.standard_normal(len(audio))  # and noise
    reports = feed_all(Listener(compiled=compiled), audio)  # what the receiver said along the way
    outcomes = [o for r in reports for o in r["outcomes"]]  # finished frames
    assert len(outcomes) == 1 and outcomes[0]["ok"]  # decoded, once
    assert outcomes[0]["header_copy"].startswith("end")  # from its second pattern
    assert abs(outcomes[0]["stream"] - 2 * FS) < LEVELS[2].samples  # and placed where the frame began, two seconds in, not where its second pattern was
    strip = FrameStrip()  # the strip itself
    for report in reports:  # everything the receiver said
        strip.update(report)  # taken in
    view = strip.view()  # what it shows at the end
    assert "received" in view["title"] and view["segs"][0] == "fair" and view["segs"][2] == "good"  # received; the first pattern shown as weak, the body as passed
    assert "second pattern" in view["notes"][0]  # and it says how the frame was found


@pytest.mark.parametrize("compiled", COMPILED)  # both listeners
def test_second_pattern_is_not_shown_as_a_new_frame(compiled):  # one frame, one entry in the strip
    rng = np.random.default_rng(3704)  # repeatable random source
    frame = build_frame("One frame, though its pattern is heard twice.", 2, link=9, msg_id=6)  # a frame at L2
    audio = np.concatenate([np.zeros(2 * FS), frame, np.zeros(3 * FS)])  # with quiet either side
    audio = audio + 0.05 * rng.standard_normal(len(audio))  # and noise
    reports = feed_all(Listener(compiled=compiled), audio)  # what the receiver said along the way
    assert all(len(r["frames"]) <= 1 for r in reports)  # never two frames at once
    starts = {f["stream"] for r in reports for f in r["frames"]}  # where the frames shown began
    assert starts and max(starts) - min(starts) < FS // 10  # always the same frame, at its start
