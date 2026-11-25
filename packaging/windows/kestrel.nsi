; Kestrel setup program for Windows (NSIS script).
; Built by build_windows.ps1, which passes three values:
;   /DVERSION=0.25   the specification version the program follows
;   /DCOMMIT=abc1234 the source commit it was built from
;   /DSRC=<folder>   the finished program folder to install (dist\Kestrel)
;   /DOUT=<file>     the setup program to write
; It installs Kestrel for the current user under %LOCALAPPDATA%\Programs\Kestrel (since 0.42; no administrator
; rights needed, so Kestrel can update itself), adds Start-menu entries (and a desktop shortcut if chosen), and
; registers an uninstaller under Apps. An older all-users copy in Program Files is offered for removal.
; Each user's own settings, contacts and logs live in %LOCALAPPDATA%\Kestrel and are not touched.

Unicode true                                   ; Unicode text throughout
!include "MUI2.nsh"                            ; the standard modern installer pages
!include "x64.nsh"                             ; tests for 64-bit Windows

Name "Kestrel ${VERSION}"                      ; the name shown in the installer
OutFile "${OUT}"                               ; the setup program to write
InstallDir "$LOCALAPPDATA\Programs\Kestrel"   ; installed for this user (since 0.42; was Program Files)
InstallDirRegKey HKCU "Software\Kestrel" "InstallDir"  ; a reinstall offers the folder used before
RequestExecutionLevel user                     ; no administrator rights: a per-user install (since 0.42)
SetCompressor /SOLID lzma                      ; the smallest setup program
BrandingText "Kestrel ${VERSION} (${COMMIT})"  ; shown at the bottom of each page

!define MUI_ICON "kestrel.ico"                 ; the installer's own icon
!define MUI_UNICON "kestrel.ico"               ; and the uninstaller's
!define MUI_ABORTWARNING                       ; ask before abandoning the installation
!define MUI_WELCOMEPAGE_TEXT "This will install Kestrel ${VERSION}, an adaptive amateur HF digital mode for short messages.$\r$\n$\r$\nEverything Kestrel needs is included: its own copy of Python and its libraries, and Hamlib's rig control program (rigctld) for tuning and keying the radio. Nothing else needs to be installed first.$\r$\n$\r$\nYou need an amateur radio license to transmit."  ; the first page
!define MUI_FINISHPAGE_RUN "$INSTDIR\Kestrel.exe"       ; offer to start Kestrel at the end
!define MUI_FINISHPAGE_RUN_TEXT "Start Kestrel now"     ; the words beside that tick box
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.txt" ; offer to show the getting-started notes
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show the getting-started notes"  ; the words beside that tick box

!insertmacro MUI_PAGE_WELCOME                  ; welcome
!insertmacro MUI_PAGE_LICENSE "${SRC}\docs\LICENSES.txt"  ; the licenses (Kestrel, its specification, Hamlib)
!insertmacro MUI_PAGE_COMPONENTS               ; choose the optional desktop shortcut
!insertmacro MUI_PAGE_DIRECTORY                ; where to install
!insertmacro MUI_PAGE_INSTFILES                ; the copying
!insertmacro MUI_PAGE_FINISH                   ; done
!insertmacro MUI_UNPAGE_CONFIRM                ; uninstall: are you sure?
!insertmacro MUI_UNPAGE_INSTFILES              ; uninstall: the removing
!insertmacro MUI_LANGUAGE "English"            ; the installer's language

