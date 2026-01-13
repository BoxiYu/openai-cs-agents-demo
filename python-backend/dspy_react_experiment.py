"""
DSPy ReAct Agent 实验
对比 DSPy ReAct 与 OpenAI Agents SDK 的效果

目标：
1. 用 DSPy ReAct 实现航空客服 Agent
2. 用 MIPROv2 优化
3. 对比优化前后效果
"""

import os
import json
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import dspy

# ============================================================
# 配置 DSPy
# ============================================================

def setup_dspy():
    """配置 DSPy 使用 Kimi K2 模型"""
    lm = dspy.LM(
        model="openai/kimi-k2-0905-preview",
        api_base=os.environ.get('OPENAI_BASE_URL', 'https://api.moonshot.cn/v1'),
        api_key=os.environ.get('OPENAI_API_KEY'),
        max_tokens=4096,
    )
    dspy.configure(lm=lm)
    return lm


# ============================================================
# 模拟数据 (与 demo_data.py 一致)
# ============================================================

MOCK_FLIGHTS = {
    "PA441": {
        "flight_number": "PA441",
        "origin": "Paris (CDG)",
        "destination": "New York (JFK)",
        "status": "Delayed 3 hours",
        "departure": "10:00",
        "arrival": "14:00 (delayed to 17:00)",
        "gate": "B22",
    },
    "NY802": {
        "flight_number": "NY802",
        "origin": "New York (JFK)",
        "destination": "Austin (AUS)",
        "status": "Will be missed due to PA441 delay",
        "departure": "15:30",
        "arrival": "19:00",
        "gate": "C15",
    },
    "NY950": {
        "flight_number": "NY950",
        "origin": "New York (JFK)",
        "destination": "Austin (AUS)",
        "status": "Available for rebooking",
        "departure": "20:00",
        "arrival": "23:30",
        "seat": "12A",
    },
}

MOCK_FAQ = {
    "baggage": "You are allowed one carry-on and one checked bag (up to 50 lbs). Overweight fee is $75.",
    "compensation": "For delays over 3 hours, we provide hotel and meal vouchers. A compensation case will be opened.",
    "wifi": "Free wifi available on all flights. Join 'Airline-Wifi' network.",
    "seats": "120 seats total: 22 business class, 98 economy. Exit rows: 4 and 16. Economy Plus: rows 5-8.",
}


# ============================================================
# DSPy Tools (同步版本，不需要 context)
# ============================================================

def flight_status(flight_number: str) -> str:
    """
    查询航班状态

    Args:
        flight_number: 航班号，如 PA441, NY802

    Returns:
        航班状态信息
    """
    flight = MOCK_FLIGHTS.get(flight_number.upper())
    if flight:
        return (
            f"Flight {flight['flight_number']}: {flight['origin']} → {flight['destination']} | "
            f"Status: {flight['status']} | Gate: {flight.get('gate', 'TBD')} | "
            f"Departure: {flight['departure']} | Arrival: {flight['arrival']}"
        )
    return f"Flight {flight_number} not found in system."


def get_alternative_flights(origin: str, destination: str) -> str:
    """
    查找替代航班

    Args:
        origin: 出发地，如 "New York"
        destination: 目的地，如 "Austin"

    Returns:
        可用的替代航班列表
    """
    alternatives = []
    for flight in MOCK_FLIGHTS.values():
        if (origin.lower() in flight["origin"].lower() and
            destination.lower() in flight["destination"].lower() and
            "rebooking" in flight["status"].lower()):
            alternatives.append(
                f"{flight['flight_number']}: {flight['departure']} → {flight['arrival']} | Seat: {flight.get('seat', 'auto-assign')}"
            )

    if alternatives:
        return "Available alternatives:\n" + "\n".join(alternatives)
    return "No alternative flights available for this route."


