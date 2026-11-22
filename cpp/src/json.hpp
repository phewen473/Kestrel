/*
 * json.hpp - a small JSON reader and writer for the Kestrel library.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * Enough JSON for the mail file and for the requests and replies that pass
 * between the library and the Python program. Objects keep their keys in the
 * order they were added, as Python dicts do, and whole numbers stay whole
 * numbers, so a file written by either side reads back the same in the other.
 */

#ifndef KESTREL_JSON_HPP  /* guard against being included twice */
#define KESTREL_JSON_HPP  /* mark it included */

#include <charconv>  /* shortest round-trip number text */
#include <cmath>  /* isfinite */
#include <cstdint>  /* fixed-size integers */
#include <cstdio>  /* snprintf */
#include <stdexcept>  /* errors */
#include <string>  /* text */
#include <utility>  /* pair, move */
#include <vector>  /* growable arrays */

namespace kes {  /* the library's C++ names */

/* One JSON value: null, true/false, a whole number, a number with a fraction, text, a list, or an object. */
class Json {  /* a value */
public:  /* what callers use */
    enum class Kind { Null, Bool, Int, Real, Text, List, Object };  /* the seven kinds */

    Json() = default;  /* null */
    Json(std::nullptr_t) {}  /* null, written as nullptr */
    Json(bool b) : kind_(Kind::Bool), int_(b ? 1 : 0) {}  /* true or false */
    Json(int v) : kind_(Kind::Int), int_(v) {}  /* a whole number */
    Json(long v) : kind_(Kind::Int), int_(v) {}  /* a whole number */
    Json(long long v) : kind_(Kind::Int), int_(v) {}  /* a whole number */
    Json(double v) : kind_(Kind::Real), real_(v) {}  /* a number with a fraction (Python float) */
    Json(const char *s) : kind_(Kind::Text), text_(s) {}  /* text */
    Json(std::string s) : kind_(Kind::Text), text_(std::move(s)) {}  /* text */

    static Json list() {  /* an empty list */
        Json j;  /* a value */
        j.kind_ = Kind::List;  /* made a list */
        return j;  /* handed back */
    }  /* end of list */
    static Json object() {  /* an empty object */
        Json j;  /* a value */
        j.kind_ = Kind::Object;  /* made an object */
        return j;  /* handed back */
    }  /* end of object */

    Kind kind() const { return kind_; }  /* which kind */
    bool is_null() const { return kind_ == Kind::Null; }  /* null? */
    bool is_number() const { return kind_ == Kind::Int || kind_ == Kind::Real; }  /* a number? */
    bool is_text() const { return kind_ == Kind::Text; }  /* text? */
    bool is_list() const { return kind_ == Kind::List; }  /* a list? */
    bool is_object() const { return kind_ == Kind::Object; }  /* an object? */

    long long as_int() const {  /* as a whole number (Python int(): a fraction is cut off) */
        if (kind_ == Kind::Int || kind_ == Kind::Bool) {  /* already whole */
            return int_;  /* as it is */
        }  /* end of the whole case */
        if (kind_ == Kind::Real && std::isfinite(real_)) {  /* a fraction */
            return static_cast<long long>(real_);  /* cut towards zero */
        }  /* end of the fraction case */
        throw std::runtime_error("not a number");  /* anything else */
    }  /* end of as_int */
    double as_real() const {  /* as a number with a fraction */
        if (kind_ == Kind::Real) {  /* already */
            return real_;  /* as it is */
        }  /* end of the real case */
        if (kind_ == Kind::Int || kind_ == Kind::Bool) {  /* whole */
            return static_cast<double>(int_);  /* converted */
        }  /* end of the whole case */
        throw std::runtime_error("not a number");  /* anything else */
    }  /* end of as_real */
    bool as_bool() const { return kind_ == Kind::Bool ? int_ != 0 : (is_number() ? as_real() != 0.0 : !is_null()); }  /* truth, roughly as Python sees it */
    const std::string &as_text() const {  /* the text */
        if (kind_ != Kind::Text) {  /* not text */
            throw std::runtime_error("not text");  /* refuse */
        }  /* end of the check */
        return text_;  /* the text */
    }  /* end of as_text */

