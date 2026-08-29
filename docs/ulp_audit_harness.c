
/* ULP audit harness for sv0-mathlib's math::trig, appended after the
 * sv0-emitted static function definitions above (same translation unit,
 * since sv0 emits them `static`). Compares against the system libm
 * (<math.h>) as an independent reference.
 *
 * USAGE (from an sv0-toolchain checkout, sv0-mathlib checked out as a
 * sibling directory):
 *
 *   printf '' > /tmp/.sv0_drv_path   # see feedback_drv_path_reset
 *   build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib/lib \
 *     > /tmp/mathlib_lib.c
 *   N=$(($(wc -l < /tmp/mathlib_lib.c) - 1))   # drop the trailing
 *                                                # `int main(void) { return 0; }`
 *                                                # sv0 emits as a fallback
 *   head -n $N /tmp/mathlib_lib.c > /tmp/mathlib_stripped.c
 *   cat sv0-mathlib/docs/ulp_audit_harness.c >> /tmp/mathlib_stripped.c
 *   cc -std=c99 -O2 -w -I sv0c/runtime /tmp/mathlib_stripped.c \
 *     sv0c/runtime/sv0_runtime.c -lm -o /tmp/ulp_audit_bin
 *   /tmp/ulp_audit_bin
 *
 * Not yet wired into CI (see docs/accuracy.md's own notes) — run by hand
 * after touching anything in lib/trig.sv0, and update docs/accuracy.md's
 * table with the new numbers.
 *
 * Near-zero handling: ULP spacing near a zero-crossing is astronomically
 * fine, so a tiny (physically insignificant) absolute difference between
 * two near-zero values explodes into a huge nominal ULP count. When
 * EITHER the reference or computed value is smaller in magnitude than
 * NEAR_ZERO_THRESHOLD, fall back to an absolute-error metric instead,
 * scaled by NEAR_ZERO_ABS_BUDGET so it's comparable to the ULP budget
 * (<=1.0 ~= "within budget").
 */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <complex.h>

#define NEAR_ZERO_THRESHOLD 1e-6
#define NEAR_ZERO_ABS_BUDGET 1e-9

static int64_t ordered_int64(double d) {
    int64_t i;
    memcpy(&i, &d, sizeof(i));
    if (i < 0) i = (int64_t)(INT64_MIN) - i;
    return i;
}

static int64_t ulp_diff(double a, double b) {
    if (a != a || b != b) return -1; /* NaN sentinel, handled by caller */
    int64_t ia = ordered_int64(a);
    int64_t ib = ordered_int64(b);
    int64_t d = ia - ib;
    return d < 0 ? -d : d;
}

static double effective_err_scaled(double got, double ref, double scale, int64_t *nan_sentinel) {
    if (got != got || ref != ref) { *nan_sentinel = 1; return 0.0; }
    *nan_sentinel = 0;
    if (fabs(got) < NEAR_ZERO_THRESHOLD * scale || fabs(ref) < NEAR_ZERO_THRESHOLD * scale) {
        return fabs(got - ref) / (NEAR_ZERO_ABS_BUDGET * scale);
    }
    return (double)ulp_diff(got, ref);
}

static double effective_err(double got, double ref, int64_t *nan_sentinel) {
    return effective_err_scaled(got, ref, 1.0, nan_sentinel);
}

typedef struct { double max_err; double at_x; double at_y; long n; long nan_mismatch; } AuditResult;

static void audit_report(const char *name, AuditResult r, int64_t budget) {
    printf("%-14s max_ulp=%.4f  at x=%.17g y=%.17g  n=%ld  nan_mismatch=%ld  budget=%lld  %s\n",
           name, r.max_err, r.at_x, r.at_y, r.n, r.nan_mismatch, (long long)budget,
           (r.max_err <= (double)budget && r.nan_mismatch == 0) ? "PASS" : "FAIL");
}

static void audit_point(AuditResult *r, double got, double ref, double x, double y) {
    int64_t nanmm;
    double e = effective_err(got, ref, &nanmm);
    if (nanmm) { r->nan_mismatch++; return; }
    if (e > r->max_err) { r->max_err = e; r->at_x = x; r->at_y = y; }
    r->n++;
}

/* Scaled variant, for a component whose own natural magnitude isn't
   O(1) the way plain real-valued sin/cos/exp/ln's outputs are (e.g. one
   component of a complex result whose OTHER component dominates by
   orders of magnitude) -- `scale` shifts the near-zero threshold/budget
   proportionally, so a component that's legitimately tiny relative to
   ITS OWN result's natural scale (not the fixed 1.0 the unscaled
   NEAR_ZERO_THRESHOLD/NEAR_ZERO_ABS_BUDGET assume) doesn't register a
   measurement artifact the same way an absolute-scale near-zero
   crossing would. `scale` is clamped to >= 1.0 so this never makes the
   threshold TIGHTER than the unscaled default for an ordinary O(1) or
   smaller result. */
