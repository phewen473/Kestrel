# Build the Kestrel setup program for Windows.
#
# Run from PowerShell in the repository:   powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1
# Needs: Git, Python 3.12 (64-bit), NSIS (makensis), and for the compiled modem MinGW-w64 g++ and CMake, on the build computer. The finished setup program needs none of them.
#
# What it does:
#   1. Exports the committed code (git archive HEAD) into a fresh, neutral work folder, so nothing that is not
#      in the repository (settings, logs, contacts, scratch files) can get into the installer, and no folder
#      names of the build computer are recorded in the program.
#   2. Makes a clean Python environment there with only the packages Kestrel needs, plus PyInstaller.
#   3. Builds the compiled modem library (kestrel.dll, with MinGW-w64 g++ and CMake if present), then Kestrel.exe
#      and its folder with PyInstaller (kestrel.spec).
#   4. Adds Hamlib's official Windows rigctld (downloaded once, checked against its published SHA-256), with its licences.
#   5. Adds the getting-started notes, the licences and the specification.
#   6. Scans every file, including the packed Python code, for anything naming the build computer or the
#      words in packaging\cache\private_words.txt (git-ignored); stops if anything is found.
#   7. Runs Kestrel.exe --check, then makes the setup program with NSIS.

param(
    [string]$Work = "C:\KestrelBuild",                                   # the neutral work folder (wiped at the start)
    [string]$Python = "",                                                # the Python to build with (found automatically if blank)
    [string]$MakeNsis = ""                                               # the NSIS compiler (found automatically if blank)
)
$ErrorActionPreference = "Stop"                                          # stop at the first error
$HamlibVersion = "4.7.2"                                                 # the Hamlib release bundled
$HamlibSha256 = "8553bc6c5c6032e8debf99c017e98f58fed7e07e7c25d04815dc3e8bbe3304c7"  # its published SHA-256 (from SHA256SUM-w64-4.7.2)
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path            # the repository root
$Cache = Join-Path $Repo "packaging\cache"                               # downloads kept between builds (git-ignored)
New-Item -ItemType Directory -Force $Cache | Out-Null                    # make sure it exists

if (-not $Python) {                                                      # no Python given: find one
    $launcher = Get-Command py -ErrorAction SilentlyContinue             # the Python launcher
    if ($launcher) { $Python = (& py -3.12 -c "import sys; print(sys.executable)").Trim() }  # Python 3.12 through the launcher
    if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }            # else whatever "python" is
}
if (-not $MakeNsis) {                                                    # no NSIS compiler given: find one
    foreach ($candidate in @("$env:ProgramFiles\NSIS\makensis.exe", "${env:ProgramFiles(x86)}\NSIS\makensis.exe", "C:\msys64\mingw64\bin\makensis.exe")) {  # the usual places
        if (Test-Path $candidate) { $MakeNsis = $candidate; break }      # the first one present
    }
    if (-not $MakeNsis) { throw "NSIS (makensis.exe) was not found; install NSIS or pass -MakeNsis" }  # cannot go on
}

Push-Location $Repo                                                      # work from the repository
$Commit = (git rev-parse --short HEAD).Trim()                            # the commit being built
$Dirty = git status --porcelain --untracked-files=no                     # uncommitted changes to tracked files
if ($Dirty) { Write-Warning "There are uncommitted changes; the installer is built from the last commit ($Commit), without them." }  # the build uses committed code only
$SpecVersion = (Select-String -Path "modem\params.py" -Pattern '^SPEC_VERSION = "([0-9A-Za-z.]+)"').Matches[0].Groups[1].Value  # the specification version (a release letter may follow, as in 0.31R1)
Write-Host "Building Kestrel $SpecVersion from commit $Commit"            # say what is being built

if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }               # start from nothing
New-Item -ItemType Directory -Force $Work | Out-Null                     # the work folder
$Src = Join-Path $Work "src"                                             # the exported code
git archive --format=zip -o (Join-Path $Work "src.zip") HEAD             # export the committed code (VERSION gets the commit stamp)
New-Item -ItemType Directory -Force $Src | Out-Null                      # the folder to unpack into
tar -xf (Join-Path $Work "src.zip") -C $Src                              # unpack it with Windows' own tar (Expand-Archive gave up on a file an antivirus program was still scanning)
if ($LASTEXITCODE -ne 0) { throw "could not unpack the exported code" }  # cannot go on
Pop-Location                                                             # back to where we were

Write-Host "Making a clean Python environment"                            # step 2
& $Python -m venv (Join-Path $Work "venv")                               # a fresh environment
$VPy = Join-Path $Work "venv\Scripts\python.exe"                         # its Python
& $VPy -m pip install --quiet --upgrade pip                              # an up-to-date installer
& $VPy -m pip install --quiet -r (Join-Path $Src "requirements.txt") pyinstaller  # Kestrel's packages and PyInstaller
if ($LASTEXITCODE -ne 0) { throw "pip could not install the packages" }  # cannot go on

