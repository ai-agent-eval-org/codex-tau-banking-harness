from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT

from codex_tau.auth import resolve_codex_command, sanitized_child_environment
from codex_tau.prompt import (
    BASELINE_AGENT_INSTRUCTION_FILE_SHA256,
    BASELINE_AGENT_INSTRUCTION_PATH,
    STANDARD_AGENT_INSTRUCTION_SHA256,
    PromptError,
    baseline_agent_instruction,
    prompt_hash,
    standard_prompt_spec,
    standard_system_prompt,
)
from codex_tau.run import _alltools_contract

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_system_prompt_is_exactly_tau2_standard() -> None:
    policy = "authoritative policy"
    expected = SYSTEM_PROMPT.format(
        agent_instruction=AGENT_INSTRUCTION,
        domain_policy=policy,
    )
    artifact = REPO_ROOT / BASELINE_AGENT_INSTRUCTION_PATH
    assert prompt_hash(artifact.read_bytes()) == (
        BASELINE_AGENT_INSTRUCTION_FILE_SHA256
    )
    assert baseline_agent_instruction(REPO_ROOT) == AGENT_INSTRUCTION
    assert standard_system_prompt(
        repo_root=REPO_ROOT,
        domain_policy=policy,
    ) == expected
    assert STANDARD_AGENT_INSTRUCTION_SHA256 == prompt_hash(
        AGENT_INSTRUCTION.encode()
    )


def test_reference_profile_has_no_custom_prompt_override() -> None:
    for name in (
        "smoke-reference",
        "test-reference",
        "vanilla-train-alltools",
        "vanilla-test-alltools",
    ):
        experiment = (REPO_ROOT / f"experiments/{name}.toml").read_text()
        assert "agent_instruction_path" not in experiment
        assert "agent_instruction_sha256" not in experiment
        assert "developer_instructions" not in experiment


def test_alltools_vanilla_prompt_is_canonical_tau2_bytes() -> None:
    _, policy = _alltools_contract()
    spec = standard_prompt_spec(repo_root=REPO_ROOT, domain_policy=policy)
    assert spec.system_prompt == SYSTEM_PROMPT.format(
        agent_instruction=AGENT_INSTRUCTION,
        domain_policy=policy,
    )
    assert spec.source_path == BASELINE_AGENT_INSTRUCTION_PATH.as_posix()


def test_baseline_artifact_change_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / BASELINE_AGENT_INSTRUCTION_PATH
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes((REPO_ROOT / BASELINE_AGENT_INSTRUCTION_PATH).read_bytes())
    assert baseline_agent_instruction(tmp_path) == AGENT_INSTRUCTION

    artifact.write_text("changed\n")
    with pytest.raises(PromptError, match="SHA-256 is not canonical"):
        baseline_agent_instruction(tmp_path)


def test_codex_adds_no_model_visible_context(tmp_path: Path) -> None:
    codex_home = tmp_path / "home"
    empty_cwd = tmp_path / "cwd"
    codex_home.mkdir()
    empty_cwd.mkdir()
    shutil.copyfile(REPO_ROOT / "codex/config.toml", codex_home / "config.toml")
    child = sanitized_child_environment()
    child["CODEX_HOME"] = str(codex_home)
    completed = subprocess.run(
        [*resolve_codex_command(REPO_ROOT), "debug", "prompt-input", "probe"],
        cwd=empty_cwd,
        env=child,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    rendered = json.loads(completed.stdout)
    assert [
        {"type": item["type"], "role": item["role"], "content": item["content"]}
        for item in rendered
    ] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "probe"}],
        }
    ]
