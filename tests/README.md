# tests - automated checks

Run them from the repository root:

```
python -m pytest -q
```

They take a few seconds. All of them should pass before any change is committed.

| File | What it checks |
|---|---|
| `test_parts.py` | Each building block alone: text to bits (control characters included), size classes, the CRCs against published check values, error correction, the interleaver, and the chirp's timing and frequency measurement |
| `test_end_to_end.py` | Whole messages through the simulated channel: clean, noisy with a frequency offset, weak signal at -20 dB, a 200-character message with drift, moderate fading, heavy static crashes (with and without the blanker), two failed copies combining into a good one, and pure noise being rejected |

The tests use fixed random seeds, so they give the same answer every time.