Write-Host "Building the compiled modem library"                         # step 3a
$Mingw = "C:\msys64\mingw64\bin"                                         # the usual MinGW-w64 folder (MSYS2)
if ((Test-Path (Join-Path $Mingw "g++.exe")) -and -not (Get-Command g++ -ErrorAction SilentlyContinue)) { $env:Path = "$Mingw;$env:Path" }  # put MinGW (g++ and CMake) on the path if it is not already
if ((Get-Command cmake -ErrorAction SilentlyContinue) -and (Get-Command g++ -ErrorAction SilentlyContinue)) {  # the tools are there
    & $VPy (Join-Path $Src "tools\build_native.py")                       # build kestrel.dll into modem\_native
    if ($LASTEXITCODE -ne 0) { throw "the compiled modem library did not build" }  # a broken build should be fixed, not shipped without
} else {                                                                 # no compiler
    Write-Warning "CMake or g++ not found: building without the compiled modem library (Kestrel will run in pure Python, more slowly)"  # say so and go on
}

Write-Host "Building Kestrel.exe"                                        # step 3
Push-Location $Src                                                       # PyInstaller works relative to the code
& $VPy -m PyInstaller --noconfirm --clean --distpath (Join-Path $Work "dist") --workpath (Join-Path $Work "build") "packaging\windows\kestrel.spec"  # build it
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "PyInstaller failed" }    # cannot go on
Pop-Location                                                             # back
$App = Join-Path $Work "dist\Kestrel"                                    # the finished program folder

