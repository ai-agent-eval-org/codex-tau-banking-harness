from __future__ import annotations

from pathlib import Path

import pytest

from codex_tau.prompt import (
    OPTIMIZED_PROMPT_MODE,
    OPTIMIZED_SYSTEM_PROMPT_PATH,
    PromptError,
    optimized_prompt_spec,
    prompt_hash,
)


def write_artifact(repo_root: Path, content: bytes) -> tuple[str, str]:
    artifact = repo_root / OPTIMIZED_SYSTEM_PROMPT_PATH
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    return OPTIMIZED_SYSTEM_PROMPT_PATH.as_posix(), prompt_hash(content)


def test_optimized_artifact_is_the_complete_system_prompt(tmp_path: Path) -> None:
    relative_path, digest = write_artifact(
        tmp_path, b"<instructions>General.</instructions>\n<policy>Banking.</policy>\n"
    )
    spec = optimized_prompt_spec(
        repo_root=tmp_path,
        domain_policy=None,
        relative_path=relative_path,
        expected_file_sha256=digest,
    )
    assert spec.mode == OPTIMIZED_PROMPT_MODE
    assert spec.source_path == relative_path
    assert spec.system_prompt == (
        "<instructions>General.</instructions>\n<policy>Banking.</policy>"
    )
    assert spec.system_prompt_sha256 == prompt_hash(spec.system_prompt.encode())
    assert spec.source_file_sha256 == digest


def test_optimized_artifact_path_is_fixed_and_repo_relative(tmp_path: Path) -> None:
    _, digest = write_artifact(tmp_path, b"instruction")
    for rejected in (
        "prompts/other.md",
        "../optimized.md",
        str((tmp_path / OPTIMIZED_SYSTEM_PROMPT_PATH).resolve()),
    ):
        with pytest.raises(PromptError, match="path must be exactly"):
            optimized_prompt_spec(
                repo_root=tmp_path,
                domain_policy=None,
                relative_path=rejected,
                expected_file_sha256=digest,
            )


def test_optimized_artifact_hash_must_be_exact(tmp_path: Path) -> None:
    relative_path, _ = write_artifact(tmp_path, b"instruction")
    with pytest.raises(PromptError, match="64 lowercase"):
        optimized_prompt_spec(
            repo_root=tmp_path,
            domain_policy=None,
            relative_path=relative_path,
            expected_file_sha256="A" * 64,
        )
    with pytest.raises(PromptError, match="does not match"):
        optimized_prompt_spec(
            repo_root=tmp_path,
            domain_policy=None,
            relative_path=relative_path,
            expected_file_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b" \n\t", "nonempty"),
        (b"\xff\xfe", "valid UTF-8"),
    ],
)
def test_optimized_artifact_must_be_nonempty_utf8(
    tmp_path: Path, content: bytes, message: str
) -> None:
    relative_path, digest = write_artifact(tmp_path, content)
    with pytest.raises(PromptError, match=message):
        optimized_prompt_spec(
            repo_root=tmp_path,
            domain_policy=None,
            relative_path=relative_path,
            expected_file_sha256=digest,
        )


def test_optimized_artifact_cannot_resolve_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-prompt.md"
    outside.write_text("instruction")
    artifact = tmp_path / OPTIMIZED_SYSTEM_PROMPT_PATH
    artifact.parent.mkdir(parents=True)
    artifact.symlink_to(outside)
    with pytest.raises(PromptError, match="outside the repository"):
        optimized_prompt_spec(
            repo_root=tmp_path,
            domain_policy=None,
            relative_path=OPTIMIZED_SYSTEM_PROMPT_PATH.as_posix(),
            expected_file_sha256=prompt_hash(outside.read_bytes()),
        )