def book_flight(flight_number: str, passenger_name: str = "Customer") -> str:
    """
    预订航班

    Args:
        flight_number: 要预订的航班号
        passenger_name: 乘客姓名

    Returns:
        预订确认信息
    """
    flight = MOCK_FLIGHTS.get(flight_number.upper())
    if flight and "rebooking" in flight.get("status", "").lower():
        import random
        import string
        confirmation = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return (
            f"Successfully booked {flight_number} for {passenger_name}. "
            f"Confirmation: {confirmation}. Seat: {flight.get('seat', 'auto-assign')}. "
            f"Departure: {flight['departure']} from {flight['origin']}."
        )
    return f"Unable to book flight {flight_number}. It may not be available for booking."


def cancel_flight(confirmation_number: str) -> str:
    """
    取消航班预订

    Args:
        confirmation_number: 预订确认号

    Returns:
        取消确认信息
    """
    return f"Flight with confirmation {confirmation_number} has been cancelled. Refund will be processed within 5-7 business days."


def update_seat(confirmation_number: str, new_seat: str) -> str:
    """
    更新座位

    Args:
        confirmation_number: 预订确认号
        new_seat: 新座位号，如 "12A"

    Returns:
        座位更新确认
    """
    return f"Seat updated to {new_seat} for confirmation {confirmation_number}."


def faq_lookup(question: str) -> str:
    """
    查询常见问题

    Args:
        question: 用户问题

    Returns:
        FAQ 答案
    """
    q = question.lower()
    if "bag" in q or "luggage" in q:
        return MOCK_FAQ["baggage"]
    elif "compensation" in q or "delay" in q or "voucher" in q:
        return MOCK_FAQ["compensation"]
    elif "wifi" in q or "internet" in q:
        return MOCK_FAQ["wifi"]
    elif "seat" in q or "plane" in q:
        return MOCK_FAQ["seats"]
    return "I don't have specific information about that. Please ask about baggage, compensation, wifi, or seating."


def issue_compensation(reason: str, confirmation_number: str = "UNKNOWN") -> str:
    """
    发放补偿

    Args:
        reason: 补偿原因
        confirmation_number: 预订确认号

    Returns:
        补偿案例信息
    """
    import random
    case_id = f"CMP-{random.randint(1000, 9999)}"
    return (
        f"Compensation case {case_id} opened for: {reason}. "
        f"Confirmation: {confirmation_number}. "
        f"Issued: Hotel voucher ($150), Meal voucher ($50). "
        f"Please keep receipts for reimbursement."
    )


# ============================================================
# DSPy ReAct Agent
# ============================================================

class AirlineServiceSignature(dspy.Signature):
    """An airline customer service agent that helps users with flight bookings,
    status inquiries, seat changes, and compensation requests.

    You should:
    1. Understand the customer's request
    2. Use appropriate tools to help them
    3. Provide clear, helpful responses
    """

    user_request: str = dspy.InputField(desc="The customer's request or question")
    response: str = dspy.OutputField(desc="Your helpful response to the customer")


def create_react_agent():
    """创建 DSPy ReAct Agent"""
    tools = [
        flight_status,
        get_alternative_flights,
        book_flight,
        cancel_flight,
        update_seat,
        faq_lookup,
        issue_compensation,
    ]

    react_agent = dspy.ReAct(
        signature=AirlineServiceSignature,
        tools=tools,
        max_iters=10,
    )

    return react_agent


# ============================================================
# 测试数据集
# ============================================================

