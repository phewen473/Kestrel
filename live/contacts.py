"""The contact book: what the operator keeps about other stations, and a history of the traffic with each.

Kept in contacts.json in the Kestrel data folder (since 0.31R3; before it
held only each saved callsign's grid locator and band, and such a file is
read as it is). The file is one JSON object, keyed by callsign:

    {"QB2KES": {"call": "QB2KES", "name": "Hank", "location": "Raleigh, NC",
                "grid": "FM05", "band": "40m", "radio": "FT-991A",
                "power_w": "50", "antenna": "40 m dipole", "notes": "...",
                "created": 1795390000.0, "updated": 1795390000.0,
                "last_heard": {"t": ..., "band": "40m", "dial_khz": 7110.0,
                               "offset_hz": 14.0, "level": "L0", "snr_db": -17.0},
                "history": [entry, ...]}}

A history entry is one stretch of traffic with the station (newest last):

    {"start": t, "end": t, "band": "40m", "dial_khz": 7110.0, "level": "L0",
     "heard_db": -17.0, "their_db": -19.0, "msgs_in": 2, "msgs_out": 1,
     "outcome": "Contact, ended"}

heard_db is how this station last heard them, their_db how they last
reported hearing this station (from an answer or acknowledgment). Traffic
with the same station on the same band within MERGE_S seconds of the last
entry is added to that entry, so a contact with many frames is one line.

What goes into a history (Settings > Contacts, "Record in history"):
"all" (All traffic: every time the station is heard, called or worked) or
"contacts" (Completed contacts: only contacts that were made and ended).
Each history keeps at most `limit` entries (30 to 200, default 120); the
oldest are dropped first.

Only stations in the book get a history: the operator adds them. The book
learns what happens from the logbook (live/logbook.py calls observe for
every event, whatever the logbook's level of detail), so it sees exactly
what the logbook sees. Mail contents are never recorded here.
"""

import json  # the file
import math  # distance and bearing between grid locators
import os  # file paths
import threading  # the window and the working thread both use the book
import time  # dates and times

from .bands import band_of  # the band a dial frequency is in

HISTORY_MIN, HISTORY_MAX, HISTORY_DEFAULT = 30, 200, 120  # how many history entries each contact may keep
MODES = ("all", "contacts")  # what goes into a history: all traffic, or completed contacts only
MODE_NAMES = {"all": "All traffic", "contacts": "Completed contacts"}  # as the Settings window shows them
FIELDS = ("name", "location", "grid", "radio", "power_w", "antenna", "notes")  # what the operator fills in
MERGE_S = 900.0  # traffic within 15 minutes of a history entry, on the same band, is added to it
RANKS = {"heard": 0, "called": 1, "contact": 2, "ended": 3}  # how far a stretch of traffic got, least first
HEARD_EVENTS = ("heard", "message", "broadcast", "telemetry")  # received events that come from a named station


def grid_center(grid):  # where a Maidenhead grid locator is
    """Return (latitude, longitude) in degrees of the middle of a 4- or 6-character grid locator, or None if it is not one."""
    grid = (grid or "").strip().upper()  # as written in capitals
    if len(grid) not in (4, 6) or not ("A" <= grid[0] <= "R" and "A" <= grid[1] <= "R" and grid[2:4].isdigit()):  # not a locator
        return None  # nowhere
    lon = (ord(grid[0]) - 65) * 20.0 - 180.0 + int(grid[2]) * 2.0  # the field and square, west edge
    lat = (ord(grid[1]) - 65) * 10.0 - 90.0 + int(grid[3])  # south edge
    if len(grid) == 6:  # a subsquare as well
        if not ("A" <= grid[4] <= "X" and "A" <= grid[5] <= "X"):  # not a subsquare
            return None  # not a locator
        return lat + (ord(grid[5]) - 65 + 0.5) / 24.0, lon + (ord(grid[4]) - 65 + 0.5) / 12.0  # the middle of the subsquare
    return lat + 0.5, lon + 1.0  # the middle of the square


