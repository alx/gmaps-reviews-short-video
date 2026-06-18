import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useMemo } from "react";
import rough from "roughjs";
import { CROSSFADE, type Palette } from "../Composition";
import { StarRating } from "./StarRating";

const CONTAINER_W = 900;
const FONT_SIZE = 54;
const LINE_HEIGHT = 82;
const CHARS_PER_LINE = 32;
const BLUR_CLEAR_FRAME = 30;
const HIGHLIGHT_END_FRAME = 68;

function wrapText(text: string): string[] {
  const words = text.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= CHARS_PER_LINE) {
      current = candidate;
    } else {
      if (current) lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function firstSentenceFallback(text: string): string[] {
  const m = text.match(/^[^.!?]+[.!?]?/);
  const sentence = (m ? m[0] : text).trim();
  return [sentence.split(" ").slice(0, 4).join(" ")];
}

function truncate(text: string): string {
  if (text.length <= 140) return text;
  return text.slice(0, 140).split(" ").slice(0, -1).join(" ").trimEnd() + "…";
}

export const ReviewHighlight: React.FC<{
  review: { text: string; rating: number; author: string };
  palette: Palette;
  highlightPhrases: string[];
}> = ({ review, palette, highlightPhrases }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(
    frame,
    [0, CROSSFADE, durationInFrames - CROSSFADE, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const blur = interpolate(frame, [0, BLUR_CLEAR_FRAME], [12, 0], {
    extrapolateRight: "clamp",
  });

  const rotateY = interpolate(frame, [0, durationInFrames], [-8, 7], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rotateX = interpolate(frame, [0, durationInFrames], [3, -3], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = interpolate(frame, [0, durationInFrames], [1.0, 1.04], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const highlightProgress = interpolate(
    frame,
    [BLUR_CLEAR_FRAME, HIGHLIGHT_END_FRAME],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const text = useMemo(() => truncate(review.text), [review.text]);
  const lines = useMemo(() => wrapText(text), [text]);

  const phrases =
    highlightPhrases.length > 0
      ? highlightPhrases
      : firstSentenceFallback(text);

  const highlightLineIndices = useMemo(() => {
    const indices = new Set<number>();
    for (const phrase of phrases) {
      const lower = phrase.toLowerCase();
      lines.forEach((line, i) => {
        if (line.toLowerCase().includes(lower)) indices.add(i);
      });
    }
    return Array.from(indices).sort((a, b) => a - b);
  }, [lines, phrases]);

  const containerH = lines.length * LINE_HEIGHT + 20;

  const roughPaths = useMemo(() => {
    // Measure actual rendered text widths via Canvas API (available in Chromium).
    const ctx = document
      .createElement("canvas")
      .getContext("2d") as CanvasRenderingContext2D;
    ctx.font = `500 ${FONT_SIZE}px system-ui, -apple-system, sans-serif`;

    const gen = rough.generator();
    const PAD_H = 10;
    const PAD_V = 8;

    return highlightLineIndices.flatMap((lineIdx, seedOffset) => {
      const textWidth = ctx.measureText(lines[lineIdx]).width;
      const rectW = textWidth + PAD_H * 2;
      const rectY = lineIdx * LINE_HEIGHT - PAD_V;
      const drawable = gen.rectangle(-PAD_H, rectY, rectW, LINE_HEIGHT + PAD_V, {
        roughness: 2.2,
        seed: seedOffset + 1,
        stroke: "rgba(255,220,0,0.0)",
        strokeWidth: 1,
        fill: "rgba(255,200,0,0.32)",
        fillStyle: "solid",
      });
      return gen.toPaths(drawable).map((p) => ({
        d: p.d,
        stroke: p.stroke ?? "none",
        fill: p.fill ?? "none",
        strokeWidth: p.strokeWidth ?? 1,
      }));
    });
  }, [highlightLineIndices, lines]);

  return (
    <AbsoluteFill style={{ opacity }}>
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to top, rgba(0,0,0,0.70) 0%, rgba(0,0,0,0.25) 55%, transparent 100%)",
          pointerEvents: "none",
        }}
      />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "80px 90px",
          perspective: "1200px",
          filter: `blur(${blur}px)`,
        }}
      >
        <div
          style={{
            transform: `scale(${scale}) rotateY(${rotateY}deg) rotateX(${rotateX}deg)`,
            transformStyle: "preserve-3d",
            width: CONTAINER_W,
            position: "relative",
          }}
        >
          {/* rough.js highlight layer — behind text */}
          <svg
            width={CONTAINER_W}
            height={containerH}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              overflow: "visible",
              zIndex: 0,
            }}
          >
            <defs>
              <clipPath id="hl-reveal">
                <rect
                  x={0}
                  y={0}
                  width={CONTAINER_W * highlightProgress}
                  height={containerH + 40}
                />
              </clipPath>
            </defs>
            <g clipPath="url(#hl-reveal)">
              {roughPaths.map((p, i) => (
                <path
                  key={i}
                  d={p.d}
                  stroke={p.stroke}
                  fill={p.fill}
                  strokeWidth={p.strokeWidth}
                />
              ))}
            </g>
          </svg>

          {/* Review text — on top of highlights */}
          <div style={{ position: "relative", zIndex: 1 }}>
            {lines.map((line, i) => (
              <div
                key={i}
                style={{
                  fontSize: FONT_SIZE,
                  lineHeight: `${LINE_HEIGHT}px`,
                  color: "rgba(255,255,255,0.96)",
                  fontFamily: "system-ui, -apple-system, sans-serif",
                  fontWeight: 500,
                  textShadow: "0 2px 14px rgba(0,0,0,0.85)",
                  whiteSpace: "pre",
                }}
              >
                {line}
              </div>
            ))}
          </div>
        </div>

        {/* Stars + author — below the 3D block */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 22,
            marginTop: 48,
          }}
        >
          <StarRating rating={review.rating} size={48} color={palette.accent} />
          <span
            style={{
              color: "rgba(255,255,255,0.72)",
              fontSize: 38,
              fontFamily: "system-ui, -apple-system, sans-serif",
              textShadow: "0 2px 8px rgba(0,0,0,0.7)",
            }}
          >
            {review.author || "Customer"}
          </span>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
