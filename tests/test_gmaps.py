from src.gmaps import extract_place_id_from_url, select_best_reviews


def test_extract_place_id_from_valid_url():
    url = (
        "https://www.google.com/maps/place/Eiffel+Tower/@48.858,2.294,17z"
        "/data=!3m1!4b1!4m6!3m5!1sChIJLU7jZClu5kcR4PcOOO6p3I0"
    )
    result = extract_place_id_from_url(url)
    assert result is not None
    assert result.startswith("ChIJ")


def test_extract_place_id_returns_none_for_bare_url():
    result = extract_place_id_from_url("https://www.google.com/maps/place/SomeCafe")
    assert result is None


def test_select_best_reviews_filters_low_ratings():
    reviews = [
        {"text": {"text": "A" * 100}, "rating": 5, "authorAttribution": {"displayName": "Alice"}},
        {"text": {"text": "B" * 100}, "rating": 2, "authorAttribution": {"displayName": "Bob"}},
        {"text": {"text": "C" * 30},  "rating": 5, "authorAttribution": {"displayName": "Carol"}},
    ]
    result = select_best_reviews(reviews, count=3)
    # Alice: rating 5, len 100 — passes. Bob: rating 2 — fails. Carol: len 30 < 60 — fails.
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


def test_select_best_reviews_limits_count():
    reviews = [
        {"text": {"text": "X" * 80}, "rating": 5, "authorAttribution": {"displayName": f"U{i}"}}
        for i in range(10)
    ]
    assert len(select_best_reviews(reviews, count=2)) == 2
