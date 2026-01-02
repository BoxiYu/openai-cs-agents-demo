"""
Enhanced tools for database, knowledge base, and MCP service interactions.
These tools support fault injection for security and robustness testing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from agents import RunContextWrapper, function_tool
from chatkit.types import ProgressUpdateEvent

from .context import AirlineAgentChatContext
from .backends import get_database, get_knowledge_base, get_mcp_bridge


# ============= Database Tools =============

@function_tool(
    name_override="db_query",
    description_override="Query the database for customer, flight, booking, or seat information. Use filters to narrow results."
)
async def db_query(
    context: RunContextWrapper[AirlineAgentChatContext],
    table: str,
    filters: str = "{}"
) -> str:
    """
    Query database with filters.

    Args:
        table: Table name - one of: customers, flights, bookings, seats
        filters: JSON string of field:value pairs for filtering
                 Example: '{"customer_id": "C001"}' or '{"flight_number": "CA1234"}'

    Returns:
        JSON string of matching records or error message
    """
    await context.context.stream(ProgressUpdateEvent(text=f"Querying {table}..."))

    # Get fault injector if in test mode
    injector = getattr(context.context.state, 'fault_injector', None)

    # Check for delay injection
    if injector:
        delay = injector.inject_delay("db_query")
        if delay > 0:
            await asyncio.sleep(delay)

        # Check for failure injection
        if injector.should_fail("db_query"):
            error_response = injector.get_failure_response("db_query")
            await context.context.stream(ProgressUpdateEvent(text=f"Database error"))
            return f"Error: {error_response}"

    # Parse filters
    try:
        filter_dict = json.loads(filters) if filters and filters != "{}" else {}
    except json.JSONDecodeError as e:
        return f"Error: Invalid filter format. Please use valid JSON. Details: {e}"

    # Execute query
    db = get_database()
    try:
        results = db.query(table, filter_dict)
    except Exception as e:
        return f"Error querying {table}: {e}"

    if not results:
        return f"No records found in {table} with filters: {filters}"

    # Format response
    response = json.dumps(results, ensure_ascii=False, indent=2)

    # Check for content injection (attack testing)
    if injector and injector.should_inject("db_query"):
        response = injector.inject("db_query", response)

    await context.context.stream(ProgressUpdateEvent(text=f"Found {len(results)} records"))
    return response


@function_tool(
    name_override="db_get_customer",
    description_override="Get customer details by customer ID or email"
)
async def db_get_customer(
    context: RunContextWrapper[AirlineAgentChatContext],
    customer_id: Optional[str] = None,
    email: Optional[str] = None
) -> str:
    """
    Get customer information.

    Args:
        customer_id: Customer ID (e.g., "C001")
        email: Customer email address

    Returns:
        Customer details or error message
    """
    if not customer_id and not email:
        return "Error: Please provide either customer_id or email"

    filters = {}
    if customer_id:
        filters["id"] = customer_id
    if email:
        filters["email"] = email

    return await db_query(context, "customers", json.dumps(filters))


@function_tool(
    name_override="db_get_booking",
    description_override="Get booking details by confirmation number"
)
async def db_get_booking(
    context: RunContextWrapper[AirlineAgentChatContext],
    confirmation_number: str
) -> str:
    """
    Get booking by confirmation number.

    Args:
        confirmation_number: Booking confirmation number (e.g., "ABC123")

    Returns:
        Booking details or error message
    """
    return await db_query(context, "bookings", json.dumps({"confirmation_number": confirmation_number}))


@function_tool(
    name_override="db_get_flight",
    description_override="Get flight details by flight number"
)
async def db_get_flight(
    context: RunContextWrapper[AirlineAgentChatContext],
    flight_number: str
) -> str:
    """
    Get flight information.

    Args:
        flight_number: Flight number (e.g., "CA1234")

    Returns:
        Flight details including status, gate, times
    """
    return await db_query(context, "flights", json.dumps({"flight_number": flight_number}))


@function_tool(
    name_override="db_update",
    description_override="Update a database record"
)
async def db_update(
    context: RunContextWrapper[AirlineAgentChatContext],
    table: str,
    record_id: str,
    updates: str
) -> str:
    """
    Update a database record.

    Args:
        table: Table name (customers, flights, bookings, seats)
        record_id: ID of the record to update
        updates: JSON string of fields to update
                 Example: '{"status": "cancelled", "cancel_reason": "Customer request"}'

    Returns:
        Success or error message
    """
    await context.context.stream(ProgressUpdateEvent(text=f"Updating {table}/{record_id}..."))

    # Get fault injector
    injector = getattr(context.context.state, 'fault_injector', None)
    if injector and injector.should_fail("db_update"):
        return f"Error: {injector.get_failure_response('db_update')}"

    try:
        update_dict = json.loads(updates)
    except json.JSONDecodeError as e:
        return f"Error: Invalid update format. Please use valid JSON. Details: {e}"

    db = get_database()
    success = db.update(table, record_id, update_dict)

    if success:
        await context.context.stream(ProgressUpdateEvent(text=f"Updated {record_id}"))
        return f"Successfully updated record {record_id} in {table}"
    else:
        return f"Error: Record {record_id} not found in {table}"


@function_tool(
    name_override="db_insert",
    description_override="Insert a new record into the database"
)
async def db_insert(
    context: RunContextWrapper[AirlineAgentChatContext],
    table: str,
    record: str
) -> str:
    """
    Insert a new record.

    Args:
        table: Table name (customers, flights, bookings, seats)
        record: JSON string of the new record

    Returns:
        Created record ID or error message
    """
    await context.context.stream(ProgressUpdateEvent(text=f"Inserting into {table}..."))

    try:
        record_dict = json.loads(record)
    except json.JSONDecodeError as e:
        return f"Error: Invalid record format. Please use valid JSON. Details: {e}"

    db = get_database()
    record_id = db.insert(table, record_dict)

    await context.context.stream(ProgressUpdateEvent(text=f"Created {record_id}"))
    return f"Successfully created record with ID: {record_id}"


# ============= Knowledge Base Tools =============

@function_tool(
    name_override="kb_search",
    description_override="Search the knowledge base for policies, FAQs, and procedures"
)
async def kb_search(
    context: RunContextWrapper[AirlineAgentChatContext],
    query: str,
    top_k: int = 3
) -> str:
    """
    Search knowledge base for relevant information.

    Args:
        query: Natural language search query (e.g., "退票政策", "行李丢失怎么办")
        top_k: Maximum number of results to return (default: 3)

    Returns:
        Relevant policies, FAQs, or procedures
    """
    await context.context.stream(ProgressUpdateEvent(text=f"Searching knowledge base..."))

    # Get fault injector
    injector = getattr(context.context.state, 'fault_injector', None)

    # Check for delay injection
    if injector:
        delay = injector.inject_delay("kb_search")
        if delay > 0:
            await asyncio.sleep(delay)

        if injector.should_fail("kb_search"):
            return f"Error: {injector.get_failure_response('kb_search')}"

    kb = get_knowledge_base()
    results = kb.search(query, top_k)

    if not results:
        return "No relevant information found in knowledge base for your query."

    # Format output
    output_lines = []
    for i, result in enumerate(results, 1):
        doc_type = result["type"]

        if doc_type == "policy":
            output_lines.append(f"{i}. [Policy] {result['title']}")
            output_lines.append(f"   Category: {result.get('category', 'general')}")
            output_lines.append(f"   {result['content']}")
        elif doc_type == "faq":
            output_lines.append(f"{i}. [FAQ] {result['question']}")
            output_lines.append(f"   {result['answer']}")
        elif doc_type == "procedure":
            output_lines.append(f"{i}. [Procedure] {result['name']}")
            steps = result.get('steps', [])
            for step in steps[:5]:  # Show first 5 steps
                output_lines.append(f"   {step}")
            if len(steps) > 5:
                output_lines.append(f"   ... and {len(steps) - 5} more steps")

        output_lines.append("")

    response = "\n".join(output_lines)

    # Check for content injection (attack testing)
    if injector and injector.should_inject("kb_search"):
        response = injector.inject("kb_search", response)

    await context.context.stream(ProgressUpdateEvent(text=f"Found {len(results)} relevant documents"))
    return response


@function_tool(
    name_override="kb_get_policy",
    description_override="Get a specific policy by category"
)
async def kb_get_policy(
    context: RunContextWrapper[AirlineAgentChatContext],
    category: str
) -> str:
    """
    Get policy for a specific category.

    Args:
        category: Policy category (refund, baggage, compensation, change, special_services, membership)

    Returns:
        Policy details
    """
    return await kb_search(context, category, top_k=1)


# ============= MCP Service Tools =============

@function_tool(
    name_override="mcp_call",
    description_override="Call an external service via MCP (email, payment, calendar)"
)
async def mcp_call(
    context: RunContextWrapper[AirlineAgentChatContext],
    service: str,
    action: str,
    params: str = "{}"
) -> str:
    """
    Call external MCP service.

    Args:
        service: Service name - one of: email, payment, calendar
        action: Action to perform:
                - email: send, check_status
                - payment: charge, refund, check_balance
                - calendar: create_event, send_reminder, check_conflicts
        params: JSON string of parameters for the action

    Returns:
        Service response or error message
    """
    await context.context.stream(ProgressUpdateEvent(text=f"Calling {service}.{action}..."))

    # Get fault injector
    injector = getattr(context.context.state, 'fault_injector', None)

    # Check for delay/failure injection
    if injector:
        delay = injector.inject_delay("mcp_call")
        if delay > 0:
            await asyncio.sleep(delay)

        if injector.should_fail("mcp_call"):
            return f"Error: {injector.get_failure_response('mcp_call')}"

    # Parse params
    try:
        params_dict = json.loads(params) if params and params != "{}" else {}
    except json.JSONDecodeError as e:
        return f"Error: Invalid params format. Please use valid JSON. Details: {e}"

    # Call service
    mcp = get_mcp_bridge()
    result = mcp.call(service, action, params_dict)

    if result.get("error"):
        return f"MCP Error [{result.get('code', 'unknown')}]: {result.get('message', 'Unknown error')}"

    response = json.dumps(result, ensure_ascii=False, indent=2)

    # Check for content injection
    if injector and injector.should_inject("mcp_call"):
        response = injector.inject("mcp_call", response)

    await context.context.stream(ProgressUpdateEvent(text=f"{service}.{action} completed"))
    return response


@function_tool(
    name_override="send_email",
    description_override="Send an email notification to the customer"
)
async def send_email(
    context: RunContextWrapper[AirlineAgentChatContext],
    to_email: str,
    subject: str,
    body: str
) -> str:
    """
    Send email to customer.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        body: Email body content

    Returns:
        Send confirmation with message ID
    """
    params = json.dumps({
        "to": to_email,
        "subject": subject,
        "body": body
    })
    return await mcp_call(context, "email", "send", params)


@function_tool(
    name_override="process_payment",
    description_override="Process a payment charge"
)
async def process_payment(
    context: RunContextWrapper[AirlineAgentChatContext],
    amount: float,
    payment_token: str,
    description: str
) -> str:
    """
    Process payment charge.

    Args:
        amount: Amount to charge
        payment_token: Payment method token (from customer record)
        description: Payment description

    Returns:
        Transaction confirmation or error
    """
    params = json.dumps({
        "amount": amount,
        "token": payment_token,
        "description": description
    })
    return await mcp_call(context, "payment", "charge", params)


@function_tool(
    name_override="process_refund",
    description_override="Process a refund to customer"
)
async def process_refund(
    context: RunContextWrapper[AirlineAgentChatContext],
    amount: float,
    original_transaction_id: str,
    reason: str
) -> str:
    """
    Process refund.

    Args:
        amount: Refund amount
        original_transaction_id: Original transaction ID to refund
        reason: Reason for refund

    Returns:
        Refund confirmation with estimated days
    """
    params = json.dumps({
        "amount": amount,
        "original_transaction_id": original_transaction_id,
        "reason": reason
    })
    return await mcp_call(context, "payment", "refund", params)


@function_tool(
    name_override="create_calendar_event",
    description_override="Create a calendar event for the customer's flight"
)
async def create_calendar_event(
    context: RunContextWrapper[AirlineAgentChatContext],
    title: str,
    start_time: str,
    end_time: str,
    location: str = "",
    description: str = ""
) -> str:
    """
    Create calendar event for flight.

    Args:
        title: Event title (e.g., "Flight CA1234 to Shanghai")
        start_time: ISO format start time
        end_time: ISO format end time
        location: Optional location (e.g., "Beijing Capital Airport")
        description: Optional event description

    Returns:
        Created event details with calendar link
    """
    params = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time
    }
    if location:
        params["location"] = location
    if description:
        params["description"] = description

    return await mcp_call(context, "calendar", "create_event", json.dumps(params))
