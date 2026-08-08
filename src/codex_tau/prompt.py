"""Fail-closed prompt construction through tau2's unmodified template."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT

STANDARD_PROMPT_MODE = "tau2_standard_llm_agent"
OPTIMIZED_PROMPT_MODE = "train_trace_one_shot_agent_instruction"
OPTIMIZED_AGENT_INSTRUCTION_PATH = Path(
    "prompts/banking_knowledge/optimized.md"
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PromptError(RuntimeError):
    """A prompt artifact violated its declared provenance contract."""


@dataclass(frozen=True)
class PromptSpec:
    """Resolved model-visible prompt bytes and their provenance."""

    mode: str
    agent_instruction: str
    agent_instruction_sha256: str
    system_prompt: str
    effective_system_prompt_sha256: str
    source_path: str | None


def prompt_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


STANDARD_AGENT_INSTRUCTION_SHA256 = prompt_hash(AGENT_INSTRUCTION.encode())


def render_system_prompt(domain_policy: str, agent_instruction: str) -> str:
    """Render only the two substitutions supported by tau2's SYSTEM_PROMPT."""
    return SYSTEM_PROMPT.format(
        domain_policy=domain_policy,
        agent_instruction=agent_instruction,
    )


def standard_system_prompt(domain_policy: str) -> str:
    """Return the byte-identical prompt used by tau2's standard LLMAgent."""
    return render_system_prompt(domain_policy, AGENT_INSTRUCTION)


def standard_prompt_spec(domain_policy: str) -> PromptSpec:
    system_prompt = standard_system_prompt(domain_policy)
    return PromptSpec(
        mode=STANDARD_PROMPT_MODE,
        agent_instruction=AGENT_INSTRUCTION,
        agent_instruction_sha256=STANDARD_AGENT_INSTRUCTION_SHA256,
        system_prompt=system_prompt,
        effective_system_prompt_sha256=prompt_hash(system_prompt.encode()),
        source_path=None,
    )


def optimized_prompt_spec(
    *,
    repo_root: Path,
    domain_policy: str,
    relative_path: str,
    expected_sha256: str,
) -> PromptSpec:
    """Load one pinned UTF-8 AGENT_INSTRUCTION replacement from the repository."""
    expected_path = OPTIMIZED_AGENT_INSTRUCTION_PATH.as_posix()
    if relative_path != expected_path:
        raise PromptError(
            f"optimized prompt path must be exactly {expected_path!r}"
        )
    if _SHA256.fullmatch(expected_sha256) is None:
        raise PromptError("optimized prompt SHA-256 must be 64 lowercase hex digits")

    resolved_root = repo_root.resolve()
    artifact_path = repo_root / OPTIMIZED_AGENT_INSTRUCTION_PATH
    try:
        resolved_artifact = artifact_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PromptError(f"optimized prompt artifact is missing: {expected_path}") from exc
    if not resolved_artifact.is_relative_to(resolved_root):
        raise PromptError("optimized prompt artifact resolves outside the repository")
    if not resolved_artifact.is_file():
        raise PromptError("optimized prompt artifact is not a regular file")

    artifact_bytes = resolved_artifact.read_bytes()
    actual_sha256 = prompt_hash(artifact_bytes)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise PromptError(
            "optimized prompt artifact SHA-256 does not match the experiment"
        )
    try:
        agent_instruction = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError("optimized prompt artifact must be valid UTF-8") from exc
    if not agent_instruction.strip():
        raise PromptError("optimized prompt artifact must be nonempty")

    system_prompt = render_system_prompt(domain_policy, agent_instruction)
    return PromptSpec(
        mode=OPTIMIZED_PROMPT_MODE,
        agent_instruction=agent_instruction,
        agent_instruction_sha256=actual_sha256,
        system_prompt=system_prompt,
        effective_system_prompt_sha256=prompt_hash(system_prompt.encode()),
        source_path=expected_path,
    )
