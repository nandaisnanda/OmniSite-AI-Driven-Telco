"""Site feasibility scoring.

The regression these tests exist for: an unmeasured signal used to be scored as a passed
signal, so a point where every engine had failed came back 82/100 "PROCEED TO SURVEY".
"""
from __future__ import annotations

import pytest

NOTHING_MEASURED = {"land_cover": None, "night_light": None,
                    "water_occurrence": None, "slope": None}
URBAN = {"land_cover": 50, "night_light": 30.0, "water_occurrence": 0.0, "slope": 2.0}
URBAN_CONTEXT = {"available": True, "power_count": 6, "power_distance": 180.0,
                 "poi_count": 11, "water_distance": 900.0}
GOOD_ROAD = {"available": True, "distance": 40.0}
CALM = {"tower_class": "standard"}


def score(app, gee=None, context=None, wind=None, road=None, rf=None):
    return app.derive_site_intelligence(gee if gee is not None else URBAN,
                                        context if context is not None else URBAN_CONTEXT,
                                        wind if wind is not None else CALM,
                                        road if road is not None else GOOD_ROAD,
                                        rf if rf is not None else {})


class TestMissingData:
    def test_no_engine_returned_anything_is_not_scored(self, omnisite):
        result = score(omnisite, gee=NOTHING_MEASURED, context={"available": False},
                       wind={}, road={}, rf={})
        assert result["recommendation"] == "insufficient"
        assert result["score"] is None
        assert result["known_signals"] == 0

    def test_elevation_only_fallback_is_still_not_scored(self, omnisite):
        """The public-elevation fallback measures nothing else; that is not a pass."""
        result = score(omnisite, gee=NOTHING_MEASURED, context={"available": False},
                       wind={}, road=GOOD_ROAD, rf={})
        assert result["recommendation"] == "insufficient"
        assert result["score"] is None

    def test_unknown_signals_never_carry_a_penalty(self, omnisite):
        """Unknown must not be scored as bad either — only as unknown."""
        result = score(omnisite, gee={**URBAN, "land_cover": None})
        assert result["permit"] == "unknown"
        assert result["permit_note"] == "permit_unscreened"

    def test_partial_screening_cannot_reach_approve(self, omnisite):
        result = score(omnisite, wind={})
        assert result["known_signals"] < result["total_signals"]
        assert result["recommendation"] == "review"

    def test_complete_screening_can_reach_approve(self, omnisite):
        result = score(omnisite)
        assert result["known_signals"] == result["total_signals"]
        assert result["recommendation"] == "approve"


class TestAccessAndTerrain:
    def test_no_road_access_is_disqualifying(self, omnisite):
        result = score(omnisite, road={"available": True, "no_road": True})
        assert result["access"] == "none"
        assert result["recommendation"] == "avoid"

    def test_distant_road_caps_at_review(self, omnisite):
        result = score(omnisite, road={"available": True, "distance": 420.0})
        assert result["access"] == "far"
        assert result["recommendation"] == "review"

    @pytest.mark.parametrize(("slope", "expected"), [
        (2.0, "flat"), (9.9, "flat"), (10.0, "moderate"), (24.9, "moderate"), (25.0, "steep"),
    ])
    def test_terrain_bands(self, omnisite, slope, expected):
        assert score(omnisite, gee={**URBAN, "slope": slope})["terrain"] == expected

    def test_steep_ground_caps_at_review(self, omnisite):
        assert score(omnisite, gee={**URBAN, "slope": 32.0})["recommendation"] == "review"

    def test_road_and_slope_actually_move_the_score(self, omnisite):
        """These were measured and displayed but excluded from the score entirely."""
        flat = score(omnisite)["score"]
        steep = score(omnisite, gee={**URBAN, "slope": 32.0})["score"]
        far = score(omnisite, road={"available": True, "distance": 420.0})["score"]
        assert steep < flat and far < flat


class TestConstraints:
    def test_permanent_water_is_restricted(self, omnisite):
        result = score(omnisite, gee={**URBAN, "land_cover": 80})
        assert result["permit"] == "restricted"
        assert result["recommendation"] == "avoid"

    def test_high_surface_water_occurrence_is_avoid(self, omnisite):
        result = score(omnisite, gee={**URBAN, "water_occurrence": 70.0})
        assert result["flood"] == "high"
        assert result["recommendation"] == "avoid"

    def test_collocation_credits_the_score(self, omnisite):
        alone = score(omnisite, rf={"available": True, "status": "greenfield"})["score"]
        shared = score(omnisite, rf={"available": True, "status": "collocation"})["score"]
        assert shared > alone

    def test_score_stays_within_bounds(self, omnisite):
        worst = score(omnisite,
                      gee={"land_cover": 80, "night_light": 0.0,
                           "water_occurrence": 95.0, "slope": 40.0},
                      context={"available": True, "power_count": 0, "power_distance": None,
                               "poi_count": 0, "water_distance": 10.0},
                      wind={"tower_class": "heavy"},
                      road={"available": True, "no_road": True})
        assert worst["score"] == 0
        best = score(omnisite, rf={"available": True, "status": "collocation"})
        assert 0 <= best["score"] <= 100
