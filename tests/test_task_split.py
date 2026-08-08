from __future__ import annotations

import math
import random
from pathlib import Path

from tau2.runner.helpers import get_tasks

from codex_tau.run import SMOKE_TASK_IDS, load_experiment
from codex_tau.task_split import (
    SPLIT_SEED,
    TEST_TASK_IDS,
    TRAIN_TASK_IDS,
    split_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_split_exactly_reproduces_seed_42_algorithm() -> None:
    all_task_ids = sorted(
        task.id
        for task in get_tasks("banking_knowledge", task_split_name=None)
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
    experiment, _ = load_experiment(REPO_ROOT / "experiments/test-candidate.toml")
    assert experiment["task_partition"] == "test"
    assert tuple(experiment["task_ids"]) == TEST_TASK_IDS
    assert experiment["retrieval"] == "alltools"
    assert experiment["trials_per_task"] == 1
    assert experiment["max_concurrency"] == 4
