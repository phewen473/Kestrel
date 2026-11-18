# Kestrel Technical Description

**Version 0.9 (draft), 18 November 2026.** Not yet in use on the air. Values marked **TBD** are placeholders that will be fixed before the first on-air test.

This document is the public technical description of the Kestrel digital mode under FCC rule 97.309(a)(4). It will be updated, with a new version number, whenever the transmitted signal changes.

© 2026 P. H. Ewen (KO4WSC). Licensed under Creative Commons Attribution 4.0 International (see `docs/LICENSE-CC-BY-4.0.txt`). Any reuse or adaptation must credit the original Kestrel project, https://github.com/phewen473/Kestrel, and state what was changed.

## 1. Purpose

Kestrel carries short free-text messages over HF radio between amateur stations. It adapts its speed to the radio path as conditions change and is built to keep a working link in weak, fading and noisy conditions.

## 2. Regulatory summary (United States)

- **Emission:** data, sent as audio tones through a single-sideband transmitter.
- **Bandwidth:** every Kestrel waveform stays within 2.8 kHz on HF.
- **Content:** plain text. Kestrel never encrypts or obscures message meaning (97.113). Message signing to prove the sender may be added later; it does not hide content.
- **Identification:** every beacon and connection frame carries the sending station's callsign.
- **Automatic operation:** unattended relays and mailboxes are subject to the message-forwarding and automatic-control rules (97.219, 97.221).

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
- Four frame sizes (size classes), holding 350, 700, 1050 or 1400 text bits. That is 50, 100, 150 or 200 characters of plain text at 7 bits each. The sender uses the smallest class that holds the text.
- **Body contents**, in order: the character count (8 bits), the text bits padded with zeros to the class size, and a 16-bit check value over everything before it. The body therefore holds 374, 724, 1074 or 1424 bits.
- **Body check value:** CRC-16 with polynomial 0x1021, start value 0xFFFF, no bit reversal and no final inversion (CRC-16/CCITT-FALSE), most significant bit first.

### 4.1 Text compression

Text may be sent plain (7 bits per character, most significant bit first) or compressed. A flag in the header says which.

- The compressed form is a fixed Huffman code: each ASCII character has a code of 3 to 13 bits, short for common characters (space 3 bits, "e" and "t" 4 bits) and long for rare ones. The code length and code of every character are listed in `tables/compression_codes.txt`.
- The codes follow from the lengths by the canonical rule: sort the characters by (code length, character number); the first gets code 0; each next character gets the previous code plus one, shifted left by the increase in length. Codes are sent most significant bit first.
- The character count in the body tells the receiver how many characters to decode; the padding after them is ignored.
- **Rule for the sender:** compress only when the compressed text fits a smaller size class than the plain text. Otherwise send plain.

Typical savings are about a quarter for plain English and about a seventh for traffic that is mostly capitals and digits.

## 5. Modem

All audio figures assume a sample rate of 12,000 samples per second.

### 5.1 Frame structure

Every frame has three parts, in order:

1. **Chirp pair:** a linear frequency sweep up from 500 Hz to 2500 Hz lasting 1 second, followed at once by a linear sweep down from 2500 Hz to 500 Hz lasting 1 second (audio frequencies; 2 seconds in all). Each sweep fades in and out over 20 ms. The pair is used to find the frame and to measure its timing and frequency offset. Two sweeps are used because a single sweep cannot tell a timing error from a frequency error: a frequency error moves the two detection peaks in opposite directions, while a timing error moves them together.
2. **Header:** 24 tones sent at the same speed level as the body (Section 5.4).
3. **Body:** the payload at the frame's speed level, with known pilot tones spread through it (Section 5.5).

