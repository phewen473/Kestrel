/*
 * kestrel.cpp - the Kestrel modem library: the routines behind kestrel.h.
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 *
 * Each function follows its Python reference line for line (named in
 * kestrel.h), in the same order of arithmetic, so that the results agree:
 * exactly for the blanker and the decoder, and to the last few rounding
 * places for anything that goes through sines, cosines or an FFT.
 */

#define KESTREL_BUILDING 1  /* this file builds the library, so its functions are exported */
#include "kestrel.h"  /* the interface being implemented */

#include <algorithm>  /* nth_element, max, min */
#include <cmath>  /* fabs, cos, sin, nearbyint */
#include <complex>  /* complex numbers for the FFT */
#include <cstdint>  /* fixed-size integers */
#include <cstring>  /* memcpy */
#include <limits>  /* infinity */
#include <thread>  /* worker threads */
#include <vector>  /* growable arrays */

#include "pocketfft_hdronly.h"  /* the FFT (the same algorithm NumPy uses), header-only, BSD licence */

namespace {  /* helpers seen only inside this file */

const double kPi = 3.141592653589793;  /* pi, to double precision (NumPy's np.pi) */
const double kSampleRate = 12000.0;  /* Kestrel's audio sample rate, samples per second (modem/params.py FS) */
const size_t kBlankBlock = 1200;  /* the blanker's neighbourhood: a tenth of a second (modem/blanker.py BLOCK) */
const int kStates = 64;  /* the convolutional code's encoder states (modem/fec.py NSTATES) */
const int kTail = 6;  /* zero bits that end every coded block (modem/fec.py TAIL) */
const int kG1 = 0171;  /* the code's first generator, octal (modem/fec.py G1) */
const int kG2 = 0133;  /* and its second (modem/fec.py G2) */
const size_t kAnchor = 64;  /* band_energies works out the mixer's sine and cosine exactly every this many samples */

/* The middle value of v[0..n), as NumPy's median gives it: the middle element
 * for an odd count, the mean of the two middle elements for an even one.
 * v is reordered. */
double median_inplace(double *v, size_t n) {  /* the middle value of n numbers */
    size_t half = n / 2;  /* the upper middle position */
    std::nth_element(v, v + half, v + n);  /* put the upper middle value in its sorted place */
    double upper = v[half];  /* the upper middle value */
    if (n % 2 == 1) {  /* an odd count has one middle value */
        return upper;  /* that is the median */
    }  /* end of the odd case */
    double lower = *std::max_element(v, v + half);  /* the lower middle value: the largest of those below */
    return (lower + upper) / 2.0;  /* their mean, computed as NumPy's mean of two numbers is */
}  /* end of median_inplace */

/* a times b for complex numbers, written out: the library's own operator checks for
 * infinities on every multiplication, which is several times slower. */
inline std::complex<double> times(std::complex<double> a, std::complex<double> b) {  /* complex product */
    return std::complex<double>(a.real() * b.real() - a.imag() * b.imag(), a.real() * b.imag() + a.imag() * b.real());  /* (ac - bd) + (ad + bc)i */
}  /* end of times */

/* The k-th smallest (counting from 0) of v[0..n), all of them zero or positive, found exactly by their bit
 * patterns: for numbers that are not negative, a larger double always has a larger 64-bit pattern, so the
 * top 16 bits sort them into 65,536 buckets in one pass; only the bucket holding the k-th is then sorted
 * out. Much faster than a general selection on long recordings; the answer is the same. */
double kth_not_negative(const double *v, size_t n, size_t k) {  /* exact selection for long runs */
    std::vector<size_t> count(65536, 0);  /* how many numbers fall in each bucket */
    for (size_t i = 0; i < n; ++i) {  /* each number */
        uint64_t bits;  /* its bit pattern */
        std::memcpy(&bits, v + i, sizeof bits);  /* copied out (the safe way to look at a double's bits) */
        ++count[bits >> 48];  /* counted in its bucket */
    }  /* end of the count */
    size_t bucket = 0, below = 0;  /* the bucket holding the k-th, and how many numbers lie in buckets before it */
    while (below + count[bucket] <= k) {  /* the k-th is past this bucket */
        below += count[bucket];  /* skip it */
        ++bucket;  /* next */
    }  /* end of the walk */
    std::vector<double> inside;  /* the numbers in that bucket */
    inside.reserve(count[bucket]);  /* room for them */
    for (size_t i = 0; i < n; ++i) {  /* each number */
        uint64_t bits;  /* its bit pattern */
        std::memcpy(&bits, v + i, sizeof bits);  /* copied out */
        if ((bits >> 48) == bucket) {  /* in the bucket */
            inside.push_back(v[i]);  /* kept */
        }  /* end of the test */
    }  /* end of the gathering */
    size_t want = k - below;  /* its place within the bucket */
    std::nth_element(inside.begin(), inside.begin() + static_cast<long>(want), inside.end());  /* put it in its sorted place */
    return inside[want];  /* the k-th smallest */
}  /* end of kth_not_negative */

/* The median of n numbers that are zero or positive, as NumPy gives it, leaving v unchanged. */
double median_not_negative(const double *v, size_t n) {  /* the middle value of a long run */
    double upper = kth_not_negative(v, n, n / 2);  /* the upper middle value */
    if (n % 2 == 1) {  /* an odd count */
        return upper;  /* the median */
    }  /* end of the odd case */
    double lower = kth_not_negative(v, n, n / 2 - 1);  /* the lower middle value */
    return (lower + upper) / 2.0;  /* their mean */
}  /* end of median_not_negative */

/* 1 when value has an odd number of 1 bits, else 0 (modem/fec.py _parity). */
int parity(int value) {  /* the parity of an integer */
    int ones = 0;  /* count of 1 bits */
    while (value) {  /* until every bit has been looked at */
        ones += value & 1;  /* count the lowest bit */
        value >>= 1;  /* move on to the next */
    }  /* end of the count */
    return ones & 1;  /* odd or even */
}  /* end of parity */


/* How many threads the heavy loops may use: the computer's own count, at most kMostThreads (more brings
 * little for blocks this size), and 1 when the count is unknown. Set by kes_set_threads. */
const unsigned kMostThreads = 8;  /* the most threads any one call uses */
unsigned g_threads = 0;  /* 0 means "not chosen yet": use the computer's count */

unsigned thread_count() {  /* how many threads to use */
    unsigned n = g_threads ? g_threads : std::thread::hardware_concurrency();  /* chosen, or the computer's count */
    return std::max(1u, std::min(n, kMostThreads));  /* between 1 and the cap */
}  /* end of thread_count */

/* Run work(first, last) over the range [0, count), split into one piece per thread. Each piece is worked out
 * exactly as it would be on one thread, so the results never depend on how many threads ran. Small jobs
 * (under `least` items per thread) stay on the calling thread, where starting threads would cost more
 * than it saves. */
template <typename Work>
void parallel_for(size_t count, size_t least, Work work) {  /* split a loop across threads */
    size_t threads = std::min<size_t>(thread_count(), least ? count / least : count);  /* threads worth starting */
    if (threads <= 1) {  /* not worth it */
        work(static_cast<size_t>(0), count);  /* all on this thread */
        return;  /* done */
    }  /* end of the small case */
    std::vector<std::thread> pool;  /* the helpers */
    size_t piece = (count + threads - 1) / threads;  /* items per thread, rounded up */
    for (size_t t = 1; t < threads; ++t) {  /* every piece but the first */
        size_t first = t * piece, last = std::min(count, first + piece);  /* its range */
        if (first < last) {  /* not empty */
            pool.emplace_back(work, first, last);  /* on a helper thread */
        }  /* end of the test */
    }  /* end of the helpers */
    work(static_cast<size_t>(0), std::min(count, piece));  /* the first piece here */
    for (auto &helper : pool) {  /* wait for every helper */
        helper.join();  /* finished */
    }  /* end of the waiting */
}  /* end of parallel_for */

}  /* end of the private helpers */

