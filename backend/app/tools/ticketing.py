"""
RailSathi AI — Ticketing Guidance Tools

Narrowly scoped, read-only tools that the agent controller can invoke.
Each tool has an explicit schema, validates its inputs, and returns
structured results with source provenance.
"""

import logging
from typing import Any
from app.knowledge.retrieval import search_guidance, SUPPORTED_TOPICS

# Valid class codes for ticket_class tool
VALID_CLASS_CODES = {"SL", "3A", "2A", "1A", "CC", "3E", "2S", "GN", "EA", "EC"}

# Valid status codes for reservation_status tool
VALID_STATUS_CODES = {"CNF", "RAC", "WL", "GNWL", "RLWL", "PQWL", "CAN", "CONFIRMED", "WAITLISTED"}

# Valid booking channels
VALID_BOOKING_CHANNELS = {"irctc_online", "counter", "agent"}

# Tool schemas for Gemini function calling
TOOL_SCHEMAS = {
    "search_ticketing_guidance": {
        "name": "search_ticketing_guidance",
        "description": (
            "Search the RailSathi knowledge base for Indian Railways ticketing guidance. "
            "Use this for general questions about railway ticketing, policies, or procedures."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The passenger's ticketing question or search terms.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic filter.",
                    "enum": SUPPORTED_TOPICS,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (1-10). Default is 5.",
                },
            },
            "required": ["query"],
        },
    },
    "explain_ticket_class": {
        "name": "explain_ticket_class",
        "description": (
            "Explain the characteristics of a specific Indian Railways ticket class "
            "(e.g., SL, 3A, 2A, 1A, CC). Can also compare two classes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "class_code": {
                    "type": "string",
                    "description": "The ticket class code (e.g., SL, 3A, 2A, 1A, CC, 3E).",
                },
                "comparison_class": {
                    "type": "string",
                    "description": "Optional second class code for comparison.",
                },
            },
            "required": ["class_code"],
        },
    },
    "explain_reservation_status": {
        "name": "explain_reservation_status",
        "description": (
            "Explain a reservation status code such as CNF (Confirmed), "
            "RAC (Reservation Against Cancellation), or WL (Waitlisted)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status_code": {
                    "type": "string",
                    "description": "The reservation status code (e.g., CNF, RAC, WL, GNWL, RLWL, PQWL).",
                },
                "question": {
                    "type": "string",
                    "description": "Optional additional context or specific question about this status.",
                },
            },
            "required": ["status_code"],
        },
    },
    "get_booking_steps": {
        "name": "get_booking_steps",
        "description": (
            "Retrieve the official ticket booking procedure for a specific channel "
            "(e.g., IRCTC online, railway station counter)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_channel": {
                    "type": "string",
                    "description": "The booking channel: 'irctc_online' or 'counter'.",
                    "enum": ["irctc_online", "counter"],
                },
                "question": {
                    "type": "string",
                    "description": "Optional specific question about the booking process.",
                },
                "ticket_type": {
                    "type": "string",
                    "description": "Optional ticket type (e.g., 'general', 'tatkal').",
                },
            },
            "required": ["booking_channel"],
        },
    },
    "get_cancellation_refund_guidance": {
        "name": "get_cancellation_refund_guidance",
        "description": (
            "Retrieve cancellation and refund rules applicable to a specific question "
            "or ticket category."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The passenger's cancellation or refund question.",
                },
                "ticket_category": {
                    "type": "string",
                    "description": "Optional ticket category (e.g., 'general', 'tatkal', 'premium').",
                },
                "booking_channel": {
                    "type": "string",
                    "description": "Optional booking channel ('irctc_online' or 'counter').",
                },
            },
            "required": ["question"],
        },
    },
}


