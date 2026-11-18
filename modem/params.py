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
FRAME_TYPE_BEACON = 2  # header value: a beacon announcing a station
FRAME_TYPE_ANSWER = 3  # header value: an answer to a beacon
FRAME_TYPE_ACK = 4  # header value: an acknowledgment of one message frame
FRAME_TYPE_IDENT = 5  # header value: a station identification
GRID_BITS = 15  # bits of a four-character grid locator
LEVEL_MASK_BITS = 8  # one bit per speed level 0 to 7, listing the levels a station can use
LEVEL_BITS = 3  # bits of a speed level number
PART_BITS = 3  # bits of a part number
ACK_STATUS_BITS = 2  # bits of the verdict in an acknowledgment
SNR_BITS = 6  # bits of the SNR in a channel report
SNR_FLOOR_DB = -30  # the SNR that is sent as 0; each step above it is 1 dB
FADE_BITS = 3  # bits of the fading index in a channel report
FADE_STEPS_PER_UNIT = 4  # the fading index is sent in quarters
OFFSET_BITS = 6  # bits of the frequency offset in a channel report
OFFSET_STEP_HZ = 2  # the frequency offset is sent in steps of 2 Hz
REPORT_BITS = SNR_BITS + FADE_BITS + OFFSET_BITS + LEVEL_BITS  # a whole channel report: 18 bits
CONTROL_BITS = {  # body length of each control frame, before its check value
    FRAME_TYPE_BEACON: CALL_BITS + GRID_BITS + LEVEL_MASK_BITS + 4,  # callsign, locator, levels, four flags: 75 bits
    FRAME_TYPE_ANSWER: 2 * CALL_BITS + REPORT_BITS + LEVEL_MASK_BITS + 2,  # two callsigns, report, levels, two flags: 124 bits
    FRAME_TYPE_ACK: LINK_ID_BITS + MSG_ID_BITS + PART_BITS + ACK_STATUS_BITS + REPORT_BITS,  # link, message, part, verdict, report: 51 bits
    FRAME_TYPE_IDENT: CALL_BITS + LINK_ID_BITS + 4,  # callsign, link number, four flags: 64 bits
}  # end of the table
ADDRESS_BITS = {FRAME_TYPE_LINK: LINK_ID_BITS + MSG_ID_BITS, FRAME_TYPE_ADDRESSED: 2 * CALL_BITS + MSG_ID_BITS + HOP_BITS + LIFE_BITS}  # size of the address block at the start of the body: 28 or 120 bits
MAX_PARTS = 8  # a message can be split into at most this many parts (3 bits)

AIRTIME_CAP_S = 60.0  # default longest transmission, in seconds
AIRTIME_POOR_CAP_S = 90.0  # longest transmission allowed when conditions are poor
