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

    cleaning: CleaningOptions = field(default_factory=CleaningOptions)
