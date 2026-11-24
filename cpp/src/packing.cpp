/*
 * packing.cpp - the Kestrel modem library: packing and unpacking the bits a frame carries.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * Text (plain or compressed), callsigns, grid locators, channel reports,
 * the frame header, the message address block, the control frames' fields
 * and the check values, each following its Python reference (named beside
 * it in kestrel.h) bit for bit.
 *
 * A function here refuses (returns -1) wherever the Python reference would
 * raise an error, and also for any text outside 7-bit ASCII, so that the
 * Python caller can run its own code and raise its own, worded, error.
 */

#define KESTREL_BUILDING 1  /* this file builds the library, so its functions are exported */
#include "kestrel.h"  /* the interface being implemented */

#include <algorithm>  /* sort, min, max */
#include <cmath>  /* nearbyint, isnan, isinf, isfinite */
#include <cstring>  /* memset, strlen */
#include <string>  /* text being worked on */
#include <utility>  /* pair */
#include <vector>  /* growable arrays */

namespace {  /* helpers seen only inside this file */

const char kAlphabet[] = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-";  /* address symbols 0 to 38 (modem/address.py ALPHABET) */
const int kBase = 40;  /* symbol values the address coding allows for (BASE) */
const int kCallChars = 9;  /* longest address (params.py CALL_CHARS) */
const int kCallBits = 48;  /* bits per address (CALL_BITS) */
const int kLinkBits = 9;  /* link number (LINK_ID_BITS) */
const int kMsgBits = 16;  /* message number (MSG_ID_BITS) */
const int kHopBits = 3;  /* relay counter (HOP_BITS) */
const int kLifeBits = 5;  /* lifetime (LIFE_BITS) */
const int kLifeUnit = 2;  /* hours per lifetime step (LIFE_UNIT_HOURS) */
const int kLevelBits = 3;  /* a level number (LEVEL_BITS) */
const int kMaskBits = 8;  /* the list of levels (LEVEL_MASK_BITS) */
const int kGridBits = 15;  /* a grid locator (GRID_BITS) */
const int kPartBits = 3;  /* a part number (PART_BITS) */
const int kStatusBits = 2;  /* an acknowledgment's verdict (ACK_STATUS_BITS) */
const int kSnrBits = 6;  /* report SNR (SNR_BITS) */
const int kSnrFloor = -30;  /* the SNR sent as 0 (SNR_FLOOR_DB) */
const int kFadeBits = 3;  /* report fading index (FADE_BITS) */
const int kFadeSteps = 4;  /* fading index sent in quarters (FADE_STEPS_PER_UNIT) */
const int kOffsetBits = 6;  /* report offset (OFFSET_BITS) */
const int kOffsetStep = 2;  /* offset sent in 2 Hz steps (OFFSET_STEP_HZ) */
const int kReportBits = kSnrBits + kFadeBits + kOffsetBits + kLevelBits;  /* a whole report: 18 bits (REPORT_BITS) */
const int kHashBits = 16;  /* a mail notice code (HASH_BITS) */
const int kSlots = 3;  /* entries per mail notice list (NOTICE_SLOTS) */
const int kCharBits = 7;  /* bits per plain character (CHAR_BITS) */
const int kLengthBits = 8;  /* the character count (LENGTH_BITS) */
const size_t kMaxChars = 200;  /* longest message (MAX_CHARS) */
const int kSizes[4] = {50, 100, 150, 200};  /* the four size classes, in plain characters (SIZE_CLASSES) */
const int kAddressBits[2] = {kLinkBits + kLevelBits + kMsgBits, 2 * kCallBits + kMsgBits + kHopBits + kLifeBits};  /* address block of a link frame (28) and an addressed frame (120) (ADDRESS_BITS) */
const int kControlBits[8] = {0, 0, kCallBits + kGridBits + kMaskBits + 4, 2 * kCallBits + kGridBits + kReportBits + kMaskBits + 2,  /* beacon 75, answer 139 (with its sender's locator since 0.33) (CONTROL_BITS)... */
                             kLinkBits + kMsgBits + kPartBits + kStatusBits + kReportBits, kCallBits + kLinkBits + 4, 0, kCallBits + 3 * kSlots * kHashBits};  /* ...ack 48, ident 61, notice 192 (types 0, 1 and 6 have none) */
const char kFields[] = "ABCDEFGHIJKLMNOPQR";  /* grid locator field letters (control.py FIELDS) */
const unsigned long long kNoGrid = (1ULL << kGridBits) - 1;  /* an answer's "no locator set" (NO_GRID: all ones; real locators run 0 to 32399) */

/* Python's str.strip() whitespace, for the ASCII range: tab to carriage return, the four separators 0x1c-0x1f, and space. */
bool is_space(unsigned char c) {  /* one character */
    return (c >= 9 && c <= 13) || (c >= 0x1c && c <= 0x1f) || c == ' ';  /* the same set Python strips */
}  /* end of is_space */

/* Strip and upper-case `in` like Python's s.strip().upper(); false for anything outside 7-bit ASCII (Python decides those). */
bool strip_upper(const char *in, std::string &out) {  /* the tidied text */
    if (in == nullptr) {  /* no text at all */
        return false;  /* refuse */
    }  /* end of the check */
    std::string s(in);  /* a copy */
    for (char &c : s) {  /* each character */
        unsigned char u = static_cast<unsigned char>(c);  /* as a number */
        if (u > 127) {  /* outside ASCII */
            return false;  /* let Python decide */
        }  /* end of the check */
        if (u >= 'a' && u <= 'z') {  /* a small letter */
            c = static_cast<char>(u - 'a' + 'A');  /* made a capital */
        }  /* end of the change */
    }  /* end of the characters */
    size_t first = 0;  /* the first character kept */
    while (first < s.size() && is_space(static_cast<unsigned char>(s[first]))) {  /* leading spaces */
        ++first;  /* skipped */
    }  /* end of the leading spaces */
    size_t last = s.size();  /* one past the last character kept */
    while (last > first && is_space(static_cast<unsigned char>(s[last - 1]))) {  /* trailing spaces */
        --last;  /* dropped */
    }  /* end of the trailing spaces */
    out = s.substr(first, last - first);  /* what is left */
    return true;  /* done */
}  /* end of strip_upper */

/* modem/address.py clean_call: capitals, no padding, 1 to 9 characters from the alphabet, no space inside. */
bool clean_call(const char *call, std::string &out) {  /* the tidied address */
    if (!strip_upper(call, out) || out.empty() || out.size() > static_cast<size_t>(kCallChars)) {  /* not ASCII, empty or too long */
        return false;  /* refuse */
    }  /* end of the check */
    for (char c : out) {  /* each character */
        if (c == ' ' || c == '\0' || std::strchr(kAlphabet, c) == nullptr) {  /* a space inside, or outside the alphabet */
            return false;  /* refuse */
        }  /* end of the test */
    }  /* end of the characters */
    return true;  /* a valid address */
}  /* end of clean_call */

/* bits.py int_to_bits: the lowest `width` bits of `value`, most significant first, appended to `v`. */
void put(std::vector<uint8_t> &v, unsigned long long value, int width) {  /* one field */
    for (int i = 0; i < width; ++i) {  /* from the top down */
        v.push_back(static_cast<uint8_t>((value >> (width - 1 - i)) & 1ULL));  /* one bit */
    }  /* end of the bits */
}  /* end of put */

/* bits.py bits_to_int: the number spelled by `width` bits starting at b, most significant first. */
unsigned long long get(const uint8_t *b, int width) {  /* one field */
    unsigned long long value = 0;  /* running total */
    for (int i = 0; i < width; ++i) {  /* from the top down */
        value = (value << 1) | b[i];  /* shift and add the next bit */
    }  /* end of the bits */
    return value;  /* the number */
}  /* end of get */

/* crc.py crc_bits: a CRC of `width` bits, fed one bit at a time. */
int crc(const uint8_t *bits, size_t n, int poly, int width, int init) {  /* the check value as a number */
    int mask = (1 << width) - 1;  /* keeps the register to `width` bits */
    int reg = init;  /* the preset value */
    for (size_t i = 0; i < n; ++i) {  /* each bit */
        int top = (reg >> (width - 1)) & 1;  /* the bit about to fall off the top */
        reg = (reg << 1) & mask;  /* shift left */
        if ((top ^ bits[i]) != 0) {  /* top bit and data bit differ */
            reg ^= poly;  /* mix in the polynomial */
        }  /* end of the test */
    }  /* end of the bits */
    return reg;  /* the register */
}  /* end of crc */

/* address.py call_to_bits, after clean_call: 9 characters padded with spaces, base 40, as 48 bits. */
void call_bits(const std::string &call, std::vector<uint8_t> &v) {  /* appended to v */
    unsigned long long value = 0;  /* running total */
    for (int i = 0; i < kCallChars; ++i) {  /* nine characters, the first carrying the most weight */
        char c = i < static_cast<int>(call.size()) ? call[static_cast<size_t>(i)] : ' ';  /* the character, or padding */
        value = value * kBase + static_cast<unsigned long long>(std::strchr(kAlphabet, c) - kAlphabet);  /* shift and add its symbol */
    }  /* end of the characters */
    put(v, value, kCallBits);  /* as 48 bits */
}  /* end of call_bits */

/* address.py bits_to_call: false when the 48 bits are not a valid address. */
bool bits_call(const uint8_t *b, std::string &out) {  /* the address */
    unsigned long long value = get(b, kCallBits);  /* one number */
    char text[kCallChars + 1] = {0};  /* the characters */
    for (int i = kCallChars - 1; i >= 0; --i) {  /* the lowest symbol is the last character */
        int symbol = static_cast<int>(value % kBase);  /* this symbol */
        value /= kBase;  /* what is left */
        if (symbol >= static_cast<int>(sizeof(kAlphabet)) - 1) {  /* the unused symbol value */
            return false;  /* not an address */
        }  /* end of the test */
        text[i] = kAlphabet[symbol];  /* its character */
    }  /* end of the symbols */
    return value == 0 && clean_call(text, out);  /* nothing left over, and a valid address once the padding is gone */
}  /* end of bits_call */

/* The canonical compression codes (compress.py _build_codes): code of each character, sorted by (length, character). */
struct Codes {  /* both tables */
    int code[128];  /* each character's code */
    std::vector<std::pair<int, int>> by_length_code;  /* (length * 65536 + code, character), for decoding */
    Codes() {  /* built once */
        std::vector<std::pair<int, int>> order;  /* (length, character) */
        for (int s = 0; s < 128; ++s) {  /* every character */
            order.emplace_back(kes_compress_length(s), s);  /* its length */
        }  /* end of the characters */
        std::sort(order.begin(), order.end());  /* shortest first, then by character number */
        int next = 0;  /* the next code */
        int last_len = 0;  /* the previous length */
        for (const auto &entry : order) {  /* in that order */
            next <<= entry.first - last_len;  /* shift when the length grows */
            code[entry.second] = next;  /* this character's code */
            by_length_code.emplace_back(entry.first * 65536 + next, entry.second);  /* remembered for decoding */
            ++next;  /* the next character's code */
            last_len = entry.first;  /* this length */
        }  /* end of the characters */
        std::sort(by_length_code.begin(), by_length_code.end());  /* sorted for searching */
    }  /* end of the constructor */
    int find(int length, int value) const {  /* the character with this code, or -1 */
        auto it = std::lower_bound(by_length_code.begin(), by_length_code.end(), std::make_pair(length * 65536 + value, -1));  /* where it would be */
        return (it != by_length_code.end() && it->first == length * 65536 + value) ? it->second : -1;  /* found or not */
    }  /* end of find */
};  /* end of Codes */

const Codes &codes() {  /* the tables, built on first use */
    static const Codes table;  /* once */
    return table;  /* shared */
}  /* end of codes */

/* text.py _check: at most 200 characters, all 7-bit ASCII. */
bool text_ok(const char *text, size_t len) {  /* can it be sent? */
    if (len > kMaxChars) {  /* too long */
        return false;  /* refuse */
    }  /* end of the check */
    for (size_t i = 0; i < len; ++i) {  /* each character */
        if (static_cast<unsigned char>(text[i]) > 127) {  /* outside 7-bit ASCII */
            return false;  /* refuse */
        }  /* end of the test */
    }  /* end of the characters */
    return true;  /* fine */
}  /* end of text_ok */

/* text.py capacity_bits: text bits a frame of this size class and type holds (-1 for a type with no text). */
int capacity(int size_class, int frame_type) {  /* text room */
    if (size_class < 0 || size_class > 3 || frame_type < 0 || frame_type > 1) {  /* not a message size or type */
        return -1;  /* refuse */
    }  /* end of the check */
    return kCharBits * kSizes[size_class] - (kAddressBits[frame_type] - kAddressBits[0]);  /* less the extra address bits */
}  /* end of capacity */

/* text.py _class_for: the smallest size class holding nbits, or -1. */
int class_for(long nbits, int frame_type) {  /* the class */
    for (int c = 0; c < 4; ++c) {  /* smallest first */
        if (nbits <= capacity(c, frame_type)) {  /* it fits */
            return c;  /* this one */
        }  /* end of the test */
    }  /* end of the classes */
    return -1;  /* too big */
}  /* end of class_for */

/* control.py pack_report: the 18 bits of a channel report; false where Python would raise. */
bool report_bits(double snr_db, double fade_index, double offset_hz, int want_level, std::vector<uint8_t> &v) {  /* appended to v */
    if (!std::isfinite(snr_db) || !std::isfinite(offset_hz) || std::isinf(fade_index) || want_level < 0 || want_level >= (1 << kLevelBits)) {  /* round() would fail, or the level does not fit */
        return false;  /* refuse */
    }  /* end of the check */
    double snr = std::nearbyint(snr_db) - kSnrFloor;  /* whole dB above -30 (round half to even, as Python's round) */
    snr = std::min(std::max(snr, 0.0), static_cast<double>((1 << kSnrBits) - 1));  /* held to 0..63 */
    double fade = std::isnan(fade_index) ? static_cast<double>(1 << kFadeBits) : fade_index;  /* a missing reading is sent as "fading" */
    fade = std::min(std::max(std::nearbyint(fade * kFadeSteps), 0.0), static_cast<double>((1 << kFadeBits) - 1));  /* quarters, held to 0..7 */
    double limit = static_cast<double>((1 << (kOffsetBits - 1)) - 1);  /* 31 */
    double offset = std::min(std::max(std::nearbyint(offset_hz / kOffsetStep), -limit - 1.0), limit);  /* 2 Hz steps, held to -32..31 */
    put(v, static_cast<unsigned long long>(snr), kSnrBits);  /* SNR */
    put(v, static_cast<unsigned long long>(fade), kFadeBits);  /* fading */
    put(v, static_cast<unsigned long long>(static_cast<long long>(offset)) & ((1ULL << kOffsetBits) - 1), kOffsetBits);  /* offset, two's complement */
    put(v, static_cast<unsigned long long>(want_level), kLevelBits);  /* the level asked for */
    return true;  /* done */
}  /* end of report_bits */

/* control.py unpack_report: the report carried by 18 bits, into f. */
void read_report(const uint8_t *b, KesFields *f) {  /* the four readings */
    f->snr_db = static_cast<double>(get(b, kSnrBits)) + kSnrFloor;  /* back to dB */
    f->fade_index = static_cast<double>(get(b + kSnrBits, kFadeBits)) / kFadeSteps;  /* back to an index */
    long raw = static_cast<long>(get(b + kSnrBits + kFadeBits, kOffsetBits));  /* the offset, unsigned */
    if (raw >= (1L << (kOffsetBits - 1))) {  /* the top bit is set */
        raw -= 1L << kOffsetBits;  /* negative */
    }  /* end of the sign */
    f->offset_hz = static_cast<double>(raw * kOffsetStep);  /* back to hertz */
    f->want_level = static_cast<int>(get(b + kReportBits - kLevelBits, kLevelBits));  /* the level asked for */
}  /* end of read_report */

/* control.py grid_to_bits: false unless two letters A to R and two digits. */
bool grid_bits(const char *grid, std::vector<uint8_t> &v) {  /* appended to v */
    std::string g;  /* the tidied locator */
    if (!strip_upper(grid, g) || g.size() != 4) {  /* not ASCII, or the wrong length */
        return false;  /* refuse */
    }  /* end of the check */
    const char *a = g[0] != '\0' ? std::strchr(kFields, g[0]) : nullptr;  /* the first letter's place */
    const char *b = g[1] != '\0' ? std::strchr(kFields, g[1]) : nullptr;  /* the second's */
    if (a == nullptr || b == nullptr || g[2] < '0' || g[2] > '9' || g[3] < '0' || g[3] > '9') {  /* not a locator */
        return false;  /* refuse */
    }  /* end of the check */
    long value = (((a - kFields) * 18 + (b - kFields)) * 10 + (g[2] - '0')) * 10 + (g[3] - '0');  /* one number, 0 to 32399 */
    put(v, static_cast<unsigned long long>(value), kGridBits);  /* as 15 bits */
    return true;  /* done */
}  /* end of grid_bits */

/* control.py bits_to_grid: false when the 15 bits are not a locator. */
bool bits_grid(const uint8_t *b, char *out) {  /* four characters and an end mark */
    unsigned long long value = get(b, kGridBits);  /* one number */
    if (value >= 18 * 18 * 100) {  /* larger than any locator */
        return false;  /* refuse */
    }  /* end of the check */
    unsigned long long pair = value / 100;  /* the two letters */
    unsigned long long digits = value % 100;  /* and the two digits */
    out[0] = kFields[pair / 18];  /* first letter */
    out[1] = kFields[pair % 18];  /* second */
    out[2] = static_cast<char>('0' + digits / 10);  /* first digit */
    out[3] = static_cast<char>('0' + digits % 10);  /* second */
    out[4] = '\0';  /* end */
    return true;  /* done */
}  /* end of bits_grid */

/* Copy an address into a fixed field of KesFields. */
void copy_call(const std::string &call, char *out) {  /* at most 9 characters and an end mark */
    std::memset(out, 0, kCallChars + 1);  /* cleared */
    call.copy(out, kCallChars);  /* the characters */
}  /* end of copy_call */

}  /* end of the private helpers */

