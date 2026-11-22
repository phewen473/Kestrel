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
#define KES_ABI_VERSION 1  /* the interface described in this file */
KES_API int kes_abi_version(void);  /* returns KES_ABI_VERSION as built into the library */

/* modem/blanker.py blank_impulses: copy x[0..n) to out, with samples far above
 * the level of their own tenth-of-a-second neighbourhood set to zero (and
 * `guard` samples either side of each). out may not overlap x. */
KES_API void kes_blank_impulses(const double *x, size_t n, double threshold, int guard, double *out);

/* modem/fec.py viterbi_decode: decode n soft coded bits (positive = probably 0)
 * of the rate-1/2, constraint-length-7 code (generators 171 and 133 octal)
 * into n/2 - 6 data bits, written to bits as 0 or 1. Returns the number of
 * data bits written, or -1 if n is too short. */
KES_API long kes_viterbi_decode(const double *llrs, size_t n, uint8_t *bits);

/* modem/mfsk.py band_energies: from audio x[0..n), take nsym blocks of `samples`
 * samples each, the first starting at round(start) (missing audio counts as
 * silence), shift each down by offset_hz plus a drift of drift_hz_s per second,
 * transform it, and write the energy of FFT bins lo..hi inclusive, one row per
 * block, to out (nsym x (hi - lo + 1) values). Returns 0, or -1 on bad
 * arguments. */
KES_API int kes_band_energies(const double *x, size_t n, double start, size_t nsym, size_t samples,
                              double offset_hz, double drift_hz_s, size_t lo, size_t hi, double *out);

#ifdef __cplusplus  /* when included from C++ */
}  /* end of the plain C names */
#endif  /* end of the C++ wrapper */

#endif  /* KESTREL_H */
