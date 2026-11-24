"""Color themes for the control panel (20 since 0.37, and 8 scope themes), and following the operating system's choice.

View > Theme (and Settings > Appearance) offers System (follow Windows'
own light or dark setting) and fifteen themes. A theme colors every part of
the program: the themed (ttk) widgets through one shared style; the plain
Tk widgets (the activity log, the status band, the lists' highlights); the
two scopes (background, traces, scales, labels, time marks); the level
meters; the status band's state colors; and, when View > Waterfall colors
is set to "Theme's own", the waterfalls. On Windows the title bar is made
dark or light to match. Windows draws the menu bar itself, so it keeps the
system's colors.

Each theme is a palette: a dict of named colors. Every theme is built on
one of two bases, light or dark, which supply any color a theme leaves out.
"""

import sys  # which operating system this is

BASES = {  # every color a theme uses, for a light and a dark theme
    "light": {"bg": "#f3f3f3", "panel": "#ffffff", "field": "#ffffff", "fg": "#1a1a1a", "muted": "#555555", "accent": "#0a64c8",  # (continued: windows, lists, writing)
              "select": "#cce4ff", "select_fg": "#000000", "border": "#c8c8c8", "heading": "#e6e6e6", "text_bg": "#ffffff", "text_fg": "#1a1a1a",  # (continued: selections, borders, the log)
              "scope_bg": "#0b0e12", "rx_trace": "#7cfc00", "tx_trace": "#ff9f43", "tx_words": "#ffd166", "scale": "#a8b0ba", "scale_faint": "#3a414a", "edge": "#e0e0e0",  # (continued: the scopes)
              "time_line": "#e8e8e8", "time_text": "#ffffff", "time_bg": "#000000", "label": "#ffffff", "label_bg": "#000000", "mark": "#ffd166",  # (continued: time marks, signal labels, station marks)
              "meter_low": "#20303a", "meter_ok": "#16452a", "meter_loud": "#4a4416", "meter_hot": "#4a1c1c", "bar_ok": "#3fbf6f", "bar_loud": "#e0c040", "bar_hot": "#e05050", "bar_low": "#5a7a8a", "bar_dim": "#4a5560", "peak": "#ffffff",  # (continued: the meters)
              "status_ok": "#1b7f3b", "status_warn": "#d98200", "status_bad": "#c0392b", "status_fg": "#ffffff", "calling_row": "#fff0a8", "warn_fg": "#b00000",  # (continued: states and warnings)
              "waterfall": "Classic"},  # the waterfall colors that go with it
    "dark": {"bg": "#1e2227", "panel": "#262b31", "field": "#2d333b", "fg": "#d8dee6", "muted": "#9aa4b0", "accent": "#4c9aff",  # (continued)
             "select": "#2f5d8a", "select_fg": "#ffffff", "border": "#3a414a", "heading": "#323840", "text_bg": "#171a1e", "text_fg": "#d8dee6",  # (continued)
             "scope_bg": "#0b0e12", "rx_trace": "#7cfc00", "tx_trace": "#ff9f43", "tx_words": "#ffd166", "scale": "#a8b0ba", "scale_faint": "#3a414a", "edge": "#e0e0e0",  # (continued)
             "time_line": "#e8e8e8", "time_text": "#ffffff", "time_bg": "#000000", "label": "#ffffff", "label_bg": "#000000", "mark": "#ffd166",  # (continued)
             "meter_low": "#20303a", "meter_ok": "#16452a", "meter_loud": "#4a4416", "meter_hot": "#4a1c1c", "bar_ok": "#3fbf6f", "bar_loud": "#e0c040", "bar_hot": "#e05050", "bar_low": "#5a7a8a", "bar_dim": "#4a5560", "peak": "#ffffff",  # (continued)
             "status_ok": "#1b7f3b", "status_warn": "#d98200", "status_bad": "#c0392b", "status_fg": "#ffffff", "calling_row": "#5a4a12", "warn_fg": "#ff7070",  # (continued)
             "waterfall": "Classic"},  # (continued)
}  # end of the bases

