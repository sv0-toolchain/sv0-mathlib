# Accuracy audit (PERF-001 / PERF-002)

One row per non-exact public function, per PERF-001: measured maximum ULP
error over the fixture domain, the iteration/degree parameter, and the
toolchain revision last measured against.

**Measured**: 2026-08-28, against `sv0-toolchain` `43ee2b0` (parent) /
`sv0c` `d0fa706` (submodule) plus the in-tree fixes this audit produced
(not yet committed as of this table's writing — see `BUGS.md`/`README.md`
for the finalized SHAs once landed).

**Method**: a standalone C harness, checked in at
[`docs/ulp_audit_harness.c`](ulp_audit_harness.c) (usage instructions in
its own header comment), compiles `sv0-mathlib/lib/` via the native
compiler (`build/sv0-megatu-compiler-native --project`), strips the
trivial fallback `main`, and links a custom `main()` in the same
translation unit that calls each `sv0`-emitted function directly (they are
`static`) and compares against the system libm (`<math.h>`) as an
independent reference. ULP distance is measured via a monotonic
bit-pattern ordering of `double` (`ordered_int64`), with an absolute-error
fallback below `1e-6` in magnitude (ULP spacing near a zero-crossing is
not a meaningful metric — a physically insignificant absolute difference
between two near-zero values otherwise explodes into an astronomical
nominal ULP count). Domains match PERF-002's own wording exactly where
PERF-002 pins one (`sin_f64`/`cos_f64`/`tan_f64`/`asin_f64`/`acos_f64`/
`atan_f64`/`atan2_f64`/`exp_f64`/`ln_f64`); `sinh_f64`/`cosh_f64`/
`tanh_f64`/`hypot_f64` (TRIG-005/TRIG-007, which don't carry a pinned
ULP bound) use an informational 3 ULP budget carried over from the
sin/cos/tan convention, not a documented requirement.

| Function | Domain sampled | Max ULP | Budget | Parameter | Status |
|---|---|---:|---:|---|---|
| `sqrt_f64` | magnitudes `1e-300`..`1e300` (100001 pts) + exact values | 1 | 2 | Newton-Raphson, exponent-doubling bracket seed, fixed 1 refinement pass (see `sqrt_bracket_guess`/`sqrt_error_bound`) | PASS |
| `sin_f64` | `[-1000*pi, 1000*pi]` (200001 pts) | 1 | 3 | double-double (Cody-Waite) range reduction to `[0,2*pi)`, double-double quarter-turn fold, 12-term Taylor `sin_poly_dd`, Neumaier-compensated | PASS |
| `cos_f64` | `[-1000*pi, 1000*pi]` (200001 pts) | 1 | 3 | same pipeline as `sin_f64`, `cos_poly_dd` | PASS |
| `tan_f64` | `[-1000*pi, 1000*pi]` (198001 pts, near-asymptote points where `|cos(x)| < 1e-6` excluded) | 3 | 3 | `sin_f64(x) / cos_f64(x)`, both kept double-double internally through the quadrant application so the division sees each operand rounded only once | PASS |
| `asin_f64` | `[-1, 1]` (100001 pts) | 2 | 3 | `atan_f64(x / sqrt_f64((1-x)*(1+x)))` — the `(1-x)*(1+x)` factored form avoids `1.0 - x*x`'s catastrophic cancellation near `\|x\| = 1` | PASS |
| `acos_f64` | `[-1, 1]` (100001 pts) | 3 | 3 | half-angle reformulation (`2*asin(sqrt((1-x)/2))` / `pi - 2*asin(sqrt((1+x)/2))`), NOT `pi/2 - asin_f64(x)` (which catastrophically cancels near `x ~= 1`) | PASS |
| `atan_f64` | magnitudes `1e-20`..`1e20`, both signs (100001 pts) | 1 | 3 | double-double throughout (`atan_f64_dd`): double-double `sqrt3`/`pi/6` for the `x > tan(pi/12)` reduction identity, double-double `pi/2` for the `x > 1` identity, 20-term Taylor `atan_small_series_dd`, single final rounding | PASS |
| `atan2_f64` | all 4 quadrants, radius `1`..`10` (100001 pts) | 2 | 3 | standard four-quadrant form built on `atan_f64` | PASS |
| `exp_f64` | `[-700, 700]` (100001 pts) | 1 | 2 | double-double (`ln2_hi`/`ln2_lo`) range reduction `x = k*ln2 + r`, 20-term Taylor, Neumaier-compensated, first-order `r_lo` correction | PASS |
| `ln_f64` | magnitudes `1e-300`..`1e300` (100001 pts) | 1 | 2 | exponent-doubling bracket for `m`/`e`, double-double `y = (m-1)/(m+1)` (Newton-style residual correction — `m+1.0` is not exact for `m` in `[1,2)`), 20-term atanh series, Neumaier-compensated, double-double `e*ln2` combination, single final rounding | PASS |
| `sinh_f64` | `[-50, 50]` (100001 pts) | 1 | 3 (informational) | Taylor series (Neumaier-compensated) for `\|x\| < 1.0`, `(exp_f64(x) - exp_f64(-x))/2` otherwise | PASS |
| `cosh_f64` | `[-50, 50]` (100001 pts) | 1 | 3 (informational) | `(exp_f64(x) + exp_f64(-x))/2` — no cancellation to begin with, no special-casing needed | PASS |
| `tanh_f64` | `[-50, 50]` (100001 pts) | 2 | 3 (informational) | `sinh_f64(x)/cosh_f64(x)` for `\|x\| < 1.0`, `(exp_f64(2x)-1)/(exp_f64(2x)+1)` otherwise, clamped to the nearest double strictly inside `(-1,1)` both by a pre-check on `\|x\|` (avoids `Infinity/Infinity`) and post-hoc on the computed result (catches rounding to exactly `+/-1.0` before the pre-check's threshold) | PASS |
| `hypot_f64` | magnitudes `1e-150`..`1e150`, both signs (100001 pts) + exact/simple pairs | 3 | 3 (informational) | scaled form (`mx * sqrt_f64(1 + (mn/mx)^2)`) avoiding overflow/underflow from squaring both inputs directly | PASS |

## Notes

- Every function above started this audit pass FAILING its budget (some by
  orders of magnitude — `acos_f64` measured 3029 ULP before its fix,
  `exp_f64` measured 714). The root cause in every case was the same
  general shape: a plain single-`f64` intermediate result silently
  discarding precision a later step needed — a range-reduction constant
  only accurate to ~1 ULP (`two_pi`, `ln2`), a subtraction/division that
  isn't exact where it looked like it should be (`m + 1.0` for `m` in
  `[1,2)`; `pi/6` vs. `sqrt(3)`-derived reductions rounding
  independently), or a summation loop accumulating rounding over many
  terms. Every fix follows the same double-double (Dekker/Knuth-Møller)
  pattern already established for `fma_f64` (ARITH-010): carry a
  `(hi, lo)` pair through the computation and round to a single `f64`
  only once, at the very end.