extern "C" {  /* the exported functions keep their plain C names */

KES_API int kes_abi_version(void) {  /* the interface version built into this library */
    return KES_ABI_VERSION;  /* as defined in kestrel.h */
}  /* end of kes_abi_version */

KES_API void kes_set_threads(int threads) {  /* how many threads the library may use */
    g_threads = threads > 0 ? static_cast<unsigned>(threads) : 0u;  /* a count, or 0 for the computer's own */
}  /* end of kes_set_threads */

KES_API int kes_threads(void) {  /* how many threads the library will use */
    return static_cast<int>(thread_count());  /* after the cap */
}  /* end of kes_threads */

KES_API void kes_blank_impulses(const double *x, size_t n, double threshold, int guard, double *out) {  /* the static-crash blanker */
    std::memcpy(out, x, n * sizeof(double));  /* start from an unchanged copy */
    if (n == 0) {  /* an empty recording */
        return;  /* nothing to do */
    }  /* end of the empty case */
    std::vector<double> level(n);  /* the size of every sample, ignoring sign */
    for (size_t i = 0; i < n; ++i) {  /* each sample */
        level[i] = std::fabs(x[i]);  /* its size */
    }  /* end of the sizes */
    size_t blocks = (n + kBlankBlock - 1) / kBlankBlock;  /* neighbourhoods, rounding up */
    std::vector<double> typical(blocks);  /* the normal level in each neighbourhood */
    parallel_for(blocks, 64, [&](size_t from, size_t to) {  /* the neighbourhoods, shared among threads */
        std::vector<double> scratch(kBlankBlock);  /* room to find one neighbourhood's median */
        for (size_t b = from; b < to; ++b) {  /* each neighbourhood in this share */
            size_t first = b * kBlankBlock;  /* its first sample */
            size_t count = std::min(kBlankBlock, n - first);  /* its length (the last may be short) */
            std::memcpy(scratch.data(), level.data() + first, count * sizeof(double));  /* a copy to reorder */
            typical[b] = median_inplace(scratch.data(), count) / 0.6745;  /* its median, as a typical level */
        }  /* end of the neighbourhoods */
    });  /* end of the shared loop */
    std::vector<double> positive;  /* every sample size above zero */
    positive.reserve(n);  /* room for all of them */
    for (size_t i = 0; i < n; ++i) {  /* each sample */
        if (level[i] > 0.0) {  /* above zero */
            positive.push_back(level[i]);  /* keep it */
        }  /* end of the test */
    }  /* end of the sizes above zero */
    double quiet = positive.empty() ? 0.0 : median_not_negative(positive.data(), positive.size()) / 0.6745;  /* the normal level of the whole recording */
    for (size_t b = 0; b < blocks; ++b) {  /* each neighbourhood */
        typical[b] = std::max(typical[b], quiet);  /* never judged quieter than the recording as a whole */
    }  /* end of the floor */
    for (size_t i = 0; i < n; ++i) {  /* each sample */
        if (level[i] > threshold * typical[i / kBlankBlock]) {  /* far louder than its neighbourhood: a spike */
            size_t from = (i >= static_cast<size_t>(guard)) ? i - guard : 0;  /* the spike's start, widened (not before the recording) */
            size_t to = std::min(n - 1, i + static_cast<size_t>(guard));  /* its end, widened (not after) */
            for (size_t j = from; j <= to; ++j) {  /* every sample it covers */
                out[j] = 0.0;  /* silenced */
            }  /* end of the silencing */
        }  /* end of the spike */
    }  /* end of the search */
}  /* end of kes_blank_impulses */

KES_API long kes_viterbi_decode(const double *llrs, size_t n, uint8_t *bits) {  /* the soft Viterbi decoder */
    long steps = static_cast<long>(n / 2);  /* one decoding step per pair of coded bits */
    if (steps < kTail) {  /* too short to hold even the tail */
        return -1;  /* refuse */
    }  /* end of the check */
    int pred[2][kStates];  /* the two states each state can be reached from */
    double sign1[2][kStates], sign2[2][kStates];  /* the two output bits on each of those paths, as +1 or -1 */
    for (int s = 0; s < kStates; ++s) {  /* each state */
        for (int h = 0; h < 2; ++h) {  /* each of its two predecessors */
            pred[h][s] = (s >> 1) | (h << 5);  /* the state it came from */
            int reg = (pred[h][s] << 1) | (s & 1);  /* the 7-bit register on that path */
            sign1[h][s] = 1.0 - 2.0 * parity(reg & kG1);  /* first output bit as +1 (0) or -1 (1) */
            sign2[h][s] = 1.0 - 2.0 * parity(reg & kG2);  /* second output bit likewise */
        }  /* end of the predecessors */
    }  /* end of the states */
    std::vector<double> metric(kStates, -1e18), next(kStates);  /* the score of the best path into each state (very low = impossible) */
    metric[0] = 0.0;  /* the encoder always starts in state 0 */
    std::vector<uint8_t> choices(static_cast<size_t>(steps) * kStates);  /* which path won, for every step and state */
    for (long t = 0; t < steps; ++t) {  /* forward through the received bits */
        double a = llrs[2 * t], b = llrs[2 * t + 1];  /* this step's two soft bits */
        for (int s = 0; s < kStates; ++s) {  /* each state */
            double c0 = metric[pred[0][s]] + sign1[0][s] * a + sign2[0][s] * b;  /* score through the first path (same order of adding as the Python) */
            double c1 = metric[pred[1][s]] + sign1[1][s] * a + sign2[1][s] * b;  /* and through the second */
            bool pick = c1 > c0;  /* the second is better */
            choices[static_cast<size_t>(t) * kStates + s] = pick ? 1 : 0;  /* remember the winner */
            next[s] = pick ? c1 : c0;  /* keep its score */
        }  /* end of the states */
        metric.swap(next);  /* the new scores become the current ones */
    }  /* end of the forward pass */
    int state = 0;  /* the tail forces the encoder to finish in state 0 */
    std::vector<uint8_t> all(static_cast<size_t>(steps));  /* every decoded bit, filled from the end */
    for (long t = steps - 1; t >= 0; --t) {  /* back along the winning path */
        all[t] = static_cast<uint8_t>(state & 1);  /* the input bit that led into this state */
        state = pred[choices[static_cast<size_t>(t) * kStates + state]][state];  /* step back */
    }  /* end of the traceback */
    std::memcpy(bits, all.data(), static_cast<size_t>(steps - kTail));  /* the data bits, without the tail */
    return steps - kTail;  /* how many */
}  /* end of kes_viterbi_decode */

KES_API int kes_band_energies(const double *x, size_t n, double start, size_t nsym, size_t samples,
                              double offset_hz, double drift_hz_s, size_t lo, size_t hi, double *out) {  /* tone blocks -> energy per FFT bin */
    if (samples == 0 || hi < lo || hi >= samples) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    long first = static_cast<long>(std::nearbyint(start));  /* the first sample, rounded half to even as Python's round() does */
    size_t need = nsym * samples;  /* samples needed for all the blocks */
    std::vector<std::complex<double>> blocks(need);  /* the shifted audio, block after block */
    /* The turning (mixer) for sample k is exp(-2 pi i (f t + d t t / 2)) with t = k / rate. Working out a sine and
     * cosine for every sample is slow, so they are worked out exactly only every kAnchor samples; in between,
     * each sample's turning is the previous one times a small step turn, and the step turn itself changes by a
     * fixed turn per sample (because the phase is a quadratic in k). The rounding error this adds over
     * kAnchor samples is around a millionth of a millionth, far below anything the decoder can notice. */
    const double scale = -2.0 * kPi;  /* the phase per unit of (f t + d t t / 2) */
    const double dt = 1.0 / kSampleRate;  /* the time between samples */
    for (size_t k0 = 0; k0 < need; k0 += kAnchor) {  /* each stretch of kAnchor samples */
        double t0 = static_cast<double>(k0) / kSampleRate;  /* the time of the stretch's first sample */
        double phase = scale * (offset_hz * t0 + 0.5 * drift_hz_s * t0 * t0);  /* its phase, worked out exactly */
        std::complex<double> turn(std::cos(phase), std::sin(phase));  /* its turning */
        double first_step = scale * (offset_hz * dt + 0.5 * drift_hz_s * dt * (2.0 * t0 + dt));  /* the phase change from its first sample to the next */
        std::complex<double> step(std::cos(first_step), std::sin(first_step));  /* as a turn */
        double bend = scale * drift_hz_s * dt * dt;  /* how much the phase change grows from one sample to the next */
        std::complex<double> grow(std::cos(bend), std::sin(bend));  /* as a turn */
        size_t end = std::min(need, k0 + kAnchor);  /* the end of the stretch */
        for (size_t k = k0; k < end; ++k) {  /* each sample in it */
            long at = first + static_cast<long>(k);  /* its place in x */
            double value = (at >= 0 && static_cast<size_t>(at) < n) ? x[at] : 0.0;  /* the audio there, or silence outside it */
            blocks[k] = value * turn;  /* the sample, shifted down */
            turn = times(turn, step);  /* the next sample's turning */
            step = times(step, grow);  /* and the next step */
        }  /* end of the stretch */
    }  /* end of the samples */
    pocketfft::shape_t shape{nsym, samples};  /* the blocks as a table: one row per block */
    pocketfft::stride_t stride{static_cast<ptrdiff_t>(samples * sizeof(std::complex<double>)), static_cast<ptrdiff_t>(sizeof(std::complex<double>))};  /* the step between rows and between samples, in bytes */
    std::vector<std::complex<double>> spectrum(need);  /* each block's spectrum */
    pocketfft::c2c(shape, stride, stride, {1}, pocketfft::FORWARD, blocks.data(), spectrum.data(), 1.0);  /* transform every row (unscaled, as NumPy's fft is) */
    size_t width = hi - lo + 1;  /* bins kept per block */
    for (size_t r = 0; r < nsym; ++r) {  /* each block */
        for (size_t c = 0; c < width; ++c) {  /* each bin kept */
            std::complex<double> v = spectrum[r * samples + lo + c];  /* its value */
            double size = std::abs(v);  /* its size, as NumPy's abs of a complex number gives it */
            out[r * width + c] = size * size;  /* its energy */
        }  /* end of the bins */
    }  /* end of the blocks */
    return 0;  /* done */
}  /* end of kes_band_energies */

KES_API int kes_detect_preamble(const double *x, size_t n, size_t samples, const int *bins, size_t ntones, int pad, int hops,
                                int reach, int whiten, int keep, long *rows, int *shifts, double *quality) {  /* the coarse pattern search */
    if (samples == 0 || ntones == 0 || pad < 1 || hops < 1 || keep < 1) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    long hop = static_cast<long>(samples) / hops;  /* the step between blocks, in samples */
    if (hop < 1 || n < samples) {  /* no step, or not even one block */
        return 0;  /* nothing to find */
    }  /* end of the short case */
    long count = static_cast<long>((n - samples) / hop) + 1;  /* how many blocks fit */
    long starts = count - hops * static_cast<long>(ntones - 1);  /* start positions that leave room for the whole pattern */
    if (starts < 1) {  /* too short to hold the pattern */
        return 0;  /* nothing to find */
    }  /* end of the short case */
    int lowest = *std::min_element(bins, bins + ntones), highest = *std::max_element(bins, bins + ntones);  /* the pattern's lowest and highest tone, in fine steps */
    long low = lowest - reach - 1, high = highest + reach + 2;  /* the only part of the spectrum that matters */
    size_t length = static_cast<size_t>(pad) * samples;  /* the padded transform length */
    if (low < 0 || static_cast<size_t>(high) > length / 2 + 1) {  /* the band would run off the spectrum */
        return -1;  /* refuse */
    }  /* end of the check */
    size_t width = static_cast<size_t>(high - low);  /* fine steps kept per block */
    std::vector<double> power(static_cast<size_t>(count) * width);  /* the energy near the pattern's tones, block by block */
    const size_t chunk = 256;  /* blocks transformed at a time, at most, to keep memory modest */
    parallel_for(static_cast<size_t>(count), 16, [&](size_t block_from, size_t block_to) {  /* the blocks, shared among threads */
        size_t rows_most = std::min(chunk, block_to - block_from);  /* the most blocks this thread transforms at once */
        std::vector<double> padded(rows_most * length, 0.0);  /* the blocks, each followed by zeros */
        std::vector<std::complex<double>> spectrum(rows_most * (length / 2 + 1));  /* their spectra */
        for (size_t first = block_from; first < block_to; first += rows_most) {  /* a batch of blocks at a time */
            size_t rows_here = std::min(rows_most, block_to - first);  /* blocks in this batch */
            for (size_t r = 0; r < rows_here; ++r) {  /* each block */
                const double *from = x + (first + r) * static_cast<size_t>(hop);  /* its first sample */
                std::memcpy(padded.data() + r * length, from, samples * sizeof(double));  /* the audio (the rest of the row stays zero) */
            }  /* end of the blocks */
            pocketfft::shape_t shape{rows_here, length};  /* a table: one row per block */
            pocketfft::stride_t in_stride{static_cast<ptrdiff_t>(length * sizeof(double)), static_cast<ptrdiff_t>(sizeof(double))};  /* steps through the input */
            pocketfft::stride_t out_stride{static_cast<ptrdiff_t>((length / 2 + 1) * sizeof(std::complex<double>)), static_cast<ptrdiff_t>(sizeof(std::complex<double>))};  /* and the output */
            pocketfft::r2c(shape, in_stride, out_stride, 1, pocketfft::FORWARD, padded.data(), spectrum.data(), 1.0);  /* transform each row (as NumPy's rfft) */
            for (size_t r = 0; r < rows_here; ++r) {  /* each block */
                double *row = power.data() + (first + r) * width;  /* where its energies go */
                const std::complex<double> *spec = spectrum.data() + r * (length / 2 + 1) + low;  /* its spectrum, from the band's bottom */
                for (size_t c = 0; c < width; ++c) {  /* each fine step kept */
                    double size = std::abs(spec[c]);  /* its size */
                    row[c] = size * size;  /* its energy */
                }  /* end of the steps */
            }  /* end of the blocks */
        }  /* end of the batches */
    });  /* end of the shared loop */
    if (whiten) {  /* level out the band first: each frequency in units of its own typical level */
        double top = *std::max_element(power.begin(), power.end());  /* the strongest energy anywhere */
        parallel_for(width, 8, [&](size_t column_from, size_t column_to) {  /* the frequencies, shared among threads */
            std::vector<double> column(static_cast<size_t>(count));  /* one frequency's energies through the recording */
            for (size_t c = column_from; c < column_to; ++c) {  /* each frequency in this share */
                for (long r = 0; r < count; ++r) {  /* each block */
                    column[static_cast<size_t>(r)] = power[static_cast<size_t>(r) * width + c];  /* copied out */
                }  /* end of the copy */
                double typical = median_inplace(column.data(), column.size()) + 1e-9 * top + 1e-30;  /* its typical level (with a floor, as the Python has) */
                for (long r = 0; r < count; ++r) {  /* each block */
                    power[static_cast<size_t>(r) * width + c] /= typical;  /* scaled */
                }  /* end of the scaling */
            }  /* end of the frequencies */
        });  /* end of the shared loop */
    }  /* end of whitening */
    long nshift = 2L * reach + 1;  /* the frequency errors tried */
    std::vector<double> total(static_cast<size_t>(starts * nshift), 0.0);  /* the pattern's energy for every start and frequency error */
    parallel_for(static_cast<size_t>(starts), 512, [&](size_t start_from, size_t start_to) {  /* the starts, shared among threads */
        for (size_t k = 0; k < ntones; ++k) {  /* one tone of the pattern at a time, in order (as the Python adds them) */
            long base = bins[k] - low - reach;  /* the column of this tone at the most negative error */
            for (long r = static_cast<long>(start_from); r < static_cast<long>(start_to); ++r) {  /* each start in this share */
                const double *row = power.data() + static_cast<size_t>(hops * static_cast<long>(k) + r) * width + base;  /* this tone's block, from that column */
                double *out = total.data() + static_cast<size_t>(r * nshift);  /* this start's totals */
                for (long j = 0; j < nshift; ++j) {  /* each frequency error */
                    out[j] += row[j];  /* add the energy where the tone should be */
                }  /* end of the errors */
            }  /* end of the starts */
        }  /* end of the tones */
    });  /* end of the shared loop */
    std::vector<double> scratch(total);  /* a copy to find the median in */
    double background = median_inplace(scratch.data(), scratch.size()) + 1e-30;  /* the typical total when nothing is there */
    std::vector<double> block_energy(static_cast<size_t>(count));  /* all the energy near the band in each block */
    for (long r = 0; r < count; ++r) {  /* each block */
        double sum = 0.0;  /* its total */
        for (size_t c = 0; c < width; ++c) {  /* each fine step */
            sum += power[static_cast<size_t>(r) * width + c];  /* added */
        }  /* end of the steps */
        block_energy[static_cast<size_t>(r)] = sum;  /* kept */
    }  /* end of the blocks */
    std::vector<double> work(static_cast<size_t>(starts * nshift));  /* the ranking score: the total weighted by how cleanly it matches */
    for (long r = 0; r < starts; ++r) {  /* each start */
        double in_blocks = 0.0;  /* the energy in the twelve blocks this start would use */
        for (size_t k = 0; k < ntones; ++k) {  /* each of them */
            in_blocks += block_energy[static_cast<size_t>(hops * static_cast<long>(k) + r)];  /* added in order */
        }  /* end of the blocks */
        in_blocks += 1e-30;  /* never zero */
        for (long j = 0; j < nshift; ++j) {  /* each frequency error */
            double t = total[static_cast<size_t>(r * nshift + j)];  /* the total */
            double share = t / in_blocks;  /* how much of the energy sits where the pattern says */
            work[static_cast<size_t>(r * nshift + j)] = t * (share * share);  /* the score (as total * share ** 2) */
        }  /* end of the errors */
    }  /* end of the starts */
    for (int found = 0; found < keep; ++found) {  /* the strongest few */
        size_t best = static_cast<size_t>(std::max_element(work.begin(), work.end()) - work.begin());  /* the largest score left (the first, if tied) */
        long row = static_cast<long>(best) / nshift, col = static_cast<long>(best) % nshift;  /* its start and frequency error */
        rows[found] = row;  /* the start, in steps of a quarter tone */
        shifts[found] = static_cast<int>(col - reach);  /* the frequency error, in fine steps */
        quality[found] = work[best] / background;  /* how far it stands above the background */
        long from = std::max(row - hops, 0L), to = std::min(row + hops, starts - 1);  /* everything within a tone of it */
        std::fill(work.begin() + from * nshift, work.begin() + (to + 1) * nshift, 0.0);  /* crossed off */
    }  /* end of the candidates */
    return keep;  /* how many were written */
}  /* end of kes_detect_preamble */

KES_API int kes_fine_time(const double *x, size_t n, size_t samples, const int *bins, size_t ntones, int pad, int hops,
                          int shift, double coarse_start, double *start_out, double *steps_out) {  /* refine one candidate */
    if (samples == 0 || ntones == 0 || pad < 1 || hops < 1) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    long tone = static_cast<long>(samples);  /* tone length in samples */
    long hop = tone / hops;  /* the coarse search's step */
    long span_all = tone * static_cast<long>(ntones);  /* the pattern's length */
    long last = static_cast<long>(n) - span_all;  /* the latest start that leaves room for the pattern */
    if (last < 0 || hop < 1) {  /* too little audio */
        return 1;  /* nothing to refine: the caller keeps the coarse answer */
    }  /* end of the short case */
    long length = static_cast<long>(pad) * tone;  /* the padded transform length the Python uses */
    std::vector<double> cosine(static_cast<size_t>(length)), sine(static_cast<size_t>(length));  /* the turning for every step round the circle */
    for (long m = 0; m < length; ++m) {  /* each step */
        double angle = (-2.0 * kPi) * static_cast<double>(m) / static_cast<double>(length);  /* its angle */
        cosine[static_cast<size_t>(m)] = std::cos(angle);  /* its cosine */
        sine[static_cast<size_t>(m)] = std::sin(angle);  /* and sine */
    }  /* end of the table */
    /* The energy of the pattern cut into tones from `begin`, at the pattern's own frequencies (offset by `extra` fine
     * steps). Each tone needs only one frequency, so it is worked out directly rather than by a whole transform. */
    auto energy_at = [&](long begin, int extra) {  /* one sum of energies */
        double sum = 0.0;  /* the total */
        for (size_t k = 0; k < ntones; ++k) {  /* each tone of the pattern */
            long bin = static_cast<long>(bins[k]) + shift + extra;  /* the frequency looked at, in fine steps */
            bin = ((bin % length) + length) % length;  /* kept on the circle */
            const double *piece = x + begin + static_cast<long>(k) * tone;  /* this tone's audio */
            double re = 0.0, im = 0.0;  /* the transform at that one frequency */
            long index = 0;  /* (bin * m) modulo the length, stepped without multiplying */
            for (long m = 0; m < tone; ++m) {  /* each sample */
                re += piece[m] * cosine[static_cast<size_t>(index)];  /* real part */
                im += piece[m] * sine[static_cast<size_t>(index)];  /* imaginary part */
                index += bin;  /* the next sample's step round the circle */
                if (index >= length) {  /* past a full turn */
                    index -= length;  /* back round */
                }  /* end of the wrap */
            }  /* end of the samples */
            sum += re * re + im * im;  /* its energy */
        }  /* end of the tones */
        return sum;  /* the pattern's energy */
    };  /* end of energy_at */
    long row = static_cast<long>(std::nearbyint(coarse_start / static_cast<double>(hop)));  /* the coarse start, in quarter tones (rounded as Python's round()) */
    long centre = std::min(std::max(row * hop, 0L), last);  /* the search starts there, kept inside the audio */
    long reach_samples = hop;  /* a quarter of a tone either side */
    std::vector<long> trial;  /* the start times tried at the last stage */
    std::vector<double> scores;  /* and the pattern's energy at each */
    long top = 0, step = 1;  /* the best trial, and the last stage's step */
    for (int stage = 0; stage < 2; ++stage) {  /* a sixteenth of a tone at a time, then an eighth of that */
        step = std::max(tone / (stage == 0 ? 16 : 128), 1L);  /* this stage's step */
        long span = reach_samples / step;  /* steps to look each side of the centre */
        trial.clear();  /* start afresh */
        scores.clear();  /* likewise */
        for (long k = -span; k <= span; ++k) {  /* each start time */
            long at = centre + k * step;  /* where */
            if (at >= 0 && at <= last) {  /* inside the audio */
                trial.push_back(at);  /* tried */
                scores.push_back(energy_at(at, 0));  /* its energy */
            }  /* end of the test */
        }  /* end of the start times */
        top = static_cast<long>(std::max_element(scores.begin(), scores.end()) - scores.begin());  /* the best (the first, if tied) */
        centre = trial[static_cast<size_t>(top)];  /* look more finely around it next */
        reach_samples = step;  /* one step either side */
    }  /* end of the stages */
    double here = scores[static_cast<size_t>(top)];  /* the energy at the best start */
    double below = energy_at(centre, -1), above = energy_at(centre, 1);  /* and half a bin either side in frequency */
    double bend = below - 2 * here + above;  /* how sharply the energy peaks across frequency */
    double nudge = bend < 0 ? 0.5 * (below - above) / bend : 0.0;  /* where the true peak lies between fine steps */
    double start = static_cast<double>(centre);  /* the best start found */
    if (top > 0 && top < static_cast<long>(trial.size()) - 1) {  /* a neighbour on each side */
        double early = scores[static_cast<size_t>(top - 1)], late = scores[static_cast<size_t>(top + 1)];  /* one step earlier and later */
        double curve = early - 2 * here + late;  /* how sharply the energy peaks across time */
        if (curve < 0) {  /* a true peak */
            start += 0.5 * (early - late) / curve * static_cast<double>(step);  /* the top of the parabola */
        }  /* end of the peak */
    }  /* end of the time refinement */
    *start_out = start;  /* the refined start */
    *steps_out = static_cast<double>(shift) + nudge;  /* the refined frequency error, in fine steps */
    return 0;  /* done */
}  /* end of kes_fine_time */

}  /* end of the exported functions (first part) */

