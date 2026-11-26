"""Whole-system tests: a message goes in, crosses the simulated channel, and must come out unchanged."""

import numpy as np  # numerical arrays

from modem import ACK_HAVE_IT, ChannelReport, build_ack, build_answer, build_beacon, build_ident, control_seconds  # control frames
from modem import (  # transmitter, receiver, levels and planner
    LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB, build_frame, build_plan, frame_seconds, is_fading, join_parts, link_id, pick_level, plan_message, receive,  # (continued)
)  # end of the import list
from modem.params import AIRTIME_CAP_S, AIRTIME_POOR_CAP_S, FS  # the airtime limits and the audio sample rate
from sim import run_channel  # channel simulator
from sim.channel import add_crashes  # static-crash generator

SHORT = "Q1AAAA: net at 0100Z confirmed.\tBring list\n"  # a 50-class message with control characters
LONG = "".join(chr(32 + (7 * i) % 95) for i in range(200))  # a full 200-character message


def _send(text, snr_db, seed, **channel):  # helper: transmit and receive once
    """Send `text` through the channel and return the receiver's report."""
    return receive(run_channel(build_frame(text), snr_db, np.random.default_rng(seed), **channel))  # build, transmit, decode


def test_frame_lengths_match_the_design():  # airtime of each size class
    assert abs(len(build_frame(SHORT)) / FS - frame_seconds(0)) < 1e-9  # the audio is exactly as long as predicted
    assert [round(frame_seconds(c)) for c in range(4)] == [88, 148, 208, 267]  # L0: about 1.5, 2.5, 3.5 and 4.5 minutes (4.8 s more than before 0.43: the second pattern)
    assert [round(frame_seconds(c, 4), 2) for c in range(4)] == [4.95, 8.32, 11.68, 15.03]  # L4: the same frames in a few seconds
    assert frame_seconds(3, 2) <= AIRTIME_CAP_S and frame_seconds(3, 1) <= AIRTIME_POOR_CAP_S  # 200 characters fit the usual cap at L2 (61 s since 0.43) and the poor-conditions cap at L1 (91 s)


def test_clean_channel():  # no noise at all
    result = _send(SHORT, None, 1)  # perfect channel
    assert result.ok and result.text == SHORT  # the exact message comes back
    assert result.level == 0 and result.size_class == 0  # the header was read correctly
    assert abs(result.start - FS) < 5  # the frame was found at the 1-second mark, to within a thousandth of a tone


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
    assert len(strong) == 1 and strong[0]["seconds"] <= AIRTIME_CAP_S and not strong[0]["extended"]  # one frame inside the usual cap
    poor = plan_message(LONG, MIN_SNR_DB[1] + 2.0)  # conditions only good enough for L1
    assert len(poor) == 1 and AIRTIME_CAP_S < poor[0]["seconds"] <= AIRTIME_POOR_CAP_S and poor[0]["extended"]  # one frame using the poor-conditions allowance
    weak = plan_message(LONG, MIN_SNR_DB[0] + 2.0)  # conditions only good enough for L0
    assert len(weak) == 4 and all(item["seconds"] <= AIRTIME_POOR_CAP_S for item in weak)  # split into four parts, each inside the allowance
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
    assert result.compressed and result.size_class == 0  # it traveled compressed in the smallest frame


def test_compression_reduces_the_number_of_parts():  # splitting packs more text into each part when it compresses
    english = "Net at 0100Z confirmed. Bring the 40 m list and check in on 7.110 if the band is open. Weather here is clear and cold tonight, wind light from the north."  # 153 characters
    plan = plan_message(english, MIN_SNR_DB[0] + 2.0)  # conditions only good enough for L0
    assert len(plan) == 3  # three parts instead of the four that plain 50-character pieces would need
    assert "".join(item["text"] for item in plan) == english  # nothing lost in the cutting


def test_receiver_tells_a_steady_signal_from_a_fading_one():  # the channel measurements the link will report back
    text = "Kestrel channel report test message, sixty characters long.."  # a message for the 100-character frame
    rng = np.random.default_rng(801)  # repeatable random source
    steady = receive(run_channel(build_frame(text, 1), -8.0, rng, offset_hz=6.0))  # noise only
    rng = np.random.default_rng(802)  # repeatable random source
    faded = receive(run_channel(build_frame(text, 1), -4.0, rng, "moderate", offset_hz=6.0))  # moderate fading
    assert steady.ok and faded.ok  # both decode
    assert abs(steady.snr_db - (-8.0)) < 1.0  # the SNR reading is close to the truth without fading...
    assert abs(faded.snr_db - (-4.0)) < 2.0  # ...and still close with it
    assert not is_fading(steady.fade_index)  # the steady signal is reported as steady
    assert is_fading(faded.fade_index)  # the fading signal is reported as fading
    assert is_fading(float("nan"))  # a missing reading is treated as fading, the safe choice


def test_fading_makes_the_level_choice_more_careful():  # fading-aware limits
    for snr_db in (-14.0, -10.0, -6.0, -2.0, 2.0):  # across the working range
        assert pick_level(snr_db, fading=True) <= pick_level(snr_db)  # fading never picks a faster level than a steady signal would
    assert pick_level(MIN_SNR_FADING_DB[4] + 2.0, fading=True) == 4  # the fastest level is still reached when the signal is strong enough
    assert pick_level(MIN_SNR_DB[4] + 2.0, fading=True) < 4  # but not at the noise-only limit
    steady = plan_message(LONG, -8.0)  # a 200-character message on a steady signal
    faded = plan_message(LONG, -8.0, fading=True)  # the same message and SNR on a fading signal
    assert sum(item["seconds"] for item in faded) > sum(item["seconds"] for item in steady)  # fading costs airtime


