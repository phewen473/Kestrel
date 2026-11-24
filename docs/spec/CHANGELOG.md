# Kestrel specification changelog

## 0.33 (draft) - November 23, 2026

- **SIGNAL VERSION 0.33. Stations following 0.32 or earlier cannot read 0.33 answers and directed calls, nor 0.33 stations theirs.**
- **The answer frame carries its sender's grid locator** (Section 5.8): 15 bits after the two callsigns, coded as in the beacon; all ones means the sender has no locator set. The answer grows from 124 to 139 field bits (70 body tones, interleaver step 201): 9.5 s at L2 (was 8.9 s), 42 s at L0 (was 40 s). Reply slots grow to match: 44.8 s after an L0 beacon, 16.7 s after L1, 11.9 s after L2 (Section 6.2). Directed calls are answer frames, so they carry it too. Why: a station heard only through an answer or a directed call had no known location, and the reference program's propagation predictions (Section 6.15) work from the locator.
- The reference program: a saved contact's locator is brought up to date whenever that station sends one (beacon, long beacon, answer or directed call), and the operator is told when it changes. Compiled library interface 13.
- The reference program's scopes: the transmit waterfall scrolls with the receive waterfall all the time, and both carry time marks (View > Time marks on the scopes, Ctrl+T, on or off), in UTC or the computer's local time (View > Scope time marks in). Nothing sent changes.
- U.S. spelling throughout the specification, the program's labels and its documentation; dates written month first.

## 0.32 (draft) - November 23, 2026

