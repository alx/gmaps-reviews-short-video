import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CROSSFADE, type Palette } from "../Composition";

const countryFlag = (code: string) =>
  [...code.toUpperCase()]
    .filter((c) => /[A-Z]/.test(c))
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join("");

export const IntroCard: React.FC<{
  businessName: string;
  rating: number;
  city?: string;
  country?: string;
  countryCode?: string;
  palette: Palette;
}> = ({ businessName, rating, city, country, countryCode, palette }) => {
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
    config: { damping: 18, stiffness: 80 },
    from: 50,
    to: 0,
  });

  const stars =
    "★".repeat(Math.round(rating)) + "☆".repeat(5 - Math.round(rating));

  const locationParts = [];
  if (city) locationParts.push(city);
  if (country) {
    const flag = countryCode ? countryFlag(countryCode) + " " : "";
    locationParts.push(flag + country);
  }

  return (
    <AbsoluteFill style={{ opacity }}>
      {/* Gradient overlay — heavier at bottom */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.15) 0%, rgba(0,0,0,0.65) 60%, rgba(0,0,0,0.85) 100%)",
        }}
      />
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "80px 60px",
          transform: `translateY(${translateY}px)`,
        }}
      >
        <div
          style={{
            fontSize: 88,
            fontWeight: 800,
            color: "white",
            textAlign: "center",
            lineHeight: 1.1,
            marginBottom: 28,
            fontFamily: "system-ui, -apple-system, sans-serif",
            textShadow: "0 4px 24px rgba(0,0,0,0.7)",
          }}
        >
          {businessName}
        </div>
        <div
          style={{
            fontSize: 56,
            color: palette.accent,
            letterSpacing: 6,
            marginBottom: 8,
            textShadow: "0 2px 8px rgba(0,0,0,0.6)",
          }}
        >
          {stars}
        </div>
        <div
          style={{
            fontSize: 44,
            color: "rgba(255,255,255,0.9)",
            marginBottom: locationParts.length ? 28 : 0,
            fontFamily: "system-ui, -apple-system, sans-serif",
          }}
        >
          {rating.toFixed(1)} / 5
        </div>
        {locationParts.length > 0 && (
          <div
            style={{
              fontSize: 40,
              color: "rgba(255,255,255,0.75)",
              textAlign: "center",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }}
          >
            {locationParts.join("  ·  ")}
          </div>
        )}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
