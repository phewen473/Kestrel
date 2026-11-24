/*
 * station.cpp - the Kestrel library: one station's link rules.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * The C++ version of link/station.py (with link/adapt.py and the planning
 * rules of modem/plan.py), method for method: beaconing and answering,
 * directed calls, locking, the message exchange with acknowledgments and
 * resends, speed adaptation, reacquiring, moving to a working frequency,
 * broadcasts, the long beacon, listening before transmitting, mail notices
 * and store and forward (through the mail store in mail.cpp).
 *
 * The station never touches audio. It is handed what the receiver decoded
 * (as JSON: the fields of modem/frame.py RxResult) and the time, and it says
 * what to send next as a frame description ({"type": "ack", "link": ...}),
 * with how long that frame lasts; whoever runs it builds the audio (the
 * compiled transmitter does that). Callers talk to it through one C function,
 * kes_station_request, with a JSON request naming the method, as for the mail
 * store. Its log lines are word for word those of the Python station, so the
 * two can be compared line by line.
 */

#define KESTREL_BUILDING 1  /* this file builds the library, so its functions are exported */
#include "kestrel.h"  /* the interface being implemented */
#include "internal.hpp"  /* the mail store's way in */
#include "json.hpp"  /* requests, replies, and the receiver's reports */
#include "rng.hpp"  /* NumPy's random generator, for the reply slot */

#include <algorithm>  /* min, max, find, stable_sort */
#include <charconv>  /* number formatting for the log */
#include <cmath>  /* isfinite, nearbyint, ceil */
#include <cstring>  /* memcpy */
#include <functional>  /* attribute getters and setters */
#include <map>  /* the attribute table */
#include <mutex>  /* one request at a time */
#include <string>  /* text */
#include <utility>  /* pair */
#include <vector>  /* growable arrays */

namespace {  /* helpers seen only inside this file */

using kes::Json;  /* the JSON value */

/* ---- numbers from modem/params.py, modem/levels.py and link/params.py ---- */
const double kFs = 12000.0;  /* audio sample rate (FS) */
const long kSamples[5] = {4800, 1620, 1080, 540, 270};  /* samples per tone, levels 0-4 (LEVELS) */
const double kMinSnr[5] = {-20.0, -16.0, -14.0, -11.0, -8.0};  /* weakest SNR per level, steady (MIN_SNR_DB) */
const double kMinSnrFading[5] = {-8.0, -2.0, -8.0, -1.0, 0.0};  /* and fading (MIN_SNR_FADING_DB) */
const double kFadeLimit = 0.15;  /* fading index above which a signal is fading (FADE_INDEX_LIMIT) */
const int kSizes[4] = {50, 100, 150, 200};  /* size classes in plain characters (SIZE_CLASSES) */
const int kPreambleTones = 12;  /* PREAMBLE_TONES */
const int kHeaderTones = 24;  /* both header copies (HEADER_SYMBOLS) */
const long kLongSamples = 714000;  /* a whole long beacon, in samples (51 tones of 14000; modem/longbeacon.py) */
const int kLongLevel = 7;  /* the long beacon's level number (LONG_LEVEL) */
const int kTypeLink = 0, kTypeAddressed = 1, kTypeBeacon = 2, kTypeAnswer = 3, kTypeAck = 4, kTypeIdent = 5, kTypeNotice = 7;  /* frame types */
const int kControlBits[8] = {0, 0, 75, 124, 48, 61, 0, 192};  /* control frame bodies (CONTROL_BITS) */
const int kAddressBits[2] = {28, 120};  /* address blocks (ADDRESS_BITS) */
const int kAckOk = 0, kAckResend = 1, kAckHaveIt = 2, kAckLink = 3;  /* acknowledgment verdicts (control.py) */
const double kSnrFloor = -30.0;  /* SNR_FLOOR_DB */
const double kAirtimeCap = 60.0;  /* AIRTIME_CAP_S */
const double kAirtimePoorCap = 90.0;  /* AIRTIME_POOR_CAP_S */
const int kMaxParts = 8;  /* MAX_PARTS */
const double kTurnaround = 1.0;  /* TURNAROUND_S */
const double kReplyMargin = 3.0;  /* REPLY_MARGIN_S */
const int kBeaconTries = 5;  /* BEACON_TRIES */
const double kReplySlotGap = 2.4;  /* REPLY_SLOT_GAP_S */
const int kCallupLevel = 2;  /* CALLUP_LEVEL */
const double kExpect = 300.0;  /* EXPECT_S */
const double kHeardForCall = 600.0;  /* HEARD_FOR_CALL_S */
const int kWideSlots = 4;  /* WIDE_SLOTS */
const int kStepUpClean = 2;  /* STEP_UP_CLEAN */
const int kStepUpLevels = 2;  /* STEP_UP_LEVELS */
const size_t kHistory = 4;  /* HISTORY */
const size_t kSnrLookback = 3;  /* SNR_LOOKBACK */
const int kMissLimit = 3;  /* MISS_LIMIT */
const int kMaxResends = 4;  /* MAX_RESENDS */
const int kReacquireTries = 4;  /* REACQUIRE_TRIES */
const int kFinalTries = 2;  /* FINAL_TRIES */
const double kLockTimeout = 300.0;  /* LOCK_TIMEOUT_S */
const double kKeepalive = 120.0;  /* KEEPALIVE_S */
const double kIdentEvery = 540.0;  /* IDENT_EVERY_S */
const int kOfferReply = 0, kOfferTurn = 1, kOfferProbe = 2, kOfferMove = 3, kOfferUnavailable = 4, kOfferNoMail = 5;  /* status-3 part values */
const double kMoveStep = 100.0;  /* MOVE_STEP_HZ */
const double kMoveSettle = 3.0;  /* MOVE_SETTLE_S */
const int kMoveTries = 2;  /* MOVE_TRIES */
const double kMoveWait = 150.0;  /* MOVE_WAIT_S */
const int kCallTries = 5;  /* CALL_TRIES */
const int kBroadcastLevel = 0;  /* BROADCAST_LEVEL */
const int kBroadcastLife = 2;  /* BROADCAST_LIFE_HOURS */
const double kWorkingIdle = 180.0;  /* WORKING_IDLE_S */
const double kWorkingWarn = 60.0;  /* WORKING_WARN_S */
const double kHoldTell = 60.0;  /* HOLD_TELL_S */
const int kHopLimit = 4;  /* HOP_LIMIT */
const double kReach = 7200.0;  /* REACH_S */
const double kNoticeL0Every = 1800.0;  /* NOTICE_L0_EVERY_S */
const double kMailTidy = 60.0;  /* MAIL_TIDY_S */

struct PyError {  /* an error the Python version would raise */
    std::string kind;  /* its name */
    std::string message;  /* its words */
};  /* end of PyError */

long samples_of(long level) {  /* LEVELS[level].samples */
    if (level < 0 || level > 4) {  /* no such level */
        throw PyError{"IndexError", "no such speed level"};  /* as Python's tuple index */
    }  /* end of the check */
    return kSamples[level];  /* the tone length */
}  /* end of samples_of */

double tone_seconds(long level) {  /* LEVELS[level].seconds */
    return static_cast<double>(samples_of(level)) / kFs;  /* samples divided by the sample rate */
}  /* end of tone_seconds */

long body_total(long coded) {  /* frame.py _layout: body tones for `coded` bits, with pilots */
    long ndata = (coded + 4) / 5;  /* data tones */
    long npilot = (ndata + 14) / 15;  /* one pilot per fifteen */
    return ndata + npilot;  /* all body tones */
}  /* end of body_total */

long control_total(int type) {  /* control_layout(type)["total"] */
    long info = kControlBits[type] + 16;  /* fields and check */
    return body_total(2 * (info + 6));  /* the convolutional code, with its tail */
}  /* end of control_total */

long message_total(int size_class) {  /* body_layout(size_class)["total"] */
    long info = kAddressBits[0] + 8 + 7L * kSizes[size_class] + 16;  /* address block, count, text room, check */
    return body_total(2 * info);  /* the LDPC code doubles the bits */
}  /* end of message_total */

double control_seconds(int type, long level) {  /* frame.py control_seconds */
    return static_cast<double>(kPreambleTones + kHeaderTones + control_total(type)) * tone_seconds(level);  /* as Python: tones times tone length */
}  /* end of control_seconds */

double frame_seconds(int size_class, long level) {  /* frame.py frame_seconds */
    return static_cast<double>(kPreambleTones + kHeaderTones + message_total(size_class)) * tone_seconds(level);  /* tones times tone length */
}  /* end of frame_seconds */

double reply_slot(long level) {  /* station.py reply_slot */
    return control_seconds(kTypeAnswer, level) + kReplySlotGap;  /* an answer and a gap */
}  /* end of reply_slot */

int pick_size_class(const std::string &text, int frame_type) {  /* text.py pick_size_class, or ValueError */
    int size_class = 0;  /* the answer */
    int compressed = 0;  /* not needed */
    if (kes_choose_packing(text.data(), text.size(), frame_type, &size_class, &compressed) != 0) {  /* too long, or not 7-bit text */
        throw PyError{"ValueError", "message does not fit one frame"};  /* as Python */
    }  /* end of the check */
    return size_class;  /* the class */
}  /* end of pick_size_class */

bool fits(const std::string &text, int size_class, int frame_type) {  /* text.py fits */
    long compressed = kes_compressed_bits(text.data(), text.size());  /* compressed length */
    if (compressed < 0) {  /* a character outside ASCII */
        throw PyError{"IndexError", "character outside 7-bit ASCII"};  /* as Python's table lookup */
    }  /* end of the check */
    long room = 7L * kSizes[size_class] - (kAddressBits[frame_type] - kAddressBits[0]);  /* capacity_bits */
    return std::min(static_cast<long>(7 * text.size()), compressed) <= room;  /* the smaller form must fit */
}  /* end of fits */

Json plan_at_level(const std::string &text, long level, bool addressed) {  /* modem/plan.py plan_at_level */
    int frame_type = addressed ? kTypeAddressed : kTypeLink;  /* which room applies */
    double whole;  /* airtime sent whole */
    try {  /* it may not fit one frame */
        whole = frame_seconds(pick_size_class(text, frame_type), level);  /* airtime */
    } catch (const PyError &e) {  /* it does not */
        if (e.kind != "ValueError") {  /* only that error means "split it" */
            throw;  /* anything else goes on */
        }  /* end of the test */
        whole = HUGE_VAL;  /* infinite */
    }  /* end of the try */
    Json plan = Json::list();  /* the frames */
    auto item = [&](const std::string &piece, long part, long parts, double seconds) {  /* one frame's entry */
        Json j = Json::object();  /* the dict */
        j["text"] = piece;  /* its text */
        j["level"] = level;  /* level */
        j["part"] = part;  /* part number */
        j["parts"] = parts;  /* parts */
        j["seconds"] = seconds;  /* airtime */
        j["extended"] = seconds > kAirtimeCap;  /* needs the 90-second allowance */
        return j;  /* the entry */
    };  /* end of item */
    if (whole <= kAirtimePoorCap) {  /* fits as one frame */
        plan.push(item(text, 0, 1, whole));  /* one frame */
        return plan;  /* done */
    }  /* end of the whole case */
    int size_class = 0;  /* the largest frame within the limit */
    for (int c = 0; c < 4; ++c) {  /* each class */
        if (frame_seconds(c, level) <= kAirtimePoorCap) {  /* short enough */
            size_class = c;  /* the largest so far */
        }  /* end of the test */
    }  /* end of the classes */
    std::vector<std::string> pieces;  /* the text cut up */
    std::string rest = text;  /* what is left */
    while (!rest.empty()) {  /* until nothing is left */
        size_t take = rest.size();  /* try everything */
        while (!fits(rest.substr(0, take), size_class, frame_type)) {  /* too big */
            --take;  /* one fewer */
        }  /* end of the shrinking */
        pieces.push_back(rest.substr(0, take));  /* the next piece */
        rest = rest.substr(take);  /* the rest */
    }  /* end of the cutting */
    if (static_cast<int>(pieces.size()) > kMaxParts) {  /* too many parts */
        throw PyError{"ValueError", "message needs too many parts"};  /* as Python */
    }  /* end of the check */
    for (size_t p = 0; p < pieces.size(); ++p) {  /* each piece */
        plan.push(item(pieces[p], static_cast<long>(p), static_cast<long>(pieces.size()), frame_seconds(pick_size_class(pieces[p], frame_type), level)));  /* its frame */
    }  /* end of the pieces */
    return plan;  /* all the frames */
}  /* end of plan_at_level */

/* An ordered map with Python dict behavior (a new key at the end, an old one keeps its place). */
template <typename T>
struct Dict {  /* the map */
    std::vector<std::pair<std::string, T>> items;  /* in order */
    T *find(const std::string &k) {  /* the value, or nullptr */
        for (auto &p : items) {  /* each */
            if (p.first == k) {  /* this one */
                return &p.second;  /* found */
            }  /* end of the test */
        }  /* end of the items */
        return nullptr;  /* not there */
    }  /* end of find */
    T &operator[](const std::string &k) {  /* setdefault / assignment */
        T *old = find(k);  /* there already? */
        if (old != nullptr) {  /* yes */
            return *old;  /* in its place */
        }  /* end of the test */
        items.emplace_back(k, T());  /* added at the end */
        return items.back().second;  /* handed back */
    }  /* end of operator[] */
    void erase(const std::string &k) {  /* del d[k] */
        for (auto it = items.begin(); it != items.end(); ++it) {  /* each */
            if (it->first == k) {  /* this one */
                items.erase(it);  /* gone */
                return;  /* done */
            }  /* end of the test */
        }  /* end of the items */
    }  /* end of erase */
};  /* end of Dict */

using Parts = Dict<Json>;  /* part number (as text) -> receiver report */

std::string same_key(const Json &r) {  /* the fields every part of one message must share: (parts, msg_id, link, dest, origin) */
    return r.at("parts").dump() + "|" + r.at("msg_id").dump() + "|" + r.at("link").dump() + "|" + r.at("dest").dump() + "|" + r.at("origin").dump();  /* as one text */
}  /* end of same_key */

Json join_parts(const Parts &parts) {  /* modem/plan.py join_parts: the whole message, or null */
    Dict<const Json *> good;  /* decoded parts, by part number (a later copy replaces an earlier one in its place) */
    for (const auto &p : parts.items) {  /* in the dict's order */
        if (p.second.at("ok").as_bool()) {  /* decoded */
            good[p.second.at("part").dump()] = &p.second;  /* kept */
        }  /* end of the test */
    }  /* end of the parts */
    if (good.items.empty()) {  /* nothing decoded */
        return Json();  /* no message */
    }  /* end of the empty case */
    const Json &first = *good.items.front().second;  /* any one part (the first) */
    long long count = first.at("parts").as_int();  /* how many parts */
    std::string key = same_key(first);  /* what they must share */
    for (const auto &g : good.items) {  /* each */
        if (same_key(*g.second) != key) {  /* from another message */
            return Json();  /* not complete */
        }  /* end of the test */
    }  /* end of the check */
    if (static_cast<long long>(good.items.size()) != count) {  /* missing parts (or extra numbers) */
        return Json();  /* not complete */
    }  /* end of the count check */
    std::string whole;  /* the message */
    for (long long i = 0; i < count; ++i) {  /* in order */
        const Json **piece = good.find(std::to_string(i));  /* part i */
        if (piece == nullptr) {  /* missing */
            return Json();  /* not complete */
        }  /* end of the test */
        whole += (*piece)->at("text").as_text();  /* glued on */
    }  /* end of the parts */
    return Json(whole);  /* the whole message */
}  /* end of join_parts */

/* ---- speed adaptation (link/adapt.py, modem/plan.py pick_level, is_fading) ---- */

bool is_fading(double fade) {  /* plan.py is_fading: a missing reading counts as fading */
    return !(fade <= kFadeLimit);  /* written so not-a-number is fading */
}  /* end of is_fading */

long pick_level(double snr_db, bool fading) {  /* plan.py pick_level with a 2 dB margin */
    const double *limits = fading ? kMinSnrFading : kMinSnr;  /* which table */
    long best = -1;  /* the fastest usable */
    for (long n = 0; n < 5; ++n) {  /* each level */
        if (snr_db >= limits[n] + 2.0) {  /* strong enough */
            best = n;  /* usable (levels are in order, so the last is the fastest) */
        }  /* end of the test */
    }  /* end of the levels */
    return best >= 0 ? best : 0;  /* the slowest when none qualifies */
}  /* end of pick_level */

std::vector<long> common_levels(const std::vector<long> &mine, const std::vector<long> &theirs) {  /* adapt.py common_levels */
    std::vector<long> out;  /* shared levels, sorted */
    for (long n = 0; n < 5; ++n) {  /* the levels this program knows */
        bool shared = std::find(mine.begin(), mine.end(), n) != mine.end() && std::find(theirs.begin(), theirs.end(), n) != theirs.end();  /* both have it */
        if (n == 0 || shared) {  /* the slowest always */
            out.push_back(n);  /* kept */
        }  /* end of the test */
    }  /* end of the levels */
    return out;  /* sorted already */
}  /* end of common_levels */

long cap_level(long level, const std::vector<long> &allowed) {  /* adapt.py cap_level */
    if (allowed.empty()) {  /* min() of nothing */
        throw PyError{"ValueError", "min() arg is an empty sequence"};  /* as Python */
    }  /* end of the check */
    bool any = false;  /* any allowed level low enough? */
    long best = 0;  /* the fastest of them */
    for (long n : allowed) {  /* each */
        if (n <= level && (!any || n > best)) {  /* low enough, and faster */
            best = n;  /* kept */
            any = true;  /* found one */
        }  /* end of the test */
    }  /* end of the levels */
    return any ? best : *std::min_element(allowed.begin(), allowed.end());  /* or the slowest allowed */
}  /* end of cap_level */

using History = std::vector<std::pair<double, double>>;  /* (SNR, fading index), newest last */

long supported_level(const History &history, const std::vector<long> &allowed) {  /* adapt.py supported_level */
    size_t from = history.size() > kSnrLookback ? history.size() - kSnrLookback : 0;  /* the last few */
    double snr = history[from].first;  /* Python's min(): the first, replaced by anything smaller */
    for (size_t i = from + 1; i < history.size(); ++i) {  /* the rest */
        if (history[i].first < snr) {  /* smaller */
            snr = history[i].first;  /* kept */
        }  /* end of the test */
    }  /* end of the readings */
    bool fading = false;  /* any fading frame? */
    for (const auto &h : history) {  /* all of them */
        fading = fading || is_fading(h.second);  /* one is enough */
    }  /* end of the readings */
    return cap_level(pick_level(snr, fading), allowed);  /* the rule, held to shared levels */
}  /* end of supported_level */

long wanted_level(const History &history, long current, long clean_run, bool failed, const std::vector<long> &allowed) {  /* adapt.py wanted_level */
    long target = supported_level(history, allowed);  /* what the measurements say */
    if (failed) {  /* the frame just heard failed */
        return cap_level(std::min(current, target) - 1, allowed);  /* below both */
    }  /* end of the failure case */
    if (target < current) {  /* conditions slipped */
        return target;  /* step down at once */
    }  /* end of the slip */
    if (target > current && clean_run >= kStepUpClean) {  /* better, and staying good */
        std::vector<long> faster;  /* allowed levels between here and the target */
        for (long n : allowed) {  /* each */
            if (current < n && n <= target) {  /* in between */
                faster.push_back(n);  /* kept */
            }  /* end of the test */
        }  /* end of the levels */
        return faster[static_cast<size_t>(std::min(static_cast<long>(kStepUpLevels), static_cast<long>(faster.size())) - 1)];  /* at most two levels up */
    }  /* end of the climb */
    return current;  /* stay */
}  /* end of wanted_level */

/* ---- formatting, as Python's f-strings do it ---- */

std::string fixed(double v, int precision, bool plus = false, size_t width = 0) {  /* format(v, "[+][width].<precision>f") */
    std::string s;  /* the text */
    if (std::isnan(v)) {  /* not a number */
        s = "nan";  /* as Python */
    } else if (std::isinf(v)) {  /* infinite */
        s = v > 0 ? "inf" : "-inf";  /* as Python */
    } else {  /* a number */
        char buf[400];  /* room for any double */
        auto res = std::to_chars(buf, buf + sizeof buf, v, std::chars_format::fixed, precision);  /* correctly rounded, whatever the language settings */
        s.assign(buf, res.ptr);  /* as text */
    }  /* end of the kinds */
    if (plus && s[0] != '-') {  /* a plus sign wanted */
        s = "+" + s;  /* added */
    }  /* end of the sign */
    if (s.size() < width) {  /* narrower than the width */
        s = std::string(width - s.size(), ' ') + s;  /* padded on the left */
    }  /* end of the padding */
    return s;  /* formatted */
}  /* end of fixed */

std::string pyrepr(const std::string &s) {  /* repr() of 7-bit text */
    bool single = s.find('\'') != std::string::npos;  /* holds a single quote */
    bool dbl = s.find('"') != std::string::npos;  /* holds a double quote */
    char quote = (single && !dbl) ? '"' : '\'';  /* Python's choice of quotes */
    std::string out(1, quote);  /* opening quote */
    for (unsigned char c : s) {  /* each character */
        if (c == static_cast<unsigned char>(quote) || c == '\\') {  /* the quote in use, or a backslash */
            out += '\\';  /* escaped */
            out += static_cast<char>(c);  /* the character */
        } else if (c == '\t') { out += "\\t"; }  /* tab */
        else if (c == '\n') { out += "\\n"; }  /* new line */
        else if (c == '\r') { out += "\\r"; }  /* return */
        else if (c < 0x20 || c == 0x7f) {  /* another control character */
            char buf[8];  /* room */
            std::snprintf(buf, sizeof buf, "\\x%02x", c);  /* \xNN */
            out += buf;  /* added */
        } else {  /* printable */
            out += static_cast<char>(c);  /* as it is */
        }  /* end of the choice */
    }  /* end of the characters */
    out += quote;  /* closing quote */
    return out;  /* the repr */
}  /* end of pyrepr */

uint32_t crc32(const std::string &s) {  /* zlib.crc32 */
    uint32_t crc = 0xFFFFFFFFu;  /* preset */
    for (unsigned char c : s) {  /* each byte */
        crc ^= c;  /* mixed in */
        for (int k = 0; k < 8; ++k) {  /* each bit */
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));  /* the reflected polynomial */
        }  /* end of the bits */
    }  /* end of the bytes */
    return crc ^ 0xFFFFFFFFu;  /* inverted */
}  /* end of crc32 */

