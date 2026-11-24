/*
 * mail.cpp - the Kestrel library: store and forward, the mail a station keeps between contacts.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * The C++ version of link/mail.py's Mailroom, method for method (spec
 * Section 8): the station's message numbers, its own messages to named
 * stations, the messages it carries for others, the IDs it has handled,
 * the delivery receipts it announces, and what other stations said in their
 * mail notices. It reads and writes the same mail file as the Python
 * version (JSON, same layout), so either can pick up where the other left.
 *
 * Callers talk to it through one C function, kes_mail_request, with a small
 * JSON request ({"op": method name, "args": [...]}) and the time; the reply
 * is {"ok": answer} or {"error": the Python error's name, "message": ...}.
 * That keeps the interface to any language a single function, and lets the
 * tests drive the Python and C++ versions with the same calls.
 */

#define KESTREL_BUILDING 1  /* this file builds the library, so its functions are exported */
#include "kestrel.h"  /* the interface being implemented */
#include "internal.hpp"  /* the station's way in */
#include "json.hpp"  /* the mail file and the requests */

#include <algorithm>  /* stable_sort, find */
#include <cmath>  /* fmod, floor, copysign */
#include <cstring>  /* memcpy */
#include <mutex>  /* one change at a time */
#include <random>  /* the first message number of a new station */
#include <string>  /* text */
#include <utility>  /* pair */
#include <vector>  /* growable arrays */

