"""Fail-closed prompt construction through tau2's unmodified template."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

from tau2.agent.llm_agent import SYSTEM_PROMPT

STANDARD_PROMPT_MODE = "tau2_standard_llm_agent"
OPTIMIZED_PROMPT_MODE = "train_trace_one_shot_agent_instruction"
BASELINE_AGENT_INSTRUCTION_PATH = Path(
    "prompts/banking_knowledge/baseline.md"
)
OPTIMIZED_AGENT_INSTRUCTION_PATH = Path(
    "prompts/banking_knowledge/optimized.md"
)
BASELINE_AGENT_INSTRUCTION_FILE_SHA256 = (
    "89c128e25653ff963dca98a0a022f3c43c009a7e499f29025c81ce9c6c1be7fd"
)
STANDARD_AGENT_INSTRUCTION_SHA256 = (
    "e00faa515230c8648931f73ed25c9528418cccc522fe8936917f4c2a047bc5d2"
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


def _read_fixed_artifact(
    *, repo_root: Path, relative_path: Path, label: str
) -> bytes:
    resolved_root = repo_root.resolve()
    artifact_path = repo_root / relative_path
    try:
        resolved_artifact = artifact_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PromptError(
            f"{label} prompt artifact is missing: {relative_path.as_posix()}"
        ) from exc
    if not resolved_artifact.is_relative_to(resolved_root):
        raise PromptError(f"{label} prompt artifact resolves outside the repository")
    if not resolved_artifact.is_file():
        raise PromptError(f"{label} prompt artifact is not a regular file")
    return resolved_artifact.read_bytes()


def baseline_agent_instruction(repo_root: Path) -> str:
    """Load the visible baseline artifact and verify canonical τ-bench bytes."""
    artifact_bytes = _read_fixed_artifact(
        repo_root=repo_root,
        relative_path=BASELINE_AGENT_INSTRUCTION_PATH,
        label="baseline",
    )
    artifact_sha256 = prompt_hash(artifact_bytes)
    if not hmac.compare_digest(
        artifact_sha256, BASELINE_AGENT_INSTRUCTION_FILE_SHA256
    ):
        raise PromptError("baseline prompt artifact SHA-256 is not canonical")
    try:
        artifact_text = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError("baseline prompt artifact must be valid UTF-8") from exc

    # Markdown files conventionally end in LF; τ-bench's stripped constant does not.
    agent_instruction = artifact_text.removesuffix("\n")
    if prompt_hash(agent_instruction.encode()) != STANDARD_AGENT_INSTRUCTION_SHA256:
        raise PromptError("baseline prompt content is not canonical τ-bench bytes")
    return agent_instruction


def render_system_prompt(domain_policy: str, agent_instruction: str) -> str:
    """Render only the two substitutions supported by tau2's SYSTEM_PROMPT."""
    return SYSTEM_PROMPT.format(
        domain_policy=domain_policy,
        agent_instruction=agent_instruction,
    )


def standard_system_prompt(*, repo_root: Path, domain_policy: str) -> str:
    """Return the byte-identical prompt used by tau2's standard LLMAgent."""
    return render_system_prompt(domain_policy, baseline_agent_instruction(repo_root))


def standard_prompt_spec(*, repo_root: Path, domain_policy: str) -> PromptSpec:
    agent_instruction = baseline_agent_instruction(repo_root)
    system_prompt = render_system_prompt(domain_policy, agent_instruction)
    return PromptSpec(
        mode=STANDARD_PROMPT_MODE,
        agent_instruction=agent_instruction,
        agent_instruction_sha256=STANDARD_AGENT_INSTRUCTION_SHA256,
        system_prompt=system_prompt,
        effective_system_prompt_sha256=prompt_hash(system_prompt.encode()),
        source_path=BASELINE_AGENT_INSTRUCTION_PATH.as_posix(),
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

    artifact_bytes = _read_fixed_artifact(
        repo_root=repo_root,
        relative_path=OPTIMIZED_AGENT_INSTRUCTION_PATH,
        label="optimized",
    )
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
