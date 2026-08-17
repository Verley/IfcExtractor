from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

DEFAULT_TARGET_TYPES = (
    "IfcWall",
    "IfcMember",
    "IfcRailing",
    "IfcSlab",
    "IfcStairFlight",
    "IfcSpace",
)


@dataclass
class CleaningOptions:
    """Which metadata to strip from an extracted IFC file.

    Defaults to removing nothing: the original notebook stripped materials
    and styles unconditionally, which was never verified to be safe for the
    `Body` representation of railings/slabs. Enable individual flags only
    once a specific removal has been confirmed not to affect geometry (see
    tests/test_cleaning.py).
    """

    remove_materials: bool = False
    remove_styles: bool = False
    remove_owner_history: bool = False


@dataclass
class ExtractionConfig:
    input_folder: str
    output_folder: str
    ifc_queue: Sequence[str]

    anchor_type: str = "IfcStair"
    target_types: Sequence[str] = field(default_factory=lambda: list(DEFAULT_TARGET_TYPES))
    proximity_distance: float = 0.50

    # If set, restrict extraction to exactly these GlobalIds instead of
    # every `anchor_type` element found in each file. Each ID is looked up
    # directly by GlobalId - it doesn't need to be an `anchor_type`
    # instance, any element works - so this is handy for reprocessing a
    # specific handful of elements (e.g. ones that were previously skipped,
    # or flagged for review) without walking the whole model. An ID not
    # present in a given file is logged and skipped, so the same list can
    # safely span multiple files in `ifc_queue`.
    anchor_guids: Sequence[str] | None = None

    cleaning: CleaningOptions = field(default_factory=CleaningOptions)

    # Some geometry (malformed stairs have been observed to trigger this)
    # makes IfcOpenShell's shape triangulation hang indefinitely. Every
    # element's geometry - each anchor's own, and every candidate element
    # considered for the proximity search - is resolved in a worker process
    # that is killed and restarted if it stalls on any single one of them
    # for longer than this many seconds. A stuck candidate element is just
    # dropped from the proximity search; a stuck anchor is skipped
    # entirely. Nothing already resolved is ever recomputed after a
    # restart. Everything skipped is listed once the whole run finishes.
    #
    # Set to None to disable the timeout entirely and wait indefinitely on
    # every element - useful if you'd rather a run take however long it
    # takes than risk skipping something that was only ever slow.
    anchor_timeout_seconds: float | None = 240.0

    # How long to wait for an anchor's proximity search + write-to-disk
    # step, once all its geometry has already been resolved. Kept separate
    # from `anchor_timeout_seconds` (same default, same None-disables
    # meaning, but tunable independently) because this step never calls
    # into IfcOpenShell's triangulation - the part that's actually known to
    # hang - so a large-but-healthy extraction (many nearby elements)
    # shouldn't be penalized by the same tight budget that guards
    # triangulation. Raise it (or set it to None) if large extractions are
    # being skipped as "timed out" when they were only ever slow to write.
    finalize_timeout_seconds: float | None = 240.0

    # Before triangulating a candidate element at all, first check whether
    # it's anywhere near an anchor using only its `ObjectPlacement` -
    # resolving a placement chain is a handful of matrix multiplications,
    # orders of magnitude cheaper than triangulating (`geom.create_shape`),
    # which is the part of IfcOpenShell that's actually known to hang. Any
    # candidate whose placement origin is farther than
    # `proximity_distance + placement_prefilter_margin` from every known
    # anchor region is skipped without ever being triangulated - fewer
    # triangulation calls means both a faster run and less exposure to
    # whatever specific element might have hung it.
    #
    # This is a conservative, not exact, filter: a placement is a single
    # point, not the element's true extent, so an element whose local
    # origin sits far from the rest of its own geometry (e.g. one end of a
    # very long wall) could in principle be filtered out even though part
    # of it is genuinely close to an anchor. `placement_prefilter_margin`
    # exists to absorb that error - raise it if your model has unusually
    # large elements, or disable the prefilter entirely for a model where
    # you'd rather not risk it.
    use_placement_prefilter: bool = True
    placement_prefilter_margin: float = 10.0
