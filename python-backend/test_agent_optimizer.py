"""
Agent Optimizer 集成测试
========================

测试 dspy_guardrails.agent_optimizer 扩展层与 DSPy ReAct 的集成。

运行方式:
    cd openai-cs-agents-demo/python-backend
    python test_agent_optimizer.py
"""

import os
import sys
from pathlib import Path

# 添加 dspyGuardrails 到路径
dspy_guardrails_path = Path(__file__).parent.parent.parent / "dspyGuardrails" / "src"
sys.path.insert(0, str(dspy_guardrails_path))

import dspy
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# =============================================================================
# 配置 DSPy
# =============================================================================

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
MOONSHOT_MODEL = os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview")

lm = dspy.LM(
    model=f"openai/{MOONSHOT_MODEL}",
    api_key=MOONSHOT_API_KEY,
    api_base=MOONSHOT_BASE_URL,
    temperature=0.7,
)
dspy.configure(lm=lm)

print(f"[CONFIG] Using model: {MOONSHOT_MODEL}")

# =============================================================================
# Mock Data
# =============================================================================

MOCK_FLIGHTS = {
    "FL123": {
        "confirmation": "FL123",
        "passenger": "张三",
        "from": "北京",
        "to": "上海",
        "departure": "2025-01-10 08:00",
        "status": "on_time",
        "gate": "A12",
    },
    "FL456": {
        "confirmation": "FL456",
        "passenger": "李四",
        "from": "上海",
        "to": "广州",
        "departure": "2025-01-10 14:30",
        "status": "delayed",
        "delay_minutes": 45,
        "gate": "B8",
    },
}

MOCK_POLICIES = {
    "baggage": "每位乘客可携带一件手提行李(不超过7kg)和一件托运行李(不超过23kg)。",
    "refund": "机票退改政策：起飞前24小时可免费退改，24小时内收取20%手续费。",
    "wifi": "航班上提供免费WiFi，连接'AirlineWiFi'网络后在浏览器中登录。",
}

# =============================================================================
# DSPy Tools
# =============================================================================

def flight_status(confirmation_number: str) -> str:
    """
    查询航班状态

    Args:
        confirmation_number: 航班确认号，如 FL123

    Returns:
        航班状态信息
    """
    flight = MOCK_FLIGHTS.get(confirmation_number)
    if not flight:
        return f"未找到确认号为 {confirmation_number} 的航班"

    status_text = "准时" if flight["status"] == "on_time" else f"延误 {flight.get('delay_minutes', 0)} 分钟"
    return (
        f"航班 {confirmation_number}:\n"
        f"  乘客: {flight['passenger']}\n"
        f"  航线: {flight['from']} → {flight['to']}\n"
        f"  起飞: {flight['departure']}\n"
        f"  状态: {status_text}\n"
        f"  登机口: {flight['gate']}"
    )


def get_policy(topic: str) -> str:
    """
    查询航空公司政策

    Args:
        topic: 政策主题，如 baggage, refund, wifi

    Returns:
        政策内容
    """
    policy = MOCK_POLICIES.get(topic.lower())
    if not policy:
        available = ", ".join(MOCK_POLICIES.keys())
        return f"未找到 '{topic}' 相关政策。可查询: {available}"
    return policy


def book_flight(origin: str, destination: str, date: str) -> str:
    """
    预订新航班

    Args:
        origin: 出发城市
        destination: 目的城市
        date: 日期 (YYYY-MM-DD)

    Returns:
        预订结果
    """
    import random
    confirmation = f"FL{random.randint(100, 999)}"
    return (
        f"预订成功！\n"
        f"  确认号: {confirmation}\n"
        f"  航线: {origin} → {destination}\n"
        f"  日期: {date}\n"
        f"  请在起飞前2小时到达机场办理登机手续。"
    )


# =============================================================================
# DSPy ReAct Agent
# =============================================================================

TOOLS = [flight_status, get_policy, book_flight]

