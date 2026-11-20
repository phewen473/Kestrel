"""Where Kestrel keeps its files, whether run from the source folder or installed.

Run from the source folder (python tools/kestrel_panel.py), the operator's
own files go in the local/ folder beside the code, which Git ignores.

Installed by the Windows setup program, the program's folder (under
Program Files) cannot be written to, so the operator's files go in the
user's own profile instead: %LOCALAPPDATA%\\Kestrel on Windows, or
~/.local/share/kestrel elsewhere. Each user of the computer gets a fresh,
empty set of settings, contacts and logs.
"""

import os  # file paths
import sys  # how the program was started


def installed():  # is this the installed (bundled) program?
    """Return True when running from the self-contained build made by PyInstaller."""
    return bool(getattr(sys, "frozen", False))  # PyInstaller sets sys.frozen


def code_dir():  # where the program's own read-only files are
    """Return the folder holding the program's own files: the bundle when installed, else the repository root."""
    if installed():  # the self-contained build
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))  # PyInstaller's folder of bundled files
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # one level above live/


def app_dir():  # where the program itself was installed
    """Return the folder of the installed program (where Kestrel.exe and the hamlib folder are), or the repository root."""
    if installed():  # the self-contained build
        return os.path.dirname(sys.executable)  # beside Kestrel.exe
    return code_dir()  # the repository root


def data_dir():  # where the operator's own files go
    """Return (creating it if needed) the folder for settings, contacts, the heard log and the logbook."""
    if installed():  # installed: the user's own profile
        if sys.platform == "win32":  # Windows
            base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")  # the user's local application data
            folder = os.path.join(base, "Kestrel")  # Kestrel's own folder there
        else:  # Linux and others
            folder = os.path.join(os.path.expanduser("~"), ".local", "share", "kestrel")  # the usual place
    else:  # run from the source folder
        folder = os.path.join(code_dir(), "local")  # local/, which Git ignores
    os.makedirs(folder, exist_ok=True)  # make sure it exists
    return folder  # the folder
