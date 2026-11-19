"""Rig control through Hamlib's rigctld: frequency, mode and transmit switching.

rigctld is the small network program from the Hamlib project that
programs such as WSJT-X use to control a radio. It knows several hundred
radios. Kestrel talks to it over a network socket, so any radio Hamlib
supports can be tuned and keyed, on this computer or another one.

Start rigctld yourself (for example: rigctld -m <model> -r <port> -s <baud>),
point Kestrel at one that is already running (default 127.0.0.1:4532), or let
RigServer start one for a chosen radio type and serial port, the way the
control panel does.
"""

import os  # file paths, for finding the rigctld program
import shutil  # looks for a program on the search path
import socket  # the network connection to rigctld
import subprocess  # starts the rigctld program
import sys  # tells Windows from other systems
import tempfile  # a scratch file for rigctld's own messages
import time  # short waits while rigctld starts

RIGCTLD_NAMES = ("rigctld", "rigctld-wsjtx", "rigctld.exe", "rigctld-wsjtx.exe")  # names the rigctld program goes by (WSJT-X ships its own copy)
HIDDEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # on Windows, start helper programs without a console window


def find_rigctld(extra_folders=()):  # look for the rigctld program
    """Return the path of a rigctld program, or "" if none is found.

    The search path is tried first, then any `extra_folders`, then the bin
    folder of any WSJT-X installed in the usual place on Windows.
    """
    for name in RIGCTLD_NAMES:  # each name it goes by
        found = shutil.which(name)  # on the search path?
        if found:  # yes
            return found  # use it
    folders = list(extra_folders)  # folders suggested by the caller
    if sys.platform == "win32":  # on Windows, look where WSJT-X is usually installed
        for top in (os.path.join(os.environ.get("SystemDrive", "") + os.sep, "WSJT"), os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):  # the usual parent folders: the WSJT-X installer's own default, then the program folders
            if top and os.path.isdir(top):  # the folder exists
                folders += [os.path.join(top, name, "bin") for name in sorted(os.listdir(top), reverse=True) if "wsjt" in name.lower()]  # every WSJT-X folder's bin, newest name first
    for folder in folders:  # each candidate folder
        for name in RIGCTLD_NAMES:  # each name
            path = os.path.join(folder, name)  # the full path
            if os.path.isfile(path):  # it is there
                return path  # use it
    return ""  # not found


def parse_models(listing):  # read rigctld's list of radios
    """Return [(model number, "Maker Model")] from the text `rigctld -l` prints, sorted by name."""
    models = []  # the radios found
    for line in listing.splitlines():  # each line of the listing
        words = [word.strip() for word in line.strip().split("  ") if word.strip()]  # its columns (separated by two or more spaces)
        if len(words) >= 3 and words[0].isdigit():  # a radio line: number, maker, model, ...
            models.append((int(words[0]), f"{words[1]} {words[2]}"))  # keep the number and the name
    return sorted(models, key=lambda model: model[1].lower())  # in name order


def list_models(program):  # ask rigctld which radios it knows
    """Return [(model number, name)] for the rigctld at `program`, or [] if it cannot be run."""
    try:  # the program may be missing or refuse to run
        done = subprocess.run([program, "-l"], capture_output=True, text=True, timeout=20, cwd=os.path.dirname(program) or None, **HIDDEN)  # ask for the list
    except (OSError, subprocess.SubprocessError):  # it could not be run
        return []  # no list
    return parse_models(done.stdout + "\n" + done.stderr)  # the list may come on either output


