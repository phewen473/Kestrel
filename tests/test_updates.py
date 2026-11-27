"""Tests for the update check (live/updates.py, since 0.42)."""
import hashlib  # to make a matching hash
import io  # fake replies
import os  # file checks
import subprocess  # the stand-in Kestrel for the end-to-end helper test (since 0.44R1)
import sys  # which Python runs the tests, and whether this is Windows
import time  # waiting for the helper

import pytest  # the test runner

from live import updates  # the module tested


def release(tag, setup_version, prerelease=True, name=None, body="", draft=False, sha=True):  # a GitHub release, as the API returns it
    setup = f"Kestrel-Setup-{setup_version}-abc1234.exe"  # its setup program's name
    assets = [{"name": setup, "browser_download_url": f"https://example.invalid/{setup}"}]  # the setup program
    if sha:  # with its hash file
        assets.append({"name": setup + ".sha256", "browser_download_url": f"https://example.invalid/{setup}.sha256"})  # the hash
    return {"tag_name": tag, "name": name or f"Kestrel {setup_version}", "body": body, "prerelease": prerelease, "draft": draft, "assets": assets, "html_url": f"https://example.invalid/{tag}"}  # the release


def test_versions_sort_in_release_order():  # 0.40 < 0.40R1 < 0.40R3 < 0.41 < 0.42
    names = ["0.42", "0.40R3", "v0.41", "0.40", "0.40R1"]  # mixed up
    assert sorted(names, key=updates.version_key) == ["0.40", "0.40R1", "0.40R3", "v0.41", "0.42"]  # in order
    assert updates.version_key("nonsense") < updates.version_key("0.01")  # unreadable sorts first


def test_signal_version_read_from_title_or_notes():  # "signal 0.42" or "Signal version 0.42"
    assert updates.signal_of({"name": "Kestrel 0.42 (signal 0.42)", "body": ""}) == "0.42"  # from the title
    assert updates.signal_of({"name": "Kestrel 0.42R1", "body": "Signal version 0.42 stays."}) == "0.42"  # from the notes
    assert updates.signal_of({"name": "Kestrel", "body": ""}) is None  # not said


def test_newer_release_offered_and_older_not():  # only something newer is offered
    found = updates.pick([release("v0.41", "0.41"), release("v0.42", "0.42", name="Kestrel 0.42 (signal 0.42)")], "0.41", "0.41")  # one newer
    assert found["version"] == "0.42" and found["new_signal"]  # offered, and it changes the signal
    assert updates.pick([release("v0.41", "0.41")], "0.41", "0.41") is None  # up to date
    assert updates.pick([release("v0.40R3", "0.40R3")], "0.41", "0.41") is None  # older


def test_test_releases_and_signal_only_choices():  # the Settings > Updates choices
    plain = [release("v0.42R1", "0.42R1", name="Kestrel 0.42R1 (signal 0.42)")]  # a revision that keeps signal 0.42
    assert updates.pick(plain, "0.42", "0.42", include_test=False) is None  # a pre-release, and test releases are not wanted
    assert updates.pick(plain, "0.42", "0.42", only_signal=True) is None  # no signal change, and only those are wanted
    assert updates.pick(plain, "0.42", "0.42")["version"] == "0.42R1"  # otherwise offered


def test_skipped_version_stays_quiet_unless_it_changes_the_signal():  # Skip this version
    plain = [release("v0.42R1", "0.42R1", name="Kestrel 0.42R1 (signal 0.42)")]  # no signal change
    assert updates.pick(plain, "0.42", "0.42", skipped="0.42R1") is None  # skipped
    signal = [release("v0.43", "0.43", name="Kestrel 0.43 (signal 0.43)")]  # a signal change
    assert updates.pick(signal, "0.42", "0.42", skipped="0.43") is not None  # shown anyway: the operator must know


def test_drafts_and_releases_without_a_setup_program_ignored():  # nothing to install
    bare = release("v0.43", "0.43")  # a release
    bare["assets"] = []  # with no files
    assert updates.pick([bare, release("v0.44", "0.44", draft=True)], "0.42", "0.42") is None  # neither offered


def test_when_checks_are_due():  # Off, At start-up, Daily
    assert updates.due("startup", 0, 1000, True) and not updates.due("startup", 0, 1000, False)  # once at start
    assert updates.due("daily", 0, 1000, True)  # at start
    assert not updates.due("daily", 1000, 1000 + 3600, False) and updates.due("daily", 1000, 1000 + updates.DAY_S, False)  # then a day later
    assert not updates.due("off", 0, 10 ** 9, True)  # never


def test_a_failed_check_is_quiet():  # no internet, GitHub down
    def broken():  # a fetcher that fails
        raise OSError("no route to host")  # as urllib would
    offer, problem = updates.check("0.41", "0.41", fetcher=broken)  # the check
    assert offer is None and "no route" in problem  # nothing offered, the reason kept for the Activity log


class Reply(io.BytesIO):  # a fake urllib reply
    def __init__(self, data):  # its content
        super().__init__(data)  # the bytes
        self.headers = {"Content-Length": str(len(data))}  # its size

    def __enter__(self):  # used in a with statement
        return self  # itself

    def __exit__(self, *exc):  # leaving the with statement
        self.close()  # done


