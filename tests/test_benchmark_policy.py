from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_non_submission_rule_is_prominent_and_durable() -> None:
    policy = (REPO_ROOT / "BENCHMARK_POLICY.md").read_text()
    readme = (REPO_ROOT / "README.md").read_text()
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    assert "Never prepare, publish, upload, or submit" in policy
    assert "τ-bench leaderboard" in policy
    assert "There is no exception to this repository rule" in policy
    assert "leaderboard or third party without fresh" not in policy
    assert "leaderboard or any third party\nwithout fresh" not in readme
    assert "request to run, inspect, compare, or summarize tasks" in policy
    assert "BENCHMARK_POLICY.md" in readme
    assert "request to run or compare tasks is not submission authorization" in readme
    assert "Never reshuffle" in agents
    assert "Prompt optimization, human labeling" in agents
    assert "Test runs must disable per-task console summaries" in agents
    assert "test trajectories must not feed prompt optimization" in policy
    assert "implementation, not authorization" in policy
    assert "consumed by one successful missing-only retry" in policy
    assert "authorizes no further retry" in policy
    assert "authorizes no additional" in agents
