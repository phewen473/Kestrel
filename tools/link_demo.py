"""Watch two simulated stations make a contact, pass messages and close, while the radio path changes.

Run from the repository root:

    python tools/link_demo.py --scenario slip

Scenarios:
    steady      a good path both ways
    asymmetric  one station hears well, the other poorly
    slip        conditions fall away steadily and then come back
    dropout     the path vanishes for a minute and a half, then returns
    fading      moderate fading on a middling path
    dead        the path dies for good part-way through

It prints every transmission and writes results/link_<scenario>.png.
"""

import argparse  # reads the command-line options
import os  # file paths and folders
import random  # makes the test messages
import sys  # lets us add the repository root to the import path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root (one level above tools/)
sys.path.insert(0, ROOT)  # make "modem", "sim" and "link" importable when run as a script

from link import Path, Station, describe, run_link  # the link layer and its two-station simulation  # noqa: E402

ENGLISH = "Good morning from South Carolina. Weather here is clear and 52 degrees with a light wind from the north. The antenna work is finished and the new feed line is in. How do you copy this evening?"  # an ordinary message, about 190 characters


def random_text(rng, length=200):  # a message that cannot be compressed
    """Return `length` random printable characters."""
    return "".join(chr(rng.randint(33, 126)) for _ in range(length))  # any printable character except space


def slip(t):  # SNR for the "slip" scenario
    """+4 dB for the first 75 s, falling 1 dB every 6 s to -15 dB, held for two minutes, then rising again."""
    if t < 75:  # a good start
        return 4.0  # steady
    bottom = 75 + 19 * 6  # the moment the fall reaches -15 dB
    if t < bottom:  # falling
        return 4.0 - (t - 75) / 6.0  # 1 dB every 6 s
    if t < bottom + 120:  # the trough
        return -15.0  # held
    return min(4.0, -15.0 + (t - bottom - 120) / 6.0)  # rising again at the same rate


def dropout(t):  # SNR for the "dropout" scenario
    """+2 dB, except for a gap from 140 s to 235 s when the path is gone."""
    return -45.0 if 140 <= t < 235 else 2.0  # far below anything decodable during the gap


def dead(t):  # SNR for the "dead" scenario
    """+2 dB until 100 s, then gone for good."""
    return 2.0 if t < 100 else -45.0  # the path never comes back


def build(name):  # set up a scenario
    """Return (path A to B, path B to A, messages from A, messages from B) for the named scenario."""
    rng = random.Random(5)  # repeatable messages
    longs = [random_text(rng) for _ in range(12)]  # twelve full-length messages that do not compress
    if name == "steady":  # a good path both ways
        return Path(3.0, offset_hz=7.0), Path(3.0, offset_hz=-4.0), [ENGLISH, "QSL?"], ["Solid copy here. 73"]  # a short exchange
    if name == "asymmetric":  # one direction strong, the other weak
        return Path(3.0, offset_hz=7.0), Path(-11.0, offset_hz=-4.0), [ENGLISH, "QSL?"], [ENGLISH]  # B hears A well; A hears B poorly
    if name == "slip":  # conditions fall away, then recover
        return Path(slip), Path(slip), longs, ["Reply from the far end."]  # plenty of traffic so the link is busy throughout
    if name == "dropout":  # a gap in the path
        return Path(dropout), Path(dropout), longs[:4], [ENGLISH]  # traffic both ways
    if name == "fading":  # moderate fading
        return Path(-3.0, "moderate"), Path(-3.0, "moderate"), [ENGLISH, "Second message.", longs[0]], ["Reply one.", ENGLISH]  # traffic both ways
    if name == "dead":  # the path dies
        return Path(dead), Path(dead), longs[:5], []  # more traffic than there is time for
    raise ValueError("unknown scenario")  # anything else


