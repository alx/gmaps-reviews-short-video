import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.web.tasks import VALID_VIBES, _build_input_props


def test_whitelist_rejects_unknown_vibe():
    assert "hacker" not in VALID_VIBES
    assert "restaurant" in VALID_VIBES
    assert "other" in VALID_VIBES


def _minimal_place():
    return {
        "business_name": "Test Cafe",
        "rating": 4.5,
        "city": "Paris",
        "country": "France",
        "country_code": "FR",
        "website_url": "",
        "review_count": 10,
        "lat": 48.8566,
        "lng": 2.3522,
    }


def test_build_input_props_includes_industry_vibe():
    props = _build_input_props(
        place_data=_minimal_place(),
        photo_paths=[],
        selected_review={},
        music_path=None,
        maps_url="https://maps.google.com",
        card_config=None,
        map_image_url="",
        industry_vibe="restaurant",
    )
    assert props["industryVibe"] == "restaurant"


def test_build_input_props_sanitizes_invalid_vibe():
    props = _build_input_props(
        place_data=_minimal_place(),
        photo_paths=[],
        selected_review={},
        music_path=None,
        maps_url="https://maps.google.com",
        card_config=None,
        map_image_url="",
        industry_vibe="hacker",
    )
    assert props["industryVibe"] == "other"
