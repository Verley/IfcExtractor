from ifc_extractor.geometry import BBoxCache, bbox_distance, build_settings, find_nearby

from tests.fixtures.builder import build_wall_with_extruded_body, new_wall_in


def test_bbox_cache_returns_none_without_representation():
    f, wall = build_wall_with_extruded_body()
    empty = f.create_entity("IfcWall", GlobalId="0" * 22)

    cache = BBoxCache(build_settings())

    assert cache.get(wall) is not None
    assert cache.get(empty) is None


def test_bbox_distance_is_zero_for_overlapping_boxes():
    box_a = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    box_b = (0.5, 0.5, 0.5, 2.0, 2.0, 2.0)

    assert bbox_distance(box_a, box_b) == 0.0


def test_bbox_distance_measures_gap_along_one_axis():
    box_a = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    box_b = (2.0, 0.0, 0.0, 3.0, 1.0, 1.0)

    assert bbox_distance(box_a, box_b) == 1.0


def test_find_nearby_respects_proximity_distance():
    f, near_wall = build_wall_with_extruded_body()
    far_wall = new_wall_in(f, location=(100.0, 0.0, 0.0))
    close_wall = new_wall_in(f, location=(2.3, 0.0, 0.0))

    cache = BBoxCache(build_settings())
    reference_boxes = [cache.get(near_wall)]

    nearby = find_nearby(reference_boxes, [far_wall, close_wall], cache, distance=0.5)

    assert close_wall in nearby
    assert far_wall not in nearby
