"""Checking for a newer Kestrel release, and installing it when the operator says so (since 0.42).

The check asks GitHub's public releases list (no account or key is needed) for the newest release, and says
whether it is newer than the running program and whether it changes the signal (stations on different signal
versions mostly cannot hear each other). Nothing is downloaded or installed unless the operator presses
Install now; then the setup program is downloaded, checked against the SHA-256 published with it, and run
silently by a small PowerShell helper script once Kestrel has closed, and Kestrel is started again.

The SHA-256 check guards against a damaged download, not a forged one (the hash comes from the same place);
release signing, planned before the first production release, will add that. Until then every install is
approved by the operator, which is the same protection as downloading the setup program by hand.
"""
import hashlib  # SHA-256 of the downloaded setup program
import json  # the releases list is JSON
import os  # file paths
import re  # reading version numbers out of names
import subprocess  # starting the helper script
import tempfile  # where the setup program is downloaded
import time  # when the last check was
import urllib.request  # talking to GitHub

NOTICE_ADDRESS = re.compile(r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)")  # the project's public address, as the NOTICE file gives it
DAY_S = 24 * 3600  # one day, in seconds
TIMEOUT_S = 15  # how long to wait for GitHub before giving up quietly
CHECK_CHOICES = ("off", "startup", "daily")  # Settings > Updates > Check for updates
NOTIFY_CHOICES = ("all", "signal")  # Settings > Updates > Notify me about
INSTALL_CHOICES = ("notify", "ask")  # Settings > Updates > When an update is found (automatic installing waits for release signing)
SETUP_NAME = re.compile(r"^Kestrel-Setup-([0-9][0-9A-Za-z.]*)-[0-9a-f]{5,40}\.exe$")  # the setup program's file name: version and commit
SIGNAL_WORDS = re.compile(r"signal(?:\s+version)?\s+v?([0-9]+\.[0-9]+)", re.IGNORECASE)  # "signal 0.41" or "Signal version 0.41" in a release's title or notes


def notice_files():  # where the NOTICE file may be
    """Return the places the originator credit is kept: docs/NOTICE.txt beside the installed program, or NOTICE in the source folder."""
    from .paths import app_dir  # the program's folder, installed or not
    return [os.path.join(app_dir(), "docs", "NOTICE.txt"), os.path.join(app_dir(), "NOTICE")]  # installed, then the source folder


def repository(files=None):  # the public repository releases are published in
    """Return "owner/name" of the public repository, read from the NOTICE file's project address (kept there, with the
    originator credit, so the address is written in one place); None when no NOTICE file can be read."""
    for name in files or notice_files():  # each place it may be
        try:  # it may be missing
            with open(name, encoding="utf-8") as handle:  # the credit
                found = NOTICE_ADDRESS.search(handle.read())  # its project address
        except OSError:  # not there
            continue  # try the next place
        if found:  # an address
            return found.group(1).removesuffix(".git")  # owner and name
    return None  # unknown


def releases_url(repo=None):  # GitHub's list of the newest releases
    """Return the address of the releases list for `repo` (read from NOTICE when not given)."""
    return f"https://api.github.com/repos/{repo or repository()}/releases?per_page=20"  # drafts are not listed for anyone not signed in


def releases_page(repo=None):  # the page an operator can open in a browser
    """Return the releases page for `repo` (read from NOTICE when not given)."""
    return f"https://github.com/{repo or repository()}/releases"  # the public page


def version_key(text):  # turn "0.40R3", "v0.41" or "0.41" into something that sorts
    """Return a tuple that sorts versions in release order: (major, minor, revision); unreadable text sorts first."""
    found = re.match(r"^v?([0-9]+)\.([0-9]+)(?:R([0-9]+))?", (text or "").strip())  # major, minor and the optional revision letter R with its number
    if not found:  # not a version
        return (-1, -1, -1)  # sorts before every real version
    return (int(found.group(1)), int(found.group(2)), int(found.group(3) or 0))  # the parts, as numbers