def validate_tool_args(tool_name: str, args: dict) -> tuple[bool, str | None]:
    """
    Validate tool arguments against the schema.

    Returns:
        (is_valid, error_message) — error_message is None if valid.
    """
    if tool_name not in TOOL_SCHEMAS:
        return False, f"Unknown tool: {tool_name}"

    schema = TOOL_SCHEMAS[tool_name]
    required = schema["parameters"].get("required", [])
    properties = schema["parameters"]["properties"]

    # Check required fields
    for field in required:
        if field not in args or not args[field]:
            return False, f"Missing required argument: {field}"

    # Check field types and values
    for key, value in args.items():
        if key not in properties:
            continue  # Ignore unknown fields

        prop = properties[key]
        if prop["type"] == "string" and not isinstance(value, str):
            return False, f"Argument '{key}' must be a string"
        if prop["type"] == "integer" and not isinstance(value, (int, float)):
            return False, f"Argument '{key}' must be an integer"
        if "enum" in prop and value not in prop["enum"]:
            return False, f"Argument '{key}' must be one of {prop['enum']}"

    # Input size limits
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 500:
            return False, f"Argument '{key}' exceeds maximum length (500 chars)"

    return True, None


def execute_tool(tool_name: str, args: dict, db_path: str) -> dict[str, Any]:
    """
    Execute a registered tool with validated arguments.

    Returns a structured result dict.
    """
    # Validate first
    is_valid, error = validate_tool_args(tool_name, args)
    if not is_valid:
        return {
            "status": "error",
            "error": error,
            "tool_name": tool_name,
        }

    # Dispatch to the appropriate handler
    handlers = {
        "search_ticketing_guidance": _handle_search,
        "explain_ticket_class": _handle_ticket_class,
        "explain_reservation_status": _handle_reservation_status,
        "get_booking_steps": _handle_booking_steps,
        "get_cancellation_refund_guidance": _handle_cancellation_refund,
    }

    handler = handlers.get(tool_name)
    if not handler:
        return {
            "status": "error",
            "error": f"No handler for tool: {tool_name}",
            "tool_name": tool_name,
        }

    try:
        result = handler(args, db_path)
        result["tool_name"] = tool_name
        return result
    except Exception:
        logging.getLogger("railsaathi.ticketing").exception("Ticketing tool %s failed", tool_name)
        return {
            "status": "error",
            "error": "Tool execution failed.",
            "tool_name": tool_name,
        }


def _handle_search(args: dict, db_path: str) -> dict:
    """Handle search_ticketing_guidance tool."""
    query = args["query"]
    topic = args.get("topic")
    limit = min(int(args.get("limit", 5)), 10)

    result = search_guidance(db_path, query, topic=topic, limit=limit)
    result["status"] = "success" if result["retrieval_status"] == "success" else "error"
    return result


def _handle_ticket_class(args: dict, db_path: str) -> dict:
    """Handle explain_ticket_class tool."""
    class_code = args["class_code"].upper().strip()
    comparison_class = args.get("comparison_class", "").upper().strip() or None

    if class_code not in VALID_CLASS_CODES:
        return {
            "status": "error",
            "error": f"Unsupported class code: {class_code}. Known codes: {sorted(VALID_CLASS_CODES)}",
        }

    if comparison_class and comparison_class not in VALID_CLASS_CODES:
        return {
            "status": "error",
            "error": f"Unsupported comparison class code: {comparison_class}. Known codes: {sorted(VALID_CLASS_CODES)}",
        }

    # Search for the primary class
    primary = search_guidance(db_path, class_code, topic="ticket_class", limit=3)

    result = {
        "status": "success",
        "primary_class": {
            "class_code": class_code,
            "results": primary.get("results", []),
            "evidence_sufficient": primary.get("evidence_sufficient", False),
        },
        "sources": primary.get("sources", []),
        "evidence_sufficient": primary.get("evidence_sufficient", False),
        "any_stale": primary.get("any_stale", False),
    }

    # If comparison requested, search for the second class
    if comparison_class:
        secondary = search_guidance(db_path, comparison_class, topic="ticket_class", limit=3)
        result["comparison_class"] = {
            "class_code": comparison_class,
            "results": secondary.get("results", []),
            "evidence_sufficient": secondary.get("evidence_sufficient", False),
        }
        result["sources"].extend(secondary.get("sources", []))
        result["evidence_sufficient"] = (
            primary.get("evidence_sufficient", False)
            and secondary.get("evidence_sufficient", False)
        )
        result["any_stale"] = primary.get("any_stale", False) or secondary.get("any_stale", False)

    if not result["evidence_sufficient"]:
        result["insufficiency_note"] = (
            f"Insufficient information found for class code '{class_code}'"
            + (f" or '{comparison_class}'" if comparison_class else "")
            + ". Information may not be available in the current knowledge base."
        )

    return result