namespace {  /* helpers seen only inside this file */

using kes::Json;  /* the JSON value */

const long long kIds = 1LL << 16;  /* message numbers 0..65535 (modem/params.py MSG_ID_BITS) */
const int kSlots = 3;  /* entries per mail notice list (NOTICE_SLOTS) */
const double kHour = 3600.0;  /* seconds in an hour (mail.py HOUR) */
const double kLifeHours = 62;  /* how long mail lives (link/params.py MAIL_LIFE_HOURS) */
const int kHopLimit = 4;  /* the most relays (HOP_LIMIT) */
const double kReceiptHours = 12;  /* how long a receipt is listed (RECEIPT_LIST_H) */
const size_t kHandedMost = 3;  /* carriers per own message (HANDED_MOST) */
const size_t kPassedMost = 2;  /* carriers per held message (PASSED_MOST) */
const double kReachS = 7200.0;  /* how long a notice's "heard" list counts (REACH_S) */
const size_t kBagMost = 50;  /* the most held messages (BAG_MOST) */
const int kBagPerOrigin = 10;  /* the most from one origin (BAG_PER_ORIGIN) */

struct PyError {  /* an error the Python version would raise */
    std::string kind;  /* its name: ValueError, RuntimeError ... */
    std::string message;  /* its words */
};  /* end of PyError */

/* address.py clean_call through the compiled packer: the tidy address, or ValueError. */
std::string clean(const std::string &call) {  /* the address */
    uint8_t bits[48];  /* its bits */
    if (kes_call_to_bits(call.c_str(), bits) != 0 || call.find('\0') != std::string::npos) {  /* not an address */
        throw PyError{"ValueError", "not a valid address: " + call};  /* as Python */
    }  /* end of the check */
    char out[10];  /* the address read back: tidy */
    kes_bits_to_call(bits, out);  /* read back */
    return out;  /* tidy */
}  /* end of clean */

long call_hash(const std::string &call) {  /* address.py call_hash, or ValueError */
    long h = kes_call_hash(call.c_str());  /* the code */
    if (h < 0) {  /* not an address */
        throw PyError{"ValueError", "not a valid address: " + call};  /* as Python */
    }  /* end of the check */
    return h;  /* the code */
}  /* end of call_hash */

long message_hash(const std::string &origin, long long id) {  /* address.py message_hash, or ValueError */
    long h = kes_message_hash(origin.c_str(), static_cast<long>(id & 0xFFFF));  /* the code (only the lowest 16 bits count) */
    if (h < 0) {  /* not an address */
        throw PyError{"ValueError", "not a valid address: " + origin};  /* as Python */
    }  /* end of the check */
    return h;  /* the code */
}  /* end of message_hash */

std::string key(const std::string &origin, long long id) {  /* mail.py key: "ORIGIN#number" */
    return clean(origin) + "#" + std::to_string(id);  /* callsign and number */
}  /* end of key */

/* Python's float floor division a // b, exactly as CPython does it. */
double floor_div(double a, double b) {  /* the quotient, rounded down */
    double mod = std::fmod(a, b);  /* the remainder */
    double div = (a - mod) / b;  /* nearly the quotient */
    if (mod != 0.0) {  /* not exact */
        if ((b < 0) != (mod < 0)) {  /* the remainder has the wrong sign */
            div -= 1.0;  /* one less */
        }  /* end of the sign fix */
    }  /* end of the inexact case */
    if (div != 0.0) {  /* not zero */
        double floored = std::floor(div);  /* rounded down */
        if (div - floored > 0.5) {  /* rounding error made it too small */
            floored += 1.0;  /* fixed */
        }  /* end of the fix */
        return floored;  /* the quotient */
    }  /* end of the non-zero case */
    return std::copysign(0.0, a / b);  /* a signed zero */
}  /* end of floor_div */

/* Ordered map from text to a value, with Python dict behavior: a new key goes at the end, an old one keeps its place. */
template <typename T>
struct Ordered {  /* the map */
    std::vector<std::pair<std::string, T>> items;  /* in order */
    T *find(const std::string &k) {  /* the value, or nullptr */
        for (auto &p : items) {  /* each */
            if (p.first == k) {  /* this one */
                return &p.second;  /* found */
            }  /* end of the test */
        }  /* end of the items */
        return nullptr;  /* not there */
    }  /* end of find */
    void set(const std::string &k, T v) {  /* d[k] = v */
        T *old = find(k);  /* already there? */
        if (old != nullptr) {  /* yes */
            *old = std::move(v);  /* replaced in its place */
        } else {  /* no */
            items.emplace_back(k, std::move(v));  /* added at the end */
        }  /* end of the choice */
    }  /* end of set */
    bool erase(const std::string &k) {  /* d.pop(k, None) */
        for (auto it = items.begin(); it != items.end(); ++it) {  /* each */
            if (it->first == k) {  /* this one */
                items.erase(it);  /* gone */
                return true;  /* was there */
            }  /* end of the test */
        }  /* end of the items */
        return false;  /* was not */
    }  /* end of erase */
};  /* end of Ordered */

struct Own {  /* one of this station's own messages: {"text", "dest", "carriers", "expires"} */
    std::string text;  /* the message */
    std::string dest;  /* who it is for */
    std::vector<std::string> carriers;  /* stations that took a copy to carry */
    Json expires;  /* when it expires (a number, kept as Python wrote it) */
};  /* end of Own */

struct Held {  /* a message held for another station */
    std::string dest;  /* who it is for */
    std::string origin;  /* who wrote it */
    long long id = 0;  /* its number */
    std::string text;  /* the message */
    long long hops = 0;  /* relays so far */
    Json expires;  /* when it expires */
    Json came_from;  /* the station that passed it here */
    Json got;  /* when it came */
    std::vector<std::string> carriers;  /* stations it was passed on to */
};  /* end of Held */

struct Receipt {  /* a delivery receipt being announced */
    Json until;  /* listed until */
    Json dest;  /* who it was delivered to */
};  /* end of Receipt */

struct Reach {  /* the last mail notice heard from one station */
    Json when;  /* when it was heard */
    std::vector<long long> held;  /* codes of stations it holds mail for */
    std::vector<long long> heard;  /* codes of stations it hears */
    std::vector<long long> receipts;  /* codes of the receipts it reported */
};  /* end of Reach */

Json texts(const std::vector<std::string> &v) {  /* a list of text as JSON */
    Json l = Json::list();  /* empty */
    for (const auto &s : v) {  /* each */
        l.push(Json(s));  /* added */
    }  /* end of the items */
    return l;  /* the list */
}  /* end of texts */

Json numbers(const std::vector<long long> &v) {  /* a list of numbers as JSON */
    Json l = Json::list();  /* empty */
    for (long long n : v) {  /* each */
        l.push(Json(n));  /* added */
    }  /* end of the items */
    return l;  /* the list */
}  /* end of numbers */

std::vector<std::string> read_texts(const Json &j) {  /* a JSON list of text */
    std::vector<std::string> v;  /* the list */
    for (const auto &x : j.items()) {  /* each */
        v.push_back(x.as_text());  /* kept */
    }  /* end of the items */
    return v;  /* the list */
}  /* end of read_texts */

std::vector<long long> read_numbers(const Json &j) {  /* a JSON list of whole numbers */
    std::vector<long long> v;  /* the list */
    for (const auto &x : j.items()) {  /* each */
        v.push_back(x.as_int());  /* kept */
    }  /* end of the items */
    return v;  /* the list */
}  /* end of read_numbers */

bool contains(const std::vector<std::string> &v, const std::string &s) {  /* s in v */
    return std::find(v.begin(), v.end(), s) != v.end();  /* found? */
}  /* end of contains */

bool contains(const std::vector<long long> &v, long long n) {  /* n in v */
    return std::find(v.begin(), v.end(), n) != v.end();  /* found? */
}  /* end of contains */

}  /* end of the private helpers */

/* The mail store (link/mail.py Mailroom). */
struct KesMail {  /* one station's mail */
    std::recursive_mutex lock;  /* one change at a time */
    double now = 0.0;  /* the time of the request being served (Python: self.clock()) */
    Json now_json;  /* the same, as given (a whole number stays whole, as Python's clock value) */
    std::string call;  /* the station's own callsign ("" for none) */
    long long next_id = 0;  /* the next message number */
    std::vector<std::pair<long long, Own>> own;  /* message number -> own message, in order */
    std::vector<Held> bag;  /* held messages, oldest first */
    Ordered<double> handled;  /* message ID -> when it may be forgotten */
    Ordered<Receipt> receipts;  /* message ID -> receipt */
    Ordered<Reach> reach;  /* callsign -> last notice */
    Json news = Json::list();  /* [kind, details] for the panel (not saved) */
    std::string reply;  /* the last reply, until the caller collects it */

    KesMail() {  /* a new, empty store */
        std::random_device rd;  /* a source of randomness */
        next_id = static_cast<long long>(rd() % kIds);  /* a new station starts at a random number */
    }  /* end of the constructor */

    Json clock() const { return now_json; }  /* Python's self.clock() */

