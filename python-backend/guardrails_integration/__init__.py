"""
dspy-guardrails integration for Virtual Agent security monitoring.

This package provides:
- GuardrailMonitor: Real-time monitoring of agent inputs/outputs
- AgentHooks: Hooks for injecting guardrail checks into agent flow
"""

from .monitors import GuardrailMonitor, GuardrailEvent
from .hooks import AgentHooks

__all__ = [
    "GuardrailMonitor",
    "GuardrailEvent",
    "AgentHooks",
]
