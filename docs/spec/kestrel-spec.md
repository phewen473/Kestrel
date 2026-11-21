# Kestrel Technical Description

**Version 0.28 (draft), 21 November 2026.** In first on-air tests since 18 November 2026. Version 0.28 changes only how long beacons are received (Section 5.9); nothing sent has changed. **Signal version 0.27:** a new frame, the long beacon (Sections 5.9 and 6.13), heard well below the other levels. Stations following 0.26 do not hear long beacons; everything else is unchanged from 0.26, in which the second copy of the header moved to the end of every frame (Section 5.1), so stations following 0.25 or earlier cannot exchange frames with 0.26 and 0.27 stations. Earlier changes: the call-up in 0.23 (beacon and answer tried first at L2, reply slots sized to the beacon's level, a directed-call flag in the answer frame), 0.24 (a calling station takes a call back as the answer) and 0.25 (availability: presence beacons and the "not available" reply). Values marked **TBD** are placeholders that will be fixed before the first on-air test.

This document is the public technical description of the Kestrel digital mode under FCC rule 97.309(a)(4). It will be updated, with a new version number, whenever the transmitted signal changes.

© 2026 P. H. Ewen (KO4WSC). Licensed under Creative Commons Attribution 4.0 International (see `docs/LICENSE-CC-BY-4.0.txt`). Any reuse or adaptation must credit the original Kestrel project, https://github.com/phewen473/Kestrel, and state what was changed.

## 1. Purpose

Kestrel carries short free-text messages over HF radio between amateur stations. It adapts its speed to the radio path as conditions change and is built to keep a working link in weak, fading and noisy conditions.

## 2. Regulatory summary (United States)

- **Emission:** data, sent as audio tones through a single-sideband transmitter.
- **Bandwidth:** every Kestrel waveform stays within 2.8 kHz on HF.
- **Content:** plain text. Kestrel never encrypts or obscures message meaning (97.113). Message signing to prove the sender may be added later; it does not hide content.
- **Identification:** every beacon, connection frame and fully addressed message frame carries the sending or originating station's callsign in plain form (Section 4.2). Frames exchanged inside a lock carry only a short link number, so a locked station also sends an identification frame (Section 5.8) at least every 10 minutes and at the end of the contact (97.119).
- **Automatic operation:** unattended relays and mail holders are subject to the message-forwarding and automatic-control rules (97.219, 97.221). A station that holds and delivers mail with no operator present operates under 97.221(b): on HF it stays within the segments that paragraph lists (28.120-28.189, 24.925-24.930, 21.090-21.100, 18.105-18.110, 14.0950-14.0995, 14.1005-14.112, 10.140-10.150, 7.100-7.105 and 3.585-3.600 MHz), or it uses the 6 m and shorter bands. Paragraph (c), which allows unattended replies elsewhere, is limited to 500 Hz. From version 0.20 a frame is no wider than its tones: about 160 Hz at L0 and 470 Hz at L1, but 710 Hz at L2 and L3 and 1420 Hz at L4. Whether a station held to L0 and L1 could operate under paragraph (c) has not been reviewed, and until it has, unattended stations keep to paragraph (b). A station with an operator at the controls is not limited to those segments. This is the author's reading of the rule as published at ecfr.gov; ARRL has been asked to review it and has not yet replied.

## 3. Layers

| Layer | Job |
|---|---|
| 1. Modem | Turns frames into audio and back: waveforms, sync, error correction, tracking. |
| 2. Link | Beacon, answer, negotiation, lock, acknowledgments, speed changes. |
| 3. Net | Optional multi-station nets: net control, turn-taking, backup net control. |
| 4. Messaging | Message format, IDs, mailboxes, relays, receipts. |
| 5. Station | Radio control, audio, time keeping, operator program. |

## 4. Character set and payload

- 7-bit ASCII (values 0-127), including control characters.
- Maximum 200 characters per message.
- Four frame sizes (size classes). The sender uses the smallest class that holds the text.
- **Body contents**, in order: an address block (Section 4.2), the character count (8 bits), the text bits padded with zeros to fill the frame, and a 16-bit check value over everything before it. The body holds 402, 752, 1102 or 1452 bits, whichever kind of frame it is.
- **Room for text.** A link frame (28-bit address block) holds 350, 700, 1050 or 1400 text bits: 50, 100, 150 or 200 characters of plain text at 7 bits each. A fully addressed frame (120-bit address block) holds 92 fewer: 258, 608, 958 or 1308 text bits, which is 36, 86, 136 or 186 plain characters. A longer message is sent compressed if that makes it fit, and otherwise split into parts (Section 6.8).
- **Body check value:** CRC-16 with polynomial 0x1021, start value 0xFFFF, no bit reversal and no final inversion (CRC-16/CCITT-FALSE), most significant bit first.

### 4.1 Text compression

Text may be sent plain (7 bits per character, most significant bit first) or compressed. A flag in the header says which.

- The compressed form is a fixed Huffman code: each ASCII character has a code of 3 to 13 bits, short for common characters (space 3 bits, "e" and "t" 4 bits) and long for rare ones. The code length and code of every character are listed in `tables/compression_codes.txt`.
- The codes follow from the lengths by the canonical rule: sort the characters by (code length, character number); the first gets code 0; each next character gets the previous code plus one, shifted left by the increase in length. Codes are sent most significant bit first.
- The character count in the body tells the receiver how many characters to decode; the padding after them is ignored.
- **Rule for the sender:** compress only when the compressed text fits a smaller size class than the plain text. Otherwise send plain.

Typical savings are about a quarter for plain English and about a seventh for traffic that is mostly capitals and digits.

### 4.2 Addresses and message numbers

Every message frame starts its body with an address block. The frame type in the header (Section 5.4) says which of the two kinds it is.

**Link frame (frame type 0): 28 bits.** Used between two stations that hold a lock.

| Field | Bits | Meaning |
|---|---|---|
| Link number | 9 | Identifies the pair of locked stations |
| Wanted level | 3 | The speed level the sending station asks its partner to use |
| Message number | 16 | The originating station's number for this message |

**Fully addressed frame (frame type 1): 120 bits.** Used for traffic outside a lock and for mail that is being held, relayed or delivered for another station.

| Field | Bits | Meaning |
|---|---|---|
| Destination | 48 | Callsign of the station the message is for, or a group name |
| Origin | 48 | Callsign of the station that wrote the message |
| Message number | 16 | The originating station's number for this message |
| Hops | 3 | How many stations have relayed the message so far |
| Lifetime | 5 | How long the message may still be kept, in units of 2 hours, rounded up (0 to 62 hours) |

- **Address coding.** An address is 1 to 9 characters from this 39-character alphabet, numbered from 0: space, A to Z, 0 to 9, "/", "-". It is written in capitals, padded on the right with spaces to 9 characters, and read as a 9-digit number in base 40 with the first character as the most significant digit. That number is sent as 48 bits, most significant bit first. Digit value 39 is not used; spaces appear only as padding.
- **Group names.** An address that contains no digit is a group or net name, not a station; every amateur callsign contains a digit. "ALL" addresses every station.
- **Message number.** The originating station numbers its messages 0 to 65535 in turn and starts again at 0. The origin callsign and the message number together are the message ID. Every part of a split message carries the same message number.
- **Link number.** The lowest 9 bits of the CRC-16 (Section 4) of the 96 address bits of the two stations: first the station that beaconed, then the station that answered. A station ignores link frames whose link number is not that of its own lock.

## 5. Modem

All audio figures assume a sample rate of 12,000 samples per second.

### 5.1 Frame structure

Every frame has four parts, in order:

1. **Preamble:** twelve tones of the frame's own speed level, at that level's tone length, in a fixed pattern that belongs to the level (table below). The preamble is used to find the frame, to measure its timing and frequency offset, and to tell the receiver which level the frame is sent at. It is as narrow as the rest of the frame and lasts twelve tone lengths: 4.8 s at L0, 1.62 s at L1, 1.08 s at L2, 0.54 s at L3 and 0.27 s at L4.
2. **Header:** 12 tones sent at the same speed level as the body (Section 5.4).
3. **Body:** the payload at the frame's speed level, with known pilot tones spread through it (Section 5.5).
4. **Header again:** the same 12 header tones, repeated after the body.

Sending the header at both ends means one fade cannot remove both copies. The receiver reads the first copy; if it does not pass its check, the receiver reads the second copy at the end of each possible body length, adds its soft bits to the first copy's (and also tries it alone), and accepts a header only when its fields give the body length it was read at. Until version 0.25 the two copies were sent back to back after the preamble, and in simulated fading one fade often removed both, losing 15 to 40 percent of frames even at strong signal levels.

Preamble patterns (tone numbers 0 to 31, in the order sent; tone frequencies are in Section 5.2):

| Level | Pattern |
|---|---|
| L0 | 12, 5, 27, 9, 24, 31, 19, 8, 2, 18, 1, 30 |
| L1 | 25, 14, 5, 0, 16, 3, 8, 22, 4, 19, 31, 9 |
| L2 | 30, 6, 15, 3, 18, 28, 5, 27, 10, 0, 24, 31 |
| L3 | 17, 3, 8, 28, 21, 15, 29, 13, 2, 9, 1, 12 |
| L4 | 9, 15, 7, 12, 25, 16, 5, 17, 24, 6, 0, 30 |

In each pattern no tone is used twice, every jump from one tone to the next is at least five tones, and no two pairs of positions the same distance apart differ by the same number of tones, so a pattern cannot be mistaken for a copy of itself shifted in time and frequency.

The receiver is not told the level in advance. It searches for all five patterns. For each pattern it adds up the energy where each of the twelve tones should be, for every start time and frequency error, and ranks the candidates by that total multiplied by the square of the share of the energy in those twelve tone lengths that the pattern's tones hold. A real preamble puts nearly all its energy where the pattern says, while chance matches inside a strong frame's body do not, so the ranking keeps a real preamble ahead of them even when the preamble itself is faded. (This ranking is a receiver choice, not part of the signal; it was added in version 0.26 after simulation showed body matches outranking faded preambles.) A level is a candidate when its pattern is found, the header that follows passes its check, the header's level field names that same level, and the spare bit is zero. Noise can occasionally pass all of these, so the receiver accepts a frame only when the body also passes its check. Sending the preamble and header at the frame's own level keeps fast frames short and slow frames narrow.

Until version 0.19 every frame instead began with a two-second chirp pair sweeping 500 to 2500 Hz. Frames of version 0.20 and later cannot be read by earlier versions, nor earlier frames by these.

Because the header states the level and size, the receiver then knows how long the frame is and how to decode it. No global time slots are needed.

### 5.2 Speed levels

Every level uses the same signalling: 32 tones, one tone at a time, each tone carrying 5 bits (multiple-tone frequency-shift keying, MFSK). Tone signalling does not depend on carrier phase and holds up in fading. A faster level sends each tone for a shorter time.

- A group of 5 bits, read most significant bit first, is the tone number 0 to 31.
- Tone number m of a level is a cosine at frequency (lowest tone + m x tone spacing), starting at phase zero, lasting one tone length at constant amplitude. Every tone holds a whole number of cycles, so the phase is continuous from tone to tone.

| Level | Tone length | Samples per tone | Lowest tone | Tone spacing | Highest tone |
|---|---|---|---|---|---|
| L0 | 0.4 s | 4800 | 1420.00 Hz | 5.000 Hz | 1575.00 Hz |
| L1 | 0.135 s | 1620 | 1266.67 Hz | 14.815 Hz | 1725.93 Hz |
| L2 | 0.09 s | 1080 | 1144.44 Hz | 22.222 Hz | 1833.33 Hz |
| L3 | 0.045 s | 540 | 1155.56 Hz | 22.222 Hz | 1844.44 Hz |
| L4 | 0.0225 s | 270 | 800.00 Hz | 44.444 Hz | 2177.78 Hz |

Exact values: with N samples per tone, one bin is 12000 / N Hz. The tone spacing is 2 bins for L0 to L2 and 1 bin for L3 and L4. The lowest tone is at bin floor(1500 x N / 12000 + 0.5) minus 16 times the spacing in bins.

Airtime of a whole frame, and the weakest signal each level needs in simulation (SNR in 2.5 kHz):

| Level | 50 chars | 100 chars | 150 chars | 200 chars | Weakest SNR, steady signal | Weakest SNR, fading signal |
|---|---|---|---|---|---|---|
| L0 | 83 s | 143 s | 203 s | 262 s | -20 dB | -8 dB |
| L1 | 28 s | 48 s | 68 s | 89 s | -16 dB | -2 dB |
| L2 | 19 s | 32 s | 46 s | 59 s | -14 dB | -8 dB |
| L3 | 9.4 s | 16 s | 23 s | 30 s | -11 dB | -1 dB |
| L4 | 4.7 s | 8.1 s | 11 s | 15 s | -8 dB | 0 dB |

The column headings are the size classes, named by the plain characters a link frame holds. Exact airtime is the tone length times (12 preamble tones + 12 header tones + 172, 322, 471 or 620 body tones + 12 header tones).

- **Steady signal:** noise only; every test frame decoded at this SNR.
- **Fading signal:** nine test frames in ten decoded at this SNR in the worst of three simulated HF paths (light, moderate and heavy fading, ITU-R F.1487), 40 frames a point, with no stronger point falling below 34 in 40. The remaining frames are recovered by combining retries (Section 5.6). Light fading is the hardest case at every level: its fades are slow, so one fade can cover a whole preamble, and in 1 to 4 frames in 40 the frame is missed even on strong signals. With 40 frames a point the limits carry about 2 dB of sampling uncertainty, which is why they do not fall evenly from L0 to L4 (measured 21 November 2026).

A station chooses the fastest level whose limit, for the kind of signal it is measuring (Section 5.7), is at least 2 dB below the measured SNR. These limits guide the choice; they do not change the signal, and they will be revised after on-air tests.

L1 and L2 are sized so that a full 200-character frame fits the 90-second and 60-second limits of Section 6.8. Frames longer than those limits are not sent; at the slow levels a long message is split into shorter parts instead.

A faster level (L5) is planned. It needs a different waveform, because tones this short would be too wide: **TBD**.

### 5.3 Error correction and interleaving

**Body.** The body is protected by a rate-1/2 low-density parity-check (LDPC) code of the repeat-accumulate kind. For k body bits (k = 402, 752, 1102 or 1452) the codeword is the k body bits followed by k parity bits.

- There are k parity checks. Every body bit takes part in exactly three checks. Parity bit i takes part in check i and in check i + 1 (the last parity bit only in the last check).
- So parity bit 0 equals the XOR of the body bits in check 0, and parity bit i equals parity bit i - 1 XOR the body bits in check i.
- The three checks of each body bit are listed, for every k, in `tables/ldpc_checks_k<k>.txt`. They come from three pseudo-random shuffles of 0..k-1 made with the xorshift32 generator (shifts 13, 17, 5; start values 0x4B455301, 0x4B455302, 0x4B455303) and a Fisher-Yates shuffle, then repaired so that no body bit uses the same or neighbouring checks twice and no two body bits share more than one check. The reference program `modem/ldpc.py` is the exact definition; the table files are its output.

**Interleaver.** The codeword is padded with zeros to a whole number of tones (805, 1505, 2205 or 2905 bits) and shuffled: bit i of the padded codeword is sent in position (step x i) mod n, where n is the padded length and step is the whole number nearest to n x 0.6180339887 that shares no factor with n (searching outwards, above before below). The steps are 498, 929, 1363 and 1796. The shuffled bits are then grouped in fives to make the data tones.

**Receiver side.** Impulse noise (static crashes) is detected and blanked before decoding. The decoder is not specified; the reference uses normalised min-sum belief propagation.

### 5.4 Header

The header carries 16 field bits followed by an 8-bit check value:

| Field | Bits | Meaning |
|---|---|---|
| Frame type | 3 | 0 = message in a link frame; 1 = message in a fully addressed frame (Section 4.2); 2 = beacon; 3 = answer; 4 = acknowledgment; 5 = identification (Section 5.8); 6 and 7 reserved (6 is never sent: receivers use it to report a long beacon, which has no header, Section 5.9) |
| Speed level | 3 | 0 to 4 |
| Size class | 2 | 0 to 3 (body of 402, 752, 1102 or 1452 bits) |
| Part number | 3 | 0 for the first part |
| Part count | 3 | number of parts minus one |
| Compressed | 1 | 1 when the text is compressed |
| Spare | 1 | always 0 |

In control frames (types 2 to 5) the size class, part number, part count and compressed fields are sent as 0.

- **Header check value:** CRC-8 with polynomial 0x07 and start value 0x00 over the 16 field bits, most significant bit first.
- **Header coding:** the 24 bits are followed by 6 zero bits and encoded with the rate-1/2, constraint-length-7 convolutional code with generators 171 and 133 (octal), giving 60 bits, sent as 12 tones. For each input bit the 7-bit register is the six previous input bits (oldest in the highest position) followed by the new bit; the first output bit is the parity of the register ANDed with 171 octal, the second with 133 octal.
- The 12 tones are sent twice: right after the preamble, and again right after the body (Section 5.1).
- Addresses and the message number are carried at the start of the body (Section 4.2), where they have the body's stronger error correction.

### 5.5 Pilots

In the body, one pilot tone is sent before every 15 data tones (so body tones 0, 16, 32, ... are pilots). Pilot number g, counting from 0, uses tone (7 x g + 3) mod 32. The receiver uses the pilots to follow frequency drift through the frame and to measure the signal-to-noise ratio.

### 5.6 Combining retries (HARQ)

When a frame fails its check, the receiver keeps the soft values of the body. The retransmission is combined with the stored copy, so the pair can decode below the level either copy could alone.

### 5.7 Tracking and channel measurement

- The preamble gives the starting frequency offset and timing.
- The pilots keep the frequency estimate current through the body.
- Stations keep accurate clocks (NTP or GPS); this narrows the timing search but is not used to define time slots.

Each received frame yields three measurements, which are reported back to the sender in every acknowledgment:

- **Frequency offset**, from the preamble and the pilots.
- **Signal-to-noise ratio (SNR)** in 2.5 kHz. Once a frame has decoded, the receiver knows every tone that was sent. The signal energy is the average, over all body tones, of the energy at the sent tone plus the bin on each side of it, less the noise in those three bins. The side bins are included because fast fading moves part of a tone's energy into them. The noise is taken from the tone positions that were not sent.
- **Fading index.** The spread (variance) of those per-tone energies, less the spread that noise alone would cause, divided by the square of the average signal energy. It is close to 0 for a steady signal and close to 1 for a signal that fades deeply and often during the frame. A frame with an index above 0.15 counts as a fading signal when choosing a level (Section 5.2).

When a frame fails its check, the same measurements are made from the pilot tones alone.

Measurements of Doppler spread (fading speed) and delay spread (multipath) are planned.

**Following the noise (receiver practice, version 0.28).** Band noise is not steady: static builds and dies away, and a receiver's gain control moves the noise up and down. When turning tone energies into soft bits, the reference receiver judges each body tone against the noise level of that tone and the eight either side of it (the median of their energies in all 32 tone positions, divided by ln 2, and never less than a tenth of the whole frame's level) instead of one level for the whole frame. In simulation, with the noise swinging 10 dB either way during the frame, L2 frames at -14 dB went from 14 to 19 decoded in 20 and long beacons at -26.5 dB from 10 to 14 in 20, with no change on steady noise.