def test_link_frame_carries_link_and_message_numbers():  # frames between two locked stations
    link = link_id("Q1AAAA", "Q2BB")  # the pair's short link number
    rng = np.random.default_rng(901)  # repeatable random source
    heard = run_channel(build_frame(SHORT, 3, link=link, msg_id=4242, want_level=2), -6.0, rng, offset_hz=-5.0)  # send through noise
    result = receive(heard)  # decode
    assert result.ok and result.text == SHORT  # the text arrives
    assert (result.frame_type, result.link, result.msg_id, result.want_level) == (0, link, 4242, 2)  # and so do the frame type, link number, message number and wanted level
    assert 0 <= link < 512  # the link number is 9 bits
    assert link_id("Q2BB", "Q1AAAA") != link  # the number depends on who beaconed and who answered


def test_addressed_frame_carries_both_callsigns():  # frames with full addresses (unconnected traffic and held mail)
    rng = np.random.default_rng(902)  # repeatable random source
    audio = build_frame(SHORT, 2, dest="Q2BB", origin="q1aaaa/p", msg_id=65535, hops=2, life_hours=47)  # lower case and an odd lifetime on purpose
    result = receive(run_channel(audio, -8.0, rng, offset_hz=4.0))  # send through noise and decode
    assert result.ok and result.text == SHORT  # the text arrives
    assert (result.frame_type, result.dest, result.origin) == (1, "Q2BB", "Q1AAAA/P")  # addresses arrive in capitals
    assert (result.msg_id, result.hops, result.life_hours) == (65535, 2, 48)  # the lifetime is rounded up to a whole two-hour step
    assert len(audio) == len(build_frame(SHORT, 2))  # an addressed frame is no longer than a link frame of the same size


def test_long_addressed_message_is_split_and_rejoined():  # 200 characters that do not compress, with full addresses
    plan = plan_message(LONG, 10.0, addressed=True)  # a strong signal, so the fastest level
    assert len(plan) == 2 and all(item["seconds"] <= 60 for item in plan)  # it needs two frames, each within the limit
    heard = [receive(audio) for audio in build_plan(plan, dest="ALL", origin="Q1AAAA", msg_id=9)]  # send and decode every part
    assert join_parts(heard) == LONG  # the parts go back together
    stray = receive(build_frame(plan[1]["text"], plan[1]["level"], 1, 2, dest="ALL", origin="Q1AAAA", msg_id=10))  # the second part of a different message
    assert join_parts([heard[0], stray]) is None  # parts of different messages are never joined


def test_beacon_and_answer_through_noise():  # the two frames that start a contact
    rng = np.random.default_rng(1001)  # repeatable random source
    beacon = receive(run_channel(build_beacon("Q1AAAA", "EM92", mail_check=True), -19.0, rng, offset_hz=11.0))  # a beacon at the slowest level, near its limit
    assert beacon.ok and beacon.frame_type == 2 and beacon.level == 0  # it decodes and says what it is
    assert (beacon.origin, beacon.fields["grid"], beacon.fields["levels"]) == ("Q1AAAA", "EM92", (0, 1, 2, 3, 4))  # who, where, and what it can do
    assert beacon.fields["listening"] and beacon.fields["mail_check"] and not beacon.fields["holds_mail"]  # its flags
    report = ChannelReport(round(beacon.snr_db), beacon.fade_index, beacon.offset_hz, 1)  # what the listener measured, asking for level 1
    answer = receive(run_channel(build_answer("Q1AAAA", "Q2BB", report, level=1), -13.0, rng, offset_hz=-7.0))  # the answer comes back faster
    assert answer.ok and answer.frame_type == 3 and answer.level == 1  # it decodes at the level it was sent at
    assert (answer.dest, answer.origin) == ("Q1AAAA", "Q2BB")  # addressed to the beaconing station, from the answering one
    assert abs(answer.fields["report"].snr_db - (-19.0)) <= 2 and answer.fields["report"].want_level == 1  # the report of the beacon arrives
    assert abs(answer.fields["report"].offset_hz - 11.0) <= 2  # including the frequency error the listener saw


def test_acknowledgment_and_identification_at_every_level():  # the frames that run and close a link
    link = link_id("Q1AAAA", "Q2BB")  # the pair's link number
    for spec in LEVELS:  # each speed level in turn
        rng = np.random.default_rng(1100 + spec.number)  # repeatable random source
        snr_db = MIN_SNR_DB[spec.number] + 3.0  # a little above the level's limit
        report = ChannelReport(-5.0, 0.25, 4.0, spec.number)  # an arbitrary report
        ack = receive(run_channel(build_ack(link, 4242, 3, ACK_HAVE_IT, report, level=spec.number), snr_db, rng, offset_hz=5.0))  # send an acknowledgment
        assert ack.ok and ack.frame_type == 4 and ack.level == spec.number  # it decodes at its own level
        assert (ack.link, ack.msg_id, ack.part, ack.fields["status"]) == (link, 4242, 3, ACK_HAVE_IT)  # which frame it is about, and the verdict
        assert ack.fields["report"] == report  # the channel report arrives intact
        ident = receive(run_channel(build_ident("Q1AAAA/P", link, final=True, level=spec.number), snr_db, rng, offset_hz=-5.0))  # send an identification
        assert ident.ok and ident.frame_type == 5 and (ident.origin, ident.link, ident.fields["final"]) == ("Q1AAAA/P", link, True)  # callsign, link and end-of-contact flag
    assert control_seconds(4, 4) < 4 and control_seconds(4, 0) < 32  # an acknowledgment is quick: under 4 s at the fastest level, about 31 s at the slowest
