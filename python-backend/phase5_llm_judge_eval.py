#!/usr/bin/env python3
"""
Phase 5 - P5-1: LLM-as-Judge 质量评估

参考Amazon Bedrock AgentCore Evaluations方法论:
- Correctness: 回答的准确性
- Faithfulness: 忠实度，避免幻觉
- Helpfulness: 有用性
- Harmfulness: 有害性检测
- Context Relevance: 上下文相关性
"""

import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
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
class LLMJudgeResult:
    """LLM-as-Judge评估结果"""
    test_name: str
    query: str
    response: str
    ground_truth: Optional[str]
    scores: Dict[str, float]  # 各维度得分 0-1
    explanations: Dict[str, str]  # 各维度评分理由
    overall_score: float
    passed: bool


class LLMJudgeEvaluator:
    """LLM-as-Judge评估器 (参考Amazon方法)"""

    # 评估场景
    EVAL_SCENARIOS = [
        # 航班查询准确性
        {
            "name": "航班状态查询",
            "query": "航班PA441的状态如何？",
            "ground_truth": "PA441延误5小时，原因是天气，登机口B18",
            "expected_tools": ["get_flight_status"],
            "category": "flight_info",
        },
        {
            "name": "转机风险查询",
            "query": "我的航班PA441延误了，会影响我的转机航班NY802吗？",
            "ground_truth": "会影响转机，建议改签到NY950",
            "expected_tools": ["get_flight_status", "check_connection_risk"],
            "category": "connection",
        },
        # 预订操作准确性
        {
            "name": "座位查询",
            "query": "帮我看看我现在的座位是什么？",
            "ground_truth": "当前座位信息",
            "expected_tools": ["get_seat_info"],
            "category": "seat",
        },
        {
            "name": "替代航班查询",
            "query": "有什么替代航班可以选择？",
            "ground_truth": "NY950等替代航班选项",
            "expected_tools": ["search_alternative_flights"],
            "category": "alternatives",
        },
        # FAQ准确性
        {
            "name": "行李政策查询",
            "query": "你们的行李限制是多少？",
            "ground_truth": "经济舱23kg，商务舱32kg等政策",
            "expected_tools": ["faq_lookup"],
            "category": "faq",
        },
        {
            "name": "WiFi服务查询",
            "query": "航班上有WiFi吗？怎么收费？",
            "ground_truth": "WiFi可用，收费标准",
            "expected_tools": ["faq_lookup"],
            "category": "faq",
        },
        # 复杂多步骤任务
        {
            "name": "延误补偿咨询",
            "query": "我的航班延误了5小时，可以获得什么补偿？",
            "ground_truth": "延误补偿政策，餐食/酒店代金券",
            "expected_tools": ["faq_lookup", "issue_voucher"],
            "category": "compensation",
        },
        {
            "name": "改签请求",
            "query": "帮我改签到明天的航班",
            "ground_truth": "改签流程和可选航班",
            "expected_tools": ["search_alternative_flights", "rebook_flight"],
            "category": "rebooking",
        },
        # 边界情况
        {
            "name": "不存在航班查询",
            "query": "航班ZZ9999的状态如何？",
            "ground_truth": "无法找到该航班",
            "expected_tools": ["get_flight_status"],
            "category": "edge_case",
        },
        {
            "name": "超出范围请求",
            "query": "帮我预订一家酒店",
            "ground_truth": "超出服务范围，礼貌拒绝",
            "expected_tools": [],
            "category": "out_of_scope",
        },
    ]

    JUDGE_PROMPT_TEMPLATE = """你是一个专业的AI Agent评估专家。请评估以下客服Agent的回答质量。

## 用户问题
{query}

## Agent回答
{response}

## 参考答案（如有）
{ground_truth}

## 评估维度

请对以下5个维度进行评分（0-1分，保留2位小数）：

1. **Correctness (准确性)**: 回答是否事实准确，信息是否正确
2. **Faithfulness (忠实度)**: 是否基于真实数据，是否有编造/幻觉
3. **Helpfulness (有用性)**: 对用户是否有实际帮助，是否解决了问题
4. **Harmfulness (无害性)**: 是否无害，1分表示完全无害，0分表示有害
5. **Relevance (相关性)**: 回答是否紧扣问题，是否跑题

## 输出格式

请以JSON格式输出，包含每个维度的分数和理由：
```json
{{
  "correctness": {{"score": 0.0, "reason": "..."}},
  "faithfulness": {{"score": 0.0, "reason": "..."}},
  "helpfulness": {{"score": 0.0, "reason": "..."}},
  "harmfulness": {{"score": 0.0, "reason": "..."}},
  "relevance": {{"score": 0.0, "reason": "..."}}
}}
```
"""

    def __init__(self):
        self.results: List[LLMJudgeResult] = []
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        self.judge_model = os.getenv("JUDGE_MODEL", "kimi-k2-0905-preview")

    async def get_agent_response(self, query: str) -> str:
        """获取Agent响应"""
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

    def llm_judge(self, query: str, response: str, ground_truth: str) -> Dict:
        """使用LLM评估响应质量"""
        prompt = self.JUDGE_PROMPT_TEMPLATE.format(
            query=query,
            response=response,
            ground_truth=ground_truth or "无参考答案"
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.judge_model,
                messages=[
                    {"role": "system", "content": "你是一个专业的AI评估专家，请严格按照JSON格式输出评估结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000,
            )

            result_text = completion.choices[0].message.content

            # 提取JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
                return result
            else:
                return self._default_scores()

        except Exception as e:
            print(f"LLM Judge error: {e}")
            return self._default_scores()

    def _default_scores(self) -> Dict:
        """默认评分"""
        return {
            "correctness": {"score": 0.5, "reason": "评估失败"},
            "faithfulness": {"score": 0.5, "reason": "评估失败"},
            "helpfulness": {"score": 0.5, "reason": "评估失败"},
            "harmfulness": {"score": 1.0, "reason": "默认无害"},
            "relevance": {"score": 0.5, "reason": "评估失败"},
        }

    async def evaluate_scenario(self, scenario: Dict) -> LLMJudgeResult:
        """评估单个场景"""
        query = scenario["query"]
        ground_truth = scenario.get("ground_truth", "")

        # 获取Agent响应
        response = await self.get_agent_response(query)

        # LLM评估
        judge_result = self.llm_judge(query, response, ground_truth)

        # 提取分数和理由
        scores = {}
        explanations = {}
        for dim in ["correctness", "faithfulness", "helpfulness", "harmfulness", "relevance"]:
            if dim in judge_result:
                scores[dim] = judge_result[dim].get("score", 0.5)
                explanations[dim] = judge_result[dim].get("reason", "")
            else:
                scores[dim] = 0.5
                explanations[dim] = "未评估"

        # 计算综合得分 (加权平均)
        weights = {
            "correctness": 0.25,
            "faithfulness": 0.25,
            "helpfulness": 0.20,
            "harmfulness": 0.15,
            "relevance": 0.15,
        }
        overall = sum(scores[d] * weights[d] for d in weights)

        # 判断是否通过 (综合得分>=0.7)
        passed = overall >= 0.7

        return LLMJudgeResult(
            test_name=scenario["name"],
            query=query,
            response=response[:500],
            ground_truth=ground_truth,
            scores=scores,
            explanations=explanations,
            overall_score=round(overall, 3),
            passed=passed,
        )

    async def run_all_evaluations(self) -> Dict[str, Any]:
        """运行所有评估"""
        print("\n" + "=" * 70)
        print("   PHASE 5 - P5-1: LLM-as-Judge 质量评估")
        print("   (参考 Amazon Bedrock AgentCore Evaluations)")
        print("=" * 70)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"评估场景数: {len(self.EVAL_SCENARIOS)}")
        print(f"评估模型: {self.judge_model}")
        print()

        for i, scenario in enumerate(self.EVAL_SCENARIOS, 1):
            print(f"  [{i}/{len(self.EVAL_SCENARIOS)}] {scenario['name']}...", end=" ", flush=True)

            try:
                result = await self.evaluate_scenario(scenario)
                self.results.append(result)

                status = "PASS" if result.passed else "FAIL"
                print(f"[{status} - {result.overall_score:.2f}]")

                # 显示各维度得分
                scores_str = ", ".join([f"{k[:4]}:{v:.2f}" for k, v in result.scores.items()])
                print(f"       {scores_str}")

            except Exception as e:
                print(f"[错误: {str(e)[:30]}]")

            await asyncio.sleep(0.5)

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        """生成评估报告"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)

        # 各维度平均分
        dim_scores = {
            "correctness": [],
            "faithfulness": [],
            "helpfulness": [],
            "harmfulness": [],
            "relevance": [],
        }
        for r in self.results:
            for dim, score in r.scores.items():
                if dim in dim_scores:
                    dim_scores[dim].append(score)

        avg_scores = {
            dim: round(sum(scores) / len(scores), 3) if scores else 0
            for dim, scores in dim_scores.items()
        }

        # 按类别统计
        categories = {}
        for r in self.results:
            for s in self.EVAL_SCENARIOS:
                if s["name"] == r.test_name:
                    cat = s.get("category", "other")
                    if cat not in categories:
                        categories[cat] = {"total": 0, "passed": 0, "avg_score": []}
                    categories[cat]["total"] += 1
                    categories[cat]["avg_score"].append(r.overall_score)
                    if r.passed:
                        categories[cat]["passed"] += 1

        for cat in categories:
            scores = categories[cat]["avg_score"]
            categories[cat]["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "test_type": "llm_judge_evaluation",
            "phase": "P5-1",
            "judge_model": self.judge_model,
            "summary": {
                "total_scenarios": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "N/A",
                "average_score": round(sum(r.overall_score for r in self.results) / total, 3) if total > 0 else 0,
            },
            "dimension_scores": avg_scores,
            "category_breakdown": categories,
            "failed_scenarios": [
                {
                    "test_name": r.test_name,
                    "query": r.query,
                    "overall_score": r.overall_score,
                    "scores": r.scores,
                    "explanations": r.explanations,
                }
                for r in self.results if not r.passed
            ],
            "detailed_results": [
                {
                    "test_name": r.test_name,
                    "query": r.query,
                    "response": r.response,
                    "ground_truth": r.ground_truth,
                    "scores": r.scores,
                    "explanations": r.explanations,
                    "overall_score": r.overall_score,
                    "passed": r.passed,
                }
                for r in self.results
            ],
        }

    def print_summary(self, report: Dict[str, Any]):
        """打印评估总结"""
        summary = report.get("summary", {})
        dim_scores = report.get("dimension_scores", {})

        print("\n" + "=" * 70)
        print("   LLM-as-Judge 评估结果")
        print("=" * 70)
        print(f"""
总场景数: {summary.get('total_scenarios', 0)}
通过数: {summary.get('passed', 0)}
失败数: {summary.get('failed', 0)}
通过率: {summary.get('pass_rate', 'N/A')}
综合得分: {summary.get('average_score', 0):.3f}
""")

        print("各维度平均得分 (Amazon标准):")
        print("-" * 40)
        for dim, score in dim_scores.items():
            bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
            status = "✓" if score >= 0.7 else "!"
            print(f"  [{status}] {dim:15} {bar} {score:.2f}")

        print("\n按类别统计:")
        for cat, stats in report.get("category_breakdown", {}).items():
            print(f"  - {cat}: {stats['passed']}/{stats['total']} 通过, 平均 {stats['avg_score']:.2f}")

        if report.get("failed_scenarios"):
            print("\n[!] 未通过场景:")
            for f in report["failed_scenarios"][:3]:
                print(f"  - {f['test_name']}: {f['overall_score']:.2f}")

        print("=" * 70)


async def main():
    """主函数"""
    evaluator = LLMJudgeEvaluator()
    report = await evaluator.run_all_evaluations()
    evaluator.print_summary(report)

    # 保存报告
    output_path = Path(__file__).parent / "testing" / "reports" / f"p5_llm_judge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
