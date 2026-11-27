# PyInstaller recipe for the self-contained Windows build of the Kestrel control panel.
# Run by build_windows.ps1 (see README.md in this folder); not normally run by hand.
# The result is a folder, dist/Kestrel, holding Kestrel.exe, its own Python and every library it uses.

import os  # file paths

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # the repository root (two levels above this file; SPECPATH is set by PyInstaller)

NATIVE = os.path.join(ROOT, "modem", "_native", "kestrel.dll")  # the compiled modem library, built by build_windows.ps1 before this runs
analysis = Analysis(  # find everything the panel imports
    [os.path.join(ROOT, "tools", "kestrel_panel.py")],  # the program to build
    pathex=[ROOT, os.path.join(ROOT, "tools")],  # so the link, live, modem and sim packages are found, and the panel's own modules beside it in tools (theme_editor, frame_strip; since 0.37)
    datas=[(os.path.join(ROOT, "VERSION"), "."), (os.path.join(ROOT, "live", "data", "sunspots.json"), os.path.join("live", "data")), (os.path.join(SPECPATH, "kestrel.ico"), ".")],  # the commit stamp, for Help > About; the shipped sunspot predictions, where live/sunspots.py looks for them (since 0.32); the icon, for the panel's title bar and taskbar button (Mast icon, since November 26, 2026)
    binaries=[(NATIVE, os.path.join("modem", "_native"))] if os.path.isfile(NATIVE) else [],  # the compiled modem library, where modem/native.py looks for it (left out if it was not built: the modem then runs in pure Python)
    hiddenimports=["pycaw.pycaw", "comtypes.stream", "serial.tools.list_ports", "tools.decode_wav", "tools.signal_report", "theme_editor", "frame_strip"],  # imported inside functions, so the search may not see them (the two tools serve File > Decode a recording and File > Signal log report); theme_editor and frame_strip named as well, as the panel's own modules beside it (a 0.37 build left them out and the program could not start; since 0.37)
    excludes=["matplotlib", "pytest", "IPython", "PyQt5", "PyQt6", "PySide6", "notebook"],  # used only by the study tools and tests, not by the panel
    noarchive=False,  # keep the Python files packed in one archive
)
pure = PYZ(analysis.pure)  # the packed Python files
program = EXE(  # Kestrel.exe
    pure,  # the packed Python files
    analysis.scripts,  # the start-up script
    [],  # nothing else inside the .exe itself (one-folder build)
    exclude_binaries=True,  # the libraries go beside it, in the folder
    name="Kestrel",  # Kestrel.exe
    icon=os.path.join(SPECPATH, "kestrel.ico"),  # the program's icon
    console=False,  # a window program: no black console window
    upx=False,  # no compression (it upsets some virus checkers)
)
COLLECT(  # gather the program and its libraries into one folder
    program,  # Kestrel.exe
    analysis.binaries,  # DLLs and compiled modules
    analysis.datas,  # data files
    upx=False,  # no compression
    name="Kestrel",  # the folder's name: dist/Kestrel
)
