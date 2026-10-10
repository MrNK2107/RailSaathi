"""Dijkstra routing over a station graph.

Hard constraints (closures, accessibility exclusions) remove edges from the
search entirely, so no cost weighting can ever override them. Unknown
accessibility is treated as uncertain: allowed by default with a penalty and a
warning, or excluded when ``require_verified_accessibility`` is set.

Route geometry is always the concatenation of the stored edge polylines.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Callable

from app.navigation.models.station import (
    AlongTheWayItem,
    Edge,
    RouteInstruction,
    RoutePreferences,
    RouteRequest,
    RouteResponse,
    RouteSegment,
    SnapResult,
)
from app.navigation.services.geometry import (
    Point,
    compass_name,
    distance_px,
    first_heading,
    last_heading,
    polyline_length_px,
    project_to_polyline,
    same_point,
    turn_phrase,
)
from app.navigation.services.graph_builder import (
    VIRTUAL_SOURCE,
    DirectedEdge,
    Snap,
    StationGraph,
    snap_to_walkway,
    with_virtual_source,
)

# Facilities worth mentioning when a route passes near them.
ALONG_THE_WAY_TYPES = {"toilet", "shop", "information_desk", "ticket_counter", "other_facility", "concourse"}
ALONG_THE_WAY_RADIUS_M = 15.0
ALONG_THE_WAY_RADIUS_PX = 80.0  # when the plan has no scale

EFFORT_MULTIPLIER = {"stairs": 1.5, "escalator": 1.2, "lift": 1.3}
UNKNOWN_ACCESSIBILITY_PENALTY = 1.25
UNKNOWN_STATUS_PENALTY = 1.1


class RoutingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def accessibility_sensitive(prefs: RoutePreferences) -> bool:
    return prefs.avoid_stairs or prefs.wheelchair or prefs.require_verified_accessibility


def preference_exclusion(edge: Edge, prefs: RoutePreferences) -> str | None:
    """Return why an edge violates a hard accessibility constraint, or None."""
    path_type = edge.path_type.value
    has_steps = (edge.steps or 0) > 0
    if prefs.wheelchair:
        if edge.accessible == "not_accessible":
            return "marked not accessible"
        if path_type in ("stairs", "escalator") or has_steps:
            return f"{'has steps' if has_steps else path_type} (not wheelchair-usable)"
    if prefs.avoid_stairs and (path_type == "stairs" or has_steps):
        return "has stairs/steps"
    if prefs.require_verified_accessibility and edge.accessible != "verified":
        return f"accessibility is '{edge.accessible}', not verified"
    return None


@dataclass
class _Search:
    graph: StationGraph
    use_metres: bool

    def base_length(self, de: DirectedEdge) -> float:
        e = de.edge
        if self.use_metres:
            if e.distance_m is not None:
                return e.distance_m
            if self.graph.metres_per_px:
                return de.length_px * self.graph.metres_per_px
        return de.length_px

    def run(
        self,
        source: str,
        target: str,
        allow: Callable[[DirectedEdge], bool],
        cost: Callable[[DirectedEdge], float],
    ) -> list[DirectedEdge] | None:
        dist = {source: 0.0}
        prev: dict[str, DirectedEdge] = {}
        tie = itertools.count()
        heap = [(0.0, next(tie), source)]
        done: set[str] = set()
        while heap:
            d, _, node = heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            if node == target:
                break
            for de in self.graph.adjacency.get(node, []):
                if not allow(de):
                    continue
                nd = d + cost(de)
                if nd < dist.get(de.to_node, float("inf")):
                    dist[de.to_node] = nd
                    prev[de.to_node] = de
                    heapq.heappush(heap, (nd, next(tie), de.to_node))
        if target not in done:
            return None
        path: list[DirectedEdge] = []
        cur = target
        while cur != source:
            de = prev[cur]
            path.append(de)
            cur = de.from_node
        path.reverse()
        return path


def snap_result(graph: StationGraph, snap: Snap) -> SnapResult:
    st = graph.station
    w, h = st.map.width, st.map.height
    e = snap.edge
    a, b = graph.nodes[e.from_], graph.nodes[e.to]
    near = a if distance_px(snap.point, a.position, w, h) <= distance_px(snap.point, b.position, w, h) else b
    metres = round(snap.distance_px * graph.metres_per_px, 1) if graph.metres_per_px else None
    away = f"{metres:.0f} m" if metres is not None else f"{snap.distance_px:.0f} px"
    if snap.within_tolerance:
        msg = f"Matched to the walkway between {a.name} and {b.name} ({away} away), nearest {near.name}."
    else:
        msg = (f"Nearest traced walkway is {away} away (between {a.name} and {b.name}), beyond the allowed "
               f"snapping distance. Choose a point on a walkway or a named start location.")
    return SnapResult(
        position=snap.position, snapped_position=snap.point, edge_id=e.id, from_node=e.from_, to_node=e.to,
        fraction_along_edge=round(snap.fraction, 4), distance_px=round(snap.distance_px, 1), distance_m=metres,
        within_tolerance=snap.within_tolerance, nearest_node_id=near.id, nearest_node_name=near.name, message=msg,
    )


def find_route(graph: StationGraph, request: RouteRequest, walking_speed_mps: float = 1.2) -> RouteResponse:
    prefs = request.preferences
    dst = request.destination
    start_snap: SnapResult | None = None
    if request.source_position is not None:
        snap = snap_to_walkway(graph, tuple(request.source_position), request.max_snap_distance_m)
        if snap is None:
            raise RoutingError("no_walkways", "This station has no open traced walkways to start from.", 422)
        start_snap = snap_result(graph, snap)
        src = VIRTUAL_SOURCE
        if snap.within_tolerance:
            graph = with_virtual_source(graph, snap)
    else:
        src = request.source
    if dst not in graph.nodes:
        raise RoutingError("unknown_node", f"Unknown destination node '{dst}' in station '{graph.station.station_id}'", 404)
    if src != VIRTUAL_SOURCE and src not in graph.nodes:
        raise RoutingError("unknown_node", f"Unknown source node '{src}' in station '{graph.station.station_id}'", 404)

    base = RouteResponse(
        status="no_route",
        station_id=graph.station.station_id,
        source=src,
        destination=dst,
        preferences=prefs,
        simulated_disruptions_applied=graph.applied_disruptions,
    )
    base.previous_route_blocked_edge_ids = _blocked_previous(graph, request.previous_edge_ids)
    base.previous_route_blocked = bool(base.previous_route_blocked_edge_ids)
    base.start_snap = start_snap
    if start_snap is not None:
        base.source_position_origin = request.source_position_origin
    if start_snap is not None and not start_snap.within_tolerance:
        base.reason = "position_not_on_walkway"
        base.explanation = start_snap.message
        return base

    for nid in (src, dst):
        if nid in graph.closed_nodes:
            name = graph.nodes[nid].name
            reason = graph.closure_reasons.get(nid, "closed")
            base.reason = "endpoint_closed"
            base.explanation = f"{name} is currently unavailable ({reason}). No route can start or end there."
            return base

    use_metres = graph.metres_per_px is not None or all(e.distance_m is not None for e in graph.edges.values())
    search = _Search(graph, use_metres)
    sensitive = accessibility_sensitive(prefs)

    def node_open(de: DirectedEdge) -> bool:
        return de.to_node not in graph.closed_nodes or de.to_node == dst

    def edge_open(de: DirectedEdge) -> bool:
        return de.edge.status != "closed" and node_open(de)

    def allowed(de: DirectedEdge) -> bool:
        return edge_open(de) and preference_exclusion(de.edge, prefs) is None

    def cost(de: DirectedEdge) -> float:
        c = search.base_length(de) * EFFORT_MULTIPLIER.get(de.edge.path_type.value, 1.0)
        if sensitive and de.edge.accessible == "unknown":
            c *= UNKNOWN_ACCESSIBILITY_PENALTY
        if de.edge.status == "unknown":
            c *= UNKNOWN_STATUS_PENALTY
        return c

    if src == dst:
        base.status = "ok"
        base.node_ids = [src]
        base.geometry = [tuple(graph.nodes[src].position)]
        base.instructions = [
            RouteInstruction(step=1, text=f"You are already at {graph.nodes[src].name}.", node_id=src)
        ]
        return base

    path = search.run(src, dst, allowed, cost)
    if path is None:
        return _explain_no_route(base, graph, search, src, dst, prefs, edge_open, node_open, cost)
    return _build_response(base, graph, search, path, prefs, walking_speed_mps)


def _blocked_previous(graph: StationGraph, previous: list[str]) -> list[str]:
    blocked = []
    for eid in previous:
        e = graph.edges.get(eid)
        if e is None or e.status == "closed" or e.from_ in graph.closed_nodes or e.to in graph.closed_nodes:
            blocked.append(eid)
    return blocked


def _explain_no_route(base, graph, search, src, dst, prefs, edge_open, node_open, cost) -> RouteResponse:
    names = graph.nodes
    unconstrained = search.run(src, dst, lambda de: True, cost)
    if unconstrained is None:
        base.reason = "not_connected"
        isolated = [n for n in (src, dst) if not graph.adjacency.get(n) and not _has_incoming(graph, n)]
        if isolated:
            iso = " and ".join(names[n].name for n in isolated)
            base.explanation = (
                f"No traced pathway reaches {iso}. The station map has no verified walkway connecting it yet."
            )
        else:
            base.explanation = (
                f"No traced pathway connects {names[src].name} to {names[dst].name} in the station graph."
            )
        return base

    open_only = search.run(src, dst, edge_open, cost)
    if open_only is None:
        blocking = [de.edge.id for de in unconstrained if de.edge.status == "closed"]
        blocking_nodes = [de.to_node for de in unconstrained if de.to_node in graph.closed_nodes and de.to_node != dst]
        base.reason = "blocked_by_closure"
        base.blocking_edge_ids = blocking
        parts = []
        if blocking:
            parts.append("closed pathway(s) " + ", ".join(blocking))
        if blocking_nodes:
            parts.append("unavailable location(s) " + ", ".join(names[n].name for n in blocking_nodes))
        base.explanation = (
            f"Every route from {names[src].name} to {names[dst].name} is blocked by "
            + "; ".join(parts or ["current closures"])
            + ". No feasible alternative exists while these closures are active."
        )
        return base

    excluded = [(de.edge.id, preference_exclusion(de.edge, prefs)) for de in open_only]
    excluded = [(eid, why) for eid, why in excluded if why]
    base.reason = "accessibility_constraints"
    base.blocking_edge_ids = [eid for eid, _ in excluded]
    detail = "; ".join(f"{eid} {why}" for eid, why in excluded)
    base.explanation = (
        f"No route satisfying your accessibility preferences was found between {names[src].name} and "
        f"{names[dst].name}. Every connecting route uses at least one excluded pathway"
        + (f" (e.g. {detail})" if detail else "")
        + ". No verified suitable route is available; please ask station staff for assistance."
    )
    return base


def _has_incoming(graph: StationGraph, node_id: str) -> bool:
    return any(de.to_node == node_id for edges in graph.adjacency.values() for de in edges)


def _concat_geometry(path: list[DirectedEdge]) -> list[Point]:
    out: list[Point] = []
    for de in path:
        for i, p in enumerate(de.geometry):
            if i == 0 and out and same_point(out[-1], p):
                continue
            out.append(p)
    return out


def _build_response(base, graph, search, path, prefs, walking_speed_mps) -> RouteResponse:
    st = graph.station
    w, h = st.map.width, st.map.height
    scale = graph.metres_per_px

    segments: list[RouteSegment] = []
    for de in path:
        e = de.edge
        est = e.distance_m if e.distance_m is not None else (de.length_px * scale if scale else None)
        segments.append(
            RouteSegment(
                edge_id=e.id,
                partial=de.from_node == VIRTUAL_SOURCE,
                from_node=de.from_node,
                to_node=de.to_node,
                geometry=list(de.geometry),
                path_type=e.path_type.value,
                steps=e.steps,
                accessible=e.accessible,
                status=e.status,
                verification=e.verification,
                distance_m=e.distance_m,
                estimated_distance_m=round(est, 1) if est is not None else None,
            )
        )

    base.status = "ok"
    base.node_ids = [path[0].from_node] + [de.to_node for de in path]
    base.edge_ids = [de.edge.id for de in path]
    base.geometry = _concat_geometry(path)
    base.segments = segments

    if all(s.distance_m is not None for s in segments):
        total = sum(s.distance_m for s in segments)
        base.distance_m = round(total, 1)
        base.estimated_distance_m = base.distance_m
        base.distance_basis = "measured"
    elif all(s.estimated_distance_m is not None for s in segments):
        base.estimated_distance_m = round(sum(s.estimated_distance_m for s in segments), 1)
        base.distance_basis = "estimated_from_map_scale"
    if base.estimated_distance_m is not None and walking_speed_mps > 0:
        base.estimated_duration_s = round(base.estimated_distance_m / walking_speed_mps)
        base.duration_assumption = f"Assumes an average walking speed of {walking_speed_mps} m/s; not measured."

    warnings: list[str] = []
    sensitive = accessibility_sensitive(prefs)
    unknown = [s.edge_id for s in segments if s.accessible == "unknown"]
    if sensitive:
        if all(s.accessible == "verified" for s in segments):
            base.accessibility_confidence = "verified"
        else:
            base.accessibility_confidence = "unverified"
            if unknown:
                warnings.append(
                    f"No fully verified accessible route is available. {len(unknown)} pathway(s) on this route have "
                    f"UNKNOWN accessibility ({', '.join(unknown)}); they may not be suitable."
                )
        dest = graph.nodes[base.destination]
        if prefs.wheelchair and dest.accessible == "not_accessible":
            warnings.append(f"{dest.name} itself is marked not accessible.")
    stairs = [s.edge_id for s in segments if s.path_type == "stairs" or (s.steps or 0) > 0]
    if stairs:
        warnings.append(f"Route includes stairs/steps on {', '.join(stairs)}.")
    status_unknown = [s.edge_id for s in segments if s.status == "unknown"]
    if status_unknown:
        warnings.append(f"Operational status is unknown for {', '.join(status_unknown)}.")
    unverified = [s.edge_id for s in segments if s.verification != "verified"]
    if unverified:
        warnings.append(
            f"{len(unverified)} of {len(segments)} pathway(s) are not verified on site (pending or simulated data)."
        )
    if base.start_snap is not None:
        origin = {"gps": "a GPS fix", "mock_gps": "a MOCK GPS fix (simulated)", "manual": "a point you chose on the map"}
        warnings.insert(0, f"Start position comes from {origin[base.source_position_origin or 'manual']}. {base.start_snap.message}")
    if base.previous_route_blocked:
        warnings.insert(
            0,
            "SIMULATED DISRUPTION: your previous route is blocked at "
            + ", ".join(base.previous_route_blocked_edge_ids)
            + ". Showing an alternative route.",
        )
    base.warnings = warnings
    base.instructions = _instructions(graph, path, segments, w, h)
    base.along_the_way = _along_the_way(graph, base)
    return base


def _along_the_way(graph: StationGraph, route: RouteResponse) -> list[AlongTheWayItem]:
    """Facilities on or near the route polyline, ordered by where you pass them."""
    st = graph.station
    w, h = st.map.width, st.map.height
    geom = route.geometry
    total = polyline_length_px(geom, w, h)
    if len(geom) < 2 or total == 0:
        return []
    radius_px = ALONG_THE_WAY_RADIUS_M / graph.metres_per_px if graph.metres_per_px else ALONG_THE_WAY_RADIUS_PX
    on_route = set(route.node_ids)
    items = []
    for n in graph.nodes.values():
        if n.type.value not in ALONG_THE_WAY_TYPES or n.id == route.destination or n.id == VIRTUAL_SOURCE:
            continue
        d, along, *_ = project_to_polyline(geom, n.position, w, h)
        if n.id not in on_route and d > radius_px:
            continue
        items.append(
            AlongTheWayItem(
                node_id=n.id, name=n.name, type=n.type.value, on_route=n.id in on_route,
                distance_from_route_m=round(d * graph.metres_per_px, 1) if graph.metres_per_px else None,
                progress=round(along / total, 3), verification=n.verification, accessible=n.accessible,
            )
        )
    return sorted(items, key=lambda i: i.progress)


def _instructions(graph: StationGraph, path: list[DirectedEdge], segments: list[RouteSegment], w: int, h: int):
    nodes = graph.nodes
    out: list[RouteInstruction] = []
    prev_heading = None
    for i, (de, seg) in enumerate(zip(path, segments)):
        target = nodes[de.to_node]
        head = first_heading(de.geometry, w, h)
        via = {
            "stairs": "take the stairs" + (f" ({seg.steps} steps)" if seg.steps else " (step count unknown)"),
            "escalator": "take the escalator",
            "lift": "take the lift",
            "ramp": "take the ramp",
            "doorway": "go through the doorway",
            "platform": "walk along the platform",
        }.get(seg.path_type, f"walk along the {seg.path_type}")
        direction = f" heading {compass_name(head)}" if head is not None else ""
        if i == 0:
            lead = f"Start at {nodes[de.from_node].name}. {via[0].upper()}{via[1:]}{direction}"
        else:
            lead = f"{turn_phrase(prev_heading, head)} at {nodes[de.from_node].name} and {via}{direction}"
        dist = seg.distance_m if seg.distance_m is not None else seg.estimated_distance_m
        is_est = seg.distance_m is None and dist is not None
        dist_txt = f" for about {dist:.0f} m{' (estimate)' if is_est else ''}" if dist is not None else ""
        out.append(
            RouteInstruction(
                step=i + 1,
                text=f"{lead}{dist_txt} to {target.name}.",
                node_id=de.from_node,
                edge_id=seg.edge_id,
                distance_m=round(dist, 1) if dist is not None else None,
                distance_is_estimate=is_est,
            )
        )
        prev_heading = last_heading(de.geometry, w, h)
    out.append(
        RouteInstruction(step=len(out) + 1, text=f"Arrive at {nodes[path[-1].to_node].name}.", node_id=path[-1].to_node)
    )
    return out