static void audit_point_scaled(AuditResult *r, double got, double ref, double x, double y, double scale) {
    int64_t nanmm;
    double s = scale > 1.0 ? scale : 1.0;
    double e = effective_err_scaled(got, ref, s, &nanmm);
    if (nanmm) { r->nan_mismatch++; return; }
    if (e > r->max_err) { r->max_err = e; r->at_x = x; r->at_y = y; }
    r->n++;
}

int main(void) {
    AuditResult r;
    long i;
    double x, ref, got;

    /* sin_f64/cos_f64/tan_f64 over [-1000*pi, 1000*pi], PERF-002's own domain, 3 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 200000; i++) {
        x = -1000.0 * M_PI + (2000.0 * M_PI) * ((double)i / 200000.0);
        ref = sin(x);
        got = sin_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("sin_f64", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 200000; i++) {
        x = -1000.0 * M_PI + (2000.0 * M_PI) * ((double)i / 200000.0);
        ref = cos(x);
        got = cos_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("cos_f64", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 200000; i++) {
        x = -1000.0 * M_PI + (2000.0 * M_PI) * ((double)i / 200000.0);
        /* skip near-asymptote points where cos(x) is tiny -- tan legitimately blows up there */
        if (fabs(cos(x)) < 1e-6) continue;
        ref = tan(x);
        got = tan_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("tan_f64", r, 3);

    /* sqrt_f64 over the full non-negative domain -- sample across magnitudes
       (tiny subnormal-adjacent through near f64::MAX), 2 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double e = -300.0 + 600.0 * ((double)i / 100000.0); /* exponent 10^e */
        x = pow(10.0, e);
        ref = sqrt(x);
        got = sqrt_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    {
        double xs[] = {0.0, 1.0, 2.0, 4.0, 100.0, 1e300, 1e-300};
        for (i = 0; i < 7; i++) {
            ref = sqrt(xs[i]);
            got = sqrt_f64(xs[i]);
            audit_point(&r, got, ref, xs[i], 0.0);
        }
    }
    audit_report("sqrt_f64", r, 2);

    /* asin_f64/acos_f64 over [-1, 1], 3 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -1.0 + 2.0 * ((double)i / 100000.0);
        ref = asin(x);
        got = asin_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("asin_f64", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -1.0 + 2.0 * ((double)i / 100000.0);
        ref = acos(x);
        got = acos_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("acos_f64", r, 3);

    /* atan_f64 over a wide domain (all finite f64 in TRIG-004's own wording;
       sample across magnitudes, both signs), 3 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double e = -20.0 + 40.0 * ((double)i / 100000.0);
        double sign = (i % 2 == 0) ? 1.0 : -1.0;
        x = sign * pow(10.0, e);
        ref = atan(x);
        got = atan_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("atan_f64", r, 3);

    /* atan2_f64 across all four quadrants, 3 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double theta = -M_PI + 2.0 * M_PI * ((double)i / 100000.0);
        double rad = 1.0 + 9.0 * ((double)(i % 997) / 997.0);
        double yy = rad * sin(theta);
        double xx = rad * cos(theta);
        ref = atan2(yy, xx);
        got = atan2_f64(yy, xx);
        audit_point(&r, got, ref, xx, yy);
    }
    audit_report("atan2_f64", r, 3);

    /* exp_f64/ln_f64 (Section 14 shared machinery), 2 ULP budget. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -700.0 + 1400.0 * ((double)i / 100000.0);
        ref = exp(x);
        got = exp_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("exp_f64", r, 2);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double e = -300.0 + 600.0 * ((double)i / 100000.0);
        x = pow(10.0, e);
        ref = log(x);
        got = ln_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("ln_f64", r, 2);

    /* sinh_f64/cosh_f64/tanh_f64 (TRIG-005) -- no PERF-002-pinned ULP
       bound exists for these today (Section 15 only pins TRIG-001/003/004
       and the shared exp/ln machinery); budget 3 used here as an
       informational carry-over from the sin/cos/tan convention, not a
       documented requirement. Domain: [-50, 50] densely samples both
       sinh_f64's small-|x| Taylor branch and its exp_f64-based branch
       (the switchover is at |x| == 1.0), and stays well inside exp_f64's
       own tested [-700, 700] range so cosh_f64/sinh_f64 (which both go
       through exp_f64 for |x| >= 1.0) aren't independently re-stressing
       the exp range-reduction path near overflow. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -50.0 + 100.0 * ((double)i / 100000.0);
        ref = sinh(x);
        got = sinh_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("sinh_f64", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -50.0 + 100.0 * ((double)i / 100000.0);
        ref = cosh(x);
        got = cosh_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("cosh_f64", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        x = -50.0 + 100.0 * ((double)i / 100000.0);
        ref = tanh(x);
        got = tanh_f64(x);
        audit_point(&r, got, ref, x, 0.0);
    }
    audit_report("tanh_f64", r, 3);

    /* hypot_f64 (TRIG-007) -- also no PERF-002-pinned bound; budget 3 is
       informational. Domain: magnitudes 1e-150..1e150 (well inside
       sqrt_f64's own tested 1e-300..1e300, since hypot_f64 squares a
       RATIO of the two inputs, not the inputs themselves, so it doesn't
       need sqrt_f64's full range to stress the overflow-avoidance path),
       both signs, plus a few exact/simple pairs. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double e = -150.0 + 300.0 * ((double)i / 100000.0);
        double sign_x = (i % 2 == 0) ? 1.0 : -1.0;
        double sign_y = ((i / 3) % 2 == 0) ? 1.0 : -1.0;
        double xx = sign_x * pow(10.0, e);
        double yy = sign_y * pow(10.0, e - 1.0 + 2.0 * ((double)(i % 997) / 997.0));
        ref = hypot(xx, yy);
        got = hypot_f64(xx, yy);
        audit_point(&r, got, ref, xx, yy);
    }
    {
        double xs[] = {0.0, 0.0, 3.0, 5.0, 1e300, 1e-300};
        double ys[] = {0.0, 1.0, 4.0, 0.0, 1e300, 1e-300};
        for (i = 0; i < 6; i++) {
            ref = hypot(xs[i], ys[i]);
            got = hypot_f64(xs[i], ys[i]);
            audit_point(&r, got, ref, xs[i], ys[i]);
        }
    }
    audit_report("hypot_f64", r, 3);

    /* CPLX-007: exp_complex/ln_complex (math::complex) -- gated on
       sin_f64/cos_f64/exp_f64/ln_f64 meeting PERF-002 (now confirmed
       above), so audited here too even though CPLX-007 itself carries
       no separate ULP number in SPEC.md -- informational 3 ULP budget,
       same convention as the TRIG-005/007 sweeps above. Reference is
       C99's <complex.h> cexp/clog (an independent implementation, not
       reusing this library's own sin_f64/cos_f64/exp_f64/ln_f64 as the
       "truth"). Each complex point contributes up to two audit_point
       calls (re, then im component) into the SAME AuditResult, so the
       reported max_ulp is the worse of the two components at whichever
       point produced it.

       exp_complex's two components can differ in NATURAL scale by many
       orders of magnitude at a single point (e.g. c.im near an odd
       multiple of pi/2, where cos_f64(c.im) legitimately crosses zero
       while sin_f64(c.im) stays near +/-1 -- the re component is then
       tiny while the im component is near the full modulus exp_f64(c.re)).
       Using the plain (unscaled, O(1)-relative) near-zero threshold there
       measures a component that's tiny only RELATIVE TO ITS OWN RESULT'S
       scale as if it were an absolute near-zero crossing, producing a
       measurement artifact (confirmed: 21 ULP at c.re=20, where the tiny
       re component's own ABSOLUTE error was ~9e-15, an excellent result
       by any real standard) -- audit_point_scaled with scale =
       cabs(refc) judges each component against the complex value's own
       modulus instead, the same fix in spirit as this file's own
       NEAR_ZERO_THRESHOLD but relative to the right unit for this
       function. */
    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 200000; i++) {
        long ri = i / 4001;
        long ii = i % 4001;
        double re_in = -20.0 + 40.0 * ((double)ri / 49.0);
        double im_in = -1000.0 * M_PI + 2000.0 * M_PI * ((double)ii / 4000.0);
        if (ri > 49) continue;
        Complex c;
        c.re = re_in;
        c.im = im_in;
        Complex got_c = exp_complex(c);
        double complex refc = cexp(re_in + im_in * I);
        double scale = cabs(refc);
        audit_point_scaled(&r, got_c.re, creal(refc), re_in, im_in, scale);
        audit_point_scaled(&r, got_c.im, cimag(refc), re_in, im_in, scale);
    }
    audit_report("exp_complex", r, 3);

    memset(&r, 0, sizeof(r));
    for (i = 0; i <= 100000; i++) {
        double e = -150.0 + 300.0 * ((double)i / 100000.0);
        double theta = -M_PI + 2.0 * M_PI * ((double)(i % 6151) / 6151.0);
        double mag = pow(10.0, e);
        double re_in = mag * cos(theta);
        double im_in = mag * sin(theta);
        Complex c;
        c.re = re_in;
        c.im = im_in;
        Complex got_c = ln_complex(c);
        double complex refc = clog(re_in + im_in * I);
        audit_point(&r, got_c.re, creal(refc), re_in, im_in);
        audit_point(&r, got_c.im, cimag(refc), re_in, im_in);
    }
    audit_report("ln_complex", r, 3);

    return 0;
}
