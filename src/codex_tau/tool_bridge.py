"""Authoritative τ-bench Tool to Codex dynamic-tool conversion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from tau2.data_model.message import MultiToolMessage, ToolCall, ToolMessage
from tau2.environment.tool import Tool


class ToolBridgeError(RuntimeError):
    """A dynamic call violated the authoritative τ-bench tool contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def dynamic_spec(tool: Tool) -> dict[str, Any]:
    """Convert the untouched OpenAI schema exported by a τ-bench Tool."""
    schema = tool.openai_schema
    if schema.get("type") != "function" or not isinstance(
        schema.get("function"), Mapping
    ):
        raise ToolBridgeError(f"{tool.name}: unsupported τ-bench schema")
    function = schema["function"]
    if function.get("name") != tool.name:
        raise ToolBridgeError(f"{tool.name}: schema name mismatch")
    parameters = function.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ToolBridgeError(f"{tool.name}: missing parameter schema")
    try:
        Draft202012Validator.check_schema(parameters)
    except SchemaError as exc:
        raise ToolBridgeError(f"{tool.name}: invalid JSON schema") from exc
    return {
        "type": "function",
        "name": function["name"],
        "description": function.get("description", ""),
        "inputSchema": parameters,
    }


class ToolCatalog:
    """Immutable-at-ingress view with runtime drift checks before every call."""

    def __init__(self, tools: Iterable[Tool]):
        self._tools = tuple(tools)
        self._by_name = {tool.name: tool for tool in self._tools}
        if len(self._by_name) != len(self._tools):
            raise ToolBridgeError("τ-bench supplied duplicate tool names")
        self.specs = tuple(dynamic_spec(tool) for tool in self._tools)
        self.hash = canonical_hash(self.specs)
        self.names = tuple(tool.name for tool in self._tools)

    def _require_unchanged(self) -> None:
        current = tuple(dynamic_spec(tool) for tool in self._tools)
        if canonical_hash(current) != self.hash:
            raise ToolBridgeError("authoritative τ-bench tool schemas changed at runtime")

    def validate_call(self, name: str, arguments: Any, call_id: str) -> ToolCall:
        self._require_unchanged()
        tool = self._by_name.get(name)
        if tool is None:
            raise ToolBridgeError(f"unknown dynamic tool: {name}")
        if not isinstance(arguments, Mapping):
            raise ToolBridgeError(f"{name}: arguments must be a JSON object")
        parameters = tool.openai_schema["function"]["parameters"]
        try:
            Draft202012Validator(parameters).validate(dict(arguments))
        except ValidationError as exc:
            raise ToolBridgeError(f"{name}: malformed arguments: {exc.message}") from exc
        return ToolCall(
            id=call_id,
            name=name,
            arguments=dict(arguments),
            requestor="assistant",
        )


@dataclass(frozen=True)
class PendingCall:
    request_id: str | int
    call_id: str
    name: str
    arguments: dict[str, Any]


class ToolCallBroker:
    """Preserve request/call identity and ordering across the τ-bench boundary."""

    def __init__(self, catalog: ToolCatalog):
        self.catalog = catalog
        self._pending: list[PendingCall] = []

    def accept(self, request_id: str | int, params: Mapping[str, Any]) -> ToolCall:
        call_id = params.get("callId")
        name = params.get("tool")
        arguments = params.get("arguments")
        if not isinstance(call_id, str) or not isinstance(name, str):
            raise ToolBridgeError("malformed item/tool/call request")
        call = self.catalog.validate_call(name, arguments, call_id)
        self._pending.append(
            PendingCall(request_id, call_id, name, dict(call.arguments))
        )
        return call

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def resolve(
        self, message: ToolMessage | MultiToolMessage
    ) -> list[tuple[str | int, dict[str, Any]]]:
        results = (
            message.tool_messages
            if isinstance(message, MultiToolMessage)
            else [message]
        )
        by_id = {result.id: result for result in results}
        if len(by_id) != len(results):
            raise ToolBridgeError("duplicate τ-bench tool result IDs")
        expected = [call.call_id for call in self._pending]
        if set(by_id) != set(expected) or len(results) != len(expected):
            raise ToolBridgeError(
                f"tool result IDs do not match pending calls: expected {expected}"
            )
        responses: list[tuple[str | int, dict[str, Any]]] = []
        for call in self._pending:
            result = by_id[call.call_id]
            responses.append(
                (
                    call.request_id,
                    {
                        "contentItems": [
                            {"type": "inputText", "text": result.content or ""}
                        ],
                        "success": not result.error,
                    },
                )
            )
        self._pending.clear()
        return responses

