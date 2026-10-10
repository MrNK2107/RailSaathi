"""Small geometry helpers working on normalized image coordinates."""

from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]


def to_pixels(p: Point, width: int, height: int) -> Point:
    return (p[0] * width, p[1] * height)


def polyline_length_px(points: Sequence[Point], width: int, height: int) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot((b[0] - a[0]) * width, (b[1] - a[1]) * height)
    return total


def distance_px(a: Point, b: Point, width: int, height: int) -> float:
    return math.hypot((b[0] - a[0]) * width, (b[1] - a[1]) * height)


def bearing_deg(a: Point, b: Point, width: int, height: int) -> float | None:
    """Screen bearing in degrees, 0 = up (north on a north-up plan), clockwise positive."""
    dx = (b[0] - a[0]) * width
    dy = (b[1] - a[1]) * height
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.degrees(math.atan2(dx, -dy)) % 360


def first_heading(points: Sequence[Point], width: int, height: int) -> float | None:
    for a, b in zip(points, points[1:]):
        h = bearing_deg(a, b, width, height)
        if h is not None:
            return h
    return None


def last_heading(points: Sequence[Point], width: int, height: int) -> float | None:
    for a, b in zip(reversed(points[:-1]), reversed(points[1:])):
        h = bearing_deg(a, b, width, height)
        if h is not None:
            return h
    return None


def compass_name(bearing: float) -> str:
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int(((bearing + 22.5) % 360) // 45)]


def turn_phrase(prev_bearing: float | None, next_bearing: float | None) -> str:
    if prev_bearing is None or next_bearing is None:
        return "Continue"
    delta = (next_bearing - prev_bearing + 540) % 360 - 180  # -180..180, positive = clockwise = right
    if abs(delta) < 30:
        return "Continue straight"
    if abs(delta) > 150:
        return "Turn around"
    side = "right" if delta > 0 else "left"
    return f"Turn {'slightly ' if abs(delta) < 60 else ''}{side}"


def same_point(a: Point, b: Point, eps: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) <= eps and abs(a[1] - b[1]) <= eps


def project_to_polyline(points: Sequence[Point], p: Point, width: int, height: int):
    """Closest point on a normalized polyline to p, measured in image pixels.

    Returns (distance_px, along_px, segment_index, t, projected_point)."""
    best = None
    along = 0.0
    px, py = p[0] * width, p[1] * height
    for i, (a, b) in enumerate(zip(points, points[1:])):
        ax, ay, bx, by = a[0] * width, a[1] * height, b[0] * width, b[1] * height
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (seg * seg)))
        qx, qy = ax + t * dx, ay + t * dy
        d = math.hypot(px - qx, py - qy)
        if best is None or d < best[0]:
            best = (d, along + t * seg, i, t, (qx / width, qy / height))
        along += seg
    return best
