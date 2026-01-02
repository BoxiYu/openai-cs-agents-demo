"""
Security testing framework for Virtual Agent.

This package provides:
- FaultInjector: Inject delays, failures, and malicious content
- TestRunner: Run security and robustness test suites
- ReportGenerator: Generate test reports in JSON and Markdown
"""

from .fault_injector import FaultInjector, FaultConfig, create_injector_for_scenario

__all__ = [
    "FaultInjector",
    "FaultConfig",
    "create_injector_for_scenario",
]

# Lazy imports to avoid circular dependencies
def get_test_runner():
    from .test_runner import TestRunner
    return TestRunner

def get_report_generator():
    from .report_generator import ReportGenerator
    return ReportGenerator
