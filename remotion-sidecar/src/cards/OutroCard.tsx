import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { QRCodeSVG } from "qrcode.react";
import { CROSSFADE } from "../Composition";

const countryFlag = (code: string) =>
  [...code.toUpperCase()]
    .filter((c) => /[A-Z]/.test(c))
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join("");

export const OutroCard: React.FC<{
  businessName: string;
  websiteUrl?: string;
  mapsUrl?: string;
  city?: string;
  country?: string;
  countryCode?: string;
  showQr: boolean;
  showWebsite: boolean;
}> = ({
  businessName,
  websiteUrl,
  mapsUrl,
  city,
  country,
  countryCode,
  showQr,
  showWebsite,
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

  const flag = countryCode ? countryFlag(countryCode) + " " : "";
  const locationLine = [city, country ? flag + country : ""]
    .filter(Boolean)
    .join("  ·  ");

  const hasQr = showQr && !!mapsUrl;
  const hasWebsite = showWebsite && !!websiteUrl;

  return (
    <AbsoluteFill
      style={{
        opacity,
        background: "linear-gradient(160deg, #0d0d1a 0%, #1a1030 100%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "80px 64px",
      }}
    >
      <div
        style={{
          transform: `translateY(${translateY}px)`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
          width: "100%",
        }}
      >
        {/* Business name */}
        <div
          style={{
            fontSize: 76,
            fontWeight: 800,
            color: "white",
            textAlign: "center",
            lineHeight: 1.1,
            fontFamily: "system-ui, -apple-system, sans-serif",
            textShadow: "0 2px 12px rgba(0,0,0,0.5)",
          }}
        >
          {businessName}
        </div>

        {/* Location */}
        {locationLine && (
          <div
            style={{
              fontSize: 38,
              color: "rgba(200,200,200,0.75)",
              textAlign: "center",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }}
          >
            {locationLine}
          </div>
        )}

        {/* Website */}
        {hasWebsite && (
          <div
            style={{
              fontSize: 32,
              color: "rgba(160,160,220,0.85)",
              textAlign: "center",
              fontFamily: "system-ui, -apple-system, sans-serif",
              marginTop: 4,
            }}
          >
            {websiteUrl!.length > 44
              ? websiteUrl!.slice(0, 41) + "…"
              : websiteUrl}
          </div>
        )}

        {/* QR code */}
        {hasQr && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 20,
              marginTop: 24,
            }}
          >
            <div
              style={{
                padding: 24,
                background: "white",
                borderRadius: 20,
                boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
              }}
            >
              <QRCodeSVG value={mapsUrl!} size={380} />
            </div>
            <div
              style={{
                fontSize: 36,
                color: "rgba(200,200,200,0.8)",
                fontFamily: "system-ui, -apple-system, sans-serif",
                textAlign: "center",
              }}
            >
              📍 Find us on Google Maps
            </div>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
