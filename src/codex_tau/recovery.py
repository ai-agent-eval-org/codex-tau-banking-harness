"""Fail-closed, one-attempt recovery for an explicitly authorized run."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau2.data_model.simulation import Results, TerminationReason
from tau2.registry import registry
from tau2.runner.batch import run_tasks
from tau2.runner.helpers import get_info as get_tau_info

from .agent import audit_filename, create_codex_tau_agent
from .manifest import assert_secret_free
from .prompt import OPTIMIZED_PROMPT_MODE, PromptSpec

TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
RECOVERABLE_EXPERIMENT = "optimized-test-alltools"
RESUME_AUTHORIZATION_RELATIVE_PATH = Path("authorizations/resume-interrupted.json")
RECOVERY_EVIDENCE_DIR = "recovery-evidence"

_AUTHORIZATION_KEYS = {
    "agent_instruction_sha256",
    "authorization_type",
    "effective_system_prompt_sha256",
    "expected_matrix_sha256",
    "experiment",
    "experiment_config_sha256",
    "format_version",
    "permitted_retry_count",
    "source_audit_set_sha256",
    "source_harness_commit",
    "source_info_sha256",
    "source_results_sha256",
    "source_run_basename",
    "tool_schema_sha256",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_RECEIPT_NAME = "recovery-receipt.json"
_ATTEMPT_CLAIM_NAME = "retry-attempt-claimed.json"


class ResumeError(RuntimeError):
    """An interrupted-run recovery violates its one-retry authorization."""


@dataclass(frozen=True)
class ResumeSource:
    """Fully validated source state for one authorized interrupted retry."""

    source_dir: Path
    results: Results
    failed_simulation: Any
    failed_audit_path: Path
    successful_audit_paths: tuple[Path, ...]
    audit_bytes: tuple[tuple[str, bytes], ...]
    prompt_spec: PromptSpec
    expected_keys: frozenset[tuple[str, int, int]]
    completed_keys: frozenset[tuple[str, int, int]]
    retry_key_sha256: str
    initial_start_time: str | None
    source_tasks_sha256: str
    source_completed_rows_sha256: str


def _regular_file_bytes(path: Path) -> bytes:
    """Read one stable regular file without following a terminal symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResumeError(f"required regular file is unreadable: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ResumeError(f"required path is not a regular file: {path.name}")
        chunks = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in stable_fields):
            raise ResumeError(f"required file changed while being read: {path.name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(_regular_file_bytes(path))


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_set_sha256(paths: list[Path] | tuple[Path, ...]) -> str:
    entries = [
        {"name": path.name, "sha256": sha256_path(path)}
        for path in sorted(paths, key=lambda item: item.name)
    ]
    return canonical_sha256(entries)


def canonical_simulations_sha256(simulations: list[Any] | tuple[Any, ...]) -> str:
    return canonical_sha256(
        [
            simulation.model_dump(mode="json")
            for simulation in sorted(simulations, key=lambda item: simulation_key(item))
        ]
    )


def trial_seeds(seed: int, trials_per_task: int) -> tuple[int, ...]:
    generator = random.Random(seed)
    return tuple(generator.randint(0, 1_000_000) for _ in range(trials_per_task))


def matrix_sha256(
    task_ids: tuple[str, ...], expected_trial_seeds: tuple[int, ...]
) -> str:
    return canonical_sha256(
        [
            {"task_id": task_id, "trial": trial, "seed": trial_seed}
            for trial, trial_seed in enumerate(expected_trial_seeds)
            for task_id in task_ids
        ]
    )


def simulation_key(simulation: Any) -> tuple[str, int, int]:
    if type(simulation.trial) is not int or type(simulation.seed) is not int:
        raise ResumeError("source checkpoint has an invalid task/trial/seed key")
    return simulation.task_id, simulation.trial, simulation.seed


def key_sha256(key: tuple[str, int, int]) -> str:
    task_id, trial, seed = key
    return canonical_sha256({"task_id": task_id, "trial": trial, "seed": seed})


def _git_output(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ResumeError("git provenance verification failed")
    return completed.stdout.strip()


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ResumeError("git provenance verification failed")
    return completed.stdout


def require_head_regular_file(
    repo_root: Path,
    path: Path,
    expected_sha256: str,
    *,
    commit: str = "HEAD",
) -> None:
    """Bind an input to a regular blob in one exact commit and current bytes."""
    resolved_root = repo_root.resolve(strict=True)
    try:
        lexical_relative = path.absolute().relative_to(resolved_root)
        resolved_path = path.resolve(strict=True)
        resolved_relative = resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ResumeError("committed input escapes the harness repository") from exc
    if lexical_relative != resolved_relative or path.is_symlink():
        raise ResumeError("committed input may not traverse a symlink")
    relative = resolved_relative.as_posix()
    entry = _git_output(repo_root, "ls-tree", commit, "--", relative)
    fields = entry.split(None, 3)
    if len(fields) != 4 or fields[0] != "100644" or fields[1] != "blob":
        raise ResumeError("committed input is not an exact regular HEAD blob")
    committed = _git_bytes(repo_root, "show", f"{commit}:{relative}")
    if (
        sha256_bytes(committed) != expected_sha256
        or sha256_path(resolved_path) != expected_sha256
    ):
        raise ResumeError("committed input bytes do not match the authorized digest")


def _git_blob_oid(value: bytes, object_format: str) -> str:
    payload = f"blob {len(value)}\0".encode() + value
    if object_format == "sha1":
        return hashlib.sha1(payload, usedforsecurity=False).hexdigest()
    if object_format == "sha256":
        return hashlib.sha256(payload).hexdigest()
    raise ResumeError("unsupported Git object format")


def require_exact_head_worktree(
    repo_root: Path,
    *,
    allowed_submodule: Path | None = None,
) -> None:
    """Compare every tracked runtime byte and mode to HEAD, ignoring run artifacts."""
    resolved_root = repo_root.resolve(strict=True)
    object_format = _git_output(repo_root, "rev-parse", "--show-object-format")
    tree = _git_bytes(repo_root, "ls-tree", "-r", "-z", "HEAD")
    entries = [entry for entry in tree.split(b"\0") if entry]
    if not entries:
        raise ResumeError("tracked HEAD tree is empty")
    seen_submodule = False
    for entry in entries:
        try:
            metadata, raw_relative = entry.split(b"\t", 1)
            raw_mode, raw_type, raw_oid = metadata.split(b" ", 2)
            relative = Path(os.fsdecode(raw_relative))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ResumeError("tracked HEAD tree is malformed") from exc
        mode = raw_mode.decode()
        object_type = raw_type.decode()
        oid = raw_oid.decode()
        path = repo_root / relative
        try:
            if path.parent.resolve(strict=True) != resolved_root / relative.parent:
                raise ResumeError("tracked path traverses a symlinked directory")
        except OSError as exc:
            raise ResumeError("tracked path parent is missing") from exc

        if mode in {"100644", "100755"} and object_type == "blob":
            value = _regular_file_bytes(path)
            executable = bool(path.stat(follow_symlinks=False).st_mode & 0o111)
            if executable != (mode == "100755"):
                raise ResumeError("tracked file mode differs from HEAD")
            if _git_blob_oid(value, object_format) != oid:
                raise ResumeError("tracked worktree bytes differ from HEAD")
            continue
        if mode == "120000" and object_type == "blob":
            if not path.is_symlink():
                raise ResumeError("tracked symlink type differs from HEAD")
            value = os.fsencode(os.readlink(path))
            if _git_blob_oid(value, object_format) != oid:
                raise ResumeError("tracked symlink target differs from HEAD")
            continue
        if mode == "160000" and object_type == "commit":
            if allowed_submodule is None or relative != allowed_submodule:
                raise ResumeError("unexpected tracked submodule")
            if path.is_symlink() or not path.is_dir():
                raise ResumeError("tracked submodule path is invalid")
            if _git_output(path, "rev-parse", "HEAD") != oid:
                raise ResumeError("tracked submodule commit differs from HEAD")
            seen_submodule = True
            continue
        raise ResumeError("unsupported tracked HEAD entry")
    if allowed_submodule is not None and not seen_submodule:
        raise ResumeError("required tracked submodule is missing")


def require_clean_repositories(
    repo_root: Path,
    authorization_path: Path,
    authorization_sha256: str,
) -> tuple[str, str]:
    """Require committed recovery code/authorization and the exact clean pin."""
    if _git_output(repo_root, "status", "--porcelain", "--untracked-files=all"):
        raise ResumeError(
            "resume requires a clean harness with a committed authorization record"
        )
    harness_commit = _git_output(repo_root, "rev-parse", "HEAD")
    if not _COMMIT_PATTERN.fullmatch(harness_commit):
        raise ResumeError("harness commit provenance is malformed")
    require_exact_head_worktree(
        repo_root,
        allowed_submodule=Path("vendor/tau2-bench"),
    )
    require_head_regular_file(
        repo_root,
        authorization_path,
        authorization_sha256,
        commit=harness_commit,
    )

    vendor_root = repo_root / "vendor" / "tau2-bench"
    vendor_commit = _git_output(vendor_root, "rev-parse", "HEAD")
    if vendor_commit != TAU_COMMIT:
        raise ResumeError("the pinned tau2 checkout is at the wrong commit")
    if _git_output(vendor_root, "status", "--porcelain", "--untracked-files=all"):
        raise ResumeError("the pinned tau2 checkout is dirty")
    require_exact_head_worktree(vendor_root)
    return harness_commit, vendor_commit


def load_resume_authorization(
    repo_root: Path,
) -> tuple[dict[str, Any], Path, str]:
    """Load the single fixed authorization file; its absence is fail-closed."""
    path = repo_root / RESUME_AUTHORIZATION_RELATIVE_PATH
    if not path.exists():
        raise ResumeError("no committed interrupted-run retry authorization is present")
    try:
        raw = _regular_file_bytes(path)
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeError("the retry authorization record is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _AUTHORIZATION_KEYS:
        raise ResumeError("the retry authorization record has the wrong schema")
    assert_secret_free(value, "resume_authorization")
    if type(value["format_version"]) is not int or value["format_version"] != 1:
        raise ResumeError("unsupported retry authorization format")
    if value["authorization_type"] != "single_interrupted_retry":
        raise ResumeError("the retry authorization type is invalid")
    if (
        type(value["permitted_retry_count"]) is not int
        or value["permitted_retry_count"] != 1
    ):
        raise ResumeError("authorization must permit exactly one retry")
    if value["experiment"] != RECOVERABLE_EXPERIMENT:
        raise ResumeError("authorization is not for the recoverable experiment")
    basename = value["source_run_basename"]
    if not isinstance(basename, str) or not basename or Path(basename).name != basename:
        raise ResumeError("authorization source basename is invalid")
    if not isinstance(
        value["source_harness_commit"], str
    ) or not _COMMIT_PATTERN.fullmatch(value["source_harness_commit"]):
        raise ResumeError("authorization source commit is malformed")
    for key in _AUTHORIZATION_KEYS:
        if key.endswith("_sha256") and (
            not isinstance(value[key], str) or not _SHA256_PATTERN.fullmatch(value[key])
        ):
            raise ResumeError("authorization contains a malformed SHA-256")
    return value, path, sha256_bytes(raw)


def atomic_write_results(path: Path, results: Results) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".recovery-results-", suffix=".json", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(results.model_dump_json(indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    assert_secret_free(value, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_results_regular(path: Path, error: str) -> Results:
    try:
        return Results.model_validate_json(_regular_file_bytes(path))
    except Exception as exc:
        raise ResumeError(error) from exc


def authorization_matches_argument(
    authorization: dict[str, Any],
    experiment_path: Path,
    source_run_dir: Path,
) -> None:
    if experiment_path.name != f"{authorization['experiment']}.toml":
        raise ResumeError("experiment argument does not match authorization")
    if source_run_dir.name != authorization["source_run_basename"]:
        raise ResumeError("source argument does not match authorization")


def require_execution_inputs_at_commits(
    repo_root: Path,
    experiment_path: Path,
    experiment: dict[str, Any],
    authorization: dict[str, Any],
    resume_harness_commit: str,
) -> None:
    """Bind config and prompt to both the source and recovery commit trees."""
    source_commit = authorization["source_harness_commit"]
    _git_output(repo_root, "cat-file", "-e", f"{source_commit}^{{commit}}")
    _git_output(
        repo_root, "merge-base", "--is-ancestor", source_commit, resume_harness_commit
    )
    prompt_path = repo_root / experiment["agent_instruction_path"]
    for commit in (source_commit, resume_harness_commit):
        require_head_regular_file(
            repo_root,
            experiment_path,
            authorization["experiment_config_sha256"],
            commit=commit,
        )
        require_head_regular_file(
            repo_root,
            prompt_path,
            authorization["agent_instruction_sha256"],
            commit=commit,
        )


def validate_tau_resume_contract(
    config: Any,
    tasks: list[Any],
    recovery_dir: Path,
    source: ResumeSource,
    receipt: dict[str, Any],
) -> None:
    """Reject τ-bench auto-resume's permissive config-drift behavior."""
    staged = load_results_regular(
        recovery_dir / "results.json",
        "staged recovery checkpoint is unreadable",
    )
    expected_info = get_tau_info(
        config,
        policy_override=source.results.info.environment_info.policy,
    )
    if (
        canonical_sha256(expected_info.model_dump(mode="json"))
        != receipt["staged_info_sha256"]
        or canonical_sha256(staged.info.model_dump(mode="json"))
        != receipt["staged_info_sha256"]
    ):
        raise ResumeError("tau auto-resume configuration differs from the exact stage")
    current_tasks_sha256 = canonical_sha256(
        [task.model_dump(mode="json") for task in tasks]
    )
    if (
        current_tasks_sha256 != receipt["source_tasks_sha256"]
        or canonical_sha256([task.model_dump(mode="json") for task in staged.tasks])
        != receipt["source_tasks_sha256"]
    ):
        raise ResumeError("tau auto-resume tasks differ from the exact stage")


def _open_exclusive_runner_log(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ResumeError("recovery runner log already exists") from exc
    except OSError as exc:
        raise ResumeError("recovery runner log is not a safe regular file") from exc
    return os.fdopen(descriptor, "w")


def _validate_source_info(
    results: Results,
    experiment: dict[str, Any],
    authorization: dict[str, Any],
    source_dir: Path,
    repo_root: Path,
    agent_name: str,
) -> None:
    info = results.info
    expected_agent_args = {
        "repo_root": str(repo_root),
        "audit_dir": str(source_dir / "adapter-audits"),
        "prompt_mode": OPTIMIZED_PROMPT_MODE,
        "agent_instruction_path": experiment["agent_instruction_path"],
        "agent_instruction_sha256": experiment["agent_instruction_sha256"],
    }
    checks = (
        info.git_commit == authorization["source_harness_commit"],
        info.num_trials == experiment["trials_per_task"],
        info.max_steps == experiment["max_steps"],
        info.max_errors == experiment["max_errors"],
        info.seed == experiment["seed"],
        info.retrieval_config == experiment["retrieval"],
        info.retrieval_config_kwargs is None,
        info.agent_info.implementation == agent_name,
        info.agent_info.llm == "gpt-5.4",
        info.agent_info.llm_args == expected_agent_args,
        info.user_info.implementation == "user_simulator",
        info.user_info.llm == "gpt-5.2",
        info.user_info.llm_args == {"reasoning_effort": "low"},
        info.environment_info.domain_name == "banking_knowledge",
    )
    if not all(checks):
        raise ResumeError("source checkpoint configuration does not match")
    if (
        canonical_sha256(info.model_dump(mode="json"))
        != authorization["source_info_sha256"]
    ):
        raise ResumeError("source checkpoint info digest does not match authorization")


def inspect_resume_source(
    source_dir: Path,
    experiment_path: Path,
    experiment: dict[str, Any],
    authorization: dict[str, Any],
) -> ResumeSource:
    """Fail closed unless the source is the exact one-failure authorized matrix."""
    from . import run as harness

    if experiment["name"] != RECOVERABLE_EXPERIMENT:
        raise ResumeError("only the interrupted optimized test is recoverable")
    task_ids = tuple(experiment["task_ids"])
    trials_per_task = int(experiment["trials_per_task"])
    if len(task_ids) != 49 or trials_per_task != 1:
        raise ResumeError("recoverable experiment matrix has changed")
    if os.path.lexists(source_dir / "manifest.json"):
        raise ResumeError("source run is already finalized")

    results_path = source_dir / "results.json"
    if not results_path.exists():
        raise ResumeError("source checkpoint is missing")
    results_bytes = _regular_file_bytes(results_path)
    if sha256_bytes(results_bytes) != authorization["source_results_sha256"]:
        raise ResumeError("source results digest does not match authorization")
    try:
        results = Results.model_validate_json(results_bytes)
    except Exception as exc:
        raise ResumeError("source checkpoint cannot be validated") from exc

    expected_trial_seeds = trial_seeds(experiment["seed"], trials_per_task)
    if (
        matrix_sha256(task_ids, expected_trial_seeds)
        != authorization["expected_matrix_sha256"]
    ):
        raise ResumeError("authorized matrix digest does not match")
    expected_keys = frozenset(
        (task_id, trial, trial_seed)
        for trial, trial_seed in enumerate(expected_trial_seeds)
        for task_id in task_ids
    )
    actual_keys = [simulation_key(simulation) for simulation in results.simulations]
    if len(actual_keys) != 49 or len(set(actual_keys)) != len(actual_keys):
        raise ResumeError("source checkpoint does not contain 49 unique rows")
    if set(actual_keys) != expected_keys:
        raise ResumeError("source checkpoint matrix does not match authorization")

    infrastructure_failures = [
        simulation
        for simulation in results.simulations
        if simulation.termination_reason == TerminationReason.INFRASTRUCTURE_ERROR
    ]
    successful = [
        simulation
        for simulation in results.simulations
        if simulation.termination_reason != TerminationReason.INFRASTRUCTURE_ERROR
    ]
    if len(infrastructure_failures) != 1 or len(successful) != 48:
        raise ResumeError("source must contain exactly one infrastructure failure")
    failed_simulation = infrastructure_failures[0]
    failed_key = simulation_key(failed_simulation)
    completed_keys = frozenset(simulation_key(simulation) for simulation in successful)
    if failed_simulation.reward_info is not None:
        raise ResumeError("the infrastructure-failure row must not have a reward")
    if any(
        simulation.reward_info is None
        or simulation.termination_reason == TerminationReason.UNEXPECTED_ERROR
        for simulation in successful
    ):
        raise ResumeError("source contains an invalid completed row")

    if tuple(task.id for task in results.tasks) != task_ids:
        raise ResumeError("source task ordering does not match the frozen matrix")
    current_tasks = harness.get_tasks(
        "banking_knowledge", task_split_name=None, task_ids=task_ids
    )
    if tuple(task.id for task in current_tasks) != task_ids:
        raise ResumeError("current task ordering does not match the frozen matrix")
    if canonical_sha256(
        [task.model_dump(mode="json") for task in results.tasks]
    ) != canonical_sha256([task.model_dump(mode="json") for task in current_tasks]):
        raise ResumeError("source task payloads do not match the pinned data")

    _validate_source_info(
        results,
        experiment,
        authorization,
        source_dir,
        harness._repo_root(),
        harness.AGENT_NAME,
    )
    if sha256_path(experiment_path) != authorization["experiment_config_sha256"]:
        raise ResumeError("experiment config digest does not match authorization")

    policy = results.info.environment_info.policy
    prompt_spec = harness._prompt_spec_for(experiment, policy)
    if (
        prompt_spec.agent_instruction_sha256
        != authorization["agent_instruction_sha256"]
        or prompt_spec.effective_system_prompt_sha256
        != authorization["effective_system_prompt_sha256"]
    ):
        raise ResumeError("authorized prompt digests do not match")
    tools, current_policy = harness._retrieval_contract(experiment["retrieval"])
    if current_policy != policy:
        raise ResumeError("source policy differs from the pinned retrieval policy")
    if harness.ToolCatalog(tools).hash != authorization["tool_schema_sha256"]:
        raise ResumeError("authorized tool-schema digest does not match")

    audit_dir = source_dir / "adapter-audits"
    if audit_dir.is_symlink() or not audit_dir.is_dir():
        raise ResumeError("source adapter-audit directory is missing")
    expected_audit_paths = {
        audit_dir / audit_filename(simulation.task_id, simulation.seed)
        for simulation in results.simulations
    }
    actual_entries = set(audit_dir.iterdir())
    if actual_entries != expected_audit_paths:
        raise ResumeError("source adapter-audit set is not exact")
    audit_bytes_by_name = {
        path.name: _regular_file_bytes(path)
        for path in sorted(actual_entries, key=lambda item: item.name)
    }
    audit_entries = [
        {"name": name, "sha256": sha256_bytes(value)}
        for name, value in audit_bytes_by_name.items()
    ]
    if canonical_sha256(audit_entries) != authorization["source_audit_set_sha256"]:
        raise ResumeError("source adapter-audit digest does not match authorization")

    failed_audit_path = audit_dir / audit_filename(
        failed_simulation.task_id, failed_simulation.seed
    )
    successful_audit_paths = []
    for simulation in sorted(
        results.simulations, key=lambda item: (item.task_id, item.trial)
    ):
        path = audit_dir / audit_filename(simulation.task_id, simulation.seed)
        try:
            audit = json.loads(audit_bytes_by_name[path.name])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResumeError("source adapter audit is malformed") from exc
        if not isinstance(audit, dict):
            raise ResumeError("source adapter audit is malformed")
        if (
            audit.get("task_id") != simulation.task_id
            or audit.get("simulation_seed") != simulation.seed
        ):
            raise ResumeError("source adapter audit identity is inconsistent")
        try:
            harness._validate_runtime_audit(
                audit,
                prompt_spec,
                require_tool_delivery=simulation is not failed_simulation,
            )
        except harness.ExperimentError as exc:
            raise ResumeError("source adapter audit failed integrity checks") from exc
        if simulation is not failed_simulation:
            successful_audit_paths.append(path)

    return ResumeSource(
        source_dir=source_dir,
        results=results,
        failed_simulation=failed_simulation,
        failed_audit_path=failed_audit_path,
        successful_audit_paths=tuple(successful_audit_paths),
        audit_bytes=tuple(audit_bytes_by_name.items()),
        prompt_spec=prompt_spec,
        expected_keys=expected_keys,
        completed_keys=completed_keys,
        retry_key_sha256=key_sha256(failed_key),
        initial_start_time=results.timestamp,
        source_tasks_sha256=canonical_sha256(
            [task.model_dump(mode="json") for task in results.tasks]
        ),
        source_completed_rows_sha256=canonical_simulations_sha256(successful),
    )


def _recovery_dir_for(
    repo_root: Path, source_dir: Path, authorization_sha256: str
) -> Path:
    return (
        repo_root / "runs" / f"{source_dir.name}--recovery-{authorization_sha256[:12]}"
    )


def _require_repository_runs_dir(repo_root: Path) -> Path:
    runs_dir = repo_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if (
        runs_dir.is_symlink()
        or runs_dir.resolve(strict=True) != repo_root.resolve(strict=True) / "runs"
    ):
        raise ResumeError("repository runs directory may not traverse a symlink")
    return runs_dir


def verify_source_unchanged(
    source: ResumeSource, authorization: dict[str, Any]
) -> None:
    """Recheck the complete authorized source snapshot without opening traces."""
    if source.source_dir.is_symlink() or os.path.lexists(
        source.source_dir / "manifest.json"
    ):
        raise ResumeError("source changed during recovery")
    results_path = source.source_dir / "results.json"
    audit_dir = source.source_dir / "adapter-audits"
    if audit_dir.is_symlink():
        raise ResumeError("source changed during recovery")
    try:
        entries = tuple(audit_dir.iterdir())
    except OSError as exc:
        raise ResumeError("source changed during recovery") from exc
    if (
        sha256_path(results_path) != authorization["source_results_sha256"]
        or audit_set_sha256(entries) != authorization["source_audit_set_sha256"]
    ):
        raise ResumeError("source changed during recovery")


def _expected_staged_results(
    source: ResumeSource,
    resume_harness_commit: str,
    final_audit_dir: Path,
) -> Results:
    staged = source.results.model_copy(deep=True)
    failed_key = simulation_key(source.failed_simulation)
    staged.simulations = [
        simulation
        for simulation in staged.simulations
        if simulation_key(simulation) != failed_key
    ]
    if len(staged.simulations) != 48:
        raise ResumeError("staging did not remove exactly one checkpoint row")
    staged.info.git_commit = resume_harness_commit
    agent_args = staged.info.agent_info.llm_args
    if not isinstance(agent_args, dict):
        raise ResumeError("staged agent configuration is malformed")
    agent_args["audit_dir"] = str(final_audit_dir)
    return staged


def _results_serialized_sha256(results: Results) -> str:
    return sha256_bytes(results.model_dump_json(indent=2).encode())


def _successful_audit_bytes(source: ResumeSource) -> tuple[tuple[str, bytes], ...]:
    successful_names = {path.name for path in source.successful_audit_paths}
    return tuple(
        (name, value) for name, value in source.audit_bytes if name in successful_names
    )


def _audit_bytes_digest(entries: tuple[tuple[str, bytes], ...]) -> str:
    return canonical_sha256(
        [
            {"name": name, "sha256": sha256_bytes(value)}
            for name, value in sorted(entries)
        ]
    )


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    atomic_write_json(path, receipt)


def _load_receipt(
    recovery_dir: Path,
    authorization_sha256: str,
    source: ResumeSource,
    authorization: dict[str, Any],
    resume_harness_commit: str,
) -> dict[str, Any]:
    try:
        receipt_path = recovery_dir / _RECEIPT_NAME
        receipt = json.loads(_regular_file_bytes(receipt_path))
        if not isinstance(receipt, dict):
            raise ResumeError("staged recovery receipt is unreadable")
        assert_secret_free(receipt, "recovery_receipt")
    except Exception as exc:
        raise ResumeError("staged recovery receipt is unreadable") from exc
    required = {
        "archived_failed_audit_sha256",
        "authorization_sha256",
        "failed_audit_sha256",
        "format_version",
        "initial_start_time",
        "permitted_retry_count",
        "resume_harness_commit",
        "retry_finished_at",
        "retry_key_sha256",
        "retry_started_at",
        "retry_started_count",
        "source_audit_set_sha256",
        "source_harness_commit",
        "source_info_sha256",
        "source_tasks_sha256",
        "source_completed_rows_sha256",
        "source_results_sha256",
        "source_run_basename",
        "staged_at",
        "staged_audits_before_retry_sha256",
        "staged_results_before_retry_sha256",
        "staged_info_sha256",
        "status",
        "tau_bench_commit",
    }
    if (
        set(receipt) != required
        or type(receipt.get("format_version")) is not int
        or receipt.get("format_version") != 1
    ):
        raise ResumeError("staged recovery receipt has the wrong schema")
    if (
        receipt.get("authorization_sha256") != authorization_sha256
        or receipt.get("source_run_basename") != source.source_dir.name
        or receipt.get("retry_key_sha256") != source.retry_key_sha256
        or type(receipt.get("permitted_retry_count")) is not int
        or receipt.get("permitted_retry_count") != 1
        or receipt.get("tau_bench_commit") != TAU_COMMIT
        or receipt.get("source_results_sha256")
        != authorization["source_results_sha256"]
        or receipt.get("source_audit_set_sha256")
        != authorization["source_audit_set_sha256"]
        or receipt.get("source_info_sha256") != authorization["source_info_sha256"]
        or receipt.get("source_harness_commit")
        != authorization["source_harness_commit"]
        or receipt.get("resume_harness_commit") != resume_harness_commit
        or receipt.get("initial_start_time") != source.initial_start_time
        or receipt.get("source_tasks_sha256") != source.source_tasks_sha256
        or receipt.get("source_completed_rows_sha256")
        != source.source_completed_rows_sha256
    ):
        raise ResumeError("staged recovery receipt does not match authorization")
    for key in required:
        if key.endswith("_sha256") and (
            not isinstance(receipt[key], str)
            or not _SHA256_PATTERN.fullmatch(receipt[key])
        ):
            raise ResumeError("staged recovery receipt has a malformed SHA-256")
    expected_staged = _expected_staged_results(
        source,
        resume_harness_commit,
        recovery_dir / "adapter-audits",
    )
    expected_staged_results_sha256 = _results_serialized_sha256(expected_staged)
    expected_staged_info_sha256 = canonical_sha256(
        expected_staged.info.model_dump(mode="json")
    )
    expected_staged_audits_sha256 = _audit_bytes_digest(_successful_audit_bytes(source))
    if (
        receipt["staged_results_before_retry_sha256"] != expected_staged_results_sha256
        or receipt["staged_info_sha256"] != expected_staged_info_sha256
        or receipt["staged_audits_before_retry_sha256"] != expected_staged_audits_sha256
    ):
        raise ResumeError("staged recovery receipt contains self-declared evidence")
    evidence_path = (
        recovery_dir / RECOVERY_EVIDENCE_DIR / "interrupted-adapter-audit.json"
    )
    audit_values = dict(source.audit_bytes)
    expected_failed_audit = audit_values[source.failed_audit_path.name]
    if (
        receipt["failed_audit_sha256"] != sha256_bytes(expected_failed_audit)
        or sha256_path(evidence_path) != receipt["archived_failed_audit_sha256"]
        or receipt["failed_audit_sha256"] != receipt["archived_failed_audit_sha256"]
    ):
        raise ResumeError("staged failed-audit evidence is inconsistent")
    if (
        receipt["status"]
        not in {
            "staged",
            "retry_started",
            "retry_returned",
            "retry_failed",
            "finalized",
        }
        or type(receipt["retry_started_count"]) is not int
        or receipt["retry_started_count"] not in {0, 1}
    ):
        raise ResumeError("staged recovery receipt state is invalid")
    return receipt


def stage_recovery(
    repo_root: Path,
    source: ResumeSource,
    authorization: dict[str, Any],
    authorization_sha256: str,
    resume_harness_commit: str,
) -> tuple[Path, dict[str, Any]]:
    """Create a deterministic missing-only checkpoint without touching source."""
    runs_dir = _require_repository_runs_dir(repo_root)
    recovery_dir = _recovery_dir_for(repo_root, source.source_dir, authorization_sha256)
    if os.path.lexists(recovery_dir):
        if recovery_dir.is_symlink() or not recovery_dir.is_dir():
            raise ResumeError("deterministic recovery path is not a directory")
        if recovery_dir.resolve(strict=True).parent != runs_dir:
            raise ResumeError("deterministic recovery path escapes repository runs")
        return recovery_dir, _load_receipt(
            recovery_dir,
            authorization_sha256,
            source,
            authorization,
            resume_harness_commit,
        )

    temporary_dir = Path(tempfile.mkdtemp(prefix=".resume-staging-", dir=runs_dir))
    final_audit_dir = recovery_dir / "adapter-audits"
    try:
        temporary_audit_dir = temporary_dir / "adapter-audits"
        temporary_audit_dir.mkdir(parents=True)
        for name, value in _successful_audit_bytes(source):
            (temporary_audit_dir / name).write_bytes(value)

        evidence_dir = temporary_dir / RECOVERY_EVIDENCE_DIR
        evidence_dir.mkdir()
        archived_failed_audit = evidence_dir / "interrupted-adapter-audit.json"
        failed_audit_bytes = dict(source.audit_bytes)[source.failed_audit_path.name]
        archived_failed_audit.write_bytes(failed_audit_bytes)

        staged_results = _expected_staged_results(
            source, resume_harness_commit, final_audit_dir
        )

        temporary_results_path = temporary_dir / "results.json"
        atomic_write_results(temporary_results_path, staged_results)
        receipt = {
            "format_version": 1,
            "status": "staged",
            "authorization_sha256": authorization_sha256,
            "source_run_basename": source.source_dir.name,
            "source_results_sha256": authorization["source_results_sha256"],
            "source_audit_set_sha256": authorization["source_audit_set_sha256"],
            "source_info_sha256": authorization["source_info_sha256"],
            "source_tasks_sha256": source.source_tasks_sha256,
            "source_completed_rows_sha256": source.source_completed_rows_sha256,
            "source_harness_commit": authorization["source_harness_commit"],
            "resume_harness_commit": resume_harness_commit,
            "tau_bench_commit": TAU_COMMIT,
            "retry_key_sha256": source.retry_key_sha256,
            "permitted_retry_count": 1,
            "retry_started_count": 0,
            "initial_start_time": source.initial_start_time,
            "staged_at": harness_now(),
            "retry_started_at": None,
            "retry_finished_at": None,
            "staged_results_before_retry_sha256": sha256_path(temporary_results_path),
            "staged_info_sha256": canonical_sha256(
                staged_results.info.model_dump(mode="json")
            ),
            "staged_audits_before_retry_sha256": audit_set_sha256(
                tuple(temporary_audit_dir.iterdir())
            ),
            "failed_audit_sha256": sha256_bytes(failed_audit_bytes),
            "archived_failed_audit_sha256": sha256_path(archived_failed_audit),
        }
        _write_receipt(temporary_dir / _RECEIPT_NAME, receipt)
        temporary_dir.replace(recovery_dir)
        return recovery_dir, receipt
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def harness_now() -> str:
    from .run import _utc_now

    return _utc_now()


def _active_audit_paths(recovery_dir: Path) -> tuple[Path, ...]:
    audit_dir = recovery_dir / "adapter-audits"
    if audit_dir.is_symlink() or not audit_dir.is_dir():
        raise ResumeError("staged active audit directory is missing")
    entries = tuple(audit_dir.iterdir())
    for path in entries:
        _regular_file_bytes(path)
    return entries


def _load_attempt_claim(
    recovery_dir: Path,
    receipt: dict[str, Any],
) -> dict[str, Any] | None:
    path = recovery_dir / _ATTEMPT_CLAIM_NAME
    if not path.exists():
        return None
    try:
        claim = json.loads(_regular_file_bytes(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeError("retry-attempt claim is unreadable") from exc
    required = {
        "authorization_sha256",
        "claimed_at",
        "format_version",
        "retry_key_sha256",
    }
    if (
        not isinstance(claim, dict)
        or set(claim) != required
        or type(claim.get("format_version")) is not int
        or claim.get("format_version") != 1
        or claim.get("authorization_sha256") != receipt["authorization_sha256"]
        or claim.get("retry_key_sha256") != receipt["retry_key_sha256"]
        or not isinstance(claim.get("claimed_at"), str)
        or not claim["claimed_at"]
    ):
        raise ResumeError("retry-attempt claim is invalid")
    assert_secret_free(claim, "retry_attempt_claim")
    return claim


def claim_retry_attempt(
    recovery_dir: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Atomically consume the one authorized attempt before any model work."""
    claim = {
        "format_version": 1,
        "authorization_sha256": receipt["authorization_sha256"],
        "retry_key_sha256": receipt["retry_key_sha256"],
        "claimed_at": harness_now(),
    }
    assert_secret_free(claim, "retry_attempt_claim")
    payload = (json.dumps(claim, indent=2, sort_keys=True) + "\n").encode()
    path = recovery_dir / _ATTEMPT_CLAIM_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ResumeError(
            "recovery attempt may have started; another retry is forbidden"
        ) from exc
    except OSError as exc:
        raise ResumeError("could not atomically claim the retry attempt") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        directory_descriptor = os.open(recovery_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        # The exclusive marker is deliberately not removed: an ambiguous claim is
        # terminal and must never permit another evaluated inference.
        raise
    return update_recovery_receipt(
        recovery_dir,
        receipt,
        status="retry_started",
        started=True,
    )


def classify_recovery_checkpoint(
    recovery_dir: Path,
    source: ResumeSource,
    receipt: dict[str, Any],
) -> str:
    """Return staged, complete, or failed without exposing the retry identity."""
    if os.path.lexists(recovery_dir / "manifest.json"):
        raise ResumeError("recovery is already finalized; retry is forbidden")
    results = load_results_regular(
        recovery_dir / "results.json",
        "staged recovery checkpoint is unreadable",
    )
    actual_keys = [simulation_key(simulation) for simulation in results.simulations]
    if len(set(actual_keys)) != len(actual_keys):
        raise ResumeError("staged recovery checkpoint contains duplicate keys")
    expected_keys = set(source.expected_keys)
    actual_key_set = set(actual_keys)
    retry_key = simulation_key(source.failed_simulation)
    missing_keys = expected_keys - actual_key_set
    claim = _load_attempt_claim(recovery_dir, receipt)
    if actual_key_set - expected_keys:
        raise ResumeError("staged recovery checkpoint contains an unauthorized key")

    active_paths = _active_audit_paths(recovery_dir)
    if missing_keys == {retry_key}:
        if (
            claim is not None
            or receipt["status"] != "staged"
            or receipt["retry_started_count"] != 0
        ):
            raise ResumeError(
                "recovery attempt may have started; another retry is forbidden"
            )
        expected_names = {path.name for path in source.successful_audit_paths}
        if {path.name for path in active_paths} != expected_names:
            raise ResumeError("staged active audit set does not match completed rows")
        if (
            sha256_path(recovery_dir / "results.json")
            != receipt["staged_results_before_retry_sha256"]
            or audit_set_sha256(active_paths)
            != receipt["staged_audits_before_retry_sha256"]
        ):
            raise ResumeError("staged recovery state changed before retry")
        return "staged"
    if missing_keys:
        raise ResumeError("staged recovery checkpoint has an unauthorized gap")
    if receipt["retry_started_count"] != 1:
        raise ResumeError("completed recovery lacks a one-attempt receipt")
    if claim is None:
        raise ResumeError("completed recovery lacks an atomic attempt claim")
    if (
        canonical_sha256(results.info.model_dump(mode="json"))
        != receipt["staged_info_sha256"]
    ):
        raise ResumeError("recovery changed the staged run information")
    if (
        canonical_sha256([task.model_dump(mode="json") for task in results.tasks])
        != receipt["source_tasks_sha256"]
    ):
        raise ResumeError("recovery changed the frozen task payloads")
    completed = [
        simulation
        for simulation in results.simulations
        if simulation_key(simulation) in source.completed_keys
    ]
    if (
        len(completed) != 48
        or canonical_simulations_sha256(completed)
        != receipt["source_completed_rows_sha256"]
    ):
        raise ResumeError("recovery changed an already completed trajectory")
    successful_audit_names = {path.name for path in source.successful_audit_paths}
    expected_final_audit_names = successful_audit_names | {
        source.failed_audit_path.name
    }
    if {path.name for path in active_paths} != expected_final_audit_names:
        raise ResumeError("completed recovery has the wrong adapter-audit set")
    completed_audits = tuple(
        path for path in active_paths if path.name in successful_audit_names
    )
    if (
        len(completed_audits) != 48
        or audit_set_sha256(completed_audits)
        != receipt["staged_audits_before_retry_sha256"]
    ):
        raise ResumeError("recovery changed a completed adapter audit")
    retried = next(
        simulation
        for simulation in results.simulations
        if simulation_key(simulation) == retry_key
    )
    if (
        retried.termination_reason
        in {
            TerminationReason.INFRASTRUCTURE_ERROR,
            TerminationReason.UNEXPECTED_ERROR,
        }
        or retried.reward_info is None
    ):
        return "failed"
    return "complete"


def update_recovery_receipt(
    recovery_dir: Path,
    receipt: dict[str, Any],
    *,
    status: str,
    started: bool = False,
    finished: bool = False,
) -> dict[str, Any]:
    updated = dict(receipt)
    updated["status"] = status
    if started:
        if updated["retry_started_count"] != 0:
            raise ResumeError("authorization permits only one retry attempt")
        updated["retry_started_count"] = 1
        updated["retry_started_at"] = harness_now()
    if finished:
        updated["retry_finished_at"] = harness_now()
    _write_receipt(recovery_dir / _RECEIPT_NAME, updated)
    return updated


def recovery_manifest_context(
    source: ResumeSource,
    authorization: dict[str, Any],
    authorization_sha256: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_dir": source.source_dir,
        "authorization_sha256": authorization_sha256,
        "source_results_sha256": authorization["source_results_sha256"],
        "source_audit_set_sha256": authorization["source_audit_set_sha256"],
        "source_info_sha256": authorization["source_info_sha256"],
        "source_harness_commit": authorization["source_harness_commit"],
        "retry_key_sha256": source.retry_key_sha256,
        "initial_start_time": source.initial_start_time,
        "staged_results_before_retry_sha256": receipt[
            "staged_results_before_retry_sha256"
        ],
        "staged_audits_before_retry_sha256": receipt[
            "staged_audits_before_retry_sha256"
        ],
        "staged_info_sha256": receipt["staged_info_sha256"],
        "source_tasks_sha256": receipt["source_tasks_sha256"],
        "source_completed_rows_sha256": receipt["source_completed_rows_sha256"],
        "retry_started_at": receipt["retry_started_at"],
        "retry_finished_at": receipt["retry_finished_at"],
        "completed_keys": source.completed_keys,
        "successful_audit_names": frozenset(
            path.name for path in source.successful_audit_paths
        ),
    }


def resume_interrupted(experiment_path: Path, source_run_dir: Path) -> Path:
    """Retry exactly one committed-and-authorized interrupted trajectory."""
    from . import run as harness

    started_at = harness._utc_now()
    repo_root = harness._repo_root()
    authorization, authorization_path, authorization_sha256 = load_resume_authorization(
        repo_root
    )
    authorization_matches_argument(authorization, experiment_path, source_run_dir)
    resume_harness_commit, _ = require_clean_repositories(
        repo_root,
        authorization_path,
        authorization_sha256,
    )

    resolved_experiment_path = experiment_path.resolve(strict=True)
    if resolved_experiment_path.parent != (repo_root / "experiments").resolve():
        raise ResumeError("experiment must be the committed repository config")
    runs_dir = _require_repository_runs_dir(repo_root)
    resolved_source_dir = source_run_dir.resolve(strict=True)
    if resolved_source_dir.parent != runs_dir:
        raise ResumeError("source run must be a direct child of repository runs")
    if (
        source_run_dir.is_symlink()
        or resolved_source_dir.name != authorization["source_run_basename"]
    ):
        raise ResumeError("resolved source does not match authorization")

    experiment = harness.load_experiment(resolved_experiment_path)
    require_execution_inputs_at_commits(
        repo_root,
        resolved_experiment_path,
        experiment,
        authorization,
        resume_harness_commit,
    )
    source = inspect_resume_source(
        resolved_source_dir,
        resolved_experiment_path,
        experiment,
        authorization,
    )
    check = harness.preflight(resolved_experiment_path)
    if (
        check["system_prompt_sha256"] != authorization["effective_system_prompt_sha256"]
        or check["agent_instruction_sha256"]
        != authorization["agent_instruction_sha256"]
        or check["tool_schema_sha256"] != authorization["tool_schema_sha256"]
    ):
        raise ResumeError("preflight differs from the committed authorization")

    recovery_dir, receipt = stage_recovery(
        repo_root,
        source,
        authorization,
        authorization_sha256,
        resume_harness_commit,
    )
    verify_source_unchanged(source, authorization)
    state = classify_recovery_checkpoint(recovery_dir, source, receipt)
    if state == "failed":
        raise ResumeError(
            "the single authorized retry failed; another retry is forbidden"
        )
    if state == "staged":
        tasks = harness.get_tasks(
            "banking_knowledge",
            task_split_name=None,
            task_ids=tuple(experiment["task_ids"]),
        )
        config = harness._build_run_config(
            experiment,
            check,
            repo_root,
            recovery_dir / "adapter-audits",
            auto_resume=True,
        )
        validate_tau_resume_contract(
            config,
            tasks,
            recovery_dir,
            source,
            receipt,
        )
        runner_log = recovery_dir / "recovery-runner.log"
        if os.path.lexists(runner_log):
            raise ResumeError("recovery runner log already exists")
        # These are the last fallible, model-free gates before the exclusive
        # attempt claim. Recheck every mutable input after preflight/staging.
        current_commit, _ = require_clean_repositories(
            repo_root,
            authorization_path,
            authorization_sha256,
        )
        if current_commit != resume_harness_commit:
            raise ResumeError("harness HEAD changed before recovery inference")
        require_execution_inputs_at_commits(
            repo_root,
            resolved_experiment_path,
            experiment,
            authorization,
            resume_harness_commit,
        )
        verify_source_unchanged(source, authorization)
        classify_recovery_checkpoint(recovery_dir, source, receipt)
        receipt = claim_retry_attempt(recovery_dir, receipt)
        if registry.get_agent_factory(harness.AGENT_NAME) is None:
            registry.register_agent_factory(create_codex_tau_agent, harness.AGENT_NAME)
        try:
            with _open_exclusive_runner_log(runner_log) as quiet_output:
                with (
                    contextlib.redirect_stdout(quiet_output),
                    contextlib.redirect_stderr(quiet_output),
                ):
                    run_tasks(
                        config,
                        tasks,
                        save_path=recovery_dir / "results.json",
                        save_dir=recovery_dir,
                        console_display=False,
                        results_format="json",
                    )
            receipt = update_recovery_receipt(
                recovery_dir,
                receipt,
                status="retry_returned",
                finished=True,
            )
        except BaseException as exc:
            update_recovery_receipt(
                recovery_dir,
                receipt,
                status="retry_failed",
                finished=True,
            )
            raise ResumeError(
                "the single authorized retry did not complete; no manifest was written"
            ) from exc
        state = classify_recovery_checkpoint(recovery_dir, source, receipt)
        if state != "complete":
            receipt = update_recovery_receipt(
                recovery_dir,
                receipt,
                status="retry_failed",
            )
            raise ResumeError(
                "the single authorized retry failed integrity checks; "
                "no manifest was written"
            )

    final_commit, _ = require_clean_repositories(
        repo_root,
        authorization_path,
        authorization_sha256,
    )
    if final_commit != resume_harness_commit:
        raise ResumeError("harness HEAD changed during recovery")
    require_execution_inputs_at_commits(
        repo_root,
        resolved_experiment_path,
        experiment,
        authorization,
        resume_harness_commit,
    )
    verify_source_unchanged(source, authorization)

    try:
        output = harness._finalize_experiment(
            experiment,
            check,
            recovery_dir,
            started_at,
            recovery=recovery_manifest_context(
                source, authorization, authorization_sha256, receipt
            ),
        )
    except Exception as exc:
        raise ResumeError(
            "recovery final integrity validation failed; no manifest was written"
        ) from exc
    update_recovery_receipt(
        recovery_dir,
        receipt,
        status="finalized",
    )
    return output
