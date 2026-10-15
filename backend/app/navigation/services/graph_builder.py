"""Builds a directed routing graph from a station file, plus a closure overlay.

Graphs are built once per station at catalogue load. The overlay only changes
*operational* status; step-free properties and geometry are never modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

from app.navigation.models.station import Disruption, Edge, Node, Station, StationMetadata
from app.navigation.services.geometry import Point, polyline_length_px


@dataclass(frozen=True)
class DirectedEdge:
    edge: Edge
    from_node: str
    to_node: str
    geometry: tuple[Point, ...]  # oriented in travel direction
    length_px: float


@dataclass
class StationGraph:
    station: Station
    nodes: dict[str, Node]
    edges: dict[str, Edge]  # effective edges (closure overlay applied)
    adjacency: dict[str, list[DirectedEdge]]
    closed_nodes: set[str]
    metres_per_px: float | None
    applied_disruptions: list[str] = field(default_factory=list)
    applied_simulated: list[str] = field(default_factory=list)
    closure_reasons: dict[str, str] = field(default_factory=dict)  # edge/node id -> reason


class UnknownClosureTarget(Exception):
    pass


def build_graph(
    station: Station,
    metadata: StationMetadata | None = None,
    disruptions: Iterable[Disruption] = (),
) -> StationGraph:
    """Build the routing graph once per station; closures are layered on with `apply_closures`."""
    w, h = station.map.width, station.map.height
    nodes = {n.id: n for n in station.nodes}
    edges: dict[str, Edge] = {}
    adjacency: dict[str, list[DirectedEdge]] = {nid: [] for nid in nodes}
    for e in station.edges:
        edges[e.id] = e
        if e.from_ not in nodes or e.to not in nodes:
            continue
        length = polyline_length_px(e.geometry, w, h)
        geom = tuple(tuple(p) for p in e.geometry)
        adjacency[e.from_].append(DirectedEdge(e, e.from_, e.to, geom, length))
        if e.bidirectional:
            adjacency[e.to].append(DirectedEdge(e, e.to, e.from_, tuple(reversed(geom)), length))
    scale = metadata.map_scale.metres_per_pixel if metadata and metadata.map_scale else None
    base = StationGraph(
        station=station,
        nodes=nodes,
        edges=edges,
        adjacency=adjacency,
        closed_nodes={nid for nid, n in nodes.items() if n.status == "closed"},
        metres_per_px=scale,
    )
    return apply_closures(base, disruptions)


def apply_closures(
    graph: StationGraph,
    disruptions: Iterable[Disruption] = (),
    simulated: Iterable[str] = (),
) -> StationGraph:
    """Return a copy of a prebuilt graph with stored disruptions and per-request what-if closures applied.

    Only operational status changes; geometry and step-free properties are never modified. The prebuilt graph
    is returned unchanged when there is nothing to apply. Unknown what-if ids raise UnknownClosureTarget."""
    disruptions, simulated = list(disruptions), list(dict.fromkeys(simulated))
    if not disruptions and not simulated:
        return graph
    closed_edges: dict[str, str] = {}
    closed_nodes: dict[str, str] = {}
    for d in disruptions:
        target = closed_edges if d.target_type == "edge" else closed_nodes
        target[d.target_id] = d.reason
    for target_id in simulated:
        if target_id in graph.edges:
            closed_edges[target_id] = "simulated closure"
        elif target_id in graph.nodes:
            closed_nodes[target_id] = "simulated closure"
        else:
            raise UnknownClosureTarget(target_id)

    edges = dict(graph.edges)
    for eid in closed_edges:
        if eid in edges:
            edges[eid] = edges[eid].model_copy(update={"status": "closed"})
    adjacency = graph.adjacency
    if closed_edges:
        adjacency = {
            nid: [replace(de, edge=edges[de.edge.id]) if de.edge.id in closed_edges else de for de in out]
            for nid, out in graph.adjacency.items()
        }
    return StationGraph(
        station=graph.station,
        nodes=graph.nodes,
        edges=edges,
        adjacency=adjacency,
        closed_nodes=graph.closed_nodes | {n for n in closed_nodes if n in graph.nodes},
        metres_per_px=graph.metres_per_px,
        applied_disruptions=graph.applied_disruptions + [d.id for d in disruptions],
        applied_simulated=graph.applied_simulated + simulated,
        closure_reasons={**graph.closure_reasons, **closed_edges, **closed_nodes},
    )


# ---------------------------------------------------------------------------
# Routing from an arbitrary position (GPS fix, mock GPS, "start here" tap)
# ---------------------------------------------------------------------------

VIRTUAL_SOURCE = "current_position"
DEFAULT_SNAP_PX = 60.0  # used when the plan has no scale


@dataclass(frozen=True)
class Snap:
    position: Point
    point: Point
    edge: Edge
    seg_index: int
    t: float
    distance_px: float
    fraction: float
    within_tolerance: bool
    tolerance_px: float


def snap_to_walkway(graph: StationGraph, position: Point, max_snap_m: float = 15.0,
                    level: int | None = None) -> Snap | None:
    """Project a free position onto the nearest open pathway on one level. Closed pathways and level transitions
    (stairs, lifts) are skipped, and so are pathways off `level` when a level is given."""
    from app.navigation.services.geometry import project_to_polyline

    st = graph.station
    w, h = st.map.width, st.map.height
    tolerance_px = max_snap_m / graph.metres_per_px if graph.metres_per_px else DEFAULT_SNAP_PX
    best: Snap | None = None
    for e in graph.edges.values():
        if e.status == "closed" or e.from_ not in graph.nodes or e.to not in graph.nodes:
            continue
        if e.from_ in graph.closed_nodes and e.to in graph.closed_nodes:
            continue
        if e.level_change != 0 or (level is not None and graph.nodes[e.from_].level != level):
            continue
        d, along, idx, t, q = project_to_polyline(e.geometry, position, w, h)
        if best is None or d < best.distance_px:
            total = polyline_length_px(e.geometry, w, h)
            best = Snap(tuple(position), q, e, idx, t, d, along / total if total else 0.0, d <= tolerance_px, tolerance_px)
    return best


def with_virtual_source(graph: StationGraph, snap: Snap) -> StationGraph:
    """Return a graph copy with a virtual node at the snapped point, joined to both
    ends of the snapped edge by the two parts of its *stored* polyline."""
    from app.navigation.models.station import Node

    st = graph.station
    w, h = st.map.width, st.map.height
    e = snap.edge
    g = [tuple(p) for p in e.geometry]
    q = tuple(snap.point)
    to_end = (q, *g[snap.seg_index + 1 :])  # forward: snapped point -> e.to
    to_start = (q, *reversed(g[: snap.seg_index + 1]))  # backward: snapped point -> e.from

    def dedupe(geom: tuple) -> tuple:
        out = [geom[0]]
        for p in geom[1:]:
            if abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
                out.append(p)
        return tuple(out) if len(out) > 1 else (geom[0], geom[0])

    def part(geom: tuple, frac: float, target: str) -> DirectedEdge:
        geom = dedupe(geom)
        dist = e.distance_m * frac if e.distance_m is not None else None
        partial = e.model_copy(update={"geometry": [list(p) for p in geom], "distance_m": dist})
        return DirectedEdge(partial, VIRTUAL_SOURCE, target, geom, polyline_length_px(geom, w, h))

    out = [part(to_end, 1 - snap.fraction, e.to)]
    if e.bidirectional:
        out.append(part(to_start, snap.fraction, e.from_))
    nodes = dict(graph.nodes)
    nodes[VIRTUAL_SOURCE] = Node(
        id=VIRTUAL_SOURCE, name="your current position", type="junction",
        position=q, level=graph.nodes[e.from_].level, verification="simulated",
    )
    adjacency = dict(graph.adjacency)
    adjacency[VIRTUAL_SOURCE] = out
    return StationGraph(
        station=st, nodes=nodes, edges=graph.edges, adjacency=adjacency,
        closed_nodes=graph.closed_nodes, metres_per_px=graph.metres_per_px,
        applied_disruptions=graph.applied_disruptions, applied_simulated=graph.applied_simulated,
        closure_reasons=graph.closure_reasons,
    )
