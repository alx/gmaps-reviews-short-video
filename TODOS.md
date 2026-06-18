# TODOS

Deferred work captured during /plan-eng-review. Each item has enough context
to pick up in a future session.

---

## T-TODO-1: Extract Palette type to shared palettes.ts

**What:** Define a `Palette` type and `PALETTES` record in a dedicated
`remotion-sidecar/src/palettes.ts` file, exported for all 4 card components
to import.

**Why:** Currently, palette objects will be inlined in `Composition.tsx` after
the initial `industryVibe` implementation. If a 5th vibe is added later, the
colors, accent, and font choices live in one place rather than scattered across
4 card components.

**Pros:** Single source of truth for all visual theme decisions. Easy to add
vibes without touching component code.

**Cons:** Premature abstraction if we only ever have 4 vibes. Adds one import
per card component.

**Context:** The initial implementation inlines PALETTES in Composition.tsx
and passes a resolved palette object to each card. Extract to palettes.ts once
the initial iteration ships and palette design stabilizes (e.g., after first
user feedback).

**Depends on:** industryVibe initial implementation shipped.

---

## T-TODO-2: Track industry_vibe in Google Analytics events

**What:** When a user submits the step1 form, fire a GA event that includes
the selected industry vibe:
```javascript
gtag('event', 'generate_started', { industry_vibe: vibeValue });
```

**Why:** Knowing which industries are most common helps validate the
Restaurant/Medical/Retail split and informs future palette investment (e.g.,
if 80% of users select Restaurant, that vibe deserves the most polish).

**Pros:** Zero server-side code. Gives segment data in GA dashboard.

**Cons:** Requires reading the select value in JS before form submit. Minor
JS addition to step1_url.html.

**Context:** The step1 form currently fires `gtag('event', 'sample_url_used')`
on sample URL button clicks. The pattern for adding vibe tracking follows the
same approach.

**Depends on:** industryVibe selector shipped in step1_url.html.