AGENT_INSTRUCTIONS = """
你是一位专业的航空公司客服助手。

职责：
1. 查询航班状态 - 使用 flight_status 工具
2. 解答政策问题 - 使用 get_policy 工具
3. 协助预订航班 - 使用 book_flight 工具

规则：
- 使用中文回复
- 始终礼貌专业
- 如果需要更多信息，请询问用户
"""


class AirlineAgentSignature(dspy.Signature):
    """航空客服 Agent 签名"""
    user_request: str = dspy.InputField(desc="用户的请求或问题")
    response: str = dspy.OutputField(desc="客服助手的回复")


class AirlineReActAgent(dspy.Module):
    """航空客服 ReAct Agent"""

    def __init__(self):
        super().__init__()
        # 使用 Signature 类而非字符串
        self.react = dspy.ReAct(
            AirlineAgentSignature,
            tools=TOOLS,
            max_iters=5,
        )
        # 注入指令到 signature
        self.react.signature = self.react.signature.with_instructions(AGENT_INSTRUCTIONS)

    def forward(self, user_request: str):
        return self.react(user_request=user_request)


# =============================================================================
# 测试用例
# =============================================================================

TEST_CASES = [
    {
        "id": "T1",
        "input": "查一下 FL123 的航班状态",
        "expected_tools": ["flight_status"],
        "expected_keywords": ["FL123", "准时", "张三"],
    },
    {
        "id": "T2",
        "input": "FL456 延误了吗？",
        "expected_tools": ["flight_status"],
        "expected_keywords": ["FL456", "延误", "45"],
    },
    {
        "id": "T3",
        "input": "行李政策是什么？",
        "expected_tools": ["get_policy"],
        "expected_keywords": ["行李", "7kg", "23kg"],
    },
    {
        "id": "T4",
        "input": "我想从北京飞深圳，1月15日",
        "expected_tools": ["book_flight"],
        "expected_keywords": ["预订", "确认号", "北京"],
    },
    {
        "id": "T5",
        "input": "退票规则是什么？",
        "expected_tools": ["get_policy"],
        "expected_keywords": ["退", "24小时", "手续费"],
    },
]


# =============================================================================
# 使用 agent_optimizer 扩展
# =============================================================================

from dspy_guardrails.agent_optimizer import (
    AgentOptimizer,
    OptimizationConfig,
    OptimizationMethod,
    wrap_agent,
    TrajectoryRecorder,
    assign_credit,
    CreditSummary,
)
from dspy_guardrails.agent_optimizer.wrapper import AgentResult
from dspy_guardrails.agent_optimizer.trajectory import StepType, Outcome


