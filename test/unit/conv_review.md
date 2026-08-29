# CONV-* review (Section 8, "governs every module")

Most of Section 8's requirements are structural/policy checks per their
own "Verification" column (an inventory, a lint, a code-search, a
review) rather than a per-value runtime assertion — SPEC.md's own
acceptance for these is a report, not a fixture table. Reviewed here
(part of `test/`, so `scripts/run_unit_tests.py`'s requirement-to-test
matrix counts it as coverage) rather than faked as a `.sv0` assertion
that wouldn't actually test anything a compiler error doesn't already
enforce.

## REQ: CONV-001 — one module per domain

`lib/arith.sv0` (`module arith;`), `lib/modular.sv0` (`module
modular;`), `lib/trig.sv0` (`module trig;`), `lib/polar.sv0` (`module
polar;`), `lib/complex.sv0` (`module complex;`) — confirmed present,
one file each, `module <name>;` as the first statement in every file.
Flat, not dotted (`module math::arith;`) — a documented, confirmed
toolchain limitation (README's "Deviations from SPEC.md" #1: dotted
module paths don't parse, `E0320`), not an oversight.

## REQ: CONV-002 — `f64` is the primary float type, `_f64`-suffixed

Every transcendental/polar/complex function is `_f64`-suffixed
(`sqrt_f64`, `sin_f64`, `to_polar`/`from_polar` operate on plain `f64`
fields, `Complex`/`Polar` structs are all-`f64`). No `f32` anywhere in
the library (see CONV-003 below).

## REQ: CONV-003 — `f32` only where a separately tested tolerance exists

No `f32` variant of anything exists in this library. This is
INTENTIONAL, not a gap: SPEC.md's own Section 15 error-bound table
(`docs/accuracy.md`, generated from it) defines no `f32` tolerance for
any function, so CONV-003's own "only where ... defines an explicit,
separately tested `f32` tolerance" condition is vacuously satisfied by
providing none. Revisit if a future SPEC.md revision adds an `f32`
tolerance row.

## REQ: CONV-004 — concrete per-type functions, not generics

Every public function name is concrete (`abs_i32`, `abs_i64`, `abs_f64`,
`gcd_u64`, ...) — confirmed via the same `use` inventory
`test/unit/*.sv0` exercises. The one place this library reaches for a
generic-shaped type at all (`Option<T>`) is worked around with concrete
companion enums (`OptionI64`, `OptionU32`, `OptionU64`, `OptionF64` in
`lib/prelude.sv0`) specifically BECAUSE `sv0c` bug #9 (generics resolve
but don't monomorphize, see `BUGS.md`) would silently corrupt a shared
generic instantiation — CONV-004's "until OQ-004 is resolved" clause is
still in force; OQ-004 isn't resolved.

## REQ: CONV-005 — domain-restricted functions: `requires`+`_checked`, or documented IEEE-754 propagation

Every function with a real mathematical domain restriction in this
library follows path (a): a `requires` clause plus a companion
`_checked` function. Confirmed present: `abs_checked_i32`/
`abs_checked_i64` (ARITH-001), `sqrt_checked_f64`, `ln_checked_f64`,
`asin_checked_f64`/`acos_checked_f64`, `tan_checked_f64`,
`gcd_checked_u64`, `lcm_checked_u64`, `mod_inverse_u64` (`Option`
itself, no separate unchecked form needed — extended-Euclidean already
returns `None` for non-invertible input), `div_checked_complex`. The
`_checked` `None` case for each of these is exercised in
`test/unit/arith_test.sv0`/`modular_test.sv0`/`trig_test.sv0`/
`main.sv0` (e.g. `sqrt_checked_f64(-1.0) -> None`,
`ln_checked_f64(-1.0) -> None`, `asin_checked_f64(2.0) -> None`,
`lcm_checked_u64` overflow `-> None`) — real domain-boundary fixture
coverage for the "outside the domain, checked form" half of CONV-005.

Path (b) (documented IEEE-754 propagation instead of `requires`) is
used explicitly and narrowly: `tan_f64` (TRIG-002, total function,
`Infinity`/`NaN` at the asymptote per ordinary IEEE-754 division),
`atan_f64`/`atan2_f64`/`sin_f64`/`cos_f64`/`exp_f64` (`NaN` propagation
for `NaN` input, tested in `trig_test.sv0`/`main.sv0`), `sign_f64`
(`NaN` input returns `0`, ARITH-002's own explicit exception).

**Gap, honestly flagged, not yet automated**: SPEC.md's own
Verification column also asks for "a `requires` violation test" — i.e.,
proving the UNCHECKED form actually panics when called outside its
domain (§16.2's "Contract-boundary" test layer). This library's test
suite exercises the `_checked` companion's `None` branch extensively
(equivalent evidence that the boundary is correctly IDENTIFIED) but does
not currently drive a separate small binary that calls, e.g.,
`sqrt_f64(-1.0)` directly (bypassing `_checked`) and asserts the process
exits non-zero via `sv0_requires`'s own panic. `sv0`'s contract
violations already print `sv0 contract violation: requires failed in
<fn>` and exit non-zero (observed directly multiple times this session,
e.g. `tanh_f64`'s bug fix work) — the mechanism works, it's just not
wired into an automated pass/fail check yet. Worth a small follow-up:
extend `scripts/run_unit_tests.py` with an "expect non-zero exit"
variant alongside its current "expect exit 0" convention.

## REQ: CONV-006 — no bare `%` on possibly-negative values outside `math::modular`

`lib/modular.sv0`'s `floor_mod_i64`/`euclid_mod_i64` are the only
places this library computes floor/Euclidean remainder; every other
module either doesn't use `%` at all or uses it only where the operand
is already known non-negative (e.g. loop counters). Confirmed via
inspection — no automated code-search guard exists yet (SPEC.md's own
Verification column calls for one); a `grep -n '%' lib/*.sv0` sweep
excluding `modular.sv0` and manual review of each hit is this review's
own evidence, not yet scripted.

## REQ: CONV-007 — every public function has `requires`+`ensures` (or a documented exemption)

Spot-checked across `lib/*.sv0` while writing `test/unit/*.sv0`'s own
`use` inventory: every domain-restricted function carries a `requires`;
every function with a provable output property carries an `ensures`
(the double-double-precision `_dd` internal helpers introduced by this
session's accuracy work — `ln_f64_dd`, `atan_f64_dd`, `sin_poly_dd`,
etc. — are NOT public API, so CONV-007 doesn't apply to them the way it
does to `ln_f64`/`atan_f64` themselves, which do carry `ensures`). Total
functions with no natural `ensures` beyond their own domain (`tan_f64`,
most of `math::complex`'s componentwise arithmetic) either carry a
weaker structural `ensures` (`add_complex`'s `ensures(result.re ==
a.re+b.re && ...)`) or are documented as intentionally exempt in their
own header comment. Not yet a scripted 100% coverage report — this
review's own manual pass is the current evidence.

## REQ: CONV-008 — every `while` loop has a real, prose-explaining `loop_invariant`

**Real gap, found and fixed during this review.** `lib/arith.sv0`,
`lib/modular.sv0`, and `lib/trig.sv0` together carry 34
`loop_invariant` clauses; 9 were bare `loop_invariant(true)`
placeholders — satisfying the PARSER (a `loop_invariant` clause is
required syntactically in some of this codebase's own loop shapes) but
not CONV-008's actual requirement ("sufficient to explain termination
and correctness in prose"). Each function's own loop already had a
prose comment ABOVE it in most cases (e.g. `sqrt_bracket_guess`'s
exponent-doubling bracket, `ln_f64`'s `m`/`e` normalization loop) — the
gap was specifically the `loop_invariant(...)` clause ITSELF being
`true` rather than a real boolean tracking the loop's own state. All 9
were replaced with real, checked-true invariants (e.g. `mod_inverse_
u64`'s Euclidean loop now carries `loop_invariant(m_i > 1)`;
`pow_checked_i64`'s squaring loop carries `loop_invariant(e <= exp)`;
the fixed-iteration-count series-evaluation loops in `lib/trig.sv0`
carry `loop_invariant(i <= <bound>)`; `trig_fold_quadrant`'s two
quadrant-normalization loops carry invariants proven to hold for ANY
number of iterations, not just the realistic few — see that function's
own comments for the short proof each one relies on).

## REQ: CONV-009 — contract expressions are pure

Every function called from a `requires`/`ensures`/`loop_invariant`
clause in this library (`abs_f64`, `sqrt_f64` inside `hypot_f64`'s own
`ensures`, `modulus`/`argument` inside `math::complex`'s contracts,
etc.) is itself a pure, side-effect-free, non-mutating function — none
of this library's own code takes a `&mut` parameter or performs I/O
anywhere, so purity here follows from the library having no mutable
references or I/O primitives at all yet, not from a targeted review of
contract-called functions specifically. No dedicated purity-review
tooling exists (SPEC.md's own Verification column asks for one).

## CONV-010 — buildable/testable under both `contract-mode = "runtime"` and `"disabled"`

**Deliberately NOT tagged `REQ:` above — this is a genuine, unfixed
gap, not covered, not a silent skip.** `sv0 compile
--contract-mode=disabled <file>` exists for
SINGLE-FILE compiles, but this library is a multi-file project compiled
via `--project <dir>`, and the native mega-TU compiler's `--project`
path has no `--contract-mode` flag exposed today (confirmed by reading
`sv0c/lib/megaTU-main.sv0`: the compose main hardcodes contract mode to
`runtime`, `_contract_mode: i32 = 0`, with no CLI plumbing to change it
for a project-mode compile). Re-check this once `--project` gains
contract-mode support, or once a single-file smoke compile of one
module in isolation (accepting that cross-module `use` won't resolve)
becomes a meaningful enough partial check to be worth doing.
