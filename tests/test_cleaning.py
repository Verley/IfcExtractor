import ifcopenshell.geom as geom

from ifc_extractor.cleaning import clean_ifc
from ifc_extractor.config import CleaningOptions

from tests.fixtures.builder import add_material_and_style, add_owner_history, build_wall_with_extruded_body


def _verts(wall):
    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    return list(geom.create_shape(settings, wall).geometry.verts)


def test_clean_ifc_removes_nothing_by_default():
    f, wall = build_wall_with_extruded_body()
    add_material_and_style(f, wall)

    clean_ifc(f, CleaningOptions())

    assert f.by_type("IfcMaterial")
    assert f.by_type("IfcStyledItem")


def test_removing_materials_and_styles_does_not_change_geometry():
    f, wall = build_wall_with_extruded_body()
    add_material_and_style(f, wall)
    before = _verts(wall)

    clean_ifc(f, CleaningOptions(remove_materials=True, remove_styles=True))

    assert not f.by_type("IfcMaterial")
    assert not f.by_type("IfcStyledItem")
    assert _verts(wall) == before


def test_removing_owner_history_scrubs_person_and_organization():
    """Regression test: a real person's name embedded via Revit's owner
    history (IfcOwnerHistory -> IfcPersonAndOrganization -> IfcPerson) must
    not survive `remove_owner_history=True`. Removing only IfcOwnerHistory
    itself leaves IfcPerson/IfcOrganization orphaned but still present -
    this is exactly the gap found in the real reference model, which still
    contained the modeler's name after the (previous) unconditional cleanup.
    """
    f, wall = build_wall_with_extruded_body()
    add_owner_history(f, wall)

    clean_ifc(f, CleaningOptions(remove_owner_history=True))

    assert not f.by_type("IfcOwnerHistory")
    assert not f.by_type("IfcPersonAndOrganization")
    assert not f.by_type("IfcPerson")
    assert not f.by_type("IfcOrganization")
    assert not f.by_type("IfcApplication")
    assert wall.OwnerHistory is None
