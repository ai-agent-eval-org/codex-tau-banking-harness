from __future__ import annotations

from pathlib import Path

import pytest
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
from tau2.data_model.simulation import (
    AgentInfo,
    Info,
    Results,
    SimulationRun,
    TerminationReason,
    UserInfo,
)
from tau2.environment.environment import EnvironmentInfo
from tau2.runner.helpers import get_tasks

from codex_tau.agent import CodexTauAgent
from codex_tau.manifest import ManifestError, read_manifest, write_manifest


def test_tau_messages_and_fake_trajectory_round_trip(tmp_path: Path) -> None:
    task = get_tasks(
        "banking_knowledge", task_split_name=None, task_ids=["task_001"]
    )[0]
    messages = [
        UserMessage.text("What card fits me?"),
        AssistantMessage.text(
            "",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="KB_search_bm25",
                    arguments={"query": "cash back card"},
                )
            ],
            cost=0.0,
        ),
        ToolMessage(id="call-1", role="tool", content="result"),
        AssistantMessage.text("Here is the documented option.", cost=0.0),
    ]
    run = SimulationRun(
        id="simulation-1",
        task_id=task.id,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:00:01",
        duration=1.0,
        termination_reason=TerminationReason.USER_STOP,
        messages=messages,
        trial=0,
        seed=300,
    )
    info = Info(
        git_commit="test",
        num_trials=1,
        max_steps=10,
        max_errors=2,
        user_info=UserInfo(
            implementation="user_simulator", llm="gpt-5.2", llm_args={}
        ),
        agent_info=AgentInfo(
            implementation="codex_tau_dynamic", llm="gpt-5.4", llm_args={}
        ),
        environment_info=EnvironmentInfo(
            domain_name="banking_knowledge", policy="policy"
        ),
        seed=300,
        retrieval_config="terminal_use",
    )
    results = Results(info=info, tasks=[task], simulations=[run])
    path = tmp_path / "results.json"
    path.write_text(results.model_dump_json(indent=2))
    loaded = Results.load(path)
    assert loaded.simulations[0].messages[1].tool_calls[0].id == "call-1"
    assert loaded.simulations[0].messages[2].id == "call-1"


def test_standard_fresh_conversation_greeting_is_accepted() -> None:
    agent = object.__new__(CodexTauAgent)
    greeting = AssistantMessage.text("Hi! How can I help you today?")
    state = agent.get_init_state([greeting])
    assert state.messages == [greeting]


def test_manifest_round_trip_and_secret_rejection(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = {
        "codex": {"authentication_mode": "chatgpt", "plan_type": "prolite"},
        "prompt": {"sha256": "a" * 64, "source_commit": "b" * 40},
    }
    write_manifest(path, manifest)
    assert read_manifest(path) == manifest
    with pytest.raises(ManifestError, match="secret-looking"):
        write_manifest(path, {"api_key": "do-not-write-this"})
    with pytest.raises(ManifestError, match="secret-looking"):
        write_manifest(path, {"value": "sk-" + ("a" * 20)})