- **SIGNAL VERSION 0.32. Stations following 0.31R4 or earlier cannot exchange frames with 0.32 stations.**
- **Gray-coded tones** (Section 5.2): a 5-bit value v is sent as tone v XOR (v >> 1), at every level and in the long beacon, so the commonest error (one tone over) costs one bit. Preamble patterns and pilots are unchanged (they name tones directly). Simulation (`tools/waveform_study.py`, 40 frames a point, nine-in-ten limits): up to 1.4 dB better (L0 noise only -21.1 -> -22.0 dB, L0 moderate fading -15.0 -> -16.3, L2 moderate -9.0 -> -10.0, L4 moderate -1.0 -> -2.0, L4 near-vertical incidence -1.3 -> -2.7), no change in the spectrum.
- **Glides between tones at L3 and L4** (Section 5.2): the frequency moves to the next tone along a raised cosine a quarter of a tone long, continuous in phase. 40 dB width: L4 2844 -> 1839 Hz (now inside 2.8 kHz), L3 1581 -> 919 Hz; power more than 100 Hz outside the tones: L4 -27.5 -> -36.4 dB. Cost in simulation at most about 0.7 dB. Measured and not adopted at L0 to L2: there the glide cost up to 5.7 dB in fading, and those levels are already narrow.
- **Faded ends** (Section 5.2): every frame fades in and out over 10 ms (raised cosine). No measurable cost.
- Measured and not adopted: other tone spacings at L0 (1 and 3 bins), L2 (1 bin) and L3 (2 bins): no worthwhile gain.
- New in the simulator: every ITU-R F.1487 condition, among them mid-latitude disturbed near vertical incidence (7 ms, 1 Hz), the condition of short 80 and 40 m paths.
- The reference program: HF propagation predictions by Recommendation ITU-R P.533 (new Section 6.15), with the ITU's own program (built by `tools/build_prop.py`, shipped in the setup program): best band by hour for any grid locator, a suggestion when a station is picked, the sky-wave condition and level to expect, and a table of NOAA's predicted sunspot numbers that can be updated over the internet or with an update file. Compiled library interface 12 (the transmitter's glide and fades, Gray coding in the transmitter and both soft-bit readers).

## 0.31R4 (draft) - November 23, 2026

- **Nothing sent has changed. The signal version stays 0.30.** Nothing in the specification changes either.
- The reference program: color controls on both scopes, so each operator can suit the waterfall to their eyesight. View > Waterfall colors offers seven color sets (the classic black, blue, yellow and red; two sets made to be read with color blindness; heat; gray; gray reversed; high contrast), and a third slider beside Floor and Range, **Color**, shifts where the colors change (up: weaker signals already reach the bright colors; down: only strong ones do). Both are remembered with the other settings.
- Test tools (no effect on the program): the channel simulator gained every ITU-R F.1487 condition, among them mid-latitude disturbed near vertical incidence (7 ms between the two paths, 1 Hz spread), and `tools/waveform_study.py` compares candidate transmit waveforms (smoothed tone changes, Gray-coded tones, other tone spacings) by spectrum and by decoding on the sky-wave conditions. Nothing from it is adopted yet.

## 0.31R3 (draft) - November 22, 2026

- **Nothing sent has changed. The signal version stays 0.30.** Nothing in the specification changes either.
- The reference program: a contact book in the panel (`live/contacts.py`, `contacts.json`): details kept for each saved station (name, location, grid locator, radio, power, antenna, notes), its last reading, and a history of the traffic with it, 30 to 200 entries (default 120), all traffic or completed contacts only. A new record is filled in from what was heard (callsign, grid locator, band, frequency, level, signal).

## 0.31R2 (draft) - November 22, 2026

- **Nothing sent has changed. The signal version stays 0.30**; 0.30, 0.31, 0.31R1 and 0.31R2 stations work together.
- Near misses (a signature whose header cannot be read) are shown to the operator only when at least 7 of the 12 pattern tones stand out in their own slots: likely a real Kestrel frame (Section 5.3, "Receiver side"). Other modes' signals, which caused nearly all the "possible Kestrel signature" lines on the air, show 0 to 2. Weak real patterns, which the old strength test (6 times the background) never reached, are now reported. The same signal is shown once a minute at most. The signal log still keeps strong patterns that fail the test, with the tone count.
- Measured and not adopted: guessing a control frame's header when it does not read (1 more frame in about 120 weak failures).
- The reference program: compiled library interface 11 (every signature whose frame passed without a header is handed back to the caller, which decides). The signal log report counts the likely near misses separately.

## 0.31R1 (draft) - November 22, 2026

- **Nothing sent has changed. The signal version stays 0.30**; 0.30, 0.31 and 0.31R1 stations work together. Every improvement below is in the receiver, so a station gains from it whatever the other station runs.
- Steady signals (carriers and other narrow signals that do not move) are notched out of the whole band, 700-2300 Hz, before searching and decoding (Section 5.3, "Receiver side"). They hid weak frames and matched the signature patterns by chance.
- A control frame whose body fails its check is kept for 30 minutes and added to later failed copies of the same frame type from about the same frequency (within 4 Hz).
- The callsigns a station expects (the station it calls, its partner, saved contacts, stations heard in 48 hours; at most 8) are tried in a failed control frame's callsign fields, with its own callsign as an answer's destination. A frame read with help must also agree with 74% of its own soft bits; the receiver says how it was read.
- The LDPC decoder: scale 0.9 (was 0.8), up to 200 passes (was 80): 37% more of 183 weak bodies read, none of 168 easier ones lost.
- The reference program: the signal log setting now takes effect at once during a run; the panel's level meters can no longer be squeezed out of sight; compiled modem library (C++, interface 5) with every new routine checked against the Python reference.

## 0.31 (draft) - November 22, 2026

- **Nothing sent has changed. The signal version stays 0.30**; 0.30 and 0.31 stations work together.
- The reference program's continuous receiver searches incrementally: only the audio that arrived since the last search is searched for signature patterns, patterns below a per-level score gate are not followed up, each candidate is timed, read and decoded once, and a candidate whose first header copy failed is retried only where its second copy may now be. On a 2014 computer the old search needed about 1.5 seconds of computing per second of audio and fell behind; the new one needs a fraction of that (live/README.md). The old search is kept as the reference and both decode the same frames in the tests.
- First step towards a compiled modem core (C++ with a C interface), with the Python modem kept as the reference it must match.

## 0.30 (draft) - November 21, 2026

- **Signal version 0.30.** Store and forward, the first part of roadmap step 3 (Section 8, rewritten). Stations following 0.29 or earlier cannot carry or deliver mail and ignore mail notices.
- New frame: the **mail notice** (frame type 7, Section 5.8), 192 bits: the sender's callsign, then short codes (CRC-16) for up to three stations it holds mail for, three delivery receipts and three stations it hears. 11.5 s at L2, 51 s at L0. Sent just before a beacon by a station holding mail or with receipts to list; with L0 beacons at most once in 30 minutes.
- Every beacon and directed call now sets the mail-check flag.
- Mail travels inside contacts as fully addressed frames (destination, origin, message number, hops, time left). Messages for a named station get their number when queued and keep it, across restarts.
- A station offers each waiting message for a third station to the partner to carry (at most 3 carriers per message); carriers pass it on only to a station whose notice says it hears the destination (at most 2), deliver it when the destination beacons or calls, and never push it. Lifetime 62 hours; hop limit 4.
- New acknowledgment code: status 3 with part number 5, "does not carry mail".
- The destination remembers every message ID for 62 hours and answers later copies with "already have it", including copies of messages it got directly from the origin.
- Receipts are listed in mail notices for 12 hours; holders hearing one drop their copies, and the origin marks its message delivered.
- The reference program: a "Carry mail for others" setting (on by default), Stations > Mail held and carried (addresses, IDs and carriers only; the content of other stations' mail is not shown or logged), and mail kept in a file per callsign between runs.

## 0.29 (draft) - November 21, 2026

- **No frame is changed. The signal version stays 0.27.** But stations must be on the same frequency to meet: 0.29 stations call on new frequencies.
- Calling frequencies moved to an area of Kestrel's own on each band (Section 6.9), away from the calling frequencies of FT8, FT4, JS8, WSPR and VarAC and, on 40 m and 20 m, out of the 97.221(b) segments used by Winlink and VARA: 80 m 3582.5, 40 m 7110.0, 30 m 10147.0, 20 m 14112.5 kHz (were 3590.0, 7101.5, 10144.0, 14108.5).
- Numbered channels replace the working frequencies (Section 6.10): Channels 1 to 4, 2.5 kHz apart, above the calling frequency on 80, 40 and 20 m (3585.0 to 3592.5; 7112.5 to 7120.0; 14115.0 to 14122.5 kHz); one channel on 30 m (10144.5 kHz).
- The new areas are for attended stations. Unattended mail holders, when built, will get frequencies of their own inside the 97.221(b) segments.
- Upper sideband on every band: the radio's data mode (USB-D) where it has one, plain USB where not. Lower sideband is not used (Section 6.9).

## 0.28 (draft) - November 21, 2026

- **Nothing sent has changed. The signal version stays 0.27**; stations following 0.27 and 0.28 work together. 0.28 is about pulling signals out of noise at the receiver, and about not transmitting over others.
- Adding repeated long beacons together (Section 5.9): a long beacon that does not decode alone is kept and added to later copies from the same station. In simulation two copies decode at -28 dB on a steady path and four at -29 dB (one alone: -26 dB); in the worst fading, nine in ten decode at -24 dB with two copies and -26 dB with four (one alone: -20 dB).
- Steady carriers on top of a long beacon are found and notched out; the pattern search and the soft bits count each frequency against its own typical level (Section 5.9).
- A long beacon is accepted only with a callsign of plausible shape (Section 5.9).
- Following the noise (Section 5.7): each body tone of every frame is judged against the noise around it in time, not one level for the whole frame.
- Listening before transmitting (new Section 6.14): beacons, long beacons, directed calls and broadcasts wait while another signal is heard where they would go; replies are never held.
- New study tool: tools/combine_study.py (results/combine_study.csv).

## 0.27 (draft) - November 21, 2026

- **Signal version 0.27.** New frame: the long beacon (Sections 5.9 and 6.13), the first part of roadmap step 2. Stations following 0.26 do not hear it; all other frames are unchanged from 0.26.
- The long beacon: its own twelve-tone pattern and no header; 1.1667 s tones 2.571 Hz apart (about 82 Hz wide); callsign, grid, available and holds-mail flags with a CRC-16, coded with the K=7 convolutional code; 59.5 seconds. In simulation every long beacon decodes down to -25.6 dB on a steady path (L0 beacon: -21 dB) and nine in ten down to -18.6 dB in the worst fading (L0: -14 dB).
- No station answers a long beacon; it is shown to the operator. Long beacons are the operator's choice instead of short (call-up) beacons, at least 10 minutes apart.
- Header frame type 6 is now used by receivers to report a long beacon (never sent).
- New study tool: tools/bottom_study.py (results/bottom_study_*.csv): today's beacon with longer tones and wider spacing, and the long beacon, in noise and fading.

## 0.26 (draft) - November 21, 2026

- **Signal version 0.26. Stations following 0.25 or earlier cannot exchange frames with 0.26 stations** (only the test stations are affected).
- Header placement (Section 5.1, 5.4): the second copy of the 12-tone header is now sent after the body instead of straight after the first copy. One fade can no longer remove both copies. Airtimes are unchanged. The receiver tries the first copy, then the second at the end of each possible body length, combined with the first and alone, and accepts only a header whose body length matches.
- Preamble ranking (Section 5.1, a receiver choice): candidates are ranked by pattern energy times the square of the pattern's share of the energy in its twelve tone lengths, so chance matches inside a strong frame's body no longer outrank a faded real preamble. In simulation, L2 frames in light fading at +5 dB now all decode (before: about 3 in 4), with no loss in steady noise (L2 at -14 dB and L0 at -20 dB still 20 of 20).
- Fading limits re-measured (Section 5.2), 40 frames a point: L0 -8, L1 -2, L2 -8, L3 -1, L4 0 dB (were -12, -10, -9, -4, -1, measured with fewer frames a point). Frames are now lost mainly in light, slow fading, where a fade can cover a whole preamble; retries recover them.
- 80 m meeting frequency 3590.0 kHz added (Section 6.9), with working frequencies 3594.0 and 3597.0 kHz; notes on choosing 80 m or 40 m by time of day; the reference program now refuses to transmit outside the U.S. amateur data segments.
- Roadmap (new Section 10): prove the link; a WSPR-like bottom level; nets and mail; a VARA-like top level. Document history is now Section 11.
- Reference program (not part of the signal): optional recording of received audio to WAV files; File > Decode a recording; reports of Kestrel signatures heard but too weak or faded to read; callsign confirmation; a warning when the radio's ALC reads high during a transmission; an optional signal log for analysis (every preamble candidate, frame, near miss, transmission and meter reading, on one sample timeline with the recordings) and tools/signal_report.py to summarize it.

## 0.25 (draft) - November 19, 2026

- **Signal version 0.25** (only the two test stations are affected).
- Available or not (Section 6.11): while the operator is not available, the station's beacons are presence beacons (listening flag 0, no reply window, nobody answers), and a directed call gets one short reply, a status-3 acknowledgment with part number 4 ("not available"), at the call's level. The caller stops calling at once.

## 0.24 (draft) - November 19, 2026

- **Signal version 0.24** (only the two test stations are affected).
- Just listen (Section 6.11): a listening station may be set to transmit nothing by itself. It then takes, by itself, only directed calls that answer something its operator started: from anyone within 5 minutes of its own last beacon, and from a station it called within 5 minutes. Other calls are shown to the operator, who responds with a call back.
- Call back (6.11): a station making a directed call that receives a directed call from the station it is calling takes it as the answer and completes the lock as a called station.

## 0.23 (draft) - November 19, 2026

- **The call-up has changed. Signal version 0.23; stations following 0.22 or earlier cannot work reliably with 0.23 stations.** (Only the two test stations had the earlier versions.)
- Middle level first (Section 6.1): a beacon goes at L2 first and, if it brings no answer, at once again at L0. The answer goes at the beacon's level (6.2). Reply slots are an answer at the beacon's level plus 2.4 s: 42.0 s at L0, 11.3 s at L2. At L2 every call-up frame is under 10 seconds and the call-up holds the calling frequency about 24 s instead of about 100.
- Starting level (6.3): each station asks straight away for the level its first measurement supports when the lock is made or confirmed.
- Directed calls (6.11): marked by the answer frame's former spare bit (now the directed-call flag); first call at L2; the report carries the caller's reading of the called station when it has one from the last 10 minutes.
- New study tool: tools/callup_study.py (results/callup_study.csv).

## 0.22 (draft) - November 19, 2026

- **No frame is changed from 0.21.** The signal version stays 0.20.
- Answering by hand (Section 6.2): a listening station may be set not to answer beacons by itself. Its operator is shown each beacon, with any messages waiting for that station, and responds, if at all, with a directed call, which the beaconing station accepts during its reply window or later while listening.

## 0.21 (draft) - November 19, 2026

- **No frame is changed from 0.20.** The signal version stays 0.20; stations following 0.20 and 0.21 work together.
- Repeating a beacon (Section 6.1): a listening station may make one beacon round at a time, at least 5 minutes apart, paused during a contact. Repeating starts only at the operator's request and stops by itself after a period with no operator activity (2 hours by default).
- Telemetry message (new Section 6.12): an ordinary message in a fixed layout, tag TLM1, giving the sender's grid, power and the stations it has heard in the last 30 minutes with their SNR and fastest level, so operators can compare stations, for example when choosing net control.
- Called while beaconing (Section 6.11): a station in its own beacon's reply window that receives a directed call confirms the call at once instead of treating it as one of the answers. (The reference program now also sends a directed call's report with no measurement, as Section 6.11 already required.)
- The document's version and the signal's version are now shown separately: the header gives both.

## 0.20 (draft) - November 18, 2026

- **The transmitted signal has changed. Version 0.20 and later cannot exchange frames with earlier versions.**
- The two-second chirp pair that began every frame is replaced by a preamble of twelve tones at the frame's own speed level, in a fixed pattern for each level (Section 5.1). The preamble is long at the slow levels and short at the fast ones (4.8 s at L0, 0.27 s at L4), is no wider than the rest of the frame, and tells the receiver the level.
- Airtimes change accordingly: about 3 seconds longer at L0, and shorter at every other level (an acknowledgment at L4 is 1.5 s, was 3.2 s). The reply slot is 42 seconds (was 39).
- Level limits re-measured in simulation with the new preamble (Section 5.2).
- Header, body, error correction, pilots, control frames and link rules are otherwise unchanged.

## 0.19 (draft) - November 18, 2026

- No frame is changed from 0.18.
- An idle working frequency is now given up after 3 minutes without a message frame (was 5). The operator's warning still comes one minute before.

## 0.18 (draft) - November 18, 2026

- No frame is changed from 0.17.
- An idle working frequency is given up: after 5 minutes with no message frame, the station that proposed the move closes the contact and both return to the meeting frequency. Its operator is warned one minute before (Section 6.10).

## 0.17 (draft) - November 18, 2026

- No frame format is changed from 0.16. Two existing frames gain a use each (Section 6.11).
- Directed call: an answer frame sent without a beacon calls one station by name; the called station completes the lock and takes the beaconing station's part.
- Messages may be marked for one callsign and are then sent only in a contact with that station.
- Broadcast: fully addressed message frames with destination ALL, sent without a lock and without acknowledgment; any station that decodes them shows the message once.

## 0.16 (draft) - November 18, 2026

- No frame format is changed from 0.15. One value is newly defined: in an acknowledgment with status 3, part number 3 means "move to a working frequency", with the offset in the message-number field (signed, 100 Hz steps).
- Working frequencies (Section 6.10): once locked, a pair may agree to leave the meeting frequency, meet again by a probe on the working frequency, and return when the contact ends. Suggested working frequencies added for 40, 30 and 20 meters.
- Keeping the lock open, closing it on request, and taking the turn in an idle lock are now described (Section 6.3). A station without the turn in an idle lock still identifies every 9 minutes.
- The description is now marked as in first on-air tests.

## 0.15 (draft) - November 18, 2026

- The transmitted signal is unchanged from 0.14.
- Suggested meeting frequencies added for 40, 30 and 20 meters (dial 7101.5, 10144.0 and 14108.5 kHz, upper sideband). Each keeps the whole signal inside a 97.221(b) segment.

## 0.14 (draft) - November 18, 2026

- Reply window defined. Slots are 39 seconds. A plain beacon is followed by one reply slot; a beacon with the new wide-window flag (the beacon's former spare bit) is followed by four, and answering stations pick one at random.
- The beaconing station widens the window after an unanswered beacon, and with a wide window locks with the strongest answer it decoded.
- No other frame is changed from 0.13.

## 0.13 (draft) - November 18, 2026

Changes that came out of simulating two stations through a whole contact.

- Link frames now carry the speed level their sender wants from its partner (3 bits). The link number shrinks from 12 bits to 9 to make room, so frame lengths are unchanged. Without this, a station that only sent messages could not tell its partner to slow its acknowledgments.
- Acknowledgment and identification frames are 3 bits shorter (the 9-bit link number): 48 and 61 field bits.
- The answer to a beacon is sent at L0. Sent at the level the beacon was heard at, it was lost whenever the return path was the weaker one.
- Status 2 in an acknowledgment now means the whole message is already held. With status 3, the part number says whether the frame is a plain reply, a turn offer or a probe.
- Link rules written out with starting values: turns, asking for slower and faster levels, what to do with no reply, reacquiring, splitting a message again when the level falls, keep-alive and identification timing.

## 0.12 (draft) - November 18, 2026

- Four control frames defined (frame types 2 to 5): beacon, answer, acknowledgment and identification. They use the same chirp pair, header, pilots and interleaver as message frames, with a short body protected by the header's convolutional code.
- Channel report defined as an 18-bit field: SNR, fading index, frequency offset and the speed level the receiver wants next.
- Link rules stated: each direction has its own speed level; a station sends at the level its partner last asked for, or slower. The lock is confirmed by an acknowledgment frame with status 3, which is also the keep-alive.
- Station identification inside a lock is now a defined frame, sent at least every 10 minutes and at the end of the contact.
- Message frames are unchanged from 0.10.

## 0.11 (draft) - November 18, 2026

- The transmitted signal is unchanged from 0.10.
- Regulatory summary: unattended mail holders operate under 97.221(b) and, on HF, stay within the band segments that paragraph lists. Paragraph (c) does not fit, because every frame is wider than 500 Hz.

## 0.10 (draft) - November 18, 2026

- Every message frame now starts its body with an address block, and there are two kinds of message frame. A link frame (frame type 0) carries a 12-bit link number and a 16-bit message number. A fully addressed frame (frame type 1) carries destination and origin callsigns (48 bits each), the message number, a hop count and the remaining lifetime.
- Callsign coding defined: up to 9 characters (letters, digits, "/", "-") in 48 bits. An address with no digit is a group name; "ALL" is everyone.
- The message ID is the origin callsign plus the message number.
- The body grows by 28 bits to 402, 752, 1102 or 1452 bits, so frames are slightly longer (200 characters: 60 s at L2, 89 s at L1). New LDPC tables in `tables/`; new interleaver steps.
- A fully addressed frame is the same length as a link frame of its size class and holds 13 fewer plain characters (36, 86, 136 or 186).
- Station identification inside a lock noted as an item to define (97.119).
- Level limits re-measured with the new frame sizes: L2 steady -14 dB (was -15); fading L1 -10 dB (was -8) and L4 -1 dB (was -3).

## 0.9 (draft) - November 18, 2026

- The transmitted signal is unchanged from 0.8.
- Channel measurement defined: every received frame yields an SNR, a fading index (0 for a steady signal, about 1 for deep, frequent fades) and a frequency offset, reported back in every acknowledgment.
- The level table gains a second limit for fading signals, measured in simulation over light, moderate and heavy fading. A frame with a fading index above 0.15 counts as fading.
- The rule for choosing a level is stated: the fastest level whose limit is at least 2 dB below the measured SNR.

## 0.8 (draft) - November 18, 2026

- Speed levels L0 to L4 are now defined exactly: tone length, tone frequencies, airtime of each frame size, and the weakest signal each level decoded in simulation.
- Body error correction is now defined: a rate-1/2 repeat-accumulate LDPC code, with its check tables in `tables/`. It replaces the convolutional code used in earlier prototypes for the body; the header keeps the convolutional code.
- Text compression added: a fixed Huffman code (`tables/compression_codes.txt`), used only when it lets the text fit a smaller frame. The header has a new "compressed" flag.
- A fourth frame size added (150 characters), so frames are 50, 100, 150 or 200 characters.
- Header fields, header coding, check values (CRC-8 and CRC-16), interleaver and pilot pattern are now written out in full.
- The receiver accepts a speed level only when both the header and the body check out at that level.

## 0.7 (draft) - November 18, 2026

- The header is now sent at the frame's own speed level, not at the most robust level. The receiver finds the level by trying the header at each one and accepting the level whose check value matches and whose level field agrees. Chosen after simulator tests: every test frame was received at the right level, and fast frames avoid about 10 seconds of header.
- The header also carries the part number and number of parts of a split message.

## 0.6 (draft) - November 18, 2026

- Signature chirp fixed as a pair: 500 to 2500 Hz up in 1 second, then 2500 to 500 Hz down in 1 second, each with 20 ms fades. Chosen after simulator tests showed the pair separates timing error from frequency error.

## 0.5 (draft) - November 18, 2026

- Airtime limits: 60 seconds per transmission by default, extended automatically to 90 seconds in poor conditions; both are operator settings.
- Messages that do not fit within the limit are split into parts, each sent and acknowledged as its own frame.

## 0.4 (draft) - November 18, 2026

- Beacons carry a mail-check flag. Holders deliver or pass on mail only in reply to a beacon with that flag; they never push mail unprompted.
- Every stored copy records the originating callsign and the station it came from (accountability trail).
- New open items: beacon size limits, holder storage limits, and confirming the automatic-control approach with ARRL.

## 0.3 (draft) - November 18, 2026

- Holding partners: one or more stations may store the same message and confirm to the sender that they hold it.
- Delivery is fully automatic when a holder hears the destination.
- First to deliver wins: holders offer the message ID first; a destination that already has it answers "already delivered".
- Delivery receipts are passed to every holding partner and listed in beacons, so all copies are dropped.

## 0.2 (draft) - November 18, 2026

- Store-and-forward redesigned for disconnected operation: no always-on station is assumed.
- Added sender's outbox, carry-and-forward with held-mail announcements in beacons, receipts that clear other holders' copies, message expiry, and nets as temporary post offices.
- Removed mailbox hubs.
- Beacons now list the callsigns a station holds mail for.

## 0.1 (draft) - November 18, 2026

- First public draft of the technical description.
- Covers purpose, regulatory summary, layer model, character set, frame structure (chirp, header, body), speed levels (estimates), error correction, HARQ, tracking, link states, nets, and store-and-forward.
- Not yet used on the air.
