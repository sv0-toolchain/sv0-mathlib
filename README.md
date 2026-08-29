# sv0-mathlib

A numeric library for the [sv0](https://github.com/sv4u/sv0-toolchain)
programming language: arithmetic, modular arithmetic, trigonometry, polar
coordinates, and complex numbers, built contract-first per
[SPEC.md](https://github.com/sv4u/project-specs/blob/main/sv0-mathlib/SPEC.md).

## Status

**F0 complete. R0.1 complete. R0.2 complete. R0.3 complete.**
`math::polar` (`Polar` struct, `to_polar`/`from_polar`, `scale_polar`/
`rotate_polar`) and `math::complex` (`Complex` struct, componentwise +
multiplicative arithmetic as free functions, `modulus`/`argument`/
`conjugate`, polar interoperability, `approx_eq`) are both done. See
README's "Deviations from SPEC.md" for why `math::complex`'s operators
are free functions (not `impl Add`/etc.), `from_polar` returns a struct
(not a tuple), and `div_checked_complex` returns a plain struct (not
`Option<Complex>`) — three more real, confirmed toolchain gaps found
finishing this module.

**PERF-002's accuracy budget is now formally met and CPLX-007 is
unblocked.** `docs/accuracy.md` records a measured maximum ULP error for
every non-exact `math::trig` function (PERF-001); all ten
(`sqrt_f64`/`sin_f64`/`cos_f64`/`tan_f64`/`asin_f64`/`acos_f64`/
`atan_f64`/`atan2_f64`/`exp_f64`/`ln_f64`) now pass their pinned budget —
several started this audit pass off by orders of magnitude (`acos_f64`
measured 3029 ULP against a 3 ULP budget; `exp_f64` measured 714 against
2) and were fixed via double-double (Dekker/Knuth-Møller) arithmetic
carried through range reduction, quadrant folding, and series
evaluation, the same technique `fma_f64` (ARITH-010) already used —
see `docs/accuracy.md` for the full table and root-cause notes.
`exp_complex`/`ln_complex`/`pow_complex` (CPLX-007) are implemented in
`lib/complex.sv0`, verified via Euler's identity.

**F0's own surface, including `abs_checked_i64`:** `math::arith`'s ARITH-001..004
are fully implemented and contract-checked: all i32, i64, and f64 forms
(`abs_i32`/`abs_i64`/`abs_f64`, `sign_i32`/`sign_i64`/`sign_f64`,
`min_i32`/`min_f64`, `max_i32`/`max_f64`, `clamp_i32`/`clamp_f64`), plus
`abs_checked_i32`/`abs_checked_i64` (`Option`/`OptionI64`-returning) and
the shared `prelude` (`Option`/`Result`/`OptionI64`). Verified on the **C
backend** by inspecting the emitted C directly, not just exit codes —
correct `int`/`int64_t`/`double` typing throughout (params, locals,
contract-result slots, call-result temps, enum payload struct fields, and
match-arm payload bindings), real `i64`-magnitude values round-tripping
correctly, and `Option`/`Result`/`OptionI64` compiling to real
tagged-struct types with working `Some`/`None` match logic. The **VM
backend** now type-checks and lowers this library's i32/i64 forms
correctly (bug #2's checker-level fix) but still can't compile the f64
forms — see BUGS.md #2 for why (VM bytecode has no float representation
at all, a separate, larger gap) — and a duplicate-type issue once more
than one file imports the same type; see BUGS.md's "Not yet working".

See [BUGS.md](BUGS.md) for fifteen toolchain gaps found across F0, R0.1,
R0.2, R0.3, and the accuracy-audit pass. **Eleven are fixed**: bug #5
(`f64` silently compiling as `int`), bug #3 (generic enums like
`Option<T>` failing to resolve), bug #1 (integer literals wider than i32
truncating), bug #7 (an explicit `let x: f64 = <arithmetic-expr>;` local
silently defaulting to `int`), bug #8 (enum payload slots and match-arm
payload bindings always `int`), bug #6's silent-diagnostics half (a
parse failure used to exit nonzero with zero error text — the same fix
also surfaced and fixed a real, sv0-mathlib-unrelated pre-existing bug in
sv0c's own test corpus, bare struct-field assignment statements silently
compiling to nothing), bug #2's checker-level half (the VM-path checker
rejected i64/u32/f64 arithmetic anywhere, not just in contracts — VM
bytecode float *lowering* remains a separate, larger, unfixed gap), bug
#10 (`loop_invariant` anywhere in a file corrupting name resolution for
an unrelated earlier function), bug #11 (`match` on a direct call
result, no intermediate `let`, mistyping the payload binding), bug #13
(a binop directly on a struct field access mistyping its own temp), and
bug #14 (a struct field name token landing at a coincidental source
position `500-599` was silently misread as an unrelated
tuple-projection index — found via `math::trig`'s first struct literal).
**Three remain genuine open gaps, each with a documented, verified
workaround this library uses instead**: bug #9 (generic enums resolve
but don't monomorphize — `abs_checked_i64` uses a concrete `OptionI64`
instead of the shared `Option<T>`), bug #12 (`match` used as a value
mistypes its own result temp — worked around via match-as-statement,
used throughout `pow_checked_i64` onward), and bug #15 (an inline struct
literal passed directly as a function-call argument sometimes resolves
its field names against the wrong struct declaration, found finishing
CPLX-007 — worked around by binding struct literals to a `let` before
passing them as arguments), plus the VM bytecode float-lowering gap
noted above.

