"""Tests: long notes (signal version 0.34): short messages in long-beacon frames, with receipts and resends."""
import numpy as np  # arrays
import pytest  # the test runner

from modem import longbeacon, longnote  # the frames
from modem.frame import RxResult  # a receiver's report
from modem.params import FS, REF_BANDWIDTH_HZ  # sample rate, SNR bandwidth


def _noise_for(audio, snr_db, rng):  # the frame in noise at `snr_db` (in 2.5 kHz)
    power = np.mean(audio ** 2)  # signal power
    noise = power / (10 ** (snr_db / 10)) / (REF_BANDWIDTH_HZ / (FS / 2))  # noise power over the whole band for that SNR in 2.5 kHz
    pad = int(2 * FS)  # two seconds of noise either side
    x = np.concatenate([np.zeros(pad), audio, np.zeros(pad)])  # the frame, with room around it
    return x + rng.normal(0.0, np.sqrt(noise), len(x))  # plus noise


def _read(x):  # decode the best long candidate in `x`
    failed = []  # copies that did not decode
    for found in longbeacon.candidates(longbeacon.clean(x)):  # the long pattern's candidates
        result = longbeacon.decode_at(longbeacon.clean(x), found, RxResult(start=found["start"]), failed=failed)  # try it
        if result.ok:  # decoded
            return result, failed  # done
    return None, failed  # nothing


def test_note_fields_round_trip():  # packing and unpacking each kind
    frames = longnote.note_fields("Q1AAAA", "Q2BB", "QSL -24 DB 73 PAT EM93")  # a 22-character note
    assert len(frames) == 1 + 4 and all(len(bits) == longnote.FIELD_BITS for bits in frames)  # a header and four text frames of 65 bits
    header = longnote.unpack(frames[0])  # the header
    assert header["note"] == "header" and header["origin"] == "Q1AAAA" and header["dest_code"] == longnote.code_for("Q2BB") and header["parts"] == 4  # who, to whom, how many
    texts = [longnote.unpack(bits) for bits in frames[1:]]  # the text frames
    assert "".join(t["text"] for t in texts).rstrip() == "QSL -24 DB 73 PAT EM93" and all(t["origin_code"] == longnote.code_for("Q1AAAA") for t in texts)  # the text, and whose it is
    receipt = longnote.unpack(longnote.pack_receipt("Q2BB", "Q1AAAA"))  # a receipt
    assert receipt == {"note": "receipt", "origin": "Q2BB", "dest_code": longnote.code_for("Q1AAAA"), "long": True}  # who received whose note
    assert longnote.unpack(longnote.pack_header("Q1AAAA", "ALL", 1))["dest_code"] == longnote.ALL_CODE  # a note to everyone
    with pytest.raises(ValueError):  # too long
        longnote.note_fields("Q1AAAA", "Q2BB", "x" * 29)  # refused


def test_note_frames_decode_weak_and_beacons_still_read():  # over the air
    rng = np.random.default_rng(34)  # repeatable
    for audio, kind in [(longnote.build_note("Q1AAAA", "Q2BB", "HELLO 73")[0], "header"), (longnote.build_note("Q1AAAA", "Q2BB", "HELLO 73")[1], "text"), (longnote.build_receipt("Q2BB", "Q1AAAA"), "receipt")]:  # each kind
        assert abs(len(audio) / FS - longbeacon.SECONDS) < 0.1  # about a minute, like the long beacon
        result, _ = _read(_noise_for(audio, -24.0, rng))  # at -24 dB
        assert result is not None and result.fields["note"] == kind  # read, as the right kind
    result, _ = _read(_noise_for(longbeacon.build_long_beacon("Q1AAAA", "EM93"), -24.0, rng))  # a long beacon, as before
    assert result is not None and result.fields["grid"] == "EM93" and "note" not in result.fields  # still a beacon


def test_two_weak_copies_of_a_note_frame_add_up():  # the receiver's combining helps a resent note
    rng = np.random.default_rng(35)  # repeatable
    audio = longnote.build_note("Q1AAAA", "Q2BB", "HELLO 73")[1]  # a text frame
    combiner = longbeacon.LongCombiner()  # the receiver's memory of failed copies
    for trial in range(12):  # weak copies until two fail alone and decode together
        result, failed = _read(_noise_for(audio, -28.0, rng))  # far below what one copy reads
        if result is not None:  # read alone this time
            continue  # not the case being tested
        for found, soft in failed[:1]:  # the strongest failed candidate
            got = combiner.offer(soft, now=trial * 300.0)  # kept, and tried with earlier copies (five minutes apart)
            if got is not None:  # decoded together
                assert got[0]["note"] == "text" and got[0]["text"] == "HELLO 7" and got[2] >= 2  # the right frame, from two or more copies
                return  # done
    raise AssertionError("weak copies never added up")  # combining never helped


