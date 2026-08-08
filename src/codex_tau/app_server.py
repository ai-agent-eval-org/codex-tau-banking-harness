"""Fail-closed JSON-RPC client for the pinned Codex app-server."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import tempfile
import threading
import time
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


_ALLOWED_ITEM_TYPES = {"userMessage", "agentMessage", "reasoning", "dynamicToolCall"}


def reject_native_item(item: Mapping[str, Any]) -> None:
    """Reject every app-server item outside the benchmark's narrow protocol."""
    item_type = item.get("type")
    if item_type not in _ALLOWED_ITEM_TYPES:
        raise ProtocolError(f"denied native Codex item observed: {item_type!r}")


class JsonRpcProcess:
    """Asyncio subprocess transport presented through a synchronous boundary."""

    def __init__(self, command: list[str], cwd: Path, env: Mapping[str, str]):
        self.inbox: queue.Queue[Mapping[str, Any]] = queue.Queue()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[str | int, asyncio.Future[Mapping[str, Any]]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        future = asyncio.run_coroutine_threadsafe(
            self._start(command, cwd, env), self._loop
        )
        future.result(timeout=30)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start(
        self, command: list[str], cwd: Path, env: Mapping[str, str]
    ) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *command,
            "app-server",
            "--strict-config",
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while await self._process.stderr.readline():
            pass

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        while line := await self._process.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.inbox.put({"transportError": "non-JSON app-server output"})
                continue
            if "id" in message and "method" not in message:
                pending = self._pending.pop(message["id"], None)
                if pending is not None and not pending.done():
                    pending.set_result(message)
            else:
                self.inbox.put(message)
        for pending in self._pending.values():
            if not pending.done():
                pending.set_exception(
                    ProtocolError("Codex app-server exited while awaiting response")
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
        domain_policy: str,
        prompt: str,
        auth_file: Path | None = None,
        transport: JsonRpcProcess | None = None,
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
        self.audit: dict[str, Any] = {
            "dynamic_call_count": 0,
            "dynamic_call_names": [],
            "native_capability_denied": False,
            "model_rerouted": False,
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
        self.transport = JsonRpcProcess(command, Path(self._temporary_cwd.name), child_env)
        self._initialize(domain_policy, prompt)

    def _initialize(self, domain_policy: str, prompt: str) -> None:
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
        self.audit["model"] = require_model_catalog(model_result)
        rate_limits = self.transport.request("account/rateLimits/read")
        buckets = rate_limits.get("rateLimitsByLimitId") if isinstance(rate_limits, Mapping) else None
        self.audit["rate_limit_ids"] = sorted(buckets) if isinstance(buckets, Mapping) else []

        empty_cwd = str(Path(self._temporary_cwd.name).resolve())
        thread = self.transport.request(
            "thread/start",
            {
                "model": "gpt-5.4",
                "cwd": empty_cwd,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "allowProviderModelFallback": False,
                "ephemeral": True,
                "baseInstructions": (
                    "You are the evaluated Rho-Bank support agent. Follow the supplied "
                    "policy and experiment prompt. Use only the supplied dynamic tools. "
                    "Do not use native Codex capabilities."
                ),
                "developerInstructions": (
                    "<domain_policy>\n"
                    + domain_policy
                    + "\n</domain_policy>\n<experiment_prompt>\n"
                    + prompt
                    + "\n</experiment_prompt>"
                ),
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
        if observed_model != "gpt-5.4":
            raise ProtocolError(f"thread model mismatch: {observed_model!r}")
        thread_value = thread.get("thread")
        if not isinstance(thread_value, Mapping) or not isinstance(
            thread_value.get("id"), str
        ):
            raise ProtocolError("thread/start returned no thread ID")
        self._thread_id = thread_value["id"]
        self.audit["instruction_sources"] = []
        self.audit["observed_thread_model"] = observed_model

    def start_turn(self, user_text: str) -> tuple[str | list[ToolCall], bool]:
        if not self._thread_id:
            raise ProtocolError("app-server thread was not initialized")
        result = self.transport.request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": user_text}],
                "model": "gpt-5.4",
                "effort": "xhigh",
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
        return self._wait_for_output()

    def continue_turn(
        self, message: ToolMessage | MultiToolMessage
    ) -> tuple[str | list[ToolCall], bool]:
        for request_id, result in self.broker.resolve(message):
            self.transport.respond(request_id, result)
        return self._wait_for_output()

    def _wait_for_output(self, timeout: float = 600) -> tuple[str | list[ToolCall], bool]:
        deadline = time.monotonic() + timeout
        calls: list[ToolCall] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("timed out waiting for Codex turn output")
            try:
                message = self.transport.inbox.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                if calls:
                    return calls, False
                continue
            if "transportError" in message:
                raise ProtocolError(str(message["transportError"]))
            method = message.get("method")
            params = message.get("params") or {}
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
            if method in {"item/started", "item/completed"}:
                item = params.get("item")
                if not isinstance(item, Mapping):
                    raise ProtocolError(f"{method} contained no item")
                try:
                    reject_native_item(item)
                except ProtocolError:
                    self.audit["native_capability_denied"] = True
                    raise
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
                return self._final_text, True
            # Benign lifecycle/delta notifications carry no new capability.
            if method in {
                "thread/started",
                "turn/started",
                "item/agentMessage/delta",
                "item/reasoning/summaryTextDelta",
                "item/reasoning/summaryPartAdded",
                "account/rateLimits/updated",
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
