"""Prompt-injection mitigations for the ticketing agent.

Everything a tool returns (knowledge-base text, third-party journey data) is untrusted from the model's point of
view. This module:

- `fence_tool_output`: serialises a tool result as JSON and wraps it in a delimited UNTRUSTED block. The payload is
  NFKC-normalised and stripped of zero-width characters (fullwidth / zero-width lookalikes collapse to ASCII), then
  `<` and `>` are JSON-escaped (\\u003c / \\u003e), so content can never produce a literal delimiter, and any
  spelling of the delimiter keyword is removed. The payload is capped at `MAX_FENCED_CHARS`.
- `sanitize_tool_result`: maps tool errors to short typed codes (`ToolErrorCode`) so free text from a failing tool
  (which may echo model-chosen arguments) never reaches the model.
- `sanitize_output`: code-enforced allowlist for URLs in model output (irctc.co.in, indianrail.gov.in,
  indianrailways.gov.in and subdomains, https only). It decodes entities and normalises first, then neutralises all
  raw HTML, reference definitions and images structurally, and replaces every other URL candidate with
  `[link removed]`. Bare domains without scheme, `//` or `www.` are not autolinked by GFM and are left as text.
"""

import html
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
#
# Structural, not vector-by-vector:
# 1. decode HTML entities until stable (bounded) and NFKC-normalise, so nothing hides behind `&sol;`, `&#47;`,
#    fullwidth or zero-width characters;
# 2. neutralise ALL raw HTML: every `<` / `>` becomes the visible `‹` / `›`, so no tag can survive or recombine;
# 3. neutralise ALL reference definitions: `]:` never survives (we never emit reference-style links), and `![`
#    is demoted to `[` so no image syntax remains;
# 4. inline links `[text](url)` keep only allowlisted targets; every other URL candidate - anything with a scheme,
#    every `//host` (also right after `:`), `www.` and `javascript:`/`data:`/`vbscript:`/`file:` - is replaced
#    unless it is an https URL whose authority is a plain ASCII hostname on an allowed domain.

_MAX_UNESCAPE_PASSES = 5
_MD_LINK = re.compile(r"\[([^\[\]\n]{0,500})\]\(\s*([^()\s]*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
_URL_BODY = r"[^\s<>()\[\]\"'`‹›]*"
_URL_CANDIDATE = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]*:)?//" + _URL_BODY
    + r"|\bwww\." + _URL_BODY
    + r"|\b(?:javascript|data|vbscript|file):" + _URL_BODY)
_REF_DEF_COLON = re.compile(r"\](\s*):")
_HOSTNAME = re.compile(r"^[A-Za-z0-9.-]+$")
_TRAILING = ".,;:!?*_~"


def is_allowed_url(url: str) -> bool:
    """https only (a protocol-relative `//host` is resolved as https). The authority must be a plain ASCII
    hostname (no userinfo, port, `&`, `%`, `\\` or other characters) equal to or under an allowed domain."""
    if not url or "\\" in url or not url.isascii() or any(ord(ch) < 33 for ch in url):
        return False
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or not _HOSTNAME.match(parts.netloc or ""):
        return False
    host = parts.netloc.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_URL_DOMAINS)


def _url_candidate(match: re.Match) -> str:
    raw = match.group(0)
    url = raw.rstrip(_TRAILING)
    tail = raw[len(url):]
    return (url if is_allowed_url(url) else LINK_REMOVED) + tail


def _strip_urls(text: str) -> str:
    return _URL_CANDIDATE.sub(_url_candidate, text)


def _decode(text: str) -> str:
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return normalise(text)


def sanitize_output(text: str) -> str:
    """Neutralise HTML, images and reference definitions, and remove every non-allowlisted URL from model output.
    Allowed inline links `[text](https://allowed/...)` are kept."""
    if not text:
        return text
    text = _decode(text.replace("\x00", "")).replace("\x00", "")
    text = text.replace("<", "‹").replace(">", "›")
    text = _REF_DEF_COLON.sub(lambda m: "]" + m.group(1) + " :", text)
    text = text.replace("![", "[")
    kept: list[str] = []

    def stash(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        label = _strip_urls(label)
        kept.append(f"[{label}]({url})" if is_allowed_url(url) else (f"{label} {LINK_REMOVED}" if label
                                                                    else LINK_REMOVED))
        return f"\x00{len(kept) - 1}\x00"

    stashed = _MD_LINK.sub(stash, text)
    cleaned = _strip_urls(stashed)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], cleaned)
