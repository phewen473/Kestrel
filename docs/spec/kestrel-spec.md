# Kestrel Technical Description

**Version 0.42R2 (draft), November 25, 2026.** In first on-air tests since November 18, 2026. Version 0.42R2 changes the reference program's window handling only (the panel's dividers come back as left; the Activity window is on, minimized, or off, and never pops up by itself); nothing sent changes. **Version 0.42R1 (draft), November 25, 2026.** Version 0.42R1 fixes the reference program only (rig control failed after the move to a per-user installation); nothing sent changes. **Version 0.42 (draft), November 25, 2026.** Nothing sent changes: **the signal version stays 0.41**, and 0.41 and 0.42 stations work together. New: chained messages (Section 6.20), a message of up to 1,000 characters sent as numbered pieces of at most 200 characters, each an ordinary message beginning "(k/n) ", only on a working channel; a station following 0.41 shows the pieces one by one. In the reference program: the other station's channel report (Section 6.4), which every answer and acknowledgment already carries, is shown as how it hears this station; a Chat window; a check for newer releases with an operator-approved Install now (Section 6.21); a per-user installation; and a layout that fits 1024x768. **Version 0.41 (draft), November 25, 2026.** **Signal version 0.41:** the long call-up (Section 6.18): a long-note frame of kind 3 (unused before) carries a directed call, its answer, or a "not available" reply in a long frame, about a minute, read down to about -22 dB, so that two stations can make contact on a fading path too weak for the short levels (which need about -8 dB when the signal fades). Once a long contact is made, messages go as long notes. **Stations following 0.40 or earlier read a long call-up as noise;** everything else is unchanged from 0.40. The reference program also keeps one sound output stream open for the whole run, ends a contact after 3 minutes without messages, with Keep-Alive and a 10-second warning to both operators (Section 6.19), and has a new panel layout; none of these change anything sent. Version 0.40R3 fixes the reference program only (messages queued while Listen was starting were not sent in that run); nothing sent changes. Version 0.40R2 fixes the reference program only (queued messages lost when a run failed to start); nothing sent changes. Version 0.40R1 changes only the reference program (its sample count is kept in step with the clock after each transmission; it can hold a chosen output power by adjusting the audio drive, and warns when power falls during a transmission); nothing sent changes, and 0.40 and 0.40R1 stations work together. Version 0.40: **Signal version 0.40:** the beacon (Section 5.8) carries the station's rig type, its Hamlib model number (16 bits), and its transmit power in whole watts (10 bits); 0 in either means not said. A beacon grows from 75 to 101 field bits: 36 s at L0 (was 31 s), 8.1 s at L2 (was 7.0 s). Receivers fill in a saved contact's radio and power from its beacons. After a contact locks, the reference program sends its operator's antenna type once to the other station as the message "ANT <type>" (Section 6.17). **Stations following 0.39 or earlier cannot read 0.40 beacons, nor 0.40 stations theirs;** long beacons and everything else are unchanged from 0.39. Version 0.39R1: Version 0.39R1 changes only the reference program: its check of the P.533 predictions against stations heard (Section 6.15) now also uses the SNR other stations report for this station's signal, per station, and says which end of a path falls short; nothing sent changes, and 0.39 and 0.39R1 stations work together. Version 0.39: **Signal version 0.39:** a long note (Section 6.16) holds up to 64 characters (was 28): a header and up to eight text frames (was four) of eight characters each (was seven), from a set of 64 characters (space, capitals, figures and common punctuation; small letters are sent as capitals) coded in 6 bits (was 7-bit ASCII), enough for a telemetry message with about four stations. **Stations following 0.38 or earlier misread 0.39 long notes, and 0.39 stations theirs;** everything else is unchanged from 0.38. Version 0.38R1 changes only how the reference program is packaged: its installer carries the P.533 ionosphere maps for three months and fetches the others from the ITU's repository the first time they are needed (Section 6.15); nothing sent changes, and 0.38 and 0.38R1 stations work together. **Signal version 0.38:** the long frame (long beacon and long notes) sends its tones five bins apart, 4.29 Hz, about 137 Hz in all (Section 5.9), which costs nothing on a steady path and reads through two to three times the Doppler spread; and a station may send power steps, four tones at 0, -10, -20 and -30 dB, just before a short beacon, announced by the beacon header's spare bit (Sections 5.4 and 5.10). **Stations following 0.37 or earlier cannot read 0.38 long beacons and long notes, nor 0.38 stations theirs; they read a beacon with power steps as noise.** Everything else is unchanged from 0.37. Version 0.37 changes only the reference program's appearance and what it shows (signal recognition, color themes); nothing in this document's rules changes, and nothing sent changes (signal version stays 0.34). Version 0.36 was not released. Version 0.35: Version 0.35 changes nothing sent (signal version stays 0.34): calling frequencies and channels for 17, 15, 10 and 6 m (Sections 6.9, 6.10); a Doppler-spread measurement on every frame (Section 5.7), used to choose levels in fast fading (Section 6.5); and, in the reference program, the short-path window from ionosondes, band activity from WSPR and PSK Reporter spots, a running check of the predictions against stations heard, and optional reporting of stations heard to PSK Reporter (Section 6.15). Version 0.34R1 changes only the reference program: its receiver also reads long-frame tones smeared by Doppler spread (Section 5.9, "Reading smeared tones"), and its propagation predictions use today's measured ionosphere and warn of flares and storms (Section 6.15); nothing sent changed, and 0.34 and 0.34R1 stations work together. **Signal version 0.34:** long notes (Section 6.16): a short message of up to 28 characters sent in long-beacon frames, heard about 5 dB below L0, with a one-minute receipt from the station addressed and up to three tries. A long-note frame is a long-beacon frame whose spare bit is 1. Stations following 0.33 or earlier hear long notes as noise; everything else is unchanged from 0.33. **Signal version 0.33:** the answer frame, which is also the directed call, carries the answering or calling station's four-character grid locator (Section 5.8), as the beacon already does, so that every station heard in a call-up has a known location for propagation predictions (Section 6.15). An answer lasts 9.5 s at L2 (was 8.9 s) and 42 s at L0 (was 40 s); reply slots grow to match (Section 6.2). **Stations following 0.32 or earlier cannot read 0.33 answers and directed calls, nor 0.33 stations theirs.** **Signal version 0.32:** the transmitted waveform changed (Section 5.2): tones are numbered in Gray code, the frequency glides between tones at L3 and L4, and every frame fades in and out over 10 ms. **Stations following 0.31R4 or earlier cannot exchange frames with 0.32 stations** (the bits read from each tone differ). In simulation on noise and on the ITU-R F.1487 sky-wave conditions (including near-vertical incidence), Gray coding gains up to about 1.4 dB; the glide keeps L4 inside 2.8 kHz at 40 dB below the peak. The reference program also gains HF propagation predictions by Recommendation ITU-R P.533 (Section 6.15), which change nothing sent. Version 0.31R4 adds only color controls to the reference program's scopes (nothing in this document changes). Version 0.31R3 adds only a contact book to the reference program's panel (nothing in this document changes). Version 0.31R2 changes only how the reference program reports signatures it cannot read (Section 5.3 "Receiver side", near misses). Version 0.31R1 improves only the reference program's receiver for weak signals (steady signals notched out of the band, failed control frames added to later copies, expected callsigns tried, LDPC decoder settings; Section 5.3 "Receiver side"); version 0.31 changed only how it searches a stream (incremental, much less computing). Nothing sent has changed: 0.30, 0.31, 0.31R1, 0.31R2, 0.31R3 and 0.31R4 stations work together. **Signal version 0.30:** store and forward (Section 8): a new frame, the mail notice (Section 5.8, frame type 7), sent just before a beacon by a station that holds mail for others or has delivery receipts to report; mail carried inside a contact as fully addressed frames; a new acknowledgment code, "does not carry mail" (part number 5 with status 3). Stations following 0.29 or earlier cannot hand over, carry or deliver mail, and ignore mail notices; contacts and messages between 0.29 and 0.30 stations otherwise work, except that a 0.30 station refuses as "already have it" any message number it has already received from that station in the last 62 hours. Version 0.29 moved the calling frequencies to an area of Kestrel's own on each band and adds numbered channels (Sections 6.9, 6.10); version 0.28 changed how frames are received (Sections 5.7, 5.9) and added listening before transmitting (6.14). Neither changes the frames sent. **Signal version 0.27:** a new frame, the long beacon (Sections 5.9 and 6.13), heard well below the other levels. Stations following 0.26 do not hear long beacons; everything else is unchanged from 0.26, in which the second copy of the header moved to the end of every frame (Section 5.1), so stations following 0.25 or earlier cannot exchange frames with 0.26 and 0.27 stations. Earlier changes: the call-up in 0.23 (beacon and answer tried first at L2, reply slots sized to the beacon's level, a directed-call flag in the answer frame), 0.24 (a calling station takes a call back as the answer) and 0.25 (availability: presence beacons and the "not available" reply). Values marked **TBD** are placeholders that will be fixed before the first on-air test.

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

