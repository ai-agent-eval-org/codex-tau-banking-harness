"""Preflight and exactly bounded two-task smoke execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tau2.data_model.simulation import Results, TerminationReason, TextRunConfig
from tau2.domains.banking_knowledge.environment import (
    get_db,
    get_knowledge_base,
)
from tau2.domains.banking_knowledge.retrieval import get_info_policy_override
from tau2.domains.banking_knowledge.retrieval_toolkits import KnowledgeToolsAllTools
from tau2.registry import registry
from tau2.runner.batch import run_tasks
from tau2.runner.helpers import get_tasks

from .agent import create_codex_tau_agent
from .app_server import CodexAppServer
from .auth import CODEX_VERSION
from .manifest import write_manifest
from .prompt import VerifiedPrompt, verify_prompt
from .tool_bridge import ToolCatalog

TAU_TAG = "v1.0.1"
TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
AUTHORIZED_TASKS = ["task_001", "task_004"]
AGENT_NAME = "codex_tau_dynamic"


class ExperimentError(RuntimeError):
    """An experiment violates a fixed smoke-run or security invariant."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_experiment(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    experiment = raw.get("experiment")
    provenance = raw.get("experttrace")
    if not isinstance(experiment, dict) or not isinstance(provenance, dict):
        raise ExperimentError("experiment TOML needs [experiment] and [experttrace]")
    required = {
        "domain": "banking_knowledge",
        "retrieval": "alltools",
        "agent_model": "gpt-5.4",
        "agent_reasoning": "xhigh",
        "user_model": "gpt-5.2",
        "user_reasoning": "low",
        "seed": 300,
        "trials_per_task": 1,
        "task_ids": AUTHORIZED_TASKS,
    }
    for key, expected in required.items():
        if experiment.get(key) != expected:
            raise ExperimentError(
                f"{key} must remain {expected!r}, got {experiment.get(key)!r}"
            )
    arm = experiment.get("arm")
    if arm not in {"baseline", "candidate"}:
        raise ExperimentError("arm must be baseline or candidate")
    expected_path = f"prompts/banking_knowledge/{arm}.md"
    if experiment.get("prompt_path") != expected_path:
        raise ExperimentError(f"{arm} prompt must be {expected_path}")
    if not provenance.get("project_id") or not provenance.get("workspace_branch"):
        raise ExperimentError("ExpertTrace project/workspace provenance is required")
    if arm == "candidate" and not all(
        provenance.get(key) for key in ("optimization_id", "candidate_branch")
    ):
        raise ExperimentError("candidate optimization provenance is required")
    return experiment, provenance


def _alltools_contract() -> tuple[list[Any], str]:
    """Build exact schemas without constructing embedder/sandbox runtimes."""
    toolkit = KnowledgeToolsAllTools(get_db(), object(), object(), object())
    tools = list(toolkit.get_tools().values())
    policy = get_info_policy_override("alltools", get_knowledge_base())
    return tools, policy


def _require_parent_prerequisites() -> dict[str, str]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ExperimentError(
            "OPENAI_API_KEY is unavailable to the parent τ-bench process; "
            "alltools embeddings and the GPT-5.2 simulator cannot run"
        )
    sandbox = shutil.which("srt")
    if sandbox is None:
        raise ExperimentError("alltools requires the `srt` sandbox executable")
    completed = subprocess.run(
        [sandbox, "--version"], capture_output=True, check=False, text=True, timeout=30
    )
    if completed.returncode != 0:
        raise ExperimentError("the `srt` sandbox executable failed its version check")
    return {"srt_path": sandbox, "srt_version": completed.stdout.strip()}


