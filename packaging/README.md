# Packaging

How Kestrel is turned into something a person can install on a computer
that has nothing else on it.

## Windows (`windows/`)

The result is one setup program, `Kestrel-Setup-<version>-<commit>.exe`.
It installs Kestrel under Program Files for all users, with Start-menu
entries (Kestrel, Kestrel - second radio, Getting started, Uninstall), an
optional desktop shortcut, and an entry under Settings > Apps for
removing it. It needs 64-bit Windows 10 or 11 and nothing else: Kestrel
brings its own copy of Python and its libraries, and Hamlib's rig
control program, rigctld.

Each Windows user's settings, contacts, stations-heard record and
logbook go in `%LOCALAPPDATA%\Kestrel`, and a new installation starts
empty. (Run from the source folder, Kestrel still uses `local/`.)

### Building it

On a Windows computer with Git, 64-bit Python 3.12 and NSIS (and, for the compiled modem,
MSYS2's MinGW-w64 g++ and CMake):

    powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1

The setup program and its SHA-256 checksum are written to
`packaging\cache\`. The build:

1. exports the **committed** code (`git archive HEAD`) into a fresh work
   folder, `C:\KestrelBuild` (wiped first), so uncommitted changes,
   settings, logs and scratch files cannot get in, and the program holds
   no folder names of the build computer;
2. makes a clean Python environment with only the packages in
   `requirements.txt` and PyInstaller;
3. builds the compiled modem library `kestrel.dll` with MinGW-w64 g++ and CMake
   (`tools/build_native.py`; it looks in `C:\msys64\mingw64\bin` if they are not on the
   path, and builds without it, with a warning, if there is no compiler), then
   `Kestrel.exe` and its folder with PyInstaller (`kestrel.spec`), which packs the DLL
   into `modem\_native`;
4. adds Hamlib's official 64-bit Windows release (version and SHA-256
   pinned in the script), with its licences and the address of its
   source code (`hamlib\SOURCE.txt`), as the GPL asks;
5. adds the getting-started notes (`README-installed.txt`), the
   licences and the specification;
6. runs `privacy_scan.py` over every file, including the Python code
   packed inside `Kestrel.exe`, and stops if it finds the build
   computer's name, the builder's user name or profile folder, or any
   word in `packaging\cache\private_words.txt` (a list you keep yourself;
   Git ignores it). The originator credit is allowed only in NOTICE, the
   licence page, the specification and the About box;
7. runs `Kestrel.exe --check` with a throwaway profile, then makes the
   setup program with NSIS (`kestrel.nsi`).

### Where the finished setup program goes

The newest setup program is copied to `install\` at the top of the
project folder, on its own, ready to run on another computer. Only the
current one is kept there. Git ignores that folder: setup programs are
published as GitHub releases, not committed.

Builds themselves run in `C:\devel\build\Kestrel\v<version>\<commit>\`
(a clean copy of the repository at that commit in `repo\`, the work folder
in `work\`, the log in `build.log`), passed to the script with `-Work`.
Keeping every build under the development folder keeps the antivirus
exceptions to one place.

### Files

| File | What it is |
|---|---|
| `windows/build_windows.ps1` | The build, start to finish |
| `windows/kestrel.spec` | PyInstaller's recipe for `Kestrel.exe` |
| `windows/kestrel.nsi` | The setup program (NSIS) |
| `windows/kestrel.ico` | The program's icon |
| `windows/README-installed.txt` | Getting-started notes installed beside the program |
| `windows/privacy_scan.py` | The check that nothing private is inside |

### Notes

- The setup program is not signed with a code-signing certificate, so
  Windows SmartScreen warns on first run ("Windows protected your PC");
  choose More info > Run anyway. Signing needs a certificate bought
  from a certificate authority.
- `Kestrel.exe --check` (from a Command Prompt in the installation
  folder) reports whether the libraries, the sound system and rigctld
  are all present, into `%LOCALAPPDATA%\Kestrel\kestrel_check.txt`.
- The radio's own USB drivers (often Silicon Labs CP210x for the CAT
  port) come from Windows Update or the radio maker, not from Kestrel.