- `atan_f64`'s own `ensures` was tightened from the SPEC.md-literal
  strict `result > -pi/2 && result < pi/2` to `>=`/`<=` — a
  correctly-rounded double-precision `atan` legitimately returns exactly
  the nearest representable double to `pi/2` for large enough `\|x\|`
  (confirmed against the system libm directly, not `sv0-mathlib`-specific
  — see `README.md`'s "Deviations from SPEC.md"). Making `atan_f64` MORE
  accurate made hitting this boundary more likely, not less; an earlier,
  less accurate version happened to round just short of it by
  coincidence.
- `sinh_f64`/`cosh_f64`/`tanh_f64`/`hypot_f64` are now swept (see table
  above); `to_radians_f64`/`to_degrees_f64` are exact (trivial scaling by
  `pi_f64()`, no series or reduction), so ULP auditing them the same way
  wouldn't say anything a `requires`/`ensures`-driven fixture doesn't
  already cover, and they're skipped here for that reason.
- The widened sweep found two real bugs, both fixed, neither previously
  caught (the original sweep only exercised these functions indirectly,
  through `sin_f64`/`cos_f64`/`exp_f64`): (1) `tanh_f64`'s pre-emptive
  `\|x\| > 20.0` clamp wasn't tight enough — `exp_f64(2*x)` underflows
  enough for `(e2x-1)/(e2x+1)` to round to exactly `+/-1.0` starting
  around `\|x\| ~= 19.98`, a real `ensures` PANIC (not just an accuracy
  miss) for input as unremarkable as `x = -19.999`; fixed by checking the
  actual computed result against the boundary, in addition to (not
  instead of) the pre-clamp, which is still needed to avoid a SEPARATE
  `Infinity/Infinity = NaN` failure mode for genuinely large `\|x\|`. (2)
  `tanh_f64` near `x = 0` measured 121 ULP — `exp_f64(2*x)` near `1.0`
  means `e2x - 1.0` catastrophically cancels, and `tanh_f64` (unlike
  `sinh_f64`, which already had a near-zero Taylor branch) had no
  cancellation-free path there at all; fixed by delegating to
  `sinh_f64(x) / cosh_f64(x)` for `\|x\| < 1.0`. `sinh_f64`'s own Taylor
  loop also picked up Neumaier-compensated summation (was a plain running
  sum) once `tanh_f64`'s division made its residual error visible.
- This table is generated by hand from the standalone C harness described
  above, not yet wired into CI as an automated regression gate (the
  PERF-001 "Generated-doc freshness test" / PERF-002 "Automated ULP-diff
  test... CI fails on any regression past the pinned bound" acceptance
  criteria) — tracked as a follow-up; `test/fixtures/` per SPEC.md OQ-005
  doesn't exist yet either (this audit used a fixed sample grid, not a
  checked-in fixture table).
