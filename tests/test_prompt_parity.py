from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT

from codex_tau.auth import resolve_codex_command, sanitized_child_environment
from codex_tau.prompt import (
    STANDARD_AGENT_INSTRUCTION_SHA256,
    prompt_hash,
    standard_system_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_system_prompt_is_exactly_tau2_standard() -> None:
    policy = "authoritative policy"
    expected = SYSTEM_PROMPT.format(
        agent_instruction=AGENT_INSTRUCTION,
        domain_policy=policy,
    )
    assert standard_system_prompt(policy) == expected
    assert STANDARD_AGENT_INSTRUCTION_SHA256 == prompt_hash(
        AGENT_INSTRUCTION.encode()
    )


def test_reference_profile_has_no_custom_prompt_artifact() -> None:
    assert not list((REPO_ROOT / "prompts/banking_knowledge").glob("*.md"))
    experiment = (REPO_ROOT / "experiments/smoke-reference.toml").read_text()
    assert "prompt_path" not in experiment
    assert "developer_instructions" not in experiment


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
