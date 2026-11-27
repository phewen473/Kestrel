# Kestrel specification changelog

## 0.44 (draft) - November 26, 2026

Every item left open after 0.43 that did not need more on-air data, in one release.

- **The channel report says how old it is and how noisy the reporting station is (Section 5.8): the signal changes.** Two fields are added to the 18-bit report, making 26 bits: the age of the measurement (3 bits: under 1 minute, 1, 2, 4, 8, 16 or 32 minutes or more, or not said) and the reporting station's own band noise, its S-meter reading in 3 dB steps from -60 to +30 dB relative to S9 (5 bits; 31 = not measured). The answer frame grows from 139 to 147 bits (48.4 s at L0, 10.9 s at L2) and the acknowledgment frame from 48 to 56 bits (33.2 s at L0, 7.5 s at L2). On the air on November 25 and 26 a partner's acknowledgments repeated the same report (-17 dB, -18 dB) for minutes because it had heard nothing newer, and one station was heard at -17 to -30 dB while hearing the other at about -2 dB with less power: the age and the noise reading make both visible. **Stations on 0.43 or earlier cannot read 0.44 answers and acknowledgment frames; both stations of a contact must run 0.44.** Beacons, message frames, bursts and the long frames are unchanged.
- **An old report never raises the sending level (Section 5.8).** A report whose age code is 3 or more (4 minutes or older) may lower the level a station sends at but never raise it.
- **The reference program reads the band noise** from the radio's S-meter through rig control every 5 seconds while receiving (not within 3 seconds of its own transmissions) and puts the median of the last 5 minutes in every report it sends. The contact bar's "They hear you" shows how old the partner's report is and the partner's noise in S-units ("-17 dB, fading · asks L0 · 3 min old · their noise S7").
- **The time of a report is taken from its age:** the hand-over to long notes when the partner hears this station at -22 dB or less (Section 6.16) now judges the report by when the partner measured it, not when it arrived.
- **A long beacon read only by adding copies together is refused when it is most likely noise** (receiver practice): when the newest copy showed no pattern, the sender is not a station expected, and it is more than 8 Hz from every station read on its own in the last 2 hours. On the air a false long beacon from a callsign nobody had heard came from four copies of noise added together, 22 Hz from where every real signal arrived; real stations' frames all arrived within about 2 Hz of each other. A refused one is named in the Activity log. Nothing sent changes.
- **A near miss strong enough to be another signal version says so** (reference program): when every one of a signature's 12 pattern tones stood out but its header could not be read, the line no longer says "too weak or faded" but that it may be a station on a different signal version. Older programs called strong frames from older signal versions "too weak".
- **A warning when the receive input stays very low** (reference program): below -60 dBFS for a minute while receiving, the Activity log and the status bar say so and what to check, and again when it recovers. On November 25 the input sat about 42 dB below normal for 42 minutes with no warning.
- **The logbook says why a run stopped** (reference program): "stopped by the operator", "ended", "stopped by a problem: ..." or, when it failed before it started, "could not start: ...". On November 25 nine "listen stopped" entries had no start and no reason.
- **The level each station last needed is kept from one start of Kestrel to the next** (reference program; two days on disk, used for two hours as in 0.43), so the first call after a restart to a weak station starts at a level it can read.
- **New program icon** ("Mast": a hovering kestrel over a lattice tower with signal arcs) for Kestrel.exe, the setup program, and the panel's title bar and taskbar button.
- **Compiled library interface 20:** KesFields carries the report's age and noise reading; the compiled station stamps its reports with their age, takes the operator's noise reading ("noise_db"), and applies the old-report rule, giving the same transmissions as the Python reference.

## 0.43 (draft) - November 26, 2026

0.43 was rebuilt the same day, before any station installed it, as one release with every fix then pending: the five signal-engine studies of November 26 (decoder-derived link quality, fading-aware reading of the body, short acknowledgment bursts, incremental redundancy, a middle pattern) were run in the simulator's white noise and in real band noise cut from the author's own recordings, and what they showed is built in. The first ten items below are that rebuild; the rest is 0.43 as first released.

