"""Tests for libkestrel, the compiled modem library: it must give what the Python reference gives.

Each test feeds the same input to the compiled routine and to the Python
one (with the library switched off for that call) and compares. The tests
are skipped when the library has not been built (python tools/build_native.py).
"""

import json  # the mail store compares its file contents

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
    for length in (75, 139, 192):  # beacon, answer (with its locator since 0.33) and notice bodies (with their check values)
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


def test_compiled_listener_hears_what_the_python_listener_hears():  # the continuous receiver, bookkeeping in the library (interface 7)
    from live.listener import Listener  # the receiver under test
    from modem import build_beacon, build_frame, longbeacon  # frames to hide in the noise
    rng = np.random.default_rng(20)  # repeatable
    x = rng.normal(0.0, 1.0, 170 * FS)  # nearly three minutes of band noise
    t = np.arange(len(x)) / FS  # the time of each sample
    x += 0.2 * np.cos(2 * np.pi * 1731.4 * t)  # a steady carrier in the band
    place = 3 * FS  # where the first frame goes
    from modem.levels import LEVELS  # the speed levels
    from modem.preamble import make_preamble  # a signature pattern with nothing after it (a near miss)
    for audio, snr in ((make_preamble(LEVELS[0]), -5.0), (build_beacon("Q1AAAA", "EM92", level=2), -10.0), (build_beacon("Q2BB", "EM94", level=0), -23.5),  # a pattern alone (a near miss); a clear beacon; a weak one (it fails)
                       (longbeacon.build_long_beacon("Q3CCC", "EM93"), -20.0), (build_frame("Compiled listener check", level=3), -6.0)):  # a long beacon; a message
        x[place:place + len(audio)] += audio * np.sqrt(10 ** (snr / 10) * (2500 / 6000) / np.mean(np.square(audio)))  # at its SNR
        place += len(audio) + 4 * FS  # a gap, then the next

    def hear(compiled):  # run one listener over the stream
        listener = Listener(compiled=compiled)  # the compiled or the Python bookkeeping
        frames, nears, searches = [], [], []  # what it reports
        listener.on_near = lambda result: nears.append((result.seen_level, listener.near_audio_sample, round(result.sync_quality, 9), result.pattern_tones))  # near misses, with their pattern-tone count
        listener.on_search = lambda result, trace: searches.append([(step["level"], step["sample"], step["header"], step.get("ok")) for step in trace])  # every try, for a signal log
        for begin in range(0, len(x), FS):  # a second at a time
            frames += [(h.result.frame_type, h.result.ok, h.result.sample, h.result.text, h.audio_sample, len(h.audio)) for h in listener.feed(x[begin:begin + FS])]  # each frame handed over
        return frames, nears, searches  # everything

    mine, ref = hear(True), hear(False)  # compiled and Python
    assert mine[0] == ref[0] and len(mine[0]) >= 3  # the same frames, at the same places, with the same audio
    assert mine[1] == ref[1] and len(mine[1]) >= 1  # the same near misses (the lone pattern at least)
    assert mine[2] == ref[2]  # the same tries, search by search


def test_transmitter_matches_python(python_only):  # frames built by the library (interface 7)
    from modem import build_ack, build_answer, build_beacon, build_frame, build_ident, build_notice  # every frame there is
    from modem.address import call_hash  # short codes for a mail notice
    from modem.control import ChannelReport  # a channel report
    report = ChannelReport(-3, 0.2, 1, 2)  # any report
    for level in range(5):  # every level
        for build, args, extra in ((build_frame, ("Hello from the compiled transmitter", ), {}), (build_frame, ("x" * 180, ), {}),  # short and long messages
                                   (build_frame, ("Addressed one", ), {"dest": "Q2BB", "origin": "Q1AAAA", "msg_id": 7}),  # an addressed message
                                   (build_beacon, ("Q1AAAA", "EM92"), {}), (build_answer, ("Q1AAAA", "Q2BB", report), {}), (build_ack, (5, 7, 0, 0, report), {}),  # control frames
                                   (build_ident, ("Q1AAAA", 17), {}), (build_notice, ("Q1AAAA", (call_hash("Q2BB"), ), (), (call_hash("Q3CCC"), )), {})):  # and the rest
            mine = build(*args, level=level, **extra)  # compiled
            ref = python_only(build, *args, level=level, **extra)  # Python
            assert len(mine) == len(ref) and np.max(np.abs(mine - ref)) < 1e-9  # the same audio, to rounding (the glides at L3 and L4 add up many small terms in a different order: about 3e-11 apart, since 0.32)


