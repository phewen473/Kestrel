# Kestrel Technical Description

**Version 0.1 (draft), 18 November 2026.** Not yet in use on the air. Values marked **TBD** are placeholders that will be fixed before the first on-air test.

This document is the public technical description of the Kestrel digital mode under FCC rule 97.309(a)(4). It will be updated, with a new version number, whenever the transmitted signal changes.

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
- Three frame sizes (size classes): 50, 100 and 200 characters. The sender uses the smallest class that holds the message.
- Each frame carries a CRC so the receiver can confirm it decoded the message correctly. CRC length: **TBD** (16 bits planned).

## 5. Modem

### 5.1 Frame structure

Every frame has three parts, in order:

1. **Chirp:** a short frequency sweep across the Kestrel passband. Used to find the frame, measure frequency offset and set timing. Length and sweep width: **TBD**.
2. **Header:** a short block sent at the most robust level, whatever the level of the rest of the frame. It states the frame type, speed level, size class and the addresses needed to route it. Exact fields: **TBD**.
3. **Body:** the payload at the negotiated speed level, with known pilot symbols spread through it so the receiver can keep tracking timing, frequency and fading to the end.

Because the header states the level and size, the receiver always knows how long the frame is and how to decode it. No global time slots are needed.

### 5.2 Speed levels

Kestrel uses a family of waveforms, numbered L0 (slowest, most robust) upward. The robust levels use multiple-tone frequency-shift keying (MFSK), which does not depend on carrier phase and holds up in deep fading. The fast levels use phase-based modulation (PSK, possibly OFDM) and are used only when the path supports them.

The number of levels and their exact waveforms are **TBD**. Working estimates for a full 200-character frame:

| Level | Airtime, 200 chars | Weakest usable SNR (2.5 kHz) | Use |
|---|---|---|---|
| L5 | about 5 s | about −5 dB | strong, stable paths |
| L4 | about 15 s | about −10 dB | |
| L3 | about 30 s | about −13 dB | |
| L2 | about 60 s | about −16 dB | |
| L1 | about 2 min | about −19 dB | |
| L0 | about 4 min | about −22 dB | beacons, calls, headers |

A 100-character frame takes about half these times and a 50-character frame about a quarter, plus the fixed chirp and header.

### 5.3 Error correction and interleaving

- Forward error correction on every body: LDPC planned; code rates per level **TBD**.
- Bits are interleaved across the whole frame in time and across tones, so a short fade or burst costs a little of everything rather than a whole section.
- Impulse noise (static crashes) is detected and the affected symbols are marked as erasures instead of being trusted.

### 5.4 Combining retries (HARQ)

When a frame fails its CRC, the receiver keeps what it received. The retransmission is combined with the stored copy, so the pair can decode below the level either copy could alone.

### 5.5 Tracking

- The chirp gives the starting frequency offset and timing.
- Pilot symbols through the body keep frequency, timing and fading estimates current.
- Offset and drift measured on one frame carry forward to the next.
- Stations keep accurate clocks (NTP or GPS); this narrows the timing search but is not used to define time slots.

### 5.6 Channel measurement

Each received frame yields measurements of signal-to-noise ratio, Doppler spread (fading speed), delay spread (multipath) and frequency offset. These are reported back to the sender in every acknowledgment.

## 6. Link

### 6.1 Beacon

A station announces itself with a beacon at level L0. The beacon carries the callsign, Maidenhead grid locator, the speed levels the station supports, a flag saying whether it is accepting connections, and a short heard list (stations it has heard recently and their SNR). After a beacon the station listens for a reply window. Window length: **TBD**.

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

- Every frame is acknowledged (ACK) or rejected (NAK). Each ACK or NAK carries the receiver's latest channel measurements.
- After several clean frames in a row the link steps up one level. Count: **TBD**.
- When measurements show conditions slipping, the link steps down before frames start failing. After a failed frame it steps down and resends, with HARQ combining.
- A short keep-alive holds the lock between messages.

### 6.6 Band starting profiles

Each band has default starting assumptions for noise, fading and multipath (for example, impulse noise and near-vertical multipath on 160 and 80 m, long-path fading on 20 m, sudden changes on 6 m). Profile values: **TBD**.

### 6.7 Unconnected traffic

Beacons, calls and messages to no particular station are sent at a robust fixed level, since there is no partner to negotiate with.

## 7. Nets (optional)

- **Net control:** a beaconing station may open a net instead of a one-to-one link. Stations that answer are admitted as members.
- **Turn-taking:** net control assigns each member a slot and sets the slot length for its net. Nets are the only place Kestrel uses fixed slots.
- **Addressing:** every frame carries "from" and "to"; "to" may be one member or ALL. Traffic to ALL is sent at the level the weakest member can decode. One-to-one traffic inside the net uses that pair's own level.
- **Backup net control:** net control names a backup and keeps it updated with the net's state (members, slots, waiting messages, delivered message IDs).
- **Heartbeat and takeover:** net control sends a heartbeat every cycle. If the backup misses a set number in a row (3 planned, **TBD**), it takes over, raises the net epoch number by one, announces the change at L0 and names a new backup.
- **Net epoch:** the highest epoch wins. A former net control that returns after a takeover sees the higher epoch and rejoins as a member.
- **Planned handoff:** net control can hand over to the backup immediately, without waiting for missed heartbeats.

## 8. Messaging and store-and-forward

- **Message ID:** every message has a unique ID so it is never delivered twice.
- **Mailbox:** a station may hold messages for a callsign it cannot reach now and deliver them when that station is heard or joins a net.
- **Relay:** if the destination cannot be reached directly but a station that can reach it is in the heard lists, the message is passed to that station. Each relay adds one hop; a hop limit (4 planned, **TBD**) stops messages circulating.
- **Receipt:** when a message reaches its destination, a delivery receipt returns to the sender.
- **Duplicates:** a message whose ID has already been handled, or whose hop limit is reached, is dropped.
- **Hubs:** an always-on station may act as a mailbox hub for others.

Each station applies the same checks to every message it receives: deliver it if it is addressed to this station; otherwise drop it if seen before or out of hops; otherwise relay it if the destination is reachable; otherwise hold it in the mailbox.

## 9. Open items

- Number of speed levels and the exact waveform of each.
- Chirp length and sweep width; header fields and coding.
- LDPC codes and rates; CRC length.
- Reply window length, timeouts, step-up count and other thresholds.
- Band starting profiles.
- Net slot timing rules; heartbeat miss count; hop limit.
- Audio passband position and occupied bandwidth of each level (all within 2.8 kHz).

## 10. Document history

See `CHANGELOG.md` in this folder.
