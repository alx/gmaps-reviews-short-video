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
            "X-Goog-FieldMask": "id,displayName,rating,userRatingCount,reviews,photos,websiteUri,location,formattedAddress"
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


def fetch_place_metadata(url: str, api_key: str) -> dict:
    """Phase 1: Resolve URL → place details without downloading photos.

    Returns dict with keys: place_id, business_name, rating, review_count,
    reviews_raw (all reviews from API), reviews (best filtered), raw_photos
    (photo dicts from API, not downloaded), website_url, maps_url.
    """
    with _client(api_key) as client:
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
        reviews_raw = details.get("reviews", [])
        reviews = select_best_reviews(reviews_raw, count=5)
        loc = details.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        address = details.get("formattedAddress", "")

        return {
            "place_id": place_id,
            "business_name": business_name,
            "rating": rating,
            "review_count": review_count,
            "reviews_raw": reviews_raw,
            "reviews": reviews,
            "raw_photos": raw_photos,
            "website_url": website_url,
            "maps_url": url,
            "lat": lat,
            "lng": lng,
            "address": address,
        }


def download_selected_photos(
    raw_photos: list[dict],
    api_key: str,
    photo_dir: str,
    indices: list[int] | None = None,
    max_photos: int = 10,
    width: int = 1080,
    height: int = 1920,
) -> list[str]:
    """Phase 2: Download photos at given indices (or all up to max_photos).

    Returns list of local file paths in the requested order.
    """
    if indices is None:
        selected = list(enumerate(raw_photos[:max_photos]))
    else:
        selected = [(i, raw_photos[i]) for i in indices if i < len(raw_photos)]

    with _client(api_key) as client:
        paths = []
        for slot, (_orig_idx, photo) in enumerate(selected):
            name = photo["name"].removesuffix("/media")
            resp = client.get(
                f"{BASE_URL}/{name}/media",
                params={"maxWidthPx": width, "maxHeightPx": height},
            )
            resp.raise_for_status()
            out = Path(photo_dir) / f"photo_{slot}.jpg"
            out.write_bytes(resp.content)
            paths.append(str(out))
    return paths


def resolve_url(url: str, api_key: str, photo_dir: str) -> dict:
    meta = fetch_place_metadata(url, api_key)
    photo_paths = download_selected_photos(meta["raw_photos"], api_key, photo_dir)
    return {
        "business_name": meta["business_name"],
        "rating": meta["rating"],
        "review_count": meta["review_count"],
        "reviews": meta["reviews"],
        "photo_paths": photo_paths,
        "website_url": meta["website_url"],
        "lat": meta["lat"],
        "lng": meta["lng"],
        "address": meta["address"],
    }
