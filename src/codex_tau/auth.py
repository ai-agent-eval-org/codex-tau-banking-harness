"""Pinned Codex executable discovery and ChatGPT credential isolation."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

CODEX_VERSION = "0.147.0"
_EXPLICIT_SECRET_VARS = {
    "OPENAI_API_KEY",
    "OPENAI_API_TOKEN",
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "CODEX_API_KEY",
    "CODEX_API_TOKEN",
    "CODEX_ACCESS_TOKEN",
    "AZURE_OPENAI_API_KEY",
}


class AuthError(RuntimeError):
    """A required subscription-auth invariant was not satisfied."""


def is_secret_environment_name(name: str) -> bool:
    """Return whether an environment variable could authorize Codex/API use."""
    upper = name.upper()
    if upper in _EXPLICIT_SECRET_VARS:
        return True
    if "OPENAI" not in upper and "CODEX" not in upper:
        return False
    return bool(re.search(r"(?:KEY|TOKEN|SECRET|CREDENTIAL|AUTH|COOKIE)", upper))


def sanitized_child_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy the environment while removing all Codex/OpenAI bearer material."""
    original = os.environ if source is None else source
    return {k: v for k, v in original.items() if not is_secret_environment_name(k)}


def default_auth_file(source: Mapping[str, str] | None = None) -> Path:
    """Resolve the existing personal Codex authentication file."""
    env = os.environ if source is None else source
    configured = env.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / "auth.json"


def resolve_codex_command(repo_root: Path) -> list[str]:
    """Resolve the repository-pinned Codex executable, native on Apple Silicon."""
    binary = repo_root / "node_modules" / ".bin" / "codex"
    if not binary.is_file():
        raise AuthError("project-local Codex is missing; run `npm ci`")
    command = [str(binary)]
    # A Python process running under Rosetta otherwise makes the universal Node
    # launcher request Codex's absent x64 optional package.
    if platform.system() == "Darwin" and platform.machine() in {"arm64", "x86_64"}:
        arch = shutil.which("arch")
        if (
            arch
            and subprocess.run(
                [arch, "-arm64", "/usr/bin/true"], capture_output=True, check=False
            ).returncode
            == 0
        ):
            command = [arch, "-arm64", *command]
    return command


def read_codex_version(command: list[str], env: Mapping[str, str] | None = None) -> str:
    """Return and enforce the pinned Codex semantic version."""
    completed = subprocess.run(
        [*command, "--version"],
        env=dict(env) if env is not None else None,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AuthError(f"unable to execute pinned Codex: {completed.stderr.strip()}")
    match = re.fullmatch(r"codex-cli\s+([^\s]+)\s*", completed.stdout)
    if match is None or match.group(1) != CODEX_VERSION:
        observed = match.group(1) if match else completed.stdout.strip()
        raise AuthError(
            f"Codex version mismatch: expected {CODEX_VERSION}, got {observed}"
        )
    return match.group(1)


def require_chatgpt_account(result: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless app-server reports a managed ChatGPT account."""
    account = result.get("account")
    if not isinstance(account, Mapping):
        raise AuthError("Codex app-server did not report an authenticated account")
    account_type = account.get("type")
    if account_type != "chatgpt":
        raise AuthError(f"Codex account must be chatgpt, got {account_type!r}")
    if result.get("requiresOpenaiAuth") is not True:
        raise AuthError(
            "Codex app-server did not require managed OpenAI authentication"
        )
    # Only non-secret account metadata may leave this boundary.
    return {
        "type": "chatgpt",
        "plan_type": account.get("planType"),
        "requires_openai_auth": True,
    }


def require_model_catalog(
    result: Mapping[str, Any],
    *,
    model: str = "gpt-5.4",
    reasoning_effort: str = "high",
) -> dict[str, Any]:
    """Require one visible model entry with the requested reasoning effort."""
    models = result.get("data")
    if not isinstance(models, list):
        raise AuthError("Codex model catalog response is malformed")
    for entry in models:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("model") != model and entry.get("id") != model:
            continue
        efforts = entry.get("supportedReasoningEfforts") or []
        values = {
            item.get("reasoningEffort") if isinstance(item, Mapping) else item
            for item in efforts
        }
        if entry.get("hidden") is True or reasoning_effort not in values:
            raise AuthError(
                f"{model} is hidden or does not advertise {reasoning_effort} reasoning"
            )
        return {
            "requested": model,
            "observed": entry.get("model") or entry.get("id"),
            "hidden": bool(entry.get("hidden")),
            "reasoning_efforts": sorted(str(value) for value in values if value),
        }
    raise AuthError(f"{model} is unavailable in the personal ChatGPT model catalog")
