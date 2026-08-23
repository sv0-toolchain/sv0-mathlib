# sv0-mathlib

A numeric library for the [sv0](https://github.com/sv4u/sv0-toolchain)
programming language: arithmetic, modular arithmetic, trigonometry, polar
coordinates, and complex numbers, built contract-first per
[SPEC.md](https://github.com/sv4u/project-specs/blob/main/sv0-mathlib/SPEC.md).

## Status

**F0 in progress.** `math::arith`'s i32 and f64 forms — `abs_i32`/`abs_f64`,
`sign_i32`/`sign_f64`, `min_i32`/`min_f64`, `max_i32`/`max_f64`,
`clamp_i32`/`clamp_f64` (ARITH-001..004) — are implemented, contract-checked,
and verified on the **C backend** (emitted C inspected for correct
`int`/`double` typing throughout — params, locals, contract-result slots,
and call-result temps, not just exit codes; fixtures include a fractional
value and a real NaN). The i32 forms are additionally verified on the **VM
backend** (matching exit codes with the C build). See [BUGS.md](BUGS.md) for
six toolchain gaps found while starting this work — bug #5 (`f64` silently
compiling as `int`, the dominant blocker) is now **fixed** upstream; bug #2
(the VM backend can't type-check a non-`i32`/`bool` contract) is not, so the
f64 forms don't yet compile under `vm-project-compile`.

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

# VM backend — i32 forms only today (bug #2: f64 contracts don't type-check here yet)
./scripts/sv0 vm-project-compile ../../sv0-mathlib
./scripts/sv0 vm-run sv0c/build/vm/main.sv0b   # expect vm_exit:0
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
├── main.sv0         # smoke/demo entry point (also ARITH-001's test today)
├── lib/
│   └── arith.sv0     # module arith — F0 arithmetic core (Section 11)
├── blocked/          # code written+verified but not wired in — see BUGS.md
├── test/{unit,fixtures,property,parity}/
└── docs/
```
