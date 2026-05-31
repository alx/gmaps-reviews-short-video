import re
import urllib.parse
from pathlib import Path

import httpx

BASE_URL = "https://places.googleapis.com/v1"


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        headers={"X-Goog-Api-Key": api_key},
        follow_redirects=True,
        timeout=30,
    )


def extract_place_id_from_url(url: str) -> str | None:
    decoded = urllib.parse.unquote(url)
    # Real Places API v1 IDs start with "ChIJ" — reject CID/hex formats
    match = re.search(r"!1s(ChIJ[A-Za-z0-9_-]+)", decoded)
    if match:
        return match.group(1)
    return None


def _extract_place_name_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.split("/")
    try:
        idx = parts.index("place")
        raw = parts[idx + 1]
        return urllib.parse.unquote_plus(raw).replace("+", " ")
    except (ValueError, IndexError):
        return None


def search_place_by_name(name: str, client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE_URL}/places:searchText",
        json={"textQuery": name},
        headers={"X-Goog-FieldMask": "places.id"},
    )
    if not resp.is_success:
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {resp.reason_phrase}: {resp.text}",
            request=resp.request,
            response=resp,
        )
    data = resp.json()
    places = data.get("places", [])
    if not places:
        raise ValueError(f"No places found for: {name!r}")
    return places[0]["id"]


def get_place_details(place_id: str, client: httpx.Client) -> dict:
    resp = client.get(
        f"{BASE_URL}/places/{place_id}",
        headers={
            "X-Goog-FieldMask": "id,displayName,rating,userRatingCount,reviews,photos,websiteUri"
        },
    )
    resp.raise_for_status()
    return resp.json()


def download_photos(
    photos: list[dict],
    client: httpx.Client,
    tmpdir: str,
    max_photos: int = 10,
) -> list[str]:
    paths = []
    for i, photo in enumerate(photos[:max_photos]):
        name = photo["name"].removesuffix("/media")
        resp = client.get(
            f"{BASE_URL}/{name}/media",
            params={"maxWidthPx": 1080, "maxHeightPx": 1920},
        )
        resp.raise_for_status()
        out = Path(tmpdir) / f"photo_{i}.jpg"
        out.write_bytes(resp.content)
        paths.append(str(out))
    return paths


def select_best_reviews(reviews: list[dict], count: int = 1) -> list[dict]:
    seen_texts: set[str] = set()
    candidates = []
    for r in reviews:
        text = r.get("text", {}).get("text", "")
        rating = r.get("rating", 0)
        if rating >= 4 and len(text) >= 60 and text not in seen_texts:
            seen_texts.add(text)
            candidates.append(
                {
                    "text": text,
                    "rating": rating,
                    "author": r.get("authorAttribution", {}).get("displayName", ""),
                }
            )
    candidates.sort(key=lambda r: (r["rating"], len(r["text"])), reverse=True)
    return candidates[:count]


def resolve_url(url: str, api_key: str, photo_dir: str) -> dict:
    with _client(api_key) as client:
        # Follow short URL redirects
        if "goo.gl" in url or "maps.app" in url:
            resp = client.head(url)
            url = str(resp.url)

        place_id = extract_place_id_from_url(url)
        if not place_id:
            name = _extract_place_name_from_url(url)
            if not name:
                raise ValueError("Could not extract place name or ID from URL")
            print(f"  Searching for: {name!r}")
            place_id = search_place_by_name(name, client)

        print(f"  Place ID: {place_id}")
        details = get_place_details(place_id, client)

        business_name = details.get("displayName", {}).get("text", "Unknown")
        rating = details.get("rating", 0.0)
        review_count = details.get("userRatingCount", 0)
        website_url = details.get("websiteUri", "")

        raw_photos = details.get("photos", [])
        photo_paths = download_photos(raw_photos, client, photo_dir)

        raw_reviews = details.get("reviews", [])
        reviews = select_best_reviews(raw_reviews, count=5)

        return {
            "business_name": business_name,
            "rating": rating,
            "review_count": review_count,
            "reviews": reviews,
            "photo_paths": photo_paths,
            "website_url": website_url,
        }
