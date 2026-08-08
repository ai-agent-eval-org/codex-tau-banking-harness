from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codex_tau.prompt import PromptError, prompt_hash, verify_prompt

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_baseline_and_candidate_are_distinct() -> None:
    baseline = (REPO_ROOT / "prompts/banking_knowledge/baseline.md").read_bytes()
    candidate = (REPO_ROOT / "prompts/banking_knowledge/candidate.md").read_bytes()
    assert prompt_hash(baseline) != prompt_hash(candidate)
    assert (REPO_ROOT / "AGENTS.md").read_bytes() == candidate


def test_exact_git_bytes_are_required(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt = prompt_dir / "candidate.md"
    prompt.write_text("explicit prompt\n")
    (tmp_path / "AGENTS.md").write_text("explicit prompt\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "prompt"], cwd=tmp_path, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    verified = verify_prompt(
        tmp_path,
        {"prompt_path": "prompts/candidate.md"},
        {"source_commit": commit, "source_path": "AGENTS.md"},
    )
    assert verified.text == "explicit prompt\n"
    assert verified.source_commit == commit
    prompt.write_text("untracked change\n")
    with pytest.raises(PromptError, match="differ"):
        verify_prompt(
            tmp_path,
            {"prompt_path": "prompts/candidate.md"},
            {"source_commit": commit, "source_path": "AGENTS.md"},
        )

