#!/usr/bin/env python3
"""DOC-001 (F0): "Every public function SHALL have a doc comment stating
its domain, its exact contract in prose, and (for non-exact functions) a
cross-reference to its docs/accuracy.md row." Verification: "Doc-comment
coverage lint" — this script.

Convention this lints: a "doc comment" for `fn NAME(...)` is a `/* ... */`
block comment whose closing `*/` is on the line immediately above the
`fn` line (blank lines allowed in between, code is not). This mirrors
how every function in lib/*.sv0 is already written. A doc comment must
be at least MIN_DOC_CHARS characters (a proxy for "real content," not a
one-line placeholder) to count.

"Public" here means every top-level `fn` in lib/*.sv0 EXCEPT the
`_dd`-suffixed double-double internal helpers (documented in trig.sv0's
own header as NOT public API — see e.g. ln_f64_dd's own comment) and a
short EXCLUDE list of other genuinely-internal helpers (also not
reachable/meaningful as a public API surface on their own).

NON_EXACT_FUNCTIONS (must additionally reference "accuracy.md" in their
own doc comment): every function docs/accuracy.md has a row for.

Usage: python3 scripts/check_doc_comments.py
Exit 0 = every public function has a qualifying doc comment, and every
non-exact one cross-references docs/accuracy.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LIB = HERE / "lib"

MIN_DOC_CHARS = 40

# Internal, not part of this library's public API surface (documented as
# such at their own declaration site) -- DOC-001 doesn't apply to these
# the way it applies to a function meant to be `use`d from outside its
# own module.
INTERNAL_HELPERS = {
    # double-double internal machinery (trig.sv0's own header note)
    "ln_f64_dd", "atan_f64_dd", "sin_poly_dd", "cos_poly_dd",
    "atan_small_series_dd", "trig_apply_quadrant_dd",
    "trig_reduce_2pi", "trig_fold_quadrant",
    "sqrt_bracket_guess", "sqrt_error_bound",
    "dekker_split", "two_prod", "two_sum",
    "frac_floor_of_nonneg",
    "complex_re_sum", "complex_im_sum", "complex_re_diff", "complex_im_diff",
    "complex_neg_re", "complex_neg_im", "complex_neg_im_of",
    "complex_re_close", "complex_im_close",
    "identity_pair",
}

# docs/accuracy.md's own measured-function set (its Measurements table).
NON_EXACT_FUNCTIONS = {
    "sqrt_f64", "sin_f64", "cos_f64", "tan_f64",
    "asin_f64", "acos_f64", "atan_f64", "atan2_f64",
    "exp_f64", "ln_f64",
    "sinh_f64", "cosh_f64", "tanh_f64", "hypot_f64",
    "exp_complex", "ln_complex", "pow_complex",
}

FN_RE = re.compile(r"^fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def find_functions(path: Path) -> list[tuple[str, int]]:
    """Returns [(name, line_number_1_based), ...] for top-level fn decls."""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        m = FN_RE.match(line)
        if m:
            out.append((m.group(1), i))
    return out


def doc_comment_above(lines: list[str], fn_line_idx0: int) -> str | None:
    """fn_line_idx0 is 0-based index of the `fn` line. Walk upward past
    blank lines; if we land on a line ending `*/`, walk further upward
    to the matching `/*` and return the joined text. Otherwise None."""
    i = fn_line_idx0 - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i < 0 or not lines[i].rstrip().endswith("*/"):
        return None
    end = i
    while i >= 0 and "/*" not in lines[i]:
        i -= 1
    if i < 0:
        return None
    start = i
    return "\n".join(lines[start:end + 1])


def main() -> int:
    problems: list[str] = []
    checked = 0

    for path in sorted(LIB.glob("*.sv0")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for name, lineno in find_functions(path):
            if name in INTERNAL_HELPERS:
                continue
            checked += 1
            doc = doc_comment_above(lines, lineno - 1)
            rel = path.relative_to(HERE)
            if doc is None:
                problems.append(f"{rel}:{lineno}: `{name}` has no doc comment directly above it")
                continue
            if len(doc) < MIN_DOC_CHARS:
                problems.append(f"{rel}:{lineno}: `{name}`'s doc comment is too short ({len(doc)} chars < {MIN_DOC_CHARS})")
                continue
            if name in NON_EXACT_FUNCTIONS and "accuracy.md" not in doc:
                problems.append(f"{rel}:{lineno}: `{name}` is non-exact (docs/accuracy.md row exists) but its doc comment doesn't reference accuracy.md")

    if problems:
        print(f"check_doc_comments: {len(problems)} problem(s) across {checked} checked functions:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"check_doc_comments: PASS ({checked} public functions, all with qualifying doc comments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