std::string clean_call(const std::string &call) {  /* address.py clean_call, or ValueError */
    uint8_t bits[48];  /* its bits */
    if (call.find('\0') != std::string::npos || kes_call_to_bits(call.c_str(), bits) != 0) {  /* not an address */
        throw PyError{"ValueError", "not a valid address: " + call};  /* as Python */
    }  /* end of the check */
    char out[10];  /* tidy */
    kes_bits_to_call(bits, out);  /* read back */
    return out;  /* tidy */
}  /* end of clean_call */

long link_id(const std::string &first, const std::string &second) {  /* address.py link_id */
    long id = kes_link_id(first.c_str(), second.c_str());  /* the number */
    if (id < 0) {  /* an address was not valid */
        throw PyError{"ValueError", "not a valid address"};  /* as Python */
    }  /* end of the check */
    return id;  /* the link number */
}  /* end of link_id */

long call_hash(const std::string &call) {  /* address.py call_hash */
    long h = kes_call_hash(call.c_str());  /* the code */
    if (h < 0) {  /* not an address */
        throw PyError{"ValueError", "not a valid address"};  /* as Python */
    }  /* end of the check */
    return h;  /* the code */
}  /* end of call_hash */

bool truthy(const Json &j) {  /* Python's bool() of a JSON value */
    switch (j.kind()) {  /* by kind */
    case Json::Kind::Null: return false;  /* None */
    case Json::Kind::Text: return !j.as_text().empty();  /* non-empty text */
    case Json::Kind::List: return !j.items().empty();  /* non-empty list */
    case Json::Kind::Object: return !j.members().empty();  /* non-empty dict */
    default: return j.as_real() != 0.0;  /* a number or a truth value */
    }  /* end of the kinds */
}  /* end of truthy */

bool is(const Json &j, const char *text) {  /* j == "text" */
    return j.is_text() && j.as_text() == text;  /* the same text */
}  /* end of is */

double real(const Json &r, const char *name) {  /* a number field of a report */
    const Json *j = r.find(name);  /* the field */
    return (j != nullptr && j->is_number()) ? j->as_real() : std::nan("");  /* or not-a-number */
}  /* end of real */

long whole(const Json &r, const char *name) {  /* a whole-number field of a report */
    return static_cast<long>(r.at(name).as_int());  /* as a number */
}  /* end of whole */

std::string text(const Json &r, const char *name) {  /* a text field of a report (empty when absent or null) */
    const Json *j = r.find(name);  /* the field */
    return (j != nullptr && j->is_text()) ? j->as_text() : std::string();  /* the text */
}  /* end of text */

const Json &field(const Json &r, const char *name) {  /* result.fields[name] */
    return r.at("fields").at(name);  /* the field */
}  /* end of field */

std::vector<long> longs(const Json &j) {  /* a list of whole numbers */
    std::vector<long> v;  /* the list */
    for (const auto &x : j.items()) {  /* each */
        v.push_back(static_cast<long>(x.as_int()));  /* kept */
    }  /* end of the items */
    return v;  /* the list */
}  /* end of longs */

Json long_list(const std::vector<long> &v) {  /* a list of whole numbers as JSON */
    Json l = Json::list();  /* empty */
    for (long n : v) {  /* each */
        l.push(Json(n));  /* added */
    }  /* end of the items */
    return l;  /* the list */
}  /* end of long_list */

Json text_list(const std::vector<std::string> &v) {  /* a list of text as JSON */
    Json l = Json::list();  /* empty */
    for (const auto &s : v) {  /* each */
        l.push(Json(s));  /* added */
    }  /* end of the items */
    return l;  /* the list */
}  /* end of text_list */

bool contains(const std::vector<long> &v, long n) {  /* n in v */
    return std::find(v.begin(), v.end(), n) != v.end();  /* found? */
}  /* end of contains */

bool contains(const std::vector<std::string> &v, const std::string &s) {  /* s in v */
    return std::find(v.begin(), v.end(), s) != v.end();  /* found? */
}  /* end of contains */

Json report(double snr, double fade, double offset, long want) {  /* a ChannelReport */
    Json j = Json::object();  /* the four readings */
    j["snr_db"] = snr;  /* SNR */
    j["fade_index"] = fade;  /* fading */
    j["offset_hz"] = offset;  /* offset */
    j["want_level"] = want;  /* level asked for */
    return j;  /* the report */
}  /* end of report */

}  /* end of the private helpers */

/* One station (link/station.py Station). */
struct KesStation {  /* its state and rules */
    std::recursive_mutex lock;  /* one request at a time */
    KesBusy busy_fn = nullptr;  /* the listen-before-transmit check, or none */
    void *busy_ctx = nullptr;  /* handed back to it */
    KesMail *mail = nullptr;  /* the mail store (owned by the caller) */
    double mail_now = 0.0;  /* the mail store's clock at this request */
    Json mail_now_json;  /* the same, as the clock gave it */
    bool clear_stored = false;  /* the receiver's kept soft bits must be dropped (station.stored = None) */

    std::string call;  /* this station's callsign */
    kes::NumpyRandom rng{0};  /* its own random numbers */
    bool wide = false;  /* asking for a wide reply window */
    Json candidates = Json::list();  /* answers collected in a wide window */
    std::vector<std::string> worked;  /* stations already worked (a set, in order) */
    std::string grid;  /* grid locator */
    std::vector<long> levels;  /* levels it can use */
    bool close_when_done = true;  /* close once both are done */
    bool keep_open = false;  /* the operator's standing choice */
    std::string state = "IDLE";  /* lock state */
    Json role;  /* "beaconer", "answerer", "caller" or None */
    std::string partner;  /* the other station */
    long link = -1;  /* the pair's link number */
    std::vector<long> allowed{0};  /* levels both can use */
    long tx_level = 0;  /* level to send at */
    long want = 0;  /* level asked for */
    History history;  /* recent measurements of the partner */
    long clean_run = 0;  /* clean frames since the last change of level */
    long good_run = 0;  /* clean frames since the last failure */
    Json last_result;  /* the last frame heard from the partner */
    std::vector<std::string> outbox;  /* messages waiting */
    Json outbox_to = Json::list();  /* who each is for (None for anyone) */
    Json outbox_ids = Json::list();  /* each one's message number, or None */
    Json broadcasts = Json::list();  /* broadcast frames waiting: [frame, level, note] */
    Json long_waiting;  /* a long beacon waiting (its frame), or None */
    Json held_since;  /* when holding began, or None */
    double held_told = -1e9;  /* when the operator was last told */
    Json bulletins = Json::list();  /* addressed messages received: [origin, dest, text] */
    Dict<Parts> bulletin_parts;  /* their parts still arriving */
    std::vector<std::string> bulletin_done;  /* their keys, once delivered */
    std::string target;  /* the station being called */
    long calls = 0;  /* calls sent without a reply */
    bool leads = false;  /* keeps the turn in a clash */
    std::vector<std::string> delivered;  /* messages acknowledged in full */
    std::vector<std::string> inbox;  /* messages received */
    Json plan = Json::list();  /* the frames of the message being sent */
    std::string plan_text;  /* its whole text */
    long part_index = 0;  /* the next frame */
    long current_id = 0;  /* its message number */
    Json pending;  /* the reply being waited for, or None */
    double deadline = 0.0;  /* when to stop waiting */
    long misses = 0;  /* unanswered transmissions */
    long resends = 0;  /* resends of the current frame */
    long probes = 0;  /* unanswered probes */
    long finals = 0;  /* unanswered closing identifications */
    long beacons = 0;  /* unanswered beacons */
    bool my_turn = false;  /* may start a transmission */
    bool peer_empty = false;  /* the partner has nothing to send */
    bool sent_final = false;  /* this station has said goodbye */
    Dict<Parts> partial;  /* message parts so far, by message number */
    std::vector<long> done_ids;  /* messages received in full */
    double last_ident = -1e9;  /* when the callsign last went out */
    double last_activity = 0.0;  /* when a frame last went either way */
    std::vector<std::string> log;  /* the log */
    double reply_margin = kReplyMargin;  /* extra wait for a reply */
    bool quiet = false;  /* idle lock, partner holds the turn */
    bool idle_told = false;  /* the partner knows the lock is idle */
    bool can_move = false;  /* the radio can be retuned */
    Json move_to_hz;  /* the working frequency to propose, or None */
    Json offset_hz = Json(0);  /* where the radio should be now */
    Json tune_at;  /* when a decided retune takes effect, or None */
    Json tune_next = Json(0);  /* where it goes */
    bool moved = false;  /* a move has been dealt with in this contact */
    long move_tries = 0;  /* proposals without a reply */
    Json settle_until;  /* after an agreed move: when to probe, or None */
    bool arriving = false;  /* the first probe on the working frequency is out */
    Json await_since;  /* waiting for the partner on the working frequency since, or None */
    bool proposed_move = false;  /* this station asked for the move */
    double last_traffic = 0.0;  /* when a message frame last went */
    bool idle_warned = false;  /* the idle warning has been given */
    bool single = false;  /* one round only, then listen again */
    bool answer_beacons = true;  /* answers beacons by itself */
    bool available = true;  /* the operator is available */
    bool answer_calls = true;  /* answers directed calls by itself */
    double last_beacon_t = -1e9;  /* when it last beaconed */
    Dict<double> called_t;  /* when it last called each station */
    std::string unavailable_from;  /* the last station that said "not available" */
    long callup = kCallupLevel;  /* the level of the next call-up */
    long beacon_sent_at = 0;  /* the level of the beacon now waiting */
    Dict<std::pair<double, Json>> heard_at;  /* callsign -> (time, report) */
    bool carries = true;  /* holds mail for others */
    Json job;  /* the mail being sent, or None */
    std::vector<std::string> refused;  /* partners that do not carry mail */
    Dict<Parts> mail_parts;  /* parts of addressed mail arriving in a lock */
    std::vector<std::string> expired;  /* own messages that expired */
    Dict<std::pair<double, Json>> notices;  /* callsign -> (time, fields) */
    bool notice_sent = false;  /* a notice just went; the beacon is next */
    double last_notice_l0 = -1e9;  /* when a notice last went with an L0 beacon */
    double tidied = -1e9;  /* when expired mail was last looked for */
    std::string reply;  /* the last reply, until collected */

