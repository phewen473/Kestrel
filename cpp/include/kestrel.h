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

/* The continuous receiver's settings, passed to kes_listener_new as an array of doubles in this order
 * (live/listener.py sets them from its own constants and modem/ settings). */
#define KES_CFG_WINDOW 0  /* samples kept */
#define KES_CFG_STEP 1  /* new samples between searches */
#define KES_CFG_LONGEST_FRAME 2  /* samples in the longest frame */
#define KES_CFG_CONTEXT_S 3  /* seconds of background searched before the newest audio */
#define KES_CFG_LONG_EVERY 4  /* the long pattern is looked for on every this-many-th search */
#define KES_CFG_KEEP 5  /* candidates kept per pattern and search */
#define KES_CFG_HEADER_SYMBOLS 6  /* tones in the two header copies together */
#define KES_CFG_PREAMBLE_TONES 7  /* tones in a pattern */
#define KES_CFG_NEAR_QUALITY 8  /* weakest pattern reported as a near miss */
#define KES_CFG_NEAR_QUALITY_MAX 9  /* strongest (above it the measure has broken down) */
#define KES_CFG_BLANK_THRESHOLD 10  /* the blanker's threshold */
#define KES_CFG_BLANK_GUARD 11  /* and guard */
#define KES_CFG_NOTCH_BLOCK 12  /* the steady-signal notch: block length */
#define KES_CFG_NOTCH_LOW 13  /* lowest frequency */
#define KES_CFG_NOTCH_HIGH 14  /* highest frequency */
#define KES_CFG_NOTCH_TIMES 15  /* how far above the band */
#define KES_CFG_NOTCH_LOCAL 16  /* neighbourhood, in steps */
#define KES_CFG_NOTCH_MOST 17  /* most steps notched */
#define KES_CFG_NOTCH_HALF 18  /* half the notch's width, Hz */
#define KES_CFG_LONG_SAMPLES 19  /* samples in a long beacon (pattern and body) */
#define KES_CFG_LONG_CLEAN_LOW 20  /* the long beacon's carrier notch: lowest frequency */
#define KES_CFG_LONG_CLEAN_HIGH 21  /* highest frequency */
#define KES_CFG_LONG_CLEAN_TIMES 22  /* how far above the band */
#define KES_CFG_LONG_CLEAN_MOST 23  /* most steps notched */
#define KES_CFG_LONG_CLEAN_HALF 24  /* half the notch's width, Hz */
#define KES_CFG_PAD 25  /* fine steps per FFT bin in the pattern search */
#define KES_CFG_HOPS 26  /* coarse search steps per tone */
#define KES_CFG_NEAR_SPAN 27  /* samples cut out with a near miss */
#define KES_CFG_COUNT 28  /* how many settings there are */

#ifdef __cplusplus  /* when included from C++ */
extern "C" {  /* keep plain C names, so other languages can find them */
#endif  /* end of the C++ wrapper's start */

/* The version of this interface. A program checks it before calling anything
 * else, and refuses a library whose interface is not the one it was written
 * for. It changes whenever a function is added, removed or changed. */
#define KES_ABI_VERSION 7  /* the interface described in this file (2: preamble search and fine timing; 3: threads and the header reader; 4: body decoder parts; 5: steady-signal notch, known-bit Viterbi; 6: whole body decoder; 7: the continuous receiver, the transmitter) */
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
 * notched out (also modem/longbeacon.py clean, with windowed 0 and local_steps -1). Blocks of `block` samples,
 * each weighted by a Hann window when `windowed`; a step whose 10th-percentile energy over the blocks is `times`
 * the band's median, and `times` the median of the steps within `local_steps` of it (no such test when
 * local_steps < 0), is steady; with none, or
 * more than `most`, nothing is changed. Each notch is
 * `half_hz` either side, cut in one transform of `size` samples (size >= n). Returns how many steps were
 * notched (0 for none), or -1 on bad arguments. */
KES_API int kes_remove_steady(const double *x, size_t n, size_t block, int windowed, double low_hz, double high_hz, double times, int local_steps, int most,
                              double half_hz, size_t size, double *out);

/* modem/frame.py _decode_body, the numerical part, in one call: pilot fit, band measurement, noise level,
 * first SNR and fading reading from the pilots, noise profile, soft bits, de-interleaving, then the
 * convolutional decoder (is_control) or the LDPC decoder (with `prior` added when nprior == coded), and
 * the CRC-16 body check. The body has `total` tones of `samples` samples from body_start; pilots at
 * pilot_pos with tones pilot_tones; data tones at data_pos; `coded` soft bits are kept. The LDPC wiring is
 * as for kes_ldpc_decode. Writes the data bits, the `coded` soft bits (after any combining), the band's
 * energies (total x (hi - lo + 1), if band_out is not NULL) and six figures to stats_out: offset (Hz),
 * drift (Hz/s), SNR (dB, from the pilots), fading index, 1.0 if the body check passed, the noise per tone.
 * Returns the number of data bits, or -1 on bad arguments. */
