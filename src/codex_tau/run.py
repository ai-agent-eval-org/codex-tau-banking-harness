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
from tau2.domains.banking_knowledge.retrieval_toolkits import (
    KnowledgeToolsAllTools,
    KnowledgeToolsWithShell,
)
from tau2.registry import registry
from tau2.runner.batch import run_tasks
from tau2.runner.helpers import get_tasks

from .agent import audit_filename, create_codex_tau_agent
from .app_server import APP_SERVER_STREAM_READER_LIMIT_BYTES, CodexAppServer
from .auth import CODEX_VERSION
from .manifest import write_manifest
from .prompt import (
    STANDARD_AGENT_INSTRUCTION_SHA256,
    standard_system_prompt,
)
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
PILOT2_TASK_IDS = TEST_TASK_IDS[:2]
PILOT5_TASK_IDS = TEST_TASK_IDS[:5]
AGENT_NAME = "codex_tau_dynamic"


class ExperimentError(RuntimeError):
    """An experiment violates a fixed evaluation or security invariant."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _show_per_task_console(task_partition: str) -> bool:
    """Keep held-out task outcomes out of prompt-development feedback."""
    if task_partition not in {"smoke", "pilot2", "pilot5", "test"}:
        raise ExperimentError(f"unknown task partition: {task_partition!r}")
    return task_partition == "smoke"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_experiment(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    experiment = raw.get("experiment")
    if not isinstance(experiment, dict):
        raise ExperimentError("experiment TOML needs [experiment]")
    required = {
        "domain": "banking_knowledge",
        "agent_model": "gpt-5.4",
        "agent_reasoning": "high",
        "user_model": "gpt-5.2",
        "user_reasoning": "low",
        "seed": 300,
        "max_steps": 200,
        "max_errors": 10,
    }
    for key, expected in required.items():
        if experiment.get(key) != expected:
            raise ExperimentError(
                f"{key} must remain {expected!r}, got {experiment.get(key)!r}"
            )
    profiles = {
        "tau_reference_trial0": "terminal_use",
        "alltools_concurrency_validation_4trials": "alltools",
        "alltools_pilot_4trials": "alltools",
    }
    profile = experiment.get("profile")
    expected_retrieval = profiles.get(profile)
    if expected_retrieval is None:
        raise ExperimentError(f"unknown experiment profile: {profile!r}")
    if experiment.get("retrieval") != expected_retrieval:
        raise ExperimentError(
            f"retrieval must be {expected_retrieval!r} for {profile!r}"
        )
    partition = experiment.get("task_partition")
    if partition == "smoke":
        authorized_task_ids = SMOKE_TASK_IDS
        expected_profile = "tau_reference_trial0"
        expected_trials = 1
        expected_concurrency = 1
    elif partition == "pilot2":
        authorized_task_ids = PILOT2_TASK_IDS
        expected_profile = "alltools_concurrency_validation_4trials"
        expected_trials = 4
        expected_concurrency = 2
    elif partition == "pilot5":
        authorized_task_ids = PILOT5_TASK_IDS
        expected_profile = "alltools_pilot_4trials"
        expected_trials = 4
        expected_concurrency = 8
    elif partition == "test":
        authorized_task_ids = TEST_TASK_IDS
        expected_profile = "tau_reference_trial0"
        expected_trials = 1
        expected_concurrency = 1
    else:
        raise ExperimentError("task_partition must be smoke, pilot2, pilot5, or test")
    if profile != expected_profile:
        raise ExperimentError(f"profile must be {expected_profile!r} for {partition!r}")
    if experiment.get("trials_per_task") != expected_trials:
        raise ExperimentError(
            f"trials_per_task must be {expected_trials} for {partition!r}"
        )
    if experiment.get("task_ids") != list(authorized_task_ids):
        raise ExperimentError(f"task_ids must equal the frozen {partition} task list")
    if experiment.get("max_concurrency") != expected_concurrency:
        raise ExperimentError(
            f"max_concurrency must be {expected_concurrency} for {partition}"
        )
    forbidden = {"prompt_path", "custom_prompt", "developer_instructions"}
    if forbidden & experiment.keys():
        raise ExperimentError("the reference profile forbids custom prompt fields")
    return experiment


def _terminal_contract() -> tuple[list[Any], str]:
    """Build terminal_use schemas without constructing the sandbox runtime."""
    toolkit = KnowledgeToolsWithShell(get_db(), object())
    tools = list(toolkit.get_tools().values())
    policy = get_info_policy_override("terminal_use", get_knowledge_base())
    return tools, policy


def _alltools_contract() -> tuple[list[Any], str]:
    """Build alltools schemas without constructing live retrieval runtimes."""
    toolkit = KnowledgeToolsAllTools(get_db(), object(), object(), object())
    tools = list(toolkit.get_tools().values())
    policy = get_info_policy_override("alltools", get_knowledge_base())
    return tools, policy


def _retrieval_contract(retrieval: str) -> tuple[list[Any], str]:
    if retrieval == "terminal_use":
        return _terminal_contract()
    if retrieval == "alltools":
        return _alltools_contract()
    raise ExperimentError(f"unsupported retrieval profile: {retrieval!r}")


def _require_parent_prerequisites() -> dict[str, str]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ExperimentError(
            "OPENAI_API_KEY is unavailable to the parent τ-bench process; "
            "the GPT-5.2 simulator cannot run"
        )
    sandbox = shutil.which("srt")
    if sandbox is None:
        raise ExperimentError("terminal_use requires the `srt` sandbox executable")
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
    experiment = load_experiment(experiment_path)
    task_ids = tuple(experiment["task_ids"])
    prerequisites = _require_parent_prerequisites() if require_platform_key else {}
    tasks = get_tasks("banking_knowledge", task_split_name=None, task_ids=task_ids)
    if tuple(task.id for task in tasks) != task_ids:
        raise ExperimentError("τ-bench returned a different frozen task ordering")
    tools, policy = _retrieval_contract(experiment["retrieval"])
    catalog = ToolCatalog(tools)
    system_prompt = standard_system_prompt(policy)
    runtime = CodexAppServer(
        repo_root=repo_root,
        tools=tools,
        system_prompt=system_prompt,
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
        "trials_per_task": experiment["trials_per_task"],
        "simulation_count": len(task_ids) * experiment["trials_per_task"],
        "max_concurrency": experiment["max_concurrency"],
        "local_split_sha256": split_sha256(),
        "prompt_mode": "tau2_standard_llm_agent",
        "agent_instruction_sha256": STANDARD_AGENT_INSTRUCTION_SHA256,
        "system_prompt_sha256": _sha256_text(system_prompt),
        "policy_sha256": _sha256_text(policy),
        "tool_names": list(catalog.names),
        "tool_schema_sha256": catalog.hash,
        "codex_version": CODEX_VERSION,
        "app_server_stream_reader_limit_bytes": (APP_SERVER_STREAM_READER_LIMIT_BYTES),
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
    audit_dir: Path, results: Results
) -> tuple[list[dict[str, Any]], list[Path]]:
    audits = []
    paths = []
    for simulation in sorted(
        results.simulations, key=lambda item: (item.task_id, item.trial)
    ):
        path = audit_dir / audit_filename(simulation.task_id, simulation.seed)
        if not path.is_file():
            raise ExperimentError(
                f"missing adapter audit for {simulation.task_id} "
                f"trial {simulation.trial} seed {simulation.seed}"
            )
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ExperimentError(f"malformed adapter audit at {path.name}")
        if value.get("task_id") != simulation.task_id:
            raise ExperimentError(f"task mismatch in adapter audit {path.name}")
        if value.get("simulation_seed") != simulation.seed:
            raise ExperimentError(f"seed mismatch in adapter audit {path.name}")
        audits.append(value)
        paths.append(path)
    expected_paths = set(paths)
    actual_paths = set(audit_dir.glob("*.json"))
    if actual_paths != expected_paths:
        extras = sorted(path.name for path in actual_paths - expected_paths)
        missing = sorted(path.name for path in expected_paths - actual_paths)
        raise ExperimentError(
            f"adapter audit set mismatch; extra={extras}, missing={missing}"
        )
    return audits, paths


def _validate_results(
    results: Results, task_ids: tuple[str, ...], trials_per_task: int
) -> None:
    expected_count = len(task_ids) * trials_per_task
    if len(results.simulations) != expected_count:
        raise ExperimentError(
            f"expected {expected_count} simulations, got {len(results.simulations)}"
        )
    expected_keys = {
        (task_id, trial) for task_id in task_ids for trial in range(trials_per_task)
    }
    actual_keys = [
        (simulation.task_id, simulation.trial) for simulation in results.simulations
    ]
    if len(set(actual_keys)) != len(actual_keys):
        raise ExperimentError("results contain duplicate task/trial pairs")
    if set(actual_keys) != expected_keys:
        raise ExperimentError("result task/trial pairs differ from the experiment")
    seeds_by_trial: dict[int, set[int]] = {}
    for simulation in results.simulations:
        seeds_by_trial.setdefault(simulation.trial, set()).add(simulation.seed)
        if simulation.reward_info is None:
            raise ExperimentError(
                f"{simulation.task_id} trial {simulation.trial} has no reward"
            )
        if simulation.termination_reason in {
            TerminationReason.INFRASTRUCTURE_ERROR,
            TerminationReason.UNEXPECTED_ERROR,
        }:
            detail = simulation.info.get("error") if simulation.info else None
            raise ExperimentError(
                f"{simulation.task_id} trial {simulation.trial} ended in "
                f"infrastructure failure: {detail}"
            )
    if any(len(seeds) != 1 for seeds in seeds_by_trial.values()):
        raise ExperimentError("tasks within a trial did not share one seed")
    trial_seeds = [
        next(iter(seeds_by_trial[trial])) for trial in range(trials_per_task)
    ]
    if len(set(trial_seeds)) != trials_per_task:
        raise ExperimentError("trials did not receive distinct seeds")


def run_experiment(experiment_path: Path) -> Path:
    started_at = _utc_now()
    repo_root = _repo_root()
    experiment = load_experiment(experiment_path)
    task_ids = tuple(experiment["task_ids"])
    trials_per_task = int(experiment["trials_per_task"])
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
        },
        user="user_simulator",
        llm_user="gpt-5.2",
        llm_args_user={"reasoning_effort": "low"},
        num_trials=trials_per_task,
        max_steps=experiment["max_steps"],
        max_errors=experiment["max_errors"],
        max_concurrency=experiment["max_concurrency"],
        seed=experiment["seed"],
        max_retries=0,
        hallucination_retries=0,
        auto_resume=False,
        auto_review=False,
        verbose_logs=False,
        retrieval_config=experiment["retrieval"],
    )
    run_tasks(
        config,
        tasks,
        save_path=results_path,
        save_dir=output_dir,
        # Held-out task summaries are evaluation data and must not become prompt
        # optimization feedback. Smoke runs retain their useful debug display.
        console_display=_show_per_task_console(experiment["task_partition"]),
        results_format="json",
    )
    reloaded = Results.load(results_path)
    _validate_results(reloaded, task_ids, trials_per_task)
    audits, audit_paths = _collect_audits(audit_dir, reloaded)
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
    trial_seeds = [
        next(
            simulation.seed
            for simulation in reloaded.simulations
            if simulation.trial == trial
        )
        for trial in range(trials_per_task)
    ]
    ended_at = _utc_now()
    manifest = {
        "format_version": 1,
        "experiment": {
            "name": experiment["name"],
            "profile": experiment["profile"],
        },
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
            "reasoning_effort": "high",
            "authentication_mode": "chatgpt",
            "plan_type": audits[0]["account"].get("plan_type"),
            "rate_limit_ids": check.get("rate_limit_ids", []),
            "stream_reader_limit_bytes": check["app_server_stream_reader_limit_bytes"],
            "child_platform_keys_present": False,
            "model_rerouted": False,
            "denied_native_event_observed": False,
        },
        "prompt": {
            "mode": "tau2_standard_llm_agent",
            "custom_prompt": False,
            "agent_instruction_sha256": STANDARD_AGENT_INSTRUCTION_SHA256,
            "effective_system_prompt_sha256": _sha256_text(
                standard_system_prompt(policy)
            ),
            "additional_developer_instructions": False,
        },
        "banking": {
            "domain": "banking_knowledge",
            "retrieval": experiment["retrieval"],
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
            "trials_per_task": trials_per_task,
            "trial_seeds": trial_seeds,
            "max_steps": experiment["max_steps"],
            "max_errors": experiment["max_errors"],
            "max_concurrency": experiment["max_concurrency"],
            "simulation_count": len(task_ids) * trials_per_task,
            "dynamic_tool_call_count": dynamic_calls,
            "start_time": started_at,
            "end_time": ended_at,
            "results_reloaded": True,
            "results_path": str(results_path.relative_to(repo_root)),
            "audit_paths": [str(path.relative_to(repo_root)) for path in audit_paths],
            "terminations": {
                f"{simulation.task_id}/trial_{simulation.trial}": (
                    simulation.termination_reason.value
                )
                for simulation in sorted(
                    reloaded.simulations,
                    key=lambda item: (item.task_id, item.trial),
                )
            },
        },
        "score": {
            "metric": (
                "Pass@1 (mean trajectory reward across "
                f"{trials_per_task} trials per task)"
            ),
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
