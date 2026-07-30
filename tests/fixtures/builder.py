from __future__ import annotations

import ifcopenshell
import ifcopenshell.guid as guid


def build_wall_with_opening_and_type() -> tuple[ifcopenshell.file, dict[str, ifcopenshell.entity_instance]]:
    """A minimal spatial tree (Project -> Site -> Building -> Storey) with a
    typed IfcWall that has an opening, itself filled by a door - enough to
    exercise closure over HasOpenings/HasFillings/IsTypedBy/decomposition
    without needing real geometry.
    """
    f = ifcopenshell.file(schema="IFC4")

    project = f.create_entity("IfcProject", GlobalId=guid.new(), Name="P")
    site = f.create_entity("IfcSite", GlobalId=guid.new(), Name="Site")
    building = f.create_entity("IfcBuilding", GlobalId=guid.new(), Name="Building")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey")

    f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=project, RelatedObjects=[site])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=site, RelatedObjects=[building])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=building, RelatedObjects=[storey])

    wall_type = f.create_entity("IfcWallType", GlobalId=guid.new(), Name="WallType", PredefinedType="STANDARD")
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Wall", PredefinedType="STANDARD")

    f.create_entity("IfcRelDefinesByType", GlobalId=guid.new(), RelatedObjects=[wall], RelatingType=wall_type)
    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[wall],
    )

    opening = f.create_entity("IfcOpeningElement", GlobalId=guid.new(), Name="Opening", PredefinedType="OPENING")
    f.create_entity(
        "IfcRelVoidsElement",
        GlobalId=guid.new(),
        RelatingBuildingElement=wall,
        RelatedOpeningElement=opening,
    )

    door = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="Door")
    f.create_entity(
        "IfcRelFillsElement",
        GlobalId=guid.new(),
        RelatingOpeningElement=opening,
        RelatedBuildingElement=door,
    )

    return f, {
        "project": project,
        "site": site,
        "building": building,
        "storey": storey,
        "wall_type": wall_type,
        "wall": wall,
        "opening": opening,
        "door": door,
    }


def build_stair_with_flight_and_landing() -> tuple[ifcopenshell.file, dict[str, ifcopenshell.entity_instance]]:
    """Reproduces the real reference model's structure: a storey directly
    contains an `IfcStair` (via `IfcRelContainedInSpatialStructure`), and the
    stair `IsDecomposedBy` an `IfcStairFlight` and a landing `IfcSlab` (via
    `IfcRelAggregates`) - neither of which has any
    `IfcRelContainedInSpatialStructure` of its own. Their spatial location is
    implied entirely by the aggregation.
    """
    f = ifcopenshell.file(schema="IFC4")

    project = f.create_entity("IfcProject", GlobalId=guid.new(), Name="P")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey")
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=project, RelatedObjects=[storey])

    stair = f.create_entity("IfcStair", GlobalId=guid.new(), Name="Stair")
    flight = f.create_entity("IfcStairFlight", GlobalId=guid.new(), Name="Flight")
    landing = f.create_entity("IfcSlab", GlobalId=guid.new(), Name="Landing", PredefinedType="LANDING")

    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[stair],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=guid.new(),
        RelatingObject=stair,
        RelatedObjects=[flight, landing],
    )

    return f, {"project": project, "storey": storey, "stair": stair, "flight": flight, "landing": landing}


def build_wall_with_extruded_body(
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    existing: tuple[ifcopenshell.file, ifcopenshell.entity_instance, ifcopenshell.entity_instance] | None = None,
) -> tuple[ifcopenshell.file, ifcopenshell.entity_instance]:
    """A single IfcWall, contained in a storey, with a real extruded-solid
    `Body` representation - used to check that extraction preserves actual
    geometry (vertex count), not just topology.

    Pass `existing=(file, storey, context)` (as returned alongside the wall
    is not enough - see `new_wall_in` below) to add a second wall into an
    already-built model, e.g. for proximity tests.
    """
    if existing is None:
        f = ifcopenshell.file(schema="IFC4")

        project = f.create_entity("IfcProject", GlobalId=guid.new(), Name="P")
        storey = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey")
        f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=project, RelatedObjects=[storey])

        context = f.create_entity(
            "IfcGeometricRepresentationContext",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1e-5,
            WorldCoordinateSystem=f.create_entity(
                "IfcAxis2Placement3D",
                Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
            ),
        )
    else:
        f, storey, context = existing

    profile = f.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=2.0,
        YDim=0.2,
    )
    solid = f.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
        ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=3.0,
    )
    shape_rep = f.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid],
    )

    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Wall", PredefinedType="STANDARD")
    wall.ObjectPlacement = f.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=location),
        ),
    )
    wall.Representation = f.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[wall],
    )

    return f, wall