class DSPyReActAgentWrapper:
    """
    DSPy ReAct Agent 的自定义包装器

    实现 OptimizableAgent 接口，支持轨迹记录和优化。
    """

    def __init__(self, agent: AirlineReActAgent):
        self.agent = agent
        self.demos = []

    def run(self, task: str, record: bool = True) -> AgentResult:
        """运行 Agent 并记录轨迹"""
        recorder = TrajectoryRecorder(task=task) if record else None

        if recorder:
            recorder.set_agent("AirlineReAct")
            recorder.record_step(
                step_type=StepType.USER_INPUT,
                input_data={"task": task},
            )

        import time
        start_time = time.time()

        try:
            # 调用 DSPy ReAct
            prediction = self.agent(user_request=task)
            latency_ms = (time.time() - start_time) * 1000

            # 提取响应
            response = getattr(prediction, 'response', str(prediction))

            # 解析轨迹
            if record and hasattr(prediction, 'trajectory'):
                traj_data = prediction.trajectory
                if isinstance(traj_data, dict):
                    i = 0
                    while f'tool_name_{i}' in traj_data or f'thought_{i}' in traj_data:
                        thought = traj_data.get(f'thought_{i}', '')
                        tool_name = traj_data.get(f'tool_name_{i}', '')
                        tool_args = traj_data.get(f'tool_args_{i}', {})
                        observation = traj_data.get(f'observation_{i}', '')

                        if tool_name and tool_name != 'finish':
                            recorder.record_step(
                                step_type=StepType.TOOL_CALL,
                                thought=thought,
                                action_type="tool_call",
                                action_name=tool_name,
                                action_args=tool_args if isinstance(tool_args, dict) else {},
                                result=observation,
                            )
                        i += 1

            # 判断成功
            success = len(response) > 20 and "error" not in response.lower()
            outcome = Outcome.SUCCESS if success else Outcome.PARTIAL

            if recorder:
                recorder.record_step(
                    step_type=StepType.AGENT_OUTPUT,
                    result=response,
                    latency_ms=latency_ms,
                )
                trajectory = recorder.finish(
                    response=response,
                    outcome=outcome,
                    reward=1.0 if success else 0.0,
                )
            else:
                trajectory = None

            return AgentResult(
                response=response,
                trajectory=trajectory,
                success=success,
            )

        except Exception as e:
            if recorder:
                recorder.record_step(
                    step_type=StepType.AGENT_OUTPUT,
                    error=str(e),
                )
                trajectory = recorder.finish(
                    response=f"Error: {e}",
                    outcome=Outcome.ERROR,
                    reward=-1.0,
                )
            else:
                trajectory = None

            return AgentResult(
                response=f"Error: {e}",
                trajectory=trajectory,
                success=False,
            )

    def get_optimizable_params(self):
        """获取可优化参数"""
        return {
            "demos": self.demos,
            "instructions": AGENT_SIGNATURE,
        }

    def set_params(self, params):
        """设置参数"""
        if "demos" in params:
            self.demos = params["demos"]
            # 将 demos 注入到 ReAct 模块
            if hasattr(self.agent.react, 'demos'):
                self.agent.react.demos = params["demos"]


def evaluate_result(result: AgentResult, test_case: dict) -> dict:
    """评估单个结果"""
    response = result.response.lower() if result.response else ""

    # 工具匹配
    tools_used = []
    if result.trajectory:
        tools_used = result.trajectory.get_tools_used()

    tool_match = any(
        expected in tools_used
        for expected in test_case["expected_tools"]
    )

    # 关键词匹配
    keyword_matches = sum(
        1 for kw in test_case["expected_keywords"]
        if kw.lower() in response
    )
    keyword_score = keyword_matches / len(test_case["expected_keywords"])

    return {
        "tool_match": tool_match,
        "keyword_score": keyword_score,
        "success": tool_match and keyword_score >= 0.5,
        "tools_used": tools_used,
    }


def custom_metric(result: AgentResult) -> float:
    """
    自定义评估指标

    综合考虑：
    - 响应长度
    - 工具使用情况
    - 无错误
    """
    if not result.success:
        return 0.0

    response = result.response or ""
    score = 0.0

    # 基础分：有实质内容
    if len(response) > 50:
        score += 0.3
    elif len(response) > 20:
        score += 0.2

    # 工具使用分
    if result.trajectory:
        tools = result.trajectory.get_tools_used()
        if tools:
            score += 0.4

    # 无错误
    if "error" not in response.lower() and "未找到" not in response:
        score += 0.3

    return min(score, 1.0)


# =============================================================================
# 主测试流程
# =============================================================================

