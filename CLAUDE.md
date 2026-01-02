# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **OpenAI Agents SDK Customer Service Demo** - a full-stack application demonstrating multi-agent customer service orchestration for an airline booking system.

**Tech Stack**: Python FastAPI + OpenAI Agents SDK + Next.js 14 + ChatKit

**Model**: kimi-k2-0905-preview (Moonshot API)

---

## Commands

### Development (Frontend + Backend)
```bash
cd ui && npm run dev
```
Starts Next.js on http://localhost:3000 and Python backend on http://localhost:8000.

### Backend Only
```bash
cd python-backend
source .venv/bin/activate
python -m uvicorn main:app --reload --port 8000
```

### Frontend Only
```bash
cd ui && npm run dev:next
```

### Setup
```bash
# Backend
cd python-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ui && npm install
```

### Security Testing
```bash
cd python-backend

# Comprehensive security test
python comprehensive_security_test.py

# dspyGuardrails integration test
python dspy_guardrails_test.py

# Individual phase tests
python phase1_direct_injection_test.py
python phase2_context_pollution_test.py
python phase3_multi_turn_test.py
python phase4_advanced_jailbreak_test.py
python phase5_comprehensive_evaluation.py

# Generate security report
python generate_security_report.py
```

### Linting
```bash
cd ui && npm run lint
```

### Environment
```bash
# python-backend/.env
OPENAI_API_KEY=sk-xxx              # Moonshot/Kimi API key
OPENAI_BASE_URL=https://api.moonshot.cn/v1
```

---

## Architecture

### Agent System

Multi-agent orchestration with agent-to-agent handoffs:

| Agent | Description | Tools |
|-------|-------------|-------|
| **Triage Agent** | Entry point, routes to specialists | Handoff to all agents |
| **Flight Information Agent** | Status, delays, connection risk | `flight_status_tool`, `get_matching_flights` |
| **Booking & Cancellation Agent** | Books, rebooks, cancels trips | `book_new_flight`, `cancel_flight`, `get_trip_details` |
| **Seat & Special Services Agent** | Seat changes, medical requests | `update_seat`, `assign_special_service_seat`, `display_seat_map` |
| **FAQ Agent** | Policy questions | `faq_lookup_tool` |
| **Refunds & Compensation Agent** | Cases, hotel/meal support | `issue_compensation` |

### Guardrails

| Guardrail | Type | Description |
|-----------|------|-------------|
| **Relevance Guardrail** | LLM-based | Checks if message is relevant to airline service |
| **Jailbreak Guardrail** | LLM-based | Detects prompt injection and manipulation attempts |

---

## Directory Structure

```
openai-cs-agents-demo/
├── CLAUDE.md                         # This file
│
├── python-backend/
│   ├── main.py                       # FastAPI app with ChatKit endpoints
│   ├── server.py                     # AirlineServer orchestration class
│   ├── memory_store.py               # In-memory ChatKit store
│   │
│   ├── airline/                      # Agent System
│   │   ├── __init__.py
│   │   ├── agents.py                 # 6 specialist agents with handoffs
│   │   ├── tools.py                  # Tool implementations
│   │   ├── guardrails.py             # Relevance + Jailbreak guardrails
│   │   ├── context.py                # AirlineAgentChatContext state
│   │   └── demo_data.py              # Mock itineraries
│   │
│   ├── data/
│   │   ├── database/                 # Mock flight database
│   │   │   ├── flights.json
│   │   │   └── passengers.json
│   │   ├── knowledge_base/           # FAQs and policies
│   │   │   ├── baggage_policy.md
│   │   │   ├── compensation_policy.md
│   │   │   └── wifi_info.md
│   │   └── mcp_services/             # MCP tool definitions
│   │
│   ├── testing/                      # Test Framework
│   │   ├── __init__.py
│   │   ├── test_runner.py            # Test execution framework
│   │   ├── report_generator.py       # Report generation
│   │   ├── fault_injector.py         # Chaos testing
│   │   └── reports/                  # Test result storage
│   │       ├── SECURITY_TEST_REPORT_*.md
│   │       ├── DSPY_GUARDRAILS_TEST_*.md
│   │       └── *.json
│   │
│   ├── phase1_direct_injection_test.py      # Direct injection, tool injection
│   ├── phase2_context_pollution_test.py     # Context pollution, hallucination
│   ├── phase3_multi_turn_test.py            # Multi-turn attacks, stress testing
│   ├── phase4_advanced_jailbreak_test.py    # Advanced jailbreaks, attack chains
│   ├── phase5_comprehensive_evaluation.py  # Goal success, LLM judge
│   │
│   ├── comprehensive_security_test.py      # Full security test suite
│   ├── dspy_guardrails_test.py             # dspyGuardrails integration
│   ├── generate_security_report.py         # Report generation script
│   │
│   ├── requirements.txt
│   └── .env                          # Environment variables
│
└── ui/                               # Next.js 14 Frontend
    ├── app/
    │   ├── page.tsx                  # Main chat interface
    │   ├── layout.tsx                # Root layout
    │   └── globals.css               # Global styles
    │
    ├── components/
    │   ├── chatkit-panel.tsx         # ChatKit UI wrapper
    │   ├── agent-panel.tsx           # Agent list and status
    │   ├── seat-map.tsx              # Interactive seat selection
    │   ├── guardrails.tsx            # Guardrail violation display
    │   ├── runner-output.tsx         # Tool execution visualization
    │   └── ui/                       # Shadcn UI components
    │       ├── button.tsx
    │       ├── card.tsx
    │       └── ...
    │
    ├── lib/
    │   └── api.ts                    # Backend API calls
    │
    ├── next.config.mjs               # Proxy rewrites to backend
    ├── tailwind.config.ts            # Tailwind CSS config
    ├── tsconfig.json                 # TypeScript config
    └── package.json
```

