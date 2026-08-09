from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tau2.data_model.message import ToolCall, ToolMessage

from codex_tau.auth import AuthError, require_model_catalog
from codex_tau.optimizer import (
    EXPECTED_SOURCE_RESULTS_SHA256,
    OPTIMIZER_MODEL,
    OPTIMIZER_REASONING_EFFORT,
    PACKET_FILES,
    OptimizerPacketTools,
    OptimizerRunError,
    _execute_calls,
    _write_non_submission_bundle,
)
from codex_tau.run import _parser
from codex_tau.tool_bridge import ToolCatalog


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_packet(tmp_path: Path) -> Path:
    packet = tmp_path / "packet"
    traces = packet / "production_traces"
    traces.mkdir(parents=True)
    baseline = (
        "<instructions>\nBaseline behavior.\n</instructions>\n"
        "<policy>\nCanonical banking policy.\n</policy>\n"
    )
    optimizer = "You are the isolated one-shot optimizer.\n"
    fixed = {"editable_surface": "baseline_prompt.md only"}
    tools = [
        {
            "name": f"banking_tool_{index:02d}",
            "description": "Authoritative banking tool.",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {"type": "object"},
            "raises": [],
            "examples": [],
        }
        for index in range(1, 18)
    ]
    (packet / "baseline_prompt.md").write_text(baseline)
    (packet / "optimizer.md").write_text(optimizer)
    (packet / "fixed_runtime_contract.json").write_text(
        json.dumps(fixed, indent=2) + "\n"
    )
    (packet / "tool_definitions.json").write_text(
        json.dumps({"tool_count": 17, "tools": tools}, indent=2) + "\n"
    )
    trace_entries = []
    for index in range(1, 49):
        trace_ref = f"train_trace_{index:03d}"
        trace = {
            "trace_ref": trace_ref,
            "termination_reason": "user_stop",
            "reward": 1 if index <= 23 else 0,
            "messages": [
                {"role": "user", "content": f"synthetic request {index}"},
                {"role": "assistant", "content": "synthetic response"},
            ],
        }
        path = traces / f"{trace_ref}.json"
        path.write_text(json.dumps(trace, indent=2) + "\n")
        trace_entries.append(
            {
                "trace_ref": trace_ref,
                "reward": trace["reward"],
                "message_count": 2,
                "sha256": sha256_path(path),
            }
        )
    manifest = {
        "format_version": 1,
        "authorization": "train-only one-shot full-prompt optimization",
        "authorized_partition": "train",
        "source_results_sha256": EXPECTED_SOURCE_RESULTS_SHA256,
        "expected_trace_count": 48,
        "exported_trace_count": 48,
        "tool_count": 17,
        "baseline_prompt_sha256": sha256_path(packet / "baseline_prompt.md"),
        "optimizer_instruction_sha256": sha256_path(packet / "optimizer.md"),
        "tool_definitions_sha256": sha256_path(packet / "tool_definitions.json"),
        "traces": trace_entries,
    }
    (packet / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return packet


def complete_evidence(toolkit: OptimizerPacketTools) -> None:
    inventory = toolkit.inspect_packet()
    assert inventory["trace_count"] == 48
    assert inventory["tool_count"] == 17
    for name in PACKET_FILES:
        result = toolkit.read_packet_file(name, max_chars=200_000)  # type: ignore[arg-type]
        assert result["eof"] is True
    for trace_ref, entry in toolkit.trace_entries.items():
        result = toolkit.read_trace(trace_ref, max_chars=200_000)
        assert result["eof"] is True
        toolkit.record_trace_analysis(
            trace_ref,
            (
                "success_regression_control"
                if entry["reward"] == 1
                else "general_failure_cluster"
            ),
            "A general causal observation for this synthetic trace.",
            "Preserve correct policy and tool-result handling behavior.",
        )
    for tool_name in toolkit.tool_names:
        toolkit.record_tool_analysis(
            tool_name,
            "The authoritative contract constrains arguments and results.",
            "Select the tool by its contract and consume its result exactly.",
        )


def candidate_prompt() -> str:
    instruction = (
        "Resolve the complete banking request safely and accurately. Inspect the "
        "authoritative tool contracts, use only decision-critical retrieval, keep "
        "resources isolated, sequence dependent actions, and report only verified "
        "results. Preserve privacy, authorization, and confirmation requirements. "
    )
    policy = (
        "Apply the canonical banking policy exactly. Specific policy requirements "
        "take precedence over general guidance. Never invent tool capabilities or "
        "claim an action succeeded before receiving its authoritative result. "
    )
    return (
        "<instructions>\n"
        + instruction * 3
        + "\n</instructions>\n<policy>\n"
        + policy * 3
        + "\n</policy>\n"
    )


def test_optimizer_tools_require_complete_coverage_before_one_submission(
    tmp_path: Path,
) -> None:
    toolkit = OptimizerPacketTools(synthetic_packet(tmp_path))
    assert set(ToolCatalog(toolkit.get_tools().values()).names) == {
        "inspect_packet",
        "read_analysis_ledger",
        "read_packet_file",
        "read_trace",
        "record_trace_analysis",
        "record_tool_analysis",
        "submit_optimization",
    }
    with pytest.raises(OptimizerRunError, match="coverage is incomplete"):
        toolkit.submit_optimization("report " * 100, candidate_prompt())

    complete_evidence(toolkit)
    with pytest.raises(OptimizerRunError, match="ledger_read_incomplete"):
        toolkit.submit_optimization("report " * 100, candidate_prompt())
    ledger = toolkit.read_analysis_ledger(max_chars=200_000)
    assert ledger["eof"] is True
    assert "success_regression_control" in ledger["content"]
    accepted = toolkit.submit_optimization("report " * 100, candidate_prompt())
    assert accepted["accepted"] is True
    assert accepted["trace_coverage"] == 48
    assert accepted["tool_coverage"] == 17
    coverage = toolkit.coverage_manifest()
    assert coverage["traces_complete"] == 48
    assert coverage["trace_analysis_count"] == 48
    assert coverage["tool_analysis_count"] == 17
    assert coverage["analysis_ledger_complete"] is True
    assert coverage["submission_count"] == 1
    with pytest.raises(OptimizerRunError, match="already submitted"):
        toolkit.submit_optimization("report " * 100, candidate_prompt())


def test_non_submission_tool_argument_error_is_returned_for_correction(
    tmp_path: Path,
) -> None:
    toolkit = OptimizerPacketTools(synthetic_packet(tmp_path))
    toolkit.inspect_packet()
    errors: list[dict[str, str]] = []
    result = _execute_calls(
        [
            ToolCall(
                id="call-1",
                name="read_trace",
                arguments={"trace_ref": "train_trace_049"},
                requestor="assistant",
            )
        ],
        toolkit.get_tools(),
        errors,
    )
    assert isinstance(result, ToolMessage)
    assert result.error is True
    assert json.loads(result.content or "null") == {
        "error": "unknown or unauthorized trace",
        "recoverable": True,
    }
    assert len(errors) == 1
    assert errors[0]["tool"] == "read_trace"
    assert set(errors[0]) == {"tool", "error_sha256", "arguments_sha256"}


def test_submission_before_structural_coverage_remains_fatal(tmp_path: Path) -> None:
    toolkit = OptimizerPacketTools(synthetic_packet(tmp_path))
    with pytest.raises(OptimizerRunError, match="coverage is incomplete"):
        _execute_calls(
            [
                ToolCall(
                    id="call-1",
                    name="submit_optimization",
                    arguments={
                        "optimization_report": "report " * 100,
                        "optimized_prompt": candidate_prompt(),
                    },
                    requestor="assistant",
                )
            ],
            toolkit.get_tools(),
            [],
        )


def test_trace_analysis_requires_full_read_and_correct_outcome_class(
    tmp_path: Path,
) -> None:
    toolkit = OptimizerPacketTools(synthetic_packet(tmp_path))
    toolkit.inspect_packet()
    with pytest.raises(OptimizerRunError, match="not fully read"):
        toolkit.record_trace_analysis(
            "train_trace_001",
            "success_regression_control",
            "General causal observation.",
            "Preserve the successful behavior.",
        )
    toolkit.read_trace("train_trace_001", max_chars=200_000)
    with pytest.raises(OptimizerRunError, match="must be regression controls"):
        toolkit.record_trace_analysis(
            "train_trace_001",
            "failure",
            "General causal observation.",
            "Preserve the successful behavior.",
        )


def test_submission_retains_optimizer_output_without_content_rejection(
    tmp_path: Path,
) -> None:
    toolkit = OptimizerPacketTools(synthetic_packet(tmp_path))
    complete_evidence(toolkit)
    toolkit.read_analysis_ledger(max_chars=200_000)
    report = "short report retained exactly"
    prompt = "arbitrary prompt containing trace, grader, reward, and task_004"
    toolkit.submit_optimization(report, prompt)
    assert toolkit.submission == {
        "optimization_report": report,
        "optimized_prompt": prompt,
    }


def test_optimizer_model_catalog_requires_sol_max() -> None:
    catalog = {
        "data": [
            {
                "id": OPTIMIZER_MODEL,
                "model": OPTIMIZER_MODEL,
                "hidden": False,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "high"},
                    {"reasoningEffort": OPTIMIZER_REASONING_EFFORT},
                ],
            }
        ]
    }
    result = require_model_catalog(
        catalog,
        model=OPTIMIZER_MODEL,
        reasoning_effort=OPTIMIZER_REASONING_EFFORT,
    )
    assert result["requested"] == OPTIMIZER_MODEL
    with pytest.raises(AuthError, match="does not advertise ultra"):
        require_model_catalog(
            catalog,
            model=OPTIMIZER_MODEL,
            reasoning_effort="ultra",
        )


