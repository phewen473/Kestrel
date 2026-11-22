# tests - automated checks

Run them from the repository root:

```
python -m pytest -q
```

They take about forty seconds. None of them needs a sound card or a radio. All of them should pass before any change is committed.

| File | What it checks |
|---|---|
| `test_parts.py` | Each building block alone: text to bits (control characters included), size classes, the channel report and grid locator coding, callsign coding (round trip, compound callsigns, group names, bad input refused), the smaller text room of fully addressed frames, the compression table (complete, reversible for every character, used only when it saves a frame size), the LDPC code (every codeword satisfies every check; noisy input is corrected), the CRCs against published check values, the header's error correction, the interleaver, and the chirp's timing and frequency measurement |
| `test_link.py` | The link layer, with two simulated stations: the speed-request rule on its own, a whole contact on a lopsided path (each direction at its own speed), a lock surviving a gap in the path, a dead path ending the lock with undelivered messages reported, the answering station giving way when both are sending, and three stations answering one beacon (pile-up, wide window, each worked in turn) |
| `test_live.py` | The continuous receiver a live station listens with (each frame reported once, as it completes; silence on noise and on half a frame), rig control against a stand-in for Hamlib's rigctld, the preselected frequencies staying inside the 97.221(b) segments, and the operator's own frequency list (add, list, remove, bad entries refused) |
| `test_weak.py` | The 0.31R1 weak-signal receiver: carriers notched (a frame under a carrier reads only with the notch; noise and strong frames are untouched), weak copies added together, expected callsigns, no false reads in 3,000 noise bodies, the LDPC settings |
| `test_native.py` | The compiled modem library (`cpp/`) against the Python reference: the blanker, the Viterbi decoder, the header reader, the LDPC decoder and noise tracking bit for bit, the tone-band measurement, the pattern search, fine timing and pilot tracking to rounding, the same answers on 1, 3 and 8 threads, the whole body decoder (every level, messages, beacons and answers, with retries combined) and the long beacon's notch, and a whole receiver run decoding the same frames either way (skipped if the library is not built) |
| `test_end_to_end.py` | Whole messages through the simulated channel: clean, noisy with a frequency offset, weak signal at -20 dB, a 200-character message with drift, moderate fading, heavy static crashes (with and without the blanker), two failed copies combining into a good one, pure noise being rejected, every speed level decoding and announcing itself, the level choice, the 60- and 90-second airtime limits, a split message being reassembled, a compressed message end to end, compression reducing the number of parts, a beacon near its limit followed by an answer carrying the report of it, acknowledgment and identification frames at every level, link frames carrying their link and message numbers, fully addressed frames carrying both callsigns, a long addressed message being split and rejoined (and parts of different messages never being joined), the receiver telling a steady signal from a fading one and reading the SNR correctly in both, and the level choice being more careful when the signal is fading |

The tests use fixed random seeds, so they give the same answer every time.
