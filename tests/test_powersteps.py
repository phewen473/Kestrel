"""Power steps before a beacon (signal version 0.38): sending, the header's flag, and reading the steps back."""

import os  # environment, for the pure-Python run
import subprocess  # a second interpreter, without the compiled library
import sys  # this interpreter

import numpy as np  # numerical arrays


def _sounding(snr_db, seed, compress_db=0.0, offset_hz=0.0):  # steps and a beacon with steps, through noise
    """Return (audio heard, sample where the beacon starts): power steps then an L2 beacon from Q1AAAA, at `snr_db`."""
    from modem import build_beacon, powersteps  # the transmitter's parts
    from modem.params import FS  # sample rate
    from sim import run_channel  # the channel simulator
    steps = powersteps.build_steps()  # the four steps
    if compress_db:  # a transmitter in its ALC: the weaker steps come out stronger than they should
        n = len(steps) // len(powersteps.STEP_DB)  # samples per step and gap
        for k in range(1, len(powersteps.STEP_DB)):  # every step after the first
            steps[k * n:(k + 1) * n] *= 10.0 ** (k * compress_db / 20.0)  # raised by that many dB a step
    beacon = build_beacon("Q1AAAA", "EM93", level=2, steps=True)  # the beacon, its header saying steps came first
    lead = 2.0  # quiet before the steps
    heard = run_channel(np.concatenate([steps, beacon]), snr_db, np.random.default_rng(seed), offset_hz=offset_hz, lead_s=lead, tail_s=2.0)  # through noise
    return heard, int(lead * FS) + len(steps)  # the audio, and where the beacon starts


def test_steps_shape():  # four steps, 1 s each with 0.25 s gaps, falling 10 dB a step
    from modem import powersteps  # the steps
    from modem.params import FS  # sample rate
    audio = powersteps.build_steps()  # sent
    assert len(audio) == powersteps.SAMPLES == round(5.0 * FS)  # 5 s
    n = int(round((powersteps.STEP_S + powersteps.GAP_S) * FS))  # one step and its gap
    rms = [np.sqrt(np.mean(audio[k * n:k * n + int(FS * 0.9)] ** 2)) for k in range(4)]  # each step's strength
    assert all(abs(20 * np.log10(rms[k] / rms[k + 1]) - 10.0) < 0.1 for k in range(3))  # 10 dB apart
    assert np.max(np.abs(audio)) <= 1.0  # no louder than the beacon


def test_beacon_flag_round_trip():  # the spare bit says steps came; the receiver reports it, and plain beacons stay plain
    from modem import build_beacon, receive  # transmitter and receiver
    from sim import run_channel  # the channel simulator
    for steps in (True, False):  # with and without
        heard = run_channel(build_beacon("Q1AAAA", "EM93", level=2, steps=steps), -5.0, np.random.default_rng(5))  # a beacon through noise
        result = receive(heard)  # read
        assert result.ok and result.fields["origin"] == "Q1AAAA"  # read back
        assert result.steps is steps  # the flag as sent


def test_only_beacons_may_set_the_flag():  # an answer or acknowledgment with steps makes no sense
    import pytest  # expected failures
    from modem.control import pack_ident  # an identification's fields
    from modem.frame import build_control  # the control-frame transmitter
    from modem.params import FRAME_TYPE_IDENT  # its type
    with pytest.raises(ValueError):  # refused
        build_control(FRAME_TYPE_IDENT, pack_ident("Q1AAAA", 5), 2, steps=True)  # an identification with steps


def test_flag_read_without_the_compiled_library():  # the pure-Python header reader accepts the flag too
    code = ("import numpy as np; from modem import build_beacon, receive, native; from sim import run_channel; "
            "assert not native.available(); r = receive(run_channel(build_beacon('Q1AAAA', 'EM93', level=2, steps=True), -5.0, np.random.default_rng(5))); "
            "assert r.ok and r.steps; print('ok')")  # a beacon with steps, read in pure Python
    env = dict(os.environ, KESTREL_NATIVE="0")  # without the library
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run it
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr  # it worked


