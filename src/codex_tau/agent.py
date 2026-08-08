"""τ-bench HalfDuplexAgent backed by one isolated Codex app-server thread."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tau2.agent.base_agent import (
    HalfDuplexAgent,
    ValidAgentInputMessage,
    is_valid_agent_history_message,
)
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
from .prompt import (
    OPTIMIZED_PROMPT_MODE,
    STANDARD_PROMPT_MODE,
    PromptSpec,
    optimized_prompt_spec,
    standard_prompt_spec,
)


class CodexAgentState(BaseModel):
    """Serializable conversation history; live app-server state stays private."""

    messages: list[Message] = Field(default_factory=list)


def audit_filename(task_id: str, seed: int) -> str:
    """Return the stable per-trajectory audit filename."""
    return f"{task_id}--seed-{seed}.json"


class CodexTauAgent(HalfDuplexAgent[CodexAgentState]):
    """Translate participant messages without executing any tool itself."""

    def __init__(
        self,
        *,
        tools: list[Tool],
        domain_policy: str,
        repo_root: Path,
        task_id: str,
        audit_path: Path,
        prompt_spec: PromptSpec,
        runtime_factory: type[CodexAppServer] = CodexAppServer,
    ):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.task_id = task_id
        self.audit_path = audit_path
        self.runtime = runtime_factory(
            repo_root=repo_root,
            tools=tools,
            system_prompt=prompt_spec.system_prompt,
            audit_sink=self._write_audit,
        )
        self.runtime.audit.update(
            {
                "agent_instruction_sha256": (
                    prompt_spec.agent_instruction_sha256
                ),
                "effective_system_prompt_sha256": (
                    prompt_spec.effective_system_prompt_sha256
                ),
                "prompt_mode": prompt_spec.mode,
                "prompt_source_path": prompt_spec.source_path,
                "task_id": task_id,
            }
        )
        self._checkpoint("agent_initialized")

    def _write_audit(self, audit: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.audit_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.audit_path)

    def _checkpoint(self, stage: str) -> None:
        self.runtime.audit["adapter_stage"] = stage
        self._write_audit(self.runtime.audit)

    def set_seed(self, seed: int) -> None:
        """Bind the audit to τ-bench's per-trial simulation seed."""
        final_path = self.audit_path.parent / audit_filename(self.task_id, seed)
        if final_path.exists() and final_path != self.audit_path:
            raise ValueError(f"duplicate audit path for {self.task_id} seed {seed}")
        if self.audit_path.exists() and final_path != self.audit_path:
            self.audit_path.replace(final_path)
        self.audit_path = final_path
        self.runtime.audit["simulation_seed"] = seed
        self._checkpoint("seed_assigned")

    def get_init_state(
        self, message_history: list[Message] | None = None
    ) -> CodexAgentState:
        history = list(message_history or [])
        if not all(is_valid_agent_history_message(message) for message in history):
            raise ValueError("invalid initial τ-bench agent history")
        # A fresh half-duplex simulation begins with τ-bench's standard assistant
        # greeting. The isolated Codex thread begins on the following user turn;
        # retaining the greeting here keeps the official trajectory serializable.
        if len(history) > 1 or any(
            isinstance(message, AssistantMessage) and message.is_tool_call()
            for message in history
        ):
            raise ValueError("CodexTauAgent does not resume prior tool conversations")
        return CodexAgentState(messages=history)

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: CodexAgentState
    ) -> tuple[AssistantMessage, CodexAgentState]:
        if isinstance(message, UserMessage):
            if not isinstance(message.content, str):
                raise ValueError("CodexTauAgent requires a text user message")
            self._checkpoint("agent_turn_starting")
            output, finished = self.runtime.start_turn(message.content)
            state.messages.append(message)
        elif isinstance(message, (ToolMessage, MultiToolMessage)):
            self._checkpoint("tool_result_returning")
            output, finished = self.runtime.continue_turn(message)
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
        else:  # pragma: no cover - protected by τ-bench's participant type
            raise TypeError(f"unsupported input message: {type(message).__name__}")

        self._checkpoint("agent_output_returned")
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
            self.runtime.require_complete_tool_delivery()
            self._checkpoint("stopped")
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
    expected_repo_root = Path(__file__).resolve().parents[2]
    if repo_root != expected_repo_root:
        raise ValueError("Codex agent repo_root must be the harness repository")
    audit_dir = Path(str(llm_args["audit_dir"])).resolve()
    prompt_mode = llm_args.get("prompt_mode")
    if prompt_mode == STANDARD_PROMPT_MODE:
        if set(llm_args) != {"repo_root", "audit_dir", "prompt_mode"}:
            raise ValueError("the vanilla agent accepts only its fixed llm_args")
        prompt_spec = standard_prompt_spec(domain_policy)
    elif prompt_mode == OPTIMIZED_PROMPT_MODE:
        if set(llm_args) != {
            "repo_root",
            "audit_dir",
            "prompt_mode",
            "agent_instruction_path",
            "agent_instruction_sha256",
        }:
            raise ValueError("the optimized agent accepts only its fixed llm_args")
        prompt_path = llm_args.get("agent_instruction_path")
        prompt_sha256 = llm_args.get("agent_instruction_sha256")
        if not isinstance(prompt_path, str) or not isinstance(prompt_sha256, str):
            raise ValueError("the optimized prompt requires a path and SHA-256")
        prompt_spec = optimized_prompt_spec(
            repo_root=repo_root,
            domain_policy=domain_policy,
            relative_path=prompt_path,
            expected_sha256=prompt_sha256,
        )
    else:
        raise ValueError(f"unknown prompt mode: {prompt_mode!r}")
    pending_audit = audit_dir / f"{task.id}--pending-{uuid.uuid4().hex}.json"
    return CodexTauAgent(
        tools=tools,
        domain_policy=domain_policy,
        repo_root=repo_root,
        task_id=task.id,
        audit_path=pending_audit,
        prompt_spec=prompt_spec,
    )
