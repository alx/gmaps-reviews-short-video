import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CROSSFADE, type Palette } from "../Composition";

const TRUNCATE_CHARS = 140;

function truncate(text: string): string {
  if (text.length <= TRUNCATE_CHARS) return text;
  const cut = text.slice(0, TRUNCATE_CHARS).split(" ").slice(0, -1).join(" ");
  return cut.trimEnd() + "…";
}

export const ReviewCard: React.FC<{
  review: { text: string; rating: number; author: string };
  palette: Palette;
}> = ({ review, palette }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const opacity = interpolate(
    frame,
    [0, CROSSFADE, durationInFrames - CROSSFADE, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const translateY = spring({
    frame,
    fps,
    config: { damping: 20, stiffness: 90 },
    from: 80,
    to: 0,
  });

  const stars =
    "★".repeat(Math.min(5, Math.max(0, Math.round(review.rating)))) +
    "☆".repeat(5 - Math.min(5, Math.max(0, Math.round(review.rating))));

  const author = review.author || "Customer";

  return (
    <AbsoluteFill
      style={{
        opacity,
        display: "flex",
        alignItems: "flex-end",
        padding: "0 48px 180px",
      }}
    >
      {/* Subtle bottom gradient so the card reads against any photo */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 50%)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          transform: `translateY(${translateY}px)`,
          background: palette.cardBg,
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
          borderRadius: 28,
          padding: "44px 52px",
          border: "1px solid rgba(255,255,255,0.12)",
          width: "100%",
          boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
          position: "relative",
        }}
      >
        {/* Stars + author */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            marginBottom: 22,
            flexWrap: "wrap",
          }}
        >
          <span style={{ color: palette.accent, fontSize: 44, letterSpacing: 3 }}>
            {stars}
          </span>
          <span
            style={{
              color: "rgba(255,255,255,0.65)",
              fontSize: 38,
              fontFamily: "system-ui, -apple-system, sans-serif",
            }}
          >
            {author}
          </span>
        </div>
        {/* Divider */}
        <div
          style={{
            height: 1,
            background: "rgba(255,255,255,0.14)",
            marginBottom: 28,
          }}
        />
        {/* Review text */}
        <div
          style={{
            fontSize: 40,
            color: "rgba(240,240,240,0.95)",
            lineHeight: 1.55,
            fontFamily: "system-ui, -apple-system, sans-serif",
          }}
        >
          "{truncate(review.text)}"
        </div>
      </div>
    </AbsoluteFill>
  );
};
