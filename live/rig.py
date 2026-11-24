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

    The copy installed with Kestrel (hamlib/bin beside the program) is tried
    first, then the search path, then any `extra_folders`, then the bin
    folder of any WSJT-X installed in the usual place on Windows.
    """
    from live.paths import app_dir  # where the installed program is
    for name in RIGCTLD_NAMES:  # each name it goes by
        bundled = os.path.join(app_dir(), "hamlib", "bin", name)  # the copy installed with Kestrel
        if os.path.isfile(bundled):  # it is there
            return bundled  # use it: it is the version Kestrel was tested with
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
    return list_models_why(program)[0]  # the list alone


def list_models_why(program):  # ask rigctld which radios it knows, and say why if it will not tell
    """Return ([(model number, name)], reason): the radios the rigctld at `program` knows, and, when the list is empty, why in plain words."""
    if not program:  # no program to ask
        return [], "no rigctld program was found on this computer"  # say so
    if not os.path.isfile(program):  # the file is not there
        return [], f"the rigctld program is not where the settings say: {program}"  # say so
    reason = ""  # why the last try failed
    for wait in (30, 90):  # two tries: an antivirus program checking a new file can make the first run very slow
        try:  # the program may refuse to run
            done = subprocess.run([program, "-l"], stdin=subprocess.DEVNULL, capture_output=True, timeout=wait, cwd=os.path.dirname(program) or None, **HIDDEN)  # ask for the list (bytes, decoded below, so an odd character in a radio's name cannot stop it)
        except subprocess.TimeoutExpired:  # it did not finish in time
            reason = f"rigctld did not answer within {wait} seconds (an antivirus program may be holding it)"  # say so, and try again
            continue  # the second try waits longer
        except (OSError, subprocess.SubprocessError) as problem:  # it could not be run at all
            return [], f"rigctld could not be run ({problem}); an antivirus program may have blocked it"  # say so
        models = parse_models(done.stdout.decode("utf-8", "replace") + "\n" + done.stderr.decode("utf-8", "replace"))  # the list may come on either output
        if models:  # it answered
            return models, ""  # the list
        reason = f"rigctld ran but listed no radios (exit code {done.returncode})"  # say so
    return [], reason  # no list, and why


def models_for(saved):  # the radio list for the Settings window
    """Return (program, models, reason): the rigctld to use and its radio list. The saved program is tried first; if it gives no list, the one found on this computer (the copy installed with Kestrel first) is used instead."""
    found = find_rigctld()  # the one this computer has
    reason = ""  # why there is no list, if there is none
    for program in ([saved] if saved else []) + ([found] if found and found != saved else []):  # the saved one, then the found one
        models, reason = list_models_why(program)  # ask it
        if models:  # it answered
            return program, models, ""  # use it
    if not saved and not found:  # nothing to ask
        reason = "no rigctld program was found on this computer. The Kestrel setup program installs one; when running from the source code, install Hamlib (or WSJT-X) or choose rigctld with Browse"  # what to do
    return saved or found, [], reason  # no list


_JOB = None  # Windows: the job object every rigctld Kestrel starts is put in; it closes, and ends them, when Kestrel ends in any way, a crash included (since 0.38R2)


def _tie_to_kestrel(process):  # make a started rigctld end when Kestrel ends, however it ends (since 0.38R2)
    """On Windows, put `process` in a job object that kills its members when Kestrel's last handle to it closes (Windows closes it when Kestrel exits or crashes). Return True if tied."""
    global _JOB  # one job for the whole program
    if sys.platform != "win32":  # elsewhere the pid file below does the work
        return False  # not tied
    try:  # the Windows calls may be refused
        import ctypes  # Windows' own functions
        from ctypes import wintypes  # their types
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # the kernel's functions
        kernel.CreateJobObjectW.restype = wintypes.HANDLE  # returns a handle
        kernel.OpenProcess.restype = wintypes.HANDLE  # returns a handle
        if _JOB is None:  # the first rigctld: make the job
            job = kernel.CreateJobObjectW(None, None)  # an unnamed job
            if not job:  # refused
                return False  # not tied

            class Limits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION, as Windows lays it out
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),  # (continued: the basic limits)
                            ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),  # (continued)
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),  # (continued: end of the basic limits)
                            ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),  # (continued: the extended part)
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]  # (continued)

            limits = Limits()  # all zero
            limits.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: members are ended when the job's last handle closes
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):  # 9 = JobObjectExtendedLimitInformation
                kernel.CloseHandle(job)  # give it back
                return False  # not tied
            _JOB = job  # kept open for Kestrel's whole life (never closed by hand: Windows closes it when Kestrel goes)
        handle = kernel.OpenProcess(0x0101, False, process.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE on the new rigctld
        if not handle:  # refused
            return False  # not tied
        tied = bool(kernel.AssignProcessToJobObject(_JOB, handle))  # into the job
        kernel.CloseHandle(handle)  # the job holds it now
        return tied  # whether it worked
    except (OSError, AttributeError, ValueError):  # anything at all from the Windows calls
        return False  # not tied; the pid file still catches it next time


def _pid_file():  # where the running rigctld's process number is noted (since 0.38R2)
    """Return the path of the file that names the rigctld Kestrel last started (in the data folder)."""
    from live.paths import data_dir  # the operator's data folder
    return os.path.join(data_dir(), "_rigctld.pid")  # beside the settings


def _image_name(pid):  # the program name of a running process, or "" if there is none
    """Return the program file name of process `pid` (lower case), or "" if no such process is running."""
    if sys.platform == "win32":  # ask Windows
        try:  # tasklist may be missing or refuse
            listing = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10, **HIDDEN).stdout  # the process, if running
        except (OSError, subprocess.SubprocessError, ValueError):  # could not ask
            return ""  # treat as gone
        first = listing.strip().splitlines()[:1]  # its line, if any
        return first[0].split('","')[0].strip('"').lower() if first and first[0].startswith('"') else ""  # the image name, or nothing
    try:  # elsewhere, /proc or a signal 0
        os.kill(int(pid), 0)  # is it there?
    except (OSError, ValueError):  # no
        return ""  # gone
    try:  # its name, where /proc has it
        with open(f"/proc/{int(pid)}/comm", encoding="utf-8") as handle:  # Linux
            return handle.read().strip().lower()  # the name
    except OSError:  # no /proc
        return "rigctld"  # assume it is ours: the pid file named it


