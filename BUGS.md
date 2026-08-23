# Toolchain bugs found while starting sv0-mathlib

Filed here first (this repo has no upstream tracker yet); each should become
a real `sv0-toolchain`/`sv0c` issue. Audited against sv0-toolchain HEAD
`840fe73` / sv0c HEAD `0705d68` (2026-08-23). **Bugs #5, #3, #1, #7, and #8
are fixed** (f64 miscompiling as `int`; generic enums failing to resolve;
integer literals wider than i32 truncating; `let`-annotations over a
non-call/struct/enum RHS ignored; enum payload slots always `int`). Bugs
#2, #6, and #9 are not fixed.

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
- Struct and function generics (bug #3's fix is enum-only) — untested,
  presumed still broken.
- `abs_checked_i64` (bug #8, not fixed) — enum payload slots are always a
  32-bit `int`; a `u64` literal near the top of its range flowing through a
  bare `Assign` temp (bug #1's residual) — neither is fixed.