def _handle_reservation_status(args: dict, db_path: str) -> dict:
    """Handle explain_reservation_status tool."""
    status_code = args["status_code"].upper().strip()
    question = args.get("question", "")

    # Normalize common aliases
    normalized = {
        "CONFIRMED": "CNF",
        "WAITLISTED": "WL",
    }.get(status_code, status_code)

    if normalized not in VALID_STATUS_CODES and status_code not in VALID_STATUS_CODES:
        return {
            "status": "error",
            "error": f"Unsupported status code: {status_code}. Known codes: {sorted(VALID_STATUS_CODES)}",
        }

    # Search for status explanation
    search_query = f"{normalized} {question}".strip()
    results = search_guidance(db_path, search_query, topic="reservation_status", limit=5)

    return {
        "status": "success",
        "status_code": normalized,
        "results": results.get("results", []),
        "sources": results.get("sources", []),
        "evidence_sufficient": results.get("evidence_sufficient", False),
        "any_stale": results.get("any_stale", False),
        "staleness_warning": results.get("staleness_warning"),
    }


def _handle_booking_steps(args: dict, db_path: str) -> dict:
    """Handle get_booking_steps tool."""
    channel = args["booking_channel"]
    question = args.get("question", "")
    ticket_type = args.get("ticket_type", "")

    search_query = f"book ticket {channel.replace('_', ' ')} {question} {ticket_type}".strip()
    results = search_guidance(db_path, search_query, topic="booking_process", limit=5)

    return {
        "status": "success",
        "booking_channel": channel,
        "results": results.get("results", []),
        "sources": results.get("sources", []),
        "evidence_sufficient": results.get("evidence_sufficient", False),
        "any_stale": results.get("any_stale", False),
        "official_url": "https://www.irctc.co.in" if channel == "irctc_online" else None,
        "disclaimer": "RailSathi provides guidance only. Complete your actual booking at the official IRCTC website or railway station.",
    }


def _handle_cancellation_refund(args: dict, db_path: str) -> dict:
    """Handle get_cancellation_refund_guidance tool."""
    question = args["question"]
    ticket_category = args.get("ticket_category", "")
    booking_channel = args.get("booking_channel", "")

    search_query = f"cancellation refund {question} {ticket_category} {booking_channel}".strip()
    results = search_guidance(db_path, search_query, topic="cancellation_refund", limit=5)

    return {
        "status": "success",
        "results": results.get("results", []),
        "sources": results.get("sources", []),
        "evidence_sufficient": results.get("evidence_sufficient", False),
        "any_stale": results.get("any_stale", False),
        "staleness_warning": results.get("staleness_warning"),
        "disclaimer": (
            "Cancellation charges and refund amounts are subject to change by Indian Railways. "
            "Always verify current rules at official sources before proceeding."
        ),
    }


def get_tool_names() -> list[str]:
    """Return the list of registered tool names."""
    return list(TOOL_SCHEMAS.keys())


def get_tool_schema(tool_name: str) -> dict | None:
    """Return the schema for a specific tool."""
    return TOOL_SCHEMAS.get(tool_name)