def end_leftover():  # a rigctld left running when Kestrel last ended badly (since 0.38R2)
    """End the rigctld that Kestrel started last time if it is still running (it would hold the radio's serial port). Return a sentence saying what was done, or ""."""
    path = _pid_file()  # the note
    try:  # it may not be there
        with open(path, encoding="utf-8") as handle:  # read it
            pid = int(handle.read().split()[0])  # the process number
    except (OSError, ValueError, IndexError):  # no note, or a damaged one
        return ""  # nothing to do
    said = ""  # nothing done yet
    name = _image_name(pid)  # what is running under that number now
    if name.startswith("rigctld"):  # still rigctld (a number reused by another program is left alone)
        try:  # end it
            if sys.platform == "win32":  # Windows
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10, **HIDDEN)  # forced
            else:  # elsewhere
                os.kill(pid, 9)  # forced
            time.sleep(0.5)  # let Windows give the serial port back
            said = f"ended a rig control program (rigctld, process {pid}) left running from an earlier session; it was holding the radio's port"  # what was done
        except (OSError, subprocess.SubprocessError):  # could not
            said = f"a rig control program (rigctld, process {pid}) from an earlier session is still running and could not be ended; end it in Task Manager"  # what to do
    try:  # the note is done with
        os.remove(path)  # gone
    except OSError:  # already gone
        pass  # fine
    return said  # for the Activity log