THEMES = {  # name -> (base, the colors that differ from the base, what the operator sees)
    "light": ("light", {}, "Light (Windows look)"),  # Windows' own look
    "dark": ("dark", {}, "Dark"),  # the dark look of earlier versions
    "midnight": ("dark", {"bg": "#0f1626", "panel": "#16203a", "field": "#1b2742", "fg": "#d6e2ff", "muted": "#8a9bc4", "accent": "#5b8cff", "select": "#28427a", "border": "#2a3a60", "heading": "#1e2c4e",  # (continued)
                          "text_bg": "#0b1120", "text_fg": "#d6e2ff", "scope_bg": "#070b16", "rx_trace": "#66d9ff", "scale_faint": "#24335a", "calling_row": "#3b3a1a", "waterfall": "Color-blind safe (blue to yellow)"}, "Midnight blue"),  # deep blue
    "solarized_light": ("light", {"bg": "#eee8d5", "panel": "#fdf6e3", "field": "#fdf6e3", "fg": "#586e75", "muted": "#93a1a1", "accent": "#268bd2", "select": "#d3e2e9", "select_fg": "#073642", "border": "#d6ceb5",  # (continued)
                                  "heading": "#e4ddc8", "text_bg": "#fdf6e3", "text_fg": "#586e75", "scope_bg": "#002b36", "rx_trace": "#859900", "tx_trace": "#cb4b16", "tx_words": "#b58900", "mark": "#b58900", "calling_row": "#f5e6a8"}, "Solarized light"),  # warm cream
    "solarized_dark": ("dark", {"bg": "#002b36", "panel": "#073642", "field": "#0a3c4a", "fg": "#93a1a1", "muted": "#657b83", "accent": "#268bd2", "select": "#0d5060", "border": "#0f4a58", "heading": "#08404e",  # (continued)
                                "text_bg": "#00222b", "text_fg": "#93a1a1", "scope_bg": "#001e26", "rx_trace": "#859900", "tx_trace": "#cb4b16", "tx_words": "#b58900", "mark": "#b58900", "scale": "#839496", "scale_faint": "#0f4a58", "calling_row": "#4a4210"}, "Solarized dark"),  # teal night
    "contrast_dark": ("dark", {"bg": "#000000", "panel": "#000000", "field": "#000000", "fg": "#ffffff", "muted": "#ffff00", "accent": "#00ffff", "select": "#0000ff", "select_fg": "#ffffff", "border": "#ffffff", "heading": "#202020",  # (continued)
                               "text_bg": "#000000", "text_fg": "#ffffff", "scope_bg": "#000000", "rx_trace": "#00ff00", "tx_trace": "#ffff00", "tx_words": "#ffff00", "scale": "#ffffff", "scale_faint": "#808080", "label": "#ffff00", "mark": "#00ffff",  # (continued)
                               "calling_row": "#606000", "warn_fg": "#ffff00", "waterfall": "High contrast (black, white, yellow)"}, "High contrast, dark"),  # for low vision
    "contrast_light": ("light", {"bg": "#ffffff", "panel": "#ffffff", "field": "#ffffff", "fg": "#000000", "muted": "#000000", "accent": "#0000c0", "select": "#000080", "select_fg": "#ffffff", "border": "#000000", "heading": "#e0e0e0",  # (continued)
                                 "text_bg": "#ffffff", "text_fg": "#000000", "scope_bg": "#ffffff", "rx_trace": "#006000", "tx_trace": "#a04000", "tx_words": "#000000", "scale": "#000000", "scale_faint": "#a0a0a0", "edge": "#000000",  # (continued)
                                 "time_line": "#000000", "time_text": "#000000", "time_bg": "#ffffff", "label": "#000000", "label_bg": "#ffffff", "mark": "#0000c0", "peak": "#000000", "calling_row": "#ffff80", "waterfall": "Gray, reversed (white to black)"}, "High contrast, light"),  # for low vision, daylight
    "night_red": ("dark", {"bg": "#0a0000", "panel": "#140202", "field": "#1a0404", "fg": "#ff4040", "muted": "#a02020", "accent": "#ff6060", "select": "#5a0a0a", "select_fg": "#ffb0b0", "border": "#3a0a0a", "heading": "#200404",  # (continued)
                           "text_bg": "#080000", "text_fg": "#ff4040", "scope_bg": "#000000", "rx_trace": "#ff3030", "tx_trace": "#c02020", "tx_words": "#ff6060", "scale": "#a02020", "scale_faint": "#3a0808", "edge": "#ff4040",  # (continued)
                           "time_line": "#802020", "time_text": "#ff6060", "label": "#ff8080", "mark": "#ff6060", "meter_low": "#200404", "meter_ok": "#300808", "meter_loud": "#401010", "meter_hot": "#601010",  # (continued)
                           "bar_ok": "#c03030", "bar_loud": "#e04040", "bar_hot": "#ff6060", "bar_low": "#601818", "bar_dim": "#401010", "peak": "#ff8080",  # (continued)
                           "status_ok": "#601010", "status_warn": "#802020", "status_bad": "#a02020", "status_fg": "#ffb0b0", "calling_row": "#3a0a0a", "warn_fg": "#ff8080", "waterfall": "Night red (black to red)"}, "Night red (keeps night vision)"),  # red only
    "forest": ("dark", {"bg": "#14201a", "panel": "#1b2b22", "field": "#21342a", "fg": "#d4e8d8", "muted": "#8fb09a", "accent": "#5ccf7a", "select": "#2e5a3c", "border": "#2c4436", "heading": "#20362a",  # (continued)
                        "text_bg": "#0f1914", "text_fg": "#d4e8d8", "scope_bg": "#08100b", "rx_trace": "#a6ff4d", "scale_faint": "#24392c", "calling_row": "#4a4a14", "waterfall": "Green phosphor (black to green)"}, "Forest green"),  # greens
    "amber": ("dark", {"bg": "#120c00", "panel": "#1c1300", "field": "#241900", "fg": "#ffb000", "muted": "#b07800", "accent": "#ffcc33", "select": "#5a3c00", "select_fg": "#ffe0a0", "border": "#3a2800", "heading": "#241900",  # (continued)
                       "text_bg": "#0c0800", "text_fg": "#ffb000", "scope_bg": "#080500", "rx_trace": "#ffb000", "tx_trace": "#ff8000", "tx_words": "#ffcc33", "scale": "#b07800", "scale_faint": "#3a2800", "edge": "#ffb000",  # (continued)
                       "label": "#ffcc33", "mark": "#ffcc33", "time_line": "#b07800", "time_text": "#ffcc33", "calling_row": "#4a3200", "warn_fg": "#ffcc33", "waterfall": "Amber (black to amber)"}, "Amber terminal"),  # an old amber screen
    "slate": ("dark", {"bg": "#2b2f36", "panel": "#343942", "field": "#3b414b", "fg": "#e3e6ea", "muted": "#a7afba", "accent": "#7aa2c8", "select": "#4d6580", "border": "#4a515c", "heading": "#3f4550",  # (continued)
                       "text_bg": "#24282e", "text_fg": "#e3e6ea", "scope_bg": "#1a1d22", "rx_trace": "#9fd3ff", "calling_row": "#5a5020", "waterfall": "Gray (black to white)"}, "Slate gray"),  # soft grays
    "sepia": ("light", {"bg": "#f1e7d0", "panel": "#fbf4e4", "field": "#fbf4e4", "fg": "#4a3b2a", "muted": "#7d6a52", "accent": "#9c5b23", "select": "#e3cfa6", "select_fg": "#2b1f12", "border": "#d6c4a0", "heading": "#eadbb9",  # (continued)
                        "text_bg": "#fbf4e4", "text_fg": "#4a3b2a", "scope_bg": "#2b1f12", "rx_trace": "#e6c27a", "tx_trace": "#d0864a", "tx_words": "#e6c27a", "mark": "#e6c27a", "calling_row": "#f3dc96", "waterfall": "Heat (black, red, yellow, white)"}, "Sepia paper"),  # old paper
    "ocean": ("dark", {"bg": "#0d2229", "panel": "#123039", "field": "#163a44", "fg": "#d2eef2", "muted": "#86b7c0", "accent": "#2ec4d6", "select": "#1d5866", "border": "#21495a", "heading": "#153640",  # (continued)
                       "text_bg": "#0a1b21", "text_fg": "#d2eef2", "scope_bg": "#06131a", "rx_trace": "#5ff2e0", "scale_faint": "#1b3c48", "calling_row": "#3d4a14", "waterfall": "Color-blind safe (purple to yellow)"}, "Ocean teal"),  # sea colors
    "dusk": ("dark", {"bg": "#1d1828", "panel": "#262035", "field": "#2d2640", "fg": "#e6dcf5", "muted": "#a596c2", "accent": "#b48cff", "select": "#47376e", "border": "#3a3052", "heading": "#2c2540",  # (continued)
                      "text_bg": "#161220", "text_fg": "#e6dcf5", "scope_bg": "#0e0b16", "rx_trace": "#ff9de2", "tx_trace": "#ffb36b", "scale_faint": "#2f2744", "calling_row": "#4e3f16", "waterfall": "Color-blind safe (purple to yellow)"}, "Purple dusk"),  # violets
    "nord": ("dark", {"bg": "#2e3440", "panel": "#3b4252", "field": "#434c5e", "fg": "#eceff4", "muted": "#a3adbf", "accent": "#88c0d0", "select": "#4c566a", "border": "#4c566a", "heading": "#3b4252",  # (continued)
                      "text_bg": "#2a2f3a", "text_fg": "#e5e9f0", "scope_bg": "#242933", "rx_trace": "#a3be8c", "tx_trace": "#d08770", "tx_words": "#ebcb8b", "mark": "#ebcb8b", "calling_row": "#5a5030", "waterfall": "Color-blind safe (blue to yellow)"}, "Nordic frost"),  # cool northern colors
    "daylight": ("light", {"bg": "#e9eef3", "panel": "#ffffff", "field": "#ffffff", "fg": "#14202c", "muted": "#4f6070", "accent": "#d0480f", "select": "#ffd9c4", "select_fg": "#14202c", "border": "#b7c3cf", "heading": "#dfe6ee",  # (continued)
                           "text_bg": "#ffffff", "text_fg": "#14202c", "scope_bg": "#f4f7fa", "rx_trace": "#0a7d2c", "tx_trace": "#d0480f", "tx_words": "#14202c", "scale": "#4f6070", "scale_faint": "#c8d2dc", "edge": "#14202c",  # (continued)
                           "time_line": "#4f6070", "time_text": "#14202c", "time_bg": "#ffffff", "label": "#14202c", "label_bg": "#ffffff", "mark": "#d0480f", "peak": "#14202c", "calling_row": "#ffe8a8", "waterfall": "Gray, reversed (white to black)"}, "Daylight (bright screens outdoors)"),  # for a sunny room or outdoors
    "graphite": ("dark", {"bg": "#232323", "panel": "#2c2c2c", "field": "#333333", "fg": "#e8e8e8", "muted": "#a0a0a0", "accent": "#e0e0e0", "select": "#4a4a4a", "select_fg": "#ffffff", "border": "#444444", "heading": "#383838",  # (continued: since 0.37)
                          "text_bg": "#1c1c1c", "text_fg": "#e8e8e8", "scope_bg": "#121212", "rx_trace": "#f0f0f0", "calling_row": "#4d4520", "waterfall": "Gray (black to white)"}, "Graphite"),  # neutral grays, no color at all
    "steel": ("light", {"bg": "#dfe7ef", "panel": "#f4f8fb", "field": "#ffffff", "fg": "#1c2b3a", "muted": "#566a7e", "accent": "#2f6ea6", "select": "#bcd4ea", "select_fg": "#0e1a26", "border": "#a9bccd", "heading": "#cfdbe6",  # (continued: since 0.37)
                        "text_bg": "#f7fafc", "text_fg": "#1c2b3a", "scope_bg": "#0d1a26", "rx_trace": "#7fd1ff", "calling_row": "#f6e7a6", "waterfall": "Color-blind safe (blue to yellow)"}, "Steel blue"),  # cool blue-gray, light
    "desert": ("light", {"bg": "#ead9c0", "panel": "#f6ebda", "field": "#fbf3e7", "fg": "#3e2f22", "muted": "#7a634a", "accent": "#c0612b", "select": "#e7c49f", "select_fg": "#2a1d12", "border": "#cdb08c", "heading": "#e0caa9",  # (continued: since 0.37)
                         "text_bg": "#fbf3e7", "text_fg": "#3e2f22", "scope_bg": "#26180c", "rx_trace": "#ffc06a", "tx_trace": "#ff7b4a", "mark": "#ffc06a", "calling_row": "#f2d68a", "waterfall": "Thermal (purple, red, yellow)"}, "Desert sand"),  # warm sand, light
    "olive": ("dark", {"bg": "#1f2318", "panel": "#282d1f", "field": "#2f3524", "fg": "#dcdcc2", "muted": "#a3a585", "accent": "#b8c96a", "select": "#4a5432", "select_fg": "#f3f3e0", "border": "#3d4430", "heading": "#323925",  # (continued: since 0.37)
                       "text_bg": "#191c13", "text_fg": "#dcdcc2", "scope_bg": "#0f120a", "rx_trace": "#c8e07a", "tx_trace": "#e0a050", "calling_row": "#4d4a1a", "waterfall": "Green phosphor (black to green)"}, "Olive drab (field radio)"),  # like military field equipment
}  # end of the themes

