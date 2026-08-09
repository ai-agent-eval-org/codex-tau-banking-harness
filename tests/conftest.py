from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("TAU2_DATA_DIR", str(REPO_ROOT / "vendor" / "tau2-bench" / "data"))

