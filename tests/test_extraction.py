import ifcopenshell.geom as geom

from ifc_extractor.extraction import extract_elements

from tests.fixtures.builder import (
    build_slab_with_same_named_profiles,
    build_stair_with_flight_and_landing,
    build_wall_with_extruded_body,
    build_wall_with_opening_and_type,
)


def test_extract_preserves_schema():
    f, ids = build_wall_with_opening_and_type()

    output = extract_elements(f, [ids["wall"]])

    assert output.schema == f.schema


def test_extract_includes_closed_graph():
    f, ids = build_wall_with_opening_and_type()

    output = extract_elements(f, [ids["wall"]])

    assert len(output.by_type("IfcWall")) == 1
    assert len(output.by_type("IfcOpeningElement")) == 1
    assert len(output.by_type("IfcDoor")) == 1
    assert len(output.by_type("IfcWallType")) == 1


def test_extract_rebuilds_spatial_tree():
    f, ids = build_wall_with_opening_and_type()

    output = extract_elements(f, [ids["wall"]])

    storeys = output.by_type("IfcBuildingStorey")
    assert len(storeys) == 1

    contained = output.by_type("IfcRelContainedInSpatialStructure")
    assert len(contained) == 1
    assert output.by_type("IfcWall")[0] in contained[0].RelatedElements

    # Project -> Site -> Building -> Storey: 3 aggregation links.
    assert len(output.by_type("IfcRelAggregates")) == 3


def test_extract_preserves_representation_geometry():
    """Regression guard for the reported bug: extraction must not distort or
    box-approximate a `Body` representation - vertex count before and after
    must match exactly.
    """
    f, wall = build_wall_with_extruded_body()

    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    original_verts = geom.create_shape(settings, wall).geometry.verts

    output = extract_elements(f, [wall])
    extracted_wall = output.by_type("IfcWall")[0]
    extracted_verts = geom.create_shape(settings, extracted_wall).geometry.verts

    assert len(extracted_verts) == len(original_verts)
    assert list(extracted_verts) == list(original_verts)

    body_reps = [
        rep.RepresentationType
        for rep in extracted_wall.Representation.Representations
    ]
    assert "SweptSolid" in body_reps


def test_extract_keeps_same_named_profiles_distinct():
    """Regression test for the confirmed root cause of the reported bug:
    `ifcpatch.ExtractElements` deduplicates profiles/materials/styles by
    name (`assume_asset_uniqueness_by_name`), which silently merges two
    genuinely different profiles that happen to share a `ProfileName` (a
    real pattern found in `3uKgU5mEHEsBxzSkRowr9b.ifc`'s stair landing,
    named "200mm_Thickness" on both extrusions) - corrupting the second
    extrusion's cross-section. This extraction must copy by entity
    identity, not by name, and keep the two profiles distinct.
    """
    f, slab = build_slab_with_same_named_profiles()
    original_items = slab.Representation.Representations[0].Items
    assert original_items[0].SweptArea.id() != original_items[1].SweptArea.id()

    output = extract_elements(f, [slab])
    extracted_slab = output.by_type("IfcSlab")[0]
    extracted_items = extracted_slab.Representation.Representations[0].Items

    assert extracted_items[0].SweptArea.id() != extracted_items[1].SweptArea.id()
    assert extracted_items[0].SweptArea.OuterCurve != extracted_items[1].SweptArea.OuterCurve


def test_extract_keeps_aggregation_children_without_direct_container():
    """Regression test for a second bug caught against the real reference
    model: a stair's flight and landing are `IsDecomposedBy` children with no
    `IfcRelContainedInSpatialStructure` of their own (their spatial location
    is implied by the aggregate). Rebuilding the tree using only
    `get_container(..., should_get_direct=True)` silently drops them - the
    fix walks `get_aggregate` first, falling back to direct containment.
    """
    f, ids = build_stair_with_flight_and_landing()

    output = extract_elements(f, [ids["stair"], ids["flight"], ids["landing"]])

    out_stair = output.by_type("IfcStair")[0]
    decomposed = {rel.RelatingObject: rel.RelatedObjects for rel in output.by_type("IfcRelAggregates")}
    assert set(decomposed[out_stair]) == set(output.by_type("IfcStairFlight") + output.by_type("IfcSlab"))

    contained = output.by_type("IfcRelContainedInSpatialStructure")
    assert len(contained) == 1
    assert list(contained[0].RelatedElements) == [out_stair]