def run_baseline_test():
    """运行基准测试"""
    print("\n" + "=" * 60)
    print("Phase 1: Baseline 测试")
    print("=" * 60)

    agent = AirlineReActAgent()
    wrapped = DSPyReActAgentWrapper(agent)

    results = []
    for tc in TEST_CASES:
        print(f"\n[{tc['id']}] {tc['input']}")

        result = wrapped.run(tc["input"])
        eval_result = evaluate_result(result, tc)

        print(f"  Response: {result.response[:100]}...")
        print(f"  Tools: {eval_result['tools_used']}")
        print(f"  Tool Match: {'✓' if eval_result['tool_match'] else '✗'}")
        print(f"  Keyword Score: {eval_result['keyword_score']:.0%}")

        results.append({
            "test_case": tc,
            "result": result,
            "eval": eval_result,
        })

    # 汇总
    success_count = sum(1 for r in results if r["eval"]["success"])
    tool_match_count = sum(1 for r in results if r["eval"]["tool_match"])
    avg_keyword = sum(r["eval"]["keyword_score"] for r in results) / len(results)

    print("\n" + "-" * 40)
    print(f"Baseline 结果:")
    print(f"  成功率: {success_count}/{len(TEST_CASES)} ({success_count/len(TEST_CASES):.0%})")
    print(f"  工具匹配: {tool_match_count}/{len(TEST_CASES)} ({tool_match_count/len(TEST_CASES):.0%})")
    print(f"  关键词得分: {avg_keyword:.0%}")

    return wrapped, results


def run_trajectory_analysis(wrapped, results):
    """运行轨迹分析"""
    print("\n" + "=" * 60)
    print("Phase 2: 轨迹分析与 Credit Assignment")
    print("=" * 60)

    for r in results:
        if r["result"].trajectory:
            traj = r["result"].trajectory

            # 分配 credit
            assign_credit(traj, method="decay")

            print(f"\n[{r['test_case']['id']}] {traj.summary()}")

            # 显示关键步骤
            for step in traj.steps:
                if step.step_type == StepType.TOOL_CALL:
                    print(f"  → Tool: {step.action_name} | Credit: {step.credit:.3f}")


def run_optimization(wrapped):
    """运行优化"""
    print("\n" + "=" * 60)
    print("Phase 3: Bootstrap 优化")
    print("=" * 60)

    config = OptimizationConfig(
        method=OptimizationMethod.BOOTSTRAP,
        num_demos=3,
        demo_selection="diverse",
        save_trajectories=False,
    )

    optimizer = AgentOptimizer(
        metric=custom_metric,
        config=config,
    )

    # 使用测试用例作为训练数据
    train_tasks = [tc["input"] for tc in TEST_CASES[:3]]
    eval_tasks = [tc["input"] for tc in TEST_CASES[3:]]

    print(f"\n训练任务: {len(train_tasks)}")
    print(f"评估任务: {len(eval_tasks)}")

    result = optimizer.optimize(
        agent=wrapped,
        train_tasks=train_tasks,
        eval_tasks=eval_tasks,
    )

    print("\n" + result.summary())

    if result.credit_summary:
        print("\nCredit 摘要:")
        print(f"  总正向贡献: {result.credit_summary.total_positive_credit:.3f}")
        print(f"  总负向贡献: {result.credit_summary.total_negative_credit:.3f}")
        if result.credit_summary.top_contributors:
            print("  Top 贡献步骤:")
            for step_id, credit, name in result.credit_summary.top_contributors[:3]:
                print(f"    - Step {step_id} ({name}): {credit:.3f}")

    return result


def main():
    """主函数"""
    print("=" * 60)
    print("Agent Optimizer 集成测试")
    print("=" * 60)
    print(f"\n测试 dspy_guardrails.agent_optimizer 扩展层")
    print(f"目标: 验证轨迹记录、Credit Assignment、Bootstrap 优化")

    # Phase 1: Baseline
    wrapped, results = run_baseline_test()

    # Phase 2: 轨迹分析
    run_trajectory_analysis(wrapped, results)

    # Phase 3: 优化 (可选，需要更多 API 调用)
    print("\n" + "=" * 60)
    print("是否运行优化? (需要额外 API 调用)")
    print("输入 'y' 运行优化，其他跳过")
    print("=" * 60)

    try:
        user_input = input("> ").strip().lower()
        if user_input == 'y':
            result = run_optimization(wrapped)
        else:
            print("跳过优化阶段")
    except EOFError:
        print("非交互模式，跳过优化阶段")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
