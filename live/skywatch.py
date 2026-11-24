"""What the bands are doing right now, from public measurements (since 0.35).

Two readings help choose a band for a contact, beside the P.533 prediction
(live/propagation.py), which describes a typical day of the month:

  * The short-path window, from the nearest ionosonde. KC2G collects the
    latest soundings (prop.kc2g.com/api/stations.json): foF2, the highest
    frequency the F2 layer returns straight up, and hmF2, its height. For a
    path of length d the highest usable frequency is about
    foF2 x sqrt(1 + (d / 2h)^2) (the secant law over a flat earth, close
    enough for near vertical incidence and short skip up to about 500
    miles). Below it a band is open on that path; above it the signal goes
    through the layer.
  * Band activity on the path, from other modes' spots. WSPR spots
    (wspr.live) and PSK Reporter reception reports within the last hour
    between the area round this station and the area round the other one
    (both directions) show which bands are carrying signals now, how many
    and how strong.

Nothing is fetched unless the operator asks (Propagation window, "Check the
bands now"). wspr.live allows 20 requests a minute and is for
non-commercial use; PSK Reporter asks for no more than one request every
five minutes: answers are kept and reused for five minutes.
"""

import json  # the answers
import math  # distances
import time  # clocks
import urllib.parse  # query strings
import urllib.request  # fetches
import xml.etree.ElementTree as ET  # PSK Reporter answers in XML

from .contacts import distance_bearing, grid_center  # grid locators -> places and distances

AGENT = {"User-Agent": "Kestrel (amateur radio digital mode)"}  # who asks
STATIONS_URL = "https://prop.kc2g.com/api/stations.json"  # the latest ionosonde soundings
WSPR_URL = "https://db1.wspr.live/"  # wspr.live's query service
PSK_URL = "https://retrieve.pskreporter.info/query"  # PSK Reporter's reception reports
FRESH_S = 3600  # a sounding older than an hour is not used
SOUNDING_KM = 1500.0  # nor one more than about 900 miles from the reflection point (foF2 changes with latitude and local time)
NEAR_KM = 300.0  # spots count when each end is within this distance of the station it stands for
CACHE_S = 300  # answers are reused for five minutes
DEFAULT_HMF2_KM = 300.0  # the F2 layer's height when the sounding does not give it
WSPR_BANDS = {3: "80 m", 7: "40 m", 10: "30 m", 14: "20 m", 18: "17 m", 21: "15 m", 28: "10 m", 50: "6 m"}  # wspr.live's band codes for Kestrel's bands
_cache = {}  # url -> (when, answer)


def _get(url, timeout=20, kind="json"):  # one fetch, reused for five minutes
    """Return the answer at `url` (JSON, or text when kind is "text"), from the cache when it is under CACHE_S old."""
    now = time.time()  # now
    held = _cache.get(url)  # an earlier answer
    if held is not None and now - held[0] < CACHE_S:  # recent enough
        return held[1]  # reuse it
    request = urllib.request.Request(url, headers=AGENT)  # the request, saying who asks
    with urllib.request.urlopen(request, timeout=timeout) as reply:  # fetch it
        body = reply.read().decode("utf-8")  # the text
    answer = json.loads(body) if kind == "json" else body  # parsed
    _cache[url] = (now, answer)  # kept
    return answer  # the answer


