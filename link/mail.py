"""Store and forward (spec Section 8): the mail a station keeps between contacts.

A Mailroom holds everything about mail that must outlast one contact and
one run of the program:

- the station's next message number, so a number is never reused while
  copies of an older message with that number may still be traveling;
- its own messages to named stations ("own"), with the stations each has
  been handed to for carrying, until a delivery is confirmed or the
  message expires;
- messages it carries for other stations ("bag");
- the IDs of messages it has received, or delivered for others ("handled"),
  so a later copy is answered with "already have it";
- delivery receipts it announces in its mail notices;
- what other stations said in their mail notices: whom they hold mail for
  and whom they hear ("reach").

Times are wall-clock seconds (time.time), because mail lives for days.
Every change goes through a method that takes the lock, because the
station changes the mail from its own thread while the panel saves it.
"""

import json  # the file the mail is kept in
import os  # file handling
import random  # the first message number of a new station
import threading  # the lock between the station's thread and the panel
import time  # the wall clock

from modem import call_hash, message_hash, native  # the short codes of a mail notice; the compiled library
from modem.address import clean_call  # tidies a callsign
from modem.params import MSG_ID_BITS, NOTICE_SLOTS  # message numbers, notice list length

from .params import BAG_MOST, BAG_PER_ORIGIN, HANDED_MOST, HOP_LIMIT, MAIL_LIFE_HOURS, PASSED_MOST, REACH_S, RECEIPT_LIST_H  # the store-and-forward settings

HOUR = 3600.0  # seconds in an hour


def key(origin, msg_id):  # how a message ID is written in the store
    """Return the message ID of message `msg_id` from `origin` as one string, "ORIGIN#number"."""
    return f"{clean_call(origin)}#{int(msg_id)}"  # callsign and number


