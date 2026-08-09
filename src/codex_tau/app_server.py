"""Fail-closed JSON-RPC client for the pinned Codex app-server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from tau2.data_model.message import MultiToolMessage, ToolCall, ToolMessage

from .auth import (
    AuthError,
    default_auth_file,
    read_codex_version,
    require_chatgpt_account,
    require_model_catalog,
    resolve_codex_command,
    sanitized_child_environment,
)
from .tool_bridge import ToolCallBroker, ToolCatalog


class ProtocolError(RuntimeError):
    """The app-server emitted a denied or malformed protocol message."""


_ALLOWED_ITEM_TYPES = frozenset(
    {"userMessage", "agentMessage", "reasoning", "dynamicToolCall"}
)
# App-server lifecycle events echo complete dynamic-tool results. The banking
# corpus is currently under 8 MiB, so 64 MiB is deliberately generous while
# still bounding memory if a shell command produces pathological output. This
# is a StreamReader line limit, not an eager allocation.
APP_SERVER_STREAM_READER_LIMIT_BYTES = 64 * 1024 * 1024
TURN_OUTPUT_TIMEOUT_SECONDS = 600
TURN_OUTPUT_IDLE_TIMEOUT_SECONDS = 120


def reject_native_item(
    item: Mapping[str, Any],
    allowed_item_types: frozenset[str] = _ALLOWED_ITEM_TYPES,
) -> None:
    """Reject every app-server item outside the benchmark's narrow protocol."""
    item_type = item.get("type")
    if item_type not in allowed_item_types:
        raise ProtocolError(f"denied native Codex item observed: {item_type!r}")


