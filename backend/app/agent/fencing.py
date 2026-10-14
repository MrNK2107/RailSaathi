"""Prompt-injection mitigations for the ticketing agent.

Everything a tool returns (knowledge-base text, third-party journey data) is untrusted from the model's point of
view. This module:

- `fence_tool_output`: serialises a tool result as JSON and wraps it in a delimited UNTRUSTED block. The payload is
  NFKC-normalised and stripped of zero-width characters (fullwidth / zero-width lookalikes collapse to ASCII), then
  `<` and `>` are JSON-escaped (\\u003c / \\u003e), so content can never produce a literal delimiter, and any
  spelling of the delimiter keyword is removed. The payload is capped at `MAX_FENCED_CHARS`.
- `sanitize_tool_result`: maps tool errors to short typed codes (`ToolErrorCode`) so free text from a failing tool
  (which may echo model-chosen arguments) never reaches the model.
- `sanitize_output`: code-enforced allowlist for URLs in model output. Only https/http URLs on irctc.co.in,
  indianrail.gov.in, indianrailways.gov.in and their subdomains survive. Raw HTML tags and comments are removed;
  reference definitions pointing elsewhere are dropped; every image (inline or reference-style) is turned into text
  or a plain link (images load without a click and are a classic exfiltration channel); any other URL candidate
  (scheme URLs, protocol-relative `//host`, `www.`, autolinks, `javascript:`/`data:` URIs) becomes
  `[link removed]`. Bare domains without scheme, `//` or `www.` are not autolinked by GFM and are left as text.
"""

import json
import re
import unicodedata
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

MAX_FENCED_CHARS = 8000
FENCE_KEYWORD = "UNTRUSTED_TOOL_OUTPUT"
FENCE_OPEN = "<<<" + FENCE_KEYWORD
FENCE_CLOSE = "<<<END_" + FENCE_KEYWORD + ">>>"
TRUNCATION_MARKER = "...[truncated]"
LINK_REMOVED = "[link removed]"

ALLOWED_URL_DOMAINS = ("irctc.co.in", "indianrail.gov.in", "indianrailways.gov.in")

_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Any spelling/spacing of the fence keyword (UNTRUSTED_TOOL_OUTPUT, untrusted tool output, Untrusted-Tool-Output...).
_KEYWORD = re.compile(r"untrusted[\s_\-]*tool[\s_\-]*output", re.IGNORECASE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


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


def normalise(text: str) -> str:
    """NFKC plus removal of zero-width characters."""
    return unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)


def _escape(text: str) -> str:
    text = normalise(text).replace("<", "\\u003c").replace(">", "\\u003e")
    return _KEYWORD.sub("[delimiter removed]", text)


def fence_tool_output(name: str, result: dict[str, Any], max_chars: int = MAX_FENCED_CHARS) -> str:
    """The string the model sees for one tool result."""
    payload = _escape(json.dumps(result, ensure_ascii=False, default=str))
    truncated = len(payload) > max_chars
    if truncated:
        payload = payload[:max_chars] + TRUNCATION_MARKER
    header = f'{FENCE_OPEN} tool="{safe_tool_name(name)}" truncated="{str(truncated).lower()}">>>'
    return f"{header}\n{payload}\n{FENCE_CLOSE}"


# --- output URL allowlist -------------------------------------------------------------------------------------

_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# Any raw HTML tag (also an unterminated one at the end of a line). Autolinks (<https://...>) do not match because
# the "tag name" is followed by ':'.
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?=[\s/>]|$)[^<>\n]*>?")
_REF_DEF = re.compile(r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*<?([^\s>]*)>?.*$", re.MULTILINE)
_MD_LINK = re.compile(r"(!?)\[([^\]\n]{0,500})\]\(\s*<?([^)\s>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_BARE_URL = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]{1,20}://|(?<![\w:/])//(?=[a-z0-9\[])|\bwww\.|\b(?:javascript|data|vbscript|file):)"
    r"[^\s<>()\[\]\"'`]*")
_TRAILING = ".,;:!?*_~"


def is_allowed_url(url: str) -> bool:
    """https/http (protocol-relative `//host` is resolved as https), no credentials, no port, no backslash, and the
    host equals or is a subdomain of an allowed domain."""
    if not url or "\\" in url or any(ord(ch) < 33 for ch in url):
        return False
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() not in ("https", "http") or "@" in parts.netloc or port is not None:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_URL_DOMAINS)


def _bare_url(match: re.Match) -> str:
    raw = match.group(0)
    url = raw.rstrip(_TRAILING)
    tail = raw[len(url):]
    return (url if is_allowed_url(url) else LINK_REMOVED) + tail


def _strip_urls(text: str) -> str:
    return _BARE_URL.sub(_bare_url, text)


def _md_link(match: re.Match) -> str:
    bang, text, url = match.groups()
    text = _strip_urls(text)
    if bang:  # images are never rendered
        return text or LINK_REMOVED
    if is_allowed_url(url):
        return f"[{text}]({url})"
    return f"{text} {LINK_REMOVED}" if text else LINK_REMOVED


def _ref_def(match: re.Match) -> str:
    return match.group(0) if is_allowed_url(match.group(1)) else ""


def sanitize_output(text: str) -> str:
    """Strip raw HTML, images and every non-allowlisted URL from model output. Allowed links are kept verbatim."""
    if not text:
        return text
    text = text.replace("\x00", "")
    text = _HTML_TAG.sub("", _HTML_COMMENT.sub("", text))
    text = _REF_DEF.sub(_ref_def, text)
    kept: list[str] = []

    def stash(match: re.Match) -> str:
        kept.append(_md_link(match))
        return f"\x00{len(kept) - 1}\x00"

    stashed = _MD_LINK.sub(stash, text)
    stashed = stashed.replace("![", "[")  # reference-style and shortcut images become links/text, never images
    cleaned = _strip_urls(stashed)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], cleaned)
