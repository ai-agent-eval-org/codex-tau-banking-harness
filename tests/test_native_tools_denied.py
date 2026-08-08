from __future__ import annotations

import pytest

from codex_tau.app_server import ProtocolError, reject_native_item


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