class JsonRpcProcess:
    """Asyncio subprocess transport presented through a synchronous boundary."""

    def __init__(
        self,
        command: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        app_server_args: tuple[str, ...] = (),
    ):
        self.inbox: queue.Queue[Mapping[str, Any]] = queue.Queue()
        self.stderr_line_count = 0
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._process: asyncio.subprocess.Process | None = None
        self._closing = False
        self._pending: dict[str | int, asyncio.Future[Mapping[str, Any]]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        future = asyncio.run_coroutine_threadsafe(
            self._start(command, cwd, env, app_server_args), self._loop
        )
        future.result(timeout=30)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start(
        self,
        command: list[str],
        cwd: Path,
        env: Mapping[str, str],
        app_server_args: tuple[str, ...],
    ) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *command,
            "app-server",
            *app_server_args,
            "--strict-config",
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=APP_SERVER_STREAM_READER_LIMIT_BYTES,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while await self._process.stderr.readline():
                # stderr can contain sensitive provider diagnostics, so retain only
                # a count for timeout diagnostics rather than the lines themselves.
                self.stderr_line_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing:
                self.inbox.put(
                    {
                        "transportError": "Codex app-server stderr reader failed "
                        f"with {type(exc).__name__}"
                    }
                )

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        reached_eof = False
        try:
            while line := await self._process.stdout.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.inbox.put({"transportError": "non-JSON app-server output"})
                    continue
                if "id" in message and "method" not in message:
                    pending = self._pending.pop(message["id"], None)
                    if pending is not None and not pending.done():
                        pending.set_result(message)
                else:
                    self.inbox.put(message)
            reached_eof = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing:
                self.inbox.put(
                    {
                        "transportError": "Codex app-server stdout reader failed "
                        f"with {type(exc).__name__}"
                    }
                )
        finally:
            for pending in self._pending.values():
                if not pending.done():
                    pending.set_exception(
                        ProtocolError("Codex app-server exited while awaiting response")
                    )
            if reached_eof and not self._closing:
                returncode = self._process.returncode
                self.inbox.put(
                    {
                        "transportError": "Codex app-server stdout closed unexpectedly; "
                        f"return code was {returncode!r}"
                    }
                )

    async def _send(self, message: Mapping[str, Any]) -> None:
        if self._process is None or self._process.returncode is not None:
            raise ProtocolError("Codex app-server exited unexpectedly")
        assert self._process.stdin is not None
        encoded = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        self._process.stdin.write(encoded)
        await self._process.stdin.drain()

    async def _request(self, method: str, params: Any, timeout: float) -> Any:
        request_id = self._next_id
        self._next_id += 1
        response_future = self._loop.create_future()
        self._pending[request_id] = response_future
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)
        try:
            response = await asyncio.wait_for(response_future, timeout)
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            error = response["error"]
            detail = error.get("message") if isinstance(error, Mapping) else "unknown"
            raise ProtocolError(f"{method} failed: {detail}")
        return response.get("result")

    def notify(self, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        asyncio.run_coroutine_threadsafe(self._send(message), self._loop).result(30)

    def request(self, method: str, params: Any = None, timeout: float = 60) -> Any:
        future = asyncio.run_coroutine_threadsafe(
            self._request(method, params, timeout), self._loop
        )
        try:
            return future.result(timeout + 5)
        except TimeoutError as exc:
            raise ProtocolError(f"timed out waiting for {method}") from exc

    def respond(self, request_id: str | int, result: Mapping[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._send({"id": request_id, "result": result}), self._loop
        )
        future.result(30)

    async def _close(self) -> None:
        self._closing = True
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), 5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task),
            return_exceptions=True,
        )

    def close(self) -> None:
        if self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._close(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class CodexAppServer:
    """One isolated app-server/thread for one τ-bench simulation."""

    def __init__(
        self,
        *,
        repo_root: Path,
        tools: list[Any],
        system_prompt: str,
        model: str = "gpt-5.4",
        reasoning_effort: str = "high",
        enable_optimizer_code_mode: bool = False,
        allowed_item_types: frozenset[str] = _ALLOWED_ITEM_TYPES,
        turn_output_timeout_seconds: float = TURN_OUTPUT_TIMEOUT_SECONDS,
        turn_output_idle_timeout_seconds: float = TURN_OUTPUT_IDLE_TIMEOUT_SECONDS,
        auth_file: Path | None = None,
        transport: JsonRpcProcess | None = None,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ):
        self.repo_root = repo_root
        self.catalog = ToolCatalog(tools)
        self.broker = ToolCallBroker(self.catalog)
        self._temporary_home: tempfile.TemporaryDirectory[str] | None = None
        self._temporary_cwd: tempfile.TemporaryDirectory[str] | None = None
        self._closed = False
        self._thread_id: str | None = None
        self._turn_id: str | None = None
        self._final_text: str | None = None
        self._expected_cwd: str | None = None
        self._audit_sink = audit_sink
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._enable_optimizer_code_mode = enable_optimizer_code_mode
        if enable_optimizer_code_mode and (
            model != "gpt-5.6-sol" or reasoning_effort != "max"
        ):
            raise ProtocolError(
                "optimizer Code Mode is restricted to GPT-5.6-Sol/max"
            )
        self._allowed_item_types = allowed_item_types
        self._turn_output_timeout_seconds = turn_output_timeout_seconds
        self._turn_output_idle_timeout_seconds = turn_output_idle_timeout_seconds
        self.audit: dict[str, Any] = {
            "base_instructions_sha256": hashlib.sha256(
                system_prompt.encode()
            ).hexdigest(),
            "context_compaction_count": 0,
            "optimizer_code_mode_enabled": enable_optimizer_code_mode,
            "optimizer_code_mode_host": "local" if enable_optimizer_code_mode else None,
            "developer_instructions_empty": True,
            "dynamic_call_count": 0,
            "dynamic_call_names": [],
            "last_protocol_method": None,
            "native_capability_denied": False,
            "model_rerouted": False,
            "requested_model": model,
            "reasoning_effort": reasoning_effort,
            "protocol_event_count": 0,
            "remote_control_statuses": [],
            "transport_stream_reader_limit_bytes": (
                APP_SERVER_STREAM_READER_LIMIT_BYTES
            ),
            "tool_results_returned": 0,
            "thread_settings_update_count": 0,
            "thread_settings_preflight_verified": False,
            "thread_settings_verified": False,
            "turns_completed": 0,
            "turns_started": 0,
            "warning_count": 0,
            "warning_sha256": [],
        }

        if transport is not None:
            self.transport = transport
            return

        command = resolve_codex_command(repo_root)
        child_env = sanitized_child_environment()
        read_codex_version(command, child_env)
        source_auth = auth_file or default_auth_file()
        if not source_auth.is_file():
            raise AuthError(f"personal ChatGPT auth file is missing: {source_auth}")
        self._temporary_home = tempfile.TemporaryDirectory(prefix="codex-tau-home-")
        self._temporary_cwd = tempfile.TemporaryDirectory(prefix="codex-tau-cwd-")
        home = Path(self._temporary_home.name)
        shutil.copyfile(repo_root / "codex" / "config.toml", home / "config.toml")
        os.symlink(source_auth.resolve(), home / "auth.json")
        child_env["CODEX_HOME"] = str(home)
        app_server_args = (
            ("--enable", "code_mode", "--enable", "code_mode_host")
            if enable_optimizer_code_mode
            else ()
        )
        self.transport = JsonRpcProcess(
            command,
            Path(self._temporary_cwd.name),
            child_env,
            app_server_args=app_server_args,
        )
        self._initialize(system_prompt)

    def _checkpoint(self, method: str | None = None) -> None:
        if method is not None:
            self.audit["last_protocol_method"] = method
            self.audit["protocol_event_count"] += 1
        if self._audit_sink is not None:
            self._audit_sink(dict(self.audit))

    def _initialize(self, system_prompt: str) -> None:
        self.transport.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-tau-banking-harness",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        account = self.transport.request("account/read", {"refreshToken": False})
        self.audit["account"] = require_chatgpt_account(account)
        model_result = self.transport.request(
            "model/list", {"includeHidden": True, "limit": 100}
        )
        self.audit["model"] = require_model_catalog(
            model_result,
            model=self._model,
            reasoning_effort=self._reasoning_effort,
        )
        rate_limits = self._read_rate_limits()
        buckets = (
            rate_limits.get("rateLimitsByLimitId")
            if isinstance(rate_limits, Mapping)
            else None
        )
        self.audit["rate_limit_ids"] = (
            sorted(buckets) if isinstance(buckets, Mapping) else []
        )

        empty_cwd = str(Path(self._temporary_cwd.name).resolve())
        self._expected_cwd = empty_cwd
        thread = self.transport.request(
            "thread/start",
            {
                "model": self._model,
                "cwd": empty_cwd,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "personality": "none",
                "allowProviderModelFallback": False,
                "ephemeral": True,
                "baseInstructions": system_prompt,
                # An explicit empty string suppresses app-server collaboration-mode
                # developer instructions; null means "use built-ins".
                "developerInstructions": "",
                "dynamicTools": list(self.catalog.specs),
                "environments": [],
                "runtimeWorkspaceRoots": [],
                "selectedCapabilityRoots": [],
                "experimentalRawEvents": False,
            },
            timeout=120,
        )
        sources = thread.get("instructionSources", [])
        if sources:
            raise ProtocolError(f"unexpected discovered instruction sources: {sources}")
        observed_model = thread.get("model")
        if observed_model != self._model:
            raise ProtocolError(f"thread model mismatch: {observed_model!r}")
        thread_value = thread.get("thread")
        if not isinstance(thread_value, Mapping) or not isinstance(
            thread_value.get("id"), str
        ):
            raise ProtocolError("thread/start returned no thread ID")
        self._thread_id = thread_value["id"]
        self.audit["instruction_sources"] = []
        self.audit["observed_thread_model"] = observed_model
        self._checkpoint("thread/start:accepted")

    def _read_rate_limits(self) -> Any:
        """Retry transient ChatGPT metadata failures before starting a task."""
        for attempt in range(3):
            try:
                return self.transport.request("account/rateLimits/read")
            except ProtocolError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (2**attempt))
        raise AssertionError("unreachable")

    def _accept_thread_settings_update(self, params: Mapping[str, Any]) -> None:
        """Verify the effective settings notification emitted by turn overrides."""
        settings = params.get("threadSettings")
        if params.get("threadId") != self._thread_id or not isinstance(
            settings, Mapping
        ):
            raise ProtocolError("thread settings update is malformed or mis-scoped")
        expected = {
            "model": self._model,
            "effort": self._reasoning_effort,
            "approvalPolicy": "never",
            "personality": "none",
        }
        for field, value in expected.items():
            if settings.get(field) != value:
                raise ProtocolError(
                    f"thread settings drift for {field}: {settings.get(field)!r}"
                )
        sandbox = settings.get("sandboxPolicy")
        if not isinstance(sandbox, Mapping) or sandbox.get("type") != "readOnly":
            raise ProtocolError("thread settings drift for sandboxPolicy")
        if self._expected_cwd is not None and settings.get("cwd") != self._expected_cwd:
            raise ProtocolError("thread settings drift for cwd")
        collaboration = settings.get("collaborationMode")
        if isinstance(collaboration, Mapping):
            collaboration_settings = collaboration.get("settings")
            if isinstance(
                collaboration_settings, Mapping
            ) and collaboration_settings.get("developerInstructions") not in {None, ""}:
                raise ProtocolError("thread settings introduced developer instructions")
        self.audit["thread_settings_update_count"] += 1
        self.audit["thread_settings_verified"] = True
        self._checkpoint("thread/settings/updated:verified")

    def _accept_warning(self, params: Mapping[str, Any]) -> None:
        """Audit an official non-fatal runtime warning without retaining its text."""
        thread_id = params.get("threadId")
        message = params.get("message")
        if thread_id not in {None, self._thread_id}:
            raise ProtocolError("app-server warning is mis-scoped")
        if not isinstance(message, str) or not message or len(message) > 10_000:
            raise ProtocolError("app-server warning is malformed")
        self.audit["warning_count"] += 1
        self.audit["warning_sha256"].append(
            hashlib.sha256(message.encode()).hexdigest()
        )
        self._checkpoint("warning:audited")

    def verify_effective_thread_settings(self, timeout: float = 30) -> None:
        """Exercise and verify app-server's settings lifecycle without a model turn."""
        if self._thread_id is None or self._expected_cwd is None:
            raise ProtocolError("app-server thread settings cannot be preflighted")
        result = self.transport.request(
            "thread/settings/update",
            {
                "threadId": self._thread_id,
                "cwd": self._expected_cwd,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"},
                "model": self._model,
                "effort": self._reasoning_effort,
                "personality": "none",
            },
            timeout=timeout,
        )
        if not isinstance(result, Mapping):
            raise ProtocolError("thread/settings/update returned a malformed response")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("timed out verifying thread settings lifecycle")
            try:
                message = self.transport.inbox.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if "transportError" in message:
                raise ProtocolError(str(message["transportError"]))
            if "id" in message:
                raise ProtocolError(
                    "unexpected app-server request during settings preflight"
                )
            method = message.get("method")
            params = message.get("params") or {}
            if method == "thread/settings/updated":
                self._accept_thread_settings_update(params)
                self.audit["thread_settings_preflight_verified"] = True
                self._checkpoint("thread/settings/preflight:verified")
                return
            if method == "remoteControl/status/changed":
                status = params.get("status")
                self.audit["remote_control_statuses"].append(status)
                if status != "disabled":
                    self.audit["native_capability_denied"] = True
                    raise ProtocolError(
                        f"Codex remote control was not disabled: {status!r}"
                    )
                continue
            if method == "warning":
                try:
                    self._accept_warning(params)
                except ProtocolError:
                    self.audit["native_capability_denied"] = True
                    raise
                continue
            if method in {
                "thread/started",
                "thread/status/changed",
                "thread/tokenUsage/updated",
                "account/rateLimits/updated",
            }:
                continue
            raise ProtocolError(
                f"unexpected app-server notification during settings preflight: "
                f"{method!r}"
            )

    def start_turn(self, user_text: str) -> tuple[str | list[ToolCall], bool]:
        if not self._thread_id:
            raise ProtocolError("app-server thread was not initialized")
        self.audit["turns_started"] += 1
        self._checkpoint("turn/start:requesting")
        result = self.transport.request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": user_text}],
                "model": self._model,
                "effort": self._reasoning_effort,
                "personality": "none",
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"},
                "environments": [],
                "runtimeWorkspaceRoots": [],
            },
            timeout=120,
        )
        turn = result.get("turn") if isinstance(result, Mapping) else None
        if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
            raise ProtocolError("turn/start returned no turn ID")
        self._turn_id = turn["id"]
        self._final_text = None
        self._checkpoint("turn/start:accepted")
        return self._wait_for_output(timeout=self._turn_output_timeout_seconds)

    def continue_turn(
        self, message: ToolMessage | MultiToolMessage
    ) -> tuple[str | list[ToolCall], bool]:
        responses = self.broker.resolve(message)
        self._checkpoint("item/tool/call:responding")
        for request_id, result in responses:
            self.transport.respond(request_id, result)
            self.audit["tool_results_returned"] += 1
        self._checkpoint("item/tool/call:responded")
        return self._wait_for_output(timeout=self._turn_output_timeout_seconds)

    def require_complete_tool_delivery(self) -> None:
        """Fail unless every accepted dynamic call received its tau2 result."""
        pending = self.broker.pending_count
        accepted = int(self.audit["dynamic_call_count"])
        returned = int(self.audit["tool_results_returned"])
        complete = pending == 0 and accepted == returned
        self.audit["pending_dynamic_call_count"] = pending
        self.audit["tool_result_delivery_complete"] = complete
        self._checkpoint(
            "tool_delivery:verified" if complete else "tool_delivery:failed"
        )
        if not complete:
            raise ProtocolError(
                "incomplete dynamic-tool result delivery: "
                f"accepted={accepted}, returned={returned}, pending={pending}"
            )

    def _wait_for_output(
        self, timeout: float | None = None
    ) -> tuple[str | list[ToolCall], bool]:
        timeout = self._turn_output_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + timeout
        idle_deadline = time.monotonic() + self._turn_output_idle_timeout_seconds
        calls: list[ToolCall] = []
        while True:
            remaining = deadline - time.monotonic()
            idle_remaining = idle_deadline - time.monotonic()
            if remaining <= 0 or idle_remaining <= 0:
                timeout_after = self.audit["last_protocol_method"]
                self.audit["app_server_stderr_line_count"] = getattr(
                    self.transport, "stderr_line_count", 0
                )
                self.audit["timeout_after_protocol_method"] = timeout_after
                self._checkpoint("turn/output:timed_out")
                raise ProtocolError(
                    "timed out waiting for Codex turn output; "
                    f"hard limit={timeout:g}s, idle limit="
                    f"{self._turn_output_idle_timeout_seconds:g}s; "
                    "last protocol method was "
                    f"{timeout_after!r}"
                )
            try:
                message = self.transport.inbox.get(
                    timeout=min(remaining, idle_remaining, 0.25)
                )
            except queue.Empty:
                if calls:
                    return calls, False
                continue
            idle_deadline = time.monotonic() + self._turn_output_idle_timeout_seconds
            if "transportError" in message:
                raise ProtocolError(str(message["transportError"]))
            method = message.get("method")
            params = message.get("params") or {}
            if method not in {
                "item/agentMessage/delta",
                "item/reasoning/summaryTextDelta",
                "item/reasoning/textDelta",
                "thread/tokenUsage/updated",
            }:
                self._checkpoint(str(method))
            if "id" in message:
                if method != "item/tool/call":
                    self.audit["native_capability_denied"] = True
                    raise ProtocolError(f"denied app-server request: {method!r}")
                call = self.broker.accept(message["id"], params)
                calls.append(call)
                self.audit["dynamic_call_count"] += 1
                self.audit["dynamic_call_names"].append(call.name)
                continue
            if method == "model/rerouted":
                self.audit["model_rerouted"] = True
                raise ProtocolError("Codex model rerouting is forbidden")
            if method == "remoteControl/status/changed":
                status = params.get("status")
                self.audit["remote_control_statuses"].append(status)
                if status != "disabled":
                    self.audit["native_capability_denied"] = True
                    raise ProtocolError(
                        f"Codex remote control was not disabled: {status!r}"
                    )
                continue
            if method == "thread/settings/updated":
                try:
                    self._accept_thread_settings_update(params)
                except ProtocolError:
                    self.audit["native_capability_denied"] = True
                    raise
                continue
            if method == "warning":
                try:
                    self._accept_warning(params)
                except ProtocolError:
                    self.audit["native_capability_denied"] = True
                    raise
                continue
            if method in {"item/started", "item/completed"}:
                item = params.get("item")
                if not isinstance(item, Mapping):
                    raise ProtocolError(f"{method} contained no item")
                try:
                    reject_native_item(item, self._allowed_item_types)
                except ProtocolError:
                    self.audit["native_capability_denied"] = True
                    raise
                if item.get("type") == "contextCompaction":
                    if method == "item/completed":
                        self.audit["context_compaction_count"] += 1
                    continue
                if (
                    method == "item/completed"
                    and item.get("type") == "agentMessage"
                    and item.get("phase") in {None, "final_answer"}
                ):
                    self._final_text = str(item.get("text") or "")
                continue
            if method == "turn/completed":
                turn = params.get("turn")
                status = turn.get("status") if isinstance(turn, Mapping) else None
                if status != "completed":
                    error = turn.get("error") if isinstance(turn, Mapping) else None
                    raise ProtocolError(f"Codex turn ended with {status!r}: {error!r}")
                if calls:
                    raise ProtocolError("turn completed with unresolved dynamic calls")
                if self._final_text is None:
                    raise ProtocolError("Codex completed without a final answer")
                self.audit["turns_completed"] += 1
                self._checkpoint("turn/completed:accepted")
                return self._final_text, True
            # Benign lifecycle/delta notifications carry no new capability.
            if method in {
                "thread/started",
                "thread/status/changed",
                "thread/tokenUsage/updated",
                "turn/started",
                "item/agentMessage/delta",
                "item/reasoning/summaryTextDelta",
                "item/reasoning/summaryPartAdded",
                "item/reasoning/textDelta",
                "account/rateLimits/updated",
                "model/verification",
                "turn/moderationMetadata",
                "model/safetyBuffering/updated",
                "serverRequest/resolved",
            }:
                continue
            raise ProtocolError(f"unexpected app-server notification: {method!r}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.transport.close()
        if self._temporary_cwd is not None:
            self._temporary_cwd.cleanup()
        if self._temporary_home is not None:
            self._temporary_home.cleanup()

    def __enter__(self) -> "CodexAppServer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
