# sv0-mathlib

A numeric library for the [sv0](https://github.com/sv4u/sv0-toolchain)
programming language: arithmetic, modular arithmetic, trigonometry, polar
coordinates, and complex numbers, built contract-first per
[SPEC.md](https://github.com/sv4u/project-specs/blob/main/sv0-mathlib/SPEC.md).

## Status

**F0 in progress.** `math::arith`'s i32 forms — `abs_i32`, `sign_i32`,
`min_i32`, `max_i32`, `clamp_i32` (ARITH-001..004) — are implemented,
contract-checked, and verified end to end on **both** the C and VM backends
(matching exit codes, emitted C inspected for correct `int` typing, a
`requires`-violation panic confirmed). See [BUGS.md](BUGS.md) for six
toolchain gaps found while starting this work. One is the dominant blocker:
**`f64` silently compiles as `int`** (bug #5) — no diagnostic, no crash,
just a wrong answer that happens to look right on small fixtures. That
blocks essentially everything past this library's i32-only slice: R0.1's
f64 pieces, and all of R0.2 (trig) and R0.3 (polar/complex). Fix that one
first.

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

## Build and test

From an `sv0-toolchain` checkout, with `sv0-mathlib` checked out as a
sibling directory:

```bash
# C backend (native compiler)
build/sv0-megatu-compiler-native --project /path/to/sv0-mathlib > /tmp/mathlib.c
cc -std=c99 -O0 -w -I sv0c/runtime /tmp/mathlib.c sv0c/runtime/sv0_runtime.c -o /tmp/mathlib_bin
/tmp/mathlib_bin; echo $?   # 0 = pass

# VM backend — both backends agree on this library's current (i32-only) surface
./scripts/sv0 vm-project-compile ../../sv0-mathlib
./scripts/sv0 vm-run sv0c/build/vm/main.sv0b   # expect vm_exit:0
```

Don't trust an exit code alone once `f64` is involved (see BUGS.md #5) —
grep the emitted C for `double` where you expect it.

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
├── main.sv0         # smoke/demo entry point (also ARITH-001's test today)
├── lib/
│   └── arith.sv0     # module arith — F0 arithmetic core (Section 11)
├── blocked/          # code written+verified but not wired in — see BUGS.md
├── test/{unit,fixtures,property,parity}/
└── docs/
```
