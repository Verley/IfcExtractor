from __future__ import annotations

import ifcopenshell
import ifcopenshell.util.element as ifc_element


def anchor_group(anchor: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
    """The anchor itself plus everything decomposed under it.

    Generalizes the common IfcStair -> IfcStairFlight case: an IfcRamp's
    IfcRampFlight parts, or a bare anchor type with no parts at all, are
    handled the same way.
    """
    return [anchor, *ifc_element.get_parts(anchor)]


def anchor_label(anchor_type: str) -> str:
    label = anchor_type[3:] if anchor_type.startswith("Ifc") else anchor_type
    return label.lower()


def output_filename(model_name: str, anchor_type: str, guid: str) -> str:
    return f"{model_name}_{anchor_label(anchor_type)}_{guid}.ifc"
