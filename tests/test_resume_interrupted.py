from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import tau2.runner.batch as tau_batch
from tau2.data_model.simulation import (
    AgentInfo,
    Info,
    Results,
    RewardInfo,
    SimulationRun,
    TerminationReason,
    TextRunConfig,
    UserInfo,
)
from tau2.data_model.tasks import EvaluationCriteria, Task, UserScenario
from tau2.environment.environment import EnvironmentInfo

import codex_tau.recovery as recovery
import codex_tau.run as run_module
from codex_tau.agent import audit_filename
from codex_tau.app_server import APP_SERVER_STREAM_READER_LIMIT_BYTES
from codex_tau.manifest import read_manifest
from codex_tau.prompt import OPTIMIZED_PROMPT_MODE, PromptSpec

SOURCE_COMMIT = "1" * 40
RESUME_COMMIT = "2" * 40
PROMPT_SHA256 = "3" * 64
SYSTEM_SHA256 = "4" * 64
TOOL_SHA256 = "5" * 64
AUTHORIZATION_SHA256 = "6" * 64
POLICY = "synthetic policy"


def _task(index: int) -> Task:
    return Task(
        id=f"synthetic_{index:03d}",
        user_scenario=UserScenario(instructions=f"synthetic scenario {index}"),
        evaluation_criteria=EvaluationCriteria(),
    )


def _prompt_spec() -> PromptSpec:
    return PromptSpec(
        mode=OPTIMIZED_PROMPT_MODE,
        system_prompt="synthetic system prompt",
        system_prompt_sha256=SYSTEM_SHA256,
        source_path="prompts/banking_knowledge/optimized.md",
        source_file_sha256=PROMPT_SHA256,
    )


def _audit(task_id: str, seed: int) -> dict:
    return {
        "account": {
            "type": "chatgpt",
            "plan_type": "synthetic",
            "requires_openai_auth": True,
        },
        "adapter_stage": "stopped",
        "base_instructions_sha256": SYSTEM_SHA256,
        "developer_instructions_empty": True,
        "dynamic_call_count": 1,
        "system_prompt_sha256": SYSTEM_SHA256,
        "instruction_sources": [],
        "model": {
            "requested": "gpt-5.4",
            "observed": "gpt-5.4",
            "hidden": False,
            "reasoning_efforts": ["high"],
        },
        "model_rerouted": False,
        "native_capability_denied": False,
        "observed_thread_model": "gpt-5.4",
        "pending_dynamic_call_count": 0,
        "prompt_mode": OPTIMIZED_PROMPT_MODE,
        "prompt_source_path": "prompts/banking_knowledge/optimized.md",
        "prompt_source_file_sha256": PROMPT_SHA256,
        "simulation_seed": seed,
        "task_id": task_id,
        "tool_result_delivery_complete": True,
        "tool_results_returned": 1,
        "transport_stream_reader_limit_bytes": (APP_SERVER_STREAM_READER_LIMIT_BYTES),
    }


def _simulation(
    task_id: str,
    seed: int,
    *,
    termination_reason: TerminationReason = TerminationReason.USER_STOP,
    reward: float | None = 1.0,
) -> SimulationRun:
    return SimulationRun(
        id=f"simulation-{task_id}",
        task_id=task_id,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:00:01",
        duration=1.0,
        termination_reason=termination_reason,
        reward_info=RewardInfo(reward=reward) if reward is not None else None,
        messages=[],
        trial=0,
        seed=seed,
    )


def _experiment(task_ids: tuple[str, ...]) -> dict:
    return {
        "name": run_module.OPTIMIZED_TEST_EXPERIMENT,
        "profile": "alltools_optimized_trial0",
        "domain": "banking_knowledge",
        "retrieval": "alltools",
        "agent_model": "gpt-5.4",
        "agent_reasoning": "high",
        "user_model": "gpt-5.2",
        "user_reasoning": "low",
        "seed": 300,
        "trials_per_task": 1,
        "max_steps": 200,
        "max_errors": 10,
        "task_partition": "test",
        "max_concurrency": 16,
        "task_ids": list(task_ids),
        "system_prompt_path": "prompts/banking_knowledge/optimized.md",
        "system_prompt_file_sha256": PROMPT_SHA256,
    }