TEST_CASES = [
    # 简单查询
    {
        "request": "What's the status of flight PA441?",
        "expected_tools": ["flight_status"],
        "expected_keywords": ["delayed", "PA441"],
        "category": "simple_query",
    },
    {
        "request": "What's your baggage policy?",
        "expected_tools": ["faq_lookup"],
        "expected_keywords": ["50 lbs", "carry-on"],
        "category": "simple_query",
    },

    # 中等复杂度
    {
        "request": "My flight PA441 is delayed. Will I miss my connection NY802?",
        "expected_tools": ["flight_status"],
        "expected_keywords": ["delayed", "missed", "connection"],
        "category": "medium",
    },
    {
        "request": "I need to rebook from New York to Austin because of the delay.",
        "expected_tools": ["get_alternative_flights", "book_flight"],
        "expected_keywords": ["NY950", "booked", "confirmation"],
        "category": "medium",
    },

    # 复杂场景
    {
        "request": "My flight PA441 from Paris is delayed and I'll miss my connection. Can you help me rebook and also arrange compensation for the delay?",
        "expected_tools": ["flight_status", "get_alternative_flights", "book_flight", "issue_compensation"],
        "expected_keywords": ["rebooked", "compensation", "voucher"],
        "category": "complex",
    },
    {
        "request": "I want to change my seat to an exit row and also understand the wifi policy.",
        "expected_tools": ["update_seat", "faq_lookup"],
        "expected_keywords": ["seat", "wifi"],
        "category": "complex",
    },

    # 边缘情况
    {
        "request": "What's the status of flight XYZ999?",
        "expected_tools": ["flight_status"],
        "expected_keywords": ["not found"],
        "category": "edge_case",
    },
    {
        "request": "Cancel my booking ABC123",
        "expected_tools": ["cancel_flight"],
        "expected_keywords": ["cancelled", "refund"],
        "category": "edge_case",
    },
]


# ============================================================
# 评估指标
# ============================================================

@dataclass
class EvalResult:
    """单个测试结果"""
    request: str
    response: str
    trajectory: list
    tools_used: list[str]
    expected_tools: list[str]
    keywords_found: list[str]
    expected_keywords: list[str]
    tool_match_score: float
    keyword_match_score: float
    latency_ms: float
    success: bool
    category: str


def evaluate_response(
    request: str,
    response: str,
    trajectory: any,
    expected_tools: list[str],
    expected_keywords: list[str],
    category: str,
    latency_ms: float,
) -> EvalResult:
    """评估单个响应"""

    # 提取使用的工具 (DSPy ReAct trajectory 是 dict 格式)
    tools_used = []
    if isinstance(trajectory, dict):
        # DSPy ReAct 格式: {'tool_name_0': 'flight_status', 'tool_name_1': 'finish', ...}
        for key, value in trajectory.items():
            if key.startswith('tool_name_') and value and value != 'finish':
                tools_used.append(value)
    elif isinstance(trajectory, (list, tuple)):
        for step in trajectory:
            if hasattr(step, 'tool') and step.tool:
                tools_used.append(step.tool)
            elif isinstance(step, dict) and 'tool' in step:
                tools_used.append(step['tool'])

    # 工具匹配分数
    if expected_tools:
        tool_matches = sum(1 for t in expected_tools if any(t in used for used in tools_used))
        tool_match_score = tool_matches / len(expected_tools)
    else:
        tool_match_score = 1.0

    # 关键词匹配分数
    response_lower = response.lower()
    keywords_found = [kw for kw in expected_keywords if kw.lower() in response_lower]
    keyword_match_score = len(keywords_found) / len(expected_keywords) if expected_keywords else 1.0

    # 综合成功判断
    success = tool_match_score >= 0.5 and keyword_match_score >= 0.5

    return EvalResult(
        request=request,
        response=response,
        trajectory=trajectory,
        tools_used=tools_used,
        expected_tools=expected_tools,
        keywords_found=keywords_found,
        expected_keywords=expected_keywords,
        tool_match_score=tool_match_score,
        keyword_match_score=keyword_match_score,
        latency_ms=latency_ms,
        success=success,
        category=category,
    )


def task_success_metric(example, prediction, trace=None) -> float:
    """DSPy 优化用的 metric 函数"""
    response = prediction.response if hasattr(prediction, 'response') else str(prediction)

    # 基础分数：响应长度合理
    if len(response) < 20:
        return 0.0

    score = 0.5  # 基础分

    # 检查是否包含有用信息
    useful_patterns = [
        "flight", "booked", "confirmed", "cancelled", "seat",
        "voucher", "compensation", "delayed", "status",
    ]
    matches = sum(1 for p in useful_patterns if p in response.lower())
    score += min(0.3, matches * 0.05)

    # 检查是否有具体数据
    if any(char.isdigit() for char in response):
        score += 0.1

    # 检查是否有确认号或航班号格式
    import re
    if re.search(r'[A-Z]{2,3}\d{3}|[A-Z0-9]{6}', response):
        score += 0.1

    return min(1.0, score)


