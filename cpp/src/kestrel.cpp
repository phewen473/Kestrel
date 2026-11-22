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
#include <cstring>  /* memcpy */
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

/* 1 when value has an odd number of 1 bits, else 0 (modem/fec.py _parity). */
int parity(int value) {  /* the parity of an integer */
    int ones = 0;  /* count of 1 bits */
    while (value) {  /* until every bit has been looked at */
        ones += value & 1;  /* count the lowest bit */
        value >>= 1;  /* move on to the next */
    }  /* end of the count */
    return ones & 1;  /* odd or even */
}  /* end of parity */

}  /* end of the private helpers */

extern "C" {  /* the exported functions keep their plain C names */

KES_API int kes_abi_version(void) {  /* the interface version built into this library */
    return KES_ABI_VERSION;  /* as defined in kestrel.h */
}  /* end of kes_abi_version */

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
    std::vector<double> scratch(kBlankBlock);  /* room to find one neighbourhood's median */
    for (size_t b = 0; b < blocks; ++b) {  /* each neighbourhood */
        size_t first = b * kBlankBlock;  /* its first sample */
        size_t count = std::min(kBlankBlock, n - first);  /* its length (the last may be short) */
        std::memcpy(scratch.data(), level.data() + first, count * sizeof(double));  /* a copy to reorder */
        typical[b] = median_inplace(scratch.data(), count) / 0.6745;  /* its median, as a typical level */
    }  /* end of the neighbourhoods */
    std::vector<double> positive;  /* every sample size above zero */
    positive.reserve(n);  /* room for all of them */
    for (size_t i = 0; i < n; ++i) {  /* each sample */
        if (level[i] > 0.0) {  /* above zero */
            positive.push_back(level[i]);  /* keep it */
        }  /* end of the test */
    }  /* end of the sizes above zero */
    double quiet = positive.empty() ? 0.0 : median_inplace(positive.data(), positive.size()) / 0.6745;  /* the normal level of the whole recording */
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

}  /* end of the exported functions */
