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


def test_preamble_search_matches_python(python_only):  # the signature-pattern search, coarse and fine
    from modem import longbeacon  # the long beacon's own pattern
    from modem.levels import LEVELS  # every speed level
    from modem.preamble import detect_preamble, make_preamble  # the routines under test, and a pattern to hide
    rng = np.random.default_rng(8)  # repeatable
    for spec in list(LEVELS) + [longbeacon.LONG]:  # each pattern
        x = rng.normal(size=30 * FS if spec is not longbeacon.LONG else 40 * FS)  # band noise
        pattern = make_preamble(spec)  # the pattern
        at = int(rng.integers(FS, len(x) - len(pattern) - FS))  # somewhere in the middle
        x[at:at + len(pattern)] += pattern * np.sqrt(10 ** (-12 / 10) * (2500 / 6000) / np.mean(np.square(pattern)))  # at -12 dB
        whiten = spec is longbeacon.LONG  # the long beacon is searched with the band levelled out
        coarse = detect_preamble(x, spec, whiten=whiten, fine=False)  # compiled, coarse
        coarse_ref = python_only(detect_preamble, x, spec, whiten=whiten, fine=False)  # Python, coarse
        assert len(coarse) == len(coarse_ref)  # as many candidates
        for a, b in zip(coarse, coarse_ref):  # each candidate
            assert (a["start"], a["offset_hz"]) == (b["start"], b["offset_hz"])  # exactly the same place and frequency
            assert abs(a["quality"] - b["quality"]) <= 1e-12 * b["quality"]  # and quality, to rounding
        fine = detect_preamble(x, spec, whiten=whiten)  # compiled, refined
        ref = python_only(detect_preamble, x, spec, whiten=whiten)  # Python, refined
        for a, b in zip(fine, ref):  # each candidate
            assert abs(a["start"] - b["start"]) < 1e-6 and abs(a["offset_hz"] - b["offset_hz"]) < 1e-9  # the same start and frequency


def test_short_audio_finds_no_pattern(python_only):  # too little audio for a whole pattern
    from modem.levels import LEVELS  # every speed level
    from modem.preamble import detect_preamble  # the routine under test
    x = np.random.default_rng(9).normal(size=1000)  # a twelfth of a second
    assert detect_preamble(x, LEVELS[0]) == python_only(detect_preamble, x, LEVELS[0]) == []  # nothing, either way


