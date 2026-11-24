"""HF propagation predictions for Kestrel's bands, by Recommendation ITU-R P.533 (since 0.31R5).

Kestrel runs the ITU's own program, ITURHFProp (built by tools/build_prop.py,
shipped in the program's "prop" folder when installed), for a path between
two grid locators: one month, every hour, Kestrel's calling frequency on
each band. It writes the program an input file and reads back its CSV
table. From the table it works out, for each band and hour:

  * the median signal-to-noise ratio, in 2.5 kHz like every Kestrel figure
    (the program is asked for a 2500 Hz bandwidth, so no conversion);
  * the SNR reached on 9 days in 10 (the "SNR90");
  * the reliability: the chance (per cent of days) that the path supports
    the band and the SNR reaches Kestrel's slowest level (L0) with 2 dB to
    spare (P.533's basic circuit reliability with that required SNR);
  * the operational MUF and the dominant mode (for example 1F2: one hop
    off the F2 layer);
  * which sky-wave condition of the simulator the path resembles (NVIS,
    one hop, several hops; see sim/channel.py) and the fastest Kestrel
    level the median SNR supports on a fading path (modem/plan.py).

P.533 gives the typical (median) conditions of the month at each hour; it
does not know about a flare or a geomagnetic storm on a given day.
"""

import csv  # reads the program's table
import io  # reads text as a file
import os  # file paths and the environment
import subprocess  # runs the program
import sys  # the platform
import tempfile  # a scratch folder for each run

from modem.levels import MIN_SNR_DB  # the weakest SNR each level decodes at (noise only)
from modem.plan import pick_level  # the fastest level a signal supports

from .bands import PRESETS_KHZ, signal_khz  # Kestrel's calling frequencies, and where the signal sits for a dial frequency
from .contacts import grid_center  # where a grid locator is
from .paths import app_dir, code_dir, installed  # where the program's files are

NOISE_CHOICES = {"QUIETRURAL": "Quiet rural", "RURAL": "Rural", "RESIDENTIAL": "Residential", "CITY": "City"}  # man-made noise at the receiver (ITU-R P.372 categories), as the operator sees them
REQUIRED_SNR_DB = MIN_SNR_DB[0] + 2.0  # the reliability asked for: L0 with the usual 2 dB margin, in 2.5 kHz
NVIS_ELEVATION_DEG = 60.0  # a dominant mode arriving at least this steeply counts as near vertical incidence
CLOSEST_KM = 50.0  # P.533 needs some distance: a path shorter than this is predicted as this long (it is then mostly NVIS anyway)
TIMEOUT_S = 120  # the longest a prediction may take


def engine_dir():  # where the ITU program is
    """Return the folder holding the ITU program (bin/) and its data (data/): "prop" beside Kestrel.exe when installed, live/_prop from the source folder."""
    return os.path.join(app_dir(), "prop") if installed() else os.path.join(code_dir(), "live", "_prop")  # the right place for this copy


def program():  # the ITU program itself
    """Return the path of ITURHFProp for this platform (whether or not it is present)."""
    return os.path.join(engine_dir(), "bin", "ITURHFProp.exe" if sys.platform.startswith("win") else "ITURHFProp")  # in bin/


def missing():  # can predictions be made?
    """Return None when the ITU program and its data are present, else a sentence saying what is missing."""
    if not os.path.isfile(program()):  # no program
        return f"The ITU-R P.533 program was not found ({program()}). From the source folder, run tools/build_prop.py."  # say so
    data = os.path.join(engine_dir(), "data")  # the data folder
    for name in ["P1239-3 Decile Factors.txt"] + [f"ionos{m:02d}.bin" for m in range(1, 13)] + [f"COEFF{m:02d}W.txt" for m in range(1, 13)]:  # every data file
        if not os.path.isfile(os.path.join(data, name)):  # one is missing
            return f"A data file of the ITU-R P.533 program is missing: {name}."  # say so
    return None  # all present


def band_frequencies():  # what to predict
    """Return {band name: center of Kestrel's signal on its calling frequency, in MHz}, lowest band first."""
    return {f"{band} m": sum(signal_khz(dial)) / 2000.0 for band, dial in sorted(PRESETS_KHZ.items(), key=lambda item: item[1])}  # the middle of the signal (its low and high edges, in kHz, averaged, in MHz) on each calling frequency


