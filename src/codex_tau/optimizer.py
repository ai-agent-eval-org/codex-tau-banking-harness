"""Run one leakage-safe prompt optimization through a fresh Codex app-server."""

import hashlib
import json
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping

from tau2.data_model.message import MultiToolMessage, ToolCall, ToolMessage
from tau2.environment.tool import Tool
from tau2.environment.toolkit import ToolKitBase, ToolType, is_tool

from .app_server import CodexAppServer
from .optimizer_packet import export_optimizer_packet
from .tool_bridge import ToolCatalog, canonical_hash

OPTIMIZER_MODEL = "gpt-5.6-sol"
OPTIMIZER_REASONING_EFFORT = "max"
DEFAULT_SOURCE_RUN = Path("runs/vanilla-train-alltools-20260808T212330Z")
DEFAULT_OUTPUT_ROOT = Path("optimizer-runs")
EXPECTED_SOURCE_RESULTS_SHA256 = (
    "49e136b4385989cdcbdd322ccf804f753da050b3f57d3edb1bbc4187ee020ff2"
)
MAX_READ_CHARS = 200_000
MAX_TOOL_CALLS = 1_000
OPTIMIZER_ALLOWED_ITEM_TYPES = frozenset(
    {
        "userMessage",
        "agentMessage",
        "reasoning",
        "dynamicToolCall",
        "contextCompaction",
    }
)
PACKET_FILES = (
    "baseline_prompt.md",
    "evidence_manifest.json",
    "fixed_runtime_contract.json",
    "tool_definitions.json",
)
PacketFileName = Literal[
    "baseline_prompt.md",
    "evidence_manifest.json",
    "fixed_runtime_contract.json",
    "tool_definitions.json",
]
BOOTSTRAP_INSTRUCTION = """Execute the authorized one-shot optimization now.

Use inspect_packet first. Read every required packet file and every trace in
bounded chunks until each tool response reports eof=true. Record exactly one
analysis entry for every trace and every authoritative banking tool. Treat
successful traces as regression controls and assign each failed trace one
primary prompt-controllable cluster. After coverage is complete, reread the
entire external analysis ledger in bounded chunks. Then call
submit_optimization exactly once with the complete optimization report and the
complete replacement system prompt. Use the isolated Code Mode entrypoint only
to invoke the seven supplied packet tools. Do not request other data or tools,
produce intermediate prompt candidates, or perform an evaluation. After the
submission is accepted, return a short completion message.
"""


