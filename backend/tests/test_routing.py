"""Routing over the prebuilt graph: step-free versus stairs, level transitions, step-free claims, what-if closures."""

import json

import pytest

from app.config import STATIONS_DIR
from app.navigation.models.station import RoutePreferences, RouteRequest, Station, StationMetadata
from app.navigation.services.graph_builder import UnknownClosureTarget, apply_closures, build_graph
from app.navigation.services.route_validator import check_route_integrity
from app.navigation.services.routing_engine import find_route
from tests.station_fixture import METADATA, station_raw


def graph_of(raw=None):
    return build_graph(Station.model_validate(raw or station_raw()), StationMetadata.model_validate(METADATA))


def route(graph, src, dst, **prefs):
    req = RouteRequest(station_id=graph.station.station_id, source=src, destination=dst,
                       preferences=RoutePreferences(**prefs))
    return find_route(graph, req)


def test_default_route_takes_the_short_stairs():
    r = route(graph_of(), "ent", "p1")
    assert r.status == "ok" and r.edge_ids == ["e_ent_hall", "e_stairs"]
    assert any("stairs" in w for w in r.warnings)
    assert "take the stairs (12 steps)" in r.instructions[1].text


@pytest.mark.parametrize("prefs", [{"avoid_stairs": True}, {"wheelchair": True}])
def test_step_free_route_avoids_the_stairs(prefs):
    r = route(graph_of(), "ent", "p1", **prefs)
    assert r.status == "ok" and r.edge_ids == ["e_ent_hall", "e_hall_j", "e_ramp"]
    assert r.estimated_distance_m > route(graph_of(), "ent", "p1").estimated_distance_m
    assert r.accessibility_confidence == "unverified"  # every pathway is "unknown"
    assert any("UNKNOWN step-free status" in w for w in r.warnings)
    assert check_route_integrity(graph_of().station, r.node_ids, r.edge_ids, r.geometry) == []


def test_wheelchair_uses_lifts_but_not_escalators():
    g = graph_of()
    assert route(g, "p1", "p2").edge_ids == ["e_lift_up", "e_escalator"]
    assert route(g, "p1", "p2", avoid_stairs=True).edge_ids == ["e_lift_up", "e_escalator"]  # escalator is no stair
    wheelchair = route(g, "p1", "p2", wheelchair=True)
    assert wheelchair.edge_ids == ["e_lift_up", "e_bridge", "e_lift_down"]
    assert [s.level_change for s in wheelchair.segments] == [1, 0, -1]
    assert "take the lift up to level 1" in wheelchair.instructions[0].text.lower()
    assert "take the lift down to level 0" in wheelchair.instructions[2].text.lower()


def test_level_names_and_reverse_direction_level_change():
    raw = station_raw(levels=[{"level": 0, "name": "Ground"}, {"level": 1, "name": "Foot-over-bridge"}])
    r = route(graph_of(raw), "fob", "p1")
    assert r.edge_ids == ["e_lift_up"] and r.segments[0].level_change == -1  # travelled against the edge
    assert "lift down to Ground (level 0)" in r.instructions[0].text


def test_no_step_free_route_is_explained_with_the_exit_exception():
    raw = station_raw()
    raw["edges"] = [e for e in raw["edges"] if e["id"] != "e_ramp"]
    next(n for n in raw["nodes"] if n["id"] == "ent")["step_free_exception"] = "Only stairs at this gate."
    r = route(graph_of(raw), "ent", "p1", wheelchair=True)
    assert r.status == "no_route" and r.reason == "accessibility_constraints"
    assert r.blocking_edge_ids == ["e_stairs"]
    assert "ENT: Only stairs at this gate." in r.explanation


