from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from codex_tau.app_server import APP_SERVER_STREAM_READER_LIMIT_BYTES
from codex_tau.prompt import BASELINE_SYSTEM_PROMPT_PATH, standard_prompt_spec
from codex_tau.run import ExperimentError, _alltools_contract, _validate_runtime_audit

REPO_ROOT = Path(__file__).resolve().parents[1]


def valid_audit() -> tuple[dict, object]:
    _, policy = _alltools_contract()
    prompt_spec = standard_prompt_spec(repo_root=REPO_ROOT, domain_policy=policy)
    audit = {
        "account": {
            "type": "chatgpt",
            "plan_type": "prolite",
            "requires_openai_auth": True,
        },
        "adapter_stage": "stopped",
        "base_instructions_sha256": prompt_spec.system_prompt_sha256,
        "developer_instructions_empty": True,
        "dynamic_call_count": 3,
        "system_prompt_sha256": prompt_spec.system_prompt_sha256,
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
        "prompt_mode": prompt_spec.mode,
        "prompt_source_path": BASELINE_SYSTEM_PROMPT_PATH.as_posix(),
        "prompt_source_file_sha256": prompt_spec.source_file_sha256,
        "tool_result_delivery_complete": True,
        "tool_results_returned": 3,
        "transport_stream_reader_limit_bytes": (
            APP_SERVER_STREAM_READER_LIMIT_BYTES
        ),
    }
    return audit, prompt_spec


def test_complete_post_run_audit_is_accepted() -> None:
    audit, prompt_spec = valid_audit()
    _validate_runtime_audit(audit, prompt_spec, require_tool_delivery=True)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("base_instructions_sha256",), "0" * 64, "prompt hash"),
        (("account", "type"), "apiKey", "ChatGPT"),
        (("observed_thread_model",), "gpt-5.3", "GPT-5.4"),
        (("model_rerouted",), True, "rerouted"),
        (("native_capability_denied",), True, "native"),
        (("instruction_sources",), ["AGENTS.md"], "instruction source"),
        (("tool_results_returned",), 2, "tool delivery"),
    ],
)
def test_post_run_audit_fails_closed(
    path: tuple[str, ...], value: object, message: str
) -> None:
    audit, prompt_spec = valid_audit()
    changed = deepcopy(audit)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ExperimentError, match=message):
        _validate_runtime_audit(changed, prompt_spec, require_tool_delivery=True)
