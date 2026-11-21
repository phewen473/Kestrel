# PyInstaller recipe for the self-contained Windows build of the Kestrel control panel.
# Run by build_windows.ps1 (see README.md in this folder); not normally run by hand.
# The result is a folder, dist/Kestrel, holding Kestrel.exe, its own Python and every library it uses.

import os  # file paths

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # the repository root (two levels above this file; SPECPATH is set by PyInstaller)

analysis = Analysis(  # find everything the panel imports
    [os.path.join(ROOT, "tools", "kestrel_panel.py")],  # the program to build
    pathex=[ROOT],  # so the link, live, modem and sim packages are found
    datas=[(os.path.join(ROOT, "VERSION"), ".")],  # the commit stamp, for Help > About
    hiddenimports=["pycaw.pycaw", "comtypes.stream", "serial.tools.list_ports", "tools.decode_wav", "tools.signal_report"],  # imported inside functions, so the search may not see them (the two tools serve File > Decode a recording and File > Signal log report)
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