- **Acknowledgment bursts (Section 5.11): the signal changes again within 0.43.** A message frame's acknowledgment, and the lock confirmation after a directed call or a single-slot beacon, can be 24 L0 tones (9.6 s) in an order fixed by everything the acknowledgment says (link, message, part, status, level asked for), which the waiting station recognizes by rank instead of decoding. In real band noise: recognized 95 times in 100 at -20 dB in slow fading and 94 at -22 dB in moderate fading, where the 31-second L0 acknowledgment frame was read 46 and 9 times; one wrong verdict in 1,200 (first study: 4 verdicts, start known within 1.5 s). As built, searching 0.5 to 7 s after the frame for 15 things the burst could say (tools/burst_study.py sweep, real noise, 100 a point): slow fading 70, 90 and 91 in 100 at -22, -20 and -18 dB; moderate 82, 95 and 96; fast (2 Hz) 90, 95 and 100; one wrong verdict and two wrong levels in 2,100. The search threshold (8.6 points) gives about one false recognition in 1,000 searches of real band noise (10,000 searches: 99.9 % below 8.1) and of the author's recordings, strong Kestrel frames included (3,630 searches: 99.9 % below 8.4). The best candidate must also beat any candidate saying something different by 2 points. A full acknowledgment frame, with the channel report, still goes when the last one sent is 5 minutes old (Section 6.5). The full receiver's acknowledgment frame is still read as before, so a lost burst costs only the usual wait.
- **The level choice measured the way a station uses it (Section 5.2).** New tables from tools/next_frame_study.py (an L0 frame's reading, then a frame of each faster level 40 s later, 12,800 trials in each noise): in fading L1 from -14 dB and L2 from -12 dB of reading (were -8 and -8), steady L1 from -18 and L2 from -16 (were -14 and -12), fast fading L1 -15, L2 -13 (were -12, -10); L3 and L4 3 to 6 dB lower likewise. The decode limits of Section 5.2 are unchanged. Signal and frames unchanged; the station asks for faster levels sooner.
- **Second tries on a failed body (Section 5.6):** wide tones (each tone plus half of each neighboring bin) and then, for a message, an order-1 ordered-statistics search. At 2 Hz Doppler spread and -18 dB the wide reading took L0 from 16 frames in 100 to 85. Receiver practice; nothing sent changes.
- **Studied and not adopted (Sections 5.6, 5.1):** a decoder-derived link-quality measure (mutual information or pre-correction bit errors of the soft bits) predicted the next frame no better than the SNR reading; a fading-aware soft metric (log I0) helped slow fading a little and hurt faster fading by up to 21 frames in 100; incremental redundancy did no better than resending the same frame (100 against 89 and 96 frames in 150 at -20 dB in slow fading); a third pattern in the middle of long L0 frames could have added at most 6.5 % (13 frames in 200), only in slow fading, for 4.8 s on every frame.
- **Short contacts that cannot carry the traffic hand it to long notes (Section 6.16, reference program).** When the partner's latest full report (10 minutes old at most) says it hears this station at -22 dB or less at L0, the messages still waiting for it go as long notes and the short contact is closed.
- **Real band noise in the simulator** (sim.NoisePool, tools/make_noise_pool.py): quiet stretches of the operator's own receive recordings, scaled to power 1 in 2.5 kHz, kept in the operator's data folder and never in the repository. On the author's 80 m band it was 1 to 1.5 dB harder on L0 frames than white noise.
- **Fix: a crash when the computer runs short of memory or threads** (compiled library). A helper thread that could not start left the threads already running to be destroyed unjoined, which ends the program ("terminate called without an active exception"); seen once, when many study processes left running had used up the computer's memory. A piece whose thread will not start now runs on the calling thread, and an error in any piece is passed on only after every thread has finished.
- **Compiled library interface 19:** the station's transmissions may be "burst" frames and say what burst they await ("listen", "listen_hz"); the compiled station has the burst rules and the new level tables, and still gives the same transmissions and log lines as the Python reference, contact for contact.
- **New tools:** tools/next_frame_study.py, tools/burst_study.py, tools/make_noise_pool.py.
- Tests: tests/test_burst.py (8, one of them the live loop taking a burst as the acknowledgment), tests/test_second_tries.py (5), tests/test_noise_pool.py (3), a twelve-thread stress test in tests/test_native.py; level expectations in tests/test_end_to_end.py, tests/test_link.py and tests/test_sky035.py follow the new tables.

- **The signal changes: signal version 0.43.** Stations running 0.42 or earlier cannot read 0.43 frames, nor 0.43 stations theirs; both stations of a contact must run 0.43. The long beacon, long notes and the long call-up are unchanged and still work between 0.41, 0.42 and 0.43 stations.
- **Why.** On the air on November 24 to 26, over a 69-mile path that the other station heard 13 to 23 dB weaker than this one (its reports: -16 to -30 dB), long beacons got through but short frames did not: 92 calls brought 5 locks, and none of the 5 carried a message. Simulation of that kind of path (slow fading, L0) found two faults, and 0.43 mends both. (1) A frame said where it began only once, in the twelve-tone preamble at its start (4.8 s of an 88-second frame); when a fade covered it, a receiver searching a recording for the frame did not find it, however well the rest arrived. (2) In live use the continuous receiver did find most such frames, because it follows even a weak pattern as it arrives, but the station then decoded each frame's audio a second time from scratch, by searching the clip, and that second decode lost them again, together with every weak control frame the continuous receiver had read only with help.
- **The pattern at both ends (Section 5.1).** Every frame is now: pattern, header, body, pattern again, header again. The twelve-tone signature pattern of the frame's level, until now sent once as the preamble, is sent a second time after the body, and the receiver can find a frame from either one. A frame found from its second pattern is read backwards from there: the header beside the pattern gives the body's length, and the body lies just before it.
- **The second header copy is marked (Section 5.4).** Its check value is sent with the bits of A5 hexadecimal flipped, so a receiver that reads one header copy alone knows which end of the frame it has found. The mark flips a fixed set of coded bits (the code is linear), which the receiver undoes before adding the two copies together.
- **Tracking from the end (Section 5.7).** A frame found from its second pattern has its frequency measured at the body's end, so the pilots are followed from the last stretch back to the first.
- **Every frame is twelve tones longer:** 4.8 s at L0, 1.62 s at L1, 1.08 s at L2, 0.54 s at L3, 0.27 s at L4. A 50-character message frame goes from 83.2 to 88.0 s at L0 and from 18.7 to 19.8 s at L2; an L2 call from 9.5 to 10.6 s; an L0 acknowledgment from 26.4 to 31.2 s. Reply slots follow (Section 6.2: 49.6 s after an L0 beacon, 13.0 s after L2).
- **Airtime limits 61 and 91 seconds (Section 6.8), from 60 and 90.** With the second pattern a full 200-character frame runs 60.1 s at L2 and 90.2 s at L1; the limits moved by one second so those frames still go whole instead of being split in two.
- **Measured on the live path** (simulation: frames fed to the continuous receiver a second at a time as from a sound card, two paths 1 ms apart, slow fading of 0.1 Hz, 48 frames a point; the count is what the station ends up with). L0 message frame of 38 characters at -8, -12, -14, -16, -18 and -20 dB: 0.42 delivered 43, 39, 35, 35, 29 and 14 in 48; 0.43 delivers 48, 48, 48, 47, 36 and 23. L0 acknowledgment at the same points: 0.42 delivered 45, 43, 43, 35, 32 and 22; 0.43 delivers 48, 48, 47, 41, 40 and 30. With 240 frames a point at -17 and -18 dB, the strength the other station reported on the air: 0.42 delivered 158 and 138 in 240 (66 and 58 %); 0.43 delivers 225 and 199 (94 and 83 %). Of the gain at -12 to -16 dB, the larger share comes from the station no longer decoding a second time (0.42's continuous receiver alone read 45, 45 and 43 of the message frames in 48, and 214 and 187 in 240 at -17 and -18 dB), the rest from the second pattern. In moderate fading (0.5 Hz) both read 47 or 48 in 48 from -18 dB up once the second decode is gone. These runs gave the receiver no expected callsigns and no earlier copies to add; on the air it has both.
- **Measured with a whole recording searched for the frame** (the one-shot receiver the tools and the link simulations use; 40 frames a point, 95-character L0 frames, two paths 1 ms apart). Slow fading (0.1 Hz): 0.42 read 35, 29, 23 and 24 in 40 at -8, -12, -16 and -18 dB; 0.43 reads 40, 39, 37 and 31. Moderate fading (0.5 Hz): 0.42 read 38, 38, 38 and 33; 0.43 reads 40, 40, 40 and 39. At 2 Hz 0.43 reads 40 in 40 down to -16 dB. Steady signal: 40 in 40 at -20 dB, 36 at -22 dB (unchanged). A receiver told where each 0.43 frame begins reads at most three more frames in 40 than the real one down to -16 dB: finding the frame is no longer what limits L0.
- **Level limits on a fading signal, re-measured** (Section 5.2; tools/fading_sweep.py, the same tool, rule and random seeds as before: nine frames in ten in the worst of light, moderate and heavy fading, 40 frames a point): L0 -16 dB (was -8), L1 -10 (was -2), L2 -10 (was -8), L3 -5 (was -1), L4 -4 (was 0). The steady-signal limits are unchanged (-20, -16, -14, -11, -8 dB). In light fading at L0 the count went from 29, 32, 34, 32, 38, 35 in 40 at -16 to -6 dB to 37, 40, 38, 40, 40, 40. A station picks its level from these tables, so on a fading path it now asks for, and gets, levels it used to avoid.
- **Fast-fading table, re-measured** (Section 6.5; tools/level_spread_study.py, now 40 frames a point): L0 -16, L1 -14, L2 -12, L3 -5, L4 -4 dB (was -14, -8, -10, -1, 0).
- **More pattern candidates followed up when a whole recording is searched** (receiver practice): eight for each level instead of three. With two patterns to a frame, the chance matches inside a strong frame's own body could outrank a faded pattern; this took 0.43 from 35 to 39 in 40 at -12 dB in slow fading. (It does little for 0.42 frames, 29 to 29 at the same point: what they lacked was a second pattern.)
- **Fix: frames the continuous receiver had read were decoded a second time, and lost.** Since the first live version the station decoded each frame's audio again from scratch after the continuous receiver had already read it. That second decode searched a short clip afresh for the pattern, where the strongest chance matches inside the frame's own body can outrank a faded pattern, and it had none of the continuous receiver's help for weak control frames (earlier failed copies added together, the callsigns it expects, Section 5.3 "Receiver side"). A frame it could not read was dropped, though the receiver had read it. The station now takes the continuous receiver's report as read, and a failed message frame is read again, with its retry added, at the place it was found (reference program; nothing sent changes, and this part would help a 0.42 signal as much).
- **A frame that fails its check is handed to the station once**, though the continuous receiver may now find it from both patterns; the second finding is still decoded (its timing is measured afresh and may read where the first did not).
- **Starting a call where the last contact left off (Section 6.11).** A station remembers for two hours the speed level each station last asked it to send at, and any slower level it had to fall back to, and starts its next directed call to that station there when that is slower than L2. On November 25 and 26, 24 of the 92 calls were L2 calls, to a station whose every report asked for L0. The panel carries the record from one Listen run to the next.
- **A near miss says where it was** (reference program): the report of a signature whose header could not be read now carries its place in the stream; tools/decode_wav.py listed every near miss at 0.0 s.
- **Frame strip** (reference program): the four segments are now Pattern, Header, Body, and Pattern + header again; a frame found from its second pattern shows its first pattern in the "weak" color and says so.
- **Compiled library interface 18:** kes_encode_frame writes the new layout; kes_read_header reads the header beside either pattern and answers 4, 5 or 6 for a frame found from its end; kes_pilot_fit takes `backward` and kes_decode_body `from_end`; a kes_listener_next frame event gives the frame's start in ev[8]. The compiled station (cpp/src/station.cpp) has the new airtimes, limits and the remembered call level; it still gives the same transmissions and log lines as the Python reference, contact for contact.
- Tests: tests/test_spread_sync.py (new, 22 tests: each end of a frame lost in turn at every level, control frames, a weak frame found from its end in noise, a drifting frame tracked backwards, the compiled reader and pilot fit against the Python reference, the continuous receiver in Python and compiled, retries added without searching afresh); tests/test_link.py (two more); tests/test_framestrip.py (two more); airtimes in tests/test_end_to_end.py; the level tables in tests/test_sky035.py.

## 0.42R3 (draft) - November 25, 2026

- No frame changes (signal version stays 0.41); 0.41, 0.42 and 0.42R3 stations work together.
- **Fix: an unanswered move split the two stations.** On November 25 a contact locked on the calling frequency; the calling station proposed a move to Channel 1, the partner (which heard it 15 to 20 dB weaker) never decoded the proposal, and after two tries the caller went to the working frequency anyway "in case the partner agreed without being heard". The partner stayed on the calling frequency offering the turn, each probed where the other was not, the lock was lost and no message went. Now a proposal that gets no reply twice is dropped for the rest of the contact and the traffic carries on where the stations are (Section 6.10). A chained message, which needs a working channel, keeps waiting, and the panel asks for the move only once per contact.
- **Logbook power reading** (reference program): the "meters" line after each transmission recorded the last reading, usually taken after the audio had ended but before the radio unkeyed, so it showed 0 W for transmissions sent at full power; it now records the middle of the readings taken while the audio was going out.
- **Outgoing audio gaps** (reference program): the signal log's clock line now also counts gaps in the audio sent to the radio (tx_underflows), so a sound card that starves the transmitter shows up.
- Tests: tests/test_link.py (one more).

## 0.42R2 (draft) - November 25, 2026

- Nothing sent changed (signal version stays 0.41); reference program only.
- **Fix: the panel's layout did not come back as it was left.** It was saved, but the dividers were put back before Windows (or Remote Desktop) had finished sizing the window, which then spread the panels out again. They are now put back again once the window has settled.
- **The Activity window is On or Off** (Settings > Operating). On: it starts minimized and stays in the background, and opens only when asked (the Activity button, View > Activity window, Ctrl+Shift+A); closing it minimizes it again. Off: there is no Activity window, and its button and menu item are greyed. It no longer pops up by itself on a warning or problem; such lines show in the warning color in the status bar at the bottom of the main window.

## 0.42R1 (draft) - November 25, 2026

- Nothing sent changed (signal version stays 0.41); reference program only.
- **Fix: rig control failed after updating to 0.42.** Settings kept the full path of the rig control program (rigctld) from the old installation under Program Files, which the 0.42 setup program removes when it installs for the current user; every Listen then stopped with "could not start the rig control program". A saved path that no longer exists is now passed over for the copy installed with Kestrel (or one found on the computer), and Settings remembers the new one.
- Tests: tests/test_settings_files.py (one more).

## 0.42 (draft) - November 25, 2026

- **Nothing sent changes: the signal version stays 0.41,** and 0.41 and 0.42 stations work together.
- **Chained messages (Section 6.20).** Up to 1,000 characters, sent as up to nine ordinary messages that begin "(k/n) ", only on a working channel (a station on the calling frequency proposes a move first). The receiving 0.42 panel joins them, showing the message as it fills in; a 0.41 station shows the pieces one by one. Before this the 0.41 panel's message box took 1,000 characters but the station refused anything over 200.
- **The other station's report of this station** (Section 6.4): every answer and acknowledgment has always carried the receiver's SNR, fading index and wanted level for the sender's last frame; the reference program now shows it in the contact bar as "They hear you" (it showed only the wanted level).
- **Chat window** (reference program): the conversation with the partner as a running exchange, with a tick on each line once acknowledged; a line is sent only on Enter or Send.
- **Updates (Section 6.21, reference program).** Settings > Updates and Help > Check for updates: a daily check of the public release list, a notice that says plainly when a release changes the signal, and Install now (download, SHA-256 check, close, silent install, restart) only with the operator's approval and only when idle. The setup program installs for the current user (no administrator prompt) and offers to remove an older all-users copy.
- **Panel**: everything fits at 1024x768 (Stations heard headings, the 48 h button, the level meters' help).
- Not in this version: fading-resistant short frames. The fading penalty of the short levels comes from slow fading (fades as long as a frame), which coding within a frame cannot remove; time diversity across transmissions will be designed from on-air fade measurements. The traffic-waiting notice in the call and faster traffic between locked stations need signal changes and are left for a later signal version.
- Tests: tests/test_chain.py, tests/test_updates.py.

## 0.41 (draft) - November 25, 2026

- **Signal version 0.41: the long call-up (Section 6.18).** The long-note frame's kind 3, unused before, carries a directed call, its answer, or a "not available" reply, in a long frame of about a minute, read down to about -22 dB. On November 24 the partner was measured at -11 to -14 dB on a fading path: long beacons decoded all night, short calls almost never (the short levels need about -8 dB when the signal fades). Short calls to a station heard only in long frames now stop after two (L2, then L0) and a long call follows; after five unanswered short calls a long call follows too if the station was heard in long frames within the hour. Once a long contact is made, waiting messages go as long notes. Stations following 0.40 or earlier read a long call-up as noise.
- **Idle timeout, Keep-Alive and the 10-second warning (Section 6.19, reference program).** A contact with no messages for 3 minutes ends (on the calling frequency too); both operators are warned 10 seconds before, with Keep going and Disconnect (replacing the one-minute notice to the station that proposed a move). Keep-Alive, a setting that replaces Keep contact open, adds 3 minutes on a working channel only, once.
- **Sound output (reference program).** One output stream stays open for the whole run instead of a new one for every transmission; opening and closing streams on a USB radio sound card is the likely cause of the received audio lost while transmitting (up to 5.9 s in 90 minutes). The signal log's clock line now separates audio lost while sending from audio lost while receiving.
- **Panel.** A new layout that fits 1024x768: a status band and a contact bar (partner, how each side hears the other, speed, traffic, the idle countdown); one toolbar; a message panel with a multi-line box, a character countdown and one Send button (To can be ALL; As chooses a normal message or a long note); the lists as tabs with counts, each time shown in local time with a UTC column; a shorter transmit scope; the Activity log in a window of its own (View > Activity window, Ctrl+Shift+A; warnings open it), with its newest line at the bottom of the main window; hover help on every control, with the shortcut keys named there; shorter frequency labels.
- Tests: tests/test_longcall.py, tests/test_idle.py, and the output stream in tests/test_panel_parts.py.

## 0.40R3 (draft) - November 25, 2026

- Nothing sent changed (signal version stays 0.40); reference program only. Found in a review of the 0.40R2 fix.
- **Fix: messages queued while Listen was starting were not sent in that run.** Listen takes the queue when it is pressed, but the station accepts new messages only once rig control and the sound devices are open, some seconds later. A message queued in between stayed in the panel's own list, listed as "waiting", for the whole run, through any contact. It is now handed to the station as soon as the station exists.
- One lock now guards every hand-over of the queue between the window and a run, so a message queued at the instant a run starts or ends cannot be missed or overwritten; the tidy-up at the end of a run stops new messages going to the finished station before it takes back what was unsent (0.40R2 did these in the other order).
- If the station cannot say what it still held, the Activity log says so instead of losing the messages silently.
- Tests: tests/test_unsent.py (one more).

## 0.40R2 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.40); reference program only.
- **Fix: queued messages that never went.** Starting Listen hands the queued messages to that run. A run that failed to start (rig control could not open the radio, a sound device missing) or stopped with a problem never gave them back: their rows stayed in Messages to send as "waiting", but no later run held them, so they were not sent when a contact with their station locked. Now every run gives back what it took and did not send, however it ends (tools/kestrel_panel.py unsent_messages). Messages already stranded this way in a running panel come back when the panel is closed and reopened (the saved queue is read again).
- When a contact locks, the Activity log says how many messages are ready to go to that station, and says so if the list shows more waiting than the station holds.
- Tests: tests/test_unsent.py.

## 0.40R1 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.40); reference program only.
- **Sample count kept in step with the clock** (live/recorder.py TimedSource.resync): on the air, the sound card delivered a fraction of a second less audio than time passed during each transmission (no overflow reported), and the count fell 5.9 s behind the clock in 90 minutes, so decode times, recording positions and time marks ran late. After each transmission, when what was received is thrown away and the listener starts afresh, a count more than 0.05 s behind the clock is made good with silence (in the recording too); the signal log notes each time and how much ("input timeline made good after transmitting").
- **Hold output power** (live/power_hold.py; Settings > Station > Hold output power at, watts): on the air a radio's output fell from 22 W to 10 W over five one-minute frames at constant audio drive. With a power named, after each transmission the median power the radio measured is compared with it and the transmit level is changed for the next one by the square root of wanted over measured, at most 2 dB a step, within 10 % left alone, and never upward while ALC is at or above the warning level (then 1 dB down, with advice to raise the radio's power setting). Needs rig control that reads the power meter. Off when blank (the default).
- **Sag warning**: when the power in the last third of a transmission is below 70 % of the first third's, the Activity log says so, whether or not holding is on.
- Stations heard buttons shortened (Respond, Save, Remove, Contacts, 48 hours) so all five fit a narrow panel; the keys (Ctrl+Y, Ctrl+K, F8) are unchanged.
- Tests: tests/test_power_hold.py.

## 0.40 (draft) - November 24, 2026

- **Signal version 0.40: rig type and watts in every beacon** (Section 5.8, modem/control.py, cpp/src/packing.cpp): the beacon adds the station's Hamlib model number (16 bits) and transmit power in whole watts (10 bits, at most 1023), 0 for either when not said: 101 field bits (was 75), 54 body tones (was 42), 36 s at L0 (was 31 s), 12 s at L1, 8.1 s at L2 (was 7.0 s), 4.0 s at L3, 2.0 s at L4; reply slots follow. The reference program sends the rig type chosen in Settings > Radio and the radio's power setting (else the full power in Settings > Station). Library interface 17 (KesFields.rig_model and watts). **Stations following 0.39 or earlier cannot read 0.40 beacons, nor 0.40 stations theirs;** long beacons are unchanged (they have no room).
- **Station details** (Section 6.17, live/contacts.py): a saved contact's radio (named from Hamlib's list, "Yaesu FT-991 (Hamlib 1035)") and power fill in from its beacons; once a contact locks the panel sends its antenna type ("ANT <type>", once per antenna to a saved contact) and fills in the other station's from its message. Each change is logged as a "details" row and told in the Activity log.
- **Reference program:** Settings > Station gains Location and Antenna (a fixed list of common HF antennas, with Homebuilt and Other; both fill into quick messages as {location} and {antenna}); a double-click on Messages received or Stations heard opens the message or station in full in a window of its own; Clear under Queue message; Stop calling moved under Broadcast to ALL; Stations heard and Messages received show the date with the time; a sorted column's heading shows an arrow and the main lists keep the chosen order as rows arrive.
- Tests: tests/test_beacon_rig.py.

## 0.39R1 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.39); reference program only.
- **Prediction check both ways, per station** (live/propcheck.py): besides each station heard here (its SNR against the P.533 prediction from its grid to yours, now at its own power when it has said it, else the usual figure), the SNR a station reports for your signal (carried in answers, acknowledgments and other frames with a channel report) is checked against the prediction from your grid to its, at your measured transmit power. prop_check.csv gains the columns direction (in or out) and power_w; an older file is rewritten with them (its lines are "in"). A contact's window shows the line **Against prediction**: heard here and they hear you, each with the prediction and the average shortfall, and what the difference points to: your transmit side (power, antenna) or noise at their end when your signal falls 8 dB or more further short than theirs; your receive side or their transmit side the other way round; the path itself (antennas at both ends, or the prediction) when both fall 10 dB or more short by about the same. The same line goes to the Activity log, at most once an hour per station, when there is something to say. Tests: tests/test_propgap.py.

## 0.39 (draft, not yet released) - November 24, 2026

- **Signal version 0.39: long notes of up to 64 characters** (Section 6.16, modem/longnote.py): a header and up to eight text frames (was four), each of eight characters (was seven) from a set of 64 coded in 6 bits (was 7-bit ASCII): space, capitals, figures and `. , ? ! ' " / : ; - + = ( ) @ # & * % $ < > _ [ ] ^ |`; small letters are sent as capitals. The header's count is 3 bits (its spare bit is gone) and a text frame's number is 3 bits. A note takes two to nine minutes. Enough for a telemetry message with grid, power, count and about four stations: Quick > Send telemetry as a long note (to the station in To, or ALL). A receiver keeps a note's parts for 40 minutes (was 20). **Stations following 0.38 or earlier misread 0.39 long notes, and 0.39 stations theirs;** long beacons, receipts and everything else are unchanged. Tests: tests/test_longnote.py.
- The rest of this version changes only the reference program (first planned as 0.38R2):
- **Contact traffic log** (live/contacts.py): each saved contact now keeps a row for every beacon, long beacon, answer and mail notice heard from it, every message, broadcast, long note and telemetry message either way, and every call and contact start and end, with the words of each message (up to 500 rows, oldest dropped first). Before, a contact's history held only merged 15-minute sessions, so single beacons and messages were not seen. Broadcasts now count as messages received in a session, received long notes are written to the logbook (they were not), and a station's receptions from the 48-hour heard log are copied into its log when it is saved.
- **Radio and power learned over the air**: when a saved station sends its "Rig and power" quick message ("RIG <radio> <n>W") or telemetry (its power), the contact's Radio and Power fields are updated, a "details" row is logged, and the Activity log says so.
- **Contact window**: the history is two tabs, Traffic (each beacon and message) and Sessions; both have a Local time column beside UTC (headed with the zone, such as "Local (UTC-5)") and sort by any column when its heading is clicked (again to reverse). The Stations heard window (48 hours) also gains Local columns.
- **Sorting the main lists**: Messages to send, Messages received, and Stations heard and saved contacts sort by any column when its heading is clicked (again to reverse).
- **Rig control no longer outlives a crash** (live/rig.py): before, the rigctld Kestrel started kept running after Kestrel crashed and held the radio's serial port, so the next start failed with "the radio did not answer on COMn". Now, on Windows, every rigctld Kestrel starts is put in a job object that Windows closes when Kestrel ends in any way, ending rigctld with it. Kestrel also notes the rigctld's process number (_rigctld.pid in the data folder) and, before starting rig control, ends a rigctld still running under that number, and any rigctld started by a Kestrel (any version) for the same serial port; a rigctld started by hand or by another program is left alone. The Activity log says when one was ended.
- **Contacts window and Stations heard kept apart**: Stations heard's "Remove contact" is now **Remove from list**: it takes stations off the list only, and a saved contact's record stays (the station comes back on the list when heard again). Contact records are kept until deleted in **Stations > Contacts** (Ctrl+K, also a button under Stations heard, and Edit Contact with an empty To box): every contact with name, location, grid, band, radio, power, last heard (UTC and local) and how many traffic rows it holds; a search box (callsign, name, location, grid, radio, antenna or notes) filters as you type; headings sort; New contact, Open / edit (double-click or Enter), Call, and Delete (the Delete key too; asks first). The window follows changes made in a contact's own window.
- **Crash record**: while the panel runs it keeps logs/crash_<time>.txt; if the program dies outright (in the compiled library or the sound system, where no ordinary error report is written), the file says where each thread was. At a normal exit the file is removed.
- Tests: tests/test_contact_log.py, tests/test_rig_leftover.py (a stand-in Kestrel killed outright takes its stand-in rigctld with it).

## 0.38R1 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.38).
- **Smaller installer.** The P.533 engine's twelve monthly ionosphere maps are 128 MB (11.2 MB each) and made the installer 134 MB, over GitHub's 100 MB file limit. The installer now carries the maps of the month it is built and the next two (tools/build_prop.py, SHIP_MONTHS); a prediction for any other month first downloads that month's map from the ITU's own repository (the release the engine is built from), checks its length and SHA-256 against the published file, and keeps it in the data folder (prop_data) for next time (live/propagation.py month_folder). The Propagation window says when it is downloading; with no connection it says that month needs one the first time. The source folder keeps all twelve. Tests: tests/test_prop_months.py.
- The installer and its checksum are kept in the repository's install/ folder (the current version only), as well as on the release page.

## 0.38 (draft) - November 24, 2026

- **Signal version 0.38.** Stations following 0.37 or earlier cannot read 0.38 long beacons and long notes, nor 0.38 stations theirs, and read a beacon with power steps as noise. Everything else is unchanged.
- **Wide long frame** (Section 5.9): the long beacon's and long notes' 32 tones are five bins apart, 4.29 Hz (were three bins, 2.57 Hz), about 137 Hz in all (were 82 Hz), still 59.5 s. The receiver reads each tone's own bin, then three bins, then five bins (new). Simulated nine-in-ten thresholds, three-bin spacing against five: no spread -26 / -26 dB, 1 Hz -22 / -22, 2 Hz -22 / -22, 3 Hz -20 / -22, 4 Hz -16 / -22, 6 Hz not read / -20 (tools/wide_spacing_study.py). The carrier cleaner covers 1500 Hz +/- 130 Hz (was 100). Tests: tests/test_wide_long.py.
- **Power steps before a beacon** (Section 5.10, modem/powersteps.py): four 1 s tones at 1500 Hz, 0, -10, -20 and -30 dB against the beacon, 0.25 s apart, sent just before a short beacon; the beacon header's spare bit says they came. Receivers look back in the audio they keep and read each step (SNR in 2.5 kHz, heard or not, how far apart): about 10 dB a step means the sending transmitter's power follows its drive, less means ALC compression. A step is heard down to about -23 dB in 2.5 kHz. The steps go first so reply slots keep their timing; the beaconing station waits 5 s more for answers. Reference program: Operate > Beacon type > Short, with power steps (Settings > Operating too); the steps read are shown in the Activity log, in Stations heard ("power steps to -20 dB, even") and as four bars in the frame strip. Library interface 16: the compiled header reader accepts the spare bit on a beacon. Tests: tests/test_powersteps.py (the steps' shape, the flag through both header readers and both stations, steps read back from a stream fed as a sound card would through both receivers, uneven steps flagged, noise alone hears none).

## 0.37 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.34); nothing in the specification's rules changes. 0.36 was not released (the number was skipped).
- **Signal recognition** (reference program, live/signalwatch.py): twice a second the newest second of received audio becomes a spectrum in 1 Hz steps (200 to 3000 Hz, Blackman-Harris window, averaged over 5 Hz); anything 10 dB over the noise is a signal, and signals are followed through time as tracks (start, length, frequency, width, strength). Each is given a type from its width, length, start time and steadiness: Kestrel (named by the receiver, with level and callsign), FT8, FT4, JS8 (FT8's shape on a JS8 frequency), WSPR, CW, Carrier, RTTY (two tones 150 to 220 Hz apart), PSK, Other. Stations > Signals detected (Ctrl+D) lists them, on now and heard lately, with start time (UTC or local, as the scopes), audio and radio frequency, width, length and strength; tick boxes choose which types are listed and labeled on the waterfall. Tested with made-up signals of each kind (tests/test_signalwatch.py), including 30 s of noise alone (nothing reported).
- **Recognized signals on the receive scope**: each recognized signal is shaded on the receive trace with its mode named (Kestrel with level and callsign), and named at the top of the waterfall while it is on. Which modes are shown, and whether on the scope, the waterfall or both, is chosen in View > Recognized signals, in the Signals detected window, or by right-clicking the receive scope; the three share one setting. The right-click menu names the signal under the pointer (mode, frequency, width, how long heard) and offers Zoom in on it, Hide its mode, Show only its mode, Full view (what a right click did before), the modes shown, and the Signals detected list.
- **Color themes** (live/theme.py): twenty themes and System (follow Windows): Light (Windows look), Dark, Midnight blue, Solarized light, Solarized dark, High contrast dark, High contrast light, Night red (keeps night vision), Forest green, Amber terminal, Slate gray, Sepia paper, Ocean teal, Purple dusk, Nordic frost, Daylight (bright screens outdoors), Graphite, Steel blue, Desert sand, Olive drab (field radio). A theme colors every part of the program: windows, lists, buttons, tick boxes, drop-downs, tabs, scroll bars, text areas, pop-up menus, the status band's state colors, the highlight of stations calling, warnings, both scopes (background, traces, scales, time marks, station and signal labels), both level meters, the recognized-signal colors, and the title bar (dark or light). View > Waterfall colors gains "Theme's own" (the waterfall follows the theme) and six sets: Night red, Amber, Green phosphor, Thermal, Ice, Ocean.
- **Scope themes** (View > Scope theme): the two scopes and the meters can follow the program theme or take one of eight looks of their own: Classic, Oscilloscope, Spectrum analyzer, Night, Amber, Paper, Thermal, Ice.
- **Theme editor** (View > Edit themes, tools/theme_editor.py): every program and scope theme, built-in or the operator's own, can be changed color by color (a color picker or #rrggbb), renamed, copied to a new theme, exported and imported; the operator's own can be deleted. Changes can be previewed on the panel before saving. A changed built-in theme is marked "changed", is kept apart from Kestrel's original, and Restore original puts it back as it came. The operator's themes and changes are kept in themes.json in the data folder.
- **Exporting and importing** (File menu): Export settings writes the station, radio, audio levels, operating, logging, quick messages and look choices to one file; this computer's sound cards, radio ports and window layout only when asked. Import settings shows whose they are, keeps a copy of the present settings in the data folder, takes only known settings of the right form, keeps this computer's sound cards and ports unless told otherwise, and offers to restart. Themes are exported and imported on their own (File > Export themes / Import themes, and in the theme editor: Export this theme, Export all themes, Import themes). Contacts and logs are not part of either.
- **Frame strip** (under the receive scope; View > Frame strip under the receive scope): a Kestrel frame as it arrives, in four segments: preamble, header, body and header again. A frame appears once its preamble has all arrived and most of its pattern stands out (or its header has been read); the body's length is known, and drawn, once the header is read; the body fills in as it arrives, each stretch colored by how clearly its tones stood out (green clear, amber readable, red lost); and the outcome is shown when the frame ends: passed, failed its check, cut off where the signal stopped (hatched), header read only from the second copy (amber), or neither header copy readable (a near miss). Boxes at the right follow the parts of a message: passed, failed, not heard ("?"), and "Message complete" when all are in. A frame that failed alone but passed with an earlier copy added is shown as passed. The receiver reports its frames in progress after every search (Listener.progress, live/framestrip.py); the compiled receiver lists its candidates through a new library call (kes_listener_candidates, library interface 15). Tested with a frame fed as a sound card would (both receivers), with noise alone (nothing shown), and with every stage of the strip (tests/test_framestrip.py).
- **Windows build**: the build now packs the panel's own modules beside it in tools (theme_editor, frame_strip); the first 0.37 build left them out and the packed program could not start. A test checks that every such module is named in the build recipe (tests/test_packaging.py).

## 0.35 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.34).
- **Bands** (Sections 6.9, 6.10): calling frequencies 17 m 18092.5, 15 m 21112.5, 10 m 28110.0 and 6 m 50340.0 kHz, with channels (two on 17 m, four elsewhere). 6 m is not in the P.533 predictions (2 to 30 MHz).
- **Doppler spread** (Section 5.7): measured on every decoded frame from how far its tones smeared into the bins beside them (in the C++ library, kes_tone_spread, ABI 14, with the same sums in Python). Shown in the activity line and the link readings, written to the signal log. Checked in simulation (tools/spread_check.py).
- **Level choice in fast fading** (Section 6.5): when every recent frame's spread reads 0.5 to 2.5 Hz, the fast-fading table (L0 -14, L1 -8, L2 -10 dB) replaces the general fading table for the slow levels (tools/level_spread_study.py). In the Python and the C++ station alike; the channel report on the air is unchanged.
- **Propagation window** (Section 6.15): Check the bands now: the short-path window from the nearest fresh ionosonde (KC2G), and WSPR and PSK Reporter activity on the path in the last hour. Predictions checked against stations heard (prop_check.csv), with a summary.
- **PSK Reporter**: optional reporting of Kestrel stations heard (Settings > Logging), off by default.
- Not built, with reasons: a two-way link-quality exchange (the acknowledgment already carries SNR, fading, offset and the level wanted, and the receiver chooses from its own measurements; the fast-fading table needed no signal change); a wide-spacing long frame and a stepped-power beacon (both would change what is sent, and the 0.34R1 study showed the three-bin reading already recovers most of the loss up to 2 Hz of spread).
- About box: thanks to KO4WZZ for testing.

## 0.34R1 (draft) - November 24, 2026

- Nothing sent changed (signal version stays 0.34). Tested first: a sky-wave study (tools/skywave_study.py) of the recommendations of the sky-wave research, on the F.1487 conditions plus two new realistic ones in the simulator: "nvis_real" (0.3 Hz spread, 0.8 ms, second path 4 dB weaker and 0.2 Hz off) and "dawn" (0.5 Hz, 1 ms, paths 0.3 Hz apart, 3 dB apart). The simulator's two-path model takes an unequal, shifted second path.
- Receiver (Section 5.9): a long beacon or long-note frame that fails from each tone's own bin is decoded again from each tone's bin plus its two neighbors, alone and when adding copies. Nine-in-ten threshold: 2 dB better at 1 Hz of Doppler spread, 4 dB at 2 Hz, 8 dB or more at 3 to 4 Hz; unchanged on a steady path. The reported SNR is still read from the tones' own bins.
- Propagation (Section 6.15): Update online also fetches KC2G's effective sunspot number and NOAA's space-weather scales and K index. For the current month the 24-hour eSSN replaces the predicted monthly number while under six hours old (on November 24 it was 34 against a predicted 86 or so); the Propagation window and the contact's "Best band now" use it. Warnings for radio blackouts (R1+), geomagnetic storms (Kp 5+) and a falling ionosphere.
- Found not needed: re-centering copies before adding (each copy is already measured at its own frequency and drift; copies 1.2 and 2 Hz apart add as well as copies on frequency), and barring L3/L4 on short paths (95 to 100 % at +10 dB in every condition, 7 ms near-vertical echo included).

## 0.34 (draft) - November 24, 2026

- **SIGNAL VERSION 0.34: long notes** (new Section 6.16). A short message of up to 28 characters sent in long-beacon frames (Section 5.9), for paths too weak for any speed level. A long-note frame is a long-beacon frame whose spare bit is 1; its other 65 field bits are a note header (sender's callsign, 12-bit code of the station addressed or 0 for ALL, number of text frames), a text frame (sender's code, frame number, seven 7-bit characters) or a receipt (receiver's callsign, the sender's code). A note is a header and one to four text frames, one minute each; the station addressed answers with a one-minute receipt; with no receipt within 150 s the note is sent again, up to three times, and the receiver adds the copies together. A note to ALL is sent once, with no receipt.
- Simulation (tests/test_longnote.py): each kind of frame read at -24 dB; a text frame at -28 dB, which one copy does not read, read from two copies added together.
- Stations following 0.33 or earlier take long-note frames for noise (the spare bit is not 0); nothing else changes.
- The reference program: Messages > Send the message as a long note (reach) (Ctrl+N, and a button beside Broadcast to ALL): the To box names the station, or ALL, chosen from the top of its list; the Message box holds up to 28 characters. Messages to send follows the note try by try and frame by frame, with a countdown while the receipt is awaited (for example "SENDING try 1/3, frame 2/4", "receipt due 2:13 (try 1/3, then try 2/3)", "DELIVERED (try 2/3)"); received notes go under Messages received, marked "long note".

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
