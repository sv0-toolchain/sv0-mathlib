# Changelog

Per DOC-003 (R1): every release records user-visible changes, any
tightened or loosened accuracy bound (PERF-002), and any contract
strengthened or weakened. No version has been tagged yet — everything
below is accumulated under `[Unreleased]` until the R1 gate review tags
one (SPEC.md §21.5).

## [Unreleased]

### Accuracy bounds tightened (PERF-002)

Every function below started a widened ULP accuracy audit
(`docs/accuracy.md`, `docs/ulp_audit_harness.c`) FAILING its budget —
several by orders of magnitude — and was brought within it via
double-double (Dekker/Knuth-Møller) arithmetic fixes. No behavior
outside the last 1-3 bits of precision changed for any of these; see
`docs/accuracy.md`'s own notes for the full root-cause writeup per
function.

| Function | Before | After | Budget |
|---|---:|---:|---:|
| `sin_f64` | ~50,000–98,000 ULP | 1 ULP | 3 |
| `cos_f64` | ~50,000–98,000 ULP | 1 ULP | 3 |
| `tan_f64` | (inherited from sin/cos) | 3 ULP | 3 |
| `asin_f64` | 12 ULP | 2 ULP | 3 |
| `acos_f64` | 3029 ULP | 3 ULP | 3 |
| `atan_f64` | 4 ULP | 1 ULP | 3 |
| `atan2_f64` | 5 ULP | 2 ULP | 3 |
| `exp_f64` | 714 ULP | 1 ULP | 2 |
| `ln_f64` | 62 ULP | 1 ULP | 2 |
| `sinh_f64` | 121 ULP (via `tanh_f64`'s division) | 1 ULP | 3 (informational — TRIG-005 has no SPEC-pinned budget) |
| `cosh_f64` | 1 ULP (no fix needed) | 1 ULP | 3 (informational) |
| `tanh_f64` | 121 ULP | 2 ULP | 3 (informational) |
| `hypot_f64` | 3 ULP (no fix needed) | 3 ULP | 3 (informational) |
| `exp_complex` | 21 ULP (harness measurement artifact, not a code defect — see notes) | 1 ULP | 3 (informational — CPLX-007 has no SPEC-pinned budget) |
| `ln_complex` | 234 ULP | 14 ULP (real, understood residual, documented — not fully under the informational budget) | 3 (informational) |

`pow_complex` was audited (informational 5 ULP budget) but not
"tightened" in the usual sense — its large nominal FAIL was traced to
system libm's own `cpow`/`cexp` not being correctly rounded at the
worst-offending points (confirmed against an independent
arbitrary-precision reference), not a defect in this library. See
`docs/accuracy.md`'s notes.

### Contracts loosened

- **`atan_f64`'s `ensures`** relaxed from TRIG-004's literal strict
  `result > -pi/2 && result < pi/2` to `result >= -pi/2 && result <=
  pi/2`. A correctly-rounded `f64` `atan` legitimately returns exactly
  the nearest representable double to `pi/2` for sufficiently large
  `|x|` (confirmed against the system libm directly: `atan(1e50)`,
  `atan(1e300)`, etc. all return `== M_PI/2` in plain C) — a strict
  inequality is unsatisfiable for an accurate double-precision
  implementation, and the accuracy work above made hitting this
  boundary MORE likely, not less (an earlier, less accurate version
  happened to round just short of it by coincidence). Matches
  `sin_f64`/`cos_f64`'s own boundary-inclusive convention. See
  `README.md`'s "Deviations from SPEC.md".

### Bugs fixed (not accuracy-budget misses — real defects)

- **`tanh_f64` ensures panic**: the `|x| > 20.0` pre-clamp wasn't tight
  enough — `exp_f64(2*x)` underflows enough for `(e2x-1)/(e2x+1)` to
  round to exactly `+/-1.0` starting around `|x| ~= 19.98`, crashing
  (`sv0 contract violation: ensures failed in tanh_f64`) for input as
  unremarkable as `x = -19.999`. Fixed by checking the actual computed
  result against the boundary, in addition to (not instead of) the
  pre-clamp, which is still needed to avoid a separate
  `Infinity/Infinity = NaN` failure mode for genuinely large `|x|`.
- **`tanh_f64` near-zero cancellation**: `exp_f64(2*x)` near `x = 0` is
  close to `1.0`, so `e2x - 1.0` catastrophically cancelled (121 ULP);
  `tanh_f64` (unlike `sinh_f64`, which already had a near-zero Taylor
  branch) had no cancellation-free path there at all. Fixed by
  delegating to `sinh_f64(x) / cosh_f64(x)` for `|x| < 1.0`.
- **`ln_f64`/`sin_f64`/`cos_f64`/`atan_f64` silently truncated to `int`**
  under a newer upstream `sv0c` revision than this library had
  previously been tested against (found setting up TEST-006's CI gate,
  which tracks the moving upstream default branch rather than a pinned
  SHA): each ended with a bare `return field_a + field_b;` combining two
  fields of the same double-double `Pair2` struct instance, a regression
  past `sv0c` bug #13's own fix (`BUGS.md` #16) that silently mistyped
  the result as `int` (`ln_f64(10.0)` returned exactly `2`, not a small
  accuracy miss). Fixed by copying each field into its own local before
  the addition, mirroring bug #13's own established workaround.

### Added

- `exp_complex`/`ln_complex`/`pow_complex` (CPLX-007) — gated on
  `sin_f64`/`cos_f64`/`exp_f64`/`ln_f64` meeting PERF-002, now
  confirmed met, so implemented rather than left "Future". Verified
  functionally via Euler's identity and an `exp(ln(z)) == z`
  round-trip, and accuracy-audited (see table above).
- `docs/accuracy.md` (PERF-001) — one row per non-exact public
  function with its measured maximum ULP error, algorithm parameter,
  and toolchain revision.
- `docs/ulp_audit_harness.c` — the standalone C ULP-audit harness used
  to produce every number above, checked in (previously lived only in
  a local scratch file) with its own usage instructions.
- This changelog (DOC-003).
- `scripts/ci` + `.github/workflows/ci.yml` (TEST-006, R1) — a
  dedicated CI gate for this repo: `.sv0` whitespace formatting and the
  block-comment nesting guard via the SAME scripts `sv0-toolchain`'s
  own `./scripts/sv0 test-guards` uses (real parity with the upstream
  toolchain, not a local copy that could drift), plus a full
  compile+run of this project. Runs locally (`bash scripts/ci`, assumes
  a sibling `sv0-toolchain` checkout — `SV0_TOOLCHAIN_ROOT` overrides)
  and in GitHub Actions on every push/PR (which bootstraps a sibling
  `sv0-toolchain` checkout first: SML/NJ install, `./scripts/sv0
  check`, then `build-sv0-megatu-native.sh`).
- `test/unit/{arith,modular,trig,polar}_test.sv0` + `test/unit/
  conv_review.md` + `scripts/run_unit_tests.py` (TEST-001, F0) — every
  requirement ID in SPEC.md Sections 8/11/12/13/15/17 now maps to at
  least one test, generated into `docs/requirement_test_matrix.md`
  and wired into `scripts/ci`. Only CONV-010 is deferred (explicitly,
  with rationale — `--project`-mode has no `--contract-mode` flag
  today, genuinely untestable, not unimplemented on this library's own
  side).

### Contracts strengthened

- **9 of 34 `loop_invariant` clauses** across `lib/arith.sv0`/
  `lib/modular.sv0`/`lib/trig.sv0` were bare `loop_invariant(true)`
  placeholders (CONV-008 wants a real, prose-explained invariant, not
  just syntax satisfied) — found and fixed while writing `test/unit/
  conv_review.md`. All 9 replaced with real, checked-true invariants
  (e.g. `mod_inverse_u64`'s `loop_invariant(m_i > 1)`,
  `pow_checked_i64`'s `loop_invariant(e <= exp)`, the fixed-iteration
  series loops' `loop_invariant(i <= <bound>)`,
  `trig_fold_quadrant`'s two quadrant-normalization loops proven for
  ANY iteration count, not just the realistic few).

### Toolchain gaps found (informational — see `BUGS.md` for full detail)

- Bug #17: `--project` file discovery silently fails (exit 2, zero
  diagnostics) when a top-level file or directory sorts alphabetically
  before `lib` — found setting up `test/unit/`. Open, workaround in
  place (stage each unit test file inside a subdirectory that sorts
  after `lib`).
- Bug #18: `let x: StructType = <bare variable already of that
  type>;` mistypes the new local as `int` — found writing `test/unit/
  polar_test.sv0`'s own `Copy`-derivation test. Open, workaround in
  place (route the copy through a trivial identity function call).
- Bug #15: an inline `Complex { ... }` struct literal passed directly
  as a function-call argument sometimes resolves its field names
  against the wrong struct declaration. Open, workaround in place
  (bind to a `let` first), follow-up task spawned to root-cause it in
  `sv0c`.
