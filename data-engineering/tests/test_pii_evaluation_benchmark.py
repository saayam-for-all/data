"""Tests for evaluation metrics, cost estimates, the benchmark and Lambda constraints."""

import ast
import sys
from pathlib import Path

import pytest

import scripts.benchmark_pii_detection as benchmark
from src.pii_evaluation.costs import comprehend_monthly_cost, comprehend_units, lambda_compute_cost
from src.pii_evaluation.dataset import GoldEntity, LabeledRequest
from src.pii_evaluation.metrics import (
    document_metrics,
    entity_metrics,
    latency_summary,
    percentile,
)
from src.pii_evaluation.spans import Span

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "pii_evaluation"


class AlwaysEmptyComprehend:
    """Fake Comprehend client that finds nothing and counts calls."""

    def __init__(self):
        self.calls = 0

    def detect_pii_entities(self, *, Text, LanguageCode):
        self.calls += 1
        return {"Entities": []}


# ------------------------------------------------------------------ metrics

def test_document_metrics_counts_and_rates():
    metrics = document_metrics([True, True, True, False, False], [True, True, False, True, False])

    assert (metrics.true_positive, metrics.false_negative) == (2, 1)
    assert (metrics.false_positive, metrics.true_negative) == (1, 1)
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.f1 == pytest.approx(2 / 3)
    assert metrics.specificity == pytest.approx(0.5)
    assert metrics.as_dict()["clean_texts_wrongly_redacted"] == 1


def test_document_metrics_undefined_rates_are_none():
    metrics = document_metrics([False, False], [False, False])

    assert metrics.precision is None and metrics.recall is None and metrics.f1 is None
    with pytest.raises(ValueError):
        document_metrics([True], [])


def test_entity_metrics_overlap_full_coverage_and_spurious_spans():
    request = LabeledRequest(
        id="R1", text="Ana Silva 202-555-0147", contains_pii=True, language="en",
        entities=(GoldEntity("PERSON", 0, 9, "Ana Silva", True),
                  GoldEntity("PHONE", 10, 22, "202-555-0147")),
    )
    predictions = {"R1": [Span(0, 3, "PERSON"), Span(10, 22, "PHONE"), Span(4, 6, "OTHER")]}
    result = entity_metrics([request], predictions)

    assert result["detected"] == 2 and result["fully_redacted"] == 1
    assert result["predicted_spans"] == 3 and result["spurious_spans"] == 0
    assert result["per_type"]["PERSON"]["fully_redacted"] == 0
    assert result["person_by_users_table_membership"]["in_users_table"]["detected"] == 1

    spurious = entity_metrics([request], {"R1": [Span(9, 10, "OTHER")]})
    assert spurious["spurious_spans"] == 1 and spurious["detected"] == 0


def test_percentile_and_latency_summary():
    values = list(range(1, 21))

    assert percentile(values, 0.95) == 19
    assert percentile([7], 0.95) == 7
    summary = latency_summary([1_000, 2_000, 3_000])
    assert summary["median_us"] == 2.0 and summary["mean_us"] == 2.0 and summary["samples"] == 3
    with pytest.raises(ValueError):
        latency_summary([])
    with pytest.raises(ValueError):
        percentile(values, 0)


# ------------------------------------------------------------------ costs

def test_comprehend_units_apply_the_three_unit_minimum():
    assert comprehend_units(0) == 3
    assert comprehend_units(300) == 3
    assert comprehend_units(301) == 4
    with pytest.raises(ValueError):
        comprehend_units(-1)


def test_comprehend_monthly_cost_and_split_calls():
    assert comprehend_monthly_cost([120, 80], 1_000) == pytest.approx(0.30)
    assert comprehend_monthly_cost([120, 80], 1_000, calls_per_request=2) == pytest.approx(0.60)
    assert comprehend_monthly_cost([450], 10_000) == pytest.approx(5.00)
    with pytest.raises(ValueError):
        comprehend_monthly_cost([], 10)


