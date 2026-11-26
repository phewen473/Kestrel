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
#define KES_CFG_NEAR_QUALITY 8  /* weakest pattern reported as a near miss (unused since interface 11: the caller decides) */
#define KES_CFG_NEAR_QUALITY_MAX 9  /* strongest (above it the measure has broken down; unused since interface 11) */
#define KES_CFG_BLANK_THRESHOLD 10  /* the blanker's threshold */
#define KES_CFG_BLANK_GUARD 11  /* and guard */
#define KES_CFG_NOTCH_BLOCK 12  /* the steady-signal notch: block length */
#define KES_CFG_NOTCH_LOW 13  /* lowest frequency */
#define KES_CFG_NOTCH_HIGH 14  /* highest frequency */
#define KES_CFG_NOTCH_TIMES 15  /* how far above the band */
#define KES_CFG_NOTCH_LOCAL 16  /* neighborhood, in steps */
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
#define KES_ABI_VERSION 19  /* the interface described in this file (19: signal version 0.43 - the station acknowledges with bursts: a transmission description may hold a "burst" frame, and "listen" / "listen_hz" say what burst a frame awaits and where; 18: signal version 0.43 - the signature pattern is sent at both ends of a frame and the second header copy's check value is marked: kes_encode_frame writes pattern, header, body, pattern, header; kes_read_header reads the header beside either pattern and answers 4, 5 or 6 for a frame found from its end; a kes_listener_next frame event gives the frame's start in ev[8], so ev must hold 9 values; kes_pilot_fit takes `backward` and kes_decode_body `from_end`, for a frame whose frequency was measured at its end; 17: a beacon carries the rig type and watts, KesFields.rig_model and watts; 16: the header reader accepts a beacon whose spare bit is set, meaning power steps came just before it (signal version 0.38); 15: kes_listener_candidates, the frames being received, for the panel's frame strip; 14: kes_tone_spread, the Doppler-spread reading; 13: signal version 0.33: the answer frame carries its sender's locator (KesFields.grid; empty = none); 12: signal version 0.32: Gray-coded tones in the transmitter and both soft-bit readers; the transmitter's glide and end fades; 2: preamble search and fine timing; 3: threads and the header reader; 4: body decoder parts; 5: steady-signal notch, known-bit Viterbi; 6: whole body decoder; 7: the continuous receiver, the transmitter; 8: packing and unpacking the bits; 9: the mail store; 10: the station's link rules; 11: every signature whose frame passed without a header is handed back as a possible near miss; the caller decides and cuts) */
KES_API int kes_abi_version(void);  /* returns KES_ABI_VERSION as built into the library */

/* Threads: the heavy routines share their work among up to 8 threads (never more than the computer has).
 * The results are the same whatever the count. kes_set_threads(0) goes back to the computer's own count. */
KES_API void kes_set_threads(int threads);  /* how many threads to use (0 = the computer's count) */
KES_API int kes_threads(void);  /* how many will be used */

/* modem/blanker.py blank_impulses: copy x[0..n) to out, with samples far above
 * the level of their own tenth-of-a-second neighborhood set to zero (and
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
 * bins lo..hi of `samples`-sample tones, tone m in column 1 + m * step. A header copy follows each of a
 * frame's two patterns (since interface 18, signal version 0.43); the copy that starts at header_start is
 * the one after the pattern found, and the mark on its check value says which end of the frame that is.
 * If it does not check out alone (or since >= 0, meaning it was tried before), the second copy is read
 * after each body length in body_totals[0..nbody) and the second pattern, with it and alone; then (only
 * when since < 0) the first copy is read before each body length, with it and alone. A header found at a
 * distance is accepted only if totals_by_type[frame type * 4 + size class] equals that length (-1 for
 * frame types that do not exist). since >= 0 skips second-copy places tried before (whole copy inside
 * x's length `since`). Writes the 24 header bits in the first copy's form. Returns 1 (first copy alone),
 * 2 (both, from the start), 3 (second copy, from the start), 4 (second copy alone: the pattern is the
 * frame's end), 5 (both, from the end), 6 (first copy, from the end), 0 (none) or -1 (bad arguments). */
KES_API int kes_read_header(const double *x, size_t n, double header_start, double offset_hz, size_t samples, size_t lo, size_t hi,
                            int step, int level, const int *totals_by_type, const int *body_totals, size_t nbody, double since,
                            uint8_t *bits);

/* modem/ldpc.py decode: normalized min-sum decoding of 2k soft values (positive = probably 0). The code's
 * wiring is given edge by edge, sorted by check: edge_bits[e] and edge_checks[e], with check c's edges
 * from starts[c] (as ldpc.py _graph gives them). Writes k data bits; returns 1 when every check is
 * satisfied, 0 when it gave up after max_iterations rounds, -1 on bad arguments. */