    void say(const char *kind, Json details) {  /* add to the news */
        Json entry = Json::list();  /* [kind, details] */
        entry.push(Json(kind));  /* the kind */
        entry.push(std::move(details));  /* the details */
        news.push(std::move(entry));  /* added */
    }  /* end of say */

    Own *own_find(long long number) {  /* self.own.get(str(number)) */
        for (auto &p : own) {  /* each */
            if (p.first == number) {  /* this one */
                return &p.second;  /* found */
            }  /* end of the test */
        }  /* end of the messages */
        return nullptr;  /* not there */
    }  /* end of own_find */

    Json own_json(const Own &o) const {  /* an own message as Python's dict */
        Json j = Json::object();  /* the dict */
        j["text"] = o.text;  /* text */
        j["dest"] = o.dest;  /* destination */
        j["carriers"] = texts(o.carriers);  /* carriers */
        j["expires"] = o.expires;  /* expiry */
        return j;  /* the dict */
    }  /* end of own_json */

    Json held_json(const Held &h) const {  /* a held message as Python's dict */
        Json j = Json::object();  /* the dict */
        j["dest"] = h.dest;  /* destination */
        j["origin"] = h.origin;  /* origin */
        j["id"] = h.id;  /* number */
        j["text"] = h.text;  /* text */
        j["hops"] = h.hops;  /* relays */
        j["expires"] = h.expires;  /* expiry */
        j["came_from"] = h.came_from;  /* who passed it here */
        j["got"] = h.got;  /* when */
        j["carriers"] = texts(h.carriers);  /* passed on to */
        return j;  /* the dict */
    }  /* end of held_json */

    /* ---- message numbers and this station's own messages ---- */

    long long new_number() {  /* the next unused message number */
        for (long long n = 0; n < kIds; ++n) {  /* at most once round */
            long long number = next_id;  /* the candidate */
            next_id = (number + 1) % kIds;  /* the counter moves on */
            if (own_find(number) == nullptr) {  /* not taken */
                return number;  /* use it */
            }  /* end of the test */
        }  /* end of the search */
        throw PyError{"RuntimeError", "every message number is in use"};  /* cannot happen */
    }  /* end of new_number */

    long long own_add(const std::string &text, const std::string &dest_in, const std::vector<long long> &taken) {  /* a message to a named station is queued */
        std::string dest = clean(dest_in);  /* tidied */
        for (const auto &p : own) {  /* waiting messages */
            if (p.second.text == text && p.second.dest == dest && !contains(taken, p.first)) {  /* the same message, not in the outbox */
                return p.first;  /* the same number */
            }  /* end of the test */
        }  /* end of the messages */
        long long number = new_number();  /* a new message */
        own.emplace_back(number, Own{text, dest, {}, Json(now + kLifeHours * kHour)});  /* remembered */
        return number;  /* its number */
    }  /* end of own_add */

    void own_drop(long long number) {  /* the operator took a message back */
        for (auto it = own.begin(); it != own.end(); ++it) {  /* each */
            if (it->first == number) {  /* this one */
                own.erase(it);  /* forgotten */
                return;  /* done */
            }  /* end of the test */
        }  /* end of the messages */
    }  /* end of own_drop */

    void own_carried(long long number, const std::string &carrier) {  /* a station took a copy to carry */
        Own *o = own_find(number);  /* the message */
        if (o != nullptr && !contains(o->carriers, carrier)) {  /* waiting, a new carrier */
            o->carriers.push_back(carrier);  /* noted */
            Json d = Json::object();  /* the news */
            d["id"] = number;  /* which */
            d["text"] = o->text;  /* text */
            d["dest"] = o->dest;  /* for whom */
            d["carrier"] = carrier;  /* carried by */
            say("carried", d);  /* told */
        }  /* end of the change */
    }  /* end of own_carried */

    bool can_hand(long long number, const std::string &partner) {  /* may this message be handed to `partner`? */
        Own *o = own_find(number);  /* the message */
        return o != nullptr && partner != o->dest && !contains(o->carriers, partner) && o->carriers.size() < kHandedMost && o->expires.as_real() > now;  /* waiting, a new carrier, room, live */
    }  /* end of can_hand */

    Json own_done(long long number, const Json &via) {  /* this station's message is known delivered */
        for (auto it = own.begin(); it != own.end(); ++it) {  /* each */
            if (it->first == number) {  /* this one */
                Own o = it->second;  /* taken out */
                own.erase(it);  /* gone */
                if (!o.carriers.empty()) {  /* copies are out with carriers */
                    add_receipt(call, number, Json(o.dest));  /* announced, so they drop them */
                }  /* end of the receipt */
                Json d = Json::object();  /* the news */
                d["id"] = number;  /* which */
                d["text"] = o.text;  /* text */
                d["dest"] = o.dest;  /* for whom */
                d["via"] = via;  /* reported by */
                say("delivered", d);  /* told */
                return own_json(o);  /* what it was */
            }  /* end of the test */
        }  /* end of the messages */
        return Json();  /* already gone */
    }  /* end of own_done */

    long long life_hours(double expires) const {  /* the lifetime a frame should carry */
        double left = -floor_div(-(expires - now), kHour);  /* whole hours left, rounded up */
        long long hours = static_cast<long long>(left);  /* as Python's int() */
        return std::max(1LL, std::min(static_cast<long long>(kLifeHours), hours));  /* at least one, at most the longest */
    }  /* end of life_hours */

