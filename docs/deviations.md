# Deviations from SPEC.md

Recorded here per the spec's own GOV-004 (don't silently guess when the
toolchain and the spec disagree — write down the deviation and why).

1. **Module names are flat, not dotted.** SPEC.md's CONV-001 calls for
   `module math::arith;` etc. The compiler rejects dotted module paths
   (`E0320: module path must be a single identifier in this slice`), so
   this repo uses flat names instead: `arith`, `modular`, `trig`, `polar`,
   `complex`, `prelude` (for the shared `Option`/`Result` declarations).
   Consumers write `use arith::abs_i32;`, not `use math::arith::abs_i32;`.
   `lib/lib.sv0` (the umbrella re-export SPEC.md's CONV-001 describes) is
   not present — no `pub use` re-export syntax exists in sv0 today, so
   there's nothing for it to do yet.
2. **Repo lives as a git submodule of `sv0-toolchain`
   (`sv0-toolchain/sv0-mathlib/`), driven by `--project` paths** — see
   deviation #10 below for this being this library's own formal
   resolution of SPEC.md §22 OQ-002, not just a practical workaround:
   `./scripts/sv0 vm-native-compile --project sv0-mathlib` and
   `build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib`
   both work from a `sv0-toolchain` checkout. No `sv0.toml` exists in
   the toolchain to root a project a different way. (It stays its own
   GitHub repository with its own history, tags and releases; the
   superproject just pins a commit.)
3. **`abs_checked_i64` returns `OptionI64`, a second concrete enum, not
   `Option<T>` instantiated at `i64`.** sv0 generic enums resolve (BUGS.md
   #3) but the compiler doesn't monomorphize them: there is exactly one
   physical struct for `Option<T>`, and its payload slot's C type is
   resolved from the *declaration's* own payload type token — for a
   generic enum that token is the literal parameter name `T`, never a
   concrete type. Reusing the shared `Option<T>` for an `i64` payload would
   silently truncate it through the same 32-bit-`int` bug BUGS.md #8 fixed
   for the non-generic case. `lib/prelude.sv0` declares `OptionI64`
   (concrete, `Some(i64)`/`None`) as a dedicated companion instead — see
   BUGS.md #9. Not a scalable pattern past a handful of concrete `_checked`
   return types; worth revisiting before R0.1+'s larger `_checked` surface
   if bug #9 isn't fixed by then.
4. **`sqrt_f64`/`sqrt_checked_f64` live in `lib/trig.sv0`, not
   `lib/arith.sv0`.** SPEC.md fully specifies both (Section 14.3's
   Newton-Raphson algorithm, Appendix C's worked `sqrt_checked_f64`
   contract, PERF-002's 2 ULP requirement) but never assigns either a
   requirement ID or a home module — neither `math::arith`'s scope
   (Section 11) nor `math::trig`'s own scope (13.1, which lists sin/cos/
   tan/asin/acos/atan/atan2/sinh/cosh/tanh/degree-radian conversion/
   hypot, but not "sqrt") names it. Placed in `math::trig` because
   `hypot_f64` (TRIG-007) needs it directly and AD-004 already groups
   "Newton-Raphson for roots" with "trig" as one combined design
   decision — see `lib/trig.sv0`'s own header comment for the full
   reasoning.
5. **`math::complex`'s operators are free functions, not `impl Add`/
   `impl Sub`/`impl Neg`/`impl Mul`/`impl Div for Complex`.** CPLX-002/
   CPLX-003 specify operator-trait desugaring; this compiler slice does
   not parse `impl <Trait> for <Type>` at all (`error[E0100]: syntax
   error`, confirmed empirically — not merely an unimplemented
   desugaring), matching an already-known gap from earlier in this
   project's toolchain audit. `add_complex`/`sub_complex`/`neg_complex`/
   `mul_complex`/`div_complex` provide the same operations, called
   explicitly instead of via `+`/`-`/`-x`/`*`/`/`.
6. **`math::polar`'s `from_polar` returns a `Point2` struct, not a
   tuple.** POLAR-003 specifies `(f64, f64)`; this compiler slice
   rejects multi-element tuples outright (`E0446: multi-element tuples
   are not supported in this slice`, confirmed empirically).
7. **`math::complex`'s `div_checked_complex` returns a `ComplexResult
   { ok: bool, re: f64, im: f64 }` struct, not `Option<Complex>`.**
   Beyond BUGS.md #9 (the shared generic `Option<T>` doesn't
   monomorphize), a STRUCT payload hits a deeper wall: an enum's
   payload slot in this compiler is always a single scalar C word — no
   slot category exists for "a whole struct," so even a concrete
   `enum OptionComplex { Some(Complex), None }` fails at the C level
   (`error: assigning to 'int' from incompatible type 'Complex'`,
   confirmed empirically). `div_checked_complex` returns the same
   "no panic on runtime-unknown input" behavior AD-005 wants without
   needing an enum payload to hold a struct at all.
8. **`atan_f64`'s `ensures` uses `>=`/`<=`, not TRIG-004's literal
   strict `>`/`<`.** True `atan(x)` lies in the open interval
   `(-pi/2, pi/2)`, but a correctly-rounded `f64` `atan` legitimately
   returns exactly the nearest representable double to `pi/2` for
   sufficiently large `|x|` — confirmed against the system libm directly
   (`atan(1e50)`, `atan(1e300)`, etc. all return `== M_PI/2` in plain C,
   not `sv0-mathlib`-specific). A strict inequality is unsatisfiable for
   an accurate double-precision implementation; the non-strict form
   matches `sin_f64`/`cos_f64`'s own boundary-inclusive convention. See
   `docs/accuracy.md` for the full accuracy audit this was found during.
9. **The Section 15 ULP fixture tables' authoritative reference is the
   system libm (`<math.h>`), not a hand-derived arbitrary-precision
   computation checked into this repository — resolving SPEC.md §22
   Open Question 5.** SPEC.md assumed the latter by default but didn't
   mandate it. In practice, `docs/ulp_audit_harness.c` (checked in)
   compares every function directly against the system's `<math.h>`/
   `<complex.h>` implementations, which is simpler, has no extra
   toolchain dependency, and covers the full swept domain rather than a
   fixed checked-in table. The one place this needed reinforcing:
   system libm is NOT always correctly rounded itself (found auditing
   `pow_complex` — `cpow`/`cexp` measured genuinely less accurate than
   this library at some points, confirmed against an independent
   arbitrary-precision reference, `mpmath`, used ad hoc as a
   second-opinion check rather than as the primary fixture source — see
   `docs/accuracy.md`'s own notes on `pow_complex`). `test/fixtures/`
   (TEST-002/TEST-003) DOES now exist — `rounding.csv`/`trig.csv` —
   but as a small set of named, discrete boundary/special-value points,
   not a full checked-in reference table for the broad ULP sweep itself;
   that broad sweep still runs against system libm directly, live, per
   this deviation's own resolution.
10. **This repository is a git submodule of `sv0-toolchain`
    (`sv0-toolchain/sv0-mathlib/`), `--project`-driven — resolving
    SPEC.md §22 Open Question 2.** OQ-002 asked whether the library
    ships as its own `sv0.toml`-rooted project *or* "as a copyable
    tree inside `sv0-toolchain` itself" — this is the latter, made
    concrete: a pinned submodule alongside `sv0c`/`sv0vm`/`sv0doc`,
    so a `sv0-toolchain` checkout is the single working tree and the
    `--project sv0-mathlib` cross-backend parity entry is always
    present (`sv0-toolchain/scripts/vm_behavioral_parity.py`). It
    keeps its own history, tags and releases as an independent
    GitHub repo. (Through v0.1.0 this deviation recorded the
    *sibling* layout; the submodule is a mechanical consolidation of
    the same "tree inside sv0-toolchain" answer — no `sv0.toml`-rooted
    convention exists in the toolchain to root a project a different
    way, confirmed empirically.)
11. **`math::random` is beyond SPEC.md, and deliberately not
    cryptographic.** SPEC.md has no PRNG section; the module grew out of
    the property-test generator that TEST-004 requires (fixed,
    checked-in seed, reproducible failures) once it needed a second
    consumer. Consequences worth knowing:
    - It has no requirement IDs, so it is absent from
      `docs/requirement_test_matrix.md`. It is instead covered by
      `test/unit/random_test.sv0`, the golden rows in
      `test/fixtures/random.csv` (produced by an independent C oracle,
      `docs/random_oracle.c`, and checked on both backends), and the
      seeded property tests.
    - The generator is a 64-bit LCG (Knuth's MMIX constants). Its state
      is its output, so one value reveals every later one, and its low
      bits are weak. It is for tests and simulation only. Nothing in the
      planned M5 crypto work (hashing, AEAD, signatures) may draw keys,
      nonces or salts from it.
    - State is threaded by value (`state = next_u64(state)`) because sv0
      has no globals. `below_u64` returns a `BelowU64 { value, state }`
      struct because rejection sampling consumes a variable number of
      draws and this compiler slice has no tuples (same reason as
      deviation 6).
    - `unit_f64` returns values in `[0.0, 1.0)` using the top 53 bits.
      The earlier property-test helper divided the full `u64` by
      `2^64 - 1`, which rounds the highest states to exactly `1.0`.
      `uniform_f64` is closed at the top (`[lo, hi]`), because
      `lo + u * (hi - lo)` can round up to `hi`.
12. **`math::stats` is beyond SPEC.md, and is a streaming accumulator, not
    a function over a sample.** SPEC.md has no statistics section. The
    module cannot take a `Vec<f64>`, array or slice of observations,
    because the toolchain stores collection elements in integer slots and
    silently truncates `f64` (BUGS.md #20). A `Stats` value is instead
    threaded by value: `s = stats_push(s, x);`. Consequences:
    - Provided: count, sum (Neumaier compensated), mean, population and
      sample variance and standard deviation (Welford with a double-double
      running mean), min, max, range; accuracy measured in `docs/accuracy.md`.
    - **Not provided:** median and percentiles, which need the whole
      sample. They wait on the upstream fix for BUGS.md #20.
    - Total functions with no panics. An undefined result (no observations,
      or fewer than two for sample variance) is NaN, so callers should
      check `stats_count` first. This is the CONV-005(b) style already used
      elsewhere in the library, not a `requires` clause, because a contract
      on a struct-field access trips BUGS.md #19.
    - A NaN observation makes every result NaN. Infinite observations are
      counted and reflected: sum and mean are +/-infinity (NaN if both
      signs appear), min/max see them, and variance and standard deviation
      are NaN.
    - Like `random`, it has no requirement IDs; `test/unit/stats_test.sv0`
      covers it on both backends.
