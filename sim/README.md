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

These are the sky-wave test conditions of ITU-R Recommendation F.1487 (Annex 3: two independently fading paths of equal strength, Gaussian Doppler spread), so results can be compared with published figures for other modes. `SKYWAVE` lists the four a mid-latitude station such as one in the south-eastern United States meets on its own paths: `good`, `moderate`, `poor` and `nvis`.

| Name | Doppler spread | Delay between paths | F.1487 name |
|---|---|---|---|
| `awgn` | none | none | noise only |
| `good` | 0.1 Hz | 0.5 ms | mid-latitude quiet |
| `moderate` | 0.5 Hz | 1 ms | mid-latitude moderate |
| `poor` | 1 Hz | 2 ms | mid-latitude disturbed |
| `nvis` | 1 Hz | 7 ms | mid-latitude disturbed, near vertical incidence (short hops on 80 and 40 m) |
| `low_quiet` | 0.5 Hz | 0.5 ms | low latitude, quiet |
| `low_moderate` | 1.5 Hz | 2 ms | low latitude, moderate |
| `low_disturbed` | 10 Hz | 6 ms | low latitude, disturbed |
| `high_quiet` | 0.5 Hz | 1 ms | high latitude, quiet |
| `high_moderate` | 10 Hz | 3 ms | high latitude, moderate |
| `high_disturbed` | 30 Hz | 7 ms | high latitude, disturbed |

## Example

```python
import numpy as np
from modem import build_frame, receive
from sim import run_channel

heard = run_channel(build_frame("hello"), -15.0, np.random.default_rng(1), "moderate", offset_hz=12.0)
print(receive(heard))
```

## Real band noise (since 0.43)

Real band noise is not white noise: on the author's 80 m recordings it was about 1 to 1.5 dB harder on Kestrel frames than white noise of the same power. `NoisePool` opens a pool of quiet stretches cut from your own receive recordings by `tools/make_noise_pool.py` (each scaled to power 1 in the 2.5 kHz band), and `run_channel(..., pool=NoisePool())` adds noise from it instead of white noise. The pool is kept in your data folder (`local/noise_pool` when run from the source folder, or the folder named by `KESTREL_NOISE_POOL`); it is never part of the repository.

## Where things stand

Working and covered by the tests in `tests/`. Not yet modeled: slow SNR changes over minutes, interference from other signals, and the radio's own filters.