    /* ---- messages carried for others ---- */

    bool has_room(const std::string &origin) const {  /* could another message from `origin` be held? */
        int from = 0;  /* how many held from it */
        for (const auto &h : bag) {  /* each held */
            from += h.origin == origin ? 1 : 0;  /* counted */
        }  /* end of the bag */
        return bag.size() < kBagMost && from < kBagPerOrigin;  /* within both limits */
    }  /* end of has_room */

    Held *bag_find(const std::string &origin, long long number) {  /* one held message, or nullptr */
        for (auto &h : bag) {  /* each */
            if (h.origin == origin && h.id == number) {  /* this one */
                return &h;  /* found */
            }  /* end of the test */
        }  /* end of the bag */
        return nullptr;  /* not held */
    }  /* end of bag_find */

    bool hold(const std::string &dest, const std::string &origin, long long number, const std::string &text, long long hops, const Json &life_hours,
              const Json &came_from) {  /* keep a message for another station */
        if (bag_find(origin, number) != nullptr || is_handled(origin, number) || !has_room(origin)) {  /* a duplicate, or no room */
            return false;  /* not taken */
        }  /* end of the check */
        Held h;  /* the new entry */
        h.dest = dest;  /* for whom */
        h.origin = origin;  /* from whom */
        h.id = number;  /* number */
        h.text = text;  /* text */
        h.hops = hops;  /* relays */
        h.expires = Json(now + life_hours.as_real() * kHour);  /* expiry */
        h.came_from = came_from;  /* passed here by */
        h.got = clock();  /* when */
        bag.push_back(h);  /* held */
        Json d = Json::object();  /* the news */
        d["id"] = number;  /* which */
        d["dest"] = dest;  /* for whom */
        d["origin"] = origin;  /* from whom */
        d["came_from"] = came_from;  /* passed here by */
        say("held", d);  /* told */
        return true;  /* held */
    }  /* end of hold */

    Json held_for(const std::string &dest) const {  /* held messages for one station that may still be sent */
        Json l = Json::list();  /* the list */
        for (const auto &h : bag) {  /* each */
            if (h.dest == dest && h.expires.as_real() > now && h.hops + 1 <= kHopLimit) {  /* live, within the hop limit */
                l.push(held_json(h));  /* listed */
            }  /* end of the test */
        }  /* end of the bag */
        return l;  /* the list */
    }  /* end of held_for */

    Json to_pass(const std::string &partner) {  /* a held message `partner` could carry on */
        for (const auto &h : bag) {  /* oldest first */
            if (h.dest != partner && !(h.came_from.is_text() && h.came_from.as_text() == partner) && partner != h.origin && !contains(h.carriers, partner) &&
                h.carriers.size() < kPassedMost && h.hops + 2 <= kHopLimit && h.expires.as_real() > now && reaches(partner, h.dest)) {  /* every condition */
                return held_json(h);  /* this one */
            }  /* end of the test */
        }  /* end of the bag */
        return Json();  /* nothing */
    }  /* end of to_pass */

    void passed(const std::string &origin, long long number, const std::string &carrier) {  /* a held message was passed on */
        Held *h = bag_find(origin, number);  /* the message */
        if (h != nullptr && !contains(h->carriers, carrier)) {  /* held, a new carrier */
            h->carriers.push_back(carrier);  /* noted */
            Json d = Json::object();  /* the news */
            d["id"] = number;  /* which */
            d["dest"] = h->dest;  /* for whom */
            d["origin"] = origin;  /* from whom */
            d["carrier"] = carrier;  /* passed to */
            say("passed", d);  /* told */
        }  /* end of the change */
    }  /* end of passed */

    void delivered_held(const std::string &origin, long long number, const Json &dest) {  /* a held message reached its destination */
        for (auto it = bag.begin(); it != bag.end(); ++it) {  /* each */
            if (it->origin == origin && it->id == number) {  /* this one */
                bag.erase(it);  /* dropped */
                Json d = Json::object();  /* the news */
                d["id"] = number;  /* which */
                d["dest"] = dest;  /* for whom */
                d["origin"] = origin;  /* from whom */
                say("handed over", d);  /* told */
                break;  /* done */
            }  /* end of the test */
        }  /* end of the bag */
        mark_handled(origin, number);  /* never take it again */
        add_receipt(origin, number, dest);  /* and announce the delivery */
    }  /* end of delivered_held */

    /* ---- what has been handled, and receipts ---- */

    void mark_handled(const std::string &origin, long long number) {  /* this message has been dealt with here */
        handled.set(key(origin, number), now + kLifeHours * kHour);  /* remembered as long as any copy could live */
    }  /* end of mark_handled */

    bool is_handled(const std::string &origin, long long number) {  /* has it been dealt with here? */
        double *until = handled.find(key(origin, number));  /* when it may be forgotten */
        return (until != nullptr ? *until : 0.0) > now;  /* and not yet forgotten */
    }  /* end of is_handled */

    void add_receipt(const std::string &origin, long long number, const Json &dest) {  /* announce a delivery */
        receipts.set(key(origin, number), Receipt{Json(now + kReceiptHours * kHour), dest});  /* for twelve hours */
    }  /* end of add_receipt */

    /* ---- mail notices ---- */

