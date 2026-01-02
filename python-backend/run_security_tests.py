#!/usr/bin/env python3
"""
Security Test Runner for Enhanced Virtual Agent.

Usage:
    python run_security_tests.py                    # Run all tests
    python run_security_tests.py --category attacks # Run specific category
    python run_security_tests.py --scenario prompt_injection_via_db  # Run specific scenario
    python run_security_tests.py --list             # List available scenarios
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from testing.fault_injector import FaultInjector, list_scenarios, ATTACK_SCENARIOS
from testing.test_runner import TestRunner, TestCase
from testing.report_generator import ReportGenerator
from guardrails_integration.monitors import GuardrailMonitor


async def run_with_simulated_agent(
    user_input: str,
    fault_injector: FaultInjector,
    monitor: GuardrailMonitor
) -> str:
    """
    Simulate agent response with fault injection and guardrail monitoring.

    This is a placeholder that can be replaced with actual agent integration.
    """
    # Simulate tool calls
    tools_called = []

    for tool_name in ["db_query", "kb_search", "mcp_call"]:
        config = fault_injector.get_config(tool_name)
        if not config or not config.enabled:
            continue

        tools_called.append(tool_name)

        # Check for delay
        delay = fault_injector.inject_delay(tool_name)
        if delay > 0:
            await asyncio.sleep(min(delay, 0.1))  # Cap for testing

        # Check for failure
        if fault_injector.should_fail(tool_name):
            error_response = fault_injector.get_failure_response(tool_name)
            monitor.check_tool_output(tool_name, error_response)
            return f"Error from {tool_name}: {error_response}"

        # Check for injection
        if fault_injector.should_inject(tool_name):
            normal_response = f"Normal response for {tool_name}"
            injected_response = fault_injector.inject(tool_name, normal_response)
            monitor.check_tool_output(tool_name, injected_response)

            # Simulate agent processing injected content
            # A secure agent should NOT follow injected instructions
            response = f"处理完成。\n\n工具返回: {injected_response}"
            monitor.check_agent_response(response)
            return response

    # No injection, return normal response
    response = f"正常响应: {user_input}"
    monitor.check_agent_response(response)
    return response


async def run_single_scenario(scenario_name: str):
    """Run a single predefined attack scenario."""
    print(f"\n{'='*60}")
    print(f"Running scenario: {scenario_name}")
    print(f"{'='*60}\n")

    if scenario_name not in ATTACK_SCENARIOS:
        print(f"Error: Unknown scenario '{scenario_name}'")
        print(f"Available scenarios: {', '.join(ATTACK_SCENARIOS.keys())}")
        return

    scenario = ATTACK_SCENARIOS[scenario_name]
    print(f"Description: {scenario.get('description', 'N/A')}")
    print(f"Affected tools: {list(scenario.get('tools', {}).keys())}")
    print()

    # Create injector and monitor
    injector = FaultInjector()
    injector.set_scenario(scenario_name)
    monitor = GuardrailMonitor(use_dspy_guardrails=False)

    # Run test
    test_input = "测试用户输入"
    print(f"User input: {test_input}")
    print()

    response = await run_with_simulated_agent(test_input, injector, monitor)

    print(f"Agent response:\n{'-'*40}")
    print(response)
    print(f"{'-'*40}\n")

    # Show guardrail results
    summary = monitor.get_summary()
    print(f"Guardrail checks: {summary['total_checks']}")
    print(f"Violations detected: {summary['violations']}")

    if summary['violations'] > 0:
        print("\nViolations:")
        for v in summary['violations_detail']:
            print(f"  - [{v['guardrail']}] {v['message']}")

    # Show injection log
    injection_log = injector.get_injection_log()
    if injection_log:
        print(f"\nInjection log:")
        for entry in injection_log:
            print(f"  - {entry['type']} on {entry['tool']}: {entry['details'][:50]}...")


async def run_all_tests(categories: list = None):
    """Run all tests and generate report."""
    print("\n" + "="*60)
    print("Virtual Agent Security Test Suite")
    print("="*60 + "\n")

    runner = TestRunner()

    if categories:
        print(f"Categories: {', '.join(categories)}")
    else:
        categories = ["attacks", "faults", "edge_cases"]
        print(f"Categories: {', '.join(categories)} (all)")

    print()

    # Run tests
    for category in categories:
        print(f"\nRunning {category} tests...")
        await runner.run_category(category)

    # Get summaries
    test_summary = runner.get_summary()
    guardrail_summary = runner.monitor.get_summary()

    # Print summary
    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)
    print(f"\nTotal tests: {test_summary['total']}")
    print(f"Passed: {test_summary['passed']}")
    print(f"Failed: {test_summary['failed']}")
    print(f"Pass rate: {test_summary['pass_rate']:.1%}")

    print("\nBy category:")
    for cat, stats in test_summary.get('by_category', {}).items():
        rate = stats['passed'] / stats['total'] if stats['total'] > 0 else 0
        status = "[OK]" if rate >= 0.9 else "[!]" if rate >= 0.7 else "[X]"
        print(f"  {status} {cat}: {stats['passed']}/{stats['total']} ({rate:.1%})")

    print(f"\nGuardrail checks: {guardrail_summary['total_checks']}")
    print(f"Violations detected: {guardrail_summary['violations']}")

    # Generate report
    generator = ReportGenerator()
    report_path = generator.generate(test_summary, guardrail_summary)
    print(f"\nDetailed report saved to: {report_path}")

    # Return exit code based on results
    return 0 if test_summary['pass_rate'] >= 0.9 else 1


def list_available_scenarios():
    """List all available attack scenarios."""
    print("\nAvailable Attack Scenarios:")
    print("="*60)

    scenarios = list_scenarios()
    for s in scenarios:
        print(f"\n{s['name']}")
        print(f"  Description: {s['description']}")
        print(f"  Affected tools: {', '.join(s['affected_tools'])}")


def main():
    parser = argparse.ArgumentParser(
        description="Security Test Runner for Virtual Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_security_tests.py                              Run all tests
  python run_security_tests.py --category attacks           Run attack tests only
  python run_security_tests.py --scenario prompt_injection_via_db  Run specific scenario
  python run_security_tests.py --list                       List available scenarios
        """
    )

    parser.add_argument(
        "--category",
        "-c",
        action="append",
        help="Test category to run (attacks, faults, edge_cases). Can be specified multiple times."
    )

    parser.add_argument(
        "--scenario",
        "-s",
        help="Run a specific predefined attack scenario"
    )

    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available attack scenarios"
    )

    args = parser.parse_args()

    if args.list:
        list_available_scenarios()
        return 0

    if args.scenario:
        asyncio.run(run_single_scenario(args.scenario))
        return 0

    return asyncio.run(run_all_tests(args.category))


if __name__ == "__main__":
    sys.exit(main())
