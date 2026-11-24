"""The theme editor of the control panel (since 0.37): View > Edit themes...

The operator can make, change, rename, delete, export and import their own
program themes and scope themes, and change the themes that come with Kestrel
too: those changes are kept apart, and Restore original puts a built-in theme
back as it came. Built-in themes cannot be deleted. Every
color of a theme is listed by what it colors, in groups, with a swatch: click
the swatch (or type #rrggbb) to change it. While "Show changes on the panel"
is ticked the panel takes each change at once, so the result can be judged
in place; Save keeps the theme in themes.json in the Kestrel data folder.
"""

import re  # color checks
import tkinter as tk  # the toolkit
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk  # pickers, dialogs and themed widgets

from live import theme  # the themes


def open_theme_editor(panel):  # View > Edit themes...
    """Open the theme editor for `panel` (a kestrel_panel.Panel)."""
    top = panel.window("themes", "Kestrel - edit themes")  # a window of its own
    state = {"scope": False, "key": None, "work": {}, "name": "", "base": "dark"}  # what is being edited
    kind = tk.StringVar(value="program")  # program or scope themes
    head = ttk.Frame(top, padding=8)  # the top row
    head.pack(fill="x")  # across the window
    ttk.Radiobutton(head, text="Program themes (the whole window)", value="program", variable=kind, command=lambda: fill_list()).pack(side="left")  # one kind
    ttk.Radiobutton(head, text="Scope themes (the two scopes and the meters)", value="scope", variable=kind, command=lambda: fill_list()).pack(side="left", padx=(12, 0))  # the other
    live = tk.BooleanVar(value=True)  # show changes on the panel as they are made
    ttk.Checkbutton(head, text="Show changes on the panel", variable=live).pack(side="right")  # its box
    body = ttk.Frame(top, padding=(8, 0, 8, 8))  # the list and the editor side by side
    body.pack(fill="both", expand=True)  # filling the window
    left = ttk.Frame(body)  # the list of themes and its buttons
    left.pack(side="left", fill="y")  # down the left
    listing = ttk.Treeview(left, columns=("name", "who"), show="headings", height=22, selectmode="browse")  # the themes
    listing.heading("name", text="Theme")  # its name
    listing.heading("who", text="")  # built in or the operator's
    listing.column("name", width=230)  # wide enough
    listing.column("who", width=70)  # narrow
    listing.pack(fill="y", expand=True)  # the list
    buttons = ttk.Frame(left)  # the list's buttons
    buttons.pack(fill="x", pady=(6, 0))  # under it
    right = ttk.Frame(body)  # the editor
    right.pack(side="left", fill="both", expand=True, padx=(10, 0))  # the rest of the window
    title = ttk.Label(right, text="", font="KestrelBig")  # the theme's name
    title.pack(anchor="w")  # at the top
    note = ttk.Label(right, text="", justify="left")  # a word on what can be done
    note.pack(anchor="w", pady=(0, 6))  # under it
    meta = ttk.Frame(right)  # name, base and waterfall set
    meta.pack(fill="x")  # across
    ttk.Label(meta, text="Name").grid(row=0, column=0, sticky="w")  # label
    name_box = ttk.Entry(meta, width=34)  # the name
    name_box.grid(row=0, column=1, sticky="w", padx=(4, 16))  # place it
    base_label = ttk.Label(meta, text="Built on")  # label
    base_label.grid(row=0, column=2, sticky="w")  # place it
    base_box = ttk.Combobox(meta, values=["light", "dark"], state="readonly", width=8)  # light or dark base (title bar, and colors left unset)
    base_box.grid(row=0, column=3, sticky="w", padx=(4, 16))  # place it
    ttk.Label(meta, text="Waterfall colors").grid(row=0, column=4, sticky="w")  # label
    fall_box = ttk.Combobox(meta, values=list(panel.waterfall_sets()), state="readonly", width=34)  # the waterfall set that goes with it
    fall_box.grid(row=0, column=5, sticky="w", padx=(4, 0))  # place it
    holder = ttk.Frame(right)  # the scrolling list of colors
    holder.pack(fill="both", expand=True, pady=(8, 0))  # the rest
    canvas = tk.Canvas(holder, highlightthickness=0, background=panel.colors["bg"])  # scrolls the rows
    bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)  # its scroll bar
    rows = ttk.Frame(canvas)  # the rows themselves
    rows.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))  # scroll as far as the rows go
    canvas.create_window((0, 0), window=rows, anchor="nw")  # the rows inside
    canvas.configure(yscrollcommand=bar.set)  # linked
    canvas.pack(side="left", fill="both", expand=True)  # place it
    bar.pack(side="right", fill="y")  # and the bar
    canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(-1 * (event.delta // 120), "units") if str(event.widget).startswith(str(top)) else None)  # the wheel scrolls the colors
    foot = ttk.Frame(right)  # Save and the rest
    foot.pack(fill="x", pady=(8, 0))  # at the foot
    swatches = {}  # color key -> (its swatch, its text box)

    def keys():  # the colors this kind of theme has
        """Return the color keys the theme being edited sets, in the editor's order."""
        if state["scope"]:  # a scope theme
            wanted = set(theme.SCOPE_KEYS) | {k for k in theme.COLOR_LABELS if k.startswith("mode_")}  # scope colors and mode colors
            return [k for k in theme.COLOR_LABELS if k in wanted]  # in order
        return list(theme.COLOR_LABELS)  # every color

    def table():  # the themes of the kind chosen
        return theme.SCOPE_THEMES if state["scope"] else theme.THEMES  # scope or program

    def built_in(key):  # does it come with Kestrel?
        return key in (theme.BUILT_IN_SCOPES if state["scope"] else theme.BUILT_IN)  # yes or no

    def full_colors(key):  # every color of a theme, as it shows
        """Return the theme's full set of colors (what the panel would use)."""
        if state["scope"]:  # a scope theme: on top of the program theme in use
            return theme.palette(panel.settings["theme"], key)  # its colors
        return theme.palette(key, "theme")  # a program theme on its own

    def fill_list(select=None):  # the list of themes
        state["scope"] = kind.get() == "scope"  # which kind
        listing.delete(*listing.get_children())  # empty it
        for key in table():  # each theme
            if state["scope"] and key == "theme":  # "follow the program theme" is not a theme to edit
                continue  # left out
            label = (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[key]  # its name
            listing.insert("", "end", iid=key, values=(label, ("changed" if theme.is_changed(key, scope=state["scope"]) else "built in") if built_in(key) else "yours"))  # one row
        children = listing.get_children()  # the rows
        pick = select if select in children else (children[0] if children else None)  # the one to show
        if pick:  # there is one
            listing.selection_set(pick)  # chosen
            listing.see(pick)  # in view
            show(pick)  # shown

    def show(key):  # put a theme in the editor
        state["key"] = key  # the theme
        colors = full_colors(key)  # all its colors
        state["work"] = {k: colors[k] for k in keys() if k in colors}  # a working copy
        state["work"]["waterfall"] = colors.get("waterfall", "Classic")  # and its waterfall set
        state["start"] = dict(state["work"])  # as it was when opened, to tell whether anything changed
        label = (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[key]  # its name
        title.configure(text=label)  # shown
        mine = True  # every theme can be changed (since 0.37: built-in ones too)
        note.configure(text="Your theme: change any color below, then Save." if not built_in(key) else "This theme comes with Kestrel. Change any color below and Save; your changes are kept apart, and Restore original puts it back as it came.")  # what can be done
        name_box.configure(state="normal")  # allow writing
        name_box.delete(0, "end")  # empty
        name_box.insert(0, label)  # its name
        name_box.configure(state="normal" if mine else "disabled")  # editable only if theirs
        base_box.set(table()[key][0] if not state["scope"] else "")  # light or dark
        base_box.configure(state="readonly" if mine and not state["scope"] else "disabled")  # editable only for their program themes
        base_label.configure(text="" if state["scope"] else "Built on")  # scope themes have no base
        fall_box.set(state["work"]["waterfall"])  # its waterfall set
        fall_box.configure(state="readonly" if mine else "disabled")  # editable only if theirs
        for child in rows.winfo_children():  # the old rows
            child.destroy()  # gone
        swatches.clear()  # forgotten
        group = None  # the group being drawn
        r = 0  # the row
        for k in keys():  # each color
            g, words = theme.COLOR_LABELS[k]  # its group and what it colors
            if g != group:  # a new group
                group = g  # this one
                ttk.Label(rows, text=g, font="KestrelSmallBold").grid(row=r, column=0, columnspan=3, sticky="w", pady=(8 if r else 0, 2))  # its heading
                r += 1  # next row
            ttk.Label(rows, text=words).grid(row=r, column=0, sticky="w", padx=(12, 8))  # what it colors
            swatch = tk.Label(rows, width=6, background=state["work"].get(k, "#000000"), relief="solid", borderwidth=1, cursor="hand2" if mine else "")  # the color itself
            swatch.grid(row=r, column=1, padx=4, pady=1)  # place it
            text = ttk.Entry(rows, width=9)  # the color as #rrggbb
            text.insert(0, state["work"].get(k, ""))  # its value
            text.grid(row=r, column=2, sticky="w")  # place it
            text.configure(state="normal" if mine else "disabled")  # editable only if theirs
            if mine:  # can be changed
                swatch.bind("<Button-1>", lambda event, key=k: pick(key))  # a click opens the color picker
                text.bind("<Return>", lambda event, key=k: typed(key))  # Enter takes a typed color
                text.bind("<FocusOut>", lambda event, key=k: typed(key))  # so does leaving the box
            swatches[k] = (swatch, text)  # kept
            r += 1  # next row

    def set_color(key, value):  # one color changed
        state["work"][key] = value  # in the working copy
        swatch, text = swatches[key]  # its widgets
        swatch.configure(background=value)  # shown
        text.delete(0, "end")  # the box...
        text.insert(0, value)  # ...says it too
        if live.get():  # show it on the panel at once
            preview()  # applied

    def pick(key):  # the color picker
        chosen = colorchooser.askcolor(color=state["work"].get(key), title=theme.COLOR_LABELS[key][1], parent=top)  # ask
        if chosen and chosen[1]:  # a color was chosen
            set_color(key, chosen[1].lower())  # taken

    def typed(key):  # a color typed as #rrggbb
        value = swatches[key][1].get().strip()  # what was typed
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):  # a color
            if value.lower() != state["work"].get(key):  # changed
                set_color(key, value.lower())  # taken
        else:  # not a color
            swatches[key][1].delete(0, "end")  # put the old one back
            swatches[key][1].insert(0, state["work"].get(key, ""))  # as it was

    def register():  # put the working copy in the tables (not yet saved to the file)
        key = state["key"]  # the theme
        label_now = (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[key]  # its name now
        same = state["work"] == state.get("start") and (fall_box.get() or state["work"].get("waterfall")) == state["start"].get("waterfall") and (name_box.get().strip() or label_now) == label_now and (state["scope"] or (base_box.get() or "dark") == table()[key][0])  # nothing changed
        if built_in(key) and same:  # a built-in theme left as it is
            return  # not stored as a change
        colors = dict(state["work"], waterfall=fall_box.get() or state["work"].get("waterfall", "Classic"))  # its colors
        label = name_box.get().strip() or (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[key]  # its name
        if state["scope"]:  # a scope theme
            theme.add_scope_theme(key, label, colors)  # in the table
        else:  # a program theme
            theme.add_program_theme(key, label, base_box.get() or "dark", colors)  # in the table

    def preview():  # show the theme being edited on the panel
        register()  # the working copy, in the tables
        if state["scope"]:  # a scope theme
            panel.apply_look(panel.settings["theme"], state["key"])  # the scopes show it
        else:  # a program theme
            panel.apply_look(state["key"], panel.settings.get("scope_theme", "theme"))  # the whole window shows it

    def save():  # Save
        register()  # into the tables
        theme.save_user()  # into themes.json
        panel.refresh_theme_menus()  # the View menu lists it under its name
        fill_list(state["key"])  # the list too
        if state["scope"] and panel.settings.get("scope_theme") == state["key"] or not state["scope"] and panel.settings["theme"] == state["key"]:  # the theme in use
            panel.apply_look(panel.settings["theme"], panel.settings.get("scope_theme", "theme"))  # shown as saved
        messagebox.showinfo("Kestrel", "Theme saved.", parent=top)  # said

    def use():  # Use it
        key = state["key"]  # the theme
        register()  # keep the edits first
        theme.save_user()  # and the file
        panel.refresh_theme_menus()  # the menus
        if state["scope"]:  # a scope theme
            panel.set_scope_theme(key)  # used and remembered
        else:  # a program theme
            panel.set_theme(key)  # used and remembered

    def copy():  # Copy to a new theme
        old = (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[state["key"]]  # the name of the one copied
        label = simpledialog.askstring("Kestrel", "Name of the new theme:", initialvalue=f"My {old}", parent=top)  # ask for a name
        if not label:  # none given
            return  # nothing done
        new = theme._slug(label.strip(), set(table()))  # a key for it
        colors = dict(state["work"], waterfall=state["work"].get("waterfall", "Classic"))  # the colors copied
        if state["scope"]:  # a scope theme
            theme.add_scope_theme(new, label.strip()[:60], colors)  # added
        else:  # a program theme
            theme.add_program_theme(new, label.strip()[:60], table()[state["key"]][0], colors)  # added
        theme.save_user()  # kept
        panel.refresh_theme_menus()  # in the menus
        fill_list(new)  # shown, ready to change

    def rename():  # Rename (a built-in theme too; Restore original gives its name back)
        label = simpledialog.askstring("Kestrel", "New name:", initialvalue=name_box.get(), parent=top)  # ask
        if label:  # given
            name_box.delete(0, "end")  # the box
            name_box.insert(0, label.strip()[:60])  # the new name
            register()  # into the tables
            theme.save_user()  # kept
            panel.refresh_theme_menus()  # in the menus
            fill_list(state["key"])  # in the list

    def delete():  # Delete
        key = state["key"]  # the theme
        if built_in(key):  # one of Kestrel's
            messagebox.showinfo("Kestrel", "Themes that come with Kestrel cannot be deleted. Restore original puts one back as it came.", parent=top)  # say so
            return  # nothing done
        label = (theme.SCOPE_NAMES if state["scope"] else theme.NAMES)[key]  # its name
        if not messagebox.askyesno("Kestrel", f"Delete the theme \"{label}\"? This cannot be undone.", parent=top):  # make sure
            return  # kept
        in_use = (panel.settings.get("scope_theme") == key) if state["scope"] else (panel.settings["theme"] == key)  # the one in use?
        theme.remove_theme(key, scope=state["scope"])  # gone
        theme.save_user()  # from the file too
        panel.refresh_theme_menus()  # and the menus
        if in_use and state["scope"]:  # its scope theme was in use
            panel.set_scope_theme("theme")  # the scopes follow the program theme again
        elif in_use:  # its program theme was in use
            panel.set_theme("dark")  # back to a built-in one
        fill_list()  # the list again

    def export():  # Export...
        path = filedialog.asksaveasfilename(parent=top, title="Export theme", defaultextension=".json", initialfile=f"kestrel-theme-{state['key']}.json", filetypes=[("Kestrel themes", "*.json")])  # where
        if path:  # chosen
            theme.export_theme(state["key"], path, scope=state["scope"])  # written
            messagebox.showinfo("Kestrel", "Theme exported. Another Kestrel station can load it with Import.", parent=top)  # said

    def export_all():  # Export all themes... (since 0.37)
        panel.export_themes()  # the same as File > Export themes: every theme of the operator's and every changed built-in one, as the list shows them now

    def import_():  # Import...
        path = filedialog.askopenfilename(parent=top, title="Import themes", filetypes=[("Kestrel themes", "*.json"), ("All files", "*.*")])  # which file
        if not path:  # none
            return  # nothing done
        count = theme.load_user(path)  # read into the tables (a theme whose key is taken gets a new one)
        if not count:  # nothing usable
            messagebox.showerror("Kestrel", "That file holds no Kestrel themes.", parent=top)  # say so
            return  # nothing done
        theme.save_user()  # kept
        panel.refresh_theme_menus()  # in the menus
        fill_list()  # the list
        messagebox.showinfo("Kestrel", f"{count} theme(s) imported.", parent=top)  # said

    def restore():  # Restore original
        key = state["key"]  # the theme
        if not built_in(key):  # one of theirs: nothing to go back to
            messagebox.showinfo("Kestrel", "Only themes that come with Kestrel can be restored. Your own themes can be deleted instead.", parent=top)  # say so
            return  # nothing done
        if not messagebox.askyesno("Kestrel", "Put this theme back as it comes with Kestrel? Your changes to it will be lost.", parent=top):  # make sure
            return  # kept
        theme.restore_original(key, scope=state["scope"])  # restored
        theme.save_user()  # the file no longer holds the changes
        panel.refresh_theme_menus()  # its name, in the menus
        panel.apply_look(panel.settings["theme"], panel.settings.get("scope_theme", "theme"))  # the panel as it now is
        fill_list(key)  # the list and the editor

    def revert():  # Close without saving: the panel goes back to what was in use
        panel.apply_look(panel.settings["theme"], panel.settings.get("scope_theme", "theme"))  # as saved
        for key in list(theme.BUILT_IN):  # unsaved edits to built-in themes are dropped...
            theme.restore_original(key)  # ...by putting them back...
        for key in list(theme.BUILT_IN_SCOPES):  # (scope themes too)
            theme.restore_original(key, scope=True)  # ...as they came...
        theme.load_user(replace=True)  # ...and reading the saved file again (saved changes and the operator's own themes)
        panel.refresh_theme_menus()  # menus as saved
        top.destroy()  # closed

    for text, command in (("Use it", use), ("Copy to a new theme", copy), ("Rename", rename), ("Restore original", restore), ("Delete", delete), ("Export this theme...", export), ("Export all themes...", export_all), ("Import themes...", import_)):  # the list's buttons
        ttk.Button(buttons, text=text, command=command).pack(fill="x", pady=1)  # one each
    ttk.Button(foot, text="Save", command=save).pack(side="left")  # keep the changes
    ttk.Button(foot, text="Close", command=revert).pack(side="right")  # close, dropping unsaved changes
    fall_box.bind("<<ComboboxSelected>>", lambda event: (state["work"].__setitem__("waterfall", fall_box.get()), preview() if live.get() else None))  # a new waterfall set
    base_box.bind("<<ComboboxSelected>>", lambda event: preview() if live.get() else None)  # a new base
    listing.bind("<<TreeviewSelect>>", lambda event: show(listing.selection()[0]) if listing.selection() else None)  # a theme picked
    top.protocol("WM_DELETE_WINDOW", revert)  # the window's own close button drops unsaved changes too
    kind.set("program")  # program themes first
    fill_list(panel.settings["theme"])  # the list, with the theme in use chosen