class PythonMailroom:  # one station's mail, kept in Python (the reference the compiled store is tested against)
    """The mail one station keeps between contacts and between runs (see the module notes)."""

    def __init__(self, call="", clock=time.time):  # an empty mailroom
        self.call = clean_call(call) if call else ""  # the station's own callsign
        self.clock = clock  # the wall clock (tests give their own)
        self.lock = threading.RLock()  # one change at a time
        self.next_id = random.randrange(1 << MSG_ID_BITS)  # a new station starts at a random number, so a station whose mail file was lost does not reuse recent numbers
        self.own = {}  # message number -> {"text", "dest", "carriers", "expires"}: this station's messages to named stations, not yet known to be delivered
        self.bag = []  # messages held for others: {"dest", "origin", "id", "text", "hops", "expires", "came_from", "got", "carriers"}
        self.handled = {}  # message ID -> when it may be forgotten: received here, or delivered or dropped as a holder
        self.receipts = {}  # message ID -> {"until", "dest"}: delivery receipts this station announces
        self.reach = {}  # callsign -> {"when", "held", "heard", "receipts"}: the last mail notice heard from each station
        self.news = []  # (kind, details) for the panel: carried, delivered, held, expired ... (not saved)

    # ---- message numbers and this station's own messages ----

    def new_number(self):  # the next message number
        """Return a message number not in use by any of this station's waiting messages, and move the counter on."""
        with self.lock:  # one change at a time
            for _ in range(1 << MSG_ID_BITS):  # at most once round
                number = self.next_id  # the candidate
                self.next_id = (number + 1) % (1 << MSG_ID_BITS)  # the counter moves on
                if str(number) not in self.own:  # not taken by a waiting message
                    return number  # use it
            raise RuntimeError("every message number is in use")  # cannot happen with 50 messages

    def own_add(self, text, dest, taken=()):  # a message to a named station is queued
        """Return the message number for `text` to `dest`. A waiting message with the same text and destination whose number is not in `taken` (numbers already queued) keeps its number, so a message re-queued after a restart is still the same message."""
        dest = clean_call(dest)  # the destination, tidied
        with self.lock:  # one change at a time
            for number, item in self.own.items():  # waiting messages
                if item["text"] == text and item["dest"] == dest and int(number) not in taken:  # this one, not already in the outbox
                    return int(number)  # the same message as before
            number = self.new_number()  # a new message
            self.own[str(number)] = {"text": text, "dest": dest, "carriers": [], "expires": self.clock() + MAIL_LIFE_HOURS * HOUR}  # remember it
            return number  # its number

    def own_drop(self, number):  # the operator took a message back
        with self.lock:  # one change at a time
            self.own.pop(str(number), None)  # forget it

    def own_item(self, number):  # one of this station's waiting messages
        with self.lock:  # one change at a time
            return self.own.get(str(number))  # or None

    def own_carried(self, number, carrier):  # a station has taken a copy to carry
        with self.lock:  # one change at a time
            item = self.own.get(str(number))  # the message
            if item is not None and carrier not in item["carriers"]:  # still waiting, and a new carrier
                item["carriers"].append(carrier)  # note who carries it
                self.news.append(("carried", {"id": number, "text": item["text"], "dest": item["dest"], "carrier": carrier}))  # tell the panel

    def can_hand(self, number, partner):  # may this message be handed to `partner` to carry?
        with self.lock:  # one change at a time
            item = self.own.get(str(number))  # the message
            return item is not None and partner != item["dest"] and partner not in item["carriers"] and len(item["carriers"]) < HANDED_MOST and item["expires"] > self.clock()  # waiting, not already with that station, room for another carrier

    def own_done(self, number, via=None):  # this station's message is known to be delivered
        """Forget the message: delivered directly (`via` None) or as a receipt from a holder showed (`via` the station that reported it). If carriers hold copies, announce a receipt so they drop them."""
        with self.lock:  # one change at a time
            item = self.own.pop(str(number), None)  # take it out
            if item is None:  # already gone
                return None  # nothing to do
            if item["carriers"]:  # copies are out with carriers
                self.add_receipt(self.call, number, item["dest"])  # tell them, through this station's notices
            self.news.append(("delivered", {"id": number, "text": item["text"], "dest": item["dest"], "via": via}))  # tell the panel
            return item  # what it was

    def life_hours(self, expires):  # the lifetime a frame should carry
        return max(1, min(MAIL_LIFE_HOURS, int(-(-(expires - self.clock()) // HOUR))))  # whole hours left, rounded up, at least one

    # ---- messages carried for others ----

    def has_room(self, origin):  # could another message from `origin` be held?
        with self.lock:  # one change at a time
            return len(self.bag) < BAG_MOST and sum(item["origin"] == origin for item in self.bag) < BAG_PER_ORIGIN  # within both limits

    def holding(self, origin, number):  # is this message held here already?
        with self.lock:  # one change at a time
            return any(item["origin"] == origin and item["id"] == number for item in self.bag)  # in the bag

    def hold(self, dest, origin, number, text, hops, life_hours, came_from):  # keep a message for another station
        """Hold a complete message for `dest`; return True if it is now held."""
        with self.lock:  # one change at a time
            if self.holding(origin, number) or self.is_handled(origin, number) or not self.has_room(origin):  # a duplicate, or no room
                return False  # not taken
            self.bag.append({"dest": dest, "origin": origin, "id": int(number), "text": text, "hops": int(hops), "expires": self.clock() + life_hours * HOUR,  # (continued)
                             "came_from": came_from, "got": self.clock(), "carriers": []})  # who passed it here, when, and who it has been passed to since
            self.news.append(("held", {"id": number, "dest": dest, "origin": origin, "came_from": came_from}))  # tell the panel
            return True  # held

    def bag_item(self, origin, number):  # one held message
        with self.lock:  # one change at a time
            return next((item for item in self.bag if item["origin"] == origin and item["id"] == number), None)  # or None

    def held_for(self, dest):  # held messages for one station that may still be sent
        with self.lock:  # one change at a time
            now = self.clock()  # the time
            return [item for item in self.bag if item["dest"] == dest and item["expires"] > now and item["hops"] + 1 <= HOP_LIMIT]  # live, and within the hop limit

    def to_pass(self, partner):  # a held message that `partner` could carry towards its destination
        with self.lock:  # one change at a time
            now = self.clock()  # the time
            for item in self.bag:  # oldest first
                if (item["dest"] != partner and partner != item["came_from"] and partner != item["origin"] and partner not in item["carriers"]  # (continued)
                        and len(item["carriers"]) < PASSED_MOST and item["hops"] + 2 <= HOP_LIMIT and item["expires"] > now and self.reaches(partner, item["dest"])):  # (continued: the partner could still deliver it, and says it hears the destination)
                    return item  # this one
            return None  # nothing

    def passed(self, origin, number, carrier):  # a held message was passed to another carrier
        with self.lock:  # one change at a time
            item = self.bag_item(origin, number)  # the message
            if item is not None and carrier not in item["carriers"]:  # still held, a new carrier
                item["carriers"].append(carrier)  # note it
                self.news.append(("passed", {"id": number, "dest": item["dest"], "origin": origin, "carrier": carrier}))  # tell the panel

    def delivered_held(self, origin, number, dest):  # a held message reached its destination (or the destination already had it)
        with self.lock:  # one change at a time
            item = self.bag_item(origin, number)  # the message
            if item is not None:  # still held
                self.bag.remove(item)  # drop it
                self.news.append(("handed over", {"id": number, "dest": dest, "origin": origin}))  # tell the panel
            self.mark_handled(origin, number)  # never take it again
            self.add_receipt(origin, number, dest)  # and announce the delivery

    # ---- what has been handled, and receipts ----

    def mark_handled(self, origin, number):  # this message has been dealt with here
        with self.lock:  # one change at a time
            self.handled[key(origin, number)] = self.clock() + MAIL_LIFE_HOURS * HOUR  # remembered as long as any copy could live

    def is_handled(self, origin, number):  # has this message been dealt with here?
        with self.lock:  # one change at a time
            return self.handled.get(key(origin, number), 0) > self.clock()  # and not yet forgotten

    def add_receipt(self, origin, number, dest):  # announce a delivery in this station's notices
        with self.lock:  # one change at a time
            self.receipts[key(origin, number)] = {"until": self.clock() + RECEIPT_LIST_H * HOUR, "dest": dest}  # for twelve hours

    # ---- mail notices ----

    def notice_lists(self, heard_calls=()):  # what this station's next mail notice should say
        """Return (held, receipts, heard): up to three short codes each. All three are empty when there is nothing worth a notice."""
        with self.lock:  # one change at a time
            now = self.clock()  # the time
            held = []  # stations mail is held for, oldest mail first
            for item in self.bag:  # held messages
                code = call_hash(item["dest"])  # its destination's code
                if item["expires"] > now and code not in held:  # live, and not listed yet
                    held.append(code)  # list it
            receipts = [message_hash(*name.rsplit("#", 1)[:1], int(name.rsplit("#", 1)[1])) for name, entry in sorted(self.receipts.items(), key=lambda pair: -pair[1]["until"]) if entry["until"] > now]  # newest receipts first
            if not held and not receipts:  # nothing held and nothing delivered lately
                return [], [], []  # no notice is needed
            heard = [call_hash(call) for call in heard_calls if call != self.call][:NOTICE_SLOTS]  # the stations this one hears, most recent first
            return held[:NOTICE_SLOTS], receipts[:NOTICE_SLOTS], heard  # three of each at most

    def heard_notice(self, origin, held, receipts, heard):  # a mail notice was heard
        """Take in another station's notice. Return the numbers of this station's own messages that its receipts show delivered."""
        with self.lock:  # one change at a time
            self.reach[origin] = {"when": self.clock(), "held": list(held), "heard": list(heard), "receipts": list(receipts)}  # remember what it said
            codes = set(receipts)  # the receipts it reports
            done = []  # this station's messages now known delivered
            for number in list(self.own):  # this station's waiting messages
                if message_hash(self.call, int(number)) in codes:  # one of them
                    self.own_done(int(number), via=origin)  # delivered
                    done.append(int(number))  # tell the station
            for item in list(self.bag):  # messages held here
                if message_hash(item["origin"], item["id"]) in codes:  # one of them has been delivered by someone
                    self.bag.remove(item)  # drop the copy
                    self.mark_handled(item["origin"], item["id"])  # and never take it again
                    self.news.append(("dropped", {"id": item["id"], "dest": item["dest"], "origin": item["origin"], "via": origin}))  # tell the panel
            return done  # for the station

    def reaches(self, station, dest):  # does `station` say it hears `dest`?
        with self.lock:  # one change at a time
            seen = self.reach.get(station)  # its last notice
            return bool(seen) and self.clock() - seen["when"] <= REACH_S and call_hash(dest) in seen["heard"]  # recent, and listing the destination

    def holds_for_me(self, station):  # did `station`'s last notice say it holds mail for this station?
        with self.lock:  # one change at a time
            seen = self.reach.get(station)  # its last notice
            return bool(seen) and self.clock() - seen["when"] <= MAIL_LIFE_HOURS * HOUR and call_hash(self.call) in seen["held"]  # within the life of any mail, and listing this station

    def forget_held_for_me(self, station):  # that station has delivered, or had nothing after all
        with self.lock:  # one change at a time
            seen = self.reach.get(station)  # its last notice
            if seen is not None:  # one was heard
                seen["held"] = [code for code in seen["held"] if code != call_hash(self.call)]  # this station no longer counts as waiting there

    # ---- tidying and keeping ----

    def tidy(self):  # let expired mail go
        """Drop everything past its time. Return the numbers of this station's own messages that expired undelivered."""
        with self.lock:  # one change at a time
            now = self.clock()  # the time
            expired = [int(number) for number, item in self.own.items() if item["expires"] <= now]  # own messages out of time
            for number in expired:  # each one
                item = self.own.pop(str(number))  # forget it
                self.news.append(("expired", {"id": number, "text": item["text"], "dest": item["dest"]}))  # tell the panel
            for item in [item for item in self.bag if item["expires"] <= now]:  # held messages out of time
                self.bag.remove(item)  # drop it
                self.mark_handled(item["origin"], item["id"])  # and do not take it again
                self.news.append(("dropped", {"id": item["id"], "dest": item["dest"], "origin": item["origin"], "via": None}))  # tell the panel
            self.handled = {name: until for name, until in self.handled.items() if until > now}  # old IDs forgotten
            self.receipts = {name: entry for name, entry in self.receipts.items() if entry["until"] > now}  # old receipts no longer listed
            self.reach = {call: seen for call, seen in self.reach.items() if now - seen["when"] <= MAIL_LIFE_HOURS * HOUR}  # old notices forgotten
            return expired  # for the station

    def take_news(self):  # what has happened since the panel last looked
        with self.lock:  # one change at a time
            news, self.news = self.news, []  # hand it over
            return news  # oldest first

    def to_dict(self):  # everything worth keeping, as plain data
        with self.lock:  # one change at a time
            return {"call": self.call, "next_id": self.next_id, "own": self.own, "bag": self.bag, "handled": self.handled, "receipts": self.receipts, "reach": self.reach}  # the store

    def save(self, path):  # write the mail to a file
        data = json.dumps(self.to_dict(), indent=1)  # as text, taken under the lock
        temporary = path + ".new"  # written first, then put in place, so a crash never leaves half a file
        with open(temporary, "w", encoding="utf-8") as handle:  # the new file
            handle.write(data)  # the mail
        os.replace(temporary, path)  # in place of the old one

    @classmethod  # makes a Mailroom
    def load(cls, path, call="", clock=time.time):  # read the mail from a file
        """Return the Mailroom kept in `path`, or an empty one if there is none (or it cannot be read). Mail kept under another callsign is not used."""
        room = cls(call, clock)  # an empty one to fill
        try:  # the file may be missing or damaged
            with open(path, encoding="utf-8") as handle:  # the kept mail
                data = json.load(handle)  # as plain data
        except (OSError, ValueError):  # nothing usable
            return room  # start empty
        if data.get("call") and room.call and data["call"] != room.call:  # kept under another callsign: that station's mail, not this one's
            return room  # start empty
        room.next_id = int(data.get("next_id", room.next_id)) % (1 << MSG_ID_BITS)  # carry on numbering where it left off
        for name in ("own", "bag", "handled", "receipts", "reach"):  # each part
            setattr(room, name, data.get(name, getattr(room, name)))  # as kept
        room.tidy()  # anything that expired while the program was closed goes now
        return room  # ready


class CompiledMailroom:  # one station's mail, kept in the compiled library (cpp/src/mail.cpp)
    """The same Mailroom, its store and rules in C++. Every method asks the library; the attributes the panel reads (own, bag, receipts ...) are snapshots."""

    def __init__(self, call="", clock=time.time):  # an empty mailroom
        self.store = native.compiled_mail()  # the store in the library
        self.clock = clock  # the wall clock (tests give their own)
        self.lock = threading.RLock()  # kept for callers that take it (the library has its own)
        self._ask("init", call, random.randrange(1 << MSG_ID_BITS))  # the callsign, and a random first number (as PythonMailroom)

    def _ask(self, op, *args):  # run one method in the library
        """Return the answer of the library's `op` for `args`, at the clock's time."""
        return self.store.request(op, args, self.clock())  # asked

    # The attributes PythonMailroom keeps, read from the library.
    call = property(lambda self: self._ask("to_dict")["call"])  # the station's callsign
    next_id = property(lambda self: self._ask("to_dict")["next_id"])  # the next message number
    own = property(lambda self: self._ask("to_dict")["own"])  # own messages waiting
    bag = property(lambda self: self._ask("to_dict")["bag"])  # messages held for others
    handled = property(lambda self: self._ask("to_dict")["handled"])  # message IDs dealt with
    receipts = property(lambda self: self._ask("to_dict")["receipts"])  # receipts announced
    reach = property(lambda self: self._ask("to_dict")["reach"])  # notices heard

    def new_number(self): return self._ask("new_number")  # the next message number
    def own_add(self, text, dest, taken=()): return self._ask("own_add", text, dest, sorted(int(n) for n in taken))  # a message queued
    def own_drop(self, number): return self._ask("own_drop", int(number))  # taken back
    def own_item(self, number): return self._ask("own_item", int(number))  # one waiting message
    def own_carried(self, number, carrier): return self._ask("own_carried", int(number), carrier)  # a carrier took it
    def can_hand(self, number, partner): return self._ask("can_hand", int(number), partner)  # may it be handed on?
    def own_done(self, number, via=None): return self._ask("own_done", int(number), via)  # delivered
    def life_hours(self, expires): return self._ask("life_hours", expires)  # the lifetime a frame carries
    def has_room(self, origin): return self._ask("has_room", origin)  # room for another?
    def holding(self, origin, number): return self._ask("holding", origin, int(number))  # held already?
    def hold(self, dest, origin, number, text, hops, life_hours, came_from): return self._ask("hold", dest, origin, int(number), text, int(hops), life_hours, came_from)  # held
    def bag_item(self, origin, number): return self._ask("bag_item", origin, int(number))  # one held message
    def held_for(self, dest): return self._ask("held_for", dest)  # held for one station
    def to_pass(self, partner): return self._ask("to_pass", partner)  # one to pass on
    def passed(self, origin, number, carrier): return self._ask("passed", origin, int(number), carrier)  # passed on
    def delivered_held(self, origin, number, dest): return self._ask("delivered_held", origin, int(number), dest)  # delivered
    def mark_handled(self, origin, number): return self._ask("mark_handled", origin, int(number))  # dealt with
    def is_handled(self, origin, number): return self._ask("is_handled", origin, int(number))  # dealt with?
    def add_receipt(self, origin, number, dest): return self._ask("add_receipt", origin, int(number), dest)  # announced
    def notice_lists(self, heard_calls=()): return tuple(self._ask("notice_lists", list(heard_calls)))  # the next notice
    def heard_notice(self, origin, held, receipts, heard): return self._ask("heard_notice", origin, [int(c) for c in held], [int(c) for c in receipts], [int(c) for c in heard])  # a notice heard
    def reaches(self, station, dest): return self._ask("reaches", station, dest)  # does it hear dest?
    def holds_for_me(self, station): return self._ask("holds_for_me", station)  # mail waiting there?
    def forget_held_for_me(self, station): return self._ask("forget_held_for_me", station)  # no longer
    def tidy(self): return self._ask("tidy")  # expired mail goes
    def take_news(self): return [tuple(entry) for entry in self._ask("take_news")]  # news for the panel
    def to_dict(self): return self._ask("to_dict")  # everything worth keeping

    def save(self, path):  # write the mail to a file (the same file PythonMailroom writes)
        data = json.dumps(self.to_dict(), indent=1)  # as text
        temporary = path + ".new"  # written first, then put in place
        with open(temporary, "w", encoding="utf-8") as handle:  # the new file
            handle.write(data)  # the mail
        os.replace(temporary, path)  # in place of the old one

    @classmethod  # makes a CompiledMailroom
    def load(cls, path, call="", clock=time.time):  # read the mail from a file
        """Return the mail kept in `path`, or an empty store if there is none, it cannot be read, or it is another station's."""
        room = cls(call, clock)  # an empty one to fill
        try:  # the file may be missing or damaged
            with open(path, encoding="utf-8") as handle:  # the kept mail
                data = json.load(handle)  # as plain data
        except (OSError, ValueError):  # nothing usable
            return room  # start empty
        room._ask("from_dict", data)  # taken in (another station's mail is ignored), and tidied
        return room  # ready


class Mailroom:  # one station's mail: the compiled store when the library is in use, otherwise the Python one
    """Make a CompiledMailroom when the compiled library is in use, else a PythonMailroom; both behave the same."""

    def __new__(cls, call="", clock=time.time):  # which kind to make
        return (CompiledMailroom if native.compiled_mail is not None and native._lib is not None else PythonMailroom)(call, clock)  # the compiled one when it can be

    @staticmethod  # reads a file
    def load(path, call="", clock=time.time):  # read the mail from a file
        """Return the mail kept in `path` (see PythonMailroom.load)."""
        return (CompiledMailroom if native._lib is not None else PythonMailroom).load(path, call, clock)  # whichever kind is in use