The receiver is not told the level in advance. After the chirp pair it tries to read the header at each speed level in turn. A level is a candidate when the header's check value matches, the header's level field names that same level, and the spare bit is zero. Noise can occasionally make a wrong level pass, so the receiver accepts a level only when the body read at that level also passes its check. Sending the header at the frame's own level keeps fast frames short: a header at the slowest level would add about 10 seconds to every frame.

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
| L0 | 76 s | 136 s | 195 s | 255 s | -20 dB | -12 dB |
| L1 | 27 s | 47 s | 67 s | 87 s | -16 dB | -8 dB |
| L2 | 19 s | 32 s | 46 s | 59 s | -15 dB | -9 dB |
| L3 | 10 s | 17 s | 24 s | 30 s | -12 dB | -4 dB |
| L4 | 6 s | 10 s | 13 s | 16 s | -9 dB | -3 dB |

- **Steady signal:** noise only; every test frame decoded at this SNR.
- **Fading signal:** nine test frames in ten decoded at this SNR in the worst of three simulated HF paths (light, moderate and heavy fading, ITU-R F.1487). The remaining frames are recovered by combining retries (Section 5.6).

A station chooses the fastest level whose limit, for the kind of signal it is measuring (Section 5.7), is at least 2 dB below the measured SNR. These limits guide the choice; they do not change the signal, and they will be revised after on-air tests.

L1 and L2 are sized so that a full 200-character frame fits the 90-second and 60-second limits of Section 6.8. Frames longer than those limits are not sent; at the slow levels a long message is split into shorter parts instead.

A faster level (L5) is planned. It needs a different waveform, because tones this short would be too wide: **TBD**.

### 5.3 Error correction and interleaving

**Body.** The body is protected by a rate-1/2 low-density parity-check (LDPC) code of the repeat-accumulate kind. For k body bits (k = 374, 724, 1074 or 1424) the codeword is the k body bits followed by k parity bits.

- There are k parity checks. Every body bit takes part in exactly three checks. Parity bit i takes part in check i and in check i + 1 (the last parity bit only in the last check).
- So parity bit 0 equals the XOR of the body bits in check 0, and parity bit i equals parity bit i - 1 XOR the body bits in check i.
- The three checks of each body bit are listed, for every k, in `tables/ldpc_checks_k<k>.txt`. They come from three pseudo-random shuffles of 0..k-1 made with the xorshift32 generator (shifts 13, 17, 5; start values 0x4B455301, 0x4B455302, 0x4B455303) and a Fisher-Yates shuffle, then repaired so that no body bit uses the same or neighbouring checks twice and no two body bits share more than one check. The reference program `modem/ldpc.py` is the exact definition; the table files are its output.

**Interleaver.** The codeword is padded with zeros to a whole number of tones (750, 1450, 2150 or 2850 bits) and shuffled: bit i of the padded codeword is sent in position (step x i) mod n, where n is the padded length and step is the whole number nearest to n x 0.6180339887 that shares no factor with n (searching outwards, above before below). The steps are 463, 897, 1329 and 1763. The shuffled bits are then grouped in fives to make the data tones.

**Receiver side.** Impulse noise (static crashes) is detected and blanked before decoding. The decoder is not specified; the reference uses normalised min-sum belief propagation.

### 5.4 Header

The header carries 16 field bits followed by an 8-bit check value:

| Field | Bits | Meaning |
|---|---|---|
| Frame type | 3 | 0 = message or part of a message |
| Speed level | 3 | 0 to 4 |
| Size class | 2 | 0 to 3 (350, 700, 1050 or 1400 text bits) |
| Part number | 3 | 0 for the first part |
| Part count | 3 | number of parts minus one |
| Compressed | 1 | 1 when the text is compressed |
| Spare | 1 | always 0 |

- **Header check value:** CRC-8 with polynomial 0x07 and start value 0x00 over the 16 field bits, most significant bit first.
- **Header coding:** the 24 bits are followed by 6 zero bits and encoded with the rate-1/2, constraint-length-7 convolutional code with generators 171 and 133 (octal), giving 60 bits, sent as 12 tones. For each input bit the 7-bit register is the six previous input bits (oldest in the highest position) followed by the new bit; the first output bit is the parity of the register ANDed with 171 octal, the second with 133 octal.
- The 12 tones are sent twice in a row (24 tones).
- Addresses and message identifiers are not yet in the header: **TBD**.

### 5.5 Pilots

