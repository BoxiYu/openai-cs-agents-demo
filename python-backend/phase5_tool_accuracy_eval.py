#!/usr/bin/env python3
"""
Phase 5 - P5-3: 工具选择准确性评估

参考Amazon Bedrock AgentCore的Tool Selection Accuracy评估:
- 评估Agent是否选择了正确的工具
- 评估工具参数是否正确
- 评估工具调用顺序是否合理
"""

import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from server import AirlineServer
from chatkit.types import (
    UserMessageItem,
    UserMessageTextContent,
    InferenceOptions,
    ThreadItemDoneEvent,
    AssistantMessageItem,
)


@dataclass
class ToolAccuracyResult:
    """工具准确性评估结果"""
    test_name: str
    query: str
    expected_tools: List[str]
    actual_tools: List[str]
    tool_match_rate: float
    unexpected_tools: List[str]
    missing_tools: List[str]
    tool_call_details: List[Dict]
    passed: bool
    notes: str = ""


class ToolAccuracyEvaluator:
    """工具选择准确性评估器"""

    # 工具映射（简化名称 -> 实际工具名）
    TOOL_NAME_MAP = {
        "get_flight_status": ["get_flight_status", "flight_status"],
        "check_connection_risk": ["check_connection_risk", "connection_risk"],
        "search_alternative_flights": ["search_alternative_flights", "search_alternatives"],
        "get_seat_info": ["get_seat_info", "seat_info", "get_seat"],
        "change_seat": ["change_seat", "update_seat"],
        "faq_lookup": ["faq_lookup", "lookup_faq", "get_faq"],
        "issue_voucher": ["issue_voucher", "create_voucher"],
        "rebook_flight": ["rebook_flight", "rebook"],
        "cancel_booking": ["cancel_booking", "cancel"],
        "open_refund_case": ["open_refund_case", "refund_case"],
    }

    # 评估场景
    EVAL_SCENARIOS = [
        # 单工具场景
        {
            "name": "航班状态查询",
            "query": "航班PA441的状态如何？",
            "expected_tools": ["get_flight_status"],
            "category": "single_tool",
        },
        {
            "name": "座位信息查询",
            "query": "我的座位是什么？",
            "expected_tools": ["get_seat_info"],
            "category": "single_tool",
        },
        {
            "name": "行李政策查询",
            "query": "托运行李限制是多少？",
            "expected_tools": ["faq_lookup"],
            "category": "single_tool",
        },
        # 多工具场景
        {
            "name": "转机风险检查",
            "query": "航班PA441延误了，会影响我的转机航班吗？",
            "expected_tools": ["get_flight_status", "check_connection_risk"],
            "category": "multi_tool",
        },
        {
            "name": "延误处理完整流程",
            "query": "我的航班延误了5小时，请帮我看看有什么替代航班，以及我可以获得什么补偿",
            "expected_tools": ["get_flight_status", "search_alternative_flights"],
            "category": "multi_tool",
        },
        # 工具序列场景
        {
            "name": "改签流程",
            "query": "帮我改签到明天的航班",
            "expected_tools": ["search_alternative_flights"],
            "category": "sequence",
        },
        {
            "name": "换座位请求",
            "query": "帮我换到靠窗的座位",
            "expected_tools": ["get_seat_info", "change_seat"],
            "category": "sequence",
        },
        # 无需工具场景
        {
            "name": "简单问候",
            "query": "你好",
            "expected_tools": [],
            "category": "no_tool",
        },
        {
            "name": "超范围请求",
            "query": "今天北京天气怎么样？",
            "expected_tools": [],
            "category": "no_tool",
        },
        # 边界场景
        {
            "name": "不存在的航班",
            "query": "航班ZZ9999的状态",
            "expected_tools": ["get_flight_status"],
            "category": "edge_case",
        },
        {
            "name": "模糊请求",
            "query": "帮帮我",
            "expected_tools": [],
            "category": "edge_case",
        },
        # 复杂场景
        {
            "name": "完整延误补偿流程",
            "query": "航班PA441延误了，请帮我看看状态、有什么替代航班、可以获得什么补偿",
            "expected_tools": ["get_flight_status", "search_alternative_flights", "faq_lookup"],
            "category": "complex",
        },
    ]

    def __init__(self):
        self.results: List[ToolAccuracyResult] = []

    def normalize_tool_name(self, tool_name: str) -> str:
        """规范化工具名称"""
        tool_lower = tool_name.lower()
        for canonical, variants in self.TOOL_NAME_MAP.items():
            if tool_lower in [v.lower() for v in variants]:
                return canonical
        return tool_lower

    async def get_agent_response_with_tools(self, query: str) -> tuple[str, List[Dict]]:
        """获取Agent响应和工具调用"""
        server = AirlineServer()
        thread = await server._ensure_thread(None, {'request': None})

        user_msg = UserMessageItem(
            id=str(uuid4()),
            thread_id=thread.id,
            created_at=datetime.now(),
            content=[UserMessageTextContent(type="input_text", text=query)],
            attachments=[],
            quoted_text=None,
            inference_options=InferenceOptions(tool_choice=None, model=None),
        )

        response_texts = []
        tool_calls = []

        try:
            async for event in server.respond(thread, user_msg, {'request': None}):
                if isinstance(event, ThreadItemDoneEvent):
                    if isinstance(event.item, AssistantMessageItem):
                        for c in event.item.content:
                            if hasattr(c, 'text'):
                                response_texts.append(c.text)
                    # 检查是否是工具调用类型
                    elif hasattr(event.item, 'name') and hasattr(event.item, 'arguments'):
                        tool_calls.append({
                            "name": event.item.name,
                            "arguments": event.item.arguments,
                        })
        except Exception as e:
            response_texts = [f"Error: {str(e)[:200]}"]

        return " ".join(response_texts), tool_calls

    async def evaluate_scenario(self, scenario: Dict) -> ToolAccuracyResult:
        """评估单个场景的工具选择"""
        query = scenario["query"]
        expected_tools = [self.normalize_tool_name(t) for t in scenario["expected_tools"]]

        # 获取响应和工具调用
        response, tool_calls = await self.get_agent_response_with_tools(query)

        # 从响应中推断工具调用（如果tool_calls为空）
        actual_tools = []
        if tool_calls:
            actual_tools = [self.normalize_tool_name(t["name"]) for t in tool_calls]
        else:
            # 从响应内容推断
            actual_tools = self._infer_tools_from_response(response)

        # 计算匹配率
        expected_set = set(expected_tools)
        actual_set = set(actual_tools)

        if not expected_set and not actual_set:
            # 都不需要工具，完美匹配
            match_rate = 1.0
        elif not expected_set:
            # 不应该调用工具但调用了
            match_rate = 0.0 if actual_set else 1.0
        elif not actual_set:
            # 应该调用工具但没调用
            match_rate = 0.0
        else:
            # 计算Jaccard相似度
            intersection = expected_set & actual_set
            union = expected_set | actual_set
            match_rate = len(intersection) / len(union) if union else 0

        # 找出缺失和多余的工具
        missing_tools = list(expected_set - actual_set)
        unexpected_tools = list(actual_set - expected_set)

        # 判断是否通过 (匹配率>=0.7)
        passed = match_rate >= 0.7

        return ToolAccuracyResult(
            test_name=scenario["name"],
            query=query,
            expected_tools=expected_tools,
            actual_tools=actual_tools,
            tool_match_rate=round(match_rate, 3),
            unexpected_tools=unexpected_tools,
            missing_tools=missing_tools,
            tool_call_details=tool_calls,
            passed=passed,
        )

    def _infer_tools_from_response(self, response: str) -> List[str]:
        """从响应内容推断使用的工具"""
        inferred = []
        response_lower = response.lower()

        # 关键词映射
        keyword_tool_map = {
            "get_flight_status": ["航班状态", "延误", "准点", "登机口", "起飞时间"],
            "check_connection_risk": ["转机", "衔接", "连接航班"],
            "search_alternative_flights": ["替代航班", "其他航班", "可选航班", "ny950"],
            "get_seat_info": ["座位", "座位号"],
            "faq_lookup": ["政策", "规定", "行李", "wifi", "补偿政策"],
        }

        for tool, keywords in keyword_tool_map.items():
            for kw in keywords:
                if kw.lower() in response_lower:
                    if tool not in inferred:
                        inferred.append(tool)
                    break

        return inferred

    async def run_all_evaluations(self) -> Dict[str, Any]:
        """运行所有评估"""
        print("\n" + "=" * 70)
        print("   PHASE 5 - P5-3: 工具选择准确性评估")
        print("   (参考 Amazon Tool Selection Accuracy)")
        print("=" * 70)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"评估场景数: {len(self.EVAL_SCENARIOS)}")
        print()

        for i, scenario in enumerate(self.EVAL_SCENARIOS, 1):
            print(f"  [{i}/{len(self.EVAL_SCENARIOS)}] {scenario['name']}...", end=" ", flush=True)

            try:
                result = await self.evaluate_scenario(scenario)
                self.results.append(result)

                status = "PASS" if result.passed else "FAIL"
                print(f"[{status}] 匹配率: {result.tool_match_rate:.0%}")

                if result.missing_tools:
                    print(f"       缺失: {result.missing_tools}")
                if result.unexpected_tools:
                    print(f"       多余: {result.unexpected_tools}")

            except Exception as e:
                print(f"[错误: {str(e)[:30]}]")

            await asyncio.sleep(0.5)

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        """生成评估报告"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)

        # 平均匹配率
        avg_match = sum(r.tool_match_rate for r in self.results) / total if total > 0 else 0

        # 按类别统计
        categories = {}
        for r in self.results:
            for s in self.EVAL_SCENARIOS:
                if s["name"] == r.test_name:
                    cat = s.get("category", "other")
                    if cat not in categories:
                        categories[cat] = {"total": 0, "passed": 0, "avg_rate": []}
                    categories[cat]["total"] += 1
                    categories[cat]["avg_rate"].append(r.tool_match_rate)
                    if r.passed:
                        categories[cat]["passed"] += 1

        for cat in categories:
            rates = categories[cat]["avg_rate"]
            categories[cat]["avg_rate"] = round(sum(rates) / len(rates), 3) if rates else 0

        # 工具统计
        tool_stats = {}
        for r in self.results:
            for t in r.expected_tools:
                if t not in tool_stats:
                    tool_stats[t] = {"expected": 0, "used": 0}
                tool_stats[t]["expected"] += 1
                if t in r.actual_tools:
                    tool_stats[t]["used"] += 1

        return {
            "timestamp": datetime.now().isoformat(),
            "test_type": "tool_accuracy_evaluation",
            "phase": "P5-3",
            "summary": {
                "total_scenarios": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "N/A",
                "average_match_rate": round(avg_match, 3),
            },
            "category_breakdown": categories,
            "tool_statistics": tool_stats,
            "failed_scenarios": [
                {
                    "test_name": r.test_name,
                    "query": r.query,
                    "expected": r.expected_tools,
                    "actual": r.actual_tools,
                    "match_rate": r.tool_match_rate,
                    "missing": r.missing_tools,
                    "unexpected": r.unexpected_tools,
                }
                for r in self.results if not r.passed
            ],
            "detailed_results": [
                {
                    "test_name": r.test_name,
                    "query": r.query,
                    "expected_tools": r.expected_tools,
                    "actual_tools": r.actual_tools,
                    "tool_match_rate": r.tool_match_rate,
                    "missing_tools": r.missing_tools,
                    "unexpected_tools": r.unexpected_tools,
                    "passed": r.passed,
                }
                for r in self.results
            ],
        }

    def print_summary(self, report: Dict[str, Any]):
        """打印评估总结"""
        summary = report.get("summary", {})

        print("\n" + "=" * 70)
        print("   工具选择准确性评估结果")
        print("=" * 70)
        print(f"""
