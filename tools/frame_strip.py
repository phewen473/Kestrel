"""Drawing the frame strip under the receive scope (since 0.37). What to draw comes from live.framestrip.FrameStrip.view()."""

BLOCKS = 80  # the body is drawn as at most this many blocks
NAMES = ("Preamble", "Header", "Body", "Header again")  # the four segments
SCORE = {"good": 2, "fair": 1, "bad": 0}  # a body tone's state as a number, for averaging into blocks
STATE = ("bad", "fair", "good")  # and back


def blocks(clarity, count):  # the body tones received, gathered into `count` blocks
    """Return `count` block states from the tone states in `clarity` (each block the average of its tones)."""
    n = len(clarity)  # tones
    if count <= 0 or n == 0:  # nothing
        return []  # no blocks
    out = []  # the blocks
    for j in range(count):  # each block
        a, b = j * n // count, max((j + 1) * n // count, j * n // count + 1)  # its tones
        part = clarity[a:min(b, n)]  # them
        out.append(STATE[round(sum(SCORE[s] for s in part) / len(part))] if part else "wait")  # their average
    return out  # all


def draw(c, v, colors, x, y, w):  # the strip, on canvas `c` at (x, y), `w` wide
    """Draw the view `v` (FrameStrip.view()) in the theme's `colors`."""
    good, fair, bad = colors["status_ok"], colors["status_warn"], colors["status_bad"]  # passed, weak, failed
    now, dim, edge = colors["accent"], colors["field"], colors["border"]  # arriving, empty, borders
    text, muted, on = colors["fg"], colors["muted"], colors["status_fg"]  # writing, quieter writing, writing on a colored segment
    fills = {"good": good, "fair": fair, "bad": bad}  # finished segments' colors
    c.delete("all")  # start again
    c.create_text(x, y, text=v["title"], anchor="nw", fill=text, font=("Segoe UI", 9, "bold"))  # what is happening
    c.create_text(x + w - 170, y, text=v.get("right", ""), anchor="ne", fill=muted, font=("Segoe UI", 9))  # level, strength, offset, time
    bar = w - 180  # the frame bar; the message's parts sit to its right
    widths = [80, 80, max(bar - 240, 120), 80]  # preamble, header, body, header again
    left = x  # running edge
    for i, (seg_w, name) in enumerate(zip(widths, NAMES)):  # each segment
        state = v["segs"][i]  # its state
        x0, x1, y0, y1 = left, left + seg_w - 3, y + 18, y + 40  # its box
        if i == 2 and state in ("now", "good", "bad", "fair", "cut") and v.get("progress") is not None and v.get("clarity"):  # the body, block by block
            count = round(BLOCKS * v["progress"])  # blocks arrived
            bw = (x1 - x0) / BLOCKS  # each one's width
            c.create_rectangle(x0, y0, x1, y1, fill=dim, outline=bad if state == "cut" else edge, dash=(4, 3) if state == "cut" else (), width=2 if state == "cut" else 1)  # the empty body
            for b, s in enumerate(blocks(v["clarity"], count)):  # each block arrived
                c.create_rectangle(x0 + b * bw, y0 + 1, x0 + (b + 1) * bw - 1, y1 - 1, fill=fills.get(s, dim), outline="")  # how clearly it came through
            mark = x0 + count * bw  # where it has got to
            if state == "now":  # still arriving
                c.create_line(mark, y0 - 4, mark, y1 + 4, fill=now, width=2)  # the edge of what has arrived
            if state == "cut":  # the signal went part way
                for hx in range(int(mark) - 22, int(x1), 9):  # hatching over what never came
                    c.create_line(max(hx, mark), y1 - max(0, mark - hx), min(hx + 22, x1), y0 + max(0, hx + 22 - x1), fill=edge)  # a slanted line, kept in the box
                c.create_line(mark, y0 - 4, mark, y1 + 4, fill=bad, width=2)  # where it stopped
            if state == "bad":  # finished and failed
                c.create_rectangle(x0, y0, x1, y1, outline=bad, width=2)  # a red edge
        elif i == 2 and state == "now" and v.get("progress") is not None:  # a body with no readings (a long beacon)
            c.create_rectangle(x0, y0, x1, y1, fill=dim, outline=now, width=2)  # outlined
            c.create_rectangle(x0 + 2, y0 + 2, x0 + 2 + (x1 - x0 - 4) * v["progress"], y1 - 2, fill=now, outline="")  # filling
        elif state == "now":  # arriving: part filled
            c.create_rectangle(x0, y0, x1, y1, fill=dim, outline=now, width=2)  # outlined
            c.create_rectangle(x0 + 2, y0 + 2, x0 + 2 + (x1 - x0 - 4) * (v.get("header_fill") or 0.0), y1 - 2, fill=now, outline="")  # filling
        elif state == "unknown":  # the body before a header is read: its length is not known
            c.create_rectangle(x0, y0, x1, y1, fill=dim, outline=edge, dash=(3, 3))  # dashed
        elif state == "missing":  # never arrived
            c.create_rectangle(x0, y0, x1, y1, fill=dim, outline=bad, dash=(4, 3), width=2)  # dashed red edge
        elif state == "none":  # this kind of frame has none (a long beacon's header)
            c.create_rectangle(x0, y0, x1, y1, fill="", outline=edge, dash=(2, 4))  # faint
        else:  # waiting, or finished
            c.create_rectangle(x0, y0, x1, y1, fill=fills.get(state, dim), outline=edge)  # solid
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=name, fill=on if state in fills and i != 2 else text, font=("Segoe UI", 8, "bold"))  # its name
        c.create_text(x0 + 2, y1 + 4, text=v["notes"][i], anchor="nw", fill=muted if state in ("wait", "unknown", "none") else text, font=("Segoe UI", 8), width=seg_w - 4)  # what was found in it
        left += seg_w  # next
    px = x + w - 165  # the message's parts
    if v.get("parts"):  # a message is being followed
        c.create_text(px, y, text="Message parts", anchor="nw", fill=muted, font=("Segoe UI", 8))  # their title
    for k, part in enumerate(v.get("parts", [])[:8]):  # each part (eight at most)
        bx = px + k * 20  # its place
        line = bad if part == "missing" else edge  # its border
        c.create_rectangle(bx, y + 18, bx + 16, y + 40, fill=fills.get(part, dim), outline=line, width=2 if part == "missing" else 1, dash=(3, 2) if part == "missing" else ())  # its box
        c.create_text(bx + 8, y + 29, text="?" if part == "missing" else str(k + 1), fill=on if part in fills else bad if part == "missing" else muted, font=("Segoe UI", 8, "bold"))  # its number, or ? when never heard
    if v.get("done"):  # something to say about the message
        c.create_text(px, y + 44, text=v["done"], anchor="nw", fill={"good": good, "fair": fair, "bad": bad}.get(v.get("done_tone"), text), font=("Segoe UI", 8, "bold"), width=165)  # said
