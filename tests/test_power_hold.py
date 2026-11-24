"""Tests: holding the output power by the drive, spotting a sag, and keeping the sample count in step with the clock after transmitting (since 0.40R1)."""
import numpy as np  # arrays

from live import power_hold  # the drive control
from live.recorder import TimedSource  # the counting source
from modem.params import FS  # sample rate


def test_off_when_blank():  # no power named: nothing changes
    assert power_hold.next_gain(0.1, 10.0, 0.1, "") == (None, "") and power_hold.next_gain(0.1, 10.0, 0.1, "0") == (None, "")  # blank or zero is off


def test_raises_and_lowers_by_the_square_root():  # power goes as the square of the drive
    new, _ = power_hold.next_gain(0.100, 30.0, 0.1, "40")  # low
    assert abs(new - 0.100 * (40 / 30) ** 0.5) < 0.001  # raised by the square root of the ratio
    new, _ = power_hold.next_gain(0.100, 10.0, 0.1, "40")  # far too low
    assert abs(new - 0.100 * 10 ** (2 / 20)) < 0.001  # but only 2 dB a step
    new, _ = power_hold.next_gain(0.200, 70.0, 0.1, "40")  # too high
    assert new < 0.200  # lowered
    assert power_hold.next_gain(0.100, 41.0, 0.1, "40") == (None, "")  # within 10 %: left alone


def test_never_up_into_alc():  # more drive with ALC high only distorts
    new, why = power_hold.next_gain(0.200, 20.0, 0.9, "40")  # low power but ALC nearly full
    assert new < 0.200 and "ALC" in why  # backed off, with the reason
    new, _ = power_hold.next_gain(0.200, 70.0, 0.9, "40")  # over power with ALC high
    assert new < 0.200  # lowered as usual


def test_sag_reported():  # the on-air case: 22 W falling to 10 W
    falling = [(22.0 - k, 0.1) for k in range(12)]  # 22 W down to 11 W
    assert power_hold.sag(falling) == (21.0, 13.0)  # the first and last thirds' medians
    assert power_hold.sag([(20.0, 0.1)] * 12) is None and power_hold.sag(falling[:4]) is None  # steady, or too short to judge


class _Card:  # a sound card that delivers less audio than time passed
    def __init__(self):  # nothing yet
        self.waiting = np.zeros(0)  # audio to hand over

    def read(self):  # hand it over
        chunk, self.waiting = self.waiting, np.zeros(0)  # all of it
        return chunk  # the audio

    def flush(self):  # drop it
        self.waiting = np.zeros(0)  # gone


def test_count_made_good_after_a_transmission():  # the audio-clock jumps seen on the air
    now = [1000.0]  # a clock the test moves
    card = _Card()  # the card
    source = TimedSource(card, clock=lambda: now[0])  # counting
    card.waiting = np.zeros(FS)  # one second arrives
    now[0] += 1.0  # as one second passes
    source.read()  # counted
    card.waiting = np.zeros(int(59.75 * FS))  # during a 60 s transmission only 59.75 s arrive
    now[0] += 60.0  # sixty seconds pass
    source.flush()  # after the transmission
    assert source.samples == 61 * FS and source.gaps == 1 and abs(source.last_gap_s - 0.25) < 0.001  # the quarter second is made good
    assert abs(source.utc_of(source.samples) - now[0]) < 0.001  # numbers and clock agree again
    card.waiting = np.zeros(FS)  # a normal second
    now[0] += 1.0  # passes
    source.flush()  # and a flush with nothing missing
    assert source.gaps == 1  # changes nothing
