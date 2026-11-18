# modem - Kestrel modem prototype (Python reference)

This is the working Python model of the Kestrel modem: it turns a text message into audio and back. It is the reference the later C++ modem will be checked against. Five speed levels (L0 to L4) exist so far, together with the rules that pick a level, keep each transmission short, and split long messages.

## What a frame looks like

```
chirp pair (2 s) | header (24 tones) | body (data tones, with a known pilot tone before every 15)
```

| Part | What it does |
|---|---|
| Chirp pair | A 1-second rising sweep, then a 1-second falling sweep, 500 to 2500 Hz. Finds the frame and measures timing and frequency offset. |
| Header | Frame type, speed level, size class, part number, part count and a "compressed" flag, with a check value. Sent twice. |
| Body | Character count, the text (plain 7-bit ASCII, or compressed), and a 16-bit check value, protected by the LDPC error-correcting code and shuffled across the frame. |
| Pilots | Known tones the receiver uses to follow frequency drift and to measure SNR. |

The header and body are sent at the frame's own speed level. The receiver is not told the level: it tries the header at each level. A level whose header check matches and whose level field agrees is a candidate, and it is accepted when the body read at that level passes its check too. (About one frame in a thousand, noise makes a wrong level's header pass; the body check catches it.)

## Speed levels

Every level sends the same 32 tones. A faster level sends each tone for a shorter time, which shortens the frame and costs sensitivity in proportion.

| Level | Tone length | Width on the air | 50 chars | 100 chars | 150 chars | 200 chars | Weakest SNR (noise only) |
|---|---|---|---|---|---|---|---|
| L0 | 0.4 s | about 160 Hz | 76 s | 136 s | 195 s | 255 s | -20 dB |
| L1 | 0.135 s | about 470 Hz | 27 s | 47 s | 67 s | 87 s | -16 dB |
| L2 | 0.09 s | about 700 Hz | 19 s | 32 s | 46 s | 59 s | -15 dB |
| L3 | 0.045 s | about 710 Hz | 10 s | 17 s | 24 s | 30 s | -12 dB |
| L4 | 0.0225 s | about 1420 Hz | 6 s | 10 s | 13 s | 16 s | -9 dB |

"Weakest SNR" is the lowest value (in 2.5 kHz) at which all 40 test frames decoded in `tools/level_sweep.py`. L1 and L2 were sized so that a full 200-character message fits the 90-second and 60-second limits. The exact tone frequencies are in the specification, section 5.2.

## Frame sizes and text compression (`text.py`, `compress.py`)

A frame's body holds 350, 700, 1050 or 1400 text bits: 50, 100, 150 or 200 characters of plain text. The sender uses the smallest size that holds the message.

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
| -10 dB or better | one L3 frame, 30 s | one L3 frame, 24 s |
| -13 dB or better | one L2 frame, 59 s | one L2 frame, 45 s |
| -14 dB or better | one L1 frame, 87 s (uses the 90-second allowance) | one L1 frame, 67 s (uses the allowance) |
| weaker | four L0 frames, 76 s each | three L0 frames, 76 s each |

When the signal is fading, pass `fading=True`. Each level then needs a stronger signal, and the same 200 characters (uncompressed) go as:

| SNR (fading) | What is sent |
|---|---|
| -1 dB or better | one L4 frame, 16 s |
| -2 dB | one L3 frame, 30 s |
| -7 dB or better | one L2 frame, 59 s |
| weaker | four L0 frames, 76 s each (L0 works to about -10 dB in fading) |

`join_parts` puts a split message back together once every part has arrived.

## The numbers

All of these are now written into the specification (sections 4 and 5).

| Item | Value |
|---|---|
| Sample rate | 12,000 samples per second |
| Chirp | 500-2500 Hz, 1 s up + 1 s down |
| Tones | 32 per level (5 bits each), centred near 1500 Hz |
| Body error correction | LDPC code, rate 1/2 (repeat-accumulate kind); decoder: normalised min-sum, up to 80 passes |
| Header error correction | Convolutional code, rate 1/2, constraint length 7, soft Viterbi decoder |
| Interleaver | Golden-ratio step formula over the whole frame |
| Checks | CRC-8 on the header, CRC-16 on the body |
| Header fields | type (3 bits), level (3), size class (2), part number (3), part count (3), compressed (1), spare (1) |

