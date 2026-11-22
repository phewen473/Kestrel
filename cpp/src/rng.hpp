/*
 * rng.hpp - NumPy's default random generator (PCG64 seeded through SeedSequence), in C++.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * A station picks its reply slot at random from a generator seeded with the
 * CRC-32 of its callsign (link/station.py: np.random.default_rng(zlib.crc32(call))).
 * This file gives the very same numbers as NumPy for that use, so the C++
 * station and the Python station make the same choices and can be tested
 * against each other: SeedSequence (NumPy's seed hashing), the PCG64
 * generator (128-bit state, XSL-RR output) and Generator.integers for small
 * ranges (Lemire's bounded method on 32-bit draws). The 128-bit arithmetic is
 * done with pairs of 64-bit words, so any C++17 compiler builds it.
 */

#ifndef KESTREL_RNG_HPP  /* guard against being included twice */
#define KESTREL_RNG_HPP  /* mark it included */

#include <cstdint>  /* fixed-size integers */
#include <vector>  /* growable arrays */

namespace kes {  /* the library's C++ names */

class NumpyRandom {  /* np.random.default_rng(seed) for a seed below 2**32 */
public:  /* what callers use */
    explicit NumpyRandom(uint32_t seed) {  /* seeded as NumPy seeds it */
        uint32_t pool[4];  /* SeedSequence's pool of four words */
        mix_entropy(pool, seed);  /* the seed hashed into the pool */
        uint32_t words[8];  /* generate_state(4, uint64): eight 32-bit words */
        generate_state(pool, words, 8);  /* drawn from the pool */
        uint64_t val[4];  /* as four 64-bit words (little-endian pairs) */
        for (int i = 0; i < 4; ++i) {  /* each */
            val[i] = static_cast<uint64_t>(words[2 * i]) | (static_cast<uint64_t>(words[2 * i + 1]) << 32);  /* low word first */
        }  /* end of the words */
        U128 initstate{val[0], val[1]};  /* the state seed (high word first) */
        state_ = U128{0, 0};  /* pcg_setseq_128_srandom_r */
        inc_ = U128{(val[2] << 1) | (val[3] >> 63), (val[3] << 1) | 1u};  /* the stream shifted left, made odd */
        step();  /* one step */
        state_ = add(state_, initstate);  /* the seed added */
        step();  /* and another step */
    }  /* end of the constructor */

    long long integers(long long low, long long high) {  /* Generator.integers(low, high): low <= n < high, for a range below 2**32 */
        uint32_t rng = static_cast<uint32_t>(high - 1 - low);  /* the inclusive span, as NumPy passes it */
        if (rng == 0) {  /* only one value */
            return low;  /* it */
        }  /* end of the trivial case */
        if (rng == 0xFFFFFFFFu) {  /* the whole 32-bit range */
            return low + next32();  /* a raw draw */
        }  /* end of the full range */
        uint32_t excl = rng + 1u;  /* the number of values */
        uint64_t m = static_cast<uint64_t>(next32()) * excl;  /* Lemire: scale a 32-bit draw */
        uint32_t leftover = static_cast<uint32_t>(m & 0xFFFFFFFFu);  /* the fractional part */
        if (leftover < excl) {  /* it may be biased */
            uint32_t threshold = static_cast<uint32_t>((0u - excl) % excl);  /* the biased stretch */
            while (leftover < threshold) {  /* in it */
                m = static_cast<uint64_t>(next32()) * excl;  /* draw again */
                leftover = static_cast<uint32_t>(m & 0xFFFFFFFFu);  /* its fractional part */
            }  /* end of the redraws */
        }  /* end of the bias check */
        return low + static_cast<long long>(m >> 32);  /* the whole part */
    }  /* end of integers */

private:  /* the workings */
    struct U128 {  /* a 128-bit number as two 64-bit halves */
        uint64_t hi;  /* the high half */
        uint64_t lo;  /* the low half */
    };  /* end of U128 */

    static U128 add(U128 a, U128 b) {  /* a + b, modulo 2**128 */
        uint64_t lo = a.lo + b.lo;  /* the low halves */
        return U128{a.hi + b.hi + (lo < a.lo ? 1u : 0u), lo};  /* with the carry */
    }  /* end of add */

    static U128 mul64(uint64_t a, uint64_t b) {  /* the full 128-bit product of two 64-bit numbers */
        uint64_t a_lo = a & 0xFFFFFFFFu, a_hi = a >> 32;  /* a's halves */
        uint64_t b_lo = b & 0xFFFFFFFFu, b_hi = b >> 32;  /* b's halves */
        uint64_t p0 = a_lo * b_lo, p1 = a_lo * b_hi, p2 = a_hi * b_lo, p3 = a_hi * b_hi;  /* the four partial products */
        uint64_t middle = (p0 >> 32) + (p1 & 0xFFFFFFFFu) + (p2 & 0xFFFFFFFFu);  /* the middle column, with carries */
        return U128{p3 + (p1 >> 32) + (p2 >> 32) + (middle >> 32), (middle << 32) | (p0 & 0xFFFFFFFFu)};  /* assembled */
    }  /* end of mul64 */

