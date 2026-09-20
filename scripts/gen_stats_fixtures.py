#!/usr/bin/env python3
"""Independent oracle for lib/stats.sv0: prints test/fixtures/stats.csv.

Independent on purpose: the sv0 code is a one-pass Welford/Neumaier
accumulator in f64. This oracle computes every finite-data result in EXACT
rational arithmetic (`fractions.Fraction` over the exact binary value of
each input double) and rounds once at the end, so it is correct to the
last bit and identical on every platform (a C `long double` oracle is not:
it is plain `double` on arm64 macOS). Two-pass variance (exact mean, then
exact squared deviations).

The order statistics (median, percentile) sort the exact values and
interpolate exactly. Non-finite data follows the module's documented policy
rather than an independent algorithm: a NaN makes everything NaN;
infinities give IEEE-style sum/mean/min/max, variance NaN, and the same
`lo*(1-f) + hi*f` interpolation the module uses for the order statistics.

`scripts/check_fixture_oracles.py` fails CI if the checked-in CSV drifts
from this script's output. To refresh after an intentional change:
  python3 scripts/gen_stats_fixtures.py > test/fixtures/stats.csv
"""

from __future__ import annotations

import math
import sys
from fractions import Fraction

EPS = 2.0 ** -52

COUNT, SUM, MEAN, VARP, VARS, SDP, SDS, MIN, MAX, RANGE, ORDER = (1 << i for i in range(11))
ALL = (1 << 11) - 1
PERCENTILES = (0, 25, 90, 100)

# (data tokens, function mask, category, notes) -- notes must not contain commas
SETS = [
    ("", ALL, "boundary", "empty: count 0; sum 0.0; everything else NaN"),
    ("5.0", ALL, "boundary", "one observation: sample variance undefined"),
    ("2.0 4.0 9.0", ALL, "typical", "mean 5; squared deviations sum to 26"),
    ("2.0 4.0 4.0 4.0 5.0 5.0 7.0 9.0", ALL, "typical", "classic set: population variance 4; stddev 2"),
    ("10000000000000000.0 1.0 -10000000000000000.0", COUNT | SUM | MIN | MAX | RANGE, "cancellation",
     "naive summation loses the 1.0; Neumaier keeps it"),
    ("1000000004.0 1000000007.0 1000000013.0 1000000016.0", ALL, "stability",
     "large common offset must not destroy the variance"),
    ("-3.5 -1.25 0.0 2.75 8.0 -0.5", ALL, "typical", "mixed signs"),
    ("0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1.0", ALL, "typical",
     "decimal fractions; none exactly representable"),
    ("7.0 7.0 7.0 7.0", ALL, "boundary", "constant data: variance exactly 0"),
    (" ".join(f"{i}.0" for i in range(1, 21)), ALL, "typical", "1 through 20"),
    ("1.0 nan 3.0", ALL, "nan", "a NaN makes every result NaN"),
    ("nan 1.0", ALL, "nan", "NaN first"),
    ("1.0 inf", ALL, "infinity", "sum/mean/max are +Infinity; variance NaN"),
    ("inf 1.0", ALL, "infinity", "infinity first"),
    ("1.0 -inf", ALL, "infinity", "sum/mean/min are -Infinity; variance NaN"),
    ("inf -inf", ALL, "infinity", "both signs: sum and mean NaN"),
]

NAN = float("nan")


def parse(tok: str) -> float:
    return float(tok)  # accepts nan / inf / -inf and decimal literals


def fmt(v: float) -> str:
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    text = repr(v)
    if "e" in text or "E" in text:
        if abs(v) < 1.0:
            raise SystemExit(f"gen_stats_fixtures: cannot print {v!r} without an exponent")
        text = "%.1f" % v
    if "." not in text:
        text += ".0"
    return text


