"""Keying the transmitter (push-to-talk).

Five ways are offered:
    none  nothing is done; use the radio's VOX, or a cable test with no radio
    rig   ask Hamlib's rigctld to key the radio (see rig.py); works with any radio Hamlib supports
    cat   send the radio a CAT command over its serial port (Yaesu: "TX1;" to transmit, "TX0;" to receive)
    rts   raise the serial port's RTS line while transmitting
    dtr   raise the serial port's DTR line while transmitting
"""

import time  # short pauses around keying

KEY_LEAD_S = 0.2  # pause after keying, before audio starts, so the transmitter is fully on
KEY_TAIL_S = 0.1  # pause after audio ends, before unkeying, so the last tone is not clipped


class Ptt:  # the transmit switch
    """Keys and unkeys the transmitter by the chosen method."""

    def __init__(self, method="none", port=None, baud=38400, key_command="TX1;", unkey_command="TX0;", rig=None):  # set up
        self.method = method  # none, rig, cat, rts or dtr
        self.rig = rig  # the rigctld connection, for the "rig" method
        self.key_command = key_command.encode("ascii")  # CAT command that starts transmitting
        self.unkey_command = unkey_command.encode("ascii")  # CAT command that returns to receive
        self.serial = None  # the serial port, when one is used
        if method == "rig" and rig is None:  # keying through rigctld needs a connection to it
            raise ValueError("--ptt rig needs --rig host:port")  # say so
        if method not in ("none", "rig"):  # a serial port is needed
            if not port:  # none was given
                raise ValueError("this PTT method needs a serial port")  # say so
            import serial  # the pyserial package (imported only when needed)
            self.serial = serial.Serial(port, baud, timeout=0.5, rtscts=False, dsrdtr=False)  # open the port
            self.serial.rts = False  # make sure the transmitter starts unkeyed...
            self.serial.dtr = False  # ...whichever line is used

    def key(self):  # start transmitting
        """Key the transmitter and wait for it to come up."""
        if self.method == "rig":  # through rigctld
            self.rig.ptt(True)  # transmit
        elif self.method == "cat":  # by CAT command
            self.serial.write(self.key_command)  # send it
        elif self.method == "rts":  # by the RTS line
            self.serial.rts = True  # raise it
        elif self.method == "dtr":  # by the DTR line
            self.serial.dtr = True  # raise it
        time.sleep(KEY_LEAD_S)  # let the transmitter come up

    def unkey(self):  # stop transmitting
        """Let the last tone finish, then unkey the transmitter."""
        time.sleep(KEY_TAIL_S)  # let the audio finish
        if self.method == "rig":  # through rigctld
            self.rig.ptt(False)  # back to receive
        elif self.method == "cat":  # by CAT command
            self.serial.write(self.unkey_command)  # send it
        elif self.method == "rts":  # by the RTS line
            self.serial.rts = False  # lower it
        elif self.method == "dtr":  # by the DTR line
            self.serial.dtr = False  # lower it

    def close(self):  # finish
        """Make sure the transmitter is unkeyed and close the serial port."""
        if self.method == "rig":  # keyed through rigctld
            self.unkey()  # never leave the transmitter keyed
        if self.serial is not None:  # a port is open
            self.unkey()  # never leave the transmitter keyed
            self.serial.close()  # release the port
