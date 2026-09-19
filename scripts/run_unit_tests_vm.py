#!/usr/bin/env python3
"""Runs every test/unit/*.sv0 and test/property/*.sv0 program on the C
backend AND the VM backend and compares exit codes. scripts/run_unit_tests.py
already gates the C backend; this adds the cross-backend surface that
`vm_behavioral_parity.py` (whole-library main only) never reached, so
modules like `random` and `stats` are checked on the VM too.

The VM leg is advisory by default, for the same reason as
run_fixture_parity.py's (an intermittent, still-unexplained sv0vm
divergence; BUGS.md "Per-fixture value check"). Pass --strict-vm to make a
VM miss fail the run. A C-backend failure or a C/VM disagreement is always
reported; only the VM leg's own failures are advisory.

Usage: python3 scripts/run_unit_tests_vm.py [--toolchain-root DIR] [--strict-vm]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import run_fixture_parity as rfp  # noqa: E402 -- reuse its C and VM runners


# Test programs whose VM run is known to diverge from the C backend, with the
# BUGS.md entry that explains it. They are reported as KNOWN, not WARN, and
# never fail the run; but if one starts passing on the VM the run FAILS until
# it is removed here, so this list cannot go stale.
KNOWN_VM_DIVERGENCE = {
    "unit/complex_test.sv0": "BUGS.md #22 (ln_complex aborts the VM in a small program)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain-root", type=Path,
                    default=Path(os.environ.get("SV0_TOOLCHAIN_ROOT")
                                 or (HERE.parent if (HERE.parent / "sv0c").is_dir()
                                     else HERE.parent / "sv0-toolchain")))
    ap.add_argument("--strict-vm", action="store_true")
    args = ap.parse_args()

    files = sorted((HERE / "test" / "unit").glob("*.sv0")) + \
        sorted((HERE / "test" / "property").glob("*.sv0"))
    hard_fail = False
    vm_miss = False
    for f in files:
        with tempfile.TemporaryDirectory(prefix="sv0mathlib_unitvm_") as tmp:
            project = rfp.stage_project(f.read_text(encoding="utf-8"), Path(tmp))
            c_exit, c_out = rfp.run_c(project, args.toolchain_root)
            v_exit, v_out = rfp.run_vm(project, args.toolchain_root)
        tag = f"{f.parent.name}/{f.name}"
        if c_exit != 0:
            print(f"run_unit_tests_vm: {tag}: FAIL on C backend (exit {c_exit}) {c_out[-200:]}",
                  file=sys.stderr)
            hard_fail = True
        elif tag in KNOWN_VM_DIVERGENCE:
            if v_exit == 0:
                print(f"run_unit_tests_vm: {tag}: now PASSES on the VM — remove it from "
                      f"KNOWN_VM_DIVERGENCE ({KNOWN_VM_DIVERGENCE[tag]})", file=sys.stderr)
                hard_fail = True
            else:
                print(f"run_unit_tests_vm: {tag}: KNOWN VM divergence — {KNOWN_VM_DIVERGENCE[tag]} "
                      f"(VM exit {v_exit})")
        elif v_exit == 0:
            print(f"run_unit_tests_vm: {tag}: PASS (C and VM agree)")
        else:
            vm_miss = True
            kind = "FAIL" if args.strict_vm else "WARN (advisory)"
            print(f"run_unit_tests_vm: {tag}: {kind} — C exit 0 but VM exit {v_exit}: "
                  f"{str(v_out)[-200:]}", file=sys.stderr)

    if hard_fail or (vm_miss and args.strict_vm):
        print("run_unit_tests_vm: FAIL", file=sys.stderr)
        return 1
    print("run_unit_tests_vm: PASS" + (" (with advisory VM warnings)" if vm_miss else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
