from ifc_extractor.closure import close_element_set

from tests.fixtures.builder import build_wall_with_opening_and_type


def test_closure_includes_openings_fillings_and_type():
    _, ids = build_wall_with_opening_and_type()

    closed = close_element_set([ids["wall"]])

    assert ids["wall"] in closed
    assert ids["opening"] in closed
    assert ids["door"] in closed
    assert ids["wall_type"] in closed


def test_closure_does_not_pull_in_unrelated_spatial_structure():
    _, ids = build_wall_with_opening_and_type()

    closed = close_element_set([ids["wall"]])

    assert ids["storey"] not in closed
    assert ids["building"] not in closed
    assert ids["site"] not in closed
    assert ids["project"] not in closed