def test_download_checked_against_its_hash(tmp_path):  # a good download is kept, a bad one refused and deleted
    data = b"setup program bytes"  # the setup program
    info = updates.describe(release("v0.42", "0.42"))  # the release
    good = hashlib.sha256(data).hexdigest()  # its real hash

    def opener(request, timeout=None):  # serve the two files
        return Reply((good + "  " + info["setup_name"] + "\n").encode()) if request.full_url.endswith(".sha256") else Reply(data)  # hash file or setup program
    path = updates.download(info, folder=str(tmp_path), opener=opener)  # fetched and checked
    assert open(path, "rb").read() == data  # kept

    def liar(request, timeout=None):  # the setup program does not match the hash
        return Reply(b"0" * 64 + b"\n") if request.full_url.endswith(".sha256") else Reply(data)  # a wrong hash
    with pytest.raises(ValueError):  # refused
        updates.download(info, folder=str(tmp_path / "bad"), opener=liar)  # tried
    assert not os.path.exists(tmp_path / "bad" / info["setup_name"])  # and deleted


def test_download_refused_without_a_hash():  # nothing to check against
    info = updates.describe(release("v0.42", "0.42", sha=False))  # no hash file
    with pytest.raises(ValueError):  # refused
        updates.download(info, opener=lambda request, timeout=None: Reply(b""))  # tried


def test_helper_waits_installs_silently_and_restarts():  # the PowerShell helper script (a batch file until 0.44R1)
    text = updates.helper_script(4242, r"C:\Temp\KestrelUpdate\Kestrel-Setup-0.42-abc1234.exe", r"C:\Users\x\AppData\Local\Programs\Kestrel\Kestrel.exe", ["--profile", "second"])  # the script
    assert "Get-Process -Id 4242" in text and "-ne 'Kestrel'" in text  # waits for this Kestrel (by number and name) to close
    assert "tasklist" not in text and "timeout /t" not in text  # none of the console tools that hung in a detached process
    assert "'Kestrel did not close; nothing was installed'" in text  # gives up rather than install over a running Kestrel
    assert "$setup = 'C:\\Temp\\KestrelUpdate\\Kestrel-Setup-0.42-abc1234.exe'" in text and "-ArgumentList '/S' -Wait" in text  # installs silently and waits for it
    assert "$arguments = @('--profile', 'second')" in text  # starts again with the same profile
    for line in text.split("\r\n"):  # every line
        assert not line.strip() or "#" in line  # carries a comment


def test_helper_quotes_paths_with_apostrophes():  # a Windows user name such as O'Brien
    text = updates.helper_script(7, r"C:\Users\O'Brien\Temp\Kestrel-Setup-0.44R1-abc1234.exe", r"C:\Users\O'Brien\Kestrel.exe")  # the script
    assert "'C:\\Users\\O''Brien\\Temp\\Kestrel-Setup-0.44R1-abc1234.exe'" in text  # the quote doubled, as PowerShell needs
    assert "$arguments = @()" in text  # no options: an empty list


@pytest.mark.skipif(sys.platform != "win32", reason="the helper runs only on Windows")  # Windows only
def test_helper_really_waits_installs_and_restarts(tmp_path):  # end to end, as Kestrel starts it (the 0.44 helper hung here)
    marker = tmp_path / "setup_ran.txt"  # written by the stand-in setup program
    restarted = tmp_path / "restarted.txt"  # written by the stand-in Kestrel
    setup = tmp_path / "fake-setup.cmd"  # a stand-in for the setup program
    setup.write_text(f'@echo ran %* > "{marker}"\r\n', encoding="ascii")  # it records that it ran, and its options
    program = tmp_path / "fake-kestrel.cmd"  # a stand-in for the installed Kestrel
    program.write_text(f'@echo %* > "{restarted}"\r\n', encoding="ascii")  # it records that it started, and its options
    kestrel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])  # a stand-in for the running Kestrel, closing in 3 seconds
    name = psutil_free_name(kestrel.pid)  # its process name, as Windows reports it
    started = time.time()  # when the helper starts
    updates.start_helper(kestrel.pid, str(setup), str(program), ["--profile", "second"], name=name)  # exactly as the panel does
    time.sleep(1.5)  # the stand-in is still running
    assert not marker.exists()  # so nothing has been installed yet
    while not restarted.exists() and time.time() - started < 45:  # wait for the helper to finish
        time.sleep(0.25)  # look again shortly
    kestrel.wait()  # the stand-in has ended
    log = (tmp_path / "update_log.txt").read_text(encoding="utf-8")  # what the helper wrote
    assert restarted.exists(), log  # Kestrel was started again
    assert "/S" in marker.read_text() and "--profile" in restarted.read_text() and "second" in restarted.read_text()  # silently installed; same profile
    assert "setup finished with code 0" in log and "Kestrel started again" in log  # and the log says so
    for _ in range(40):  # the helper deletes itself as its last step
        if not (tmp_path / "kestrel_update.ps1").exists():  # gone
            break  # done
        time.sleep(0.25)  # look again shortly
    assert not (tmp_path / "kestrel_update.ps1").exists()  # tidied away


def psutil_free_name(pid):  # a process's name without extra packages
    """Return the name Windows gives process `pid`, without its .exe (what PowerShell's ProcessName shows)."""
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout  # one CSV line, run with normal handles
    return out.split(",")[0].strip('"').rsplit(".", 1)[0]  # "python.exe" -> "python"


def test_repository_read_from_the_notice_file(tmp_path):  # the project's address is written once, in NOTICE
    notice = tmp_path / "NOTICE.txt"  # a credit file
    notice.write_text("Kestrel\nhttps://github.com/example-owner/Kestrel\nmore text\n", encoding="utf-8")  # with a project address
    assert updates.repository([str(tmp_path / "missing"), str(notice)]) == "example-owner/Kestrel"  # found in the second place
    assert updates.repository([str(tmp_path / "missing")]) is None  # no file: unknown
    assert updates.releases_page("example-owner/Kestrel").endswith("/example-owner/Kestrel/releases")  # the page built from it
