"""Preflight and exactly bounded local banking evaluations."""

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
from .app_server import BASE_INSTRUCTIONS_SHA256, CodexAppServer
from .auth import CODEX_VERSION
from .manifest import write_manifest
from .prompt import VerifiedPrompt, verify_prompt
from .task_split import (
    SPLIT_ALGORITHM,
    SPLIT_SEED,
    SPLIT_TEST_FRACTION,
    TEST_TASK_IDS,
    TRAIN_TASK_IDS,
    split_sha256,
)
from .tool_bridge import ToolCatalog

TAU_TAG = "v1.0.1"
TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
SMOKE_TASK_IDS = ("task_001", "task_004")
AGENT_NAME = "codex_tau_dynamic"


class ExperimentError(RuntimeError):
    """An experiment violates a fixed evaluation or security invariant."""


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
    }
    for key, expected in required.items():
        if experiment.get(key) != expected:
            raise ExperimentError(
                f"{key} must remain {expected!r}, got {experiment.get(key)!r}"
            )
    arm = experiment.get("arm")
    if arm not in {"baseline", "candidate"}:
        raise ExperimentError("arm must be baseline or candidate")
    partition = experiment.get("task_partition")
    if partition == "smoke":
        authorized_task_ids = SMOKE_TASK_IDS
        expected_concurrency = 1
    elif partition == "test":
        if arm != "candidate":
            raise ExperimentError("the frozen test partition must use the candidate arm")
        authorized_task_ids = TEST_TASK_IDS
        expected_concurrency = 4
    else:
        raise ExperimentError("task_partition must be smoke or test")
    if experiment.get("task_ids") != list(authorized_task_ids):
        raise ExperimentError(
            f"task_ids must equal the frozen {partition} task list"
        )
    if experiment.get("max_concurrency") != expected_concurrency:
        raise ExperimentError(
            f"max_concurrency must be {expected_concurrency} for {partition}"
        )
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
    task_ids = tuple(experiment["task_ids"])
    prompt = verify_prompt(repo_root, experiment, provenance)
    prerequisites = (
        _require_parent_prerequisites() if require_platform_key else {}
    )
    tasks = get_tasks("banking_knowledge", task_split_name=None, task_ids=task_ids)
    if tuple(task.id for task in tasks) != task_ids:
        raise ExperimentError("τ-bench returned a different frozen task ordering")
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
        "task_partition": experiment["task_partition"],
        "task_ids": list(task_ids),
        "task_count": len(task_ids),
        "local_split_sha256": split_sha256(),
        "prompt_sha256": prompt.sha256,
        "base_instructions_sha256": BASE_INSTRUCTIONS_SHA256,
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


def _collect_audits(
    audit_dir: Path, task_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    audits = []
    for task_id in task_ids:
        path = audit_dir / f"{task_id}.json"
        if not path.is_file():
            raise ExperimentError(f"missing adapter audit for {task_id}")
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ExperimentError(f"malformed adapter audit for {task_id}")
        audits.append(value)
    return audits


def _validate_results(results: Results, task_ids: tuple[str, ...]) -> None:
    if len(results.simulations) != len(task_ids):
        raise ExperimentError(
            f"expected {len(task_ids)} simulations, got {len(results.simulations)}"
        )
    result_task_ids = [simulation.task_id for simulation in results.simulations]
    if len(set(result_task_ids)) != len(result_task_ids):
        raise ExperimentError("results contain duplicate task IDs")
    if set(result_task_ids) != set(task_ids):
        raise ExperimentError("result task IDs differ from the frozen task set")
    for simulation in results.simulations:
        if simulation.trial != 0:
            raise ExperimentError("each task must have exactly one trial")
        if simulation.reward_info is None:
            raise ExperimentError(f"{simulation.task_id} has no reward")
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
    task_ids = tuple(experiment["task_ids"])
    verified_prompt: VerifiedPrompt = verify_prompt(repo_root, experiment, provenance)
    check = preflight(experiment_path)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = repo_root / "runs" / f"{experiment['name']}-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    audit_dir = output_dir / "adapter-audits"
    results_path = output_dir / "results.json"

    if registry.get_agent_factory(AGENT_NAME) is None:
        registry.register_agent_factory(create_codex_tau_agent, AGENT_NAME)
    tasks = get_tasks("banking_knowledge", task_split_name=None, task_ids=task_ids)
    config = TextRunConfig(
        domain="banking_knowledge",
        task_set_name="banking_knowledge",
        task_split_name=None,
        task_ids=list(task_ids),
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
        max_concurrency=experiment["max_concurrency"],
        seed=experiment["seed"],
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
    _validate_results(reloaded, task_ids)
    audits = _collect_audits(audit_dir, task_ids)
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
    rewards = [
        float(simulation.reward_info.reward)
        for simulation in reloaded.simulations
        if simulation.reward_info is not None
    ]
    pass_at_1 = sum(rewards) / len(rewards)
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
            "common_base_instructions_sha256": BASE_INSTRUCTIONS_SHA256,
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
            "local_split": {
                "algorithm": SPLIT_ALGORITHM,
                "seed": SPLIT_SEED,
                "test_fraction": SPLIT_TEST_FRACTION,
                "train_count": len(TRAIN_TASK_IDS),
                "test_count": len(TEST_TASK_IDS),
                "sha256": split_sha256(),
            },
        },
        "user_simulator": {"model": "gpt-5.2", "reasoning_effort": "low"},
        "execution": {
            "seed": experiment["seed"],
            "task_partition": experiment["task_partition"],
            "task_ids": list(task_ids),
            "trials_per_task": 1,
            "max_concurrency": experiment["max_concurrency"],
            "simulation_count": len(task_ids),
            "dynamic_tool_call_count": dynamic_calls,
            "start_time": started_at,
            "end_time": ended_at,
            "results_reloaded": True,
            "results_path": str(results_path.relative_to(repo_root)),
            "audit_paths": [
                str((audit_dir / f"{task_id}.json").relative_to(repo_root))
                for task_id in task_ids
            ],
            "terminations": {
                simulation.task_id: simulation.termination_reason.value
                for simulation in reloaded.simulations
            },
        },
        "score": {
            "metric": "Pass@1 (mean single-trial reward)",
            "pass_at_1": pass_at_1,
            "percent": pass_at_1 * 100,
            "passed": sum(reward == 1.0 for reward in rewards),
            "failed": sum(reward != 1.0 for reward in rewards),
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
            print(f"verified local evaluation artifacts: {output}")
    except Exception as exc:
        print(f"codex-tau: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
