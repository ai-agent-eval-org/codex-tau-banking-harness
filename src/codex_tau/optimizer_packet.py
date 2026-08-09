"""Export a leakage-safe, train-only packet for one-shot prompt optimization."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .run import VANILLA_TRAIN_EXPERIMENT, _alltools_contract
from .task_split import TRAIN_TASK_IDS, split_sha256
from .tool_bridge import ToolCatalog

BASELINE_PATH = Path("prompts/banking_knowledge/baseline.md")
OPTIMIZER_PATH = Path("prompts/banking_knowledge/optimizer.md")
EXPECTED_TERMINATION = "user_stop"
TRACE_MESSAGE_KEYS = (
    "id",
    "role",
    "content",
    "tool_calls",
    "requestor",
    "error",
)


class OptimizerPacketError(RuntimeError):
    """The source evidence is incomplete, unauthorized, or malformed."""


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OptimizerPacketError(f"cannot read {path}") from exc
    if not isinstance(value, dict):
        raise OptimizerPacketError(f"{path} must contain a JSON object")
    return value


def _require(value: bool, message: str) -> None:
    if not value:
        raise OptimizerPacketError(message)


def sanitize_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the complete model-visible exchange while dropping provider metadata."""
    sanitized = {
        key: message[key]
        for key in TRACE_MESSAGE_KEYS
        if key in message and message[key] is not None
    }
    _require(
        sanitized.get("role") in {"assistant", "user", "tool"},
        "trace message has an invalid role",
    )
    return sanitized


