from __future__ import annotations

import queue
from pathlib import Path

import pytest

from codex_tau.app_server import CodexAppServer, ProtocolError, reject_native_item


class FakeTransport:
    def __init__(self, messages: list[dict]):
        self.inbox = queue.Queue()
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
        domain_policy="policy",
        prompt="prompt",
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
        domain_policy="policy",
        prompt="prompt",
        transport=transport,  # type: ignore[arg-type]
    )
    with pytest.raises(ProtocolError, match="remote control"):
        runtime._wait_for_output()