def test_require_verified_excludes_reported_and_unknown_claims():
    raw = station_raw()
    for e in raw["edges"]:
        if e["id"] in ("e_ent_hall", "e_hall_j"):
            e["step_free"], e["verification"] = "verified", "verified"
        if e["id"] == "e_ramp":
            e["step_free"] = "reported"
    g = graph_of(raw)
    r = route(g, "ent", "p1", wheelchair=True)
    assert r.status == "ok" and any("reported step-free by a source but not verified" in w for w in r.warnings)
    strict = route(g, "ent", "p1", wheelchair=True, require_verified_accessibility=True)
    assert strict.status == "no_route" and strict.reason == "accessibility_constraints"
    raw["edges"][3]["step_free"], raw["edges"][3]["verification"] = "verified", "verified"
    verified = route(graph_of(raw), "ent", "p1", wheelchair=True, require_verified_accessibility=True)
    assert verified.status == "ok" and verified.accessibility_confidence == "verified"


def test_closures_are_layered_on_the_prebuilt_graph_without_changing_it():
    base = graph_of()
    assert apply_closures(base) is base  # nothing to apply: the prebuilt graph itself
    closed = apply_closures(base, simulated=["e_ramp"])
    assert base.edges["e_ramp"].status == "open" and closed.edges["e_ramp"].status == "closed"
    r = route(closed, "ent", "p1", wheelchair=True)
    assert r.status == "no_route" and r.reason == "accessibility_constraints"  # only the stairs remain
    assert r.simulated_closures_applied == ["e_ramp"]
    assert route(closed, "ent", "p1").edge_ids == ["e_ent_hall", "e_stairs"]
    assert route(base, "ent", "p1", wheelchair=True).status == "ok"
    gate = route(apply_closures(base, simulated=["e_ent_hall"]), "ent", "p1")
    assert gate.reason == "blocked_by_closure" and gate.blocking_edge_ids == ["e_ent_hall"]
    node_closed = apply_closures(base, simulated=["hall"])
    assert route(node_closed, "ent", "p1").reason == "blocked_by_closure"
    with pytest.raises(UnknownClosureTarget):
        apply_closures(base, simulated=["ghost"])


def test_position_snapping_respects_level_and_skips_level_transitions():
    g = graph_of()
    # (0.65, 0.2) lies on the bridge (level 1) and above the platform area (level 0).
    on_bridge = find_route(g, RouteRequest(station_id="test_station", source_position=(0.65, 0.2),
                                           source_level=1, destination="fob2"))
    assert on_bridge.status == "ok" and on_bridge.start_snap.edge_id == "e_bridge"
    ground = find_route(g, RouteRequest(station_id="test_station", source_position=(0.5, 0.35), source_level=0,
                                        destination="p1", max_snap_distance_m=200))
    assert ground.start_snap.edge_id not in ("e_lift_up", "e_escalator", "e_lift_down")


# ---- the bundled station -----------------------------------------------------------------------------------------

def chennai():
    folder = STATIONS_DIR / "chennai_central"
    station = Station.model_validate(json.loads((folder / "station.json").read_text(encoding="utf-8")))
    meta = StationMetadata.model_validate(json.loads((folder / "metadata.json").read_text(encoding="utf-8")))
    return build_graph(station, meta)


def test_chennai_stairs_entrance_has_no_step_free_route_and_says_why():
    g = chennai()
    plain = route(g, "ent_jn_road", "platform_10")
    assert plain.status == "ok" and "edge_004" in plain.edge_ids
    step_free = route(g, "ent_jn_road", "platform_10", wheelchair=True)
    assert step_free.status == "no_route" and step_free.reason == "accessibility_constraints"
    assert "no step-free alternative is mapped or verified" in step_free.explanation


def test_chennai_step_free_route_from_the_main_entrance_is_unverified():
    r = route(chennai(), "ent_wall_tax", "platform_10", wheelchair=True)
    assert r.status == "ok"
    assert all(s.path_type not in ("stairs", "escalator") for s in r.segments)
    assert r.accessibility_confidence == "unverified"