def test_note_receipt_and_resend():  # the exchange, without audio
    from live.notes import LongNotes, RECEIPT_WAIT_S  # the note logic
    sender, receiver = LongNotes("Q1AAAA"), LongNotes("Q2BB")  # two stations
    sender.queue("Q2BB", "QSL -24 DB 73")  # a note
    frames, what = sender.next_frames(0.0)  # it goes out
    assert len(frames) == 3 and all(f.kind == "long note" for f in frames)  # header and two text frames
    sender.sent(what, 180.0)  # all sent by three minutes
    fields = [longnote.unpack(bits) for bits in longnote.note_fields("Q1AAAA", "Q2BB", "QSL -24 DB 73")]  # what the receiver reads
    receiver.heard(fields[0], 60.0)  # the header
    receiver.heard(fields[2], 180.0)  # the second text frame (the first was lost)
    assert receiver.events == []  # not complete yet
    sender.tick(180.0 + RECEIPT_WAIT_S + 1)  # no receipt in time
    assert sender.events[-1][0] == "resending" and sender.due(400.0) == "note"  # it goes again
    frames, what = sender.next_frames(400.0)  # the second try
    sender.sent(what, 580.0)  # sent
    receiver.heard(fields[1], 460.0)  # the missing part arrives (perhaps from two copies added together)
    assert receiver.events == [("received", "Q1AAAA", "Q2BB", "QSL -24 DB 73")]  # the whole note
    assert receiver.due(470.0) == "receipt"  # a receipt is due
    receipt, _ = receiver.next_frames(600.0)  # it goes
    assert receipt[0].kind == "long receipt"  # one frame
    sender.heard(longnote.unpack(longnote.pack_receipt("Q2BB", "Q1AAAA")), 660.0)  # the sender hears it
    assert sender.events[-1] == ("delivered", "Q2BB", "QSL -24 DB 73", 2) and not sender.busy()  # delivered on the second try
    receiver.heard(fields[0], 700.0)  # a stray third copy, header
    receiver.heard(fields[1], 760.0)  # and text
    receiver.heard(fields[2], 820.0)  # complete again
    assert len([e for e in receiver.events if e[0] == "received"]) == 1  # not shown twice


def test_notes_to_others_are_not_shown_and_all_gets_no_receipt():  # addressing
    from live.notes import LongNotes  # the note logic
    listener = LongNotes("Q3CCC")  # a third station
    for bits in longnote.note_fields("Q1AAAA", "Q2BB", "PRIVATE"):  # a note to someone else
        listener.heard(longnote.unpack(bits), 10.0)  # heard
    assert listener.events == [] and not listener.busy()  # not shown, no receipt
    for bits in longnote.note_fields("Q1AAAA", "ALL", "CQ NET 2100Z"):  # a note to everyone
        listener.heard(longnote.unpack(bits), 20.0)  # heard
    assert listener.events == [("received", "Q1AAAA", "ALL", "CQ NET 2100Z")] and not listener.busy()  # shown, and no receipt
    sender = LongNotes("Q1AAAA")  # the sender of a note to ALL
    sender.queue("ALL", "CQ NET 2100Z")  # queued
    _, what = sender.next_frames(0.0)  # sent
    sender.sent(what, 120.0)  # done
    assert sender.events == [("sent", "ALL", "CQ NET 2100Z", 1)] and not sender.busy()  # reported sent, nothing to wait for


def test_runner_sends_a_queued_note_when_free():  # the live loop, with stand-in audio
    from link.station import Station  # the link rules
    from live.notes import LongNotes  # the note logic
    from live.runner import run_station  # the live loop

    class Source:  # a quiet sound card
        def read(self):  # the newest audio
            return np.zeros(1200)  # a tenth of a second of silence

        def flush(self):  # throw away what arrived
            pass  # nothing kept

    class Sink:  # a sound card that keeps what it is given
        def __init__(self):  # nothing sent yet
            self.sent = []  # each transmission's audio

        def play(self, audio):  # send it
            self.sent.append(audio)  # kept

    class Ptt:  # a transmit switch that does nothing
        def key(self):  # on
            pass  # nothing

        def unkey(self):  # off
            pass  # nothing

    station = Station("Q1AAAA", "EM93")  # this station
    station.listen()  # just listening
    notes = LongNotes("Q1AAAA")  # its long notes
    notes.queue("Q2BB", "HI 73")  # one short note
    events, sink = [], Sink()  # what is reported, and what goes out
    run_station(station, Source(), sink, Ptt(), say=lambda line: None, limit_s=1.0, listen_first=False, notes=notes, on_note=events.append)  # a second of running
    assert len(sink.sent) == 2 and all(abs(len(audio) / FS - longbeacon.SECONDS) < 0.1 for audio in sink.sent)  # the header and one text frame, a minute each
    assert notes.outgoing and notes.outgoing[0].waiting_until > 0 and notes.due(2.0) is None  # now waiting for the receipt