    static U128 mul(U128 a, U128 b) {  /* a * b, modulo 2**128 */
        U128 low = mul64(a.lo, b.lo);  /* the low halves' full product */
        return U128{low.hi + a.lo * b.hi + a.hi * b.lo, low.lo};  /* plus the cross terms (their high parts fall off) */
    }  /* end of mul */

    U128 state_{0, 0};  /* PCG64's state */
    U128 inc_{0, 0};  /* and its increment */
    bool has32_ = false;  /* a spare 32-bit half is waiting */
    uint32_t spare_ = 0;  /* that half */

    static constexpr uint32_t kInitA = 0x43b0d7e5u;  /* SeedSequence constants (numpy/random/bit_generator.pyx) */
    static constexpr uint32_t kMultA = 0x931e8875u;  /* ... */
    static constexpr uint32_t kInitB = 0x8b51f9ddu;  /* ... */
    static constexpr uint32_t kMultB = 0x58f38dedu;  /* ... */
    static constexpr uint32_t kMixL = 0xca01f9ddu;  /* ... */
    static constexpr uint32_t kMixR = 0x4973f715u;  /* ... */

    static uint32_t hashmix(uint32_t value, uint32_t &hash_const) {  /* SeedSequence hashmix */
        value ^= hash_const;  /* mixed with the constant */
        hash_const *= kMultA;  /* the constant moves on */
        value *= hash_const;  /* multiplied */
        value ^= value >> 16;  /* folded */
        return value;  /* hashed */
    }  /* end of hashmix */

    static uint32_t mix(uint32_t x, uint32_t y) {  /* SeedSequence mix */
        uint32_t result = kMixL * x - kMixR * y;  /* combined */
        result ^= result >> 16;  /* folded */
        return result;  /* mixed */
    }  /* end of mix */

    static void mix_entropy(uint32_t *pool, uint32_t seed) {  /* SeedSequence.mix_entropy for one 32-bit word of entropy */
        uint32_t hash_const = kInitA;  /* the running constant */
        for (int i = 0; i < 4; ++i) {  /* fill the pool */
            pool[i] = hashmix(i == 0 ? seed : 0u, hash_const);  /* the seed, then zeros */
        }  /* end of the fill */
        for (int src = 0; src < 4; ++src) {  /* mix every word... */
            for (int dst = 0; dst < 4; ++dst) {  /* ...into every other */
                if (src != dst) {  /* not itself */
                    pool[dst] = mix(pool[dst], hashmix(pool[src], hash_const));  /* mixed in */
                }  /* end of the test */
            }  /* end of the destinations */
        }  /* end of the sources */
    }  /* end of mix_entropy */

    static void generate_state(const uint32_t *pool, uint32_t *out, int n) {  /* SeedSequence.generate_state, 32-bit words */
        uint32_t hash_const = kInitB;  /* the running constant */
        for (int i = 0; i < n; ++i) {  /* each word */
            uint32_t v = pool[i % 4];  /* cycling through the pool */
            v ^= hash_const;  /* mixed */
            hash_const *= kMultB;  /* the constant moves on */
            v *= hash_const;  /* multiplied */
            v ^= v >> 16;  /* folded */
            out[i] = v;  /* kept */
        }  /* end of the words */
    }  /* end of generate_state */

    void step() {  /* one PCG step */
        const U128 mult{0x2360ED051FC65DA4ULL, 0x4385DF649FCCF645ULL};  /* PCG's 128-bit multiplier */
        state_ = add(mul(state_, mult), inc_);  /* the linear congruential step */
    }  /* end of step */

    uint64_t next64() {  /* PCG64's 64-bit output: step, then XSL-RR */
        step();  /* advance */
        uint64_t value = state_.hi ^ state_.lo;  /* fold the halves */
        unsigned rot = static_cast<unsigned>(state_.hi >> 58);  /* the rotation: the top six bits */
        return (value >> rot) | (value << ((64u - rot) & 63u));  /* rotate right */
    }  /* end of next64 */

    uint32_t next32() {  /* NumPy's pcg64_next32: two 32-bit draws from each 64-bit one, low half first */
        if (has32_) {  /* a half is waiting */
            has32_ = false;  /* used */
            return spare_;  /* the high half */
        }  /* end of the spare */
        uint64_t next = next64();  /* a fresh draw */
        has32_ = true;  /* the high half waits */
        spare_ = static_cast<uint32_t>(next >> 32);  /* kept */
        return static_cast<uint32_t>(next & 0xFFFFFFFFu);  /* the low half now */
    }  /* end of next32 */
};  /* end of NumpyRandom */

}  /* end of namespace kes */

#endif  /* KESTREL_RNG_HPP */
