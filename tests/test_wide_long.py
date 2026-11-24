"""The wide long frame (signal version 0.38): tones five bins apart, read with own-bin, three-bin and five-bin sums."""

import numpy as np  # numerical arrays


def _faded(audio, spread_hz, snr_db, seed):  # the frame through a two-path fading channel with noise
    from modem.params import FS  # sample rate
    from sim.channel import _analytic, add_noise, watterson  # the channel's parts
    rng = np.random.default_rng(seed)  # repeatable
    y = np.concatenate([np.zeros(FS), audio, np.zeros(FS)])  # a second of quiet either side
    a = watterson(_analytic(y), spread_hz, 1.0, rng)  # two paths 1 ms apart, smeared by the spread
    return add_noise(a.real, snr_db, float(np.mean(audio ** 2)), rng)  # and noise at that SNR (2.5 kHz)


def test_wide_spacing_numbers():  # five bins, 4.29 Hz, 137 Hz in all, still 59.5 s
    from modem import longbeacon  # the long frame
    assert longbeacon.LONG.step == 5  # five bins apart
    assert abs(longbeacon.LONG.step * longbeacon.LONG.bin_hz - 4.2857) < 0.001  # 4.29 Hz
    assert abs(longbeacon.SECONDS - 59.5) < 0.01  # unchanged length
    low, high = longbeacon.LONG.tone_bins[0] * longbeacon.LONG.bin_hz, longbeacon.LONG.tone_bins[-1] * longbeacon.LONG.bin_hz  # the band
    assert 1420 < low < 1440 and 1560 < high < 1570  # about 1431 to 1564 Hz
    assert longbeacon.CLEAN_HALF_HZ >= (high - low) / 2 + 50  # the carrier cleaner covers the band and the frequency error allowed


def test_five_bin_sums_read_a_smeared_frame():  # at 4 Hz of spread the five-bin reading decodes where the center bin cannot
    from modem import longbeacon  # the long frame
    from modem.params import FS, PREAMBLE_TONES  # sample rate, pattern length
    audio = longbeacon.build_long_beacon("Q1AAAA", "EM93")  # a long beacon
    read_center, read_any = 0, 0  # frames read by the center bin alone, and by any reading
    for seed in range(6):  # six frames
        x = _faded(audio, 4.0, -18.0, 900 + seed)  # 4 Hz of spread at -18 dB
        soft = longbeacon.soft_at(x, {"start": float(FS), "offset_hz": 0.0, "quality": 1.0})  # measured where it was sent
        assert soft is not None and soft.wider is not None  # all of it, five-bin sums included
        read_center += longbeacon.decode_energies(soft.energies)[0] is not None  # center bin only
        fields, _ = longbeacon.decode_soft(soft.energies, soft.wide, soft.wider)  # the receiver's order
        read_any += fields is not None and fields["origin"] == "Q1AAAA"  # read correctly
    assert read_any >= 5  # the study: 19 in 20 at -20 dB, all at -18
    assert read_any > read_center  # the sums did the work


def test_wide_frame_through_the_receiver_on_a_steady_path():  # nothing lost on a quiet path: the whole receiver, -24 dB
    from modem import receive  # the full receiver
    from modem.longbeacon import build_long_beacon  # the transmitter
    from modem.params import LONG_LEVEL  # how the receiver reports it
    from sim import run_channel  # the channel simulator
    heard = run_channel(build_long_beacon("Q1AAAA", "EM93"), -24.0, np.random.default_rng(38), offset_hz=2.0, lead_s=4.0, tail_s=2.0)  # 2 Hz off, a little under the steady limit's margin
    result = receive(heard, long_beacons=True)  # searched for every pattern
    assert result.ok and result.level == LONG_LEVEL and result.origin == "Q1AAAA"  # read back
