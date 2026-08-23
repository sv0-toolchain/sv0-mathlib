# Toolchain bugs found while starting sv0-mathlib

Filed here first (this repo has no upstream tracker yet); each should become
a real `sv0-toolchain`/`sv0c` issue. Audited against sv0-toolchain HEAD
`840fe73` / sv0c HEAD `0705d68` (2026-08-23). **Bugs #5 and #3 are fixed**
(f64 miscompiling as `int`; generic enums failing to resolve). Bug #7 (a
narrower f64 residual) was found while verifying #3 and is not yet fixed.

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

## 3. `enum Foo<T> { ... }` fails everywhere — mischaracterized, then FIXED

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (uncommitted in that
repo's working tree). **Correcting this entry's original claim**: this was
never a `--project`-specific bug. Re-testing found `enum Option<T>` fails in
plain **single-file** mode too — including `sv0c`'s own canonical
`test/integration/option_result/option_result.sv0` fixture — and every
"working" enum fixture in the corpus (`question_op`, `uc_option_sum`, the
whole `pc3b6` suite) turned out to use a **concrete, non-generic** enum
(`enum Opt { Some(i32), None }`); none of them actually exercised `<T>`. The
original repro happened to combine a generic enum with `--project` and drew
the wrong conclusion from it.

**Root cause**: `sv0c/lib/parser.sv0`'s `parse_generic_params` (called from
`parse_enum_item` and elsewhere) parses `<T>` correctly enough to skip past
the tokens, but the parsed names were never retained anywhere — the parser
did the syntactic work and then discarded it. Downstream,
`sv0c/lib/resolver.sv0`'s `resolve_ty` — the pass that checks whether a
referenced type name actually exists — had no third case for "a type
parameter bound by the enclosing item," only module-registered types and
prelude builtins, because that information was never available. This isn't
a subtle regression; it's the same gap the M5 audit already flagged as
"generics still evolving" (`10_generics_placeholder.sv0`), now traced to
its exact mechanism.

**Fix**: `parse_enum_item` now retains each enum's `<T, ...>` name tokens
into a new file-scoped `tparam_names` set (threaded through
`parse_item`/`parse_program`); `resolve_ty` checks membership in that set as
a third fallback (after module types, after prelude builtins) before
rejecting a name as unknown. Deliberately **file-scoped, not
per-declaring-item-scoped** — sv0 has no nested/shadowing generic scopes
today (a type param is only ever referenced inside the item that binds it),
so this is a documented simplification: over-permissive in a hypothetical
case where two unrelated items both declare an unrelated `T`, never
under-permissive, and no such case exists anywhere in the corpus today.
Scoped to **enum** declarations only — struct and function generics still
hit the same underlying gap and are not fixed by this change (fn generics
in particular need call-site type inference/monomorphization, a materially
bigger problem than "don't reject the name").

**Verified**: `sv0c/test/integration/option_result/option_result.sv0`
compiles and runs correctly (`./scripts/sv0 compile-run`, exit 0) for the
first time; the `pc3b6-native-project-acceptance.sh` 18-fixture corpus
stays green after rebuild. `sv0-mathlib`'s `lib/prelude.sv0` (`Option`,
`Result`) and `abs_checked_i32` are restored — emitted C inspected
(`Option`/`Result` compile to `typedef struct { int tag; int p0; }`-shaped
types, `abs_checked_i32` correctly builds and matches `Some`/`None`), full
suite runs to exit 0.

## 7. An explicit `let x: f64 = <arithmetic-expr>;` local still defaults to `int`

**Severity: medium — narrower than bug #5, but the same failure shape
(silent truncation/UB, no diagnostic), found while verifying bug #3's fix.**
`sv0c/lib/lowering.sv0`'s `expr_init_cty` (which decides a `let` local's C
declaration type) infers **purely from the init expression's shape** —
struct literal, 2-segment enum-ctor path, or function call — and has no
parameter for the `let` statement's own explicit type annotation at all.
So `let nan: f64 = 0.0 / 0.0;` (RHS is a binop, none of the three shapes
`expr_init_cty` recognizes) silently declares `int nan;` in the emitted C —
worse than bug #5's Assign-temp case, because assigning a computed
`double` (correctly computed — the division itself is fine) into that `int`
variable is **undefined behavior** in C (double-to-int conversion of a NaN
is UB), not just a silent wrong-but-defined truncation. Confirmed via
`sv0-mathlib`'s own `main.sv0`, which originally used exactly this pattern
to construct a NaN test value.