Every level uses the same signaling: 32 tones, one tone at a time, each tone carrying 5 bits (multiple-tone frequency-shift keying, MFSK). Tone signaling does not depend on carrier phase and holds up in fading. A faster level sends each tone for a shorter time.

- A group of 5 bits, read most significant bit first, is a value v from 0 to 31. It is sent as tone number m = v XOR (v >> 1), its Gray code (since 0.32), so neighboring tones differ in one bit only and the commonest error, landing one tone over, costs one bit. The preamble patterns and the pilots name tone numbers directly; they are not Gray-coded.
- Tone number m of a level is at frequency f(m) = lowest tone + m x tone spacing. A frame (preamble, header, body, header) is one waveform: s(n) = A(n) cos(2 pi (f(0) + f(1) + ... + f(n-1)) / 12000), where f(n) is the frequency wanted at sample n, starting at phase zero. Every tone holds a whole number of cycles, so the phase is continuous from tone to tone.
- At L0, L1 and L2 (and in the long beacon) f(n) steps from one tone to the next. At L3 and L4 it glides (since 0.32): the steps are smoothed with a raised-cosine bump g of G = round(0.25 x samples per tone) points (G = 135 at L3, 68 at L4), g(k) = 0.5 - 0.5 cos(2 pi (k + 1) / (G + 1)) for k = 0 to G - 1, scaled so the points add up to 1. f(n) is the sum over k of g(k) x step(n + k - floor(G / 2)), the first and last tone's frequency held beyond the ends. This narrows L4 from 2844 Hz to 1839 Hz at 40 dB below the peak (L3 from 1581 Hz to 919 Hz) for at most about 0.7 dB of sensitivity in simulation.
- A(n) is 1 except for a raised-cosine fade over the first and last 120 samples (10 ms) of every frame (since 0.32): A(n) = 0.5 - 0.5 cos(pi n / 120) for n = 0 to 119, and the same mirrored at the end. The transmission starts and stops without a click.

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
- **Fading signal:** nine test frames in ten decoded at this SNR in the worst of three simulated HF paths (light, moderate and heavy fading, ITU-R F.1487), 40 frames a point, with no stronger point falling below 34 in 40. The remaining frames are recovered by combining retries (Section 5.6). Light fading is the hardest case at every level: its fades are slow, so one fade can cover a whole preamble, and in 1 to 4 frames in 40 the frame is missed even on strong signals. With 40 frames a point the limits carry about 2 dB of sampling uncertainty, which is why they do not fall evenly from L0 to L4 (measured November 21, 2026).

A station chooses the fastest level whose limit, for the kind of signal it is measuring (Section 5.7), is at least 2 dB below the measured SNR. These limits guide the choice; they do not change the signal, and they will be revised after on-air tests.

L1 and L2 are sized so that a full 200-character frame fits the 90-second and 60-second limits of Section 6.8. Frames longer than those limits are not sent; at the slow levels a long message is split into shorter parts instead.

A faster level (L5) is planned. It needs a different waveform, because tones this short would be too wide: **TBD**.

### 5.3 Error correction and interleaving

**Body.** The body is protected by a rate-1/2 low-density parity-check (LDPC) code of the repeat-accumulate kind. For k body bits (k = 402, 752, 1102 or 1452) the codeword is the k body bits followed by k parity bits.

- There are k parity checks. Every body bit takes part in exactly three checks. Parity bit i takes part in check i and in check i + 1 (the last parity bit only in the last check).
- So parity bit 0 equals the XOR of the body bits in check 0, and parity bit i equals parity bit i - 1 XOR the body bits in check i.
- The three checks of each body bit are listed, for every k, in `tables/ldpc_checks_k<k>.txt`. They come from three pseudo-random shuffles of 0..k-1 made with the xorshift32 generator (shifts 13, 17, 5; start values 0x4B455301, 0x4B455302, 0x4B455303) and a Fisher-Yates shuffle, then repaired so that no body bit uses the same or neighboring checks twice and no two body bits share more than one check. The reference program `modem/ldpc.py` is the exact definition; the table files are its output.

**Interleaver.** The codeword is padded with zeros to a whole number of tones (805, 1505, 2205 or 2905 bits) and shuffled: bit i of the padded codeword is sent in position (step x i) mod n, where n is the padded length and step is the whole number nearest to n x 0.6180339887 that shares no factor with n (searching outwards, above before below). The steps are 498, 929, 1363 and 1796. The shuffled bits are then grouped in fives to make the data tones.

**Receiver side.** Impulse noise (static crashes) is detected and blanked before decoding. The decoder is not specified; the reference uses normalized min-sum belief propagation (scale 0.9, up to 200 passes since 0.31R1; 0.8 and 80 before).

*Reference receiver for weak signals (since 0.31R1; informative, none of it changes what is sent):*
- **Steady signals are notched out** before searching and decoding: in 0.4 s blocks from 700 to 2300 Hz, a 2.5 Hz step whose energy even in its quietest tenth of the time is 4 times both the band's typical level and the median of the steps within 25 Hz of it is a carrier or other steady narrow signal, and a notch 2.5 Hz wide removes it (at most 24 steps; more is a strong wide signal and nothing is removed). Measured: a carrier on a frame's own tones made L0 at -18 dB, L2 at -12 dB and L3 at -9 dB unreadable (0-3 of 12); with the notch all 12 read.
- **Failed control frames are added to later copies.** The soft bits of a control frame whose body fails its check are kept for 30 minutes; a later failure of the same frame type with a frequency offset within 4 Hz is decoded added to each of the 4 most recent (and to all of them together). A station's call-up sends the same frame at L2 and then at L0, and repeats it; the copies add whatever their level.
- **Expected callsigns are tried.** When a control frame still fails, the callsigns the station expects (the station it is calling, its partner, saved contacts and stations heard in the last 48 hours; at most 8 besides the station's own) are tried in its callsign fields: as the origin of a beacon, identification or mail notice, and as the destination (the station's own callsign) and origin of an answer. The convolutional decoder keeps only paths that agree with the assumed bits.
- A frame read only with such help must pass its check value, unpack, carry callsign-shaped callsigns, and agree with at least 74 per cent of its own soft bits (real weak frames measured 0.78 and up; noise that passes the check by chance, 0.62 to 0.68). In 60,000 noise-only trials with two noise "copies" and 8 expected callsigns each, none was accepted. The receiver reports how such a frame was read.
- Measured (20 frames a point, single copy versus with one earlier copy and the right callsigns expected): L0 beacon at -23 dB 9 to 18 of 20, at -24 dB 3 to 9; L2 answer at -17 dB 1 to 14; L0 answer at -24 dB 0 to 11. Below that the header, not the body, is what fails.
- **Near misses (since 0.31R2).** A signature pattern whose frame passes without a readable header is a near miss. It is shown to the operator only when it is likely a real Kestrel frame: at least 7 of its 12 pattern tones must each be the strongest tone in its own slot. Measured in simulation: a real frame at the edge of decoding shows 5 to 9 (L0 at -24 dB in fading, 7 or more about half the time); 8-FSK, 16-FSK, RTTY and OFDM signals of other modes that match the pattern's total energy show 0 to 2; the strongest chance matches in plain noise show 2 to 5, and 7 about once in 2,000 (8 never in 4,500); in 30 minutes of simulated noise and 15 minutes with 60 strong bursts of other modes, no near miss was shown. A near miss of the same level within 5 Hz of one shown in the last minute is not shown again. Strong patterns that fail the tone test (standing 6 times above the background) are still kept in the signal log. Before 0.31R2 a near miss was any pattern standing 6 times above the background: in practice another mode's signal, since a real frame weak enough to lose its header stands far lower. Measured too: trying the known headers of the five control frames on a pattern whose header did not read added 1 frame in about 120 weak failures (L0 and L2, beacon, answer, acknowledgment, -16 to -27 dB), because near the limit the body fails with the header, so it was not adopted.

