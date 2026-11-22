/*
 * internal.hpp - calls between the parts of the Kestrel library (not part of the public C interface).
 *
 * Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
 */

#ifndef KESTREL_INTERNAL_HPP  /* guard against being included twice */
#define KESTREL_INTERNAL_HPP  /* mark it included */

#include <string>  /* text */

#include "kestrel.h"  /* the public types */

namespace kes {  /* the library's C++ names */

/* Run one mail store request and return its reply in one locked step (the station uses this, so a reply
 * can never be mixed up with another thread's request; kes_mail_request/kes_mail_reply are for callers
 * outside the library, which must not interleave their own two calls on one store). */
std::string mail_call(KesMail *mail, const std::string &request, double now);

}  /* end of namespace kes */

#endif  /* KESTREL_INTERNAL_HPP */
