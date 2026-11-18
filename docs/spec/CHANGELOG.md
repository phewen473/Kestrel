# Kestrel specification changelog

## 0.2 (draft) - 18 November 2026

- Store-and-forward redesigned for disconnected operation: no always-on station is assumed.
- Added sender's outbox, carry-and-forward with held-mail announcements in beacons, receipts that clear other holders' copies, message expiry, and nets as temporary post offices.
- Removed mailbox hubs.
- Beacons now list the callsigns a station holds mail for.

## 0.1 (draft) - 18 November 2026

- First public draft of the technical description.
- Covers purpose, regulatory summary, layer model, character set, frame structure (chirp, header, body), speed levels (estimates), error correction, HARQ, tracking, link states, nets, and store-and-forward.
- Not yet used on the air.
