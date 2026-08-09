from __future__ import annotations

import math
import random
from pathlib import Path

from tau2.runner.helpers import get_tasks

from codex_tau.prompt import OPTIMIZED_SYSTEM_PROMPT_PATH, prompt_hash
from codex_tau.run import (
    OPTIMIZED_TEST_EXPERIMENT,
    PILOT2_TASK_IDS,
    PILOT5_TASK_IDS,
    SMOKE_TASK_IDS,
    VANILLA_TEST_EXPERIMENT,
    VANILLA_TRAIN_EXPERIMENT,
    _authorized_experiments,
    _show_per_task_console,
    load_experiment,
)
from codex_tau.task_split import (
    SPLIT_SEED,
    TEST_TASK_IDS,
    TRAIN_TASK_IDS,
    split_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_split_exactly_reproduces_seed_42_algorithm() -> None:
    all_task_ids = sorted(
        task.id for task in get_tasks("banking_knowledge", task_split_name=None)
    )
    shuffled = list(all_task_ids)
    random.Random(SPLIT_SEED).shuffle(shuffled)
    test_count = math.ceil(len(shuffled) * 0.5)

    assert SPLIT_SEED == 42
    assert len(all_task_ids) == 97
    assert TEST_TASK_IDS == tuple(sorted(shuffled[:test_count]))
    assert TRAIN_TASK_IDS == tuple(sorted(shuffled[test_count:]))
    assert len(TRAIN_TASK_IDS) == 48
    assert len(TEST_TASK_IDS) == 49
    assert set(TRAIN_TASK_IDS).isdisjoint(TEST_TASK_IDS)
    assert set(TRAIN_TASK_IDS) | set(TEST_TASK_IDS) == set(all_task_ids)
    assert set(SMOKE_TASK_IDS) <= set(TRAIN_TASK_IDS)


def test_split_digest_is_stable() -> None:
    assert split_sha256() == (
        "48224cbcbfcbad9f149842a64bc26b920ade3335d4e9d8f735b9d135f5394a08"
    )


def test_test_experiment_is_exactly_bounded_to_frozen_test_ids() -> None:
    experiment = load_experiment(REPO_ROOT / "experiments/test-reference.toml")
    assert experiment["task_partition"] == "test"
    assert tuple(experiment["task_ids"]) == TEST_TASK_IDS
    assert experiment["retrieval"] == "terminal_use"
    assert experiment["agent_reasoning"] == "high"
    assert experiment["max_steps"] == 200
    assert experiment["trials_per_task"] == 1
    assert experiment["max_concurrency"] == 1


def test_alltools_pilot5_is_the_predeclared_holdout_prefix() -> None:
    experiment = load_experiment(REPO_ROOT / "experiments/pilot5-alltools.toml")
    assert PILOT5_TASK_IDS == TEST_TASK_IDS[:5]
    assert tuple(experiment["task_ids"]) == PILOT5_TASK_IDS
    assert experiment["profile"] == "alltools_pilot_4trials"
    assert experiment["retrieval"] == "alltools"
    assert experiment["trials_per_task"] == 4
    assert experiment["max_steps"] == 200
    assert experiment["max_concurrency"] == 8


def test_alltools_pilot5_concurrency16_is_exactly_bounded() -> None:
    experiment = load_experiment(
        REPO_ROOT / "experiments/pilot5-alltools-concurrency16.toml"
    )
    assert PILOT5_TASK_IDS == TEST_TASK_IDS[:5]
    assert tuple(experiment["task_ids"]) == PILOT5_TASK_IDS
    assert experiment["profile"] == "alltools_pilot_concurrency16_4trials"
    assert experiment["retrieval"] == "alltools"
    assert experiment["trials_per_task"] == 4
    assert experiment["max_steps"] == 200
    assert experiment["max_concurrency"] == 16


def test_alltools_concurrency_validation_is_exactly_bounded() -> None:
    experiment = load_experiment(
        REPO_ROOT / "experiments/pilot2-alltools-concurrency2.toml"
    )
    assert PILOT2_TASK_IDS == TEST_TASK_IDS[:2]
    assert tuple(experiment["task_ids"]) == PILOT2_TASK_IDS
    assert experiment["profile"] == "alltools_concurrency_validation_4trials"
    assert experiment["retrieval"] == "alltools"
    assert experiment["trials_per_task"] == 4
    assert experiment["max_steps"] == 200
    assert experiment["max_concurrency"] == 2


def test_held_out_runs_suppress_task_level_console_feedback() -> None:
    assert _show_per_task_console("smoke") is True
    assert _show_per_task_console("train") is True
    assert _show_per_task_console("pilot2") is False
    assert _show_per_task_console("pilot5") is False
    assert _show_per_task_console("test") is False


def test_fresh_alltools_vanilla_matrices_are_exactly_frozen() -> None:
    cases = (
        (VANILLA_TRAIN_EXPERIMENT, "train", TRAIN_TASK_IDS),
        (VANILLA_TEST_EXPERIMENT, "test", TEST_TASK_IDS),
    )
    for name, partition, task_ids in cases:
        experiment = load_experiment(REPO_ROOT / f"experiments/{name}.toml")
        assert experiment["name"] == name
        assert experiment["profile"] == "alltools_vanilla_trial0"
        assert experiment["task_partition"] == partition
        assert tuple(experiment["task_ids"]) == task_ids
        assert experiment["retrieval"] == "alltools"
        assert experiment["agent_model"] == "gpt-5.4"
        assert experiment["agent_reasoning"] == "high"
        assert experiment["user_model"] == "gpt-5.2"
        assert experiment["user_reasoning"] == "low"
        assert experiment["trials_per_task"] == 1
        assert experiment["max_steps"] == 200
        assert experiment["max_concurrency"] == 16
        assert "system_prompt_path" not in experiment
        assert "system_prompt_file_sha256" not in experiment


def test_optimized_test_is_exactly_frozen_and_hash_pinned() -> None:
    authorization = _authorized_experiments()[OPTIMIZED_TEST_EXPERIMENT]
    assert authorization == {
        "profile": "alltools_optimized_trial0",
        "retrieval": "alltools",
        "task_partition": "test",
        "task_ids": TEST_TASK_IDS,
        "trials_per_task": 1,
        "max_concurrency": 16,
        "prompt_mode": "train_trace_one_shot_full_system_prompt",
    }

    experiment = load_experiment(
        REPO_ROOT / f"experiments/{OPTIMIZED_TEST_EXPERIMENT}.toml"
    )
    artifact = REPO_ROOT / OPTIMIZED_SYSTEM_PROMPT_PATH
    assert experiment["name"] == OPTIMIZED_TEST_EXPERIMENT
    assert experiment["profile"] == "alltools_optimized_trial0"
    assert experiment["task_partition"] == "test"
    assert tuple(experiment["task_ids"]) == TEST_TASK_IDS
    assert experiment["retrieval"] == "alltools"
    assert experiment["agent_model"] == "gpt-5.4"
    assert experiment["agent_reasoning"] == "high"
    assert experiment["user_model"] == "gpt-5.2"
    assert experiment["user_reasoning"] == "low"
    assert experiment["trials_per_task"] == 1
    assert experiment["max_steps"] == 200
    assert experiment["max_concurrency"] == 16
    assert experiment["system_prompt_path"] == (
        OPTIMIZED_SYSTEM_PROMPT_PATH.as_posix()
    )
    assert experiment["system_prompt_file_sha256"] == prompt_hash(
        artifact.read_bytes()
    )
    assert experiment["system_prompt_file_sha256"] == (
        "e113c6ef7a8e0ee829089bd57c08d65bc9bc9c2fe76ad96e7f8c7c993d0c559e"
    )
