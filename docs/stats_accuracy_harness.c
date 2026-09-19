/* Accuracy harness for sv0-mathlib's module::stats, appended after the
 * sv0-emitted static function definitions (same translation unit, since
 * sv0 emits them `static`) by scripts/run_stats_accuracy.py, which also
 * compiles and runs it and does the grading.
 *
 * The harness only GENERATES: for each seeded data set it feeds the values
 * through the sv0-emitted Stats accumulator and prints the inputs and the
 * results, both as hex floats (`%a`, exact round trip). The exact
 * reference is computed by the Python driver in rational arithmetic, so
 * nothing here depends on this machine's `long double`.
 *
 * Output, per data set:
 *   SET <family> <n> <sum> <mean> <varp> <vars> <sdp> <sds> <min> <max>
 *   <n hex-float inputs>
 *
 * Families:
 *   uniform      x in [-1, 1)
 *   offset       x = 1e9 + u, u in [0, 1)   (variance stability)
 *   cancel       mixed magnitudes 1..1e8 with the running total cancelled at
 *                the end, so |sum| << sum(|x|)   (compensated-summation test)
 *   stream       20000 values in [0, 1)     (accumulation over a long run)
 */
#include <stdio.h>
#include <stdint.h>
#include <math.h>

static uint64_t rng_state = 88172645463325252ULL;

static double rng_unit(void) {
    uint64_t x = rng_state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    rng_state = x;
    return (double)((x * 2685821657736338717ULL) >> 11) * (1.0 / 9007199254740992.0);
}

#define MAXN 20100
static double data[MAXN];

static void emit_set(const char *family, int n) {
    Stats s = stats_new();
    for (int i = 0; i < n; i++) s = stats_push(s, data[i]);
    printf("SET %s %d %a %a %a %a %a %a %a %a\n", family, n,
           stats_sum_f64(s), stats_mean_f64(s),
           stats_variance_pop_f64(s), stats_variance_sample_f64(s),
           stats_stddev_pop_f64(s), stats_stddev_sample_f64(s),
           stats_min_f64(s), stats_max_f64(s));
    for (int i = 0; i < n; i++) printf("%a%c", data[i], i + 1 == n ? '\n' : ' ');
}

int main(void) {
    for (int set = 0; set < 20; set++) {
        for (int i = 0; i < 1000; i++) data[i] = rng_unit() * 2.0 - 1.0;
        emit_set("uniform", 1000);
    }
    for (int set = 0; set < 20; set++) {
        for (int i = 0; i < 1000; i++) data[i] = 1000000000.0 + rng_unit();
        emit_set("offset", 1000);
    }
    for (int set = 0; set < 20; set++) {
        int n = 400;
        double running = 0.0;
        for (int i = 0; i < n; i++) {
            double mag = pow(10.0, (double)((i * 7 + set) % 9));
            double v = (rng_unit() * 2.0 - 1.0) * mag;
            data[i] = v;
            running += v;
        }
        data[n] = -running;
        emit_set("cancel", n + 1);
    }
    for (int set = 0; set < 3; set++) {
        for (int i = 0; i < 20000; i++) data[i] = rng_unit();
        emit_set("stream", 20000);
    }
    return 0;
}
