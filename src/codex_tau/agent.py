"""τ-bench HalfDuplexAgent backed by one isolated Codex app-server thread."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.tasks import Task
from tau2.environment.tool import Tool

from .app_server import CodexAppServer


class CodexAgentState(BaseModel):
    """Serializable conversation history; live app-server state stays private."""

    messages: list[Message] = Field(default_factory=list)


class CodexTauAgent(HalfDuplexAgent[CodexAgentState]):
    """Translate participant messages without executing any tool itself."""

    def __init__(
        self,
        *,
        tools: list[Tool],
        domain_policy: str,
        repo_root: Path,
        prompt: str,
        audit_path: Path,
        runtime_factory: type[CodexAppServer] = CodexAppServer,
    ):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.audit_path = audit_path
        self.runtime = runtime_factory(
            repo_root=repo_root,
            tools=tools,
            domain_policy=domain_policy,
            prompt=prompt,
        )

    def get_init_state(
        self, message_history: list[Message] | None = None
    ) -> CodexAgentState:
        if message_history:
            raise ValueError("CodexTauAgent requires a fresh app-server thread")
        return CodexAgentState()

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: CodexAgentState
    ) -> tuple[AssistantMessage, CodexAgentState]:
        if isinstance(message, UserMessage):
            if not isinstance(message.content, str):
                raise ValueError("CodexTauAgent requires a text user message")
            output, finished = self.runtime.start_turn(message.content)
            state.messages.append(message)
        elif isinstance(message, (ToolMessage, MultiToolMessage)):
            output, finished = self.runtime.continue_turn(message)
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
        else:  # pragma: no cover - protected by τ-bench's participant type
            raise TypeError(f"unsupported input message: {type(message).__name__}")

        if finished:
            if not isinstance(output, str):
                raise TypeError("final Codex output was not text")
            assistant = AssistantMessage.text(output, cost=0.0)
        else:
            if not isinstance(output, list) or not output:
                raise TypeError("Codex dynamic-tool output was empty")
            assistant = AssistantMessage.text("", tool_calls=output, cost=0.0)
        state.messages.append(assistant)
        return assistant, state

    def stop(
        self,
        message: ValidAgentInputMessage | None = None,
        state: CodexAgentState | None = None,
    ) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self.audit_path.write_text(
                json.dumps(self.runtime.audit, indent=2, sort_keys=True) + "\n"
            )
        finally:
            self.runtime.close()


def create_codex_tau_agent(
    *,
    tools: list[Tool],
    domain_policy: str,
    llm: str | None = None,
    llm_args: dict[str, Any] | None = None,
    task: Task | None = None,
    **_: Any,
) -> CodexTauAgent:
    """τ-bench registry factory with explicit model and file inputs."""
    if llm != "gpt-5.4":
        raise ValueError(f"evaluated agent model must be gpt-5.4, got {llm!r}")
    if task is None or llm_args is None:
        raise ValueError("Codex agent factory requires task and llm_args")
    repo_root = Path(str(llm_args["repo_root"])).resolve()
    audit_dir = Path(str(llm_args["audit_dir"])).resolve()
    prompt = llm_args.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("Codex agent factory requires a non-empty prompt")
    return CodexTauAgent(
        tools=tools,
        domain_policy=domain_policy,
        repo_root=repo_root,
        prompt=prompt,
        audit_path=audit_dir / f"{task.id}.json",
    )