KES_API int kes_ldpc_decode(const double *llrs, long k, const long *edge_bits, const long *edge_checks, long nedges, const long *starts,
                            double scale, int max_iterations, uint8_t *bits);

/* modem/mfsk.py noise_profile: the noise energy per tone position at each of `rows` symbols of tone_e
 * (rows x 32), the median of each symbol and `span` either side (mirrored at the ends) over ln 2, never
 * below a tenth of the whole frame's level; with tracking 0 (or a short frame), the whole frame's level. */
KES_API int kes_noise_profile(const double *tone_e, size_t rows, int span, int tracking, double *level);

/* modem/mfsk.py tone_spread (since ABI 14): how far known tones spread into the bins beside them, the
 * mark Doppler spread leaves. `band` is rows x cols energies (band_energies: tone m in column 1 + m * step),
 * tones[r] the tone sent in row r, noise[r] that row's noise energy per bin. out[0] = share of the signal
 * found in the two neighbors (0 to 1; -1 when no signal), out[1] = upper neighbor less lower over the
 * signal (a leftover frequency error), out[2] = signal over noise summed over the rows (trust). 0, or -1. */
KES_API int kes_tone_spread(const double *band, size_t rows, size_t cols, const long *tones, int step, const double *noise, double *out);

/* modem/mfsk.py pilot_frequency_fit: measure the pilots (positions[i] tones after `start`, each sending
 * tone tones[i]) in stretches of about eight, each searched around where the last found the signal, on a
 * grid `pad` times finer than one bin, `fine_span` steps each side; fit a straight line through the
 * stretches. Writes the extra offset at the first symbol (Hz) and the drift (Hz per second). With
 * `backward` (since interface 18) the stretches are followed from the last to the first: offset_hz was
 * then measured at the frame's end (a frame found from its second pattern), and a drifting signal is
 * followed back from there; the answers are still the extra offset at the first symbol and the drift. */
KES_API int kes_pilot_fit(const double *x, size_t n, double start, const long *positions, const int *tones, size_t npilots, size_t samples,
                          const int *tone_bins, int pad, int fine_span, double offset_hz, int backward, double *extra_out, double *drift_out);

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
 * `from_end` (since interface 18) says offset_hz was measured at the frame's end; it is handed to
 * kes_pilot_fit as `backward`. Returns the number of data bits, or -1 on bad arguments. */
KES_API long kes_decode_body(const double *x, size_t n, double body_start, double offset_hz, size_t samples, size_t lo, size_t hi, int step,
                             size_t total, const long *pilot_pos, const int *pilot_tones, size_t npilots, const long *data_pos, size_t ndata,
                             size_t coded, int is_control, long info, const long *edge_bits, const long *edge_checks, long nedges,
                             const long *starts, double scale, int iterations, const double *prior, size_t nprior, int pad, int fine_span,
                             int noise_span, int tracking, int from_end, uint8_t *data_out, double *llrs_out, double *band_out, double *stats_out);

/* The continuous receiver (live/listener.py, incremental search). The library keeps the audio and the
 * candidates; the caller decodes the frames it is told are ready and says what to cut out.
 *   kes_listener_new(cfg, KES_CFG_COUNT); kes_listener_set_pattern for slots 0-4 (levels) and 5 (long
 *   beacon): values = number, samples, reach, whiten, gate, preamble samples, lo, hi, step; bins = the
 *   pattern's tones in fine steps; kes_listener_set_tables(totals by type [32], body totals, count).
 *   kes_listener_feed returns 1 when a search is due; then kes_listener_begin (0: too little audio), and
 *   kes_listener_next until it returns 0. Its events, in ev[0..7]: 1 a frame to decode (level, start,
 *   receiver's start, offset, quality, end); 2 a long beacon to read (level, start, start, offset,
 *   quality); 3 a candidate whose header could not be read yet (ev[6] = 1 when its frame has passed
 *   without one, so it is let go: a possible near miss, whose audio is kes_listener_near_audio and whose
 *   stream sample is ev[7]; since interface 11 the caller decides whether to report it, and cuts it
 *   out with kes_listener_cut if it does). The
 *   blanked and notched store the frames are read from is kes_listener_x, valid until the next search. */
/* The transmitter (modem/frame.py build_frame and build_control, once the bits are packed): code the 24
 * header bits (K = 7) and the body (with its CRC: the convolutional code if is_control, else the LDPC code,
 * whose three shuffles `rows` (3 x k) come from ldpc.py info_checks), pad and interleave the body, place
 * its data tones and pilots, and write the audio of pattern, header, body, pattern again and header again
 * (the second header copy with its check value marked; since interface 18, signal version 0.43): tones of
 * `samples` samples at tone_bins[tone] FFT bins, numbered in Gray code, as one continuous-phase waveform
 * whose frequency glides over `glide` of a tone at each change (0 = sudden steps) and which fades in and
 * out over `fade` samples at its ends (since interface 12, signal version 0.32). `audio` must hold
 * (2 * npreamble + 24 + total) * samples values. Returns the number of samples written, or -1 on bad arguments. */