def preflight(
    experiment_path: Path, *, require_platform_key: bool = True
) -> dict[str, Any]:
    repo_root = _repo_root()
    experiment, provenance = load_experiment(experiment_path)
    prompt = verify_prompt(repo_root, experiment, provenance)
    prerequisites = (
        _require_parent_prerequisites() if require_platform_key else {}
    )
    tasks = get_tasks("banking_knowledge", task_split_name=None, task_ids=AUTHORIZED_TASKS)
    if [task.id for task in tasks] != AUTHORIZED_TASKS:
        raise ExperimentError("τ-bench returned a different fixed task ordering")
    tools, policy = _alltools_contract()
    catalog = ToolCatalog(tools)
    runtime = CodexAppServer(
        repo_root=repo_root,
        tools=tools,
        domain_policy=policy,
        prompt=prompt.text,
    )
    try:
        runtime_audit = dict(runtime.audit)
    finally:
        runtime.close()
    if runtime_audit.get("instruction_sources") != []:
        raise ExperimentError("Codex discovered an implicit instruction source")
    if runtime_audit.get("observed_thread_model") != "gpt-5.4":
        raise ExperimentError("Codex did not start the requested GPT-5.4 thread")
    return {
        "status": "ready",
        "experiment": experiment["name"],
        "task_ids": AUTHORIZED_TASKS,
        "prompt_sha256": prompt.sha256,
        "policy_sha256": _sha256_text(policy),
        "tool_names": list(catalog.names),
        "tool_schema_sha256": catalog.hash,
        "codex_version": CODEX_VERSION,
        "account": runtime_audit["account"],
        "model": runtime_audit["model"],
        "rate_limit_ids": runtime_audit.get("rate_limit_ids", []),
        "child_platform_keys_present": False,
        **prerequisites,
    }


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def _collect_audits(audit_dir: Path) -> list[dict[str, Any]]:
    audits = []
    for task_id in AUTHORIZED_TASKS:
        path = audit_dir / f"{task_id}.json"
        if not path.is_file():
            raise ExperimentError(f"missing adapter audit for {task_id}")
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ExperimentError(f"malformed adapter audit for {task_id}")
        audits.append(value)
    return audits


def _validate_results(results: Results) -> None:
    if len(results.simulations) != 2:
        raise ExperimentError("an arm must contain exactly two simulations")
    if [simulation.task_id for simulation in results.simulations] != AUTHORIZED_TASKS:
        raise ExperimentError("result task IDs/order differ from the fixed smoke set")
    for simulation in results.simulations:
        if simulation.trial != 0:
            raise ExperimentError("each smoke task must have exactly one trial")
        if simulation.termination_reason in {
            TerminationReason.INFRASTRUCTURE_ERROR,
            TerminationReason.UNEXPECTED_ERROR,
        }:
            detail = simulation.info.get("error") if simulation.info else None
            raise ExperimentError(
                f"{simulation.task_id} ended in infrastructure failure: {detail}"
            )


