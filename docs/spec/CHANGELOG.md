# Kestrel specification changelog

## 0.12 (draft) - 18 November 2026

- Four control frames defined (frame types 2 to 5): beacon, answer, acknowledgment and identification. They use the same chirp pair, header, pilots and interleaver as message frames, with a short body protected by the header's convolutional code.
- Channel report defined as an 18-bit field: SNR, fading index, frequency offset and the speed level the receiver wants next.
- Link rules stated: each direction has its own speed level; a station sends at the level its partner last asked for, or slower. The lock is confirmed by an acknowledgment frame with status 3, which is also the keep-alive.
- Station identification inside a lock is now a defined frame, sent at least every 10 minutes and at the end of the contact.
- Message frames are unchanged from 0.10.

## 0.11 (draft) - 18 November 2026

- The transmitted signal is unchanged from 0.10.
- Regulatory summary: unattended mail holders operate under 97.221(b) and, on HF, stay within the band segments that paragraph lists. Paragraph (c) does not fit, because every frame is wider than 500 Hz.

## 0.10 (draft) - 18 November 2026

- Every message frame now starts its body with an address block, and there are two kinds of message frame. A link frame (frame type 0) carries a 12-bit link number and a 16-bit message number. A fully addressed frame (frame type 1) carries destination and origin callsigns (48 bits each), the message number, a hop count and the remaining lifetime.
- Callsign coding defined: up to 9 characters (letters, digits, "/", "-") in 48 bits. An address with no digit is a group name; "ALL" is everyone.
- The message ID is the origin callsign plus the message number.
- The body grows by 28 bits to 402, 752, 1102 or 1452 bits, so frames are slightly longer (200 characters: 60 s at L2, 89 s at L1). New LDPC tables in `tables/`; new interleaver steps.
- A fully addressed frame is the same length as a link frame of its size class and holds 13 fewer plain characters (36, 86, 136 or 186).
- Station identification inside a lock noted as an item to define (97.119).
- Level limits re-measured with the new frame sizes: L2 steady -14 dB (was -15); fading L1 -10 dB (was -8) and L4 -1 dB (was -3).

## 0.9 (draft) - 18 November 2026

- The transmitted signal is unchanged from 0.8.
- Channel measurement defined: every received frame yields an SNR, a fading index (0 for a steady signal, about 1 for deep, frequent fades) and a frequency offset, reported back in every acknowledgment.
- The level table gains a second limit for fading signals, measured in simulation over light, moderate and heavy fading. A frame with a fading index above 0.15 counts as fading.
- The rule for choosing a level is stated: the fastest level whose limit is at least 2 dB below the measured SNR.

## 0.8 (draft) - 18 November 2026

- Speed levels L0 to L4 are now defined exactly: tone length, tone frequencies, airtime of each frame size, and the weakest signal each level decoded in simulation.
- Body error correction is now defined: a rate-1/2 repeat-accumulate LDPC code, with its check tables in `tables/`. It replaces the convolutional code used in earlier prototypes for the body; the header keeps the convolutional code.
- Text compression added: a fixed Huffman code (`tables/compression_codes.txt`), used only when it lets the text fit a smaller frame. The header has a new "compressed" flag.
- A fourth frame size added (150 characters), so frames are 50, 100, 150 or 200 characters.
- Header fields, header coding, check values (CRC-8 and CRC-16), interleaver and pilot pattern are now written out in full.
- The receiver accepts a speed level only when both the header and the body check out at that level.

## 0.7 (draft) - 18 November 2026

- The header is now sent at the frame's own speed level, not at the most robust level. The receiver finds the level by trying the header at each one and accepting the level whose check value matches and whose level field agrees. Chosen after simulator tests: every test frame was received at the right level, and fast frames avoid about 10 seconds of header.
- The header also carries the part number and number of parts of a split message.

## 0.6 (draft) - 18 November 2026

- Signature chirp fixed as a pair: 500 to 2500 Hz up in 1 second, then 2500 to 500 Hz down in 1 second, each with 20 ms fades. Chosen after simulator tests showed the pair separates timing error from frequency error.

## 0.5 (draft) - 18 November 2026

- Airtime limits: 60 seconds per transmission by default, extended automatically to 90 seconds in poor conditions; both are operator settings.
- Messages that do not fit within the limit are split into parts, each sent and acknowledged as its own frame.

## 0.4 (draft) - 18 November 2026

- Beacons carry a mail-check flag. Holders deliver or pass on mail only in reply to a beacon with that flag; they never push mail unprompted.
- Every stored copy records the originating callsign and the station it came from (accountability trail).
- New open items: beacon size limits, holder storage limits, and confirming the automatic-control approach with ARRL.

## 0.3 (draft) - 18 November 2026

- Holding partners: one or more stations may store the same message and confirm to the sender that they hold it.
- Delivery is fully automatic when a holder hears the destination.
- First to deliver wins: holders offer the message ID first; a destination that already has it answers "already delivered".
- Delivery receipts are passed to every holding partner and listed in beacons, so all copies are dropped.

## 0.2 (draft) - 18 November 2026

- Store-and-forward redesigned for disconnected operation: no always-on station is assumed.
- Added sender's outbox, carry-and-forward with held-mail announcements in beacons, receipts that clear other holders' copies, message expiry, and nets as temporary post offices.
- Removed mailbox hubs.
- Beacons now list the callsigns a station holds mail for.

## 0.1 (draft) - 18 November 2026

- First public draft of the technical description.
- Covers purpose, regulatory summary, layer model, character set, frame structure (chirp, header, body), speed levels (estimates), error correction, HARQ, tracking, link states, nets, and store-and-forward.
- Not yet used on the air.
