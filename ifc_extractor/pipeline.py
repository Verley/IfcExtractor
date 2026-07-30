from __future__ import annotations

import logging
import os

import ifcopenshell
import ifcopenshell.util.element as ifc_element

from .cleaning import clean_ifc
from .config import ExtractionConfig
from .extraction import extract_elements
from .geometry import BBoxCache, build_settings, find_nearby

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Tracks which (model, anchor) pairs have already been processed, so
    re-running the pipeline skips completed work. Backed by a plain text
    file of `f"{model_name}__{anchor_guid}"` lines, matching the original
    notebook's format.
    """

    def __init__(self, progress_file: str) -> None:
        self._progress_file = progress_file
        self._processed: set[str] = set()
        if os.path.exists(progress_file):
            with open(progress_file, "r") as f:
                self._processed = set(f.read().splitlines())

    def is_done(self, key: str) -> bool:
        return key in self._processed

    def mark_done(self, key: str) -> None:
        self._processed.add(key)
        with open(self._progress_file, "a") as f:
            f.write(key + "\n")


def _anchor_group(anchor: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
    """The anchor itself plus everything decomposed under it.

    Generalizes the original notebook's IfcStair -> IfcStairFlight-specific
    logic: an IfcRamp's IfcRampFlight parts, or a bare anchor type with no
    parts at all, are handled the same way.
    """
    return [anchor, *ifc_element.get_parts(anchor)]


def _anchor_label(anchor_type: str) -> str:
    label = anchor_type[3:] if anchor_type.startswith("Ifc") else anchor_type
    return label.lower()


def process_ifc(
    input_ifc: str,
    model_name: str,
    config: ExtractionConfig,
    progress: ProgressTracker,
) -> None:
    logger.info("Processing: %s", model_name)

    ifc_file = ifcopenshell.open(input_ifc)
    logger.info("Opened: %s (schema %s)", model_name, ifc_file.schema)
    settings = build_settings()
    bbox_cache = BBoxCache(settings)

    target_elements = []
    for type_name in config.target_types:
        logger.info("Counting %s...", type_name)
        elements = ifc_file.by_type(type_name)
        logger.info("%s: %d", type_name, len(elements))
        target_elements.extend(elements)

    anchors = ifc_file.by_type(config.anchor_type)
    logger.info("Total %s: %d", config.anchor_type, len(anchors))

    for index, anchor in enumerate(anchors):
        logger.info("Processing %s %d/%d", config.anchor_type, index + 1, len(anchors))

        process_key = f"{model_name}__{anchor.GlobalId}"
        if progress.is_done(process_key):
            logger.info("Already processed")
            continue

        group = _anchor_group(anchor)
        reference_boxes = [box for box in (bbox_cache.get(el) for el in group) if box is not None]

        nearby = find_nearby(reference_boxes, target_elements, bbox_cache, config.proximity_distance)
        logger.info("Nearby elements: %d", len(nearby))

        elements_to_extract = set(group) | set(nearby)
        logger.info("Total extracted: %d", len(elements_to_extract))

        output = extract_elements(ifc_file, elements_to_extract)
        clean_ifc(output, config.cleaning)

        output_file = os.path.join(
            config.output_folder,
            f"{model_name}_{_anchor_label(config.anchor_type)}_{anchor.GlobalId}.ifc",
        )
        output.write(output_file)
        logger.info("Saved: %s", output_file)

        progress.mark_done(process_key)


def run_pipeline(config: ExtractionConfig) -> None:
    os.makedirs(config.output_folder, exist_ok=True)
    progress_file = os.path.join(config.output_folder, "processed.txt")
    progress = ProgressTracker(progress_file)

    for filename in config.ifc_queue:
        input_ifc = os.path.join(config.input_folder, filename)
        model_name = os.path.splitext(filename)[0]
        process_ifc(input_ifc, model_name, config, progress)

    logger.info("ALL FILES FINISHED.")
