# link - Kestrel link layer (Python reference)

This folder holds the rules that turn single frames into a contact: how two stations find each other, lock, pass messages, change speed as conditions change, recover when frames are lost, and close. The modem in `modem/` makes and decodes the frames; this folder decides which frame to send next.

Nothing here touches a radio. A `Station` is handed the audio it heard and the time, and returns the audio it wants to send. `simulate.py` connects two stations through the HF channel simulator. A real program would connect one station to a sound card and a radio.

## A contact, step by step

1. **Beacon.** The calling station sends a beacon at the slowest level (L0).
2. **Answer.** A listening station answers, also at L0, because it knows nothing yet about the path in its own direction. The answer says how well the beacon was heard and which speed level the answering station wants.
3. **Lock.** The calling station confirms with a short acknowledgment carrying its own report. Both are now locked.
4. **Messages.** The station holding the turn sends its messages. Every message frame is acknowledged, and every acknowledgment carries a fresh channel report.
5. **Turn.** When the sender has nothing left it offers the turn. The partner either starts sending or says it has nothing either.
6. **Close.** When both are empty, each sends an identification frame with the end-of-contact flag.

## When several stations answer

A plain beacon is followed by one 39-second reply slot. If three stations all answer in it, they land on top of each other and the caller decodes none of them. Its next beacon then asks for a **wide window** of four slots, and each answering station picks a slot at random. The caller listens to all four, locks with the strongest answer it decoded, works that station, and beacons again for the rest. A station that has just been worked stays out of the next window.

## The rules

| Situation | What the station does |
|---|---|
| Choosing a speed | The station that hears a signal decides its speed. It asks for a level in every acknowledgment and in every message frame; the partner sends at that level or slower, never faster. Each direction has its own level. |
| Conditions slipping | The receiver asks for a slower level at once, guided by the weakest of its last three readings. |
| Conditions improving | After two clean frames in a row it asks for a faster level, climbing at most two levels at a time. |
| A frame fails its check | The receiver asks for it again, one level slower, and adds the two copies together. |
| No reply | The sender tries again one level slower. |
| Three tries with no reply | The sender probes at the slowest level ("are you still there?"). A reply restores the lock and both sides start measuring afresh. |
| Four probes with no reply | The lock is given up. Messages not acknowledged stay in the outbox and the operator is told. |
| Nothing heard from the partner for five minutes | A station waiting for its partner gives up the lock. |
| Level falls during a split message | The message is split again for the new level and started over under the same number, so no frame runs past the airtime limit. |
| Both stations sending at once | The station that beaconed keeps the turn; the station that answered gives way. |
| Nine minutes without sending a callsign | The station sends an identification frame before anything else. |

A sender never reports a message as delivered unless its acknowledgment was heard. If the message arrived but the acknowledgment was lost, the sender offers it again and the receiver answers "already have it".

## Starting values (`params.py`)

These are first settings, chosen in simulation and meant to be tuned on the air.

| Setting | Value |
|---|---|
| Clean frames before asking for a faster level | 2 |
| Most levels climbed at once | 2 |
| Readings the weakest is taken from | 3 |
| Tries with no reply before probing | 3 |
| Resends of one frame at the receiver's request before probing | 4 |
| Probes before giving up the lock | 4 |
| Beacons without an answer before giving up | 5 |
| Reply slot length | 39 s |
| Reply slots after a wide-window beacon | 4 |
| Pause between hearing and replying | 1 s |
| Keep-alive after silence | 120 s |
| Silence before a waiting station gives up the lock | 300 s |
| Identification | every 9 minutes at most |

## What the simulation showed (18 November 2026)

Run `python tools/link_demo.py --scenario <name>`; charts are in `results/`.

- **Lopsided path** (+3 dB one way, -11 dB the other): one direction ran at L4 and the other at L2. Nothing was lost.
- **Conditions slipping** (+4 dB down to -15 dB in two minutes, then back): the link stepped down L4, L2, L1, L0 and back up without losing a single frame; all 13 messages arrived.
- **Path gone for a minute and a half:** three frames lost, the stations found each other again by probing, and every message arrived once.
- **Path gone for good:** the sender gave up after four probes and reported what was not delivered.
- **Fading:** 36 contacts across light, moderate and heavy fading at 0 to -9 dB. In every one, all six messages arrived complete, in order and once, and the contact closed properly.
- **Several answering stations:** six groups of two to five stations answering one caller, on steady and fading paths. Every station was worked and every message arrived once. Three stations took 5 to 12 minutes, depending on how the slots fell; five took about 25.

Two faults in the first design were found this way and fixed:

- An answer sent at the speed the beacon was heard at was lost when the return path was worse. Answers now go at L0.
- A station that only sent messages had no way to tell its partner to slow its acknowledgments down. Every message frame now carries the level its sender wants.

## Not covered yet

- Two stations transmitting at the same moment. The simulation takes turns, so a real collision is never produced; the give-way rule is tested by hand.
- Nets, and store-and-forward.

## Files

| File | Contents |
|---|---|
| `station.py` | One station's rules: `Station`, with `poll`, `hear` and `handle` |
| `adapt.py` | How a receiver chooses the level to ask for |
| `simulate.py` | Stations joined by the channel simulator: `run_link` (two stations), `run_group` (one caller, several answering stations), `Path`, `describe` |
| `params.py` | The starting values above |

## Added with spec v0.16

- **Keeping the lock open.** `Station(..., close_when_done=False)` holds the lock after the traffic is done; `station.end()` closes it. A station without the turn in an idle lock takes the turn when it gets a message, after waiting long enough for a goodbye from its partner to arrive.
- **Working frequencies.** Set `station.move_to_hz` (an offset from the calling frequency) and `station.can_move = True`. Once locked, the station proposes the move; a partner that can move agrees and retunes, one that cannot declines. `station.tuning(now)` says where the radio should be at any moment; the simulation uses it to make a frame inaudible when the two stations are on different frequencies.
- Three new tests cover the move, the refusal, and a lock kept open that carries later traffic and closes on request.

## Added with spec v0.17

- **Messages for one callsign.** `station.queue(text, to="Q2BB")` holds the message until Q2BB is the partner. `station.outbox_to` runs alongside `station.outbox`.
- **Directed call.** `station.call_station("Q2BB")` in place of `beacon()`: the station sends an answer frame nobody asked for, addressed to Q2BB. A listening Q2BB locks and takes the beaconing station's part (`station.leads`); everyone else stays silent. Five calls without a reply and the caller gives up.
- **Broadcast.** `station.broadcast(text)` queues fully addressed frames to ALL, sent by `poll()` while the station is idle and never acknowledged. Any station that decodes them collects the parts and adds `(origin, destination, text)` to `station.bulletins`, once.
- Four new tests cover a targeted message that waits, a directed call (and a bystander staying silent), a call nobody answers, and a broadcast heard by two stations.

## Added with spec v0.18

- **An idle working frequency is given up.** The station that proposed the move times the gap since the last message frame (`last_traffic`). At two minutes it logs a warning for its operator; at three it closes the contact (the limit was five minutes in v0.18 and is three from v0.19) (`WORKING_IDLE_S`, `WORKING_WARN_S` in `params.py`), and both stations return to the calling frequency as they do at the end of any contact. One new test.
