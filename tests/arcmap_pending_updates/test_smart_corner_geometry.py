"""Pure geometry unit tests. Create only; DO NOT RUN until user authorizes.

Compatible with Python 3 test runner; geometry implementation remains Python 2.7-safe.
"""
import os
import sys
import unittest

_ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "arcmap", "engine"))
_BRIDGE = os.path.join(_ENGINE, "arcmap_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

from core.smart_corner_geometry import (
    CornerGeometryError, canonical_hash, classify_vertices,
    normalize_ring, ring_area, select_reviewed_candidates,
)


def closed(points):
    return points + [points[0]]


def rectangle_dense():
    points = (
        [(x, 0) for x in range(0, 41)] +
        [(40, y) for y in range(1, 31)] +
        [(x, 30) for x in range(39, -1, -1)] +
        [(0, y) for y in range(29, 0, -1)]
    )
    return closed(points)


class SmartCornerGeometryTests(unittest.TestCase):
    def test_dense_rectangle_identifies_four_semantic_corners(self):
        rows = classify_vertices(rectangle_dense())
        self.assertEqual(4, rows["counts"]["CORNER"])
        self.assertEqual(0, rows["counts"]["REVIEW"])
        self.assertEqual(len(rectangle_dense()) - 1 - 4, rows["counts"]["STRAIGHT"])
        corners = select_reviewed_candidates(rows)
        self.assertEqual(4, len(corners))
        self.assertEqual({(0, 0), (40, 0), (40, 30), (0, 30)},
                         {(p["x"], p["y"]) for p in corners})
        self.assertEqual(list(range(1, 5)), [p["Id"] for p in corners])
        self.assertEqual((0, 30), (corners[0]["x"], corners[0]["y"]))
        self.assertTrue(rows["clockwise"])

    def test_winding_reversal_produces_same_clockwise_coordinate_sequence(self):
        points = rectangle_dense()[:-1]
        forward = select_reviewed_candidates(classify_vertices(closed(points)))
        reverse = select_reviewed_candidates(classify_vertices(closed(list(reversed(points)))))
        self.assertEqual([(x["x"], x["y"]) for x in forward],
                         [(x["x"], x["y"]) for x in reverse])

    def test_ring_rotation_does_not_change_order(self):
        points = rectangle_dense()[:-1]
        original = select_reviewed_candidates(classify_vertices(closed(points)))
        rotated = select_reviewed_candidates(classify_vertices(closed(points[27:] + points[:27])))
        self.assertEqual([(x["x"], x["y"]) for x in original],
                         [(x["x"], x["y"]) for x in rotated])

    def test_l_shape_preserves_concave_corner(self):
        ring = closed([(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)])
        corners = select_reviewed_candidates(classify_vertices(ring))
        self.assertEqual(6, len(corners))
        self.assertIn((2, 2), {(p["x"], p["y"]) for p in corners})

    def test_small_true_stair_step_not_filtered_by_default(self):
        ring = closed([(0, 0), (10, 0), (10, 5), (9.5, 5),
                       (9.5, 5.5), (9, 5.5), (9, 8), (0, 8)])
        result = classify_vertices(ring)
        self.assertEqual(8, result["counts"]["CORNER"])

    def test_optional_short_edge_moves_corner_to_review(self):
        ring = closed([(0, 0), (10, 0), (10, 5), (9.5, 5),
                       (9.5, 5.5), (9, 5.5), (9, 8), (0, 8)])
        result = classify_vertices(ring, min_segment_length_m=1)
        self.assertGreater(result["counts"]["REVIEW"], 0)

    def test_noncollinear_small_bend_is_review_not_auto_commit(self):
        ring = closed([(0, 0), (5, 0), (10, 0.4), (10, 10), (0, 10)])
        result = classify_vertices(ring)
        ambiguous = [x for x in result["candidates"] if x["class"] == "REVIEW"]
        self.assertGreaterEqual(len(ambiguous), 1)
        chosen = select_reviewed_candidates(result)
        self.assertNotIn((5, 0), {(x["x"], x["y"]) for x in chosen})

    def test_manual_include_exclude_with_reason_and_clockwise_ids(self):
        ring = closed([(0, 0), (5, 0), (10, 0.4), (10, 10), (0, 10)])
        analysis = classify_vertices(ring)
        candidate = next(x for x in analysis["candidates"] if x["class"] == "REVIEW")
        selected = select_reviewed_candidates(analysis,
                                              include_indices=[candidate["vertex_index"]])
        self.assertIn(candidate["vertex_index"], [x["vertex_index"] for x in selected])
        self.assertEqual(list(range(1, len(selected) + 1)),
                         [x["Id"] for x in selected])
        self.assertEqual("MANUAL_INCLUDE",
                         next(x["decision"] for x in selected if x["vertex_index"] ==
                              candidate["vertex_index"]))
        dropped = select_reviewed_candidates(analysis, exclude_indices=[
            next(x["vertex_index"] for x in selected if x["class"] == "CORNER")
        ])
        self.assertEqual(len([c for c in analysis["candidates"] if c["class"] == "CORNER"]) - 1,
                         len(dropped))

    def test_repeated_override_indices_are_rejected(self):
        result = classify_vertices(rectangle_dense())
        index = result["candidates"][0]["vertex_index"]
        with self.assertRaises(CornerGeometryError):
            select_reviewed_candidates(result, include_indices=[index, index])

    def test_include_exclude_conflict_rejected(self):
        result = classify_vertices(rectangle_dense())
        idx = result["candidates"][0]["vertex_index"]
        with self.assertRaises(CornerGeometryError):
            select_reviewed_candidates(result, include_indices=[idx], exclude_indices=[idx])

    def test_unknown_override_rejected(self):
        with self.assertRaises(CornerGeometryError):
            select_reviewed_candidates(classify_vertices(rectangle_dense()),
                                       include_indices=[999999])

    def test_source_coords_preserved_when_metric_coords_different(self):
        base = closed([(120, 10), (120.02, 10), (120.02, 10.01), (120, 10.01)])
        original = []
        for i, (x, y) in enumerate(base):
            original.append({"x": x, "y": y,
                             "metric_x": x * 100000, "metric_y": y * 100000,
                             "vertex_index": i})
        chosen = select_reviewed_candidates(classify_vertices(original))
        self.assertEqual({(x, y) for x, y in base[:-1]},
                         {(c["x"], c["y"]) for c in chosen})

    def test_closure_duplicate_removed_once(self):
        normal = normalize_ring(rectangle_dense())
        self.assertEqual(len(rectangle_dense()) - 1, len(normal["vertices"]))

    def test_consecutive_duplicate_does_not_duplicate_corner(self):
        ring = closed([(0, 0), (10, 0), (10, 0), (10, 10), (0, 10)])
        result = classify_vertices(ring)
        self.assertEqual(4, result["counts"]["CORNER"])
        self.assertEqual(1, len(result["removed_duplicate_indices"]))

    def test_self_intersection_rejected(self):
        bowtie = closed([(0, 0), (3, 3), (0, 3), (3, 0)])
        with self.assertRaises(CornerGeometryError):
            classify_vertices(bowtie)

    def test_zero_area_rejected(self):
        with self.assertRaises(CornerGeometryError):
            classify_vertices(closed([(0, 0), (1, 0), (2, 0)]))

    def test_nonfinite_coordinate_rejected(self):
        with self.assertRaises(CornerGeometryError):
            classify_vertices(closed([(0, 0), (2, 0), (2, float("nan")), (0, 2)]))

    def test_bad_parameters_rejected(self):
        with self.assertRaises(CornerGeometryError):
            classify_vertices(rectangle_dense(), min_turn_deg=2, straight_turn_deg=3)
        with self.assertRaises(CornerGeometryError):
            classify_vertices(rectangle_dense(), collinear_tolerance_m=-1)

    def test_too_few_selected_corners_only_blocks_commit_not_preview(self):
        result = classify_vertices(rectangle_dense())
        all_corner_indices = [c["vertex_index"] for c in result["candidates"]
                              if c["class"] == "CORNER"]
        selected = select_reviewed_candidates(result, exclude_indices=all_corner_indices)
        self.assertEqual([], selected)
        with self.assertRaises(CornerGeometryError):
            select_reviewed_candidates(result, exclude_indices=all_corner_indices,
                                       require_minimum=True)

    def test_hash_is_repeatable_and_sensitive_to_revision(self):
        self.assertEqual(canonical_hash({"a": 1, "b": 2}),
                         canonical_hash({"b": 2, "a": 1}))
        self.assertNotEqual(canonical_hash({"a": 1}), canonical_hash({"a": 2}))


if __name__ == "__main__":
    unittest.main()
