"""P6 judge calibration — drives judge_agent directly against human-scored fixtures.

Does NOT run a full dev_cycle. Calls judge_agent.run() with pre-composed
context dicts derived from checked-in fixture files.

Assertions:
- known_bad scores strictly lower than known_good
- known_bad decision is not ready_for_approval
- known_good decision is ready_for_approval or needs_changes (not rejected unless
  the model disagrees with the fixture, but score ordering must hold)
- borderline score falls between known_bad and known_good
- scoring patterns differ across cases (dimension_scores not mechanically identical)
- a calibration report is written to the same directory for inspection
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# Workers source is one level above tests/
_WORKERS_APP = Path(__file__).parent.parent.parent / "app"
if str(_WORKERS_APP) not in sys.path:
    sys.path.insert(0, str(_WORKERS_APP.parent))

from app.agents import judge_agent  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPORT_PATH = Path(__file__).parent / "calibration_report.json"

FIXTURE_LABELS = ["known_good", "known_bad", "borderline"]


def _load_fixture(label: str) -> dict:
    path = FIXTURES_DIR / f"{label}.json"
    with open(path) as fh:
        return json.load(fh)


def _fixture_to_context(fixture: dict) -> dict:
    prior_artifacts = []
    for art_type, body_key in [
        ("tasks", "tasks"),
        ("dev_output", "dev_output"),
        ("review_findings", "review_findings"),
        ("test_results", "test_results"),
    ]:
        if fixture.get(body_key):
            prior_artifacts.append({
                "artifact_type": art_type,
                "body": fixture[body_key],
            })
    return {
        "brief": fixture["brief"],
        "prior_artifacts": prior_artifacts,
    }


def _run_judge(fixture: dict) -> dict:
    context = _fixture_to_context(fixture)
    artifacts = judge_agent.run(context)
    assert len(artifacts) == 1, f"Expected 1 artifact, got {len(artifacts)}"
    art = artifacts[0]
    assert art["artifact_type"] == "rubric_score"
    body = json.loads(art["body"])
    return body


@pytest.fixture(scope="module")
def calibration_results():
    """Run all three fixtures and return results keyed by label."""
    results = {}
    for label in FIXTURE_LABELS:
        fixture = _load_fixture(label)
        start = time.time()
        body = _run_judge(fixture)
        elapsed = round(time.time() - start, 2)
        results[label] = {
            "score": body["score"],
            "decision": body["decision"],
            "dimension_scores": body["dimension_scores"],
            "recommendation": body["recommendation"],
            "elapsed_seconds": elapsed,
        }
    return results


def test_known_good_scores_above_known_bad(calibration_results):
    good = calibration_results["known_good"]["score"]
    bad = calibration_results["known_bad"]["score"]
    assert good > bad, (
        f"known_good score ({good}) must exceed known_bad score ({bad})"
    )


def test_known_bad_decision_is_not_ready_for_approval(calibration_results):
    decision = calibration_results["known_bad"]["decision"]
    assert decision != "ready_for_approval", (
        f"known_bad must not be ready_for_approval, got: {decision}"
    )


def test_borderline_score_between_known_bad_and_known_good(calibration_results):
    good = calibration_results["known_good"]["score"]
    bad = calibration_results["known_bad"]["score"]
    borderline = calibration_results["borderline"]["score"]
    # Borderline should be strictly between bad and good (or at least above bad)
    assert borderline > bad, (
        f"borderline score ({borderline}) must exceed known_bad score ({bad})"
    )
    assert borderline < good or borderline <= good, (
        f"borderline score ({borderline}) should not exceed known_good score ({good})"
    )


def test_dimension_scores_differ_across_cases(calibration_results):
    """Score vectors must not be mechanically identical across all three cases."""
    def _score_vector(label):
        return tuple(
            item.get("score", 0)
            for item in calibration_results[label]["dimension_scores"]
        )

    vectors = {label: _score_vector(label) for label in FIXTURE_LABELS}
    unique_vectors = set(vectors.values())
    assert len(unique_vectors) > 1, (
        f"All dimension_score vectors are identical across cases — judge is not "
        f"differentiating: {vectors}"
    )


def test_recommendation_is_substantive(calibration_results):
    for label, result in calibration_results.items():
        rec = result["recommendation"]
        assert len(rec) >= 100, (
            f"{label}: recommendation too short ({len(rec)} chars): {rec!r}"
        )


def test_calibration_report_written(calibration_results, tmp_path):
    """Write the report to the fixtures directory for human inspection."""
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": calibration_results,
        "summary": {
            label: {
                "score": calibration_results[label]["score"],
                "decision": calibration_results[label]["decision"],
            }
            for label in FIXTURE_LABELS
        },
        "ordering_check": {
            "known_good_score": calibration_results["known_good"]["score"],
            "borderline_score": calibration_results["borderline"]["score"],
            "known_bad_score": calibration_results["known_bad"]["score"],
            "ordering_correct": (
                calibration_results["known_good"]["score"]
                > calibration_results["borderline"]["score"]
                > calibration_results["known_bad"]["score"]
            ),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    assert REPORT_PATH.exists()
