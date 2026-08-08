"""Coordinate handling, distance, and the search grids that spend external quota."""
from __future__ import annotations

import math

import pytest


class TestValidCoordinate:
    @pytest.mark.parametrize("pair", [(0, 0), (-6.1938, 106.823), (90, 180), (-90, -180)])
    def test_accepts_valid_wgs84(self, omnisite, pair):
        assert omnisite.valid_coordinate(*pair)

    @pytest.mark.parametrize("pair", [
        (91, 0), (-91, 0), (0, 181), (0, -181),
        (float("nan"), 0), (float("inf"), 0), ("abc", 0), (None, None),
    ])
    def test_rejects_out_of_range_and_junk(self, omnisite, pair):
        assert not omnisite.valid_coordinate(*pair)

    def test_accepts_numeric_strings(self, omnisite):
        assert omnisite.valid_coordinate("-6.1938", "106.8230")


class TestHaversine:
    def test_identical_points_are_zero(self, omnisite):
        assert omnisite.haversine(-6.2, 106.8, -6.2, 106.8) == 0.0

    def test_known_distance(self, omnisite):
        """Jakarta to Bandung is ~116 km great-circle."""
        metres = omnisite.haversine(-6.2088, 106.8456, -6.9175, 107.6191)
        assert 115_000 < metres < 118_000

    def test_symmetric(self, omnisite):
        forward = omnisite.haversine(-6.2, 106.8, -7.8, 110.4)
        backward = omnisite.haversine(-7.8, 110.4, -6.2, 106.8)
        assert forward == pytest.approx(backward)

    def test_antipodal_points_do_not_overflow(self, omnisite):
        """The clamp on the intermediate term exists for exactly this case."""
        assert omnisite.haversine(0, 0, 0, 180) == pytest.approx(20_015_000, rel=1e-3)


class TestCandidateGrid:
    def test_cells_stay_inside_the_circle(self, omnisite):
        grid = omnisite.candidate_grid(-6.2, 106.8, 5.0, 1.0)
        for lat, lon in grid:
            assert omnisite.haversine(-6.2, 106.8, lat, lon) <= 5_200

    def test_finer_spacing_yields_more_cells(self, omnisite):
        assert len(omnisite.candidate_grid(-6.2, 106.8, 8.0, 1.0)) > \
               len(omnisite.candidate_grid(-6.2, 106.8, 8.0, 2.0))

    def test_every_reachable_ui_setting_stays_within_the_batch_cap(self, omnisite):
        """The UI must not offer a search the Earth Engine batcher would refuse."""
        for radius in (2.0, 3.0, 5.0, 8.0):
            for spacing in (0.5, 1.0, 2.0, 5.0):
                cells = len(omnisite.candidate_grid(-6.2, 106.8, radius, spacing))
                assert cells <= omnisite.MAX_GRID_CELLS, (radius, spacing, cells)


class TestTowerTiles:
    def test_every_reachable_ui_radius_stays_within_quota_budget(self, omnisite):
        """10 km was chosen as the ceiling precisely so this holds."""
        for radius in (2.0, 3.0, 5.0, 8.0):
            tiles = len(omnisite.tower_tile_centres(-6.2, 106.8, radius))
            assert tiles <= omnisite.MAX_TOWER_TILES, (radius, tiles)

    def test_eight_kilometres_is_exactly_the_budget(self, omnisite):
        """The UI ceiling is derived from this number, not chosen independently."""
        assert len(omnisite.tower_tile_centres(-6.2, 106.8, 8.0)) == omnisite.MAX_TOWER_TILES

    def test_the_old_uncapped_radius_would_have_blown_the_budget(self, omnisite):
        """Documents why the radius input is capped: 25 km meant 729 serial lookups."""
        assert len(omnisite.tower_tile_centres(-6.2, 106.8, 25.0)) == 729

    def test_tiles_widen_with_latitude(self, omnisite):
        """Longitude degrees shrink toward the poles; spacing must compensate."""
        equator = omnisite.tower_tile_centres(0.0, 106.8, 8.0)
        high = omnisite.tower_tile_centres(60.0, 106.8, 8.0)
        assert len(high) <= len(equator)


class TestDistanceText:
    def test_metres_below_a_kilometre(self, omnisite):
        assert "820" in omnisite.distance_text(820.0)

    def test_kilometres_above(self, omnisite):
        assert "1.5" in omnisite.distance_text(1500.0)

    def test_none_is_reported_as_unmapped_not_zero(self, omnisite):
        assert omnisite.distance_text(None) == omnisite.EN["not_mapped"]


class TestCoordKey:
    def test_rounds_to_six_decimals(self, omnisite):
        assert omnisite.coord_key(-6.19381234, 106.82301234) == (-6.193812, 106.823012)

    def test_near_identical_clicks_collapse_to_one_key(self, omnisite):
        assert omnisite.coord_key(-6.1938001, 106.823) == omnisite.coord_key(-6.1938002, 106.823)

    def test_grid_is_empty_for_a_degenerate_radius(self, omnisite):
        assert omnisite.candidate_grid(-6.2, 106.8, 0.0, 1.0) == [(-6.2, 106.8)] or \
               math.isclose(len(omnisite.candidate_grid(-6.2, 106.8, 0.0, 1.0)), 1)