def _km(a, b):  # great-circle distance between two (lat, lon) points
    """Return the distance in km between (lat, lon) points `a` and `b`."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))  # in radians
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2  # the haversine
    return 2 * 6371.0 * math.asin(math.sqrt(min(half, 1.0)))  # along the surface


def _when(text):  # an ionosonde time -> seconds since 1970 (UTC)
    """Return the sounding time `text` ("2026-11-24T06:15:00") as seconds since 1970, or None."""
    try:  # it may be missing or odd
        return time.mktime(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone  # read as UTC
    except ValueError:  # not a time
        return None  # unknown


def nearest_sounding(lat, lon, soundings, now=None):  # the closest fresh ionosonde
    """Return (sounding, km away) of the nearest sounding under FRESH_S old with a confident foF2, or (None, None)."""
    now = now or time.time()  # now
    best = (None, None)  # nothing yet
    for s in soundings or []:  # every station
        try:  # odd entries are skipped
            when = _when(s.get("time"))  # its time
            fof2, cs = s.get("fof2"), s.get("cs")  # the critical frequency and its confidence score
            place = (float(s["station"]["latitude"]), (float(s["station"]["longitude"]) + 180.0) % 360.0 - 180.0)  # where (longitude given 0-360 east)
        except (KeyError, TypeError, ValueError):  # not usable
            continue  # next
        if when is None or now - when > FRESH_S or fof2 is None or (cs is not None and float(cs) < 25):  # stale, missing or doubtful
            continue  # next
        km = _km((lat, lon), place)  # how far
        if km > SOUNDING_KM:  # too far away to describe this part of the sky
            continue  # next
        if best[1] is None or km < best[1]:  # the nearest so far
            best = (s, km)  # kept
    return best  # the nearest


def short_path_muf(fof2, hmf2_km, path_km):  # the secant law
    """Return the highest usable frequency (MHz) on a path of `path_km` reflected at `hmf2_km` with critical frequency `fof2`."""
    return float(fof2) * math.sqrt(1.0 + (path_km / (2.0 * hmf2_km)) ** 2)  # foF2 times the secant of the angle of incidence


def nvis_window(own_grid, far_grid=None, bands=None, soundings=None, now=None):  # the short-path window now
    """Return a dict: station, km away, age_min, fof2, hmf2, path_km, muf, open (bands below the MUF), closed; or None when no fresh sounding is near.

    `bands` maps band names to MHz (default: Kestrel's calling frequencies). The
    path is from this station to `far_grid` (straight up when None or unknown).
    """
    here = grid_center(own_grid)  # where this station is
    if here is None:  # no grid
        return None  # unknown
    if soundings is None:  # not given: fetch
        soundings = _get(STATIONS_URL)  # the latest soundings
    there = grid_center(far_grid) if far_grid else None  # the other end
    middle = ((here[0] + there[0]) / 2, (here[1] + there[1]) / 2) if there else here  # the reflection point, roughly half way
    s, km = nearest_sounding(middle[0], middle[1], soundings, now)  # the nearest sounding to it
    if s is None:  # none fresh
        return None  # unknown
    path_km = _km(here, there) if there else 0.0  # the path length
    hmf2 = float(s.get("hmf2") or DEFAULT_HMF2_KM)  # the layer's height
    muf = short_path_muf(s["fof2"], hmf2, path_km)  # the highest usable frequency on this path
    if bands is None:  # Kestrel's bands
        from .propagation import band_frequencies  # the calling frequencies (imported here to keep this module light)
        bands = band_frequencies()  # name -> MHz
    return {"station": s["station"]["name"], "km": km, "age_min": ((now or time.time()) - _when(s["time"])) / 60.0, "fof2": float(s["fof2"]), "hmf2": hmf2,  # the sounding
            "path_km": path_km, "muf": muf, "open": [b for b, mhz in bands.items() if mhz < muf], "closed": [b for b, mhz in bands.items() if mhz >= muf]}  # the answer


def wspr_query(own, far, hours=1.0):  # the SQL for spots on a path
    """Return the wspr.live SQL counting spots by band in the last `hours` between (lat, lon) `own` and `far`, both ways."""
    near = lambda a_lat, a_lon, b: f"greatCircleDistance({a_lon}, {a_lat}, {b[1]:.3f}, {b[0]:.3f}) < {NEAR_KM * 1000:.0f}"  # within NEAR_KM of a place
    one_way = f"({near('tx_lat', 'tx_lon', own)} AND {near('rx_lat', 'rx_lon', far)})"  # from here to there
    other_way = f"({near('tx_lat', 'tx_lon', far)} AND {near('rx_lat', 'rx_lon', own)})"  # from there to here
    bands = ", ".join(str(b) for b in WSPR_BANDS)  # Kestrel's bands
    return (f"SELECT band, count() AS n, median(snr) AS mid, max(snr) AS best FROM wspr.rx WHERE time > now() - INTERVAL {int(hours * 60)} MINUTE "
            f"AND band IN ({bands}) AND ({one_way} OR {other_way}) GROUP BY band FORMAT JSON")  # spots by band


def wspr_activity(own_grid, far_grid, hours=1.0):  # WSPR spots on the path
    """Return {band name: (spots, median SNR, best SNR)} from wspr.live for the last `hours`."""
    own, far = grid_center(own_grid), grid_center(far_grid)  # the two places
    if own is None or far is None:  # a grid missing
        return {}  # nothing to ask
    url = WSPR_URL + "?" + urllib.parse.urlencode({"query": wspr_query(own, far, hours)})  # the request
    rows = _get(url).get("data", [])  # the answer's rows
    return {WSPR_BANDS[int(r["band"])]: (int(r["n"]), float(r["mid"]), float(r["best"])) for r in rows if int(r["band"]) in WSPR_BANDS}  # by band


def _band_name(hz):  # a frequency -> one of Kestrel's band names
    """Return the Kestrel band name ("40 m") for a frequency in Hz, or None."""
    from .bands import band_of  # the band edges
    name = band_of(hz / 1000.0)  # e.g. "40m"
    return f"{name[:-1]} m" if name else None  # "40 m"


def psk_activity(own_grid, far_grid, contact=""):  # PSK Reporter reports on the path
    """Return {band name: spots} for reception reports in the last hour between the square round this station and the area round the other one."""
    own, far = grid_center(own_grid), grid_center(far_grid)  # the two places
    if own is None or far is None:  # a grid missing
        return {}  # nothing to ask
    query = {"callsign": own_grid[:4].upper(), "modify": "grid", "flowStartSeconds": "-3600", "rronly": "1", "noactive": "1"}  # reports to or from this station's square
    if contact:  # PSK Reporter asks callers to say who they are
        query["appcontact"] = contact  # the operator's address
    text = _get(PSK_URL + "?" + urllib.parse.urlencode(query), kind="text")  # the XML
    out = {}  # spots by band
    for report in ET.fromstring(text).iter("receptionReport"):  # each report
        ends = [grid_center(report.get(key, "")[:4]) for key in ("senderLocator", "receiverLocator")]  # both ends, as squares
        if any(e is None for e in ends):  # a locator missing
            continue  # next
        if not any(_km(e, far) < NEAR_KM for e in ends):  # neither end near the other station
            continue  # not this path
        name = _band_name(float(report.get("frequency", 0) or 0))  # its band
        if name:  # one of the amateur bands
            out[name] = out.get(name, 0) + 1  # counted
    return out  # by band


def describe_window(w):  # the short-path window in words
    """Return one line for a nvis_window answer."""
    if not w:  # none
        return "Short-path window: no fresh ionosonde sounding nearby"  # say so
    return (f"Short-path window: foF2 {w['fof2']:.1f} MHz at {w['station']} ({w['km'] * 0.6214:.0f} miles away, {w['age_min']:.0f} min ago); "  # the sounding
            f"highest usable on this {w['path_km'] * 0.6214:.0f}-mile path about {w['muf']:.1f} MHz: open {', '.join(w['open']) or 'none'}")  # the answer


def describe_activity(wspr, psk):  # band activity in words
    """Return one line for wspr_activity and psk_activity answers."""
    names = sorted(set(wspr) | set(psk), key=lambda b: int(b.split()[0]), reverse=True)  # every band with something, 80 m first
    if not names:  # nothing
        return "Band activity on this path in the last hour: none spotted (WSPR, PSK Reporter)"  # say so
    parts = []  # one per band
    for b in names:  # each band
        bits = []  # what is known
        if b in wspr:  # WSPR spots
            bits.append(f"{wspr[b][0]} WSPR, median {wspr[b][1]:+.0f} dB")  # count and strength
        if b in psk:  # PSK Reporter reports
            bits.append(f"{psk[b]} PSK Reporter")  # count
        parts.append(f"{b}: " + ", ".join(bits))  # the band's part
    return "Band activity on this path in the last hour: " + "; ".join(parts)  # the line


def busiest(wspr, psk):  # the band with the most evidence
    """Return the band name with the most spots on the path (WSPR and PSK Reporter together), or None."""
    totals = {}  # spots by band
    for b, (n, _snr, _best) in wspr.items():  # WSPR
        totals[b] = totals.get(b, 0) + n  # counted
    for b, n in psk.items():  # PSK Reporter
        totals[b] = totals.get(b, 0) + n  # counted
    return max(totals, key=totals.get) if totals else None  # the busiest


__all__ = ["nvis_window", "wspr_activity", "psk_activity", "describe_window", "describe_activity", "busiest", "short_path_muf", "distance_bearing"]  # what others use
