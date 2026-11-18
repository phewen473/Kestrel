"""Whole-system tests: a message goes in, crosses the simulated channel, and must come out unchanged."""

import numpy as np  # numerical arrays

from modem import build_frame, frame_seconds, receive  # transmitter and receiver
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
    assert [round(frame_seconds(c)) for c in range(3)] == [74, 134, 254]  # about 1, 2 and 4 minutes


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
    assert result.size_class == 2  # the header announced the 200-character size
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
    first = _send(SHORT, -23.5, 211)  # first copy: too weak to decode by itself
    second_alone = _send(SHORT, -23.5, 311)  # second copy: also too weak by itself
    assert not first.ok and not second_alone.ok  # neither copy decodes alone
    assert first.body_llrs is not None  # but the first copy's soft bits were kept
    heard = run_channel(build_frame(SHORT), -23.5, np.random.default_rng(311))  # the same second copy again
    combined = receive(heard, prior_llrs=first.body_llrs)  # decode it together with the first copy
    assert combined.ok and combined.text == SHORT  # together they decode


def test_noise_alone_is_rejected():  # no signal: the receiver must not invent a message
    noise = np.random.default_rng(8).standard_normal(30 * FS)  # 30 seconds of pure noise
    assert not receive(noise).ok  # nothing decodes
