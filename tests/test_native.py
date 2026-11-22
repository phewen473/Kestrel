"""Tests for libkestrel, the compiled modem library: it must give what the Python reference gives.

Each test feeds the same input to the compiled routine and to the Python
one (with the library switched off for that call) and compares. The tests
are skipped when the library has not been built (python tools/build_native.py).
"""

import numpy as np  # numerical arrays
import pytest  # the test runner

from modem import native  # the bridge to the library
from modem.params import FS  # the sample rate

pytestmark = pytest.mark.skipif(not native.available(), reason="the compiled library is not built")  # every test here needs the library


@pytest.fixture  # a helper the tests ask for by name
def python_only(monkeypatch):  # run a block of code with the library switched off
    """Return a function that calls its argument with the compiled library out of use."""
    def run(work, *args, **kwargs):  # call `work` in pure Python
        with monkeypatch.context() as patch:  # undone when the block ends
            patch.setattr(native, "_lib", None)  # pretend the library is not there
            return work(*args, **kwargs)  # the Python reference's answer
    return run  # the helper


def test_blanker_matches_python(python_only):  # the static-crash blanker
    from modem.blanker import blank_impulses  # the routine under test
    rng = np.random.default_rng(3)  # repeatable
    for length in (0, 1, 1199, 1200, 12345, 120000):  # empty, tiny, one block short, exactly one block, ragged and long
        x = rng.normal(size=length)  # band noise
        if length > 100:  # room for spikes
            x[rng.integers(0, length, 5)] = rng.choice([-1, 1], 5) * 60.0  # five static crashes
        assert np.array_equal(blank_impulses(x), python_only(blank_impulses, x))  # exactly the same samples


def test_blanker_handles_silence(python_only):  # all zeros: no level to judge against
    from modem.blanker import blank_impulses  # the routine under test
    x = np.zeros(5000)  # silence
    x[2500] = 1.0  # one lone click
    assert np.array_equal(blank_impulses(x), python_only(blank_impulses, x))  # the same answer either way


def test_viterbi_matches_python(python_only):  # the error-correcting decoder
    from modem.fec import conv_encode, viterbi_decode  # the code under test
    rng = np.random.default_rng(4)  # repeatable
    for length in (1, 40, 300, 1600):  # short and long blocks
        bits = rng.integers(0, 2, length)  # random data
        coded = 1.0 - 2.0 * conv_encode(bits)  # coded bits as +1 / -1
        for noise in (0.5, 1.5, 3.0):  # clean, noisy, hopeless
            llrs = coded + rng.normal(size=len(coded)) * noise  # through the noise
            assert np.array_equal(viterbi_decode(llrs), python_only(viterbi_decode, llrs))  # the same decision for every bit


def test_band_energies_match_python(python_only):  # the tone-band measurement behind every symbol read
    from modem.levels import LEVELS  # every speed level
    from modem.mfsk import band_energies  # the routine under test
    rng = np.random.default_rng(5)  # repeatable
    x = rng.normal(size=20 * FS)  # 20 seconds of noise
    for level in LEVELS:  # each level's tone length
        for start, offset, drift in ((0.0, 0.0, 0.0), (1234.5, 7.3, 0.04), (-500.0, -11.0, -0.3), (len(x) - 3.5 * level.samples, 2.0, 0.0)):  # plain, shifted and drifting, starting before the audio, running off its end
            mine = band_energies(x, start, 16, level, offset, drift)  # compiled
            ref = python_only(band_energies, x, start, 16, level, offset, drift)  # Python
            assert mine.shape == ref.shape  # the same table
            assert np.max(np.abs(mine - ref)) <= 1e-11 * np.max(ref)  # equal to rounding (the mixer is worked out a little differently)


def test_whole_receiver_decodes_the_same(python_only):  # end to end: the same frames, compiled or not
    from live.listener import Listener  # the continuous receiver
    from modem import build_beacon, build_frame  # frames to hide in the noise
    rng = np.random.default_rng(6)  # repeatable
    x = rng.normal(0.0, 1.0, 40 * FS)  # 40 seconds of band noise
    t = 2 * FS  # where the first frame goes
    for audio, snr in ((build_beacon("Q1AAAA", "EM92", level=2), -12.0), (build_frame("Compiled or not, the same answer", level=3), -8.0)):  # two frames
        x[t:t + len(audio)] += audio * np.sqrt(10 ** (snr / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # at its SNR against the noise
        t += len(audio) + 3 * FS  # a gap, then the next

    def decode():  # run the receiver over the whole stream
        listener = Listener()  # a fresh receiver
        got = []  # what it decodes
        for begin in range(0, len(x), FS):  # one second at a time
            got += [(h.result.frame_type, h.result.level, h.result.text, round(h.result.sample / FS)) for h in listener.feed(x[begin:begin + FS]) if h.result.ok]  # each frame, its text and where it began
        return got  # the list

    mine = decode()  # with the library
    assert mine == python_only(decode) and len(mine) == 2  # both frames, identical either way


def test_describe_says_what_is_in_use():  # the About box line
    assert native.describe() == "compiled modem library in use"  # loaded, so it says so