    bool locked() const { return state == "LOCKED" || state == "DEGRADED" || state == "REACQUIRE"; }  /* LOCKED_STATES */

    void setup(const std::string &call_in, const std::string &grid_in, const Json &levels_in, bool close) {  /* Station.__init__ */
        call = clean_call(call_in);  /* the callsign */
        rng = kes::NumpyRandom(crc32(call));  /* its random numbers */
        grid = grid_in;  /* locator */
        levels.clear();  /* the levels */
        if (levels_in.is_null()) {  /* every level */
            for (long n = 0; n < 5; ++n) {  /* 0 to 4 */
                levels.push_back(n);  /* kept */
            }  /* end of the levels */
        } else {  /* the given ones */
            levels = longs(levels_in);  /* kept */
        }  /* end of the choice */
        close_when_done = close;  /* close when done */
        keep_open = !close;  /* the standing choice */
        callup = contains(levels, kCallupLevel) ? kCallupLevel : 0;  /* the middle level first, if it has it */
    }  /* end of setup */

    /* ---- the mail store ---- */

    Json mail_ask(const char *op, Json args) {  /* one Mailroom method */
        if (mail == nullptr) {  /* no store */
            throw PyError{"AttributeError", "the station has no mail store"};  /* refuse */
        }  /* end of the check */
        Json req = Json::object();  /* the request */
        req["op"] = op;  /* the method */
        req["args"] = std::move(args);  /* its arguments */
        req["now"] = mail_now_json;  /* the mail clock */
        Json rep = Json::parse(kes::mail_call(mail, req.dump(), mail_now));  /* asked and answered in one locked step */
        if (const Json *err = rep.find("error")) {  /* the method raised */
            throw PyError{err->as_text(), text(rep, "message")};  /* passed on */
        }  /* end of the error */
        return rep.at("ok");  /* the answer */
    }  /* end of mail_ask */

    template <typename... A>
    Json mail_call(const char *op, A... args) {  /* a Mailroom method with these arguments */
        Json l = Json::list();  /* the arguments */
        (l.push(Json(args)), ...);  /* each one */
        return mail_ask(op, l);  /* asked */
    }  /* end of mail_call */

    /* ---- starting up ---- */

    void beacon() {  /* become the station that calls */
        role = "beaconer";  /* sends beacons */
        leads = true;  /* keeps the turn */
    }  /* end of beacon */

    void listen() {  /* become the station that answers */
        role = "answerer";  /* answers beacons */
    }  /* end of listen */

    void call_station(const std::string &who) {  /* call one station by name */
        if (clean_call(who) == call) {  /* itself */
            throw PyError{"ValueError", call + " is this station's own callsign; call the other station's"};  /* refused */
        }  /* end of the check */
        role = "caller";  /* sends directed calls */
        target = clean_call(who);  /* to this station */
        leads = false;  /* the called station keeps the turn */
    }  /* end of call_station */

    void beacon_once() {  /* one beacon round, then listen */
        beacon();  /* calling for now */
        beacons = kBeaconTries - 1;  /* one beacon only */
        single = true;  /* then listen again */
    }  /* end of beacon_once */

    void call_once(const std::string &who) {  /* one call, then listen */
        call_station(who);  /* calling for now */
        single = true;  /* then listen again */
    }  /* end of call_once */

    bool bag_held() {  /* bool(self.mail.bag) */
        return mail_call("bag_count").as_int() > 0;  /* anything held? */
    }  /* end of bag_held */

    void long_beacon(const Json &holds_mail) {  /* queue one long beacon */
        Json f = Json::object();  /* its description */
        f["type"] = "long";  /* a long beacon */
        f["call"] = call;  /* callsign */
        f["grid"] = grid;  /* locator */
        f["available"] = available;  /* taking contacts? */
        f["holds_mail"] = holds_mail.is_null() ? bag_held() : truthy(holds_mail);  /* holding mail for others? */
        long_waiting = f;  /* ready */
    }  /* end of long_beacon */

    void queue(const std::string &msg, const Json &to) {  /* hand the station a message */
        outbox.push_back(msg);  /* oldest first */
        outbox_to.push(truthy(to) ? Json(clean_call(to.as_text())) : Json());  /* who it is for */
        if (truthy(to)) {  /* a named station: its number now */
            Json taken = Json::list();  /* numbers already queued */
            std::vector<long long> seen;  /* (a set: each once) */
            for (const auto &n : outbox_ids.items()) {  /* each queued number */
                if (!n.is_null() && std::find(seen.begin(), seen.end(), n.as_int()) == seen.end()) {  /* a number, not seen yet */
                    seen.push_back(n.as_int());  /* noted */
                }  /* end of the test */
            }  /* end of the numbers */
            std::sort(seen.begin(), seen.end());  /* in order */
            for (long long n : seen) {  /* each */
                taken.push(Json(n));  /* listed */
            }  /* end of the numbers */
            outbox_ids.push(mail_call("own_add", msg, to.as_text(), taken));  /* its number */
        } else {  /* for whoever the partner is */
            outbox_ids.push(Json());  /* no number yet */
        }  /* end of the choice */
    }  /* end of queue */

    void broadcast(const std::string &msg, long level) {  /* queue a broadcast to ALL */
        Json number = mail_call("new_number");  /* the next message number */
        Json plan_items = plan_at_level(msg, level, true);  /* cut into frames */
        for (const auto &item : plan_items.items()) {  /* each frame */
            Json f = Json::object();  /* a fully addressed frame for everyone */
            f["type"] = "addressed";  /* its kind */
            f["text"] = item.at("text");  /* text */
            f["level"] = level;  /* level */
            f["part"] = item.at("part");  /* part */
            f["parts"] = item.at("parts");  /* parts */
            f["msg_id"] = number;  /* number */
            f["dest"] = "ALL";  /* everyone */
            f["origin"] = call;  /* from here */
            f["hops"] = 0;  /* no relays */
            f["life_hours"] = kBroadcastLife;  /* the shortest lifetime */
            Json entry = Json::list();  /* [frame, level, note] */
            entry.push(f);  /* the frame */
            entry.push(Json(level));  /* its level */
            entry.push(Json("to ALL, msg " + number.dump() + " part " + std::to_string(item.at("part").as_int() + 1) + "/" + item.at("parts").dump()));  /* the note */
            broadcasts.push(entry);  /* waiting */
        }  /* end of the frames */
    }  /* end of broadcast */

    bool unqueue(const std::string &msg, const Json &to) {  /* take back a waiting message */
        Json wanted = truthy(to) ? Json(clean_call(to.as_text())) : Json();  /* the address as kept */
        for (long index = static_cast<long>(outbox.size()) - 1; index >= 0; --index) {  /* newest first */
            const Json &kept_to = outbox_to.items()[static_cast<size_t>(index)];  /* its address */
            bool same_to = kept_to.is_null() ? wanted.is_null() : (wanted.is_text() && kept_to.as_text() == wanted.as_text());  /* the same address */
            if (outbox[static_cast<size_t>(index)] == msg && same_to && !(index == 0 && truthy(plan))) {  /* the same message, not under way */
                Json number = outbox_ids.items()[static_cast<size_t>(index)];  /* its number */
                outbox.erase(outbox.begin() + index);  /* removed */
                outbox_to.items().erase(outbox_to.items().begin() + index);  /* with its address */
                outbox_ids.items().erase(outbox_ids.items().begin() + index);  /* and number */
                if (!number.is_null()) {  /* a message to a named station */
                    mail_call("own_drop", number);  /* no longer waiting */
                }  /* end of the drop */
                return true;  /* removed */
            }  /* end of the test */
        }  /* end of the outbox */
        return false;  /* nothing matched */
    }  /* end of unqueue */

    long sendable() {  /* the first message for this partner (or anyone), or -1 */
        for (size_t i = 0; i < outbox_to.items().size(); ++i) {  /* oldest first */
            const Json &to = outbox_to.items()[i];  /* its address */
            if (to.is_null() || to.as_text() == partner) {  /* for anyone, or for the partner */
                return static_cast<long>(i);  /* this one */
            }  /* end of the test */
        }  /* end of the outbox */
        return -1;  /* nothing */
    }  /* end of sendable */

    bool has_for(const std::string &who) {  /* traffic for a callsign? */
        for (const auto &to : outbox_to.items()) {  /* each address */
            if (to.is_null() || to.as_text() == who) {  /* for anyone, or for that station */
                return true;  /* yes */
            }  /* end of the test */
        }  /* end of the outbox */
        return truthy(mail_call("held_for", who));  /* or mail held for it */
    }  /* end of has_for */

    Json make_job(const char *kind, const Json &item, long hops) {  /* a mail job from a held or own message */
        Json j = Json::object();  /* the job */
        j["kind"] = kind;  /* deliver, hand or pass */
        j["dest"] = item.at("dest");  /* for whom */
        j["origin"] = item.at("origin");  /* from whom */
        j["id"] = item.at("id");  /* number */
        j["text"] = item.at("text");  /* text */
        j["hops"] = hops;  /* hops it will carry */
        j["life"] = mail_call("life_hours", item.at("expires"));  /* lifetime */
        return j;  /* the job */
    }  /* end of make_job */

    Json mail_job() {  /* the next mail job for the partner, or None */
        if (partner.empty() || !locked()) {  /* no contact */
            return Json();  /* nothing */
        }  /* end of the check */
        Json held = mail_call("held_for", partner);  /* mail held for the partner */
        if (!held.items().empty()) {  /* there is some */
            const Json &item = held.items().front();  /* the first */
            return make_job("deliver", item, static_cast<long>(item.at("hops").as_int()) + 1);  /* deliver it */
        }  /* end of the delivery */
        if (contains(refused, partner)) {  /* the partner does not carry mail */
            return Json();  /* nothing more */
        }  /* end of the check */
        for (size_t i = 0; i < outbox.size(); ++i) {  /* own messages, oldest first */
            const Json &to = outbox_to.items()[i];  /* address */
            const Json &number = outbox_ids.items()[i];  /* number */
            if (truthy(to) && to.as_text() != partner && !number.is_null() && truthy(mail_call("can_hand", number, partner))) {  /* for another station, may be handed over */
                Json own = mail_call("own_item", number);  /* the stored message */
                Json item = Json::object();  /* as a job source */
                item["dest"] = to;  /* for whom */
                item["origin"] = call;  /* from here */
                item["id"] = number;  /* number */
                item["text"] = outbox[i];  /* text */
                item["expires"] = own.at("expires");  /* expiry */
                return make_job("hand", item, 0);  /* hand a copy over */
            }  /* end of the test */
        }  /* end of the outbox */
        Json item = mail_call("to_pass", partner);  /* held mail the partner hears the destination of */
        if (!item.is_null()) {  /* there is some */
            return make_job("pass", item, static_cast<long>(item.at("hops").as_int()) + 1);  /* pass a copy on */
        }  /* end of the pass */
        return Json();  /* nothing */
    }  /* end of mail_job */

    bool has_traffic() {  /* anything to send in this contact? */
        return sendable() >= 0 || !mail_job().is_null();  /* own message or mail */
    }  /* end of has_traffic */

    std::vector<std::string> heard_calls(double now) {  /* stations heard lately, most recent first */
        std::vector<std::pair<std::string, double>> order;  /* (call, time) */
        for (const auto &p : heard_at.items) {  /* in the dict's order */
            order.emplace_back(p.first, p.second.first);  /* kept */
        }  /* end of the items */
        std::stable_sort(order.begin(), order.end(), [](const auto &a, const auto &b) { return -a.second < -b.second; });  /* newest first, ties in order */
        std::vector<std::string> out;  /* the calls */
        for (const auto &p : order) {  /* each */
            if (now - p.second <= kReach) {  /* recent */
                out.push_back(p.first);  /* kept */
            }  /* end of the test */
        }  /* end of the calls */
        return out;  /* the list */
    }  /* end of heard_calls */

    bool mail_waiting_at(const std::string &who) {  /* does `who` hold mail for this station? */
        return truthy(mail_call("holds_for_me", who));  /* as the store remembers */
    }  /* end of mail_waiting_at */

    Json tuning(double now) {  /* where the radio should be */
        if (!tune_at.is_null() && now >= tune_at.as_real()) {  /* a retune is due */
            offset_hz = tune_next;  /* it takes effect */
            tune_at = Json();  /* done */
        }  /* end of the retune */
        return offset_hz;  /* in force */
    }  /* end of tuning */

    void retune(double when, const Json &offset) {  /* decide a retune */
        tune_at = Json(when);  /* when */
        tune_next = offset;  /* where */
    }  /* end of retune */

    /* ---- small helpers ---- */

    void say(double now, const std::string &what) {  /* a log line */
        log.push_back(fixed(now, 1, false, 7) + "s " + call + ": " + what);  /* time, who, what */
    }  /* end of say */

    Json report_of(const Json &r) {  /* a report on one frame outside a contact */
        double snr = real(r, "snr_db");  /* its SNR */
        bool ok = std::isfinite(snr);  /* measured? */
        long level = ok ? supported_level(History{{snr, real(r, "fade_index")}}, levels) : 0;  /* the level it supports */
        return report(ok ? snr : kSnrFloor, real(r, "fade_index"), real(r, "offset_hz"), level);  /* the report */
    }  /* end of report_of */

    Json my_report() {  /* the report to send back */
        bool have = !last_result.is_null();  /* a frame heard? */
        double snr = have ? real(last_result, "snr_db") : std::nan("");  /* its SNR */
        return report(have && std::isfinite(snr) ? snr : -30.0, have ? real(last_result, "fade_index") : std::nan(""), have ? real(last_result, "offset_hz") : 0.0, want);  /* readings and the level wanted */
    }  /* end of my_report */

    void note(const Json &r, bool failed) {  /* take in a frame's measurements */
        last_result = r;  /* for the next report */
        double snr = real(r, "snr_db");  /* SNR */
        if (std::isfinite(snr)) {  /* usable */
            history.emplace_back(snr, real(r, "fade_index"));  /* added */
            if (history.size() > kHistory) {  /* too many */
                history.erase(history.begin(), history.end() - static_cast<long>(kHistory));  /* only the recent ones */
            }  /* end of the trim */
        }  /* end of the reading */
        clean_run = failed ? 0 : clean_run + 1;  /* clean frames since the last change */
        good_run = failed ? 0 : good_run + 1;  /* since the last failure */
        if (!history.empty()) {  /* with a measurement */
            long fresh = wanted_level(history, want, clean_run, failed, allowed);  /* the level to ask for */
            if (fresh != want) {  /* changed */
                clean_run = 0;  /* a new run */
                want = fresh;  /* asked for */
            }  /* end of the change */
        }  /* end of the decision */
        if (failed && state == "LOCKED") {  /* a failure degrades */
            state = "DEGRADED";  /* but keeps the lock */
        } else if (!failed && state == "DEGRADED" && good_run >= kStepUpClean) {  /* clean again */
            state = "LOCKED";  /* healthy */
        }  /* end of the state */
    }  /* end of note */

    void fresh_start(const Json &r) {  /* measurements from one new frame */
        double snr = real(r, "snr_db");  /* SNR */
        history.clear();  /* older readings forgotten */
        if (std::isfinite(snr)) {  /* usable */
            history.emplace_back(snr, real(r, "fade_index"));  /* this one */
        }  /* end of the reading */
        last_result = r;  /* for the next report */
        clean_run = good_run = 0;  /* new runs */
        want = !history.empty() ? supported_level(history, allowed) : *std::min_element(allowed.begin(), allowed.end());  /* what it supports */
    }  /* end of fresh_start */