### 5.8 Control frames

Beacons, answers, acknowledgments and identifications are short frames with the same structure as a message frame: preamble, header, body. They may be sent at any speed level; the receiver finds the level as for any frame (Section 5.1).

**Body.** The fields of the frame (tables below), followed by the 16-bit check value of Section 4 over those fields. The body is encoded with the header's convolutional code (Section 5.4: six zero bits added, rate 1/2, generators 171 and 133), padded with zeros to a whole number of tones, interleaved by the rule of Section 5.3, and sent with pilots as in Section 5.5. Retries of control frames are not combined.

| Frame | Field bits | Bits sent after coding and padding | Body tones | Interleaver step |
|---|---|---|---|---|
| Beacon | 75 | 195 | 42 | 121 |
| Answer | 124 | 295 | 63 | 182 |
| Acknowledgment | 48 | 140 | 30 | 87 |
| Identification | 61 | 170 | 37 | 107 |

Airtime of a whole control frame:

| Frame | L0 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|---|
| Beacon | 31 s | 11 s | 7.0 s | 3.5 s | 1.8 s |
| Answer | 40 s | 13 s | 8.9 s | 4.5 s | 2.2 s |
| Acknowledgment | 26 s | 8.9 s | 5.9 s | 3.0 s | 1.5 s |
| Identification | 29 s | 9.9 s | 6.6 s | 3.3 s | 1.6 s |