In the body, one pilot tone is sent before every 15 data tones (so body tones 0, 16, 32, ... are pilots). Pilot number g, counting from 0, uses tone (7 x g + 3) mod 32. The receiver uses the pilots to follow frequency drift through the frame and to measure the signal-to-noise ratio.

### 5.6 Combining retries (HARQ)

When a frame fails its check, the receiver keeps the soft values of the body. The retransmission is combined with the stored copy, so the pair can decode below the level either copy could alone.

### 5.7 Tracking and channel measurement

- The chirp pair gives the starting frequency offset and timing.
- The pilots keep the frequency estimate current through the body.
- Stations keep accurate clocks (NTP or GPS); this narrows the timing search but is not used to define time slots.

Each received frame yields three measurements, which are reported back to the sender in every acknowledgment:

- **Frequency offset**, from the chirp pair and the pilots.
- **Signal-to-noise ratio (SNR)** in 2.5 kHz. Once a frame has decoded, the receiver knows every tone that was sent. The signal energy is the average, over all body tones, of the energy at the sent tone plus the bin on each side of it, less the noise in those three bins. The side bins are included because fast fading moves part of a tone's energy into them. The noise is taken from the tone positions that were not sent.
- **Fading index.** The spread (variance) of those per-tone energies, less the spread that noise alone would cause, divided by the square of the average signal energy. It is close to 0 for a steady signal and close to 1 for a signal that fades deeply and often during the frame. A frame with an index above 0.15 counts as a fading signal when choosing a level (Section 5.2).

When a frame fails its check, the same measurements are made from the pilot tones alone.

Measurements of Doppler spread (fading speed) and delay spread (multipath) are planned.

## 6. Link

### 6.1 Beacon

A station announces itself with a beacon at level L0. The beacon carries the callsign, Maidenhead grid locator, the speed levels the station supports, a flag saying whether it is accepting connections, a short heard list (stations it has heard recently and their SNR), the callsigns it is holding mail for, the IDs of recent delivery receipts it knows of, and a **mail-check flag** that asks any station holding mail for it to deliver now. After a beacon the station listens for a reply window. Window length: **TBD**.

### 6.2 Answer

A station that wants to connect replies inside the window at L0. If several stations reply, each picks a random slot within the window to reduce collisions, and the beaconing station chooses one.

### 6.3 Negotiation and lock

The two stations exchange channel measurements and agree on a starting level, using the band's starting profile (Section 6.6) as the first guess. They then align timing and frequency and enter the LOCKED state. From then on every frame is addressed to the pair and keeps its own session timing, set by the handshake.

### 6.4 Lock states

| State | Meaning | Leaves when |
|---|---|---|
| LOCKED | Link healthy | Conditions slip → DEGRADED; END sent or received → RELEASED |
| DEGRADED | Errors or SNR falling | Frames clean again → LOCKED; sustained loss → REACQUIRE |
| REACQUIRE | Sending short sync bursts at L0 using the last known offset, timing and level | Sync regained → LOCKED; timeout → RELEASED |
| RELEASED | Session over | Station returns to beaconing or listening |

A single bad frame never drops the lock. Timeouts and thresholds: **TBD**.

### 6.5 Acknowledgment and speed changes

- Every frame is acknowledged (ACK) or rejected (NAK). Each ACK or NAK carries the receiver's latest channel measurements: SNR, fading index and frequency offset (Section 5.7).
- After several clean frames in a row the link steps up one level. Count: **TBD**.
- When measurements show conditions slipping, the link steps down before frames start failing. After a failed frame it steps down and resends, with HARQ combining.
- A short keep-alive holds the lock between messages.

### 6.6 Band starting profiles

Each band has default starting assumptions for noise, fading and multipath (for example, impulse noise and near-vertical multipath on 160 and 80 m, long-path fading on 20 m, sudden changes on 6 m). Profile values: **TBD**.

### 6.7 Unconnected traffic

Beacons, calls and messages to no particular station are sent at a robust fixed level, since there is no partner to negotiate with.

### 6.8 Airtime limits and message splitting

No single transmission should hold the frequency for long. The link applies these rules automatically, using the channel measurements it already has:

