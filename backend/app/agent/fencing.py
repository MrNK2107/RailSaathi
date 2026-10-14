"""Prompt-injection mitigations for the ticketing agent.

Everything a tool returns (knowledge-base text, third-party journey data) is untrusted from the model's point of
view. This module:

- `fence_tool_output`: serialises a tool result as JSON and wraps it in a delimited UNTRUSTED block. `<` and `>`
  are JSON-escaped (\\u003c / \\u003e), so content can never produce a literal delimiter, and any spelling of the
  delimiter keyword is removed. The payload is capped at `MAX_FENCED_CHARS`.
- `sanitize_tool_result`: maps tool errors to short typed codes (`ToolErrorCode`) so free text from a failing tool
  (which may echo model-chosen arguments) never reaches the model.
- `sanitize_output`: code-enforced allowlist for URLs in model output. Only https/http URLs on irctc.co.in,
  indianrail.gov.in and their subdomains survive; any other URL (bare, `www.`, autolink, markdown link or image,
  `javascript:`/`data:` URIs) is replaced by `[link removed]`. Markdown images are always removed (they load
  without a click and are a classic exfiltration channel).
"""

import json
import re
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

MAX_FENCED_CHARS = 8000
FENCE_KEYWORD = "UNTRUSTED_TOOL_OUTPUT"
FENCE_OPEN = "<<<" + FENCE_KEYWORD
FENCE_CLOSE = "<<<END_" + FENCE_KEYWORD + ">>>"
TRUNCATION_MARKER = "...[truncated]"
LINK_REMOVED = "[link removed]"

ALLOWED_URL_DOMAINS = ("irctc.co.in", "indianrail.gov.in")

_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Any spelling/spacing of the fence keyword (UNTRUSTED_TOOL_OUTPUT, untrusted tool output, Untrusted-Tool-Output...).
_KEYWORD = re.compile(r"untrusted[\s_\-]*tool[\s_\-]*output", re.IGNORECASE)


class ToolErrorCode(StrEnum):
    INVALID_ARGUMENTS = "invalid_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNAVAILABLE = "unavailable"
    TOOL_FAILED = "tool_failed"


def tool_error(code: ToolErrorCode) -> dict[str, str]:
    return {"status": "error", "error_code": code.value}


def sanitize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Successful results pass through; error results become `{"status": "error", "error_code": <code>}`."""
    if result.get("status") != "error":
        return result
    try:
        code = ToolErrorCode(result.get("error_code", ToolErrorCode.TOOL_FAILED))
    except ValueError:
        code = ToolErrorCode.TOOL_FAILED
    return tool_error(code)


def safe_tool_name(name: str) -> str:
    return name if isinstance(name, str) and _TOOL_NAME.match(name) else "unknown"


def _escape(text: str) -> str:
    return _KEYWORD.sub("[delimiter removed]", text.replace("<", "\\u003c").replace(">", "\\u003e"))


def fence_tool_output(name: str, result: dict[str, Any], max_chars: int = MAX_FENCED_CHARS) -> str:
    """The string the model sees for one tool result."""
    payload = _escape(json.dumps(result, ensure_ascii=False, default=str))
    truncated = len(payload) > max_chars
    if truncated:
        payload = payload[:max_chars] + TRUNCATION_MARKER
    header = f'{FENCE_OPEN} tool="{safe_tool_name(name)}" truncated="{str(truncated).lower()}">>>'
    return f"{header}\n{payload}\n{FENCE_CLOSE}"


# --- output URL allowlist -------------------------------------------------------------------------------------

_MD_LINK = re.compile(r"(!?)\[([^\]\n]{0,500})\]\(\s*<?([^)\s>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_BARE_URL = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]{1,20}://|\bwww\.|\b(?:javascript|data|vbscript|file):)[^\s<>()\[\]\"'`]*")
_TRAILING = ".,;:!?*_~"


def is_allowed_url(url: str) -> bool:
    """https/http, no credentials, no port, no backslash, host == or subdomain of an allowed domain."""
    if not url or "\\" in url or any(ord(ch) < 33 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() not in ("https", "http") or "@" in parts.netloc or port is not None:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_URL_DOMAINS)


def _md_link(match: re.Match) -> str:
    bang, text, url = match.groups()
    text = _BARE_URL.sub(_bare_url, text)
    if bang:  # images are never rendered
        return text or LINK_REMOVED
    if is_allowed_url(url):
        return f"[{text}]({url})"
    return f"{text} {LINK_REMOVED}" if text else LINK_REMOVED


def _bare_url(match: re.Match) -> str:
    raw = match.group(0)
    url = raw.rstrip(_TRAILING)
    tail = raw[len(url):]
    return (url if is_allowed_url(url) else LINK_REMOVED) + tail


def sanitize_output(text: str) -> str:
    """Strip every non-allowlisted URL from model output. Allowed markdown links are kept verbatim."""
    if not text:
        return text
    kept: list[str] = []

    def stash(match: re.Match) -> str:
        kept.append(_md_link(match))
        return f"\x00{len(kept) - 1}\x00"

    stashed = _MD_LINK.sub(stash, text.replace("\x00", ""))
    cleaned = _BARE_URL.sub(_bare_url, stashed)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], cleaned)