def test_describe_says_what_is_in_use():  # the About box line
    assert native.describe().startswith("compiled modem library in use")  # loaded, so it says so


def _outcome(work, *args, **kwargs):  # what a call gives: its answer, or the kind of error it raises
    """Return ("ok", answer) with arrays turned into lists, or ("error", the exception's type)."""
    try:  # run it
        got = work(*args, **kwargs)  # the answer
    except Exception as err:  # noqa: BLE001 - any error is part of the answer being compared
        return ("error", type(err))  # the kind of error
    if isinstance(got, np.ndarray):  # an array of bits
        return ("ok", got.astype(int).tolist())  # as a plain list
    if isinstance(got, dict):  # unpacked fields
        return ("ok", {k: (vars(v) if hasattr(v, "__dataclass_fields__") else v) for k, v in got.items()})  # reports as plain dicts
    return ("ok", got)  # anything else as it is


def _same(python_only, work, *args, **kwargs):  # the library and Python agree on one call
    """Assert that `work` gives the same answer, or the same kind of error, with and without the library."""
    mine = _outcome(work, *args, **kwargs)  # compiled
    ref = _outcome(python_only, work, *args, **kwargs)  # Python (python_only passes `work` through)
    assert mine == ref, (work.__name__, args, kwargs, mine, ref)  # the same


def test_packing_matches_python(python_only):  # bit packing and unpacking (interface 8)
    from modem import native  # the bridge
    from modem.address import bits_to_call, call_hash, call_to_bits, link_id, message_hash  # addresses
    from modem.crc import crc8, crc16  # check values
    from modem.text import bits_to_text, choose_packing, text_to_bits  # text
    assert native._lib is not None  # the library is in use, so the comparison means something
    rng = np.random.default_rng(8)  # repeatable
    for n in (0, 1, 7, 16, 24, 75, 300, 1424):  # check values over many lengths
        bits = rng.integers(0, 2, n)  # random bits
        _same(python_only, crc16, bits)  # body check
        _same(python_only, crc8, bits)  # header check
    calls = ["Q1AAAA", "q2bb", " Q3CCC/P ", "ALL", "Q1AAAA-10", "Q1AAAAAAA", "Q1AAAAAAAA", "", "   ", "Q1 AA", "Q1@AA", "Q1ÉA", "Q1\0A", "\x1cQ9Z\x1f", 7]  # good, untidy and bad
    for call in calls:  # each
        _same(python_only, call_to_bits, call)  # to bits
        _same(python_only, call_hash, call)  # its short code
        _same(python_only, message_hash, call, 513)  # a message code
        _same(python_only, link_id, call, "Q2BB")  # a link number
    for _ in range(300):  # random address bits: most are not addresses
        _same(python_only, bits_to_call, rng.integers(0, 2, 48))  # back to text
    for call in calls[:6]:  # and the bits of the valid ones
        _same(python_only, bits_to_call, call_to_bits(call))  # round trip
    texts = ["", "Hi", "Hello from the compiled packer", "x" * 50, "x" * 51, "e" * 200, "Q" * 200, "Z{|}~" * 40, "a" * 201, "café", "tab\there\nnew\0zero",
             "".join(chr(c) for c in range(128)), "The quick brown fox " * 9]  # short, long, borderline, bad
    for text in texts:  # each
        for frame_type in (0, 1, 2):  # link, addressed, and a type with no text
            _same(python_only, choose_packing, text, frame_type)  # the packing choice
            for size_class in range(4):  # every size
                for compressed in (False, True):  # both forms
                    _same(python_only, text_to_bits, text, size_class, compressed, frame_type)  # packed
                    try:  # and back again, when it packs
                        bits = python_only(text_to_bits, text, size_class, compressed, frame_type)  # the reference bits
                    except (ValueError, KeyError):  # it does not fit, or the type carries no text
                        continue  # nothing to unpack
                    _same(python_only, bits_to_text, bits, compressed)  # unpacked
                    damaged = bits.copy()  # a damaged copy
                    damaged[rng.integers(0, len(bits), 6)] ^= 1  # six bits flipped
                    _same(python_only, bits_to_text, damaged, compressed)  # the same text, or the same error
    for _ in range(200):  # random bodies
        _same(python_only, bits_to_text, rng.integers(0, 2, int(rng.integers(0, 1408))), bool(rng.integers(0, 2)))  # nonsense, read the same way


