"""Tests for the update check (live/updates.py, since 0.42)."""
import hashlib  # to make a matching hash
import io  # fake replies
import os  # file checks

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


def test_helper_waits_installs_silently_and_restarts():  # the batch file
    text = updates.helper_script(4242, r"C:\Temp\KestrelUpdate\Kestrel-Setup-0.42-abc1234.exe", r"C:\Users\x\AppData\Local\Programs\Kestrel\Kestrel.exe", ["--profile", "second"])  # the script
    assert 'PID eq 4242' in text and "goto wait" in text  # waits for Kestrel to close
    assert 'Kestrel-Setup-0.42-abc1234.exe" /S' in text  # installs silently
    assert 'Kestrel.exe" "--profile" "second"' in text  # starts again with the same profile
    lines = [line for line in text.split("\r\n") if line and not line.startswith(("@", "REM", ":", ")", "  REM"))]  # the working lines
    assert lines  # there are some


def test_repository_read_from_the_notice_file(tmp_path):  # the project's address is written once, in NOTICE
    notice = tmp_path / "NOTICE.txt"  # a credit file
    notice.write_text("Kestrel\nhttps://github.com/example-owner/Kestrel\nmore text\n", encoding="utf-8")  # with a project address
    assert updates.repository([str(tmp_path / "missing"), str(notice)]) == "example-owner/Kestrel"  # found in the second place
    assert updates.repository([str(tmp_path / "missing")]) is None  # no file: unknown
    assert updates.releases_page("example-owner/Kestrel").endswith("/example-owner/Kestrel/releases")  # the page built from it
