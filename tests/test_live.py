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
        (4.0, build_beacon("KO4WSC", "EM92", level=1)),  # a beacon
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
    assert seen[:5] == ["M PKTUSB 0", "F 14108500", "f", "T 1", "T 0"]  # exactly the commands rigctld expects
    try:  # a command the radio refuses
        rig._set("X 1")  # nonsense
        raised = False  # it should not get here
    except RuntimeError:  # the refusal is reported
        raised = True  # as it should be
    assert raised  # a refused command is never silently ignored
    rig.close()  # hang up
