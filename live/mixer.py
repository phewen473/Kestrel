"""Windows' own volume setting for a sound device, so the panel can set the receive input level.

The level that matters for the receive audio is the one at the sound
card's input: if the radio's audio drives it into clipping, nothing done
to the samples afterwards can undo the damage. Windows keeps a recording
level for every input device (Sound settings > Recording > Properties >
Levels); this module reads and changes that setting for the device the
panel uses, through the pycaw package. Where pycaw is not installed, or
the device cannot be matched, the panel shows the meter only and says
where to set the level by hand.

Device names: the sound library lists a Windows device by a name that
may be cut short (31 characters for the oldest kind of device), so the
match is made on the start of the full name Windows uses.
"""

import sys  # which operating system this is


def _normalize(name):  # a device name reduced for comparing
    return " ".join(name.replace("(", " ").replace(")", " ").split()).lower()  # brackets and repeated spaces removed, lower case


class DeviceLevel:  # the Windows volume control of one sound device
    """get() and set() the device's level, 0.0 to 1.0, as in Windows' Sound settings."""

    def __init__(self, control, name):  # wrap a found control
        self.control = control  # Windows' volume interface for the device
        self.name = name  # the device's full name in Windows

    def get(self):  # the present level
        """Return the device's level, 0.0 to 1.0."""
        return float(self.control.GetMasterVolumeLevelScalar())  # as Windows has it

    def set(self, level):  # change the level
        """Set the device's level, 0.0 to 1.0."""
        self.control.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(level))), None)  # kept within range


def find(name, kind="input"):  # look for a device's volume control
    """Return a DeviceLevel for the input (or output) device called `name`, or None if it cannot be had on this computer."""
    if sys.platform != "win32" or not name:  # only Windows, and only a named device
        return None  # nothing to offer
    try:  # pycaw may be missing, or Windows may refuse
        from ctypes import POINTER, cast  # for turning Windows' answer into a usable interface
        from comtypes import CLSCTX_ALL  # how the interface is asked for
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # Windows' sound device interfaces
        flow = 1 if kind == "input" else 0  # eCapture for inputs, eRender for outputs
        enumerator = AudioUtilities.GetDeviceEnumerator()  # Windows' list of sound devices
        devices = enumerator.EnumAudioEndpoints(flow, 1)  # the working (active) ones of the kind wanted
        wanted = _normalize(name)  # the name to look for
        for index in range(devices.GetCount()):  # each device
            device = devices.Item(index)  # the device
            full = AudioUtilities.CreateDevice(device).FriendlyName or ""  # its full name in Windows
            if _normalize(full).startswith(wanted) or wanted.startswith(_normalize(full)):  # the same device, allowing for a shortened name
                control = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)  # its volume control
                return DeviceLevel(cast(control, POINTER(IAudioEndpointVolume)), full)  # ready to use
    except Exception:  # pycaw is missing or Windows said no
        return None  # the meter still works; the level is set by hand
    return None  # no device of that name
