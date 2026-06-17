import express from "express";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import { v4 as uuidv4 } from "uuid";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const PORT = parseInt(process.env.SIDECAR_PORT ?? "3001");
const ROOT_DIR =
  process.env.SIDECAR_ROOT_DIR ?? path.join(__dirname, "..");

const app = express();
app.use(express.json({ limit: "10mb" }));

// Serve the project root so Chromium can fetch photos, map images, and music.
app.use("/assets", express.static(ROOT_DIR));

const jobs = new Map();
let bundlePath = null;

async function initBundle() {
  console.log("Bundling Remotion composition…");
  bundlePath = await bundle({
    entryPoint: require.resolve("./src/index.tsx"),
    webpackOverride: (config) => config,
  });
  console.log("Bundle ready:", bundlePath);
}

app.get("/health", (_req, res) => {
  res.json({ status: bundlePath ? "ready" : "bundling" });
});

app.post("/render", async (req, res) => {
  if (!bundlePath) {
    return res.status(503).json({ error: "Bundle not ready yet" });
  }

  const { outputPath, inputProps } = req.body;
  if (!outputPath || !inputProps) {
    return res.status(400).json({ error: "outputPath and inputProps required" });
  }

  const jobId = uuidv4();
  jobs.set(jobId, { progress: 0, done: false, error: null });
  res.json({ jobId });

  (async () => {
    try {
      const composition = await selectComposition({
        serveUrl: bundlePath,
        id: "ReviewVideo",
        inputProps,
      });

      await renderMedia({
        composition,
        serveUrl: bundlePath,
        codec: "h264",
        outputLocation: outputPath,
        inputProps,
        chromiumOptions: { enableMultiProcessOnLinux: true },
        onProgress: ({ progress }) => {
          const job = jobs.get(jobId);
          if (job) job.progress = progress;
        },
      });

      jobs.set(jobId, { progress: 1, done: true, error: null });
    } catch (err) {
      console.error("Render error:", err);
      jobs.set(jobId, { progress: 0, done: true, error: err.message });
    }
  })();
});

app.get("/jobs/:id", (req, res) => {
  const job = jobs.get(req.params.id);
  if (!job) return res.status(404).json({ error: "Job not found" });
  res.json(job);
});

initBundle()
  .then(() => {
    app.listen(PORT, "127.0.0.1", () => {
      console.log(`Remotion sidecar listening on http://127.0.0.1:${PORT}`);
    });
  })
  .catch((err) => {
    console.error("Failed to initialize bundle:", err);
    process.exit(1);
  });