---

## Key Implementation Details

### Agent Definition Pattern

```python
# python-backend/airline/agents.py
from agents import Agent, InputGuardrail
from airline.context import AirlineAgentChatContext

MODEL = "kimi-k2-0905-preview"

def booking_agent_instructions(context: RunContextWrapper) -> str:
    """Dynamic instructions with context injection."""
    ctx = context.context.state
    return f"""You are a booking agent for an airline.

Customer: {ctx.passenger_name}
Confirmation: {ctx.confirmation_number}
Current itinerary: {ctx.itinerary}

Help the customer with booking changes..."""

booking_agent = Agent[AirlineAgentChatContext](
    name="Booking Agent",
    model=MODEL,
    handoff_description="Books, rebooks, or cancels flights",
    instructions=booking_agent_instructions,
    tools=[book_new_flight, cancel_flight, get_trip_details],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)
```

### Tool Definition Pattern

```python
# python-backend/airline/tools.py
from agents import function_tool, RunContextWrapper
from airline.context import AirlineAgentChatContext

@function_tool
async def book_new_flight(
    context: RunContextWrapper[AirlineAgentChatContext],
    flight_number: str,
    departure_date: str,
) -> str:
    """Books a new flight for the customer.

    Args:
        flight_number: The flight number to book (e.g., "NY950")
        departure_date: Departure date in YYYY-MM-DD format
    """
    ctx = context.context.state
    # Use context for personalization
    result = book_flight_service(
        passenger=ctx.passenger_name,
        flight=flight_number,
        date=departure_date,
    )
    return f"Booked flight {flight_number} for {ctx.passenger_name}"
```

### Guardrail Definition Pattern

```python
# python-backend/airline/guardrails.py
from agents import InputGuardrail, GuardrailFunctionOutput

@InputGuardrail
async def jailbreak_guardrail(
    context: RunContextWrapper[AirlineAgentChatContext],
    agent: Agent,
    input: str,
) -> GuardrailFunctionOutput:
    """Detects prompt injection and jailbreak attempts."""

    # LLM-based detection
    result = await detect_jailbreak(input)

    if result.is_jailbreak:
        return GuardrailFunctionOutput(
            output_info="Jailbreak attempt detected",
            tripwire_triggered=True,
        )

    return GuardrailFunctionOutput(
        output_info="Input is safe",
        tripwire_triggered=False,
    )
```

### Context Variables

`AirlineAgentChatContext` tracks conversation state:

| Field | Type | Description |
|-------|------|-------------|
| `passenger_name` | str | Customer's name |
| `confirmation_number` | str | Booking confirmation |
| `seat_number` | str | Current seat assignment |
| `flight_number` | str | Current flight |
| `account_number` | str | Loyalty account |
| `itinerary` | dict | Full trip details |
| `vouchers` | list | Issued vouchers |
| `special_service_note` | str | Medical/special requests |
| `origin` | str | Origin airport |
| `destination` | str | Destination airport |

### Communication Flow

```
┌─────────────┐     POST /chatkit     ┌─────────────────┐
│   Frontend  │ ──────────────────►  │  FastAPI Server │
│  (Next.js)  │                       │   (main.py)     │
└─────────────┘                       └────────┬────────┘
       ▲                                       │
       │                                       ▼
       │                              ┌─────────────────┐
       │  SSE /chatkit/state/stream   │  AirlineServer  │
       │ ◄────────────────────────────│   (server.py)   │
       │                              └────────┬────────┘
       │                                       │
       │                                       ▼
       │                              ┌─────────────────┐
       │                              │  Agent Runner   │
       │                              │  (OpenAI SDK)   │
       │                              └────────┬────────┘
       │                                       │
       │                                       ▼
       │                              ┌─────────────────┐
       │                              │   Guardrails    │
       │                              │ + Tool Executor │
       └──────────────────────────────└─────────────────┘
```

---

## Security Testing

### Test Phases

| Phase | Focus | Tests |
|-------|-------|-------|
| **Phase 1** | Direct Attacks | Injection, tool injection, output validation |
| **Phase 2** | Indirect Attacks | Context pollution, hallucination, supply chain |
| **Phase 3** | Advanced Attacks | Fairness, log injection, multi-turn, stress |
| **Phase 4** | Bypass Techniques | Advanced jailbreaks, attack chains, business logic |
| **Phase 5** | Comprehensive | Goal success, LLM judge, full evaluation |