def signal_of(release):  # the signal version a release says it carries
    """Return the signal version named in a release's title or notes ("signal 0.42"), or None."""
    for text in (release.get("name") or "", release.get("body") or ""):  # the title first, then the notes
        found = SIGNAL_WORDS.search(text)  # the first mention
        if found:  # there is one
            return found.group(1)  # the version, as text
    return None  # not said


def describe(release):  # the parts of one GitHub release that matter here
    """Return the release's version, signal version, setup program and hash file, or None if it has no setup program."""
    assets = {asset.get("name", ""): asset.get("browser_download_url", "") for asset in release.get("assets") or []}  # its files, by name
    setup = next((name for name in assets if SETUP_NAME.match(name)), None)  # the setup program
    if setup is None:  # a release without one cannot be installed
        return None  # skipped
    version = SETUP_NAME.match(setup).group(1)  # the version, from the file name (more reliable than the tag)
    return {"tag": release.get("tag_name", ""), "version": version, "signal": signal_of(release),  # what it is
            "test": bool(release.get("prerelease")), "page": release.get("html_url") or releases_page(),  # whether it is a test release, and its page
            "setup_name": setup, "setup_url": assets[setup], "sha_url": assets.get(setup + ".sha256", ""),  # the setup program and its published hash
            "notes": (release.get("body") or "").strip()}  # what changed


def pick(releases, current, current_signal, include_test=True, only_signal=False, skipped=""):  # the release to tell the operator about
    """From GitHub's release list, return the newest installable release newer than `current`, or None.

    include_test: count pre-releases. only_signal: only a release that changes the signal. skipped: a version the
    operator chose to skip (still shown if it changes the signal and the running one does not know it).
    """
    found = [describe(release) for release in releases if not release.get("draft")]  # every published release, described
    found = [info for info in found if info is not None and (include_test or not info["test"])]  # installable, and test releases only if wanted
    if not found:  # nothing to offer
        return None  # no news
    newest = max(found, key=lambda info: version_key(info["version"]))  # the newest
    if version_key(newest["version"]) <= version_key(current):  # not newer than what is running
        return None  # up to date
    newest["new_signal"] = bool(newest["signal"]) and version_key(newest["signal"]) > version_key(current_signal)  # whether it changes what is sent
    if only_signal and not newest["new_signal"]:  # the operator wants only signal changes
        return None  # not this one
    if skipped and newest["version"] == skipped and not newest["new_signal"]:  # skipped, and nothing on the air depends on it
        return None  # stay quiet
    return newest  # tell the operator


def due(setting, last_check, now, started_now):  # whether to check now
    """Return True when a check is due: "startup" checks once when Kestrel starts; "daily" at start and every 24 hours."""
    if setting == "startup":  # once per start
        return started_now  # only at the start
    if setting == "daily":  # at start, and once a day while running
        return started_now or now - float(last_check or 0) >= DAY_S  # at the start, or a day after the last check
    return False  # off


def fetch(url=None, timeout=TIMEOUT_S, opener=None):  # GitHub's release list
    """Return the list of releases from GitHub (raises OSError or ValueError on failure; the caller stays quiet about it)."""
    if url is None:  # the usual list
        repo = repository()  # from NOTICE
        if repo is None:  # no NOTICE file to read it from
            raise OSError("the NOTICE file, which gives the project's address, was not found")  # a quiet failure, like no internet
        url = releases_url(repo)  # the list
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Kestrel-update-check"})  # GitHub asks every caller to name itself
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as reply:  # ask
        return json.loads(reply.read().decode("utf-8"))  # the list


def check(current, current_signal, include_test=True, only_signal=False, skipped="", fetcher=fetch):  # one complete check
    """Return (release to offer or None, problem text or None). A failed check is a problem, never an exception."""
    try:  # GitHub may be unreachable
        return pick(fetcher(), current, current_signal, include_test, only_signal, skipped), None  # the answer
    except Exception as problem:  # no internet, GitHub down, an unexpected reply
        return None, str(problem) or problem.__class__.__name__  # say why, quietly


def sha256_of(path):  # the SHA-256 of a file
    """Return the file's SHA-256 as 64 lowercase hex digits."""
    digest = hashlib.sha256()  # the running hash
    with open(path, "rb") as handle:  # the file
        for block in iter(lambda: handle.read(1 << 20), b""):  # a megabyte at a time
            digest.update(block)  # add it
    return digest.hexdigest()  # the result


