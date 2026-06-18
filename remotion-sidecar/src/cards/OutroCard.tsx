import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useMemo } from "react";
import QRCode from "qrcode";
import { loadFont as loadDancingScript } from "@remotion/google-fonts/DancingScript";
import { loadFont as loadPacifico } from "@remotion/google-fonts/Pacifico";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadGreatVibes } from "@remotion/google-fonts/GreatVibes";
import { loadFont as loadPlayfairDisplay } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { CROSSFADE } from "../Composition";

const FONTS: Record<string, { fontFamily: string }> = {
  DancingScript: loadDancingScript(),
  Pacifico: loadPacifico(),
  Caveat: loadCaveat(),
  GreatVibes: loadGreatVibes(),
  PlayfairDisplay: loadPlayfairDisplay(),
  Montserrat: loadMontserrat(),
};

function resolveFontFamily(titleFont?: string): string {
  const key = titleFont ?? "PlayfairDisplay";
  return FONTS[key]?.fontFamily ?? "Georgia, serif";
}

const GOLD = "#C9952A";
const GOLD_MUTED = "#B8943E";
const OFF_WHITE = "#F5F0E8";

const MapPinIcon: React.FC = () => (
  <svg width="26" height="32" viewBox="0 0 26 32" fill="none">
    <path
      d="M13 0C5.82 0 0 5.82 0 13c0 9.1 11.7 19 13 19s13-9.9 13-19C26 5.82 20.18 0 13 0z"
      fill="#7A4F2E"
    />
    <path
      d="M13 1.4C6.59 1.4 1.4 6.59 1.4 13c0 8 10.4 17.2 11.6 17.2S24.6 21 24.6 13C24.6 6.59 19.41 1.4 13 1.4z"
      fill="#9C6540"
    />
    <circle cx="13" cy="13" r="5" fill="#BF8A60" />
    <circle cx="13" cy="13" r="2.8" fill="#7A4F2E" />
  </svg>
);

const RoundedQR: React.FC<{
  value: string;
  size: number;
  initial: string;
}> = ({ value, size, initial }) => {
  const matrix = useMemo(() => {
    try {
      return QRCode.create(value, { errorCorrectionLevel: "M" }).modules;
    } catch {
      return null;
    }
  }, [value]);

  if (!matrix) return null;

  const N = matrix.size;
  const margin = 2;
  const totalModules = N + margin * 2;
  const cellSize = size / totalModules;
  const rx = cellSize * 0.28;

  const logoSpan = Math.max(3, Math.floor(N * 0.2));
  const centerStart = Math.floor((N - logoSpan) / 2);
  const centerEnd = centerStart + logoSpan;

  const modules: React.ReactElement[] = [];
  for (let r = 0; r < N; r++) {
    for (let c = 0; c < N; c++) {
      if (!matrix.get(r, c)) continue;
      if (r >= centerStart && r < centerEnd && c >= centerStart && c < centerEnd) continue;
      const x = (c + margin) * cellSize;
      const y = (r + margin) * cellSize;
      modules.push(
        <rect
          key={`${r}-${c}`}
          x={x}
          y={y}
          width={cellSize}
          height={cellSize}
          rx={rx}
          ry={rx}
          fill={OFF_WHITE}
        />
      );
    }
  }

  const logoSize = logoSpan * cellSize;
  const logoX = (centerStart + margin) * cellSize;
  const logoY = (centerStart + margin) * cellSize;
  const logoFontSize = logoSize * 0.7;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {modules}
      <rect
        x={logoX}
        y={logoY}
        width={logoSize}
        height={logoSize}
        rx={logoSize * 0.18}
        fill="#12101e"
      />
      <text
        x={logoX + logoSize / 2}
        y={logoY + logoSize / 2 + logoFontSize * 0.36}
        textAnchor="middle"
        fontSize={logoFontSize}
        fontWeight="700"
        fill={GOLD}
        fontFamily="Georgia, serif"
      >
        {initial}
      </text>
    </svg>
  );
};

const countryFlag = (code: string) =>
  [...code.toUpperCase()]
    .filter((c) => /[A-Z]/.test(c))
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join("");