    long frame_samples(const Json &f) {  /* how many samples a frame description's audio has */
        const std::string &type = f.at("type").as_text();  /* its kind */
        if (type == "long") {  /* a long beacon */
            return kLongSamples;  /* fixed */
        }  /* end of the long beacon */
        long level = static_cast<long>(f.at("level").as_int());  /* its level */
        if (type == "message" || type == "addressed") {  /* a message frame */
            int size_class = pick_size_class(f.at("text").as_text(), type == "message" ? kTypeLink : kTypeAddressed);  /* its size */
            return (kPreambleTones + kHeaderTones + message_total(size_class)) * samples_of(level);  /* preamble, headers, body */
        }  /* end of a message */
        int ftype = type == "ack" ? kTypeAck : type == "ident" ? kTypeIdent : type == "answer" ? kTypeAnswer : type == "beacon" ? kTypeBeacon : kTypeNotice;  /* the control frame type */
        return (kPreambleTones + kHeaderTones + control_total(ftype)) * samples_of(level);  /* preamble, headers, body */
    }  /* end of frame_samples */

    Json send(double now, const Json &frame, const char *kind, long level, const Json &expects, double reply_s, const std::string &note_text) {  /* prepare one transmission */
        double seconds = static_cast<double>(frame_samples(frame)) / kFs;  /* its length, as len(audio) / FS */
        Json tx = Json::object();  /* the Transmission */
        tx["frame"] = frame;  /* what to build */
        tx["kind"] = kind;  /* what it is */
        tx["level"] = level;  /* its level */
        tx["note"] = note_text;  /* detail */
        tx["delay"] = 0.0;  /* sent at once */
        tx["seconds"] = seconds;  /* its length */
        pending = expects;  /* the reply to wait for */
        deadline = now + seconds + kTurnaround + reply_s + reply_margin;  /* how long to wait */
        last_activity = now + seconds;  /* active until it ends */
        return tx;  /* for whoever runs the radio */
    }  /* end of send */

    Json ack(double now, long msg_id, long part, long status, const char *kind, const Json &expects = Json(), double reply_s = 0.0) {  /* an acknowledgment */
        Json f = Json::object();  /* its description */
        f["type"] = "ack";  /* an acknowledgment */
        f["link"] = link;  /* link */
        f["msg_id"] = msg_id;  /* message number */
        f["part"] = part;  /* part */
        f["status"] = status;  /* verdict */
        f["report"] = my_report();  /* report */
        f["level"] = tx_level;  /* at the level asked for */
        return send(now, f, kind, tx_level, expects, reply_s, "wants L" + std::to_string(want));  /* sent */
    }  /* end of ack */

    Json ident(double now, bool final) {  /* an identification */
        last_ident = now;  /* the callsign goes out */
        sent_final = sent_final || final;  /* a goodbye remembered */
        Json f = Json::object();  /* its description */
        f["type"] = "ident";  /* an identification */
        f["call"] = call;  /* callsign */
        f["link"] = link;  /* link */
        f["final"] = final;  /* goodbye? */
        f["level"] = tx_level;  /* level */
        if (final) {  /* the closing one */
            return send(now, f, "final", tx_level, Json("final"), control_seconds(kTypeIdent, want), "");  /* wait for the partner's */
        }  /* end of the goodbye */
        return send(now, f, "ident", tx_level, Json(), 0.0, "");  /* no reply needed */
    }  /* end of ident */

    double longest_reply() {  /* the longest reply to a turn offer */
        double message = std::min(frame_seconds(3, want), kAirtimePoorCap);  /* the largest message frame, within the limit */
        return std::max(message, control_seconds(kTypeAck, want));  /* or an acknowledgment */
    }  /* end of longest_reply */

    /* ---- sending messages ---- */

    void start_message(const std::string &msg, const Json &number, const Json &the_job) {  /* plan a message */
        job = the_job;  /* mail, or None */
        plan = plan_at_level(msg, tx_level, !the_job.is_null());  /* cut into frames */
        plan_text = msg;  /* the whole text */
        part_index = 0;  /* first frame */
        current_id = static_cast<long>(!number.is_null() ? number.as_int() : mail_call("new_number").as_int());  /* its number */
        resends = 0;  /* clean slate */
    }  /* end of start_message */

    Json send_part(double now) {  /* send the next frame */
        Json item = plan.items()[static_cast<size_t>(part_index)];  /* the frame due */
        if (frame_seconds(pick_size_class(item.at("text").as_text(), kTypeLink), tx_level) > kAirtimePoorCap) {  /* now too long at this level */
            say(now, "level fell to L" + std::to_string(tx_level) + "; splitting the message again");  /* explain */
            plan = plan_at_level(plan_text, tx_level, !job.is_null());  /* planned again */
            part_index = 0;  /* from the start */
            item = plan.items()[0];  /* the frame due now */
        }  /* end of the replan */
        Json f = Json::object();  /* the frame */
        std::string note_text;  /* its note */
        f["text"] = item.at("text");  /* text */
        f["level"] = tx_level;  /* level */
        f["part"] = item.at("part");  /* part */
        f["parts"] = item.at("parts");  /* parts */
        std::string which = "part " + std::to_string(item.at("part").as_int() + 1) + "/" + item.at("parts").dump();  /* "part 1/2" */
        if (job.is_null()) {  /* this station's own message */
            f["type"] = "message";  /* a link frame */
            f["link"] = link;  /* link */
            f["msg_id"] = current_id;  /* number */
            f["want_level"] = want;  /* the level wanted back */
            note_text = "msg " + std::to_string(current_id) + " " + which;  /* which frame */
        } else {  /* mail: a fully addressed frame */
            f["type"] = "addressed";  /* addressed */
            f["msg_id"] = job.at("id");  /* number */
            f["dest"] = job.at("dest");  /* destination */
            f["origin"] = job.at("origin");  /* origin */
            f["hops"] = job.at("hops");  /* hops */
            f["life_hours"] = job.at("life");  /* lifetime */
            note_text = job.at("kind").as_text() + " mail " + job.at("origin").as_text() + "#" + job.at("id").dump() + " for " + job.at("dest").as_text() + ", " + which;  /* which frame */
        }  /* end of the two kinds */
        idle_told = false;  /* traffic is moving */
        last_traffic = now;  /* the idle clock restarts */
        idle_warned = false;  /* no warning due */
        return send(now, f, "message", tx_level, Json("ack"), control_seconds(kTypeAck, want), note_text);  /* wait for its acknowledgment */
    }  /* end of send_part */

    Json next(double now) {  /* what to send when it is this station's turn */
        if (now - last_ident >= kIdentEvery) {  /* time to identify */
            return ident(now, false);  /* first */
        }  /* end of the identification */
        if (truthy(move_to_hz) && can_move && !moved) {  /* a working frequency is wanted */
            return propose_move(now);  /* ask first */
        }  /* end of the move */
        if (truthy(plan) && part_index < static_cast<long>(plan.items().size())) {  /* a message under way */
            return send_part(now);  /* its next frame */
        }  /* end of the message */
        long index = sendable();  /* the next message for this partner */
        if (index >= 0) {  /* there is one */
            std::string m = outbox[static_cast<size_t>(index)];  /* to the front... */
            outbox.erase(outbox.begin() + index);  /* ... */
            outbox.insert(outbox.begin(), m);  /* ... */
            Json t = outbox_to.items()[static_cast<size_t>(index)];  /* ...with its address... */
            outbox_to.items().erase(outbox_to.items().begin() + index);  /* ... */
            outbox_to.items().insert(outbox_to.items().begin(), t);  /* ... */
            Json n = outbox_ids.items()[static_cast<size_t>(index)];  /* ...and number */
            outbox_ids.items().erase(outbox_ids.items().begin() + index);  /* ... */
            outbox_ids.items().insert(outbox_ids.items().begin(), n);  /* ... */
            start_message(outbox[0], outbox_ids.items()[0], Json());  /* planned */
            return send_part(now);  /* its first frame */
        }  /* end of the own message */
        Json the_job = mail_job();  /* mail to send */
        if (!the_job.is_null()) {  /* there is some */
            const std::string &kind = the_job.at("kind").as_text();  /* which */
            if (kind == "deliver") { say(now, "delivering mail from " + the_job.at("origin").as_text() + " held here for " + partner); }  /* explain */
            else if (kind == "hand") { say(now, "handing " + partner + " a message for " + the_job.at("dest").as_text() + " to carry"); }  /* explain */
            else { say(now, "passing " + partner + " mail for " + the_job.at("dest").as_text() + ", which it hears"); }  /* explain */
            start_message(the_job.at("text").as_text(), the_job.at("id"), the_job);  /* planned */
            return send_part(now);  /* its first frame */
        }  /* end of the mail */
        if (!peer_empty) {  /* the partner has not said it is empty */
            idle_told = true;  /* this offer says this station is idle */
            return ack(now, 0, kOfferTurn, kAckLink, "offer", Json("offer"), longest_reply());  /* offer the turn */
        }  /* end of the offer */
        if (close_when_done) {  /* both finished */
            return ident(now, true);  /* close */
        }  /* end of the close */
        if (!idle_told) {  /* kept open, partner not told */
            idle_told = true;  /* tell it once */
            return ack(now, 0, kOfferTurn, kAckLink, "offer", Json("offer"), longest_reply());  /* an offer of the turn */
        }  /* end of the idle offer */
        return Json();  /* quiet */
    }  /* end of next */

    Json propose_move(double now) {  /* ask the partner to move */
        ++move_tries;  /* counted */
        long steps = static_cast<long>(static_cast<long long>(std::nearbyint(move_to_hz.as_real() / kMoveStep)) & 0xFFFF);  /* signed 16-bit count of 100 Hz steps */
        proposed_move = true;  /* this station asked */
        if (move_tries == 1) {  /* the first time */
            say(now, "proposing a move to the working frequency (" + fixed(move_to_hz.as_real() / 1000.0, 1, true) + " kHz)");  /* explain */
        }  /* end of the note */
        return ack(now, steps, kOfferMove, kAckLink, "move", Json("move"), control_seconds(kTypeAck, want));  /* the proposal */
    }  /* end of propose_move */

    Json reacquire(double now) {  /* find the partner again */
        if (state != "REACQUIRE") {  /* entering */
            state = "REACQUIRE";  /* noted */
            probes = 0;  /* none yet */
            say(now, "no reply; reacquiring at the slowest level");  /* explain */
        }  /* end of the entry */
        tx_level = *std::min_element(allowed.begin(), allowed.end());  /* slowest */
        want = tx_level;  /* and ask for it */
        return ack(now, 0, kOfferProbe, kAckLink, "probe", Json("probe"), control_seconds(kTypeAck, want));  /* "are you still there?" */
    }  /* end of reacquire */

    void new_contact() {  /* ready for another contact */
        state = "IDLE";  /* no partner */
        pending = Json();  /* nothing awaited */
        partner.clear();  /* nobody */
        link = -1;  /* no link */
        job = Json();  /* no mail */
        mail_parts = Dict<Parts>();  /* nothing half-received */
        notice_sent = false;  /* no notice just sent */
        history.clear();  /* no measurements */
        last_result = Json();  /* none */
        clean_run = good_run = 0;  /* no runs */
        plan = Json::list();  /* nothing under way */
        part_index = misses = resends = probes = finals = beacons = 0;  /* no counts */
        my_turn = peer_empty = sent_final = false;  /* no turn, no goodbyes */
        partial = Dict<Parts>();  /* nothing half-received */
        done_ids.clear();  /* none */
        clear_stored = true;  /* the receiver's kept soft bits go */
        candidates = Json::list();  /* none */
        quiet = moved = false;  /* no idle lock, no move */
        move_tries = 0;  /* none */
        settle_until = Json();  /* none */
        arriving = false;  /* none */
        await_since = Json();  /* none */
        idle_told = false;  /* nothing said */
        proposed_move = idle_warned = false;  /* none */
        leads = is(role, "beaconer");  /* the beaconing station leads */
        calls = 0;  /* no calls */
        close_when_done = !keep_open;  /* end() applied to that contact only */
        callup = contains(levels, kCallupLevel) ? kCallupLevel : 0;  /* the middle level first again */
        if (single) {  /* a single round is over */
            single = false;  /* done */
            role = "answerer";  /* listen again */
            leads = false;  /* not leading */
            target.clear();  /* nobody */
        }  /* end of the single round */
    }  /* end of new_contact */

    std::string cancel(double now) {  /* the operator stops calling (station.py cancel) */
        if (state != "IDLE" || (is(role, "answerer") && !pending.is_null())) {  /* a contact under way, or an answer awaiting confirmation */
            return "";  /* left alone */
        }  /* end of the check */
        std::vector<std::string> stopped;  /* what is stopped */
        if (is(role, "caller")) {  /* a directed call */
            stopped.push_back("calling " + target);  /* that */
        } else if (is(role, "beaconer")) {  /* a beacon round */
            stopped.push_back("beaconing");  /* that */
        }  /* end of the roles */
        if (!long_waiting.is_null()) {  /* a long beacon waiting */
            stopped.push_back("the long beacon");  /* that too */
        }  /* end of the long beacon */
        if (!broadcasts.items().empty()) {  /* broadcast frames waiting */
            stopped.push_back(std::to_string(broadcasts.items().size()) + " broadcast frame(s)");  /* those too */
        }  /* end of the broadcasts */
        if (stopped.empty()) {  /* nothing under way */
            return "";  /* nothing to stop */
        }  /* end of the check */
        long_waiting = Json();  /* nothing more waits */
        broadcasts = Json::list();  /* ... */
        state = "RELEASED";  /* no partner */
        pending = Json();  /* nothing awaited */
        partner.clear();  /* nobody */
        link = -1;  /* no link */
        candidates = Json::list();  /* no answers */
        role = "answerer";  /* listening afterwards */
        single = leads = false;  /* ... */
        target.clear();  /* ... */
        calls = beacons = 0;  /* ... */
        std::string words = "stopped ";  /* what happened */
        for (size_t i = 0; i < stopped.size(); ++i) {  /* each item */
            words += (i ? ", " : "") + stopped[i];  /* listed */
        }  /* end of the items */
        words += " (operator)";  /* by whom */
        say(now, words);  /* in the log */
        return words;  /* for whoever runs the station */
    }  /* end of cancel */

    void release(double now, const std::string &why) {  /* the contact is over */
        if (!partner.empty() && !contains(worked, partner)) {  /* a partner, not yet in the set */
            worked.push_back(partner);  /* worked */
        }  /* end of the set */
        state = "RELEASED";  /* final */
        pending = Json();  /* nothing more */
        quiet = false;  /* no idle lock */
        settle_until = Json();  /* no move */
        await_since = Json();  /* no wait */
        if (truthy(offset_hz) || !tune_at.is_null()) {  /* on, or going to, a working frequency */
            retune(now, Json(0));  /* back to the calling frequency */
        }  /* end of the retune */
        say(now, why);  /* say why */
    }  /* end of release */

    /* ---- acting on what was heard ---- */

    Json handle(const Json &r, double now) {  /* react to a frame just heard */
        if (state == "RELEASED") {  /* over */
            return Json();  /* silent */
        }  /* end of the check */
        long kind = whole(r, "frame_type");  /* what sort */
        if (!r.at("ok").as_bool()) {  /* did not decode */
            if (text(r, "reason") == "body check failed" && (kind == kTypeLink || kind == kTypeAddressed) && locked() && pending.is_null()) {  /* a damaged message frame */
                note(r, true);  /* a slower level asked for */
                say(now, "frame failed its check; asking for L" + std::to_string(want) + " and a resend");  /* explain */
                return ack(now, 0, whole(r, "part"), kAckResend, "ack");  /* ask again */
            }  /* end of the damaged frame */
            return Json();  /* nothing to reply to */
        }  /* end of the failure */
        last_activity = now;  /* heard */
        std::string sender;  /* the callsign it carries */
        const Json *fields = r.find("fields");  /* its fields */
        if (fields != nullptr && fields->is_object() && fields->find("origin") != nullptr && truthy(fields->at("origin"))) {  /* a control frame naming its sender */
            sender = fields->at("origin").as_text();  /* who */
        } else if (kind == kTypeAddressed) {  /* an addressed message */
            sender = text(r, "origin");  /* its origin */
        }  /* end of the sender */
        double snr = real(r, "snr_db");  /* SNR */
        if (!sender.empty() && std::isfinite(snr)) {  /* named and measured */
            heard_at[sender] = {now, report(snr, real(r, "fade_index"), real(r, "offset_hz"), supported_level(History{{snr, real(r, "fade_index")}}, levels))};  /* remembered */
        }  /* end of the reading */
        if (kind == kTypeAddressed) { return on_addressed(r, now); }  /* addressed message */
        if (kind == kTypeNotice) { return on_notice(r, now); }  /* mail notice */
        if (kind == kTypeBeacon) { return on_beacon(r, now); }  /* beacon */
        if (kind == kTypeAnswer) { return on_answer(r, now); }  /* answer */
        if (state == "IDLE" && !is(pending, "confirm")) {  /* everything else needs a partner */
            return Json();  /* ignored */
        }  /* end of the check */
        if (whole(r, "link") != link) {  /* somebody else's lock */
            return Json();  /* ignored */
        }  /* end of the check */
        await_since = Json();  /* the partner has been heard */
        if (kind == kTypeAck) { return on_ack(r, now); }  /* acknowledgment */
        if (kind == kTypeLink) { return on_message(r, now); }  /* message frame */
        if (kind == kTypeIdent) { return on_ident(r, now); }  /* identification */
        return Json();  /* anything else */
    }  /* end of handle */

