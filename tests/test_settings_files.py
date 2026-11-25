"""Tests for File > Export settings and Import settings, and File > Export themes (since 0.37)."""

import json  # the files' form
import os  # paths
import sys  # import path

import pytest  # expected failures


def panel_module():  # the panel's module (its folder is not a package)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))  # the panel's folder
    import kestrel_panel as kp  # the panel
    return kp  # it


def test_export_leaves_this_computer_out_unless_asked(tmp_path):  # sound cards, ports and layout stay behind by default
    kp = panel_module()  # the panel
    settings = dict(kp.DEFAULTS, call="Q1ABC", grid="EM92", audio_in="Line In (USB CODEC)", cat_port="COM7", layout={"w": 1400})  # a station's settings
    plain, full = tmp_path / "plain.json", tmp_path / "full.json"  # two exports
    kp.export_settings_file(settings, str(plain))  # without this computer's own
    kp.export_settings_file(settings, str(full), machine=True)  # with them
    data = json.loads(plain.read_text(encoding="utf-8"))  # read back
    assert data["kind"] == kp.SETTINGS_KIND and data["settings"]["call"] == "Q1ABC" and data["settings"]["grid"] == "EM92"  # the station is in it
    assert not any(key in data["settings"] for key in kp.MACHINE_KEYS)  # this computer's own are not
    assert json.loads(full.read_text(encoding="utf-8"))["settings"]["cat_port"] == "COM7"  # unless asked for


def test_import_keeps_this_computer_and_checks_forms(tmp_path):  # an import lays the file's settings over the present ones
    kp = panel_module()  # the panel
    other = dict(kp.DEFAULTS, call="Q2XYZ", beacon_every_min=10, cat_port="COM3", theme="nord")  # another station's settings
    path = tmp_path / "other.json"  # its file
    kp.export_settings_file(other, str(path), machine=True)  # exported with its ports
    raw = json.loads(path.read_text(encoding="utf-8"))  # spoil two settings and add an unknown one
    raw["settings"]["record_rx"] = "yes"  # wrong form (should be true or false)
    raw["settings"]["no_such_setting"] = 1  # unknown
    path.write_text(json.dumps(raw), encoding="utf-8")  # written back
    incoming = kp.read_settings_file(str(path))  # read
    assert "no_such_setting" not in incoming  # unknown settings dropped
    here = dict(kp.DEFAULTS, call="Q1ABC", cat_port="COM7")  # this computer's settings
    merged = kp.merged_settings(here, incoming)  # this computer's ports kept
    assert merged["call"] == "Q2XYZ" and merged["beacon_every_min"] == 10 and merged["theme"] == "nord"  # the file's settings taken
    assert merged["cat_port"] == "COM7" and merged["record_rx"] is False  # this computer's port kept; the spoiled one ignored
    assert kp.merged_settings(here, incoming, machine=True)["cat_port"] == "COM3"  # the file's port, when asked for
    assert here["call"] == "Q1ABC"  # the present settings untouched


def test_a_themes_file_is_not_a_settings_file(tmp_path):  # the two kinds are kept apart
    kp = panel_module()  # the panel
    path = tmp_path / "themes.json"  # a themes file
    path.write_text(json.dumps({"kind": "kestrel-themes", "program": {}, "scope": {}}), encoding="utf-8")  # written
    with pytest.raises(ValueError):  # refused
        kp.read_settings_file(str(path))  # as settings


def test_export_all_themes_round_trip(tmp_path):  # File > Export themes, then Import themes
    from live import theme  # the themes
    theme.add_program_theme("test_mine", "Test mine", "dark", {"bg": "#101820"})  # one of the operator's
    theme.add_program_theme("nord", "Nordic frost", "dark", dict(theme.palette("nord"), fg="#ffffff"))  # a changed built-in one
    try:  # whatever happens, put things back
        path = tmp_path / "all.json"  # the file
        theme.export_all(str(path))  # written
        data = json.loads(path.read_text(encoding="utf-8"))  # read back
        assert data["kind"] == "kestrel-themes" and "test_mine" in data["program"] and "nord" in data["changed"]["program"]  # both in it
        theme.remove_theme("test_mine")  # forgotten here
        theme.restore_original("nord")  # as it came
        assert theme.load_user(str(path)) >= 2 and "test_mine" in theme.THEMES and theme.is_changed("nord")  # both back
    finally:  # tidy up
        theme.remove_theme("test_mine")  # gone
        theme.restore_original("nord")  # as it came


def test_a_saved_rigctld_that_has_gone_falls_back_to_one_found(monkeypatch, tmp_path):  # since 0.42R1
    """0.42 moved Kestrel from Program Files to the per-user folder and removed the old copy; settings that still named the old rigctld stopped every Listen."""
    kp = panel_module()  # the panel
    found = tmp_path / "rigctld.exe"  # the copy installed with Kestrel
    found.write_text("x")  # it exists
    monkeypatch.setattr(kp, "find_rigctld", lambda *args: str(found))  # what the search would find
    assert kp.rigctld_program({"rigctld": str(tmp_path / "gone" / "rigctld.exe")}) == str(found)  # a stale path is passed over
    assert kp.rigctld_program({"rigctld": ""}) == str(found)  # none chosen: the one found
    chosen = tmp_path / "mine.exe"  # one the operator chose
    chosen.write_text("x")  # it exists
    assert kp.rigctld_program({"rigctld": str(chosen)}) == str(chosen)  # still used