## Files

| File | Contents |
|---|---|
| `params.py` | The shared prototype numbers |
| `levels.py` | The speed levels and the SNR each one needs, for steady and for fading signals |
| `frame.py` | `build_frame` (transmitter) and `receive` (receiver) |
| `plan.py` | Level choice, airtime limits, splitting and reassembly |
| `chirp.py` | Makes and detects the signature chirp pair |
| `mfsk.py` | The 32-tone waveform, soft-bit calculation and pilot drift tracking |
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
| Light fading (0.1 Hz, 0.5 ms) | -12 dB | -19 dB |
| Moderate fading (0.5 Hz, 1 ms) | -12 dB (95 % at -16 dB) | -19 dB |
| Heavy fading (1 Hz, 2 ms) | -8 dB (95 % from -12 dB) | -18 dB |

Also shown by the tests: a 200-character frame decodes while drifting 2.5 Hz; the blanker rescues a frame from heavy static crashes; two copies that each fail at -23.3 dB decode when combined; a split message is reassembled; and a compressed message goes through end to end.

## What we learned

- **The chirp pair works.** One sweep up and one down lets the receiver separate timing from frequency error. It measured a 15 Hz offset to within half a hertz at -15 dB.
- **In deep noise the chirp was the weak link at first.** A noise peak could outrank the real chirp. The receiver now keeps the best three candidates and lets the header check choose.
- **Speed costs what theory says.** Each level's limit moved by almost exactly the ratio of tone lengths, so the level table can be planned on paper.
- **A header at L0 would cost every frame about 10 seconds.** That is why the prototype sends the header at the frame's own level and lets the receiver discover the level. The specification adopted this in v0.7.
- **The LDPC code earned its place.** Against the earlier convolutional code it gained about half a decibel on short frames and over a decibel on long ones, and in heavy fading the every-frame point moved from -4 dB to -8 dB.
- **Fading costs about 8 to 12 dB** at the every-frame point. Slow fades last longer than the interleaver can spread. Combining retries is the tool meant to cover this.
- **Slow fading is the hard case for fast levels.** A fast frame is over in seconds, so a slow fade can swallow most of it and the interleaver has nothing to spread across. That is why the fastest levels need the biggest allowance for fading.

## What the receiver measures (`mfsk.py`: `signal_report`)

Every decoded frame comes back with two channel readings, which the link will send to the other station in its acknowledgment:

| Reading | Meaning |
|---|---|
| `snr_db` | Signal-to-noise ratio in 2.5 kHz. After a frame decodes, the receiver knows every tone that was sent, so it measures all of them, including the bin on each side of each tone where fast fading smears the energy. |
| `fade_index` | How much the signal faded during the frame: about 0 for a steady signal, about 1 for deep, frequent fades. Above 0.15 counts as fading. |

Measured in `tools/fading_sweep.py`: the SNR reading is within about 1 dB of the truth in a level's working range (it reads up to 3 dB low on the fastest level in heavy fading with a strong signal, which errs on the safe side). The fading index stayed at zero for every noise-only frame, and flagged every frame in moderate and heavy fading. In light fading a very short frame can sit inside one slow fade and look steady, so about one in six of those is not flagged; the link layer will need to look at several frames, not one.

## Limits for a fading signal

| Level | Steady signal | Light fading | Moderate fading | Heavy fading | Limit used when fading |
|---|---|---|---|---|---|
| L0 | -20 dB | -16 dB | -14 dB | -12 dB | -12 dB |
| L1 | -16 dB | -8 dB | -12 dB | -14 dB | -8 dB |
| L2 | -15 dB | -9 dB | -11 dB | -11 dB | -9 dB |
| L3 | -12 dB | -4 dB | -6 dB | -8 dB | -4 dB |
| L4 | -9 dB | -3 dB | -3 dB | -5 dB | -3 dB |

The steady column is where every test frame decoded. The fading columns are where nine frames in ten decoded (40 frames per point, 2 dB steps); the last column is the worst of the three. Retry combining is meant to cover the tenth frame.

## Not built yet

A fifth, faster level (L5, which needs a different waveform), addresses and message IDs, the link layer (beacon, answer, negotiation, acknowledgments), nets and store-and-forward.
