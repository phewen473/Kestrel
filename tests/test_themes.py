"""Tests for the color themes (since 0.37): live/theme.py."""

import re  # color checks


def test_at_least_twelve_complete_themes():  # every theme names every color, in a form Tk accepts
    from live import theme  # the themes

    assert len(theme.THEMES) >= 12 and theme.CHOICES[0] == "system"  # twelve or more, System first
    keys = set(theme.BASES["light"])  # every color a theme uses
    assert keys == set(theme.BASES["dark"])  # both bases name the same colors
    for name in theme.THEMES:  # each theme
        colors = theme.palette(name)  # its full palette
        assert keys <= set(colors), (name, keys - set(colors))  # nothing missing
        for key in keys - {"waterfall"}:  # each color (the waterfall entry is a color set's name)
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", colors[key]), (name, key, colors[key])  # a #rrggbb color
        assert colors["base"] in ("light", "dark") and colors["name"] == name  # labeled
        assert name in theme.NAMES and theme.NAMES[name]  # shown to the operator with a name


def test_theme_waterfalls_exist_and_unknown_names_fall_back():  # the waterfall sets themes ask for, and a bad saved name
    import sys  # import path
    import os  # paths
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))  # the panel's folder
    from live import theme  # the themes
    import kestrel_panel as kp  # the panel (for its waterfall color sets)

    for name in theme.THEMES:  # each theme
        assert theme.palette(name)["waterfall"] in kp.PALETTES, name  # its waterfall set is one the panel offers
    assert theme.resolve("no such theme") == "light"  # an unknown saved name gives the light theme
    assert theme.resolve("system") in ("light", "dark")  # System follows Windows
