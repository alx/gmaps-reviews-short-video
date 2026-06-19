# ADR 0003: Place cache directory structure and image management

## Status
Accepted

## Context

The app fetches Google Maps place data (metadata + photos) on every Step 1 submission, even for places the user has visited before. There is an existing flat-file metadata cache (`place_cache/{place_id}.json`) but photos land in ephemeral session dirs and are lost between sessions.

Three needs drove this decision:
1. Avoid redundant API calls for known places.
2. Give users a persistent, curated image pool per place that populates the Step 2 photo grid.
3. Surface past videos for a place at Step 1 without re-fetching.

## Decision

### Cache directory layout

Migrate from a flat `place_cache/{place_id}.json` to a directory per place:

```
web_workspace/
  place_cache/
    {place_id}/
      meta.json          ← place metadata (was {place_id}.json)
      images/
        thumb_{n}.jpg    ← 400×711 thumbnails (all fetched photos)
        full_{n}.jpg     ← 1080×1920 full-res (only generated photos)
  place_index/
    {place_id}.json      ← ordered list of session UUIDs for that place
  sessions/
    {uuid}/
      ...                ← unchanged
```

### Image population

- **At fetch time**: all available thumbnails are written to `place_cache/{place_id}/images/`. The Step 2 grid reads from this directory on repeat visits — no API call needed.
- **At generation time**: full-res copies of the selected photos are written to `place_cache/{place_id}/images/`. Thumbnails already present are not re-downloaded.

### Video lookup

- Each `sessions/{uuid}/metadata.json` gains a `place_id` field written at generation time.
- A `place_index/{place_id}.json` file maintains an ordered list of session UUIDs for that place, appended at generation time.
- Step 1, on resolving a known place_id, reads the index, filters to sessions that still have `video.mp4`, and renders a past-videos strip. Missing sessions are skipped (lazy cleanup, no hard delete).

### Refresh policy

The cache is **never automatically invalidated**. A "Refresh" button in Step 1 triggers a new API call, updates `meta.json`, and merges new thumbnails into `images/` without removing manually managed files.

### Image management UI

Step 2 photo grid gains:
- A **delete button** (×) per thumbnail — immediately removes the file from `place_cache/{place_id}/images/` via HTMX.
- An **upload drop zone** alongside the grid — adds custom images to `place_cache/{place_id}/images/`.

## Alternatives considered

- **Flat JSON + session scan for video lookup**: rejected — O(n) scan across all sessions becomes slow.
- **Separate `image_cache/` top-level dir**: rejected — splits place data across two locations; a single place dir is easier to inspect and delete.
- **Automatic TTL-based re-fetch**: rejected — surprise API quota usage; explicit Refresh matches the curated-asset mental model.
- **Video caching**: rejected — video output varies by review/music/photo selection; finding past videos via the place index is sufficient.
