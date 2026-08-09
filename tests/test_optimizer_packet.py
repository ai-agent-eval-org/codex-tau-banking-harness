from __future__ import annotations

import pytest

from codex_tau.optimizer_packet import OptimizerPacketError, sanitize_message


def test_sanitize_message_preserves_model_visible_exchange_only() -> None:
    message = {
        "id": "call-1",
        "role": "tool",
        "content": "delivered result",
        "requestor": "assistant",
        "error": False,
        "tool_calls": None,
        "raw_data": {"hidden": "provider response"},
        "audio_script_gold": "hidden expected wording",
        "usage": {"prompt_tokens": 123},
        "cost": 1.25,
        "timestamp": "2026-08-09T00:00:00Z",
    }

    assert sanitize_message(message) == {
        "id": "call-1",
        "role": "tool",
        "content": "delivered result",
        "requestor": "assistant",
        "error": False,
    }


def test_sanitize_message_rejects_unknown_roles() -> None:
    with pytest.raises(OptimizerPacketError, match="invalid role"):
        sanitize_message({"role": "grader", "content": "hidden"})