    Json notice_lists(const std::vector<std::string> &heard_calls) {  /* what the next mail notice should say */
        std::vector<long long> held;  /* stations mail is held for */
        for (const auto &h : bag) {  /* held messages */
            long long code = call_hash(h.dest);  /* the destination's code */
            if (h.expires.as_real() > now && !contains(held, code)) {  /* live, not listed yet */
                held.push_back(code);  /* listed */
            }  /* end of the test */
        }  /* end of the bag */
        std::vector<std::pair<std::string, Receipt>> order(receipts.items);  /* receipts... */
        std::stable_sort(order.begin(), order.end(), [](const auto &a, const auto &b) { return -a.second.until.as_real() < -b.second.until.as_real(); });  /* ...newest first */
        std::vector<long long> codes;  /* their codes */
        for (const auto &p : order) {  /* each */
            if (p.second.until.as_real() > now) {  /* still listed */
                size_t hash_at = p.first.rfind('#');  /* the split between origin and number */
                codes.push_back(message_hash(p.first.substr(0, hash_at), std::stoll(p.first.substr(hash_at + 1))));  /* its code */
            }  /* end of the test */
        }  /* end of the receipts */
        Json out = Json::list();  /* [held, receipts, heard] */
        if (held.empty() && codes.empty()) {  /* nothing worth a notice */
            out.push(Json::list());  /* empty */
            out.push(Json::list());  /* empty */
            out.push(Json::list());  /* empty */
            return out;  /* no notice */
        }  /* end of the empty case */
        std::vector<long long> heard;  /* stations this one hears */
        for (const auto &c : heard_calls) {  /* most recent first */
            if (c != call) {  /* not itself */
                heard.push_back(call_hash(c));  /* its code */
            }  /* end of the test */
        }  /* end of the calls */
        held.resize(std::min(held.size(), static_cast<size_t>(kSlots)));  /* three at most */
        codes.resize(std::min(codes.size(), static_cast<size_t>(kSlots)));  /* three at most */
        heard.resize(std::min(heard.size(), static_cast<size_t>(kSlots)));  /* three at most */
        out.push(numbers(held));  /* held */
        out.push(numbers(codes));  /* receipts */
        out.push(numbers(heard));  /* heard */
        return out;  /* the lists */
    }  /* end of notice_lists */

    Json heard_notice(const std::string &origin, const std::vector<long long> &held, const std::vector<long long> &rec, const std::vector<long long> &heard) {  /* a mail notice was heard */
        reach.set(origin, Reach{clock(), held, heard, rec});  /* what it said */
        Json done = Json::list();  /* own messages now known delivered */
        std::vector<long long> numbers_now;  /* this station's waiting messages */
        for (const auto &p : own) {  /* list(self.own) */
            numbers_now.push_back(p.first);  /* each */
        }  /* end of the copy */
        for (long long number : numbers_now) {  /* each */
            if (contains(rec, message_hash(call, number))) {  /* delivered */
                own_done(number, Json(origin));  /* forgotten */
                done.push(Json(number));  /* reported */
            }  /* end of the test */
        }  /* end of the messages */
        std::vector<Held> copy(bag);  /* list(self.bag) */
        for (const auto &h : copy) {  /* each held */
            if (contains(rec, message_hash(h.origin, h.id))) {  /* delivered by someone */
                for (auto it = bag.begin(); it != bag.end(); ++it) {  /* find it */
                    if (it->origin == h.origin && it->id == h.id && it->dest == h.dest) {  /* this one */
                        bag.erase(it);  /* dropped */
                        break;  /* done */
                    }  /* end of the test */
                }  /* end of the search */
                mark_handled(h.origin, h.id);  /* never take it again */
                Json d = Json::object();  /* the news */
                d["id"] = h.id;  /* which */
                d["dest"] = h.dest;  /* for whom */
                d["origin"] = h.origin;  /* from whom */
                d["via"] = origin;  /* reported by */
                say("dropped", d);  /* told */
            }  /* end of the test */
        }  /* end of the bag */
        return done;  /* for the station */
    }  /* end of heard_notice */

    bool reaches(const std::string &station, const std::string &dest) {  /* does `station` say it hears `dest`? */
        Reach *seen = reach.find(station);  /* its last notice */
        return seen != nullptr && now - seen->when.as_real() <= kReachS && contains(seen->heard, call_hash(dest));  /* recent, listing the destination */
    }  /* end of reaches */

    bool holds_for_me(const std::string &station) {  /* did its last notice say it holds mail for this station? */
        Reach *seen = reach.find(station);  /* its last notice */
        return seen != nullptr && now - seen->when.as_real() <= kLifeHours * kHour && contains(seen->held, call_hash(call));  /* within the life of mail, listing this station */
    }  /* end of holds_for_me */

    void forget_held_for_me(const std::string &station) {  /* that station has delivered, or had nothing */
        Reach *seen = reach.find(station);  /* its last notice */
        if (seen != nullptr) {  /* one was heard */
            long long mine = call_hash(call);  /* this station's code */
            seen->held.erase(std::remove(seen->held.begin(), seen->held.end(), mine), seen->held.end());  /* no longer waiting there */
        }  /* end of the change */
    }  /* end of forget_held_for_me */

    /* ---- tidying and keeping ---- */

