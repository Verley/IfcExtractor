from __future__ import annotations

import logging

import ifcopenshell

from .config import CleaningOptions

logger = logging.getLogger(__name__)


def clean_ifc(ifc_model: ifcopenshell.file, options: CleaningOptions) -> None:
    """Strip metadata from an extracted IFC file, in place.

    Every removal here is opt-in (see `CleaningOptions`) because the
    original unconditional version of this function was never verified not
    to affect the `Body` representation of railings/slabs — see
    tests/test_cleaning.py for the regression check that justifies enabling
    a given flag.
    """
    if options.remove_materials:
        logger.info("Removing materials...")
        for rel in list(ifc_model.by_type("IfcRelAssociatesMaterial")):
            ifc_model.remove(rel)
        for obj in list(ifc_model.by_type("IfcMaterial")):
            ifc_model.remove(obj)

    if options.remove_styles:
        logger.info("Removing styles...")
        for obj in list(ifc_model.by_type("IfcStyledItem")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcSurfaceStyle")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcPresentationLayerAssignment")):
            ifc_model.remove(obj)

    if options.remove_owner_history:
        logger.info("Removing owner history...")
        # IfcOwnerHistory only wraps a reference to the actual identifying
        # data (IfcPersonAndOrganization -> IfcPerson/IfcOrganization); it
        # must be removed too, otherwise the modeler's real name/company
        # (e.g. embedded by Revit on export) survives in the file.
        for obj in list(ifc_model.by_type("IfcOwnerHistory")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcPersonAndOrganization")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcPerson")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcOrganization")):
            ifc_model.remove(obj)
        for obj in list(ifc_model.by_type("IfcApplication")):
            ifc_model.remove(obj)
