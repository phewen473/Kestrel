"""Whole-system tests: a message goes in, crosses the simulated channel, and must come out unchanged."""

import numpy as np  # numerical arrays

from modem import LEVELS, MIN_SNR_DB, build_frame, build_plan, frame_seconds, join_parts, pick_level, plan_message, receive  # transmitter, receiver, levels and planner
from modem.params import FS  # audio sample rate
from sim import run_channel  # channel simulator
from sim.channel import add_crashes  # static-crash generator

SHORT = "KO4WSC: net at 0100Z confirmed.\tBring list\n"  # a 50-class message with control characters
LONG = "".join(chr(32 + (7 * i) % 95) for i in range(200))  # a full 200-character message


def _send(text, snr_db, seed, **channel):  # helper: transmit and receive once
    """Send `text` through the channel and return the receiver's report."""
    return receive(run_channel(build_frame(text), snr_db, np.random.default_rng(seed), **channel))  # build, transmit, decode


def test_frame_lengths_match_the_design():  # airtime of each size class
    assert abs(len(build_frame(SHORT)) / FS - frame_seconds(0)) < 1e-9  # the audio is exactly as long as predicted
    assert [round(frame_seconds(c)) for c in range(4)] == [76, 136, 195, 255]  # L0: about 1, 2, 3 and 4 minutes
    assert frame_seconds(3, 2) <= 60 and frame_seconds(3, 1) <= 90  # 200 characters fit the 60 s cap at L2 and the 90 s cap at L1


def test_clean_channel():  # no noise at all
    result = _send(SHORT, None, 1)  # perfect channel
    assert result.ok and result.text == SHORT  # the exact message comes back
    assert result.level == 0 and result.size_class == 0  # the header was read correctly
    assert abs(result.start - FS) < 1  # the frame was found at the 1-second mark


def test_noise_with_frequency_offset():  # 14 dB below the noise and 12 Hz off frequency
    result = _send(SHORT, -14.0, 2, offset_hz=12.0)  # noisy, mistuned channel
    assert result.ok and result.text == SHORT  # the exact message comes back
    assert abs(result.offset_hz - 12.0) < 0.5  # the receiver measured the mistuning
    assert abs(result.snr_db + 14.0) < 1.5  # the receiver's own SNR reading is about right


def test_weak_signal_near_the_design_target():  # 20 dB below the noise
    result = _send(SHORT, -20.0, 3, offset_hz=-6.0)  # very weak signal
    assert result.ok and result.text == SHORT  # the exact message comes back


def test_full_length_message_with_drift():  # 200 characters while the frequency drifts
    result = _send(LONG, -14.0, 4, offset_hz=-8.0, drift_hz_s=0.01)  # drifts 2.5 Hz over the 4-minute frame
    assert result.ok and result.text == LONG  # the exact message comes back
    assert result.size_class == 3  # the header announced the 200-character size
    assert abs(result.drift_hz_s - 0.01) < 0.003  # the pilots measured the drift


def test_moderate_fading():  # ITU-R F.1487 mid-latitude moderate: 0.5 Hz spread, 1 ms delay
    result = _send(SHORT, -6.0, 5, condition="moderate", offset_hz=3.0)  # fading, multipath and noise together
    assert result.ok and result.text == SHORT  # the exact message comes back


def test_static_crashes_need_the_blanker():  # heavy static: the blanker makes the difference
    rng = np.random.default_rng(6)  # repeatable random source
    heard = run_channel(build_frame(SHORT), -15.0, rng)  # noisy channel
    heard = add_crashes(heard, 10.0, 0.5, rng, level_db=50.0)  # ten very loud crashes every second
    assert not receive(heard, blank=False).ok  # without the blanker the frame is lost
    result = receive(heard, blank=True)  # with the blanker...
    assert result.ok and result.text == SHORT  # ...the exact message comes back


def test_two_failed_copies_combine_into_a_good_one():  # the "combine retries" feature (HARQ)
    first = _send(SHORT, -23.3, 211)  # first copy: too weak to decode by itself
    second_alone = _send(SHORT, -23.3, 311)  # second copy: also too weak by itself
    assert not first.ok and not second_alone.ok  # neither copy decodes alone
    assert first.body_llrs is not None  # but the first copy's soft bits were kept
    heard = run_channel(build_frame(SHORT), -23.3, np.random.default_rng(311))  # the same second copy again
    combined = receive(heard, prior_llrs=first.body_llrs)  # decode it together with the first copy
    assert combined.ok and combined.text == SHORT  # together they decode


