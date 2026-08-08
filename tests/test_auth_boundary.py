from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codex_tau.app_server import JsonRpcProcess
from codex_tau.auth import (
    AuthError,
    read_codex_version,
    require_chatgpt_account,
    resolve_codex_command,
    sanitized_child_environment,
)


def test_platform_credentials_are_stripped() -> None:
    child = sanitized_child_environment(
        {
            "PATH": "/bin",
            "OPENAI_API_KEY": "secret",
            "CODEX_API_KEY": "secret",
            "OPENAI_ACCESS_TOKEN": "secret",
            "CODEX_SESSION_TOKEN": "secret",
            "UNRELATED": "preserved",
        }
    )
    assert child == {"PATH": "/bin", "UNRELATED": "preserved"}


def test_chatgpt_account_is_required() -> None:
    result = require_chatgpt_account(
        {
            "account": {"type": "chatgpt", "planType": "prolite"},
            "requiresOpenaiAuth": True,
        }
    )
    assert result == {
        "type": "chatgpt",
        "plan_type": "prolite",
        "requires_openai_auth": True,
    }
    with pytest.raises(AuthError, match="must be chatgpt"):
        require_chatgpt_account(
            {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True}
        )
    with pytest.raises(AuthError, match="did not report"):
        require_chatgpt_account({"account": None, "requiresOpenaiAuth": True})


def test_codex_version_mismatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "codex-cli 0.0.1\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AuthError, match="version mismatch"):
        read_codex_version(["codex"])


def test_pinned_strict_configuration_is_accepted(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    codex_home = tmp_path / "home"
    empty_cwd = tmp_path / "cwd"
    codex_home.mkdir()
    empty_cwd.mkdir()
    shutil.copyfile(repo_root / "codex/config.toml", codex_home / "config.toml")
    child = sanitized_child_environment()
    child["CODEX_HOME"] = str(codex_home)
    transport = JsonRpcProcess(resolve_codex_command(repo_root), empty_cwd, child)
    try:
        result = transport.request(
            "initialize",
            {
                "clientInfo": {"name": "config-contract-test", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        assert isinstance(result, dict)
    finally:
        transport.close()