def _validated_simulations(
    results: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    simulations = results.get("simulations")
    _require(isinstance(simulations, list), "results.simulations must be a list")
    _require(
        len(simulations) == len(TRAIN_TASK_IDS),
        f"expected {len(TRAIN_TASK_IDS)} train simulations",
    )
    _require(
        all(isinstance(simulation, dict) for simulation in simulations),
        "every simulation must be an object",
    )
    by_task = {simulation.get("task_id"): simulation for simulation in simulations}
    _require(
        len(by_task) == len(simulations),
        "source run contains duplicate or missing task IDs",
    )
    _require(
        set(by_task) == set(TRAIN_TASK_IDS),
        "source run is not the frozen train partition",
    )
    ordered = [by_task[task_id] for task_id in TRAIN_TASK_IDS]
    for simulation in ordered:
        task_id = simulation["task_id"]
        _require(simulation.get("trial") == 0, f"{task_id}: expected trial 0")
        _require(
            simulation.get("termination_reason") == EXPECTED_TERMINATION,
            f"{task_id}: expected {EXPECTED_TERMINATION}",
        )
        messages = simulation.get("messages")
        _require(
            isinstance(messages, list) and messages,
            f"{task_id}: missing messages",
        )
        reward_info = simulation.get("reward_info")
        _require(isinstance(reward_info, dict), f"{task_id}: missing reward_info")
        _require(
            reward_info.get("reward") in {0, 0.0, 1, 1.0},
            f"{task_id}: reward must be binary",
        )
    return ordered


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    experiment = manifest.get("experiment")
    execution = manifest.get("execution")
    banking = manifest.get("banking")
    prompt = manifest.get("prompt")
    _require(isinstance(experiment, dict), "manifest.experiment is missing")
    _require(isinstance(execution, dict), "manifest.execution is missing")
    _require(isinstance(banking, dict), "manifest.banking is missing")
    _require(isinstance(prompt, dict), "manifest.prompt is missing")
    _require(
        experiment.get("name") == VANILLA_TRAIN_EXPERIMENT,
        "source is not vanilla-train-alltools",
    )
    _require(execution.get("task_partition") == "train", "source is not train")
    _require(execution.get("trials_per_task") == 1, "expected one trial per task")
    _require(execution.get("simulation_count") == 48, "expected 48 simulations")
    _require(execution.get("task_ids") == list(TRAIN_TASK_IDS), "task order drift")
    _require(banking.get("retrieval") == "alltools", "expected alltools retrieval")
    _require(prompt.get("custom_prompt") is False, "source prompt is not baseline")


def export_optimizer_packet(
    *, repo_root: Path, source_run: Path, output_dir: Path
) -> dict[str, Any]:
    """Validate and export one exact train-only optimizer input packet."""
    repo_root = repo_root.resolve()
    source_run = source_run.resolve()
    output_dir = output_dir.resolve()
    _require(not output_dir.exists(), f"output already exists: {output_dir}")

    results_path = source_run / "results.json"
    manifest_path = source_run / "manifest.json"
    baseline_path = repo_root / BASELINE_PATH
    optimizer_path = repo_root / OPTIMIZER_PATH
    results = _load_object(results_path)
    source_manifest = _load_object(manifest_path)
    _validate_manifest(source_manifest)
    simulations = _validated_simulations(results)

    tools, _ = _alltools_contract()
    catalog = ToolCatalog(tools)
    source_tool_hash = source_manifest["banking"].get("tool_schema_sha256")
    _require(catalog.hash == source_tool_hash, "authoritative tool-schema drift")

    output_dir.mkdir(parents=True)
    traces_dir = output_dir / "production_traces"
    traces_dir.mkdir()
    shutil.copyfile(baseline_path, output_dir / "baseline_prompt.md")
    shutil.copyfile(optimizer_path, output_dir / "optimizer.md")
    tool_definitions = []
    for tool, dynamic in zip(tools, catalog.specs, strict=True):
        tool_definitions.append(
            {
                "name": dynamic["name"],
                "description": dynamic["description"],
                "input_schema": dynamic["inputSchema"],
                "output_schema": tool.returns.model_json_schema(),
                "raises": tool.raises,
                "examples": tool.examples,
            }
        )
    (output_dir / "tool_definitions.json").write_text(
        json.dumps(
            {
                "model_visible_catalog_sha256": catalog.hash,
                "tool_count": len(tool_definitions),
                "tools": tool_definitions,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    rewards: Counter[int] = Counter()
    trace_entries: list[dict[str, Any]] = []
    for index, simulation in enumerate(simulations, start=1):
        trace_ref = f"train_trace_{index:03d}"
        reward = int(simulation["reward_info"]["reward"])
        rewards[reward] += 1
        trace = {
            "trace_ref": trace_ref,
            "termination_reason": simulation["termination_reason"],
            "reward": reward,
            "messages": [sanitize_message(message) for message in simulation["messages"]],
        }
        trace_path = traces_dir / f"{trace_ref}.json"
        trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
        trace_entries.append(
            {
                "trace_ref": trace_ref,
                "reward": reward,
                "message_count": len(trace["messages"]),
                "sha256": _sha256_path(trace_path),
            }
        )

    fixed_runtime_contract = {
        "domain": source_manifest["banking"]["domain"],
        "retrieval": source_manifest["banking"]["retrieval"],
        "tool_schema_sha256": catalog.hash,
        "ordered_tool_names": list(catalog.names),
        "tau_bench": source_manifest["tau_bench"],
        "codex": source_manifest["codex"],
        "user_simulator": source_manifest["user_simulator"],
        "max_steps": source_manifest["execution"]["max_steps"],
        "max_errors": source_manifest["execution"]["max_errors"],
        "additional_developer_instructions": False,
        "editable_surface": "baseline_prompt.md only",
    }
    (output_dir / "fixed_runtime_contract.json").write_text(
        json.dumps(fixed_runtime_contract, indent=2, ensure_ascii=False) + "\n"
    )

    evidence_manifest = {
        "format_version": 1,
        "authorization": "train-only one-shot full-prompt optimization",
        "authorized_partition": "train",
        "source_experiment": VANILLA_TRAIN_EXPERIMENT,
        "source_run_basename": source_run.name,
        "source_results_sha256": _sha256_path(results_path),
        "source_manifest_sha256": _sha256_path(manifest_path),
        "source_task_ids_sha256": _canonical_sha256(list(TRAIN_TASK_IDS)),
        "split_sha256": split_sha256(),
        "expected_trace_count": len(TRAIN_TASK_IDS),
        "exported_trace_count": len(trace_entries),
        "passed": rewards[1],
        "failed": rewards[0],
        "termination_reasons": {EXPECTED_TERMINATION: len(trace_entries)},
        "baseline_prompt_sha256": _sha256_path(output_dir / "baseline_prompt.md"),
        "optimizer_instruction_sha256": _sha256_path(output_dir / "optimizer.md"),
        "tool_definitions_sha256": _sha256_path(output_dir / "tool_definitions.json"),
        "tool_schema_sha256": catalog.hash,
        "tool_count": len(tool_definitions),
        "traces": trace_entries,
        "excluded_as_unauthorized_or_nontrajectory": [
            "top-level task definitions and evaluation criteria",
            "reward action checks, database checks, assertions, and grader details",
            "provider raw responses, usage, cost, timing, and audio metadata",
            "every pilot, validation, test, and prior optimized artifact",
        ],
        "completeness_verdict": (
            "complete: every model-visible message, tool call, and tool result from "
            "all 48 authorized train trajectories is present"
        ),
    }
    (output_dir / "evidence_manifest.json").write_text(
        json.dumps(evidence_manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return evidence_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = export_optimizer_packet(
        repo_root=args.repo_root,
        source_run=args.source_run,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
