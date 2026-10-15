"""Pydantic models for station graphs, routing requests and disruptions.

Coordinates are normalized image coordinates: (0, 0) is the top-left of the
blueprint image and (1, 1) is the bottom-right. ``metadata.json`` supplies the
plan scale (``metres_per_pixel``) and the ``geo_reference`` anchor.

Schema version 2 (one migration from version 1):
- ``accessible`` became ``step_free`` (``verified | reported | unknown``) on nodes and edges;
- ``Node.level`` and ``Edge.level_change`` describe floor transitions;
- ``Node.cues``, ``Station.levels``, ``Station.areas`` and ``Station.panoramas`` are optional
  inputs for AR localisation and the 3D tour; ``Station.ar_enabled`` gates the cue coverage check.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.options import DataProvenance

STATION_ID_PATTERN = r"^[a-z0-9_]{1,64}$"
ELEMENT_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,80}$"
MAP_IMAGE_PATTERN = r"^[a-z0-9_\-]{1,64}\.png$"

# Whether a node or pathway can be used without steps: verified on site, reported by a cited source but not
# verified, or unknown. Stairs, escalators and pathways with steps are never step-free, whatever this says.
StepFree = Literal["verified", "reported", "unknown"]
Verification = Literal["verified", "simulated", "pending"]
OperationalStatus = Literal["open", "closed", "unknown"]

Point = tuple[float, float]


class NodeType(str, Enum):
    entrance = "entrance"
    exit = "exit"  # exit-only gate; entrances are exits too
    concourse = "concourse"
    junction = "junction"
    foot_over_bridge = "foot_over_bridge"
    platform_access = "platform_access"
    platform = "platform"
    ticket_counter = "ticket_counter"
    toilet = "toilet"
    information_desk = "information_desk"
    shop = "shop"
    other_facility = "other_facility"


# Nodes a passenger can leave the station through. Each must have a step-free route to every platform or say
# why not in ``Node.step_free_exception``.
EXIT_NODE_TYPES = frozenset({NodeType.entrance, NodeType.exit})


class PathType(str, Enum):
    walkway = "walkway"
    corridor = "corridor"
    doorway = "doorway"
    platform = "platform"
    stairs = "stairs"
    ramp = "ramp"
    escalator = "escalator"
    lift = "lift"
    other = "other"


# Pathways that may change level, and the ones that always have steps.
LEVEL_CHANGE_PATH_TYPES = frozenset({PathType.stairs, PathType.ramp, PathType.escalator, PathType.lift})
STEPPED_PATH_TYPES = frozenset({PathType.stairs, PathType.escalator})


class MapInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = Field(pattern=MAP_IMAGE_PATTERN)  # file name inside the station folder, e.g. "map.png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_system: Literal["normalized_image"] = "normalized_image"


class VisualCue(BaseModel):
    """What a camera would see at a node: signboard text or a distinctive feature, with its provenance."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["signboard", "feature"]
    text: str = Field(min_length=1, max_length=200)  # e.g. "Platform 10", "Wall Tax Road", "Food Plaza"
    # Bearing the camera faces to see the cue, degrees clockwise from plan-up (station frame), if known.
    facing_deg: Optional[float] = Field(default=None, ge=0, lt=360)
    source: str = Field(min_length=1, max_length=300)
    verified_on: Optional[date]  # required key: null states explicitly that the cue is not verified on site


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ELEMENT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    type: NodeType
    position: Point
    level: int = Field(default=0, ge=-5, le=10)  # 0 = ground; 1 = first floor or foot-over-bridge
    verification: Verification
    # Whether the location itself can be used without steps (e.g. a step-free toilet).
    step_free: StepFree = "unknown"
    # Exits only: why this exit has no step-free route to every platform (shown to passengers).
    step_free_exception: Optional[str] = Field(default=None, min_length=1, max_length=300)
    status: OperationalStatus = "open"
    cues: list[VisualCue] = []
    notes: Optional[str] = None


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(pattern=ELEMENT_ID_PATTERN)
    from_: str = Field(alias="from")
    to: str
    bidirectional: bool = True
    distance_m: Optional[float] = Field(default=None, ge=0)
    path_type: PathType
    steps: Optional[int] = Field(default=None, ge=0)
    # Levels gained travelling `from` -> `to` (negative = down). Must equal the nodes' level difference.
    level_change: int = Field(default=0, ge=-10, le=10)
    # Required with no default: every pathway must state its step-free status explicitly.
    step_free: StepFree
    status: OperationalStatus
    verification: Verification
    geometry: list[Point] = Field(min_length=2)
    notes: Optional[str] = None

    @property
    def stepped(self) -> bool:
        """True when the pathway has steps: stairs, an escalator, or a counted step."""
        return self.path_type in STEPPED_PATH_TYPES or (self.steps or 0) > 0