def draw(events, path, title, out_path):  # the picture
    """Save a chart: the path's SNR over time, and every transmission as a bar at the height of its speed level."""
    import matplotlib  # plotting library
    matplotlib.use("Agg")  # draw to a file, no window needed
    import matplotlib.pyplot as plt  # the plotting interface

    end = events[-1]["t"] + events[-1]["seconds"]  # when the last transmission finished
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [1, 2]})  # SNR above, levels below
    times = [end * i / 400 for i in range(401)]  # 401 moments across the run
    top.plot(times, [max(path.snr_at(t), -25.0) for t in times], color="black")  # the path's SNR (floored at -25 dB so a dead path stays on the chart)
    top.set_ylabel("SNR in 2.5 kHz (dB)")  # y-axis title
    top.grid(True, alpha=0.3)  # light grid lines
    callers = sorted({e["sender"] for e in events})  # the two callsigns
    colours = dict(zip(callers, ("tab:blue", "tab:orange")))  # one colour each
    for e in events:  # one bar per transmission
        shade = colours[e["sender"]]  # the sender's colour
        bottom.barh(e["level"], e["seconds"], left=e["t"], height=0.6, color=shade if e["heard"] else "white", edgecolor=shade, hatch=None if e["heard"] else "////")  # solid when heard, hatched when lost
    for call in callers:  # legend entries
        bottom.barh(0, 0, color=colours[call], label=call)  # an invisible bar that carries the label
    bottom.barh(0, 0, color="white", edgecolor="grey", hatch="////", label="not decoded")  # legend entry for lost frames
    bottom.set_yticks(range(5))  # one tick per level
    bottom.set_yticklabels([f"L{n}" for n in range(5)])  # named L0 to L4
    bottom.set_ylabel("Speed level of each transmission")  # y-axis title
    bottom.set_xlabel("Time (s)")  # x-axis title
    bottom.grid(True, axis="x", alpha=0.3)  # light vertical grid lines
    bottom.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False)  # legend below the chart, clear of the bars
    fig.suptitle(title)  # overall title
    fig.tight_layout()  # trim the margins
    fig.savefig(out_path, dpi=130)  # save the chart


def main():  # the script itself
    """Run one scenario, print the timeline and save the chart."""
    parser = argparse.ArgumentParser(description="Kestrel two-station link demonstration")  # describe the tool
    parser.add_argument("--scenario", default="slip", choices=["steady", "asymmetric", "slip", "dropout", "fading", "dead"], help="which radio path to simulate")  # the scenario
    parser.add_argument("--seed", type=int, default=1, help="random seed, for a repeatable run")  # repeatability
    args = parser.parse_args()  # read the options
    path_ab, path_ba, from_a, from_b = build(args.scenario)  # the paths and the traffic
    a = Station("KO4WSC", "EM92")  # the station that calls
    b = Station("W1AW", "FN31")  # the station that answers
    a.beacon()  # A beacons
    b.listen()  # B listens
    for text in from_a:  # A's traffic
        a.queue(text)  # into A's outbox
    for text in from_b:  # B's traffic
        b.queue(text)  # into B's outbox
    events = run_link(a, b, path_ab, path_ba, seed=args.seed)  # run the contact
    print("\n".join(describe(events)))  # every transmission
    print()  # blank line
    print("\n".join(sorted(a.log + b.log)))  # what each station decided, in time order
    print()  # blank line
    airtime = sum(e["seconds"] for e in events)  # total transmitting time
    print(f"{a.call}: {a.state}, delivered {len(a.delivered)} of {len(from_a)}, received {len(a.inbox)}")  # A's summary
    print(f"{b.call}: {b.state}, delivered {len(b.delivered)} of {len(from_b)}, received {len(b.inbox)}")  # B's summary
    print(f"{len(events)} transmissions, {airtime:.0f} s on the air, {sum(not e['heard'] for e in events)} not decoded")  # totals
    out_dir = os.path.join(ROOT, "results")  # where the chart goes
    os.makedirs(out_dir, exist_ok=True)  # create the folder if needed
    out_path = os.path.join(out_dir, f"link_{args.scenario}.png")  # the chart file
    draw(events, path_ab, f"Kestrel link, scenario: {args.scenario}", out_path)  # draw it
    print("wrote", out_path)  # say where it went


if __name__ == "__main__":  # only when run as a script
    main()  # go
