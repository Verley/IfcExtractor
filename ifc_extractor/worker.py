from __future__ import annotations

import logging
import os
from multiprocessing.connection import Connection

import ifcopenshell

from .anchors import anchor_group, output_filename
from .cleaning import clean_ifc
from .config import ExtractionConfig
from .extraction import extract_elements
from .geometry import BBox, BBoxCache, build_settings, find_nearby, is_within_margin, placement_point


def _resolve_bbox(
    bbox_cache: BBoxCache, element: ifcopenshell.entity_instance, conn: Connection
) -> BBox | None:
    """Compute (or fetch) `element`'s bbox, reporting progress to the
    parent as it goes.

    Every *new* computation is bracketed by an ("attempt", guid) message
    before the call and a ("bbox", guid, box) message after. If this
    process gets killed for taking too long, the parent can tell from the
    last "attempt" it saw exactly which element was in flight - seeding it
    as `None` in a fresh worker without ever recomputing anything that
    already resolved successfully. Already-cached elements (seeded from a
    previous worker, or resolved earlier in this one) are returned
    directly, without any message, since the parent already knows them.
    """
    guid = element.GlobalId
    if bbox_cache.has(guid):
        return bbox_cache.get(element)

    conn.send(("attempt", guid))
    box = bbox_cache.get(element)
    conn.send(("bbox", guid, box))
    return box


def _index_target_elements(
    bbox_cache: BBoxCache,
    target_elements: list[ifcopenshell.entity_instance],
    anchors: dict[str, ifcopenshell.entity_instance],
    config: ExtractionConfig,
    conn: Connection,
) -> None:
    """Resolve every candidate element's bbox, optionally skipping the ones
    that `placement_point` + `is_within_margin` can already tell are nowhere
    near any anchor - without ever triangulating them at all.

    Anchor *regions* (not just each anchor's own bbox) are triangulated
    first to build the reference points for that filter: many real-world
    anchors - an `IfcStair`, notably - have no `Representation` of their
    own at all, only their decomposition parts (flight, landing, ...) do
    (see `anchor_group`). If no region could be resolved for any anchor at
    all, the filter has nothing to compare against, so every candidate is
    triangulated normally instead (fail open, never fail closed).
    """
    regions: list[BBox] = []
    if config.use_placement_prefilter:
        for anchor in anchors.values():
            for element in anchor_group(anchor):
                box = _resolve_bbox(bbox_cache, element, conn)
                if box is not None:
                    regions.append(box)

    if regions:
        margin = config.proximity_distance + config.placement_prefilter_margin
        for element in target_elements:
            guid = element.GlobalId
            if bbox_cache.has(guid):
                continue

            point = placement_point(element)
            if point is not None and not is_within_margin(point, regions, margin):
                bbox_cache.seed(guid, None)
                continue

            _resolve_bbox(bbox_cache, element, conn)
    else:
        for element in target_elements:
            _resolve_bbox(bbox_cache, element, conn)


def _write_atomically(output: ifcopenshell.file, output_file: str) -> None:
    """Write `output` to `output_file` without ever leaving a truncated
    file at that path if the process is killed mid-write (e.g. by a
    finalize-phase timeout in the parent): write to a temp file in the
    same directory, then atomically move it into place.
    """
    tmp_file = output_file + ".tmp"
    output.write(tmp_file)
    os.replace(tmp_file, output_file)


def worker_main(
    conn: Connection,
    input_ifc: str,
    model_name: str,
    config: ExtractionConfig,
    seed_bboxes: dict[str, BBox | None],
) -> None:
    """Entry point for the per-file worker process.

    Runs the whole per-anchor pipeline in a separate OS process so a hung
    `geom.create_shape` call (e.g. on malformed geometry) can be killed
    outright by the parent via `Process.terminate()`. A thread-based
    timeout can't interrupt a blocking call into IfcOpenShell's C++ core -
    the thread just keeps consuming CPU forever in the background - but an
    OS process can always be killed.

    `seed_bboxes` pre-populates the bbox cache (see `_resolve_bbox`) so a
    restart after a single slow element or anchor doesn't have to
    retriangulate every other element in the model.

    Configures basic logging on entry: this runs in a freshly spawned
    process (Windows/macOS "spawn"), which does not inherit the parent's
    `logging.basicConfig(...)` - without this, warnings logged in here
    (e.g. `BBoxCache`'s "Geometry error for %s" from a real, non-timeout
    failure) would silently go to Python's bare last-resort handler
    instead of the notebook's configured output.

    Protocol over `conn`:
      worker -> parent: ("attempt", guid) / ("bbox", guid, box) around
                         every newly computed element bbox.
      worker -> parent: ("missing_anchors", [guid, ...]) for any requested
                         `config.anchor_guids` not found in this file (only
                         sent when `anchor_guids` is set).
      worker -> parent: ("ready", [guid, ...]) once the file is open, its
                         candidate elements are indexed, or ("fatal",
                         message) if opening/indexing failed outright.
      parent -> worker: a GlobalId string to process next, or "stop".
      worker -> parent: ("finalizing", guid) once an anchor's own geometry
                         is resolved and it has moved on to the proximity
                         search and write-to-disk step (which never calls
                         into IfcOpenShell's triangulation).
      worker -> parent: ("done", guid, extracted_count, output_file) on
                         success, or ("error", guid, message) on failure.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        ifc_file = ifcopenshell.open(input_ifc)
        settings = build_settings()
        bbox_cache = BBoxCache(settings)
        for guid, box in seed_bboxes.items():
            bbox_cache.seed(guid, box)

        if config.anchor_guids:
            anchors = {}
            missing = []
            for guid in config.anchor_guids:
                try:
                    anchors[guid] = ifc_file.by_guid(guid)
                except RuntimeError:
                    missing.append(guid)
            if missing:
                conn.send(("missing_anchors", missing))
        else:
            anchors = {a.GlobalId: a for a in ifc_file.by_type(config.anchor_type)}

        target_elements = []
        for type_name in config.target_types:
            target_elements.extend(ifc_file.by_type(type_name))

        _index_target_elements(bbox_cache, target_elements, anchors, config, conn)

        conn.send(("ready", list(anchors.keys())))
    except Exception as exc:
        conn.send(("fatal", str(exc)))
        return

    while True:
        message = conn.recv()
        if message == "stop":
            return

        guid = message
        try:
            anchor = anchors[guid]
            group = anchor_group(anchor)
            reference_boxes = [
                box for box in (_resolve_bbox(bbox_cache, el, conn) for el in group) if box is not None
            ]
            conn.send(("finalizing", guid))

            nearby = find_nearby(reference_boxes, target_elements, bbox_cache, config.proximity_distance)
            elements_to_extract = set(group) | set(nearby)

            output = extract_elements(ifc_file, elements_to_extract)
            clean_ifc(output, config.cleaning)

            output_file = os.path.join(
                config.output_folder,
                # anchor.is_a(), not config.anchor_type: identical when
                # anchors come from by_type(config.anchor_type), but
                # correct even when config.anchor_guids names elements of
                # mixed/different types.
                output_filename(model_name, anchor.is_a(), guid),
            )
            _write_atomically(output, output_file)
            conn.send(("done", guid, len(elements_to_extract), output_file))
        except Exception as exc:
            conn.send(("error", guid, str(exc)))