KES_API long kes_decode_body(const double *x, size_t n, double body_start, double offset_hz, size_t samples, size_t lo, size_t hi, int step,
                             size_t total, const long *pilot_pos, const int *pilot_tones, size_t npilots, const long *data_pos, size_t ndata,
                             size_t coded, int is_control, long info, const long *edge_bits, const long *edge_checks, long nedges,
                             const long *starts, double scale, int iterations, const double *prior, size_t nprior, int pad, int fine_span,
                             int noise_span, int tracking, uint8_t *data_out, double *llrs_out, double *band_out, double *stats_out);

/* The continuous receiver (live/listener.py, incremental search). The library keeps the audio and the
 * candidates; the caller decodes the frames it is told are ready and says what to cut out.
 *   kes_listener_new(cfg, KES_CFG_COUNT); kes_listener_set_pattern for slots 0-4 (levels) and 5 (long
 *   beacon): values = number, samples, reach, whiten, gate, preamble samples, lo, hi, step; bins = the
 *   pattern's tones in fine steps; kes_listener_set_tables(totals by type [32], body totals, count).
 *   kes_listener_feed returns 1 when a search is due; then kes_listener_begin (0: too little audio), and
 *   kes_listener_next until it returns 0. Its events, in ev[0..7]: 1 a frame to decode (level, start,
 *   receiver's start, offset, quality, end); 2 a long beacon to read (level, start, start, offset,
 *   quality); 3 a candidate whose header could not be read yet (ev[6] = 1 when it was also a near miss,
 *   whose audio is kes_listener_near_audio and whose stream sample is ev[7]; it has been cut out). The
 *   blanked and notched store the frames are read from is kes_listener_x, valid until the next search. */
/* The transmitter (modem/frame.py build_frame and build_control, once the bits are packed): code the 24
 * header bits (K = 7) and the body (with its CRC: the convolutional code if is_control, else the LDPC code,
 * whose three shuffles `rows` (3 x k) come from ldpc.py info_checks), pad and interleave the body, place
 * its data tones and pilots, and write the audio of preamble, header, body and header again: cosine
 * bursts of `samples` samples at tone_bins[tone] FFT bins. `audio` must hold (npreamble + 24 + total) *
 * samples values. Returns the number of samples written, or -1 on bad arguments. */
KES_API long kes_encode_frame(const uint8_t *header_bits, const uint8_t *data_bits, size_t ndata_bits, int is_control, const long *rows,
                              size_t total, const long *data_pos, size_t ndata, const long *pilot_pos, const int *pilot_tones, size_t npilots,
                              size_t coded, const int *preamble_tones, size_t npreamble, size_t samples, const int *tone_bins, double *audio);

typedef struct KesListener KesListener;  /* a continuous receiver (its insides are the library's own) */
KES_API KesListener *kes_listener_new(const double *cfg, size_t count);  /* make one (NULL if count is not KES_CFG_COUNT) */
KES_API void kes_listener_free(KesListener *h);  /* end it */
KES_API int kes_listener_set_pattern(KesListener *h, int slot, const double *values, const int *bins, size_t ntones);  /* describe a pattern */
KES_API int kes_listener_set_tables(KesListener *h, const int *totals_by_type, const int *body_totals, size_t nbody);  /* the header reader's tables */
KES_API void kes_listener_clear(KesListener *h);  /* forget everything heard */
KES_API int kes_listener_feed(KesListener *h, const double *samples, size_t n, long long at, int counted);  /* add audio (numbered from `at` when counted); 1 when a search is due */
KES_API int kes_listener_begin(KesListener *h, int near_on);  /* start a search */
KES_API int kes_listener_next(KesListener *h, double *ev);  /* the next event of the search (0 when done) */
KES_API size_t kes_listener_size(KesListener *h);  /* samples kept */
KES_API const double *kes_listener_x(KesListener *h);  /* the processed store */
KES_API size_t kes_listener_x_size(KesListener *h);  /* its length */
KES_API const double *kes_listener_near_audio(KesListener *h);  /* the latest near miss's audio */
KES_API size_t kes_listener_near_size(KesListener *h);  /* its length */
KES_API long long kes_listener_number(KesListener *h, long position);  /* a store position as a stream number */
KES_API void kes_listener_cut(KesListener *h, long start, long end);  /* take a stretch out of the store */
KES_API long kes_listener_searches(KesListener *h);  /* searches so far */
KES_API size_t kes_listener_pending(KesListener *h);  /* candidates being followed */
KES_API size_t kes_listener_copy(KesListener *h, long from, long to, double *out);  /* copy a stretch of the store; returns how many */

#ifdef __cplusplus  /* when included from C++ */
}  /* end of the plain C names */
#endif  /* end of the C++ wrapper */

#endif  /* KESTREL_H */
