from __future__ import annotations

from typing import Iterable

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element as ifc_element

from .closure import close_element_set


def extract_elements(
    ifc_file: ifcopenshell.file,
    elements: Iterable[ifcopenshell.entity_instance],
) -> ifcopenshell.file:
    """Extract a self-contained subset of `ifc_file` into a new file.

    Replaces `ifcpatch.execute(recipe="ExtractElements")`. That recipe has a
    confirmed issue where the output schema can silently differ from the
    source (IfcOpenShell issue #6414); porting entities across schema
    versions can make ifcopenshell fall back to a simplified geometry for
    representations it can't migrate faithfully (e.g. the boolean-clipped
    bodies typical of railings and stair landings). This function always
    creates the new file with the exact same schema as the source, and
    closes the element set explicitly (see `closure.py`) before copying, so
    nothing referenced by the kept geometry is left dangling.
    """
    new_file = ifcopenshell.file(schema=ifc_file.schema)

    closed_elements = close_element_set(elements)
    for element in closed_elements:
        new_file.add(element)

    _rebuild_spatial_tree(new_file, closed_elements)

    return new_file


def _immediate_parent(
    node: ifcopenshell.entity_instance,
) -> tuple[str, ifcopenshell.entity_instance] | None:
    """The single relationship that places `node` in the combined spatial /
    decomposition tree, and its kind.

    An element's parent comes from *one or the other* of two relationships,
    never both: `IfcRelAggregates` (e.g. a stair's flight and landing, which
    have no `IfcRelContainedInSpatialStructure` of their own - their spatial
    location is implied entirely by the aggregate they belong to) or
    `IfcRelContainedInSpatialStructure` (e.g. the stair itself, or a railing
    placed directly in a storey with no aggregation involved). Checking only
    containment (as `ifcopenshell.util.element.get_container` does when
    `should_get_direct=True`) silently drops aggregation children out of the
    rebuilt tree - this was a real bug caught against the reference model,
    where the stair's landing/flight are `IsDecomposedBy` children and
    therefore have no direct container at all.
    """
    aggregate = ifc_element.get_aggregate(node)
    if aggregate is not None:
        return "aggregates", aggregate

    contained_in_structure = getattr(node, "ContainedInStructure", None)
    if contained_in_structure:
        return "contains", contained_in_structure[0].RelatingStructure

    return None


def _rebuild_spatial_tree(
    new_file: ifcopenshell.file,
    source_elements: Iterable[ifcopenshell.entity_instance],
) -> None:
    """Recreate spatial containment/decomposition relations in `new_file`.

    `file.add()` only follows forward attribute references, so the inverse
    relationships that place an element in the spatial tree
    (IfcRelContainedInSpatialStructure, IfcRelAggregates) are not copied
    automatically and must be rebuilt here from the source model. `add()` is
    memoized per target file (repeated calls with the same source entity
    return the same target entity), so parents can be looked up freely.
    """
    contained_in: dict[ifcopenshell.entity_instance, set[ifcopenshell.entity_instance]] = {}
    aggregates: dict[ifcopenshell.entity_instance, set[ifcopenshell.entity_instance]] = {}

    for element in source_elements:
        child = element
        while (edge := _immediate_parent(child)) is not None:
            kind, parent = edge
            (aggregates if kind == "aggregates" else contained_in).setdefault(parent, set()).add(child)
            child = parent

    for container, members in contained_in.items():
        new_file.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=ifcopenshell.guid.new(),
            RelatingStructure=new_file.add(container),
            RelatedElements=[new_file.add(member) for member in members],
        )

    for parent, children in aggregates.items():
        new_file.create_entity(
            "IfcRelAggregates",
            GlobalId=ifcopenshell.guid.new(),
            RelatingObject=new_file.add(parent),
            RelatedObjects=[new_file.add(child) for child in children],
        )
