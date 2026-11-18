# sim - HF channel simulator

Makes a clean Kestrel signal sound like it crossed a real HF path, so the modem can be tested on the PC without keying a radio. Every random choice comes from a seeded generator, so any test can be repeated exactly.

## What it can add

| Effect | Function | Notes |
|---|---|---|
| Noise | `add_noise` | SNR is quoted in 2.5 kHz, the same way WSJT-X reports it |
| Fading and multipath | `watterson` | Two independently fading paths, the second delayed (the Watterson model) |
| Frequency offset and drift | inside `run_channel` | Offset in Hz, drift in Hz per second |
| Static crashes | `add_crashes` | Short, very loud bursts at a chosen rate |

`run_channel` applies all of them in one call and adds silence before and after the signal.

## Named conditions

These are the mid-latitude test conditions of ITU-R Recommendation F.1487, so results can be compared with published figures for other modes.

| Name | Doppler spread | Delay between paths | F.1487 name |
|---|---|---|---|
| `awgn` | none | none | noise only |
| `good` | 0.1 Hz | 0.5 ms | mid-latitude quiet |
| `moderate` | 0.5 Hz | 1 ms | mid-latitude moderate |
| `poor` | 1 Hz | 2 ms | mid-latitude disturbed |

## Example

```python
import numpy as np
from modem import build_frame, receive
from sim import run_channel

heard = run_channel(build_frame("hello"), -15.0, np.random.default_rng(1), "moderate", offset_hz=12.0)
print(receive(heard))
```

## Where things stand

Working and covered by the tests in `tests/`. Not yet modelled: slow SNR changes over minutes, interference from other signals, and the radio's own filters.