KES_API long kes_encode_frame(const uint8_t *header_bits, const uint8_t *data_bits, size_t ndata_bits, int is_control, const long *rows,
                              size_t total, const long *data_pos, size_t ndata, const long *pilot_pos, const int *pilot_tones, size_t npilots,
                              size_t coded, const int *preamble_tones, size_t npreamble, size_t samples, const int *tone_bins, double glide, size_t fade,
                              double *audio);

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
/* Since interface 15: the candidates being followed, for the panel's frame strip, KES_CANDIDATE_FIELDS
 * values each: pattern slot (0-4 levels, 5 long beacon), stream sample where the pattern starts, store
 * position now (-1 if gone), offset Hz, quality, coarse (1 = not yet finely timed), header read (1/0),
 * which copy gave it (1 first, 2 both, 3 second), the header's 16 field bits as a number (first bit
 * highest; 0 when not read), first copy tried and unreadable (1/0), fine-timing fraction. Returns how
 * many were written (at most `most`). */
#define KES_CANDIDATE_FIELDS 11  /* values per candidate */
KES_API size_t kes_listener_candidates(KesListener *h, double *out, size_t most);  /* the candidates, for the frame strip */
KES_API size_t kes_listener_copy(KesListener *h, long from, long to, double *out);  /* copy a stretch of the store; returns how many */


/* ---- Packing and unpacking the bits a frame carries (cpp/src/packing.cpp, since interface 8) ----
 * Each function refuses (returns -1) where its Python reference would raise an error, and for any text
 * outside 7-bit ASCII, so the Python caller can run its own code and raise its own worded error.
 * Bits are passed one per byte (0 or 1), most significant first; addresses and locators as C strings. */

/* The named fields of a control frame or a message's address block. Text fields end with a zero byte. */
typedef struct KesFields {
    char origin[10];  /* who sent it (beacon, answer, ident, notice) or wrote it (addressed message) */
    char dest[10];  /* who it is for (answer, addressed message) */
    char grid[5];  /* four-character grid locator (beacon) */
    int levels;  /* the speed levels a station can use: bit n set for level n (beacon, answer) */
    int listening;  /* beacon flag: will take answers */
    int mail_check;  /* beacon and answer flag: wants its mail */
    int holds_mail;  /* beacon flag: holds mail for others */
    int wide;  /* beacon flag: wide reply window */
    int directed;  /* answer flag: a directed call */
    int final_flag;  /* ident flag: the end of the contact */
    long link;  /* short link number (ack, ident, link message) */
    long msg_id;  /* message number (ack, message) */
    long part;  /* part number (ack) */
    long status;  /* the acknowledgment's verdict (ack) */
    long hops;  /* relays so far (addressed message) */
    long life_hours;  /* lifetime left, in hours (addressed message) */
    double snr_db;  /* channel report: SNR in 2.5 kHz (answer, ack) */
    double fade_index;  /* channel report: fading index */
    double offset_hz;  /* channel report: frequency offset */
    int want_level;  /* channel report or link message: the level asked for */
    long held[3];  /* mail notice: codes of the stations mail is held for */
    long receipts[3];  /* mail notice: codes of the delivery receipts */
    long heard[3];  /* mail notice: codes of the stations heard */
    int nheld;  /* entries in held */
    int nreceipts;  /* entries in receipts */
    int nheard;  /* entries in heard */
    long rig_model;  /* beacon: the rig type, a Hamlib model number (0: not said; since interface 17) */
    long watts;  /* beacon: transmit power in whole watts (0: not said; since interface 17) */
} KesFields;

