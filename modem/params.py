"""The numbers that define the Kestrel signal and frame format.

They match the specification (sections 4 and 5).
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
FRAME_TYPE_LINK = 0  # header value: a message between two locked stations, marked with their short link number
FRAME_TYPE_ADDRESSED = 1  # header value: a message carrying full destination and origin addresses
CALL_CHARS = 9  # longest callsign or group name, in characters
CALL_BITS = 48  # bits used to send one address
LINK_ID_BITS = 12  # bits of the short link number shared by two locked stations
MSG_ID_BITS = 16  # bits of the message number chosen by the originating station
HOP_BITS = 3  # bits of the relay counter (how many stations have passed the message on)
LIFE_BITS = 5  # bits of the remaining lifetime, counted in units of two hours
LIFE_UNIT_HOURS = 2  # hours per step of the lifetime field
ADDRESS_BITS = {FRAME_TYPE_LINK: LINK_ID_BITS + MSG_ID_BITS, FRAME_TYPE_ADDRESSED: 2 * CALL_BITS + MSG_ID_BITS + HOP_BITS + LIFE_BITS}  # size of the address block at the start of the body: 28 or 120 bits
MAX_PARTS = 8  # a message can be split into at most this many parts (3 bits)

AIRTIME_CAP_S = 60.0  # default longest transmission, in seconds
AIRTIME_POOR_CAP_S = 90.0  # longest transmission allowed when conditions are poor
