"""Reporting Kestrel stations heard to PSK Reporter (since 0.35; off unless the operator turns it on).

PSK Reporter (pskreporter.info) collects reception reports from many
programs and shows them on a map, so operators can see where their signal
goes. Each Kestrel frame decoded with a sender's callsign becomes one report:
the sender's callsign and locator (when known), the frequency the signal
was on, the mode "KESTREL", the SNR, and the time.

The reports go by UDP to report.pskreporter.info, port 4739, in PSK
Reporter's IPFIX format (RFC 5101, enterprise number 30351), following its
rules for programs:
  * at most one datagram every five minutes (unless one is full), with a
    random part added to the timer so many stations do not send at once;
  * each callsign reported at most once in five minutes;
  * the record descriptions in the first three datagrams, then hourly;
  * the same UDP source port for the whole run, one random identifier per run.
Nothing is sent when the station's own callsign or locator is not set.
"""

import random  # the session identifier and the timer's random part
import socket  # UDP
import struct  # network byte order
import threading  # the sending timer runs beside the program
import time  # clocks

HOST = "report.pskreporter.info"  # where reports go
PORT = 4739  # and the port
TEST_PORT = 14739  # PSK Reporter's test port (reports are checked but not kept)
ENTERPRISE = 30351  # PSK Reporter's IPFIX enterprise number
RX_TEMPLATE = 0x9992  # the receiver record's template number
TX_TEMPLATE = 0x9993  # the sender records' template number
INTERVAL_S = 300.0  # at most one datagram every five minutes
JITTER_S = 60.0  # plus up to a minute at random
REPEAT_S = 300.0  # a callsign reported at most once in five minutes
TEMPLATE_EVERY_S = 3600.0  # the record descriptions again every hour
FULL_BYTES = 1200  # a datagram this large is sent at once
SOFTWARE = "Kestrel"  # the program, as reported (the version is added)


def _field(number, length):  # one field specifier of PSK Reporter's own (enterprise bit set)
    """Return the 8 bytes describing field `number` (of enterprise 30351) with `length` bytes (0xFFFF = variable)."""
    return struct.pack("!HHI", 0x8000 | number, length, ENTERPRISE)  # number with the enterprise bit, length, enterprise


def templates():  # the record descriptions
    """Return the two template sets: the receiver record (callsign, locator, software) and the sender record (callsign, frequency, SNR, mode, information source, locator, time)."""
    rx_fields = _field(2, 0xFFFF) + _field(4, 0xFFFF) + _field(8, 0xFFFF)  # receiverCallsign, receiverLocator, decodingSoftware
    rx = struct.pack("!HHH", RX_TEMPLATE, 3, 0) + rx_fields  # template number, 3 fields, no scope fields (an options template)
    rx_set = struct.pack("!HH", 3, 4 + len(rx)) + rx  # set 3: options template set
    tx_fields = (_field(1, 0xFFFF) + _field(5, 4) + _field(6, 1) + _field(10, 0xFFFF) + _field(11, 1) + _field(3, 0xFFFF)  # senderCallsign, frequency, sNR, mode, informationSource, senderLocator
                 + struct.pack("!HH", 150, 4))  # flowStartSeconds (an IANA field, no enterprise)
    tx = struct.pack("!HH", TX_TEMPLATE, 7) + tx_fields  # template number, 7 fields
    tx_set = struct.pack("!HH", 2, 4 + len(tx)) + tx  # set 2: template set
    return rx_set + tx_set  # both


def _text(value):  # a variable-length text field
    """Return `value` as one length byte and its ASCII bytes (at most 254)."""
    data = str(value or "").encode("ascii", "replace")[:254]  # the text
    return bytes([len(data)]) + data  # length first


def _padded_set(set_id, body):  # a data set, padded to four bytes
    """Return a data set with id `set_id` holding `body`, padded with zeros to a multiple of four bytes."""
    pad = (-(4 + len(body))) % 4  # bytes to add
    return struct.pack("!HH", set_id, 4 + len(body) + pad) + body + b"\0" * pad  # header, records, padding


def receiver_record(call, grid, version):  # this station
    """Return the receiver data set for `call` at `grid`."""
    return _padded_set(RX_TEMPLATE, _text(call) + _text(grid) + _text(f"{SOFTWARE} {version}"))  # one record