    std::vector<Json> &items() { return list_; }  /* a list's items */
    const std::vector<Json> &items() const { return list_; }  /* a list's items, read only */
    std::vector<std::pair<std::string, Json>> &members() { return object_; }  /* an object's members, in order */
    const std::vector<std::pair<std::string, Json>> &members() const { return object_; }  /* read only */
    void push(Json v) { list_.push_back(std::move(v)); }  /* add to a list */

    const Json *find(const std::string &key) const {  /* an object's member, or nullptr */
        for (const auto &m : object_) {  /* each member */
            if (m.first == key) {  /* this one */
                return &m.second;  /* found */
            }  /* end of the test */
        }  /* end of the members */
        return nullptr;  /* not there */
    }  /* end of find */
    Json &operator[](const std::string &key) {  /* an object's member, added at the end if new (as a Python dict) */
        for (auto &m : object_) {  /* each member */
            if (m.first == key) {  /* this one */
                return m.second;  /* found: it keeps its place */
            }  /* end of the test */
        }  /* end of the members */
        object_.emplace_back(key, Json());  /* a new member */
        return object_.back().second;  /* handed back */
    }  /* end of operator[] */
    const Json &at(const std::string &key) const {  /* a member that must be there */
        const Json *j = find(key);  /* look */
        if (j == nullptr) {  /* missing */
            throw std::runtime_error("missing " + key);  /* refuse */
        }  /* end of the check */
        return *j;  /* found */
    }  /* end of at */
    const Json &at(size_t i) const {  /* a list item that must be there */
        if (i >= list_.size()) {  /* past the end */
            throw std::runtime_error("too few arguments");  /* refuse */
        }  /* end of the check */
        return list_[i];  /* found */
    }  /* end of at */

    std::string dump() const {  /* the value as compact JSON text */
        std::string out;  /* the text */
        write(out);  /* written */
        return out;  /* handed back */
    }  /* end of dump */

    static Json parse(const std::string &text) {  /* JSON text -> value; throws on bad text */
        size_t at = 0;  /* where reading has got to */
        Json v = read(text, at);  /* the value */
        skip(text, at);  /* trailing spaces */
        if (at != text.size()) {  /* anything else after it */
            throw std::runtime_error("extra text after JSON");  /* refuse */
        }  /* end of the check */
        return v;  /* the value */
    }  /* end of parse */

private:  /* the workings */
    Kind kind_ = Kind::Null;  /* which kind */
    long long int_ = 0;  /* a whole number or a truth value */
    double real_ = 0.0;  /* a number with a fraction */
    std::string text_;  /* text */
    std::vector<Json> list_;  /* a list */
    std::vector<std::pair<std::string, Json>> object_;  /* an object, in order */

    static void escape(std::string &out, unsigned cp) {  /* one code point as \\uXXXX (a surrogate pair above 0xFFFF), as Python's json.dumps */
        char buf[16];  /* room */
        if (cp >= 0x10000) {  /* needs a pair */
            cp -= 0x10000;  /* the part to split */
            std::snprintf(buf, sizeof buf, "\\u%04x\\u%04x", 0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF));  /* both halves */
        } else {  /* one is enough */
            std::snprintf(buf, sizeof buf, "\\u%04x", cp);  /* written as \\uXXXX */
        }  /* end of the choice */
        out += buf;  /* added */
    }  /* end of escape */

