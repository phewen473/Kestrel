"""Tests for the second tries on a failed body: wide tones and the OSD search (since 0.43)."""

import numpy as np  # numerical arrays

from modem import LEVELS, build_frame, ldpc, osd, receive  # levels, transmitter, LDPC code, OSD, receiver
from modem.frame import RxResult, _second_tries, body_layout  # the second tries, a blank report, the body's shape
from modem.mfsk import tone_energies, wide_tone_energies  # tones alone, and with their neighbors
from sim.channel import _analytic, add_noise, watterson  # the channel's parts

TEXT = "SECOND TRY TEST 1234" * 2  # 40 characters: the 50-character class


def test_generator_matches_the_encoder():  # OSD's generator is the code's own
    """Every codeword OSD's generator makes is the LDPC encoder's codeword for the same data, at every body size."""
    rng = np.random.default_rng(1)  # repeatable
    for k in (402, 752, 1102, 1452):  # the four body sizes
        data = rng.integers(0, 2, k).astype(np.uint8)  # random data
        assert np.array_equal(data.astype(np.int64) @ osd.generator(k) % 2, ldpc.encode(data))  # the same codeword


def test_osd_corrects_a_few_strong_errors():  # it finds the codeword
    """A codeword with mild noise and a few confidently wrong bits comes back right."""
    rng = np.random.default_rng(2)  # repeatable
    k = 402  # the 50-character body
    data = rng.integers(0, 2, k).astype(np.uint8)  # random data
    llrs = 4.0 * (1.0 - 2.0 * ldpc.encode(data)) + rng.normal(0, 1.0, 2 * k)  # clear soft bits
    llrs[rng.choice(2 * k, 6, replace=False)] *= -0.3  # six bits turned the wrong way, without much confidence
    assert np.array_equal(osd.decode(llrs, k), data)  # read right


def test_wide_tones_add_half_the_neighbors():  # the helper's arithmetic
    """At a two-bin level each wide tone is the tone plus half of each neighbor; at a one-bin level the tones alone."""
    band = np.arange(2 * 65, dtype=float).reshape(2, 65)  # a made-up band, two symbols (65 bins: L0 band from a bin below the lowest tone to a bin above the highest)
    spec = LEVELS[0]  # L0: tones two bins apart
    wide = wide_tone_energies(band, spec)  # wide tones
    assert np.allclose(wide[:, 0], band[:, 1] + 0.5 * (band[:, 0] + band[:, 2]))  # the lowest tone
    assert np.allclose(wide[:, 31], band[:, 63] + 0.5 * (band[:, 62] + band[:, 64]))  # the highest tone
    assert np.array_equal(wide_tone_energies(band[:, :34], LEVELS[3]), tone_energies(band[:, :34], LEVELS[3]))  # L3: no bins between tones


def test_noise_bodies_never_pass():  # the second tries do not invent frames
    """Bodies of pure noise, run through the second tries, never pass their check (each try has a 1 in 65,536 chance)."""
    rng = np.random.default_rng(3)  # repeatable
    spec = LEVELS[0]  # L0
    layout = body_layout(0)  # the 50-character body
    for _ in range(100):  # a hundred noise bodies
        band = rng.exponential(1.0, (layout["total"], 65))  # noise energies in every bin
        llrs = rng.normal(0, 1.5, 2 * layout["info"])  # noise soft bits
        result = RxResult()  # a blank report
        assert _second_tries(band, spec, layout, False, llrs, None, result) is None  # nothing read
        assert result.second_try == ""  # and nothing claimed


def test_wide_second_try_reads_fast_fading():  # the gain it was added for
    """In fast fading (2 Hz spread) at -18 dB, the second tries read frames the first reading lost."""
    rng = np.random.default_rng(4)  # repeatable
    audio = build_frame(TEXT, 0)  # an L0 frame
    read, by_wide = 0, 0  # frames read, and of those by the wide try
    for _ in range(8):  # a few frames
        y = np.concatenate([np.zeros(12000), audio, np.zeros(12000)])  # a second of quiet either side
        y = add_noise(watterson(_analytic(y), 2.0, 1.0, rng).real, -18.0, float(np.mean(audio ** 2)), rng)  # fast fading and noise
        cand = [({"start": 12000.0, "offset_hz": 0.0, "quality": 1.0}, LEVELS[0])]  # where the frame is
        r = receive(y, long_beacons=False, candidates=cand)  # read it
        read += bool(r.ok and r.text == TEXT)  # read right
        by_wide += r.second_try == "wide"  # by the wide try
    assert by_wide >= 2 and read >= 5  # the wide try earned its place (measured: 8 of 8 read, 4 of them by it)
