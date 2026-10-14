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
  path/query. Entities are decoded, text normalised and every control / separator character collapsed to a space
  first (so tokens agree with what a renderer sees); raw HTML, reference definitions and images are neutralised
  structurally; every other link-like token (autolinkable scheme, `//`, `www.`, `@`, or a non-allowlisted dotted
  name a fuzzy linkifier would link) is replaced as a whole by `[link removed]`. Callers cap the answer with
  `truncate_answer` first.
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
# Structural, whole-token validation (never approve a prefix). Tokenisation must agree with every renderer, so the
# text is canonicalised first and every later step works on exactly the string the renderer will see:
# 1. decode HTML entities, NFKC-normalise, map every control / separator character (Unicode Cc, Zs, Zl, Zp and
#    anything `str.isspace` accepts) except `\n` to an ASCII space and delete every format character (Cf:
#    zero-width, bidi, soft hyphen ...) and replace every Cn / Co / Cs code point with U+FFFD (Python's Unicode
#    database may be older than the renderer's, which can treat them as letters); repeat until stable (bounded; if it never stabilises every `&` is escaped).
#    Afterwards the only whitespace left is ` ` and `\n`, which every renderer treats as a link terminator;
# 2. neutralise ALL raw HTML: every `<` / `>` becomes the visible `‹` / `›`;
# 3. neutralise ALL reference definitions (`]` + optional whitespace + `:` is broken) and demote `![` to `[`;
# 4. inline links `[text](destination)` (destination may hold balanced parentheses) are kept only when the WHOLE
#    destination matches the strict grammar below; otherwise the link becomes `text [link removed]`; every other
#    `](` is split to `] (`, which CommonMark never parses as a link;
# 5. every other token (split on ` ` / `\n` only) that a renderer could link is validated as a whole: after
#    trimming trailing sentence punctuation, one unbalanced closing `)` and one leading `(`, it must fully match
#    the strict grammar (with no second `//` or `www.` after the host), or the whole token becomes `[link removed]`.
#    A token is link-like when it contains an autolinkable or dangerous scheme (`http(s):`, `ftp:`, `mailto:`,
#    `xmpp:`, `javascript:`, `vbscript:`, `data:`, `file:`), `//`, `www.`, an `@` in a token with any alphanumeric
#    text, or a dotted name with a TLD-like label (or a dotted quad) that is not an allowlisted host - fuzzy
#    linkifiers such as linkify-it turn `evil.com` into a link. `label:value` text such as `PNR:1234` or
#    `Time:10:00` is not link-like.
#
# Strict grammar: `https://` + an allowlisted host (dot-separated ASCII labels of letters, digits and inner hyphens)
# + optional path, query and fragment made only of `A-Za-z0-9-._~/?#=&%+`. No userinfo, port, quotes, brackets,
# parentheses, backticks, backslashes or `@` anywhere, and no `%` in the host.
#
# Every regex is linear: literal alternations, possessive quantifiers and bounded repetitions only. Callers cap the
# answer length (`truncate_answer`) before sanitising.

MAX_ANSWER_CHARS = 8000
ELLIPSIS = "…"
_MAX_DECODE_PASSES = 10
_MAX_URL_CHARS = 2048
_SAFE_URL = re.compile(r"https://((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63})"
                       r"((?:[/?#][A-Za-z0-9\-._~/?#=&%+]*+)?)")
_LINKISH = re.compile(r"(?i)(?:https?|ftp|mailto|xmpp|javascript|vbscript|data|file):.|//|www\.")
_MD_LINK = re.compile(
    r"\[([^\[\]\n]{0,500}+)\]\( *+\n?+ *+((?:[^()\s]++|\([^()\s]*+\))*+)"
    r"(?: ++\n?+ *+(?:\"[^\"\n]*+\"|'[^'\n]*+'))?+ *+\n?+ *+\)")
_REF_DEF_COLON = re.compile(r"\]([ \n]*+):")
_IMAGE = re.compile(r"!++\[")
_TOKEN = re.compile(r"[^ \n]++")
_SENTENCE_PUNCT = ".,;:!?"
_PLACEHOLDER = re.compile(r"\x00(\d++)\x00")
_DOT_RUN = re.compile(r"\.{2,}+")
# File extensions that are not TLDs, so `ERS.pdf` or `PnrEnquiry.html` stay text.
_FILE_EXTENSIONS = frozenset({"pdf", "html", "htm", "jsp", "php", "aspx", "txt", "csv", "doc", "docx", "xls",
                              "xlsx", "png", "jpg", "jpeg", "gif"})


class _SeparatorMap(dict):
    """str.translate table: controls and separators (except newline) become a space, format characters vanish,
    unassigned / private-use / surrogate code points become U+FFFD (a newer Unicode may call them letters)."""

    def __missing__(self, code: int) -> int | str | None:
        ch = chr(code)
        category = unicodedata.category(ch)
        value: int | str | None = code
        if ch != "\n" and (category in ("Cc", "Zs", "Zl", "Zp") or ch.isspace()):
            value = " "
        elif category == "Cf":
            value = None
        elif category in ("Cn", "Co", "Cs"):  # unassigned here may be a letter to a newer renderer / browser
            value = "\ufffd"
        self[code] = value
        return value


class _LabelMap(dict):
    """str.translate table for host detection: label characters stay, dots become `.`, everything else a space.
    Linkifiers differ, so there are variants: symbols as separators or as label characters, and U+3002 as a
    separator (linkify-it) or as a dot (IDNA maps it to one)."""

    def __init__(self, symbols_are_labels: bool, ideographic_dot: bool) -> None:
        super().__init__()
        self._symbols = symbols_are_labels
        self._ideographic_dot = ideographic_dot

    def __missing__(self, code: int) -> int | str:
        ch = chr(code)
        value: int | str = code
        if ch == "." or (ch == "\u3002" and self._ideographic_dot):
            value = "."
        elif ch != "-":
            group = unicodedata.category(ch)[0]
            if not (group in "LMN" or (self._symbols and group == "S")):
                value = " "
        self[code] = value
        return value


