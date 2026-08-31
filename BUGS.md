# Toolchain bugs found while starting sv0-mathlib

Filed here first (this repo has no upstream tracker yet); each should become
a real `sv0-toolchain`/`sv0c` issue. Audited against sv0-toolchain HEAD
`43ee2b0` / sv0c HEAD `d0fa706` (2026-08-28), updated through the R0.3 +
accuracy-audit + TEST-006 CI-gate + TEST-001/TEST-004 test-suite work —
bugs #16/#17/#18/#19 were found and worked around against a LATER
upstream revision (`sv0-toolchain` `c318513` / `sv0c` `53de895`) than
the rest of this file's own pin, since this library's CI tracks the
moving upstream default branch, not a fixed SHA.
**Bugs #1, #2 (checker-level half), #3, #5, #6 (diagnostics half), #7, #8,
#10, #11, #13, and #14 are fixed.** Bug #9 (generic enums resolve but
don't monomorphize) and #12 (`match` used as a value mistypes its own
result temp) remain open, genuine gaps — each has a documented, verified
workaround this library uses instead. Bug #15 (an inline struct literal
passed directly as a function-call argument sometimes resolves its field
names against the wrong struct declaration), found finishing CPLX-007, is
open — also with a documented, verified workaround. Bug #16 (a bare
`return field_a + field_b;` combining two fields of the SAME struct
instance mistypes its own temp — a regression past bug #13's own fix,
found setting up `scripts/ci`/TEST-006) and bug #19 (the SAME family, but
for a struct-literal field initializer OR a `requires`/`ensures` clause
that combines a struct-field access in a binop — found via `test/
property/property_test.sv0`, TEST-004) are open — workarounds applied
throughout `lib/complex.sv0`/`lib/polar.sv0`/`lib/trig.sv0`. Bug #17
(`--project` file discovery silently fails — exit 2, zero diagnostics —
when a top-level file/directory sorts alphabetically before `lib`) and
bug #18 (`let x: StructType = <bare variable already of that type>;`
mistypes the new local as `int`), both found setting up `test/unit/`
(TEST-001), are also open — all four with documented, verified
workarounds. Bug #6's fix also surfaced and fixed a real,
sv0-mathlib-unrelated parser/lowering defect in sv0c's own test corpus
(bare struct-field assignment statements silently compiling to nothing)
— noted under bug #6 rather than given its own number, since it was
never a blocker for this library.

## 1. Integer literals wider than i32 are silently truncated to 32 bits

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (uncommitted in that
repo's working tree). Any integer literal that didn't fit in `i32`
(`> 2147483647`) was truncated mod 2^32 at parse time, **regardless of the
declared type it was assigned into** — `let y: i64 = 5000000000;` compiled
to `int y; y = 705032704;` (`5000000000 mod 2^32`), and `int`, not
`int64_t`. Root cause: `sv0c/lib/lowering.sv0`'s
`parse_decimal_i32_from_tok` (the function that turns a literal's source
text into its `Value::VInt` payload) accumulates digits into a plain `i32`
with no overflow guard — this is downstream of, but the same shape as,
`sv0c/lib/ast.sv0:9`'s `Literal::IntLit(i32)` (that AST type itself turned
out to be a vestigial/unused copy, not on the live emission path — see bug
#5's writeup for how that was traced).

**Fix**: rather than widen `VInt`'s payload (i32, used at ~30 call sites
across the compiler's own internals for small values like AST tags — too
large a blast radius to touch safely), added a new `Value::VIntWide(i32)`
variant carrying the literal's *source token handle*, the same "print the
original text verbatim" strategy bug #5 used for `VFloat` — a bare decimal
integer literal is already valid C, and the C compiler infers the correct
width itself, so there's no need to parse it into any bounded sv0 integer
at compile time at all. `lower_lit_to_ir_value` routes to `VInt` (fits i32,
unchanged fast path) or `VIntWide` (doesn't fit, checked via a new
`decimal_lit_fits_i32` — pure string comparison against `"2147483647"`, no
overflow-prone arithmetic needed to detect the overflow).

