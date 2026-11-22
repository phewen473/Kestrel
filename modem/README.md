# modem - Kestrel modem prototype (Python reference)

This is the working Python model of the Kestrel modem: it turns a text message into audio and back. It is the reference the later C++ modem will be checked against. Five speed levels (L0 to L4) exist so far, together with the rules that pick a level, keep each transmission short, and split long messages.

## What a frame looks like

```
preamble (12 tones in the level's own pattern) | header (24 tones) | body (data tones, with a known pilot tone before every 15)
```

| Part | What it does |
|---|---|
| Preamble | Twelve tones of the frame's own speed level in a fixed pattern that belongs to the level. Finds the frame, measures timing and frequency offset, and says which level the frame uses. Long at slow levels (4.8 s at L0), short at fast ones (0.27 s at L4), and no wider than the data. |
| Header | Frame type (message in a link frame, message in a fully addressed frame, beacon, answer, acknowledgment or identification), speed level, size class, part number, part count and a "compressed" flag, with a check value. Sent twice. |
| Body | An address block (who the frame is for and which message it is), the character count, the text (plain 7-bit ASCII, or compressed), and a 16-bit check value, protected by the LDPC error-correcting code and shuffled across the frame. |
| Pilots | Known tones the receiver uses to follow frequency drift and to measure SNR. |

The header and body are sent at the frame's own speed level. The receiver is not told the level: it tries the header at each level. A level whose header check matches and whose level field agrees is a candidate, and it is accepted when the body read at that level passes its check too. (About one frame in a thousand, noise makes a wrong level's header pass; the body check catches it.)

## Speed levels

Every level sends the same 32 tones. A faster level sends each tone for a shorter time, which shortens the frame and costs sensitivity in proportion.

| Level | Tone length | Width on the air | 50 chars | 100 chars | 150 chars | 200 chars | Weakest SNR (noise only) |
|---|---|---|---|---|---|---|---|
| L0 | 0.4 s | about 160 Hz | 80 s | 140 s | 200 s | 260 s | -20 dB |
| L1 | 0.135 s | about 470 Hz | 28 s | 49 s | 69 s | 89 s | -16 dB |
| L2 | 0.09 s | about 700 Hz | 20 s | 33 s | 47 s | 60 s | -14 dB |
| L3 | 0.045 s | about 710 Hz | 11 s | 18 s | 24 s | 31 s | -12 dB |
| L4 | 0.0225 s | about 1420 Hz | 6 s | 10 s | 13 s | 16 s | -9 dB |

"Weakest SNR" is the lowest value (in 2.5 kHz) at which all 40 test frames decoded in `tools/level_sweep.py`. L1 and L2 were sized so that a full 200-character message fits the 90-second and 60-second limits. The exact tone frequencies are in the specification, section 5.2.

## Addresses and message numbers (`address.py`)

Every frame's body starts with an address block. There are two kinds of frame:

| Kind | Used for | Address block |
|---|---|---|
| Link frame | Messages between two stations that hold a lock | 28 bits: a 9-bit link number for the pair, the speed level the sender wants from its partner, and a 16-bit message number |
| Fully addressed frame | Traffic outside a lock, and mail being held, relayed or delivered | 120 bits: destination callsign, origin callsign, message number, relay count, remaining lifetime |

- A callsign is up to 9 characters (letters, digits, `/` and `-`) packed into 48 bits, so `Q1AAAA/MM` or `Q7/Q6FFF` fit.
- An address with no digit is a group name. `ALL` means everyone.
- The origin callsign plus the message number is the message ID. Every part of a split message carries the same one, and `join_parts` refuses to join parts of different messages.
- The link number is worked out from the two callsigns (`link_id`), so nothing extra has to be agreed.
- Both kinds of frame are the same length. The longer address block of a fully addressed frame takes room from the text: it holds 36, 86, 136 or 186 plain characters where a link frame holds 50, 100, 150 or 200. A longer message is compressed if that makes it fit, and split otherwise.