def run_experiment(experiment_path: Path) -> Path:
    started_at = _utc_now()
    repo_root = _repo_root()
    experiment, provenance = load_experiment(experiment_path)
    verified_prompt: VerifiedPrompt = verify_prompt(repo_root, experiment, provenance)
    check = preflight(experiment_path)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = repo_root / "runs" / f"{experiment['name']}-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    audit_dir = output_dir / "adapter-audits"
    results_path = output_dir / "results.json"

    if registry.get_agent_factory(AGENT_NAME) is None:
        registry.register_agent_factory(create_codex_tau_agent, AGENT_NAME)
    tasks = get_tasks("banking_knowledge", task_split_name=None, task_ids=AUTHORIZED_TASKS)
    config = TextRunConfig(
        domain="banking_knowledge",
        task_set_name="banking_knowledge",
        task_split_name=None,
        task_ids=AUTHORIZED_TASKS,
        agent=AGENT_NAME,
        llm_agent="gpt-5.4",
        llm_args_agent={
            "repo_root": str(repo_root),
            "audit_dir": str(audit_dir),
            "prompt": verified_prompt.text,
        },
        user="user_simulator",
        llm_user="gpt-5.2",
        llm_args_user={"reasoning_effort": "low"},
        num_trials=1,
        max_steps=100,
        max_errors=10,
        max_concurrency=1,
        seed=300,
        max_retries=0,
        hallucination_retries=0,
        auto_resume=False,
        auto_review=False,
        verbose_logs=False,
        retrieval_config="alltools",
    )
    run_tasks(
        config,
        tasks,
        save_path=results_path,
        save_dir=output_dir,
        console_display=True,
        results_format="json",
    )
    reloaded = Results.load(results_path)
    _validate_results(reloaded)
    audits = _collect_audits(audit_dir)
    dynamic_calls = sum(int(audit.get("dynamic_call_count", 0)) for audit in audits)
    if dynamic_calls < 1:
        raise ExperimentError("no real Codex dynamic-tool round trip was captured")
    if any(audit.get("native_capability_denied") for audit in audits):
        raise ExperimentError("a denied Codex-native capability event was observed")
    if any(audit.get("model_rerouted") for audit in audits):
        raise ExperimentError("Codex rerouted the evaluated model")
    for audit in audits:
        if audit.get("instruction_sources") != []:
            raise ExperimentError("Codex discovered repository instructions")
        if audit.get("account", {}).get("type") != "chatgpt":
            raise ExperimentError("a simulation did not use ChatGPT authentication")

    policy = reloaded.info.environment_info.policy
    ended_at = _utc_now()
    manifest = {
        "format_version": 1,
        "experiment": {"name": experiment["name"], "arm": experiment["arm"]},
        "harness": {
            "repository": "https://github.com/ai-agent-eval-org/codex-tau-banking-harness",
            "commit": _git_head(repo_root),
        },
        "tau_bench": {"tag": TAU_TAG, "commit": TAU_COMMIT},
        "codex": {
            "version": CODEX_VERSION,
            "requested_model": "gpt-5.4",
            "observed_models": sorted(
                {str(audit["observed_thread_model"]) for audit in audits}
            ),
            "reasoning_effort": "xhigh",
            "authentication_mode": "chatgpt",
            "plan_type": audits[0]["account"].get("plan_type"),
            "rate_limit_ids": check.get("rate_limit_ids", []),
            "child_platform_keys_present": False,
            "model_rerouted": False,
            "denied_native_event_observed": False,
        },
        "prompt": {
            "path": verified_prompt.path,
            "sha256": verified_prompt.sha256,
            "source_path": verified_prompt.source_path,
            "source_commit": verified_prompt.source_commit,
            "workspace_branch": provenance["workspace_branch"],
            "candidate_branch": provenance.get("candidate_branch") or None,
        },
        "experttrace": {
            "project_id": provenance["project_id"],
            "workspace": provenance["workspace"],
            "optimization_id": provenance.get("optimization_id") or None,
        },
        "banking": {
            "domain": "banking_knowledge",
            "retrieval": "alltools",
            "policy_sha256": _sha256_text(policy),
            "ordered_tool_names": check["tool_names"],
            "tool_schema_sha256": check["tool_schema_sha256"],
        },
        "user_simulator": {"model": "gpt-5.2", "reasoning_effort": "low"},
        "execution": {
            "seed": 300,
            "task_ids": AUTHORIZED_TASKS,
            "trials_per_task": 1,
            "simulation_count": 2,
            "dynamic_tool_call_count": dynamic_calls,
            "start_time": started_at,
            "end_time": ended_at,
            "results_reloaded": True,
            "results_path": str(results_path.relative_to(repo_root)),
            "audit_paths": [
                str((audit_dir / f"{task_id}.json").relative_to(repo_root))
                for task_id in AUTHORIZED_TASKS
            ],
            "terminations": {
                simulation.task_id: simulation.termination_reason.value
                for simulation in reloaded.simulations
            },
        },
    }
    write_manifest(output_dir / "manifest.json", manifest)
    return output_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-tau")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "run"):
        child = subparsers.add_parser(command)
        child.add_argument("experiment", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "preflight":
            print(json.dumps(preflight(arguments.experiment), indent=2, sort_keys=True))
        else:
            output = run_experiment(arguments.experiment)
            print(f"verified smoke artifacts: {output}")
    except Exception as exc:
        print(f"codex-tau: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