namespace {  /* more private helpers, for the header reader */

const int kTones = 32;  /* tones in every level's alphabet (modem/params.py M_TONES) */
const int kBitsPerTone = 5;  /* bits each tone carries (BITS_PER_SYMBOL) */
const int kHeaderTones = 12;  /* tones in one header copy (frame.py HEADER_SYMBOLS_ONCE) */
const int kHeaderCoded = 60;  /* coded bits in one header copy (HEADER_CODED_BITS) */
const int kHeaderFields = 16;  /* header field bits before the check value (HEADER_FIELD_BITS) */
const int kHeaderBits = 24;  /* field bits and the 8-bit check value */

/* The soft bits of one header copy whose first tone starts at sample `start` (frame.py _header_llrs):
 * measure the copy's tones, judge them against the noise (mfsk.py noise_level) and turn each tone's
 * energies into five soft bits (mfsk.py energies_to_llrs). Writes kHeaderCoded values to llrs. */
void header_llrs(const double *x, size_t n, double start, double offset_hz, size_t samples, size_t lo, size_t hi, int step, double *llrs) {  /* one header copy -> soft bits */
    size_t width = hi - lo + 1;  /* bins measured per tone */
    std::vector<double> band(static_cast<size_t>(kHeaderTones) * width);  /* the band's energies, tone by tone */
    kes_band_energies(x, n, start, kHeaderTones, samples, offset_hz, 0.0, lo, hi, band.data());  /* measured */
    double tone_e[kHeaderTones * kTones];  /* the 32 tone positions of each tone */
    double top = 0.0;  /* the strongest of them */
    for (int r = 0; r < kHeaderTones; ++r) {  /* each tone of the copy */
        for (int m = 0; m < kTones; ++m) {  /* each tone position */
            double e = band[static_cast<size_t>(r) * width + 1 + static_cast<size_t>(m * step)];  /* column 1 + m * step (mfsk.py tone_energies) */
            tone_e[r * kTones + m] = e;  /* kept */
            top = std::max(top, e);  /* the strongest so far */
        }  /* end of the positions */
    }  /* end of the tones */
    double scratch[kHeaderTones * kTones];  /* a copy to find the median in */
    std::memcpy(scratch, tone_e, sizeof scratch);  /* copied */
    double floor = 1e-12 * top + 1e-300;  /* never zero */
    double noise = std::max(median_inplace(scratch, kHeaderTones * kTones) / std::log(2.0), floor);  /* the noise per tone position (median / ln 2) */
    for (int r = 0; r < kHeaderTones; ++r) {  /* each tone */
        for (int j = 0; j < kBitsPerTone; ++j) {  /* each of its five bits, most significant first */
            double zero = -1.0, one = -1.0;  /* the strongest tone whose bit j is 0, and is 1 (energies are never negative) */
            for (int m = 0; m < kTones; ++m) {  /* each tone position */
                double e = tone_e[r * kTones + m];  /* its energy */
                if ((m >> (kBitsPerTone - 1 - j)) & 1) {  /* bit j is 1 */
                    one = std::max(one, e);  /* the strongest such */
                } else {  /* bit j is 0 */
                    zero = std::max(zero, e);  /* likewise */
                }  /* end of the test */
            }  /* end of the positions */
            int index = r * kBitsPerTone + j;  /* where this soft bit goes */
            if (index < kHeaderCoded) {  /* padding dropped */
                llrs[index] = (zero - one) / noise;  /* the confidence: positive means probably 0 */
            }  /* end of the test */
        }  /* end of the bits */
    }  /* end of the tones */
}  /* end of header_llrs */

/* CRC-8 (polynomial 0x07, start 0) of bits[0..count), as modem/crc.py crc8 computes it. */
int crc8_bits(const uint8_t *bits, int count) {  /* the header's check value */
    int reg = 0;  /* the register */
    for (int i = 0; i < count; ++i) {  /* one bit at a time */
        int top = (reg >> 7) & 1;  /* the bit about to fall off the top */
        reg = (reg << 1) & 0xFF;  /* shift */
        if (top ^ bits[i]) {  /* they differ */
            reg ^= 0x07;  /* mix in the polynomial */
        }  /* end of the test */
    }  /* end of the bits */
    return reg;  /* the check value */
}  /* end of crc8_bits */

/* Decode soft header bits and check them (frame.py _check_header): true, with the 24 header bits in `bits`,
 * when the check value matches, the level field names `level` and the spare bit is clear. */
bool check_header(const double *llrs, int level, uint8_t *bits) {  /* decode and check */
    uint8_t decoded[kHeaderCoded / 2];  /* room for the decoder's output */
    long got = kes_viterbi_decode(llrs, kHeaderCoded, decoded);  /* correct errors */
    if (got != kHeaderBits) {  /* not the expected length (cannot happen for a whole copy) */
        return false;  /* no */
    }  /* end of the check */
    int check = 0;  /* the received check value */
    for (int i = 0; i < 8; ++i) {  /* its eight bits, most significant first */
        check = (check << 1) | decoded[kHeaderFields + i];  /* gathered */
    }  /* end of the bits */
    int named = (decoded[3] << 2) | (decoded[4] << 1) | decoded[5];  /* the level the header names */
    if (crc8_bits(decoded, kHeaderFields) != check || named != level || decoded[15] != 0) {  /* any of the three tests fails */
        return false;  /* no */
    }  /* end of the tests */
    std::memcpy(bits, decoded, kHeaderBits);  /* the header */
    return true;  /* this may be a frame */
}  /* end of check_header */

}  /* end of the header reader's helpers */

