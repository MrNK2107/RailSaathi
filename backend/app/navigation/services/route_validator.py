"""Station graph integrity validation.

Errors block publishing. Warnings are surfaced to the developer but never
"fixed" automatically: the validator does not create, delete or move anything.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from app.navigation.models.station import (
    Station,
    StationMetadata,
    ValidationIssue,
    ValidationReport,
)
from app.navigation.services.geometry import distance_px, polyline_length_px

# A traced polyline must start/end within this many image pixels of its nodes.
ENDPOINT_TOLERANCE_PX = 6.0
# A single straight segment longer than this fraction of the image diagonal is suspicious.
LONG_SEGMENT_FRACTION = 0.25
# Measured distance vs. map-scale estimate ratio outside this band is suspicious.
DISTANCE_RATIO_BAND = (0.33, 3.0)


def _err(code: str, message: str, **kw: Any) -> ValidationIssue:
    return ValidationIssue(level="error", code=code, message=message, **kw)


def _warn(code: str, message: str, **kw: Any) -> ValidationIssue:
    return ValidationIssue(level="warning", code=code, message=message, **kw)


def _schema_issues(exc: ValidationError, raw: Any) -> list[ValidationIssue]:
    issues = []
    for e in exc.errors():
        loc = e.get("loc", ())
        node_id = edge_id = None
        if len(loc) >= 2 and loc[0] in ("nodes", "edges") and isinstance(loc[1], int) and isinstance(raw, dict):
            try:
                ident = raw[loc[0]][loc[1]].get("id")
            except (KeyError, IndexError, TypeError, AttributeError):
                ident = None
            if loc[0] == "nodes":
                node_id = ident
            else:
                edge_id = ident
        where = ".".join(str(p) for p in loc) or "(root)"
        msg = e.get("msg", "invalid value")
        if e.get("type") == "missing" and loc and loc[-1] == "accessible":
            msg = "accessibility status is required (verified, not_accessible or unknown)"
        issues.append(_err("schema", f"{where}: {msg}", node_id=node_id, edge_id=edge_id))
    return issues


def _valid_coord(p: Any) -> bool:
    return (
        isinstance(p, (list, tuple))
        and len(p) == 2
        and all(isinstance(v, (int, float)) and math.isfinite(v) and 0.0 <= v <= 1.0 for v in p)
    )


def validate_station_data(
    raw: Any,
    metadata: StationMetadata | None = None,
    expected_station_id: str | None = None,
) -> ValidationReport:
    try:
        station = Station.model_validate(raw)
    except ValidationError as exc:
        errors = _schema_issues(exc, raw)
        return ValidationReport(valid=False, errors=errors, warnings=[])
    errors, warnings = validate_graph(station, metadata, expected_station_id)
    return ValidationReport(valid=not errors, errors=errors, warnings=warnings)


def validate_graph(
    station: Station,
    metadata: StationMetadata | None = None,
    expected_station_id: str | None = None,
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    w, h = station.map.width, station.map.height
    diag = math.hypot(w, h)

    if expected_station_id and station.station_id != expected_station_id:
        errors.append(
            _err("station_id_mismatch", f"station_id '{station.station_id}' does not match '{expected_station_id}'")
        )

    # Nodes ---------------------------------------------------------------
    nodes = {}
    for n in station.nodes:
        if n.id in nodes:
            errors.append(_err("duplicate_node_id", f"Duplicate node ID '{n.id}'", node_id=n.id))
        nodes[n.id] = n
        if not _valid_coord(n.position):
            errors.append(
                _err("invalid_coordinates", f"Node '{n.id}' has coordinates outside 0..1: {n.position}", node_id=n.id)
            )

    # Edges ---------------------------------------------------------------
    seen_edges: set[str] = set()
    pairs: dict[frozenset, list[str]] = defaultdict(list)
    degree: dict[str, int] = defaultdict(int)
    scale = metadata.map_scale.metres_per_pixel if metadata and metadata.map_scale else None

    for e in station.edges:
        if e.id in seen_edges:
            errors.append(_err("duplicate_edge_id", f"Duplicate edge ID '{e.id}'", edge_id=e.id))
        seen_edges.add(e.id)

        missing = [ref for ref in (e.from_, e.to) if ref not in nodes]
        for ref in missing:
            errors.append(_err("unknown_node", f"Edge '{e.id}' references unknown node '{ref}'", edge_id=e.id))
        if e.from_ == e.to:
            errors.append(_err("self_loop", f"Edge '{e.id}' starts and ends at the same node '{e.from_}'", edge_id=e.id))

        bad_points = [p for p in e.geometry if not _valid_coord(p)]
        if bad_points:
            errors.append(
                _err("invalid_coordinates", f"Edge '{e.id}' has geometry points outside 0..1", edge_id=e.id)
            )

        if not missing and not bad_points:
            start_gap = distance_px(e.geometry[0], nodes[e.from_].position, w, h)
            end_gap = distance_px(e.geometry[-1], nodes[e.to].position, w, h)
            if start_gap > ENDPOINT_TOLERANCE_PX:
                errors.append(
                    _err(
                        "geometry_start_mismatch",
                        f"Edge '{e.id}' geometry starts {start_gap:.0f}px away from node '{e.from_}'",
                        edge_id=e.id,
                    )
                )
            if end_gap > ENDPOINT_TOLERANCE_PX:
                errors.append(
                    _err(
                        "geometry_end_mismatch",
                        f"Edge '{e.id}' geometry ends {end_gap:.0f}px away from node '{e.to}'",
                        edge_id=e.id,
                    )
                )

            for a, b in zip(e.geometry, e.geometry[1:]):
                if distance_px(a, b, w, h) > LONG_SEGMENT_FRACTION * diag:
                    warnings.append(
                        _warn(
                            "long_straight_segment",
                            f"Edge '{e.id}' has a very long straight segment; confirm it follows a real corridor",
                            edge_id=e.id,
                        )
                    )
                    break

            if scale and e.distance_m:
                est = polyline_length_px(e.geometry, w, h) * scale
                if est > 0:
                    ratio = e.distance_m / est
                    if not (DISTANCE_RATIO_BAND[0] <= ratio <= DISTANCE_RATIO_BAND[1]):
                        warnings.append(
                            _warn(
                                "distance_mismatch",
                                f"Edge '{e.id}' distance {e.distance_m} m differs strongly from traced length ≈{est:.0f} m",
                                edge_id=e.id,
                            )
                        )

        # Accessibility claims must be consistent with what is known about the pathway.
        stepped = e.path_type.value in ("stairs", "escalator") or (e.steps or 0) > 0
        if e.accessible == "verified" and stepped:
            errors.append(
                _err(
                    "contradictory_accessibility",
                    f"Edge '{e.id}' is marked accessible 'verified' but has stairs/steps",
                    edge_id=e.id,
                )
            )
        if e.accessible == "verified" and e.verification != "verified":
            warnings.append(
                _warn(
                    "unverified_accessibility_claim",
                    f"Edge '{e.id}' claims verified accessibility but the pathway itself is '{e.verification}'",
                    edge_id=e.id,
                )
            )

        if not missing and e.from_ != e.to:
            pairs[frozenset((e.from_, e.to))].append(e.id)
            degree[e.from_] += 1
            degree[e.to] += 1

    for pair, ids in pairs.items():
        if len(ids) > 1:
            a, b = sorted(pair)
            warnings.append(
                _warn("parallel_edges", f"Multiple pathways connect '{a}' and '{b}': {', '.join(ids)}", edge_id=ids[0])
            )

    # Connectivity ----------------------------------------------------------
    for nid, n in nodes.items():
        if degree[nid] == 0:
            warnings.append(_warn("isolated_node", f"Node '{nid}' ({n.name}) has no pathways", node_id=nid))
        elif n.type.value == "junction" and degree[nid] == 1:
            warnings.append(_warn("dead_end_junction", f"Junction '{nid}' is connected to only one pathway", node_id=nid))

    components = _components(station, set(nodes))
    connected = [c for c in components if len(c) > 1]
    if len(connected) > 1:
        connected.sort(key=len, reverse=True)
        for comp in connected[1:]:
            sample = ", ".join(sorted(comp)[:5])
            warnings.append(
                _warn(
                    "disconnected_component",
                    f"{len(comp)} node(s) are unreachable from the main network (e.g. {sample})",
                    node_id=sorted(comp)[0],
                )
            )
    return errors, warnings


def _components(station: Station, node_ids: set[str]) -> list[set[str]]:
    adj: dict[str, set[str]] = {n: set() for n in node_ids}
    for e in station.edges:
        if e.from_ in adj and e.to in adj and e.from_ != e.to:
            adj[e.from_].add(e.to)
            adj[e.to].add(e.from_)
    seen: set[str] = set()
    comps = []
    for start in sorted(node_ids):
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            stack.extend(adj[cur] - comp)
        seen |= comp
        comps.append(comp)
    return comps


def check_route_integrity(station: Station, node_ids: list[str], edge_ids: list[str], geometry: list) -> list[str]:
    """Verify that a computed route is a connected walk over stored edges whose
    geometry is exactly the concatenation of the stored polylines. Returns problems."""
    problems: list[str] = []
    edges = {e.id: e for e in station.edges}
    if len(node_ids) != len(edge_ids) + 1:
        return ["node/edge count mismatch"]
    expected: list = []
    for i, eid in enumerate(edge_ids):
        e = edges.get(eid)
        if e is None:
            problems.append(f"unknown edge {eid}")
            continue
        a, b = node_ids[i], node_ids[i + 1]
        if (e.from_, e.to) == (a, b):
            geom = list(e.geometry)
        elif e.bidirectional and (e.to, e.from_) == (a, b):
            geom = list(reversed(e.geometry))
        else:
            problems.append(f"edge {eid} does not connect {a} -> {b}")
            continue
        if expected and tuple(expected[-1]) == tuple(geom[0]):
            geom = geom[1:]
        expected.extend(geom)
    if not problems and [tuple(p) for p in expected] != [tuple(p) for p in geometry]:
        problems.append("route geometry differs from stored pathway polylines")
    return problems
