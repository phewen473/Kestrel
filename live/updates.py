"""Checking for a newer Kestrel release, and installing it when the operator says so (since 0.42).

The check asks GitHub's public releases list (no account or key is needed) for the newest release, and says
whether it is newer than the running program and whether it changes the signal (stations on different signal
versions mostly cannot hear each other). Nothing is downloaded or installed unless the operator presses
Install now; then the setup program is downloaded, checked against the SHA-256 published with it, and run
silently by a small helper script once Kestrel has closed, and Kestrel is started again.

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

REPOSITORY = "phewen473/Kestrel"  # the public repository releases are published in
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20"  # the newest releases, drafts excluded for anyone not signed in
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"  # the page an operator can open in a browser
DAY_S = 24 * 3600  # one day, in seconds
TIMEOUT_S = 15  # how long to wait for GitHub before giving up quietly
CHECK_CHOICES = ("off", "startup", "daily")  # Settings > Updates > Check for updates
NOTIFY_CHOICES = ("all", "signal")  # Settings > Updates > Notify me about
INSTALL_CHOICES = ("notify", "ask")  # Settings > Updates > When an update is found (automatic installing waits for release signing)
SETUP_NAME = re.compile(r"^Kestrel-Setup-([0-9][0-9A-Za-z.]*)-[0-9a-f]{5,40}\.exe$")  # the setup program's file name: version and commit
SIGNAL_WORDS = re.compile(r"signal(?:\s+version)?\s+v?([0-9]+\.[0-9]+)", re.IGNORECASE)  # "signal 0.41" or "Signal version 0.41" in a release's title or notes


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
            "test": bool(release.get("prerelease")), "page": release.get("html_url") or RELEASES_PAGE,  # whether it is a test release, and its page
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


def fetch(url=RELEASES_URL, timeout=TIMEOUT_S, opener=None):  # GitHub's release list
    """Return the list of releases from GitHub (raises OSError or ValueError on failure; the caller stays quiet about it)."""
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


def helper_script(pid, setup, program, arguments=()):  # the batch file that installs once Kestrel has closed
    """Return the text of a Windows batch file that waits for process `pid` to end, runs `setup` silently,
    and starts `program` with `arguments`. Every line carries a REM saying what it does."""
    quoted = " ".join('"' + str(argument).replace('"', '') + '"' for argument in arguments)  # the arguments, each quoted
    log = os.path.join(os.path.dirname(setup), "update_log.txt")  # what happened, in case anyone asks
    return "\r\n".join([  # Windows line endings
        "@echo off",  # do not echo the commands
        "REM Kestrel update helper: waits for Kestrel to close, installs the new version, starts Kestrel again.",  # what this file is
        f'echo %date% %time% waiting for Kestrel (process {int(pid)}) to close > "{log}"',  # start the log
        ":wait",  # the waiting loop
        f'tasklist /FI "PID eq {int(pid)}" 2>nul | find "{int(pid)}" >nul',  # is Kestrel still running?
        "if not errorlevel 1 (",  # it is
        "  REM still running: wait a second and look again",  # explain the branch
        "  timeout /t 1 /nobreak >nul",  # wait a second
        "  goto wait",  # and look again
        ")",  # end of the branch
        f'echo %date% %time% installing "{setup}" >> "{log}"',  # log it
        f'"{setup}" /S',  # run the setup program silently (NSIS's /S)
        f'echo %date% %time% setup finished with code %errorlevel% >> "{log}"',  # log the result
        f'start "" "{program}" {quoted}'.rstrip(),  # start Kestrel again, with the same profile
        "REM this helper deletes itself when done",  # explain the last line
        '(goto) 2>nul & del "%~f0"',  # delete this batch file
        ""])  # a final line ending


def start_helper(pid, setup, program, arguments=()):  # write the helper and start it, detached
    """Write the helper batch file beside the setup program and start it so it outlives Kestrel. Return its path."""
    path = os.path.join(os.path.dirname(setup), "kestrel_update.cmd")  # beside the download
    with open(path, "w", encoding="ascii", errors="replace", newline="") as handle:  # plain text, Windows line endings already in place
        handle.write(helper_script(pid, setup, program, arguments))  # the script
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)  # on Windows: its own process, no window, not tied to Kestrel
    subprocess.Popen(["cmd.exe", "/c", path], creationflags=flags, close_fds=True)  # started
    return path  # for the log


def now():  # the time, for the last-check record
    """Return the current time in seconds since 1970 (a function so tests can replace it)."""
    return time.time()  # the clock
