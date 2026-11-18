# Kestrel specification changelog

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
