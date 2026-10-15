"""AR guidance: `POST /api/navigation/localize` estimates where in the station a camera frame was taken.

A stateless query (nothing is written), so it fits the read-only navigation API. Hardening, in order:
1. multipart only, Content-Length required and checked against the limit before the body is read (the body-size
   middleware also enforces it while streaming);
2. a signed session (issued when none is sent) and the shared limiter: `localize_rate_limit` per session and
   `localize_ip_rate_limit` per client IP per `localize_rate_window_seconds`;
3. one JPEG or WebP part, size-checked and sniffed by magic bytes; the frame stays in memory.

Privacy: the frame is never stored or logged. Only the node id, confidence, latency and status are logged.
A model outage, a missing configuration or an unusable answer returns `status: "unavailable"`, never a 500.
"""

import logging
import re
import secrets
import time
from datetime import UTC

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.deps import offload
from app.api.middleware import client_ip
from app.api.navigation import _c, _station
from app.container import Container
from app.domain.enums import DataMode
from app.domain.options import DataProvenance
from app.harness.errors import PlannerError
from app.llm.base import Deadline, LLMError
from app.llm.vision import LocalizeHint, LocalizeResult, guard_result
from app.navigation.models.station import ELEMENT_ID_PATTERN, STATION_ID_PATTERN, Station
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken

log = logging.getLogger("railsaathi.localize")
router = APIRouter(tags=["Indoor Concourse Navigation"])

LOCALIZE_PATH = "/api/navigation/localize"
SOURCE = "gemini-vision"
APPROXIMATE_NOTE = ("Approximate: estimated from one camera frame against a schematic, unsurveyed layout. "
                    "Check the station signs and ask staff if unsure.")
LOW_CONFIDENCE_MESSAGE = "Not sure where you are. Pick your spot from the candidates, or point the camera at a sign."
UNAVAILABLE_MESSAGE = "Camera positioning is unavailable right now. Use the map to pick your position."
ALLOWED_TYPES = {"image/jpeg": "jpeg", "image/webp": "webp"}
MAX_ROUTE_NODES = 200
_STATION_RE = re.compile(STATION_ID_PATTERN)
_ELEMENT_RE = re.compile(ELEMENT_ID_PATTERN)


def _sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _session(c: Container, token: str | None) -> tuple[str, str]:
    if token is None:
        session_id = f"loc_{secrets.token_urlsafe(18)}"
        return session_id, c.signer.issue(session_id)
    try:
        return c.signer.verify(token), token
    except InvalidSessionToken as exc:
        raise PlannerError("invalid_session_token", "A valid session token is required.") from exc


async def _enforce_rate_limit(request: Request, c: Container, session_id: str) -> None:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    s = c.settings
    ip = client_ip(request.headers, request.scope, s.trusted_proxy_hops)
    for key, limit in ((f"loc:sid:{session_id}", s.localize_rate_limit), (f"loc:ip:{ip}", s.localize_ip_rate_limit)):
        decision = await offload(limiter.hit, key, limit, s.localize_rate_window_seconds)
        if not decision.allowed:
            raise HTTPException(429, {"code": "rate_limited",
                                      "message": "Too many camera fixes. Please wait a few minutes."},
                                headers={"Retry-After": str(decision.retry_after)})


async def _read_form(request: Request, max_body: int) -> FormData:
    """Parse the multipart body in memory: the spool limit is above the body limit, so nothing goes to disk."""
    parser = MultiPartParser(request.headers, request.stream(), max_files=1, max_fields=4, max_part_size=8192)
    parser.spool_max_size = max_body + 1
    try:
        return await parser.parse()
    except MultiPartException:
        raise HTTPException(400, {"code": "invalid_upload", "message": "The upload could not be read."}) from None


def _text_field(form: FormData, name: str, pattern: re.Pattern, required: bool = False) -> str | None:
    value = form.get(name)
    if value is None or value == "":
        if required:
            raise HTTPException(422, {"code": "invalid_request", "message": f"{name} is required."})
        return None
    if not isinstance(value, str) or not pattern.match(value):
        raise HTTPException(422, {"code": "invalid_request", "message": f"{name} is invalid."})
    return value


def _hint(form: FormData, station: Station) -> LocalizeHint:
    node_ids = {n.id for n in station.nodes}
    previous = _text_field(form, "previous_node_id", _ELEMENT_RE)
    if previous is not None and previous not in node_ids:
        raise HTTPException(422, {"code": "unknown_node", "message": "previous_node_id is not a node of this station."})
    raw = form.get("route_node_ids") or ""
    if not isinstance(raw, str):
        raise HTTPException(422, {"code": "invalid_request", "message": "route_node_ids is invalid."})
    route = tuple(part.strip() for part in raw.split(",") if part.strip())
    if len(route) > MAX_ROUTE_NODES or any(r not in node_ids for r in route):
        raise HTTPException(422, {"code": "unknown_node",
                                  "message": "route_node_ids must be node ids of this station."})
    return LocalizeHint(previous_node_id=previous, route_node_ids=route)