```
build_frame("QSL 73", level=3, link=link_id("Q1AAAA", "Q2BB"), msg_id=17)          # link frame
build_frame("QSL 73", level=0, dest="Q2BB", origin="Q1AAAA", msg_id=17)           # fully addressed frame
```

## Control frames (`control.py`)

Four short frames set up and run a link, and a fifth (since 0.30) announces mail. They look like message frames on the air (preamble, header, body) and can be sent at any speed level.

| Frame | What it says | L0 | L2 | L4 |
|---|---|---|---|---|
| Beacon | "Here I am": callsign, grid locator, speed levels, whether it takes answers, mail-check flag, whether it holds mail, and whether answers should spread over four reply slots | 28 s | 8 s | 3.5 s |
| Answer | "I hear you": both callsigns, a report of how the beacon was received, the answerer's speed levels | 37 s | 10 s | 4 s |
| Acknowledgment | "Got it", "send it again" or "already have the whole message", with a channel report. With no message named it confirms the lock, offers the turn, or asks "are you still there?" | 24 s | 7 s | 3.2 s |
| Mail notice | Since 0.30, just before a beacon: the callsign, then short codes (CRC-16) for up to three stations mail is held for, three delivery receipts and three stations heard. `build_notice`, `call_hash`, `message_hash` | 51 s | 11.5 s | 2.9 s |
| Identification | The station's callsign, sent every 10 minutes in a lock and at the end of a contact | 26 s | 7.5 s | 3.4 s |

Every answer and acknowledgment carries a **channel report** (18 bits): the SNR, the fading index, the frequency offset, and the speed level the receiver wants the sender to use next. That last field is how the speed adapts: the station that hears the signal decides, and the sender follows. Message frames carry the wanted level too, so a station that is only sending can still slow its partner's acknowledgments.

```
build_beacon("Q1AAAA", "EM92", mail_check=True)                                    # level 0 unless told otherwise
build_answer("Q1AAAA", "Q2BB", ChannelReport(-12.0, 0.0, 6.0, want_level=2), level=1)
build_ack(link, msg_id=17, part=0, status=ACK_OK, report=report, level=3)
build_ident("Q1AAAA", link, final=True, level=3)
```

`receive` returns the same report as for a message, with the frame's fields in `result.fields`.

