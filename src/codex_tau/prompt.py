"""Fail-closed loading of complete model-visible system-prompt artifacts."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT

STANDARD_PROMPT_MODE = "tau2_canonical_system_prompt"
OPTIMIZED_PROMPT_MODE = "train_trace_one_shot_full_system_prompt"
BASELINE_SYSTEM_PROMPT_PATH = Path("prompts/banking_knowledge/baseline.md")
OPTIMIZED_SYSTEM_PROMPT_PATH = Path("prompts/banking_knowledge/optimized.md")
OPTIMIZED_SYSTEM_PROMPT_FILE_SHA256 = (
    "4022d30ae66d704fdc1954202aafd94ef0140f3dea65a53b0f154b702ec47e4c"
)
BASELINE_SYSTEM_PROMPT_FILE_SHA256 = (
    "c51896d46edd67711f8288735462b104202d4b250609ced2e5c16ded52ba90c3"
)
BASELINE_SYSTEM_PROMPT_SHA256 = (
    "40e0c2afebb858e37b99b3dffcaba2cf1f2d48ad26908612fd4b5756d4899780"
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PromptError(RuntimeError):
    """A prompt artifact violated its declared provenance contract."""


@dataclass(frozen=True)
class PromptSpec:
    """Resolved model-visible prompt bytes and their provenance."""

    mode: str
    system_prompt: str
    system_prompt_sha256: str
    source_path: str | None
    source_file_sha256: str | None


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


def _decode_prompt_file(artifact_bytes: bytes, *, label: str) -> str:
    try:
        artifact_text = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError(f"{label} prompt artifact must be valid UTF-8") from exc
    # The Markdown artifact conventionally ends in LF; that separator is not sent.
    system_prompt = artifact_text.removesuffix("\n")
    if not system_prompt.strip():
        raise PromptError(f"{label} prompt artifact must be nonempty")
    return system_prompt


def baseline_system_prompt(repo_root: Path) -> str:
    """Load and verify the visible canonical alltools system prompt."""
    artifact_bytes = _read_fixed_artifact(
        repo_root=repo_root,
        relative_path=BASELINE_SYSTEM_PROMPT_PATH,
        label="baseline",
    )
    if not hmac.compare_digest(
        prompt_hash(artifact_bytes), BASELINE_SYSTEM_PROMPT_FILE_SHA256
    ):
        raise PromptError("baseline prompt artifact SHA-256 is not canonical")
    system_prompt = _decode_prompt_file(artifact_bytes, label="baseline")
    if prompt_hash(system_prompt.encode()) != BASELINE_SYSTEM_PROMPT_SHA256:
        raise PromptError("baseline prompt content is not canonical alltools bytes")
    return system_prompt


def render_canonical_system_prompt(domain_policy: str) -> str:
    """Render τ-bench's pinned canonical prompt for a runtime policy."""
    return SYSTEM_PROMPT.format(
        domain_policy=domain_policy,
        agent_instruction=AGENT_INSTRUCTION,
    )


def standard_system_prompt(*, repo_root: Path, domain_policy: str) -> str:
    """Use the full alltools artifact or exact τ-bench reference rendering."""
    rendered = render_canonical_system_prompt(domain_policy)
    baseline = baseline_system_prompt(repo_root)
    return baseline if hmac.compare_digest(rendered, baseline) else rendered


def standard_prompt_spec(*, repo_root: Path, domain_policy: str) -> PromptSpec:
    rendered = render_canonical_system_prompt(domain_policy)
    baseline = baseline_system_prompt(repo_root)
    uses_artifact = hmac.compare_digest(rendered, baseline)
    system_prompt = baseline if uses_artifact else rendered
    return PromptSpec(
        mode=STANDARD_PROMPT_MODE,
        system_prompt=system_prompt,
        system_prompt_sha256=prompt_hash(system_prompt.encode()),
        source_path=(
            BASELINE_SYSTEM_PROMPT_PATH.as_posix() if uses_artifact else None
        ),
        source_file_sha256=(
            BASELINE_SYSTEM_PROMPT_FILE_SHA256 if uses_artifact else None
        ),
    )


def optimized_prompt_spec(
    *,
    repo_root: Path,
    domain_policy: str | None,
    relative_path: str,
    expected_file_sha256: str,
) -> PromptSpec:
    """Load one pinned complete alltools system-prompt replacement."""
    expected_path = OPTIMIZED_SYSTEM_PROMPT_PATH.as_posix()
    if relative_path != expected_path:
        raise PromptError(f"optimized prompt path must be exactly {expected_path!r}")
    if _SHA256.fullmatch(expected_file_sha256) is None:
        raise PromptError("optimized prompt SHA-256 must be 64 lowercase hex digits")

    if domain_policy is not None:
        canonical = render_canonical_system_prompt(domain_policy)
        if not hmac.compare_digest(canonical, baseline_system_prompt(repo_root)):
            raise PromptError("optimized prompt is restricted to the alltools policy")

    artifact_bytes = _read_fixed_artifact(
        repo_root=repo_root,
        relative_path=OPTIMIZED_SYSTEM_PROMPT_PATH,
        label="optimized",
    )
    actual_file_sha256 = prompt_hash(artifact_bytes)
    if not hmac.compare_digest(actual_file_sha256, expected_file_sha256):
        raise PromptError(
            "optimized prompt artifact SHA-256 does not match the experiment"
        )
    system_prompt = _decode_prompt_file(artifact_bytes, label="optimized")
    return PromptSpec(
        mode=OPTIMIZED_PROMPT_MODE,
        system_prompt=system_prompt,
        system_prompt_sha256=prompt_hash(system_prompt.encode()),
        source_path=expected_path,
        source_file_sha256=actual_file_sha256,
    )
