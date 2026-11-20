KESTREL - getting started
=========================

Kestrel is an adaptive amateur HF digital mode for short messages (up to
200 characters). Two stations call, lock on to each other, and send
messages at the fastest speed the band allows.

You need an amateur radio licence to transmit, and must use Kestrel only
where your licence allows.


WHAT WAS INSTALLED
------------------
- Kestrel.exe, the control panel, with its own copy of Python and every
  library it uses. Nothing else needs to be installed.
- hamlib\bin\rigctld.exe, Hamlib's rig control program, which Kestrel
  starts by itself to tune and key your radio over its CAT cable.
- docs\ - the Kestrel specification and the licences.

Your own settings, contacts, stations-heard record and logbook are kept
for each Windows user in:
    %LOCALAPPDATA%\Kestrel
(paste that into the File Explorer address bar to open it). A new
installation starts empty.


FIRST START
-----------
1. Connect the radio to the computer with its USB cable and turn it on.
   Windows usually installs the radio's USB drivers by itself. If no
   COM port and no "USB Audio CODEC" sound device appear, install the
   USB driver from the radio maker's website (for many Yaesu and Icom
   radios this is the Silicon Labs CP210x "Virtual COM Port" driver).
2. Start Kestrel from the Start menu. The first time, it opens Settings.
3. Station tab: your callsign and grid locator (and, if you like, your
   name and a description of your rig, for the quick messages).
4. Radio tab: choose your radio type from the list (type part of the
   name to narrow it), its CAT serial port, speed and handshake as set in
   the radio's menu, and how the transmitter is keyed (CAT is usual).
5. Audio tab: the sound devices that lead from and to the radio (often
   called "USB Audio CODEC").
6. Save. Kestrel tunes the radio and starts listening.
7. Set the radio's USB audio output so the receive meter on the right of
   the panel sits in the green band (no red, no CLIP).
8. Help > Keyboard shortcuts (F1) lists every key; every function is
   also on the menus.

Radio settings that matter for most radios: upper sideband data mode
(DATA-U / PKTUSB), the receive filter wide (about 3 kHz) and, on some
Yaesu radios, the SSB "data shift" set to 1500 Hz.


HOW IT BEHAVES ON THE AIR
-------------------------
- Listen (F2) just listens. Nothing is transmitted unless you start it.
- Beacon (call anyone, F5) calls for a partner every few minutes until
  you press it again.
- A station that beacons, or calls you by name, is highlighted in the
  Stations heard list; select it and press Respond (Ctrl+Y) to answer.
- Available / Unavailable (Ctrl+U): while unavailable, a station calling
  you by name gets one short "not available" reply.


CHECKING THE INSTALLATION
-------------------------
Run this from a Command Prompt in the installation folder:
    Kestrel.exe --check
It checks the libraries, the sound system and rigctld, and writes the
result to kestrel_check.txt in %LOCALAPPDATA%\Kestrel.


A SECOND RADIO
--------------
Start menu > Kestrel > "Kestrel - second radio" opens a second panel
with its own settings, for a second radio on the same computer.


REMOVING KESTREL
----------------
Settings > Apps > Kestrel > Uninstall (or Start menu > Kestrel >
Uninstall Kestrel). Your own settings and logs in %LOCALAPPDATA%\Kestrel
are kept; delete that folder too if you no longer want them.


LICENCES
--------
Kestrel's program is under the Apache License 2.0 and its specification
under CC BY 4.0 (see docs\LICENSES.txt and docs\NOTICE.txt). Hamlib is
free software under the GNU GPL and LGPL; its licences and the address of
its source code are in hamlib\.