def test_frame_fields_match_python(python_only):  # header, address block and control frames (interface 8)
    from modem import control  # control frame fields
    from modem.control import ChannelReport  # a channel report
    from modem.frame import RxResult, _address_block, _header_bits, _read_address_block  # the frame's own packing
    rng = np.random.default_rng(9)  # repeatable
    for _ in range(200):  # random headers, some out of range
        args = [int(v) for v in rng.integers(-2, 10, 5)] + [int(rng.integers(0, 3))]  # type, level, size, part, parts, compressed
        _same(python_only, _header_bits, *args)  # the 24 bits
    for args in ((0, 5, 2, 513, None, None, 0, 48), (0, 512, 0, 1, None, None, 0, 48), (0, 3, 8, 1, None, None, 0, 48), (0, 3, 1, 70000, None, None, 0, 48),  # link frames
                 (1, 0, 0, 7, "Q2BB", "Q1AAAA", 2, 47), (1, 0, 0, 7, "Q2BB", "Q1AAAA", 8, 48), (1, 0, 0, 7, "Q2BB", "Q1AAAA", 0, 63), (1, 0, 0, 7, "Q2BB", "Q1AAAA", 0, 62.9),  # addressed
                 (1, 0, 0, 7, "Q2BB", "Q1AAAA", 0, -1), (1, 0, 0, 7, "Q2BB", "Q1AAAA", 0, -3), (1, 0, 0, 7, "bad call", "Q1AAAA", 0, 48), (1, 0, 0, 7, None, "Q1AAAA", 0, 48)):  # edges
        _same(python_only, _address_block, *args)  # the block
    for frame_type, length in ((0, 28), (1, 120)):  # reading blocks back
        for _ in range(100):  # random ones, most addresses invalid
            bits = rng.integers(0, 2, length)  # the bits

            def read(bits=bits, frame_type=frame_type):  # what the receiver keeps
                result = RxResult()  # an empty report
                result.frame_type = frame_type  # of this kind
                _read_address_block(result, bits)  # filled in
                return (result.link, result.want_level, result.msg_id, result.dest, result.origin, result.hops, result.life_hours)  # the fields
            _same(python_only, read)  # the same
        good = python_only(_address_block, frame_type, 5, 2, 513, "Q2BB", "Q1AAAA", 3, 47)  # a real block

        def read_good(bits=good, frame_type=frame_type):  # a real block read back
            result = RxResult()  # an empty report
            result.frame_type = frame_type  # of this kind
            _read_address_block(result, bits)  # filled in
            return (result.link, result.want_level, result.msg_id, result.dest, result.origin, result.hops, result.life_hours)  # the fields
        _same(python_only, read_good)  # the same
    reports = [ChannelReport(-3, 0.2, 1, 2), ChannelReport(-30.5, 0.125, 3.0, 0), ChannelReport(2.5, float("nan"), -70, 7), ChannelReport(40, 9, 100, 1),  # ordinary, rounding, missing, clipped
               ChannelReport(-28.5, 0.375, -5.0, 3), ChannelReport(float("nan"), 0, 0, 0), ChannelReport(0, float("inf"), 0, 0), ChannelReport(0, 0, 0, 8)]  # errors
    for report in reports:  # each report
        _same(python_only, control.pack_answer, "Q1AAAA", "Q2BB", report, (0, 1, 2), mail_check=True)  # in an answer
        _same(python_only, control.pack_ack, 5, 513, 2, 1, report)  # in an acknowledgment
    for args, extra in ((("Q1AAAA", "EM92", (0, 2, 4)), {}), (("q1aaaa", " fn31 ", ()), {"listening": False, "wide": True}), (("Q1AAAA", "SS99", (0,)), {}), (("Q1AAAA", "EM9", (0,)), {}),  # beacons
                        (("Q1AAAA", "EM92", (8,)), {}), (("Q1AAAA", "EM92", (0,)), {"holds_mail": 2})):  # bad level, odd flag
        _same(python_only, control.pack_beacon, *args, **extra)  # packed
    for args in ((5, 513, 2, 1), (512, 0, 0, 0), (0, 65536, 0, 0), (0, 0, 8, 0), (0, 0, 0, 4), (1.0, 0, 0, 0)):  # acknowledgments, some out of range
        _same(python_only, control.pack_ack, *args, reports[0])  # packed
    for args in (("Q1AAAA", 17), ("Q1AAAA", 511, True), ("Q1AAAA", 512), ("Q1 A", 3)):  # identifications
        _same(python_only, control.pack_ident, *args)  # packed
    for lists in (((), (), ()), ((1, 2, 3, 4), (65535,), (7,)), ((0,), (), ()), ((65536,), (), ()), (("12",), (), ())):  # mail notices
        _same(python_only, control.pack_notice, "Q1AAAA", *lists)  # packed
    for frame_type in (control.FRAME_TYPE_BEACON, control.FRAME_TYPE_ANSWER, control.FRAME_TYPE_ACK, control.FRAME_TYPE_IDENT, control.FRAME_TYPE_NOTICE):  # every control frame
        length = control.CONTROL_BITS[frame_type]  # its body length
        for _ in range(150):  # random bodies
            _same(python_only, control.unpack, frame_type, rng.integers(0, 2, length))  # unpacked, or refused, the same way
        _same(python_only, control.unpack, frame_type, rng.integers(0, 2, length + 1))  # the wrong length
    good = [control.pack_beacon("Q1AAAA", "EM92", (0, 2)), control.pack_answer("Q1AAAA", "Q2BB", reports[1], (1,)), control.pack_ack(5, 513, 2, 1, reports[4]),  # real bodies
            control.pack_ident("Q1AAAA", 17, True), control.pack_notice("Q1AAAA", (9,), (), (4, 5))]  # (continued)
    for frame_type, bits in zip((control.FRAME_TYPE_BEACON, control.FRAME_TYPE_ANSWER, control.FRAME_TYPE_ACK, control.FRAME_TYPE_IDENT, control.FRAME_TYPE_NOTICE), good):  # each
        _same(python_only, control.unpack, frame_type, bits)  # unpacked the same
    _same(python_only, control.unpack, 0, np.zeros(10, dtype=int))  # not a control frame


