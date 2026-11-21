"""Tests of the continuous receiver that a live station listens with."""

import numpy as np  # numerical arrays

from live import Listener, frame_samples  # the continuous receiver
from modem import ChannelReport, build_ack, build_beacon, build_frame, receive  # frames and the plain receiver
from modem.params import FS  # audio sample rate


def stream(pieces, rng, noise=0.05):  # build one long recording
    """Return audio made of the given frames, each preceded by its gap in seconds, with steady noise throughout."""
    parts = []  # the pieces, in order
    for gap_s, audio in pieces:  # each frame and the silence before it
        parts.append(np.zeros(int(gap_s * FS)))  # the gap
        parts.append(audio)  # the frame
    parts.append(np.zeros(3 * FS))  # three seconds after the last frame
    out = np.concatenate(parts)  # one recording
    return out + noise * rng.standard_normal(len(out))  # with background noise


def test_listener_finds_each_frame_once_as_audio_arrives():  # the basic job
    rng = np.random.default_rng(1201)  # repeatable random source
    report = ChannelReport(-5.0, 0.0, 2.0, 3)  # an arbitrary channel report
    frames = [  # three different frames, at three levels, with gaps between
        (4.0, build_beacon("Q1AAAA", "EM92", level=1)),  # a beacon
        (2.5, build_frame("First message over a live stream.", 3, link=77, msg_id=5, want_level=4)),  # a message
        (1.0, build_ack(77, 5, 0, 0, report, level=4)),  # its acknowledgment, hard on its heels
    ]  # end of the list
    audio = stream(frames, rng)  # the whole recording
    listener = Listener()  # an empty listener
    heard = []  # what it reports
    for i in range(0, len(audio), 2400):  # feed it a fifth of a second at a time, as a sound card would
        heard.extend(listener.feed(audio[i:i + 2400]))  # collect whatever completes
    assert [h.result.frame_type for h in heard] == [2, 0, 4]  # beacon, message, acknowledgment: each once, in order
    assert all(h.result.ok for h in heard)  # all decoded
    assert heard[1].result.text == "First message over a live stream."  # the message text arrived
    again = receive(heard[1].audio)  # the stretch of audio handed over with the message
    assert again.ok and again.text == heard[1].result.text  # holds the whole frame, so a station can decode it again itself
    assert abs(len(heard[1].audio) - frame_samples(heard[1].result) - FS) <= 2  # the frame plus half a second either side