def test_noise_alone_is_rejected():  # no signal: the receiver must not invent a message
    noise = np.random.default_rng(8).standard_normal(30 * FS)  # 30 seconds of pure noise
    assert not receive(noise).ok  # nothing decodes


def test_every_level_decodes_and_announces_itself():  # the receiver is never told the level
    for spec in LEVELS:  # one speed level at a time
        heard = run_channel(build_frame(LONG, spec.number), MIN_SNR_DB[spec.number] + 3.0, np.random.default_rng(20 + spec.number), offset_hz=7.0)  # 3 dB above the level's limit
        result = receive(heard)  # decode without saying which level was used
        assert result.ok and result.text == LONG  # the exact message comes back
        assert result.level == spec.number  # and the receiver worked out the level by itself


def test_fast_level_through_fading():  # a faster level on a fading path with a good signal
    result = receive(run_channel(build_frame(SHORT, 3), 0.0, np.random.default_rng(31), "moderate"))  # L3, moderate fading, 0 dB
    assert result.ok and result.text == SHORT and result.level == 3  # the exact message comes back at L3


def test_level_choice_follows_the_signal():  # rule 1: fastest level the conditions support
    assert pick_level(10.0) == LEVELS[-1].number  # a strong signal gets the fastest level
    assert pick_level(-30.0) == 0  # a hopeless signal falls back to the slowest
    for spec in LEVELS:  # exactly at each level's limit plus the margin...
        assert pick_level(MIN_SNR_DB[spec.number] + 2.0) == spec.number  # ...that level is chosen


def test_plan_respects_the_airtime_limits():  # rules 2 to 4
    strong = plan_message(LONG, MIN_SNR_DB[2] + 2.0)  # conditions good enough for L2
    assert len(strong) == 1 and strong[0]["seconds"] <= 60 and not strong[0]["extended"]  # one frame inside the 60-second cap
    poor = plan_message(LONG, MIN_SNR_DB[1] + 2.0)  # conditions only good enough for L1
    assert len(poor) == 1 and 60 < poor[0]["seconds"] <= 90 and poor[0]["extended"]  # one frame using the 90-second allowance
    weak = plan_message(LONG, MIN_SNR_DB[0] + 2.0)  # conditions only good enough for L0
    assert len(weak) == 4 and all(item["seconds"] <= 90 for item in weak)  # split into four parts, each inside 90 seconds
    assert "".join(item["text"] for item in weak) == LONG  # the parts together are the whole message
    assert len(plan_message(SHORT, MIN_SNR_DB[0] + 2.0)) == 1  # a short message still goes whole at L0


def test_split_message_is_reassembled():  # a 200-character message at L0, sent as four parts
    plan = plan_message(LONG, -18.0)  # weak signal: the planner chooses L0 and splits
    reports = []  # what the receiver makes of each part
    for i, audio in enumerate(build_plan(plan)):  # send the parts one after another
        reports.append(receive(run_channel(audio, -18.0, np.random.default_rng(40 + i))))  # each through its own noisy channel
    assert [r.part for r in reports] == [0, 1, 2, 3] and all(r.parts == 4 for r in reports)  # every part knows its place
    assert join_parts(reports[:3]) is None  # with one part missing there is no message yet
    assert join_parts(reports) == LONG  # with all four the message is whole again


def test_compressed_message_end_to_end():  # compression lets a longer text ride in a smaller frame
    english = "arrived safe, will call sunday after church. love to all"  # 56 characters: too long for the smallest frame unless compressed
    result = _send(english, -19.0, 50)  # weak signal, noise only
    assert result.ok and result.text == english  # the exact message comes back
    assert result.compressed and result.size_class == 0  # it travelled compressed in the smallest frame


def test_compression_reduces_the_number_of_parts():  # splitting packs more text into each part when it compresses
    english = "Net at 0100Z confirmed. Bring the 40 m list and check in on 7.110 if the band is open. Weather here is clear and cold tonight, wind light from the north."  # 153 characters
    plan = plan_message(english, MIN_SNR_DB[0] + 2.0)  # conditions only good enough for L0
    assert len(plan) == 3  # three parts instead of the four that plain 50-character pieces would need
    assert "".join(item["text"] for item in plan) == english  # nothing lost in the cutting
