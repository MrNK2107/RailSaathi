"""Prompt-injection mitigations for the ticketing agent.

Everything a tool returns (knowledge-base text, third-party journey data) is untrusted from the model's point of
view. This module:

- `fence_tool_output`: serialises a tool result as JSON and wraps it in a delimited UNTRUSTED block. The payload is
  NFKC-normalised and stripped of zero-width characters (fullwidth / zero-width lookalikes collapse to ASCII), then
  `<` and `>` are JSON-escaped (\\u003c / \\u003e), so content can never produce a literal delimiter, and any
  spelling of the delimiter keyword is removed. The payload is capped at `MAX_FENCED_CHARS`.
- `sanitize_tool_result`: maps tool errors to short typed codes (`ToolErrorCode`) so free text from a failing tool
  (which may echo model-chosen arguments) never reaches the model.
- `sanitize_output`: code-enforced allowlist for links in model output. A link survives only if the whole URL is
  `https://` + a host on irctc.co.in / indianrail.gov.in / indianrailways.gov.in (or a subdomain) + a plain
  path/query. Entities are decoded and text normalised first; raw HTML, reference definitions and images are
  neutralised structurally; every other link-like token (scheme, `//`, `www.`, e-mail) is replaced as a whole by
  `[link removed]`. Bare domains without any of those markers are not autolinked by GFM and stay as text.
"""

import html
import json
import re
import unicodedata
from enum import StrEnum
from typing import Any

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
# Structural, whole-token validation (never approve a prefix):
# 1. decode HTML entities until stable (bounded) and NFKC-normalise, so nothing hides behind `&sol;`, `&#47;`,
#    fullwidth or zero-width characters;
# 2. neutralise ALL raw HTML: every `<` / `>` becomes the visible `‹` / `›`;
# 3. neutralise ALL reference definitions (`]` + optional whitespace + `:` is broken) and demote `![` to `[`;
# 4. inline links `[text](destination)` (destination may hold balanced parentheses) are kept only when the WHOLE
#    destination matches the strict grammar below; otherwise the link becomes `text [link removed]`;
# 5. every other whitespace-delimited token that a renderer could link (contains a scheme, `//`, `www.`, or
#    `@` followed by a dotted name) is validated as a whole: after trimming trailing sentence punctuation, one
#    unbalanced closing `)`/`]` and one leading `(`, it must fully match the strict grammar, or the whole token is
#    replaced by `[link removed]`.
#
# Strict grammar: `https://` + an allowlisted host (dot-separated ASCII labels of letters, digits and inner hyphens) + optional path, query
# and fragment made only of `A-Za-z0-9-._~/?#=&%+`. No userinfo, port, quotes, brackets, parentheses, backticks,
# backslashes or `@` anywhere.

_MAX_UNESCAPE_PASSES = 5
_SAFE_URL = re.compile(r"https://((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,})"
                       r"(?:[/?#][A-Za-z0-9\-._~/?#=&%+]*)?")
_LINKISH = re.compile(r"(?i)[a-z][a-z0-9+.\-]*:\S|//|www\.|@[^\s@]*[A-Za-z0-9-]\.[A-Za-z0-9]")
_MD_LINK = re.compile(
    r"\[([^\[\]\n]{0,500})\]\(\s*((?:[^()\s]|\([^()\s]*\))*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
_REF_DEF_COLON = re.compile(r"\](\s*):")
_TOKEN = re.compile(r"\S+")
_SENTENCE_PUNCT = ".,;:!?"
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")


def is_allowed_url(url: str) -> bool:
    """True only when the whole string matches the strict grammar with an allowlisted host."""
    match = _SAFE_URL.fullmatch(url or "")
    if not match:
        return False
    host = match.group(1).lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_URL_DOMAINS)


def _trim(token: str) -> tuple[str, str, str]:
    """(lead, core, tail): one leading `(`, trailing sentence punctuation and one unbalanced closing `)`/`]`."""
    lead = ""
    if token.startswith("(") and token[1:].lower().startswith("https://"):
        lead, token = "(", token[1:]
    core = token.rstrip(_SENTENCE_PUNCT)
    for close, open_ in ((")", "("), ("]", "[")):
        if core.endswith(close) and core.count(close) > core.count(open_):
            core = core[:-1]
            break
    core = core.rstrip(_SENTENCE_PUNCT)
    return lead, core, token[len(core):]


def _check_token(match: re.Match) -> str:
    token = match.group(0)
    visible = _PLACEHOLDER.sub("", token)
    if not _LINKISH.search(visible):
        return token
    if _PLACEHOLDER.search(token):  # a kept link glued to other link-like text: drop the whole token
        return LINK_REMOVED
    lead, core, tail = _trim(token)
    return token if is_allowed_url(core) else lead + LINK_REMOVED + tail


def _strip_urls(text: str) -> str:
    return _TOKEN.sub(_check_token, text)


def _decode(text: str) -> str:
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return normalise(text)


def sanitize_output(text: str) -> str:
    """Neutralise HTML, images and reference definitions and remove every link that is not an allowlisted https
    URL. Allowed inline links `[text](https://allowed/...)` are kept."""
    if not text:
        return text
    text = _decode(text.replace("\x00", "")).replace("\x00", "")
    text = text.replace("<", "‹").replace(">", "›")
    text = _REF_DEF_COLON.sub(lambda m: "]" + m.group(1) + " :", text)
    text = text.replace("![", "[")
    kept: list[str] = []

    def stash(match: re.Match) -> str:
        label = _strip_urls(match.group(1))
        destination = match.group(2)
        if is_allowed_url(destination):
            kept.append(f"[{label}]({destination})")
            return f"\x00{len(kept) - 1}\x00"
        return f"{label} {LINK_REMOVED}" if label.strip() else LINK_REMOVED

    stashed = _MD_LINK.sub(stash, text)
    cleaned = _strip_urls(stashed)
    return _PLACEHOLDER.sub(lambda m: kept[int(m.group(1))], cleaned)
