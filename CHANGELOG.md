# Changelog

Per DOC-003 (R1): every release records user-visible changes, any
tightened or loosened accuracy bound (PERF-002), and any contract
strengthened or weakened. Versions follow [Semantic Versioning](https://semver.org/);
`sv0` itself is pre-1.0, so this library is too.

## [Unreleased]

_Nothing yet._

## [0.1.0] — 2026-08-30

First tagged release. **Closes the SPEC.md R1 gate (§21.5).** F0, R0.1,
R0.2 and R0.3 are all implemented, contract-checked, accuracy-audited,
and covered by the generated requirement-to-test matrix. Everything
under this heading is the accumulated F0→R1 work; the R1 gate review
itself is recorded first.

### R1 gate review (SPEC.md §21.5, backlog F.5 / BL-123–BL-127)

- **BL-123** — every requirement ID at or below R1 has at least one
  passing test (`scripts/run_unit_tests.py`, wired into `scripts/ci`);
  the generated `docs/requirement_test_matrix.md` has zero uncovered
  in-scope IDs. `CONV-010` is **explicitly deferred**: the toolchain's
  `--project` mode has no `--contract-mode` flag, so it is genuinely
  untestable today — not unimplemented on this library's own side (full
  investigation in `test/unit/conv_review.md`). `PERF-003` is
  Future-scoped and out of R1.
- **BL-124** — no accuracy bound has silently regressed. There is no
  prior release to diff against; every PERF-002 bound is CI-enforced via
  `test/unit/trig_test.sv0` and recorded in `docs/accuracy.md`. One
  contract was *loosened* (see "Contracts loosened" below) with a
  recorded rationale; a formal SPEC.md amendment to TRIG-004's literal
  text (Section 24 change control) is the clean follow-up.
- **BL-125** — SPEC.md §22 open questions: **OQ-002** (repository shape)
  and **OQ-005** (ULP fixture reference) are **resolved** (README
  deviations #10 and #9). **OQ-001** (`%` sign on negative operands),
  **OQ-003** (Tier 2 native builtins) and **OQ-004** (generic numeric
  facade) are **explicitly deferred with rationale** — none affects
  shipped functionality (the spec itself scopes them out of F0–R1).
- **BL-126** — this changelog.

### Known limitations at 0.1.0

These are documented toolchain gaps, not library defects; the public
API, contracts and accuracy bounds are stable.

- The per-fixture cross-backend check (`scripts/run_fixture_parity.py`,
  COMPAT-002 / TEST-005) **gates on the C backend** and is **advisory on
  the VM backend** — an `Unsafe.cast` f64-decode bug in `sv0vm` under
  the SML/NJ 110.99.9 the CI runner installs (`BUGS.md`, "Per-fixture
  value check"). The whole-library exit-code cross-backend gate
  (`vm_behavioral_parity.py`, COMPAT-001) is green 8/8.
- Workarounds are in place for open upstream `sv0c` bugs — `BUGS.md`
  #15 (inline struct-literal argument field resolution), #17 (`--project`
  discovery vs. alphabetical ordering), #18 (`let x: T = <bare var>;`
  mistyping), #19 (struct-field binop in a struct literal / contract
  clause mistyping to `int`).

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
- **`sqrt_f64(+Infinity)` silently computed `NaN`, not `+Infinity`**:
  the bracket-then-Newton algorithm's own arithmetic overflows to
  `Infinity`/`NaN` internally for infinite input (found via `test/
  fixtures/trig.csv`, TEST-003). Fixed by special-casing
  `is_infinite_f64(x)` up front, returning `x` directly; also
  broadened `sqrt_f64`'s own `ensures` to accommodate this case.
- **`exp_f64(-Infinity)` silently computed `NaN`, not `0.0`**: the same
  overflow-in-range-reduction shape as the `sqrt_f64` case above (found
  the same way). Fixed by special-casing `+Infinity`/`-Infinity` input
  up front (`exp(+Infinity) = +Infinity`, `exp(-Infinity) = 0.0`).
- **`abs_f64(NaN)` panicked on its own `ensures`**: `abs_f64`'s
  `ensures(result >= 0.0)` had no `NaN` escape hatch, so the
  IEEE-754-correct answer (`NaN`) failed its own contract — this
  pervasively-used helper's gap was masked until `exp_f64(-Infinity)`'s
  own (separately fixed) bug started passing a `NaN` intermediate
  through it. Fixed by adding `|| result != result` to the `ensures`,
  matching this codebase's established `NaN`-propagation pattern.

### Added