**Not fixed** — found and worked around (`main.sv0` now passes the NaN
expression inline as a call argument, which uses a different, unaffected
lowering path, instead of binding it through a `let`) rather than fixed
upstream, given the size of the remaining work already landed this session.
A real fix needs `expr_init_cty` (or its caller) to receive and prefer the
`let` statement's parsed annotation type when one is present, falling back
to shape-inference only when it's absent (`let x = ...;` with no
annotation). Any `let x: f64 = ...;` / `let x: u32 = ...;` / etc. whose RHS
isn't a struct literal, enum constructor, or function call should be
treated as suspect until this lands — grep for that pattern and check the
emitted C type directly, the same lesson as bug #5.

## 5. `f64` (and `f32`, and `u32`) silently compile as `int` in the native backend

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (uncommitted in that
repo's working tree — commit there separately). Six sub-bugs found and
fixed, all confirmed via `build/sv0-megatu-native`/
`build/sv0-megatu-compiler-native` rebuild:

1. `ast_ty_to_c_string` (`sv0c/lib/lowering.sv0`) — added `f32`/`f64`/`u32`.
2. `lower_lit_to_ir_value` (`sv0c/lib/lowering.sv0`) — float literals fell
   through to `Value::VUnit` (never implemented, not merely buggy); added a
   `VFloat(i32)` variant (token-handle, mirroring `VString`'s pattern) to
   `lowering.sv0` and `codegen.sv0`'s parallel `Value` enums, wired through
   `megatu_emit_value` in `sv0c/lib/megaTU-main.sv0` to print the literal's
   source text verbatim (already valid C double syntax).
3. `infer_lit` (`sv0c/lib/checker.sv0`) — `lit_tag == 1` (the real parser's
   FloatLit tag) was mapped to `TY_BOOL()`, a stale leftover from before
   bool literals were correctly moved to tag 5. Fixed to `TY_FLOAT()`.
4. `synth_expr`'s `ExprBinop`/`ExprUnop` cases (`sv0c/lib/checker.sv0`) —
   computed operand types then discarded them, hardcoding `TY_INT()` for
   every arithmetic/negation op via `binop_result_ty_tag`/
   `unop_result_ty_tag`. Fixed to propagate the actual operand type for
   Arith/Neg/BitNot (Cmp/Logic/Not still resolve to `TY_BOOL`).
5. **The residual found while verifying #1-4**: every codegen-synthesized
   temp was declared `int` unconditionally — three separate emission sites
   in `sv0c/lib/megaTU-main.sv0`, none of which had any type information to
   work with (`codegen_Instr`/`codegen_Expr` carry none):
   - `codegen_Instr::Assign` — fixed by adding a minimal (handle → is_float)
     type environment (`megatu_tyenv_push`/`_lookup_is_float`,
     `megatu_value_is_float`, `megatu_expr_is_float`), seeded per-function
     from parameter types (`megatu_seed_param_tyenv`) and grown as
     `DeclNamed`/`Assign`/`Call` instructions are walked. Only arithmetic
     ops (`+ - * / %`) and unary `Neg` propagate float-ness; comparison/
     logical/bitwise ops always resolve `int` regardless of operand type.
   - `codegen_Instr::DeclVar` — used for several purposes, but the one that
     mattered here is the `ensures`-clause `result` slot; detected by name
     (`"result"`) and typed from the enclosing function's own return type
     (`ret_ty`, already threaded into this function) instead of a bare
     `int` default. Other `DeclVar` uses (arithmetic-widening/tuple-helper
     slots) are left as `int`, which is correct for them.
   - `codegen_Instr::Call`'s untyped case (`rt_h == 0`, i.e. every ordinary
     user-function call without an explicit typed `box_deref`) — added
     `megatu_fn_ret_cty` (resolves the callee by source-text name match,
     since a call-site token and the declaration-site token are different
     positions — `megatu_find_item_by_label`'s existing raw-token-index
     match doesn't work across that boundary) to look up the real return
     type instead of defaulting to `int`. This was the fix that mattered
     most in practice: `clamp_f64` calling `min_f64(max_f64(x, lo), hi)`
     would otherwise still truncate at every call boundary.

**Verified, not just exit-code-checked**: inspected the emitted C directly
for every case — `abs_f64`, `sign_f64` (including the NaN branch and the
`result` slot), `min_f64`/`max_f64` (including the `!= self` NaN-detection
comparisons, confirmed typed `int` not `double`), and `clamp_f64` (nested
calls through `min_f64(max_f64(...))`) all produce fully correct `double`
arithmetic end to end, then actually ran the corresponding fixtures (0 =
pass) including a fractional value (`0.5`) and a real NaN (`0.0 / 0.0`) —
values that would have exposed the earlier `int`-truncation immediately.
**No regression**: `sv0-mathlib`'s full current suite (i32 forms + restored
f64 forms) still compiles/runs to exit 0, and the toolchain's own
`scripts/pc3b6-native-project-acceptance.sh` corpus (18 fixtures, including
`Option`- and struct-using ones, which don't go through this Assign/DeclVar
path) is still all green after each rebuild.

**Still separately blocked**: the VM backend (bug #2) — `ensures(result >=
0.0)` on `abs_f64` still fails to type-check there; that's a different
subsystem (SML-legacy's contract checker) untouched by this fix.
`lib/arith.sv0`'s f64 functions are restored and compile/run correctly on
the C backend only; see that file's header comment.

**Original bug description, for the record:** The
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
  (`build/sv0-megatu-compiler-native --project <dir>`) — confirmed against
  this repo's full current surface: `abs_i32`, `sign_i32`, `min_i32`,
  `max_i32`, `clamp_i32` (emitted C uses `int` throughout as expected); the
  `requires` violation at `abs_i32(i32::MIN)` separately confirmed to panic
  (`sv0 contract violation: requires failed in abs_i32`).
- **VM backend confirmed too, for a pure-`i32`, no-`Option` subset** (true
  as of the commit that first added this line; **no longer true of the
  current `main.sv0`**, which now uses `Option` — see "Not yet working"
  below): `./scripts/sv0 vm-project-compile` + `./scripts/sv0 vm-run` both
  produced `vm_exit:0`, matching the C backend.
- **All of `math::arith`'s f64 forms (bug #5, now fixed)** —
  `abs_f64`/`sign_f64`/`min_f64`/`max_f64`/`clamp_f64`, on the **C backend**:
  emitted C uses `double` throughout (params, locals, the `ensures`
  `result` slot, comparison temps correctly staying `int`, and — the fix
  that mattered most — call-result temps for `clamp_f64`'s nested
  `min_f64(max_f64(...))`); compiled, linked, and run to exit `0` on a
  fixture set that includes a fractional value and a real NaN
  (`0.0 / 0.0`), not just integer-valued floats.
- **`Option`/`Result` and `abs_checked_i32` (bug #3, now fixed)** — generic
  enums resolve correctly under `--project`; `lib/prelude.sv0` restored,
  `abs_checked_i32` compiles to a real `Option`-returning function
  (`typedef struct { int tag; int p0; } Option;`), and the full
  `Some`/`None` match logic runs correctly (exit 0, both branches
  exercised).

## Not yet working

- **VM backend for the current `main.sv0` at all** — two independent,
  layered reasons, both bug #2's subsystem (SML-legacy, untouched by any
  fix this session): (a) `abs_f64`'s `ensures(result >= 0.0)` fails to
  type-check (the original bug #2 finding), and (b) newly found — once
  `main.sv0` and `lib/arith.sv0` **both** `use prelude::Option;`,
  `vm-project-compile` fails with `error[E0309]: E0304: duplicate type
  Option`. SML-legacy appears to inline/duplicate an imported type per
  importing file rather than sharing one declaration; the native compiler
  (used for the C backend) has no such issue. Not investigated further —
  bug #2's existing "SML-legacy has real gaps, not planned to be
  extended" framing already covers this; noting it here rather than as a
  new bug number.
- `abs_i64`/`sign_i64` (bug #1, not fixed) — large i64/u64 literals still
  truncate.
- Struct and function generics (bug #3's fix is enum-only) — untested,
  presumed still broken.
- `let x: f64 = <arithmetic-expr>;` (bug #7, not fixed) — silently declares
  `int`; avoid the pattern (pass the expression inline instead) until fixed.