    Json tidy() {  /* let expired mail go */
        Json expired = Json::list();  /* own messages that expired */
        std::vector<long long> gone;  /* their numbers */
        for (const auto &p : own) {  /* each */
            if (p.second.expires.as_real() <= now) {  /* out of time */
                gone.push_back(p.first);  /* noted */
            }  /* end of the test */
        }  /* end of the messages */
        for (long long number : gone) {  /* each */
            Own o = *own_find(number);  /* the message */
            own_drop(number);  /* forgotten */
            Json d = Json::object();  /* the news */
            d["id"] = number;  /* which */
            d["text"] = o.text;  /* text */
            d["dest"] = o.dest;  /* for whom */
            say("expired", d);  /* told */
            expired.push(Json(number));  /* reported */
        }  /* end of the expired */
        std::vector<Held> out_of_time;  /* held messages out of time */
        for (const auto &h : bag) {  /* each */
            if (h.expires.as_real() <= now) {  /* out of time */
                out_of_time.push_back(h);  /* noted */
            }  /* end of the test */
        }  /* end of the bag */
        for (const auto &h : out_of_time) {  /* each */
            for (auto it = bag.begin(); it != bag.end(); ++it) {  /* find it (the first equal entry, as list.remove) */
                if (it->origin == h.origin && it->id == h.id && it->dest == h.dest && it->expires.as_real() == h.expires.as_real()) {  /* this one */
                    bag.erase(it);  /* dropped */
                    break;  /* done */
                }  /* end of the test */
            }  /* end of the search */
            mark_handled(h.origin, h.id);  /* not taken again */
            Json d = Json::object();  /* the news */
            d["id"] = h.id;  /* which */
            d["dest"] = h.dest;  /* for whom */
            d["origin"] = h.origin;  /* from whom */
            d["via"] = Json();  /* nobody */
            say("dropped", d);  /* told */
        }  /* end of the held */
        Ordered<double> kept;  /* handled IDs still remembered */
        for (const auto &p : handled.items) {  /* each */
            if (p.second > now) {  /* not yet forgotten */
                kept.items.push_back(p);  /* kept */
            }  /* end of the test */
        }  /* end of the IDs */
        handled = kept;  /* the rest forgotten */
        Ordered<Receipt> listed;  /* receipts still listed */
        for (const auto &p : receipts.items) {  /* each */
            if (p.second.until.as_real() > now) {  /* still listed */
                listed.items.push_back(p);  /* kept */
            }  /* end of the test */
        }  /* end of the receipts */
        receipts = listed;  /* the rest gone */
        Ordered<Reach> recent;  /* notices still remembered */
        for (const auto &p : reach.items) {  /* each */
            if (now - p.second.when.as_real() <= kLifeHours * kHour) {  /* recent */
                recent.items.push_back(p);  /* kept */
            }  /* end of the test */
        }  /* end of the notices */
        reach = recent;  /* the rest forgotten */
        return expired;  /* for the station */
    }  /* end of tidy */

    Json take_news() {  /* what has happened since the panel last looked */
        Json out = news;  /* handed over */
        news = Json::list();  /* emptied */
        return out;  /* oldest first */
    }  /* end of take_news */

    Json to_dict() const {  /* everything worth keeping, in the mail file's layout */
        Json d = Json::object();  /* the store */
        d["call"] = call;  /* callsign */
        d["next_id"] = next_id;  /* next number */
        Json o = Json::object();  /* own messages */
        for (const auto &p : own) {  /* each */
            o[std::to_string(p.first)] = own_json(p.second);  /* keyed by number, as text */
        }  /* end of the own */
        d["own"] = o;  /* added */
        Json b = Json::list();  /* held messages */
        for (const auto &h : bag) {  /* each */
            b.push(held_json(h));  /* added */
        }  /* end of the bag */
        d["bag"] = b;  /* added */
        Json hd = Json::object();  /* handled IDs */
        for (const auto &p : handled.items) {  /* each */
            hd[p.first] = Json(p.second);  /* until */
        }  /* end of the IDs */
        d["handled"] = hd;  /* added */
        Json r = Json::object();  /* receipts */
        for (const auto &p : receipts.items) {  /* each */
            Json e = Json::object();  /* the entry */
            e["until"] = p.second.until;  /* until */
            e["dest"] = p.second.dest;  /* for whom */
            r[p.first] = e;  /* added */
        }  /* end of the receipts */
        d["receipts"] = r;  /* added */
        Json re = Json::object();  /* notices */
        for (const auto &p : reach.items) {  /* each */
            Json e = Json::object();  /* the entry */
            e["when"] = p.second.when;  /* when */
            e["held"] = numbers(p.second.held);  /* held for */
            e["heard"] = numbers(p.second.heard);  /* heard */
            e["receipts"] = numbers(p.second.receipts);  /* receipts */
            re[p.first] = e;  /* added */
        }  /* end of the notices */
        d["reach"] = re;  /* added */
        return d;  /* the store */
    }  /* end of to_dict */

