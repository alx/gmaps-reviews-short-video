# Node.js sidecar over subprocess for Remotion rendering

Flask cannot call Remotion's `renderMedia()` directly because it's a Node.js API. We chose a long-running Express sidecar over a per-render subprocess because the sidecar bundles the Remotion project once at startup (bundling takes ~15s) and keeps the bundle in memory across renders. A subprocess would re-bundle on every render job, making each video take 15s longer. The sidecar also enables real-time progress streaming via `onProgress` callbacks that the subprocess approach cannot provide cleanly.

**Considered options rejected:**
- *Per-render subprocess* — re-bundles every time, no clean progress reporting
- *Remotion Lambda (AWS)* — rejected; the project must run fully locally without cloud dependencies