def new_wall_in(f: ifcopenshell.file, location: tuple[float, float, float]) -> ifcopenshell.entity_instance:
    """Adds a second wall to a file already built by
    `build_wall_with_extruded_body`, at the given location - for proximity
    tests that need two independent elements in the same model.
    """
    storey = f.by_type("IfcBuildingStorey")[0]
    context = f.by_type("IfcGeometricRepresentationContext")[0]
    _, wall = build_wall_with_extruded_body(location=location, existing=(f, storey, context))
    return wall


def add_material_and_style(f: ifcopenshell.file, wall: ifcopenshell.entity_instance) -> None:
    """Attaches a material association and a styled item/surface style to an
    existing wall (as built by `build_wall_with_extruded_body`), so tests
    can check that removing them via `clean_ifc` doesn't touch geometry.
    """
    material = f.create_entity("IfcMaterial", Name="Concrete")
    f.create_entity(
        "IfcRelAssociatesMaterial",
        GlobalId=guid.new(),
        RelatedObjects=[wall],
        RelatingMaterial=material,
    )

    solid = wall.Representation.Representations[0].Items[0]
    style = f.create_entity(
        "IfcSurfaceStyle",
        Name="Grey",
        Side="BOTH",
        Styles=[f.create_entity("IfcSurfaceStyleShading", SurfaceColour=f.create_entity(
            "IfcColourRgb", Red=0.5, Green=0.5, Blue=0.5,
        ))],
    )
    f.create_entity(
        "IfcStyledItem",
        Item=solid,
        Styles=[f.create_entity("IfcPresentationStyleAssignment", Styles=[style])],
    )


def add_owner_history(f: ifcopenshell.file, element: ifcopenshell.entity_instance) -> None:
    """Attaches an `IfcOwnerHistory` (with a real-shaped person/org/app
    chain, mirroring what Revit embeds on export) to an existing element -
    so tests can check that `remove_owner_history` actually scrubs the
    modeler's identity, not just the `IfcOwnerHistory` wrapper.
    """
    person = f.create_entity("IfcPerson", FamilyName="Doe", GivenName="Jane")
    organization = f.create_entity("IfcOrganization", Name="Acme Corp")
    person_and_org = f.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=organization)
    application = f.create_entity(
        "IfcApplication",
        ApplicationDeveloper=organization,
        Version="2024",
        ApplicationFullName="Autodesk Revit 2024",
        ApplicationIdentifier="Revit",
    )
    owner_history = f.create_entity(
        "IfcOwnerHistory",
        OwningUser=person_and_org,
        OwningApplication=application,
        ChangeAction="NOCHANGE",
        CreationDate=0,
    )
    element.OwnerHistory = owner_history


def _polyline(f: ifcopenshell.file, points: list[tuple[float, float]]) -> ifcopenshell.entity_instance:
    return f.create_entity(
        "IfcPolyline",
        Points=[f.create_entity("IfcCartesianPoint", Coordinates=p) for p in points],
    )


def build_slab_with_same_named_profiles() -> tuple[ifcopenshell.file, ifcopenshell.entity_instance]:
    """A slab whose `Body` has two `IfcExtrudedAreaSolid` items with
    genuinely different profile geometry that happen to share the same
    `ProfileName` ("200mm_Thickness") - the exact pattern found in the real
    reference model (`3uKgU5mEHEsBxzSkRowr9b.ifc`'s stair landing).

    `ifcpatch`'s `ExtractElements` recipe deduplicates profiles/materials/
    styles by name (`assume_asset_uniqueness_by_name`, default True), which
    collapses these two distinct profiles into one and corrupts the second
    extrusion's cross-section - this is the confirmed root cause of the
    landing/railing distortion bug.
    """
    f = ifcopenshell.file(schema="IFC4")

    project = f.create_entity("IfcProject", GlobalId=guid.new(), Name="P")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey")
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(), RelatingObject=project, RelatedObjects=[storey])

    context = f.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )

    profile_a = f.create_entity(
        "IfcArbitraryClosedProfileDef",
        ProfileType="AREA",
        ProfileName="200mm_Thickness",
        OuterCurve=_polyline(f, [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]),
    )
    profile_b = f.create_entity(
        "IfcArbitraryClosedProfileDef",
        ProfileType="AREA",
        ProfileName="200mm_Thickness",
        OuterCurve=_polyline(f, [(0.0, 0.0), (5.0, 0.0), (5.0, 3.0), (0.0, 3.0), (0.0, 0.0)]),
    )

    position = f.create_entity(
        "IfcAxis2Placement3D",
        Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
    )
    direction = f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))

    solid_a = f.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile_a, Position=position, ExtrudedDirection=direction, Depth=1.0
    )
    solid_b = f.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile_b, Position=position, ExtrudedDirection=direction, Depth=1.0
    )

    shape_rep = f.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid_a, solid_b],
    )

    slab = f.create_entity("IfcSlab", GlobalId=guid.new(), Name="Slab", PredefinedType="LANDING")
    slab.ObjectPlacement = f.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )
    slab.Representation = f.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[slab],
    )

    return f, slab
