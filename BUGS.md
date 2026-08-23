# Toolchain bugs found while starting sv0-mathlib

Filed here first (this repo has no upstream tracker yet); each should become
a real `sv0-toolchain`/`sv0c` issue. Audited against sv0-toolchain HEAD
`840fe73` / sv0c HEAD `0705d68` (2026-08-23). Bug #5 is the one to fix
first — it blocks the majority of this spec's surface (everything f64).

## 1. Integer literals wider than i32 are silently truncated to 32 bits

**Severity: critical.** Any integer literal that doesn't fit in `i32`
(`> 2147483647` or `< -2147483648`) is truncated mod 2^32 at parse time,
**regardless of the declared type it's assigned into** — `let y: i64 = 5000000000;`
compiles to `int y; y = 705032704;` (`5000000000 mod 2^32`), and `int`, not
`int64_t`. Root cause: `sv0c/lib/ast.sv0:9` — `IntLit(i32)` — the AST's
integer-literal variant can only hold an `i32`, so every literal is forced
through that width during parsing, before the surrounding type context (a
`let`/param/`requires` annotation) is ever consulted.

Repro:
```
fn f() -> i64 {
    let y: i64 = 9223372036854775807;  // i64::MAX
    return y;
}
```
`./scripts/sv0 compile <file>` emits `int y; y = -1;` — both the value and
the C type are wrong.

**Impact on this library:** blocks `i64`/`u64`::MIN/MAX-boundary contracts
(ARITH-001's `abs_i64`), `u64` moduli near `u64::MAX` (MOD-003/004), and any
"cryptographic-scale" fixture MOD-005 asks for. **Impact on M5:** identical
mechanism would corrupt any `u64`/`u128` crypto constant larger than
`i32::MAX` — SHA round constants are u32-sized and safe, but Ed25519's field
prime (`2^255 - 19`) and any 64-bit portion of ChaCha20/Poly1305 state built
from a literal (not computed) would silently truncate the same way.

## 2. The VM-target toolchain path can't type-check non-i32/bool contracts

**Severity: high, VM backend only.** `./scripts/sv0 vm-project-compile` /
`vm-compile` invoke the SML-legacy bootstrap compiler (`sml-legacy/`), whose
contract-expression checker (`sml-legacy/type_checker/checker.sml:648-670`)
hardcodes `Arith => TyInt 32` and `Cmp => TyInt 32 or TyBool` for every binop
inside a `requires`/`ensures`/`loop_invariant` — there's no case for `i64`,
any unsigned width, or `f64`. A contract clause on any of those types fails
with `E0400: type mismatch`, even a trivial one (`requires(x > 0)` on an
`i64` param). Casting the literal (`requires(x > (0 as i64))`) does not help
— the class dispatch itself is the i32-only branch, not literal inference.

The native/self-hosted checker (`sv0c/lib/checker.sv0`, used by
`./scripts/sv0 compile`/`emit-c`/`verify`) has no such restriction —
confirmed `requires(x > 0)` on an `i64` param compiles clean there.

**Impact on this library:** `sv0 vm-run`/`vm-project-compile` — the exact
commands SPEC.md Appendix E.4's tooling loop and COMPAT-001/002 (C/VM
cross-backend parity) prescribe — cannot type-check contracts on anything
past `math::arith`'s `i32` forms. **Impact on M5:** Epic F's
`#[constant_time]` contracts are defined over `u8`/`u32`/`u64` crypto
buffers; if they're meant to run through the VM-target path at all, they'd
hit this identically. Worth confirming with the M5 planners whether Epic F's
constant-time verification is scoped to the C/LLVM paths only — if so this
may be a non-issue for M5, but it should be an explicit decision, not an
assumption.

## 3. `enum Foo<T> { ... }` fails under `--project` (multi-file build) mode

**Severity: critical, blocks Option/Result entirely in real projects.**
`enum Option<T> { Some(T), None }` compiles fine as a single file
(`./scripts/sv0 compile`), but the identical declaration fails under
`--project` with `error[E0301]: unknown type` pointing at the enum's own `T`
— reproduced with the **native** mega-TU compiler
(`build/sv0-megatu-compiler-native --project <dir>`), and reproduced with a
**single-file** project directory (not a cross-module issue — a one-file
`--project` build with nothing but the enum declaration fails the same way).
Independent of relative vs. absolute path.

Repro:
```
mkdir -p /tmp/repro && cat > /tmp/repro/main.sv0 <<'EOF'
enum Option<T> { Some(T), None }
fn main() -> i32 { let x: Option = Option::Some(5); return 0; }
EOF
build/sv0-megatu-compiler-native --project /tmp/repro
# error[E0301]: unknown type  --> 1:23  |  enum Option<T> { Some(T), None }
```

**Impact on this library:** every `_checked` companion this spec mandates
(CONV-005(a)) returns `Option<T>`; none of them can be wired into the real
multi-file project until this is fixed. `lib/prelude.sv0` and
`abs_checked_i32` are held in `blocked/` (verified correct via a single-file
harness — see git history) until this lands.

## 5. `f64` (and `f32`, and `u32`) silently compile as `int` in the native backend

**Severity: critical — this is the dominant blocker for this library.** The
native compiler's C-backend type-name mapping,
`sv0c/lib/lowering.sv0:4871` (`ast_ty_to_c_string`), enumerates
`i32`/`bool`/`i8`/`u8`/`i16`/`u16`/`i64`/`u64`/`isize`/`usize`/`string`/
`str`/`String`/`Vec`/`Box` and **has no case for `f32`, `f64`, or `u32`** —
it falls through to `return "int";` for any of them. There is no
diagnostic; the function silently emits `int`. Confirmed for `f64`:

```
fn f(x: f64) -> f64 { return 0.0 - x; }
```
compiles to
```c
static int f(int x) { int _sv0t0 = (0 - x); return _sv0t0; }
```
— parameter, return type, and the `0.0` literal are all silently `int`.
`fn f() -> f64 { return 1.0; }` (a bare float-literal return, no arithmetic)
instead hard-fails with `error[E0400]: type mismatch` — so the bug has two
faces depending on the function body's shape, neither of which is a working
`double`. Reproduced both via `build/sv0-megatu-native` (single-file) and
`build/sv0-megatu-compiler-native --project` (multi-file) — this is not a
`--project`-specific bug. There is **zero `f64`/`f32` usage anywhere in
`sv0c`'s own test/examples corpus** (`grep -rl ": f64"` returns nothing),
consistent with this being simply untested, not a regression.

**This retracts an earlier claim in this repo's git history**: the first
commit's `abs_f64` was reported as "C-backend verified" — it was not. Its
exit-code test happened to pass only because `5.0`/`-5.0`/`0.0`, silently
truncated to `int`, produce the same comparison results as their real
`double` values for that specific fixture. The lesson, now applied here and
worth generalizing to any future toolchain claim: **inspect the emitted C
for the expected C type, don't trust an exit code alone** — a miscompiled
type can still happen to produce a correct-looking result on a narrow
fixture. `abs_f64` and every other f64 function are held in
`blocked/arith_f64.sv0.blocked` until this is fixed.

**Impact on this library:** blocks essentially all of R0.1's f64 pieces
(`fma_f64`, `lerp_f64`), and *all* of R0.2 (`math::trig`) and R0.3
(`math::polar`/`math::complex`), which are f64 by definition (CONV-002).
**Impact on M5:** none directly — M5's open decision #4 already recommends
excluding f32/f64 from LLVM emission this milestone, so this doesn't block
M5's crypto/LLVM work. But `u32` being silently `int` is worth M5 double-
checking explicitly for Epic D/std-foundation's width-normalization work
(`i32`/`bool` were flagged as mapping to plain `int`; `u32` should be
flagged the same way — it's in the same missing-case bucket as `f64`).

## 6. The `==>` implication operator in SPEC.md's contracts doesn't parse

**Severity: low, but silent.** SPEC.md's own worked examples (e.g.
ARITH-009's `ensures(t == 0.0 ==> result == a)`) use `==>` for logical
implication. This is not a real sv0 operator — no occurrence anywhere in
`sv0doc` or the test corpus — and compiling a contract that uses it fails
**silently**: `./scripts/sv0 compile` exits nonzero with **no error message
at all** (not even a generic parse-failure line), because it invokes
`build/sv0-megatu-native` in a mode where a parse failure just returns a
bare nonzero exit code. Rewrite `P ==> Q` as `!(P) || (Q)` — confirmed
working. Filed here because it's a spec/toolchain interaction that will
silently produce empty output for anyone following SPEC.md's examples
literally, and separately because a compiler that exits nonzero with zero
diagnostic text on *any* parse failure is itself worth a bug report.

## 4. `./scripts/sv0 compile` (single-file, default SML-heap path) is
   inconsistent for files outside `sv0c/`

**Severity: medium, operational.** The same file with the same content
compiles under `./scripts/sv0 compile-run <relative-path-under-sv0c>` but
fails with the *same* spurious `E0301: unknown type` as bug #3 when invoked
as `./scripts/sv0 compile /absolute/path/outside/sv0c/file.sv0`. Not
explained by the known `/tmp/.sv0_drv_path` staleness gotcha (reset and
retested, still fails). Root cause not isolated — noting as an operational
constraint: **always stage single-file compiler invocations at a path
relative to `sv0c/`** until this is understood; don't trust an absolute-path
invocation even for code that's known-good.

## Working today — genuinely verified (emitted C inspected, not just exit code)

- Single-file compile/verify (`./scripts/sv0 compile`, `verify`, `emit-c`)
  for `i32`/`bool` contracts, staged at a path relative to `sv0c/`.
- Multi-file `--project` builds via the **native** mega-TU compiler
  (`build/sv0-megatu-compiler-native --project <dir>`) for `i32`-only code
  with no generic (`<T>`) declarations — confirmed against this repo's
  current `main.sv0` + `lib/arith.sv0` (`abs_i32`, `sign_i32`, `min_i32`,
  `max_i32`, `clamp_i32`): emitted C uses `int` throughout as expected,
  compiled, linked (`cc`), and run to exit `0`; the `requires` violation at
  `abs_i32(i32::MIN)` was separately confirmed to panic
  (`sv0 contract violation: requires failed in abs_i32`).
- **VM backend now confirmed too**, for this same `i32`-only subset:
  `./scripts/sv0 vm-project-compile ../../sv0-mathlib` +
  `./scripts/sv0 vm-run` both produce `vm_exit:0`, matching the C backend —
  real COMPAT-001 parity, not just a hoped-for one. This is the first
  slice where **both backends agree** on this library's real surface.

## Not yet working

- **Anything f64** — blocked by bug #5, not just the VM path (bug #2 is now
  moot for f64 specifically until #5 is fixed first; even the C backend
  miscompiles it).
- VM backend for anything with a non-`i32`/`bool` contract (bug #2) — not
  re-tested since bug #5 means there's no correctly-compiling f64 code yet
  to test it against.
