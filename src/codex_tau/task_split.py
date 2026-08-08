"""Frozen local train/test split for the public banking task set."""

from __future__ import annotations

import hashlib
import json

SPLIT_SEED = 42
SPLIT_TEST_FRACTION = 0.5
SPLIT_ALGORITHM = (
    "sort task IDs; random.Random(42).shuffle; first ceil(n*0.5) to test; "
    "remainder to train; sort each partition"
)

TRAIN_TASK_IDS = (
    "task_001",
    "task_003",
    "task_004",
    "task_005",
    "task_006",
    "task_007",
    "task_015",
    "task_017",
    "task_018",
    "task_020",
    "task_021",
    "task_023",
    "task_024",
    "task_025",
    "task_026",
    "task_028",
    "task_029",
    "task_032",
    "task_033",
    "task_034",
    "task_036",
    "task_040",
    "task_044",
    "task_049",
    "task_052",
    "task_054",
    "task_059",
    "task_060",
    "task_063",
    "task_064",
    "task_067",
    "task_070",
    "task_072",
    "task_075",
    "task_077",
    "task_079",
    "task_081",
    "task_083",
    "task_087",
    "task_088",
    "task_090",
    "task_092",
    "task_093",
    "task_094",
    "task_095",
    "task_097",
    "task_099",
    "task_100",
)

TEST_TASK_IDS = (
    "task_002",
    "task_008",
    "task_010",
    "task_012",
    "task_014",
    "task_016",
    "task_019",
    "task_022",
    "task_027",
    "task_031",
    "task_035",
    "task_037",
    "task_038",
    "task_039",
    "task_041",
    "task_043",
    "task_045",
    "task_046",
    "task_047",
    "task_048",
    "task_050",
    "task_051",
    "task_053",
    "task_055",
    "task_056",
    "task_057",
    "task_058",
    "task_061",
    "task_062",
    "task_065",
    "task_066",
    "task_068",
    "task_069",
    "task_071",
    "task_073",
    "task_074",
    "task_076",
    "task_078",
    "task_080",
    "task_082",
    "task_084",
    "task_085",
    "task_086",
    "task_089",
    "task_091",
    "task_096",
    "task_098",
    "task_101",
    "task_102",
)


def split_sha256() -> str:
    """Return a stable digest covering the complete frozen split contract."""
    payload = {
        "algorithm": SPLIT_ALGORITHM,
        "seed": SPLIT_SEED,
        "test": TEST_TASK_IDS,
        "test_fraction": SPLIT_TEST_FRACTION,
        "train": TRAIN_TASK_IDS,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