extern "C" {  /* the exported functions, continued */

KES_API int kes_read_header(const double *x, size_t n, double header_start, double offset_hz, size_t samples, size_t lo, size_t hi,
                            int step, int level, const int *totals_by_type, const int *body_totals, size_t nbody, double since,
                            uint8_t *bits) {  /* frame.py _read_header_how */
    if (samples == 0 || hi < lo || hi >= samples || step < 1) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    double length = static_cast<double>(n);  /* the recording's length, as a number */
    double copy = static_cast<double>(kHeaderTones) * static_cast<double>(samples);  /* one header copy's length */
    if (header_start < 0 || header_start + copy > length) {  /* the first copy is not (yet) wholly inside */
        return 0;  /* nothing to read */
    }  /* end of the check */
    double first[kHeaderCoded], second[kHeaderCoded], both[kHeaderCoded];  /* soft bits of each copy, and their sum */
    header_llrs(x, n, header_start, offset_hz, samples, lo, hi, step, first);  /* the first copy */
    if (since < 0 && check_header(first, level, bits)) {  /* tried alone (unless it was tried before), and it checked out */
        return 1;  /* "first": the usual case */
    }  /* end of the first copy */
    double quarter = static_cast<double>(samples / 4);  /* a quarter of a tone (rounded down, as samples // 4) */
    for (size_t i = 0; i < nbody; ++i) {  /* every place the second copy could be */
        int total = body_totals[i];  /* a body length, in tones */
        double second_start = header_start + static_cast<double>(kHeaderTones + total) * static_cast<double>(samples);  /* just after such a body */
        if (second_start + copy > length + quarter) {  /* not (yet) inside the recording */
            continue;  /* cannot try this length yet */
        }  /* end of the check */
        if (since >= 0 && second_start + copy <= since) {  /* tried before, with the whole copy there */
            continue;  /* nothing new here */
        }  /* end of the check */
        header_llrs(x, n, second_start, offset_hz, samples, lo, hi, step, second);  /* the second copy */
        for (int k = 0; k < kHeaderCoded; ++k) {  /* each soft bit */
            both[k] = first[k] + second[k];  /* the two copies added */
        }  /* end of the sum */
        const double *tries[2] = {both, second};  /* both copies together, then the second alone */
        for (int t = 0; t < 2; ++t) {  /* each */
            if (check_header(tries[t], level, bits)) {  /* it checked out */
                int frame_type = (bits[0] << 2) | (bits[1] << 1) | bits[2];  /* the frame type it names */
                int size_class = (bits[6] << 1) | bits[7];  /* and the size class */
                if (totals_by_type[frame_type * 4 + size_class] == total) {  /* its own fields give the body length it was read at */
                    return t == 0 ? 2 : 3;  /* "both" or "second" */
                }  /* end of the agreement */
            }  /* end of the check */
        }  /* end of the tries */
    }  /* end of the places */
    return 0;  /* no header here */
}  /* end of kes_read_header */

KES_API int kes_ldpc_decode(const double *llrs, long k, const long *edge_bits, const long *edge_checks, long nedges, const long *starts,
                            double scale, int max_iterations, uint8_t *bits) {  /* modem/ldpc.py decode: normalised min-sum */
    if (k < 1 || nedges < 1) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    long nbits = 2 * k;  /* the codeword: k data bits then k parity bits */
    std::vector<double> to_check(static_cast<size_t>(nedges)), to_bit(static_cast<size_t>(nedges));  /* the messages along every edge, each way */
    std::vector<double> total(llrs, llrs + nbits), sums(static_cast<size_t>(nbits));  /* the belief about every bit, and the check messages added up */
    std::vector<double> low(static_cast<size_t>(k)), second(static_cast<size_t>(k));  /* per check: the least confident message, and the next */
    std::vector<long> ties(static_cast<size_t>(k));  /* per check: how many edges carry that least confidence */
    std::vector<int> odd(static_cast<size_t>(k));  /* per check: is the number of "1" votes odd? */
    const double inf = std::numeric_limits<double>::infinity();  /* larger than any message */
    for (long e = 0; e < nedges; ++e) {  /* every edge */
        to_check[static_cast<size_t>(e)] = llrs[edge_bits[e]];  /* starts as the received value of its bit */
    }  /* end of the edges */
    auto check_end = [&](long c) { return c + 1 < k ? starts[c + 1] : nedges; };  /* where check c's edges end */
    for (int round = 0; round < max_iterations; ++round) {  /* repeat until satisfied, or give up */
        for (long c = 0; c < k; ++c) {  /* each check */
            double least = inf;  /* the least confident message into it */
            long count = 0;  /* how many tie for least */
            int parity = 0;  /* the parity of its "1" votes */
            for (long e = starts[c]; e < check_end(c); ++e) {  /* each of its edges */
                double mag = std::fabs(to_check[static_cast<size_t>(e)]);  /* that message's confidence */
                least = std::min(least, mag);  /* the least so far */
                parity ^= to_check[static_cast<size_t>(e)] < 0 ? 1 : 0;  /* its vote */
            }  /* end of the edges */
            double runner = inf;  /* the least among the others */
            for (long e = starts[c]; e < check_end(c); ++e) {  /* each edge again */
                double mag = std::fabs(to_check[static_cast<size_t>(e)]);  /* its confidence */
                if (mag == least) {  /* carries the least */
                    ++count;  /* one more tie */
                } else {  /* does not */
                    runner = std::min(runner, mag);  /* a candidate for second */
                }  /* end of the test */
            }  /* end of the edges */
            low[static_cast<size_t>(c)] = least;  /* kept */
            ties[static_cast<size_t>(c)] = count;  /* kept */
            second[static_cast<size_t>(c)] = count > 1 ? least : runner;  /* with a tie, the runner-up equals the minimum */
            odd[static_cast<size_t>(c)] = parity;  /* kept */
        }  /* end of the checks */
        std::fill(sums.begin(), sums.end(), 0.0);  /* the check messages, added up per bit, start at zero */
        for (long e = 0; e < nedges; ++e) {  /* every edge, in order (as NumPy's bincount adds them) */
            long c = edge_checks[e];  /* its check */
            double mag = std::fabs(to_check[static_cast<size_t>(e)]);  /* its incoming confidence */
            bool is_low = mag == low[static_cast<size_t>(c)];  /* it carries the least */
            double out_mag = (is_low && ties[static_cast<size_t>(c)] == 1) ? second[static_cast<size_t>(c)] : low[static_cast<size_t>(c)];  /* each edge hears the minimum of the others */
            int neg = to_check[static_cast<size_t>(e)] < 0 ? 1 : 0;  /* its own vote */
            int out_neg = odd[static_cast<size_t>(c)] ^ neg;  /* the parity of the others */
            double message = scale * out_mag * (1.0 - 2.0 * out_neg);  /* the message back to the bit */
            to_bit[static_cast<size_t>(e)] = message;  /* kept */
            sums[static_cast<size_t>(edge_bits[e])] += message;  /* added to its bit */
        }  /* end of the edges */
        for (long b = 0; b < nbits; ++b) {  /* every bit */
            total[static_cast<size_t>(b)] = llrs[b] + sums[static_cast<size_t>(b)];  /* the received value plus all check messages */
        }  /* end of the bits */
        bool satisfied = true;  /* do all checks hold? */
        for (long c = 0; c < k && satisfied; ++c) {  /* each check, until one fails */
            int parity = 0;  /* the parity of its bits' current guesses */
            for (long e = starts[c]; e < check_end(c); ++e) {  /* each edge */
                parity ^= total[static_cast<size_t>(edge_bits[e])] < 0 ? 1 : 0;  /* that bit's guess */
            }  /* end of the edges */
            satisfied = parity == 0;  /* holds or not */
        }  /* end of the checks */
        if (satisfied) {  /* the codeword checks out */
            for (long b = 0; b < k; ++b) {  /* the data bits */
                bits[b] = total[static_cast<size_t>(b)] < 0 ? 1 : 0;  /* their decisions */
            }  /* end of the bits */
            return 1;  /* every check satisfied */
        }  /* end of the success */
        for (long e = 0; e < nedges; ++e) {  /* every edge */
            to_check[static_cast<size_t>(e)] = total[static_cast<size_t>(edge_bits[e])] - to_bit[static_cast<size_t>(e)];  /* each bit tells a check everything except what that check said */
        }  /* end of the edges */
    }  /* end of the rounds */
    for (long b = 0; b < k; ++b) {  /* gave up: the data bits */
        bits[b] = total[static_cast<size_t>(b)] < 0 ? 1 : 0;  /* best guesses */
    }  /* end of the bits */
    return 0;  /* not every check satisfied */
}  /* end of kes_ldpc_decode */

KES_API int kes_noise_profile(const double *tone_e, size_t rows, int span, int tracking, double *level) {  /* modem/mfsk.py noise_profile */
    if (rows == 0 || span < 0) {  /* nothing to do */
        return -1;  /* refuse */
    }  /* end of the check */
    size_t cells = rows * kTones;  /* every tone position of every symbol */
    double top = *std::max_element(tone_e, tone_e + cells);  /* the strongest energy */
    std::vector<double> scratch(tone_e, tone_e + cells);  /* a copy to find the median in */
    double whole = std::max(median_inplace(scratch.data(), cells) / std::log(2.0), 1e-12 * top + 1e-300);  /* the level over the whole frame (mfsk.py noise_level) */
    size_t width = 2 * static_cast<size_t>(span) + 1;  /* symbols in each neighbourhood */
    if (!tracking || rows < width) {  /* tracking off, or the frame too short to track within */
        std::fill(level, level + rows, whole);  /* one level throughout */
        return 0;  /* done */
    }  /* end of the simple case */
    std::vector<double> window(width * kTones);  /* one neighbourhood's energies */
    for (size_t i = 0; i < rows; ++i) {  /* each symbol */
        for (size_t w = 0; w < width; ++w) {  /* each symbol of its neighbourhood, mirrored at the frame's ends (as the Python pads) */
            long at = static_cast<long>(i + w) - span;  /* its place in the frame */
            if (at < 0) {  /* before the first symbol */
                at = -at;  /* mirrored: rows span, span - 1, ... 1 */
            } else if (at >= static_cast<long>(rows)) {  /* after the last */
                at = 2 * static_cast<long>(rows) - 2 - at;  /* mirrored: rows n - 2, n - 3, ... */
            }  /* end of the mirroring */
            std::memcpy(window.data() + w * kTones, tone_e + static_cast<size_t>(at) * kTones, kTones * sizeof(double));  /* its 32 energies */
        }  /* end of the neighbourhood */
        double local = median_inplace(window.data(), window.size()) / std::log(2.0);  /* the middle value, as an average noise energy */
        level[i] = std::max(local, 0.1 * whole);  /* never wildly below the frame's own level */
    }  /* end of the symbols */
    return 0;  /* done */
}  /* end of kes_noise_profile */

KES_API int kes_pilot_fit(const double *x, size_t n, double start, const long *positions, const int *tones, size_t npilots, size_t samples,
                          const int *tone_bins, int pad, int fine_span, double offset_hz, double *extra_out, double *drift_out) {  /* modem/mfsk.py pilot_frequency_fit */
    if (npilots == 0 || samples == 0 || pad < 1 || fine_span < 0) {  /* nonsense */
        return -1;  /* refuse */
    }  /* end of the check */
    size_t length = static_cast<size_t>(pad) * samples;  /* the padded transform length */
    std::vector<double> cosine(length), sine(length);  /* the turning for every step round the circle */
    for (size_t m = 0; m < length; ++m) {  /* each step */
        double angle = (-2.0 * kPi) * static_cast<double>(m) / static_cast<double>(length);  /* its angle */
        cosine[m] = std::cos(angle);  /* its cosine */
        sine[m] = std::sin(angle);  /* and sine */
    }  /* end of the table */
    double bin_hz = kSampleRate / static_cast<double>(samples);  /* one FFT bin, in hertz */
    size_t groups = std::max<size_t>(1, npilots / 8);  /* stretches of about eight pilots */
    double track = 0.0;  /* the frequency error found so far, on top of the preamble's estimate */
    std::vector<double> times, errors;  /* each stretch's middle time and measured error */
    std::vector<double> re(samples), im(samples);  /* one pilot's shifted audio */
    size_t base = npilots / groups, extra_items = npilots % groups;  /* how NumPy's array_split shares the pilots: the first `extra_items` stretches get one more */
    size_t index = 0;  /* the next pilot */
    for (size_t g = 0; g < groups; ++g) {  /* each stretch, in order */
        size_t count = base + (g < extra_items ? 1 : 0);  /* pilots in it */
        std::vector<double> avg(2 * static_cast<size_t>(fine_span) + 1, 0.0);  /* the fine spectra added up */
        double position_sum = 0.0;  /* for the stretch's middle time */
        for (size_t p = index; p < index + count; ++p) {  /* each pilot in the stretch */
            position_sum += static_cast<double>(positions[p]);  /* its position, for the mean */
            long first = static_cast<long>(std::nearbyint(start + static_cast<double>(positions[p] * static_cast<long>(samples))));  /* its first sample (mfsk.py _mixed_blocks rounds) */
            double shift = offset_hz + track;  /* the correction so far */
            for (size_t m = 0; m < samples; ++m) {  /* each sample */
                long at = first + static_cast<long>(m);  /* its place in x */
                double value = (at >= 0 && static_cast<size_t>(at) < n) ? x[at] : 0.0;  /* the audio, or silence outside it */
                double phase = (-2.0 * kPi) * (shift * (static_cast<double>(m) / kSampleRate));  /* the turning that cancels the offset */
                re[m] = value * std::cos(phase);  /* shifted down: real part */
                im[m] = value * std::sin(phase);  /* imaginary part */
            }  /* end of the samples */
            long centre = static_cast<long>(tone_bins[tones[p]]) * pad;  /* where the pilot should be on the fine grid */
            for (int j = -fine_span; j <= fine_span; ++j) {  /* the few fine steps either side */
                long bin = ((centre + j) % static_cast<long>(length) + static_cast<long>(length)) % static_cast<long>(length);  /* that fine frequency, on the circle */
                double sr = 0.0, si = 0.0;  /* the transform there */
                size_t step_index = 0;  /* (bin * m) modulo the length */
                for (size_t m = 0; m < samples; ++m) {  /* each sample */
                    double c = cosine[step_index], s = sine[step_index];  /* the turning */
                    sr += re[m] * c - im[m] * s;  /* real part of the product */
                    si += re[m] * s + im[m] * c;  /* imaginary part */
                    step_index += static_cast<size_t>(bin);  /* the next sample's step */
                    if (step_index >= length) {  /* past a full turn */
                        step_index -= length;  /* back round */
                    }  /* end of the wrap */
                }  /* end of the samples */
                avg[static_cast<size_t>(j + fine_span)] += sr * sr + si * si;  /* its energy, added */
            }  /* end of the fine steps */
        }  /* end of the pilots */
        size_t peak = static_cast<size_t>(std::max_element(avg.begin(), avg.end()) - avg.begin());  /* the fine step with most energy */
        double frac = 0.0;  /* the fraction-of-a-step correction */
        if (peak > 0 && peak < avg.size() - 1) {  /* a neighbour each side */
            double a = avg[peak - 1], b = avg[peak], c = avg[peak + 1];  /* the peak and its neighbours */
            double bend = a - 2 * b + c;  /* how sharply they curve */
            if (bend != 0) {  /* not flat */
                frac = 0.5 * (a - c) / bend;  /* the top of the parabola */
            }  /* end of the test */
        }  /* end of the refinement */
        track += (static_cast<double>(peak) + frac - fine_span) * bin_hz / pad;  /* move to where this stretch found the signal */
        errors.push_back(track);  /* recorded */
        times.push_back(position_sum / static_cast<double>(count) * (static_cast<double>(samples) / kSampleRate));  /* and when */
        index += count;  /* on to the next stretch */
    }  /* end of the stretches */
    if (groups >= 2) {  /* a trend can be seen */
        double mean_t = 0.0, mean_e = 0.0;  /* the averages */
        for (size_t g = 0; g < groups; ++g) {  /* each stretch */
            mean_t += times[g];  /* added */
            mean_e += errors[g];  /* added */
        }  /* end of the sums */
        mean_t /= static_cast<double>(groups);  /* the mean time */
        mean_e /= static_cast<double>(groups);  /* the mean error */
        double sxy = 0.0, sxx = 0.0;  /* the least-squares sums */
        for (size_t g = 0; g < groups; ++g) {  /* each stretch */
            sxy += (times[g] - mean_t) * (errors[g] - mean_e);  /* how time and error move together */
            sxx += (times[g] - mean_t) * (times[g] - mean_t);  /* how time spreads */
        }  /* end of the sums */
        double slope = sxx > 0 ? sxy / sxx : 0.0;  /* the straight line's slope: the drift */
        *extra_out = mean_e - slope * mean_t;  /* its value at time zero: the error at the start */
        *drift_out = slope;  /* the drift, in hertz per second */
    } else {  /* one stretch only */
        *extra_out = errors[0];  /* a fixed correction */
        *drift_out = 0.0;  /* no drift */
    }  /* end of the fit */
    return 0;  /* done */
}  /* end of kes_pilot_fit */

}  /* end of the exported functions */