### 5.4 Header

The header carries 16 field bits followed by an 8-bit check value:

| Field | Bits | Meaning |
|---|---|---|
| Frame type | 3 | 0 = message in a link frame; 1 = message in a fully addressed frame (Section 4.2); 2 = beacon; 3 = answer; 4 = acknowledgment; 5 = identification; 7 = mail notice (Section 5.8); 6 reserved (never sent: receivers use it to report a long beacon, which has no header, Section 5.9) |
| Speed level | 3 | 0 to 4 |
| Size class | 2 | 0 to 3 (body of 402, 752, 1102 or 1452 bits) |
| Part number | 3 | 0 for the first part |
| Part count | 3 | number of parts minus one |
| Compressed | 1 | 1 when the text is compressed |
| Spare | 1 | 0; in a beacon only, 1 when power steps were sent just before the frame (Section 5.10, since 0.38) |

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

- **Doppler spread** (since 0.35). Fading smears each tone's energy into the bins beside it. Over the known tones of a decoded frame, the receiver adds the energy in each tone's own bin and in its two neighbors (less the noise in each) and finds the Gaussian Doppler spectrum whose expected share in the neighbors matches (spread = twice its standard deviation, as ITU-R F.1487 measures it). L3 and L4 leave a share of 0.0034 and 0.0031 beside each tone through their glides on a steady path, which is taken off first. No reading is given unless the known tones' signal adds up to 30 times one bin's noise. In simulation (tools/spread_check.py, one fading path, 12 frames a point) L0, L1, L2 and the long frame read 0.1 to 2 Hz within about 10 % (the long frame to about 2 Hz; its tones are 2.6 Hz apart); L3 and L4, whose bins are 22 and 44 Hz wide, read spreads from about 1 Hz up, to within 1 or 2 Hz. The reading is reported to the operator and logged; it is not sent on the air.

A measurement of delay spread (multipath) is planned.

**Following the noise (receiver practice, version 0.28).** Band noise is not steady: static builds and dies away, and a receiver's gain control moves the noise up and down. When turning tone energies into soft bits, the reference receiver judges each body tone against the noise level of that tone and the eight either side of it (the median of their energies in all 32 tone positions, divided by ln 2, and never less than a tenth of the whole frame's level) instead of one level for the whole frame. In simulation, with the noise swinging 10 dB either way during the frame, L2 frames at -14 dB went from 14 to 19 decoded in 20 and long beacons at -26.5 dB from 10 to 14 in 20, with no change on steady noise.

### 5.8 Control frames

Beacons, answers, acknowledgments, identifications and mail notices are short frames with the same structure as a message frame: preamble, header, body. They may be sent at any speed level; the receiver finds the level as for any frame (Section 5.1).

**Body.** The fields of the frame (tables below), followed by the 16-bit check value of Section 4 over those fields. The body is encoded with the header's convolutional code (Section 5.4: six zero bits added, rate 1/2, generators 171 and 133), padded with zeros to a whole number of tones, interleaved by the rule of Section 5.3, and sent with pilots as in Section 5.5. Retries of control frames are not combined.

| Frame | Field bits | Bits sent after coding and padding | Body tones | Interleaver step |
|---|---|---|---|---|
| Beacon | 101 | 250 | 54 | 157 |
| Answer | 139 | 325 | 70 | 201 |
| Acknowledgment | 48 | 140 | 30 | 87 |
| Identification | 61 | 170 | 37 | 107 |
| Mail notice | 192 | 430 | 92 | 267 |

Airtime of a whole control frame:

| Frame | L0 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|---|
| Beacon | 36 s | 12 s | 8.1 s | 4.0 s | 2.0 s |
| Answer | 42 s | 14 s | 9.5 s | 4.8 s | 2.4 s |
| Acknowledgment | 26 s | 8.9 s | 5.9 s | 3.0 s | 1.5 s |
| Identification | 29 s | 9.9 s | 6.6 s | 3.3 s | 1.6 s |
| Mail notice | 51 s | 17 s | 11.5 s | 5.8 s | 2.9 s |

**Beacon (type 2), 101 bits** (75 before 0.40)

| Field | Bits | Meaning |
|---|---|---|
| Origin | 48 | Callsign of the beaconing station (Section 4.2) |
| Locator | 15 | Four-character Maidenhead grid locator |
| Levels | 8 | Speed levels the station can use: the bit for level n has the value 2^n |
| Listening | 1 | 1 when the station will take answers; 0 for a presence beacon from a station whose operator is not available (Section 6.11) |
| Mail check | 1 | 1 asks any station holding mail for the origin to deliver it now |
| Holds mail | 1 | 1 when the station is holding mail for others |
| Wide window | 1 | 0 = one reply slot follows the beacon; 1 = four reply slots follow (Section 6.2) |
| Rig type | 16 | The station's radio as its Hamlib model number (for example 1035 for the Yaesu FT-991); 0 when not said (since 0.40) |
| Power | 10 | The station's transmit power in whole watts, 1 to 1023; 0 when not said (since 0.40) |

**Answer (type 3), 139 bits**

| Field | Bits | Meaning |
|---|---|---|
| Destination | 48 | Callsign of the beaconing station being answered |
| Origin | 48 | Callsign of the answering station |
| Locator | 15 | Four-character Maidenhead grid locator of the origin, coded as in the beacon (since 0.33); all ones (32767) when the origin has no locator set. Any other value above 32399 makes the frame invalid. Answers and directed calls carry it so that every station heard in a call-up has a known location for propagation predictions (Section 6.15) |
| Channel report | 18 | How the beacon was received (see below) |
| Levels | 8 | Speed levels the answering station can use |
| Mail check | 1 | 1 asks the beaconing station to deliver any mail it holds for the origin |
| Directed call | 1 | 1 marks a directed call (Section 6.11) rather than a reply to a beacon |

**Acknowledgment (type 4), 48 bits**

| Field | Bits | Meaning |
|---|---|---|
| Link number | 9 | The lock this frame belongs to (Section 4.2) |
| Message number | 16 | The message being acknowledged |
| Part number | 3 | The part being acknowledged. With status 3: 0 = a plain reply; 1 = "I have nothing to send, the turn is yours"; 2 = "are you still there?" (Section 6.5); 3 = "move to the working frequency given in the message number" (Section 6.10); 4 = "not available": the operator of the station called is away (Section 6.11); 5 = "does not carry mail": the station will not hold the message named in the message number for another station (Section 8) |
| Status | 2 | 0 = received correctly; 1 = failed its check, send again (the message number is not significant); 2 = the whole message is already held or delivered here, stop sending it; 3 = no message referred to (lock business; the message number is 0, except with part number 3, where it carries a frequency offset, Section 6.10) |
| Channel report | 18 | How the frame being acknowledged was received |

**Identification (type 5), 61 bits**

| Field | Bits | Meaning |
|---|---|---|
| Origin | 48 | Callsign of the sending station |
| Link number | 9 | The lock this frame belongs to |
| End of contact | 1 | 1 when this is the station's last transmission of the contact |
| Spare | 3 | always 0 |

**Mail notice (type 7), 192 bits** (since 0.30)

| Field | Bits | Meaning |
|---|---|---|
| Origin | 48 | Callsign of the sending station |
| Held for | 3 x 16 | Short codes of up to three stations the sender holds mail for, oldest mail first |
| Receipts | 3 x 16 | Short codes of up to three messages whose delivery the sender reports, newest first |
| Heard | 3 x 16 | Short codes of up to three stations the sender has decoded in the last 2 hours, most recent first |

**Short codes.** A station's code is the CRC-16 of Section 4 over its 48 address bits (Section 4.2); a message's code is the CRC-16 over the origin's 48 address bits followed by the 16-bit message number. A result of 0 is sent as 1, because 0 marks an unused entry. Codes are short so that a notice stays small; two callsigns may share a code (about one chance in 65,000), which at worst makes a station ask for mail it does not have or drop a copy of mail that was not delivered (the origin keeps its own copy, Section 8).

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

**Tones.** 32 tones, one at a time, as at every level (Section 5.2), but each held 14,000 samples (1.1667 s). One bin is 0.857 Hz; the tones are 5 bins (4.286 Hz) apart, the lowest at bin 1670 (1431.43 Hz) and the highest at bin 1825 (1564.29 Hz), so the signal is about 137 Hz wide. (Until signal version 0.38 the tones were 3 bins, 2.571 Hz, apart and the signal 82 Hz wide; the wider spacing loses nothing on a steady path and reads through two to three times the Doppler spread: see "Reading smeared tones" below.) The receiver reports the long beacon's level as LB (the number 7 in programs).

