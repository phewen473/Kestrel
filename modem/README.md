# modem - Kestrel modem prototype (Python reference)

This is the working Python model of the Kestrel modem: it turns a text message into audio and back. It is the reference the later C++ modem will be checked against. Five speed levels (L0 to L4) exist so far, together with the rules that pick a level, keep each transmission short, and split long messages.

## What a frame looks like

```
chirp pair (2 s) | header (24 tones) | body (data tones, with a known pilot tone before every 15)
```

| Part | What it does |
|---|---|
| Chirp pair | A 1-second rising sweep, then a 1-second falling sweep, 500 to 2500 Hz. Finds the frame and measures timing and frequency offset. |
| Header | Frame type, speed level, size class, part number and part count, with a check value. Sent twice. |
| Body | Character count, the characters (7-bit ASCII), and a 16-bit check value, protected by error correction and shuffled across the frame. |
| Pilots | Known tones the receiver uses to follow frequency drift and to measure SNR. |

The header and body are sent at the frame's own speed level. The receiver is not told the level: it tries the header at each level and accepts the one whose check value matches and whose level field agrees.

## Speed levels

Every level sends the same 32 tones. A faster level sends each tone for a shorter time, which shortens the frame and costs sensitivity in proportion.

| Level | Tone length | Width on the air | 50 chars | 100 chars | 200 chars | Weakest SNR (noise only) |
|---|---|---|---|---|---|---|
| L0 | 0.4 s | about 160 Hz | 77 s | 136 s | 256 s | -20 dB |
| L1 | 0.135 s | about 470 Hz | 27 s | 47 s | 88 s | -16 dB |
| L2 | 0.09 s | about 700 Hz | 19 s | 32 s | 59 s | -14 dB |
| L3 | 0.045 s | about 710 Hz | 10 s | 17 s | 31 s | -11 dB |
| L4 | 0.0225 s | about 1420 Hz | 6 s | 10 s | 16 s | -9 dB |

"Weakest SNR" is the lowest value (in 2.5 kHz) at which all 40 test frames decoded in `tools/level_sweep.py`. L1 and L2 were sized so that a full 200-character message fits the 90-second and 60-second limits.

## Choosing a level, airtime limits and splitting (`plan.py`)

`plan_message(text, snr_db)` applies the rules of specification section 6.8:

1. Use the fastest level the signal supports (the level's weakest SNR plus a 2 dB margin).
2. Keep each transmission within 60 seconds.
3. If conditions are too poor for that, allow up to 90 seconds.
4. If the message still does not fit, split it into parts, each a frame of its own.

For a 200-character message that works out as:

| SNR (noise only) | What is sent |
|---|---|
| -7 dB or better | one L4 frame, 16 s |
| -9 dB or better | one L3 frame, 31 s |
| -12 dB or better | one L2 frame, 59 s |
| -14 dB or better | one L1 frame, 88 s (uses the 90-second allowance) |
| weaker | four L0 frames of 50 characters, 77 s each |

`join_parts` puts a split message back together once every part has arrived.

## Prototype numbers

The chirp pair is agreed and in the specification. The rest are test values; the specification keeps them as TBD until they are agreed.

| Item | Value |
|---|---|
| Sample rate | 12,000 samples per second |
| Chirp | 500-2500 Hz, 1 s up + 1 s down (agreed; in the spec since v0.6) |
| Tones | 32 per level (5 bits each), centred near 1500 Hz |
| Error correction | Convolutional code, rate 1/2, constraint length 7, soft Viterbi decoder (stand-in for the planned LDPC code) |
| Interleaver | Golden-ratio step formula over the whole frame |
| Checks | CRC-8 on the header, CRC-16 on the body |
| Header fields | type (3 bits), level (3), size class (2), part number (3), part count (3), spare (2) |

## Files

| File | Contents |
|---|---|
| `params.py` | The shared prototype numbers |
| `levels.py` | The speed levels and the SNR each one needs |
| `frame.py` | `build_frame` (transmitter) and `receive` (receiver) |
| `plan.py` | Level choice, airtime limits, splitting and reassembly |
| `chirp.py` | Makes and detects the signature chirp pair |
| `mfsk.py` | The 32-tone waveform, soft-bit calculation and pilot drift tracking |
| `fec.py` | Error-correction encoder and Viterbi decoder |
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
| Heavy fading (1 Hz, 2 ms) | -4 dB (97 % from -10 dB) | -18 dB |

Also shown by the tests: a 200-character frame decodes while drifting 2.5 Hz; the blanker rescues a frame from heavy static crashes; two copies that each fail at -23.5 dB decode when combined; and a 200-character message split into four L0 parts is reassembled.

## What we learned

- **The chirp pair works.** One sweep up and one down lets the receiver separate timing from frequency error. It measured a 15 Hz offset to within half a hertz at -15 dB.
- **In deep noise the chirp was the weak link at first.** A noise peak could outrank the real chirp. The receiver now keeps the best three candidates and lets the header check choose.
- **Speed costs what theory says.** Each level's limit moved by almost exactly the ratio of tone lengths, so the level table can be planned on paper.
- **A header at L0 would cost every frame about 10 seconds.** That is why the header is sent at the frame's own level and the receiver discovers the level. This was agreed and has been in the specification since v0.7.
- **Fading costs about 9 dB or more** at the every-frame point, and heavy fading leaves a few percent of frames failing until the signal is much stronger. Slow fades last longer than the interleaver can spread. Combining retries is the tool meant to cover this.
- **The SNR reading runs about 2 dB low in heavy fading**, because fast fading smears each tone's energy. The level choice above uses noise-only limits; the link layer will need fading-aware limits.

## Not built yet

A fifth, faster level (L5, which needs a different waveform), text compression, the planned LDPC code, addresses and message IDs, the link layer (beacon, answer, negotiation, acknowledgments), nets and store-and-forward.