def distance_bearing(from_grid, to_grid):  # how far, and which way
    """Return (miles, bearing in degrees from north) from the middle of one grid locator to the middle of another, or None if either is not a locator."""
    a, b = grid_center(from_grid), grid_center(to_grid)  # the two places
    if a is None or b is None:  # one is not a locator
        return None  # unknown
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))  # in radians
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2  # the haversine
    miles = 2 * 3958.8 * math.asin(math.sqrt(half))  # along the earth's surface (mean radius 3958.8 miles)
    bearing = math.degrees(math.atan2(math.sin(lon2 - lon1) * math.cos(lat2), math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))) % 360.0  # the initial great-circle bearing
    return miles, bearing  # both


def clamp_limit(value):  # a history length the book accepts
    """Return `value` as a history length between HISTORY_MIN and HISTORY_MAX (HISTORY_DEFAULT if it is not a number)."""
    try:  # it may be text from a settings box
        number = int(float(value))  # as a whole number
    except (TypeError, ValueError):  # not a number at all
        return HISTORY_DEFAULT  # the default
    return max(HISTORY_MIN, min(HISTORY_MAX, number))  # within the range


def blank_record(call):  # a new contact with nothing known yet
    """Return a contact record for `call` with every field empty."""
    now = time.time()  # the moment it is made
    record = {"call": call, "band": ""}  # the callsign, and the band it was last heard on
    record.update({name: "" for name in FIELDS})  # the operator's fields, empty
    record.update({"created": now, "updated": now, "last_heard": {}, "history": []})  # when, and nothing heard yet
    return record  # the record


def normal_record(call, record):  # a record read from the file, made whole
    """Return `record` (as read from the file, perhaps from before 0.31R3) with every field present."""
    whole = blank_record(call)  # every field, empty
    if isinstance(record, dict):  # something usable was read
        whole.update({key: value for key, value in record.items() if key in whole})  # keep what it had
    whole["call"] = call  # the key is the callsign
    whole["history"] = [entry for entry in whole["history"] if isinstance(entry, dict)] if isinstance(whole["history"], list) else []  # only real entries
    whole["last_heard"] = whole["last_heard"] if isinstance(whole["last_heard"], dict) else {}  # only a real reading
    return whole  # the record


def outcome_text(rank, kind=""):  # the words for how far a stretch of traffic got
    """Return the outcome shown in a history for `rank` (RANKS), with the kind of frame heard for rank 0."""
    if rank >= RANKS["ended"]:  # a contact made and ended
        return "Contact, ended"  # done
    if rank >= RANKS["contact"]:  # a contact made
        return "Contact"  # it may still be going on, or have faded
    if rank >= RANKS["called"]:  # this station called it
        return "Called, no answer"  # until it answers
    return f"Heard {kind}".strip()  # only heard