    bool from_dict(const Json &data) {  /* Mailroom.load, after the file is read: false (and nothing changed) if it is not this station's or not readable */
        if (!data.is_object()) {  /* not a store */
            return false;  /* start empty */
        }  /* end of the check */
        const Json *kept_call = data.find("call");  /* whose mail it is */
        if (kept_call != nullptr && kept_call->is_text() && !kept_call->as_text().empty() && !call.empty() && kept_call->as_text() != call) {  /* another station's */
            return false;  /* start empty */
        }  /* end of the check */
        try {  /* the parts must have the right shapes */
            long long next = next_id;  /* the counter */
            if (const Json *n = data.find("next_id")) {  /* kept */
                next = ((n->as_int() % kIds) + kIds) % kIds;  /* carried on (Python's % is never negative) */
            }  /* end of the counter */
            std::vector<std::pair<long long, Own>> o2;  /* own messages */
            if (const Json *o = data.find("own")) {  /* kept */
                for (const auto &m : o->members()) {  /* each */
                    const Json &v = m.second;  /* the entry */
                    o2.emplace_back(std::stoll(m.first), Own{v.at("text").as_text(), v.at("dest").as_text(), read_texts(v.at("carriers")), v.at("expires")});  /* read */
                }  /* end of the own */
            } else {  /* not kept */
                o2 = own;  /* as before */
            }  /* end of the own */
            std::vector<Held> b2;  /* held messages */
            if (const Json *b = data.find("bag")) {  /* kept */
                for (const auto &v : b->items()) {  /* each */
                    Held h;  /* the entry */
                    h.dest = v.at("dest").as_text();  /* for whom */
                    h.origin = v.at("origin").as_text();  /* from whom */
                    h.id = v.at("id").as_int();  /* number */
                    h.text = v.at("text").as_text();  /* text */
                    h.hops = v.at("hops").as_int();  /* relays */
                    h.expires = v.at("expires");  /* expiry */
                    h.came_from = v.at("came_from");  /* passed by */
                    h.got = v.at("got");  /* when */
                    h.carriers = read_texts(v.at("carriers"));  /* passed to */
                    b2.push_back(h);  /* kept */
                }  /* end of the bag */
            } else {  /* not kept */
                b2 = bag;  /* as before */
            }  /* end of the bag */
            Ordered<double> h2 = handled;  /* handled IDs */
            if (const Json *h = data.find("handled")) {  /* kept */
                h2 = Ordered<double>();  /* replaced */
                for (const auto &m : h->members()) {  /* each */
                    h2.set(m.first, m.second.as_real());  /* until */
                }  /* end of the IDs */
            }  /* end of the IDs */
            Ordered<Receipt> r2 = receipts;  /* receipts */
            if (const Json *r = data.find("receipts")) {  /* kept */
                r2 = Ordered<Receipt>();  /* replaced */
                for (const auto &m : r->members()) {  /* each */
                    r2.set(m.first, Receipt{m.second.at("until"), m.second.at("dest")});  /* the entry */
                }  /* end of the receipts */
            }  /* end of the receipts */
            Ordered<Reach> re2 = reach;  /* notices */
            if (const Json *re = data.find("reach")) {  /* kept */
                re2 = Ordered<Reach>();  /* replaced */
                for (const auto &m : re->members()) {  /* each */
                    re2.set(m.first, Reach{m.second.at("when"), read_numbers(m.second.at("held")), read_numbers(m.second.at("heard")), read_numbers(m.second.at("receipts"))});  /* the entry */
                }  /* end of the notices */
            }  /* end of the notices */
            next_id = next;  /* all read: take them */
            own = o2;  /* own */
            bag = b2;  /* bag */
            handled = h2;  /* handled */
            receipts = r2;  /* receipts */
            reach = re2;  /* notices */
        } catch (const std::exception &) {  /* a part had the wrong shape */
            return false;  /* start empty */
        }  /* end of the reading */
        tidy();  /* anything that expired while closed goes now */
        return true;  /* loaded */
    }  /* end of from_dict */

