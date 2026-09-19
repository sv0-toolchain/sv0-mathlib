#!/usr/bin/env python3
"""Fixture provenance gate. Regenerates each oracle-produced fixture and
fails if the checked-in CSV differs:

  test/fixtures/random.csv  <- docs/random_oracle.c (compiled with cc; plain
                               uint64_t arithmetic, deterministic)
  test/fixtures/stats.csv   <- scripts/gen_stats_fixtures.py (exact rational
                               arithmetic, platform independent)

No sv0 toolchain needed. To refresh after an intentional change:
  cc -std=c99 -O0 docs/random_oracle.c -o /tmp/random_oracle && /tmp/random_oracle > test/fixtures/random.csv
  python3 scripts/gen_stats_fixtures.py > test/fixtures/stats.csv
Exit 0 = all match; 1 = drift; 2 = an oracle failed to build/run."""

from __future__ import annotations

import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIXTURES = HERE / "test" / "fixtures"


def oracle_random() -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="sv0mathlib_randoracle_") as tmp:
        exe = Path(tmp) / "random_oracle"
        cc = subprocess.run(["cc", "-std=c99", "-O0", "-w", str(HERE / "docs" / "random_oracle.c"),
                             "-o", str(exe)], capture_output=True, text=True)
        if cc.returncode != 0:
            return 2, "", f"oracle failed to compile:\n{cc.stderr}"
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        return run.returncode, run.stdout, run.stderr


def oracle_stats() -> tuple[int, str, str]:
    run = subprocess.run([sys.executable, str(HERE / "scripts" / "gen_stats_fixtures.py")],
                         capture_output=True, text=True)
    return run.returncode, run.stdout, run.stderr


def main() -> int:
    worst = 0
    for name, oracle in (("random.csv", oracle_random), ("stats.csv", oracle_stats)):
        rc, out, err = oracle()
        if rc != 0:
            print(f"check_fixture_oracles: {name}: oracle exited {rc}:\n{err}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        want = (FIXTURES / name).read_text(encoding="utf-8")
        if out == want:
            print(f"check_fixture_oracles: {name}: PASS ({want.count(chr(10)) - 1} rows match its oracle)")
            continue
        diff = difflib.unified_diff(want.splitlines(), out.splitlines(),
                                    f"test/fixtures/{name}", "oracle output", lineterm="")
        print(f"check_fixture_oracles: {name}: FAIL — drifted from its oracle:", file=sys.stderr)
        print("\n".join(list(diff)[:40]), file=sys.stderr)
        worst = max(worst, 1)
    if worst == 0:
        print("check_fixture_oracles: PASS")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