class ContactBook(dict):  # callsign -> record, with the file and the history rules
    """The contact book: a dict of records keyed by callsign, saved to `path`.

    It is a dict so code that only reads it (is a callsign saved, what is
    its grid) needs nothing special. Change records only through put,
    delete and observe, which hold the lock and keep the file up to date.
    """

    def __init__(self, path, limit=HISTORY_DEFAULT, mode="all"):  # open the book
        super().__init__()  # an empty dict
        self.path = path  # where it is kept
        self.limit = clamp_limit(limit)  # how many history entries each contact keeps
        self.mode = mode if mode in MODES else "all"  # what goes into a history
        self.lock = threading.RLock()  # one change at a time
        self.sessions = {}  # callsign -> the history entry being added to now (kept in memory)
        self.load()  # read what is there

    def load(self):  # read the file
        """Read the book from its file; a missing or damaged file gives an empty book."""
        try:  # it may not exist yet
            with open(self.path, "r", encoding="utf-8") as handle:  # open it
                data = json.load(handle)  # the whole book
        except (OSError, ValueError):  # missing or damaged
            data = {}  # start empty
        with self.lock:  # nobody else touches it meanwhile
            self.clear()  # forget what was held
            for call, record in (data.items() if isinstance(data, dict) else ()):  # each saved station
                key = str(call).strip().upper()  # its callsign
                if key:  # a real one
                    self[key] = normal_record(key, record)  # made whole
                    del self[key]["history"][:-self.limit]  # no more than the limit
            self.sessions.clear()  # nothing in progress after a restart

    def save(self):  # write the file
        """Write the whole book to its file (through a temporary file, so a failure never leaves half a book). Return True if it was written."""
        with self.lock:  # a consistent book
            text = json.dumps(dict(self), indent=1, ensure_ascii=False)  # the whole book as text
        folder = os.path.dirname(self.path)  # its folder
        temporary = self.path + ".tmp"  # written first
        try:  # the disk may refuse
            if folder:  # a folder is named
                os.makedirs(folder, exist_ok=True)  # make sure it is there
            with open(temporary, "w", encoding="utf-8") as handle:  # the new copy
                handle.write(text)  # the book
            os.replace(temporary, self.path)  # then put it in place in one step
            return True  # written
        except OSError:  # it could not be written
            return False  # the book in memory is still right

    def put(self, call, **fields):  # add a contact, or change one
        """Add `call` to the book (if it is not there) and set the given fields; return its record. Unknown field names are ignored."""
        call = call.strip().upper()  # the callsign, as the book keeps it
        with self.lock:  # one change at a time
            record = self.get(call) or blank_record(call)  # the record, or a new one
            for name, value in fields.items():  # each field given
                if name in FIELDS or name in ("band", "last_heard"):  # one the operator (or the panel) may set
                    record[name] = value  # set it
            record["updated"] = time.time()  # changed now
            self[call] = record  # in the book
        self.save()  # and in the file
        return record  # the record

    def delete(self, call):  # forget a contact and its history
        """Remove `call` and its history from the book; return True if it was there."""
        call = call.strip().upper()  # the callsign
        with self.lock:  # one change at a time
            gone = self.pop(call, None) is not None  # take it out
            self.sessions.pop(call, None)  # and anything in progress
        if gone:  # something changed
            self.save()  # write the file
        return gone  # whether it was there

    def trimmed_by(self, limit):  # how much a smaller limit would drop
        """Return how many history entries, in all, a history length of `limit` would drop."""
        limit = clamp_limit(limit)  # as the book would take it
        with self.lock:  # a consistent count
            return sum(max(0, len(record["history"]) - limit) for record in self.values())  # the entries over the limit

    def set_policy(self, limit, mode):  # Settings > Contacts changed
        """Set the history length and what goes into a history; a smaller length trims every history now."""
        with self.lock:  # one change at a time
            self.limit = clamp_limit(limit)  # the length
            self.mode = mode if mode in MODES else "all"  # what is recorded
            trimmed = False  # nothing dropped yet
            for record in self.values():  # each contact
                if len(record["history"]) > self.limit:  # too long now
                    del record["history"][:-self.limit]  # the oldest go
                    trimmed = True  # something changed
        if trimmed:  # the file is out of date
            self.save()  # write it

    def add_entry(self, call, entry):  # add a history entry made elsewhere (the first reception, when a contact is made from the stations heard)
        """Append `entry` to `call`'s history (if `call` is in the book), dropping the oldest past the limit."""
        with self.lock:  # one change at a time
            record = self.get(call)  # the contact
            if record is None:  # not in the book
                return  # nothing to do
            record["history"].append(entry)  # newest last
            del record["history"][:-self.limit]  # no more than the limit
        self.save()  # write the file

    def _session(self, call, when, dial_khz):  # the history entry traffic at `when` belongs to
        entry = self.sessions.get(call)  # the stretch of traffic in progress
        band = band_of(dial_khz) if dial_khz else ""  # the band now
        if entry is not None and when - entry["end"] <= MERGE_S and (not band or not entry["band"] or entry["band"] == band):  # still the same stretch
            entry["end"] = max(entry["end"], when)  # it goes on
            return entry  # add to it
        entry = {"start": when, "end": when, "band": band, "dial_khz": dial_khz or 0.0, "level": "", "heard_db": None, "their_db": None,  # (continued)
                 "msgs_in": 0, "msgs_out": 0, "outcome": "", "rank": -1}  # a new stretch
        self.sessions[call] = entry  # in progress
        if self.mode == "all":  # all traffic is recorded
            self[call]["history"].append(entry)  # into the history now (it keeps changing as the traffic goes on)
            del self[call]["history"][:-self.limit]  # no more than the limit
        return entry  # add to it

    def observe(self, event, when, fields):  # one logbook event
        """Note a logbook event (called by live/logbook.py for every event, at every level of detail).

        Only events naming a station in the book change anything: a
        received event from it updates its last-heard reading and adds to
        its history; a call, message or contact with it adds to its history.
        """
        direction = fields.get("direction", "")  # RX, TX or -- (a contact starting or ending)
        call = str(fields.get("from" if direction == "RX" else "to") or "").strip().upper()  # the other station
        if event not in HEARD_EVENTS + ("call", "contact start", "contact end") or not call or call == "ALL":  # not about one station
            return  # nothing to note
        if event in HEARD_EVENTS and direction != "RX":  # sent by this station: only messages count
            if event != "message":  # a broadcast or anything else sent
                return  # not about one station
        with self.lock:  # one change at a time
            record = self.get(call)  # the contact
            if record is None:  # not in the book
                return  # only contacts get a history
            dial_khz = fields.get("dial_khz") or 0.0  # where
            snr = fields.get("snr_db")  # how well it was heard, if this is a reception
            if direction == "RX":  # heard from it
                record["last_heard"] = {"t": when, "band": band_of(dial_khz) if dial_khz else "", "dial_khz": dial_khz, "offset_hz": fields.get("offset_hz"),  # (continued)
                                        "level": fields.get("level") or record["last_heard"].get("level", ""), "snr_db": snr if snr is not None else record["last_heard"].get("snr_db")}  # the latest reading
                if dial_khz:  # the band is known
                    record["band"] = band_of(dial_khz)  # remember it
            entry = self._session(call, when, dial_khz)  # the stretch of traffic this belongs to
            if fields.get("level") and direction in ("RX", "TX") and not str(fields["level"]).endswith("?"):  # a speed level was used
                entry["level"] = max(entry["level"], str(fields["level"])) if entry["level"] else str(fields["level"])  # the fastest
            if direction == "RX" and snr is not None:  # a reading
                entry["heard_db"] = round(float(snr), 1)  # how it was heard, latest
            if fields.get("report_db") is not None:  # it said how it heard this station
                entry["their_db"] = round(float(fields["report_db"]), 1)  # latest
            if event == "message":  # a message
                entry["msgs_in" if direction == "RX" else "msgs_out"] += 1  # counted
            rank = {"call": RANKS["called"], "contact start": RANKS["contact"], "contact end": RANKS["ended"]}.get(event, RANKS["heard"])  # how far this got
            if event == "call" and entry["rank"] >= RANKS["contact"]:  # a call inside a contact (a resend)
                rank = entry["rank"]  # nothing new
            if rank >= entry["rank"]:  # as far as before, or further
                kind = str(fields.get("text") or "").split()[0] if event == "heard" and fields.get("text") else event  # what was heard
                entry["outcome"] = outcome_text(rank, kind if rank == RANKS["heard"] else "")  # the words
                entry["rank"] = rank  # remembered
            if event == "contact end":  # the contact is over
                if self.mode == "contacts":  # only completed contacts are recorded
                    record["history"].append(entry)  # this one now
                    del record["history"][:-self.limit]  # no more than the limit
                self.sessions.pop(call, None)  # the next traffic starts a new entry
            saving = direction == "RX" or self.mode == "all" or event == "contact end"  # the file changes
        if saving:  # worth writing
            self.save()  # write the file