# ============================================================
# 实验运行
# ============================================================

def run_baseline_evaluation(agent, test_cases: list[dict]) -> list[EvalResult]:
    """运行基线评估"""
    results = []

    for i, case in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] Testing: {case['request'][:50]}...")

        start_time = time.time()
        try:
            prediction = agent(user_request=case["request"])
            latency_ms = (time.time() - start_time) * 1000

            response = prediction.response if hasattr(prediction, 'response') else str(prediction)
            trajectory = prediction.trajectory if hasattr(prediction, 'trajectory') else []

            result = evaluate_response(
                request=case["request"],
                response=response,
                trajectory=trajectory,
                expected_tools=case["expected_tools"],
                expected_keywords=case["expected_keywords"],
                category=case["category"],
                latency_ms=latency_ms,
            )
            results.append(result)

            status = "✓" if result.success else "✗"
            print(f"  {status} Tool score: {result.tool_match_score:.2f}, Keyword score: {result.keyword_match_score:.2f}")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append(EvalResult(
                request=case["request"],
                response=f"Error: {e}",
                trajectory=[],
                tools_used=[],
                expected_tools=case["expected_tools"],
                keywords_found=[],
                expected_keywords=case["expected_keywords"],
                tool_match_score=0.0,
                keyword_match_score=0.0,
                latency_ms=0.0,
                success=False,
                category=case["category"],
            ))

    return results


def run_optimization(agent, trainset: list) -> dspy.Module:
    """运行 MIPROv2 优化"""
    print("\n" + "="*60)
    print("Starting MIPROv2 Optimization...")
    print("="*60)

    # 创建训练数据
    train_examples = []
    for case in trainset:
        example = dspy.Example(
            user_request=case["request"],
        ).with_inputs("user_request")
        train_examples.append(example)

    # MIPROv2 优化器
    optimizer = dspy.MIPROv2(
        metric=task_success_metric,
        auto="light",  # light mode 更快
        num_threads=1,  # 避免 rate limiting
    )

    # 运行优化
    optimized_agent = optimizer.compile(
        agent,
        trainset=train_examples,
        requires_permission_to_run=False,
    )

    return optimized_agent


