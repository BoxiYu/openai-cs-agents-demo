"""
Agent hooks for integrating guardrail checks into agent execution flow.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, Any, Optional

from .monitors import GuardrailMonitor, ValidationResult


class AgentHooks:
    """
    Hooks for injecting guardrail checks into agent execution.

    Provides decorators and callbacks for:
    - Checking tool outputs before agent processes them
    - Checking agent responses before sending to user
    - Logging and alerting on violations
    """

    def __init__(self, monitor: Optional[GuardrailMonitor] = None):
        """
        Initialize hooks.

        Args:
            monitor: GuardrailMonitor instance (creates one if not provided)
        """
        self.monitor = monitor or GuardrailMonitor()
        self.on_violation: Callable[[str, ValidationResult], None] = self._default_violation_handler
        self.block_on_violation: bool = False  # Whether to block responses with violations

    def _default_violation_handler(self, source: str, result: ValidationResult):
        """Default handler for violations - just logs."""
        print(f"[GUARDRAIL VIOLATION] {source}: {result.message}")

    def set_violation_handler(self, handler: Callable[[str, ValidationResult], None]):
        """Set custom violation handler."""
        self.on_violation = handler

    def wrap_tool(self, tool_func: Callable) -> Callable:
        """
        Decorator to wrap a tool function with guardrail checks.

        Checks the tool's output for injected malicious content
        before it's processed by the agent.

        Args:
            tool_func: The tool function to wrap

        Returns:
            Wrapped function with guardrail checks
        """
        @wraps(tool_func)
        async def wrapped(*args, **kwargs):
            # Execute original tool
            result = await tool_func(*args, **kwargs)

            # Check output
            tool_name = getattr(tool_func, "__name__", "unknown_tool")
            result_str = str(result)

            violations = self.monitor.check_tool_output(tool_name, result_str)

            for v in violations:
                if not v.passed:
                    self.on_violation(f"tool:{tool_name}", v)

            return result

        return wrapped

    def check_user_input(self, input_text: str) -> tuple[bool, list[ValidationResult]]:
        """
        Check user input before processing.

        Args:
            input_text: User's input message

        Returns:
            Tuple of (is_safe, list of validation results)
        """
        results = self.monitor.check_user_input(input_text)
        is_safe = all(r.passed for r in results)

        for r in results:
            if not r.passed:
                self.on_violation("user_input", r)

        return is_safe, results

    def check_before_response(self, response: str) -> tuple[bool, str]:
        """
        Check agent response before sending to user.

        Args:
            response: Agent's response text

        Returns:
            Tuple of (is_safe, potentially_modified_response)
        """
        results = self.monitor.check_agent_response(response)
        is_safe = all(r.passed for r in results)

        for r in results:
            if not r.passed:
                self.on_violation("agent_response", r)

        if not is_safe and self.block_on_violation:
            return False, "I apologize, but I cannot provide that response."

        return is_safe, response

    def get_monitoring_stats(self) -> dict:
        """Get current monitoring statistics."""
        return self.monitor.get_summary()


class ToolOutputFilter:
    """
    Filter for removing potentially malicious content from tool outputs.
    """

    # Patterns that indicate injected instructions
    DANGEROUS_PATTERNS = [
        "忽略之前",
        "ignore previous",
        "[SYSTEM",
        "[系统",
        "开发者模式",
        "developer mode",
        "DAN模式",
        "DAN mode",
    ]

    @classmethod
    def filter_output(cls, output: str) -> tuple[str, bool]:
        """
        Filter potentially malicious content from output.

        Args:
            output: Tool output to filter

        Returns:
            Tuple of (filtered_output, was_modified)
        """
        output_lower = output.lower()

        for pattern in cls.DANGEROUS_PATTERNS:
            if pattern.lower() in output_lower:
                # Find and remove the dangerous section
                # For now, just truncate at the pattern
                idx = output_lower.find(pattern.lower())
                if idx > 0:
                    return output[:idx] + "\n[Content filtered for security]", True

        return output, False


def create_guarded_tool(tool_func: Callable, monitor: GuardrailMonitor) -> Callable:
    """
    Factory function to create a guarded version of a tool.

    Args:
        tool_func: Original tool function
        monitor: GuardrailMonitor instance

    Returns:
        Guarded tool function
    """
    hooks = AgentHooks(monitor)
    return hooks.wrap_tool(tool_func)