def test_mail_store_matches_python():  # the compiled mail store (interface 9) against link/mail.py, call for call
    from link.mail import CompiledMailroom, PythonMailroom  # the two stores
    from modem.address import call_hash, message_hash  # short codes
    rng = np.random.default_rng(11)  # repeatable
    calls = ["Q1AAAA", "Q2BB", "Q3CCC", "Q4DD", "Q5EEE", "ALL"]  # the stations about
    for run in range(6):  # several independent runs
        clock = [1.8e9 if run % 2 else 1800000000]  # the wall clock (a whole number in some runs, as a clock may give)
        py = PythonMailroom("Q1AAAA", clock=lambda: clock[0])  # the reference
        cc = CompiledMailroom("Q1AAAA", clock=lambda: clock[0])  # the library's
        py.next_id = 65530 + run  # the same first number (near the wrap)
        cc._ask("init", "Q1AAAA", 65530 + run)  # in both
        numbers = []  # own message numbers so far
        held = []  # (origin, number, dest) held so far
        for step in range(400):  # random calls
            pick = int(rng.integers(0, 22))  # which method
            who = calls[int(rng.integers(0, len(calls)))]  # a station
            other = calls[int(rng.integers(0, len(calls)))]  # another
            number = numbers[int(rng.integers(0, len(numbers)))] if numbers and rng.random() < 0.8 else int(rng.integers(0, 65536))  # a number, usually a real one
            if pick == 0:  # queue a message
                call = ("own_add", (f"text {int(rng.integers(0, 4))}", other if rng.random() < 0.95 else "bad call", set(numbers[:2]) if rng.random() < 0.3 else ()))  # sometimes a repeat
            elif pick == 1:  # drop one
                call = ("own_drop", (number,))  # taken back
            elif pick == 2:  # carried
                call = ("own_carried", (number, who))  # a carrier
            elif pick == 3:  # may hand?
                call = ("can_hand", (number, who))  # asked
            elif pick == 4:  # delivered
                call = ("own_done", (number, who if rng.random() < 0.5 else None))  # directly or by receipt
            elif pick == 5:  # hold one
                origin = other if rng.random() < 0.9 else "Q7GG"  # usually a known station
                n = int(rng.integers(0, 40))  # its number
                call = ("hold", (who, origin, n, f"held {n}", int(rng.integers(0, 4)), int(rng.integers(1, 63)), calls[int(rng.integers(0, len(calls)))]))  # held
                held.append((origin, n, who))  # remembered
            elif pick == 6 and held:  # one held
                o, n, d = held[int(rng.integers(0, len(held)))]  # which
                call = ("bag_item", (o, n))  # looked up
            elif pick == 7:  # held for
                call = ("held_for", (who,))  # listed
            elif pick == 8:  # to pass
                call = ("to_pass", (who,))  # one to pass on
            elif pick == 9 and held:  # passed
                o, n, d = held[int(rng.integers(0, len(held)))]  # which
                call = ("passed", (o, n, who))  # passed on
            elif pick == 10 and held:  # delivered held
                o, n, d = held[int(rng.integers(0, len(held)))]  # which
                call = ("delivered_held", (o, n, d))  # delivered
            elif pick == 11:  # handled
                call = ("mark_handled", (who, int(rng.integers(0, 40))))  # dealt with
            elif pick == 12:  # handled?
                call = ("is_handled", (who, int(rng.integers(0, 40))))  # asked
            elif pick == 13:  # receipt
                call = ("add_receipt", (who, int(rng.integers(0, 40)), other))  # announced
            elif pick == 14:  # the notice
                call = ("notice_lists", (list(rng.permutation(calls)[:int(rng.integers(0, 6))]),))  # with stations heard
            elif pick == 15:  # a notice heard
                codes = [call_hash(c) for c in calls]  # possible codes
                receipts = [message_hash("Q1AAAA", n) for n in numbers[:2]] + [message_hash(o, n) for o, n, d in held[:2]]  # some that match
                call = ("heard_notice", (who, codes[:int(rng.integers(0, 3))], receipts[:int(rng.integers(0, len(receipts) + 1))], codes[int(rng.integers(0, 3)):]))  # heard
            elif pick == 16:  # reaches?
                call = ("reaches", (who, other))  # asked
            elif pick == 17:  # holds for me?
                call = ("holds_for_me", (who,))  # asked
            elif pick == 18:  # forget
                call = ("forget_held_for_me", (who,))  # forgotten
            elif pick == 19:  # tidy, after time passes
                clock[0] += float(rng.choice([60.0, 3600.0, 7.5 * 3600, 30 * 3600]))  # time moves on
                call = ("tidy", ())  # tidied
            elif pick == 20:  # life hours
                call = ("life_hours", (clock[0] + float(rng.uniform(-7200, 300000)),))  # for some expiry
            else:  # room?
                call = ("has_room", (who,))  # asked
            name, args = call  # the call
            results = []  # what each store gives
            for room in (py, cc):  # both
                try:  # it may raise
                    results.append(("ok", getattr(room, name)(*args)))  # the answer
                except Exception as err:  # noqa: BLE001 - the error is part of the comparison
                    results.append(("error", type(err)))  # the kind of error
            if name == "own_add" and results[0][0] == "ok" and results[0][1] not in numbers:  # a new message
                numbers.append(results[0][1])  # remembered
            assert results[0] == results[1], (run, step, name, args, results)  # the same answer
            assert py.take_news() == cc.take_news(), (run, step, name)  # the same news
            assert json.loads(json.dumps(py.to_dict())) == cc.to_dict(), (run, step, name)  # the same store
            clock[0] += 1.0  # a second passes
        reloaded = CompiledMailroom("Q1AAAA", clock=lambda: clock[0])  # the compiled store reading the Python store's file contents
        reloaded._ask("from_dict", json.loads(json.dumps(py.to_dict())))  # loaded (and tidied)
        py.tidy()  # the same tidy on the reference
        assert json.loads(json.dumps(py.to_dict())) == reloaded.to_dict()  # the same
        other_station = CompiledMailroom("Q9ZZ", clock=lambda: clock[0])  # another station
        assert other_station._ask("from_dict", py.to_dict()) is False  # does not take Q1AAAA's mail