**Beacon (type 2), 75 bits**

| Field | Bits | Meaning |
|---|---|---|
| Origin | 48 | Callsign of the beaconing station (Section 4.2) |
| Locator | 15 | Four-character Maidenhead grid locator |
| Levels | 8 | Speed levels the station can use: the bit for level n has the value 2^n |
| Listening | 1 | 1 when the station will take answers; 0 for a presence beacon from a station whose operator is not available (Section 6.11) |
| Mail check | 1 | 1 asks any station holding mail for the origin to deliver it now |
| Holds mail | 1 | 1 when the station is holding mail for others |
| Wide window | 1 | 0 = one reply slot follows the beacon; 1 = four reply slots follow (Section 6.2) |

**Answer (type 3), 124 bits**

| Field | Bits | Meaning |
|---|---|---|
| Destination | 48 | Callsign of the beaconing station being answered |
| Origin | 48 | Callsign of the answering station |
| Channel report | 18 | How the beacon was received (see below) |
| Levels | 8 | Speed levels the answering station can use |
| Mail check | 1 | 1 asks the beaconing station to deliver any mail it holds for the origin |
| Directed call | 1 | 1 marks a directed call (Section 6.11) rather than a reply to a beacon |

**Acknowledgment (type 4), 48 bits**

| Field | Bits | Meaning |
|---|---|---|
| Link number | 9 | The lock this frame belongs to (Section 4.2) |
| Message number | 16 | The message being acknowledged |
| Part number | 3 | The part being acknowledged. With status 3: 0 = a plain reply; 1 = "I have nothing to send, the turn is yours"; 2 = "are you still there?" (Section 6.5); 3 = "move to the working frequency given in the message number" (Section 6.10); 4 = "not available": the operator of the station called is away (Section 6.11) |
| Status | 2 | 0 = received correctly; 1 = failed its check, send again (the message number is not significant); 2 = the whole message is already held or delivered here, stop sending it; 3 = no message referred to (lock business; the message number is 0, except with part number 3, where it carries a frequency offset, Section 6.10) |
| Channel report | 18 | How the frame being acknowledged was received |