def test_listener_stays_quiet_on_noise_and_on_half_a_frame():  # two things it must not do
    rng = np.random.default_rng(1202)  # repeatable random source
    listener = Listener()  # an empty listener
    noise = rng.standard_normal(60 * FS)  # a minute of pure noise
    reported = []  # anything it claims to hear
    for i in range(0, len(noise), 6000):  # half a second at a time
        reported.extend(listener.feed(noise[i:i + 6000]))  # collect
    assert reported == []  # noise is never reported as a frame
    listener.clear()  # start afresh
    frame = build_frame("x" * 120, 2, link=1, msg_id=1) + 0.05 * rng.standard_normal(len(build_frame("x" * 120, 2, link=1, msg_id=1)))  # a 47-second frame
    half = len(frame) // 2  # its midpoint
    early = []  # reports before the frame is complete
    for i in range(0, half, 6000):  # feed the first half only
        early.extend(listener.feed(frame[i:i + 6000]))  # collect
    assert early == []  # nothing is reported while the frame is still arriving
    late = []  # reports once the rest arrives
    rest = np.concatenate([frame[(half // 6000 + (half % 6000 > 0)) * 6000:], np.zeros(2 * FS) + 0.05 * rng.standard_normal(2 * FS)])  # the remainder, then two seconds of noise
    for i in range(0, len(rest), 6000):  # feed it
        late.extend(listener.feed(rest[i:i + 6000]))  # collect
    assert len(late) == 1 and late[0].result.ok and late[0].result.text == "x" * 120  # reported once, complete and correct


def test_rig_control_speaks_rigctld():  # tuning and keying through Hamlib's rigctld
    import socket  # a stand-in rigctld is run on a local socket
    import threading  # in its own thread

    from live.ptt import Ptt  # the transmit switch
    from live.rig import RigCtl  # the rigctld client

    radio = {"hz": 7100000, "tx": 0}  # the stand-in radio's state
    seen = []  # every command it was sent
    server = socket.socket()  # the stand-in's listening socket
    server.bind(("127.0.0.1", 0))  # any free port
    server.listen(1)  # one client

    def serve():  # the stand-in rigctld
        client, _ = server.accept()  # wait for Kestrel to connect
        waiting = b""  # bytes not yet used
        while True:  # until the client goes away
            more = client.recv(100)  # read
            if not more:  # closed
                break  # done
            waiting += more  # collect
            while b"\n" in waiting:  # every complete line
                line, _, waiting = waiting.partition(b"\n")  # take one
                words = line.decode().split()  # the command and its arguments
                seen.append(line.decode())  # remember it
                if words[0] == "f":  # "what frequency?"
                    client.sendall(f"{radio['hz']}\n".encode())  # answer with the number
                elif words[0] in ("F", "M", "T"):  # set frequency, set mode, key
                    if words[0] == "F":  # frequency
                        radio["hz"] = int(words[1])  # tune
                    if words[0] == "T":  # transmit switch
                        radio["tx"] = int(words[1])  # key or unkey
                    client.sendall(b"RPRT 0\n")  # "done"
                else:  # anything else
                    client.sendall(b"RPRT -1\n")  # "refused"

    threading.Thread(target=serve, daemon=True).start()  # start the stand-in
    rig = RigCtl(f"127.0.0.1:{server.getsockname()[1]}")  # connect to it
    rig.set_mode("PKTUSB")  # choose the mode
    rig.set_frequency(14108500.4)  # tune, with a fraction of a hertz to be rounded off
    assert rig.frequency() == 14108500.0  # the radio reports the new frequency
    ptt = Ptt("rig", rig=rig)  # key through rigctld
    ptt.key()  # transmit
    assert radio["tx"] == 1  # the radio is keyed
    ptt.unkey()  # receive
    assert radio["tx"] == 0  # the radio is unkeyed
    assert seen[:5] == ["M PKTUSB 3000", "F 14108500", "f", "T 1", "T 0"]  # exactly the commands rigctld expects, with the wide receive filter Kestrel needs
    try:  # a command the radio refuses
        rig._set("X 1")  # nonsense
        raised = False  # it should not get here
    except RuntimeError:  # the refusal is reported
        raised = True  # as it should be
    assert raised  # a refused command is never silently ignored
    rig.close()  # hang up


def test_preselected_frequencies_sit_inside_the_automatic_segments():  # the band presets
    from live.bands import PRESETS_KHZ, dial_khz, in_automatic_segment, signal_khz  # the presets and their checks

    assert sorted(PRESETS_KHZ, key=int) == ["20", "30", "40", "80"]  # one preset each for 20, 30, 40 and 80 metres
    from live.bands import WORKING_KHZ, in_data_segment  # the channels, and the data-segment check
    for band in PRESETS_KHZ:  # every preset
        assert in_data_segment(dial_khz(band)) == band  # the calling frequency keeps the whole signal inside the band's U.S. data segment
        assert all(in_data_segment(channel) == band for channel in WORKING_KHZ[band])  # and so does every channel
    assert not in_automatic_segment(dial_khz("40")) and not in_automatic_segment(dial_khz("20"))  # from 0.29 the 40 m and 20 m areas are outside the 97.221(b) segments: attended stations only
    assert dial_khz("20m") == dial_khz(20) == 14112.5  # "20m", 20 and "20" all mean the same band
    assert WORKING_KHZ["20"] == (14115.0, 14117.5, 14120.0, 14122.5) and len(WORKING_KHZ["30"]) == 1  # Channels 1 to 4, 2.5 kHz apart; 30 m has room for one
    assert signal_khz(14108.5) == (14109.0, 14111.0)  # the signal sits 500 to 2500 Hz above the dial
    assert not in_automatic_segment(14098.0)  # a signal that would straddle the beacon frequency at 14100 is refused
    assert not in_automatic_segment(7074.0)  # and so is one outside the segments altogether
    try:  # a band with no preset
        dial_khz("160")  # 160 metres has none
        raised = False  # it should not get here
    except ValueError:  # the lookup refuses
        raised = True  # as it should
    assert raised  # an unknown band is never silently accepted


def test_operator_can_keep_frequencies_of_their_own(tmp_path):  # the list behind the frequency drop-down
    from live.bands import add_user_frequency, all_frequencies, describe_frequency, remove_user_frequency, user_frequencies  # the frequency list

    mine = str(tmp_path / "local" / "frequencies.json")  # a private list for this test (the folder does not exist yet)
    assert [e["band"] for e in all_frequencies(mine)] == ["80 m", "40 m", "30 m", "20 m"]  # with nothing saved, only the presets
    add_user_frequency("17 m", 18106.0, note="evening net", path=mine)  # a frequency inside a 97.221(b) segment
    add_user_frequency("40 m", "7110", mode="usb", path=mine)  # one outside, typed as text and in lower case
    listed = all_frequencies(mine)  # presets first, then the operator's own
    assert [e["builtin"] for e in listed] == [True, True, True, True, False, False]  # four presets, two of the operator's
    assert (listed[5]["dial_khz"], listed[5]["mode"]) == (7110.0, "USB")  # the text became a number, the mode capitals
    assert "97.221(b) segment" in describe_frequency(listed[4]) and "evening net" in describe_frequency(listed[4])  # the list says an unattended station may use it
    assert "attended only" in describe_frequency(listed[5])  # and that the other needs an operator present
    remove_user_frequency(0, mine)  # take the first of the operator's own away
    assert [e["band"] for e in user_frequencies(mine)] == ["40 m"]  # the other is still there, and was saved
    for bad in (("", 7100.0), ("40 m", "abc"), ("40 m", 5.0)):  # no band name, not a number, not a sensible frequency
        try:  # each must be refused
            add_user_frequency(bad[0], bad[1], path=mine)  # try to add it
            raised = False  # it should not get here
        except ValueError:  # refused
            raised = True  # as it should be
        assert raised  # nothing bad is ever saved


def test_status_from_log_lines():  # the panel's status display reads the station's state from log lines
    from live import status_for  # the function under test
    assert status_for("   73.0s Q1AAAA: locked with Q2BB; told to send at L4, asking for L3")[0] == "LOCKED with Q2BB  -  sending at L4, receiving at L3"  # the beaconing side's lock line
    assert status_for("  151.0s Q1AAAA: locked with Q2BB; told to send at L4")[0] == "LOCKED with Q2BB  -  sending at L4"  # the answering side's lock line
    assert status_for("  104.3s Q1AAAA: heard Q2BB at +26 dB; answering, asking for L4")[0] == "ANSWERING Q2BB"  # a beacon being answered
    assert status_for("  170.1s Q1AAAA: contact closed by partner")[0] == "CONTACT CLOSED"  # the end of a contact
    assert status_for("    0.0s  Q1AAAA on the air as answerer")[0].startswith("LISTENING")  # waiting for a beacon
    assert status_for("    0.0s  sending beacon at L0, 28.4 s")[0].startswith("CALLING")  # calling
    assert status_for("  126.7s  finished")[0] == "STOPPED"  # the run has ended
    assert status_for("   91.2s  heard acknowledgment at L4, +14.4 dB") is None  # an ordinary line changes nothing


def test_plain_log_lines():  # the panel's plain view drops the technical detail from a log line
    from live import plain_line  # the function under test
    assert plain_line("   73.0s  heard answer at L0, +33.0 dB, offset +4.3 Hz, fading 0.00  {'dest': 'Q1AAAA', 'levels': (0, 1)}") == "heard answer at L0, +33.0 dB, fading 0.00"  # a control frame loses its stamp, offset and fields
    assert plain_line("             73.0s Q1AAAA: locked with Q2BB; told to send at L4, asking for L4") == "locked with Q2BB; told to send at L4, asking for L4"  # a station note loses its stamp and callsign
    assert plain_line("   36.5s  sending answer at L0, 36.8 s  slot 0, wants L4") == "sending answer at L0, 36.8 s"  # a transmission loses its slot and wanted level
    assert plain_line(" 1224.1s  noise briefly looked like the start of a frame; nothing decoded") is None  # a false alarm is left out
    assert plain_line("radio tuned to 10144.0 kHz PKTUSB  (30 m)") == "radio tuned to 10144.0 kHz PKTUSB  (30 m)"  # an ordinary line is unchanged


def test_rigctld_model_list_is_read():  # the list of radios rigctld prints is turned into numbers and names
    from live.rig import parse_models  # the function under test
    listing = " Rig #  Mfg                    Model                   Version         Status      Macro\n  1042  Yaesu                  FTDX-10                 20230101.0      Stable      RIG_MODEL_FTDX10\n     1  Hamlib                 Dummy                   20221128.0      Stable      RIG_MODEL_DUMMY\n"  # a short sample of the listing
    assert parse_models(listing) == [(1, "Hamlib Dummy"), (1042, "Yaesu FTDX-10")]  # numbers and names, in name order, without the heading line


def test_working_frequencies_for_a_calling_frequency():  # the working frequencies offered after a lock
    from live.bands import builtin_frequencies, signal_khz, working_offsets_hz  # the functions under test
    for entry in builtin_frequencies():  # each meeting frequency
        offsets = working_offsets_hz(entry)  # its working frequencies, as offsets in hertz
        assert offsets and all(offset % 100 == 0 for offset in offsets)  # there are some, and each fits the 100 Hz steps the move uses
        calling = signal_khz(entry["dial_khz"])  # where the calling signal sits
        for offset in offsets:  # each working frequency
            working = signal_khz(entry["dial_khz"] + offset / 1000.0)  # where its signal sits
            assert working[1] <= calling[0] or working[0] >= calling[1]  # it does not overlap the calling frequency
    assert working_offsets_hz({"band": "17 m", "dial_khz": 18106.0, "builtin": False}) == [2500, -2500]  # an operator's own frequency gets the next channel up and down
    from live.bands import channel_names  # the names the panel shows
    forty = [entry for entry in builtin_frequencies() if entry["band"] == "40 m"][0]  # the 40 m calling frequency
    assert channel_names(forty) == [("Channel 1", 2500), ("Channel 2", 5000), ("Channel 3", 7500), ("Channel 4", 10000)]  # numbered, 2.5 kHz apart


def test_upper_sideband_only_and_the_data_mode_fallback(tmp_path):  # USB-D where the radio has it, USB where not, never LSB
    from live.bands import add_user_frequency, mode_name  # the operator's list
    from live.rig import RigCtl  # rig control

    mine = str(tmp_path / "frequencies.json")  # a private list
    assert add_user_frequency("17 m", 18106.0, mode="usb-d", path=mine)["mode"] == "PKTUSB"  # "USB-D" is the radio's data mode
    assert add_user_frequency("17 m", 18106.0, mode="USB", path=mine)["mode"] == "USB"  # plain USB is allowed
    for bad in ("LSB", "PKTLSB", "LSB-D", "CW"):  # lower sideband and anything else
        try:  # must be refused
            add_user_frequency("40 m", 7110.0, mode=bad, path=mine)  # try it
            raised = False  # it should not get here
        except ValueError:  # refused
            raised = True  # as it should
        assert raised  # Kestrel is upper sideband only
    assert mode_name("PKTUSB") == "USB-D" and mode_name("USB") == "USB"  # as operators know them

    class Fake(RigCtl):  # a radio with no data mode, without a network connection
        def __init__(self, has_data):  # set up
            self.has_data, self.sent = has_data, []  # whether it has USB-D, and what it was asked
        def _set(self, command):  # a command that changes something
            self.sent.append(command)  # note it
            if command.startswith("M PKTUSB") and not self.has_data:  # no such mode on this radio
                raise RuntimeError("rigctld refused")  # as rigctld reports it

    old = Fake(False)  # a radio without USB-D
    assert old.set_data_mode("auto") == "USB" and old.sent == ["M PKTUSB 3000", "M USB 3000"]  # the data mode is tried, then plain USB
    new = Fake(True)  # a radio with it
    assert new.set_data_mode("auto") == "PKTUSB" and new.sent == ["M PKTUSB 3000"]  # taken at once
    assert Fake(True).set_data_mode("USB") == "USB"  # the operator can ask for plain USB


def test_scope_spectrum_shows_a_tone_where_it_is():  # the scope's spectrum puts a tone at the right place and level
    import numpy as np  # arrays
    from live.audio import SCOPE_SAMPLES, scope_spectrum  # the function under test
    t = np.arange(SCOPE_SAMPLES) / 48000.0  # the sample times at the sound card's rate
    levels = scope_spectrum(0.5 * np.sin(2 * np.pi * 1500.0 * t), 48000.0, 3000.0, 512)  # a half-scale tone at 1500 Hz
    peak = int(np.argmax(levels))  # where the display is brightest
    assert abs(peak * 3000.0 / 511 - 1500.0) < 10.0  # within a few hertz of 1500
    assert abs(levels[peak] - 20 * np.log10(0.5)) < 3.0  # and about 6 dB below full scale, as a half-scale tone should be (a display point may fall between two frequency bins)
    assert levels[60] < levels[peak] - 60  # far from the tone the display is dark


def test_waiting_call_is_dropped_when_a_contact_starts_first():  # the bug of 19 November: an old call went out after a long contact ended
    from link import Station  # the link rules
    from live import call_request  # the panel's directed-call request
    said = []  # what the request told the operator
    a = Station("Q1AAAA", "EM92")  # the station
    a.listen()  # listening
    a.beacon_once()  # in the middle of a beacon round when the operator asks for the call
    request = call_request("Q2BB", after_contact=False, say=said.append)  # call Q2BB once free
    assert request(a) is False  # busy with the beacon round: it waits
    a.state, a.partner = "LOCKED", "Q2BB"  # then Q2BB answers the beacon and the pair lock
    assert request(a) is True and "already in contact" in said[-1]  # the call is dropped, not saved for later
    a.state, a.partner = "LOCKED", "Q3CCC"  # a contact with somebody else instead
    other = call_request("Q2BB", after_contact=False, say=said.append)  # a fresh request made before that contact
    assert other(a) is True and "started first" in said[-1]  # dropped too


def test_call_asked_for_during_a_contact_waits_for_it_to_end():  # "call Q2BB when this contact is over" still works
    from link import Station  # the link rules
    from live import call_request  # the panel's directed-call request
    a = Station("Q1AAAA", "EM92")  # the station
    a.listen()  # listening
    a.state, a.partner = "LOCKED", "Q3CCC"  # in a contact with Q3CCC
    request = call_request("Q2BB", after_contact=True, say=lambda text: None)  # the operator asks to call Q2BB afterwards
    assert request(a) is False  # it waits for the contact
    a.state, a.partner = "IDLE", ""  # the contact ends and the station is listening again
    assert request(a) is True and a.role == "caller" and a.target == "Q2BB"  # now the call is made


def test_data_segment_check_refuses_frequencies_outside_the_amateur_bands():  # the check that would have caught 3160 kHz
    from live.bands import add_user_frequency, in_data_segment  # the check, and adding a frequency
    import tempfile  # a scratch file for the operator's list

    assert in_data_segment(3582.5) == "80"  # the 80 m calling frequency is inside the 80 m data segment
    assert in_data_segment(3160.0) is None  # 3160 kHz is not an amateur frequency at all
    assert in_data_segment(7099.0) == "40"  # 7099.5-7101.5 kHz is inside 7000-7125
    assert in_data_segment(3599.0) is None  # the signal would run past 3600 kHz, the top of the 80 m data segment
    with tempfile.TemporaryDirectory() as folder:  # an empty place for the list
        path = folder + "/frequencies.json"  # the list's file
        try:  # adding an out-of-band HF frequency must be refused
            add_user_frequency("80 m", 3160.0, path=path)  # the typo from the first on-air test
            raised = False  # it should not get here
        except ValueError:  # refused
            raised = True  # as it should
        assert raised  # never silently accepted
        assert add_user_frequency("80 m", 3585.0, path=path)["dial_khz"] == 3585.0  # an in-band one is kept


def test_recorder_writes_wav_that_reads_back(tmp_path):  # the received-audio recorder
    import numpy as np  # numerical arrays
    from live.recorder import Recorder, read_wav  # the recorder and the reader
    from modem.params import FS  # 12,000 samples per second

    audio = 0.3 * np.sin(2 * np.pi * 1000 * np.arange(int(2.5 * FS)) / FS)  # two and a half seconds of a 1 kHz tone
    rec = Recorder(str(tmp_path), label="Q1AAAA", file_seconds=1, clock=lambda: 1795280000.0)  # one-second files, so the split is tested
    rec.write(audio[:7000])  # in two uneven pieces, as a live source delivers it
    rec.write(audio[7000:])  # the rest
    rec.close()  # finish
    assert len(rec.files) == 3  # 2.5 seconds in one-second files makes three files
    back = np.concatenate([read_wav(path)[0] for path in sorted(rec.files)])  # read them all back in order
    assert len(back) == len(audio)  # every sample is there
    assert np.max(np.abs(back - audio)) < 1e-3  # and matches to within 16-bit rounding


def test_listener_reports_a_near_miss_once():  # a clear signature whose header cannot be read
    import numpy as np  # numerical arrays
    from live.listener import Listener  # the continuous receiver
    from modem import build_frame  # the transmitter
    from modem.params import FS  # 12,000 samples per second

    frame = build_frame("Q1AAAA DE Q2BB", 3)  # a frame at L3
    rng = np.random.default_rng(3)  # repeatable noise
    spoilt = frame.copy()  # the same frame...
    spoilt[int(0.5 * len(frame)):] = 0.0  # ...with its second half (and so the second header copy) gone
    from modem.levels import LEVELS  # level numbers
    from modem.params import PREAMBLE_TONES  # the preamble's length in tones
    first = PREAMBLE_TONES * LEVELS[3].samples  # where the first header copy starts
    spoilt[first:first + 12 * LEVELS[3].samples] = rng.standard_normal(12 * LEVELS[3].samples) * 0.3  # and its first header copy drowned in noise
    audio = np.concatenate([rng.standard_normal(5 * FS) * 0.02, spoilt, rng.standard_normal(100 * FS) * 0.02])  # noise, the spoilt frame, plenty of noise after
    audio[5 * FS:5 * FS + len(spoilt)] += rng.standard_normal(len(spoilt)) * 0.02  # background noise under the frame too
    listener, seen = Listener(), []  # a receiver, and a list of near misses
    listener.on_near = seen.append  # collect them
    for begin in range(0, len(audio), FS):  # one second at a time
        assert not listener.feed(audio[begin:begin + FS])  # nothing decodes
    assert len(seen) == 1  # the signature was reported, exactly once
    assert seen[0].seen_level >= 0  # with a guess at its level


def test_rig_list_says_why_it_is_empty_and_falls_back(tmp_path, monkeypatch):  # the Settings window's rig type list
    import os  # file permissions
    import sys  # which system this is
    import live.rig as rig  # rig control helpers

    models, reason = rig.list_models_why(str(tmp_path / "missing" / "rigctld"))  # a saved path that is no longer there
    assert models == [] and "not where the settings say" in reason  # no list, and the reason in plain words
    assert rig.list_models_why("")[1].startswith("no rigctld program")  # nothing to ask at all
    if sys.platform == "win32":  # the rest needs a stand-in program, made here as a shell script
        return  # not on Windows
    good = tmp_path / "rigctld"  # a stand-in rigctld that lists two radios
    good.write_text("#!/bin/sh\necho ' Rig #  Mfg                    Model                   Version         Status'\necho '  1035  Yaesu                  FT-991                  20240101.0      Stable'\necho '  1042  Yaesu                  FTDX-10                 20240101.0      Stable'\n")  # in rigctld's own layout
    os.chmod(good, 0o755)  # make it runnable
    silent = tmp_path / "silent"  # one that runs but lists nothing
    silent.write_text("#!/bin/sh\nexit 3\n")  # no output
    os.chmod(silent, 0o755)  # make it runnable
    assert rig.list_models_why(str(good)) == ([(1035, "Yaesu FT-991"), (1042, "Yaesu FTDX-10")], "")  # the list, and no complaint
    assert "listed no radios" in rig.list_models_why(str(silent))[1]  # ran, but nothing came back
    monkeypatch.setattr(rig, "find_rigctld", lambda extra_folders=(): str(good))  # this computer has the good one
    program, models, reason = rig.models_for(str(tmp_path / "missing" / "rigctld"))  # the settings name one that has gone
    assert program == str(good) and len(models) == 2 and reason == ""  # the one found is used instead, and the list is filled
    monkeypatch.setattr(rig, "find_rigctld", lambda extra_folders=(): "")  # a computer with none at all
    assert rig.models_for("")[1] == [] and "setup program installs one" in rig.models_for("")[2]  # empty, with what to do about it


def test_transmit_scope_shows_what_is_being_played():  # the transmit scope's spectrum follows the audio going out
    import time  # to place the playback position
    from live.audio import CARD_RATE, AudioOut  # the sound-card output and its rate
    sink = AudioOut(None, 0.5)  # an output that is never opened
    assert sink.spectrum() is None  # nothing is playing, so there is nothing to show
    t = np.arange(2 * CARD_RATE) / CARD_RATE  # two seconds at the card's rate
    sink.sending, sink.started, sink.playing = (0.5 * np.sin(2 * np.pi * 1500.0 * t)).astype("float32"), time.monotonic() - 1.0, True  # a 1500 Hz tone, one second into its playing
    levels = sink.spectrum(3000.0, 720)  # what the transmit scope would draw
    assert len(levels) == 720  # one level per point across
    assert abs(int(np.argmax(levels)) * 3000.0 / 719 - 1500.0) < 6.0  # the peak is at 1500 Hz, to within a point or so
    sink.playing = False  # the transmission ends
    assert sink.spectrum() is None  # and the scope has nothing new to show


def test_scope_spectrum_zoomed_separates_long_beacon_tones():  # a zoomed-in scope shows two tones 2.57 Hz apart as two peaks
    from live.audio import CARD_RATE, SCOPE_LONG, scope_length, scope_spectrum  # the functions under test
    assert scope_length(1400.0, 1600.0) == SCOPE_LONG  # a narrow view uses the longer stretch of audio
    t = np.arange(SCOPE_LONG) / CARD_RATE  # that stretch, in seconds
    levels = scope_spectrum(0.3 * np.sin(2 * np.pi * 1500.0 * t) + 0.3 * np.sin(2 * np.pi * 1502.571 * t), CARD_RATE, 1600.0, 720, 1400.0)  # two neighbouring long-beacon tones, seen 200 Hz wide
    hz = np.linspace(1400.0, 1600.0, 720)  # the frequency of each point
    assert len(levels) == 720  # one level per point across
    dip = levels[np.argmin(np.abs(hz - 1501.29))]  # the level midway between the two tones
    assert levels[np.argmin(np.abs(hz - 1500.0))] - dip > 5.0 and levels[np.argmin(np.abs(hz - 1502.571))] - dip > 5.0  # each tone stands clear of the gap between them