def test_header_reader_matches_python(python_only):  # reading the header after a preamble, both copies
    from modem import build_beacon, build_frame  # frames to read
    from modem.frame import _read_header_how  # the routine under test
    from modem.levels import LEVELS  # every speed level
    from modem.preamble import preamble_samples  # where the header begins
    rng = np.random.default_rng(10)  # repeatable
    outcomes = set()  # which copies gave headers, to be sure both paths ran
    for trial in range(8):  # a few frames at each level
        for spec in LEVELS:  # each level
            audio = build_beacon("Q1AAAA", "EM92", level=spec.number) if trial % 2 else build_frame("Header test", level=spec.number)  # a frame
            x = rng.normal(size=len(audio) + 3 * FS)  # noise around it
            x[FS:FS + len(audio)] += audio * np.sqrt(10 ** (float(rng.uniform(-20, -6)) / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # at a random SNR
            start = FS + preamble_samples(spec)  # the first header copy
            for since in (None, float(len(x) // 2)):  # a first try, and a later one
                mine = _read_header_how(x, start, 0.0, spec, since=since)  # compiled
                ref = python_only(_read_header_how, x, start, 0.0, spec, since=since)  # Python
                assert mine[1] == ref[1] and (mine[0] is None) == (ref[0] is None)  # the same outcome
                if ref[0] is not None:  # a header was read
                    assert np.array_equal(mine[0], ref[0])  # the same bits
                outcomes.add(ref[1])  # noted
    assert {"first", ""} <= outcomes  # headers found and not found both happened


def test_thread_count_does_not_change_results():  # sharing work among threads must not change any answer
    from modem.blanker import blank_impulses  # one shared routine
    from modem.levels import LEVELS  # a level to search
    from modem.preamble import detect_preamble  # another
    x = np.random.default_rng(11).normal(size=60 * FS)  # a minute of noise
    x[30000] = 80.0  # a static crash
    answers = []  # what each thread count gives
    try:  # put the count back afterwards
        for count in (1, 3, 8):  # one thread, a few, the most
            native.set_threads(count)  # limit them
            answers.append((blank_impulses(x), detect_preamble(x, LEVELS[1], fine=False)))  # blanker and search
    finally:  # always
        native.set_threads(0)  # the computer's own count again
    for blanked, found in answers[1:]:  # every other count
        assert np.array_equal(blanked, answers[0][0]) and found == answers[0][1]  # exactly the same


def test_ldpc_decoder_matches_python(python_only):  # the body's error correction
    from modem import ldpc  # the code under test
    rng = np.random.default_rng(12)  # repeatable
    verdicts = set()  # whether decoding succeeded, to be sure both outcomes were tried
    for k in (374, 752, 1452):  # a short, a middle and the longest body
        for noise in (0.8, 1.6, 3.0):  # easy, hard, hopeless
            bits = rng.integers(0, 2, k)  # random data
            llrs = (1.0 - 2.0 * ldpc.encode(bits)) * 2.0 + rng.normal(size=2 * k) * noise  # through the noise
            mine, ref = ldpc.decode(llrs, k), python_only(ldpc.decode, llrs, k)  # compiled and Python
            assert np.array_equal(mine[0], ref[0]) and mine[1] == ref[1]  # the same bits and verdict
            verdicts.add(ref[1])  # noted
    assert verdicts == {True, False}  # both a success and a give-up were compared


def test_noise_profile_matches_python(python_only):  # the noise level followed through a frame
    from modem.mfsk import noise_profile  # the routine under test
    rng = np.random.default_rng(13)  # repeatable
    for rows in (5, 16, 17, 60, 620):  # too short to track, just long enough, and long frames
        energies = rng.exponential(size=(rows, 32)) * np.linspace(1, 10, rows)[:, None]  # noise that grows through the frame
        energies[:, 7] += 20.0  # and a signal on one tone
        assert np.array_equal(noise_profile(energies), python_only(noise_profile, energies))  # exactly the same levels


def test_pilot_fit_matches_python(python_only):  # frequency and drift from the pilot tones
    from modem.levels import LEVELS  # every speed level
    from modem.mfsk import pilot_frequency_fit  # the routine under test
    rng = np.random.default_rng(14)  # repeatable
    positions = np.arange(0, 320, 16)  # pilots every sixteenth tone
    tones = (7 * np.arange(len(positions)) + 2) % 32  # which tone each sends
    for spec in LEVELS:  # each level
        x = rng.normal(size=int(330 * spec.samples + 2 * FS))  # noise long enough for the pilots
        for offset in (0.0, 4.2, -9.7):  # frequency errors from the preamble
            mine = pilot_frequency_fit(x, 1500.5, positions, tones, spec, offset)  # compiled
            ref = python_only(pilot_frequency_fit, x, 1500.5, positions, tones, spec, offset)  # Python
            assert abs(mine[0] - ref[0]) < 1e-9 and abs(mine[1] - ref[1]) < 1e-9  # the same fit, to rounding


def test_notch_matches_python(python_only):  # the steady-signal notch (0.31R1)
    from modem.notch import remove_steady  # the routine under test
    rng = np.random.default_rng(15)  # repeatable
    t = np.arange(100 * FS) / FS  # 100 seconds
    for carriers in ((), (1489.3, ), (1466.9, 1433.0, 2000.2)):  # none, one, several
        x = rng.normal(size=len(t))  # band noise
        for frequency in carriers:  # each carrier
            x += 0.4 * np.cos(2 * np.pi * frequency * t)  # added
        assert np.max(np.abs(remove_steady(x) - python_only(remove_steady, x))) < 1e-9  # the same audio, to rounding


def test_viterbi_with_known_bits_matches_python(python_only):  # the decoder with expected callsigns (0.31R1)
    from modem.fec import conv_encode, viterbi_decode  # the code under test
    rng = np.random.default_rng(16)  # repeatable
    for length in (75, 124, 192):  # beacon, answer and notice bodies (with their check values)
        bits = rng.integers(0, 2, length + 16)  # random data
        llrs = (1.0 - 2.0 * conv_encode(bits)) + rng.normal(size=2 * (length + 22)) * 2.5  # very noisy
        known = -np.ones(length + 16, dtype=np.int8)  # nothing known...
        known[:48] = bits[:48]  # ...but the first callsign
        assert np.array_equal(viterbi_decode(llrs, known), python_only(viterbi_decode, llrs, known))  # the same decision for every bit


def test_whole_body_decoder_matches_python(python_only):  # pilots to checked body in one call (interface 6)
    import math  # not-a-number tests
    from modem import build_answer, build_beacon, build_frame  # frames to decode
    from modem.control import ChannelReport  # an answer's report
    from modem.frame import receive  # the receiver
    rng = np.random.default_rng(17)  # repeatable
    for level in range(5):  # every level
        for kind in range(3):  # a message, a beacon, an answer
            audio = (build_frame("Body decoder check", level=level) if kind == 0 else build_beacon("Q2BB", "EM94", level=level) if kind == 1
                     else build_answer("Q1AAAA", "Q2BB", ChannelReport(-3, 0.2, 1, 2), level=level))  # the frame
            for snr in (-22.0, -10.0, 5.0):  # failing, near the limit, strong
                x = rng.normal(size=len(audio) + 3 * FS)  # noise around it
                x[FS:FS + len(audio)] += audio * np.sqrt(10 ** (snr / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # at its SNR
                mine, ref = receive(x, long_beacons=False), python_only(receive, x, long_beacons=False)  # compiled and Python
                assert (mine.ok, mine.reason, mine.text, mine.origin, mine.dest) == (ref.ok, ref.reason, ref.text, ref.origin, ref.dest)  # the same outcome
                for name in ("offset_hz", "drift_hz_s", "snr_db", "fade_index"):  # the measurements
                    a, b = getattr(mine, name), getattr(ref, name)  # each way
                    assert (math.isnan(a) and math.isnan(b)) or abs(a - b) < 1e-6  # equal to rounding
                assert (mine.body_llrs is None) == (ref.body_llrs is None)  # soft bits kept alike
                if ref.body_llrs is not None:  # kept
                    assert np.max(np.abs(mine.body_llrs - ref.body_llrs)) < 1e-6  # the same soft bits


def test_body_decoder_combines_retries_like_python(python_only):  # HARQ through the compiled body decoder
    from modem import build_frame  # a message frame
    from modem.frame import receive  # the receiver
    rng = np.random.default_rng(18)  # repeatable
    audio = build_frame("Two weak copies make one good one", level=2)  # an L2 message
    for _ in range(6):  # a few pairs
        copies = []  # two weak copies
        for _copy in range(2):  # each
            x = rng.normal(size=len(audio) + 3 * FS)  # noise
            x[FS:FS + len(audio)] += audio * np.sqrt(10 ** (-16.0 / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # below L2's limit
            copies.append(x)  # kept
        first = python_only(receive, copies[0], long_beacons=False)  # the first copy, in Python
        if first.body_llrs is None:  # no header read: nothing to combine
            continue  # next pair
        mine = receive(copies[1], prior_llrs=first.body_llrs, long_beacons=False)  # the second, combined, compiled
        ref = python_only(receive, copies[1], prior_llrs=first.body_llrs, long_beacons=False)  # and in Python
        assert (mine.ok, mine.reason, mine.text) == (ref.ok, ref.reason, ref.text)  # the same outcome


def test_long_beacon_carrier_notch_matches_python(python_only):  # longbeacon.clean through the compiled notch (interface 6)
    from modem import longbeacon  # the routine under test
    rng = np.random.default_rng(19)  # repeatable
    t = np.arange(30 * FS) / FS  # 30 seconds
    for carriers in ((), (1490.2, ), (1462.0, 1531.7)):  # none, one, two near the long beacon's tones
        x = rng.normal(size=len(t))  # band noise
        for frequency in carriers:  # each carrier
            x += 0.3 * np.cos(2 * np.pi * frequency * t)  # added
        mine, ref = longbeacon.clean(x), python_only(longbeacon.clean, x)  # compiled and Python
        assert (mine is x) == (ref is x) and np.max(np.abs(mine - ref)) < 1e-9  # the same audio, and left alone in the same cases


def test_describe_says_what_is_in_use():  # the About box line
    assert native.describe().startswith("compiled modem library in use")  # loaded, so it says so
