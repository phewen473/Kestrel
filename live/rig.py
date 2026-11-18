"""Rig control through Hamlib's rigctld: frequency, mode and transmit switching.

rigctld is the small network program from the Hamlib project that
programs such as WSJT-X use to control a radio. It knows several hundred
radios. Kestrel talks to it over a network socket, so any radio Hamlib
supports can be tuned and keyed, on this computer or another one.

Start rigctld yourself (for example: rigctld -m <model> -r <port> -s <baud>),
or point Kestrel at one that is already running (default 127.0.0.1:4532).
"""

import socket  # the network connection to rigctld


class RigCtl:  # a connection to rigctld
    """Tune and key a radio through rigctld."""

    def __init__(self, address="127.0.0.1:4532", timeout=3.0):  # connect
        host, _, port = address.partition(":")  # "host:port"; the port may be left out
        self.sock = socket.create_connection((host or "127.0.0.1", int(port or 4532)), timeout=timeout)  # open the connection
        self.sock.settimeout(timeout)  # never wait for ever on a reply
        self.pending = b""  # bytes received but not yet used

    def _line(self):  # read one line of rigctld's reply
        while b"\n" not in self.pending:  # until a whole line has arrived
            more = self.sock.recv(4096)  # wait for more
            if not more:  # the connection closed
                raise ConnectionError("rigctld closed the connection")  # say so
            self.pending += more  # add it
        line, _, self.pending = self.pending.partition(b"\n")  # split off the first line
        return line.decode("ascii", "replace").strip()  # as text

    def _set(self, command):  # send a command that changes something
        self.sock.sendall((command + "\n").encode("ascii"))  # send it
        reply = self._line()  # rigctld answers "RPRT 0" when it worked
        if reply != "RPRT 0":  # anything else is a failure
            raise RuntimeError(f"rigctld refused '{command}': {reply}")  # say what went wrong

    def _get(self, command):  # send a command that asks for a value
        self.sock.sendall((command + "\n").encode("ascii"))  # send it
        reply = self._line()  # the value, or an error report
        if reply.startswith("RPRT"):  # an error report
            raise RuntimeError(f"rigctld refused '{command}': {reply}")  # say what went wrong
        return reply  # the value

    def frequency(self):  # where is the radio tuned?
        """Return the radio's frequency in Hz."""
        return float(self._get("f"))  # ask and convert

    def set_frequency(self, hz):  # tune the radio
        """Tune the radio to `hz` (the dial frequency, in Hz)."""
        self._set(f"F {int(round(hz))}")  # whole hertz

    def set_mode(self, mode="PKTUSB", passband_hz=3000):  # choose the radio's mode
        """Put the radio in `mode` (PKTUSB is upper sideband for data) with a receive filter `passband_hz` wide.

        Kestrel's chirp spans 500 to 2500 Hz of audio, so the filter must be
        about 3000 Hz wide. A passband of 0 asks Hamlib for its usual width
        for the mode, which on some radios is a narrow data filter (600 Hz on
        an FTDX10) that removes the signal altogether.
        """
        self._set(f"M {mode} {int(passband_hz)}")  # mode and filter width

    def ptt(self, on):  # key or unkey the transmitter
        """Switch the transmitter on (True) or off (False)."""
        self._set(f"T {1 if on else 0}")  # 1 = transmit, 0 = receive

    def close(self):  # finish
        """Close the connection to rigctld."""
        self.sock.close()  # release the socket