1. **Fastest level first.** The link uses the fastest speed level the measured conditions support.
2. **Default limit: 60 seconds per transmission.** The link does not choose a level that would make a message frame run longer than this.
3. **Poor-conditions limit: 90 seconds.** When the measured conditions are too poor for the message to fit in 60 seconds, the link allows up to 90 seconds without operator action.
4. **Splitting.** When the message still does not fit, it is sent as two or more shorter parts. Each part is a frame of its own within the 90-second limit and is acknowledged separately, so a failed part is retried alone. The header of each part carries its part number and the number of parts (Section 5.4), up to 8 parts; the message is delivered, and its receipt issued, when all parts have arrived. The message ID that ties the parts together: **TBD**.

Both limits are operator settings; 60 and 90 seconds are the defaults.

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

- **Message ID:** every message has a unique ID so it is never delivered twice, however many stations hold a copy.
- **Sender's outbox:** the sender keeps every message until a delivery receipt returns or the message expires. The sender is always the last-resort copy.
- **Holding partners:** one or more stations may accept and store a copy of the same message. Each holding partner confirms to the sender that it holds the message, so the sender knows who is carrying it. Holders list the callsigns they hold mail for in their beacons.
- **Automatic delivery, on request:** delivery needs no operator action, but it is always a reply. When a holder hears a beacon from the destination with the mail-check flag set, it answers in the reply window and delivers. When a holder hears a beacon with the mail-check flag from a station that can reach the destination (shown in that station's heard list), it passes the message on the same way. Holders never call a station unprompted to push mail. This keeps unattended holders replying to a station that asked, which is intended to fit the automatic-control rules (97.221), and saves airtime by sending mail only to stations that are listening.
- **Accountability trail:** every stored copy records the originating callsign and the callsign of the station it was received from, so the forwarding path can always be traced (97.219).
- **First to deliver wins:** a holder first offers the message ID. If the destination does not have it, the holder sends the message; if the destination already has it, it answers "already delivered" and the holder drops its copy without sending it again. The first holder to complete delivery wins.
- **Hop limit:** each relay adds one hop; a hop limit (4 planned, **TBD**) stops messages circulating.
- **Receipt to every holder:** when a message reaches its destination, the destination issues a delivery receipt carrying the message ID. The receipt travels back toward the sender like a small message, is passed to every known holding partner, and is listed in beacons for a time (recent-receipts list). Every holder that learns of the receipt drops its copy, and the sender marks the message delivered.
- **Expiry:** every message carries a lifetime (48 hours planned, **TBD**). When it runs out, holders drop the message and the sender is told it was not delivered.
- **Nets as temporary post offices:** while a net is running, net control holds the net's mail and copies it to the backup net control. When the net closes, undelivered mail stays with its holders and continues to be carried.
- **Duplicates:** a message whose ID has already been handled, whose hop limit is reached, or whose lifetime has run out is dropped.

Each station applies the same checks to every message it receives: deliver it if it is addressed to this station; otherwise drop it if seen before, out of hops or expired; otherwise relay it if the destination is reachable now; otherwise hold it and announce it in beacons until it is delivered, a receipt is heard or it expires. All of this runs automatically.

## 9. Open items

- Speed level L5 (a faster waveform) and any further levels.
- Measurement of Doppler spread and delay spread; level limits confirmed by on-air tests.
- Addresses and message identifiers in the header; frame types other than a message (beacon, answer, acknowledgment).
- Reply window length, timeouts, step-up count and other thresholds.
- Band starting profiles.
- Net slot timing rules; heartbeat miss count; hop limit.
- Message lifetime; how long receipts stay listed.
- Message splitting: how parts are held and forwarded by holding partners.
- Beacon size: short hashed message IDs, caps on the held-mail and receipt lists, and which entries go first when a list is full.
- Storage limits: how much mail a holder will carry in total and per originating station.
- Confirm with ARRL that reply-on-mail-check delivery by unattended holders fits 97.221, and which band segments apply.

## 10. Document history

See `CHANGELOG.md` in this folder.