**Identification (type 5), 61 bits**

| Field | Bits | Meaning |
|---|---|---|
| Origin | 48 | Callsign of the sending station |
| Link number | 9 | The lock this frame belongs to |
| End of contact | 1 | 1 when this is the station's last transmission of the contact |
| Spare | 3 | always 0 |

**Channel report, 18 bits**

| Field | Bits | Coding |
|---|---|---|
| SNR | 6 | SNR in 2.5 kHz, rounded to a whole dB, plus 30; held to 0 to 63 (-30 to +33 dB) |
| Fading index | 3 | The fading index of Section 5.7 times 4, rounded; held to 0 to 7. A missing reading is sent as 7 |
| Frequency offset | 6 | Offset in Hz divided by 2, rounded, as a signed (two's complement) number; held to -32 to 31 (-64 to +62 Hz) |
| Wanted level | 3 | The speed level the reporting station asks the other station to use for its next frames |

**Locator coding.** The two letters (A to R) count 0 to 17 and the two digits 0 to 9. The locator is the number ((first letter x 18 + second letter) x 10 + first digit) x 10 + second digit, sent as 15 bits, most significant bit first.

### 5.9 Long beacon

The long beacon (signal version 0.27) is a compact frame for being heard where nothing else gets through. It carries only what discovery needs and has no header: its own twelve-tone pattern says what it is.

1. **Pattern:** twelve tones, 18, 25, 30, 16, 5, 26, 21, 9, 2, 14, 23, 4, at the long beacon's tone length. The pattern follows the rules of Section 5.1.
2. **Body:** 36 data tones and 3 pilots (Section 5.5), 39 tones in all.

**Tones.** 32 tones, one at a time, as at every level (Section 5.2), but each held 14,000 samples (1.1667 s). One bin is 0.857 Hz; the tones are 3 bins (2.571 Hz) apart, the lowest at bin 1702 (1458.86 Hz) and the highest at 1538.57 Hz, so the signal is about 82 Hz wide. The receiver reports the long beacon's level as LB (the number 7 in programs).

**Airtime.** 51 tones x 1.1667 s = 59.5 seconds.

**Body.** 66 field bits followed by the 16-bit check value of Section 4 (82 bits), encoded with the header's convolutional code (six zero bits added, rate 1/2: 176 bits), padded to 180 bits (36 tones), interleaved by the rule of Section 5.3 (step 113) and sent with a pilot before every 15 data tones. Pilots use tones 3, 10 and 17.

| Field | Bits | Meaning |
|---|---|---|
| Callsign | 48 | The sending station (Section 4.2) |
| Grid locator | 15 | Four characters, coded as in Section 5.8 |
| Available | 1 | 1 when the operator is taking contacts (Section 6.11) |
| Holds mail | 1 | 1 when the station holds mail for others |
| Spare | 1 | Always 0 |

**Why this shape.** Simulation (tools/bottom_study.py, 40 beacons a point) of today's beacon with its tones held longer found that 1.6 s tones reach about -28 dB on a steady path but need 125 seconds; tones 1.25 Hz apart smear in heavy fading, while 2.5 Hz apart lose nothing on a steady path and gain about 6 dB in heavy fading; 3.2 s tones (250 s) reach -30 dB on a steady path but only -21 dB (nine in ten) in the worst fading. No timed slots were needed at any of these lengths. Keeping the long beacon to about a minute meant dropping the header, the level list and the other beacon flags, which leaves room for tones three times as long as L0's. **Sensitivity** (40 long beacons a point, through the full receiver, frequency error up to 2 Hz): every one decodes down to -25.6 dB on a steady path (nine in ten at -26.6 dB, about half at -27.6 dB), and nine in ten down to -18.6 dB in the worst of light, moderate and heavy fading (about half at -22.6 dB). For comparison, an L0 beacon (31 s): -21 dB on a steady path, and -14 dB nine in ten and -20 dB about half in the worst fading; WSPR is about -28 dB with 111 seconds and timed slots.

**Receiving long beacons (receiver practice, version 0.28; not part of the signal).** The reference receiver does three things beyond decoding each long beacon alone.

- **Adding repeats together.** A station repeats the same long beacon, so every copy carries the same tones. The receiver keeps the tone energies (each divided by its noise level) of any long-beacon candidate that was all there but did not decode, for 45 minutes. Each new one is first tried alone, then added to one, two or three kept copies whose audio frequency is within 3 Hz of its own and which were heard at least 2 minutes earlier, and decoded from the sums. The signal adds in the same tones each time; the noise does not.
- **Removing steady carriers.** A frequency within 100 Hz of 1500 Hz that, even in its quietest tenth of the time, stands 4 times above the rest of that band is taken to be a steady carrier and is cut out with a notch 1.3 Hz wide before the search. (More than twelve such bins is taken to be a strong signal, not carriers, and nothing is cut.) The search for the pattern then counts each frequency in units of its own typical level, and a tone position whose typical energy is twice the band's is scaled down to match.
- **A plausible callsign.** A decode is accepted only if its check value passes, its spare bit is 0 and its callsign has the shape of an amateur callsign. With many combinations of copies tried, the 16-bit check alone would let noise through now and then.

Measured in simulation (tools/combine_study.py, 40 trials a point, four copies ten minutes apart, each with its own noise and fading):

| Copies added | Steady path: all (or 39 of 40) decode | Steady path: nine in ten | Worst of light, moderate and heavy fading: nine in ten |
|---|---|---|---|
| 1 | -26 dB | -26 dB (35 of 40 at -27) | -20 dB |
| 2 | -28 dB | -28 dB | -24 dB |
| 3 | -28 dB | -29 dB | -24 dB (every one) |
| 4 | -29 dB | -30 dB | -26 dB |

In 9,600 stretches of noise alone (173 hours of an empty band) nothing was decoded. With a steady carrier inside the beacon's band and a beacon at -22 dB: a carrier as strong as the beacon cost 6 decodes in 20 before these steps and none after; one 20 dB stronger cost all 20 before and 0 to 6 in 20 after.

## 6. Link

### 6.1 Beacon

A station announces itself with a beacon frame (Section 5.8), first at level L2 and then, if that brings no answer, at L0 (see below). The beacon gives the callsign, grid locator and supported speed levels, says whether the station is taking answers and whether it holds mail for others, and carries the **mail-check flag** that asks any station holding mail for it to deliver now. After a beacon the station listens for the reply window (Section 6.2).

A longer beacon that also lists stations heard, the callsigns mail is held for and recent delivery receipts is planned: **TBD**. (This is not the long beacon of Sections 5.9 and 6.13, which is about reach.)

A station may send a **long beacon** (Section 6.13) instead of this call-up. The beacon of this section is the default and is called the short beacon where the two need telling apart.

- **Middle level first.** Every call-up begins at L2, where the beacon (7.0 s), answer (8.9 s) and confirmation (5.9 s) each take under 10 seconds and the whole exchange holds the calling frequency for about 24 seconds; at L0 it takes about 100. L2 needs a signal of about -14 dB (Section 5.2). If an L2 beacon brings no answer it can decode, the station beacons again at once at L0, which reaches down to about -20 dB; this second beacon does not count as one of the tries. Later beacons in the same call go at L0. The next call-up, after a contact or a later round, starts at L2 again. In the simulator (tools/callup_study.py) this cut the expected time on the calling frequency from 99 to 24 seconds on any steady path of -14 dB or better, and from 107-134 to 24-66 seconds in moderate fading at -10 dB or better, at a cost of about 21 seconds for stations too weak for L2.
- **Repeating a beacon.** A station that is otherwise listening may call for a partner again from time to time. Each round is one beacon and its reply window; if nobody answers, the station goes back to listening. Rounds are at least 5 minutes apart (the operator program allows 5 to 60 minutes), measured from the start of one round to the start of the next. A round is not sent while the station is in a contact, has answered another station and is waiting for the lock to be confirmed, or is making a directed call; after a contact the interval starts again from the end of the contact.
- **Attended operation.** Repeating beacons start only when the operator asks for them. The operator program stops them by itself after a period with no operator activity at the station (2 hours by default, adjustable from 15 minutes to 12 hours, or turned off by the operator), so that a station left alone does not go on calling. A station repeating beacons with nobody at the controls is under automatic control (Section 2).

### 6.2 Answer and the reply window

A station that wants to connect replies with an answer frame (Section 5.8), sent at the level the beacon came at: having decoded the beacon shows the path carries that level, and the beaconing station's reply window is sized for it. The answer reports how the beacon was received and names the speed level the answering station wants the beaconing station to use.

The numbers below are starting values from simulation, to be tuned on the air.

- **Reply slots.** The reply window is divided into slots, each as long as an answer at the beacon's level plus 2.4 seconds: 42.0 s after an L0 beacon, 15.8 s after L1, 11.3 s after L2. The first starts 1 second after the beacon ends. A plain beacon is followed by one slot. A beacon with the wide-window flag set is followed by four.
- **Answering.** After a plain beacon a station answers in the only slot. After a wide-window beacon it picks one of the four slots at random and answers at the start of that slot.
- **Choosing.** With one slot, the beaconing station locks with the answer it decodes. With four, it listens to the whole window and locks with the strongest answer it decoded.
- **When to widen.** A station's first beacon is plain. An L2 beacon with no answer is followed by a plain L0 beacon (the path may simply be too weak for L2). If an L0 beacon brings no answer it can decode, which is what happens when several stations answer on top of each other, its following beacons ask for the wide window. It keeps asking for the wide window in later calls for as long as more than one answer arrives in a window.
- **Answering by hand.** A listening station may be set not to answer beacons by itself. Its operator is shown each beacon heard, with any messages waiting for that station, and chooses whether to respond. Because no operator can begin an answer within its reply slot, the response is a directed call (Section 6.11). The beaconing station accepts it while it is still waiting in its reply window (Section 6.11, "Called while beaconing"), or later while listening. Directed calls to the station's own callsign are always answered.
- **Not chosen.** An answering station that hears no confirmation with its own link number returns to listening and may answer the next beacon.
- **Already worked.** A station does not answer a beacon from a station it has just finished a contact with, unless it has new traffic for it.

### 6.3 Lock, speed and turns

- **Lock.** The beaconing station completes the lock by sending an acknowledgment frame with status 3 (part number 0), carrying the link number and its report of how the answer was received. Both stations are then in the LOCKED state. An answering station that misses this frame but hears any frame with its link number is locked all the same.
- **Each direction has its own speed level.** A station sends at the level its partner most recently asked for, or slower; it never sends faster. The partner asks in the "wanted level" field of every channel report and of every link frame. Because every frame states its own level, the two ends cannot fall out of step.
- **The receiving station decides** the level it asks for from its own measurements, by the rule of Section 5.2, guided by the weakest of its recent readings.
- **Starting level.** When the lock is made or confirmed, each station asks straight away for the level its first measurement of the partner supports, up or down, instead of starting at L0 and climbing. The beaconing station does this on hearing the answer; the answering (or calling) station on hearing the confirmation.
- **Turns.** Only the station holding the turn starts an exchange. The beaconing station holds it first. A station with nothing left to send offers the turn with a status-3 acknowledgment, part number 1. The partner answers by sending a message frame, which takes the turn, or with a status-3 acknowledgment, part number 0, which declines it.
- **If both stations find themselves sending** (after a lost frame), the station that beaconed carries on and the station that answered gives way.
- **Keeping the lock open.** By default the station holding the turn closes the contact once neither side has anything left to send. Either station may instead keep the lock open: when its own traffic is done it offers the turn once more, so that its partner knows the lock is idle, and then stays silent while the keep-alive of Section 6.5 holds the lock. Either station may close the contact at any time it holds the turn, with its closing identification.
- **Taking the turn in an idle lock.** When the lock is idle (the station holding the turn has offered it and been declined), the other station may take the turn if it later has a message to send or wants to close the contact. It first waits long enough for a closing identification from its partner to arrive (the length of that frame at the level in use, plus the reply margin). If both then start at once, the rule above settles it.
- Frames between the pair keep their own session timing, set by the handshake.

### 6.4 Lock states

| State | Meaning | Leaves when |
|---|---|---|
| LOCKED | Link healthy | Conditions slip → DEGRADED; identification frame with the end-of-contact flag sent or received → RELEASED |
| DEGRADED | Errors or SNR falling | Frames clean again → LOCKED; sustained loss → REACQUIRE |
| REACQUIRE | Sending probes at L0 (Section 6.5) | Probe answered → LOCKED; 4 probes unanswered → RELEASED |
| RELEASED | Session over | Station returns to beaconing or listening |

A single bad frame never drops the lock.

### 6.5 Acknowledgment, speed changes and recovery

The numbers in this section are starting values from simulation, to be tuned on the air.

- Every message frame is answered with an acknowledgment frame (Section 5.8), carrying the receiver's channel report for that frame and the level it wants next.
- **Asking for a slower level.** When its measurements support less than the current level, the receiver asks for the slower level at once. After a frame that fails its check it asks for one level slower still, and for the frame to be sent again; it combines the copies (Section 5.6).
- **Asking for a faster level.** After 2 frames in a row received correctly, the receiver asks for a faster level, moving up at most 2 levels at a time.
- **No reply.** A station that hears no reply sends its frame again one level slower. A receiver that already holds the whole message answers "already have it" (status 2). A station reports a message as delivered only when its acknowledgment has been heard.
- **Reacquiring.** After 3 transmissions in a row with no reply, or 4 requests to resend the same frame, the station enters REACQUIRE and sends a status-3 acknowledgment with part number 2 at L0, asking for the reply at L0. The partner answers with a status-3 acknowledgment, part number 0. Both then start their measurements afresh and the interrupted exchange resumes. After 4 probes with no reply the lock is RELEASED and the operator is told which messages were not delivered.
- **Splitting again.** If the level falls while a split message is being sent, so that the next part would exceed the airtime limit (Section 6.8), the sender splits the whole message again for the new level and starts it again under the same message number. A receiver that holds parts of a message and receives a part with a different part count discards the parts it held.
- **Silence.** A locked station that is waiting for its partner and hears nothing for 5 minutes releases the lock.
- **Keep-alive.** When neither station has traffic and the lock is kept open, the station holding the turn offers it again after 120 seconds of silence.
- **Identification.** Each station sends an identification frame before any other frame once 9 minutes have passed since it last sent its callsign (a station without the turn in an idle lock sends it all the same), and as its last transmission of the contact with the end-of-contact flag set. A station that receives the closing identification sends its own in return.

### 6.6 Band starting profiles

Each band has default starting assumptions for noise, fading and multipath (for example, impulse noise and near-vertical multipath on 160 and 80 m, long-path fading on 20 m, sudden changes on 6 m). Profile values: **TBD**.

### 6.7 Unconnected traffic

Beacons, calls and messages to no particular station are sent at a robust fixed level, since there is no partner to negotiate with.

### 6.8 Airtime limits and message splitting

No single transmission should hold the frequency for long. The link applies these rules automatically, using the channel measurements it already has:

1. **Fastest level first.** The link uses the fastest speed level the measured conditions support.
2. **Default limit: 60 seconds per transmission.** The link does not choose a level that would make a message frame run longer than this.
3. **Poor-conditions limit: 90 seconds.** When the measured conditions are too poor for the message to fit in 60 seconds, the link allows up to 90 seconds without operator action.
4. **Splitting.** When the message still does not fit, it is sent as two or more shorter parts. Each part is a frame of its own within the 90-second limit and is acknowledged separately, so a failed part is retried alone. The header of each part carries its part number and the number of parts (Section 5.4), up to 8 parts; the message is delivered, and its receipt issued, when all parts have arrived. Every part carries the same addressing and message number (Section 4.2), which ties the parts together.

Both limits are operator settings; 60 and 90 seconds are the defaults.

### 6.9 Suggested frequencies (United States)

So that stations can find each other, one meeting frequency is suggested per band. Each is the dial frequency of an upper-sideband radio. Kestrel's tones are centred 1500 Hz above it; the widest level, L4, reaches from 800 Hz to 2180 Hz above it. The table allows the 500 Hz to 2500 Hz that earlier versions occupied.

| Band | Dial frequency (USB) | Signal occupies | Inside 97.221(b) segment |
|---|---|---|---|
| 80 m | 3590.0 kHz | 3590.5 to 3592.5 kHz | 3585 to 3600 kHz |
| 40 m | 7101.5 kHz | 7102.0 to 7104.0 kHz | 7100 to 7105 kHz |
| 30 m | 10144.0 kHz | 10144.5 to 10146.5 kHz | 10140 to 10150 kHz |
| 20 m | 14108.5 kHz | 14109.0 to 14111.0 kHz | 14100.5 to 14112 kHz |

- Every suggested frequency keeps the whole signal inside a segment that 97.221(b) allows for automatically controlled stations, so the same frequency serves attended stations and unattended mail holders (Section 2).
- The 30 m choice stays above the FT4, WSPR and PSK activity at the bottom of that segment; the 20 m choice stays clear of the beacons on 14100 kHz; the 80 m choice stays above the FT8 (3573 kHz) and JS8 (3578 kHz) activity.
- 80 m suits paths of roughly 50 to 300 miles in the evening and at night, when 40 m often skips over them; 40 m suits the same distances in the daytime and late afternoon.
- The reference program refuses to transmit on a frequency whose signal would fall outside the U.S. amateur data segments (Amateur Extra limits; General class starts 25 kHz higher on 80, 40, 20 and 15 m).
- These segments are shared with other data modes. A station listens before transmitting (Section 6.14) and moves if the frequency is in use.
- On 30 m the amateur power limit is 200 W PEP.
- These are first choices, to be confirmed by listening on the air. Other bands: **TBD**.
- Operators may use other frequencies by agreement. A station with no operator present must keep its whole signal inside a 97.221(b) segment.

### 6.10 Working frequencies

A long contact on a meeting frequency keeps others from calling there. Once locked, the pair may move to a working frequency and leave the meeting (calling) frequency free.

- **Proposal.** The station holding the turn sends a status-3 acknowledgment with part number 3. Its message-number field carries the working frequency as an offset from the frequency on which the lock was made: a signed 16-bit count (two's complement) of 100 Hz steps, so +25 means 2.5 kHz higher.
- **Agreement.** A station that can change frequency answers with the same frame (status 3, part number 3, the same offset), then changes frequency when that frame has been sent. A station that cannot, or will not, answers with a plain reply (status 3, part number 0), and the contact stays where it is. A move is proposed at most once in a contact.
- **Meeting again.** The proposing station changes frequency when it hears the agreement, waits 3 seconds, and sends a probe (status 3, part number 2) at the level in use. The partner answers as for any probe, both start their measurements afresh, and the contact carries on. If the probe goes unanswered the usual reacquiring rule applies (Section 6.5), on the working frequency.
- **A lost agreement.** If a proposal gets no reply it is sent once more. If that also gets no reply, the proposing station goes to the working frequency anyway and probes there, in case its partner agreed without being heard.
- **Giving up.** A station that has moved at its partner's request and hears nothing from it on the working frequency for 150 seconds releases the lock.
- **An idle working frequency.** On a working frequency, the station that proposed the move watches the time since a message frame last went in either direction (or since the pair arrived). Keep-alive exchanges do not count. After 3 minutes with no message frame it closes the contact in the ordinary way, with closing identifications, and both stations return to the meeting frequency. One minute beforehand it warns its own operator, who may keep the contact on the working frequency by sending a message.
- **Returning.** When the contact ends for any reason, each station returns to the meeting frequency: after its closing identification has been sent, or at once if the lock is released without one.
- **Listen first.** The operator of the proposing station is responsible for choosing a working frequency that is clear. An automatic check is **TBD**.

Suggested working frequencies (dial, upper sideband; first choices, to be confirmed by listening):

| Band | Meeting frequency | Working frequencies | Notes |
|---|---|---|---|
| 40 m | 7101.5 kHz | 7106.5, 7109.0 kHz | Signals 7107.0 to 7109.0 and 7109.5 to 7111.5 kHz. Outside the 97.221(b) segment, so only with an operator present. |
| 30 m | 10144.0 kHz | 10146.5, 10141.5 kHz | Signals 10147.0 to 10149.0 and 10142.0 to 10144.0 kHz, both inside 10140 to 10150 kHz. |
| 20 m | 14108.5 kHz | 14106.0, 14103.5, 14101.0 kHz | Signals 14106.5 to 14108.5, 14104.0 to 14106.0 and 14101.5 to 14103.5 kHz, all inside 14100.5 to 14112 kHz. |

For any other meeting frequency, the working frequencies offered are 2.5 kHz above and 2.5 kHz below it.

### 6.11 Directed calls, messages for one station, and broadcasts

- **Directed call.** A station may call one particular station instead of beaconing. It sends an answer frame (Section 5.8) with the directed-call flag set and the called station as destination: first at L2, and at L0 for any repeats. If the calling station has decoded a frame from the called station in the last 10 minutes, the channel report carries that reading and the level it supports, so the called station can start at that level; otherwise it carries no measurement (SNR at the bottom of the scale, fading index at its largest value) and asks for L0. Only the station named replies; every other station stays silent.
- **Who answers by itself.** A listening station may be set to answer directed calls by itself, or (the reference program's default) to just listen. A station that just listens transmits nothing unless its operator starts it, except that it accepts, by itself, a directed call from any station within 5 minutes of its own last beacon, and from a station it has itself called within the last 5 minutes: those calls answer something its operator started. Any other directed call is shown to the operator, who responds, if at all, with a directed call of its own (a call back).
- **Available or not.** The operator sets the station available or not available for contacts. While it is not available: (1) its beacons are presence beacons, with the listening flag 0 and no reply window, and nobody answers them; (2) a directed call addressed to it gets one short reply, a status-3 acknowledgment with part number 4 ("not available"), sent at the level the call came at, with the link number the caller is using (Section 6.3) and a report of how the call was received; nothing else is sent and no contact is made. A calling station that hears this reply stops calling at once and tells its operator. Operator programs show each station's last known availability. A station left not available with nobody at the controls is under automatic control when it sends that reply (Section 2).
- **Call back.** A station making a directed call that receives a directed call from the very station it is calling takes it as the answer: it stops calling and completes the lock as a called station would (below).
- **Being called.** An idle, listening station that receives a directed call addressed to it and takes it (as above) treats it as follows. It completes the lock as a beaconing station would (Section 6.3), except that its confirming acknowledgment has part number 1: it hands the first turn to the caller, who called because it has something to send. That first offer does not mean the called station has nothing to send. For the rest of the contact the called station takes the beaconing station's part: it keeps the turn if both find themselves sending, and its callsign comes first in the link number. It sends an identification frame the first time it holds the turn, since nothing it has sent so far carries its callsign. Until the lock is confirmed the calling station assumes the called station supports the same speed levels as itself.
- **Called while beaconing.** A station waiting in the reply window of its own beacon that receives a directed call to itself (an answer frame with the directed-call flag set) stops waiting for answers and confirms the call at once, as a listening station would.
- **No reply.** The call is repeated when its confirmation does not arrive; after 5 calls without a reply the calling station gives up.
- **Messages for one station.** A message may be marked for one callsign. It is sent only in a contact with that station, as ordinary link frames with their usual acknowledgments, and otherwise waits. A station that has already worked a caller answers that caller's next beacon only if it has a message for that caller or for anyone.
- **Broadcast.** A message for every station in range is sent as fully addressed message frames (frame type 1, Section 5.7) with the destination ALL, the sender's callsign as origin, a hop count of 0 and the shortest lifetime. It is sent at L0 unless the operator chooses otherwise, split into parts under the airtime limits (Section 6.8), and only while the sending station is in no contact. Nobody acknowledges a broadcast and it is not forwarded.
- **Receiving.** Any station that decodes every part of a fully addressed message whose destination is ALL or its own callsign shows it to its operator once, with the origin; repeats of the same message number from the same origin are dropped. This applies whether or not the receiving station is in a contact of its own.
- **Listen first.** A broadcast is sent without knowing who is listening or who is in the middle of an exchange. The operator checks that the frequency is clear before sending one.

### 6.12 Telemetry message

A station can tell others how well it hears the band, so that operators can compare stations, for example to choose the station best placed to act as net control (Section 7). It does so with an ordinary message, sent to one station or broadcast to ALL, whose text follows a fixed layout. Nothing in the link layer treats it differently.

- **Layout.** Words separated by single spaces: the tag `TLM1`; the sender's grid locator; `P` followed by the transmit power in whole watts, or `P?` if it is not known; `N` followed by the number of stations heard in the 30 minutes before the message was made; then one entry for each of those stations, strongest first. An entry is the station's callsign, its median SNR over that time as a sign and two digits (dB in 2500 Hz), the letter `L` and the fastest speed level decoded from it. Example: `TLM1 EM92 P50 N3 Q1AAAA+05L3 Q2BB-08L1 Q3CCC-15L0`.
- **Length.** The message stays within 200 characters. Entries that do not fit are left out; N still counts every station heard.
- **Text before the tag.** Other words may come before `TLM1` (the sender's callsign, for example). A receiving program looks for the tag anywhere in the message and reads the words after it.
- **Comparing.** A receiving program may rank the stations whose telemetry it has received by the number of stations each hears, then by the median of the SNRs listed. This is a guide for the operators; it is not used by any automatic rule.

### 6.13 Long beacon

The long beacon (Section 5.9) says "this station is here" as far as the path allows. It asks for nothing.

- **No reply.** No station answers a long beacon by itself, whatever its settings. A receiving station shows it to its operator, with the sender's callsign, grid, availability and the signal measurement, and logs it. The operator may respond with a directed call (Section 6.11); a path that carries only the long beacon may be too weak for that.
- **Choosing it.** Short beacons are the default. The operator chooses long beacons instead (the reference program has a Beacon type setting); a repeating long beacon follows the rules of Section 6.1 for repeating beacons, except that rounds are at least 10 minutes apart, because each holds the frequency for a minute.
- **When it goes.** Only when the station is not in a contact, not waiting for a reply and not sending a broadcast.
- **Identification.** The long beacon carries the sending station's callsign in plain form (Section 2).
- **Unattended.** As with any repeating beacon, a station sending long beacons with nobody at the controls is under automatic control (Section 2).

### 6.14 Listening before transmitting

A station does not start a transmission of its own over another signal.

- **What is held.** Anything the station starts unasked: a beacon, a long beacon, a directed call, a broadcast. It waits until the frequency has been clear for 2 seconds, then sends. The operator is told at once and every minute while it waits.
- **What is not held.** Replies inside an exchange: an answer in its reply slot, a confirmation, an acknowledgment, a retry, an identification. Their timing is part of the link rules, and the other station is waiting for them.
- **How the reference program decides** (live/busy.py; a receiver practice, not part of the signal). The received audio is measured in half-second blocks and 50 Hz strips from 300 to 2900 Hz. Each strip's noise floor is the level it stays above nine tenths of the time over the last two minutes. The frequency is in use when, in the last 2 seconds, strips within 75 Hz of the band the transmission would occupy were at 4 times their floor twice or more. It needs no knowledge of what the other signal is. In simulation it never took 2,000 seconds of noise for a signal, and it noticed a Kestrel L2 frame from about -10 dB (in 2.5 kHz) upward.
- **Limits.** A weaker signal may not be noticed, nor one that has been on without a break for two minutes, nor anything while this station transmits. The operator may turn the check off, and remains responsible for the frequency either way.

## 7. Nets (optional)

- **Net control:** a beaconing station may open a net instead of a one-to-one link. Stations that answer are admitted as members.
- **Turn-taking:** net control assigns each member a slot and sets the slot length for its net. Nets are the only place Kestrel uses fixed slots.
- **Addressing:** every frame carries "from" and "to"; "to" may be one member or ALL. Traffic to ALL is sent at the level the weakest member can decode. One-to-one traffic inside the net uses that pair's own level.
- **Backup net control:** net control names a backup and keeps it updated with the net's state (members, slots, waiting messages, delivered message IDs).
- **Heartbeat and takeover:** net control sends a heartbeat every cycle. If the backup misses a set number in a row (3 planned, **TBD**), it takes over, raises the net epoch number by one, announces the change at L0 and names a new backup.
- **Net epoch:** the highest epoch wins. A former net control that returns after a takeover sees the higher epoch and rejoins as a member.
- **Planned handoff:** net control can hand over to the backup immediately, without waiting for missed heartbeats.

## 8. Messaging and store-and-forward (disconnected operation)

Kestrel assumes no station is always on the air and no infrastructure exists. Stations come and go, and paths open and close with propagation. Messages move whenever two stations happen to hear each other.

- **Message ID:** the origin callsign together with the message number (Section 4.2). It is unique, so a message is never delivered twice, however many stations hold a copy.
- **Sender's outbox:** the sender keeps every message until a delivery receipt returns or the message expires. The sender is always the last-resort copy.
- **Holding partners:** one or more stations may accept and store a copy of the same message. Each holding partner confirms to the sender that it holds the message, so the sender knows who is carrying it. Holders list the callsigns they hold mail for in their beacons.
- **Automatic delivery, on request:** delivery needs no operator action, but it is always a reply. When a holder hears a beacon from the destination with the mail-check flag set, it answers in the reply window and delivers. When a holder hears a beacon with the mail-check flag from a station that can reach the destination (shown in that station's heard list), it passes the message on the same way. Holders never call a station unprompted to push mail. This keeps unattended holders replying to a station that asked, which is intended to fit the automatic-control rules (97.221), and saves airtime by sending mail only to stations that are listening.
- **Accountability trail:** every stored copy records the originating callsign and the callsign of the station it was received from, so the forwarding path can always be traced (97.219).
- **First to deliver wins:** a holder first offers the message ID. If the destination does not have it, the holder sends the message; if the destination already has it, it answers "already delivered" and the holder drops its copy without sending it again. The first holder to complete delivery wins.
- **Hop limit:** each relay adds one hop; a hop limit (4 planned, **TBD**) stops messages circulating. The count travels in the address block.
- **Receipt to every holder:** when a message reaches its destination, the destination issues a delivery receipt carrying the message ID. The receipt travels back toward the sender like a small message, is passed to every known holding partner, and is listed in beacons for a time (recent-receipts list). Every holder that learns of the receipt drops its copy, and the sender marks the message delivered.
- **Expiry:** every message carries its remaining lifetime in the address block (48 hours at the start planned, **TBD**; the field allows up to 62). When it runs out, holders drop the message and the sender is told it was not delivered.
- **Nets as temporary post offices:** while a net is running, net control holds the net's mail and copies it to the backup net control. When the net closes, undelivered mail stays with its holders and continues to be carried.
- **Duplicates:** a message whose ID has already been handled, whose hop limit is reached, or whose lifetime has run out is dropped.

Each station applies the same checks to every message it receives: deliver it if it is addressed to this station; otherwise drop it if seen before, out of hops or expired; otherwise relay it if the destination is reachable now; otherwise hold it and announce it in beacons until it is delivered, a receipt is heard or it expires. All of this runs automatically.

## 9. Open items

- Speed level L5 (a faster waveform) and any further levels.
- Measurement of Doppler spread and delay spread; level limits confirmed by on-air tests.
- The longer beacon carrying the heard list, held-mail list and delivery receipts.
- Band starting profiles.
- Net slot timing rules; heartbeat miss count; hop limit.
- Message lifetime; how long receipts stay listed.
- Message splitting: how parts are held and forwarded by holding partners.
- Beacon size: short hashed message IDs, caps on the held-mail and receipt lists, and which entries go first when a list is full.
- Storage limits: how much mail a holder will carry in total and per originating station.
- ARRL review of the 97.221(b) reading in Section 2 for unattended mail holders (asked; awaiting a reply).

## 10. Roadmap (proposed, 21 November 2026)

The aim is one open mode that reaches like WSPR, carries messages like JS8Call and moves traffic quickly when the path allows, like VARA, with store-and-forward and net-control failover built in. It is reached by stretching Kestrel's one-mode, many-levels design at both ends. Each step is proposed, not settled; each becomes part of this description only when its signal is defined and tested.

| Step | Work | Purpose |
|---|---|---|
| 1. Prove the link | Recording and decoding received audio; near-miss reports; fading re-measured and the header moved (0.26); on-air setup checks; on-air tests at 100+ miles | Show that the existing levels hold a contact over real HF paths |
| 2. A WSPR-like bottom level | **First part in 0.27: the long beacon** (Sections 5.9, 6.13), about a minute, shown to the operator, not answered. Timed slots proved unnecessary. **0.28: receivers add repeated long beacons together** and remove steady carriers. Still open: a reply at this level (a reception report), and short notes | Reach: be heard where nothing else gets through |
| 3. Nets and mail | Nets with net control, backup and takeover (Section 7); store-and-forward completed (Section 8) | Groups and disconnected operation, at every level |
| 4. A VARA-like top level | A multi-carrier PSK or OFDM waveform within 2.8 kHz for strong paths (Section 5.2, L5) | Throughput for relays and longer traffic |

Steps 2 and 4 change the signal and will raise the signal version. Step 3 is mostly link and messaging rules.

## 11. Document history

See `CHANGELOG.md` in this folder.