    Json on_beacon(const Json &r, double now) {  /* a beacon was heard */
        if (!is(role, "answerer") || state != "IDLE" || !truthy(field(r, "listening"))) {  /* not answering */
            return Json();  /* silent */
        }  /* end of the check */
        std::string origin = text(r, "origin");  /* result.origin */
        bool for_mail = (truthy(field(r, "mail_check")) && truthy(mail_call("held_for", origin))) || mail_waiting_at(origin);  /* mail either way */
        if (!answer_beacons && !(for_mail && available)) {  /* answered by hand */
            return Json();  /* silent */
        }  /* end of the check */
        if (contains(worked, origin) && !has_for(origin)) {  /* already worked, nothing new */
            return Json();  /* leave the window to others */
        }  /* end of the check */
        long level = whole(r, "level");  /* the beacon's level */
        double slot_s = reply_slot(level);  /* its slots */
        bool wide_window = truthy(field(r, "wide"));  /* a wide window? */
        long slot = wide_window ? static_cast<long>(rng.integers(0, kWideSlots)) : 0;  /* a random slot, or the only one */
        long slots_left = (wide_window ? kWideSlots : 1) - slot;  /* to the end of the window */
        partner = origin;  /* the caller */
        link = link_id(partner, call);  /* beaconing station first */
        allowed = common_levels(levels, longs(field(r, "levels")));  /* shared levels */
        fresh_start(r);  /* first measurement */
        tx_level = contains(allowed, level) ? level : *std::min_element(allowed.begin(), allowed.end());  /* at the beacon's level */
        last_ident = now;  /* the answer carries the callsign */
        say(now, "heard " + partner + " at " + fixed(real(r, "snr_db"), 0, true) + " dB; answering, asking for L" + std::to_string(want));  /* explain */
        Json f = Json::object();  /* the answer */
        f["type"] = "answer";  /* an answer */
        f["dest"] = partner;  /* to the caller */
        f["origin"] = call;  /* from here */
        f["report"] = my_report();  /* report */
        f["levels"] = long_list(levels);  /* levels */
        f["mail_check"] = false;  /* default */
        f["directed"] = false;  /* a reply, not a call */
        f["level"] = tx_level;  /* level */
        double wait = static_cast<double>(slot) * slot_s + static_cast<double>(slots_left) * slot_s + control_seconds(kTypeAck, 0);  /* its slot, the rest of the window, the confirmation */
        Json tx = send(now, f, "answer", tx_level, Json("confirm"), wait, "slot " + std::to_string(slot) + ", wants L" + std::to_string(want));  /* wait for the confirmation */
        tx["delay"] = static_cast<double>(slot) * slot_s;  /* held back until its slot */
        return tx;  /* the answer */
    }  /* end of on_beacon */

    Json on_addressed(const Json &r, double now) {  /* a fully addressed frame */
        std::string dest = text(r, "dest");  /* for whom */
        if (dest != "ALL" && locked() && !partner.empty()) {  /* mail from the partner */
            return on_mail(r, now);  /* handled there */
        }  /* end of the mail */
        if (dest != "ALL" && dest != call) {  /* for someone else */
            return Json();  /* not this station's */
        }  /* end of the check */
        std::string key = r.at("origin").dump() + "#" + r.at("msg_id").dump();  /* which message */
        if (contains(bulletin_done, key)) {  /* already delivered */
            return Json();  /* nothing */
        }  /* end of the check */
        Parts &parts = bulletin_parts[key];  /* its parts */
        parts[r.at("part").dump()] = r;  /* this one */
        Json joined = join_parts(parts);  /* complete? */
        if (!joined.is_null()) {  /* yes */
            Json entry = Json::list();  /* (origin, dest, text) */
            entry.push(r.at("origin"));  /* origin */
            entry.push(r.at("dest"));  /* destination */
            entry.push(joined);  /* text */
            bulletins.push(entry);  /* delivered */
            bulletin_done.push_back(key);  /* done */
            bulletin_parts.erase(key);  /* parts no longer needed */
            say(now, std::string(dest == "ALL" ? "broadcast" : "message") + " from " + text(r, "origin") + ": " + pyrepr(joined.as_text().substr(0, 40)));  /* explain */
        }  /* end of the delivery */
        return Json();  /* nobody acknowledges these */
    }  /* end of on_addressed */

    Json on_mail(const Json &r, double now) {  /* addressed mail from the partner, inside a contact */
        if (!traffic_from_partner(now)) {  /* this station keeps the turn */
            return Json();  /* carry on */
        }  /* end of the check */
        note(r, false);  /* measurements */
        std::string origin = text(r, "origin");  /* origin */
        long number = whole(r, "msg_id");  /* number */
        std::string dest = text(r, "dest");  /* for whom */
        bool mine = dest == call;  /* for this station? */
        long hops = whole(r, "hops");  /* hops so far */
        if (!mine && (!carries || hops + 1 > kHopLimit || (!truthy(mail_call("has_room", origin)) && !truthy(mail_call("holding", origin, number))))) {  /* will not keep it */
            say(now, "declined to carry mail for " + dest + (carries ? "" : " (carrying mail for others is off)"));  /* explain */
            return ack(now, number, kOfferNoMail, kAckLink, "ack");  /* "I do not carry mail" */
        }  /* end of the refusal */
        if (truthy(mail_call("is_handled", origin, number)) || (!mine && truthy(mail_call("holding", origin, number)))) {  /* dealt with already */
            return ack(now, number, whole(r, "part"), kAckHaveIt, "ack");  /* stop sending it */
        }  /* end of the duplicate */
        std::string key = r.at("origin").dump() + "#" + r.at("msg_id").dump();  /* which message */
        Parts &parts = mail_parts[key];  /* its parts */
        for (const auto &held : parts.items) {  /* each held part */
            if (held.second.at("parts").dump() != r.at("parts").dump()) {  /* split differently */
                parts = Parts();  /* old parts no use */
                break;  /* cleared */
            }  /* end of the test */
        }  /* end of the parts */
        parts[r.at("part").dump()] = r;  /* this one */
        Json joined = join_parts(parts);  /* complete? */
        if (!joined.is_null()) {  /* yes */
            mail_parts.erase(key);  /* parts no longer needed */
            if (mine) {  /* for this station */
                Json entry = Json::list();  /* (origin, dest, text) */
                entry.push(Json(origin == partner ? origin : origin + " via " + partner));  /* who carried it */
                entry.push(Json(call));  /* to here */
                entry.push(joined);  /* text */
                bulletins.push(entry);  /* delivered */
                mail_call("mark_handled", origin, number);  /* never again */
                if (origin != partner) {  /* through a carrier */
                    mail_call("add_receipt", origin, number, call);  /* announce it */
                    mail_call("forget_held_for_me", partner);  /* that carrier has delivered */
                }  /* end of the receipt */
                say(now, "mail from " + origin + (origin == partner ? "" : " via " + partner) + ": " + pyrepr(joined.as_text().substr(0, 40)));  /* explain */
            } else {  /* to carry */
                Json life = Json(std::max(1L, whole(r, "life_hours")));  /* at least an hour */
                Json args = Json::list();  /* hold(dest, origin, number, text, hops, life, came_from) */
                args.push(Json(dest));  /* destination */
                args.push(Json(origin));  /* origin */
                args.push(Json(number));  /* number */
                args.push(joined);  /* text */
                args.push(Json(hops));  /* hops */
                args.push(life);  /* lifetime */
                args.push(Json(partner));  /* passed by */
                mail_ask("hold", args);  /* kept */
                say(now, "holding mail from " + origin + " for " + dest + " (hop " + std::to_string(hops) + ")");  /* explain */
            }  /* end of the two kinds */
        }  /* end of the complete message */
        return ack(now, number, whole(r, "part"), kAckOk, "ack");  /* acknowledge */
    }  /* end of on_mail */

    long outbox_index(long long number) {  /* outbox_ids.index(number), or -1 */
        for (size_t i = 0; i < outbox_ids.items().size(); ++i) {  /* each */
            const Json &n = outbox_ids.items()[i];  /* its number */
            if (!n.is_null() && n.as_int() == number) {  /* this one */
                return static_cast<long>(i);  /* found */
            }  /* end of the test */
        }  /* end of the numbers */
        return -1;  /* not there */
    }  /* end of outbox_index */

    void drop_outbox(long index, std::vector<std::string> &into) {  /* move an outbox message to `into` */
        into.push_back(outbox[static_cast<size_t>(index)]);  /* moved */
        outbox.erase(outbox.begin() + index);  /* removed */
        outbox_to.items().erase(outbox_to.items().begin() + index);  /* with its address */
        outbox_ids.items().erase(outbox_ids.items().begin() + index);  /* and number */
    }  /* end of drop_outbox */

    Json on_notice(const Json &r, double now) {  /* a mail notice */
        const Json &fields = r.at("fields");  /* what it says */
        std::string origin = fields.at("origin").as_text();  /* who */
        notices[origin] = {now, fields};  /* remembered */
        Json args = Json::list();  /* heard_notice(origin, held, receipts, heard) */
        args.push(Json(origin));  /* who */
        args.push(fields.at("held"));  /* held for */
        args.push(fields.at("receipts"));  /* receipts */
        args.push(fields.at("heard"));  /* heard */
        Json done = mail_ask("heard_notice", args);  /* own messages now delivered */
        for (const auto &n : done.items()) {  /* each */
            long index = outbox_index(n.as_int());  /* still waiting here? */
            if (index >= 0 && !(index == 0 && truthy(plan) && job.is_null())) {  /* and not being sent */
                drop_outbox(index, delivered);  /* delivered */
                say(now, origin + " reports message " + n.dump() + " delivered");  /* explain */
            }  /* end of the test */
        }  /* end of the numbers */
        if (contains(longs(fields.at("held")), call_hash(call))) {  /* it holds mail for this station */
            say(now, origin + " holds mail for this station");  /* explain */
        }  /* end of the note */
        return Json();  /* no reply */
    }  /* end of on_notice */

    static bool is_call(const Json &r) {  /* an answer frame carrying a directed call */
        const Json *d = r.at("fields").find("directed");  /* the flag */
        return d != nullptr && truthy(*d);  /* set? */
    }  /* end of is_call */

    bool expects_call_from(const std::string &who, double now) {  /* a call this station asked for? */
        double *t = called_t.find(who);  /* when it was called */
        return now - last_beacon_t <= kExpect || now - (t != nullptr ? *t : -1e9) <= kExpect;  /* a recent beacon or call */
    }  /* end of expects_call_from */

    Json on_answer(const Json &r, double now) {  /* an answer was heard */
        std::string origin = text(r, "origin");  /* who */
        std::string dest = text(r, "dest");  /* to whom */
        bool listening_role = role.is_null() || is(role, "answerer");  /* answerer or no role */
        if (!available && is_call(r) && dest == call && state == "IDLE" && listening_role) {  /* called while not available */
            link = link_id(call, origin);  /* the caller's link number */
            tx_level = whole(r, "level");  /* at the call's level */
            say(now, "called by " + origin + "; replying: not available");  /* explain */
            Json f = Json::object();  /* the one short reply */
            f["type"] = "ack";  /* an acknowledgment */
            f["link"] = link;  /* link */
            f["msg_id"] = 0;  /* none */
            f["part"] = kOfferUnavailable;  /* "not available" */
            f["status"] = kAckLink;  /* status 3 */
            f["report"] = report_of(r);  /* how the call was heard */
            f["level"] = tx_level;  /* level */
            link = -1;  /* no contact */
            return send(now, f, "not available", tx_level, Json(), 0.0, "to " + origin);  /* sent */
        }  /* end of the refusal */
        bool wanted = answer_calls || expects_call_from(origin, now) || (truthy(field(r, "mail_check")) && truthy(mail_call("held_for", origin)));  /* takes the call */
        bool answering_call = is(role, "answerer") && pending.is_null() && is_call(r) && wanted;  /* a listening station */
        bool beaconing_call = is(role, "beaconer") && is(pending, "answer") && is_call(r);  /* one in its reply window */
        bool called_back = is(role, "caller") && is_call(r) && origin == target;  /* one calling that very station */
        if (state == "IDLE" && dest == call && (answering_call || beaconing_call || called_back)) {  /* a call it takes */
            if (beaconing_call) {  /* mid beacon round */
                candidates = Json::list();  /* round over */
                if (single) {  /* a single round */
                    role = "answerer";  /* listen afterwards */
                }  /* end of the role */
            }  /* end of the round */
            if (called_back) {  /* its call answered by a call */
                pending = Json();  /* stop waiting */
            }  /* end of the call back */
            say(now, "called by " + origin);  /* explain */
            leads = true;  /* takes the beaconing station's part */
            lock_with(r, now);  /* locked */
            return ack(now, 0, kOfferTurn, kAckLink, "confirm", Json("offer"), longest_reply());  /* confirm, hand the caller the turn */
        }  /* end of the call */
        if (!is(role, "beaconer") || !is(pending, "answer") || dest != call) {  /* not expecting one */
            return Json();  /* silent */
        }  /* end of the check */
        if (wide) {  /* a wide window */
            candidates.push(r);  /* kept */
            return Json();  /* decide later */
        }  /* end of the wide window */
        return lock_with(r, now);  /* lock at once */
    }  /* end of on_answer */

    Json lock_with(const Json &r, double now) {  /* lock with the station that answered */
        partner = text(r, "origin");  /* who */
        link = link_id(call, partner);  /* beaconing station first */
        allowed = common_levels(levels, longs(field(r, "levels")));  /* shared levels */
        tx_level = cap_level(static_cast<long>(field(r, "report").at("want_level").as_int()), allowed);  /* the level it asked for */
        fresh_start(r);  /* first measurement */
        state = "LOCKED";  /* locked */
        my_turn = true;  /* beaconing station first */
        beacons = 0;  /* answered */
        say(now, "locked with " + partner + "; told to send at L" + std::to_string(tx_level) + ", asking for L" + std::to_string(want));  /* explain */
        return ack(now, 0, kOfferReply, kAckLink, "confirm");  /* confirm */
    }  /* end of lock_with */

