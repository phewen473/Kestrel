/*
 * kestrel.h - the C interface of the Kestrel modem library (libkestrel).
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0
 * (see LICENSE and NOTICE at the top of the repository).
 *
 * The library holds the parts of the Kestrel modem that need the most
 * computing, written in C++ and offered through plain C functions, so that
 * any language can call them: the Python program (through ctypes), and a
 * later Qt program, a Raspberry Pi build or other software.
 *
 * Every function here does exactly what the Python function named beside
 * it does; the Python modem is the reference, and the tests check that the
 * two agree. Arrays are passed as pointers with their lengths; the caller
 * owns all memory. Numbers are doubles unless said otherwise.
 */

#ifndef KESTREL_H  /* guard against being included twice */
#define KESTREL_H  /* mark it included */

#include <stddef.h>  /* size_t */
#include <stdint.h>  /* fixed-size integer types */

#ifdef _WIN32  /* on Windows the functions must be exported from the DLL */
#  ifdef KESTREL_BUILDING  /* while the library itself is being built */
#    define KES_API __declspec(dllexport)  /* export them */
#  else  /* while a program that uses the library is being built */
#    define KES_API __declspec(dllimport)  /* import them */
#  endif  /* end of the Windows choice */
#else  /* Linux, macOS and others */
#  define KES_API __attribute__((visibility("default")))  /* make them visible outside the library */
#endif  /* end of the platform choice */

