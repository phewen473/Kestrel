"""Tests for real band noise in the simulator (sim.NoisePool and tools/make_noise_pool.py, since 0.43)."""

import os  # file paths
import sys  # the tools folder on the import path
import wave  # writes a test recording

import numpy as np  # numerical arrays
import pytest  # test framework

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root
sys.path.insert(0, os.path.join(ROOT, "tools"))  # make the tool importable

import make_noise_pool  # the pool maker  # noqa: E402
from sim import NoisePool, run_channel  # the pool and the channel  # noqa: E402
from sim.channel import FS  # sample rate  # noqa: E402


def _recording(path, rng):  # a made-up receive recording
    """Write 400 s of noise with a loud 'transmission' in the middle (seconds 150 to 200) to `path`."""
    x = 0.01 * rng.standard_normal(400 * FS)  # band noise
    x[150 * FS:200 * FS] += 0.2 * np.sin(2 * np.pi * 1500 * np.arange(50 * FS) / FS)  # a strong tone over it
    with wave.open(str(path), "wb") as w:  # 12 kHz mono 16-bit
        w.setnchannels(1)  # mono
        w.setsampwidth(2)  # 16-bit
        w.setframerate(FS)  # 12 kHz
        w.writeframes((x * 32767).astype("<i2").tobytes())  # the samples


def test_pool_keeps_only_quiet_stretches(tmp_path):  # the loud part is left out
    """The tool keeps the two quiet runs either side of the loud part, each scaled to band power 1."""
    rng = np.random.default_rng(1)  # repeatable
    _recording(tmp_path / "rx.wav", rng)  # the recording
    found = make_noise_pool.quiet_stretches(make_noise_pool.read_wav(str(tmp_path / "rx.wav")), 140)  # its quiet stretches
    assert len(found) == 2  # before and after the loud part
    assert sorted(round(len(s) / FS) for s in found) == [148, 198]  # 0-150 s and 200-400 s, a second trimmed at each end: neither reaches into the loud part
    from scipy import signal  # band filter, for the check
    b, a = signal.butter(4, [250 / (FS / 2), 2750 / (FS / 2)], "band")  # the 2.5 kHz band
    for s in found:  # each stretch
        assert abs(np.mean(signal.lfilter(b, a, s) ** 2) - 1.0) < 0.05  # power 1 in the band


def test_run_channel_with_pool_gives_the_asked_snr(tmp_path, monkeypatch):  # the SNR is right with real noise
    """A tone run through the channel with pool noise sits at the asked SNR in 2.5 kHz."""
    rng = np.random.default_rng(2)  # repeatable
    _recording(tmp_path / "rx.wav", rng)  # the recording
    monkeypatch.setattr(sys, "argv", ["make_noise_pool.py", str(tmp_path / "rx.wav"), "--out", str(tmp_path / "pool"), "--min-run", "140"])  # the command line
    assert make_noise_pool.main() == 0  # the pool made
    pool = NoisePool(str(tmp_path / "pool"))  # opened
    assert pool.seconds > 250  # nearly all of the quiet part
    tone = np.sin(2 * np.pi * 1500 * np.arange(60 * FS) / FS)  # a minute of tone
    y = run_channel(tone, -10.0, np.random.default_rng(3), lead_s=0, tail_s=0, pool=pool)  # at -10 dB
    noise = y - tone  # what was added
    from scipy import signal  # band filter, for the check
    b, a = signal.butter(4, [250 / (FS / 2), 2750 / (FS / 2)], "band")  # the 2.5 kHz band
    snr = 10 * np.log10(np.mean(tone ** 2) / np.mean(signal.lfilter(b, a, noise) ** 2))  # measured SNR in the band
    assert abs(snr - (-10.0)) < 0.5  # as asked


def test_missing_pool_says_how_to_make_one(tmp_path):  # a clear message
    """Opening an empty folder raises FileNotFoundError naming the tool."""
    with pytest.raises(FileNotFoundError, match="make_noise_pool"):  # the message names the tool
        NoisePool(str(tmp_path))  # an empty folder