    Json on_ack(const Json &r, double now) {  /* an acknowledgment */
        const Json &fields = r.at("fields");  /* its contents */
        long status = static_cast<long>(fields.at("status").as_int());  /* verdict */
        long part = static_cast<long>(fields.at("part").as_int());  /* part (or offer code) */
        if (status == kAckLink && part == kOfferUnavailable && is(role, "caller") && state == "IDLE") {  /* "not available" */
            unavailable_from = partner;  /* who */
            release(now, partner + " is not available");  /* stop calling */
            return Json();  /* nothing */
        }  /* end of the refusal */
        tx_level = cap_level(static_cast<long>(fields.at("report").at("want_level").as_int()), allowed);  /* the level asked for */
        if (state == "IDLE") {  /* waiting for this */
            fresh_start(r);  /* first frame since the lock */
            state = "LOCKED";  /* confirmed */
            say(now, "locked with " + partner + "; told to send at L" + std::to_string(tx_level));  /* explain */
        }  /* end of the lock */
        if (status == kAckLink && part == kOfferNoMail && !job.is_null() && is(pending, "ack")) {  /* the partner will not carry the mail */
            pending = Json();  /* over */
            misses = resends = 0;  /* reset */
            if (!contains(refused, partner)) {  /* a set */
                refused.push_back(partner);  /* not asked again */
            }  /* end of the set */
            say(now, partner + " does not carry mail for others");  /* explain */
            job = Json();  /* nothing under way */
            plan = Json::list();  /* nothing planned */
            return next(now);  /* carry on */
        }  /* end of the refusal */
        if (status == kAckLink) {  /* no message referred to */
            return on_link_ack(r, part, now);  /* lock business */
        }  /* end of the link business */
        note(r, false);  /* a clean frame */
        if (!is(pending, "ack")) {  /* not waiting for one */
            return Json();  /* nothing */
        }  /* end of the check */
        pending = Json();  /* over */
        misses = 0;  /* answering */
        if (state == "DEGRADED") {  /* recovering */
            state = "LOCKED";  /* heard again */
        }  /* end of the recovery */
        if (status == kAckResend) {  /* failed at the far end */
            ++resends;  /* counted */
            if (resends > kMaxResends) {  /* too many */
                return reacquire(now);  /* check the path */
            }  /* end of the check */
            say(now, "asked to resend at L" + std::to_string(tx_level));  /* explain */
            return send_part(now);  /* again */
        }  /* end of the resend */
        resends = 0;  /* this frame is done */
        part_index = status == kAckHaveIt ? static_cast<long>(plan.items().size()) : part_index + 1;  /* the next frame, or all done */
        if (part_index >= static_cast<long>(plan.items().size())) {  /* the last frame */
            if (!job.is_null()) {  /* mail */
                job_done(now, status);  /* recorded */
            } else {  /* own message */
                delivered.push_back(outbox.front());  /* delivered */
                outbox.erase(outbox.begin());  /* removed */
                outbox_to.items().erase(outbox_to.items().begin());  /* with its address */
                Json number = outbox_ids.items().front();  /* and number */
                outbox_ids.items().erase(outbox_ids.items().begin());  /* removed */
                if (!number.is_null()) {  /* to a named station */
                    mail_call("own_done", number);  /* no longer waiting */
                }  /* end of the store */
                say(now, "message " + std::to_string(current_id) + " delivered");  /* explain */
            }  /* end of the kinds */
            plan = Json::list();  /* nothing under way */
        }  /* end of the message */
        return next(now);  /* carry on */
    }  /* end of on_ack */

    void job_done(double now, long status) {  /* mail taken in full */
        Json done = job;  /* the mail */
        job = Json();  /* nothing under way */
        bool already = status == kAckHaveIt;  /* it had it */
        const std::string &kind = done.at("kind").as_text();  /* which */
        if (kind == "deliver") {  /* delivered */
            mail_call("delivered_held", done.at("origin"), done.at("id"), partner);  /* recorded */
            say(now, "mail from " + done.at("origin").as_text() + " " + (already ? "was already with" : "delivered to") + " " + partner);  /* explain */
        } else if (kind == "hand") {  /* handed over */
            mail_call("own_carried", done.at("id"), partner);  /* a carrier */
            say(now, partner + " " + (already ? "already carries" : "is carrying") + " the message for " + done.at("dest").as_text());  /* explain */
        } else {  /* passed on */
            mail_call("passed", done.at("origin"), done.at("id"), partner);  /* noted */
            say(now, partner + " " + (already ? "already had" : "took") + " the mail for " + done.at("dest").as_text());  /* explain */
        }  /* end of the kinds */
    }  /* end of job_done */

    bool gives_way(double now) {  /* both sending: who backs off? */
        if (!(is(pending, "ack") || is(pending, "offer") || is(pending, "probe") || is(pending, "move"))) {  /* no exchange of its own */
            return true;  /* no clash */
        }  /* end of the check */
        if (leads) {  /* keeps the turn */
            return false;  /* ignores the frame */
        }  /* end of the leader */
        say(now, "both sides were sending; giving way");  /* explain */
        pending = Json();  /* stop waiting */
        my_turn = false;  /* turn handed back */
        misses = probes = 0;  /* the partner is there */
        return true;  /* answer it */
    }  /* end of gives_way */

    Json on_link_ack(const Json &r, long code, double now) {  /* a status-3 acknowledgment */
        if (code == kOfferMove) {  /* a move */
            return on_move(r, now);  /* dealt with there */
        }  /* end of the move */
        if ((code == kOfferProbe || code == kOfferTurn) && !gives_way(now)) {  /* asked while mid-exchange */
            return Json();  /* carry on */
        }  /* end of the clash */
        if (code == kOfferProbe) {  /* the partner is probing */
            fresh_start(r);  /* afresh */
            state = "LOCKED";  /* it is there */
            clear_stored = true;  /* half-received frame forgotten */
            say(now, "probe heard; replying, asking for L" + std::to_string(want));  /* explain */
            return ack(now, 0, kOfferReply, kAckLink, "reply");  /* "still here" */
        }  /* end of the probe */
        note(r, false);  /* a clean frame */
        if (code == kOfferTurn) {  /* the turn offered */
            peer_empty = !is(pending, "confirm");  /* the partner is empty (unless it is confirming a lock) */
            pending = Json();  /* over */
            if (truthy(plan) || has_traffic()) {  /* traffic here */
                my_turn = true;  /* take the turn */
                return next(now);  /* use it */
            }  /* end of the traffic */
            my_turn = false;  /* the partner keeps it */
            quiet = true;  /* idle lock */
            return ack(now, 0, kOfferReply, kAckLink, "reply");  /* say so */
        }  /* end of the offer */
        if (is(pending, "probe")) {  /* a probe answered */
            fresh_start(r);  /* afresh */
            state = "LOCKED";  /* back */
            pending = Json();  /* over */
            misses = probes = resends = 0;  /* clean slate */
            my_turn = true;  /* carry on */
            if (arriving) {  /* after a move */
                arriving = false;  /* arrived */
                say(now, "partner found on the working frequency; told to send at L" + std::to_string(tx_level) + ", asking for L" + std::to_string(want));  /* explain */
            } else {  /* an ordinary recovery */
                say(now, "reacquired; told to send at L" + std::to_string(tx_level) + ", asking for L" + std::to_string(want));  /* explain */
            }  /* end of the two cases */
            return next(now);  /* resume */
        }  /* end of the probe reply */
        if (is(pending, "move")) {  /* a plain reply to a move: it cannot */
            pending = Json();  /* over */
            misses = 0;  /* answering */
            moved = true;  /* not again */
            say(now, "partner cannot change frequency; staying on the calling frequency");  /* explain */
            return next(now);  /* carry on */
        }  /* end of the refused move */
        if (is(pending, "offer")) {  /* the turn declined */
            pending = Json();  /* over */
            misses = 0;  /* answering */
            peer_empty = true;  /* both empty */
            return next(now);  /* close, or stay quiet */
        }  /* end of the declined offer */
        if (is(pending, "confirm")) {  /* the lock confirmed */
            pending = Json();  /* over */
        }  /* end of the confirmation */
        return Json();  /* nothing */
    }  /* end of on_link_ack */

    Json on_move(const Json &r, double now) {  /* a status-3 acknowledgment about moving */
        long steps = static_cast<long>(field(r, "msg_id").as_int());  /* unsigned 16-bit count */
        double offset = static_cast<double>((steps >= 0x8000 ? steps - 0x10000 : steps)) * kMoveStep;  /* signed hertz */
        Json offset_json = Json(static_cast<long>((steps >= 0x8000 ? steps - 0x10000 : steps) * 100));  /* the same, whole (as Python: int times int) */
        note(r, false);  /* a clean frame */
        bool same = !move_to_hz.is_null() && offset == move_to_hz.as_real();  /* the offset this station proposed */
        if (is(pending, "move") && (same || leads)) {  /* agreed (or the leader's proposal stands) */
            if (!same) {  /* proposed elsewhere at the same moment */
                return Json();  /* ignored */
            }  /* end of the clash */
            pending = Json();  /* over */
            misses = 0;  /* answering */
            moved = true;  /* agreed */
            retune(now, offset_json);  /* change now */
            settle_until = Json(now + kMoveSettle);  /* then probe */
            last_traffic = now;  /* the idle clock starts */
            idle_warned = false;  /* no warning */
            my_turn = true;  /* this station first */
            say(now, "partner agreed; moving " + fixed(offset / 1000.0, 1, true) + " kHz to the working frequency");  /* explain */
            return Json();  /* nothing until settled */
        }  /* end of the agreement */
        pending = Json();  /* a proposal from the partner ends any wait */
        my_turn = false;  /* the partner first after the move */
        moved = true;  /* one move per contact */
        if (!can_move) {  /* cannot retune */
            say(now, "partner proposed a working frequency; this station cannot change frequency, staying");  /* explain */
            return ack(now, 0, kOfferReply, kAckLink, "reply");  /* "no" */
        }  /* end of the refusal */
        Json answer = ack(now, steps, kOfferMove, kAckLink, "move-ok");  /* "agreed" */
        double seconds = answer.at("seconds").as_real();  /* its length */
        retune(now + seconds + 0.5, offset_json);  /* move once it has been sent */
        await_since = Json(now + seconds);  /* and wait there */
        say(now, "partner proposed a working frequency; agreeing and moving " + fixed(offset / 1000.0, 1, true) + " kHz");  /* explain */
        return answer;  /* the agreement */
    }  /* end of on_move */

    bool traffic_from_partner(double now) {  /* a message frame from the partner: turn bookkeeping */
        if (state == "IDLE") {  /* the confirmation was missed */
            state = "LOCKED";  /* the link number proves the lock */
        }  /* end of the lock */
        if (is(pending, "confirm") || is(pending, "offer")) {  /* it answers a pending confirmation or offer */
            pending = Json();  /* over */
            misses = 0;  /* answering */
        } else if (!gives_way(now)) {  /* both sending */
            return false;  /* the leader carries on */
        }  /* end of the turn */
        my_turn = false;  /* the partner has it */
        peer_empty = false;  /* and has traffic */
        quiet = false;  /* not idle */
        idle_told = false;  /* to be told again */
        last_traffic = now;  /* the idle clock restarts */
        idle_warned = false;  /* no warning */
        return true;  /* take the frame */
    }  /* end of traffic_from_partner */

    Json on_message(const Json &r, double now) {  /* a message frame */
        if (!traffic_from_partner(now)) {  /* this station keeps the turn */
            return Json();  /* carry on */
        }  /* end of the check */
        tx_level = cap_level(whole(r, "want_level"), allowed);  /* the level wanted back */
        note(r, false);  /* measurements */
        long status = kAckOk;  /* received */
        long number = whole(r, "msg_id");  /* its number */
        if (contains(done_ids, number) || truthy(mail_call("is_handled", partner, number))) {  /* already here */
            status = kAckHaveIt;  /* stop sending it */
        } else {  /* still collecting */
            std::string key = std::to_string(number);  /* which message */
            Parts &parts = partial[key];  /* its parts */
            for (const auto &held : parts.items) {  /* each */
                if (held.second.at("parts").dump() != r.at("parts").dump()) {  /* split differently */
                    parts = Parts();  /* old parts no use */
                    break;  /* cleared */
                }  /* end of the test */
            }  /* end of the parts */
            parts[r.at("part").dump()] = r;  /* this one */
            Json joined = join_parts(parts);  /* complete? */
            if (!joined.is_null()) {  /* yes */
                inbox.push_back(joined.as_text());  /* delivered */
                done_ids.push_back(number);  /* done */
                mail_call("mark_handled", partner, number);  /* and beyond this contact */
                partial.erase(key);  /* parts no longer needed */
                say(now, "received message " + std::to_string(number) + ": " + pyrepr(joined.as_text().substr(0, 40)));  /* explain */
            }  /* end of the complete message */
        }  /* end of the collecting */
        return ack(now, number, whole(r, "part"), status, "ack");  /* acknowledge */
    }  /* end of on_message */

    Json on_ident(const Json &r, double now) {  /* an identification */
        if (!truthy(field(r, "final"))) {  /* routine */
            return Json();  /* no reply */
        }  /* end of the check */
        if (sent_final) {  /* already said goodbye */
            release(now, "contact closed");  /* both done */
            return Json();  /* nothing */
        }  /* end of the second goodbye */
        Json answer = ident(now, true);  /* goodbye in return */
        release(now, "contact closed by partner");  /* and leave */
        if (!tune_at.is_null()) {  /* on a working frequency */
            tune_at = Json(now + answer.at("seconds").as_real() + 0.5);  /* back after the goodbye */
        }  /* end of the retune */
        return answer;  /* the goodbye */
    }  /* end of on_ident */

    /* ---- acting on the clock ---- */

    Json poll(double now) {  /* anything to send unprompted? */
        if (now - tidied >= kMailTidy) {  /* time to tidy the mail */
            tidied = now;  /* remembered */
            Json gone = mail_call("tidy");  /* own messages that ran out */
            for (const auto &n : gone.items()) {  /* each */
                long index = outbox_index(n.as_int());  /* still waiting? */
                if (index >= 0 && !(index == 0 && truthy(plan) && job.is_null())) {  /* and not being sent */
                    drop_outbox(index, expired);  /* expired */
                    say(now, "message " + n.dump() + " expired undelivered");  /* explain */
                }  /* end of the test */
            }  /* end of the numbers */
        }  /* end of the tidy */
        if (state == "RELEASED") {  /* over */
            return Json();  /* nothing */
        }  /* end of the check */
        if (watching_idle()) {  /* watching an idle working frequency */
            double idle = now - last_traffic;  /* time without messages */
            if (idle >= kWorkingIdle) {  /* the limit */
                say(now, "no messages for " + fixed(kWorkingIdle / 60, 0) + " minutes on the working frequency; closing the contact and returning to the calling frequency");  /* explain */
                close_when_done = true;  /* close properly */
            } else if (idle >= kWorkingIdle - kWorkingWarn && !idle_warned) {  /* a minute to go */
                idle_warned = true;  /* once */
                say(now, "no messages for " + fixed((kWorkingIdle - kWorkingWarn) / 60, 0) + " minutes; returning to the calling frequency in one minute unless a message is sent");  /* warning */
            }  /* end of the idle checks */
        }  /* end of the watch */
        if (!pending.is_null()) {  /* waiting */
            if (now < deadline) {  /* still time */
                return Json();  /* wait */
            }  /* end of the wait */
            return timed_out(now);  /* no reply came */
        }  /* end of the waiting */
        if (!settle_until.is_null()) {  /* radios retuning */
            if (now < settle_until.as_real()) {  /* not yet */
                return Json();  /* wait */
            }  /* end of the wait */
            settle_until = Json();  /* settled */
            arriving = true;  /* look for the partner */
            return ack(now, 0, kOfferProbe, kAckLink, "probe", Json("probe"), control_seconds(kTypeAck, want));  /* "are you here?" */
        }  /* end of the settling */
        if (!await_since.is_null() && now - await_since.as_real() >= kMoveWait) {  /* the partner never appeared */
            release(now, "partner not heard on the working frequency; lock given up");  /* back */
            return Json();  /* nothing */
        }  /* end of the wait */
        if (locked() && quiet && !my_turn && now - last_activity >= quiet_gap()) {  /* idle lock, partner has had its chance */
            if (has_traffic() || close_when_done) {  /* something to send, or closing */
                quiet = false;  /* not idle */
                my_turn = true;  /* take the turn */
                return next(now);  /* send */
            }  /* end of the traffic */
            if (now - last_ident >= kIdentEvery) {  /* time to identify */
                return ident(now, false);  /* identify */
            }  /* end of the identification */
        }  /* end of the idle lock */
        if (!long_waiting.is_null() && state == "IDLE" && pending.is_null()) {  /* a long beacon waits */
            if (hold(now, "long beacon", kLongLevel)) {  /* frequency in use */
                return Json();  /* wait */
            }  /* end of the hold */
            Json f = long_waiting;  /* taken */
            long_waiting = Json();  /* gone */
            last_ident = now;  /* it carries the callsign */
            return send(now, f, "long beacon", kLongLevel, Json(), 0.0, "nobody answers a long beacon");  /* sent */
        }  /* end of the long beacon */
        if (!broadcasts.items().empty() && state == "IDLE") {  /* a broadcast waits */
            if (hold(now, "broadcast", static_cast<long>(broadcasts.items()[0].at(1).as_int()))) {  /* frequency in use */
                return Json();  /* wait */
            }  /* end of the hold */
            Json entry = broadcasts.items().front();  /* its next frame */
            broadcasts.items().erase(broadcasts.items().begin());  /* taken */
            last_ident = now;  /* it carries the callsign */
            return send(now, entry.at(0), "broadcast", static_cast<long>(entry.at(1).as_int()), Json(), 0.0, entry.at(2).as_text());  /* sent */
        }  /* end of the broadcast */
        if (is(role, "beaconer") && state == "IDLE") {  /* looking for a partner */
            if (hold(now, "beacon", callup)) {  /* in use */
                return Json();  /* wait */
            }  /* end of the hold */
            return beacon_now(now);  /* call */
        }  /* end of the beaconing */
        if (is(role, "caller") && state == "IDLE") {  /* calling one station */
            if (hold(now, "call", calls == 0 ? callup : *std::min_element(levels.begin(), levels.end()))) {  /* in use */
                return Json();  /* wait */
            }  /* end of the hold */
            return call_now(now);  /* call it */
        }  /* end of the calling */
        if (locked() && my_turn) {  /* this station's turn */
            if (peer_empty && !truthy(plan) && !has_traffic() && !close_when_done) {  /* both idle, kept open */
                if (now - last_activity < kKeepalive) {  /* not long enough */
                    return Json();  /* quiet */
                }  /* end of the wait */
                peer_empty = false;  /* check on the partner */
            }  /* end of the idle lock */
            return next(now);  /* whatever is due */
        }  /* end of the turn */
        if (locked() && now - last_activity >= kLockTimeout) {  /* nothing heard for long */
            release(now, "partner not heard for five minutes; lock given up");  /* stop waiting */
        }  /* end of the timeout */
        return Json();  /* nothing */
    }  /* end of poll */

