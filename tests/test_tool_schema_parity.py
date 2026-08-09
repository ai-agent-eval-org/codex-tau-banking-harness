from __future__ import annotations

import pytest
from tau2.domains.banking_knowledge.environment import get_db
from tau2.domains.banking_knowledge.retrieval_toolkits import KnowledgeToolsAllTools

from codex_tau.run import _alltools_contract
from codex_tau.tool_bridge import ToolBridgeError, ToolCatalog, dynamic_spec


def alltools_tools():
    toolkit = KnowledgeToolsAllTools(get_db(), object(), object(), object())
    return list(toolkit.get_tools().values())


def test_every_runtime_schema_survives_exact_conversion() -> None:
    tools = alltools_tools()
    catalog = ToolCatalog(tools)
    assert catalog.names == tuple(tool.name for tool in tools)
    assert "shell" in catalog.names
    assert "KB_search_bm25" in catalog.names
    assert "KB_search_dense" in catalog.names
    for tool in tools:
        original = tool.openai_schema["function"]
        converted = dynamic_spec(tool)
        assert converted["name"] == original["name"]
        assert converted["description"] == original["description"]
        assert converted["inputSchema"] == original["parameters"]


def test_unknown_and_invalid_calls_are_rejected() -> None:
    catalog = ToolCatalog(alltools_tools())
    with pytest.raises(ToolBridgeError, match="unknown"):
        catalog.validate_call("not_a_tau_tool", {}, "call-1")
    with pytest.raises(ToolBridgeError, match="malformed"):
        catalog.validate_call("get_user_information_by_id", {}, "call-2")


def test_alltools_uses_every_authoritative_schema_without_modification() -> None:
    direct_tools = alltools_tools()
    contract_tools, _ = _alltools_contract()
    assert [tool.name for tool in contract_tools] == [
        tool.name for tool in direct_tools
    ]
    assert {"KB_search_bm25", "KB_search_dense", "shell"} <= {
        tool.name for tool in contract_tools
    }
    catalog = ToolCatalog(contract_tools)
    for tool, converted in zip(contract_tools, catalog.specs, strict=True):
        authoritative = tool.openai_schema["function"]
        assert converted == {
            "type": "function",
            "name": authoritative["name"],
            "description": authoritative["description"],
            "inputSchema": authoritative["parameters"],
        }


def test_runtime_schema_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = alltools_tools()
    catalog = ToolCatalog(tools)
    original = tools[0].__class__.openai_schema

    def changed_schema(self):
        value = original.fget(self)
        value["function"]["description"] += " drift"
        return value

    monkeypatch.setattr(tools[0].__class__, "openai_schema", property(changed_schema))
    with pytest.raises(ToolBridgeError, match="changed at runtime"):
        catalog.validate_call(catalog.names[0], {}, "call-3")
