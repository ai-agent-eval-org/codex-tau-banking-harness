"""Prompt loading, hashing, and Git/ExpertTrace provenance verification."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class PromptError(RuntimeError):
    """Prompt bytes or provenance are not exact."""


@dataclass(frozen=True)
class VerifiedPrompt:
    text: str
    sha256: str
    path: str
    source_commit: str
    source_path: str


def prompt_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_prompt(
    repo_root: Path, experiment: Mapping[str, Any], provenance: Mapping[str, Any]
) -> VerifiedPrompt:
    relative = experiment.get("prompt_path")
    source_commit = provenance.get("source_commit")
    source_path = provenance.get("source_path")
    if not all(isinstance(value, str) and value for value in (relative, source_commit, source_path)):
        raise PromptError("prompt provenance is incomplete")
    if source_commit == "PENDING":
        raise PromptError("prompt source commit is not pinned")
    path = (repo_root / relative).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise PromptError("prompt path escapes the repository") from exc
    local_bytes = path.read_bytes()
    completed = subprocess.run(
        ["git", "show", f"{source_commit}:{source_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PromptError(
            f"unable to read prompt provenance {source_commit}:{source_path}"
        )
    if completed.stdout != local_bytes:
        raise PromptError("harness prompt bytes differ from their provenance commit")
    try:
        text = local_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError("prompt must be UTF-8") from exc
    return VerifiedPrompt(
        text=text,
        sha256=prompt_hash(local_bytes),
        path=str(relative),
        source_commit=source_commit,
        source_path=source_path,
    )