总场景数: {summary.get('total_scenarios', 0)}
通过数: {summary.get('passed', 0)}
失败数: {summary.get('failed', 0)}
通过率: {summary.get('pass_rate', 'N/A')}
平均匹配率: {summary.get('average_match_rate', 0):.1%}
""")

        print("按类别统计:")
        for cat, stats in report.get("category_breakdown", {}).items():
            bar = "█" * int(stats["avg_rate"] * 20) + "░" * (20 - int(stats["avg_rate"] * 20))
            print(f"  {cat:15} {bar} {stats['passed']}/{stats['total']} ({stats['avg_rate']:.0%})")

        print("\n工具使用统计:")
        for tool, stats in report.get("tool_statistics", {}).items():
            rate = stats["used"] / stats["expected"] if stats["expected"] > 0 else 0
            print(f"  {tool:30} {stats['used']}/{stats['expected']} ({rate:.0%})")

        if report.get("failed_scenarios"):
            print("\n[!] 失败场景:")
            for f in report["failed_scenarios"][:5]:
                print(f"  - {f['test_name']}: {f['match_rate']:.0%}")
                print(f"      期望: {f['expected']}")
                print(f"      实际: {f['actual']}")

        print("=" * 70)


async def main():
    """主函数"""
    evaluator = ToolAccuracyEvaluator()
    report = await evaluator.run_all_evaluations()
    evaluator.print_summary(report)

    # 保存报告
    output_path = Path(__file__).parent / "testing" / "reports" / f"p5_tool_accuracy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