    Json serve(const std::string &op, const Json &a) {  /* run one request */
        auto text = [&](size_t i) { return a.at(i).as_text(); };  /* a text argument */
        auto whole = [&](size_t i) { return a.at(i).as_int(); };  /* a whole-number argument */
        auto calls = [&](size_t i) { return read_texts(a.at(i)); };  /* a list of callsigns */
        auto codes = [&](size_t i) { return read_numbers(a.at(i)); };  /* a list of codes */
        if (op == "init") {  /* set the callsign and counter */
            call = text(0).empty() ? std::string() : clean(text(0));  /* the callsign */
            if (a.items().size() > 1 && !a.at(1).is_null()) {  /* a counter given */
                next_id = ((whole(1) % kIds) + kIds) % kIds;  /* taken */
            }  /* end of the counter */
            return Json();  /* nothing */
        }  /* end of init */
        if (op == "new_number") { return Json(new_number()); }  /* the next number */
        if (op == "own_add") { return Json(own_add(text(0), text(1), a.items().size() > 2 ? codes(2) : std::vector<long long>())); }  /* queued */
        if (op == "own_drop") { own_drop(whole(0)); return Json(); }  /* dropped */
        if (op == "own_item") { Own *o = own_find(whole(0)); return o ? own_json(*o) : Json(); }  /* one message */
        if (op == "own_carried") { own_carried(whole(0), text(1)); return Json(); }  /* carried */
        if (op == "can_hand") { return Json(can_hand(whole(0), text(1))); }  /* may hand? */
        if (op == "own_done") { return own_done(whole(0), a.items().size() > 1 ? a.at(1) : Json()); }  /* delivered */
        if (op == "life_hours") { return Json(life_hours(a.at(0).as_real())); }  /* hours to carry */
        if (op == "has_room") { return Json(has_room(text(0))); }  /* room? */
        if (op == "holding") { return Json(bag_find(text(0), whole(1)) != nullptr); }  /* held? */
        if (op == "hold") { return Json(hold(text(0), text(1), whole(2), text(3), whole(4), a.at(5), a.at(6))); }  /* held */
        if (op == "bag_item") { Held *h = bag_find(text(0), whole(1)); return h ? held_json(*h) : Json(); }  /* one held */
        if (op == "held_for") { return held_for(text(0)); }  /* held for one */
        if (op == "to_pass") { return to_pass(text(0)); }  /* one to pass on */
        if (op == "passed") { passed(text(0), whole(1), text(2)); return Json(); }  /* passed */
        if (op == "delivered_held") { delivered_held(text(0), whole(1), a.at(2)); return Json(); }  /* delivered */
        if (op == "mark_handled") { mark_handled(text(0), whole(1)); return Json(); }  /* handled */
        if (op == "is_handled") { return Json(is_handled(text(0), whole(1))); }  /* handled? */
        if (op == "add_receipt") { add_receipt(text(0), whole(1), a.at(2)); return Json(); }  /* receipt */
        if (op == "notice_lists") { return notice_lists(a.items().empty() ? std::vector<std::string>() : calls(0)); }  /* the notice */
        if (op == "heard_notice") { return heard_notice(text(0), codes(1), codes(2), codes(3)); }  /* a notice heard */
        if (op == "reaches") { return Json(reaches(text(0), text(1))); }  /* reaches? */
        if (op == "holds_for_me") { return Json(holds_for_me(text(0))); }  /* holds for me? */
        if (op == "forget_held_for_me") { forget_held_for_me(text(0)); return Json(); }  /* forgotten */
        if (op == "tidy") { return tidy(); }  /* tidied */
        if (op == "take_news") { return take_news(); }  /* the news */
        if (op == "to_dict") { return to_dict(); }  /* the store */
        if (op == "bag_count") { return Json(static_cast<long long>(bag.size())); }  /* how many held (bool(self.bag) without copying them) */
        if (op == "from_dict") { return Json(from_dict(a.at(0))); }  /* loaded */
        throw PyError{"AttributeError", "no such mail operation: " + op};  /* unknown */
    }  /* end of serve */
};  /* end of KesMail */

extern "C" {  /* the mail store's C interface */

KES_API KesMail *kes_mail_new(void) {  /* a new, empty store */
    return new KesMail();  /* made */
}  /* end of kes_mail_new */

KES_API void kes_mail_free(KesMail *m) {  /* done with it */
    delete m;  /* freed */
}  /* end of kes_mail_free */

}  /* end of the mail store's C interface (first part) */

namespace {  /* the request runner, shared by both ways in */

std::string run_request(KesMail *m, const char *request, double now) {  /* one request, its reply as text (the caller holds the lock) */
    Json reply = Json::object();  /* the answer */
    try {  /* any step may fail */
        Json req = Json::parse(request);  /* the request */
        m->now = now;  /* the time */
        const Json *given = req.find("now");  /* the time as the caller's clock gave it (whole or not) */
        m->now_json = (given != nullptr && given->is_number()) ? *given : Json(now);  /* kept for "got" and "when" */
        const Json *args = req.find("args");  /* the arguments */
        reply["ok"] = m->serve(req.at("op").as_text(), args != nullptr ? *args : Json::list());  /* served */
    } catch (const PyError &e) {  /* an error Python would raise */
        reply = Json::object();  /* start again */
        reply["error"] = e.kind;  /* its name */
        reply["message"] = e.message;  /* its words */
    } catch (const std::exception &e) {  /* a bad request */
        reply = Json::object();  /* start again */
        reply["error"] = "TypeError";  /* as Python would call a wrong argument */
        reply["message"] = e.what();  /* the reason */
    }  /* end of the request */
    return reply.dump();  /* the reply */
}  /* end of run_request */

}  /* end of the request runner */

std::string kes::mail_call(KesMail *m, const std::string &request, double now) {  /* the station's way in: request and reply in one locked step */
    std::lock_guard<std::recursive_mutex> guard(m->lock);  /* one change at a time */
    return run_request(m, request.c_str(), now);  /* the reply */
}  /* end of kes::mail_call */

extern "C" {  /* the mail store's C interface, continued */

KES_API long kes_mail_request(KesMail *m, const char *request, double now) {  /* run one request at time `now` */
    if (m == nullptr || request == nullptr) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    std::lock_guard<std::recursive_mutex> guard(m->lock);  /* one change at a time */
    m->reply = run_request(m, request, now);  /* run, and kept for collection */
    return static_cast<long>(m->reply.size());  /* its length */
}  /* end of kes_mail_request */

KES_API long kes_mail_reply(KesMail *m, char *out, size_t cap) {  /* collect the last reply */
    if (m == nullptr || out == nullptr || cap < m->reply.size()) {  /* no room */
        return -1;  /* refuse */
    }  /* end of the check */
    std::memcpy(out, m->reply.data(), m->reply.size());  /* copied */
    return static_cast<long>(m->reply.size());  /* its length */
}  /* end of kes_mail_reply */

}  /* end of the mail store's C interface */
