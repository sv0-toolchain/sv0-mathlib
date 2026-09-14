# sv0-mathlib

A numeric library for the [sv0](https://github.com/sv4u/sv0-toolchain)
programming language: arithmetic, modular arithmetic, trigonometry, polar
coordinates, and complex numbers, built contract-first per
[SPEC.md](https://github.com/sv4u/project-specs/blob/main/sv0-mathlib/SPEC.md).

**Status: `v0.1.0`, released 2026-08-30.** The full SPEC.md ladder (F0
through the R1 gate, §21.5) is implemented, contract-checked,
accuracy-audited, and covered by a generated requirement-to-test matrix.
See [CHANGELOG.md](CHANGELOG.md) for the release history and
[docs/deviations.md](docs/deviations.md) for where this implementation
and the spec disagree, and why.

## Modules

| Module | Contents | Spec section |
|---|---|---|
| [`arith`](lib/arith.sv0) | abs/sign/min/max/clamp, rounding, integer power, checked/wrapping/saturating arithmetic, interpolation, FMA | §11 |
| [`modular`](lib/modular.sv0) | floor/Euclidean remainder, GCD/LCM, modular add/sub/mul/pow/inverse, congruence | §12 |
| [`trig`](lib/trig.sv0) | sqrt, trigonometric/hyperbolic functions, degree/radian conversion, hypot | §13–14 |
| [`polar`](lib/polar.sv0) | Cartesian/polar conversion, polar-form scale and rotate | §17 |
| [`complex`](lib/complex.sv0) | `Complex` arithmetic, modulus/argument/conjugate, polar interop, `exp`/`ln`/`pow` | §18 |
| `prelude` | shared `Option`/`Result`-shaped types used across the above | — |

111 public functions total — see [docs/api.md](docs/api.md) for the full
generated reference (signature, contract, and doc comment per function).

## Quick example

```sv0
use arith::abs_f64;
use arith::clamp_f64;
use trig::hypot_f64;
use complex::Complex;
use complex::mul_complex;
use complex::modulus;

fn main() -> i32 {
    let d: f64 = hypot_f64(3.0, 4.0);          // 5.0
    let c: f64 = clamp_f64(abs_f64(0.0 - 9.0), 0.0, 5.0); // 5.0

    let a: Complex = Complex { re: 1.0, im: 2.0 };
    let b: Complex = Complex { re: 3.0, im: 0.0 - 1.0 };
    let p: Complex = mul_complex(a, b);         // 5.0 + 5.0i
    let m: f64 = modulus(p);                    // ~7.071

    if d == 5.0 && c == 5.0 { return 0; }
    return 1;
}
```

Every non-exact function (anything with a measured ULP error — the
trigonometric, exponential, and complex-exponential families) documents
its accuracy budget in its own doc comment and in
[docs/accuracy.md](docs/accuracy.md).

## Build and test

**`scripts/ci`** is the fastest way to check everything at once. From a
`sv0-toolchain` checkout with this submodule populated
(`git submodule update --init sv0-mathlib`), run it from
`sv0-toolchain/sv0-mathlib/`:

```bash
bash scripts/ci
```

It finds the toolchain at its own parent directory automatically
(`SV0_TOOLCHAIN_ROOT` overrides). It runs `.sv0` whitespace formatting
and the block-comment nesting guard (via the same scripts
`sv0-toolchain`'s own `./scripts/sv0 test-guards` uses), a full
compile+run of this project, `test/unit` + `test/property`, the doc-comment
and fixture-coverage lints, the cross-backend (C vs. VM) parity checks,
and an accuracy-regression gate (every non-exact function's measured ULP
error, re-checked against `docs/accuracy.md`'s pinned budgets on every
run — see `scripts/run_ulp_audit.py`). GitHub Actions
(`.github/workflows/ci.yml`) runs it twice on every push/PR: once
against the `sv0-toolchain` revision pinned in
`.github/sv0-toolchain-pin.txt` (**required** — this is the reproducible
build every contributor should agree on), and once against upstream's
live default branch (**advisory** — surfaces a toolchain regression
against this library as soon as it lands, without blocking this
library's own merges on someone else's breaking change).

The individual steps, run by hand:

```bash
# C backend (native compiler)
build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib > /tmp/mathlib.c
cc -std=c99 -O0 -w -I sv0c/runtime /tmp/mathlib.c sv0c/runtime/sv0_runtime.c -o /tmp/mathlib_bin
/tmp/mathlib_bin; echo $?   # 0 = pass

# VM backend (native emitter — f64/i64 capable)
./scripts/sv0 vm-native-compile --project sv0-mathlib /tmp/mathlib.sv0b
./scripts/sv0 vm-run /tmp/mathlib.sv0b   # vm_exit:0 — matches the C backend

# Cross-backend parity (both of the above, exit codes compared):
./scripts/sv0 vm-behavioral-parity
```

## Repository layout

```text
sv0-mathlib/
├── README.md
├── CHANGELOG.md     # user-visible changes, accuracy-bound changes, contract changes
├── BUGS.md          # toolchain-level gaps found during development (upstream sv0c/sv0vm issues)
├── main.sv0         # smoke/demo entry point
├── .github/
│   ├── workflows/ci.yml
│   └── sv0-toolchain-pin.txt # the sv0-toolchain SHA CI's required leg builds against
├── scripts/
│   ├── ci                    # the CI gate: fmt + guard + compile/run + tests + lints + parity + ULP
│   ├── run_unit_tests.py     # runs test/unit + test/property, generates docs/requirement_test_matrix.md
│   ├── check_fixtures.py     # fixture-manifest completeness + boundary-coverage lint
│   ├── check_doc_comments.py # doc-comment coverage lint
│   ├── gen_api_docs.py       # generates docs/api.md
│   ├── run_fixture_parity.py # drives every fixture row through a live build, checks vs. expected
│   ├── run_ulp_audit.py      # accuracy-regression gate against docs/accuracy.md's pinned budgets
│   └── check_vm_emitter_determinism.py # diagnostic: is the native VM emitter's .sv0b output stable?
├── lib/               # arith, modular, trig, polar, complex, prelude
├── test/
│   ├── unit/           # one standalone fn main()->i32 binary per module
│   ├── property/       # seeded-PRNG algebraic-invariant checks
│   ├── fixtures/       # boundary/special-value CSV tables + manifest
│   └── parity/         # cross-backend parity (see parity/README.md)
└── docs/
    ├── api.md                      # generated: full function reference
    ├── accuracy.md                 # measured ULP error per non-exact function
    ├── deviations.md               # where this library departs from SPEC.md, and why
    ├── ulp_audit_harness.c         # the C harness used to produce accuracy.md's numbers
    └── requirement_test_matrix.md  # generated: requirement ID -> test mapping
```

## Tier 1 / Tier 2

No native transcendental math (`sqrt`, `sin`, `cos`, …) exists anywhere in
the sv0 toolchain — not as a keyword, stdlib function, C runtime symbol, or
VM opcode. Every function in this library is **Tier 1**: implemented in pure
sv0 using arithmetic operators only, portable to every backend without a
compiler change. A **Tier 2** (native-builtin-backed) tier is a possible
future direction, not a commitment — see SPEC.md §4.3 and §22 OQ-003.

## Known limitations

- The legacy SML `--target=vm` path lacks `f64` support — use
  `./scripts/sv0 vm-native-compile --project` instead.
- The VM-backend leg of `scripts/run_fixture_parity.py` is advisory, not
  gating: the SML/NJ-110.99.9-specific `Unsafe.cast` f64-codec bug it
  was tracking is fixed upstream in `sv0vm`, but the same failure still
  shows up intermittently even with the fix — a separate, still-
  unconfirmed source of nondeterminism (see `BUGS.md`).
- A handful of `sv0` toolchain gaps have documented, verified workarounds
  in this library's own source (see the relevant doc comment or module
  header for the specific one in play).
- `ln_complex`/`pow_complex` measure outside their own informational ULP
  budget — both are documented, understood non-issues (a real but tiny
  residual, and a system-libm reference-quality artifact, respectively;
  see `docs/accuracy.md`), not open bugs, and `scripts/run_ulp_audit.py`
  still gates on neither growing worse.

See [BUGS.md](BUGS.md) for the full, itemized toolchain-gap record kept
during this library's development — useful if you're working on `sv0c`/
`sv0vm` itself, not required reading to use this library.

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT license](LICENSE-MIT) at your option — the same terms as the rest of
the `sv0-toolchain` project.

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in this library by you, as defined in the
Apache-2.0 license, shall be dual licensed as above, without any
additional terms or conditions.
