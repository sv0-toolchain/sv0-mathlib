# `test/parity/` — cross-backend behavioral parity (COMPAT-001 / COMPAT-002 / TEST-005)

Every function in this library is Tier 1 (pure sv0 arithmetic), so SPEC §5.1
requires **identical results on the C backend and the VM backend**. That gate
was blocked for a long time because the VM toolchain path could not compile or
run floating-point code (`BUGS.md` #2). It no longer is: `sv0-toolchain`'s
`sv0c-vm-float-parity` work added f64 + i64/u64 to the native VM bytecode
emitter and to `sv0vm`.

There is **no separate fixture set here** — the parity check runs the *whole
library* through both backends and compares. `scripts/ci` (no `--skip-parity`)
invokes the toolchain's harness:

```bash
python3 "$SV0_TOOLCHAIN_ROOT/scripts/vm_behavioral_parity.py"
```

That harness reads `sv0c/test/vm-parity/behavioral-manifest.txt` in the
toolchain, whose entries include `--project ../sv0-mathlib` (this checkout, as
the documented sibling layout — README deviation #10). For each entry it:

1. emits C (`build/sv0-megatu-native`) → compiles → runs → records exit code;
2. emits `.sv0b` (`build/sv0-megatu-vm-native`) → runs on `sv0vm` → records exit code;
3. asserts the two exit codes match.

`main.sv0` is the ARITH-001 test binary (0 = pass, nonzero = first failing case
index), so an exit-code match is a per-case result match across the two
backends. Running it by hand:

```bash
# from the sv0-toolchain checkout
./scripts/sv0 vm-native-compile --project ../sv0-mathlib /tmp/mathlib.sv0b
./scripts/sv0 vm-run /tmp/mathlib.sv0b            # expect vm_exit:0
build/sv0-megatu-native --project ../sv0-mathlib > /tmp/mathlib.c
cc -std=c99 -O0 -w -I sv0c/runtime /tmp/mathlib.c sv0c/runtime/sv0_runtime.c -o /tmp/mathlib_c
/tmp/mathlib_c; echo $?                            # expect 0
```

## What's covered vs. what isn't

- **Covered:** the full library compiles and runs on the VM; every `main.sv0`
  self-test case (F0 abs/sign/min/max/clamp for i32/i64/f64, `_checked`
  companions, the prelude `Option`/`Result`) produces the same result on both
  backends. The toolchain manifest also runs standalone f64/i64 fixtures
  (`vmf_f64_*`, `vmf_i64_arith`) exercising the arithmetic/comparison/struct/
  contract paths.
- **Not yet a bit/ULP-for-ULP fixture-table diff.** SPEC §16.2's per-fixture
  cross-backend diff over `test/fixtures/{rounding,trig}.csv` still runs on the
  C backend only (`docs/ulp_audit_harness.c`). Extending that harness to also
  run each fixture through `sv0vm` and ULP-compare is the remaining refinement;
  the exit-code parity above already establishes that the two backends agree on
  every self-test the library ships.