SCOPE_THEMES = {  # the scopes' own look, chosen apart from the program's theme (since 0.37): name -> (colors that replace the theme's on the scopes and meters, what the operator sees)
    "theme": ({}, "Follow the program theme"),  # the theme decides
    "classic": ({"scope_bg": "#0b0e12", "rx_trace": "#7cfc00", "tx_trace": "#ff9f43", "tx_words": "#ffd166", "scale": "#a8b0ba", "scale_faint": "#3a414a", "edge": "#e0e0e0", "time_line": "#e8e8e8", "time_text": "#ffffff", "time_bg": "#000000", "label": "#ffffff", "label_bg": "#000000", "mark": "#ffd166", "waterfall": "Classic"}, "Classic (black, green trace)"),  # the scopes as they always were
    "oscilloscope": ({"scope_bg": "#001a0a", "rx_trace": "#39ff6a", "tx_trace": "#a6ff4d", "tx_words": "#7dff9a", "scale": "#2fa856", "scale_faint": "#0b4020", "edge": "#39ff6a", "time_line": "#2fa856", "time_text": "#7dff9a", "time_bg": "#001a0a", "label": "#7dff9a", "label_bg": "#001a0a", "mark": "#b6ff9e", "waterfall": "Green phosphor (black to green)"}, "Oscilloscope (green phosphor)"),  # a green-screen scope
    "analyzer": ({"scope_bg": "#06122a", "rx_trace": "#ffe84d", "tx_trace": "#ff7a45", "tx_words": "#ffe84d", "scale": "#8fb3ff", "scale_faint": "#1c3466", "edge": "#c9dbff", "time_line": "#8fb3ff", "time_text": "#ffffff", "time_bg": "#06122a", "label": "#ffffff", "label_bg": "#06122a", "mark": "#ffe84d", "waterfall": "Color-blind safe (blue to yellow)"}, "Spectrum analyzer (blue, yellow trace)"),  # a bench analyzer
    "night": ({"scope_bg": "#000000", "rx_trace": "#ff3030", "tx_trace": "#c02020", "tx_words": "#ff6060", "scale": "#a02020", "scale_faint": "#3a0808", "edge": "#ff4040", "time_line": "#802020", "time_text": "#ff6060", "time_bg": "#000000", "label": "#ff8080", "label_bg": "#000000", "mark": "#ff6060", "waterfall": "Night red (black to red)"}, "Night red"),  # keeps night vision
    "amber": ({"scope_bg": "#0a0600", "rx_trace": "#ffb000", "tx_trace": "#ff7a00", "tx_words": "#ffcc33", "scale": "#b07800", "scale_faint": "#3a2800", "edge": "#ffb000", "time_line": "#b07800", "time_text": "#ffcc33", "time_bg": "#0a0600", "label": "#ffcc33", "label_bg": "#0a0600", "mark": "#ffcc33", "waterfall": "Amber (black to amber)"}, "Amber"),  # an amber screen
    "paper": ({"scope_bg": "#fafaf7", "rx_trace": "#0a5a1e", "tx_trace": "#b04000", "tx_words": "#202020", "scale": "#505050", "scale_faint": "#d0d0c8", "edge": "#202020", "time_line": "#606060", "time_text": "#202020", "time_bg": "#fafaf7", "label": "#202020", "label_bg": "#fafaf7", "mark": "#b04000", "waterfall": "Gray, reversed (white to black)"}, "Paper (light scope, dark ink)"),  # a printed chart
    "thermal": ({"scope_bg": "#0c0414", "rx_trace": "#ffd23f", "tx_trace": "#ff5a36", "tx_words": "#ffd23f", "scale": "#b08cc8", "scale_faint": "#2e1a40", "edge": "#e0c8f0", "time_line": "#b08cc8", "time_text": "#ffffff", "time_bg": "#0c0414", "label": "#ffffff", "label_bg": "#0c0414", "mark": "#ffd23f", "waterfall": "Thermal (purple, red, yellow)"}, "Thermal camera"),  # purple through red to yellow
    "ice": ({"scope_bg": "#020a14", "rx_trace": "#bff3ff", "tx_trace": "#7ab8ff", "tx_words": "#dff8ff", "scale": "#7aa6c2", "scale_faint": "#123048", "edge": "#dff8ff", "time_line": "#7aa6c2", "time_text": "#ffffff", "time_bg": "#020a14", "label": "#dff8ff", "label_bg": "#020a14", "mark": "#bff3ff", "waterfall": "Ice (black, blue, white)"}, "Ice"),  # cold blues and white
}  # end of the scope themes
SCOPE_NAMES = {key: value[1] for key, value in SCOPE_THEMES.items()}  # each, as the operator sees it
BUILT_IN = set(THEMES)  # the program themes that come with Kestrel (they can be changed, and put back; never deleted)
BUILT_IN_SCOPES = set(SCOPE_THEMES)  # the same, for the scope themes
ORIGINALS = {key: (value[0], dict(value[1]), value[2]) for key, value in THEMES.items()}  # the program themes as they come with Kestrel, for Restore original
ORIGINAL_SCOPES = {key: (dict(value[0]), value[1]) for key, value in SCOPE_THEMES.items()}  # the same, for the scope themes
SCOPE_KEYS = ("scope_bg", "rx_trace", "tx_trace", "tx_words", "scale", "scale_faint", "edge", "time_line", "time_text", "time_bg", "label", "label_bg", "mark", "waterfall")  # the colors a scope theme sets

