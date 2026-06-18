import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useMemo } from "react";
import { loadFont } from "@remotion/google-fonts/Montserrat";
import { CROSSFADE, type Palette } from "../Composition";
import { StarRating } from "./StarRating";

const { fontFamily: MONTSERRAT } = loadFont();

const CONTAINER_W = 900;
const FONT_SIZE = 54;
const LINE_HEIGHT = 82;
const CHARS_PER_LINE = 32;
const BLUR_CLEAR_FRAME = 30;

const GOLD = "#C9952A";
const AUTHOR_COLOR = "#2d1f05";

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

function truncate(text: string): string {
  if (text.length <= 140) return text;
  return text.slice(0, 140).split(" ").slice(0, -1).join(" ").trimEnd() + "…";
}


export const ReviewHighlight: React.FC<{
  review: { text: string; rating: number; author: string };
  palette: Palette;
  highlightPhrases: string[];
}> = ({ review }) => {
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

  const text = useMemo(() => truncate(review.text), [review.text]);
  const lines = useMemo(() => wrapText(text), [text]);

  return (
    <AbsoluteFill style={{ opacity }}>
      {/* Top vignette only — lets photo show through in center and bottom */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.30) 0%, transparent 35%)",
          pointerEvents: "none",
        }}
      />

      {/* Content anchored to bottom */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "flex-end",
          paddingBottom: 72,
          filter: `blur(${blur}px)`,
        }}
      >
        {/* 3D tilt wrapper */}
        <div
          style={{
            width: CONTAINER_W,
            transform: `scale(${scale}) rotateY(${rotateY}deg) rotateX(${rotateX}deg)`,
            transformStyle: "preserve-3d",
            perspective: "1200px",
          }}
        >
          {/* White panel */}
          <div
            style={{
              background: "rgba(255, 255, 255, 0.72)",
              borderRadius: 24,
              padding: "40px 60px 36px",
              boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 36,
            }}
          >
            {/* Testimonial text */}
            <div style={{ textAlign: "center" }}>
              {lines.map((line, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: FONT_SIZE,
                    lineHeight: `${LINE_HEIGHT}px`,
                    color: "#1c1a14",
                    fontFamily: MONTSERRAT,
                    fontWeight: 500,
                    whiteSpace: "pre",
                  }}
                >
                  {line}
                </div>
              ))}
            </div>

            {/* Stars + author — single row, right-aligned */}
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "flex-end",
                gap: 20,
                width: "100%",
              }}
            >
              <StarRating rating={review.rating} size={40} color={GOLD} />
              <span
                style={{
                  color: AUTHOR_COLOR,
                  fontSize: 36,
                  fontFamily: MONTSERRAT,
                  fontWeight: 700,
                  letterSpacing: "0.02em",
                }}
              >
                {review.author || "Customer"}
              </span>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
