"""Tests for the operator's own themes and changes to built-in themes (since 0.37): saving, reading back, restoring, exporting and importing."""


def test_own_and_changed_themes_round_trip(tmp_path):  # saved, forgotten, read back
    from live import theme  # the themes

    path = str(tmp_path / "themes.json")  # a private file
    try:  # whatever happens, the tables are put back for the other tests
        theme.add_program_theme("my_test", "My test", "dark", dict(theme.palette("dark"), accent="#123456", mode_ft8="#abcdef"))  # one of the operator's own
        theme.add_scope_theme("my_scope", "My scope", {"scope_bg": "#010203", "rx_trace": "#fedcba", "waterfall": "Ice (black, blue, white)"})  # and a scope theme
        theme.add_program_theme("dark", "Dark, changed", "dark", dict(theme.palette("dark"), bg="#000001"))  # a built-in theme changed
        assert theme.is_changed("dark") and not theme.is_changed("light")  # noticed
        theme.save_user(path)  # kept
        theme.remove_theme("my_test")  # forgotten
        theme.remove_theme("my_scope", scope=True)  # (both)
        theme.restore_original("dark")  # and the change undone
        assert "my_test" not in theme.THEMES and not theme.is_changed("dark")  # gone
        assert theme.load_user(path, replace=True) == 3  # all three read back
        assert theme.palette("my_test")["accent"] == "#123456" and theme.palette("my_test")["mode_ft8"] == "#abcdef"  # the operator's theme, mode colors included
        assert theme.palette("dark", "my_scope")["scope_bg"] == "#010203"  # the scope theme on the scopes
        assert theme.palette("dark")["bg"] == "#000001" and theme.NAMES["dark"] == "Dark, changed"  # the change to the built-in theme
        assert "my_test" in theme.CHOICES and "my_scope" in theme.SCOPE_NAMES  # offered
        theme.remove_theme("dark")  # a built-in theme is never deleted
        assert "dark" in theme.THEMES  # still there
        out = str(tmp_path / "share.json")  # an export
        theme.export_theme("my_test", out)  # written
        theme.remove_theme("my_test")  # forgotten here
        assert theme.load_user(out) == 1 and "my_test" in theme.THEMES  # imported again
        assert theme.load_user(out) == 1 and sum(1 for k in theme.THEMES if theme.NAMES[k] == "My test") == 2  # a second import gets a new key, never overwriting
    finally:  # put the tables back
        for key in [k for k in theme.THEMES if k.startswith("my_")]:  # the test's own
            theme.remove_theme(key)  # removed
        for key in [k for k in theme.SCOPE_THEMES if k.startswith("my_")]:  # (scope too)
            theme.remove_theme(key, scope=True)  # removed
        theme.restore_original("dark")  # as it comes
