import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadDancingScript } from "@remotion/google-fonts/DancingScript";
import { loadFont as loadPacifico } from "@remotion/google-fonts/Pacifico";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadGreatVibes } from "@remotion/google-fonts/GreatVibes";
import { loadFont as loadPlayfairDisplay } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { CROSSFADE, type Palette } from "../Composition";
import { StarRating } from "./StarRating";

// Load all fonts at module level so Remotion can prefetch them.
const FONTS: Record<string, { fontFamily: string }> = {
  DancingScript: loadDancingScript(),
  Pacifico: loadPacifico(),
  Caveat: loadCaveat(),
  GreatVibes: loadGreatVibes(),
  PlayfairDisplay: loadPlayfairDisplay(),
  Montserrat: loadMontserrat(),
};

const FALLBACK_FONT = "Montserrat, system-ui, -apple-system, sans-serif";

function resolveFontFamily(titleFont?: string): string {
  const key = titleFont ?? "PlayfairDisplay";
  return FONTS[key]?.fontFamily ?? FALLBACK_FONT;
}

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
  tagline?: string;
  titleFont?: string;
}> = ({ businessName, rating, city, country, countryCode, tagline, titleFont }) => {
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
    from: 30,
    to: 0,
  });

  const locationParts = [];
  if (city) locationParts.push(city);
  if (country) {
    const flag = countryCode ? countryFlag(countryCode) + " " : "";
    locationParts.push(flag + country);
  }

  const titleFontFamily = resolveFontFamily(titleFont);

  return (
    <AbsoluteFill style={{ opacity }}>
      {/* Gradient darkens top for text legibility */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.45) 55%, rgba(0,0,0,0.10) 100%)",
        }}
      />
      {/* Text block anchored to top */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "flex-start",
          paddingTop: "18%",
          padding: "0 60px",
          paddingLeft: 60,
          paddingRight: 60,
          transform: `translateY(${translateY}px)`,
        }}
      >
        <div
          style={{
            paddingTop: "18%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            width: "100%",
          }}
        >
          {/* Business name in selected font */}
          <div
            style={{
              fontSize: 88,
              fontWeight: 700,
              color: "white",
              textAlign: "center",
              lineHeight: 1.15,
              marginBottom: tagline ? 20 : 36,
              fontFamily: titleFontFamily,
              textShadow: "0 4px 28px rgba(0,0,0,0.75)",
            }}
          >
            {businessName}
          </div>

          {/* Optional tagline */}
          {tagline && (
            <div
              style={{
                fontSize: 38,
                color: "rgba(255,255,255,0.82)",
                textAlign: "center",
                fontFamily: "Montserrat, system-ui, sans-serif",
                fontWeight: 400,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                marginBottom: 36,
                textShadow: "0 2px 12px rgba(0,0,0,0.6)",
              }}
            >
              {tagline}
            </div>
          )}

          {/* Stars */}
          <div style={{ marginBottom: 16 }}>
            <StarRating rating={rating} size={56} />
          </div>

          {/* Rating number */}
          <div
            style={{
              fontSize: 44,
              color: "rgba(255,255,255,0.92)",
              marginBottom: locationParts.length ? 28 : 0,
              fontFamily: "Montserrat, system-ui, sans-serif",
              fontWeight: 600,
              padding: "4px 20px",
            }}
          >
            {rating.toFixed(1)} / 5
          </div>

          {/* Location */}
          {locationParts.length > 0 && (
            <div
              style={{
                fontSize: 40,
                color: "rgba(255,255,255,0.75)",
                textAlign: "center",
                fontFamily: "Montserrat, system-ui, sans-serif",
              }}
            >
              {locationParts.join("  ·  ")}
            </div>
          )}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