def _repin(case: SimpleNamespace) -> None:
    case.results.save(case.results_path)
    case.authorization["source_results_sha256"] = recovery.sha256_path(
        case.results_path
    )
    case.authorization["source_info_sha256"] = recovery.canonical_sha256(
        case.results.info.model_dump(mode="json")
    )
    case.authorization["source_audit_set_sha256"] = recovery.audit_set_sha256(
        tuple(case.audit_dir.iterdir())
    )


@pytest.fixture
def synthetic_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    repo_root = tmp_path / "repository"
    source_dir = repo_root / "runs" / "optimized-test-alltools-synthetic"
    audit_dir = source_dir / "adapter-audits"
    experiment_path = repo_root / "experiments" / "optimized-test-alltools.toml"
    audit_dir.mkdir(parents=True)
    experiment_path.parent.mkdir(parents=True)
    experiment_path.write_text("synthetic committed experiment config\n")

    tasks = [_task(index) for index in range(49)]
    task_ids = tuple(task.id for task in tasks)
    experiment = _experiment(task_ids)
    seed = recovery.trial_seeds(300, 1)[0]
    simulations = [_simulation(task_id, seed) for task_id in task_ids]
    simulations[-1] = _simulation(
        task_ids[-1],
        seed,
        termination_reason=TerminationReason.INFRASTRUCTURE_ERROR,
        reward=None,
    )
    info = Info(
        git_commit=SOURCE_COMMIT,
        num_trials=1,
        max_steps=200,
        max_errors=10,
        user_info=UserInfo(
            implementation="user_simulator",
            llm="gpt-5.2",
            llm_args={"reasoning_effort": "low"},
            global_simulation_guidelines="synthetic guidelines",
        ),
        agent_info=AgentInfo(
            implementation=run_module.AGENT_NAME,
            llm="gpt-5.4",
            llm_args={
                "repo_root": str(repo_root),
                "audit_dir": str(audit_dir),
                "prompt_mode": OPTIMIZED_PROMPT_MODE,
                "system_prompt_path": "prompts/banking_knowledge/optimized.md",
                "system_prompt_file_sha256": PROMPT_SHA256,
            },
        ),
        environment_info=EnvironmentInfo(
            domain_name="banking_knowledge", policy=POLICY
        ),
        seed=300,
        retrieval_config="alltools",
    )
    results = Results(info=info, tasks=tasks, simulations=simulations)
    results_path = source_dir / "results.json"
    results.save(results_path)
    for simulation in simulations:
        path = audit_dir / audit_filename(simulation.task_id, simulation.seed)
        path.write_text(json.dumps(_audit(simulation.task_id, simulation.seed)))

    authorization = {
        "format_version": 1,
        "authorization_type": "single_interrupted_retry",
        "experiment": run_module.OPTIMIZED_TEST_EXPERIMENT,
        "source_run_basename": source_dir.name,
        "source_harness_commit": SOURCE_COMMIT,
        "source_results_sha256": recovery.sha256_path(results_path),
        "source_audit_set_sha256": recovery.audit_set_sha256(
            tuple(audit_dir.iterdir())
        ),
        "source_info_sha256": recovery.canonical_sha256(info.model_dump(mode="json")),
        "experiment_config_sha256": recovery.sha256_path(experiment_path),
        "system_prompt_file_sha256": PROMPT_SHA256,
        "system_prompt_sha256": SYSTEM_SHA256,
        "tool_schema_sha256": TOOL_SHA256,
        "expected_matrix_sha256": recovery.matrix_sha256(task_ids, (seed,)),
        "permitted_retry_count": 1,
    }
    monkeypatch.setattr(run_module, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(
        run_module,
        "get_tasks",
        lambda *args, **kwargs: deepcopy(tasks),
    )
    monkeypatch.setattr(
        run_module, "_prompt_spec_for", lambda *args, **kwargs: _prompt_spec()
    )
    monkeypatch.setattr(
        run_module, "_retrieval_contract", lambda retrieval: ([], POLICY)
    )
    monkeypatch.setattr(
        run_module,
        "ToolCatalog",
        lambda tools: SimpleNamespace(hash=TOOL_SHA256),
    )
    return SimpleNamespace(
        repo_root=repo_root,
        source_dir=source_dir,
        audit_dir=audit_dir,
        experiment_path=experiment_path,
        experiment=experiment,
        tasks=tasks,
        task_ids=task_ids,
        seed=seed,
        results=results,
        results_path=results_path,
        authorization=authorization,
    )


def _inspect(case: SimpleNamespace) -> recovery.ResumeSource:
    return recovery.inspect_resume_source(
        case.source_dir,
        case.experiment_path,
        case.experiment,
        case.authorization,
    )


def _append_retry(
    recovery_dir: Path,
    source: recovery.ResumeSource,
    *,
    successful: bool,
) -> None:
    results_path = recovery_dir / "results.json"
    results = Results.load(results_path)
    replacement = source.failed_simulation.model_copy(deep=True)
    replacement.id = "synthetic-retry"
    if successful:
        replacement.termination_reason = TerminationReason.USER_STOP
        replacement.reward_info = RewardInfo(reward=1.0)
    results.simulations.append(replacement)
    recovery.atomic_write_results(results_path, results)
    audit_path = (
        recovery_dir
        / "adapter-audits"
        / audit_filename(replacement.task_id, replacement.seed)
    )
    audit_path.write_text(json.dumps(_audit(replacement.task_id, replacement.seed)))


def _check() -> dict:
    return {
        "prompt_mode": OPTIMIZED_PROMPT_MODE,
        "prompt_source_file_sha256": PROMPT_SHA256,
        "system_prompt_sha256": SYSTEM_SHA256,
        "tool_names": ["synthetic_tool"],
        "tool_schema_sha256": TOOL_SHA256,
        "rate_limit_ids": [],
        "app_server_stream_reader_limit_bytes": (APP_SERVER_STREAM_READER_LIMIT_BYTES),
    }


def test_exact_source_is_accepted(synthetic_case: SimpleNamespace) -> None:
    source = _inspect(synthetic_case)
    assert len(source.successful_audit_paths) == 48
    assert source.retry_key_sha256 == recovery.key_sha256(
        recovery.simulation_key(source.failed_simulation)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "two_infrastructure",
        "missing_reward",
        "unexpected",
        "wrong_seed",
        "wrong_config",
    ],
)
def test_source_matrix_and_config_rejections(
    synthetic_case: SimpleNamespace, mutation: str
) -> None:
    simulations = synthetic_case.results.simulations
    if mutation == "duplicate":
        simulations[0].task_id = simulations[1].task_id
    elif mutation == "two_infrastructure":
        simulations[0].termination_reason = TerminationReason.INFRASTRUCTURE_ERROR
        simulations[0].reward_info = None
    elif mutation == "missing_reward":
        simulations[0].reward_info = None
    elif mutation == "unexpected":
        simulations[0].termination_reason = TerminationReason.UNEXPECTED_ERROR
    elif mutation == "wrong_seed":
        simulations[0].seed += 1
    else:
        synthetic_case.results.info.max_steps += 1
    _repin(synthetic_case)
    with pytest.raises(recovery.ResumeError):
        _inspect(synthetic_case)