class OptimizerRunError(RuntimeError):
    """The optimizer violated an evidence, execution, or output invariant."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode())


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OptimizerRunError(f"cannot read optimizer packet file: {path}") from exc
    if not isinstance(value, dict):
        raise OptimizerRunError(f"optimizer packet file must be an object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OptimizerRunError(message)


class _Coverage:
    def __init__(self, total: int):
        self.total = total
        self.ranges: list[tuple[int, int]] = []

    def add(self, start: int, end: int) -> None:
        if end <= start:
            return
        merged: list[tuple[int, int]] = []
        for left, right in sorted([*self.ranges, (start, end)]):
            if not merged or left > merged[-1][1]:
                merged.append((left, right))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        self.ranges = merged

    @property
    def complete(self) -> bool:
        return self.total == 0 or self.ranges == [(0, self.total)]

    @property
    def delivered(self) -> int:
        return sum(right - left for left, right in self.ranges)


def validate_optimized_prompt(prompt: str, baseline: str) -> None:
    """Reject malformed, trace-specific, or non-replacement prompt output."""
    _require(
        prompt == prompt.strip() + "\n", "optimized prompt needs one final newline"
    )
    _require(500 <= len(prompt) <= 100_000, "optimized prompt length is invalid")
    _require(prompt != baseline, "optimizer returned the unchanged baseline")
    _require(
        re.fullmatch(
            r"<instructions>\n.+\n</instructions>\n<policy>\n.+\n</policy>\n",
            prompt,
            flags=re.DOTALL,
        )
        is not None,
        "prompt must contain only one nonempty instructions section followed by "
        "one nonempty policy section",
    )
    _require("```" not in prompt, "optimized prompt must not contain code fences")
    forbidden = (
        r"\btrain_trace_\d+\b",
        r"\btask_\d+\b",
        r"\btraces?\b",
        r"\bgrader\b",
        r"\breward\b",
        r"\bbenchmark\b",
        r"\bsimulator\b",
        r"\bevaluat(?:e|ed|ing|ion|ions|or|ors)\b",
        r"\boptimi[sz](?:e|ed|es|er|ers|ing|ation|ations)\b",
        r"\bvalidation (?:set|trace|result)\b",
        r"\btest (?:set|trace|result)\b",
        r"\bproduction trace\b",
    )
    for pattern in forbidden:
        _require(
            re.search(pattern, prompt, flags=re.IGNORECASE) is None,
            f"optimized prompt contains forbidden evidence language: {pattern}",
        )
    _require(
        re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", prompt, re.I) is None,
        "optimized prompt contains an email address",
    )
    _require(
        re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            prompt,
            re.I,
        )
        is None,
        "optimized prompt contains a UUID",
    )


class OptimizerPacketTools(ToolKitBase):
    """Audited, read-only access to one exported train packet and one submission."""

    def __init__(self, packet_dir: Path):
        super().__init__()
        self.packet_dir = packet_dir.resolve()
        self.manifest = _load_object(self.packet_dir / "evidence_manifest.json")
        _require(
            self.manifest.get("authorized_partition") == "train",
            "optimizer packet is not train-only",
        )
        _require(
            self.manifest.get("authorization")
            == "train-only one-shot full-prompt optimization",
            "optimizer packet authorization marker is invalid",
        )
        _require(
            self.manifest.get("source_results_sha256")
            == EXPECTED_SOURCE_RESULTS_SHA256,
            "optimizer packet is not the fixed authorized train evidence",
        )
        trace_entries = self.manifest.get("traces")
        _require(isinstance(trace_entries, list), "packet trace manifest is missing")
        self.trace_entries: dict[str, dict[str, Any]] = {}
        for entry in trace_entries:
            _require(isinstance(entry, dict), "packet trace entry is malformed")
            trace_ref = entry.get("trace_ref")
            _require(isinstance(trace_ref, str), "packet trace reference is malformed")
            _require(trace_ref not in self.trace_entries, "duplicate packet trace")
            self.trace_entries[trace_ref] = dict(entry)
        _require(
            len(self.trace_entries) == self.manifest.get("expected_trace_count") == 48,
            "optimizer packet must contain the exact 48 train traces",
        )

        self.packet_text: dict[str, str] = {}
        self.packet_hashes: dict[str, str] = {}
        for name in (*PACKET_FILES, "optimizer.md"):
            path = self.packet_dir / name
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError) as exc:
                raise OptimizerRunError(f"cannot read packet file: {name}") from exc
            self.packet_text[name] = text
            self.packet_hashes[name] = _sha256_path(path)

        expected_hashes = {
            "baseline_prompt.md": self.manifest.get("baseline_prompt_sha256"),
            "optimizer.md": self.manifest.get("optimizer_instruction_sha256"),
            "tool_definitions.json": self.manifest.get("tool_definitions_sha256"),
        }
        for name, expected in expected_hashes.items():
            _require(
                isinstance(expected, str) and self.packet_hashes[name] == expected,
                f"optimizer packet hash mismatch: {name}",
            )

        definitions = _load_object(self.packet_dir / "tool_definitions.json")
        tools = definitions.get("tools")
        _require(isinstance(tools, list), "packet tool definitions are missing")
        self.tool_names = tuple(
            tool.get("name") for tool in tools if isinstance(tool, Mapping)
        )
        _require(
            len(self.tool_names) == self.manifest.get("tool_count") == 17
            and all(isinstance(name, str) for name in self.tool_names),
            "optimizer packet must contain the exact 17 tool definitions",
        )
        _require(len(set(self.tool_names)) == 17, "duplicate packet tool definition")

        self.trace_text: dict[str, str] = {}
        self.trace_hashes: dict[str, str] = {}
        for trace_ref, entry in self.trace_entries.items():
            path = self.packet_dir / "production_traces" / f"{trace_ref}.json"
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError) as exc:
                raise OptimizerRunError(
                    f"cannot read packet trace: {trace_ref}"
                ) from exc
            digest = _sha256_path(path)
            _require(digest == entry.get("sha256"), f"trace hash mismatch: {trace_ref}")
            self.trace_text[trace_ref] = text
            self.trace_hashes[trace_ref] = digest

        self.coverage = {
            name: _Coverage(len(self.packet_text[name])) for name in PACKET_FILES
        }
        self.trace_coverage = {
            trace_ref: _Coverage(len(text))
            for trace_ref, text in self.trace_text.items()
        }
        self.trace_analysis: dict[str, dict[str, str]] = {}
        self.tool_analysis: dict[str, dict[str, str]] = {}
        self.analysis_ledger_text: str | None = None
        self.analysis_ledger_coverage: _Coverage | None = None
        self.inspected = False
        self.submission: dict[str, str] | None = None

    def _chunk(
        self, *, text: str, coverage: _Coverage, offset: int, max_chars: int
    ) -> dict[str, Any]:
        _require(isinstance(offset, int) and 0 <= offset <= len(text), "invalid offset")
        _require(
            isinstance(max_chars, int) and 1 <= max_chars <= MAX_READ_CHARS,
            f"max_chars must be between 1 and {MAX_READ_CHARS}",
        )
        end = min(len(text), offset + max_chars)
        coverage.add(offset, end)
        return {
            "offset": offset,
            "next_offset": end,
            "total_chars": len(text),
            "eof": end == len(text),
            "content": text[offset:end],
        }

    def _coverage_error(self) -> str | None:
        missing_files = [
            name for name, value in self.coverage.items() if not value.complete
        ]
        missing_traces = [
            name for name, value in self.trace_coverage.items() if not value.complete
        ]
        missing_trace_analysis = sorted(
            set(self.trace_entries) - set(self.trace_analysis)
        )
        missing_tool_analysis = sorted(set(self.tool_names) - set(self.tool_analysis))
        missing_ledger_read = (
            not missing_trace_analysis
            and not missing_tool_analysis
            and (
                self.analysis_ledger_coverage is None
                or not self.analysis_ledger_coverage.complete
            )
        )
        if not any(
            (
                missing_files,
                missing_traces,
                missing_trace_analysis,
                missing_tool_analysis,
                missing_ledger_read,
            )
        ):
            return None
        return json.dumps(
            {
                "missing_packet_files": missing_files,
                "missing_trace_reads": missing_traces,
                "missing_trace_analysis": missing_trace_analysis,
                "missing_tool_analysis": missing_tool_analysis,
                "analysis_ledger_read_incomplete": missing_ledger_read,
            },
            sort_keys=True,
        )

    @is_tool(ToolType.READ)
    def inspect_packet(self) -> dict[str, Any]:
        """Inspect the authorized packet inventory before reading evidence."""
        self.inspected = True
        return {
            "authorized_partition": "train",
            "required_packet_files": [
                {
                    "name": name,
                    "total_chars": len(self.packet_text[name]),
                    "sha256": self.packet_hashes[name],
                }
                for name in PACKET_FILES
            ],
            "traces": [
                {
                    "trace_ref": trace_ref,
                    "reward": self.trace_entries[trace_ref]["reward"],
                    "total_chars": len(self.trace_text[trace_ref]),
                    "sha256": self.trace_hashes[trace_ref],
                }
                for trace_ref in self.trace_entries
            ],
            "tool_names": list(self.tool_names),
            "trace_count": len(self.trace_entries),
            "tool_count": len(self.tool_names),
            "maximum_read_chars": MAX_READ_CHARS,
        }

    @is_tool(ToolType.READ)
    def read_packet_file(
        self,
        file_name: PacketFileName,
        offset: int = 0,
        max_chars: int = 100_000,
    ) -> dict[str, Any]:
        """Read one bounded chunk from a required non-trace packet file.

        Args:
            file_name: Exact packet filename returned by inspect_packet.
            offset: Character offset at which to start reading.
            max_chars: Maximum characters to return, capped at 200000.
        """
        _require(self.inspected, "inspect_packet must be called first")
        _require(file_name in PACKET_FILES, "unknown packet file")
        result = self._chunk(
            text=self.packet_text[file_name],
            coverage=self.coverage[file_name],
            offset=offset,
            max_chars=max_chars,
        )
        result["file_name"] = file_name
        result["sha256"] = self.packet_hashes[file_name]
        return result

    @is_tool(ToolType.READ)
    def read_trace(
        self, trace_ref: str, offset: int = 0, max_chars: int = 100_000
    ) -> dict[str, Any]:
        """Read one bounded chunk from an authorized production trace.

        Args:
            trace_ref: An anonymized train trace reference from inspect_packet.
            offset: Character offset at which to start reading.
            max_chars: Maximum characters to return, capped at 200000.
        """
        _require(self.inspected, "inspect_packet must be called first")
        _require(trace_ref in self.trace_text, "unknown or unauthorized trace")
        result = self._chunk(
            text=self.trace_text[trace_ref],
            coverage=self.trace_coverage[trace_ref],
            offset=offset,
            max_chars=max_chars,
        )
        result["trace_ref"] = trace_ref
        result["reward"] = self.trace_entries[trace_ref]["reward"]
        result["sha256"] = self.trace_hashes[trace_ref]
        return result

    @is_tool(ToolType.GENERIC, mutates_state=False)
    def record_trace_analysis(
        self,
        trace_ref: str,
        primary_cluster: str,
        causal_analysis: str,
        preserved_behavior: str,
    ) -> dict[str, Any]:
        """Record the sole analysis-ledger entry for one fully read trace.

        Args:
            trace_ref: An anonymized trace reference from inspect_packet.
            primary_cluster: One general failure cluster, or success_regression_control.
            causal_analysis: General prompt-controllable causal finding.
            preserved_behavior: Successful behavior or regression constraint to preserve.
        """
        _require(trace_ref in self.trace_coverage, "unknown or unauthorized trace")
        _require(self.trace_coverage[trace_ref].complete, "trace is not fully read")
        _require(
            trace_ref not in self.trace_analysis, "trace analysis already recorded"
        )
        for value in (primary_cluster, causal_analysis, preserved_behavior):
            _require(
                isinstance(value, str) and 3 <= len(value) <= 4_000,
                "trace analysis field length is invalid",
            )
        reward = self.trace_entries[trace_ref]["reward"]
        if reward == 1:
            _require(
                primary_cluster == "success_regression_control",
                "successful traces must be regression controls",
            )
        else:
            _require(
                primary_cluster != "success_regression_control",
                "failed traces need a failure cluster",
            )
        self.trace_analysis[trace_ref] = {
            "primary_cluster": primary_cluster,
            "causal_analysis": causal_analysis,
            "preserved_behavior": preserved_behavior,
        }
        return {
            "accepted": True,
            "trace_ref": trace_ref,
            "recorded_trace_count": len(self.trace_analysis),
            "required_trace_count": len(self.trace_entries),
        }

    @is_tool(ToolType.GENERIC, mutates_state=False)
    def record_tool_analysis(
        self, tool_name: str, contract_observation: str, prompt_implication: str
    ) -> dict[str, Any]:
        """Record the sole analysis-ledger entry for one authoritative tool.

        Args:
            tool_name: Exact authoritative tool name from inspect_packet.
            contract_observation: Relevant description/schema/result constraint.
            prompt_implication: General instruction implication without changing the tool.
        """
        _require(tool_name in self.tool_names, "unknown tool name")
        _require(
            self.coverage["tool_definitions.json"].complete,
            "tool definitions are not fully read",
        )
        _require(tool_name not in self.tool_analysis, "tool analysis already recorded")
        for value in (contract_observation, prompt_implication):
            _require(
                isinstance(value, str) and 3 <= len(value) <= 4_000,
                "tool analysis field length is invalid",
            )
        self.tool_analysis[tool_name] = {
            "contract_observation": contract_observation,
            "prompt_implication": prompt_implication,
        }
        return {
            "accepted": True,
            "tool_name": tool_name,
            "recorded_tool_count": len(self.tool_analysis),
            "required_tool_count": len(self.tool_names),
        }

    @is_tool(ToolType.READ)
    def read_analysis_ledger(
        self, offset: int = 0, max_chars: int = 100_000
    ) -> dict[str, Any]:
        """Reread the complete external analysis ledger before final synthesis.

        Args:
            offset: Character offset at which to start reading.
            max_chars: Maximum characters to return, capped at 200000.
        """
        _require(
            len(self.trace_analysis) == len(self.trace_entries),
            "trace analysis ledger is incomplete",
        )
        _require(
            len(self.tool_analysis) == len(self.tool_names),
            "tool analysis ledger is incomplete",
        )
        if self.analysis_ledger_text is None:
            self.analysis_ledger_text = (
                json.dumps(
                    {
                        "trace_analysis": self.trace_analysis,
                        "tool_analysis": self.tool_analysis,
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            self.analysis_ledger_coverage = _Coverage(len(self.analysis_ledger_text))
        assert self.analysis_ledger_coverage is not None
        result = self._chunk(
            text=self.analysis_ledger_text,
            coverage=self.analysis_ledger_coverage,
            offset=offset,
            max_chars=max_chars,
        )
        result["sha256"] = _sha256_text(self.analysis_ledger_text)
        return result

    @is_tool(ToolType.WRITE, mutates_state=False)
    def submit_optimization(
        self, optimization_report: str, optimized_prompt: str
    ) -> dict[str, Any]:
        """Submit the one final report and complete replacement prompt.

        Args:
            optimization_report: Complete evidence-grounded optimization report.
            optimized_prompt: Complete replacement instructions-plus-policy system prompt.
        """
        _require(self.submission is None, "an optimization was already submitted")
        coverage_error = self._coverage_error()
        _require(
            coverage_error is None,
            f"optimizer coverage is incomplete: {coverage_error}",
        )
        _require(
            isinstance(optimization_report, str)
            and 500 <= len(optimization_report) <= 200_000,
            "optimization report length is invalid",
        )
        if not optimized_prompt.endswith("\n"):
            optimized_prompt += "\n"
        baseline = self.packet_text["baseline_prompt.md"]
        validate_optimized_prompt(optimized_prompt, baseline)
        self.submission = {
            "optimization_report": optimization_report.strip() + "\n",
            "optimized_prompt": optimized_prompt,
        }
        return {
            "accepted": True,
            "optimization_report_sha256": _sha256_text(
                self.submission["optimization_report"]
            ),
            "optimized_prompt_sha256": _sha256_text(optimized_prompt),
            "trace_coverage": len(self.trace_analysis),
            "tool_coverage": len(self.tool_analysis),
        }

    def coverage_manifest(self) -> dict[str, Any]:
        return {
            "packet_files": {
                name: {
                    "complete": coverage.complete,
                    "delivered_chars": coverage.delivered,
                    "total_chars": coverage.total,
                }
                for name, coverage in self.coverage.items()
            },
            "traces_complete": sum(
                coverage.complete for coverage in self.trace_coverage.values()
            ),
            "traces_required": len(self.trace_coverage),
            "trace_analysis_count": len(self.trace_analysis),
            "tool_analysis_count": len(self.tool_analysis),
            "analysis_ledger_complete": bool(
                self.analysis_ledger_coverage and self.analysis_ledger_coverage.complete
            ),
            "analysis_ledger_sha256": (
                _sha256_text(self.analysis_ledger_text)
                if self.analysis_ledger_text is not None
                else None
            ),
            "trace_analysis_sha256": canonical_hash(self.trace_analysis),
            "tool_analysis_sha256": canonical_hash(self.tool_analysis),
            "submission_count": int(self.submission is not None),
        }


def _tool_result(call: ToolCall, tool: Tool) -> ToolMessage:
    result = tool(**dict(call.arguments))
    content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return ToolMessage(
        id=call.id,
        role="tool",
        content=content,
        requestor="assistant",
        error=False,
    )


def _execute_calls(
    calls: list[ToolCall], tools: Mapping[str, Tool]
) -> ToolMessage | MultiToolMessage:
    messages: list[ToolMessage] = []
    for call in calls:
        tool = tools.get(call.name)
        _require(tool is not None, f"optimizer requested unknown tool: {call.name}")
        messages.append(_tool_result(call, tool))
    if len(messages) == 1:
        return messages[0]
    return MultiToolMessage(role="tool", tool_messages=messages)


def _git_provenance(repo_root: Path, *, require_clean: bool) -> dict[str, Any]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    if require_clean:
        _require(not status, "optimizer execution requires a clean tracked worktree")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "branch": branch, "tracked_worktree_clean": not status}


def _runtime(*, repo_root: Path, toolkit: OptimizerPacketTools) -> CodexAppServer:
    tools = list(toolkit.get_tools().values())
    return CodexAppServer(
        repo_root=repo_root,
        tools=tools,
        system_prompt=toolkit.packet_text["optimizer.md"],
        model=OPTIMIZER_MODEL,
        reasoning_effort=OPTIMIZER_REASONING_EFFORT,
        enable_optimizer_code_mode=True,
        allowed_item_types=OPTIMIZER_ALLOWED_ITEM_TYPES,
        turn_output_timeout_seconds=7_200,
        turn_output_idle_timeout_seconds=600,
    )


def optimizer_preflight(
    *, repo_root: Path, source_run: Path = DEFAULT_SOURCE_RUN
) -> dict[str, Any]:
    """Prepare the exact packet and verify auth/model/thread without inference."""
    repo_root = repo_root.resolve()
    resolved_source = (
        (repo_root / source_run).resolve()
        if not source_run.is_absolute()
        else source_run.resolve()
    )
    with tempfile.TemporaryDirectory(prefix="codex-tau-optimizer-preflight-") as root:
        packet_dir = Path(root) / "packet"
        manifest = export_optimizer_packet(
            repo_root=repo_root,
            source_run=resolved_source,
            output_dir=packet_dir,
        )
        toolkit = OptimizerPacketTools(packet_dir)
        with _runtime(repo_root=repo_root, toolkit=toolkit) as runtime:
            runtime.verify_effective_thread_settings()
            audit = dict(runtime.audit)
        return {
            "source_run": str(resolved_source),
            "source_results_sha256": manifest["source_results_sha256"],
            "packet_manifest_sha256": _sha256_path(
                packet_dir / "evidence_manifest.json"
            ),
            "trace_count": len(toolkit.trace_entries),
            "tool_count": len(toolkit.tool_names),
            "optimizer_instruction_sha256": toolkit.packet_hashes["optimizer.md"],
            "dynamic_tool_schema_sha256": ToolCatalog(
                toolkit.get_tools().values()
            ).hash,
            "codex": audit,
        }


def _default_output_dir(repo_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / DEFAULT_OUTPUT_ROOT / f"one-shot-{stamp}"


def _write_non_submission_bundle(
    *,
    output_dir: Path,
    final_response: str,
    audit: Mapping[str, Any],
    coverage: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    """Retain a local-only diagnostic when a turn ends without submission."""
    output_dir.mkdir(parents=True)
    response_path = output_dir / "final-response.txt"
    response_path.write_text(final_response)
    receipt = {
        "format_version": 1,
        "classification": "failed optimizer attempt: no submission",
        "codex": dict(audit),
        "coverage": dict(coverage),
        "final_response": {
            "path": response_path.name,
            "chars": len(final_response),
            "sha256": _sha256_path(response_path),
        },
        "harness": dict(provenance),
        "promotion": {
            "active_prompt_unchanged": True,
            "evaluation_run": False,
        },
    }
    (output_dir / "failure.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )


def run_optimizer(
    *,
    repo_root: Path,
    source_run: Path = DEFAULT_SOURCE_RUN,
    output_dir: Path | None = None,
) -> Path:
    """Execute one authorized optimizer turn and write a verified local bundle."""
    repo_root = repo_root.resolve()
    provenance = _git_provenance(repo_root, require_clean=True)
    resolved_source = (
        (repo_root / source_run).resolve()
        if not source_run.is_absolute()
        else source_run.resolve()
    )
    resolved_output = (
        _default_output_dir(repo_root)
        if output_dir is None
        else (
            (repo_root / output_dir).resolve()
            if not output_dir.is_absolute()
            else output_dir.resolve()
        )
    )
    output_root = (repo_root / DEFAULT_OUTPUT_ROOT).resolve()
    _require(
        resolved_output != output_root and resolved_output.is_relative_to(output_root),
        f"optimizer output must be below {output_root}",
    )
    _require(
        not resolved_output.exists(),
        f"optimizer output already exists: {resolved_output}",
    )

    started_at = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="codex-tau-optimizer-") as root:
        packet_dir = Path(root) / "packet"
        packet_manifest = export_optimizer_packet(
            repo_root=repo_root,
            source_run=resolved_source,
            output_dir=packet_dir,
        )
        toolkit = OptimizerPacketTools(packet_dir)
        tool_map = toolkit.get_tools()
        catalog = ToolCatalog(tool_map.values())
        with _runtime(repo_root=repo_root, toolkit=toolkit) as runtime:
            runtime.verify_effective_thread_settings()
            value, complete = runtime.start_turn(BOOTSTRAP_INSTRUCTION)
            handled_calls = 0
            while not complete:
                _require(
                    isinstance(value, list) and value, "optimizer returned no calls"
                )
                handled_calls += len(value)
                _require(
                    handled_calls <= MAX_TOOL_CALLS,
                    "optimizer tool-call limit exceeded",
                )
                value, complete = runtime.continue_turn(_execute_calls(value, tool_map))
            _require(isinstance(value, str), "optimizer final response is not text")
            runtime.require_complete_tool_delivery()
            audit = dict(runtime.audit)

        coverage = toolkit.coverage_manifest()
        if toolkit.submission is None:
            _write_non_submission_bundle(
                output_dir=resolved_output,
                final_response=value,
                audit=audit,
                coverage=coverage,
                provenance=provenance,
            )
            raise OptimizerRunError(
                "optimizer completed without submission; local diagnostic: "
                f"{resolved_output}"
            )
        _require(coverage["submission_count"] == 1, "optimizer submission count drift")
        _require(
            coverage["traces_complete"] == coverage["traces_required"] == 48,
            "optimizer trace coverage is incomplete",
        )
        _require(coverage["trace_analysis_count"] == 48, "trace ledger is incomplete")
        _require(coverage["tool_analysis_count"] == 17, "tool ledger is incomplete")
        _require(
            coverage["analysis_ledger_complete"] is True,
            "analysis ledger was not fully reread",
        )

        report = toolkit.submission["optimization_report"]
        prompt = toolkit.submission["optimized_prompt"]
        resolved_output.mkdir(parents=True)
        report_path = resolved_output / "optimization-report.md"
        prompt_path = resolved_output / "optimized.md"
        report_path.write_text(report)
        prompt_path.write_text(prompt)
        final_manifest = {
            "format_version": 1,
            "classification": "train-only one-shot full-prompt optimization",
            "authorization": {
                "source": "explicit user instruction in the initiating Codex task",
                "attempts_permitted": 1,
                "attempts_executed": 1,
            },
            "execution": {
                "started_at": started_at,
                "completed_at": datetime.now(UTC).isoformat(),
                "one_turn": audit.get("turns_started")
                == audit.get("turns_completed")
                == 1,
                "automatic_retry": False,
                "tool_calls": handled_calls,
                "final_response_sha256": _sha256_text(value),
            },
            "source": {
                "run": str(resolved_source),
                "results_sha256": packet_manifest["source_results_sha256"],
                "manifest_sha256": packet_manifest["source_manifest_sha256"],
                "partition": packet_manifest["authorized_partition"],
            },
            "packet": {
                "evidence_manifest_sha256": _sha256_path(
                    packet_dir / "evidence_manifest.json"
                ),
                "optimizer_instruction_sha256": toolkit.packet_hashes["optimizer.md"],
                "baseline_prompt_sha256": toolkit.packet_hashes["baseline_prompt.md"],
                "tool_definitions_sha256": toolkit.packet_hashes[
                    "tool_definitions.json"
                ],
                "dynamic_tool_schema_sha256": catalog.hash,
                "bootstrap_instruction_sha256": _sha256_text(BOOTSTRAP_INSTRUCTION),
            },
            "coverage": coverage,
            "codex": audit,
            "outputs": {
                "optimization_report_sha256": _sha256_path(report_path),
                "optimized_prompt_sha256": _sha256_path(prompt_path),
                "optimized_prompt_chars": len(prompt),
            },
            "harness": provenance,
            "promotion": {
                "active_prompt_unchanged": True,
                "evaluation_run": False,
                "requires_separate_human_review": True,
            },
        }
        (resolved_output / "manifest.json").write_text(
            json.dumps(final_manifest, indent=2, sort_keys=True) + "\n"
        )
    return resolved_output
