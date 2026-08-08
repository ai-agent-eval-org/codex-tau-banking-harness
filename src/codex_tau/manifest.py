"""Small, secret-free run manifest generation and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_SECRET_KEY_NAMES = {
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "client_secret",
}
_SECRET_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,}|"
    r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})"
)


class ManifestError(RuntimeError):
    """Manifest contains secret-looking data or malformed metadata."""


def assert_secret_free(value: Any, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEY_NAMES:
                raise ManifestError(f"secret-looking key at {path}.{key}")
            assert_secret_free(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_secret_free(child, f"{path}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ManifestError(f"secret-looking value at {path}")


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Validate then atomically replace the small JSON manifest."""
    assert_secret_free(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ManifestError("manifest root must be an object")
    assert_secret_free(value)
    return value