    static void write_text(std::string &out, const std::string &s) {  /* text with JSON escapes, all ASCII (as Python's json.dumps) */
        out += '"';  /* opening quote */
        for (size_t i = 0; i < s.size(); ++i) {  /* each byte */
            unsigned char c = static_cast<unsigned char>(s[i]);  /* as a number */
            switch (c) {  /* the special ones */
            case '"': out += "\\\""; break;  /* quote */
            case '\\': out += "\\\\"; break;  /* backslash */
            case '\n': out += "\\n"; break;  /* new line */
            case '\r': out += "\\r"; break;  /* return */
            case '\t': out += "\\t"; break;  /* tab */
            case '\b': out += "\\b"; break;  /* backspace */
            case '\f': out += "\\f"; break;  /* form feed */
            default:  /* everything else */
                if (c < 0x20) {  /* another control character */
                    escape(out, c);  /* escaped */
                } else if (c < 0x80) {  /* plain ASCII (DEL too, as Python) */
                    out += static_cast<char>(c);  /* as it is */
                } else {  /* the start of a UTF-8 sequence */
                    int more = c >= 0xF0 ? 3 : (c >= 0xE0 ? 2 : (c >= 0xC0 ? 1 : 0));  /* bytes that follow */
                    unsigned cp = more == 3 ? (c & 0x07u) : (more == 2 ? (c & 0x0Fu) : (more == 1 ? (c & 0x1Fu) : 0xFFFDu));  /* its first bits (a stray byte becomes the replacement character) */
                    for (int k = 0; k < more && i + 1 < s.size(); ++k) {  /* the rest of the sequence */
                        cp = (cp << 6) | (static_cast<unsigned char>(s[++i]) & 0x3Fu);  /* added */
                    }  /* end of the sequence */
                    escape(out, cp);  /* escaped */
                }  /* end of the choice */
            }  /* end of the special ones */
        }  /* end of the bytes */
        out += '"';  /* closing quote */
    }  /* end of write_text */

    void write(std::string &out) const {  /* compact JSON */
        switch (kind_) {  /* by kind */
        case Kind::Null: out += "null"; break;  /* null */
        case Kind::Bool: out += int_ ? "true" : "false"; break;  /* truth */
        case Kind::Int: out += std::to_string(int_); break;  /* a whole number */
        case Kind::Real: {  /* a number with a fraction */
            if (!std::isfinite(real_)) {  /* infinity or not-a-number */
                out += std::isnan(real_) ? "NaN" : (real_ > 0 ? "Infinity" : "-Infinity");  /* as Python writes them */
                break;  /* done */
            }  /* end of the special case */
            char buf[32];  /* room */
            auto res = std::to_chars(buf, buf + sizeof buf, real_);  /* the shortest text that reads back exactly (as Python's repr) */
            std::string s(buf, res.ptr);  /* as text */
            if (s.find_first_of(".eEn") == std::string::npos) {  /* it looks whole */
                s += ".0";  /* keep it a fraction, as Python writes 1.0 */
            }  /* end of the fix */
            out += s;  /* added */
            break;  /* done */
        }  /* end of the real case */
        case Kind::Text: write_text(out, text_); break;  /* text */
        case Kind::List:  /* a list */
            out += '[';  /* opening */
            for (size_t i = 0; i < list_.size(); ++i) {  /* each item */
                if (i) {  /* not the first */
                    out += ", ";  /* separator */
                }  /* end of the separator */
                list_[i].write(out);  /* the item */
            }  /* end of the items */
            out += ']';  /* closing */
            break;  /* done */
        case Kind::Object:  /* an object */
            out += '{';  /* opening */
            for (size_t i = 0; i < object_.size(); ++i) {  /* each member */
                if (i) {  /* not the first */
                    out += ", ";  /* separator */
                }  /* end of the separator */
                write_text(out, object_[i].first);  /* the key */
                out += ": ";  /* then */
                object_[i].second.write(out);  /* the value */
            }  /* end of the members */
            out += '}';  /* closing */
            break;  /* done */
        }  /* end of the kinds */
    }  /* end of write */

    static void skip(const std::string &t, size_t &at) {  /* pass over white space */
        while (at < t.size() && (t[at] == ' ' || t[at] == '\n' || t[at] == '\r' || t[at] == '\t')) {  /* JSON white space */
            ++at;  /* skipped */
        }  /* end of the spaces */
    }  /* end of skip */

    static bool word(const std::string &t, size_t &at, const char *w) {  /* is the literal `w` next? */
        size_t n = std::char_traits<char>::length(w);  /* its length */
        if (t.compare(at, n, w) == 0) {  /* it is */
            at += n;  /* passed */
            return true;  /* yes */
        }  /* end of the test */
        return false;  /* no */
    }  /* end of word */