COLOR_LABELS = {  # every color the operator can change, in groups, as the theme editor shows them: key -> (group, what it colors)
    "bg": ("Windows", "Window background"), "panel": ("Windows", "Panels and buttons"), "field": ("Windows", "Boxes you type in"), "fg": ("Windows", "Writing"),  # (continued)
    "muted": ("Windows", "Quieter writing (titles of groups)"), "accent": ("Windows", "Accent (pushed-in buttons, ticks)"), "border": ("Windows", "Borders"), "heading": ("Windows", "List headings and open tab"),  # (continued)
    "select": ("Lists", "Chosen row"), "select_fg": ("Lists", "Writing on the chosen row"), "calling_row": ("Lists", "Stations calling now"), "text_bg": ("Lists", "Activity log background"), "text_fg": ("Lists", "Activity log writing"),  # (continued)
    "status_ok": ("Status band", "Locked (green)"), "status_warn": ("Status band", "Trouble (amber)"), "status_bad": ("Status band", "Failed (red)"), "status_fg": ("Status band", "Writing on them"), "warn_fg": ("Status band", "Warnings in windows"),  # (continued)
    "scope_bg": ("Scopes", "Scope background"), "rx_trace": ("Scopes", "Receive trace"), "tx_trace": ("Scopes", "Transmit trace"), "tx_words": ("Scopes", "Transmit scope words"), "scale": ("Scopes", "Scales and numbers"),  # (continued)
    "scale_faint": ("Scopes", "Faint grid lines"), "edge": ("Scopes", "Kestrel band edges"), "time_line": ("Scopes", "Time-mark lines"), "time_text": ("Scopes", "Time-mark writing"), "time_bg": ("Scopes", "Behind time marks"),  # (continued)
    "label": ("Scopes", "Signal names"), "label_bg": ("Scopes", "Behind signal names"), "mark": ("Scopes", "Stations decoded (bracket and callsign)"),  # (continued)
    "meter_low": ("Meters", "Zone: too low"), "meter_ok": ("Meters", "Zone: aim here"), "meter_loud": ("Meters", "Zone: getting loud"), "meter_hot": ("Meters", "Zone: too loud"), "bar_ok": ("Meters", "Bar: good"),  # (continued)
    "bar_loud": ("Meters", "Bar: loud"), "bar_hot": ("Meters", "Bar: too loud, CLIP"), "bar_low": ("Meters", "Bar: too low"), "bar_dim": ("Meters", "Bar: a setting, not a reading"), "peak": ("Meters", "Peak mark"),  # (continued)
    **{f"mode_{k}": ("Recognized signals", f"{k.upper() if len(k) <= 4 else k.capitalize()} band and name") for k in ("kestrel", "ft8", "ft4", "js8", "wspr", "cw", "carrier", "rtty", "psk", "other")},  # (continued: one color per mode)
}  # end of the labels (and "waterfall", the waterfall color set, chosen from a list)
MODE_COLORS = {"kestrel": "#ffd166", "ft8": "#4da3ff", "ft4": "#3fd0e0", "js8": "#c38cff", "wspr": "#5ce07a", "cw": "#ffe14d", "carrier": "#a8b0ba", "rtty": "#ff9f43", "psk": "#ff7ab8", "other": "#d0d0d0"}  # each recognized mode's highlight on the scopes (since 0.37), readable on a dark scope
MODE_COLORS_LIGHT = {"kestrel": "#a06000", "ft8": "#0050c0", "ft4": "#007a8a", "js8": "#7030b0", "wspr": "#107a30", "cw": "#8a7000", "carrier": "#505860", "rtty": "#c05000", "psk": "#b0306a", "other": "#404040"}  # the same, for a light scope
MODE_COLORS_RED = {"kestrel": "#ff8080", "ft8": "#ff5050", "ft4": "#e04040", "js8": "#ff6a6a", "wspr": "#d03030", "cw": "#ff9090", "carrier": "#a02020", "rtty": "#ff7070", "psk": "#e05050", "other": "#c04040"}  # the same in reds only, for Night red
CHOICES = ["system"] + list(THEMES)  # what the operator may pick, System first (a list: the operator's own themes are added to it)
NAMES = {"system": "System (follow Windows)", **{key: value[2] for key, value in THEMES.items()}}  # each, as the operator sees it


