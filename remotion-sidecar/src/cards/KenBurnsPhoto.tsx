import { AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { CROSSFADE } from "../Composition";

export const KenBurnsPhoto: React.FC<{ url: string; isFirst: boolean }> = ({
  url,
  isFirst,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const scale = interpolate(frame, [0, durationInFrames], [1, 1.08], {
    extrapolateRight: "clamp",
  });

  const opacity = isFirst
    ? 1
    : interpolate(frame, [0, CROSSFADE], [0, 1], {
        extrapolateRight: "clamp",
      });

  return (
    <AbsoluteFill style={{ opacity }}>
      <AbsoluteFill
        style={{
          transform: `scale(${scale})`,
          transformOrigin: "center center",
        }}
      >
        <Img
          src={url}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