Function .onInit                               ; before anything is shown
  ${IfNot} ${RunningX64}                       ; 32-bit Windows
    MessageBox MB_ICONSTOP "Kestrel needs 64-bit Windows 10 or 11."  ; cannot run there
    Abort                                      ; stop
  ${EndIf}
  SetRegView 64                                ; use the 64-bit registry
  ReadRegStr $1 HKLM "Software\Kestrel" "InstallDir"  ; an all-users copy installed by 0.41 or earlier, if any
  ${If} $1 != ""                               ; there is one
  ${AndIf} ${FileExists} "$1\Uninstall.exe"     ; and its uninstaller is still there
    IfSilent oldkept                           ; a silent install never asks (an update from 0.42 on finds none)
    MessageBox MB_YESNO|MB_ICONQUESTION "An older Kestrel is installed for all users in$\r$\n$1$\r$\n$\r$\nKestrel now installs for you alone, so it can update itself. Remove the old copy now? Windows will ask for permission. Your settings, contacts and logs are kept either way." IDNO oldkept  ; ask
    ExecShellWait "runas" "$1\Uninstall.exe" "/S _?=$1"  ; run its uninstaller with administrator rights, silently, and wait
    RMDir /r "$1"                               ; its folder (and the uninstaller, which _?= leaves behind), if Windows allows
    oldkept:                                   ; carry on either way
  ${EndIf}                                     ; done with the old copy
FunctionEnd

Section "Kestrel (required)" SecMain           ; the program itself
  SectionIn RO                                 ; always installed
  SetShellVarContext current                   ; Start-menu entries for this user
  RMDir /r "$INSTDIR\_internal"                ; an older version's libraries go first, so none are left behind
  SetOutPath "$INSTDIR"                        ; copy into the installation folder
  File /r "${SRC}\*.*"                         ; everything in the finished program folder
  CreateDirectory "$SMPROGRAMS\Kestrel"        ; the Start-menu folder
  CreateShortcut "$SMPROGRAMS\Kestrel\Kestrel.lnk" "$INSTDIR\Kestrel.exe"  ; start the panel
  CreateShortcut "$SMPROGRAMS\Kestrel\Kestrel - second radio.lnk" "$INSTDIR\Kestrel.exe" "--profile second"  ; a second panel with its own settings, for a second radio
  CreateShortcut "$SMPROGRAMS\Kestrel\Getting started.lnk" "$INSTDIR\README.txt"  ; the notes
  CreateShortcut "$SMPROGRAMS\Kestrel\Uninstall Kestrel.lnk" "$INSTDIR\Uninstall.exe"  ; remove it
  WriteUninstaller "$INSTDIR\Uninstall.exe"    ; the uninstaller
  WriteRegStr HKCU "Software\Kestrel" "InstallDir" "$INSTDIR"  ; remember where it went
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayName" "Kestrel"  ; listed under Apps
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayVersion" "${VERSION} (${COMMIT})"  ; its version
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "Publisher" "Kestrel project"  ; who it is from
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayIcon" "$INSTDIR\Kestrel.exe"  ; its icon
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "UninstallString" '"$INSTDIR\Uninstall.exe"'  ; how to remove it
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "NoModify" 1  ; no "change" button
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "NoRepair" 1  ; no "repair" button
SectionEnd

Section "Desktop shortcut" SecDesktop          ; optional
  SetShellVarContext current                   ; for this user
  CreateShortcut "$DESKTOP\Kestrel.lnk" "$INSTDIR\Kestrel.exe"  ; the shortcut
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN    ; the descriptions shown on the components page
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "The Kestrel control panel, its own Python, and Hamlib's rig control program."  ; the program
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A Kestrel shortcut on the desktop."  ; the shortcut
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"                            ; removing Kestrel
  SetShellVarContext current                   ; the entries made for this user
  SetRegView 64                                ; the 64-bit registry
  RMDir /r "$INSTDIR"                          ; the program folder
  RMDir /r "$SMPROGRAMS\Kestrel"               ; the Start-menu folder
  Delete "$DESKTOP\Kestrel.lnk"                ; the desktop shortcut, if made
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel"  ; the Apps entry
  DeleteRegKey HKCU "Software\Kestrel"         ; the remembered folder
  MessageBox MB_ICONINFORMATION "Kestrel has been removed.$\r$\n$\r$\nYour own settings, contacts and logs were kept, in the Kestrel folder under %LOCALAPPDATA%. Delete that folder too if you no longer want them." /SD IDOK  ; say what was kept
SectionEnd