def user_file():  # where the operator's own themes are kept
    """Return the path of themes.json in the operator's Kestrel data folder."""
    from .paths import data_dir  # the operator's data folder (imported here so the module loads anywhere)
    import os  # paths
    return os.path.join(data_dir(), "themes.json")  # the file


def _slug(label, taken):  # a key for a new theme
    """Return a key made from `label` that is not in `taken`, beginning "my_" so it never matches a built-in theme."""
    base = "my_" + "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")[:30]  # letters and digits
    key, n = base, 2  # the first try
    while key in taken:  # already used
        key, n = f"{base}_{n}", n + 1  # numbered
    return key  # free


def _clean_colors(colors, allowed):  # keep only real colors
    """Return the entries of `colors` whose key is in `allowed` and whose value is a #rrggbb color (or, for "waterfall", any text)."""
    import re  # checks
    out = {}  # the good ones
    for key, value in (colors or {}).items():  # each
        if key == "waterfall" and key in allowed and isinstance(value, str):  # a waterfall set's name
            out[key] = value  # kept
        elif key in allowed and isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):  # a color
            out[key] = value.lower()  # kept
    return out  # cleaned


def add_program_theme(key, label, base, colors):  # put one of the operator's program themes in the tables
    """Add (or replace) the operator's program theme `key`."""
    THEMES[key] = (base if base in BASES else "dark", _clean_colors(colors, set(COLOR_LABELS) | {"waterfall"}), label)  # the theme (every color the editor offers, mode colors included)
    NAMES[key] = label  # its name
    if key not in CHOICES:  # new
        CHOICES.append(key)  # offered