## Tier 1 / Tier 2

No native transcendental math (`sqrt`, `sin`, `cos`, …) exists anywhere in
the sv0 toolchain — not as a keyword, stdlib function, C runtime symbol, or
VM opcode. Every function in this library is **Tier 1**: implemented in pure
sv0 using arithmetic operators only, portable to every backend without a
compiler change. A **Tier 2** (native-builtin-backed) tier is a possible
future direction, not a commitment — see SPEC.md §4.3 and §22 OQ-003.

## Deviations from SPEC.md

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
2. **Repo lives as a sibling of `sv0-toolchain`, driven by relative
   `--project` paths**, resolving SPEC.md §22 OQ-002 in practice ahead of
   a formal decision: `./scripts/sv0 vm-project-compile ../../sv0-mathlib`
   and `build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib`
   both work today from a `sv0-toolchain` checkout. No `sv0.toml` exists in
   the toolchain to root a project a different way.
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

## Build and test

From an `sv0-toolchain` checkout, with `sv0-mathlib` checked out as a
sibling directory:

```bash
# C backend (native compiler)
build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib > /tmp/mathlib.c
cc -std=c99 -O0 -w -I sv0c/runtime /tmp/mathlib.c sv0c/runtime/sv0_runtime.c -o /tmp/mathlib_bin
/tmp/mathlib_bin; echo $?   # 0 = pass

# VM backend — still doesn't compile this library end to end: the
# duplicate-Option-type issue (BUGS.md "Not yet working") blocks it before
# the f64 forms' own separate bytecode-float gap (BUGS.md #2) would.
./scripts/sv0 vm-project-compile ../../sv0-mathlib
./scripts/sv0 vm-run sv0c/build/vm/main.sv0b
```

When touching `f64` code, don't trust an exit code alone — grep the emitted
C for `double` where you expect it (see BUGS.md #5's fix for exactly how
this bit us once already).

`main.sv0` currently doubles as the ARITH-001 test binary (0 = pass,
nonzero = first failing case index) — see `main.sv0`'s comment for why the
per-function `test/unit/<fn>_test.sv0` layout SPEC.md §16.1 describes isn't
wired up yet (the project tooling has no multi-entry-point convention we've
confirmed works).

## Repository layout

```text
sv0-mathlib/
├── README.md
├── BUGS.md          # toolchain gaps found during development
├── main.sv0         # smoke/demo entry point (also the full test suite today)
├── lib/
│   ├── arith.sv0     # module arith — F0 arithmetic core (Section 11)
│   ├── modular.sv0   # module modular — R0.1/R0.2 modular arithmetic (Section 12)
│   ├── trig.sv0       # module trig — R0.2 sqrt/trig/exp/ln (Section 13-14)
│   ├── polar.sv0      # module polar — R0.3 polar coordinates (Section 17)
│   ├── complex.sv0    # module complex — R0.3 complex numbers, incl. CPLX-007 (Section 18)
│   └── prelude.sv0   # module prelude — shared Option/Result declarations
├── test/{unit,fixtures,property,parity}/
└── docs/
    └── accuracy.md   # PERF-001/PERF-002: measured ULP error per non-exact function
```
