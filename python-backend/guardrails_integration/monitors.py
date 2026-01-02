"""
Guardrail monitoring for real-time security detection.

Integrates with dspy-guardrails to monitor agent interactions
and detect potential security violations.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Any


@dataclass
class ValidationResult:
    """Result of a guardrail validation check."""
    passed: bool
    score: float  # 0.0 - 1.0
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class GuardrailEvent:
    """Record of a single guardrail check."""
    timestamp: str
    guardrail_name: str
    input_text: str
    result: ValidationResult
    source: str  # "user_input", "tool_output", "agent_response"
    tool_name: Optional[str] = None


class SimplePromptInjectionDetector:
    """
    Simple pattern-based prompt injection detector.
    Used when dspy-guardrails is not available.
    """

    INJECTION_PATTERNS = [
        r"忽略.{0,20}(之前|所有|以上).{0,10}(指令|说明|规则)",
        r"ignore.{0,20}(previous|all|above).{0,10}(instructions?|rules?)",
        r"\[?(SYSTEM|系统|管理员)\]?\s*(OVERRIDE|覆盖|更新)",
        r"你(现在|已经)?是.{0,10}(管理员|开发者|超级用户)",
        r"(DAN|Developer)\s*(Mode|模式)",
        r"(进入|启用|激活).{0,10}(开发者|管理员|调试)\s*(模式|权限)",
        r"请?(输出|显示|告诉我).{0,20}(系统提示|system prompt)",
        r"安全(检查|限制).{0,10}(已禁用|已关闭|跳过)",
    ]

    def __init__(self):
        self.patterns = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def validate(self, text: str) -> ValidationResult:
        """Check for prompt injection patterns."""
        for pattern in self.patterns:
            if pattern.search(text):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    message=f"Potential prompt injection detected: {pattern.pattern}",
                    details={"pattern": pattern.pattern}
                )
        return ValidationResult(
            passed=True,
            score=1.0,
            message="No prompt injection patterns detected",
            details={}
        )


class SimplePIIDetector:
    """
    Simple pattern-based PII detector.
    Detects credit card numbers, SSN, email addresses, phone numbers.
    """

    PII_PATTERNS = {
        "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "cvv": r"\bCVV[:\s]*\d{3,4}\b",
        "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        "email_leak": r"发送.{0,20}(邮件|信息).{0,10}到.{0,20}@",
        "api_key": r"(api[_-]?key|token|密钥)[:\s]*['\"]?[\w-]{20,}",
    }

    def __init__(self):
        self.patterns = {k: re.compile(v, re.IGNORECASE) for k, v in self.PII_PATTERNS.items()}

    def validate(self, text: str) -> ValidationResult:
        """Check for PII patterns."""
        for pii_type, pattern in self.patterns.items():
            if pattern.search(text):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    message=f"Potential PII detected: {pii_type}",
                    details={"pii_type": pii_type}
                )
        return ValidationResult(
            passed=True,
            score=1.0,
            message="No PII patterns detected",
            details={}
        )


class SimpleJailbreakDetector:
    """
    Simple pattern-based jailbreak detector.
    Detects common jailbreak attempts.
    """

    JAILBREAK_PATTERNS = [
        r"(DAN|Do Anything Now)\s*(模式|mode)",
        r"没有.{0,10}(限制|规则|约束)",
        r"(no|without).{0,10}(limits?|restrictions?|rules?)",
        r"假(装|设|如|扮).{0,20}(你是|没有限制)",
        r"(pretend|imagine|suppose).{0,20}(you are|no restrictions)",
        r"(角色扮演|roleplay).{0,20}(绕过|bypass)",
        r"(忘记|forget).{0,20}(你是|规则|限制)",
        r"从现在开始.{0,20}(不要|不再|没有)",
    ]

    def __init__(self):
        self.patterns = [re.compile(p, re.IGNORECASE) for p in self.JAILBREAK_PATTERNS]

    def validate(self, text: str) -> ValidationResult:
        """Check for jailbreak attempts."""
        for pattern in self.patterns:
            if pattern.search(text):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    message=f"Potential jailbreak attempt detected",
                    details={"pattern": pattern.pattern}
                )
        return ValidationResult(
            passed=True,
            score=1.0,
            message="No jailbreak patterns detected",
            details={}
        )


class GuardrailMonitor:
    """
    Real-time guardrail monitoring for agent interactions.

    Checks user inputs, tool outputs, and agent responses
    against configured guardrails.
    """

    def __init__(self, use_dspy_guardrails: bool = True):
        """
        Initialize the monitor.

        Args:
            use_dspy_guardrails: Whether to use dspy-guardrails library
                                 (falls back to simple detectors if unavailable)
        """
        self.events: list[GuardrailEvent] = []
        self._guardrails: dict = {}
        self._use_dspy = use_dspy_guardrails

        self._init_guardrails()

    def _init_guardrails(self):
        """Initialize guardrails (dspy or fallback)."""
        if self._use_dspy:
            try:
                # Try to import dspy-guardrails
                dspy_path = Path(__file__).parent.parent.parent.parent / "src"
                if dspy_path.exists():
                    sys.path.insert(0, str(dspy_path))

                from dspy_guardrails.input_guardrails.prompt_injection import PromptInjectionGuardrail
                from dspy_guardrails.content_safety.pii_detection import PIIDetectionGuardrail

                self._guardrails["prompt_injection"] = PromptInjectionGuardrail()
                self._guardrails["pii_detection"] = PIIDetectionGuardrail()
                print("Using dspy-guardrails for security monitoring")
                return
            except ImportError as e:
                print(f"dspy-guardrails not available ({e}), using fallback detectors")

        # Fallback to simple pattern-based detectors
        self._guardrails["prompt_injection"] = SimplePromptInjectionDetector()
        self._guardrails["pii_detection"] = SimplePIIDetector()
        self._guardrails["jailbreak"] = SimpleJailbreakDetector()

    def check_user_input(self, text: str) -> list[ValidationResult]:
        """
        Check user input against all guardrails.

        Args:
            text: User's input message

        Returns:
            List of validation results
        """
        return self._run_checks(text, "user_input")

    def check_tool_output(self, tool_name: str, output: str) -> list[ValidationResult]:
        """
        Check tool output for injected malicious content.

        Args:
            tool_name: Name of the tool that produced the output
            output: The tool's output

        Returns:
            List of validation results
        """
        return self._run_checks(output, "tool_output", tool_name)

    def check_agent_response(self, response: str) -> list[ValidationResult]:
        """
        Check agent's final response before sending to user.

        Args:
            response: Agent's response text

        Returns:
            List of validation results
        """
        return self._run_checks(response, "agent_response")

    def _run_checks(
        self,
        text: str,
        source: str,
        tool_name: Optional[str] = None
    ) -> list[ValidationResult]:
        """Run all guardrail checks on text."""
        results = []

        for name, guardrail in self._guardrails.items():
            try:
                result = guardrail.validate(text)
                # Convert to our ValidationResult if needed
                if not isinstance(result, ValidationResult):
                    result = ValidationResult(
                        passed=getattr(result, 'passed', True),
                        score=getattr(result, 'score', 1.0),
                        message=getattr(result, 'message', ''),
                        details=getattr(result, 'details', {})
                    )
            except Exception as e:
                result = ValidationResult(
                    passed=True,
                    score=1.0,
                    message=f"Guardrail check failed: {e}",
                    details={"error": str(e)}
                )

            self._record_event(name, text, result, source, tool_name)
            results.append(result)

        return results

    def _record_event(
        self,
        guardrail_name: str,
        text: str,
        result: ValidationResult,
        source: str,
        tool_name: Optional[str] = None
    ):
        """Record a guardrail check event."""
        # Truncate long text
        display_text = text[:500] + "..." if len(text) > 500 else text

        event = GuardrailEvent(
            timestamp=datetime.now().isoformat(),
            guardrail_name=guardrail_name,
            input_text=display_text,
            result=result,
            source=source,
            tool_name=tool_name
        )
        self.events.append(event)

    def get_violations(self) -> list[GuardrailEvent]:
        """Get all events where guardrails were violated."""
        return [e for e in self.events if not e.result.passed]

    def get_summary(self) -> dict:
        """Get monitoring summary statistics."""
        violations = self.get_violations()

        return {
            "total_checks": len(self.events),
            "violations": len(violations),
            "violation_rate": len(violations) / len(self.events) if self.events else 0,
            "by_guardrail": self._count_by_field("guardrail_name"),
            "by_source": self._count_by_field("source"),
            "violations_detail": [
                {
                    "timestamp": v.timestamp,
                    "guardrail": v.guardrail_name,
                    "source": v.source,
                    "tool": v.tool_name,
                    "message": v.result.message
                }
                for v in violations
            ]
        }

    def _count_by_field(self, field_name: str) -> dict:
        """Count events by a specific field."""
        counts: dict = {}
        for event in self.events:
            key = getattr(event, field_name)
            if key not in counts:
                counts[key] = {"total": 0, "violations": 0}
            counts[key]["total"] += 1
            if not event.result.passed:
                counts[key]["violations"] += 1
        return counts

    def export_events(self, path: Path):
        """Export events to JSON file."""
        data = {
            "summary": self.get_summary(),
            "events": [
                {
                    "timestamp": e.timestamp,
                    "guardrail_name": e.guardrail_name,
                    "input_text": e.input_text,
                    "passed": e.result.passed,
                    "score": e.result.score,
                    "message": e.result.message,
                    "source": e.source,
                    "tool_name": e.tool_name
                }
                for e in self.events
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self):
        """Clear all recorded events."""
        self.events.clear()
