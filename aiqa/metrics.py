"""Seeded-defect detection and verdict false-PASS with clustered one-sided 95 % bounds (AQP-1 P13b; design 07 "Metric definitions").

The sampling unit is the feature: each feature contributes its own rate (hits / rows) with equal weight, and the bound is a Wilson
score lower bound (detection) or a Clopper-Pearson upper bound (false-PASS; beta quantile, fractional counts allowed) on the mean of
those feature rates with n = number of features. Rows of one feature are correlated, so they never count as independent evidence and a
feature with many rows cannot dominate; the bound is monotone in every feature's rate (one more miss or FALSE_PASS never improves it).
Below the minimum counts the numbers are still shown but the status is PROVISIONAL and gates must not use them."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from .contracts import InvalidInput, load_json

Z95 = 1.6448536269514722  # standard normal quantile of 0.95 (one-sided 95 %)
MIN_FEATURES, MIN_N = 8, 20  # design 07 defaults, to be re-fixed after epoch 1
VERDICTS = {"CORRECT", "FALSE_PASS", "UNSURE"}


@dataclass(frozen=True)
class Estimate:
    side: str  # "lower" (detection) or "upper" (false-PASS)
    n: int
    features: int
    hits: int
    excluded: int  # BLOCKED mutant runs, UNSURE adjudications: counted, never in n
    rate: float | None  # mean of the feature rates
    bound: float | None
    status: str  # "OK" or "PROVISIONAL"


def _betacf(
    x: float, a: float, b: float
) -> float:  # Lentz continued fraction of the incomplete beta
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        for num in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            d = 1 / (d * num + 1 if abs(d * num + 1) > tiny else tiny)
            c = 1 + num / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0 or x >= 1:
        return float(x >= 1)
    if x > (a + 1) / (a + b + 2):
        return 1 - beta_cdf(1 - x, b, a)
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )  # fmt: skip
    return math.exp(log_front) * _betacf(x, a, b) / a


def wilson_lower(rate: float, n: float) -> float:
    z2 = Z95 * Z95
    spread = Z95 * math.sqrt(rate * (1 - rate) / n + z2 / (4 * n * n))
    return (rate + z2 / (2 * n) - spread) / (1 + z2 / n)


def clopper_pearson_upper(x: float, n: float) -> float:
    if x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):  # the 95 % point of Beta(x + 1, n - x), found by bisection
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if beta_cdf(mid, x + 1, n - x) < 0.95 else (lo, mid)
    return (lo + hi) / 2


def _estimate(side: str, rows: list[tuple[str, int]], excluded: int) -> Estimate:
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for feature, hit in rows:
        per[feature][0] += hit
        per[feature][1] += 1
    n, features = len(rows), len(per)
    status = "OK" if features >= MIN_FEATURES and n >= MIN_N else "PROVISIONAL"
    if not n:
        return Estimate(side, 0, 0, 0, excluded, None, None, status)
    mean = sum(h / m for h, m in per.values()) / features
    bound = (
        wilson_lower(mean, features)
        if side == "lower"
        else clopper_pearson_upper(mean * features, features)
    )
    return Estimate(
        side,
        n,
        features,
        sum(h for h, _ in per.values()),
        excluded,
        mean,
        bound,
        status,
    )


def detection(rows: Iterable[tuple[str, object]]) -> Estimate:
    """Per validated mutant: (feature, detected); None marks a BLOCKED run, excluded and counted."""
    given = list(rows)
    if any(d is not None and not isinstance(d, bool) for _, d in given):
        raise InvalidInput("Detection rows need true, false or null")
    kept = [(f, int(d is True)) for f, d in given if d is not None]
    return _estimate("lower", kept, len(given) - len(kept))


def false_pass(rows: Iterable[tuple[str, object]]) -> Estimate:
    """Per owner-adjudicated sampled PASS: (feature, verdict); UNSURE is excluded and counted."""
    given = list(rows)
    if bad := [v for _, v in given if not isinstance(v, str) or v not in VERDICTS]:
        raise InvalidInput(f"Unknown verdict {bad[0]!r}")
    kept = [(f, int(v == "FALSE_PASS")) for f, v in given if v != "UNSURE"]
    return _estimate("upper", kept, len(given) - len(kept))


def add_arguments(commands: Any) -> None:
    cmd = commands.add_parser("metrics")
    cmd.add_argument(
        "summary",
        type=Path,
        help="JSON from `qa_ledger.py audit summary`: detection and false_pass rows",
    )


def _grouped(rows: object, key: str) -> dict[str, list[Any]]:
    if not isinstance(rows, list):
        raise InvalidInput("Unusable audit summary: rows must be a list")
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in cast(list[object], rows):
        if not isinstance(row, dict):
            raise InvalidInput("Unusable audit summary: a row is not an object")
        fields = cast(dict[str, object], row)
        group, feature = fields["group"], fields["feature"]
        if not all(isinstance(v, str) and v.strip() for v in (group, feature)):
            raise InvalidInput("Unusable audit summary: group and feature are text")
        grouped[cast(str, group)].append((cast(str, feature), fields[key]))
    return grouped


def run(args: argparse.Namespace) -> int:
    doc: Any = load_json(args.summary)
    try:
        groups = {
            name: _grouped(doc[name], key)
            for name, key in (("detection", "detected"), ("false_pass", "verdict"))
        }
    except (KeyError, TypeError, AttributeError) as e:
        raise InvalidInput(f"Unusable audit summary: {e!r}") from None
    out = {
        "detection": {g: asdict(detection(r)) for g, r in groups["detection"].items()},
        "false_pass": {
            g: asdict(false_pass(r)) for g, r in groups["false_pass"].items()
        },
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0