def download(info, folder=None, opener=None, progress=None):  # fetch and check the setup program
    """Download the release's setup program and check it against its published SHA-256. Return the file's path.

    Raises ValueError if there is no published hash or the file does not match it (the file is then deleted).
    `progress(done_bytes, total_bytes)` is called as it arrives.
    """
    if not info.get("sha_url"):  # no hash published: cannot tell a damaged file
        raise ValueError("the release has no SHA-256 file, so the download could not be checked")  # refuse
    opener = opener or urllib.request.urlopen  # the way to fetch
    folder = folder or os.path.join(tempfile.gettempdir(), "KestrelUpdate")  # where it goes
    os.makedirs(folder, exist_ok=True)  # make sure that exists
    request = urllib.request.Request(info["sha_url"], headers={"User-Agent": "Kestrel-update-check"})  # the hash file
    with opener(request, timeout=TIMEOUT_S) as reply:  # fetch it
        expected = reply.read().decode("ascii", "replace").split()[0].strip().lower()  # its first word is the hash
    path = os.path.join(folder, info["setup_name"])  # where the setup program goes
    request = urllib.request.Request(info["setup_url"], headers={"User-Agent": "Kestrel-update-check"})  # the setup program
    with opener(request, timeout=60) as reply, open(path, "wb") as handle:  # fetch it into the file
        total, done = int(reply.headers.get("Content-Length") or 0), 0  # its size, if said, and how much has come
        for block in iter(lambda: reply.read(1 << 16), b""):  # 64 KB at a time
            handle.write(block)  # keep it
            done += len(block)  # count it
            if progress is not None:  # someone is watching
                progress(done, total)  # say how far
    if sha256_of(path) != expected:  # not the file that was published
        os.remove(path)  # never keep a bad installer
        raise ValueError("the downloaded setup program does not match its published SHA-256; nothing was installed")  # refuse
    return path  # ready to run


def install_folder():  # where a per-user install puts Kestrel (since 0.42)
    """Return the folder the 0.42 and later setup program installs into: %LOCALAPPDATA%\\Programs\\Kestrel."""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Programs", "Kestrel")  # the usual place for programs installed for one user


HELPER_WAIT_S = 300  # how long the helper waits for Kestrel to close before giving up and installing nothing (since 0.44R1)


def _ps_quote(text):  # a PowerShell single-quoted string
    """Return `text` as a PowerShell single-quoted string literal (a quote inside is doubled, as PowerShell requires)."""
    return "'" + str(text).replace("'", "''") + "'"  # quoted, with any apostrophe in a path doubled


