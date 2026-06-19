# gmaps-reviews-short-video

A local web app (Flask) that scrapes Google Maps place data and generates a short vertical video (1080×1920) showcasing business reviews. The video renderer is Remotion (React/Chromium), invoked via a Node.js sidecar process.

## Language

**Sidecar**:
The Node.js Express process that runs alongside Flask on localhost. Accepts render jobs via HTTP, invokes Remotion's `renderMedia()`, and serves workspace assets as static files.
_Avoid_: renderer service, Node server, backend

**Composition**:
The Remotion React component that defines the visual layout and animation of the video. Receives `inputProps` at render time and computes total frame count via `calculateMetadata`.
_Avoid_: template, video component, React video

**inputProps**:
The JSON object passed from Flask through the sidecar to the Composition. Carries all business data needed to render: business name, rating, photo URLs, review text, card enable/disable flags, map image URL, music URL.
_Avoid_: render params, video params, props

**Card**:
One of four named segments of the video: Intro, Review, Map, Outro. Each card has a boolean `enabled` flag in `inputProps`. Durations are fixed sensible defaults, not user-configurable.
_Avoid_: slide, scene, segment, section

**Render job**:
A single video generation request initiated when the user submits the Step 2 form. Flask creates a `TaskState`, POSTs to the sidecar, polls `/jobs/:id` for progress, and writes the output to `session_dir/video.mp4`.
_Avoid_: task, generation, encode job

**Serve URL**:
The URL of the pre-bundled Remotion project, served by the sidecar's Express static middleware. Built once via `@remotion/bundler` at sidecar startup.
_Avoid_: bundle URL, remotion URL

**Workspace**:
The root directory on disk where Flask stores all session data. Also mounted as a static file root by the sidecar so Chromium can fetch photos, map images, and music during rendering.
_Avoid_: data dir, storage, output dir

**Session dir**:
A per-task subdirectory within the workspace (`sessions/<task_id>/`). Contains downloaded photos, the pre-rendered map image, and the final `video.mp4`.
_Avoid_: task dir, output folder

**Map image**:
A static OpenStreetMap PNG pre-rendered by Python's `staticmap` library before the render job is dispatched. Passed to the Composition as a URL via `inputProps`. The Composition treats it as an ordinary `<Img>` source.
_Avoid_: map tile, map frame, OSM image

**Companion video**:
A standalone 15-second vertical (1080×1920) Manim-rendered video published separately from the review video. Tells a historical or contextual story about the reviewed place. Entry point: `src/companion.py`.
_Avoid_: context video, history video, explainer

**Story arc**:
The 4-beat narrative structure of a companion video: Hook (place name + founding year, 4s) → Key fact (surprising historical fact, 5s) → Stat (animated counter of a notable number, 3s) → CTA (star rating + channel handle, 3s).
_Avoid_: scenes, slides, beats (use "story arc" for the structure, "scene" for each Manim Scene class)

**Story beats**:
The structured JSON output of the Wikipedia + LLM extraction step: `hook_subtitle`, `key_fact`, `stat` (value/unit/label), `cta`. Passed as Python constants into the generated Manim script.
_Avoid_: LLM output, context data, extracted facts

**Place cache**:
The per-place directory at `web_workspace/place_cache/{place_id}/`. Contains `meta.json` (place metadata) and `images/` (thumbnails and full-res photos). Populated at fetch time (thumbnails) and generation time (full-res). Never auto-invalidated; updated via an explicit Refresh action.
_Avoid_: location cache, place data dir

**Place index**:
A JSON file at `web_workspace/place_index/{place_id}.json` that lists session UUIDs where a video was generated for that place. Used to surface past videos in Step 1. Appended at generation time; stale entries (missing `video.mp4`) are skipped lazily.
_Avoid_: session index, video index

**Image pool**:
The `images/` subdirectory inside a Place cache. The canonical source of photos for the Step 2 grid. Users can delete images or upload custom ones; these changes persist across sessions.
_Avoid_: photo cache, image folder, image library

**Accent color**:
A hex color derived per-place from the dominant mid-tone pixel of the first downloaded photo, via PIL. Used as the primary highlight color in the companion video. Falls back to `#D4A843` (warm gold) when no photo is available.
_Avoid_: theme color, brand color, palette
