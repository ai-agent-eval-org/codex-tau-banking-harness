from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from tau2.data_model.simulation import RewardInfo, TerminationReason

from codex_tau.agent import CodexTauAgent, audit_filename
from codex_tau.run import ExperimentError, _collect_audits, _validate_results

TRIAL_SEEDS = (626729, 373753, 361454, 1567)


def fake_results() -> SimpleNamespace:
    simulations = []
    for trial, seed in enumerate(TRIAL_SEEDS):
        for task_id in ("task_002", "task_008"):
            simulations.append(
                SimpleNamespace(
                    task_id=task_id,
                    trial=trial,
                    seed=seed,
                    reward_info=RewardInfo(reward=1.0),
                    termination_reason=TerminationReason.USER_STOP,
                    info={},
                )
            )
    return SimpleNamespace(simulations=simulations)


def test_four_trial_results_and_audits_are_unique(tmp_path) -> None:
    results = fake_results()
    _validate_results(results, ("task_002", "task_008"), 4)
    for simulation in results.simulations:
        path = tmp_path / audit_filename(simulation.task_id, simulation.seed)
        path.write_text(
            json.dumps(
                {
                    "task_id": simulation.task_id,
                    "simulation_seed": simulation.seed,
                }
            )
        )
    audits, paths = _collect_audits(tmp_path, results)
    assert len(audits) == 8
    assert len(paths) == len(set(paths)) == 8


def test_duplicate_task_trial_pair_is_rejected() -> None:
    results = fake_results()
    results.simulations[-1].trial = 0
    results.simulations[-1].seed = TRIAL_SEEDS[0]
    with pytest.raises(ExperimentError, match="duplicate task/trial"):
        _validate_results(results, ("task_002", "task_008"), 4)


def test_agent_seed_rebinds_pending_audit(tmp_path) -> None:
    pending = tmp_path / "task_002--pending-token.json"
    pending.write_text("{}")
    agent = object.__new__(CodexTauAgent)
    agent.task_id = "task_002"
    agent.audit_path = pending
    agent.runtime = SimpleNamespace(audit={"task_id": "task_002"})
    agent.set_seed(TRIAL_SEEDS[0])
    expected = tmp_path / audit_filename("task_002", TRIAL_SEEDS[0])
    assert agent.audit_path == expected
    assert not pending.exists()
    assert json.loads(expected.read_text())["simulation_seed"] == TRIAL_SEEDS[0]
