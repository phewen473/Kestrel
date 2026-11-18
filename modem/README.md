# modem - Kestrel modem prototype (Python reference)

This is the first working slice of the Kestrel modem: it turns a text message into audio and back. It is the reference the later C++ modem will be checked against. Only speed level L0 (the slowest, most robust level) exists so far.

## What a frame looks like

```
chirp pair (2 s) | header (18 tones) | body (data tones, with a known pilot tone before every 15)
```

| Part | What it does |
|---|---|
| Chirp pair | A 1-second rising sweep, then a 1-second falling sweep, 500 to 2500 Hz. Finds the frame and measures timing and frequency offset. |
| Header | Frame type, speed level and size class, with a check value. Sent twice. Tells the receiver how long the frame is and how to decode it. |
| Body | Character count, the characters (7-bit ASCII), and a 16-bit check value, protected by error correction and shuffled across the frame. |
| Pilots | Known tones the receiver uses to follow frequency drift and to measure SNR. |

## Prototype numbers

These are test values, not design decisions. The specification keeps them as TBD until we agree them.

| Item | Value |
|---|---|
| Sample rate | 12,000 samples per second |
| Chirp | 500-2500 Hz, 1 s up + 1 s down |
| L0 waveform | 32 tones (5 bits each), 0.4 s per tone, tones 5 Hz apart, 1420-1575 Hz |
| Occupied bandwidth (L0 tones) | about 160 Hz |
| Error correction | Convolutional code, rate 1/2, constraint length 7, soft Viterbi decoder (stand-in for the planned LDPC code) |
| Interleaver | Golden-ratio step formula over the whole frame |
| Checks | CRC-8 on the header, CRC-16 on the body |
| Airtime | 74 s (50 characters), 134 s (100), 254 s (200) |

## Files

| File | Contents |
|---|---|
| `params.py` | All the prototype numbers in one place |
| `frame.py` | `build_frame` (transmitter) and `receive` (receiver) |
| `chirp.py` | Makes and detects the signature chirp pair |
| `mfsk.py` | The 32-tone waveform, soft-bit calculation and pilot drift tracking |
| `fec.py` | Error-correction encoder and Viterbi decoder |
| `interleave.py` | The bit shuffler |
| `crc.py`, `bits.py`, `text.py` | Check values, bit helpers, and text to bits |
| `blanker.py` | Static-crash blanker |

## Measured results (18 November 2026)

From `tools/snr_sweep.py`: 40 random 40-character messages per point, each with a random frequency offset of up to 20 Hz. SNR is in 2.5 kHz. The full table is in `results/l0_snr_sweep.csv` and the chart in `results/l0_snr_sweep.png`.

| Channel | 100 % decoded at | About half decoded at |
|---|---|---|
| Noise only | -21 dB | between -22 and -23 dB (75 % at -22 dB) |
| Light fading (0.1 Hz, 0.5 ms) | -12 dB | -19 dB |
| Moderate fading (0.5 Hz, 1 ms) | -14 dB | -19 dB |
| Heavy fading (1 Hz, 2 ms) | -10 dB | -18 dB |

Also shown by the tests: a 200-character frame decodes while drifting 2.5 Hz; the blanker rescues a frame from heavy static crashes; and two copies that each fail at -23.5 dB decode when combined.

## What we learned

- **The chirp pair works.** One sweep up and one down lets the receiver separate timing from frequency error. It measured a 15 Hz offset to within half a hertz at -15 dB.
- **In deep noise the chirp was the weak link at first.** A noise peak could outrank the real chirp. The receiver now keeps the best three candidates and lets the header check choose.
- **Fading costs 7 to 11 dB** at the 100 % point. Slow fades last longer than the interleaver can spread within a 74-second frame. Combining retries is the tool meant to cover this.
- **The SNR reading runs low in heavy fading** (it showed about -9 dB when the true figure was -2 dB), because fast fading smears each tone's energy. The measurement needs to be made fading-aware before the link layer relies on it.

## Not built yet

Faster levels (L1 to L5), the planned LDPC code, addresses in the header, the link layer (beacon, answer, negotiation, acknowledgments), nets and store-and-forward.
