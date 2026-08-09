from __future__ import annotations

from pathlib import Path

import pytest

from codex_tau.run import ExperimentError, load_experiment

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "experiments/vanilla-train-alltools.toml"
OPTIMIZED_SOURCE = REPO_ROOT / "experiments/optimized-test-alltools.toml"


def write_experiment(tmp_path: Path, text: str) -> Path:
    path = tmp_path / SOURCE.name
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("max_concurrency = 16", "max_concurrency = 8", "max_concurrency"),
        (
            'profile = "alltools_vanilla_trial0"',
            'profile = "alltools_optimized_trial0"',
            "profile",
        ),
        ('"task_001",', '"task_002",', "task_ids"),
    ],
)
def test_exact_vanilla_matrix_rejects_changes(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    changed = SOURCE.read_text().replace(old, new, 1)
    with pytest.raises(ExperimentError, match=message):
        load_experiment(write_experiment(tmp_path, changed))


@pytest.mark.parametrize(
    "extra",
    [
        'developer_instructions = "extra"',
        'system_prompt_path = "prompts/banking_knowledge/prompt.md"',
        'custom_prompt = "text"',
    ],
)
def test_vanilla_matrix_rejects_every_custom_prompt_field(
    tmp_path: Path, extra: str
) -> None:
    changed = SOURCE.read_text().replace(
        'task_partition = "train"',
        f'task_partition = "train"\n{extra}',
    )
    with pytest.raises(ExperimentError, match="fixed canonical fields"):
        load_experiment(write_experiment(tmp_path, changed))


def test_experiment_filename_must_match_fixed_name(tmp_path: Path) -> None:
    path = tmp_path / "renamed.toml"
    path.write_text(SOURCE.read_text())
    with pytest.raises(ExperimentError, match="filename"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            'system_prompt_path = "prompts/banking_knowledge/optimized.md"',
            'system_prompt_path = "prompts/banking_knowledge/other.md"',
        ),
        (
            'system_prompt_file_sha256 = '
            '"e113c6ef7a8e0ee829089bd57c08d65bc9bc9c2fe76ad96e7f8c7c993d0c559e"',
            'system_prompt_file_sha256 = '
            '"0000000000000000000000000000000000000000000000000000000000000000"',
        ),
    ],
)
def test_optimized_matrix_rejects_prompt_provenance_changes(
    tmp_path: Path, old: str, new: str
) -> None:
    changed = OPTIMIZED_SOURCE.read_text().replace(old, new, 1)
    path = tmp_path / OPTIMIZED_SOURCE.name
    path.write_text(changed)
    with pytest.raises(ExperimentError, match="optimized prompt fields"):
        load_experiment(path)
