from __future__ import annotations

import logging
import math
from typing import Iterable

import ifcopenshell
import ifcopenshell.geom as geom
import ifcopenshell.util.placement as ifc_placement

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float, float, float]


def build_settings() -> geom.settings:
    """Settings for `BBoxCache` only - never used for the actual
    extraction, which copies IFC entities directly and never triangulates
    anything (see `extraction.py`). Because of that, the mesh only ever
    needs to be accurate enough for an envelope (min/max), not for display:
    tessellation tolerance is loosened well below any reasonable
    `proximity_distance`, which can dramatically speed up (or avoid
    near-hangs on) complex or degenerate curved geometry that would
    otherwise be tessellated to visualization-grade precision for no
    benefit here.
    """
    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.DISABLE_OPENING_SUBTRACTIONS, True)
    settings.set(settings.MESHER_LINEAR_DEFLECTION, 0.01)  # 1cm, vs. the 1mm default
    settings.set(settings.CIRCLE_SEGMENTS, 8)  # vs. the default 16
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

    def has(self, guid: str) -> bool:
        """Whether `guid` has already been resolved (or given up on), i.e.
        whether calling `.get()` for it would be free."""
        return guid in self._cache

    def seed(self, guid: str, box: BBox | None) -> None:
        """Pre-populate a cache entry, e.g. with a result carried over from
        a previous worker process so it isn't recomputed after a restart."""
        self._cache[guid] = box

    def get(self, element: ifcopenshell.entity_instance) -> BBox | None:
        guid = element.GlobalId

        if guid in self._cache:
            return self._cache[guid]

        if not element.Representation:
            self._cache[guid] = None
            return None

        try:
            shape = geom.create_shape(self._settings, element)
            verts = shape.geometry.verts
            xs, ys, zs = verts[0::3], verts[1::3], verts[2::3]
            bbox: BBox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        except Exception as exc:
            # Also covers a shape that triangulates "successfully" but with
            # zero vertices (degenerate/non-manifold representation) -
            # min()/max() on an empty sequence raises ValueError, which is
            # exactly as much "this element's geometry is bad" as a
            # create_shape() failure and should be handled the same way.
            logger.warning("Geometry error for %s: %s", guid, exc)
            self._cache[guid] = None
            return None

        self._cache[guid] = bbox
        return bbox


def bbox_distance(a: BBox, b: BBox) -> float:
    dx = max(a[0] - b[3], b[0] - a[3], 0.0)
    dy = max(a[1] - b[4], b[1] - a[4], 0.0)
    dz = max(a[2] - b[5], b[2] - a[5], 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def placement_point(element: ifcopenshell.entity_instance) -> tuple[float, float, float] | None:
    """The world-space origin of `element`'s placement, or None if it has
    no resolvable `ObjectPlacement`.

    Orders of magnitude cheaper than `BBoxCache.get()`: resolving a
    placement chain is a handful of 4x4 matrix multiplications, while
    triangulating a shape invokes the full geometry kernel (profile/sweep/
    boolean evaluation, then meshing) - the part of IfcOpenShell that's
    actually known to hang on malformed geometry (see `BBoxCache`). Used to
    cheaply estimate whether an element is even worth triangulating at all
    (see `is_within_margin` and `worker.py`'s placement pre-filter).

    It's a single point, not the element's true extent, so it's only safe
    to use as a *conservative* (generously margined) pre-filter, never as
    a stand-in for the real bounding box.
    """
    if not element.ObjectPlacement:
        return None
    try:
        matrix = ifc_placement.get_local_placement(element.ObjectPlacement)
    except Exception as exc:
        logger.warning("Placement error for %s: %s", element.GlobalId, exc)
        return None
    return (float(matrix[0, 3]), float(matrix[1, 3]), float(matrix[2, 3]))


def is_within_margin(point: tuple[float, float, float], regions: Iterable[BBox], margin: float) -> bool:
    """Whether `point` is within `margin` of any of `regions` (each an
    exact bbox). Reuses `bbox_distance` by treating `point` as a
    zero-volume box."""
    x, y, z = point
    point_box: BBox = (x, y, z, x, y, z)
    return any(bbox_distance(region, point_box) <= margin for region in regions)


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
