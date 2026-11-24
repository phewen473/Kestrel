"""The numbers that define the Kestrel signal and frame format.

They match the specification (sections 4 and 5).
"""

SPEC_VERSION = "0.39"  # the version of docs/spec/kestrel-spec.md that this program follows (a test checks the two agree)
SIGNAL_VERSION = "0.39"  # the specification version in which the on-air behavior last changed (0.39: long notes of up to 64 characters, eight text frames of eight 6-bit characters; 0.38: the long frame's tones five bins apart (4.29 Hz, 137 Hz in all), and power steps before a beacon, announced by the header's spare bit; 0.34: long notes, sent in long-beacon frames with the spare bit set; 0.33: the answer frame carries the sender's grid locator; 0.32: Gray-coded tones, glides between tones at L3 and L4, faded ends; 0.30: the mail notice frame, mail carried and delivered for other stations; 0.23: call-up at L2 first, reply slots sized to the level, directed-call flag; 0.24: a calling station takes a call back as the answer; 0.25: availability; 0.26: the second header copy moved to the end of the frame; 0.27: the long beacon): stations with the same signal version can hear each other
FS = 12000  # audio sample rate, in samples per second
REF_BANDWIDTH_HZ = 2500.0  # bandwidth that all SNR figures are quoted in
RAMP_S = 0.010  # every transmission fades in and out over this long, along a raised cosine (since 0.32), so it starts and stops without a click

CHIRP_F0 = 500.0  # lowest frequency of the chirp pair that began every frame up to spec v0.19 (kept for the comparison study), in Hz
CHIRP_F1 = 2500.0  # highest frequency of the signature chirp, in Hz
CHIRP_SECONDS = 1.0  # length of each sweep (one up, one down), in seconds
CHIRP_SAMPLES = int(CHIRP_SECONDS * FS)  # the same length counted in samples
CHIRP_RAMP_SECONDS = 0.02  # fade-in and fade-out time at each end of a sweep
CHIRP_RATE = (CHIRP_F1 - CHIRP_F0) / CHIRP_SECONDS  # sweep speed, in Hz per second

PREAMBLE_TONES = 12  # every frame starts with this many tones in a pattern fixed for its speed level
PREAMBLE_PATTERNS = (  # the twelve tone numbers that start every frame, one row per speed level
    (12, 5, 27, 9, 24, 31, 19, 8, 2, 18, 1, 30),  # L0
    (25, 14, 5, 0, 16, 3, 8, 22, 4, 19, 31, 9),  # L1
    (30, 6, 15, 3, 18, 28, 5, 27, 10, 0, 24, 31),  # L2
    (17, 3, 8, 28, 21, 15, 29, 13, 2, 9, 1, 12),  # L3
    (9, 15, 7, 12, 25, 16, 5, 17, 24, 6, 0, 30),  # L4
)  # each row: no tone used twice, every jump at least five tones, and no two pairs of positions the same distance apart differ by the same number of tones
LONG_PATTERN = (18, 25, 30, 16, 5, 26, 21, 9, 2, 14, 23, 4)  # the long beacon's own twelve-tone pattern (same rules as the rows above; it starts the long beacon and identifies it)
LONG_LEVEL = 7  # the number the long beacon's level goes by in reports and logs (shown as "LB"; levels 5 and 6 are kept for faster levels)
LONG_SAMPLES = 14000  # samples in one long-beacon tone: 1.167 s
LONG_STEP = 5  # the long frame's tones sit five FFT bins apart: 4.29 Hz, about 137 Hz for all 32 (three bins, 2.57 Hz and 82 Hz, until signal version 0.38: the wider spacing costs nothing on a steady path and gains about 2 dB at 3 Hz of Doppler spread, 6 dB at 4 Hz and 10 dB at 6 Hz)
FRAME_TYPE_LONG = 6  # the frame type the receiver reports for a long beacon (the long beacon has no header; this number is never sent)
M_TONES = 32  # number of different tones every level can send
BITS_PER_SYMBOL = 5  # each tone carries 5 bits, because 2**5 = 32
CENTER_HZ = 1500.0  # the tones of every level are centered near this audio frequency

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
HEADER_REPEAT = 2  # the coded header is sent twice for extra robustness: once after the preamble and once after the body (since signal version 0.26), so one fade cannot take both
FRAME_TYPE_LINK = 0  # header value: a message between two locked stations, marked with their short link number
FRAME_TYPE_ADDRESSED = 1  # header value: a message carrying full destination and origin addresses
CALL_CHARS = 9  # longest callsign or group name, in characters
CALL_BITS = 48  # bits used to send one address
LINK_ID_BITS = 9  # bits of the short link number shared by two locked stations
MSG_ID_BITS = 16  # bits of the message number chosen by the originating station
HOP_BITS = 3  # bits of the relay counter (how many stations have passed the message on)
LIFE_BITS = 5  # bits of the remaining lifetime, counted in units of two hours
LIFE_UNIT_HOURS = 2  # hours per step of the lifetime field
FRAME_TYPE_BEACON = 2  # header value: a beacon announcing a station
FRAME_TYPE_ANSWER = 3  # header value: an answer to a beacon
FRAME_TYPE_ACK = 4  # header value: an acknowledgment of one message frame
FRAME_TYPE_IDENT = 5  # header value: a station identification
FRAME_TYPE_NOTICE = 7  # header value: a mail notice, sent just before a beacon by a station that holds mail or has delivery receipts to report (since 0.30)
HASH_BITS = 16  # bits of a short code standing for a callsign or a message ID in a mail notice
NOTICE_SLOTS = 3  # entries of each list in a mail notice: stations mail is held for, delivery receipts, stations heard
GRID_BITS = 15  # bits of a four-character grid locator
NO_GRID = (1 << GRID_BITS) - 1  # the value an answer sends when its sender has no locator set (all ones; real locators run 0 to 32399)
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
    FRAME_TYPE_ANSWER: 2 * CALL_BITS + GRID_BITS + REPORT_BITS + LEVEL_MASK_BITS + 2,  # two callsigns, the sender's locator (since 0.33), report, levels, two flags: 139 bits
    FRAME_TYPE_ACK: LINK_ID_BITS + MSG_ID_BITS + PART_BITS + ACK_STATUS_BITS + REPORT_BITS,  # link, message, part, verdict, report: 48 bits
    FRAME_TYPE_IDENT: CALL_BITS + LINK_ID_BITS + 4,  # callsign, link number, four flags: 61 bits
    FRAME_TYPE_NOTICE: CALL_BITS + 3 * NOTICE_SLOTS * HASH_BITS,  # callsign, then three lists of three short codes: held for, receipts, heard: 192 bits
}  # end of the table
ADDRESS_BITS = {FRAME_TYPE_LINK: LINK_ID_BITS + LEVEL_BITS + MSG_ID_BITS, FRAME_TYPE_ADDRESSED: 2 * CALL_BITS + MSG_ID_BITS + HOP_BITS + LIFE_BITS}  # size of the address block at the start of the body: 28 or 120 bits
MAX_PARTS = 8  # a message can be split into at most this many parts (3 bits)

AIRTIME_CAP_S = 60.0  # default longest transmission, in seconds
AIRTIME_POOR_CAP_S = 90.0  # longest transmission allowed when conditions are poor