def input_text(tx, rx, year, month, ssn, freqs_mhz, power_w, noise, data_folder):  # the program's input file
    """Return the text of an ITURHFProp input file for one month, every hour, the given frequencies (point to point, isotropic antennas)."""
    power_dbkw = 10.0 * __import__("math").log10(max(float(power_w), 0.001) / 1000.0)  # transmitter power in dB relative to 1 kW, as P.533 takes it
    folder = data_folder.rstrip("\\/") + os.sep  # the data folder, ending in a separator (the program adds file names directly)
    lines = [  # one setting per line, as the ITU's examples write them
        'PathName "Kestrel"', 'PathTXName "TX"', f"Path.L_tx.lat {tx[0]:.4f}", f"Path.L_tx.lng {tx[1]:.4f}",  # the transmitting station
        'TXAntFilePath "ISOTROPIC"', "TXGOS 0.0",  # its antenna: isotropic (0 dBi)
        'PathRXName "RX"', f"Path.L_rx.lat {rx[0]:.4f}", f"Path.L_rx.lng {rx[1]:.4f}",  # the receiving station
        'RXAntFilePath "ISOTROPIC"', "RXGOS 0.0", 'AntennaOrientation "TX2RX"',  # its antenna, and both pointed at each other
        f"Path.year {int(year)}", f"Path.month {int(month)}",  # the month
        "Path.hour " + ",".join(str(h) for h in range(1, 25)),  # every hour (1 to 24 UTC)
        f"Path.SSN {int(round(float(ssn)))}",  # the smoothed sunspot number
        "Path.frequency " + ",".join(f"{f:.4f}" for f in freqs_mhz),  # the frequencies
        f"Path.txpower {power_dbkw:.2f}", "Path.BW 2500.0",  # power, and the bandwidth Kestrel quotes SNR in
        f"Path.SNRr {REQUIRED_SNR_DB:.1f}", "Path.SNRXXp 90",  # the SNR asked for (L0 with margin), and the SNR reached on 9 days in 10
        f'Path.ManMadeNoise "{noise}"', 'Path.Modulation "ANALOG"', "Path.SIRr 10.0",  # noise at the receiver; the simple (analogue) reliability method
        "Path.A 0.0", "Path.TW 0.0", "Path.FW 0.0", "Path.T0 0.0", "Path.F0 0.0", 'Path.SorL "SHORTPATH"',  # digital-method settings (unused), short path
        'RptFileFormat "RPT_OPMUF | RPT_SNR | RPT_SNRXX | RPT_BCR | RPT_DOMMODE | RPT_D"',  # the columns wanted
        *[f"{corner}.lat {rx[0]:.4f}" for corner in ("LL", "LR", "UL", "UR")], *[f"{corner}.lng {rx[1]:.4f}" for corner in ("LL", "LR", "UL", "UR")],  # one receiving point (not an area)
        "latinc 1.0", "lnginc 1.0", f'DataFilePath "{folder}"',  # area steps (unused), and where the data files are
    ]  # end of the lines
    return "\n".join(lines) + "\n"  # the file's text


def condition_of(mode, elevation_deg):  # which simulator condition a path resembles
    """Return the sim/channel.py condition a dominant mode resembles: "nvis" (steep, near vertical), "moderate" (one hop) or "poor" (two hops or more)."""
    hops = int("".join(ch for ch in str(mode) if ch.isdigit())[:1] or 1)  # the number of hops (the 2 of 2F2)
    if elevation_deg >= NVIS_ELEVATION_DEG:  # arriving steeply
        return "nvis"  # near vertical incidence: long echoes (ITU-R F.1487 up to 7 ms)
    return "moderate" if hops <= 1 else "poor"  # one hop, or several


def level_for(snr_db):  # the fastest Kestrel level a median SNR supports
    """Return the fastest level (0-4) a fading path at `snr_db` (2.5 kHz) supports with the usual margin, or None when even L0 needs more (the long beacon may still be heard)."""
    if snr_db is None or snr_db < MIN_SNR_DB[0] + 2.0:  # below L0's limit with margin
        return None  # no ordinary level; at best the long beacon
    return pick_level(snr_db, fading=True)  # fading limits: sky wave always fades


def parse(text, bands):  # the program's CSV table -> rows
    """Return the rows of an ITURHFProp CSV table as dictionaries, matched to `bands` ({name: MHz})."""
    start = text.find("month,hour,")  # the table's heading (the program may print a header before it)
    if start < 0:  # no table
        raise RuntimeError("the ITU program gave no table" + (": " + text.strip()[-300:] if text.strip() else ""))  # say so
    rows = []  # the result
    for record in csv.DictReader(io.StringIO(text[start:])):  # each line of the table
        mhz = float(record["frequency"])  # its frequency (the program rounds it to 2 decimals)
        band = min(bands, key=lambda name: abs(bands[name] - mhz))  # the band it belongs to
        elevation = float(record.get("DMele") or 0.0)  # elevation of the dominant mode, degrees
        snr = float(record["SNR"])  # median SNR in 2.5 kHz
        rows.append({  # one band at one hour
            "hour": int(record["hour"]) % 24,  # UTC hour, 0 to 23 (the program counts 1 to 24)
            "band": band, "mhz": bands[band],  # which band
            "snr": snr, "snr90": float(record["SNRXXp"]),  # median SNR, and the SNR reached on 9 days in 10
            "reliability": max(0.0, min(100.0, float(record["BCR"]))),  # per cent of days L0 works (path open and SNR enough)
            "muf": float(record["OPMUF"]), "mode": record.get("DMidx", ""), "elevation": elevation,  # the MUF and the dominant mode
            "km": float(record["distance"]),  # the path length
            "condition": condition_of(record.get("DMidx", ""), elevation),  # which simulator condition it resembles
            "level": level_for(snr),  # the fastest level expected
        })  # end of the row
    return rows  # every band at every hour


