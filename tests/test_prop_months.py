"""Ionosphere maps shipped for a few months and fetched for the rest (since 0.38): live/propagation.py and tools/build_prop.py."""

import hashlib  # checksums
import os  # paths
import shutil  # copying
import sys  # import path
import time  # dates

import pytest  # fixtures and expected failures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository


def _build_prop():  # tools/build_prop.py as a module
    sys.path.insert(0, os.path.join(ROOT, "tools"))  # its folder
    import build_prop  # the build tool
    return build_prop  # it


def test_installer_months_wrap_and_agree():  # the build month and the next two, past December; the same number in both files
    from live import propagation  # the predictions
    bp = _build_prop()  # the build tool
    assert bp.SHIP_MONTHS == propagation.SHIP_MONTHS == 3  # agree
    nov = time.strptime("2026-11-24", "%Y-%m-%d")  # November
    assert bp.ship_months("C:/somewhere/prop", today=nov) == [1, 11, 12]  # November, December, January
    assert bp.ship_months(bp.TARGET, today=nov) == list(range(1, 13))  # the source folder keeps every month
    assert bp.ship_months("x", months=12, today=nov) == list(range(1, 13))  # all, when asked


@pytest.fixture
def engine(tmp_path, monkeypatch):  # a stand-in engine folder holding the small files and one month's map, and an empty download folder
    from live import propagation  # the predictions
    real = os.path.join(propagation.engine_dir(), "data")  # the source folder's data (all twelve months)
    if not os.path.isdir(real):  # the engine is not built here
        pytest.skip("the ITU engine is not built in this copy (tools/build_prop.py)")  # nothing to copy
    shipped = tmp_path / "prop" / "data"  # the stand-in shipped data
    shipped.mkdir(parents=True)  # made
    for name in propagation.SMALL_FILES + ["ionos11.bin"]:  # the small files and November's map
        shutil.copy2(os.path.join(real, name), shipped / name)  # copied
    monkeypatch.setattr(propagation, "engine_dir", lambda: str(tmp_path / "prop"))  # used as the engine folder
    monkeypatch.setattr(propagation, "fetched_dir", lambda: str(tmp_path / "fetched"))  # downloads go here
    return propagation, real, tmp_path  # for the tests


def test_shipped_month_needs_nothing(engine):  # November ships: no download, the shipped folder is used
    propagation, _real, tmp = engine  # the stand-ins
    assert not propagation.needs_download(11)  # shipped
    assert propagation.month_folder(11) == str(tmp / "prop" / "data")  # used as it is
    assert not (tmp / "fetched").exists()  # nothing fetched


def test_missing_month_is_fetched_and_checked(engine, monkeypatch):  # March: fetched once, checked, and the small files put beside it
    propagation, real, tmp = engine  # the stand-ins
    calls = []  # downloads made
    monkeypatch.setattr(propagation, "_download_map", lambda month, path: (calls.append(month), shutil.copy2(os.path.join(real, f"ionos{month:02d}.bin"), path)))  # a stand-in download (the real file, copied)
    assert propagation.needs_download(3)  # not shipped
    folder = propagation.month_folder(3)  # fetched
    assert folder == str(tmp / "fetched") and calls == [3]  # into the download folder, once
    for name in propagation.SMALL_FILES + ["ionos03.bin"]:  # everything the program reads
        assert (tmp / "fetched" / name).is_file()  # is there
    assert propagation.month_folder(3) == folder and calls == [3]  # the second time: no download
    assert not propagation.needs_download(3)  # remembered


def test_damaged_download_is_refused(engine, monkeypatch, tmp_path):  # a file that is not the ITU's map is thrown away
    propagation, _real, tmp = engine  # the stand-ins
    import io  # a fake response
    import urllib.request  # replaced
    class Fake(io.BytesIO):  # a response that sends the wrong bytes
        def __enter__(self): return self  # as a context
        def __exit__(self, *a): return False  # nothing to clean
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Fake(b"\0" * propagation.IONOS_BYTES))  # right length, wrong content
    with pytest.raises(RuntimeError, match="did not match"):  # refused
        propagation.month_folder(4)  # April
    assert not (tmp / "fetched" / "ionos04.bin").exists() and not (tmp / "fetched" / "ionos04.bin.part").exists()  # nothing left behind


def test_no_connection_says_why(engine, monkeypatch):  # offline: a clear message
    propagation, _real, _tmp = engine  # the stand-ins
    import urllib.error  # the error
    import urllib.request  # replaced
    def offline(*a, **k):  # no network
        raise urllib.error.URLError("no network")  # as urllib says it
    monkeypatch.setattr(urllib.request, "urlopen", offline)  # no network
    with pytest.raises(RuntimeError, match="internet connection"):  # said
        propagation.month_folder(5)  # May


def test_published_checksums_match_the_source_files():  # the twelve checksums are those of the ITU's files in the source folder
    from live import propagation  # the predictions
    real = os.path.join(propagation.engine_dir(), "data")  # all twelve
    if not os.path.isfile(os.path.join(real, "ionos12.bin")):  # not built here
        pytest.skip("the ITU engine is not built in this copy")  # nothing to compare
    for month in range(1, 13):  # each
        with open(os.path.join(real, f"ionos{month:02d}.bin"), "rb") as handle:  # read
            assert hashlib.sha256(handle.read()).hexdigest() == propagation.IONOS_SHA256[month]  # the same


@pytest.mark.skipif(os.environ.get("KESTREL_NET_TESTS") != "1", reason="downloads 11 MB from GitHub; set KESTREL_NET_TESTS=1 to run")
def test_real_download(engine):  # the ITU's repository, for real
    propagation, _real, tmp = engine  # the stand-ins
    folder = propagation.month_folder(6)  # June, fetched
    assert propagation._good_map(os.path.join(folder, "ionos06.bin"), 6)  # the ITU's file