extern "C" {  /* the exported packing functions */

KES_API int kes_compress_length(int character) {  /* compress.py LENGTHS */
    static const unsigned char lengths[128] = {  /* code length in bits for character numbers 0 to 127 */
        13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 8, 13, 13, 13, 13, 13,  /* 0-15: control characters (10 = new line) */
        13, 13, 13, 13, 13, 13, 13, 13, 13, 12, 12, 12, 12, 12, 12, 12,  /* 16-31: control characters */
        3, 9, 11, 11, 11, 11, 11, 9, 11, 11, 11, 11, 8, 9, 7, 8,  /* 32-47: space ! " # $ % & ' ( ) * + , - . / */
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 9, 11, 11, 11, 11, 8,  /* 48-63: digits 0-9 : ; < = > ? */
        11, 6, 8, 7, 7, 6, 7, 7, 6, 6, 8, 8, 7, 7, 6, 6,  /* 64-79: @ A-O */
        7, 8, 7, 6, 6, 7, 8, 7, 8, 7, 8, 11, 11, 11, 11, 11,  /* 80-95: P-Z [ \ ] ^ _ */
        11, 5, 7, 6, 5, 4, 6, 7, 5, 5, 10, 8, 6, 6, 5, 5,  /* 96-111: ` a-o */
        7, 11, 5, 5, 4, 6, 8, 6, 10, 7, 11, 11, 11, 11, 11, 12,  /* 112-127: p-z { | } ~ DEL */
    };  /* end of the table */
    return (character >= 0 && character < 128) ? lengths[character] : -1;  /* its length, or -1 outside ASCII */
}  /* end of kes_compress_length */

KES_API int kes_crc16(const uint8_t *bits, size_t n) {  /* crc.py crc16 */
    return crc(bits, n, 0x1021, 16, 0xFFFF);  /* CRC-16/CCITT-FALSE */
}  /* end of kes_crc16 */

KES_API int kes_crc8(const uint8_t *bits, size_t n) {  /* crc.py crc8 */
    return crc(bits, n, 0x07, 8, 0x00);  /* CRC-8 */
}  /* end of kes_crc8 */

KES_API int kes_call_to_bits(const char *call, uint8_t *out) {  /* address.py call_to_bits */
    std::string tidy;  /* the cleaned address */
    if (!clean_call(call, tidy)) {  /* not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* the bits */
    call_bits(tidy, v);  /* made */
    std::copy(v.begin(), v.end(), out);  /* handed back */
    return 0;  /* done */
}  /* end of kes_call_to_bits */

KES_API int kes_bits_to_call(const uint8_t *bits, char *out) {  /* address.py bits_to_call */
    std::string call;  /* the address */
    if (!bits_call(bits, call)) {  /* not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    copy_call(call, out);  /* handed back */
    return 0;  /* done */
}  /* end of kes_bits_to_call */

KES_API long kes_call_hash(const char *call) {  /* address.py call_hash */
    std::string tidy;  /* the cleaned address */
    if (!clean_call(call, tidy)) {  /* not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* its bits */
    call_bits(tidy, v);  /* made */
    int h = kes_crc16(v.data(), v.size());  /* their check value */
    return h != 0 ? h : 1;  /* never 0, which marks an empty entry */
}  /* end of kes_call_hash */

KES_API long kes_message_hash(const char *origin, long msg_id) {  /* address.py message_hash */
    std::string tidy;  /* the cleaned address */
    if (!clean_call(origin, tidy)) {  /* not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* the origin's bits and the number's */
    call_bits(tidy, v);  /* the origin */
    put(v, static_cast<unsigned long long>(msg_id), 16);  /* the number's lowest 16 bits */
    int h = kes_crc16(v.data(), v.size());  /* their check value */
    return h != 0 ? h : 1;  /* never 0 */
}  /* end of kes_message_hash */

KES_API long kes_link_id(const char *first, const char *second) {  /* address.py link_id */
    std::string a;  /* the first address */
    std::string b;  /* the second */
    if (!clean_call(first, a) || !clean_call(second, b)) {  /* either is not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* both addresses' bits */
    call_bits(a, v);  /* the first */
    call_bits(b, v);  /* the second */
    return kes_crc16(v.data(), v.size()) & ((1 << kLinkBits) - 1);  /* the lowest 9 bits of their check value */
}  /* end of kes_link_id */

KES_API long kes_compressed_bits(const char *text, size_t len) {  /* compress.py compressed_bits */
    long total = 0;  /* running total */
    for (size_t i = 0; i < len; ++i) {  /* each character */
        int length = kes_compress_length(static_cast<unsigned char>(text[i]));  /* its code length */
        if (length < 0) {  /* outside ASCII */
            return -1;  /* refuse */
        }  /* end of the check */
        total += length;  /* added */
    }  /* end of the characters */
    return total;  /* the bits needed */
}  /* end of kes_compressed_bits */

KES_API int kes_choose_packing(const char *text, size_t len, int frame_type, int *size_class, int *compressed) {  /* text.py choose_packing */
    if (!text_ok(text, len) || frame_type < 0 || frame_type > 1) {  /* text that cannot be sent, or not a message type */
        return -1;  /* refuse */
    }  /* end of the check */
    int plain = class_for(static_cast<long>(kCharBits * len), frame_type);  /* class without compression */
    int small = class_for(kes_compressed_bits(text, len), frame_type);  /* class with compression */
    if (small >= 0 && (plain < 0 || small < plain)) {  /* compression gets it into a smaller frame, or into one at all */
        *size_class = small;  /* that class */
        *compressed = 1;  /* compressed */
        return 0;  /* done */
    }  /* end of the compressed case */
    if (plain < 0) {  /* too big either way */
        return -1;  /* refuse: the message must be split */
    }  /* end of the check */
    *size_class = plain;  /* the plain class */
    *compressed = 0;  /* not compressed */
    return 0;  /* done */
}  /* end of kes_choose_packing */

KES_API long kes_text_to_bits(const char *text, size_t len, int size_class, int compressed, int frame_type, uint8_t *out) {  /* text.py text_to_bits */
    int room = capacity(size_class, frame_type);  /* text bits the frame holds */
    if (!text_ok(text, len) || room < 0) {  /* text that cannot be sent, or a size or type with no text */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* the bits */
    put(v, len, kLengthBits);  /* the character count */
    for (size_t i = 0; i < len; ++i) {  /* each character */
        int c = static_cast<unsigned char>(text[i]);  /* its number */
        if (compressed) {  /* compressed form */
            put(v, static_cast<unsigned long long>(codes().code[c]), kes_compress_length(c));  /* its code */
        } else {  /* plain form */
            put(v, static_cast<unsigned long long>(c), kCharBits);  /* seven bits */
        }  /* end of the forms */
    }  /* end of the characters */
    if (v.size() > static_cast<size_t>(kLengthBits + room)) {  /* the text does not fit the chosen class */
        return -1;  /* refuse */
    }  /* end of the check */
    v.resize(static_cast<size_t>(kLengthBits + room), 0);  /* zero padding */
    std::copy(v.begin(), v.end(), out);  /* handed back */
    return static_cast<long>(v.size());  /* bits written */
}  /* end of kes_text_to_bits */

KES_API long kes_bits_to_text(const uint8_t *bits, size_t n, int compressed, char *out, size_t cap) {  /* text.py bits_to_text */
    if (n < static_cast<size_t>(kLengthBits)) {  /* no room for the count */
        return -1;  /* refuse */
    }  /* end of the check */
    size_t count = static_cast<size_t>(get(bits, kLengthBits));  /* the true character count */
    const uint8_t *payload = bits + kLengthBits;  /* the text bits */
    size_t room = n - kLengthBits;  /* how many there are */
    if (count > cap) {  /* no room to hand them back */
        return -1;  /* refuse */
    }  /* end of the check */
    if (compressed) {  /* compressed: compress.py decompress */
        size_t got = 0;  /* characters found */
        int code = 0;  /* the code being collected */
        int length = 0;  /* its bits so far */
        for (size_t i = 0; i < room && got < count; ++i) {  /* one bit at a time, until every character is found */
            code = (code << 1) | payload[i];  /* add the bit */
            ++length;  /* one more */
            if (length > 13) {  /* longer than any code: it can never complete */
                return -1;  /* the frame is damaged */
            }  /* end of the check */
            int symbol = codes().find(length, code);  /* a complete code? */
            if (symbol >= 0) {  /* yes */
                out[got++] = static_cast<char>(symbol);  /* its character */
                code = 0;  /* start again */
                length = 0;  /* from nothing */
            }  /* end of the test */
        }  /* end of the bits */
        return got == count ? static_cast<long>(count) : -1;  /* every character, or damaged */
    }  /* end of the compressed form */
    if (count * kCharBits > room) {  /* more characters than there is room for */
        return -1;  /* damaged */
    }  /* end of the check */
    for (size_t i = 0; i < count; ++i) {  /* each character */
        out[i] = static_cast<char>(get(payload + i * kCharBits, kCharBits));  /* seven bits */
    }  /* end of the characters */
    return static_cast<long>(count);  /* characters written */
}  /* end of kes_bits_to_text */

KES_API void kes_header_bits(int frame_type, int level, int size_class, int part, int parts, int compressed, uint8_t *out) {  /* frame.py _header_bits */
    std::vector<uint8_t> v;  /* the bits */
    put(v, static_cast<unsigned long long>(frame_type), 3);  /* frame type */
    put(v, static_cast<unsigned long long>(level), 3);  /* speed level */
    put(v, static_cast<unsigned long long>(size_class), 2);  /* size class */
    put(v, static_cast<unsigned long long>(part), 3);  /* part number */
    put(v, static_cast<unsigned long long>(parts - 1), 3);  /* parts, less one */
    put(v, static_cast<unsigned long long>(compressed), 1);  /* compressed? (its lowest bit, as Python int_to_bits takes it) */
    put(v, 0, 1);  /* the spare bit */
    put(v, static_cast<unsigned long long>(kes_crc8(v.data(), v.size())), 8);  /* the check value */
    std::copy(v.begin(), v.end(), out);  /* handed back */
}  /* end of kes_header_bits */

KES_API long kes_address_block(int frame_type, long link, long want_level, long msg_id, const char *dest, const char *origin, long hops, long life_hours,
                               uint8_t *out) {  /* frame.py _address_block */
    if (msg_id < 0 || msg_id >= (1L << kMsgBits)) {  /* the message number does not fit */
        return -1;  /* refuse */
    }  /* end of the check */
    std::vector<uint8_t> v;  /* the bits */
    if (frame_type == 0) {  /* a link frame */
        if (link < 0 || link >= (1L << kLinkBits) || want_level < 0 || want_level >= (1L << kLevelBits)) {  /* a field does not fit */
            return -1;  /* refuse */
        }  /* end of the check */
        put(v, static_cast<unsigned long long>(link), kLinkBits);  /* link number */
        put(v, static_cast<unsigned long long>(want_level), kLevelBits);  /* wanted level */
        put(v, static_cast<unsigned long long>(msg_id), kMsgBits);  /* message number */
    } else {  /* a fully addressed frame */
        long life = life_hours >= 0 ? (life_hours + kLifeUnit - 1) / kLifeUnit : -((-life_hours) / kLifeUnit);  /* two-hour steps, rounded up (as Python's -(-x // 2)) */
        std::string d;  /* the destination */
        std::string o;  /* the origin */
        if (hops < 0 || hops >= (1L << kHopBits) || life < 0 || life >= (1L << kLifeBits) || !clean_call(dest, d) || !clean_call(origin, o)) {  /* a field does not fit, or an address is not valid */
            return -1;  /* refuse */
        }  /* end of the check */
        call_bits(d, v);  /* who it is for */
        call_bits(o, v);  /* who wrote it */
        put(v, static_cast<unsigned long long>(msg_id), kMsgBits);  /* message number */
        put(v, static_cast<unsigned long long>(hops), kHopBits);  /* relays so far */
        put(v, static_cast<unsigned long long>(life), kLifeBits);  /* lifetime left */
    }  /* end of the two kinds */
    std::copy(v.begin(), v.end(), out);  /* handed back */
    return static_cast<long>(v.size());  /* bits written */
}  /* end of kes_address_block */

KES_API int kes_read_address_block(int frame_type, const uint8_t *bits, KesFields *f) {  /* frame.py _read_address_block */
    std::memset(f, 0, sizeof(*f));  /* nothing yet */
    if (frame_type == 0) {  /* a link frame */
        f->link = static_cast<long>(get(bits, kLinkBits));  /* link number */
        f->want_level = static_cast<int>(get(bits + kLinkBits, kLevelBits));  /* wanted level */
        f->msg_id = static_cast<long>(get(bits + kLinkBits + kLevelBits, kMsgBits));  /* message number */
        return 0;  /* done */
    }  /* end of the link frame */
    std::string d;  /* destination */
    std::string o;  /* origin */
    if (!bits_call(bits, d) || !bits_call(bits + kCallBits, o)) {  /* either is not an address */
        return -1;  /* refuse */
    }  /* end of the check */
    copy_call(d, f->dest);  /* who it is for */
    copy_call(o, f->origin);  /* who wrote it */
    const uint8_t *rest = bits + 2 * kCallBits;  /* the counters */
    f->msg_id = static_cast<long>(get(rest, kMsgBits));  /* message number */
    f->hops = static_cast<long>(get(rest + kMsgBits, kHopBits));  /* relays so far */
    f->life_hours = static_cast<long>(get(rest + kMsgBits + kHopBits, kLifeBits)) * kLifeUnit;  /* lifetime, in hours */
    return 0;  /* done */
}  /* end of kes_read_address_block */

KES_API int kes_levels_mask(const long *levels, size_t n) {  /* control.py levels_to_bits, as a number */
    int mask = 0;  /* no levels yet */
    for (size_t i = 0; i < n; ++i) {  /* each level */
        if (levels[i] < 0 || levels[i] >= kMaskBits) {  /* no bit for it */
            return -1;  /* refuse */
        }  /* end of the check */
        mask |= 1 << levels[i];  /* its bit */
    }  /* end of the levels */
    return mask;  /* the list */
}  /* end of kes_levels_mask */

KES_API long kes_pack_control(int frame_type, const KesFields *f, uint8_t *out) {  /* control.py pack_beacon, pack_answer, pack_ack, pack_ident, pack_notice */
    std::vector<uint8_t> v;  /* the bits */
    std::string a;  /* an address */
    std::string b;  /* a second address */
    switch (frame_type) {  /* which frame */
    case 2:  /* a beacon: callsign, locator, levels, four flags */
        if (!clean_call(f->origin, a)) {  /* not an address */
            return -1;  /* refuse */
        }  /* end of the check */
        call_bits(a, v);  /* the callsign */
        if (!grid_bits(f->grid, v) || f->levels < 0 || f->levels > 255) {  /* not a locator, or not a level list */
            return -1;  /* refuse */
        }  /* end of the check */
        put(v, static_cast<unsigned long long>(f->levels), kMaskBits);  /* the levels */
        v.push_back(static_cast<uint8_t>(f->listening));  /* will take answers */
        v.push_back(static_cast<uint8_t>(f->mail_check));  /* wants its mail */
        v.push_back(static_cast<uint8_t>(f->holds_mail));  /* holds mail for others */
        v.push_back(static_cast<uint8_t>(f->wide));  /* wide reply window */
        break;  /* done */
    case 3: {  /* an answer: two callsigns, the sender's locator, a report, levels, two flags */
        if (!clean_call(f->dest, a) || !clean_call(f->origin, b)) {  /* not addresses */
            return -1;  /* refuse */
        }  /* end of the check */
        call_bits(a, v);  /* to whom */
        call_bits(b, v);  /* from whom */
        std::string g;  /* the locator, tidied */
        if (!strip_upper(f->grid, g)) {  /* not ASCII */
            return -1;  /* refuse */
        }  /* end of the check */
        if (g.empty()) {  /* none set */
            put(v, kNoGrid, kGridBits);  /* "no locator" */
        } else if (!grid_bits(f->grid, v)) {  /* not a locator */
            return -1;  /* refuse */
        }  /* end of the locator */
        if (!report_bits(f->snr_db, f->fade_index, f->offset_hz, f->want_level, v) || f->levels < 0 || f->levels > 255) {  /* a bad report or level list */
            return -1;  /* refuse */
        }  /* end of the check */
        put(v, static_cast<unsigned long long>(f->levels), kMaskBits);  /* the levels */
        v.push_back(static_cast<uint8_t>(f->mail_check));  /* wants its mail */
        v.push_back(static_cast<uint8_t>(f->directed));  /* a directed call */
        break;  /* done */
    }  /* end of the answer */
    case 4:  /* an acknowledgment: link, message, part, verdict, report */
        if (f->link < 0 || f->link >= (1L << kLinkBits) || f->msg_id < 0 || f->msg_id >= (1L << kMsgBits) || f->part < 0 || f->part >= (1L << kPartBits) ||
            f->status < 0 || f->status >= (1L << kStatusBits)) {  /* a field does not fit */
            return -1;  /* refuse */
        }  /* end of the check */
        put(v, static_cast<unsigned long long>(f->link), kLinkBits);  /* link */
        put(v, static_cast<unsigned long long>(f->msg_id), kMsgBits);  /* message */
        put(v, static_cast<unsigned long long>(f->part), kPartBits);  /* part */
        put(v, static_cast<unsigned long long>(f->status), kStatusBits);  /* verdict */
        if (!report_bits(f->snr_db, f->fade_index, f->offset_hz, f->want_level, v)) {  /* a bad report */
            return -1;  /* refuse */
        }  /* end of the check */
        break;  /* done */
    case 5:  /* an identification: callsign, link, four flags */
        if (f->link < 0 || f->link >= (1L << kLinkBits) || !clean_call(f->origin, a)) {  /* the link does not fit, or not an address */
            return -1;  /* refuse */
        }  /* end of the check */
        call_bits(a, v);  /* the callsign */
        put(v, static_cast<unsigned long long>(f->link), kLinkBits);  /* the link */
        v.push_back(static_cast<uint8_t>(f->final_flag));  /* end of contact */
        put(v, 0, 3);  /* three spare bits */
        break;  /* done */
    case 7: {  /* a mail notice: callsign, then three lists of three codes */
        if (!clean_call(f->origin, a)) {  /* not an address */
            return -1;  /* refuse */
        }  /* end of the check */
        call_bits(a, v);  /* the callsign */
        const long *lists[3] = {f->held, f->receipts, f->heard};  /* the three lists */
        const int counts[3] = {f->nheld, f->nreceipts, f->nheard};  /* how many entries each has */
        for (int l = 0; l < 3; ++l) {  /* each list */
            int n = std::min(std::max(counts[l], 0), kSlots);  /* at most three */
            for (int s = 0; s < kSlots; ++s) {  /* each entry */
                long code = s < n ? lists[l][s] : 0;  /* the code, or empty */
                if (s < n && (code <= 0 || code >= (1L << kHashBits))) {  /* a given code must fit, and not be 0 */
                    return -1;  /* refuse */
                }  /* end of the check */
                put(v, static_cast<unsigned long long>(code), kHashBits);  /* the code */
            }  /* end of the entries */
        }  /* end of the lists */
        break;  /* done */
    }  /* end of the notice */
    default:  /* not a control frame */
        return -1;  /* refuse */
    }  /* end of the frames */
    std::copy(v.begin(), v.end(), out);  /* handed back */
    return static_cast<long>(v.size());  /* bits written */
}  /* end of kes_pack_control */

KES_API int kes_unpack_control(int frame_type, const uint8_t *bits, size_t n, KesFields *f) {  /* control.py unpack */
    std::memset(f, 0, sizeof(*f));  /* nothing yet */
    if (frame_type < 0 || frame_type > 7 || kControlBits[frame_type] == 0 || n != static_cast<size_t>(kControlBits[frame_type])) {  /* not a control frame, or the wrong length */
        return -1;  /* refuse */
    }  /* end of the check */
    std::string a;  /* an address */
    std::string b;  /* a second address */
    switch (frame_type) {  /* which frame */
    case 2: {  /* a beacon */
        const uint8_t *rest = bits + kCallBits;  /* after the callsign */
        if (!bits_call(bits, a) || !bits_grid(rest, f->grid)) {  /* not an address or not a locator */
            return -1;  /* refuse */
        }  /* end of the check */
        copy_call(a, f->origin);  /* who */
        f->levels = static_cast<int>(get(rest + kGridBits, kMaskBits));  /* the levels */
        const uint8_t *flags = rest + kGridBits + kMaskBits;  /* the four flags */
        f->listening = flags[0];  /* will take answers */
        f->mail_check = flags[1];  /* wants its mail */
        f->holds_mail = flags[2];  /* holds mail */
        f->wide = flags[3];  /* wide reply window */
        return 0;  /* done */
    }  /* end of the beacon */
    case 3: {  /* an answer */
        if (!bits_call(bits, a) || !bits_call(bits + kCallBits, b)) {  /* not addresses */
            return -1;  /* refuse */
        }  /* end of the check */
        copy_call(a, f->dest);  /* to whom */
        copy_call(b, f->origin);  /* from whom */
        const uint8_t *place = bits + 2 * kCallBits;  /* the locator, after the callsigns */
        if (get(place, kGridBits) != kNoGrid && !bits_grid(place, f->grid)) {  /* neither "none" nor a locator: damaged */
            return -1;  /* refuse */
        }  /* end of the locator ("none" leaves it empty) */
        const uint8_t *rest = place + kGridBits;  /* after the locator */
        read_report(rest, f);  /* the report */
        f->levels = static_cast<int>(get(rest + kReportBits, kMaskBits));  /* the levels */
        f->mail_check = rest[kReportBits + kMaskBits];  /* wants its mail */
        f->directed = rest[kReportBits + kMaskBits + 1];  /* a directed call */
        return 0;  /* done */
    }  /* end of the answer */
    case 4: {  /* an acknowledgment */
        f->link = static_cast<long>(get(bits, kLinkBits));  /* link */
        f->msg_id = static_cast<long>(get(bits + kLinkBits, kMsgBits));  /* message */
        const uint8_t *rest = bits + kLinkBits + kMsgBits;  /* after them */
        f->part = static_cast<long>(get(rest, kPartBits));  /* part */
        f->status = static_cast<long>(get(rest + kPartBits, kStatusBits));  /* verdict */
        read_report(rest + kPartBits + kStatusBits, f);  /* the report */
        return 0;  /* done */
    }  /* end of the acknowledgment */
    case 5:  /* an identification */
        if (!bits_call(bits, a)) {  /* not an address */
            return -1;  /* refuse */
        }  /* end of the check */
        copy_call(a, f->origin);  /* who */
        f->link = static_cast<long>(get(bits + kCallBits, kLinkBits));  /* the link */
        f->final_flag = bits[kCallBits + kLinkBits];  /* end of contact */
        return 0;  /* done */
    default: {  /* a mail notice (type 7) */
        if (!bits_call(bits, a)) {  /* not an address */
            return -1;  /* refuse */
        }  /* end of the check */
        copy_call(a, f->origin);  /* who */
        long *lists[3] = {f->held, f->receipts, f->heard};  /* the three lists */
        int *counts[3] = {&f->nheld, &f->nreceipts, &f->nheard};  /* and their lengths */
        for (int l = 0; l < 3; ++l) {  /* each list */
            for (int s = 0; s < kSlots; ++s) {  /* each entry */
                long code = static_cast<long>(get(bits + kCallBits + (l * kSlots + s) * kHashBits, kHashBits));  /* the code */
                if (code != 0) {  /* not an empty entry */
                    lists[l][(*counts[l])++] = code;  /* kept */
                }  /* end of the test */
            }  /* end of the entries */
        }  /* end of the lists */
        return 0;  /* done */
    }  /* end of the notice */
    }  /* end of the frames */
}  /* end of kes_unpack_control */

}  /* end of the exported packing functions */