def sender_records(spots):  # the stations heard
    """Return the sender data set for `spots`: (callsign, frequency Hz, SNR dB, locator, time) each."""
    body = b""  # the records
    for call, hz, snr, grid, when in spots:  # each spot
        snr_byte = max(-128, min(127, int(round(snr))))  # SNR as a signed byte
        body += _text(call) + struct.pack("!I", int(hz)) + struct.pack("!b", snr_byte) + _text("KESTREL") + bytes([1]) + _text(grid) + struct.pack("!I", int(when))  # one record (information source 1: decoded automatically)
    return _padded_set(TX_TEMPLATE, body)  # the set


def datagram(call, grid, version, spots, sequence, session, with_templates, now=None):  # one IPFIX message
    """Return one datagram: the IPFIX header, the descriptions when asked, this station's record and the spots."""
    sets = (templates() if with_templates else b"") + receiver_record(call, grid, version) + sender_records(spots)  # everything after the header
    return struct.pack("!HHIII", 10, 16 + len(sets), int(now or time.time()), sequence, session) + sets  # version 10, length, export time, sequence (counts records), observation domain (the session)


class Spotter:  # reports stations heard, on PSK Reporter's schedule
    """Collect spots and send them in one datagram every five minutes or so."""

    def __init__(self, call, grid, version, host=HOST, port=PORT):  # set up, without sending anything
        self.call, self.grid, self.version = call, grid, version  # this station
        self.address = (host, port)  # where to send
        self.session = random.getrandbits(32)  # one identifier for this run
        self.sequence = 0  # records sent so far
        self.datagrams = 0  # datagrams sent so far
        self.last_templates = 0.0  # when the descriptions last went
        self.pending = {}  # callsign -> spot waiting to go
        self.reported = {}  # callsign -> when last sent
        self.next_send = time.time() + INTERVAL_S + random.uniform(0, JITTER_S)  # the first datagram's time
        self.sock = None  # opened when first needed (the same source port for the whole run)
        self.lock = threading.Lock()  # spots arrive from the receiver's thread
        self.sent_spots = 0  # for the panel

    def add(self, call, hz, snr, grid="", when=None):  # one station heard
        """Queue a spot of `call` heard on `hz` at `snr` dB (from `grid`); ignored if that callsign was reported in the last five minutes."""
        if not call or not self.call or not self.grid:  # nothing to report, or this station unknown
            return False  # not queued
        when = when or time.time()  # when it was heard
        with self.lock:  # one at a time
            if when - self.reported.get(call, -1e9) < REPEAT_S:  # sent lately
                return False  # once in five minutes is enough
            self.pending[call] = (call, hz, snr, grid, when)  # the latest spot of it
        return True  # queued

    def due(self, now=None):  # time to send?
        """Return True when the pending spots should go now (the timer has run out, or a datagram would be full)."""
        now = now or time.time()  # now
        with self.lock:  # one at a time
            if not self.pending:  # nothing to send
                return False  # no
            return now >= self.next_send or len(sender_records(list(self.pending.values()))) > FULL_BYTES  # time, or full

    def flush(self, now=None):  # send the pending spots
        """Send one datagram with every pending spot; return how many were sent (0 on a network error, the spots kept)."""
        now = now or time.time()  # now
        with self.lock:  # one at a time
            spots = list(self.pending.values())  # what to send
            if not spots:  # nothing
                return 0  # nothing sent
            with_templates = self.datagrams < 3 or now - self.last_templates >= TEMPLATE_EVERY_S  # descriptions in the first three and hourly
            packet = datagram(self.call, self.grid, self.version, spots, self.sequence, self.session, with_templates, now)  # the datagram
            try:  # the network may be down
                if self.sock is None:  # first use
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # one socket for the run
                self.sock.sendto(packet, self.address)  # send it
            except OSError:  # no network
                self.next_send = now + INTERVAL_S + random.uniform(0, JITTER_S)  # try again later
                return 0  # kept for then
            self.sequence += len(spots)  # the sequence counts records
            self.datagrams += 1  # one more datagram
            if with_templates:  # the descriptions went
                self.last_templates = now  # note when
            for call, *_ in spots:  # each spot sent
                self.reported[call] = now  # not again for five minutes
            self.reported = {c: t for c, t in self.reported.items() if now - t < REPEAT_S}  # forget old ones
            self.pending.clear()  # all gone
            self.sent_spots += len(spots)  # counted
            self.next_send = now + INTERVAL_S + random.uniform(0, JITTER_S)  # the next datagram's time
            return len(spots)  # how many

    def tick(self, now=None):  # call now and then
        """Send if due; return how many spots were sent."""
        return self.flush(now) if self.due(now) else 0  # send when due

    def close(self):  # at the end of the run
        """Send what is pending and close the socket."""
        self.flush()  # last spots
        if self.sock is not None:  # opened
            self.sock.close()  # closed
            self.sock = None  # gone