    double quiet_gap() {  /* how long an idle station waits before taking the turn */
        return control_seconds(kTypeIdent, want) + kTurnaround + reply_margin;  /* room for a goodbye */
    }  /* end of quiet_gap */

    bool watching_idle() {  /* gives up an idle working frequency? */
        return truthy(offset_hz) && proposed_move && locked() && !close_when_done;  /* on its own working frequency, kept open */
    }  /* end of watching_idle */

    Json next_wake() {  /* when poll() is next needed, or None */
        Json usual = usual_wake();  /* the ordinary rules */
        if (!watching_idle()) {  /* nothing to add */
            return usual;  /* as it is */
        }  /* end of the check */
        double idle_at = last_traffic + (idle_warned ? kWorkingIdle : kWorkingIdle - kWorkingWarn);  /* warning or closing */
        return usual.is_null() ? Json(idle_at) : Json(std::min(usual.as_real(), idle_at));  /* whichever first */
    }  /* end of next_wake */

    Json usual_wake() {  /* the next moment the ordinary rules need attention */
        if (state == "RELEASED") {  /* over */
            return Json();  /* never */
        }  /* end of the check */
        if (!pending.is_null()) {  /* waiting */
            return Json(deadline);  /* until the deadline */
        }  /* end of the wait */
        if (!settle_until.is_null()) {  /* retuning */
            return settle_until;  /* until settled */
        }  /* end of the settling */
        if (locked() && quiet && !my_turn && (has_traffic() || close_when_done)) {  /* idle, with something to send */
            return Json(last_activity + quiet_gap());  /* after the partner's chance */
        }  /* end of the idle lock */
        if (!await_since.is_null()) {  /* waiting on a working frequency */
            return Json(await_since.as_real() + kMoveWait);  /* until that runs out */
        }  /* end of the wait */
        if (locked() && my_turn && peer_empty && !close_when_done) {  /* idle and kept open */
            return Json(last_activity + kKeepalive);  /* keep-alive */
        }  /* end of the keep-alive */
        if (locked() && !my_turn) {  /* waiting for the partner */
            return Json(last_activity + kLockTimeout);  /* until it is too long */
        }  /* end of the timeout */
        return Json();  /* nothing */
    }  /* end of usual_wake */

    Json call_now(double now) {  /* send a directed call */
        if (calls >= kCallTries) {  /* enough */
            release(now, "no answer from " + target);  /* give up */
            return Json();  /* nothing */
        }  /* end of the check */
        ++calls;  /* counted */
        called_t[target] = now;  /* a call back is expected */
        partner = target;  /* the station called */
        link = link_id(partner, call);  /* the called station first */
        allowed = levels;  /* assume the same levels */
        tx_level = calls == 1 ? callup : *std::min_element(allowed.begin(), allowed.end());  /* middle level first, then the slowest */
        last_ident = now;  /* the call carries the callsign */
        if (calls == 1) {  /* the first */
            say(now, "calling " + target);  /* explain */
        }  /* end of the note */
        Json rep;  /* the report it carries */
        auto *heard = heard_at.find(target);  /* the last reading of that station */
        if (heard != nullptr && now - heard->first <= kHeardForCall) {  /* recent */
            rep = heard->second;  /* with the call */
        } else {  /* none */
            rep = report(kSnrFloor, std::nan(""), 0.0, 0);  /* no measurement, L0 */
        }  /* end of the report */
        Json f = Json::object();  /* a directed call */
        f["type"] = "answer";  /* an answer frame */
        f["dest"] = partner;  /* to the station called */
        f["origin"] = call;  /* from here */
        f["report"] = rep;  /* report */
        f["levels"] = long_list(levels);  /* levels */
        f["mail_check"] = true;  /* asking for mail */
        f["directed"] = true;  /* a call */
        f["level"] = tx_level;  /* level */
        return send(now, f, "call", tx_level, Json("confirm"), control_seconds(kTypeAck, 0), "to " + target);  /* wait for the confirmation */
    }  /* end of call_now */

    Json notice_now(double now) {  /* a mail notice before a beacon, or None */
        if (notice_sent) {  /* one just went */
            notice_sent = false;  /* the beacon next */
            return Json();  /* send the beacon */
        }  /* end of the check */
        if (!available || (callup == 0 && now - last_notice_l0 < kNoticeL0Every)) {  /* not taking contacts, or an L0 notice too soon */
            return Json();  /* none */
        }  /* end of the check */
        Json args = Json::list();  /* notice_lists(heard calls) */
        args.push(text_list(heard_calls(now)));  /* stations heard */
        Json lists = mail_ask("notice_lists", args);  /* what it would say */
        const Json &held = lists.at(0);  /* held for */
        const Json &receipts = lists.at(1);  /* receipts */
        if (!truthy(held) && !truthy(receipts)) {  /* nothing to tell */
            return Json();  /* none */
        }  /* end of the check */
        if (callup == 0) {  /* with an L0 beacon */
            last_notice_l0 = now;  /* remembered */
        }  /* end of the note */
        notice_sent = true;  /* the beacon follows */
        last_ident = now;  /* it carries the callsign */
        Json f = Json::object();  /* the notice */
        f["type"] = "notice";  /* a mail notice */
        f["call"] = call;  /* from here */
        f["held"] = held;  /* held for */
        f["receipts"] = receipts;  /* receipts */
        f["heard"] = lists.at(2);  /* heard */
        f["level"] = callup;  /* at the beacon's level */
        return send(now, f, "mail notice", callup, Json(), 0.0, "holds mail for " + std::to_string(held.items().size()) + ", " + std::to_string(receipts.items().size()) + " receipt(s)");  /* no reply */
    }  /* end of notice_now */

    Json beacon_now(double now) {  /* send a beacon */
        Json notice = notice_now(now);  /* a notice first? */
        if (!notice.is_null()) {  /* yes */
            return notice;  /* the beacon comes next */
        }  /* end of the notice */
        ++beacons;  /* counted */
        last_beacon_t = now;  /* calls expected for a while */
        last_ident = now;  /* it carries the callsign */
        candidates = Json::list();  /* a new window */
        Json f = Json::object();  /* the beacon */
        f["type"] = "beacon";  /* a beacon */
        f["call"] = call;  /* from here */
        f["grid"] = grid;  /* locator */
        f["levels"] = long_list(levels);  /* levels */
        beacon_sent_at = callup;  /* its level */
        if (!available) {  /* a presence beacon */
            f["listening"] = false;  /* taking no answers */
            f["mail_check"] = false;  /* default */
            f["holds_mail"] = false;  /* default */
            f["level"] = beacon_sent_at;  /* level */
            f["wide"] = false;  /* default */
            Json tx = send(now, f, "beacon", beacon_sent_at, Json(), 0.0, "not available: presence only");  /* no window */
            release(now, "presence beacon sent; not taking contacts");  /* round over */
            return tx;  /* sent */
        }  /* end of the presence beacon */
        f["listening"] = true;  /* taking answers */
        f["mail_check"] = true;  /* asking for mail */
        f["holds_mail"] = bag_held();  /* holding mail? */
        f["level"] = beacon_sent_at;  /* level */
        f["wide"] = wide;  /* window size */
        double window = static_cast<double>(wide ? kWideSlots : 1) * reply_slot(beacon_sent_at);  /* how long to listen */
        return send(now, f, "beacon", beacon_sent_at, Json("answer"), window - kReplyMargin, wide ? "wide window" : "");  /* then listen */
    }  /* end of beacon_now */

    bool hold(double now, const std::string &what, long level) {  /* listen before transmitting */
        if (busy_fn == nullptr || busy_fn(busy_ctx, static_cast<int>(level)) == 0) {  /* clear */
            if (!held_since.is_null()) {  /* was holding */
                say(now, "frequency clear after " + fixed(now - held_since.as_real(), 0) + " s; sending the " + what);  /* explain */
                held_since = Json();  /* no longer */
            }  /* end of the note */
            return false;  /* go ahead */
        }  /* end of the clear case */
        if (held_since.is_null()) {  /* just begun */
            held_since = Json(now);  /* remembered */
        }  /* end of the start */
        if (now - held_told >= kHoldTell) {  /* not told lately */
            held_told = now;  /* remembered */
            say(now, "frequency in use: holding the " + what + " until it is clear");  /* explain */
        }  /* end of the note */
        return true;  /* wait */
    }  /* end of hold */

    Json timed_out(double now) {  /* the reply did not come */
        Json waited_for = pending;  /* what was expected */
        pending = Json();  /* stop waiting */
        if (is(waited_for, "answer") && !candidates.items().empty()) {  /* a wide window with answers */
            const Json *best = &candidates.items().front();  /* max() by SNR: the first, replaced by anything larger */
            for (const auto &c : candidates.items()) {  /* each */
                if (real(c, "snr_db") > real(*best, "snr_db")) {  /* stronger */
                    best = &c;  /* kept */
                }  /* end of the test */
            }  /* end of the answers */
            Json chosen = *best;  /* copied (candidates may change) */
            wide = candidates.items().size() > 1;  /* several waiting: keep it wide */
            say(now, std::to_string(candidates.items().size()) + " answer(s) in the window; choosing " + text(chosen, "origin"));  /* explain */
            return lock_with(chosen, now);  /* lock */
        }  /* end of the wide window */
        if (is(waited_for, "answer") && beacon_sent_at > 0) {  /* no answer to the faster beacon */
            long was = beacon_sent_at;  /* its level */
            callup = 0;  /* L0 now */
            beacons -= 1;  /* not counted */
            say(now, "no answer at L" + std::to_string(was) + "; calling again at L0");  /* explain */
            return beacon_now(now);  /* the L0 beacon */
        }  /* end of the faster beacon */
        if (is(waited_for, "answer")) {  /* nobody answered */
            wide = true;  /* a wide window from now on */
            if (beacons >= kBeaconTries) {  /* enough */
                release(now, "no answer to the beacon");  /* give up */
                return Json();  /* nothing */
            }  /* end of the check */
            return beacon_now(now);  /* again */
        }  /* end of the beacon */
        if (is(waited_for, "confirm") && is(role, "caller")) {  /* a call unanswered */
            state = "IDLE";  /* still looking */
            return call_now(now);  /* again, or give up */
        }  /* end of the call */
        if (is(waited_for, "confirm")) {  /* lock never confirmed */
            state = "IDLE";  /* listen again */
            say(now, "lock not confirmed; listening again");  /* explain */
            return Json();  /* nothing */
        }  /* end of the confirmation */
        if (is(waited_for, "final")) {  /* no goodbye */
            ++finals;  /* counted */
            if (finals >= kFinalTries) {  /* enough */
                release(now, "contact closed (no closing reply heard)");  /* leave */
                return Json();  /* nothing */
            }  /* end of the check */
            return ident(now, true);  /* once more */
        }  /* end of the goodbye */
        if (is(waited_for, "move")) {  /* no reply to a move */
            if (move_tries < kMoveTries) {  /* once more */
                return propose_move(now);  /* again */
            }  /* end of the retry */
            moved = true;  /* it may have agreed unheard */
            retune(now, move_to_hz);  /* go and look */
            settle_until = Json(now + kMoveSettle);  /* after settling */
            last_traffic = now;  /* the idle clock starts */
            idle_warned = false;  /* no warning */
            say(now, "no reply to the move; looking for the partner on the working frequency");  /* explain */
            return Json();  /* the probe follows */
        }  /* end of the move */
        if (is(waited_for, "probe")) {  /* a probe unanswered */
            ++probes;  /* counted */
            if (probes >= kReacquireTries) {  /* enough */
                release(now, "lock lost; " + std::to_string(outbox.size()) + " message(s) not delivered");  /* give up */
                return Json();  /* nothing */
            }  /* end of the check */
            return reacquire(now);  /* again */
        }  /* end of the probe */
        ++misses;  /* a message frame or offer unanswered */
        if (state == "LOCKED") {  /* degrades */
            state = "DEGRADED";  /* but holds */
        }  /* end of the state */
        if (misses >= kMissLimit) {  /* too many */
            return reacquire(now);  /* find the partner */
        }  /* end of the check */
        tx_level = cap_level(tx_level - 1, allowed);  /* one level slower */
        say(now, "no reply; trying again at L" + std::to_string(tx_level));  /* explain */
        if (is(waited_for, "ack")) {  /* a message frame */
            return send_part(now);  /* again */
        }  /* end of the message */
        return ack(now, 0, kOfferTurn, kAckLink, "offer", Json("offer"), longest_reply());  /* offer again */
    }  /* end of timed_out */

    /* ---- the attributes, read and set by name (as Python's station.name) ---- */

    Json parts_json(const Dict<Parts> &d) {  /* a dict of part dicts */
        Json o = Json::object();  /* the outer dict */
        for (const auto &p : d.items) {  /* each message */
            Json inner = Json::object();  /* its parts */
            for (const auto &q : p.second.items) {  /* each part */
                inner[q.first] = q.second;  /* the report */
            }  /* end of the parts */
            o[p.first] = inner;  /* added */
        }  /* end of the messages */
        return o;  /* the dict */
    }  /* end of parts_json */

    Json pair_dict(const Dict<std::pair<double, Json>> &d) {  /* callsign -> [time, value] */
        Json o = Json::object();  /* the dict */
        for (const auto &p : d.items) {  /* each */
            Json pair = Json::list();  /* (time, value) */
            pair.push(Json(p.second.first));  /* time */
            pair.push(p.second.second);  /* value */
            o[p.first] = pair;  /* added */
        }  /* end of the items */
        return o;  /* the dict */
    }  /* end of pair_dict */

