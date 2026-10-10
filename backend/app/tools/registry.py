"""
RailSathi AI — Unified Tool Registry

Aggregates both Ticketing Guidance and Goal-Based Journey Planning tools.
Provides unified validation, schema declaration, and execution dispatching.
"""

from typing import Any
from app.tools.ticketing import (
    TOOL_SCHEMAS as TICKETING_TOOL_SCHEMAS,
    validate_tool_args as validate_ticketing_args,
    execute_tool as execute_ticketing_tool,
)
from app.tools.journey_tools import (
    JOURNEY_TOOL_SCHEMAS,
    validate_journey_tool_args,
    execute_journey_tool,
)

# Combined tool schema dictionary
ALL_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    **TICKETING_TOOL_SCHEMAS,
    **JOURNEY_TOOL_SCHEMAS,
}


def get_all_tool_names() -> list[str]:
    """Return all registered tool names across all modules."""
    return list(ALL_TOOL_SCHEMAS.keys())


def get_all_tool_schemas() -> dict[str, dict[str, Any]]:
    """Return combined schema dictionary for all tools."""
    return ALL_TOOL_SCHEMAS


def validate_any_tool_args(tool_name: str, args: dict) -> tuple[bool, str | None]:
    """Validate arguments for any registered tool."""
    if tool_name in TICKETING_TOOL_SCHEMAS:
        return validate_ticketing_args(tool_name, args)
    elif tool_name in JOURNEY_TOOL_SCHEMAS:
        return validate_journey_tool_args(tool_name, args)
    return False, f"Unknown tool: '{tool_name}'"


def execute_any_tool(tool_name: str, args: dict, db_path: str) -> dict[str, Any]:
    """Dispatch tool execution to the appropriate module."""
    if tool_name in TICKETING_TOOL_SCHEMAS:
        return execute_ticketing_tool(tool_name, args, db_path)
    elif tool_name in JOURNEY_TOOL_SCHEMAS:
        return execute_journey_tool(tool_name, args)
    return {"status": "error", "error": f"No handler registered for tool: {tool_name}"}
