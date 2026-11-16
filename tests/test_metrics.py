import json
from pathlib import Path

import pytest

from aiqa import metrics
from aiqa.cli import main as cli_main
from aiqa.contracts import InvalidInput


def per_feature(hits: list[int], size: int) -> list[tuple[str, bool]]:
    return [(f"f{i}", j < h) for i, h in enumerate(hits) for j in range(size)]


@pytest.mark.parametrize(
    ("x", "n", "upper"),
    [
        (0, 20, 0.1391),
        (1, 20, 0.2161),
        (2, 20, 0.2826),
        (0, 59, 0.0495),
        (5, 10, 0.7776),
    ],
)
def test_clopper_pearson_upper_matches_published_tables(x: int, n: int, upper: float):
    assert round(metrics.clopper_pearson_upper(x, n), 4) == upper
    assert metrics.clopper_pearson_upper(n, n) == 1.0
    assert metrics.clopper_pearson_upper(0, 20.0) == pytest.approx(1 - 0.05 ** (1 / 20))


@pytest.mark.parametrize(
    ("rate", "n", "lower"),
    [(0.9, 20, 0.7383), (1.0, 10, 0.7871), (1.0, 20, 0.8808), (0.75, 7, 0.4413)],
)
def test_wilson_lower_matches_hand_computation(rate: float, n: int, lower: float):
    assert round(metrics.wilson_lower(rate, n), 4) == lower


def test_the_bound_is_that_of_the_mean_of_the_feature_rates():
    est = metrics.detection(per_feature([3, 3, 3, 3, 0, 0, 3, 3], 3))
    assert (est.n, est.features, est.hits, est.rate, est.status) == (
        24,
        8,
        18,
        0.75,
        "OK",
    )
    assert (est.side, round(est.bound or 0, 4)) == (
        "lower",
        0.4602,
    )  # Wilson at n = 8 features, not 24 rows
    clean = metrics.detection([(f"f{i}", True) for i in range(10) for _ in range(2)])
    assert (clean.rate, round(clean.bound or 0, 4), clean.status) == (1.0, 0.7871, "OK")
    zero = metrics.false_pass(
        [(f"f{i}", "CORRECT") for i in range(8) for _ in range(100)]
    )
    assert (zero.n, round(zero.bound or 0, 4)) == (
        800,
        0.3123,
    )  # 800 correlated rows are 8 observations


def test_a_feature_with_many_rows_cannot_dominate():
    rows = [("big", True)] * 100 + [(f"f{i}", False) for i in range(7)]
    est = metrics.detection(rows)
    assert (est.n, est.hits, est.rate, round(est.bound or 0, 4)) == (
        107,
        100,
        0.125,
        0.0284,
    )
    assert metrics.detection([("a", True), ("a", False), ("a", True)]).features == 1


def test_one_more_miss_never_improves_a_bound():
    for hits, size in (
        ([10] * 8, 10),
        ([0] + [10] * 7, 10),
        ([100] * 7 + [0], 100),
        ([3] * 8, 3),
        ([5, 4, 3, 3, 3, 3, 3, 3], 5),
    ):
        for i, count in enumerate(hits):
            if count == 0:
                continue
            worse = [*hits[:i], count - 1, *hits[i + 1 :]]
            before, after = (
                metrics.detection(per_feature(hits, size)),
                metrics.detection(per_feature(worse, size)),
            )
            assert (after.bound or 0) <= (before.bound or 0), (hits, i)
            misses = [
                (f, "CORRECT" if h else "FALSE_PASS")
                for f, h in per_feature(hits, size)
            ]
            more = [
                (f, "CORRECT" if h else "FALSE_PASS")
                for f, h in per_feature(worse, size)
            ]
            assert (metrics.false_pass(misses).bound or 0) <= (
                metrics.false_pass(more).bound or 0
            ), (hits, i)


def test_below_the_minimum_counts_the_result_is_provisional():
    assert (
        metrics.detection(per_feature([1] * 7, 3)).status == "PROVISIONAL"
    )  # 7 features
    assert (
        metrics.detection(per_feature([1] * 8, 2)).status == "PROVISIONAL"
    )  # 16 mutants
    assert metrics.detection(per_feature([1] * 8, 3)).status == "OK"
    none = metrics.detection([])
    assert (none.rate, none.bound, none.status) == (
        None,
        None,
        "PROVISIONAL",
    )


def test_blocked_mutant_runs_are_excluded_and_counted():
    est = metrics.detection([("a", True), ("a", None), ("b", False)])
    assert (est.n, est.hits, est.excluded, est.rate) == (2, 1, 1, 0.5)


def test_false_pass_upper_bound_excludes_unsure_and_counts_it():
    clean = metrics.false_pass(
        [(f"f{i}", "CORRECT") for i in range(10) for _ in range(2)]
    )
    assert (clean.side, clean.hits, round(clean.bound or 0, 4), clean.status) == (
        "upper",
        0,
        0.2589,
        "OK",
    )
    verdicts = ["CORRECT"] * 3
    rows = [(f"f{i}", v) for i in range(8) for v in verdicts]
    rows[0], rows[5] = ("f0", "FALSE_PASS"), ("f1", "UNSURE")
    est = metrics.false_pass(rows)
    assert (est.n, est.hits, est.excluded, est.status) == (23, 1, 1, "OK")
    assert round(est.bound or 0, 4) == 0.37
    with pytest.raises(InvalidInput):
        metrics.false_pass([("a", "WRONG")])


def test_metrics_command_prints_each_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    summary = {
        "detection": [{"group": "ordering", "feature": "f", "detected": True}],
        "false_pass": [{"group": "p", "feature": "f", "verdict": "UNSURE"}],
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    assert cli_main(["metrics", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (
        out["detection"]["ordering"]["status"],
        out["false_pass"]["p"]["excluded"],
    ) == ("PROVISIONAL", 1)
    with pytest.raises(InvalidInput):
        metrics.detection([("a", 1)])
    ok = {"group": "g", "feature": "f", "detected": True}
    for bad in (
        {},
        {"detection": "", "false_pass": []},
        {"detection": {}, "false_pass": []},
        {"detection": [1], "false_pass": []},
        {"detection": [{**ok, "feature": 0}], "false_pass": []},
        {"detection": [{**ok, "feature": None}], "false_pass": []},
        {"detection": [{**ok, "group": " "}], "false_pass": []},
        {"detection": [{"group": "g", "feature": "f"}], "false_pass": []},
        {
            "detection": [],
            "false_pass": [{"group": "g", "feature": "f", "verdict": []}],
        },
    ):
        path.write_text(json.dumps(bad))
        capsys.readouterr()
        assert cli_main(["metrics", str(path)]) == 2, bad
        assert capsys.readouterr().out.strip(), bad  # a message, never a traceback