def order_stat(xs: list[float], p: float | None) -> tuple[float, float]:
    """(value, scale): the median (p is None) or the p-th percentile of xs,
    and the magnitude the tolerance is relative to (max(|lo|, |hi|) of the two
    values it interpolates)."""
    n = len(xs)
    if n == 0 or any(math.isnan(x) for x in xs) or (p is not None and math.isnan(p)):
        return NAN, 0.0
    finite = all(math.isfinite(x) for x in xs)
    fx = sorted(xs)
    if p is None:
        mid = n // 2
        if n % 2 == 1:
            return fx[mid], abs(fx[mid])
        lo, hi = fx[mid - 1], fx[mid]
        scale = max(abs(lo), abs(hi))
        if finite:
            return float((Fraction(lo) + Fraction(hi)) / 2), scale
        return lo * 0.5 + hi * 0.5, scale
    pos = Fraction(p) * (n - 1) / 100
    k = pos.numerator // pos.denominator
    if k >= n - 1:
        return fx[n - 1], abs(fx[n - 1])
    frac = pos - k
    lo, hi = fx[k], fx[k + 1]
    scale = max(abs(lo), abs(hi))
    if frac == 0:
        return lo, abs(lo)
    if finite:
        return float(Fraction(lo) + frac * (Fraction(hi) - Fraction(lo))), scale
    f = float(frac)
    return lo * (1.0 - f) + hi * f, scale


def results(xs: list[float]) -> dict[str, float]:
    n = len(xs)
    out: dict[str, float] = {}
    if n == 0:
        return {"sum": 0.0, "mean": NAN, "varp": NAN, "vars": NAN, "min": NAN, "max": NAN, "range": NAN}
    if any(math.isnan(x) for x in xs):
        return {k: NAN for k in ("sum", "mean", "varp", "vars", "min", "max", "range")}
    lo, hi = min(xs), max(xs)
    if any(math.isinf(x) for x in xs):
        s = math.fsum(xs) if not (any(x == math.inf for x in xs) and any(x == -math.inf for x in xs)) else NAN
        mean = s / n if not math.isnan(s) else NAN
        return {"sum": s, "mean": mean, "varp": NAN, "vars": NAN, "min": lo, "max": hi,
                "range": hi - lo if not (math.isinf(hi) and math.isinf(lo) and hi == lo) else NAN}
    fx = [Fraction(x) for x in xs]
    total = sum(fx, Fraction(0))
    mean = total / n
    ss = sum(((x - mean) ** 2 for x in fx), Fraction(0))
    out["sum"] = float(total)
    out["mean"] = float(mean)
    out["varp"] = float(ss / n)
    out["vars"] = float(ss / (n - 1)) if n >= 2 else NAN
    out["min"], out["max"] = lo, hi
    out["range"] = float(Fraction(hi) - Fraction(lo))
    return out


def main() -> int:
    w = sys.stdout.write
    w("function,data,param,expected,tolerance,category,notes\n")
    for data, mask, category, notes in SETS:
        xs = [parse(t) for t in data.split()]
        r = results(xs)
        rows = [
            (COUNT, "stats_count", None, True),
            (SUM, "stats_sum_f64", r["sum"], False),
            (MEAN, "stats_mean_f64", r["mean"], False),
            (VARP, "stats_variance_pop_f64", r["varp"], False),
            (VARS, "stats_variance_sample_f64", r["vars"], False),
            (SDP, "stats_stddev_pop_f64", math.sqrt(r["varp"]) if not math.isnan(r["varp"]) else NAN, False),
            (SDS, "stats_stddev_sample_f64", math.sqrt(r["vars"]) if not math.isnan(r["vars"]) else NAN, False),
            (MIN, "stats_min_f64", r["min"], True),
            (MAX, "stats_max_f64", r["max"], True),
            (RANGE, "stats_range_f64", r["range"], True),
        ]
        for bit, fn, expected, exact in rows:
            if not mask & bit:
                continue
            if fn == "stats_count":
                w(f"{fn},{data},,{len(xs)},0.0,{category},{notes}\n")
                continue
            tol = 0.0 if exact else 8.0 * EPS * abs(expected)
            tol_s = "0.0" if (math.isnan(expected) or math.isinf(expected) or tol == 0.0) else "%.30f" % tol
            w(f"{fn},{data},,{fmt(expected)},{tol_s},{category},{notes}\n")
        if mask & ORDER:
            cases = [("stats_median_f64", None)] + [("stats_percentile_f64", float(p)) for p in PERCENTILES]
            for fn, p in cases:
                expected, scale = order_stat(xs, p)
                tol = 8.0 * EPS * scale
                exact = math.isnan(expected) or math.isinf(expected) or not math.isfinite(tol) or tol == 0.0
                tol_s = "0.0" if exact else "%.30f" % tol
                param = "" if p is None else fmt(p)
                w(f"{fn},{data},{param},{fmt(expected)},{tol_s},{category},{notes}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