KES_API int kes_compress_length(int character);  /* modem/compress.py LENGTHS: the code length of a character 0..127 (-1 outside) */
KES_API int kes_crc16(const uint8_t *bits, size_t n);  /* modem/crc.py crc16: CRC-16/CCITT-FALSE of n bits, as a number */
KES_API int kes_crc8(const uint8_t *bits, size_t n);  /* modem/crc.py crc8: CRC-8 of n bits, as a number */
KES_API int kes_call_to_bits(const char *call, uint8_t *out);  /* modem/address.py call_to_bits: 48 bits into out; 0, or -1 */
KES_API int kes_bits_to_call(const uint8_t *bits, char *out);  /* modem/address.py bits_to_call: the address from 48 bits into out (10 bytes); 0, or -1 */
KES_API long kes_call_hash(const char *call);  /* modem/address.py call_hash: 1..65535, or -1 */
KES_API long kes_message_hash(const char *origin, long msg_id);  /* modem/address.py message_hash: 1..65535, or -1 */
KES_API long kes_link_id(const char *first, const char *second);  /* modem/address.py link_id: 0..511, or -1 */
KES_API long kes_compressed_bits(const char *text, size_t len);  /* modem/compress.py compressed_bits, or -1 */
KES_API int kes_choose_packing(const char *text, size_t len, int frame_type, int *size_class, int *compressed);  /* modem/text.py choose_packing: 0, or -1 */
KES_API long kes_text_to_bits(const char *text, size_t len, int size_class, int compressed, int frame_type, uint8_t *out);  /* modem/text.py text_to_bits: bits written (at most 1408), or -1 */
KES_API long kes_bits_to_text(const uint8_t *bits, size_t n, int compressed, char *out, size_t cap);  /* modem/text.py bits_to_text: characters written, or -1 */
KES_API void kes_header_bits(int frame_type, int level, int size_class, int part, int parts, int compressed, uint8_t *out);  /* modem/frame.py _header_bits: 24 bits */
KES_API long kes_address_block(int frame_type, long link, long want_level, long msg_id, const char *dest, const char *origin, long hops, long life_hours,
                               uint8_t *out);  /* modem/frame.py _address_block: 28 or 120 bits written, or -1 */
KES_API int kes_read_address_block(int frame_type, const uint8_t *bits, KesFields *fields);  /* modem/frame.py _read_address_block: 0, or -1 */
KES_API int kes_levels_mask(const long *levels, size_t n);  /* modem/control.py levels_to_bits, as a number, or -1 */
KES_API long kes_pack_control(int frame_type, const KesFields *fields, uint8_t *out);  /* modem/control.py pack_beacon / answer / ack / ident / notice: bits written (at most 192), or -1 */
KES_API int kes_unpack_control(int frame_type, const uint8_t *bits, size_t n, KesFields *fields);  /* modem/control.py unpack: 0, or -1 */


/* ---- Store and forward: the mail a station keeps (cpp/src/mail.cpp, since interface 9) ----
 * link/mail.py Mailroom in C++. One store per station. Each request is JSON: {"op": a Mailroom method
 * name, "args": [its arguments], "now": the clock}; `now` is the wall-clock time in seconds. The reply,
 * collected with kes_mail_reply, is {"ok": the method's answer} or {"error": the Python error's name,
 * "message": ...}. "to_dict" gives the mail file's contents and "from_dict" loads them, so the file is
 * the same JSON as the Python version's. */
typedef struct KesMail KesMail;  /* the store (its insides are private) */
KES_API KesMail *kes_mail_new(void);  /* a new, empty store with a random first message number */
KES_API void kes_mail_free(KesMail *mail);  /* free it */
KES_API long kes_mail_request(KesMail *mail, const char *request, double now);  /* run one request; returns the reply's length in bytes, or -1 */
KES_API long kes_mail_reply(KesMail *mail, char *out, size_t cap);  /* copy the last reply into out (no end mark); returns its length, or -1 if cap is too small */

/* ---- One station's link rules (cpp/src/station.cpp, since interface 10) ----
 * link/station.py Station in C++. Requests are JSON: {"op": a Station method name (or "init", "get",
 * "set"), "args": [...], "mail_now": the mail store's clock}. "handle" takes the receiver's report as
 * JSON (modem/frame.py RxResult's fields); "handle" and "poll" answer with a transmission
 * ({"frame": {"type": "ack", ...}, "kind", "level", "note", "delay", "seconds"}) or null. The reply,
 * collected with kes_station_reply, is {"ok": ..., "clear_stored": true when the receiver's kept soft
 * bits must be dropped} or {"error": the Python error's name, "message": ...}. */
typedef struct KesStation KesStation;  /* the station (its insides are private) */
typedef int (*KesBusy)(void *ctx, int level);  /* listen before transmitting: nonzero when the frequency is in use where a frame at `level` would go */
KES_API KesStation *kes_station_new(void);  /* a new station; set it up with the "init" request */
KES_API void kes_station_free(KesStation *station);  /* free it */
KES_API void kes_station_set_mail(KesStation *station, KesMail *mail);  /* the mail store it uses (the caller keeps it alive) */
KES_API void kes_station_set_busy(KesStation *station, KesBusy busy, void *ctx);  /* the listen-before-transmit check (NULL for none) */
KES_API long kes_station_request(KesStation *station, const char *request);  /* run one request; returns the reply's length, or -1 */
KES_API long kes_station_reply(KesStation *station, char *out, size_t cap);  /* copy the last reply into out; returns its length, or -1 */

#ifdef __cplusplus  /* when included from C++ */
}  /* end of the plain C names */
#endif  /* end of the C++ wrapper */

#endif  /* KESTREL_H */
