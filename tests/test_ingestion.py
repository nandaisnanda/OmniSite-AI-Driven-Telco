"""Upload header detection and the i18n contract the UI depends on."""
from __future__ import annotations

import string

import pytest


class TestFindColumn:
    @pytest.mark.parametrize("header", [
        "lat", "LAT", " Latitude ", "Latitude (WGS84)", "lat_deg", "LAT-DEG",
        "Lintang", "latitude_dd", "Y",
    ])
    def test_recognises_latitude_variants(self, omnisite, header):
        assert omnisite.find_column([header, "other"], omnisite.LAT_NAMES) == header

    @pytest.mark.parametrize("header", [
        "lon", "LNG", "Long", " Longitude ", "Longitude (WGS84)", "lon_deg",
        "Bujur", "X",
    ])
    def test_recognises_longitude_variants(self, omnisite, header):
        assert omnisite.find_column([header, "other"], omnisite.LON_NAMES) == header

    def test_exact_header_beats_a_fuzzy_one(self, omnisite):
        columns = ["site latitude reference", "lat"]
        assert omnisite.find_column(columns, omnisite.LAT_NAMES) == "lat"

    def test_taken_column_is_not_claimed_twice(self, omnisite):
        columns = ["coordinate", "lat", "lon"]
        lat = omnisite.find_column(columns, omnisite.LAT_NAMES)
        lon = omnisite.find_column(columns, omnisite.LON_NAMES, taken=lat)
        assert (lat, lon) == ("lat", "lon")

    def test_unrelated_headers_return_none(self, omnisite):
        assert omnisite.find_column(["site", "region", "owner"], omnisite.LAT_NAMES) is None

    def test_real_world_pair(self, omnisite):
        columns = ["Site ID", "Latitude (WGS84)", "Longitude (WGS84)", "Notes"]
        lat = omnisite.find_column(columns, omnisite.LAT_NAMES)
        lon = omnisite.find_column(columns, omnisite.LON_NAMES, taken=lat)
        assert (lat, lon) == ("Latitude (WGS84)", "Longitude (WGS84)")


class TestHeaderTokens:
    def test_splits_on_punctuation_and_case(self, omnisite):
        assert omnisite.header_tokens("Lat_Deg (WGS84)") == ["lat", "deg", "wgs84"]

    def test_empty_header_yields_no_tokens(self, omnisite):
        assert omnisite.header_tokens("   ") == []


class TestTranslations:
    """The UI resolves several keys dynamically, so a gap only surfaces at runtime."""

    def test_every_language_has_the_same_keys(self, omnisite):
        for code, table in omnisite.TEXT.items():
            assert set(table) == set(omnisite.EN), f"{code} key set diverges"

    def test_placeholders_match_across_languages(self, omnisite):
        def fields(template):
            return {name for _, name, _, _ in string.Formatter().parse(template) if name}

        for code, table in omnisite.TEXT.items():
            for key, template in table.items():
                assert fields(template) == fields(omnisite.EN[key]), f"{code}:{key}"

    @pytest.mark.parametrize("prefix,values", [
        ("permit_", ("low", "medium", "high", "restricted", "unknown")),
        ("risk_", ("low", "medium", "high", "unknown")),
        ("market_", ("low", "medium", "high", "unknown")),
        ("access_", ("near", "far", "none", "unknown")),
        ("terrain_", ("flat", "moderate", "steep", "unknown")),
        ("tower_", ("standard", "reinforced", "heavy")),
        ("verdict_", ("approve", "review", "avoid", "insufficient")),
    ])
    def test_dynamically_built_keys_exist_in_every_language(self, omnisite, prefix, values):
        for code, table in omnisite.TEXT.items():
            for value in values:
                assert f"{prefix}{value}" in table, f"{code} missing {prefix}{value}"

    def test_recommendation_labels_exist(self, omnisite):
        for code, table in omnisite.TEXT.items():
            for verdict in ("approve", "review", "avoid", "insufficient"):
                assert verdict in table, f"{code} missing {verdict}"

    def test_no_template_is_empty(self, omnisite):
        for code, table in omnisite.TEXT.items():
            for key, template in table.items():
                assert template.strip(), f"{code}:{key} is blank"


class TestSettings:
    def test_secure_int_falls_back_on_junk(self, omnisite, monkeypatch):
        monkeypatch.setenv("OMNISITE_TEST_INT", "not-a-number")
        assert omnisite.secure_int("OMNISITE_TEST_INT", 7) == 7

    def test_secure_int_reads_the_environment(self, omnisite, monkeypatch):
        monkeypatch.setenv("OMNISITE_TEST_INT", "42")
        assert omnisite.secure_int("OMNISITE_TEST_INT", 7) == 42

    def test_secure_int_respects_its_floor(self, omnisite, monkeypatch):
        monkeypatch.setenv("OMNISITE_TEST_INT", "0")
        assert omnisite.secure_int("OMNISITE_TEST_INT", 7, minimum=3) == 3

    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("0", False), ("", False), ("maybe", False),
    ])
    def test_secure_flag_parsing(self, omnisite, monkeypatch, raw, expected):
        monkeypatch.setenv("OMNISITE_TEST_FLAG", raw)
        # An empty environment variable is ignored by secure_setting, which then falls
        # through to the "false" default — the same answer either way.
        assert omnisite.secure_flag("OMNISITE_TEST_FLAG") is expected


class TestCoverNames:
    def test_known_class_resolves(self, omnisite):
        assert omnisite.cover_name(50) == omnisite.EN["built"]

    def test_unknown_class_reports_the_code(self, omnisite):
        assert "77" in omnisite.cover_name(77)

    def test_missing_class_is_unavailable(self, omnisite):
        assert omnisite.cover_name(None) == omnisite.EN["unavailable"]
