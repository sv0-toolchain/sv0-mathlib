/* Independent C oracle for lib/random.sv0 (module::random). Prints
 * test/fixtures/random.csv on stdout; scripts/check_random_oracle.py
 * recompiles this file and fails CI if the checked-in CSV drifts from it.
 *
 * Independent on purpose: the LCG is plain uint64_t arithmetic, and
 * below_u64's bucket width uses unsigned __int128 (floor(2^64 / n)
 * directly) rather than the sv0 code's wrapping `(0 - n) / n + 1`. The
 * n == 1 case is NOT special-cased here (bucket width 2^64 falls out of
 * the general path), so it cross-checks the sv0 special case.
 *
 * Build/run: cc -std=c99 -O0 docs/random_oracle.c -o /tmp/random_oracle
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned __int128 u128;

static uint64_t next_u64(uint64_t s) {
    return s * 6364136223846793005ULL + 1442695040888963407ULL;
}

static double unit_f64(uint64_t s) {
    return (double)(s >> 11) / 9007199254740992.0;
}

static void below_u64(uint64_t state, uint64_t n, uint64_t *value, uint64_t *out) {
    u128 w = ((u128)1 << 64) / n;
    u128 limit = w * (u128)n;
    uint64_t s = next_u64(state);
    while ((u128)s >= limit) s = next_u64(s);
    *value = (uint64_t)((u128)s / w);
    *out = s;
}

/* %.17g round-trips a double; force a ".0" so sv0 lexes it as a float and
 * refuse exponent forms (the fixture generator emits literals verbatim). */
static void print_f64(double v) {
    char buf[64];
    snprintf(buf, sizeof buf, "%.17g", v);
    if (strchr(buf, 'e') || strchr(buf, 'E')) {
        fprintf(stderr, "random_oracle: exponent form for %s; pick another state\n", buf);
        exit(1);
    }
    printf("%s%s", buf, strchr(buf, '.') ? "" : ".0");
}

static const uint64_t SEED = 88172645463325252ULL;

int main(void) {
    const uint64_t states[] = {
        0ULL, 1ULL, 9223372036854775808ULL, 18446744073709551615ULL,
    };
    const uint64_t ns[] = {
        1ULL, 2ULL, 3ULL, 7ULL, 8ULL, 10ULL, 1000000007ULL,
        9223372036854775808ULL, 9223372036854775809ULL, 18446744073709551615ULL,
    };
    size_t i, j;

    printf("function,state,n,expected,expected_state,category,notes\n");

    /* next_u64: a short chain from SEED, plus edge states. */
    {
        uint64_t s = SEED;
        for (i = 0; i < 4; i++) {
            uint64_t nx = next_u64(s);
            printf("next_u64,%llu,,%llu,,typical,chain step %zu from the property-test seed\n",
                   (unsigned long long)s, (unsigned long long)nx, i + 1);
            s = nx;
        }
    }
    for (i = 0; i < sizeof states / sizeof states[0]; i++)
        printf("next_u64,%llu,,%llu,,boundary,edge state\n",
               (unsigned long long)states[i], (unsigned long long)next_u64(states[i]));

    /* unit_f64: the exact-scaling edge cases and a few typical states.
     * States 2048..2^53 give exponent-form doubles, which are not fixture literals, so
     * the small end is covered only by 0 and 2047 (both exactly 0.0). */
    {
        const uint64_t us[] = {0ULL, 2047ULL, 1ULL << 62, 9223372036854775808ULL,
                               18446744073709551615ULL, SEED};
        for (i = 0; i < sizeof us / sizeof us[0]; i++) {
            printf("unit_f64,%llu,,", (unsigned long long)us[i]);
            print_f64(unit_f64(us[i]));
            printf(",,%s,%s\n", (us[i] == 18446744073709551615ULL) ? "boundary" : "typical",
                   (us[i] == 18446744073709551615ULL) ? "largest value is 1 - 2^-53 (strictly below 1.0)" : "top 53 bits scaled by 2^-53");
        }
    }

    /* below_u64: each n from two start states (n = 2^63 + 1 rejects ~half of raw draws). */
    {
        const uint64_t bs[2] = {1ULL, SEED};
        for (j = 0; j < sizeof ns / sizeof ns[0]; j++)
            for (i = 0; i < 2; i++) {
                uint64_t v, out;
                below_u64(bs[i], ns[j], &v, &out);
                printf("below_u64,%llu,%llu,%llu,%llu,%s,%s\n",
                       (unsigned long long)bs[i], (unsigned long long)ns[j],
                       (unsigned long long)v, (unsigned long long)out,
                       ns[j] == 1ULL ? "boundary" : "typical",
                       ns[j] == 9223372036854775808ULL ? "power of two (bucket width 2) so no rejection"
                       : ns[j] == 9223372036854775809ULL ? "bucket width 1; about half of raw draws rejected"
                       : ns[j] == 18446744073709551615ULL ? "bucket width 1; only the single top value rejected"
                       : "bucketed draw");
            }
    }
    /* below_u64 rejection path: walk a chain from SEED and emit the first
     * three states where n = 2^63 + 1 forces a redraw (the returned state
     * is then NOT the immediate successor of the input). */
    {
        const uint64_t n = 9223372036854775809ULL;
        uint64_t s = SEED;
        int found = 0;
        while (found < 3) {
            uint64_t v, out;
            below_u64(s, n, &v, &out);
            if (out != next_u64(s)) {
                printf("below_u64,%llu,%llu,%llu,%llu,rejection,first raw draw rejected; state advanced past it\n",
                       (unsigned long long)s, (unsigned long long)n,
                       (unsigned long long)v, (unsigned long long)out);
                found++;
            }
            s = next_u64(s);
        }
    }
    return 0;
}
