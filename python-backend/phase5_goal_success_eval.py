#!/usr/bin/env python3
"""
Phase 5 - P5-2: 目标完成率评估

参考Amazon Bedrock AgentCore的Goal Success Rate评估:
- 定义明确的用户目标
- 评估Agent是否成功完成目标
- 衡量任务完成的完整性
"""

import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from dataclasses import dataclass
from typing import List, Dict, Any
from openai import OpenAI

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
class GoalResult:
    """目标完成评估结果"""
    goal_name: str
    goal_description: str
    user_queries: List[str]
    agent_responses: List[str]
    success_criteria: List[str]
    criteria_met: List[bool]
    goal_achieved: bool
    completion_rate: float
    notes: str = ""


class GoalSuccessEvaluator:
    """目标完成率评估器"""

    # 用户目标场景
    GOAL_SCENARIOS = [
        # 信息获取目标
        {
            "name": "获取航班延误信息",
            "description": "用户想了解航班PA441的延误详情",
            "queries": [
                "航班PA441的状态如何？",
            ],
            "success_criteria": [
                "提供航班当前状态（延误/准点）",
                "说明延误原因",
                "提供预计起飞/到达时间",
            ],
            "category": "info_retrieval",
        },
        {
            "name": "了解转机风险",
            "description": "用户想知道延误是否影响转机",
            "queries": [
                "我的航班PA441延误了，会影响转机吗？",
            ],
            "success_criteria": [
                "确认是否会影响转机",
                "提供转机航班信息",
                "给出建议（改签或等待）",
            ],
            "category": "info_retrieval",
        },
        # 操作执行目标
        {
            "name": "查看替代航班",
            "description": "用户想查看可选的替代航班",
            "queries": [
                "有什么替代航班可以选择？",
            ],
            "success_criteria": [
                "提供至少一个替代航班选项",
                "包含航班号",
                "包含时间信息",
            ],
            "category": "action",
        },
        {
            "name": "查询座位信息",
            "description": "用户想了解当前座位",
            "queries": [
                "我现在的座位是什么？",
            ],
            "success_criteria": [
                "提供座位号",
                "说明座位位置（靠窗/过道）",
            ],
            "category": "action",
        },
        # 多步骤目标
        {
            "name": "完整延误处理流程",
            "description": "用户需要处理航班延误的完整流程",
            "queries": [
                "航班PA441延误了，请帮我处理",
                "有什么替代航班？",
                "我可以获得什么补偿？",
            ],
            "success_criteria": [
                "确认延误状态",
                "提供替代航班选项",
                "说明补偿政策",
                "提供下一步行动建议",
            ],
            "category": "multi_step",
        },
        # FAQ目标
        {
            "name": "了解行李政策",
            "description": "用户想了解行李限制",
            "queries": [
                "行李限制是多少？托运和手提各是多少？",
            ],
            "success_criteria": [
                "提供托运行李限制",
                "提供手提行李限制",
                "说明超重费用（如适用）",
            ],
            "category": "faq",
        },
        {
            "name": "了解WiFi服务",
            "description": "用户想了解航班WiFi",
            "queries": [
                "航班上有WiFi吗？怎么使用？",
            ],
            "success_criteria": [
                "确认WiFi是否可用",
                "说明使用方法或收费",
            ],
            "category": "faq",
        },
        # 边界目标
        {
            "name": "处理不存在的航班",
            "description": "用户查询不存在的航班",
            "queries": [
                "航班ZZ9999的状态如何？",
            ],
            "success_criteria": [
                "明确告知找不到该航班",
                "不编造虚假信息",
            ],
            "category": "edge_case",
        },
        {
            "name": "拒绝超范围请求",
            "description": "用户请求超出服务范围",
            "queries": [
                "帮我订一家酒店",
            ],
            "success_criteria": [
                "礼貌拒绝",
                "说明服务范围",
                "不尝试执行无关操作",
            ],
            "category": "edge_case",
        },
        # 复杂目标
        {
            "name": "完整改签流程",
            "description": "用户需要改签到其他航班",
            "queries": [
                "我想改签到明天的航班",
                "有哪些航班可选？",
            ],
            "success_criteria": [
                "理解改签意图",
                "提供可选航班列表",
                "说明改签流程或费用",
                "提供确认信息",
            ],
            "category": "multi_step",
        },
    ]

    def __init__(self):
        self.results: List[GoalResult] = []
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        self.judge_model = os.getenv("JUDGE_MODEL", "kimi-k2-0905-preview")

    async def get_agent_response(self, query: str, server: AirlineServer, thread) -> str:
        """获取Agent响应"""
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
        try:
            async for event in server.respond(thread, user_msg, {'request': None}):
                if isinstance(event, ThreadItemDoneEvent):
                    if isinstance(event.item, AssistantMessageItem):
                        for c in event.item.content:
                            if hasattr(c, 'text'):
                                response_texts.append(c.text)
        except Exception as e:
            response_texts = [f"Error: {str(e)[:200]}"]

        return " ".join(response_texts)

    def evaluate_criteria(self, responses: List[str], criteria: List[str]) -> List[bool]:
        """使用LLM评估各标准是否满足"""
        combined_response = "\n\n".join(responses)

        prompt = f"""请评估以下Agent响应是否满足各项成功标准。

## Agent响应
{combined_response}

## 成功标准
{json.dumps(criteria, ensure_ascii=False, indent=2)}

## 评估要求
对每个标准，判断Agent响应是否满足。输出JSON数组，每个元素为true或false。

示例输出：
[true, false, true]

请直接输出JSON数组："""

        try:
            completion = self.client.chat.completions.create(
                model=self.judge_model,
                messages=[
                    {"role": "system", "content": "你是一个客观的评估专家。请严格按照要求输出JSON数组。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200,
            )

            result_text = completion.choices[0].message.content.strip()

            # 提取JSON数组
            import re
            json_match = re.search(r'\[[\s\S]*?\]', result_text)
            if json_match:
                result = json.loads(json_match.group())
                # 确保长度匹配
                while len(result) < len(criteria):
                    result.append(False)
                return result[:len(criteria)]
            else:
                return [False] * len(criteria)

        except Exception as e:
            print(f"Criteria evaluation error: {e}")
            return [False] * len(criteria)

    async def evaluate_goal(self, scenario: Dict) -> GoalResult:
        """评估单个目标"""
        server = AirlineServer()
        thread = await server._ensure_thread(None, {'request': None})

        # 执行所有查询
        responses = []
        for query in scenario["queries"]:
            response = await self.get_agent_response(query, server, thread)
            responses.append(response)
            await asyncio.sleep(0.3)

        # 评估各标准
        criteria = scenario["success_criteria"]
        criteria_met = self.evaluate_criteria(responses, criteria)

        # 计算完成率
        met_count = sum(1 for m in criteria_met if m)
        completion_rate = met_count / len(criteria) if criteria else 0

        # 判断目标是否达成 (80%以上标准满足)
        goal_achieved = completion_rate >= 0.8

        return GoalResult(
            goal_name=scenario["name"],
            goal_description=scenario["description"],
            user_queries=scenario["queries"],
            agent_responses=[r[:300] for r in responses],
            success_criteria=criteria,
            criteria_met=criteria_met,
            goal_achieved=goal_achieved,
            completion_rate=round(completion_rate, 3),
        )

    async def run_all_evaluations(self) -> Dict[str, Any]:
        """运行所有评估"""
        print("\n" + "=" * 70)
        print("   PHASE 5 - P5-2: 目标完成率评估")
        print("   (参考 Amazon Goal Success Rate)")
        print("=" * 70)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"评估目标数: {len(self.GOAL_SCENARIOS)}")
        print()

        for i, scenario in enumerate(self.GOAL_SCENARIOS, 1):
            print(f"  [{i}/{len(self.GOAL_SCENARIOS)}] {scenario['name']}...", end=" ", flush=True)

            try:
                result = await self.evaluate_goal(scenario)
                self.results.append(result)

                status = "达成" if result.goal_achieved else "未达成"
                met = sum(1 for m in result.criteria_met if m)
                total = len(result.criteria_met)
                print(f"[{status}] {met}/{total} 标准 ({result.completion_rate:.0%})")

            except Exception as e:
                print(f"[错误: {str(e)[:30]}]")

            await asyncio.sleep(0.5)

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        """生成评估报告"""
        total = len(self.results)
        achieved = sum(1 for r in self.results if r.goal_achieved)

        # 平均完成率
        avg_completion = sum(r.completion_rate for r in self.results) / total if total > 0 else 0

        # 按类别统计
        categories = {}
        for r in self.results:
            for s in self.GOAL_SCENARIOS:
                if s["name"] == r.goal_name:
                    cat = s.get("category", "other")
                    if cat not in categories:
                        categories[cat] = {"total": 0, "achieved": 0, "avg_rate": []}
                    categories[cat]["total"] += 1
                    categories[cat]["avg_rate"].append(r.completion_rate)
                    if r.goal_achieved:
                        categories[cat]["achieved"] += 1

        for cat in categories:
            rates = categories[cat]["avg_rate"]
            categories[cat]["avg_rate"] = round(sum(rates) / len(rates), 3) if rates else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "test_type": "goal_success_evaluation",
            "phase": "P5-2",
            "summary": {
                "total_goals": total,
                "achieved": achieved,
                "not_achieved": total - achieved,
                "success_rate": f"{(achieved / total * 100):.1f}%" if total > 0 else "N/A",
                "average_completion": round(avg_completion, 3),
            },
            "category_breakdown": categories,
            "failed_goals": [
                {
                    "goal_name": r.goal_name,
                    "description": r.goal_description,
                    "completion_rate": r.completion_rate,
                    "criteria_status": list(zip(r.success_criteria, r.criteria_met)),
                }
                for r in self.results if not r.goal_achieved
            ],
            "detailed_results": [
                {
                    "goal_name": r.goal_name,
                    "description": r.goal_description,
                    "queries": r.user_queries,
                    "responses": r.agent_responses,
                    "success_criteria": r.success_criteria,
                    "criteria_met": r.criteria_met,
                    "goal_achieved": r.goal_achieved,
                    "completion_rate": r.completion_rate,
                }
                for r in self.results
            ],
        }

    def print_summary(self, report: Dict[str, Any]):
        """打印评估总结"""
        summary = report.get("summary", {})

        print("\n" + "=" * 70)
        print("   目标完成率评估结果")
        print("=" * 70)
        print(f"""
总目标数: {summary.get('total_goals', 0)}
达成目标: {summary.get('achieved', 0)}
未达成: {summary.get('not_achieved', 0)}
成功率: {summary.get('success_rate', 'N/A')}
平均完成度: {summary.get('average_completion', 0):.1%}
""")

        print("按类别统计:")
        for cat, stats in report.get("category_breakdown", {}).items():
            bar = "█" * int(stats["avg_rate"] * 20) + "░" * (20 - int(stats["avg_rate"] * 20))
            print(f"  {cat:15} {bar} {stats['achieved']}/{stats['total']} ({stats['avg_rate']:.0%})")

        if report.get("failed_goals"):
            print("\n[!] 未达成目标:")
            for g in report["failed_goals"][:5]:
                print(f"  - {g['goal_name']}: {g['completion_rate']:.0%}")
                for crit, met in g["criteria_status"]:
                    status = "✓" if met else "✗"
                    print(f"      [{status}] {crit[:40]}")

        print("=" * 70)


async def main():
    """主函数"""
    evaluator = GoalSuccessEvaluator()
    report = await evaluator.run_all_evaluations()
    evaluator.print_summary(report)

    # 保存报告
    output_path = Path(__file__).parent / "testing" / "reports" / f"p5_goal_success_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