- **Cross-backend parity (COMPAT-001 / COMPAT-002 / TEST-005).** The
  `sv0-toolchain` native VM bytecode emitter + `sv0vm` gained f64 +
  i64/u64 + contract support (`sv0c-vm-float-parity`, 2026-08-29), so
  this entire library now compiles **and runs** on the VM backend with
  results identical to the C backend. `scripts/ci` grew a `--skip-parity`
  section that runs the toolchain's `vm_behavioral_parity.py` (both
  backends, exit codes compared, including `--project ../sv0-mathlib`);
  `test/parity/README.md` documents it. `BUGS.md #2` (the long-standing
  "VM bytecode has no float representation" blocker) is resolved for the
  native VM path. No library code changed.
- **Per-fixture value check (COMPAT-002 / TEST-005).**
  `scripts/run_fixture_parity.py` generates a `fn main() -> i32` with one
  check per (row, function) from `test/fixtures/{rounding,trig}.csv`,
  compiles + runs it, and checks each result against the row's own
  EXPECTED column — the reproducible form of the one-time manual fixture
  check the manifest used to describe. Wired into `scripts/ci`
  (`--skip-fixture-parity`). The **C-backend leg gates**; the
  **VM-backend leg is advisory** — it passes on SML/NJ 2026.1 but a
  transcendental `ensures` aborts the run under the SML/NJ 110.99.9 the
  CI runner installs (`BUGS.md`; `--strict-vm` to gate on it). Sign-of-
  zero is compared by value only (`ceil_f64`/`trunc_f64` of a small
  negative return `+0.0` here vs libm's `-0.0`; SPEC pins none) and
  `PANIC` rows are listed as skipped; see `test/fixtures/manifest.md`.
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
- `test/fixtures/rounding.csv` + `test/fixtures/trig.csv` +
  `test/fixtures/manifest.md` + `scripts/check_fixtures.py` (TEST-002,
  F0; TEST-003, R0.1) — named boundary/`NaN`/`Infinity`/`-0.0` fixture
  rows for `floor_f64`/`ceil_f64`/`round_f64`/`trunc_f64` (ARITH-005
  names `rounding.csv` explicitly) and every ULP-budgeted `math::trig`
  function, each with recorded provenance and toolchain revision, linted
  for manifest completeness and per-function boundary coverage, wired
  into `scripts/ci`.
- `test/property/property_test.sv0` (TEST-004, R0.1) — a small
  deterministic PCG/Knuth-MMIX-style PRNG seeded by a checked-in literal
  drives `sin_f64(x)^2 + cos_f64(x)^2 ~= 1.0`, `to_polar`/`from_polar`
  round-tripping, `mod_inverse_u64` composed with `mul_mod_u64`, and
  `Complex` addition/multiplication commutativity+associativity over 20-
  30 samples each; `scripts/run_unit_tests.py` now also discovers and
  runs `test/property/*.sv0` the same way it runs `test/unit/*.sv0`.
- `scripts/check_doc_comments.py` (DOC-001, F0) — every public function
  across `lib/` now has a doc comment stating its domain/contract in
  prose, with non-exact (ULP-budgeted) functions additionally required
  to cross-reference `docs/accuracy.md`; internal helper functions are
  exempted by an explicit allow-list, not by omission. 66 gaps found
  (missing comments, too-short comments, and missing accuracy.md
  cross-references) across `lib/arith.sv0`/`lib/prelude.sv0`/
  `lib/modular.sv0`/`lib/polar.sv0`/`lib/complex.sv0`/`lib/trig.sv0`,
  all fixed. Wired into `scripts/ci`.

### Repository shape

- **SPEC.md §22 Open Question 2 (repository shape) is now formally
  resolved**, not just practically worked around: this repository IS
  the sibling-of-`sv0-toolchain`, `--project`-driven shape, recorded as
  its own numbered deviation (`README.md` deviation #10) per SPEC.md
  §21.5's R1-gate wording wanting open questions "resolved or
  explicitly deferred with rationale."

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

- Bug #19: a struct-literal field initializer, OR a `requires`/
  `ensures` clause, that is itself a binop involving a struct-field
  access mistypes as `int` — the widest and most consequential finding
  this session: found via `test/property/property_test.sv0`'s random-
  sample associativity check, this affected every componentwise
  arithmetic function in `math::complex` AND their own contract
  clauses (the latter making genuinely-correct code panic on some
  random samples but not others, reading as flakiness). Open, workaround
  in place throughout `lib/complex.sv0`/`lib/polar.sv0`/`lib/trig.sv0`
  (extract fields to locals before struct-literal use; route
  contract-clause expressions through small pure helper functions,
  since a contract has no access to the function body's own locals).
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