def test_lambda_compute_cost():
    assert lambda_compute_cost(1.0, 1_024, memory_mb=1024) == pytest.approx(1_024 * 0.0000166667)
    with pytest.raises(ValueError):
        lambda_compute_cost(-1, 10)


# ------------------------------------------------------------------ benchmark

def _small_run(**kwargs):
    return benchmark.run(benchmark.DEFAULT_DATASET, benchmark.DEFAULT_USERS, repeat=1, warmup=0,
                         scale_sizes=[200], seed=1, **kwargs)


def test_benchmark_reports_comprehend_as_not_measured_without_a_client():
    results = _small_run(comprehend_status={"boto3_installed": False, "credentials_found": False,
                                            "reason": "test"})

    assert results["approaches"]["C"]["status"] == "NOT MEASURED"
    assert "document" not in results["approaches"]["C"]
    assert results["baseline_equivalence"]["mismatched_ids"] == []


def test_benchmark_runs_every_approach_on_the_same_texts():
    results = _small_run()
    texts = results["dataset"]["texts"]

    for key in ("A", "B_full", "B_token", "D"):
        data = results["approaches"][key]
        document = data["document"]
        assert sum(document[k] for k in ("true_positive", "false_negative",
                                         "false_positive", "true_negative")) == texts
        assert data["latency"]["samples"] == texts
        assert set(data["redacted"]) == {f"{p}{n:02d}" for p, n in
                                         [("C", i) for i in range(1, 28)] + [("P", i) for i in range(1, 48)]}


def test_benchmark_accuracy_is_reproducible():
    first, second = _small_run(), _small_run()
    for key in ("A", "B_full", "B_token", "D"):
        assert first["approaches"][key]["document"] == second["approaches"][key]["document"]
        assert first["approaches"][key]["redacted"] == second["approaches"][key]["redacted"]


def test_benchmark_with_fake_comprehend_client_counts_calls():
    client = AlwaysEmptyComprehend()
    results = _small_run(comprehend_client=client)
    texts = results["dataset"]["texts"]

    assert results["approaches"]["C"]["status"] == "MEASURED"
    assert results["approaches"]["C"]["comprehend_calls"] == client.calls == 2 * texts
    assert (results["approaches"]["C"]["document"]["true_positive"]
            == results["approaches"]["A"]["document"]["true_positive"])


def test_benchmark_external_dataset_is_scored_at_document_level(tmp_path):
    external = tmp_path / "external.jsonl"
    external.write_text('{"id": "E1", "text": "Call 202-555-0147", "contains_pii": true}\n'
                        '{"id": "E2", "text": "We need blankets", "contains_pii": false}\n',
                        encoding="utf-8")
    results = _small_run(external_path=external)
    document = results["external_binary_evaluation"]["approaches"]["A"]["document"]

    assert (document["true_positive"], document["true_negative"]) == (1, 1)


def test_cli_refuses_comprehend_without_billing_approval(capsys):
    with pytest.raises(SystemExit) as exit_info:
        benchmark.main(["--comprehend"])
    assert exit_info.value.code == 2
    assert "billable" in capsys.readouterr().err


def test_cli_writes_json_report(tmp_path):
    output = tmp_path / "results.json"

    assert benchmark.main(["--repeat", "1", "--warmup", "0", "--scale-sizes", "100",
                           "--output", str(output)]) == 0
    assert '"NOT MEASURED"' in output.read_text(encoding="utf-8")


# ------------------------------------------------------------------ Lambda constraints

def _top_level_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_detection_modules_import_only_the_standard_library():
    for path in PACKAGE_DIR.glob("*.py"):
        for name in _top_level_imports(path):
            root = name.split(".")[0]
            assert root in sys.stdlib_module_names or name.startswith("src.pii_evaluation") \
                or root == "__future__", f"{path.name} imports {name}"


def test_boto3_is_only_imported_inside_functions():
    for path in PACKAGE_DIR.glob("*.py"):
        assert "boto3" not in _top_level_imports(path)


def test_detection_package_is_small_enough_for_lambda():
    total_bytes = sum(path.stat().st_size for path in PACKAGE_DIR.glob("*.py"))
    assert total_bytes < 200_000