class Level(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: int = Field(ge=-5, le=10)
    name: str = Field(min_length=1, max_length=80)  # e.g. "Ground (concourse)", "Foot-over-bridge"
    elevation_m: Optional[float] = None  # floor height above ground level, if known


class Area(BaseModel):
    """A polygon traced from the map (platform, concourse, building footprint, track bed) for 3D extrusion."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ELEMENT_ID_PATTERN)
    kind: Literal["platform", "concourse", "building_footprint", "track_bed"]
    name: Optional[str] = Field(default=None, max_length=120)
    level: int = Field(default=0, ge=-5, le=10)
    height_m: float = Field(ge=0, le=100)  # extrusion height
    # Closed ring in normalized image coordinates: the last point repeats the first.
    polygon: list[Point] = Field(min_length=4)


class Panorama(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pano_id: str = Field(min_length=1, max_length=200)
    node_id: str = Field(pattern=ELEMENT_ID_PATTERN)  # nearest node
    heading: float = Field(ge=0, lt=360)
    pitch: float = Field(default=0, ge=-90, le=90)
    kind: Literal["street_view", "photosphere"]
    verified_on: Optional[date]  # required key: null states explicitly that the match is not verified


class Station(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    station_id: str = Field(pattern=STATION_ID_PATTERN)
    station_name: str = Field(min_length=1)
    map: MapInfo
    nodes: list[Node]
    edges: list[Edge]
    # AR guidance may be enabled only when cues cover at least 80% of the routable nodes (checked by validate).
    ar_enabled: bool = False
    levels: list[Level] = []
    areas: list[Area] = []
    panoramas: list[Panorama] = []

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


class MapScale(BaseModel):
    metres_per_pixel: float = Field(gt=0)
    source: str
    verification: Verification


class StationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    station_name: str
    city: Optional[str] = None
    map_source: Optional[str] = None
    map_scale: Optional[MapScale] = None
    data_status: str = "mock"
    routing: bool = True  # False: the graph is illustrative, so only the map and information are served
    notes: list[str] = []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RoutePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avoid_stairs: bool = False
    wheelchair: bool = False
    # Exclude pathways whose step-free status is not verified on site, instead of only warning.
    require_verified_accessibility: bool = False


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(pattern=STATION_ID_PATTERN)
    # Start either at a node ...
    source: Optional[str] = Field(default=None, min_length=1)
    # ... or at a position (GPS fix, mock GPS, or "start here" tap), snapped to the nearest walkway.
    source_position: Optional[Point] = None
    source_position_origin: Literal["gps", "mock_gps", "manual"] = "manual"
    # Level of `source_position`; when given, only pathways on that level are considered for snapping.
    source_level: Optional[int] = Field(default=None, ge=-5, le=10)
    max_snap_distance_m: float = Field(default=15.0, gt=0, le=200)
    destination: str = Field(min_length=1)
    preferences: RoutePreferences = RoutePreferences()
    apply_disruptions: bool = True
    # Edge IDs of a previously displayed route, used to explain rerouting.
    previous_edge_ids: list[str] = Field(default=[], max_length=200)
    # What-if closures (edge or node ids) for this request only; nothing is stored. Refused unless public
    # disruption simulation is enabled, which it never is in production.
    simulate_closures: list[str] = Field(default=[], max_length=20)

    @model_validator(mode="after")
    def _one_source(self) -> "RouteRequest":
        if (self.source is None) == (self.source_position is None):
            raise ValueError("Provide exactly one of 'source' or 'source_position'")
        if self.source_position is not None and not all(0 <= v <= 1 for v in self.source_position):
            raise ValueError("source_position must be normalized coordinates between 0 and 1")
        return self


class SnapResult(BaseModel):
    """A free position matched to the nearest open walkway."""

    position: Point
    snapped_position: Point
    edge_id: str
    from_node: str
    to_node: str
    fraction_along_edge: float
    distance_px: float
    distance_m: Optional[float]  # estimate from the plan scale, if known
    within_tolerance: bool
    nearest_node_id: str
    nearest_node_name: str
    message: str


class AlongTheWayItem(BaseModel):
    node_id: str
    name: str
    type: str
    on_route: bool
    distance_from_route_m: Optional[float]  # plan-scale estimate
    progress: float  # 0 = start, 1 = destination
    verification: Verification
    step_free: StepFree


class RouteSegment(BaseModel):
    edge_id: str
    partial: bool = False  # True when the walk starts part-way along this edge
    from_node: str
    to_node: str
    geometry: list[Point]
    path_type: str
    steps: Optional[int]
    level_change: int = 0  # in travel direction
    step_free: StepFree
    status: OperationalStatus
    verification: Verification
    distance_m: Optional[float]
    estimated_distance_m: Optional[float]


class RouteInstruction(BaseModel):
    step: int
    text: str
    node_id: str
    edge_id: Optional[str] = None
    distance_m: Optional[float] = None
    distance_is_estimate: bool = False


class RouteResponse(BaseModel):
    status: Literal["ok", "no_route"]
    station_id: str
    source: str  # node ID, or "current_position" when routing from a position
    destination: str
    preferences: RoutePreferences
    node_ids: list[str] = []
    edge_ids: list[str] = []
    geometry: list[Point] = []
    segments: list[RouteSegment] = []
    distance_m: Optional[float] = None
    estimated_distance_m: Optional[float] = None
    distance_basis: Literal["measured", "estimated_from_map_scale", "unavailable"] = "unavailable"
    estimated_duration_s: Optional[float] = None
    duration_assumption: Optional[str] = None
    accessibility_confidence: Literal["verified", "unverified", "not_applicable"] = "not_applicable"
    warnings: list[str] = []
    instructions: list[RouteInstruction] = []
    reason: Optional[str] = None
    explanation: Optional[str] = None
    blocking_edge_ids: list[str] = []
    previous_route_blocked: bool = False
    previous_route_blocked_edge_ids: list[str] = []
    disruptions_applied: list[str] = []  # ids of stored disruptions applied to this route
    simulated_closures_applied: list[str] = []  # what-if closures from this request
    start_snap: Optional[SnapResult] = None
    source_position_origin: Optional[Literal["gps", "mock_gps", "manual"]] = None
    along_the_way: list[AlongTheWayItem] = []
    provenance: Optional[DataProvenance] = None  # station layouts are static, schematic data


# ---------------------------------------------------------------------------
# Disruptions (runtime overlay with a TTL; written only by internal callers)
# ---------------------------------------------------------------------------


class DisruptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["edge", "node"]
    target_id: str = Field(pattern=ELEMENT_ID_PATTERN)
    reason: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=120)  # who reported it, e.g. "station control room"
    simulated: bool = False  # simulated disruptions are refused in production
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=7 * 86_400)  # default from Settings


class Disruption(BaseModel):
    id: str
    station_id: str
    target_type: Literal["edge", "node"]
    target_id: str
    kind: Literal["pathway_closure", "facility_outage"]
    reason: str
    source: str
    simulated: bool
    created_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------------------
# Catalogue (catalogue.json at the root of the station data, local or Cloud Storage)
# ---------------------------------------------------------------------------

# "<station_id>" for a local folder, "<station_id>/<version>" for a published Cloud Storage version.
CATALOGUE_PATH_PATTERN = r"^[a-z0-9_]{1,64}(/[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63})?$"


class CatalogueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(pattern=STATION_ID_PATTERN)
    station_name: str = Field(min_length=1)
    city: Optional[str] = None
    data_status: str = "mock"
    version: str = Field(min_length=1, max_length=64)  # "local" or the published version folder
    path: str = Field(pattern=CATALOGUE_PATH_PATTERN)  # folder holding station.json, map, metadata, info

    @model_validator(mode="after")
    def _path_matches_station(self) -> "CatalogueEntry":
        if self.path.split("/")[0] != self.station_id:
            raise ValueError("catalogue path must start with the station id")
        return self


class Catalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    stations: list[CatalogueEntry] = []

    @model_validator(mode="after")
    def _unique(self) -> "Catalogue":
        ids = [s.station_id for s in self.stations]
        if len(ids) != len(set(ids)):
            raise ValueError("each station may appear once in the catalogue")
        return self