#ifdef __cplusplus  /* when included from C++ */
extern "C" {  /* keep plain C names, so other languages can find them */
#endif  /* end of the C++ wrapper's start */

/* The version of this interface. A program checks it before calling anything
 * else, and refuses a library whose interface is not the one it was written
 * for. It changes whenever a function is added, removed or changed. */
#define KES_ABI_VERSION 5  /* the interface described in this file (2: preamble search and fine timing; 3: threads and the header reader; 4: body decoder parts; 5: steady-signal notch, known-bit Viterbi) */
KES_API int kes_abi_version(void);  /* returns KES_ABI_VERSION as built into the library */

/* Threads: the heavy routines share their work among up to 8 threads (never more than the computer has).
 * The results are the same whatever the count. kes_set_threads(0) goes back to the computer's own count. */
KES_API void kes_set_threads(int threads);  /* how many threads to use (0 = the computer's count) */
KES_API int kes_threads(void);  /* how many will be used */

/* modem/blanker.py blank_impulses: copy x[0..n) to out, with samples far above
 * the level of their own tenth-of-a-second neighbourhood set to zero (and
 * `guard` samples either side of each). out may not overlap x. */
KES_API void kes_blank_impulses(const double *x, size_t n, double threshold, int guard, double *out);

/* modem/fec.py viterbi_decode: decode n soft coded bits (positive = probably 0)
 * of the rate-1/2, constraint-length-7 code (generators 171 and 133 octal)
 * into n/2 - 6 data bits, written to bits as 0 or 1. Returns the number of
 * data bits written, or -1 if n is too short. */
KES_API long kes_viterbi_decode(const double *llrs, size_t n, uint8_t *bits);

/* The same decoder with some data bits known in advance (modem/fec.py viterbi_decode(llrs, known)):
 * known[i] is 0 or 1 for a known data bit i, -1 for an unknown one; only paths that agree survive.
 * nknown may be shorter than the data (the rest are unknown). */
KES_API long kes_viterbi_decode_known(const double *llrs, size_t n, const int8_t *known, size_t nknown, uint8_t *bits);

/* modem/mfsk.py band_energies: from audio x[0..n), take nsym blocks of `samples`
 * samples each, the first starting at round(start) (missing audio counts as
 * silence), shift each down by offset_hz plus a drift of drift_hz_s per second,
 * transform it, and write the energy of FFT bins lo..hi inclusive, one row per
 * block, to out (nsym x (hi - lo + 1) values). Returns 0, or -1 on bad
 * arguments. */
KES_API int kes_band_energies(const double *x, size_t n, double start, size_t nsym, size_t samples,
                              double offset_hz, double drift_hz_s, size_t lo, size_t hi, double *out);

/* modem/preamble.py detect_preamble (the coarse search, fine=False): cut x[0..n) into blocks of `samples`
 * samples, samples/hops apart; transform each, padded to pad*samples; for every start and every frequency
 * error from -reach to +reach fine steps, add the energy at the pattern's tones (bins[0..ntones), in fine
 * steps, one tone `hops` blocks after the last); rank by total * share^2 and return the `keep` strongest,
 * crossing off everything within a tone of each. With whiten, each frequency is first divided by its own
 * median. Writes rows (start, in blocks), shifts (frequency error, fine steps) and quality (score over the
 * median score). Returns how many were written (keep, or 0 when x is too short), or -1 on bad arguments. */
KES_API int kes_detect_preamble(const double *x, size_t n, size_t samples, const int *bins, size_t ntones, int pad, int hops,
                                int reach, int whiten, int keep, long *rows, int *shifts, double *quality);

/* modem/preamble.py fine_time: refine a candidate from the coarse search (its start in samples, and its
 * frequency error `shift` in fine steps): search a quarter tone either side in sixteenths, then eighths of
 * that, for the start where the pattern holds most energy, and place the start and the frequency between
 * steps with parabolas. Writes the start (samples) and the frequency error (fine steps, fractional).
 * Returns 0, 1 when there is too little audio to refine (the caller keeps the coarse answer), or -1. */
KES_API int kes_fine_time(const double *x, size_t n, size_t samples, const int *bins, size_t ntones, int pad, int hops,
                          int shift, double coarse_start, double *start_out, double *steps_out);

/* modem/frame.py _read_header_how: read the header after a preamble of level `level`. The tone band is FFT
 * bins lo..hi of `samples`-sample tones, tone m in column 1 + m * step. The first copy starts at
 * header_start; if it does not check out (or since >= 0, meaning it was tried before) the second copy is
 * read after each body length in body_totals[0..nbody), with the first and alone, and accepted only if
 * totals_by_type[frame type * 4 + size class] equals that length (-1 for frame types that do not exist).
 * since >= 0 skips second-copy places tried before (whole copy inside x's length `since`).
 * Writes the 24 header bits. Returns 1 (first copy), 2 (both), 3 (second), 0 (none) or -1 (bad arguments). */
KES_API int kes_read_header(const double *x, size_t n, double header_start, double offset_hz, size_t samples, size_t lo, size_t hi,
                            int step, int level, const int *totals_by_type, const int *body_totals, size_t nbody, double since,
                            uint8_t *bits);

/* modem/ldpc.py decode: normalised min-sum decoding of 2k soft values (positive = probably 0). The code's
 * wiring is given edge by edge, sorted by check: edge_bits[e] and edge_checks[e], with check c's edges
 * from starts[c] (as ldpc.py _graph gives them). Writes k data bits; returns 1 when every check is
 * satisfied, 0 when it gave up after max_iterations rounds, -1 on bad arguments. */
KES_API int kes_ldpc_decode(const double *llrs, long k, const long *edge_bits, const long *edge_checks, long nedges, const long *starts,
                            double scale, int max_iterations, uint8_t *bits);

/* modem/mfsk.py noise_profile: the noise energy per tone position at each of `rows` symbols of tone_e
 * (rows x 32), the median of each symbol and `span` either side (mirrored at the ends) over ln 2, never
 * below a tenth of the whole frame's level; with tracking 0 (or a short frame), the whole frame's level. */
KES_API int kes_noise_profile(const double *tone_e, size_t rows, int span, int tracking, double *level);

/* modem/mfsk.py pilot_frequency_fit: measure the pilots (positions[i] tones after `start`, each sending
 * tone tones[i]) in stretches of about eight, each searched around where the last found the signal, on a
 * grid `pad` times finer than one bin, `fine_span` steps each side; fit a straight line through the
 * stretches. Writes the extra offset at the first symbol (Hz) and the drift (Hz per second). */
KES_API int kes_pilot_fit(const double *x, size_t n, double start, const long *positions, const int *tones, size_t npilots, size_t samples,
                          const int *tone_bins, int pad, int fine_span, double offset_hz, double *extra_out, double *drift_out);

/* modem/notch.py remove_steady: copy x[0..n) to out with every steady signal between low_hz and high_hz
 * notched out. Blocks of `block` samples, each weighted by a Hann window; a step whose 10th-percentile energy over the blocks is `times`
 * the band's median, and `times` the median of the steps within `local_steps` of it, is steady; with none, or
 * more than `most`, nothing is changed. Each notch is
 * `half_hz` either side, cut in one transform of `size` samples (size >= n). Returns how many steps were
 * notched (0 for none), or -1 on bad arguments. */
KES_API int kes_remove_steady(const double *x, size_t n, size_t block, double low_hz, double high_hz, double times, int local_steps, int most,
                              double half_hz, size_t size, double *out);

#ifdef __cplusplus  /* when included from C++ */
}  /* end of the plain C names */
#endif  /* end of the C++ wrapper */

#endif  /* KESTREL_H */