def end_kestrel_holders(port, keep=None):  # rigctlds started by any Kestrel for this serial port, left running (since 0.38R2)
    """On Windows, end every rigctld whose command line is the one Kestrel uses (listening on 127.0.0.1) for serial port `port`, except process `keep`.

    This catches one left by an older Kestrel that kept no note of its
    process number. A rigctld started by hand or by another program
    (which does not listen with Kestrel's "-T 127.0.0.1 -t" pattern) is left
    alone. Return a sentence saying what was done, or "".
    """
    if sys.platform != "win32" or not port:  # Windows only (elsewhere the pid file is enough)
        return ""  # nothing done
    query = "Get-CimInstance Win32_Process -Filter \"Name like 'rigctld%'\" | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"  # every rigctld and how it was started
    try:  # PowerShell may be slow or missing
        listing = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True, timeout=20, **HIDDEN).stdout  # the list
    except (OSError, subprocess.SubprocessError):  # could not ask
        return ""  # nothing done
    ended = []  # process numbers ended
    for line in listing.splitlines():  # each rigctld
        pid, _, command = line.partition("\t")  # its number and command line
        words = command.split()  # the command line, word by word
        try:  # the serial port it was given
            given = words[words.index("-r") + 1].strip('"')  # after -r
        except (ValueError, IndexError):  # none
            continue  # not one of Kestrel's
        if given.upper() != port.upper() or "-T" not in words or "127.0.0.1" not in words or not pid.strip().isdigit() or int(pid) == keep:  # another port, not Kestrel's pattern, or the one running now
            continue  # left alone
        subprocess.run(["taskkill", "/PID", pid.strip(), "/F"], capture_output=True, timeout=10, **HIDDEN)  # ended
        ended.append(pid.strip())  # counted
    if not ended:  # none
        return ""  # nothing done
    time.sleep(0.5)  # let Windows give the serial port back
    return f"ended {len(ended)} rig control program{'s' if len(ended) > 1 else ''} (rigctld, process {', '.join(ended)}) left running on {port} from an earlier session"  # what was done


class RigServer:  # a rigctld started and stopped by Kestrel
    """Runs rigctld for one radio, so the operator only has to choose the radio type and its serial port."""

    def __init__(self):  # nothing running yet
        self.process = None  # the rigctld process, when one is running
        self.config = None  # the settings it was started with
        self.address = ""  # where it is listening, as host:port
        self.notes = None  # a scratch file that collects rigctld's own messages
        self.news = []  # sentences for the Activity log (a leftover rigctld ended, since 0.38R2)

    def ensure(self, program, model, port, baud, handshake="none"):  # make sure rigctld is running with these settings
        """Start rigctld if needed and return its address. Raise RuntimeError with the reason if it will not start."""
        config = (program, int(model), port, int(baud), handshake)  # the settings asked for
        if self.process is not None and self.process.poll() is None and config == self.config:  # already running with the same settings
            return self.address  # use it as it is
        self.stop()  # stop any rigctld running with other settings
        for said in (end_leftover(), end_kestrel_holders(port)):  # one left from a crash would hold the serial port: the one noted last time, then any other started by a Kestrel for this port (since 0.38R2)
            if said:  # something was done
                self.news.append(said)  # tell the operator
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
        _tie_to_kestrel(self.process)  # it ends when Kestrel ends, even in a crash (since 0.38R2)
        try:  # note its number, so the next start can end it if it is somehow left running
            with open(_pid_file(), "w", encoding="utf-8") as handle:  # the note
                handle.write(f"{self.process.pid}\n")  # its process number
        except OSError:  # the folder may refuse
            pass  # the job object still ends it
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
            try:  # it is gone: so is the note of its number (since 0.38R2)
                os.remove(_pid_file())  # no leftover to look for next time
            except OSError:  # not there
                pass  # fine
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

        Kestrel's fastest level spans about 800 to 2200 Hz of audio, centered on
        1500 Hz, so a filter about 3000 Hz wide passes every level with room to spare. A passband of 0 asks Hamlib for its usual width
        for the mode, which on some radios is a narrow data filter (600 Hz on
        an FTDX10) that removes the signal altogether.
        """
        self._set(f"M {mode} {int(passband_hz)}")  # mode and filter width

    def set_data_mode(self, prefer="auto", passband_hz=3000):  # upper sideband, the radio's data mode if it has one
        """Put the radio in upper sideband for Kestrel and return the mode set: "PKTUSB" (the radio's data mode, USB-D) or "USB".

        `prefer` is "auto" (the data mode if the radio has one, plain USB if
        it refuses), "PKTUSB" or "USB". Kestrel never uses lower sideband.
        """
        if prefer != "USB":  # the data mode is wanted, or to be tried first
            try:  # not every radio has one
                self.set_mode("PKTUSB", passband_hz)  # upper sideband, data
                return "PKTUSB"  # the radio took it
            except RuntimeError:  # the radio (or Hamlib's driver for it) has no such mode
                if prefer == "PKTUSB":  # the operator insisted on it
                    raise  # say so
        self.set_mode("USB", passband_hz)  # plain upper sideband
        return "USB"  # what was set

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