Control frames decode at about the same SNR as message frames (36 to 40 of 40 at each level's steady limit). In slow fading a short frame can vanish into one fade: at the fading limits 31 to 40 of 40 got through. The link layer must be ready to repeat them.

## Frame sizes and text compression (`text.py`, `compress.py`)

A link frame's body holds 350, 700, 1050 or 1400 text bits: 50, 100, 150 or 200 characters of plain text. The sender uses the smallest size that holds the message.

Text can also be sent compressed, with a fixed table that gives common characters short codes (space 3 bits, "e" and "t" 4 bits) and rare ones long codes (up to 13 bits). The rule is simple: **compress only when it lets the message fit a smaller frame.** A 200-character English sentence that compresses to 978 bits goes in the 150-character frame instead of the 200-character one, saving about a quarter of the airtime. Traffic that is mostly capitals and digits saves about a seventh, which is often not enough to drop a size, so it goes plain.

The table is fixed and published (`docs/spec/tables/compression_codes.txt`), so nothing has to be agreed between stations beforehand.

## Choosing a level, airtime limits and splitting (`plan.py`)

`plan_message(text, snr_db)` applies the rules of specification section 6.8:

1. Use the fastest level the signal supports (the level's weakest SNR plus a 2 dB margin).
2. Keep each transmission within 60 seconds.
3. If conditions are too poor for that, allow up to 90 seconds.
4. If the message still does not fit, split it into parts, each a frame of its own.

For a 200-character message that works out as:

| SNR (noise only) | Text that does not compress | Plain English (fits the 150-character frame) |
|---|---|---|
| -7 dB or better | one L4 frame, 16 s | one L4 frame, 13 s |
| -10 dB or better | one L3 frame, 31 s | one L3 frame, 24 s |
| -12 dB or better | one L2 frame, 60 s | one L2 frame, 47 s |
| -14 dB or better | one L1 frame, 89 s (uses the 90-second allowance) | one L1 frame, 69 s (uses the allowance) |
| weaker | four L0 frames, 80 s each | three L0 frames, 80 s each |

Pass `addressed=True` for fully addressed frames; `build_plan(plan, dest=..., origin=..., msg_id=...)` then puts the same addressing on every part.

When the signal is fading, pass `fading=True`. Each level then needs a stronger signal, and the same 200 characters (uncompressed) go as:

| SNR (fading) | What is sent |
|---|---|
| +1 dB or better | one L4 frame, 16 s |
| -2 dB or better | one L3 frame, 31 s |
| -7 dB or better | one L2 frame, 60 s |
| -8 dB | one L1 frame, 89 s (uses the 90-second allowance) |
| weaker | four L0 frames, 80 s each (L0 works to about -10 dB in fading) |

`join_parts` puts a split message back together once every part has arrived.

## The numbers

All of these are now written into the specification (sections 4 and 5).

| Item | Value |
|---|---|
| Sample rate | 12,000 samples per second |
| Preamble | 12 tones at the frame's level, a fixed pattern per level (`PREAMBLE_PATTERNS` in `params.py`) |
| Tones | 32 per level (5 bits each), centred near 1500 Hz |
| Body error correction | LDPC code, rate 1/2 (repeat-accumulate kind); decoder: normalised min-sum, up to 80 passes |
| Header error correction | Convolutional code, rate 1/2, constraint length 7, soft Viterbi decoder |
| Interleaver | Golden-ratio step formula over the whole frame |
| Checks | CRC-8 on the header, CRC-16 on the body |
| Header fields | type (3 bits), level (3), size class (2), part number (3), part count (3), compressed (1), spare (1) |
| Address block | link frame: link number (9 bits), wanted level (3), message number (16); fully addressed frame: destination (48), origin (48), message number (16), relays (3), lifetime (5) |

## Files

| File | Contents |
|---|---|
| `params.py` | The shared prototype numbers |
| `levels.py` | The speed levels and the SNR each one needs, for steady and for fading signals |
| `frame.py` | `build_frame` (transmitter) and `receive` (receiver) |
| `plan.py` | Level choice, airtime limits, splitting and reassembly |
| `preamble.py` | Makes and detects the signature tone pattern that starts every frame |
| `chirp.py` | The chirp pair that started every frame up to spec v0.19; kept only for the comparison in `tools/preamble_study.py` |
| `mfsk.py` | The 32-tone waveform, soft-bit calculation and pilot drift tracking |
| `address.py` | Callsign coding (48 bits each) and the link number |
| `control.py` | The fields of beacon, answer, acknowledgment and identification frames, and the channel report |
| `ldpc.py` | The LDPC code that protects the body: builds the check tables, encodes, decodes |
| `compress.py` | Text compression: the fixed code table, compress and decompress |
| `fec.py` | The header's convolutional encoder and Viterbi decoder |
| `interleave.py` | The bit shuffler |
| `crc.py`, `bits.py`, `text.py` | Check values, bit helpers, and text to bits |
| `blanker.py` | Static-crash blanker |

## Measured results for L0 under fading (18 November 2026)

From `tools/snr_sweep.py`: 40 random 40-character messages per point, each with a random frequency offset of up to 20 Hz. SNR is in 2.5 kHz. Tables and charts are in `results/`.

| Channel | Every frame decoded at | About half decoded at |
|---|---|---|
| Noise only | -21 dB | between -22 and -23 dB |
| Light fading (0.1 Hz, 0.5 ms) | -6 dB (92 % or better from -14 dB) | -19 dB |
| Moderate fading (0.5 Hz, 1 ms) | -10 dB (92 % or better from -16 dB) | -19 dB |
| Heavy fading (1 Hz, 2 ms) | -6 dB (90 % or better from -12 dB) | -18 dB |

With 40 frames per point, one stray failure moves the "every frame" figure by several decibels, so the nine-in-ten figures further down are the steadier guide.

Also shown by the tests: a 200-character frame decodes while drifting 2.5 Hz; the blanker rescues a frame from heavy static crashes; two copies that each fail at -23.3 dB decode when combined; link frames and fully addressed frames deliver their addressing; a split message is reassembled; and a compressed message goes through end to end.

## What we learned

- **The tone-pattern preamble replaced the chirp pair (spec v0.20).** The chirp was two seconds long and 2 kHz wide at every level, which made fast frames mostly preamble and slow frames far wider than their data. A study (`tools/preamble_study.py`) showed twelve tones of the level's own set are found 98 to 100 percent of the time at each level's weakest working signal.
- **The receiver keeps the best three candidates for each level's pattern** and lets the header and body checks pick the real frame, because in deep noise a noise peak can outrank the real preamble.
- **Speed costs what theory says.** Each level's limit moved by almost exactly the ratio of tone lengths, so the level table can be planned on paper.
- **A header at L0 would cost every frame about 10 seconds.** That is why the prototype sends the header at the frame's own level and lets the receiver discover the level. The specification adopted this in v0.7.
- **The LDPC code earned its place.** Against the earlier convolutional code it gained about half a decibel on short frames and over a decibel on long ones.
- **Fading costs about 4 to 8 dB** at the nine-in-ten point on the slowest level, and more on the fast levels. Slow fades last longer than the interleaver can spread. Combining retries is the tool meant to cover this.
- **Slow fading is the hard case for fast levels.** A fast frame is over in seconds, so a slow fade can swallow most of it and the interleaver has nothing to spread across. That is why the fastest levels need the biggest allowance for fading.

## What the receiver measures (`mfsk.py`: `signal_report`)

Every decoded frame comes back with two channel readings, which the link will send to the other station in its acknowledgment:

| Reading | Meaning |
|---|---|
| `snr_db` | Signal-to-noise ratio in 2.5 kHz. After a frame decodes, the receiver knows every tone that was sent, so it measures all of them, including the bin on each side of each tone where fast fading smears the energy. |
| `fade_index` | How much the signal faded during the frame: about 0 for a steady signal, about 1 for deep, frequent fades. Above 0.15 counts as fading. |

Measured in `tools/fading_sweep.py`: the SNR reading is within about 1 dB of the truth in a level's working range (it reads up to 3 dB low on the fastest level in heavy fading with a strong signal, which errs on the safe side). The fading index stayed at zero for every noise-only frame, and flagged every frame in moderate and heavy fading. In light fading a very short frame can sit inside one slow fade and look steady, so on the two fastest levels roughly one frame in eight is not flagged; the link layer will need to look at several frames, not one.

## Limits for a fading signal

| Level | Steady signal | Light fading | Moderate fading | Heavy fading | Limit used when fading |
|---|---|---|---|---|---|
| L0 | -20 dB | -16 dB | -16 dB | -12 dB | -12 dB |
| L1 | -16 dB | -10 dB | -12 dB | -14 dB | -10 dB |
| L2 | -14 dB | -9 dB | -11 dB | -11 dB | -9 dB |
| L3 | -12 dB | -4 dB | -8 dB | -8 dB | -4 dB |
| L4 | -9 dB | -1 dB | -3 dB | -5 dB | -1 dB |

The steady column is where every test frame decoded. The fading columns are where nine frames in ten decoded (40 frames per point, 2 dB steps); the last column is the worst of the three. Retry combining is meant to cover the tenth frame.

## Not built yet

A fifth, faster level (L5, which needs a different waveform). The link rules that use these frames are in `link/`. Nets and store-and-forward are not built yet.