def test_minimal_optimize_command_has_no_required_arguments() -> None:
    arguments = _parser().parse_args(["optimize"])
    assert arguments.command == "optimize"
    assert arguments.source_run == Path("runs/vanilla-train-alltools-20260808T212330Z")
    assert arguments.output_dir is None
    assert arguments.preflight_only is False


def test_packet_rejects_any_other_train_results(tmp_path: Path) -> None:
    packet = synthetic_packet(tmp_path)
    manifest_path = packet / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_results_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(OptimizerRunError, match="fixed authorized train evidence"):
        OptimizerPacketTools(packet)


def test_non_submission_bundle_is_local_and_diagnostic(tmp_path: Path) -> None:
    output = tmp_path / "optimizer-runs" / "failed-attempt"
    _write_non_submission_bundle(
        output_dir=output,
        final_response="No submission was made.",
        audit={"turns_started": 1, "turns_completed": 1},
        coverage={"submission_count": 0},
        provenance={"commit": "abc123", "tracked_worktree_clean": True},
    )
    receipt = json.loads((output / "failure.json").read_text())
    assert receipt["classification"] == "failed optimizer attempt: no submission"
    assert receipt["final_response"]["path"] == "final-response.txt"
    assert receipt["coverage"]["submission_count"] == 0
    assert receipt["promotion"] == {
        "active_prompt_unchanged": True,
        "evaluation_run": False,
    }
    assert (output / "final-response.txt").read_text() == "No submission was made."