def helper_script(pid, setup, program, arguments=(), name="Kestrel", wait_s=HELPER_WAIT_S):  # the PowerShell script that installs once Kestrel has closed
    """Return the text of a PowerShell script that waits for process `pid` (named `name`) to end, runs `setup`
    silently, and starts `program` with `arguments`. Every line carries a comment saying what it does.

    Until 0.44R1 this was a batch file whose `tasklist | find` check hung for ever in the detached, console-less
    process Kestrel starts it in (and whose `timeout` cannot run there at all), so the update stopped at
    "waiting for Kestrel to close". PowerShell asks Windows about the process directly: no pipe, no console."""
    log = os.path.join(os.path.dirname(setup), "update_log.txt")  # what happened, in case anyone asks
    listed = ", ".join(_ps_quote(argument) for argument in arguments)  # the arguments, each quoted, for a PowerShell list
    return "\r\n".join([  # Windows line endings
        "# Kestrel update helper: waits for Kestrel to close, installs the new version, starts Kestrel again.",  # what this file is
        f"$log = {_ps_quote(log)}  # the record of what this helper did",  # where the log goes
        "function Say($text) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $text) }  # one dated line in the log",  # the logging helper
        f"Set-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' waiting for Kestrel (process {int(pid)}) to close')  # start a fresh log",  # first line
        f"$deadline = (Get-Date).AddSeconds({int(wait_s)})  # give up if Kestrel has not closed by then",  # the limit
        f"while ($true) {{  # look until Kestrel has gone",  # the waiting loop
        f"  $running = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue  # the process with Kestrel's number, if any",  # ask Windows
        f"  if (-not $running -or $running.ProcessName -ne {_ps_quote(name)}) {{ break }}  # gone (or the number now belongs to another program): carry on",  # done waiting
        "  if ((Get-Date) -gt $deadline) { Say 'Kestrel did not close; nothing was installed'; exit 1 }  # never install over a running Kestrel",  # the limit reached
        "  Start-Sleep -Milliseconds 500  # wait half a second and look again",  # pause
        "}  # end of the waiting loop",  # loop end
        "Start-Sleep -Seconds 1  # let Windows release Kestrel's files",  # a moment for file handles
        f"$setup = {_ps_quote(setup)}  # the downloaded and checked setup program",  # the installer
        "Say ('installing ' + $setup)  # log it",  # log
        "try {  # the setup program may fail to start",  # guard
        "  $run = Start-Process -FilePath $setup -ArgumentList '/S' -Wait -PassThru  # run it silently (NSIS's /S) and wait for it",  # install
        "  Say ('setup finished with code ' + $run.ExitCode)  # log the result",  # result
        "} catch {  # it could not be run",  # failure
        "  Say ('setup could not be run: ' + $_.Exception.Message)  # log why",  # reason
        "}  # end of the guard",  # guard end
        f"$program = {_ps_quote(program)}  # the installed Kestrel",  # the program
        f"$arguments = @({listed})  # the options Kestrel was running with (its profile)",  # same options
        "try {  # start Kestrel again, whatever version is now installed",  # guard
        "  if ($arguments.Count -gt 0) { Start-Process -FilePath $program -ArgumentList $arguments } else { Start-Process -FilePath $program }  # started, with the same options",  # restart
        "  Say 'Kestrel started again'  # log it",  # log
        "} catch {  # it could not be started",  # failure
        "  Say ('Kestrel could not be started: ' + $_.Exception.Message)  # log why",  # reason
        "}  # end of the guard",  # guard end
        "Remove-Item -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue  # this helper deletes itself when done",  # tidy up
        ""])  # a final line ending


def powershell_exe():  # Windows PowerShell, by its full path
    """Return the full path of Windows PowerShell 5.1, which every Windows 10 and 11 has, or plain powershell.exe."""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")  # the usual place
    return path if os.path.exists(path) else "powershell.exe"  # found, or let Windows search for it


def start_helper(pid, setup, program, arguments=(), name="Kestrel"):  # write the helper and start it, apart from Kestrel
    """Write the helper script beside the setup program and start it so it outlives Kestrel. Return its path."""
    path = os.path.join(os.path.dirname(setup), "kestrel_update.ps1")  # beside the download
    old = os.path.join(os.path.dirname(setup), "kestrel_update.cmd")  # the batch helper used until 0.44R1
    if os.path.exists(old):  # left behind by an update that hung
        try:  # it may be locked
            os.remove(old)  # tidied away
        except OSError:  # still in use
            pass  # harmless: it is never run again
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:  # UTF-8 with a byte-order mark, so Windows PowerShell reads any non-ASCII path right
        handle.write(helper_script(pid, setup, program, arguments, name))  # the script
    command = [powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", path]  # run the script once, hidden, without the user's profile
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)  # its own hidden console (not DETACHED_PROCESS: a process with no console cannot run console tools reliably), and Ctrl+C in Kestrel never reaches it
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)  # leave any job Kestrel was started in, so closing Kestrel cannot end the helper
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)  # real (empty) standard handles, none of Kestrel's
    try:  # first with the breakaway
        subprocess.Popen(command, creationflags=flags | breakaway, **quiet)  # started
    except OSError:  # Kestrel is in a job that does not allow breaking away
        subprocess.Popen(command, creationflags=flags, **quiet)  # started without it
    return path  # for the log


def now():  # the time, for the last-check record
    """Return the current time in seconds since 1970 (a function so tests can replace it)."""
    return time.time()  # the clock
