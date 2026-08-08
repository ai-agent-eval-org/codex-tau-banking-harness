from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_non_submission_rule_is_prominent_and_durable() -> None:
    policy = (REPO_ROOT / "BENCHMARK_POLICY.md").read_text()
    readme = (REPO_ROOT / "README.md").read_text()
    assert "Never prepare, publish, upload, or submit" in policy
    assert "request to run, inspect, compare, or summarize tasks" in policy
    assert "BENCHMARK_POLICY.md" in readme
    assert "request to run or compare tasks is not submission authorization" in readme