def _station_scenarios(make):  # contacts run with stations made by `make` (PythonStation or CompiledStation); returns everything worth comparing
    """Run a set of contacts and return their events, logs, results and stores, for comparison between the two kinds of station."""
    from link import Path, run_group, run_link  # the simulation
    clock = [1.8e9]  # the mail stores' wall clock

    def station(call, grid, **extra):  # one station on the shared mail clock
        made = make(call, grid, **extra)  # made
        made.mail.clock = lambda: clock[0]  # the shared clock
        made.mail._ask("init", call, 4242) if hasattr(made.mail, "_ask") else setattr(made.mail, "next_id", 4242)  # the same first message number in both runs
        return made  # ready

    def summary(*stations):  # what each station ended with
        return json.dumps([(s.call, s.state, s.log, s.delivered, s.inbox, s.bulletins, s.outbox, s.want, s.tx_level, s.history, s.mail.to_dict()) for s in stations], default=str)  # the lot, as text now (the Python station's lists go on changing)

    out = []  # everything to compare
    a, b = station("Q1AAAA", "EM92"), station("Q2BB", "FN31")  # 1. a plain contact on a fading path, traffic both ways
    a.queue("First message from A. " * 4)  # a longer message
    a.queue("Second, short.")  # and a short one
    b.queue("Reply from B, with a little news.")  # and one back
    a.beacon()  # A calls
    b.listen()  # B answers
    out.append((run_link(a, b, Path(snr_db=-6.0, condition="moderate"), Path(snr_db=-8.0, condition="moderate"), seed=3), summary(a, b)))  # run
    a, b = station("Q1AAAA", "EM92"), station("Q2BB", "FN31")  # 2. a path that fades away mid-contact: resends, slower levels, reacquiring
    a.queue("A message long enough to need several frames at the slow levels, sent while the path fades away. " * 2)  # long
    a.beacon()  # A calls
    b.listen()  # B answers
    out.append((run_link(a, b, Path(snr_db=lambda t: -4.0 if t < 30 else (-15.0 if t < 150 else -32.0), condition="moderate"), Path(snr_db=-5.0), seed=5, limit_s=1800.0), summary(a, b)))  # run
    a, b = station("Q1AAAA", "EM92", close_when_done=False), station("Q2BB", "FN31", close_when_done=False)  # 3. a move to a working frequency, kept open, then idle
    a.can_move = b.can_move = True  # both radios can retune
    a.move_to_hz = 1500  # A proposes +1.5 kHz
    a.queue("On the working frequency now.")  # traffic
    a.beacon()  # A calls
    b.listen()  # B answers
    out.append((run_link(a, b, Path(snr_db=0.0), Path(snr_db=0.0), seed=7, limit_s=900.0), summary(a, b)))  # run
    a, b = station("Q1AAAA", "EM92"), station("Q2BB", "FN31")  # 4. a directed call, a broadcast, a long beacon
    a.broadcast("To everyone: net at 2100Z.")  # a broadcast first
    a.long_beacon()  # and a long beacon
    a.call_station("Q2BB")  # then a call by name
    a.queue("Called you by name.")  # traffic
    b.listen()  # B listens
    out.append((run_link(a, b, Path(snr_db=-2.0), Path(snr_db=-2.0), seed=9, limit_s=1800.0), summary(a, b)))  # run
    origin, carrier, dest = station("Q1AAAA", "EM92"), station("Q2BB", "FN31"), station("Q3CCC", "EM73")  # 5. store and forward: A -> B -> C, receipt back to A
    origin.queue("Hello C, carried by B.", to="Q3CCC")  # mail for C
    for first, second, seed in ((origin, carrier, 11), (dest, carrier, 12), (carrier, origin, 13)):  # A meets B, C meets B, B meets A
        clock[0] += 3600.0  # an hour between contacts
        first.new_contact()  # ready
        second.new_contact()  # ready
        first.beacon()  # calls
        second.listen()  # answers
        out.append((run_link(first, second, Path(snr_db=0.0), Path(snr_db=0.0), seed=seed), summary(origin, carrier, dest)))  # run
    caller = station("Q1AAAA", "EM92")  # 6. one caller, three answering stations: wide windows and random reply slots
    others = [station(call, "FN31") for call in ("Q2BB", "Q3CCC", "Q4DD")]  # the others
    for other in others:  # each
        other.listen()  # answers
        other.queue(f"Traffic from {other.call}.")  # with something to say
    caller.beacon()  # calls
    caller.wide = True  # asking for a wide window from the start (as after an unanswered beacon)
    paths = {other.call: Path(snr_db=-3.0) for other in others}  # easy paths
    out.append((run_group(caller, others, paths, paths, seed=17), summary(caller, *others)))  # run
    a, b = station("Q1AAAA", "EM92"), station("Q2BB", "FN31")  # 7. a call to a station whose operator is not available
    b.available = False  # not taking contacts
    b.listen()  # but listening
    a.call_station("Q2BB")  # called by name
    out.append((run_link(a, b, Path(snr_db=0.0), Path(snr_db=0.0), seed=19, limit_s=600.0), summary(a, b)))  # run
    return out  # everything


def test_station_matches_python():  # the compiled station (interface 10) against link/station.py, contact for contact
    from link.station import CompiledStation, PythonStation  # the two kinds of station
    mine = _station_scenarios(CompiledStation)  # compiled
    ref = _station_scenarios(PythonStation)  # Python
    assert len(mine) == len(ref)  # the same number of runs
    for index, ((events, ends), (ref_events, ref_ends)) in enumerate(zip(mine, ref)):  # each run
        assert len(events) == len(ref_events), (index, len(events), len(ref_events))  # the same number of frames
        for event, ref_event in zip(events, ref_events):  # each frame
            assert json.dumps(event, sort_keys=True, default=str) == json.dumps(ref_event, sort_keys=True, default=str), (index, event, ref_event)  # the same frame, at the same time, with the same outcome (states and levels after it included)
        assert ends == ref_ends, index  # the same logs, results and stores for every station
    assert sum(len(events) for events, _ in mine) > 60  # the runs did real work