**Airtime.** 51 tones x 1.1667 s = 59.5 seconds.

**Body.** 66 field bits followed by the 16-bit check value of Section 4 (82 bits), encoded with the header's convolutional code (six zero bits added, rate 1/2: 176 bits), padded to 180 bits (36 tones), interleaved by the rule of Section 5.3 (step 113) and sent with a pilot before every 15 data tones. Pilots use tones 3, 10 and 17.

| Field | Bits | Meaning |
|---|---|---|
| Callsign | 48 | The sending station (Section 4.2) |
| Grid locator | 15 | Four characters, coded as in Section 5.8 |
| Available | 1 | 1 when the operator is taking contacts (Section 6.11) |
| Holds mail | 1 | 1 when the station holds mail for others |
| Spare | 1 | Always 0 in a long beacon; 1 marks a long-note frame (Section 6.16), whose other 65 field bits are laid out differently |

**Why this shape.** Simulation (tools/bottom_study.py, 40 beacons a point) of today's beacon with its tones held longer found that 1.6 s tones reach about -28 dB on a steady path but need 125 seconds; tones 1.25 Hz apart smear in heavy fading, while 2.5 Hz apart lose nothing on a steady path and gain about 6 dB in heavy fading; 3.2 s tones (250 s) reach -30 dB on a steady path but only -21 dB (nine in ten) in the worst fading. No timed slots were needed at any of these lengths. Keeping the long beacon to about a minute meant dropping the header, the level list and the other beacon flags, which leaves room for tones three times as long as L0's. **Sensitivity** (40 long beacons a point, through the full receiver, frequency error up to 2 Hz): every one decodes down to -25.6 dB on a steady path (nine in ten at -26.6 dB, about half at -27.6 dB), and nine in ten down to -18.6 dB in the worst of light, moderate and heavy fading (about half at -22.6 dB). For comparison, an L0 beacon (31 s): -21 dB on a steady path, and -14 dB nine in ten and -20 dB about half in the worst fading; WSPR is about -28 dB with 111 seconds and timed slots.

**Receiving long beacons (receiver practice, version 0.28; not part of the signal).** The reference receiver does three things beyond decoding each long beacon alone.

- **Adding repeats together.** A station repeats the same long beacon, so every copy carries the same tones. The receiver keeps the tone energies (each divided by its noise level) of any long-beacon candidate that was all there but did not decode, for 45 minutes. Each new one is first tried alone, then added to one, two or three kept copies whose audio frequency is within 3 Hz of its own and which were heard at least 2 minutes earlier, and decoded from the sums. The signal adds in the same tones each time; the noise does not.
- **Removing steady carriers.** A frequency within 130 Hz of 1500 Hz (100 Hz before 0.38) that, even in its quietest tenth of the time, stands 4 times above the rest of that band is taken to be a steady carrier and is cut out with a notch 1.3 Hz wide before the search. (More than twelve such bins is taken to be a strong signal, not carriers, and nothing is cut.) The search for the pattern then counts each frequency in units of its own typical level, and a tone position whose typical energy is twice the band's is scaled down to match.
- **A plausible callsign.** A decode is accepted only if its check value passes, its spare bit is 0 (1 marks a long note, Section 6.16, checked by its own rules) and its callsign has the shape of an amateur callsign. With many combinations of copies tried, the 16-bit check alone would let noise through now and then.
- **Reading smeared tones (since 0.34R1; five bins since 0.38).** Doppler spread smears a 1.17 s tone into the bins beside it. The receiver first decodes from each tone's own bin, as before; if that fails it decodes again from each tone's bin plus the bin either side; and since 0.38, if that fails too, from each tone's bin plus the two bins either side (the tones are five bins apart, so no bin is counted twice), alone and when adding copies. The table below was measured with the tones three bins apart; the one after it compares three-bin and five-bin spacing. Measured in simulation (tools/skywave_study.py, 40 trials a point, two-path fading with 1 ms between the paths, signal at the known start), the weakest SNR at which nine in ten decode:

| Doppler spread | Own bin only | Own bin, then three bins |
|---|---|---|
| none (noise only) | -26 dB | -26 dB |
| 0.25 to 0.5 Hz | -22 dB | -22 dB |
| 1 Hz | -20 dB | -22 dB |
| 2 Hz | -18 dB | -22 dB |
| 3 Hz | above -12 dB | -20 dB |
| 4 Hz | above -12 dB | -14 dB |

  With the tones five bins apart (signal version 0.38; tools/wide_spacing_study.py, 40 trials a point, the same channel), the weakest SNR at which nine in ten decode, reading the own bin, then three bins, then five:

| Doppler spread | 3 bins apart (to 0.37) | 5 bins apart (0.38) |
|---|---|---|
| none (noise only) | -26 dB | -26 dB |
| 1 Hz | -22 dB | -22 dB |
| 2 Hz | -22 dB | -22 dB |
| 3 Hz | -20 dB | -22 dB |
| 4 Hz | -16 dB | -22 dB |
| 6 Hz | not read | -20 dB |

  The same study found that copies heard 1.2 or 2 Hz apart (a drifting transmitter, a sunrise shift) still add as well as copies on the same frequency, because each copy is measured at its own frequency and drift before adding; that the speed levels L2 to L4 decode (95 to 100 %) at +10 dB in every mid-latitude condition, including near vertical incidence with 7 ms between the paths, so none needs to be barred on short paths; and that a long frame 4 Hz off and drifting 0.01 Hz/s is found and read as well as one on frequency.

Measured in simulation (tools/combine_study.py, 40 trials a point, four copies ten minutes apart, each with its own noise and fading):

| Copies added | Steady path: all (or 39 of 40) decode | Steady path: nine in ten | Worst of light, moderate and heavy fading: nine in ten |
|---|---|---|---|
| 1 | -26 dB | -26 dB (35 of 40 at -27) | -20 dB |
| 2 | -28 dB | -28 dB | -24 dB |
| 3 | -28 dB | -29 dB | -24 dB (every one) |
| 4 | -29 dB | -30 dB | -26 dB |

In 9,600 stretches of noise alone (173 hours of an empty band) nothing was decoded. With a steady carrier inside the beacon's band and a beacon at -22 dB: a carrier as strong as the beacon cost 6 decodes in 20 before these steps and none after; one 20 dB stronger cost all 20 before and 0 to 6 in 20 after.

### 5.10 Power steps before a beacon (since 0.38)

A station may send, in the same transmission just before a short beacon (Section 5.8, frame type 2), four steady tones at the center of the band, each a tenth of the power of the one before, as the NCDXF beacons do with their dashes at 100, 10, 1 and 0.1 W:

| Step | Power against the beacon | Length | Then |
|---|---|---|---|
| 1 | 0 dB (the beacon's own) | 1 s | 0.25 s of silence |
| 2 | -10 dB | 1 s | 0.25 s of silence |
| 3 | -20 dB | 1 s | 0.25 s of silence |
| 4 | -30 dB | 1 s | 0.25 s of silence |

Each step is a tone at 1500 Hz faded in and out over 20 ms; the whole sounding lasts 5 s, and the beacon's preamble follows the last silence. The beacon's header spare bit is 1 (Section 5.4), so a receiver that decodes the beacon knows to look back in its audio for the steps. A receiver that reads them reports each step's strength as SNR in 2.5 kHz, which steps stood out (the reference receiver counts a step heard when its tone stands 8 dB above the noise in its own 1.25 Hz bin, about -23 dB in 2.5 kHz), and how far apart neighboring steps measured: about 10 dB each when the sending transmitter's power follows its audio drive, less when it is in ALC compression. The steps go before the beacon, not after it, so reply slots (Section 6.2) are timed from the end of the beacon as always; the beaconing station allows 5 s more for answers. Nothing else carries the spare bit set; a receiver rejects any other header whose spare bit is 1.

## 6. Link

### 6.1 Beacon

A station announces itself with a beacon frame (Section 5.8), first at level L2 and then, if that brings no answer, at L0 (see below). The beacon gives the callsign, grid locator and supported speed levels, says whether the station is taking answers and whether it holds mail for others, and carries the **mail-check flag** that asks any station holding mail for it to deliver now. After a beacon the station listens for the reply window (Section 6.2).

Since 0.30 every beacon has the mail-check flag set. A station that holds mail for others, or has delivery receipts to report, sends a **mail notice** (Section 5.8) immediately before its beacon, at the beacon's level: with every beacon at the first call-up level, and with an L0 beacon at most once in 30 minutes (a notice lasts 51 s at L0). Presence beacons (Section 6.11) have no notice. See Section 8. (The long beacon of Sections 5.9 and 6.13, which is about reach, carries only the holds-mail flag.)

A station may send a **long beacon** (Section 6.13) instead of this call-up. The beacon of this section is the default and is called the short beacon where the two need telling apart.

- **Middle level first.** Every call-up begins at L2, where the beacon (7.0 s), answer (9.5 s since 0.33, which added the answering station's locator) and confirmation (5.9 s) each take under 10 seconds and the whole exchange holds the calling frequency for about 25 seconds; at L0 it takes about 100. L2 needs a signal of about -14 dB (Section 5.2). If an L2 beacon brings no answer it can decode, the station beacons again at once at L0, which reaches down to about -20 dB; this second beacon does not count as one of the tries. Later beacons in the same call go at L0. The next call-up, after a contact or a later round, starts at L2 again. In the simulator (tools/callup_study.py) this cut the expected time on the calling frequency from 99 to 24 seconds on any steady path of -14 dB or better, and from 107-134 to 24-66 seconds in moderate fading at -10 dB or better, at a cost of about 21 seconds for stations too weak for L2.
- **Repeating a beacon.** A station that is otherwise listening may call for a partner again from time to time. Each round is one beacon and its reply window; if nobody answers, the station goes back to listening. Rounds are at least 5 minutes apart (the operator program allows 5 to 60 minutes), measured from the start of one round to the start of the next. A round is not sent while the station is in a contact, has answered another station and is waiting for the lock to be confirmed, or is making a directed call; after a contact the interval starts again from the end of the contact.
- **Attended operation.** Repeating beacons start only when the operator asks for them. The operator program stops them by itself after a period with no operator activity at the station (2 hours by default, adjustable from 15 minutes to 12 hours, or turned off by the operator), so that a station left alone does not go on calling. A station repeating beacons with nobody at the controls is under automatic control (Section 2).

### 6.2 Answer and the reply window

A station that wants to connect replies with an answer frame (Section 5.8), sent at the level the beacon came at: having decoded the beacon shows the path carries that level, and the beaconing station's reply window is sized for it. The answer reports how the beacon was received and names the speed level the answering station wants the beaconing station to use.

The numbers below are starting values from simulation, to be tuned on the air.

- **Reply slots.** The reply window is divided into slots, each as long as an answer at the beacon's level plus 2.4 seconds: 44.8 s after an L0 beacon, 16.7 s after L1, 11.9 s after L2 (since 0.33; the answer grew by its locator). The first starts 1 second after the beacon ends. A plain beacon is followed by one slot. A beacon with the wide-window flag set is followed by four.
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
- **Fast fading (since 0.35).** When the recent frames are all fading and every one of them has a measured Doppler spread from 0.5 to 2.5 Hz (Section 5.7), the receiver judges levels by a fast-fading table: L0 -14, L1 -8, L2 -10, L3 -1, L4 0 dB, against -8, -2, -8, -1 and 0 dB for fading in general. Fading that fast averages out within a frame, so slow frames suffer less than in slow, deep fading, which is the worst case and keeps the general table. Measured in simulation (tools/level_spread_study.py, two paths 1 ms apart, 20 frames a point, nine in ten decoded): at 0.1, 0.5 and 2 Hz of spread, L0 -8, -14, -16 dB; L1 -4, -8, -10; L2 -4, -10, -12; L3 0, -2, 0; L4 -2, 0, -4. L3 and L4 keep the general figures. In practice a receiver in fast fading asks for L2 from 2 dB weaker signals than before. One slow or unmeasured frame among the recent ones returns to the general table.
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

### 6.9 Calling frequencies (United States)

So that stations can find each other, one calling frequency is suggested per band. Each is the dial frequency of an upper-sideband radio. Kestrel's tones are centered 1500 Hz above it; the widest level, L4, reaches from 800 Hz to 2180 Hz above it. The table allows 500 Hz to 2500 Hz.

From version 0.29 the calling frequencies sit in an area of Kestrel's own on each band, with numbered channels beside them (Section 6.10), away from the calling frequencies other modes have settled on, as far as each band allows.

| Band | Calling (dial, USB) | Signal occupies | Why there |
|---|---|---|---|
| 80 m | 3582.5 kHz | 3583.0 to 3585.0 kHz | Just above the JS8 activity (3578 kHz), below the 97.221(b) segment (3585 kHz up) where Winlink gateways are. 80 m has no empty space; this is the least used that could be found. |
| 40 m | 7110.0 kHz | 7110.5 to 7112.5 kHz | Above the 97.221(b) segment (7100 to 7105 kHz) and the VarAC calling frequency (7105 kHz). |
| 30 m | 10147.0 kHz | 10147.5 to 10149.5 kHz | The top of the band, above FT8, FT4 and WSPR. The band is 50 kHz wide and full. |
| 20 m | 14112.5 kHz | 14113.0 to 14115.0 kHz | Above the 97.221(b) segment (to 14112 kHz) and the VarAC calling frequency (14105 kHz), below where phone begins outside the United States (14125 kHz). |
| 17 m | 18092.5 kHz | 18093.0 to 18095.0 kHz | Below FT8 (18100 kHz), FT4, JS8 and WSPR (18104 kHz) and the 97.221(b) segment (18105 to 18110 kHz); the 17 m data segment is only 42 kHz wide. Since 0.35. |
| 15 m | 21112.5 kHz | 21113.0 to 21115.0 kHz | Above the 97.221(b) segment and WSPR (21090 to 21100 kHz), well below FT4 (21140 kHz). Since 0.35. |
| 10 m | 28110.0 kHz | 28110.5 to 28112.5 kHz | Above the RTTY activity (28080 to 28100 kHz), below the 97.221(b) segment and WSPR (28120 kHz up) and FT4 (28180 kHz); the beacon segment (28200 to 28300 kHz) is left alone. Since 0.35. |
| 6 m | 50340.0 kHz | 50340.5 to 50342.5 kHz | In the 6 m digital area, above FT8 (50313 and 50323 kHz), FT4 and JS8 (50318 kHz) and MSK144 (50260 and 50280 kHz). Data is allowed anywhere above 50.1 MHz. Since 0.35. |

- **Kept clear of** (dial frequencies, from published lists in November 2026): FT8 3573, 7074, 10136, 14074 kHz; FT4 3575, 7047.5, 10140, 14080 kHz; WSPR 3568.6, 7038.6, 10138.7, 14095.6 kHz; JS8 3578, 7078, 10130, 14078 kHz; VarAC 3595, 7105, 10133, 14105 kHz; and, on 40 m and 20 m, the 97.221(b) segments used by Winlink and VARA gateways.
- **Attended stations only.** The 80 m, 40 m and 20 m calling frequencies and all their channels are outside the 97.221(b) segments, or share them with gateways. A station using them has an operator at the controls. Until version 0.28 the calling frequencies were inside those segments so that unattended mail holders could share them; unattended stations (Section 8) are not built yet and will be given frequencies of their own inside the segments when they are (Section 2).
- **Upper sideband on every band**, 80 m and 40 m included: the radio's data mode (often called USB-D, DATA-U or PKT-USB) where it has one, plain USB where it has not. Lower sideband is not used: it would turn the tones upside down. The reference program asks the radio for its data mode and falls back to plain USB if the radio has none.
- 80 m suits paths of roughly 50 to 300 miles in the evening and at night, when 40 m often skips over them; 40 m suits the same distances in the daytime and late afternoon.
- The reference program refuses to transmit on a frequency whose signal would fall outside the U.S. amateur data segments (Amateur Extra limits; General class starts 25 kHz higher on 80, 40, 20 and 15 m; all the frequencies here are inside the General limits).
- Every part of these bands is shared. A station listens before transmitting (Section 6.14) and moves if the frequency is in use.
- On 30 m the amateur power limit is 200 W PEP.
- These are first choices, to be confirmed by listening on the air. 160, 60 and 12 m: **TBD**. 17, 15, 10 and 6 m open mostly in daylight and near the peak of the solar cycle; 6 m mostly by sporadic E in summer, which the P.533 predictions (Section 6.15, 2 to 30 MHz) do not cover.
- Operators may use other frequencies by agreement. A station with no operator present must keep its whole signal inside a 97.221(b) segment.

### 6.10 Channels (working frequencies)

A long contact on a calling frequency keeps others from calling there. Once locked, the pair may move to a channel (a working frequency) and leave the calling frequency free.

- **Proposal.** The station holding the turn sends a status-3 acknowledgment with part number 3. Its message-number field carries the working frequency as an offset from the frequency on which the lock was made: a signed 16-bit count (two's complement) of 100 Hz steps, so +25 means 2.5 kHz higher.
- **Agreement.** A station that can change frequency answers with the same frame (status 3, part number 3, the same offset), then changes frequency when that frame has been sent. A station that cannot, or will not, answers with a plain reply (status 3, part number 0), and the contact stays where it is. A move is proposed at most once in a contact.
- **Meeting again.** The proposing station changes frequency when it hears the agreement, waits 3 seconds, and sends a probe (status 3, part number 2) at the level in use. The partner answers as for any probe, both start their measurements afresh, and the contact carries on. If the probe goes unanswered the usual reacquiring rule applies (Section 6.5), on the working frequency.
- **A lost agreement.** If a proposal gets no reply it is sent once more. If that also gets no reply, the proposing station goes to the working frequency anyway and probes there, in case its partner agreed without being heard.
- **Giving up.** A station that has moved at its partner's request and hears nothing from it on the working frequency for 150 seconds releases the lock.
- **An idle working frequency.** On a working frequency, the station that proposed the move watches the time since a message frame last went in either direction (or since the pair arrived). Keep-alive exchanges do not count. After 3 minutes with no message frame it closes the contact in the ordinary way, with closing identifications, and both stations return to the calling frequency. One minute beforehand it warns its own operator, who may keep the contact on the working frequency by sending a message.
- **Returning.** When the contact ends for any reason, each station returns to the calling frequency: after its closing identification has been sent, or at once if the lock is released without one.
- **Listen first.** The operator of the proposing station is responsible for choosing a channel that is clear. An automatic check of the channel before moving is **TBD** (the check of Section 6.14 covers the frequency the station is on).

**Channels** (dial, upper sideband; first choices, to be confirmed by listening). Channels are 2.5 kHz apart: the widest Kestrel signal is 1.4 kHz, which leaves about 1 kHz between neighbors.

| Band | Calling | Channel 1 | Channel 2 | Channel 3 | Channel 4 | Notes |
|---|---|---|---|---|---|---|
| 80 m | 3582.5 | 3585.0 | 3587.5 | 3590.0 | 3592.5 | The channels share 3585 to 3595 kHz with Winlink gateways and RTTY; listen first. They stop short of the VarAC calling frequency (3595 kHz). |
| 40 m | 7110.0 | 7112.5 | 7115.0 | 7117.5 | 7120.0 | Signals to 7122.5 kHz, inside the U.S. data segment (to 7125 kHz). |
| 30 m | 10147.0 | 10144.5 | none | none | none | Room for one channel only. |
| 20 m | 14112.5 | 14115.0 | 14117.5 | 14120.0 | 14122.5 | Signals to 14125.0 kHz. |
| 17 m | 18092.5 | 18090.0 | 18095.0 | none | none | The data segment is narrow: one channel below the calling frequency and one above, all below FT8 (18100 kHz). Since 0.35. |
| 15 m | 21112.5 | 21115.0 | 21117.5 | 21120.0 | 21122.5 | Signals to 21125.0 kHz, inside every class's data segment. Since 0.35. |
| 10 m | 28110.0 | 28102.5 | 28105.0 | 28107.5 | 28112.5 | Signals 28103.0 to 28115.0 kHz, below the 97.221(b) segment (28120 kHz). Since 0.35. |
| 6 m | 50340.0 | 50342.5 | 50345.0 | 50347.5 | 50350.0 | Signals to 50352.5 kHz. Since 0.35. |

For any other calling frequency, the channels offered are 2.5 kHz above and 2.5 kHz below it.

### 6.11 Directed calls, messages for one station, and broadcasts

- **Directed call.** A station may call one particular station instead of beaconing. It sends an answer frame (Section 5.8) with the directed-call flag set, the mail-check flag set (since 0.30) and the called station as destination: first at L2, and at L0 for any repeats. If the calling station has decoded a frame from the called station in the last 10 minutes, the channel report carries that reading and the level it supports, so the called station can start at that level; otherwise it carries no measurement (SNR at the bottom of the scale, fading index at its largest value) and asks for L0. Only the station named replies; every other station stays silent.
- **Who answers by itself.** A listening station may be set to answer directed calls by itself, or (the reference program's default) to just listen. A station that just listens transmits nothing unless its operator starts it, except that it accepts, by itself, a directed call from any station within 5 minutes of its own last beacon, and from a station it has itself called within the last 5 minutes: those calls answer something its operator started. Any other directed call is shown to the operator, who responds, if at all, with a directed call of its own (a call back).
- **Available or not.** The operator sets the station available or not available for contacts. While it is not available: (1) its beacons are presence beacons, with the listening flag 0 and no reply window, and nobody answers them; (2) a directed call addressed to it gets one short reply, a status-3 acknowledgment with part number 4 ("not available"), sent at the level the call came at, with the link number the caller is using (Section 6.3) and a report of how the call was received; nothing else is sent and no contact is made. A calling station that hears this reply stops calling at once and tells its operator. Operator programs show each station's last known availability. A station left not available with nobody at the controls is under automatic control when it sends that reply (Section 2).
- **Call back.** A station making a directed call that receives a directed call from the very station it is calling takes it as the answer: it stops calling and completes the lock as a called station would (below).
- **Being called.** An idle, listening station that receives a directed call addressed to it and takes it (as above) treats it as follows. It completes the lock as a beaconing station would (Section 6.3), except that its confirming acknowledgment has part number 1: it hands the first turn to the caller, who called because it has something to send. That first offer does not mean the called station has nothing to send. For the rest of the contact the called station takes the beaconing station's part: it keeps the turn if both find themselves sending, and its callsign comes first in the link number. It sends an identification frame the first time it holds the turn, since nothing it has sent so far carries its callsign. Until the lock is confirmed the calling station assumes the called station supports the same speed levels as itself.
- **Called while beaconing.** A station waiting in the reply window of its own beacon that receives a directed call to itself (an answer frame with the directed-call flag set) stops waiting for answers and confirms the call at once, as a listening station would.
- **No reply.** The call is repeated when its confirmation does not arrive; after 5 calls without a reply the calling station gives up.
- **Messages for one station.** A message may be marked for one callsign. It is sent to that station in a contact with it, as ordinary link frames with their usual acknowledgments; until then it waits, and since 0.30 copies of it may be handed to other stations to carry (Section 8). Its message number is fixed when it is queued. A station that has already worked a caller answers that caller's next beacon only if it has a message for that caller or for anyone.
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

### 6.15 Propagation predictions (reference program, since 0.32)

Nothing here is part of the signal; it helps the operator choose a band and a time.

- **Method.** Recommendation ITU-R P.533-14, run with the ITU's own implementation (ITURHFProp with P533 and P372, ITU-R Study Group 3, release v14.3), for one month, every hour, Kestrel's calling frequency on each band (Section 6.9), isotropic antennas, the operator's power and man-made noise setting (quiet rural, rural, residential, city), and a 2500 Hz bandwidth so that the predicted SNR is in the same 2.5 kHz as every Kestrel figure.
- **What is shown.** For each band and hour: the median SNR; the SNR reached on 9 days in 10; the reliability, P.533's basic circuit reliability with a required SNR of L0's limit plus 2 dB (-18 dB), that is the share of days on which the path supports the band and L0 works; the operational MUF; the dominant mode; the fastest level the median SNR supports on a fading path (Section 5.2); and which ITU-R F.1487 condition the path resembles: near vertical incidence when the dominant mode arrives 60 degrees or more above the horizon, one hop, or two hops or more. The best band at an hour is the most reliable (to the nearest 10 %), then the strongest.
- **Sunspot number.** P.533 needs the 12-month smoothed sunspot number. The program carries a table of NOAA SWPC's predicted monthly values ("prediction set"), shows the set in use and its issue date, and can take a newer set from NOAA over the internet or from an update file placed in its "updates" folder; the set with the latest issue date is used.
- **Today's ionosphere (since 0.34R1).** When the operator updates online, the program also fetches the effective sunspot number (eSSN) of prop.kc2g.com, which is fitted every 15 minutes to the world's ionosondes, and NOAA SWPC's space-weather scales and planetary K index. For a prediction of the current month, the 24-hour eSSN replaces the predicted monthly value while it is under six hours old (the two can differ by a factor of two on a given day); other months keep the prediction. The program warns of a radio blackout (NOAA R1 or worse, from a solar flare), a geomagnetic storm (Kp 5 or more) and a falling ionosphere (6-hour eSSN under 85 % of the 24-hour value). Nothing is fetched unless the operator asks.
- **The bands now (since 0.35).** On request ("Check the bands now") the program shows: the **short-path window**, from the nearest ionosonde sounding under an hour old and within about 900 miles of the path's middle (KC2G's collection of GIRO and NOAA soundings): foF2 and hmF2 give the highest usable frequency on the path by the secant law, foF2 x sqrt(1 + (d / 2 hmF2)^2), and the Kestrel bands below it; and **band activity on the path**: WSPR spots (wspr.live) and PSK Reporter reception reports of the last hour whose two ends lie within 300 km of the two stations, by band, with the median WSPR SNR. Answers are reused for five minutes (wspr.live allows 20 requests a minute; PSK Reporter asks for one every five minutes).
- **Checking the predictions (since 0.35).** For each station decoded whose grid is known, once an hour per band, the P.533 median SNR for that path, band and hour (with the sunspot number in use) is recorded beside the SNR actually heard. The Propagation window shows, over the last 30 days, how many were checked, the average of heard minus predicted, and the typical difference. The far station's power is not known; the operator's own power setting is assumed.
- **Reporting to PSK Reporter (since 0.35; off unless turned on).** Each station decoded (callsign, locator when known, the frequency of its signal, SNR, time) is reported to pskreporter.info as mode KESTREL, by its IPFIX protocol over UDP: at most one datagram about every five minutes with a random delay added, each callsign at most once in five minutes, the record descriptions in the first three datagrams and hourly.
- **Limits.** P.533 predicts the median conditions of the month; a solar flare or a geomagnetic storm on a given day is not in it (the warnings above only flag them). Ground wave is not predicted; a path under about 50 km is predicted as 50 km long.

### 6.16 Long notes (since 0.34)

A long note is a short message sent in long-beacon frames (Section 5.9), for paths too weak for any speed level: it is heard where the long beacon is heard, about 5 dB below L0. It is slow: a frame of about a minute carries eight characters.

**Frames.** Each frame is a long-beacon frame (same pattern, tones, body, coding and check value) whose last field bit, the long beacon's spare, is 1. The other 65 field bits are one of three kinds:

| Kind | Fields (bits) |
|---|---|
| 0, note header | kind (2), origin callsign (48), destination code (12), number of text frames less one (3) |
| 1, note text | kind (2), origin code (12), text frame number 0 to 7 (3), eight characters of 6 bits each (48) |
| 2, receipt | kind (2), origin callsign, the station that received the note (48), destination code, the note's sender (12), spare 0 (3) |

Kind 3 is not used. A **code** stands for a callsign: the low 12 bits of the CRC-16 (Section 4) of its 48 address bits (Section 4.2), with 0 replaced by 1; the code 0 means ALL. A **character** is a 6-bit number standing for one of these 64, in order from 0: space, A to Z, 0 to 9, then `. , ? ! ' " / : ; - + = ( ) @ # & * % $ < > _ [ ] ^ |`. Small letters are sent as capitals; other characters cannot be sent. A receiver accepts a header only if its callsign has the shape of an amateur callsign, a receipt only if, in addition, its spare bits are 0, and a text frame only if its code is not 0. (Before 0.39 a header had two bits for the count and a spare bit, and a text frame two bits for its number and seven characters of 7-bit ASCII.)

**A note** is a header followed by one to eight text frames: up to 64 characters, with trailing spaces removed. Each frame is its own transmission of 59.5 s, with the usual turnaround between them, so a note takes two to nine minutes. A telemetry message (Section 6.12) of up to 64 characters may be sent as a long note; it then carries the grid, power and count and as many stations as fit (about four). A receiver keeps the parts of a note it has heard for 40 minutes while it waits for the rest (three tries of the longest note). It is sent only when no contact is under way, and, like a long beacon, only when the frequency is clear (Section 6.14). The header carries the sender's callsign, which identifies the station.

**Receipt.** A station that receives the whole of a note addressed to it (its code in the header's destination) answers with a receipt, one long frame, once the frequency is free; it answers again if the same note arrives again more than 90 seconds later. A note to ALL gets no receipt and is sent once. A note to one station whose receipt is not heard within 150 seconds after its last frame is sent again, up to three times in all. The receiving station keeps the measurements of frames that did not decode and adds later copies to them (Section 5.9, "Adding repeats together"), so each try reaches further: two copies are heard about 2 dB further down than one.

**Showing notes.** Notes to the station or to ALL are shown to the operator, the same note only once in an hour. Notes to other stations are not shown, and the text of a long-note frame is not repeated in the activity log. Stations following 0.33 or earlier take long-note frames for noise.

### 6.17 Station details (since 0.40)

A receiver that decodes a beacon carrying a rig type or power fills them into the beaconing station's contact record, when it keeps one, naming the rig from Hamlib's list of radios ("Yaesu FT-991 (Hamlib 1035)"), or by its number when the list is not at hand. The operator chooses the station's antenna type in the reference program from a fixed list of common antennas, including Homebuilt and Other. Once a contact locks, the station sends its antenna type to the other station as an ordinary message, "ANT <type>" (once per antenna to a station it keeps a record of; every contact to one it does not), and a receiver fills it into that station's record. Nothing else about the contact changes.

### 6.18 Long call-up (since 0.41)

On a fading HF path the short levels need about -8 dB (Section 5.2's table), while the long frame (Section 5.9) reads down to about -22 dB. When a station's short directed calls go unanswered and the station called has been heard in a long frame (a long beacon, a long note or a receipt) within the last hour, the calling station calls it with long frames.

**The frame** is a long-note frame (Section 6.16) of kind 3: kind (2 bits) | origin callsign (48) | destination code (12) | phase (2) | traffic waiting (1). Phase 0 is a call, 1 an answer (the called station accepts), 2 "not available"; phase 3 is not sent. The traffic bit says the caller has a message waiting for the station called.

**When.** Short calls go first: L2, then L0 (Section 6.11). When the station called has lately been heard only in long frames, the short calls stop after two; otherwise after the usual five. A long call follows when the frequency is clear (Section 6.14). The station called answers at once, without waiting for a clear frequency, as for a receipt; while its operator is unavailable it sends one "not available" reply instead. With no answer within 150 seconds the call is sent once more (two tries in all); the receiver adds copies together (Section 5.9).

**The long contact.** A station that sends an answer, and a station that reads one, are in a long contact. Each side's waiting messages for the other go as long notes (Section 6.16): small letters as capitals, a character a note cannot carry as "?", 64 characters to a note. The long contact lasts while long frames keep coming from the partner, and lapses 30 minutes after the last one.

### 6.19 Idle timeout, Keep-Alive and the 10-second warning (reference program, since 0.41)

A locked contact with no messages either way for 3 minutes ends. On a working channel the link rules close it and both stations return to the calling frequency (Section 6.10); on the calling frequency the reference program ends it with the closing identification. Both operators are warned 10 seconds before, with two choices: Keep going (a short KEEP GOING message, which counts as traffic at both stations and restarts both timers) and Disconnect (End contact). Neither station times out while a frame is being sent or received.

Keep-Alive, a setting, gives a contact on a working channel 3 more minutes, never more and never on the calling frequency: shortly before the first limit the station sends one short KEEP-ALIVE message, which counts as traffic at both ends. A KEEP-ALIVE, sent or received, never earns another extension, so two stations with Keep-Alive on extend once between them.

### 6.20 Chained messages (since 0.42)

A message longer than one frame's 200 characters, up to 1,000, is sent as a chain of up to nine ordinary messages ("pieces"), each at most 200 characters. Each piece begins with its number and the number of pieces, in plain text: an open parenthesis, the piece number (1 to 9), a slash, the number of pieces (2 to 9), a close parenthesis and a space, as in "(2/5) ". The text is cut at spaces where possible; a word longer than a piece is cut where it must be. The pieces are sent in order inside one contact, each acknowledged and resent like any message (Section 6.6), and each may itself be split into frames (Section 6.8).

**Working channels only.** Pieces are sent only once the contact is on a working channel (Section 6.10). A station holding pieces for a partner on the calling frequency proposes a move to a working channel before its next traffic; if it cannot change frequency, the pieces wait. A broadcast to ALL is never chained.

**Receiving.** A receiver collects the pieces from one sender, shows the message as it fills in, with a gap where a piece is missing, and joins the pieces with single spaces once all have arrived. A new piece 1, or a piece with a different count, starts a new chain. Because the numbering is plain text, anyone monitoring can read a chain in order, and a station that does not join chains shows each piece as an ordinary message.

### 6.21 Updates (reference program, since 0.42)

The reference program asks the public list of releases where it is published whether a newer version exists: when it starts and once a day, or only at start, or never (the operator's choice). It sends nothing about the station. It says plainly when a newer release changes the signal version. With the operator's approval, Install now downloads the setup program, checks it against the SHA-256 published with it, waits until no contact is under way and nothing is being sent, closes the program the usual way (waiting messages are kept), installs the update and starts the program again. The published hash guards only against a damaged download; signed releases are planned before the first production release, and only then may an unattended station install updates by itself.

## 7. Nets (optional)

- **Net control:** a beaconing station may open a net instead of a one-to-one link. Stations that answer are admitted as members.
- **Turn-taking:** net control assigns each member a slot and sets the slot length for its net. Nets are the only place Kestrel uses fixed slots.
- **Addressing:** every frame carries "from" and "to"; "to" may be one member or ALL. Traffic to ALL is sent at the level the weakest member can decode. One-to-one traffic inside the net uses that pair's own level.
- **Backup net control:** net control names a backup and keeps it updated with the net's state (members, slots, waiting messages, delivered message IDs).
- **Heartbeat and takeover:** net control sends a heartbeat every cycle. If the backup misses a set number in a row (3 planned, **TBD**), it takes over, raises the net epoch number by one, announces the change at L0 and names a new backup.
- **Net epoch:** the highest epoch wins. A former net control that returns after a takeover sees the higher epoch and rejoins as a member.
- **Planned handoff:** net control can hand over to the backup immediately, without waiting for missed heartbeats.

## 8. Messaging and store-and-forward (disconnected operation)

Kestrel assumes no station is always on the air and no infrastructure exists. Stations come and go, and paths open and close with propagation. Messages move whenever two stations happen to hear each other. Since 0.30 this section describes what stations do; the values marked are first settings, to be tuned on the air.

### 8.1 Messages and their IDs

- **Message ID:** the origin callsign together with the message number (Section 4.2). A message for a named station gets its number when it is queued and keeps it, through restarts of the program, wherever its copies go. A station never reuses a number while copies of an older message with that number may still be traveling; a station with no record of its last number starts at a random one.
- **Lifetime:** 62 hours from when the message is queued (the most the lifetime field allows). Every copy carries the time left, rounded up to whole hours and sent in units of 2 hours.
- **Hops:** the number of times stations other than the origin have sent the message on. The origin sends 0; each carrier that sends it on adds one. No station sends a message on if that would make the count more than 4, and no station takes a message to carry that it could not send on.

### 8.2 Carrying mail

- **Sender's outbox:** the origin keeps every message until it learns of the delivery or the message expires. The origin is always the last-resort copy.
- **Handing over.** In any contact, after its own traffic for the partner, a station offers the partner each waiting message addressed to a third station, unless that partner already carries it. Each message is handed to at most 3 stations. It is sent inside the contact as fully addressed frames (frame type 1) carrying the destination, the origin, the message number, the hop count and the time left, split under the airtime limits (Section 6.8) and acknowledged frame by frame like any message.
- **Carrying.** A station whose operator has allowed it ("carry mail for others", on by default in the reference program) keeps the message once every part has arrived (it holds the whole text, and splits it again for its own level when it sends it on), with the callsign of the station that handed it over and the time it arrived (the accountability trail, 97.219). A station that will not carry it, has no room (first settings: 50 messages, 10 from any one origin) or could not send it on within the hop limit answers the first frame with a status-3 acknowledgment, part number 5, "does not carry mail", with the message number; the sender then offers that station no more mail in that run. A station that already holds the message, or has already handled it, answers "already have it" (status 2).
- **Passing on.** A carrier passes a message to another station only if that station's last mail notice, within 2 hours, listed the destination among the stations it hears, and at most to 2 stations. It never passes a message back to the station it came from or to its origin.

### 8.3 Delivery

- **On request, never pushed.** Every beacon and every directed call carries the mail-check flag (Sections 6.1, 6.11). A station holding mail for the beaconing or calling station answers that beacon or call even if its operator has set it to just listen (Section 6.11), and delivers in the contact that follows. A station also answers the beacon of a station whose last mail notice listed it among the stations mail is held for. Holders never call a station to push mail. This keeps delivery a reply to a station that asked, which is intended to fit the automatic-control rules (97.221), and saves airtime by sending mail only to stations that are listening.
- **First to deliver wins.** The destination remembers for 62 hours every message ID it has received, whichever station brought it, and answers any later copy with "already have it" (status 2) at its first frame. The holder then drops its copy without sending the rest. Messages from the origin itself in link frames count too: the origin's message number is the message number of the link frames.
- **Shown once.** The destination shows the message to its operator once, with the origin and, if it came through a carrier, the carrier ("Q1AAAA via Q2BB").

### 8.4 Receipts and the mail notice

- **Receipts.** When a holder delivers a message, or learns that the destination already has it, it drops its copy and lists a receipt for the message in its mail notices for 12 hours. The destination does the same for a message that reached it through a carrier, and the origin does the same for a message it delivered itself while copies were out with carriers.
- **Hearing a receipt.** A station that hears a mail notice listing a receipt for a message it holds drops its copy and never takes that message again. An origin that hears a receipt for one of its own messages marks it delivered.
- **The notice.** A station that holds mail or has receipts to list sends a mail notice just before its beacon (Section 6.1): up to three stations it holds mail for, three receipts and three stations it hears (Section 5.8). A station hearing a notice that lists it knows that station holds mail for it.
- **Expiry.** A message whose time has run out is dropped by its holders, and its origin tells the operator it was not delivered.

### 8.5 Not yet settled

- **Nets as temporary post offices:** while a net is running, net control holds the net's mail and copies it to the backup net control. When the net closes, undelivered mail stays with its holders and continues to be carried (Section 7).
- Unattended mail holders, with frequencies of their own inside the 97.221(b) segments (Section 6.9).

## 9. Open items

- Speed level L5 (a faster waveform) and any further levels.
- Measurement of Doppler spread and delay spread; level limits confirmed by on-air tests.
- Store-and-forward settings to be confirmed on the air: hop limit (4), message lifetime (62 hours), how long receipts are listed (12 hours), how many carriers per message (3 by the origin, 2 by a carrier), holder storage (50 messages, 10 per origin).
- Band starting profiles.
- Net slot timing rules; heartbeat miss count.
- ARRL review of the 97.221(b) reading in Section 2 for unattended mail holders (asked; awaiting a reply).

## 10. Roadmap (proposed, November 21, 2026)

The aim is one open mode that reaches like WSPR, carries messages like JS8Call and moves traffic quickly when the path allows, like VARA, with store-and-forward and net-control failover built in. It is reached by stretching Kestrel's one-mode, many-levels design at both ends. Each step is proposed, not settled; each becomes part of this description only when its signal is defined and tested.

| Step | Work | Purpose |
|---|---|---|
| 1. Prove the link | Recording and decoding received audio; near-miss reports; fading re-measured and the header moved (0.26); on-air setup checks; on-air tests at 100+ miles | Show that the existing levels hold a contact over real HF paths |
| 2. A WSPR-like bottom level | **First part in 0.27: the long beacon** (Sections 5.9, 6.13), about a minute, shown to the operator, not answered. Timed slots proved unnecessary. **0.28: receivers add repeated long beacons together** and remove steady carriers. Still open: a reply at this level (a reception report), and short notes | Reach: be heard where nothing else gets through |
| 3. Nets and mail | **First part in 0.30: store and forward** (Section 8): mail handed to carriers, delivered on request, receipts in a mail notice. Still open: nets with net control, backup and takeover (Section 7), and nets as post offices | Groups and disconnected operation, at every level |
| 4. A VARA-like top level | A multi-carrier PSK or OFDM waveform within 2.8 kHz for strong paths (Section 5.2, L5) | Throughput for relays and longer traffic |

Steps 2 and 4 change the signal and will raise the signal version. Step 3 is mostly link and messaging rules, though its first part (0.30) added the mail notice frame.

## 11. Document history

See `CHANGELOG.md` in this folder.
