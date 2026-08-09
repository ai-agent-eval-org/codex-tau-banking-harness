"""Codex app-server adapter for the τ-bench banking knowledge domain."""

import os
from pathlib import Path

# τ-bench intentionally keeps benchmark data outside its built wheel. The pinned
# source submodule supplies it without relying on an ambient checkout.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PINNED_DATA = _REPO_ROOT / "vendor" / "tau2-bench" / "data"
if _PINNED_DATA.is_dir():
    os.environ.setdefault("TAU2_DATA_DIR", str(_PINNED_DATA))

__version__ = "0.1.0"
