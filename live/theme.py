"""Light and dark looks for the control panel, and following the operating system's choice.

The panel offers three choices under View > Theme: System (follow
Windows' own light or dark setting), Light and Dark. The themed (ttk)
widgets are restyled through one shared style; the few plain Tk widgets
(the log, the status band, the scope's surround) are colored by the
panel from the palette returned here. On Windows the title bar is turned
dark too. Windows draws the menu bar and its menus itself, so those keep
the system's colors.
"""

import sys  # which operating system this is

PALETTES = {  # the colors of each look
    "light": {"bg": "#f3f3f3", "panel": "#ffffff", "field": "#ffffff", "fg": "#1a1a1a", "muted": "#555555", "accent": "#0a64c8",  # (continued)
              "select": "#cce4ff", "select_fg": "#000000", "border": "#c8c8c8", "heading": "#e6e6e6", "text_bg": "#ffffff", "text_fg": "#1a1a1a"},  # light
    "dark": {"bg": "#1e2227", "panel": "#262b31", "field": "#2d333b", "fg": "#d8dee6", "muted": "#9aa4b0", "accent": "#4c9aff",  # (continued)
             "select": "#2f5d8a", "select_fg": "#ffffff", "border": "#3a414a", "heading": "#323840", "text_bg": "#171a1e", "text_fg": "#d8dee6"},  # dark
}
CHOICES = ("system", "light", "dark")  # what the operator may pick


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


def resolve(choice):  # turn the operator's choice into "light" or "dark"
    """Return "dark" or "light" for `choice` (system, light or dark)."""
    if choice == "system":  # follow the operating system
        return "dark" if system_prefers_dark() else "light"  # whichever it is set to
    return choice if choice in PALETTES else "light"  # the choice itself, or light if it is unknown


def apply(root, choice):  # restyle every themed widget
    """Apply the look `choice` to the whole program and return its palette (a dict of colors), with "name" set to light or dark."""
    from tkinter import ttk  # the themed widgets
    name = resolve(choice)  # light or dark
    colors = dict(PALETTES[name], name=name)  # the palette, labeled
    style = ttk.Style(root)  # the shared style
    if name == "light" and "vista" in style.theme_names():  # Windows' own look is available
        style.theme_use("vista")  # use it for light, so the panel looks like any other Windows program
    else:  # dark, or not on Windows
        style.theme_use("clam")  # a theme whose colors can all be changed
        c = colors  # shorter name
        style.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"], bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["bg"], troughcolor=c["panel"], focuscolor=c["accent"], selectbackground=c["select"], selectforeground=c["select_fg"], insertcolor=c["fg"])  # every widget's basic colors
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])  # the boxes around groups
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["muted"])  # their titles
        style.configure("TButton", background=c["panel"], foreground=c["fg"], bordercolor=c["border"], padding=(8, 3))  # buttons
        style.map("TButton", background=[("pressed", c["select"]), ("active", c["heading"])], foreground=[("disabled", c["muted"])])  # buttons when pressed, under the mouse, or unavailable
        style.configure("Toolbutton", background=c["panel"], foreground=c["fg"], bordercolor=c["border"], padding=(8, 3), relief="raised")  # push-on, push-off buttons
        style.map("Toolbutton", background=[("selected", c["accent"]), ("active", c["heading"])], foreground=[("selected", "#ffffff")], relief=[("selected", "sunken")])  # pushed in: accent color
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"], indicatorbackground=c["field"], indicatorforeground=c["fg"])  # tick boxes
        style.map("TCheckbutton", background=[("active", c["bg"])], indicatorbackground=[("selected", c["accent"])])  # ticked
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"], indicatorbackground=c["field"], indicatorforeground=c["fg"])  # choice buttons
        style.map("TRadiobutton", background=[("active", c["bg"])], indicatorbackground=[("selected", c["accent"])])  # chosen
        style.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"])  # text boxes
        style.configure("TCombobox", fieldbackground=c["field"], foreground=c["fg"], background=c["panel"], arrowcolor=c["fg"])  # drop-down lists
        style.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["fg"])], selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])])  # read-only ones look the same
        style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["fg"], bordercolor=c["border"])  # the lists
        style.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["select_fg"])])  # a chosen row
        style.configure("Treeview.Heading", background=c["heading"], foreground=c["fg"], bordercolor=c["border"])  # list headings
        style.map("Treeview.Heading", background=[("active", c["select"])])  # a heading under the mouse
        for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):  # scroll bars, both ways
            style.configure(name, background=c["heading"], troughcolor=c["bg"], arrowcolor=c["fg"], bordercolor=c["border"], lightcolor=c["heading"], darkcolor=c["heading"], gripcount=0)  # dark thumb on a darker trough
            style.map(name, background=[("pressed", c["select"]), ("active", c["border"])], lightcolor=[("active", c["border"])], darkcolor=[("active", c["border"])])  # lighter under the mouse
        style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])  # the tabbed Settings window
        style.configure("TNotebook.Tab", background=c["panel"], foreground=c["fg"], padding=(10, 4))  # its tabs
        style.map("TNotebook.Tab", background=[("selected", c["heading"])], foreground=[("selected", c["fg"])])  # the open tab
        style.configure("Vertical.TScale", background=c["heading"], troughcolor=c["field"], lightcolor=c["heading"], darkcolor=c["heading"], bordercolor=c["border"])  # the level sliders
        style.map("Vertical.TScale", background=[("active", c["border"])])  # lighter under the mouse
    root.option_add("*TCombobox*Listbox.background", colors["field"])  # the open list of a drop-down (for lists made from now on)
    root.option_add("*TCombobox*Listbox.foreground", colors["fg"])  # its writing
    root.option_add("*TCombobox*Listbox.selectBackground", colors["select"])  # its chosen line
    root.option_add("*TCombobox*Listbox.selectForeground", colors["select_fg"])  # and that line's writing
    return colors  # for the plain Tk widgets


def color_window(window, colors):  # color one window's background and, on Windows, its title bar
    """Set the background of a top-level `window` and make its title bar dark or light to match."""
    window.configure(background=colors["bg"])  # the window's own background
    if sys.platform != "win32":  # title bars are Windows' business only here
        return  # nothing more
    try:  # an older Windows may not know the setting
        import ctypes  # calls into Windows itself
        window.update_idletasks()  # make sure the window exists on screen
        handle = ctypes.windll.user32.GetParent(window.winfo_id())  # the window Windows draws the title bar on
        dark = ctypes.c_int(1 if colors["name"] == "dark" else 0)  # dark title bar or not
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on current Windows, 19 on early Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, attribute, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:  # accepted
                break  # done
    except Exception:  # anything at all: the title bar is only cosmetic
        pass  # leave it as Windows drew it


def recolor_comboboxes(widget, colors):  # restyle drop-down lists that already exist
    """Give the open lists of every drop-down under `widget` the palette's colors (option_add only reaches lists made later)."""
    from tkinter import ttk  # the themed widgets
    for child in widget.winfo_children():  # every widget inside
        if isinstance(child, ttk.Combobox):  # a drop-down list
            try:  # Tk builds the open list on demand
                popdown = child.tk.call("ttk::combobox::PopdownWindow", child)  # the window holding the open list
                child.tk.call(f"{popdown}.f.l", "configure", "-background", colors["field"], "-foreground", colors["fg"], "-selectbackground", colors["select"], "-selectforeground", colors["select_fg"])  # color it
            except Exception:  # an older Tk names it differently
                pass  # it will look plain until the panel is reopened
        recolor_comboboxes(child, colors)  # and anything inside this widget