def predict(from_grid, to_grid, year, month, ssn, power_w=100.0, noise="RURAL", bands=None):  # one month's prediction
    """Return the rows of a P.533 prediction from `from_grid` to `to_grid` for every hour of `month` (1-12) of `year`, for each band.

    Raises ValueError for a bad grid locator and RuntimeError if the program
    is missing or fails.
    """
    why = missing()  # is the program there?
    if why:  # no
        raise RuntimeError(why)  # say what is missing
    tx, rx = grid_center(from_grid), grid_center(to_grid)  # the two places
    if tx is None or rx is None:  # one is not a locator
        raise ValueError(f"not a grid locator: {from_grid if tx is None else to_grid}")  # say which
    if abs(tx[0] - rx[0]) < 0.5 and abs(tx[1] - rx[1]) < 0.6:  # nearly the same place (under about 50 km)
        rx = (rx[0] + 0.45 if rx[0] < 80 else rx[0] - 0.45, rx[1])  # move the far end about 50 km north (south near the pole): P.533 needs a path
    bands = bands or band_frequencies()  # the bands to predict
    if noise not in NOISE_CHOICES:  # an unknown noise setting
        noise = "RURAL"  # the usual one
    with tempfile.TemporaryDirectory(prefix="kestrel-prop-") as work:  # a scratch folder, removed afterwards
        infile, outfile = os.path.join(work, "path.in"), os.path.join(work, "path.csv")  # the two files
        with open(infile, "w", encoding="ascii") as handle:  # write the input
            handle.write(input_text(tx, rx, year, month, ssn, list(bands.values()), power_w, noise, os.path.join(engine_dir(), "data")))  # the settings
        env = dict(os.environ)  # the program's environment
        bin_dir = os.path.dirname(program())  # where its libraries are
        if not sys.platform.startswith("win"):  # Linux: the libraries are found through the loader's path
            env["LD_LIBRARY_PATH"] = bin_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")  # beside the program
        flags = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}  # no console window flashing up on Windows
        result = subprocess.run([program(), "-s", "-c", infile, outfile], cwd=bin_dir, env=env, capture_output=True, text=True, timeout=TIMEOUT_S, **flags)  # run it, from its own folder so it finds its libraries
        if not os.path.isfile(outfile):  # no table written
            raise RuntimeError(f"the ITU program failed (code {result.returncode}): {(result.stdout + result.stderr).strip()[-300:]}")  # say why
        with open(outfile, encoding="ascii", errors="replace") as handle:  # read the table
            return parse(handle.read(), bands)  # the rows


def best_at(rows, hour):  # the band to use at an hour
    """Return the row of the best band at UTC `hour`: the most reliable, then the strongest; None if no band reaches L0 at all."""
    here = [r for r in rows if r["hour"] == hour % 24 and r["level"] is not None]  # bands that work at that hour
    if not here:  # none
        return None  # no band
    return max(here, key=lambda r: (round(r["reliability"] / 10.0), r["snr"]))  # most reliable (to the nearest 10 %), then strongest


def best_times(rows, band, count=3):  # when a band is best
    """Return up to `count` UTC hours at which `band` is most reliable (and reaches L0), best first."""
    here = sorted((r for r in rows if r["band"] == band and r["level"] is not None), key=lambda r: (-r["reliability"], -r["snr"]))  # that band's workable hours, best first
    return [r["hour"] for r in here[:count]]  # their hours


def suggestion(rows, hour):  # one line for the panel
    """Return a sentence suggesting the band (and level, and sky-wave condition) for UTC `hour`, and the best hour if now is poor."""
    best = best_at(rows, hour)  # the best band now
    names = {"nvis": "near-vertical (NVIS)", "moderate": "one hop", "poor": "two hops or more"}  # conditions in words
    if best is None:  # nothing works now
        overall = max(rows, key=lambda r: (r["reliability"], r["snr"]), default=None)  # the best band at any hour
        if overall is None or overall["level"] is None:  # nothing works all day
            return "No band is predicted to reach Kestrel L0 on this path this month; try the long beacon."  # say so
        return f"No band works now; best at {overall['hour']:02d}00 UTC on {overall['band']} ({overall['reliability']:.0f} % of days, SNR {overall['snr']:+.0f} dB)."  # when to try instead
    return f"Now: {best['band']}, {best['reliability']:.0f} % of days, median SNR {best['snr']:+.0f} dB, expect L{best['level']}; {names[best['condition']]} ({best['mode']}, {best['km']:.0f} km)."  # the suggestion
