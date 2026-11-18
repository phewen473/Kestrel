"""Prototype numbers for the Kestrel modem.

The chirp pair is agreed and in the specification. The other numbers are
test values; the specification keeps them as TBD until they are agreed.
"""

FS = 12000  # audio sample rate, in samples per second
REF_BANDWIDTH_HZ = 2500.0  # bandwidth that all SNR figures are quoted in

CHIRP_F0 = 500.0  # lowest frequency of the signature chirp, in Hz
CHIRP_F1 = 2500.0  # highest frequency of the signature chirp, in Hz
CHIRP_SECONDS = 1.0  # length of each sweep (one up, one down), in seconds
CHIRP_SAMPLES = int(CHIRP_SECONDS * FS)  # the same length counted in samples
CHIRP_RAMP_SECONDS = 0.02  # fade-in and fade-out time at each end of a sweep
CHIRP_RATE = (CHIRP_F1 - CHIRP_F0) / CHIRP_SECONDS  # sweep speed, in Hz per second

M_TONES = 32  # number of different tones every level can send
BITS_PER_SYMBOL = 5  # each tone carries 5 bits, because 2**5 = 32
CENTRE_HZ = 1500.0  # the tones of every level are centred near this audio frequency

PILOT_EVERY = 15  # one known pilot tone is sent before every 15 data tones
PILOT_STEP = 7  # pilot number g uses tone (7 * g + 3) mod 32
PILOT_START = 3  # tone used by the very first pilot

SIZE_CLASSES = (50, 100, 150, 200)  # the four frame sizes, in plain (uncompressed) characters
MAX_CHARS = 200  # longest message, in characters
LENGTH_BITS = 8  # bits used to say how many characters the frame really carries
CHAR_BITS = 7  # bits per character (7-bit ASCII)
BODY_CRC_BITS = 16  # check bits at the end of the message body

HEADER_FIELD_BITS = 16  # frame type (3) + level (3) + size class (2) + part number (3) + part count (3) + compressed (1) + spare (1)
HEADER_CRC_BITS = 8  # check bits at the end of the header
HEADER_REPEAT = 2  # the coded header is sent twice for extra robustness
FRAME_TYPE_MESSAGE = 0  # header value meaning "this frame carries a message or a part of one"
MAX_PARTS = 8  # a message can be split into at most this many parts (3 bits)

AIRTIME_CAP_S = 60.0  # default longest transmission, in seconds
AIRTIME_POOR_CAP_S = 90.0  # longest transmission allowed when conditions are poor