Write-Host "Adding Hamlib $HamlibVersion"                                # step 4
$Zip = Join-Path $Cache "hamlib-w64-$HamlibVersion.zip"                  # the download, kept between builds
if (-not (Test-Path $Zip)) { Invoke-WebRequest "https://github.com/Hamlib/Hamlib/releases/download/$HamlibVersion/hamlib-w64-$HamlibVersion.zip" -OutFile $Zip }  # fetch it once
if ((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower() -ne $HamlibSha256) { throw "the Hamlib download does not match its published checksum" }  # refuse a damaged or altered file
$HamlibTmp = Join-Path $Work "hamlib"                                    # where to unpack it
New-Item -ItemType Directory -Force $HamlibTmp | Out-Null                # the folder to unpack into
tar -xf $Zip -C $HamlibTmp                                               # unpack it with Windows' own tar
if ($LASTEXITCODE -ne 0) { throw "could not unpack Hamlib" }             # cannot go on
$HamlibTop = Join-Path $HamlibTmp "hamlib-w64-$HamlibVersion"            # its top folder
New-Item -ItemType Directory -Force (Join-Path $App "hamlib\bin") | Out-Null  # hamlib\bin beside Kestrel.exe
Copy-Item (Join-Path $HamlibTop "bin\rigctld.exe"), (Join-Path $HamlibTop "bin\rigctl.exe") (Join-Path $App "hamlib\bin")  # the rig control programs
Copy-Item (Join-Path $HamlibTop "bin\*.dll") (Join-Path $App "hamlib\bin")  # and the libraries they need
Copy-Item (Join-Path $HamlibTop "COPYING.txt"), (Join-Path $HamlibTop "COPYING.LIB.txt"), (Join-Path $HamlibTop "LICENSE.txt"), (Join-Path $HamlibTop "README.w64-bin.txt") (Join-Path $App "hamlib")  # its licences and notes
@"
Hamlib $HamlibVersion (64-bit Windows build, unchanged), from the Hamlib project.
Hamlib is free software: the library under the GNU LGPL, the programs under the GNU GPL (see COPYING.txt and COPYING.LIB.txt).
Its complete source code is at:
  https://github.com/Hamlib/Hamlib/releases/download/$HamlibVersion/hamlib-$HamlibVersion.tar.gz
  https://github.com/Hamlib/Hamlib
Kestrel runs rigctld.exe as a separate program; Kestrel itself is under the Apache License 2.0.
"@ | Set-Content -Encoding utf8 (Join-Path $App "hamlib\SOURCE.txt")     # where Hamlib's source is, as its licence asks

Write-Host "Adding the ITU-R P.533 propagation engine"                    # step 4b (since 0.32)
$ItuCache = Join-Path $Cache "ITU-R-HF"                                  # the ITU's source, kept between builds (fetched once, at the pinned commit)
& $VPy (Join-Path $Src "tools\build_prop.py") --source $ItuCache --target (Join-Path $App "prop")  # build ITURHFProp, P533 and P372 with MinGW gcc, and copy them with their data into prop\ beside Kestrel.exe
if ($LASTEXITCODE -ne 0) { throw "the ITU-R P.533 engine did not build" }  # a broken build should be fixed, not shipped without

Write-Host "Adding the notes, licences and specification"                # step 5
New-Item -ItemType Directory -Force (Join-Path $App "docs") | Out-Null   # docs beside Kestrel.exe
Copy-Item (Join-Path $Src "packaging\windows\README-installed.txt") (Join-Path $App "README.txt")  # the getting-started notes
Copy-Item (Join-Path $Src "NOTICE") (Join-Path $App "docs\NOTICE.txt")  # the originator credit
Copy-Item (Join-Path $Src "LICENSE") (Join-Path $App "docs\LICENSE-Apache-2.0.txt")  # the program's licence
Copy-Item (Join-Path $Src "docs\LICENSE-CC-BY-4.0.txt") (Join-Path $App "docs\LICENSE-CC-BY-4.0.txt")  # the specification's licence
Copy-Item (Join-Path $Src "cpp\third_party\pocketfft\LICENSE.md") (Join-Path $App "docs\LICENSE-pocketfft.txt")  # the FFT inside the compiled modem library (BSD licence: its notice must travel with it)
Copy-Item (Join-Path $Src "docs\spec\kestrel-spec.md"), (Join-Path $Src "docs\spec\CHANGELOG.md") (Join-Path $App "docs")  # the specification and its history
$Licences = @((Get-Content -Raw (Join-Path $Src "NOTICE")), "`r`n==== Kestrel program: Apache License 2.0 ====`r`n", (Get-Content -Raw (Join-Path $Src "LICENSE")), "`r`n==== Kestrel specification: CC BY 4.0 (see docs\LICENSE-CC-BY-4.0.txt) ====`r`n", "`r`n==== Hamlib: GNU GPL / LGPL (see hamlib\COPYING.txt, hamlib\COPYING.LIB.txt and hamlib\SOURCE.txt) ====`r`n", "`r`n==== ITU-R P.533 propagation engine (ITURHFProp, P533, P372, ITU-R Study Group 3) ====`r`n", (Get-Content -Raw (Join-Path $App "prop\SOURCE.txt")), "`r`n==== Sunspot predictions: NOAA Space Weather Prediction Center (United States government work, public domain) ====`r`n") -join "`r`n"  # one text for the installer's licence page
$Licences | Set-Content -Encoding utf8 (Join-Path $App "docs\LICENSES.txt")  # written beside the others

Write-Host "Privacy scan"                                                # step 6
$Credit = (Select-String -Path (Join-Path $Src "NOTICE") -Pattern '\(([A-Z]{1,2}[0-9][A-Z]{1,4})\)').Matches[0].Groups[1].Value  # the originator's callsign, as the NOTICE file gives it (a callsign has a digit; this skips "(KES)")
$WordList = Join-Path $Cache "private_words.txt"                         # the private word list (git-ignored; optional)
& $VPy (Join-Path $Src "packaging\windows\privacy_scan.py") $App --words $WordList --allow "$Credit=NOTICE" --allow "$Credit=LICENSES" --allow "$Credit=kestrel-spec" --credit-files "NOTICE,LICENSES,kestrel-spec"  # the credit may appear only where the licence needs it: NOTICE, the licence page, and the specification's copyright line (and the About box, inside the program)
if ($LASTEXITCODE -ne 0) { throw "the privacy scan found something; see above" }  # never publish that

Write-Host "Checking the program starts"                                 # step 7
$env:LOCALAPPDATA_SAVED = $env:LOCALAPPDATA                             # remember the real profile folder
$env:LOCALAPPDATA = Join-Path $Work "checkprofile"                       # a throwaway profile, so the check leaves nothing in the builder's own
Start-Process -FilePath (Join-Path $App "Kestrel.exe") -ArgumentList "--check" -Wait  # the installation check
$env:LOCALAPPDATA = $env:LOCALAPPDATA_SAVED                             # back to the real one
Get-Content (Join-Path $Work "checkprofile\Kestrel\kestrel_check.txt")  # show its report
$Out = Join-Path $Repo "packaging\cache\Kestrel-Setup-$SpecVersion-$Commit.exe"  # the setup program
Push-Location (Join-Path $Src "packaging\windows")                       # NSIS finds the icon beside the script
& $MakeNsis /V2 "/DVERSION=$SpecVersion" "/DCOMMIT=$Commit" "/DSRC=$App" "/DOUT=$Out" "kestrel.nsi"  # make it
$NsisResult = $LASTEXITCODE                                              # how it went
Pop-Location                                                             # back
if ($NsisResult -ne 0) { throw "NSIS failed" }                           # cannot go on
$Hash = (Get-FileHash $Out -Algorithm SHA256).Hash.ToLower()             # its checksum, to publish beside it
"$Hash  $(Split-Path $Out -Leaf)" | Set-Content -Encoding ascii "$Out.sha256"  # written beside it
Write-Host "Done: $Out"                                                  # where it is
Write-Host "SHA-256: $Hash"                                              # and its checksum