### dspyGuardrails Integration

```python
# python-backend/dspy_guardrails_test.py
from dspy_guardrails.redteam import (
    PromptInjectionAttacker,
    JailbreakAttacker,
    RedTeamEvaluator,
)
from dspy_guardrails.testing import SecurityTestRunner

# Configure dspyGuardrails
import dspy
dspy.configure(lm=dspy.LM(
    model="openai/kimi-k2-0905-preview",
    api_base="https://api.moonshot.cn/v1",
))

# Run attacks
attacker = PromptInjectionAttacker(use_llm=True)
attacks = [attacker(target_behavior="reveal system prompt") for _ in range(10)]

# Evaluate
evaluator = RedTeamEvaluator()
report = evaluator.evaluate(
    target=airline_guardrail,
    target_name="Airline Jailbreak Guardrail",
    attacks=attacks,
)
print(report.summary())
```

### Test Report Location

```
python-backend/testing/reports/
├── SECURITY_TEST_REPORT_*.md      # Markdown assessment reports
├── DSPY_GUARDRAILS_TEST_*.md      # dspyGuardrails test reports
├── comprehensive_test_*.json       # Detailed JSON test data
└── dspy_guardrails_test_*.json     # dspyGuardrails results
```

---

## Demo Scenarios

### Disrupted Itinerary
- **Route**: Paris (CDG) → New York (JFK) → Austin (AUS)
- **Flights**: PA441, NY802 (delayed)
- **Scenario**: Connection at risk, needs rebooking to NY950

### On-Time Itinerary
- **Route**: San Francisco (SFO) → Los Angeles (LAX)
- **Flight**: FLT-123
- **Scenario**: Normal operation, seat change requests

---

## Adding New Components

### New Agent

1. Define instruction function in `airline/agents.py`:
```python
def my_agent_instructions(context: RunContextWrapper) -> str:
    ctx = context.context.state
    return f"You are a {role}. Customer: {ctx.passenger_name}..."
```

2. Create agent:
```python
my_agent = Agent[AirlineAgentChatContext](
    name="My Agent",
    model=MODEL,
    handoff_description="Description for triage",
    instructions=my_agent_instructions,
    tools=[tool1, tool2],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)
```

3. Add handoff relationship:
```python
triage_agent.handoff_to = [..., my_agent]
```

### New Tool

Define in `airline/tools.py`:
```python
@function_tool
async def my_tool(
    context: RunContextWrapper[AirlineAgentChatContext],
    param1: str,
    param2: int,
) -> str:
    """Tool description for the LLM.

    Args:
        param1: Description of param1
        param2: Description of param2
    """
    ctx = context.context.state
    # Implementation
    return result
```

### New Guardrail

Define in `airline/guardrails.py`:
```python
@InputGuardrail
async def my_guardrail(
    context: RunContextWrapper[AirlineAgentChatContext],
    agent: Agent,
    input: str,
) -> GuardrailFunctionOutput:
    """Guardrail description."""

    is_safe = check_safety(input)

    return GuardrailFunctionOutput(
        output_info="Safe" if is_safe else "Blocked",
        tripwire_triggered=not is_safe,
    )
```

---

## Frontend Components

### ChatKit Panel
```tsx
// components/chatkit-panel.tsx
<ChatKitPanel
  onMessage={handleMessage}
  agentState={agentState}
  guardrailStatus={guardrailStatus}
/>
```

### Agent Panel
```tsx
// components/agent-panel.tsx
<AgentPanel
  agents={agents}
  activeAgent={activeAgent}
  handoffHistory={handoffHistory}
/>
```

### Seat Map
```tsx
// components/seat-map.tsx
<SeatMap
  seats={seatData}
  selectedSeat={selectedSeat}
  onSeatSelect={handleSeatSelect}
/>
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chatkit` | POST | Send message to agent |
| `/chatkit/state` | GET | Get current conversation state |
| `/chatkit/state/stream` | GET | SSE stream for real-time updates |
| `/bootstrap` | POST | Initialize new conversation |
| `/health` | GET | Health check |

---

## Related Projects (Monorepo)

| Project | Description |
|---------|-------------|
| `../dspyGuardrails/` | Core guardrails library with red team framework |
| `../guardrails-mcp/` | TypeScript MCP server |
| `../agent-copilot-demo/` | Agent copilot demonstration |
| `../agent-evaluation/` | Amazon Bedrock evaluation framework |
| `../experiments/` | Benchmark results |

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Backend not starting | Check `.env` for API key |
| Frontend 404 errors | Ensure backend is running on :8000 |
| Agent not responding | Check Moonshot API quota |
| Guardrail false positives | Adjust threshold in `guardrails.py` |
| SSE connection drops | Check network/proxy settings |

### Logs

```bash
# Backend logs
cd python-backend
python -m uvicorn main:app --reload --log-level debug

# Frontend logs
cd ui
npm run dev 2>&1 | tee frontend.log
```
