; Kestrel setup program for Windows (NSIS script).
; Built by build_windows.ps1, which passes three values:
;   /DVERSION=0.25   the specification version the program follows
;   /DCOMMIT=abc1234 the source commit it was built from
;   /DSRC=<folder>   the finished program folder to install (dist\Kestrel)
;   /DOUT=<file>     the setup program to write
; It installs Kestrel for all users under Program Files, adds Start-menu entries
; (and a desktop shortcut if chosen), and registers an uninstaller under Apps.
; Each user's own settings, contacts and logs live in %LOCALAPPDATA%\Kestrel and are not touched.

Unicode true                                   ; Unicode text throughout
!include "MUI2.nsh"                            ; the standard modern installer pages
!include "x64.nsh"                             ; tests for 64-bit Windows

Name "Kestrel ${VERSION}"                      ; the name shown in the installer
OutFile "${OUT}"                               ; the setup program to write
InstallDir "$PROGRAMFILES64\Kestrel"           ; installed under Program Files
InstallDirRegKey HKLM "Software\Kestrel" "InstallDir"  ; a reinstall offers the folder used before
RequestExecutionLevel admin                    ; Program Files needs administrator rights
SetCompressor /SOLID lzma                      ; the smallest setup program
BrandingText "Kestrel ${VERSION} (${COMMIT})"  ; shown at the bottom of each page

!define MUI_ICON "kestrel.ico"                 ; the installer's own icon
!define MUI_UNICON "kestrel.ico"               ; and the uninstaller's
!define MUI_ABORTWARNING                       ; ask before abandoning the installation
!define MUI_WELCOMEPAGE_TEXT "This will install Kestrel ${VERSION}, an adaptive amateur HF digital mode for short messages.$\r$\n$\r$\nEverything Kestrel needs is included: its own copy of Python and its libraries, and Hamlib's rig control program (rigctld) for tuning and keying the radio. Nothing else needs to be installed first.$\r$\n$\r$\nYou need an amateur radio licence to transmit."  ; the first page
!define MUI_FINISHPAGE_RUN "$INSTDIR\Kestrel.exe"       ; offer to start Kestrel at the end
!define MUI_FINISHPAGE_RUN_TEXT "Start Kestrel now"     ; the words beside that tick box
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.txt" ; offer to show the getting-started notes
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show the getting-started notes"  ; the words beside that tick box

!insertmacro MUI_PAGE_WELCOME                  ; welcome
!insertmacro MUI_PAGE_LICENSE "${SRC}\docs\LICENSES.txt"  ; the licences (Kestrel, its specification, Hamlib)
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
FunctionEnd

Section "Kestrel (required)" SecMain           ; the program itself
  SectionIn RO                                 ; always installed
  SetShellVarContext all                       ; Start-menu entries for every user
  RMDir /r "$INSTDIR\_internal"                ; an older version's libraries go first, so none are left behind
  SetOutPath "$INSTDIR"                        ; copy into the installation folder
  File /r "${SRC}\*.*"                         ; everything in the finished program folder
  CreateDirectory "$SMPROGRAMS\Kestrel"        ; the Start-menu folder
  CreateShortcut "$SMPROGRAMS\Kestrel\Kestrel.lnk" "$INSTDIR\Kestrel.exe"  ; start the panel
  CreateShortcut "$SMPROGRAMS\Kestrel\Kestrel - second radio.lnk" "$INSTDIR\Kestrel.exe" "--profile second"  ; a second panel with its own settings, for a second radio
  CreateShortcut "$SMPROGRAMS\Kestrel\Getting started.lnk" "$INSTDIR\README.txt"  ; the notes
  CreateShortcut "$SMPROGRAMS\Kestrel\Uninstall Kestrel.lnk" "$INSTDIR\Uninstall.exe"  ; remove it
  WriteUninstaller "$INSTDIR\Uninstall.exe"    ; the uninstaller
  WriteRegStr HKLM "Software\Kestrel" "InstallDir" "$INSTDIR"  ; remember where it went
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayName" "Kestrel"  ; listed under Apps
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayVersion" "${VERSION} (${COMMIT})"  ; its version
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "Publisher" "Kestrel project"  ; who it is from
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "DisplayIcon" "$INSTDIR\Kestrel.exe"  ; its icon
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "UninstallString" '"$INSTDIR\Uninstall.exe"'  ; how to remove it
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "NoModify" 1  ; no "change" button
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel" "NoRepair" 1  ; no "repair" button
SectionEnd

Section "Desktop shortcut" SecDesktop          ; optional
  SetShellVarContext all                       ; for every user
  CreateShortcut "$DESKTOP\Kestrel.lnk" "$INSTDIR\Kestrel.exe"  ; the shortcut
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN    ; the descriptions shown on the components page
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "The Kestrel control panel, its own Python, and Hamlib's rig control program."  ; the program
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A Kestrel shortcut on the desktop."  ; the shortcut
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"                            ; removing Kestrel
  SetShellVarContext all                       ; the entries made for every user
  SetRegView 64                                ; the 64-bit registry
  RMDir /r "$INSTDIR"                          ; the program folder
  RMDir /r "$SMPROGRAMS\Kestrel"               ; the Start-menu folder
  Delete "$DESKTOP\Kestrel.lnk"                ; the desktop shortcut, if made
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Kestrel"  ; the Apps entry
  DeleteRegKey HKLM "Software\Kestrel"         ; the remembered folder
  MessageBox MB_ICONINFORMATION "Kestrel has been removed.$\r$\n$\r$\nYour own settings, contacts and logs were kept, in the Kestrel folder under %LOCALAPPDATA%. Delete that folder too if you no longer want them." /SD IDOK  ; say what was kept
SectionEnd
