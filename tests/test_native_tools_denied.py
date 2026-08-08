from __future__ import annotations

import queue
from pathlib import Path

import pytest

from codex_tau.app_server import CodexAppServer, ProtocolError, reject_native_item


class FakeTransport:
    def __init__(self, messages: list[dict]):
        self.inbox = queue.Queue()
        self.stderr_line_count = 0
        for message in messages:
            self.inbox.put(message)

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    "item_type",
    [
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "webSearch",
        "imageView",
        "imageGeneration",
        "plan",
        "collabAgentToolCall",
        "hookPrompt",
    ],
)
def test_every_native_capability_item_fails_closed(item_type: str) -> None:
    with pytest.raises(ProtocolError, match="denied native"):
        reject_native_item({"type": item_type})


def test_tau_dynamic_tool_item_is_the_only_tool_item_allowed() -> None:
    reject_native_item({"type": "dynamicToolCall"})


def test_disabled_remote_control_status_is_lifecycle_only() -> None:
    transport = FakeTransport(
        [
            {
                "method": "remoteControl/status/changed",
                "params": {"status": "disabled"},
            },
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": "done",
                    }
                },
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"status": "completed"}},
            },
        ]
    )
    runtime = CodexAppServer(
        repo_root=Path("."),
        tools=[],
        system_prompt="prompt",
        transport=transport,  # type: ignore[arg-type]
    )
    assert runtime._wait_for_output() == ("done", True)
    assert runtime.audit["remote_control_statuses"] == ["disabled"]


def test_enabled_remote_control_status_fails_closed() -> None:
    transport = FakeTransport(
        [
            {
                "method": "remoteControl/status/changed",
                "params": {"status": "connected"},
            }
        ]
    )
    runtime = CodexAppServer(
        repo_root=Path("."),
        tools=[],
        system_prompt="prompt",
        transport=transport,  # type: ignore[arg-type]
    )
    with pytest.raises(ProtocolError, match="remote control"):
        runtime._wait_for_output()


def test_stalled_turn_reports_last_protocol_boundary() -> None:
    snapshots: list[dict] = []
    transport = FakeTransport([])
    runtime = CodexAppServer(
        repo_root=Path("."),
        tools=[],
        system_prompt="prompt",
        transport=transport,  # type: ignore[arg-type]
        audit_sink=snapshots.append,
    )
    runtime.audit["last_protocol_method"] = "turn/start:accepted"
    with pytest.raises(ProtocolError, match="turn/start:accepted"):
        runtime._wait_for_output(timeout=0)
    assert snapshots[-1]["last_protocol_method"] == "turn/output:timed_out"
    assert snapshots[-1]["timeout_after_protocol_method"] == "turn/start:accepted"
    assert snapshots[-1]["app_server_stderr_line_count"] == 0


def test_incomplete_dynamic_tool_delivery_fails_closed() -> None:
    snapshots: list[dict] = []
    runtime = CodexAppServer(
        repo_root=Path("."),
        tools=[],
        system_prompt="prompt",
        transport=FakeTransport([]),  # type: ignore[arg-type]
        audit_sink=snapshots.append,
    )
    runtime.audit["dynamic_call_count"] = 1
    with pytest.raises(ProtocolError, match="incomplete dynamic-tool"):
        runtime.require_complete_tool_delivery()
    assert snapshots[-1]["tool_result_delivery_complete"] is False
    assert snapshots[-1]["pending_dynamic_call_count"] == 0