def test_steps_read_back_and_fall_evenly():  # a beacon at +2 dB: the first three steps heard, 10 dB apart; the last lost in the noise
    from modem import powersteps, receive  # the steps and the receiver
    heard, start = _sounding(2.0, 38, offset_hz=3.0)  # 3 Hz off; a step is heard down to about -23 dB in 2.5 kHz, so -30 dB (-28) is not
    result = receive(heard)  # the beacon
    assert result.ok and result.steps  # read, with the flag
    reading = powersteps.measure(heard, result.start, result.offset_hz)  # the steps before it
    assert reading is not None  # read
    assert reading.heard == (True, True, True, False)  # 0, -10 and -20 dB heard; -30 dB (about -28 dB in 2.5 kHz) not
    assert abs(reading.snr_db[0] - 2.0) < 2.0  # step 0 arrives at the beacon's strength
    assert reading.even is True and all(8.0 < a < 12.0 for a in reading.apart_db)  # 10 dB apart
    assert reading.lowest_db == -20.0  # the weakest heard
    assert "power follows the drive" in reading.describe()  # said so


def test_compressed_steps_are_flagged():  # a transmitter whose weaker steps come out 5 dB too strong
    from modem import powersteps, receive  # the steps and the receiver
    heard, start = _sounding(-12.0, 7, compress_db=5.0)  # each step 5 dB instead of 10 dB below the last
    result = receive(heard)  # the beacon
    reading = powersteps.measure(heard, result.start, result.offset_hz)  # the steps
    assert reading.even is False  # uneven
    assert "uneven" in reading.describe()  # said so


def test_noise_alone_hears_no_steps():  # no steps sent: nothing heard where they would be
    from modem import powersteps  # the steps
    from modem.params import FS  # sample rate
    rng = np.random.default_rng(1)  # repeatable
    heard_any = 0  # steps "heard" in noise
    for _ in range(20):  # twenty tries
        x = rng.normal(0.0, 1.0, int(7 * FS))  # 7 s of noise
        reading = powersteps.measure(x, int(6 * FS))  # as if a beacon began at 6 s
        heard_any += sum(reading.heard)  # count
    assert heard_any <= 1  # at most one chance hit in 80 steps


def test_too_little_audio_before_the_beacon():  # the audio kept does not reach back 5 s
    from modem import powersteps  # the steps
    assert powersteps.measure(np.zeros(1000), 500) is None  # nothing to read


def test_station_sends_steps_before_its_beacon():  # both stations: the beacon carries the flag and the steps go first
    from link.station import CompiledStation, PythonStation  # the two stations
    from modem import native, powersteps, receive  # the steps and the receiver
    kinds = [PythonStation] + ([CompiledStation] if native.available() else [])  # the compiled one when the library is in use
    for kind in kinds:  # each
        station = kind("Q1AAAA", "EM93")  # a station
        station.power_steps = True  # steps wanted
        station.beacon()  # become the calling station
        tx = station.poll(0.0)  # its first beacon
        assert tx is not None and tx.kind == "beacon"  # a beacon
        assert tx.lead is not None and len(tx.lead) == powersteps.SAMPLES  # with the steps first
        assert len(tx.on_air()) == len(tx.lead) + len(tx.audio)  # both go out
        assert "power steps first" in tx.note  # said in the log
        heard = receive(np.concatenate([np.zeros(6000), tx.audio, np.zeros(6000)]))  # the frame alone
        assert heard.ok and heard.steps  # its header says steps came first
        station.power_steps = False  # and without
        station2 = kind("Q1AAAA", "EM93")  # a fresh station
        station2.beacon()  # calling
        tx2 = station2.poll(0.0)  # a plain beacon
        assert tx2.lead is None and not receive(np.concatenate([np.zeros(6000), tx2.audio, np.zeros(6000)])).steps  # no steps, no flag


def test_listener_reads_steps_from_a_sound_card_stream():  # fed in pieces as a sound card would: the beacon arrives with its steps read
    from live.listener import Listener  # the continuous receiver
    from modem import native  # whether the compiled receiver is in use
    heard_audio, _ = _sounding(0.0, 11)  # steps and a beacon at 0 dB
    for compiled in ([False, True] if native.available() else [False]):  # both receivers
        listener = Listener(compiled=compiled)  # a fresh one
        found = []  # frames handed over
        for i in range(0, len(heard_audio), 1200):  # a tenth of a second at a time
            found += listener.feed(heard_audio[i:i + 1200])  # fed
        beacons = [h for h in found if h.result.ok and h.result.steps]  # the beacon with steps
        assert beacons, f"no beacon found (compiled={compiled})"  # found
        reading = beacons[0].result.power_steps  # what was read of its steps
        assert reading is not None and reading.heard[:2] == (True, True)  # the first two steps heard at least
