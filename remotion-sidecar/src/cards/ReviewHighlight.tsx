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
const LIGHT_GOLD = "#D4AF6A";

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

const BRACKET_SIZE = 40;
const BRACKET_STROKE = 2.5;

const CornerBracket: React.FC<{ rotation: number }> = ({ rotation }) => (
  <svg
    width={BRACKET_SIZE}
    height={BRACKET_SIZE}
    viewBox="0 0 40 40"
    style={{
      position: "absolute",
      transform: `rotate(${rotation}deg)`,
      ...(rotation === 0 && { top: 0, left: 0 }),
      ...(rotation === 90 && { top: 0, right: 0 }),
      ...(rotation === 180 && { bottom: 0, right: 0 }),
      ...(rotation === 270 && { bottom: 0, left: 0 }),
    }}
  >
    <path
      d="M 36 4 L 4 4 L 4 36"
      fill="none"
      stroke={GOLD}
      strokeWidth={BRACKET_STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

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
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 48,
          }}
        >
          {/* Testimonial text block with corner brackets */}
          <div
            style={{
              position: "relative",
              padding: "48px 64px",
              textAlign: "center",
            }}
          >
            <CornerBracket rotation={0} />
            <CornerBracket rotation={90} />
            <CornerBracket rotation={180} />
            <CornerBracket rotation={270} />

            {lines.map((line, i) => (
              <div
                key={i}
                style={{
                  fontSize: FONT_SIZE,
                  lineHeight: `${LINE_HEIGHT}px`,
                  color: "rgba(255,252,240,0.95)",
                  fontFamily: MONTSERRAT,
                  fontWeight: 500,
                  textShadow:
                    "0 0 24px rgba(0,0,0,0.95), 0 2px 10px rgba(0,0,0,0.85)",
                  whiteSpace: "pre",
                }}
              >
                {line}
              </div>
            ))}
          </div>

          {/* Stars centered below text */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 20,
            }}
          >
            <StarRating rating={review.rating} size={48} color={GOLD} />
            <span
              style={{
                color: LIGHT_GOLD,
                fontSize: 36,
                fontFamily: MONTSERRAT,
                fontWeight: 300,
                textShadow: "0 2px 10px rgba(0,0,0,0.8)",
                letterSpacing: "0.04em",
              }}
            >
              {review.author || "Customer"}
            </span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