_SEPARATORS = _SeparatorMap()
_LABEL_TABLES = tuple(_LabelMap(symbols, dot) for symbols in (False, True) for dot in (False, True))


def _allowed_match(url: str) -> re.Match | None:
    if not url or len(url) > _MAX_URL_CHARS:
        return None
    match = _SAFE_URL.fullmatch(url)
    if not match:
        return None
    host = match.group(1).lower()
    return match if any(host == d or host.endswith("." + d) for d in ALLOWED_URL_DOMAINS) else None


def is_allowed_url(url: str) -> bool:
    """True only when the whole string matches the strict grammar with an allowlisted host."""
    return _allowed_match(url) is not None


def truncate_answer(text: str, max_chars: int = MAX_ANSWER_CHARS) -> str:
    """Cap a model answer (before it is sanitised) so sanitising and rendering stay cheap."""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars] + ELLIPSIS


def _tld_like(label: str) -> bool:
    low = label.lower()
    if low.startswith("xn--"):
        return True
    if not low.isascii():
        return any(c.isalpha() for c in low)
    return len(low) >= 2 and low.isalpha() and low not in _FILE_EXTENSIONS


def _has_foreign_domain(token: str) -> bool:
    """A dotted name a fuzzy linkifier could link (TLD-like label or dotted quad) whose host is not allowlisted."""
    if "." not in token and "\u3002" not in token:
        return False
    for table in _LABEL_TABLES:
        for run in token.translate(table).split():
            for group in _DOT_RUN.split(run.strip(".")):
                labels = group.split(".")
                if len(labels) < 2 or is_allowed_url("https://" + group):
                    continue
                if any(_tld_like(label) for label in labels[1:]):
                    return True
                if len(labels) == 4 and all(label.isdigit() for label in labels):
                    return True
    return False


def _is_linkish(text: str) -> bool:
    if _LINKISH.search(text):
        return True
    if "@" in text and any(c.isalnum() for c in text):
        return True
    return _has_foreign_domain(text)


def _is_allowed_bare(url: str, tail: str) -> bool:
    """A bare URL a renderer will autolink: strict grammar, no second link start hidden after the host, and no `;`
    straight after the host (GFM keeps a trailing `;` in the link, which would then be part of the host)."""
    match = _allowed_match(url)
    if match is None:
        return False
    rest = match.group(2).lower()
    return "//" not in rest and "www." not in rest and (bool(rest) or ";" not in tail)


def _trim(token: str) -> tuple[str, str, str]:
    """(lead, core, tail): one leading `(`, trailing sentence punctuation and one unbalanced closing `)` (GFM
    trims exactly these; it keeps a trailing `]`, so a `]` is never trimmed)."""
    lead = ""
    if token.startswith("(") and token[1:].lower().startswith("https://"):
        lead, token = "(", token[1:]
    core = token.rstrip(_SENTENCE_PUNCT)
    if core.endswith(")") and core.count(")") > core.count("("):
        core = core[:-1].rstrip(_SENTENCE_PUNCT)
    return lead, core, token[len(core):]


def _check_token(match: re.Match) -> str:
    token = match.group(0)
    if not _is_linkish(_PLACEHOLDER.sub("", token)):
        return token
    if _PLACEHOLDER.search(token):  # a kept link glued to other link-like text: drop the whole token
        return LINK_REMOVED
    lead, core, tail = _trim(token)
    return token if _is_allowed_bare(core, tail) else lead + LINK_REMOVED + tail


def _strip_urls(text: str) -> str:
    return _TOKEN.sub(_check_token, text)


def _canonicalise(text: str) -> str:
    """Entity-decode, NFKC-normalise and collapse separators / drop format characters until stable."""
    for _ in range(_MAX_DECODE_PASSES):
        decoded = unicodedata.normalize("NFKC", html.unescape(text)).translate(_SEPARATORS)
        if decoded == text:
            return text
        text = decoded
    return text.replace("&", "&amp;")  # never stabilised: make sure no renderer decodes anything further


def sanitize_output(text: str) -> str:
    """Neutralise HTML, images and reference definitions and remove every link that is not an allowlisted https
    URL. Allowed inline links `[text](https://allowed/...)` are kept."""
    if not text:
        return text
    text = _canonicalise(text)
    text = text.replace("<", "‹").replace(">", "›")
    text = _REF_DEF_COLON.sub(lambda m: "]" + m.group(1) + " :", text)
    text = _IMAGE.sub("[", text)
    kept: list[str] = []

    def stash(match: re.Match) -> str:
        label = _strip_urls(match.group(1))
        destination = match.group(2)
        if is_allowed_url(destination):
            kept.append(f"[{label}]({destination})")
            return f"\x00{len(kept) - 1}\x00"
        return f"{label} {LINK_REMOVED}" if label.strip() else LINK_REMOVED

    stashed = _MD_LINK.sub(stash, text)
    # Neutralise again after the replacements (the `[link removed]` marker must never become a reference definition
    # or open a link): any remaining `](` could start an inline link, any `]:` a definition.
    cleaned = _strip_urls(stashed).replace("](", "] (")
    cleaned = _REF_DEF_COLON.sub(lambda m: "]" + m.group(1) + " :", cleaned)
    return _PLACEHOLDER.sub(lambda m: kept[int(m.group(1))], cleaned)