def add_scope_theme(key, label, colors):  # put one of the operator's scope themes in the tables
    """Add (or replace) the operator's scope theme `key`."""
    SCOPE_THEMES[key] = (_clean_colors(colors, set(SCOPE_KEYS) | {k for k in COLOR_LABELS if k.startswith("mode_")}), label)  # the theme (scope colors, and the recognized modes' colors)
    SCOPE_NAMES[key] = label  # its name


def is_changed(key, scope=False):  # has the operator changed a built-in theme?
    """Return True when the built-in theme `key` differs from how it comes with Kestrel."""
    if scope:  # a scope theme
        return key in ORIGINAL_SCOPES and key in SCOPE_THEMES and (SCOPE_THEMES[key][0] != ORIGINAL_SCOPES[key][0] or SCOPE_THEMES[key][1] != ORIGINAL_SCOPES[key][1])  # colors or name changed
    return key in ORIGINALS and key in THEMES and THEMES[key] != ORIGINALS[key]  # base, colors or name changed


def restore_original(key, scope=False):  # Restore original
    """Put the built-in theme `key` back as it comes with Kestrel."""
    if scope and key in ORIGINAL_SCOPES:  # a scope theme
        colors, label = ORIGINAL_SCOPES[key]  # as it comes
        SCOPE_THEMES[key] = (dict(colors), label)  # restored
        SCOPE_NAMES[key] = label  # and its name
    elif not scope and key in ORIGINALS:  # a program theme
        base, own, label = ORIGINALS[key]  # as it comes
        THEMES[key] = (base, dict(own), label)  # restored
        NAMES[key] = label  # and its name


def remove_theme(key, scope=False):  # forget one of the operator's themes
    """Remove the operator's theme `key` (built-in themes are never removed)."""
    if scope and key in SCOPE_THEMES and key not in BUILT_IN_SCOPES:  # one of theirs
        del SCOPE_THEMES[key]  # gone
        del SCOPE_NAMES[key]  # and its name
    elif not scope and key in THEMES and key not in BUILT_IN:  # one of theirs
        del THEMES[key]  # gone
        del NAMES[key]  # and its name
        CHOICES.remove(key)  # no longer offered


def user_themes():  # the operator's own themes, as they are saved
    """Return {"program": {key: {"name", "base", "colors"}}, "scope": {key: {"name", "colors"}}} for every theme the operator made."""
    return {"program": {k: {"name": v[2], "base": v[0], "colors": dict(v[1])} for k, v in THEMES.items() if k not in BUILT_IN},  # program themes
            "scope": {k: {"name": v[1], "colors": dict(v[0])} for k, v in SCOPE_THEMES.items() if k not in BUILT_IN_SCOPES},  # scope themes
            "changed": {"program": {k: {"name": v[2], "base": v[0], "colors": dict(v[1])} for k, v in THEMES.items() if is_changed(k)},  # built-in program themes the operator changed
                        "scope": {k: {"name": v[1], "colors": dict(v[0])} for k, v in SCOPE_THEMES.items() if is_changed(k, scope=True)}}}  # and built-in scope themes


def save_user(path=None):  # keep the operator's themes
    """Write the operator's own themes to themes.json (or `path`)."""
    import json  # the file's form
    with open(path or user_file(), "w", encoding="utf-8") as handle:  # write it
        json.dump(dict(user_themes(), kind="kestrel-themes"), handle, indent=1, sort_keys=True)  # readable
        handle.write("\n")  # end with a new line


def load_user(path=None, replace=False):  # read the operator's themes (at start, or a file to import)
    """Read themes from themes.json (or `path`) into the tables; return how many were read. With replace=False, a theme whose key is taken gets a new key."""
    import json  # the file's form
    try:  # there may be none, or a damaged one
        with open(path or user_file(), encoding="utf-8") as handle:  # read it
            data = json.load(handle)  # the themes
    except (OSError, ValueError):  # none, or damaged
        return 0  # nothing read
    count = 0  # read so far
    changed = data.get("changed") or {}  # built-in themes the operator changed
    for key, item in (changed.get("program") or {}).items():  # each changed program theme
        if key in BUILT_IN and isinstance(item, dict):  # still one of Kestrel's
            add_program_theme(key, str(item.get("name") or ORIGINALS[key][2])[:60], item.get("base", ORIGINALS[key][0]), item.get("colors"))  # the operator's version
            count += 1  # counted
    for key, item in (changed.get("scope") or {}).items():  # each changed scope theme
        if key in BUILT_IN_SCOPES and key != "theme" and isinstance(item, dict):  # still one of Kestrel's
            add_scope_theme(key, str(item.get("name") or ORIGINAL_SCOPES[key][1])[:60], item.get("colors"))  # the operator's version
            count += 1  # counted
    for key, item in (data.get("program") or {}).items():  # each program theme
        if not isinstance(item, dict):  # not one
            continue  # skipped
        new = key if (replace or key not in THEMES) and key not in BUILT_IN else _slug(str(item.get("name", key)), set(THEMES))  # its key here
        add_program_theme(new, str(item.get("name", key))[:60], item.get("base", "dark"), item.get("colors"))  # added
        count += 1  # counted
    for key, item in (data.get("scope") or {}).items():  # each scope theme
        if not isinstance(item, dict):  # not one
            continue  # skipped
        new = key if (replace or key not in SCOPE_THEMES) and key not in BUILT_IN_SCOPES else _slug(str(item.get("name", key)), set(SCOPE_THEMES))  # its key here
        add_scope_theme(new, str(item.get("name", key))[:60], item.get("colors"))  # added
        count += 1  # counted
    return count  # how many


def export_all(path):  # File > Export themes, and the editor's Export all themes (since 0.37)
    """Write every theme the operator made, and every built-in theme they changed, to `path` (the same form as themes.json, so Import reads it)."""
    import json  # the file's form
    with open(path, "w", encoding="utf-8") as handle:  # write it
        json.dump(dict(user_themes(), kind="kestrel-themes"), handle, indent=1, sort_keys=True)  # readable
        handle.write("\n")  # end with a new line


