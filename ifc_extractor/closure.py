from __future__ import annotations

from typing import Iterable

import ifcopenshell
import ifcopenshell.util.element as ifc_element


def close_element_set(
    elements: Iterable[ifcopenshell.entity_instance],
) -> set[ifcopenshell.entity_instance]:
    """Expand an initial set of elements into everything that must travel
    with them for their geometry to remain valid in a new file.

    ifcpatch's ExtractElements recipe only pulls in `HasOpenings` for the
    elements it is explicitly told to add, and leaves types/representation
    maps and opening fillings to whatever `file.add()` happens to reach by
    forward reference. That is usually enough, but not always: this closure
    makes the dependency explicit and testable, which matters most for
    railings and stair landings, whose bodies are frequently defined via
    boolean-clipped openings and/or a type's RepresentationMap rather than a
    plain extrusion on the occurrence itself.
    """
    closed: dict[int, ifcopenshell.entity_instance] = {}
    queue: list[ifcopenshell.entity_instance] = list(elements)

    while queue:
        element = queue.pop()
        if element.id() in closed:
            continue
        closed[element.id()] = element

        for rel in ifc_element.get_openings(element):
            opening = rel.RelatedOpeningElement
            queue.append(opening)
            for fill_rel in getattr(opening, "HasFillings", ()):
                queue.append(fill_rel.RelatedBuildingElement)

        element_type = ifc_element.get_type(element)
        if element_type is not None:
            queue.append(element_type)

        for part in ifc_element.get_parts(element):
            queue.append(part)

    return set(closed.values())
