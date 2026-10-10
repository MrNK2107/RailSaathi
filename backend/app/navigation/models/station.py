"""Pydantic models for station graphs, routing requests and disruptions.

Coordinates are normalized image coordinates: (0, 0) is the top-left of the
blueprint image and (1, 1) is the bottom-right.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

STATION_ID_PATTERN = r"^[a-z0-9_]{1,64}$"
ELEMENT_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,80}$"

Accessibility = Literal["verified", "not_accessible", "unknown"]
Verification = Literal["verified", "simulated", "pending"]
OperationalStatus = Literal["open", "closed", "unknown"]

Point = tuple[float, float]


class NodeType(str, Enum):
    entrance = "entrance"
    concourse = "concourse"
    junction = "junction"
    platform_access = "platform_access"
    platform = "platform"
    ticket_counter = "ticket_counter"
    toilet = "toilet"
    information_desk = "information_desk"
    shop = "shop"
    other_facility = "other_facility"


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


class MapInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_system: Literal["normalized_image"] = "normalized_image"


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ELEMENT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    type: NodeType
    position: Point
    verification: Verification
    # Accessibility of the facility itself (e.g. an accessible toilet).
    accessible: Accessibility = "unknown"
    status: OperationalStatus = "open"
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
    # Required with no default: every pathway must state its accessibility explicitly.
    accessible: Accessibility
    status: OperationalStatus
    verification: Verification
    geometry: list[Point] = Field(min_length=2)
    notes: Optional[str] = None


class Station(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    station_id: str = Field(pattern=STATION_ID_PATTERN)
    station_name: str = Field(min_length=1)
    map: MapInfo
    nodes: list[Node]
    edges: list[Edge]

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
    # Exclude pathways whose accessibility is unknown instead of only warning.
    require_verified_accessibility: bool = False


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(pattern=STATION_ID_PATTERN)
    # Start either at a node ...
    source: Optional[str] = Field(default=None, min_length=1)
    # ... or at a position (GPS fix, mock GPS, or "start here" tap), snapped to the nearest walkway.
    source_position: Optional[Point] = None
    source_position_origin: Literal["gps", "mock_gps", "manual"] = "manual"
    max_snap_distance_m: float = Field(default=15.0, gt=0, le=200)
    destination: str = Field(min_length=1)
    preferences: RoutePreferences = RoutePreferences()
    apply_disruptions: bool = True
    # Edge IDs of a previously displayed route, used to explain rerouting.
    previous_edge_ids: list[str] = []

    @model_validator(mode="after")
    def _one_source(self) -> "RouteRequest":
        if (self.source is None) == (self.source_position is None):
            raise ValueError("Provide exactly one of 'source' or 'source_position'")
        if self.source_position is not None and not all(0 <= v <= 1 for v in self.source_position):
            raise ValueError("source_position must be normalized coordinates between 0 and 1")
        return self


class SnapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(pattern=STATION_ID_PATTERN)
    position: Point
    max_snap_distance_m: float = Field(default=15.0, gt=0, le=200)


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
    accessible: Accessibility


class RouteSegment(BaseModel):
    edge_id: str
    partial: bool = False  # True when the walk starts part-way along this edge
    from_node: str
    to_node: str
    geometry: list[Point]
    path_type: str
    steps: Optional[int]
    accessible: Accessibility
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
    simulated_disruptions_applied: list[str] = []
    start_snap: Optional[SnapResult] = None
    source_position_origin: Optional[Literal["gps", "mock_gps", "manual"]] = None
    along_the_way: list[AlongTheWayItem] = []


# ---------------------------------------------------------------------------
# Disruptions (simulated, runtime overlay only)
# ---------------------------------------------------------------------------


class DisruptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["edge", "node"]
    target_id: str = Field(min_length=1)
    reason: str = Field(default="Simulated closure", max_length=200)


class Disruption(BaseModel):
    id: str
    station_id: str
    target_type: Literal["edge", "node"]
    target_id: str
    kind: Literal["pathway_closure", "facility_outage"]
    reason: str
    created_at: datetime
    simulated: Literal[True] = True