def test_source_audit_set_and_digest_rejections(
    synthetic_case: SimpleNamespace,
) -> None:
    extra = synthetic_case.audit_dir / "unexpected.json"
    extra.write_text("{}")
    synthetic_case.authorization["source_audit_set_sha256"] = recovery.audit_set_sha256(
        tuple(synthetic_case.audit_dir.iterdir())
    )
    with pytest.raises(recovery.ResumeError, match="not exact"):
        _inspect(synthetic_case)
    extra.unlink()
    first = next(iter(synthetic_case.audit_dir.iterdir()))
    value = json.loads(first.read_text())
    value["model_rerouted"] = True
    first.write_text(json.dumps(value))
    synthetic_case.authorization["source_audit_set_sha256"] = recovery.audit_set_sha256(
        tuple(synthetic_case.audit_dir.iterdir())
    )
    with pytest.raises(recovery.ResumeError, match="integrity"):
        _inspect(synthetic_case)


def test_staging_is_immutable_and_avoids_audit_collision(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    before_results = recovery.sha256_path(synthetic_case.results_path)
    before_audits = recovery.audit_set_sha256(tuple(synthetic_case.audit_dir.iterdir()))
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    assert recovery.sha256_path(synthetic_case.results_path) == before_results
    assert (
        recovery.audit_set_sha256(tuple(synthetic_case.audit_dir.iterdir()))
        == before_audits
    )
    assert len(Results.load(recovery_dir / "results.json").simulations) == 48
    assert len(tuple((recovery_dir / "adapter-audits").iterdir())) == 48
    assert not (
        recovery_dir / "adapter-audits" / source.failed_audit_path.name
    ).exists()
    archived = (
        recovery_dir / recovery.RECOVERY_EVIDENCE_DIR / "interrupted-adapter-audit.json"
    )
    assert archived.is_file()
    assert recovery.sha256_path(archived) == receipt["failed_audit_sha256"]
    assert (
        recovery.classify_recovery_checkpoint(recovery_dir, source, receipt) == "staged"
    )


def test_crash_states_never_repeat_started_or_completed_key(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    started = recovery.claim_retry_attempt(recovery_dir, receipt)
    with pytest.raises(recovery.ResumeError, match="another retry"):
        recovery.classify_recovery_checkpoint(recovery_dir, source, started)

    _append_retry(recovery_dir, source, successful=True)
    assert (
        recovery.classify_recovery_checkpoint(recovery_dir, source, started)
        == "complete"
    )
    run_module.write_manifest(recovery_dir / "manifest.json", {"valid": True})
    with pytest.raises(recovery.ResumeError, match="already finalized"):
        recovery.classify_recovery_checkpoint(recovery_dir, source, started)


def test_existing_staged_receipt_mismatch_is_rejected(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    receipt["source_harness_commit"] = "9" * 40
    run_module.write_manifest(recovery_dir / "recovery-receipt.json", receipt)
    with pytest.raises(recovery.ResumeError, match="does not match"):
        recovery.stage_recovery(
            synthetic_case.repo_root,
            source,
            synthetic_case.authorization,
            AUTHORIZATION_SHA256,
            RESUME_COMMIT,
        )


def test_retry_failure_is_terminal_without_manifest(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    started = recovery.claim_retry_attempt(recovery_dir, receipt)
    _append_retry(recovery_dir, source, successful=False)
    assert (
        recovery.classify_recovery_checkpoint(recovery_dir, source, started) == "failed"
    )
    assert not (recovery_dir / "manifest.json").exists()


def test_pinned_tau_resume_runs_only_the_missing_original_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = [_task(index) for index in range(3)]
    seed = recovery.trial_seeds(300, 1)[0]
    config = TextRunConfig(
        domain="mock",
        task_set_name="mock",
        task_split_name=None,
        task_ids=[task.id for task in tasks],
        agent="llm_agent",
        llm_agent="synthetic-agent",
        llm_args_agent={},
        user="user_simulator",
        llm_user="synthetic-user",
        llm_args_user={},
        num_trials=1,
        max_steps=5,
        max_errors=2,
        max_concurrency=2,
        seed=300,
        max_retries=0,
        hallucination_retries=0,
        auto_resume=True,
        auto_review=False,
        verbose_logs=False,
    )
    info = Info(
        git_commit="synthetic",
        num_trials=1,
        max_steps=5,
        max_errors=2,
        user_info=UserInfo(implementation="user_simulator"),
        agent_info=AgentInfo(implementation="llm_agent"),
        environment_info=EnvironmentInfo(domain_name="mock", policy="synthetic"),
        seed=300,
    )
    checkpoint = Results(
        info=info,
        tasks=tasks,
        simulations=[_simulation(task.id, seed) for task in tasks[:2]],
    )
    save_path = tmp_path / "results.json"
    checkpoint.save(save_path)
    calls = []

    def fake_run_single_task(config, task, *, seed, **kwargs):
        calls.append((task.id, seed))
        return _simulation(task.id, seed)

    monkeypatch.setattr(tau_batch, "get_info", lambda *args, **kwargs: info)
    monkeypatch.setattr(tau_batch, "run_single_task", fake_run_single_task)
    resumed = tau_batch.run_tasks(
        config,
        tasks,
        save_path=save_path,
        save_dir=tmp_path,
        console_display=False,
        results_format="json",
    )
    assert calls == [(tasks[-1].id, seed)]
    assert len(resumed.simulations) == 3
    keys = {
        (simulation.task_id, simulation.trial, simulation.seed)
        for simulation in resumed.simulations
    }
    assert len(keys) == 3


def test_resume_invokes_tau_once_and_keeps_console_quiet(
    synthetic_case: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _inspect(synthetic_case)
    calls = []
    gate_calls = {"clean": 0, "inputs": 0, "source": 0}
    monkeypatch.setattr(
        recovery,
        "load_resume_authorization",
        lambda repo_root: (
            synthetic_case.authorization,
            repo_root / recovery.RESUME_AUTHORIZATION_RELATIVE_PATH,
            AUTHORIZATION_SHA256,
        ),
    )

    def fake_clean(*args):
        gate_calls["clean"] += 1
        return RESUME_COMMIT, recovery.TAU_COMMIT

    def fake_inputs(*args):
        gate_calls["inputs"] += 1

    def fake_source(*args):
        gate_calls["source"] += 1

    monkeypatch.setattr(recovery, "require_clean_repositories", fake_clean)
    monkeypatch.setattr(recovery, "require_execution_inputs_at_commits", fake_inputs)
    monkeypatch.setattr(recovery, "verify_source_unchanged", fake_source)
    monkeypatch.setattr(recovery, "validate_tau_resume_contract", lambda *args: None)
    monkeypatch.setattr(
        run_module, "load_experiment", lambda path: synthetic_case.experiment
    )
    monkeypatch.setattr(recovery, "inspect_resume_source", lambda *args: source)
    monkeypatch.setattr(run_module, "preflight", lambda path: _check())
    monkeypatch.setattr(recovery.registry, "get_agent_factory", lambda name: object())

    def fake_run_tasks(config, tasks, **kwargs):
        calls.append((config, tasks, kwargs))
        print("synthetic per-task identity and reward must remain private")
        staged = Results.load(kwargs["save_path"])
        assert len(staged.simulations) == 48
        _append_retry(kwargs["save_dir"], source, successful=True)
        return Results.load(kwargs["save_path"])

    monkeypatch.setattr(recovery, "run_tasks", fake_run_tasks)

    def fake_finalize(experiment, check, output_dir, started_at, **kwargs):
        run_module.write_manifest(output_dir / "manifest.json", {"valid": True})
        return output_dir

    monkeypatch.setattr(run_module, "_finalize_experiment", fake_finalize)
    output = recovery.resume_interrupted(
        synthetic_case.experiment_path, synthetic_case.source_dir
    )
    assert len(calls) == 1
    assert gate_calls == {"clean": 3, "inputs": 3, "source": 3}
    config, tasks, kwargs = calls[0]
    assert config.auto_resume is True
    assert config.seed == 300
    assert config.max_concurrency == 16
    assert len(tasks) == 49
    assert kwargs["console_display"] is False
    assert "synthetic per-task" not in capsys.readouterr().out
    assert (output / "recovery-runner.log").read_text().startswith("synthetic per-task")
    with pytest.raises(recovery.ResumeError, match="already finalized"):
        recovery.resume_interrupted(
            synthetic_case.experiment_path, synthetic_case.source_dir
        )
    assert len(calls) == 1


def test_final_manifest_records_recovery_provenance(
    synthetic_case: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    receipt = recovery.claim_retry_attempt(recovery_dir, receipt)
    _append_retry(recovery_dir, source, successful=True)
    monkeypatch.setattr(run_module, "_git_head", lambda repo_root: RESUME_COMMIT)
    output = run_module._finalize_experiment(
        synthetic_case.experiment,
        _check(),
        recovery_dir,
        "2026-01-02T00:00:00+00:00",
        recovery=recovery.recovery_manifest_context(
            source,
            synthetic_case.authorization,
            AUTHORIZATION_SHA256,
            receipt,
        ),
    )
    manifest = read_manifest(output / "manifest.json")
    assert manifest["format_version"] == 2
    assert manifest["harness"]["initial_commit"] == SOURCE_COMMIT
    assert manifest["harness"]["resume_commit"] == RESUME_COMMIT
    recovery_data = manifest["execution"]["recovery"]
    assert recovery_data["retry_count"] == 1
    assert recovery_data["exact_key_replacement"] is True
    assert (
        recovery_data["scientific_classification"]
        == "single missing-only infrastructure retry"
    )
    assert recovery_data["independent_full_matrix_rerun"] is False
    assert recovery_data["retry_selected_from_reward"] is False
    assert recovery_data["source_immutable_verified"] is True
    assert (
        recovery_data["source_results_sha256"]
        == (synthetic_case.authorization["source_results_sha256"])
    )
    assert recovery_data["final_results_sha256"] == recovery.sha256_path(
        output / "results.json"
    )


def test_authorization_absence_and_schema_mismatch(tmp_path: Path) -> None:
    with pytest.raises(recovery.ResumeError, match="no committed"):
        recovery.load_resume_authorization(tmp_path)
    path = tmp_path / recovery.RESUME_AUTHORIZATION_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"format_version": 1}))
    with pytest.raises(recovery.ResumeError, match="wrong schema"):
        recovery.load_resume_authorization(tmp_path)


def test_authorization_argument_and_source_digest_mismatch(
    synthetic_case: SimpleNamespace,
) -> None:
    with pytest.raises(recovery.ResumeError, match="experiment argument"):
        recovery.authorization_matches_argument(
            synthetic_case.authorization,
            Path("experiments/different.toml"),
            synthetic_case.source_dir,
        )
    synthetic_case.authorization["source_results_sha256"] = "0" * 64
    with pytest.raises(recovery.ResumeError, match="results digest"):
        _inspect(synthetic_case)


@pytest.mark.parametrize(
    "mode", ["not_at_head", "dirty_harness", "wrong_pin", "dirty_vendor"]
)
def test_clean_committed_and_vendor_pin_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    repo_root = tmp_path / "repository"
    authorization_path = repo_root / recovery.RESUME_AUTHORIZATION_RELATIVE_PATH
    authorization_path.parent.mkdir(parents=True)
    authorization_path.write_text("{}")
    vendor_root = repo_root / "vendor" / "tau2-bench"

    def fake_head_file(*args, **kwargs) -> None:
        if mode == "not_at_head":
            raise recovery.ResumeError("committed input bytes do not match")

    def fake_git_output(cwd: Path, *arguments: str) -> str:
        if arguments[0] == "rev-parse":
            if cwd == vendor_root:
                return "0" * 40 if mode == "wrong_pin" else recovery.TAU_COMMIT
            return RESUME_COMMIT
        if cwd == repo_root and mode == "dirty_harness":
            return " M src/synthetic.py"
        if cwd == vendor_root and mode == "dirty_vendor":
            return " M synthetic.py"
        return ""

    monkeypatch.setattr(recovery, "_git_output", fake_git_output)
    monkeypatch.setattr(recovery, "require_head_regular_file", fake_head_file)
    monkeypatch.setattr(
        recovery, "require_exact_head_worktree", lambda *args, **kwargs: None
    )
    with pytest.raises(recovery.ResumeError):
        recovery.require_clean_repositories(
            repo_root, authorization_path, recovery.sha256_path(authorization_path)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("format_version", True), ("permitted_retry_count", True)],
)
def test_authorization_integer_fields_reject_booleans(
    tmp_path: Path, field: str, value: object
) -> None:
    authorization = {
        "format_version": 1,
        "authorization_type": "single_interrupted_retry",
        "experiment": run_module.OPTIMIZED_TEST_EXPERIMENT,
        "source_run_basename": "optimized-test-alltools-synthetic",
        "source_harness_commit": SOURCE_COMMIT,
        "source_results_sha256": "0" * 64,
        "source_audit_set_sha256": "1" * 64,
        "source_info_sha256": "2" * 64,
        "experiment_config_sha256": "3" * 64,
        "system_prompt_file_sha256": "4" * 64,
        "system_prompt_sha256": "5" * 64,
        "tool_schema_sha256": "6" * 64,
        "expected_matrix_sha256": "7" * 64,
        "permitted_retry_count": 1,
    }
    authorization[field] = value
    path = tmp_path / recovery.RESUME_AUTHORIZATION_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(authorization))
    with pytest.raises(recovery.ResumeError):
        recovery.load_resume_authorization(tmp_path)


def test_head_binding_defeats_assume_unchanged(tmp_path: Path) -> None:
    repo_root = tmp_path / "repository"
    path = repo_root / recovery.RESUME_AUTHORIZATION_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text("authorized\n")
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "synthetic@example.invalid"],
        ["git", "config", "user.name", "Synthetic"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "authorization"],
    )
    for command in commands:
        subprocess.run(command, cwd=repo_root, check=True)
    expected = recovery.sha256_path(path)
    recovery.require_head_regular_file(repo_root, path, expected)
    runtime_path = repo_root / "runtime.py"
    runtime_path.write_text("AUTHORIZED = True\n")
    subprocess.run(["git", "add", "runtime.py"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-qm", "runtime"], cwd=repo_root, check=True)
    recovery.require_exact_head_worktree(repo_root)
    subprocess.run(
        ["git", "update-index", "--assume-unchanged", str(path.relative_to(repo_root))],
        cwd=repo_root,
        check=True,
    )
    path.write_text("silently changed\n")
    assert not subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with pytest.raises(recovery.ResumeError, match="authorized digest"):
        recovery.require_head_regular_file(repo_root, path, expected)
    path.write_text("authorized\n")
    runtime_path.write_text("AUTHORIZED = False\n")
    subprocess.run(
        ["git", "update-index", "--assume-unchanged", "runtime.py"],
        cwd=repo_root,
        check=True,
    )
    with pytest.raises(recovery.ResumeError, match="worktree bytes"):
        recovery.require_exact_head_worktree(repo_root)


def test_symlinked_source_audit_is_rejected(
    synthetic_case: SimpleNamespace, tmp_path: Path
) -> None:
    path = next(iter(synthetic_case.audit_dir.iterdir()))
    target = tmp_path / "audit-target.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(recovery.ResumeError, match="regular file"):
        _inspect(synthetic_case)


def test_symlinked_recovery_dir_and_runner_log_are_rejected(
    synthetic_case: SimpleNamespace, tmp_path: Path
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir = recovery._recovery_dir_for(
        synthetic_case.repo_root,
        synthetic_case.source_dir,
        AUTHORIZATION_SHA256,
    )
    target = tmp_path / "outside-recovery"
    target.mkdir()
    recovery_dir.symlink_to(target, target_is_directory=True)
    with pytest.raises(recovery.ResumeError, match="not a directory"):
        recovery.stage_recovery(
            synthetic_case.repo_root,
            source,
            synthetic_case.authorization,
            AUTHORIZATION_SHA256,
            RESUME_COMMIT,
        )

    recovery_dir.unlink()
    recovery_dir, _ = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    runner_target = tmp_path / "runner-target.log"
    runner_target.write_text("must not be overwritten")
    (recovery_dir / "recovery-runner.log").symlink_to(runner_target)
    with pytest.raises(recovery.ResumeError, match="already exists"):
        recovery._open_exclusive_runner_log(recovery_dir / "recovery-runner.log")
    assert runner_target.read_text() == "must not be overwritten"


def test_repository_runs_directory_cannot_be_a_symlink(tmp_path: Path) -> None:
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    (repo_root / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(recovery.ResumeError, match="runs directory"):
        recovery._require_repository_runs_dir(repo_root)


def test_attempt_claim_is_exclusive_and_required_for_complete_checkpoint(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    started = recovery.claim_retry_attempt(recovery_dir, receipt)
    with pytest.raises(recovery.ResumeError, match="another retry"):
        recovery.claim_retry_attempt(recovery_dir, started)

    # Even a forged started receipt plus a complete checkpoint cannot replace
    # the atomic claim evidence.
    (recovery_dir / recovery._ATTEMPT_CLAIM_NAME).unlink()
    _append_retry(recovery_dir, source, successful=True)
    with pytest.raises(recovery.ResumeError, match="atomic attempt claim"):
        recovery.classify_recovery_checkpoint(recovery_dir, source, started)


@pytest.mark.parametrize("mutation", ["row", "task", "info", "audit"])
def test_completed_source_evidence_cannot_change_during_retry(
    synthetic_case: SimpleNamespace, mutation: str
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    started = recovery.claim_retry_attempt(recovery_dir, receipt)
    _append_retry(recovery_dir, source, successful=True)
    results_path = recovery_dir / "results.json"
    results = Results.load(results_path)
    if mutation == "row":
        results.simulations[0].duration += 1
        recovery.atomic_write_results(results_path, results)
    elif mutation == "task":
        results.tasks[0].user_scenario.instructions += " changed"
        recovery.atomic_write_results(results_path, results)
    elif mutation == "info":
        results.info.max_steps += 1
        recovery.atomic_write_results(results_path, results)
    else:
        path = recovery_dir / "adapter-audits" / source.successful_audit_paths[0].name
        value = json.loads(path.read_text())
        value["dynamic_call_count"] += 1
        path.write_text(json.dumps(value))
    with pytest.raises(recovery.ResumeError, match="recovery changed"):
        recovery.classify_recovery_checkpoint(recovery_dir, source, started)


def test_tau_auto_resume_config_drift_is_rejected(
    synthetic_case: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    config = run_module._build_run_config(
        synthetic_case.experiment,
        _check(),
        synthetic_case.repo_root,
        recovery_dir / "adapter-audits",
        auto_resume=True,
    )
    staged_info = Results.load(recovery_dir / "results.json").info
    monkeypatch.setattr(
        recovery,
        "get_tau_info",
        lambda *args, **kwargs: staged_info.model_copy(deep=True),
    )
    recovery.validate_tau_resume_contract(
        config,
        synthetic_case.tasks,
        recovery_dir,
        source,
        receipt,
    )
    changed_info = staged_info.model_copy(deep=True)
    changed_info.user_info.global_simulation_guidelines = "changed guideline"
    monkeypatch.setattr(recovery, "get_tau_info", lambda *args, **kwargs: changed_info)
    with pytest.raises(recovery.ResumeError, match="configuration differs"):
        recovery.validate_tau_resume_contract(
            config,
            synthetic_case.tasks,
            recovery_dir,
            source,
            receipt,
        )


def test_staged_receipt_cannot_self_declare_changed_checkpoint(
    synthetic_case: SimpleNamespace,
) -> None:
    source = _inspect(synthetic_case)
    recovery_dir, receipt = recovery.stage_recovery(
        synthetic_case.repo_root,
        source,
        synthetic_case.authorization,
        AUTHORIZATION_SHA256,
        RESUME_COMMIT,
    )
    results = Results.load(recovery_dir / "results.json")
    results.info.max_steps += 1
    recovery.atomic_write_results(recovery_dir / "results.json", results)
    receipt["staged_results_before_retry_sha256"] = recovery.sha256_path(
        recovery_dir / "results.json"
    )
    receipt["staged_info_sha256"] = recovery.canonical_sha256(
        results.info.model_dump(mode="json")
    )
    recovery.atomic_write_json(recovery_dir / "recovery-receipt.json", receipt)
    with pytest.raises(recovery.ResumeError, match="self-declared evidence"):
        recovery.stage_recovery(
            synthetic_case.repo_root,
            source,
            synthetic_case.authorization,
            AUTHORIZATION_SHA256,
            RESUME_COMMIT,
        )
