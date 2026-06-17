import { Composition, registerRoot } from "remotion";
import { ReviewVideo, calculateMetadata, defaultProps } from "./Composition";

const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ReviewVideo"
      component={ReviewVideo}
      calculateMetadata={calculateMetadata}
      durationInFrames={300}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
    />
  );
};

registerRoot(RemotionRoot);
