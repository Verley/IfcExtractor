from __future__ import annotations

import logging
import math
from typing import Iterable

import ifcopenshell
import ifcopenshell.geom as geom

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float, float, float]


def build_settings() -> geom.settings:
    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.DISABLE_OPENING_SUBTRACTIONS, True)
    return settings


class BBoxCache:
    """Caches the world-space bounding box of each element by GlobalId, so a
    shape is only ever triangulated once per run.

    Kept as an explicit AABB scan (not `ifcopenshell.geom.tree`) because
    `tree.select`/`select_box` returned empty results against the reference
    file in this ifcopenshell build (0.8.5) even for elements with
    confirmed-overlapping bounding boxes; the manual approach is simple and
    verified correct.
    """

    def __init__(self, settings: geom.settings) -> None:
        self._settings = settings
        self._cache: dict[str, BBox | None] = {}

    def get(self, element: ifcopenshell.entity_instance) -> BBox | None:
        guid = element.GlobalId

        if guid in self._cache:
            return self._cache[guid]

        if not element.Representation:
            self._cache[guid] = None
            return None

        try:
            shape = geom.create_shape(self._settings, element)
        except Exception as exc:
            logger.warning("Geometry error for %s: %s", guid, exc)
            self._cache[guid] = None
            return None

        verts = shape.geometry.verts
        xs, ys, zs = verts[0::3], verts[1::3], verts[2::3]
        bbox: BBox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        self._cache[guid] = bbox
        return bbox


def bbox_distance(a: BBox, b: BBox) -> float:
    dx = max(a[0] - b[3], b[0] - a[3], 0.0)
    dy = max(a[1] - b[4], b[1] - a[4], 0.0)
    dz = max(a[2] - b[5], b[2] - a[5], 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def find_nearby(
    reference_boxes: Iterable[BBox],
    candidates: Iterable[ifcopenshell.entity_instance],
    bbox_cache: BBoxCache,
    distance: float,
) -> list[ifcopenshell.entity_instance]:
    """Return every candidate within `distance` of any of `reference_boxes`."""
    reference_boxes = list(reference_boxes)
    nearby = []

    for candidate in candidates:
        box = bbox_cache.get(candidate)
        if box is None:
            continue

        for ref_box in reference_boxes:
            if bbox_distance(ref_box, box) <= distance:
                nearby.append(candidate)
                break

    return nearby