    Json get(const std::string &name) {  /* station.<name> */
        if (name == "call") return Json(call);  /* callsign */
        if (name == "wide") return Json(wide);  /* wide window */
        if (name == "candidates") return candidates;  /* answers in the window */
        if (name == "worked") return text_list(worked);  /* stations worked */
        if (name == "grid") return Json(grid);  /* locator */
        if (name == "levels") return long_list(levels);  /* levels */
        if (name == "close_when_done") return Json(close_when_done);  /* close when done */
        if (name == "keep_open") return Json(keep_open);  /* kept open */
        if (name == "state") return Json(state);  /* state */
        if (name == "role") return role;  /* role */
        if (name == "partner") return Json(partner);  /* partner */
        if (name == "link") return Json(link);  /* link */
        if (name == "allowed") return long_list(allowed);  /* shared levels */
        if (name == "tx_level") return Json(tx_level);  /* sending level */
        if (name == "want") return Json(want);  /* level asked for */
        if (name == "history") {  /* measurements */
            Json l = Json::list();  /* the list */
            for (const auto &h : history) {  /* each */
                Json pair = Json::list();  /* (SNR, fading) */
                pair.push(Json(h.first));  /* SNR */
                pair.push(Json(h.second));  /* fading */
                l.push(pair);  /* added */
            }  /* end of the readings */
            return l;  /* the list */
        }  /* end of history */
        if (name == "clean_run") return Json(clean_run);  /* clean run */
        if (name == "good_run") return Json(good_run);  /* good run */
        if (name == "last_result") return last_result;  /* the last frame */
        if (name == "outbox") return text_list(outbox);  /* outbox */
        if (name == "outbox_to") return outbox_to;  /* addresses */
        if (name == "outbox_ids") return outbox_ids;  /* numbers */
        if (name == "broadcasts") return broadcasts;  /* broadcasts waiting */
        if (name == "long_waiting") return long_waiting;  /* long beacon waiting */
        if (name == "held_since") return held_since;  /* holding since */
        if (name == "held_told") return Json(held_told);  /* told at */
        if (name == "bulletins") return bulletins;  /* addressed messages */
        if (name == "bulletin_parts") return parts_json(bulletin_parts);  /* their parts */
        if (name == "bulletin_done") return text_list(bulletin_done);  /* delivered keys */
        if (name == "target") return Json(target);  /* called station */
        if (name == "calls") return Json(calls);  /* calls */
        if (name == "leads") return Json(leads);  /* leads */
        if (name == "delivered") return text_list(delivered);  /* delivered */
        if (name == "inbox") return text_list(inbox);  /* inbox */
        if (name == "plan") return plan;  /* plan */
        if (name == "plan_text") return Json(plan_text);  /* plan text */
        if (name == "part_index") return Json(part_index);  /* next frame */
        if (name == "current_id") return Json(current_id);  /* number */
        if (name == "pending") return pending;  /* awaited */
        if (name == "deadline") return Json(deadline);  /* deadline */
        if (name == "misses") return Json(misses);  /* misses */
        if (name == "resends") return Json(resends);  /* resends */
        if (name == "probes") return Json(probes);  /* probes */
        if (name == "finals") return Json(finals);  /* finals */
        if (name == "beacons") return Json(beacons);  /* beacons */
        if (name == "my_turn") return Json(my_turn);  /* turn */
        if (name == "peer_empty") return Json(peer_empty);  /* partner empty */
        if (name == "sent_final") return Json(sent_final);  /* goodbye sent */
        if (name == "partial") return parts_json(partial);  /* partial messages */
        if (name == "done_ids") return long_list(done_ids);  /* done */
        if (name == "last_ident") return Json(last_ident);  /* last identified */
        if (name == "last_activity") return Json(last_activity);  /* last active */
        if (name == "log") return text_list(log);  /* log */
        if (name == "reply_margin") return Json(reply_margin);  /* margin */
        if (name == "quiet") return Json(quiet);  /* quiet */
        if (name == "idle_told") return Json(idle_told);  /* idle told */
        if (name == "can_move") return Json(can_move);  /* can move */
        if (name == "move_to_hz") return move_to_hz;  /* working frequency */
        if (name == "offset_hz") return offset_hz;  /* offset now */
        if (name == "tune_at") return tune_at;  /* retune at */
        if (name == "tune_next") return tune_next;  /* retune to */
        if (name == "moved") return Json(moved);  /* moved */
        if (name == "move_tries") return Json(move_tries);  /* move tries */
        if (name == "settle_until") return settle_until;  /* settle until */
        if (name == "arriving") return Json(arriving);  /* arriving */
        if (name == "await_since") return await_since;  /* awaiting since */
        if (name == "proposed_move") return Json(proposed_move);  /* proposed */
        if (name == "last_traffic") return Json(last_traffic);  /* last traffic */
        if (name == "idle_warned") return Json(idle_warned);  /* warned */
        if (name == "single") return Json(single);  /* single round */
        if (name == "answer_beacons") return Json(answer_beacons);  /* answers beacons */
        if (name == "available") return Json(available);  /* available */
        if (name == "answer_calls") return Json(answer_calls);  /* answers calls */
        if (name == "last_beacon_t") return Json(last_beacon_t);  /* last beacon */
        if (name == "called_t") {  /* calls made */
            Json o = Json::object();  /* the dict */
            for (const auto &p : called_t.items) {  /* each */
                o[p.first] = Json(p.second);  /* when */
            }  /* end of the items */
            return o;  /* the dict */
        }  /* end of called_t */
        if (name == "unavailable_from") return Json(unavailable_from);  /* "not available" from */
        if (name == "callup") return Json(callup);  /* call-up level */
        if (name == "beacon_sent_at") return Json(beacon_sent_at);  /* beacon level */
        if (name == "heard_at") return pair_dict(heard_at);  /* readings */
        if (name == "carries") return Json(carries);  /* carries mail */
        if (name == "job") return job;  /* mail job */
        if (name == "refused") return text_list(refused);  /* refused */
        if (name == "mail_parts") return parts_json(mail_parts);  /* mail parts */
        if (name == "expired") return text_list(expired);  /* expired */
        if (name == "notices") return pair_dict(notices);  /* notices */
        if (name == "notice_sent") return Json(notice_sent);  /* notice sent */
        if (name == "last_notice_l0") return Json(last_notice_l0);  /* last L0 notice */
        if (name == "tidied") return Json(tidied);  /* last tidy */
        throw PyError{"AttributeError", "'Station' object has no attribute '" + name + "'"};  /* unknown */
    }  /* end of get */

    void set(const std::string &name, const Json &v) {  /* station.<name> = v */
        auto strings = [](const Json &j) {  /* a list of text */
            std::vector<std::string> out;  /* the list */
            for (const auto &x : j.items()) {  /* each */
                out.push_back(x.as_text());  /* kept */
            }  /* end of the items */
            return out;  /* the list */
        };  /* end of strings */
        if (name == "wide") { wide = truthy(v); return; }  /* wide window */
        if (name == "candidates") { candidates = v; return; }  /* answers */
        if (name == "worked") { worked = strings(v); return; }  /* worked */
        if (name == "grid") { grid = v.as_text(); return; }  /* locator */
        if (name == "levels") { levels = longs(v); return; }  /* levels */
        if (name == "close_when_done") { close_when_done = truthy(v); return; }  /* close when done */
        if (name == "keep_open") { keep_open = truthy(v); return; }  /* kept open */
        if (name == "state") { state = v.as_text(); return; }  /* state */
        if (name == "role") { role = v; return; }  /* role */
        if (name == "partner") { partner = v.as_text(); return; }  /* partner */
        if (name == "link") { link = static_cast<long>(v.as_int()); return; }  /* link */
        if (name == "allowed") { allowed = longs(v); return; }  /* shared levels */
        if (name == "tx_level") { tx_level = static_cast<long>(v.as_int()); return; }  /* sending level */
        if (name == "want") { want = static_cast<long>(v.as_int()); return; }  /* level asked for */
        if (name == "history") {  /* measurements */
            history.clear();  /* replaced */
            for (const auto &h : v.items()) {  /* each */
                history.emplace_back(h.at(0).as_real(), h.at(1).as_real());  /* (SNR, fading) */
            }  /* end of the readings */
            return;  /* done */
        }  /* end of history */
        if (name == "outbox") { outbox = strings(v); return; }  /* outbox */
        if (name == "outbox_to") { outbox_to = v; return; }  /* addresses */
        if (name == "outbox_ids") { outbox_ids = v; return; }  /* numbers */
        if (name == "target") { target = v.as_text(); return; }  /* called station */
        if (name == "calls") { calls = static_cast<long>(v.as_int()); return; }  /* calls */
        if (name == "leads") { leads = truthy(v); return; }  /* leads */
        if (name == "plan") { plan = v; return; }  /* plan */
        if (name == "plan_text") { plan_text = v.as_text(); return; }  /* plan text */
        if (name == "part_index") { part_index = static_cast<long>(v.as_int()); return; }  /* next frame */
        if (name == "pending") { pending = v; return; }  /* awaited */
        if (name == "deadline") { deadline = v.as_real(); return; }  /* deadline */
        if (name == "misses") { misses = static_cast<long>(v.as_int()); return; }  /* misses */
        if (name == "beacons") { beacons = static_cast<long>(v.as_int()); return; }  /* beacons */
        if (name == "my_turn") { my_turn = truthy(v); return; }  /* turn */
        if (name == "peer_empty") { peer_empty = truthy(v); return; }  /* partner empty */
        if (name == "last_ident") { last_ident = v.as_real(); return; }  /* last identified */
        if (name == "last_activity") { last_activity = v.as_real(); return; }  /* last active */
        if (name == "reply_margin") { reply_margin = v.as_real(); return; }  /* margin */
        if (name == "quiet") { quiet = truthy(v); return; }  /* quiet */
        if (name == "can_move") { can_move = truthy(v); return; }  /* can move */
        if (name == "move_to_hz") { move_to_hz = v; return; }  /* working frequency */
        if (name == "single") { single = truthy(v); return; }  /* single round */
        if (name == "answer_beacons") { answer_beacons = truthy(v); return; }  /* answers beacons */
        if (name == "available") { available = truthy(v); return; }  /* available */
        if (name == "answer_calls") { answer_calls = truthy(v); return; }  /* answers calls */
        if (name == "carries") { carries = truthy(v); return; }  /* carries mail */
        if (name == "callup") { callup = static_cast<long>(v.as_int()); return; }  /* call-up level */
        if (name == "unavailable_from") { unavailable_from = v.as_text(); return; }  /* "not available" from */
        if (name == "last_traffic") { last_traffic = v.as_real(); return; }  /* last traffic */
        if (name == "tidied") { tidied = v.as_real(); return; }  /* last tidy */
        throw PyError{"AttributeError", "the station's '" + name + "' cannot be set this way"};  /* not settable */
    }  /* end of set */

    Json serve(const std::string &op, const Json &a) {  /* one request */
        auto num = [&](size_t i) { return a.at(i).as_real(); };  /* a number argument */
        auto str = [&](size_t i) { return a.at(i).as_text(); };  /* a text argument */
        auto arg = [&](size_t i) { return a.items().size() > i ? a.at(i) : Json(); };  /* an optional argument */
        if (op == "init") { setup(str(0), str(1), arg(2), a.items().size() > 3 ? truthy(a.at(3)) : true); return Json(); }  /* set up */
        if (op == "get") { return get(str(0)); }  /* read an attribute */
        if (op == "set") { set(str(0), a.at(1)); return Json(); }  /* set one */
        if (op == "beacon") { beacon(); return Json(); }  /* beacon */
        if (op == "listen") { listen(); return Json(); }  /* listen */
        if (op == "call_station") { call_station(str(0)); return Json(); }  /* call */
        if (op == "beacon_once") { beacon_once(); return Json(); }  /* one beacon round */
        if (op == "call_once") { call_once(str(0)); return Json(); }  /* one call */
        if (op == "long_beacon") { long_beacon(arg(0)); return Json(); }  /* a long beacon */
        if (op == "queue") { queue(str(0), arg(1)); return Json(); }  /* queue */
        if (op == "broadcast") { broadcast(str(0), a.items().size() > 1 ? static_cast<long>(a.at(1).as_int()) : kBroadcastLevel); return Json(); }  /* broadcast */
        if (op == "unqueue") { return Json(unqueue(str(0), arg(1))); }  /* take back */
        if (op == "mail_waiting_at") { return Json(mail_waiting_at(str(0))); }  /* mail waiting? */
        if (op == "end") { close_when_done = true; return Json(); }  /* close when done */
        if (op == "cancel") { return Json(cancel(num(0))); }  /* stop calling */
        if (op == "tuning") { return tuning(num(0)); }  /* where to tune */
        if (op == "handle") { return handle(a.at(0), num(1)); }  /* a frame heard */
        if (op == "poll") { return poll(num(0)); }  /* the clock */
        if (op == "next_wake") { return next_wake(); }  /* next wake */
        if (op == "new_contact") { new_contact(); return Json(); }  /* ready again */
        if (op == "expects_call_from") { return Json(expects_call_from(str(0), num(1))); }  /* expecting a call? */
        if (op == "_ack") {  /* an acknowledgment (tests) */
            std::string kind = str(4);  /* its kind */
            return ack(num(0), static_cast<long>(a.at(1).as_int()), static_cast<long>(a.at(2).as_int()), static_cast<long>(a.at(3).as_int()), kind.c_str(), arg(5), a.items().size() > 6 ? num(6) : 0.0);  /* made */
        }  /* end of _ack */
        throw PyError{"AttributeError", "'Station' object has no attribute '" + op + "'"};  /* unknown */
    }  /* end of serve */
};  /* end of KesStation */

extern "C" {  /* the station's C interface */

KES_API KesStation *kes_station_new(void) {  /* a new station (set it up with "init") */
    return new KesStation();  /* made */
}  /* end of kes_station_new */

KES_API void kes_station_free(KesStation *s) {  /* done with it */
    delete s;  /* freed */
}  /* end of kes_station_free */

KES_API void kes_station_set_mail(KesStation *s, KesMail *mail) {  /* the mail store it uses (owned by the caller) */
    if (s != nullptr) {  /* a station */
        std::lock_guard<std::recursive_mutex> guard(s->lock);  /* one at a time */
        s->mail = mail;  /* used from now on */
    }  /* end of the check */
}  /* end of kes_station_set_mail */

KES_API void kes_station_set_busy(KesStation *s, KesBusy busy, void *ctx) {  /* the listen-before-transmit check, or none */
    if (s != nullptr) {  /* a station */
        std::lock_guard<std::recursive_mutex> guard(s->lock);  /* one at a time */
        s->busy_fn = busy;  /* the check */
        s->busy_ctx = ctx;  /* its context */
    }  /* end of the check */
}  /* end of kes_station_set_busy */

KES_API long kes_station_request(KesStation *s, const char *request) {  /* run one request */
    if (s == nullptr || request == nullptr) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    std::lock_guard<std::recursive_mutex> guard(s->lock);  /* one at a time */
    Json reply = Json::object();  /* the answer */
    s->clear_stored = false;  /* nothing to tell yet */
    try {  /* any step may fail */
        Json req = Json::parse(request);  /* the request */
        const Json *mail_now = req.find("mail_now");  /* the mail clock */
        s->mail_now_json = (mail_now != nullptr && mail_now->is_number()) ? *mail_now : Json(0.0);  /* as given */
        s->mail_now = s->mail_now_json.as_real();  /* as a number */
        const Json *args = req.find("args");  /* the arguments */
        reply["ok"] = s->serve(req.at("op").as_text(), args != nullptr ? *args : Json::list());  /* served */
    } catch (const PyError &e) {  /* an error Python would raise */
        reply = Json::object();  /* start again */
        reply["error"] = e.kind;  /* its name */
        reply["message"] = e.message;  /* its words */
    } catch (const std::exception &e) {  /* a bad request */
        reply = Json::object();  /* start again */
        reply["error"] = "TypeError";  /* a wrong argument */
        reply["message"] = e.what();  /* the reason */
    }  /* end of the request */
    reply["clear_stored"] = s->clear_stored;  /* drop the receiver's kept soft bits? */
    s->reply = reply.dump();  /* kept for collection */
    return static_cast<long>(s->reply.size());  /* its length */
}  /* end of kes_station_request */

KES_API long kes_station_reply(KesStation *s, char *out, size_t cap) {  /* collect the last reply */
    if (s == nullptr || out == nullptr || cap < s->reply.size()) {  /* no room */
        return -1;  /* refuse */
    }  /* end of the check */
    std::memcpy(out, s->reply.data(), s->reply.size());  /* copied */
    return static_cast<long>(s->reply.size());  /* its length */
}  /* end of kes_station_reply */

}  /* end of the station's C interface */
