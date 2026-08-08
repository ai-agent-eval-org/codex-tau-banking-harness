from __future__ import annotations

from tau2.data_model.message import MultiToolMessage, ToolMessage
from tau2.domains.banking_knowledge.environment import get_db
from tau2.domains.banking_knowledge.retrieval_toolkits import KnowledgeToolsAllTools

from codex_tau.tool_bridge import ToolCallBroker, ToolCatalog


def broker() -> ToolCallBroker:
    toolkit = KnowledgeToolsAllTools(get_db(), object(), object(), object())
    return ToolCallBroker(ToolCatalog(toolkit.get_tools().values()))


def test_single_call_round_trip_preserves_callback_id() -> None:
    value = broker()
    call = value.accept(
        41,
        {
            "callId": "call-a",
            "tool": "get_user_information_by_id",
            "arguments": {"user_id": "123"},
        },
    )
    assert call.id == "call-a"
    assert call.name == "get_user_information_by_id"
    responses = value.resolve(
        ToolMessage(
            id="call-a",
            role="tool",
            content='{"name":"Ada"}',
            requestor="assistant",
        )
    )
    assert responses == [
        (
            41,
            {
                "contentItems": [
                    {"type": "inputText", "text": '{"name":"Ada"}'}
                ],
                "success": True,
            },
        )
    ]


def test_parallel_calls_keep_request_order_despite_result_order() -> None:
    value = broker()
    first = value.accept(
        "rpc-a",
        {
            "callId": "call-a",
            "tool": "get_user_information_by_id",
            "arguments": {"user_id": "123"},
        },
    )
    second = value.accept(
        "rpc-b",
        {
            "callId": "call-b",
            "tool": "get_user_information_by_email",
            "arguments": {"email": "ada@example.com"},
        },
    )
    message = MultiToolMessage(
        role="tool",
        tool_messages=[
            ToolMessage(id=second.id, role="tool", content="second"),
            ToolMessage(id=first.id, role="tool", content="first"),
        ],
    )
    responses = value.resolve(message)
    assert [request_id for request_id, _ in responses] == ["rpc-a", "rpc-b"]
    assert [response["contentItems"][0]["text"] for _, response in responses] == [
        "first",
        "second",
    ]

