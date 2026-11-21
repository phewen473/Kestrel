"""The family of speed levels.

Every level sends the same 32 tones; a faster level simply sends each tone
for a shorter time. Halving the tone time halves the airtime, and costs
3 dB of sensitivity, because each tone then carries half the energy.
"""

from dataclasses import dataclass  # simple record type

import numpy as np  # numerical arrays

from .params import CENTRE_HZ, FS, M_TONES  # shared waveform numbers


@dataclass(frozen=True)  # a fixed record that cannot be changed by accident
class Level:  # one speed level
    """The numbers that define one speed level."""

    number: int  # the level's number (0 is the slowest and most robust)
    samples: int  # audio samples in one tone
    step: int  # how many FFT bins apart neighbouring tones sit

    @property  # computed from the fields above
    def seconds(self):  # tone length in seconds
        """Length of one tone, in seconds."""
        return self.samples / FS  # samples divided by the sample rate

    @property  # computed from the fields above
    def bin_hz(self):  # width of one FFT bin
        """Width of one FFT bin for a tone-length block, in Hz."""
        return FS / self.samples  # the sample rate divided by the block length

    @property  # computed from the fields above
    def base_bin(self):  # where the lowest tone sits
        """FFT bin of the lowest tone, chosen so the 32 tones straddle 1500 Hz."""
        return int(CENTRE_HZ / self.bin_hz + 0.5) - self.step * M_TONES // 2  # centre bin, minus half the width of the tone block

    @property  # computed from the fields above
    def tone_bins(self):  # where all 32 tones sit
        """FFT bin of each of the 32 tones."""
        return self.base_bin + self.step * np.arange(M_TONES)  # evenly spaced from the lowest tone up


def level_name(number):  # how a level is shown to people
    """Return a level's name as shown in logs and lists: L0 to L4, or LB for the long beacon (signal version 0.27); "?" for none."""
    from .params import LONG_LEVEL  # the long beacon's level number
    if number == LONG_LEVEL:  # the long beacon
        return "LB"  # its own name
    return f"L{number}" if number is not None and number >= 0 else "?"  # an ordinary level, or none


LEVELS = (  # the levels built so far: (number, samples per tone, tone spacing in bins)
    Level(0, 4800, 2),  # L0: 0.4 s tones, 5 Hz apart, about 160 Hz wide
    Level(1, 1620, 2),  # L1: 0.135 s tones, 15 Hz apart, about 470 Hz wide (200 characters in under 90 s)
    Level(2, 1080, 2),  # L2: 0.09 s tones, 22 Hz apart, about 710 Hz wide (200 characters in under 60 s)
    Level(3, 540, 1),  # L3: 0.045 s tones, 22 Hz apart, about 710 Hz wide
    Level(4, 270, 1),  # L4: 0.0225 s tones, 44 Hz apart, about 1420 Hz wide
)  # end of the table

MIN_SNR_DB = (-20.0, -16.0, -14.0, -11.0, -8.0)  # weakest SNR (2.5 kHz, noise only) at which every test frame decoded, per level (re-measured with the tone-pattern preamble: L3 and L4 each lost 1 dB, one frame in forty failing at the old figure)
MIN_SNR_FADING_DB = (-8.0, -2.0, -8.0, -1.0, 0.0)  # weakest SNR at which nine test frames in ten decoded in the worst of light, moderate and heavy fading, per level (re-measured for 0.26 with 40 frames a point; light, slow fading is the worst case: a preamble faded away entirely loses the frame, and retries recover it)
FADE_INDEX_LIMIT = 0.15  # a received frame whose fading index is above this counts as "fading"
