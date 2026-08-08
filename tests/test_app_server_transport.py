from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

from codex_tau.app_server import (
    APP_SERVER_STREAM_READER_LIMIT_BYTES,
    JsonRpcProcess,
)


def test_stream_reader_budget_is_liberal_but_bounded() -> None:
    assert APP_SERVER_STREAM_READER_LIMIT_BYTES == 64 * 1024 * 1024


def test_json_rpc_transport_accepts_line_above_asyncio_default(
    tmp_path: Path,
) -> None:
    payload_size = 128 * 1024
    child_code = (
        "import json; "
        f"print(json.dumps({{'method':'probe','params':{{'text':'x'*{payload_size}}}}}), "
        "flush=True)"
    )
    transport = JsonRpcProcess(
        [sys.executable, "-c", child_code], tmp_path, os.environ
    )
    try:
        message = transport.inbox.get(timeout=5)
        assert message["method"] == "probe"
        assert len(message["params"]["text"]) == payload_size
    finally:
        transport.close()


def test_unexpected_stdout_close_is_reported_without_watchdog(
    tmp_path: Path,
) -> None:
    transport = JsonRpcProcess(
        [sys.executable, "-c", "pass"], tmp_path, os.environ
    )
    try:
        message = transport.inbox.get(timeout=5)
        assert "stdout closed unexpectedly" in message["transportError"]
    except queue.Empty as exc:  # pragma: no cover - makes failure diagnostic explicit
        raise AssertionError("transport did not report subprocess exit") from exc
    finally:
        transport.close()
