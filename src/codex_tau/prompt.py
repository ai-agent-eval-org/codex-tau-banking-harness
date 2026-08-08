"""Exact prompt construction for the standard tau2 LLM agent."""

from __future__ import annotations

import hashlib

from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT


def prompt_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


STANDARD_AGENT_INSTRUCTION_SHA256 = prompt_hash(AGENT_INSTRUCTION.encode())


def standard_system_prompt(domain_policy: str) -> str:
    """Use the exact prompt constructor used by tau2's standard LLMAgent."""
    return SYSTEM_PROMPT.format(
        domain_policy=domain_policy,
        agent_instruction=AGENT_INSTRUCTION,
    )