export const OutroCard: React.FC<{
  businessName: string;
  websiteUrl?: string;
  mapsUrl?: string;
  miniMapUrl?: string;
  city?: string;
  country?: string;
  countryCode?: string;
  showQr: boolean;
  showWebsite: boolean;
  titleFont?: string;
}> = ({
  businessName,
  websiteUrl,
  mapsUrl,
  miniMapUrl,
  city,
  country,
  countryCode,
  showQr,
  showWebsite,
  titleFont,
}) => {
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
    config: { damping: 22, stiffness: 75 },
    from: 60,
    to: 0,
  });

  // Slow shimmer sweep: 0% → 100% over the slide duration
  const shimmerPos = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const flag = countryCode ? countryFlag(countryCode) + " " : "";
  const locationLine = [city, country ? flag + country : ""]
    .filter(Boolean)
    .join("  ·  ");

  const hasQr = showQr && !!mapsUrl;
  const hasWebsite = showWebsite && !!websiteUrl;
  const titleFontFamily = resolveFontFamily(titleFont);
  const initial = businessName.charAt(0).toUpperCase();

  return (
    <AbsoluteFill
      style={{
        opacity,
        background:
          "linear-gradient(160deg, #0d1b2a 0%, #1a1628 55%, #251e18 100%)",
      }}
    >
      {miniMapUrl ? (
        /* Three-zone layout: top text | map | QR */
        <div
          style={{
            transform: `translateY(${translateY}px)`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "space-between",
            height: "100%",
            padding: "48px 80px",
          }}
        >
          {/* TOP: business name + location + website */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
              marginTop: 40,
            }}
          >
            <div
              style={{
                fontSize: 76,
                fontWeight: 700,
                fontFamily: titleFontFamily,
                lineHeight: 1.15,
                textAlign: "center",
                background:
                  "linear-gradient(105deg, #7a5c18 0%, #c9952a 22%, #f5d98b 50%, #c9952a 78%, #7a5c18 100%)",
                backgroundSize: "200% 100%",
                backgroundPosition: `${shimmerPos}% 0`,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              {businessName}
            </div>
            {locationLine && (
              <div
                style={{
                  fontSize: 32,
                  color: "rgba(205,185,140,0.72)",
                  textAlign: "center",
                  fontFamily: "Montserrat, system-ui, sans-serif",
                  letterSpacing: "0.05em",
                }}
              >
                {locationLine}
              </div>
            )}
            {hasWebsite && (
              <div
                style={{
                  fontSize: 27,
                  color: GOLD_MUTED,
                  textAlign: "center",
                  fontFamily: "Montserrat, system-ui, sans-serif",
                  letterSpacing: "0.04em",
                  opacity: 0.82,
                }}
              >
                {websiteUrl!.length > 44
                  ? websiteUrl!.slice(0, 41) + "…"
                  : websiteUrl}
              </div>
            )}
          </div>

          {/* MIDDLE: map as large as possible */}
          <div
            style={{
              width: 920,
              height: 920,
              borderRadius: 24,
              overflow: "hidden",
              boxShadow:
                "0 12px 60px rgba(0,0,0,0.7), 0 0 0 1px rgba(201,149,42,0.22)",
            }}
          >
            <img
              src={miniMapUrl}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>

          {/* BOTTOM: QR + "scan to visit" */}
          {hasQr && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 14,
                marginBottom: 40,
              }}
            >
              <div
                style={{
                  padding: 22,
                  background: "rgba(8,6,18,0.88)",
                  borderRadius: 20,
                  boxShadow:
                    "0 8px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(201,149,42,0.18)",
                }}
              >
                <RoundedQR value={mapsUrl!} size={320} initial={initial} />
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 24,
                  color: "rgba(215,195,145,0.85)",
                  fontFamily: "Montserrat, system-ui, sans-serif",
                  fontWeight: 500,
                }}
              >
                <MapPinIcon />
                Scan to visit us
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Fallback: centered layout when no map */
        <div
          style={{
            transform: `translateY(${translateY}px)`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            gap: 20,
            padding: "48px 80px",
          }}
        >
          <div
            style={{
              fontSize: 76,
              fontWeight: 700,
              fontFamily: titleFontFamily,
              lineHeight: 1.15,
              textAlign: "center",
              background:
                "linear-gradient(105deg, #7a5c18 0%, #c9952a 22%, #f5d98b 50%, #c9952a 78%, #7a5c18 100%)",
              backgroundSize: "200% 100%",
              backgroundPosition: `${shimmerPos}% 0`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            {businessName}
          </div>
          {locationLine && (
            <div
              style={{
                fontSize: 32,
                color: "rgba(205,185,140,0.72)",
                textAlign: "center",
                fontFamily: "Montserrat, system-ui, sans-serif",
                letterSpacing: "0.05em",
              }}
            >
              {locationLine}
            </div>
          )}
          {hasWebsite && (
            <div
              style={{
                fontSize: 27,
                color: GOLD_MUTED,
                textAlign: "center",
                fontFamily: "Montserrat, system-ui, sans-serif",
                letterSpacing: "0.04em",
                opacity: 0.82,
              }}
            >
              {websiteUrl!.length > 44
                ? websiteUrl!.slice(0, 41) + "…"
                : websiteUrl}
            </div>
          )}
          {hasQr && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 14,
                marginTop: 8,
              }}
            >
              <div
                style={{
                  padding: 22,
                  background: "rgba(8,6,18,0.88)",
                  borderRadius: 20,
                  boxShadow:
                    "0 8px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(201,149,42,0.18)",
                }}
              >
                <RoundedQR value={mapsUrl!} size={320} initial={initial} />
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 24,
                  color: "rgba(215,195,145,0.85)",
                  fontFamily: "Montserrat, system-ui, sans-serif",
                  fontWeight: 500,
                }}
              >
                <MapPinIcon />
                Scan to visit us
              </div>
            </div>
          )}
        </div>
      )}
    </AbsoluteFill>
  );
};