def export_theme(key, path, scope=False):  # one theme to a file, to give to someone
    """Write the theme `key` (a program or scope theme, built-in or not) to `path` as a themes file another Kestrel can import."""
    import json  # the file's form
    if scope:  # a scope theme
        colors, label = SCOPE_THEMES[key]  # its colors
        data = {"kind": "kestrel-themes", "program": {}, "scope": {key: {"name": label, "colors": dict(colors)}}}  # the file
    else:  # a program theme
        base, own, label = THEMES[key]  # its colors
        data = {"kind": "kestrel-themes", "program": {key: {"name": label, "base": base, "colors": dict(palette(key), **{}) if key in BUILT_IN else dict(own)}}, "scope": {}}  # the file (a built-in theme is written out in full)
        data["program"][key]["colors"] = {k: v for k, v in data["program"][key]["colors"].items() if k in COLOR_LABELS or k == "waterfall"}  # colors only
    with open(path, "w", encoding="utf-8") as handle:  # write it
        json.dump(data, handle, indent=1, sort_keys=True)  # readable
        handle.write("\n")  # end with a new line


def system_prefers_dark():  # what the operating system is set to
    """Return True if Windows is set to dark mode for apps; False elsewhere or if it cannot be told."""
    if sys.platform != "win32":  # only Windows is asked
        return False  # light elsewhere
    try:  # the setting lives in the registry
        import winreg  # the Windows registry
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")  # the personalisation settings
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")  # 1 = light, 0 = dark
        winreg.CloseKey(key)  # done with it
        return value == 0  # dark when apps are not light
    except OSError:  # the value is not there (older Windows)
        return False  # assume light


load_user()  # the operator's own themes join the tables when the program starts (since 0.37)


def resolve(choice):  # turn the operator's choice into a theme's name
    """Return the theme name for `choice` (system follows Windows; an unknown name gives light)."""
    if choice == "system":  # follow the operating system
        return "dark" if system_prefers_dark() else "light"  # whichever it is set to
    return choice if choice in THEMES else "light"  # the choice itself, or light if it is unknown


def palette(choice, scope="theme"):  # every color of a theme
    """Return the full palette of `choice`: its base's colors with the theme's own on top (and the scope theme `scope`'s on the scopes), plus "name" (the theme) and "base" (light or dark)."""
    name = resolve(choice)  # the theme
    base, own, _words = THEMES[name]  # its base and its own colors
    scoped = SCOPE_THEMES.get(scope, SCOPE_THEMES["theme"])[0]  # the scope theme's colors (none when the scopes follow the theme)
    night = scope == "night" or (not scoped and name == "night_red")  # red only on the scopes
    light_scope = scope == "paper" or (not scoped and name in ("contrast_light", "daylight"))  # a light scope
    modes = MODE_COLORS_RED if night else (MODE_COLORS_LIGHT if light_scope else MODE_COLORS)  # each mode's color, readable on that scope
    out = dict(BASES[base])  # the base's colors
    out.update({f"mode_{k}": v for k, v in modes.items()})  # each mode's color
    out.update(own)  # the theme's own colors on top (an operator's theme may set the mode colors too)
    out.update(scoped)  # the scope theme's on the scopes
    out.update(name=name, base=base, scope=scope)  # labeled
    return out  # complete


