"""Prototype numbers for the Kestrel modem.

These are starting values for testing, not final design decisions.
The specification keeps them as TBD until the tests back them up.
"""

FS = 12000  # audio sample rate, in samples per second
REF_BANDWIDTH_HZ = 2500.0  # bandwidth that all SNR figures are quoted in

CHIRP_F0 = 500.0  # lowest frequency of the signature chirp, in Hz
CHIRP_F1 = 2500.0  # highest frequency of the signature chirp, in Hz
CHIRP_SECONDS = 1.0  # length of each sweep (one up, one down), in seconds
CHIRP_SAMPLES = int(CHIRP_SECONDS * FS)  # the same length counted in samples
CHIRP_RAMP_SECONDS = 0.02  # fade-in and fade-out time at each end of a sweep
CHIRP_RATE = (CHIRP_F1 - CHIRP_F0) / CHIRP_SECONDS  # sweep speed, in Hz per second

M_TONES = 32  # number of different tones the L0 waveform can send
BITS_PER_SYMBOL = 5  # each tone carries 5 bits, because 2**5 = 32
SYMBOL_SAMPLES = 4800  # samples in one tone (0.4 seconds at 12 kHz)
SYMBOL_SECONDS = SYMBOL_SAMPLES / FS  # the same tone length in seconds
BIN_HZ = FS / SYMBOL_SAMPLES  # width of one FFT bin for a tone-length block (2.5 Hz)
TONE_STEP_BINS = 2  # tones sit two bins apart (5 Hz), leaving a quiet bin between
BASE_BIN = 568  # FFT bin of the lowest tone (568 x 2.5 Hz = 1420 Hz)

PILOT_EVERY = 15  # one known pilot tone is sent before every 15 data tones
PILOT_STEP = 7  # pilot number g uses tone (7 * g + 3) mod 32
PILOT_START = 3  # tone used by the very first pilot

SIZE_CLASSES = (50, 100, 200)  # the three message sizes, in characters
LENGTH_BITS = 8  # bits used to say how many characters the message really has
CHAR_BITS = 7  # bits per character (7-bit ASCII)
BODY_CRC_BITS = 16  # check bits at the end of the message body

HEADER_FIELD_BITS = 8  # frame type (3) + speed level (3) + size class (2)
HEADER_CRC_BITS = 8  # check bits at the end of the header
HEADER_REPEAT = 2  # the coded header is sent twice for extra robustness
FRAME_TYPE_MESSAGE = 0  # header value meaning "this frame carries a message"