def generate_report(baseline_results: list[EvalResult], optimized_results: list[EvalResult] = None) -> str:
    """生成评估报告"""

    def calc_stats(results: list[EvalResult]) -> dict:
        if not results:
            return {}

        success_rate = sum(1 for r in results if r.success) / len(results)
        avg_tool_score = sum(r.tool_match_score for r in results) / len(results)
        avg_keyword_score = sum(r.keyword_match_score for r in results) / len(results)
        avg_latency = sum(r.latency_ms for r in results) / len(results)

        # 按类别统计
        by_category = {}
        for r in results:
            if r.category not in by_category:
                by_category[r.category] = []
            by_category[r.category].append(r)

        category_stats = {}
        for cat, cat_results in by_category.items():
            category_stats[cat] = {
                "success_rate": sum(1 for r in cat_results if r.success) / len(cat_results),
                "count": len(cat_results),
            }

        return {
            "success_rate": success_rate,
            "avg_tool_score": avg_tool_score,
            "avg_keyword_score": avg_keyword_score,
            "avg_latency_ms": avg_latency,
            "by_category": category_stats,
        }

    baseline_stats = calc_stats(baseline_results)

    report = []
    report.append("=" * 60)
    report.append("DSPy ReAct Agent 评估报告")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 60)

    report.append("\n## Baseline 结果\n")
    report.append(f"- 成功率: {baseline_stats['success_rate']:.2%}")
    report.append(f"- 平均工具匹配: {baseline_stats['avg_tool_score']:.2%}")
    report.append(f"- 平均关键词匹配: {baseline_stats['avg_keyword_score']:.2%}")
    report.append(f"- 平均延迟: {baseline_stats['avg_latency_ms']:.0f}ms")

    report.append("\n### 按类别:\n")
    for cat, stats in baseline_stats.get("by_category", {}).items():
        report.append(f"- {cat}: {stats['success_rate']:.2%} ({stats['count']} cases)")

    if optimized_results:
        optimized_stats = calc_stats(optimized_results)

        report.append("\n## Optimized 结果\n")
        report.append(f"- 成功率: {optimized_stats['success_rate']:.2%}")
        report.append(f"- 平均工具匹配: {optimized_stats['avg_tool_score']:.2%}")
        report.append(f"- 平均关键词匹配: {optimized_stats['avg_keyword_score']:.2%}")
        report.append(f"- 平均延迟: {optimized_stats['avg_latency_ms']:.0f}ms")

        report.append("\n### 按类别:\n")
        for cat, stats in optimized_stats.get("by_category", {}).items():
            report.append(f"- {cat}: {stats['success_rate']:.2%} ({stats['count']} cases)")

        report.append("\n## 对比\n")
        improvement = optimized_stats['success_rate'] - baseline_stats['success_rate']
        report.append(f"- 成功率变化: {improvement:+.2%}")
        report.append(f"- 工具匹配变化: {optimized_stats['avg_tool_score'] - baseline_stats['avg_tool_score']:+.2%}")
        report.append(f"- 关键词匹配变化: {optimized_stats['avg_keyword_score'] - baseline_stats['avg_keyword_score']:+.2%}")

    report.append("\n## 详细结果\n")
    for i, r in enumerate(baseline_results):
        status = "✓" if r.success else "✗"
        report.append(f"\n### Case {i+1}: {r.category}")
        report.append(f"**Request:** {r.request}")
        report.append(f"**Status:** {status}")
        report.append(f"**Tools used:** {r.tools_used}")
        report.append(f"**Response:** {r.response[:200]}...")

    return "\n".join(report)


# ============================================================
# 主函数
# ============================================================

def main():
    """运行完整实验"""
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 60)
    print("DSPy ReAct Agent Experiment")
    print("=" * 60)

    # 1. 配置 DSPy
    print("\n[1/4] Configuring DSPy...")
    setup_dspy()

    # 2. 创建 Agent
    print("\n[2/4] Creating ReAct Agent...")
    agent = create_react_agent()

    # 3. 运行 Baseline 评估
    print("\n[3/4] Running Baseline Evaluation...")
    baseline_results = run_baseline_evaluation(agent, TEST_CASES)

    # 4. 生成报告
    print("\n[4/4] Generating Report...")
    report = generate_report(baseline_results)
    print(report)

    # 保存报告
    report_path = f"testing/reports/dspy_react_experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n报告已保存到: {report_path}")

    # 询问是否运行优化
    print("\n" + "=" * 60)
    print("Baseline 评估完成。")
    print("运行 MIPROv2 优化需要更多时间和 API 调用。")
    print("=" * 60)

    return baseline_results


def run_with_optimization():
    """运行完整实验（包含优化）"""
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 60)
    print("DSPy ReAct Agent Experiment (with Optimization)")
    print("=" * 60)

    # 配置
    setup_dspy()

    # 创建 Agent
    agent = create_react_agent()

    # Baseline 评估
    print("\n[1/3] Running Baseline Evaluation...")
    baseline_results = run_baseline_evaluation(agent, TEST_CASES)

    # 优化
    print("\n[2/3] Running Optimization...")
    optimized_agent = run_optimization(agent, TEST_CASES[:5])  # 用前5个作为训练集

    # Optimized 评估
    print("\n[3/3] Running Optimized Evaluation...")
    optimized_results = run_baseline_evaluation(optimized_agent, TEST_CASES)

    # 报告
    report = generate_report(baseline_results, optimized_results)
    print(report)

    # 保存
    report_path = f"testing/reports/dspy_react_optimized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n报告已保存到: {report_path}")

    return baseline_results, optimized_results


if __name__ == "__main__":
    # 默认只运行 baseline
    # 如果要运行优化，使用 run_with_optimization()
    main()