def apply(root, choice, scope="theme"):  # restyle every themed widget
    """Apply the theme `choice` (and scope theme `scope`) to the whole program and return its palette (a dict of colors, with "name" and "base")."""
    from tkinter import ttk  # the themed widgets
    colors = palette(choice, scope)  # the colors
    style = ttk.Style(root)  # the shared style
    if colors["name"] == "light" and "vista" in style.theme_names():  # the Windows look is available
        style.theme_use("vista")  # use it, so the panel looks like any other Windows program
    else:  # every other theme
        style.theme_use("clam")  # a theme whose colors can all be changed
        c = colors  # shorter name
        style.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"], bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["bg"], troughcolor=c["panel"], focuscolor=c["accent"], selectbackground=c["select"], selectforeground=c["select_fg"], insertcolor=c["fg"])  # every widget's basic colors
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])  # the boxes around groups
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["muted"])  # their titles
        style.configure("TButton", background=c["panel"], foreground=c["fg"], bordercolor=c["border"], padding=(8, 3))  # buttons
        style.map("TButton", background=[("pressed", c["select"]), ("active", c["heading"])], foreground=[("disabled", c["muted"])])  # buttons when pressed, under the mouse, or unavailable
        style.configure("Toolbutton", background=c["panel"], foreground=c["fg"], bordercolor=c["border"], padding=(8, 3), relief="raised")  # push-on, push-off buttons
        style.map("Toolbutton", background=[("selected", c["accent"]), ("active", c["heading"])], foreground=[("selected", c["select_fg"] if c["base"] == "light" else "#ffffff")], relief=[("selected", "sunken")])  # pushed in: accent color
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"], indicatorbackground=c["field"], indicatorforeground=c["fg"])  # tick boxes
        style.map("TCheckbutton", background=[("active", c["bg"])], indicatorbackground=[("selected", c["accent"])])  # ticked
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"], indicatorbackground=c["field"], indicatorforeground=c["fg"])  # choice buttons
        style.map("TRadiobutton", background=[("active", c["bg"])], indicatorbackground=[("selected", c["accent"])])  # chosen
        style.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"])  # text boxes
        style.configure("TSpinbox", fieldbackground=c["field"], foreground=c["fg"], background=c["panel"], arrowcolor=c["fg"])  # number boxes
        style.configure("TCombobox", fieldbackground=c["field"], foreground=c["fg"], background=c["panel"], arrowcolor=c["fg"])  # drop-down lists
        style.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["fg"])], selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])])  # read-only ones look the same
        style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["fg"], bordercolor=c["border"])  # the lists
        style.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["select_fg"])])  # a chosen row
        style.configure("Treeview.Heading", background=c["heading"], foreground=c["fg"], bordercolor=c["border"])  # list headings
        style.map("Treeview.Heading", background=[("active", c["select"])])  # a heading under the mouse
        for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):  # scroll bars, both ways
            style.configure(name, background=c["heading"], troughcolor=c["bg"], arrowcolor=c["fg"], bordercolor=c["border"], lightcolor=c["heading"], darkcolor=c["heading"], gripcount=0)  # thumb on a trough
            style.map(name, background=[("pressed", c["select"]), ("active", c["border"])], lightcolor=[("active", c["border"])], darkcolor=[("active", c["border"])])  # lighter under the mouse
        style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])  # the tabbed Settings window
        style.configure("TNotebook.Tab", background=c["panel"], foreground=c["fg"], padding=(10, 4))  # its tabs
        style.map("TNotebook.Tab", background=[("selected", c["heading"])], foreground=[("selected", c["fg"])])  # the open tab
        style.configure("Vertical.TScale", background=c["heading"], troughcolor=c["field"], lightcolor=c["heading"], darkcolor=c["heading"], bordercolor=c["border"])  # the level sliders
        style.map("Vertical.TScale", background=[("active", c["border"])])  # lighter under the mouse
        style.configure("TPanedwindow", background=c["border"])  # the dividers between panels
        style.configure("Sash", sashthickness=6, gripcount=0, background=c["border"])  # their handles
        style.configure("TProgressbar", background=c["accent"], troughcolor=c["field"], bordercolor=c["border"])  # progress bars
    root.option_add("*TCombobox*Listbox.background", colors["field"])  # the open list of a drop-down (for lists made from now on)
    root.option_add("*TCombobox*Listbox.foreground", colors["fg"])  # its writing
    root.option_add("*TCombobox*Listbox.selectBackground", colors["select"])  # its chosen line
    root.option_add("*TCombobox*Listbox.selectForeground", colors["select_fg"])  # and that line's writing
    root.option_add("*Menu.background", colors["panel"])  # pop-up menus (right-click menus; Windows draws the menu bar itself)
    root.option_add("*Menu.foreground", colors["fg"])  # their writing
    root.option_add("*Menu.activeBackground", colors["select"])  # the item under the mouse
    root.option_add("*Menu.activeForeground", colors["select_fg"])  # and its writing
    root.option_add("*Text.background", colors["text_bg"])  # text areas made from now on
    root.option_add("*Text.foreground", colors["text_fg"])  # their writing
    root.option_add("*Text.insertBackground", colors["text_fg"])  # their cursor
    root.option_add("*Listbox.background", colors["field"])  # plain lists made from now on
    root.option_add("*Listbox.foreground", colors["fg"])  # their writing
    return colors  # for the plain Tk widgets and the scopes


def color_window(window, colors):  # color one window's background and, on Windows, its title bar
    """Set the background of a top-level `window` and make its title bar dark or light to match."""
    window.configure(background=colors["bg"])  # the window's own background
    if sys.platform != "win32":  # title bars are Windows' business only here
        return  # nothing more
    try:  # an older Windows may not know the setting
        import ctypes  # calls into Windows itself
        window.update_idletasks()  # make sure the window exists on screen
        handle = ctypes.windll.user32.GetParent(window.winfo_id())  # the window Windows draws the title bar on
        dark = ctypes.c_int(1 if colors.get("base", colors.get("name")) == "dark" else 0)  # dark title bar or not
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on current Windows, 19 on early Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, attribute, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:  # accepted
                break  # done
    except Exception:  # anything at all: the title bar is only cosmetic
        pass  # leave it as Windows drew it


def recolor_plain(widget, colors):  # restyle plain Tk widgets that already exist (option_add only reaches widgets made later)
    """Give every plain Text, Listbox, Menu and Canvas-less widget under `widget` the palette's colors, and the open lists of drop-downs."""
    from tkinter import ttk  # the themed widgets
    import tkinter as tk  # the plain widgets
    for child in widget.winfo_children():  # every widget inside
        try:  # each kind takes different options
            if isinstance(child, ttk.Combobox):  # a drop-down list
                popdown = child.tk.call("ttk::combobox::PopdownWindow", child)  # the window holding the open list
                child.tk.call(f"{popdown}.f.l", "configure", "-background", colors["field"], "-foreground", colors["fg"], "-selectbackground", colors["select"], "-selectforeground", colors["select_fg"])  # color it
            elif isinstance(child, tk.Text):  # a text area
                child.configure(background=colors["text_bg"], foreground=colors["text_fg"], insertbackground=colors["text_fg"], selectbackground=colors["select"], selectforeground=colors["select_fg"])  # colored
            elif isinstance(child, tk.Listbox):  # a plain list
                child.configure(background=colors["field"], foreground=colors["fg"], selectbackground=colors["select"], selectforeground=colors["select_fg"])  # colored
            elif isinstance(child, tk.Menu):  # a pop-up menu
                child.configure(background=colors["panel"], foreground=colors["fg"], activebackground=colors["select"], activeforeground=colors["select_fg"])  # colored
            elif isinstance(child, tk.Toplevel):  # a window of its own
                color_window(child, colors)  # its background and title bar
        except Exception:  # a widget that takes none of these
            pass  # left alone
        recolor_plain(child, colors)  # and anything inside this widget


def recolor_comboboxes(widget, colors):  # kept for callers from before 0.37
    """Restyle plain widgets and drop-down lists under `widget` (see recolor_plain)."""
    recolor_plain(widget, colors)  # the same
