import {
  AbsoluteFill,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CROSSFADE } from "../Composition";

export const MapCard: React.FC<{
  mapImageUrl: string;
  businessName: string;
  city?: string;
}> = ({ mapImageUrl, businessName, city }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(
    frame,
    [0, CROSSFADE, durationInFrames - CROSSFADE, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const shortName =
    businessName.length > 32
      ? businessName.slice(0, 31) + "…"
      : businessName;

  return (
    <AbsoluteFill style={{ opacity }}>
      <Img
        src={mapImageUrl}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
      {/* Bottom gradient + labels */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to top, rgba(0,0,0,0.88) 0%, rgba(0,0,0,0.4) 30%, transparent 55%)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          padding: "0 60px 120px",
        }}
      >
        {city && (
          <div
            style={{
              fontSize: 60,
              fontWeight: 700,
              color: "white",
              fontFamily: "system-ui, -apple-system, sans-serif",
              marginBottom: 10,
              textShadow: "0 2px 8px rgba(0,0,0,0.6)",
            }}
          >
            {city}
          </div>
        )}
        <div
          style={{
            fontSize: 40,
            color: "rgba(210,210,210,0.9)",
            fontFamily: "system-ui, -apple-system, sans-serif",
          }}
        >
          {shortName}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