**A second sub-bug found while verifying the first**: fixing the literal's
*value* wasn't enough — the same three "hardcode int" emission sites bug
#5 fixed for `double` (`Assign`, the `result` `DeclVar` slot, untyped
`Call` results) *also* silently discarded int64-ness for ordinary i64
arithmetic (not just `VIntWide` literals) — `fn abs_i64(x: i64) -> i64 { ...
0 - x ... }` still emitted `int _sv0t = (0 - x);`, truncating right back
down. Root cause: `x` is a real source token, and — unlike a compiler-
synthesized `_sv0tN` temp, whose handle is a global counter and therefore
identical at its declaration and every later use — a parameter's or local's
*declaration* token and each of its *use-site* tokens are different
positions in the source text. Bug #5's tyenv tracked category by raw handle
equality, which works for temps but silently never matches for a real
variable referenced more than once. Fixed by widening the tyenv from a
boolean (float/not-float) to a 3-way category (int/double/int64_t) and
falling back to a **source-text comparison** when handle equality misses,
mirroring how `megatu_fn_ret_cty` (bug #5) already had to resolve a call
target by text for the identical reason.

Repro (now fixed):
```
fn abs_i64(x: i64) -> i64
    requires(x != (0 - 9223372036854775807 - 1))
    ensures(result >= 0)
{
    if x < 0 { return 0 - x; }
    return x;
}
```
now emits fully correct `int64_t` throughout (params, temps, the `result`
slot, the boundary-literal `requires` expression), verified by running it
against `abs_i64(9223372036854775807)` and `abs_i64(-9223372036854775807)`
(exit 0), not just inspecting the C.

**Residual, not fixed**: `u64` literals whose magnitude exceeds `i64::MAX`
(~9.2e18, versus `u64::MAX`'s ~1.8e19) are not specifically handled —
`VIntWide` doesn't parse or classify the literal at all (by design), so
the *value* still prints correctly for the full `u64` range (C infers the
type from the literal text itself), but the temp-typing category-tracking
system only has an `int64_t` bucket, not a separate `uint64_t` one — a
`u64` value near the top of its range flowing through a bare `Assign` temp
would still get declared `int64_t`, which cannot represent it. Narrower
than the original bug; not yet fixed. See also bug #8 (enum payload slots)
for a related, separately-scoped residual found while restoring
`abs_checked_i64`.

**Impact on this library:** unblocks `i64` boundary contracts (ARITH-001's
`abs_i64`, restored — see `lib/arith.sv0`). `abs_checked_i64` remains
blocked by bug #8, a different root cause. **Impact on M5:** the original
concern (Ed25519's field prime, ChaCha20/Poly1305 constants) is
substantially de-risked for the signed/i64-range part of that surface;
the `u64`-top-half residual above is worth flagging to M5 planners
specifically, since Ed25519's field prime (`2^255 - 19`) is far outside
even `u64` range and would need real bignum literal support regardless —
this fix doesn't reach that far, and isn't intended to.

## 2. The VM-target toolchain path can't type-check / lower / run f64

**STATUS (2026-08-29): FIXED end to end for the *native* VM path.**
`sv0-toolchain`'s `sv0c-vm-float-parity` work (task
`task/sv0c-vm-float-parity.Rmd`, slices VMF-###) added f64 + i64/u64
to the native mega-TU VM bytecode emitter (`build/sv0-megatu-vm-native`),
the `.sv0b` codec, and the `sv0vm` interpreter: typed `ADD_F64`/`ADD_I64`
opcode selection, a pure-integer correctly-rounded decimal→IEEE-754
converter (no float in the toolchain itself), `CF64`/`CI64` cells with
mixed-width coercion, and contract (`requires`/`ensures`) support. It
also fixed two pre-existing native-VM-emitter bugs surfaced along the
way (a contract-message pool panic; a struct-typed `result` contract
slot).

**This entire library now compiles AND runs on the VM backend, matching
the C backend.** `SV0_DRV_REQUEST="--project /path/to/sv0-mathlib"
build/sv0-megatu-vm-native` emits a runnable `.sv0b`; `sv0vm` executes
`main.sv0`'s full self-test suite to `vm_exit:0`, identical to the C
backend's exit 0. `./scripts/ci` (no `--skip-parity`) runs the
toolchain's `scripts/vm_behavioral_parity.py`, which diffs exit codes
across both backends for every fixture including `--project
../sv0-mathlib`. See `test/parity/README.md`.

**Invocation** (the SML `--target=vm` path below is unchanged and still
lacks f64 — use the native path):
```bash
# from the sv0-toolchain checkout
./scripts/sv0 vm-native-compile --project sv0-mathlib /tmp/mathlib.sv0b
./scripts/sv0 vm-run /tmp/mathlib.sv0b     # vm_exit:0
```

**Per-fixture value check — added (2026-08-30).**
`scripts/run_fixture_parity.py` generates a `fn main() -> i32` with one
check per (row, function) from `test/fixtures/{rounding,trig}.csv`,
compiles + runs it on both backends (C: native `--project` → `cc`; VM:
native VM emitter → `.sv0b` → `sv0vm`), and checks each result against
the row's own EXPECTED column. Wired into `scripts/ci`
(`--skip-fixture-parity`). `PANIC` rows are skipped (a `requires`
violation can't run inside one non-crashing binary) and zero results are
compared by value only (SPEC pins no sign-of-zero for
`ceil_f64`/`trunc_f64` of small negatives). The broad full-domain ULP
sweep in `docs/ulp_audit_harness.c` stays C-backend-only by design — it
needs `<math.h>` as its reference oracle.

**Open — the VM leg of that check is advisory, not gating.** Every row
passes on the C backend, and on the VM backend under SML/NJ **2026.1**
(the version on the dev machine it was written on). Under SML/NJ
**110.99.9** (what the GitHub Actions runner installs), running the
generated program on `sv0vm` aborts with, verbatim from CI:

```
run_fixture_parity: VM backend  — WARN (advisory): a requires/ensures aborted the run — ensures failed: frac_floor_of_nonneg
```

`frac_floor_of_nonneg` (`lib/arith.sv0`) is the shared bounded binary-
search primitive behind `floor_f64`/`ceil_f64`/`round_f64`/`trunc_f64`;
its `ensures` is `result <= x` and `result > x - 1.0 || result == x`. It
is pure `f64` `+ - / <= >=` over exact powers of two — nothing that
should differ across a correct IEEE-754 backend — so the leading
suspect is the `Unsafe.cast`-based `real`↔`Word64` round-trip in
`sv0vm/src/bytecode/bytecode.sml` (`f64Le`/`f64AtVec`) mis-decoding a
literal like `4503599627370496.0` (2^52, the loop's starting `bit`)
under 110.99.9's object representation, so the search accumulates a
`result > x`. Alternatively a version-sensitive `Real` op in the
interpreter's `arithFF`/`cmp` (`sv0vm/src/interpreter/interpreter.sml`).
SML/NJ 110.99.9 segfaults under QEMU user-mode emulation on Apple
Silicon, so it can't be reproduced on the dev machine — it needs a real
amd64 Linux env.

**Attempted 2026-08-30 (twice), reverted both times.** A field-math
codec replacing the `Unsafe.cast` (reconstruct the IEEE-754 fields with
pure Basis `Real` ops — `toManExp`/`fromManExp`/`toLargeInt`/`signBit`,
no `Unsafe`) round-tripped every value on SML/NJ 2026.1, passed the 7
small f64 behavioral-parity fixtures on 110.99.9 in CI every time, and
in one CI run made BOTH `vm_behavioral_parity` 8/8 AND the per-fixture
VM leg 84/84 green on 110.99.9 — but in ~2 of 3 CI runs it broke
`vm_behavioral_parity --project ../sv0-mathlib` (the full-library VM run
exits 1, `1/8`). Same codec, same commit, intermittent — so on top of a
`bitsToReal` bug for some bit pattern the `Unsafe.cast` path tolerates,
the sv0 native VM emitter's `.sv0b` output is very likely
nondeterministic (function/string ordering), and only some byte-order
variants trip the codec. The `Unsafe.cast` path passes `--project` 8/8
consistently, so it stays. Reverted: sv0vm `d990ef9`→`5509bfc`→
`7a4faeb`→`50d355d`; sv0-mathlib `4945f8e`→`b5f4e9f`→`a1d53de`→
`681ce90`. A real fix needs an amd64 Linux env and must address BOTH the
codec and emitter determinism — see the follow-up task. The exit-code
cross-backend gate (`vm_behavioral_parity.py`, COMPAT-001) and the
C-backend per-fixture leg are green.

---

Historical detail (the state before 2026-08-29):

**The checker-level restriction was FIXED (2026-08-23, sv0c `69ae8a5`);
VM bytecode float support was a separate, larger gap — now also fixed
per the status above.** `./scripts/sv0
vm-project-compile`/`vm-compile` invoke the SML-legacy bootstrap compiler
(`sml-legacy/`). Re-investigating this while fixing it found the original
framing undersold the scope: `sml-legacy/type_checker/checker.sml`'s
`synth` hardcoded `TyInt 32` for every arithmetic/comparison/unary-minus/
bitnot operand **anywhere in a function body, not just inside
`requires`/`ensures`/`loop_invariant`** — `fn add1(x: i64) -> i64 { return
x + 1; }` failed `E0400` with no contract involved at all.

**Fix** (three layered gaps, all in `checker.sml`/`unify.sml`): (1)
Arith/Cmp/Neg/BitNot now synthesize and propagate the real operand type
(mirroring the native checker's own equivalent fix, this file's bug #5)
instead of assuming i32 — for Arith specifically, prefers whichever
operand is numeric and not the bare literal default, so a real-typed value
wins over a literal on either side (`0 - x`, this codebase's idiomatic
negation pattern, has the literal on the LEFT, so a naive "trust the left
operand" rule — what a first attempt at this fix tried, copying the native
checker's own known-simplified approach — breaks it). (2) A float literal
had **no `synth` case at all** — not merely defaulted wrong, it fell
straight through to the generic "E0402: expression form not supported"
catch-all, so `x < 0.0` on an `f64` param failed outright regardless of
(1). Added `TyFloat 64` as its default (f64, the spec's own default float
width). (3) `Unify.unify` required an *exact width match* between two
`TyInt`/`TyUint`/`TyFloat` values — since every literal synthesizes to one
fixed default width with no bidirectional check-against-expected-type
anywhere in this checker, ordinary correct code like `fn f(x: i64) -> i64
{ ... return 0 - 1; }` failed: `0 - 1` has no i64-typed value anywhere in
it to infer the width from, so its synthesized `TyInt 32` never unified
against the declared `i64` return type even though `-1` is exactly
representable at both widths. Relaxed same-category `TyInt`/`TyUint`/
`TyFloat` unification to be width-blind, matching the native checker's own
type system (which never tracked integer/float width at the checker level
at all — the real C width is resolved later, downstream, during
lowering/emission). Signed vs. unsigned and int vs. float still don't
unify.

**Still separately blocked, NOT fixed: VM bytecode has zero float
representation at all.** Even with the checker now accepting `f64`, `sv0
vm-compile` on an `f64` function fails at a LATER, different stage —
`sml-legacy/ir/lowering.sml`'s `lowerLit` raises `"literal not supported
in lowering slice"` for any `FloatLit`, because `Ir.value` (SML-legacy's
own bytecode IR value type) has no float variant whatsoever — this isn't
a missing case to patch, it's the absence of float as a concept anywhere
in the VM's value representation or (presumably) its opcode set. Fixing
this would mean new IR/bytecode value/opcode support and corresponding
`sv0vm` (the SML bytecode interpreter) changes — a materially larger
feature, not a bug-shaped fix, and out of scope here.

The native/self-hosted checker (`sv0c/lib/checker.sv0`, used by
`./scripts/sv0 compile`/`emit-c`/`verify`) never had this restriction —
confirmed `requires(x > 0)` on an `i64` param compiled clean there even
before this fix.

**Verified**: an i64 param/return function with a requires/ensures
contract, the idiomatic `0 - x` negation pattern, and a plain
non-contract i64 body all type-check and lower to VM bytecode correctly
now. `f64` contracts type-check (the checker-level fix) but fail at
lowering (the separate, unfixed gap above) — confirmed both are real,
distinct boundaries, not the same bug. `integration-vm`'s existing
23-fixture suite stays green (no regression from the widened unify).

**Impact on this library:** unblocks `abs_i64`/`sign_i64`'s contracts (and
any future integer-width `_checked` function) on the VM path;
`abs_f64`/`sign_f64`/`min_f64`/`max_f64`/`clamp_f64` and all of R0.2/R0.3
(inherently f64) remain VM-blocked by the separate bytecode-float gap.
**Impact on M5:** Epic F's `#[constant_time]` contracts over `u8`/`u32`/
`u64` crypto buffers are now unblocked at the checker level if they're
meant to run through the VM-target path — still worth confirming with M5
planners whether that's the intended scope, since VM float support
remains entirely absent regardless.

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

## 7. An explicit `let x: f64 = <arithmetic-expr>;` local silently defaulted to `int`

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (uncommitted in that
repo's working tree). Same failure shape as bug #5 (silent truncation/UB,
no diagnostic), found while verifying bug #3's fix, and — worse than bug
#5's Assign-temp case — genuinely undefined behavior in C (double-to-int
conversion of a NaN), not just a defined truncation.

**Root cause**: two DUPLICATE copies of `let`-statement lowering
(`lower_stmt` for a function's top-level body, `lower_tag_block` for
nested `{}` blocks — same logic, maintained twice) each pick a `let`
local's C declaration type **purely from the init expression's shape** —
struct literal, 2-segment enum-ctor path, function call, `box_deref` — with
no case for a plain arithmetic/literal RHS, which falls through to a bare
`DeclVar` (always `int`). The `let` statement's own explicit type
annotation (`sv0c/lib/parser.sv0`'s `parse_let_stmt`, `LetStmt`'s own `d2`
field) *was* being parsed and stored correctly — a comment right next to
it even says so (`"was a bare 0/-1 present flag, unread by consumers"`) —
but neither lowering copy had been updated to actually read it. Textbook
instance of this session's recurring pattern: data made available,
consumer never revisited.

**Fix**: in both `lower_stmt` and `lower_tag_block`, when none of the
existing shape-based special cases apply, check the `let`'s own annotation
token; if it names one of the primitives whose C type isn't the default
`int` (`i8/u8/i16/u16/i64/u64/u32/f32/f64/isize/usize` — new helper
`is_wide_primitive_ty_name`), defer to a `DeclNamed` using that annotation
instead of the bare `DeclVar`. Deliberately excludes `i32`/`bool`
(already correct via the existing default) to keep the change minimal. A
second, necessary half of the fix: `megaTU-main.sv0`'s `megatu_ty_name`
printed a `DeclNamed`'s type token as **raw source text** — correct for a
struct/enum name (which *is* its own C name) but not for a primitive
annotation (`"f64"` is valid sv0, not valid C) — so it now routes through
a new `megatu_primitive_cty_or_raw` translation step first (mirrors
`ast_ty_to_c_string`, but must NOT just call that directly: its own
"unrecognized name" fallback is *also* `"int"`, which would be
indistinguishable from a genuine `i32`/`bool` match and wrongly turn an
unrecognized struct name into the word `"int"`).

**Verified**: `let nan: f64 = 0.0 / 0.0;` now emits `double nan;`, in both
a function's top-level body and inside a nested block; a parallel `i64`
case (`let big: i64 = 9223372036854775807;` inside an `if` block) emits
`int64_t big;`. Both run correctly (exit 0), not just inspected in the C.
`sv0-mathlib`'s `main.sv0` restored the natural `let nan: f64 = 0.0/0.0;`
pattern (previously worked around by passing the expression inline to a
call) and passes. `pc3b6-native-project-acceptance.sh`'s 18-fixture corpus
stays green.

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

**Severity: low. The silent-diagnostic half is FIXED upstream
(2026-08-23, sv0-toolchain, uncommitted in that repo's working tree at
filing time — see below); the syntax half is a deliberate non-fix.**
SPEC.md's own worked examples (e.g. ARITH-009's
`ensures(t == 0.0 ==> result == a)`) use `==>` for logical implication.
This is not a real sv0 operator — no occurrence anywhere in `sv0doc` or
the test corpus. Rewrite `P ==> Q` as `!(P) || (Q)` — confirmed working;
recommending SPEC.md be corrected rather than adding new compiler syntax
for a rarely-needed operator with a one-line rewrite, so `==>` itself
stays unimplemented by design, not oversight.

**The silent-diagnostics half, however, was a real toolchain bug and is
fixed**: compiling a contract using `==>` (or any other genuine parse
failure) used to exit nonzero with **no error message at all** — not even
a generic parse-failure line — because `build/sv0-megatu-compiler-native`
had a parse-failure path with no diagnostic-emission logic at all.
`parser.sv0`'s `parse_program` now encodes the failing top-level item's
own start token into its failure return value (an approximate location —
whatever failed deeper inside that item's own parse isn't separately
pinpointed, since the parser has no diagnostic-packing machinery of its
own — but real, not none), and `megaTU-main.sv0`'s `main()` reports it
through the existing diagnostic formatter (`E0100`/"syntax error") instead
of silently falling through. Verified: the `==>` repro now prints
`error[E0100]: syntax error` with a line/col/snippet, in both single-file
and `--project` mode, instead of empty stdout+stderr.
`pc3b6-native-project-acceptance.sh` and `self-host-check-golden` both
green after the fix.

**Also surfaced by this fix, not by sv0-mathlib itself (this library has
no struct types yet) — a real, separate, PRE-EXISTING bug in sv0c's own
test corpus, now also fixed (sv0c commits `1e48373`/`8c04af1`):** a bare
`q.x = 7;`/`q.x += 3;` field-assignment statement (distinct from a
`let`-bound struct initializer) silently compiled to nothing at all — the
`self-host-sv0-loop` gate's own `field_assign.sv0` fixture had been
compiling to `int main(void) { return 0; }` and exit 0, for a completely
wrong reason, since before this session started (confirmed via bisection
to sv0c commit `d669398`). Root cause: `parser.sv0`'s
`parse_assign_target_op_pos` checked token tag 15 (`::`, COLONCOLON) for
the `.` in an assignment target instead of tag 16 (DOT), so a bare field
assignment never matched at all and silently vanished; a second, separate
gap one layer downstream (`lowering.sv0`'s `ExprAssignOp` lowering had no
case for a struct-field target, only a plain variable) meant even after
fixing the first, `q.x += 3;` specifically still silently vanished.
Neither is a sv0-mathlib blocker (no struct usage in this library's F0
surface), but both are now fixed regardless, and stand as a second
concrete instance of exactly the failure mode this bug's fix targets:
before it, a real parser/lowering defect had been indistinguishable from
"nothing to compile" for who knows how long.

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

## 8. Enum payload slots are always a 32-bit `int`, regardless of type

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (uncommitted in that
repo's working tree). Two layered sub-bugs, both in the same "everything
numeric defaults to int" family as bugs #5/#1/#7, just a fourth and fifth
location:

**8a — the enum typedef's own field.** An enum variant's payload field
always compiled to plain C `int`, regardless of the payload's declared sv0
type:
```
enum Box64 { Wrap(i64) }
```
compiled to `typedef struct { int tag; int p0; } Box64;` — `p0` was `int`,
not `int64_t`. Root cause: `sv0c/lib/lowering.sv0`'s `emit_enum_td`
hardcoded `int p{N};` for every payload slot; the parser had never even
retained each variant's payload TYPE tokens to hardcode away from
(`parse_enum_item` recorded the payload's presence/count, never its type
name). Fix: `parse_enum_item` now also records each payload's type-name
token (two new flat program-wide arrays,
`enum_variant_payload_count_by_variant` / `enum_variant_payload_ty_name_tok`,
threaded through `parse_item`/`parse_program`/`lower`/
`collect_typedefs_str`); a new `enum_slot_ctys_for_item` resolves each
slot's C category by scanning every variant of that enum item — since sv0
enums compile to one flat shared struct (not a real C union), a slot's
category is only sound if every variant that actually uses that slot
agrees; on any conflict or if nothing recognizes it, falls back to the
prior always-safe `int` default, so this is only ever an improvement, never
a regression.

**8b — reading the payload back out via `match`, found immediately after
fixing 8a while testing the actual `abs_checked_i64` round-trip.** Even
with the struct field itself now correctly `int64_t`, a match arm binding
like `Option::Some(v) => ...` still declared `v` as plain `int`,
truncating the value on the way back out:
```c
int64_t p0;           /* 8a's fix: the field itself is now correct */
...
int v = some_case.p0; /* 8b: reading it back out was still wrong */
```
Root cause: a match-arm payload bind lowers to an ordinary `Assign`
instruction whose RHS is a `VMember` (struct-field-access) value — this
routes through the SAME (handle → category) tyenv machinery bug #5/#1
built for temp-typing, but `megatu_value_cty`'s `VMember` case
(`sv0c/lib/megaTU-main.sv0`) was hardcoded to `return 0` (`int`), the
"future work" stub left when that machinery was first written. Fixed by
building a second, small lookup table in `main()` — reusing 8a's own
`enum_slot_ctys_for_item` so the two can never disagree — mapping each
enum item to its slots' categories, and extending the tyenv with a third
parallel array tracking each handle's *enum item index* (populated
alongside the existing category at every `DeclNamed`/parameter-seed site,
by resolving the declared type name against the new table). `VMember`'s
case now: decode the payload-slot sentinel handle (`fh <= -10` → slot
`0 - 10 - fh`, the same encoding `megatu_field_name` already used to print
`p<i>`), resolve the scrutinee's own enum item via the tyenv, and look up
that slot's category — falling back to the prior `int` default whenever
the scrutinee isn't a tracked enum-typed handle.

**Verified**: `enum Box64 { Wrap(i64) }` now emits `int64_t p0;`
(confirms 8a); the full `abs_checked_i64` round trip —
```
enum Option { Some(i64), None }
fn abs_checked_i64(x: i64) -> Option { ... return Option::Some(abs_i64(x)); }
...
let ok: bool = match some_case { Option::Some(v) => v == 9223372036854775807, ... };
```
now emits `int64_t v = some_case.p0;` (confirms 8b) and **runs to exit 0**
end to end — not just inspected in the C.
`scripts/pc3b6-native-project-acceptance.sh`'s 18-fixture corpus stays
green, and this repo's current full suite (i32 + f64 + i64 forms) still
compiles and runs to exit 0 after rebuild.

**Deliberately NOT restored via the shared generic `prelude::Option<T>`
— see bug #9.** 8a's per-item slot-category resolution reads each payload
slot's type-name TOKEN as it was written in the enum DECLARATION. For a
generic `enum Option<T> { Some(T), None }`, that token is the literal text
`"T"` — a type PARAMETER name, not a concrete type — which
`enum_payload_ty_name_to_category` correctly doesn't recognize (it isn't
`i64`/`u64`/`u32`/`f32`/`f64`), so it falls back to `int`, same as before
either half of this fix. Confirmed empirically: instantiating the SAME
shared `Option<T>` with `Option::Some(<i64>)` still truncates through `v`,
because there is only ever one physical declaration of `Option`'s payload
type (`T`), not a distinct one per call-site instantiation — sv0 has no
monomorphization (see bug #9). This fix is real and correct for what it
claims — a NON-generic (concrete) enum's payload slots and match bindings
now honor their real declared type — it just doesn't, and structurally
cannot, reach the generic case without bug #9 also being fixed.

**Impact on this library:** `abs_checked_i64` is restored using a
**second, concrete, non-generic** enum dedicated to the `i64` case
(`OptionI64`) rather than the shared generic `Option<T>` — see
`lib/prelude.sv0` and bug #9 for why, and README.md's "Deviations from
SPEC.md" for this as a recorded, deliberate workaround, not an oversight.

## 9. Generic enums have no monomorphization — one shared instantiation, not one per concrete type

**Severity: high for this library's `_checked`-function pattern generally;
NOT fixed; found while restoring `abs_checked_i64` after bug #8.** Bug #3
made `enum Option<T> { Some(T), None }` parse and resolve at all (its `<T>`
no longer causes an "unknown type" error); it did not make each concrete
instantiation (`Option<i32>` vs `Option<i64>` vs `Option<f64>`) into a
distinct type. There is exactly one physical C struct for `Option`, and
its payload slot's category is resolved from the DECLARATION's own payload
type token — which, for a generic enum, is the parameter name `T`, never a
concrete type, regardless of how many different concrete types the enum is
actually instantiated with across a program. Confirmed empirically: a
program declaring the single shared `enum Option<T> { Some(T), None }` and
calling `Option::Some(<large i64 value>)` still emits `int v = ...p0;` at
the match-arm binding and silently truncates on run — the exact symptom
bug #8 fixes, just unreachable for the generic case because 8's fix has
nothing but the literal text `"T"` to resolve.

**Impact on this library:** SPEC.md's `_checked` function family (any
function returning `Option<T>` for `T` other than the one concrete type
whichever single instantiation happens to "win," in practice whichever
concrete type an `Option` value was most recently constructed with in the
same translation unit) is not soundly usable with the SHARED
`prelude::Option<T>` for more than one payload type per program. Worked
around here, not fixed: `lib/prelude.sv0` additionally declares
`OptionI64` (concrete, non-generic, `Some(i64)`/`None`) alongside the
generic `Option<T>` used for `i32`, and `abs_checked_i64` returns
`OptionI64` — see README.md's "Deviations from SPEC.md" for this as a
recorded workaround. This does not scale past a handful of concrete
`_checked` return types without either (a) real monomorphization landing
upstream, or (b) this library hand-declaring one concrete `Option<T>`
variant per `T` it needs (`OptionU32`, `OptionF64`, ...) — acceptable for
F0's small surface, worth revisiting before R0.1+'s larger `_checked`
surface if bug #9 isn't fixed by then.

## 10. `loop_invariant` on a `while` loop corrupts name resolution for an unrelated, earlier function

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (sv0c commit `9d0b69c`,
parent `0aa2e59`). Found immediately on adding this library's first
`loop_invariant` clause (R0.1's `frac_floor_of_nonneg`, an ARITH-005
helper) to `lib/arith.sv0`, a file with several other, earlier functions:
compiling started failing with `error[E0300]: unbound name` pointing at
`lo` inside `clamp_i32`'s own `requires(lo <= hi)` — a completely
unrelated, unmodified, previously-working function. The loop_invariant
clause's actual *content* was irrelevant: even a bare
`loop_invariant(true)` triggered it (confirmed by bisection down to a
minimal 8-line repro); only whether one was present anywhere in the file
mattered, and the specific earlier function it broke shifted depending on
what else was in the file — a strong signal of an index/offset bug rather
than anything semantically related to `loop_invariant`'s own meaning.

**Root cause**: `sv0c/lib/resolver.sv0`'s and `sv0c/lib/checker.sv0`'s
`WhileLoop` (tag 12) handling both read a loop_invariant clause's
expression via `inv_f + ii`, treating `inv_f` (the while node's `ed3`) as
a direct index into the `et` expression-node arena. It isn't one:
`parser.sv0`'s `block_stmt_sidecar_push` (the same mechanism block
statements and match arms already use to survive being non-contiguous in
`et`) stores each loop_invariant's REAL `et` index in the shared `pp`
pool and returns `offset + 1` into THAT pool as the handle — a
`block_stmt_index` helper already exists specifically to decode this
indirection back to the real `et` index, and both consumers should have
used it, but instead used the raw `pp`-pool offset as an `et` index
directly. Since `pp` (identifiers/paths) is typically much smaller than
`et` (every expression node in the whole file), the wrong index landed on
some unrelated, earlier `et` node — resolver.sv0 then resolved (and
reported errors on) THAT node instead of the real loop_invariant
expression; checker.sv0's `expr_references_result` (checking for illegal
`result` references, a narrower, easy-to-miss consequence of the same
bug) silently scanned the wrong subtree too, fixed for consistency even
without its own failing repro.

**Fix**: route both call sites through `block_stmt_index`, exactly like
block statements and match arms already do.

**Verified**: the 8-line minimal repro (an unrelated `clamp_i32`-style
function plus a new function with a bare `while cond loop_invariant(true)
{ }`) compiles clean; this library's actual `frac_floor_of_nonneg`
(a real, meaningful loop_invariant, `acc <= x`) compiles and its callers
(`trunc_f64`/`floor_f64`/`ceil_f64`/`round_f64`) all run correctly.
`pc3b6-native-project-acceptance.sh`, `self-host-check-golden`, and
`integration-vm` all green after the fix.

**Impact on this library**: blocked ARITH-005 entirely until fixed (any
file combining a `loop_invariant`-bearing helper with other functions hit
this). **Impact on M5**: any LLVM-backend or crypto code using
`loop_invariant` in a multi-function file would have hit this identically
— worth flagging to M5 planners as a real, now-fixed compiler
correctness gap, not just a mathlib-local nuisance.

## 11. `match` on a direct call result (no intermediate `let`) mistypes the payload binding

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (sv0c commit `4bda54a`,
parent `43f36bf`). Found while adding ARITH-007's `pow_checked_i64`:
`match f() { Some(v) => ..., None => ... }` — matching directly on a
function call's own result, with no intermediate `let` — declared `v` as
plain `int` regardless of its real type, truncating any i64/u64/f32/f64/
u32 payload. The `let x: T = f(); match x { ... }` form (an intermediate
`let`) already worked correctly (bug #8's fix covers it).

**Root cause**: bug #8's fix resolves a match-arm payload binding's real
category by looking up the SCRUTINEE's own enum item in the tyenv — but
that lookup was only ever populated for a `DeclNamed`-typed local (a
`let x: T = ...`); a bare function-call result temp
(`codegen_Instr::Call` in `megaTU-main.sv0`) always registered with a
hardcoded "no enum" sentinel, even when the call's own resolved return
type IS a known enum. Fixed by computing the enum index from the call's
resolved return-type name, exactly as `DeclNamed` already does.

**Verified**: `match f() { Some(v) => v == <i64 value>, None => false }`
on an `OptionI64`-returning function now correctly declares
`int64_t v = ...` and produces the right result — previously silently
truncated with zero diagnostic. `pc3b6-native-project-acceptance.sh` and
`self-host-check-golden` both green.

## 12. `match` used AS A VALUE mistypes its own overall result temp

**Severity: medium — found immediately after fixing bug #11, NOT fixed.**
`let x: T = match opt { Some(v) => v, None => dflt };` — binding a
match's OWN VALUE (not just a payload) — declares the match expression's
internal result-holding temp as plain `int`, regardless of the arms'
real type, even when every individual piece around it (the payload
binding `v`, and the outer `let x: T = ...`'s own declaration) is
correctly typed by bugs #8 and #11's fixes. Confirmed via inspecting the
emitted C: `int _sv0t1; ... _sv0t1 = v; ... x = _sv0t1;` — `x` itself
ends up `int64_t` (bug #7's fix), but the match's own intermediate temp
truncates the value on the way there.

**Root cause**: `lowering.sv0`'s `lower_tag_match` allocates the match's
overall result via a bare, untyped `Instr::DeclVar(out)` (the same
"declare with no type info" shape bugs #5/#8 already fixed for other
DeclVar cases — the `ensures`-clause `result` slot, by name, and enum
payload/scrutinee categories, by tyenv lookup) — but nothing resolves
`out`'s real category here, because every match arm stores into it via
`Instr::Store` (not `Assign`, which is where category inference lives),
and `Store`'s target must already be declared by the time it runs. A
correct general fix needs `DeclVar`'s emission to look ahead through the
(possibly deeply nested, if/else-chain-shaped) match-arm instructions to
find the first `Store` into this handle and infer its category from
there — a proper prepass, not a small patch — which this session's
remaining budget didn't cover.

**Workaround, used throughout this library from here on (verified to
fully sidestep the bug)**: never bind a `match`'s value directly when the
arms produce a wide (non-i32/bool) type. Instead, declare an
already-correctly-typed `let mut` local (`DeclNamed`, unaffected by this
bug) and use `match` as a bare STATEMENT whose arms assign into it:
```
let mut v: i64 = 0;
match opt {
    OptionI64::Some(x) => { v = x; },
    OptionI64::None => {},
}
```
instead of `let v: i64 = match opt { OptionI64::Some(x) => x, ... };`.
`pow_checked_i64` (ARITH-007) uses exactly this pattern. Boolean-valued
match arms (this library's dominant `_checked`-function-testing idiom,
e.g. `let ok: bool = match opt { Some(v) => v == N, None => false };`)
are NOT affected — `bool` fits `int` correctly regardless, so only
match-as-value bindings whose arms produce a genuinely wide type need
the workaround.

## 13. A binop performed directly on a struct field access mistypes its own temp

**Severity: medium — found while implementing ARITH-010 (`fma_f64`), NOT
fixed.** `sa.hi * sb.hi` — a binary operator applied DIRECTLY to two
struct field accesses (`sa`/`sb: Pair2 { hi: f64, lo: f64 }`) — declares
its own result temp as plain C `int`, silently truncating the product of
two `f64` fields. Confirmed via inspecting the emitted C:
`int _sv0t2 = (sa.hi * sb.hi);`. The exact same "everything numeric
defaults to int" family as bugs #5/#8/#11, but for a PLAIN struct field
(a `codegen_Value::VMember` whose field handle is an ordinary field-name
token) rather than an enum payload slot — bug #8/#11's fix only extended
`megatu_value_cty`'s `VMember` case to resolve ENUM payload slot
categories via the tyenv's enum-item tracking; a struct field access
still falls through that same function's default `return 0;` (`int`)
unconditionally, since no equivalent "which struct type, which field"
lookup table exists for structs the way one now does for enums.

**Root cause**: `megatu_value_cty`'s `VMember` case in `megaTU-main.sv0`
only special-cases the enum-payload-slot sentinel range (`fh <= -10`); a
positive field-name token (the shape every ordinary struct field access
uses) has no corresponding lookup at all. A correct general fix needs new
infrastructure mirroring bug #8's enum-slot table, but keyed by struct
item + field NAME rather than enum item + slot INDEX (structs don't use
the same payload-slot-index encoding enums do) — scoped but not attempted
this session.

**Workaround (verified to fully sidestep it, used throughout `fma_f64`'s
Dekker-splitting implementation)**: never perform arithmetic directly on
a struct field access when the field is a wide (non-i32/bool) type.
Instead, copy each field into its own local first (`let sa_hi: f64 =
sa.hi;`), then do arithmetic on the LOCALS — a local's own `DeclNamed`
typing is unaffected by this bug (bug #7's fix covers it independently),
so `sa_hi * sb_hi` (both plain variables) resolves correctly.

**Impact on this library**: blocked `fma_f64` (ARITH-010) until worked
around; will recur for R0.2/R0.3's `Complex`/`Polar` struct types, which
are entirely `f64`-field structs — worth fixing upstream before that work
starts, rather than re-discovering the same workaround repeatedly.

## 14. A struct field name token landing at index 500-599 was misread as a tuple projection

**STATUS (2026-08-23): FIXED in `sv0-toolchain`** (sv0c commit `a74d537`,
included in the parent's later submodule bump — this checkout is shared
with other concurrent sv0-toolchain work, so the parent's own bump commit
that picked this up isn't this library's to cite by hash). Found while
adding `math::trig`'s `sin_f64`/
`cos_f64` (a `SinCos { sin: f64, cos: f64 }` struct literal in a file
large enough to push a real field-name token past source position 500):
compiling failed with a C-level error, `no member named 'f93' in
'SinCos'` — the struct's `s`/`c`-shaped (in the original repro) field
names were emitted as `f93`/`f97` instead.

**Root cause**: two entirely different features shared the same handle
space by coincidence, not by design. A regular struct field access
(`obj.fieldname`, `codegen_Value::VMember`'s field handle) uses the
field name's own real, positive source TOKEN INDEX directly — unbounded,
growing with file size, same as any other token. Tuple projection
(`obj.0`, `obj.1`, sv0's numeric-index syntax for tuples) encoded its
field index as a SYNTHETIC handle `500 + field_num`, decoded by
`megatu_field_name` (`megaTU-main.sv0`) as "any handle in `[500, 600)`
is a tuple field" — but `500..599` isn't a reserved sentinel space at
all, it's well within the range real token indices reach in any
moderately-sized multi-function file (this repo's own files routinely
exceed token 500). Once a genuine struct field name token landed in
that range, it was silently misidentified as a tuple-projection index
instead of resolved by its real name.

**Fix**: moved the tuple-projection encoding to a NEGATIVE sentinel
range (`-2000000 - field_num`) instead — real token indices are always
`>= 0`, so this is unconditionally collision-free, not merely
improbable. Chosen far enough below the existing enum tag/payload-slot
sentinels (`-1`, `-10-i`) that no realistic enum payload count could
ever reach it either, mirroring `lower_temp_base`'s own "far above any
realistic token count" reasoning for temp handles, just mirrored onto
the negative axis.

**Verified**: the exact struct-literal repro that triggered this now
compiles and runs correctly; `pc3b6-native-project-acceptance.sh`,
`self-host-check-golden`, and `integration-vm` all stay green (this
library doesn't use tuples with more than one element — `E0446:
multi-element tuples are not supported in this slice` — so nothing here
exercises the *tuple* side of this fix directly, only confirms the
*collision* is gone).

**Impact on this library**: blocked `math::trig`'s very first struct
usage; would have blocked `math::polar`/`math::complex` (both
`Complex`/`Polar` are structs) identically, and in fact ANY sufficiently
large file with ANY struct field access — this wasn't specific to
`math::trig`'s particular size, just the first place in this project
that happened to cross the threshold.

## 15. An inline struct literal passed directly as a function-call argument sometimes resolves its field names against the wrong struct declaration

**STATUS (2026-08-28): OPEN, workaround verified.** Found finishing
CPLX-007 (`exp_complex`/`ln_complex`/`pow_complex`, `main.sv0`'s new
test cases). `Complex { re: 0.0 - 1.0, im: 0.0 }` passed directly as the
2nd argument to `approx_eq(euler, Complex { re: 0.0 - 1.0, im: 0.0 },
epsilon)` compiled to:

```c
Complex _sv0t521;
_sv0t521.hi = hi;
_sv0t521.lo = lo;
```

— `.hi`/`.lo` are `Pair2`'s field names (`arith.sv0`'s double-double
helper struct, unrelated to `Complex`), and `hi`/`lo` as bare
identifiers don't even exist in this scope (a second, independent
compile error). The SAME struct literal shape, immediately bound to a
`let` first (`let neg_one: Complex = Complex { re: 0.0 - 1.0, im: 0.0 };
approx_eq(euler, neg_one, epsilon)`), compiles correctly with `.re`/
`.im`. Not reproduced for every inline struct-literal argument —
`div_checked_complex(c1, Complex { re: 0.0, im: 0.0 })` a few lines
earlier in this same file compiles fine — so this looks like a
stateful/positional bug in whatever tracks "the current struct type" for
literal field-name resolution (the same subsystem bug #13/#14 touched),
not a blanket "inline struct literal arguments never work." Not yet
root-caused in `sv0c` itself — no repro isolated smaller than this
file's own real usage, and no time spent bisecting which specific
preceding construct flips the resolver's state.

**Workaround (used throughout `main.sv0`'s CPLX-007 tests)**: always
bind a struct literal to a `let` before passing it as a function-call
argument, never inline `Fn(a, Struct { field: v, ... }, b)` — matches
this library's existing convention (nearly everywhere else in
`main.sv0`) of naming intermediate values anyway.

**Impact on this library**: low — the workaround is free (no field-copy
overhead beyond what emits either way), and this file already leaned
toward named intermediates before this bug was found. Worth a focused
follow-up to isolate a minimal repro and find the actual root cause in
`sv0c`, since "sometimes, not always" bugs are the ones most likely to
bite a future consumer who doesn't know to work around them.

## 16. A bare `return field_a + field_b;` combining two field accesses of the SAME struct instance mistypes its own temp — a regression past bug #13's fix

**STATUS (2026-08-28): FIXED in `sv0-mathlib` via workaround; the
underlying `sv0c` regression is NOT fixed, and NOT yet root-caused.**
Found setting up `scripts/ci` (TEST-006): `sv0-mathlib`'s CI, which
checks out `sv0-toolchain`'s default branch fresh (not pinned to any
particular commit — this library tracks the moving upstream, per its
own README "Deviations from SPEC.md" #2), failed at `ln_f64`'s own
`main.sv0` assertion (`ln_f64(10.0)` off by more than its stated
accuracy budget) against `sv0-toolchain` `c318513` / `sv0c` `53de895` —
a LATER revision than the `sv0c` `d0fa706` this library's own accuracy
audit was measured against (BUGS.md #13's own fix commit). Bisected by
building the native compiler at both revisions and comparing emitted C
for the exact same `sv0-mathlib` source: at `d0fa706`,

```c
static double ln_f64(double x) {
  ...
  Pair2 p = ln_f64_dd(x);
  double _sv0t1 = (p.hi + p.lo);   // correct
  return _sv0t1;
}
```

at `53de895`, the IDENTICAL `sv0-mathlib` source (`return p.hi + p.lo;`)
instead emits:

```c
static double ln_f64(double x) {
  ...
  Pair2 p = ln_f64_dd(x);
  int _sv0t1 = (p.hi + p.lo);      // WRONG — silently truncates to int 2
  return _sv0t1;
}
```

— `ln_f64(10.0)` returned exactly `2` (an `int`-truncated `2.30258...`)
under the newer compiler, not merely a small accuracy miss. This is the
exact "everything numeric defaults to int" family bug #13's fix was
supposed to close (a binop directly on a struct field access mistyping
its own temp), but here BOTH operands are field accesses of the SAME
struct local (`p.hi + p.lo`), not two different structs — bug #13's own
repro (`sa.hi * sb.hi`) used two different `Pair2` locals `sa`/`sb`.
Something in `sv0c`'s struct-field-category resolution regressed (or
was never fully covered) for this narrower shape between `d0fa706` and
`53de895` — not yet bisected further or root-caused within `sv0c`
itself; that's real, separate `sv0-toolchain` work, not something this
session had scope to chase down.

**Impact on this library**: significant — this exact `return
X.field_a + X.field_b;` pattern is the standard "round a double-double
result to a single `f64`" idiom this library's own accuracy work
(BUGS.md's accuracy-audit commits) introduced pervasively:
`ln_f64`/`sin_f64`/`cos_f64`/`atan_f64` all ended with exactly this
shape. All four were silently broken (truncated to `int`) under the
newer compiler — confirmed via a full local reproduction (cloned
`sv0-toolchain` at the exact `c318513`/`53de895` pins CI used, built the
native compiler fresh, ran this library's full test suite: failed at
`ln_f64` first, the earliest such call in `main.sv0`'s test sequence;
`sin_f64`/`cos_f64`/`atan_f64` would very likely have failed too had the
suite gotten past `ln_f64`).

**Workaround (applied to all four affected functions in
`lib/trig.sv0`)**: copy each field into its own local before the binop,
mirroring bug #13's own original workaround exactly:

```sv0
let p: Pair2 = ln_f64_dd(x);
let p_hi: f64 = p.hi;
let p_lo: f64 = p.lo;
return p_hi + p_lo;
```

Verified: rebuilt the native compiler at BOTH the `d0fa706`-era pin this
library was previously tested against AND the current `c318513`/`53de895`
upstream HEAD; `scripts/ci` and the full `docs/ulp_audit_harness.c`
sweep pass identically on both (same ULP numbers on the `d0fa706` build
as before this fix — confirming the fix is a pure typing correction with
no effect on the actual computed values; `ln_complex`/`pow_complex`'s
own already-documented informational residuals shifted slightly on the
newer `53de895` build, consistent with unrelated codegen changes
elsewhere in that revision, not a new regression from this fix).

**Follow-up**: a session should bisect `sv0c` between `d0fa706` and
`53de895` to find and fix the actual regression, and add a regression
test to `sv0c`'s own test corpus for the narrower "same-struct,
two-field binop" shape specifically (bug #13's existing regression
coverage, if any, evidently didn't catch this).

## 17. `--project` file discovery silently fails (exit 2, zero diagnostics) when a top-level file/directory sorts alphabetically before `lib`

**STATUS (2026-08-29): OPEN, workaround verified.** Found setting up
`test/unit/` (TEST-001). A `--project <dir>` compile that has always
worked (`lib/` plus one extra `.sv0` file at the project root) started
failing — `exit code 2`, `stdout` AND `stderr` both completely empty,
no diagnostic text at all (the same failure shape bug #6's own fix was
supposed to close — silent parse/link failures — but this isn't a parse
error; the SAME file compiles fine under a different name). Bisected by
renaming the one variable (the extra file's name, keeping its content
byte-identical) across a matrix of names:

```
arith_test.sv0   -> exit 2   (fails)
arithtest.sv0    -> exit 2   (fails)
foo.sv0          -> exit 2   (fails)
aaa.sv0          -> exit 2   (fails)
kkk.sv0          -> exit 2   (fails)
zz_arith_test.sv0  -> exit 0 (works)
my_arith_test.sv0  -> exit 0 (works)
trig_test.sv0      -> exit 0 (works)
mmm.sv0            -> exit 0 (works)
zzz.sv0            -> exit 0 (works)
```

The pattern: whether the file's name sorts alphabetically BEFORE or
AFTER `lib` (the project's own subdirectory) — `a`/`f`/`k` fail, `m`/
`t`/`z` succeed. Confirmed it's really about DIRECTORY sort order, not
the file's own name: moving the exact same file into a subdirectory
(`tests/arith_test.sv0` — `tests` sorts after `lib`) succeeds, while
moving it into a differently-named subdirectory (`aaa/arith_test.sv0` —
`aaa` sorts before `lib`) fails with the identical exit-2/no-diagnostic
shape. So `--project`'s file-discovery walk is order-sensitive in a way
that has nothing to do with imports or module structure — something
about processing a project-root entry before it reaches `lib/` breaks
silently, most likely (not yet root-caused inside `sv0c` itself)
whatever populates the module/prelude registry expects `lib/` (or
whichever directory a real multi-file sv0 project conventionally puts
its library code in) to be visited first.

**Workaround** (used in `scripts/run_unit_tests.py`, which builds a
fresh temp project per `test/unit/*.sv0` file — see that script's own
comment): put the extra file inside a subdirectory whose name sorts
alphabetically AFTER `lib` (the script uses `under_test/`), never at
the project root or in a before-`lib` subdirectory.

**Impact on this library**: would have silently blocked `test/unit/`
entirely (TEST-001) with zero indication of WHY — every one of this
library's own module names (`arith`, `complex`, `modular`, `polar`)
sorts before `lib` alphabetically, so a naive
`<module>_test.sv0`-at-the-project-root convention (the shape SPEC.md
§16.1 describes) would have hit this for `arith_test.sv0`/
`complex_test.sv0`/`modular_test.sv0` specifically, while
`trig_test.sv0`/`polar_test.sv0` (sorting after `lib`) would have
worked — an intermittent, filename-dependent failure that's exactly the
kind of thing that looks like flakiness rather than a real, deterministic
bug until bisected.

## 18. `let x: StructType = <plain variable already of that struct type>;` mistypes the new local as `int`

**STATUS (2026-08-29): OPEN, workaround verified.** Found writing
`test/unit/polar_test.sv0` (POLAR-001's own "`Copy`-derivation test").
Minimal repro:

```sv0
use polar::Polar;
fn main() -> i32 {
    let p0: Polar = Polar { r: 1.0, theta: 2.0 };
    let p0_copy: Polar = p0;   /* RHS is a bare variable, not a call/literal */
    if p0.r != p0_copy.r { return 1; }
    return 0;
}
```

compiles to:

```c
int p0_copy;
p0_copy = p0;
if ((p0.r != p0_copy.r)) {   /* p0.r on an `int` — compile error */
```

— the same "everything defaults to `int`" family as bugs #5/#7/#8/#13/
#16, but for yet another specific shape none of those fixes covered:
a `let` binding whose right-hand side is a BARE VARIABLE already of the
target struct type (not a function call, not a struct literal, not an
enum constructor). `p1: Polar = to_polar(3.0, 4.0)` (a call result) and
`p3: Polar = Polar { r: 5.0, theta: ... }` (a struct literal) both work
correctly elsewhere in this same file — this is specifically the
"identifier expression" `let`-init shape that's uncovered. Not
root-caused inside `sv0c` itself this session (likely the same
`expr_init_cty`-style "infer purely from the init expression's shape"
logic bug #7's own fix note describes, just missing an `Identifier`
case alongside the `Call`/`StructLit`/`EnumCtor` ones it already
handles).

**Workaround**: route the copy through a trivial identity function
(a `Call`, which resolves its type correctly) instead of a bare `let x:
T = y;`:

```sv0
fn identity_polar(p: Polar) -> Polar { return p; }
...
let p0_copy: Polar = identity_polar(p0);
```

used in `test/unit/polar_test.sv0`'s own POLAR-001 test.

**Impact on this library**: low so far — this exact shape (binding a
`let` directly to an already-in-scope struct-typed variable, with no
intervening call or literal) doesn't appear to occur anywhere in
`lib/*.sv0`'s own real code (every struct-typed `let` in this library's
actual functions is either a call result or a struct literal), only in
this new test file's own attempt to demonstrate `Copy` directly. Worth
a follow-up to root-cause and fix upstream regardless, since it's a
natural pattern for any future consumer to reach for.

## 19. A struct-literal field initializer, or a `requires`/`ensures` clause, that is itself a binop involving a struct-field access mistypes as `int`

**STATUS (2026-08-29): OPEN, workaround verified — a WIDER regression
than bug #16, found via `test/property/property_test.sv0`.** Building
TEST-004's property-test layer surfaced this while checking `Complex`
addition's associativity: the check intermittently panicked (not every
run — see below for why) with `sv0 contract violation: ensures failed
in add_complex` under `sv0c` `53de895` (`scripts/ci`'s own unpinned
toolchain). Bisected in two parts:

**Part A — struct-literal field initializers.** `Complex { re: a.re +
b.re, im: a.im + b.im }` (`add_complex`'s function BODY, `a`/`b` two
DIFFERENT `Complex` parameters, same field name) — this is bug #13's
EXACT original repro shape, previously fixed, now regressed for THIS
specific context:

```c
Complex _sv0t0;
int _sv0t1 = (a.re + b.re);   /* WRONG */
_sv0t0.re = _sv0t1;
```

A minimal, isolated repro (a `Pt { re: f64, im: f64 }` struct, `add_pt`
returning `Pt { re: a.re + b.re, im: a.im + b.im }`) confirmed this is
general, not `Complex`-specific. Audited every struct literal in
`lib/*.sv0` for a directly-inlined struct-field access inside a binop
(field-op-field OR field-op-literal/local) and fixed each one the
established way — extract every field to its own local FIRST, so the
struct literal only ever combines LOCAL-op-LOCAL: `add_complex`/
`sub_complex`/`neg_complex`/`conjugate`/`from_polar_complex`/
`exp_complex` in `lib/complex.sv0`, `from_polar`/`scale_polar`/
`rotate_polar` in `lib/polar.sv0`, and `atan_f64_dd`'s negative-`x`
branch in `lib/trig.sv0`. (`mul_complex`/`div_complex` were already
written this way before this bug was even found — coincidentally safe,
not deliberately.)

**Part B — `requires`/`ensures` clauses themselves.** This is the part
that made the failure LOOK intermittent: `add_complex`'s own `ensures`
clause, `ensures(result.re == a.re + b.re && ...)`, has the SAME
field-combining binop, and it emits the SAME broken `int` temp:

```c
int _sv0t3 = (a.re + b.re);
int _sv0t4 = (result.re == _sv0t3);
```

— comparing a correctly-computed `double result.re` against an
`int`-truncated version of its own expected value. This ONLY panics
when the true (double-precision) sum isn't itself exactly equal to its
own integer truncation — which most random `f64` sums aren't, but
SOME coincidentally are (e.g. any sum that lands on a whole number),
which is why this read as flaky rather than deterministic at first.
Contract clauses can't use Part A's workaround (`requires`/`ensures`
are declared in the function SIGNATURE, before the body, with no access
to body-local variables) — fixed instead by moving the field-combining
expression into a small pure helper function (`complex_re_sum`,
`complex_im_diff`, `complex_neg_re`, etc., in `lib/complex.sv0`) and
calling THAT from the contract clause; a function call's return value
resolves its type correctly everywhere this was checked (unlike an
inline field-combining binop). `approx_eq`'s ensures AND its own
function body both had this shape (`abs_f64(a.re - b.re) <= epsilon`)
and were fixed the same way (`complex_re_close`/`complex_im_close`).

**What's confirmed SAFE (not overcorrected)**: a `let x: f64 = sa.hi *
sb.hi;` in a function BODY (an explicit-annotation `let`, bug #7's own
fix path) — unaffected; `ensures(result.r == p.r * k)` in
`scale_polar` (a single field combined with a plain PARAMETER, not
another field) — unaffected, confirmed via direct emitted-C inspection
(`double _sv0t2 = (p.r * k);`, correctly typed) before leaving it as
plain code. The trigger appears to need BOTH a struct-field-access
operand AND a context that lacks an explicit `let`-style type
annotation to fall back on (struct-literal init, or a contract clause) —
not fully root-caused inside `sv0c` itself; that's real, separate
`sv0-toolchain` work.

**Impact on this library**: significant, and specifically dangerous
because it's the kind of bug that reads as accuracy flakiness or a
false contract violation rather than an obvious compile error — every
one of `math::complex`'s componentwise arithmetic functions and their
own `ensures` clauses were affected, and would have silently (or
`ensures`-panic-ingly) shipped wrong behavior under a moving upstream
toolchain pin without `test/property/property_test.sv0` catching it —
TEST-001's own per-function unit tests, using fixed/typical inputs, did
NOT catch this (their sample points happened not to expose the
truncation), which is exactly the kind of gap SPEC.md's own property-
test layer (Section 16.2) exists to catch.

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
- **`abs_i64`/`sign_i64` (bug #1, now fixed)** — `int64_t` throughout
  (params, temps, the `requires`/`ensures` expressions), verified by
  running `abs_i64(9223372036854775807)` and its negation to exit 0, not
  just inspecting the C.
- **`let nan: f64 = 0.0 / 0.0;` (bug #7, now fixed)** — `main.sv0`'s NaN
  test case, previously worked around, now uses the natural pattern
  directly and compiles to `double nan;`, verified by running the full
  suite (exit 0).

## Not yet working

- **The SML `--target=vm` path** (`./scripts/sv0 vm-project-compile`) still
  cannot compile this library: (a) `abs_f64`'s `ensures(result >= 0.0)`
  fails to type-check on that path, and (b) `error[E0304]: duplicate type
  Option` once two files `use prelude::Option;` (SML-legacy inlines an
  imported type per importing file). **Both are moot** — the *native* VM
  path (`./scripts/sv0 vm-native-compile --project`, bug #2 status above)
  compiles + runs the whole library. SML-legacy is frozen and not planned
  to be extended.
- Struct and function generics (bug #3's fix is enum-only) — untested,
  presumed still broken.
- `let x: T = match { ... };` for a wide (non-i32/bool) `T` (bug #12, not
  fixed) — the match expression's own overall result temp is always
  `int`; use the match-as-statement workaround documented there instead.
- A `u64` literal near the top of its range flowing through a bare
  `Assign` temp (bug #1's residual, still not fixed — narrower than the
  original bug, not yet hit by anything in this library).