class RigServer:  # a rigctld started and stopped by Kestrel
    """Runs rigctld for one radio, so the operator only has to choose the radio type and its serial port."""

    def __init__(self):  # nothing running yet
        self.process = None  # the rigctld process, when one is running
        self.config = None  # the settings it was started with
        self.address = ""  # where it is listening, as host:port
        self.notes = None  # a scratch file that collects rigctld's own messages

    def ensure(self, program, model, port, baud, handshake="none"):  # make sure rigctld is running with these settings
        """Start rigctld if needed and return its address. Raise RuntimeError with the reason if it will not start."""
        config = (program, int(model), port, int(baud), handshake)  # the settings asked for
        if self.process is not None and self.process.poll() is None and config == self.config:  # already running with the same settings
            return self.address  # use it as it is
        self.stop()  # stop any rigctld running with other settings
        with socket.socket() as probe:  # find a free network port on this computer
            probe.bind(("127.0.0.1", 0))  # let the system choose one
            tcp = probe.getsockname()[1]  # the port it chose
        command = [program, "-m", str(config[1]), "-r", port, "-s", str(config[3]), "-T", "127.0.0.1", "-t", str(tcp)]  # radio type, serial port, speed, and where to listen
        if handshake == "hardware":  # the radio wants RTS/CTS handshaking
            command += ["-C", "serial_handshake=Hardware"]  # say so
        self.notes = tempfile.TemporaryFile(mode="w+")  # rigctld's messages go to a scratch file (a pipe nobody reads would fill up and stall it)
        try:  # the program may be missing
            self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=self.notes, text=True, cwd=os.path.dirname(program) or None, **HIDDEN)  # start rigctld
        except OSError as problem:  # it could not be started
            raise RuntimeError(f"could not start the rig control program: {problem}")  # say why
        self.config, self.address = config, f"127.0.0.1:{tcp}"  # remember what is running and where
        for _ in range(60):  # give it up to six seconds to open the radio
            if self.process.poll() is not None:  # it has already given up
                self.notes.seek(0)  # go back to the start of its messages
                reason = self.notes.read().strip().splitlines()[-1:]  # the last thing it said
                self.process = None  # nothing is running
                raise RuntimeError("rig control could not open the radio" + (f": {reason[0]}" if reason else "") + f" (check the rig type, that {port} is the right port and that no other program is using it)")  # say why
            try:  # is it listening yet?
                socket.create_connection(("127.0.0.1", tcp), timeout=0.2).close()  # try to connect
                break  # yes: go on to check the radio itself
            except OSError:  # not yet
                time.sleep(0.1)  # wait a moment
        else:  # it never started listening
            self.stop()  # give up on it
            raise RuntimeError("rig control did not start in time")  # say so
        try:  # rigctld is running; now make sure the radio itself answers
            check = RigCtl(self.address, timeout=5.0)  # connect
            check.frequency()  # ask the radio where it is tuned
            check.close()  # hang up
        except (OSError, RuntimeError, ValueError):  # no answer, or nonsense
            self.stop()  # do not leave a rig control running that cannot reach the radio
            raise RuntimeError(f"the radio did not answer on {port}. Check that the rig type and CAT port are right, that the radio is on, and that no other program (another rig control window, WSJT-X, JS8Call) is using {port}")  # say what to check
        return self.address  # ready, and proven to reach the radio

    def stop(self):  # stop rigctld
        """Stop the rigctld this object started, if any."""
        if self.process is not None and self.process.poll() is None:  # one is running
            self.process.terminate()  # ask it to stop
            try:  # give it a moment
                self.process.wait(timeout=3)  # wait for it to go
            except subprocess.TimeoutExpired:  # it did not
                self.process.kill()  # insist
        self.process = None  # nothing is running now
        if self.notes is not None:  # its messages are no longer needed
            self.notes.close()  # delete the scratch file
            self.notes = None  # none is open now


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

        Kestrel's fastest level spans about 800 to 2200 Hz of audio, centred on
        1500 Hz, so a filter about 3000 Hz wide passes every level with room to spare. A passband of 0 asks Hamlib for its usual width
        for the mode, which on some radios is a narrow data filter (600 Hz on
        an FTDX10) that removes the signal altogether.
        """
        self._set(f"M {mode} {int(passband_hz)}")  # mode and filter width

    def level(self, name):  # read one of the radio's levels or meters
        """Return a level by its Hamlib name: RFPOWER (power setting, 0 to 1 of full power), RFPOWER_METER_WATTS (power out, watts), ALC (0 to 1), SWR, STRENGTH (S-meter, dB relative to S9).

        Raises RuntimeError if the radio, or this version of Hamlib, does not offer it.
        """
        return float(self._get(f"l {name}"))  # ask and convert

    def ptt(self, on):  # key or unkey the transmitter
        """Switch the transmitter on (True) or off (False)."""
        self._set(f"T {1 if on else 0}")  # 1 = transmit, 0 = receive

    def close(self):  # finish
        """Close the connection to rigctld."""
        self.sock.close()  # release the socket