async def _image(form: FormData, max_bytes: int) -> tuple[bytes, str]:
    image = form.get("image")
    if not isinstance(image, UploadFile):
        raise HTTPException(422, {"code": "invalid_request", "message": "image is required."})
    content_type = (image.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, {"code": "unsupported_image_type", "message": "The image must be JPEG or WebP."})
    if image.size is not None and image.size > max_bytes:
        raise HTTPException(413, {"code": "image_too_large", "message": "The image is too large."})
    data = await image.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, {"code": "image_too_large", "message": "The image is too large."})
    if _sniff(data) != ALLOWED_TYPES[content_type]:
        raise HTTPException(415, {"code": "unsupported_image_type", "message": "The image must be JPEG or WebP."})
    return data, content_type


def _provenance(c: Container, mode: DataMode, note: str) -> dict:
    return DataProvenance(mode=mode, source=SOURCE, as_of=c.clock.now().astimezone(UTC), note=note).model_dump(
        mode="json")


def _body(c: Container, station: Station, token: str, started: float, result: LocalizeResult | None,
          message: str | None = None) -> dict:
    threshold = c.settings.localize_confidence_threshold
    nodes = {n.id: n for n in station.nodes}
    latency_ms = int((time.monotonic() - started) * 1000)
    if result is None:
        status, fix, candidates = "unavailable", None, []
        provenance = _provenance(c, DataMode.UNAVAILABLE, message or UNAVAILABLE_MESSAGE)
    else:
        candidates = [{"node_id": cand.node_id, "node_name": nodes[cand.node_id].name,
                       "confidence": round(cand.confidence, 3)} for cand in result.candidates]
        fix = None
        if result.node_id is not None and result.confidence >= threshold:
            status = "fix"
            node = nodes[result.node_id]
            fix = {"node_id": node.id, "node_name": node.name, "level": node.level, "position": list(node.position),
                   "confidence": round(result.confidence, 3), "facing_bearing_deg": result.facing_bearing_deg,
                   "matched_cues": list(result.matched_cues)}
        else:
            status, message = "low_confidence", LOW_CONFIDENCE_MESSAGE
            if result.node_id is not None:  # the best guess becomes the first candidate
                candidates = [{"node_id": result.node_id, "node_name": nodes[result.node_id].name,
                               "confidence": round(result.confidence, 3)}] + candidates
                candidates = candidates[:3]
        provenance = _provenance(c, DataMode.LIVE, APPROXIMATE_NOTE)
    log.info("localize", extra={"fields": {"status": status, "node_id": result.node_id if result else None,
                                           "confidence": round(result.confidence, 3) if result else None,
                                           "latency_ms": latency_ms}})
    return {"status": status, "station_id": station.station_id, "fix": fix, "candidates": candidates,
            "confidence_threshold": threshold, "latency_ms": latency_ms, "message": message,
            "session_token": token, "provenance": provenance}


def _localize(c: Container, data: bytes, mime_type: str, station: Station, hint: LocalizeHint) -> LocalizeResult | None:
    try:
        result = c.vision.localize(data, mime_type, station, hint, Deadline(c.settings.localize_deadline_seconds))
    except LLMError as err:
        log.warning("localize unavailable (%s)", err.kind.value)
        return None
    except Exception as exc:  # noqa: BLE001 - an outage is reported as unavailable, never a 500
        log.warning("localize failed (%s)", type(exc).__name__)
        return None
    return guard_result(result, station)


@router.post(LOCALIZE_PATH)
async def localize(request: Request) -> dict:
    """Multipart form: `station_id`, `image` (JPEG/WebP), optional `previous_node_id` and `route_node_ids`
    (comma-separated node ids of the route being followed) as priors."""
    started = time.monotonic()
    c = _c(request)
    s = c.settings
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(415, {"code": "unsupported_media_type", "message": "Send the frame as multipart/form-data."})
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(411, {"code": "length_required", "message": "Content-Length is required."})
    if int(length) > s.localize_max_body_bytes:
        raise HTTPException(413, {"code": "image_too_large", "message": "The image is too large."})
    session_id, token = _session(c, request.headers.get(TOKEN_HEADER))
    await _enforce_rate_limit(request, c, session_id)
    form = await _read_form(request, s.localize_max_body_bytes)
    try:
        station_id = _text_field(form, "station_id", _STATION_RE, required=True)
        loaded = _station(c, station_id)
        station = loaded.station
        if not (station.ar_enabled and s.ar_guidance_on(station_id)):
            raise HTTPException(404, {"code": "ar_guidance_unavailable",
                                      "message": "AR guidance is not available for this station."})
        hint = _hint(form, station)
        data, mime_type = await _image(form, s.localize_max_image_bytes)
    finally:
        await form.close()
    if c.vision is None:
        return _body(c, station, token, started, None)
    result = await offload(_localize, c, data, mime_type, station, hint)
    del data  # the frame is not kept beyond the model call
    return _body(c, station, token, started, result)


def ar_guidance_stations(c: Container) -> list[str]:
    """Stations where AR guidance is offered: data opts in, the per-station flag is on and a localizer exists."""
    if c.vision is None or c.stations is None:
        return []
    return [sid for sid in c.stations.ids()
            if c.stations.get(sid).station.ar_enabled and c.settings.ar_guidance_on(sid)]