    static unsigned hex4(const std::string &t, size_t at) {  /* four hex digits */
        if (at + 4 > t.size()) {  /* too short */
            throw std::runtime_error("bad \\u escape");  /* refuse */
        }  /* end of the check */
        unsigned v = 0;  /* the number */
        for (size_t i = at; i < at + 4; ++i) {  /* each digit */
            char c = t[i];  /* the digit */
            v <<= 4;  /* shift */
            if (c >= '0' && c <= '9') { v |= static_cast<unsigned>(c - '0'); }  /* 0-9 */
            else if (c >= 'a' && c <= 'f') { v |= static_cast<unsigned>(c - 'a' + 10); }  /* a-f */
            else if (c >= 'A' && c <= 'F') { v |= static_cast<unsigned>(c - 'A' + 10); }  /* A-F */
            else { throw std::runtime_error("bad \\u escape"); }  /* anything else */
        }  /* end of the digits */
        return v;  /* the number */
    }  /* end of hex4 */

    static void utf8(std::string &out, unsigned cp) {  /* a code point as UTF-8 */
        if (cp < 0x80) { out += static_cast<char>(cp); }  /* one byte */
        else if (cp < 0x800) { out += static_cast<char>(0xC0 | (cp >> 6)); out += static_cast<char>(0x80 | (cp & 0x3F)); }  /* two */
        else if (cp < 0x10000) { out += static_cast<char>(0xE0 | (cp >> 12)); out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F)); out += static_cast<char>(0x80 | (cp & 0x3F)); }  /* three */
        else { out += static_cast<char>(0xF0 | (cp >> 18)); out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F)); out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F)); out += static_cast<char>(0x80 | (cp & 0x3F)); }  /* four */
    }  /* end of utf8 */

    static std::string read_text(const std::string &t, size_t &at) {  /* a quoted string; `at` is on the opening quote */
        std::string s;  /* the text */
        ++at;  /* past the quote */
        while (true) {  /* each character */
            if (at >= t.size()) {  /* ran out */
                throw std::runtime_error("unfinished text");  /* refuse */
            }  /* end of the check */
            char c = t[at++];  /* the character */
            if (c == '"') {  /* the closing quote */
                return s;  /* done */
            }  /* end of the test */
            if (c != '\\') {  /* an ordinary character */
                s += c;  /* kept */
                continue;  /* next */
            }  /* end of the ordinary case */
            if (at >= t.size()) {  /* an escape at the very end */
                throw std::runtime_error("unfinished escape");  /* refuse */
            }  /* end of the check */
            char e = t[at++];  /* the escape letter */
            switch (e) {  /* which escape */
            case '"': s += '"'; break;  /* quote */
            case '\\': s += '\\'; break;  /* backslash */
            case '/': s += '/'; break;  /* slash */
            case 'b': s += '\b'; break;  /* backspace */
            case 'f': s += '\f'; break;  /* form feed */
            case 'n': s += '\n'; break;  /* new line */
            case 'r': s += '\r'; break;  /* return */
            case 't': s += '\t'; break;  /* tab */
            case 'u': {  /* a code point */
                unsigned cp = hex4(t, at);  /* its number */
                at += 4;  /* past it */
                if (cp >= 0xD800 && cp < 0xDC00 && at + 6 <= t.size() && t[at] == '\\' && t[at + 1] == 'u') {  /* the first half of a pair */
                    unsigned low = hex4(t, at + 2);  /* the second half */
                    if (low >= 0xDC00 && low < 0xE000) {  /* it is one */
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);  /* together */
                        at += 6;  /* past it */
                    }  /* end of the pair */
                }  /* end of the pair test */
                utf8(s, cp);  /* as UTF-8 */
                break;  /* done */
            }  /* end of the code point */
            default:  /* anything else */
                throw std::runtime_error("bad escape");  /* refuse */
            }  /* end of the escapes */
        }  /* end of the characters */
    }  /* end of read_text */

    static Json read(const std::string &t, size_t &at) {  /* one value */
        skip(t, at);  /* leading spaces */
        if (at >= t.size()) {  /* nothing there */
            throw std::runtime_error("JSON ended early");  /* refuse */
        }  /* end of the check */
        char c = t[at];  /* what comes next */
        if (c == '{') {  /* an object */
            Json o = object();  /* empty */
            ++at;  /* past the brace */
            skip(t, at);  /* spaces */
            if (at < t.size() && t[at] == '}') {  /* empty */
                ++at;  /* past it */
                return o;  /* done */
            }  /* end of the empty case */
            while (true) {  /* each member */
                skip(t, at);  /* spaces */
                if (at >= t.size() || t[at] != '"') {  /* a key must be text */
                    throw std::runtime_error("expected a key");  /* refuse */
                }  /* end of the check */
                std::string k = read_text(t, at);  /* the key */
                skip(t, at);  /* spaces */
                if (at >= t.size() || t[at] != ':') {  /* the colon */
                    throw std::runtime_error("expected ':'");  /* refuse */
                }  /* end of the check */
                ++at;  /* past it */
                o[k] = read(t, at);  /* the value (a repeated key keeps its first place and its last value, as Python) */
                skip(t, at);  /* spaces */
                if (at < t.size() && t[at] == ',') {  /* another member */
                    ++at;  /* past the comma */
                    continue;  /* next */
                }  /* end of the comma */
                if (at < t.size() && t[at] == '}') {  /* the end */
                    ++at;  /* past it */
                    return o;  /* done */
                }  /* end of the end */
                throw std::runtime_error("expected ',' or '}'");  /* anything else */
            }  /* end of the members */
        }  /* end of the object */
        if (c == '[') {  /* a list */
            Json l = list();  /* empty */
            ++at;  /* past the bracket */
            skip(t, at);  /* spaces */
            if (at < t.size() && t[at] == ']') {  /* empty */
                ++at;  /* past it */
                return l;  /* done */
            }  /* end of the empty case */
            while (true) {  /* each item */
                l.push(read(t, at));  /* the item */
                skip(t, at);  /* spaces */
                if (at < t.size() && t[at] == ',') {  /* another item */
                    ++at;  /* past the comma */
                    continue;  /* next */
                }  /* end of the comma */
                if (at < t.size() && t[at] == ']') {  /* the end */
                    ++at;  /* past it */
                    return l;  /* done */
                }  /* end of the end */
                throw std::runtime_error("expected ',' or ']'");  /* anything else */
            }  /* end of the items */
        }  /* end of the list */
        if (c == '"') {  /* text */
            return Json(read_text(t, at));  /* the text */
        }  /* end of text */
        if (word(t, at, "null")) { return Json(); }  /* null */
        if (word(t, at, "true")) { return Json(true); }  /* true */
        if (word(t, at, "false")) { return Json(false); }  /* false */
        if (word(t, at, "NaN")) { return Json(std::nan("")); }  /* Python's not-a-number */
        if (word(t, at, "Infinity")) { return Json(HUGE_VAL); }  /* Python's infinity */
        if (word(t, at, "-Infinity")) { return Json(-HUGE_VAL); }  /* and its negative */
        size_t start = at;  /* a number */
        bool real = false;  /* has it a fraction or an exponent? */
        if (at < t.size() && t[at] == '-') { ++at; }  /* a sign */
        while (at < t.size() && ((t[at] >= '0' && t[at] <= '9') || t[at] == '.' || t[at] == 'e' || t[at] == 'E' || t[at] == '+' || t[at] == '-')) {  /* its characters */
            real = real || t[at] == '.' || t[at] == 'e' || t[at] == 'E';  /* a fraction or exponent */
            ++at;  /* next */
        }  /* end of the characters */
        std::string n = t.substr(start, at - start);  /* the number's text */
        if (n.empty() || n == "-") {  /* nothing that is a number */
            throw std::runtime_error("bad JSON value");  /* refuse */
        }  /* end of the check */
        if (!real) {  /* a whole number */
            long long v = 0;  /* its value */
            auto res = std::from_chars(n.data(), n.data() + n.size(), v);  /* read */
            if (res.ec == std::errc() && res.ptr == n.data() + n.size()) {  /* it fits */
                return Json(v);  /* whole */
            }  /* end of the fit */
        }  /* end of the whole case */
        double d = 0.0;  /* as a fraction (also a whole number too large for 64 bits) */
        auto res = std::from_chars(n.data(), n.data() + n.size(), d);  /* read, whatever the computer's language settings */
        if (res.ec != std::errc() || res.ptr != n.data() + n.size()) {  /* not all of it was a number */
            throw std::runtime_error("bad number");  /* refuse */
        }  /* end of the check */
        return Json(d);  /* the number */
    }  /* end of read */
};  /* end of Json */

}  /* end of namespace kes */

#endif  /* KESTREL_JSON_HPP */
