import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { IntroCard } from "./cards/IntroCard";
import { ReviewCard } from "./cards/ReviewCard";
import { ReviewHighlight } from "./cards/ReviewHighlight";
import { MapCard } from "./cards/MapCard";
import { OutroCard } from "./cards/OutroCard";
import { KenBurnsPhoto } from "./cards/KenBurnsPhoto";

export type Palette = { accent: string; cardBg: string };

export const PALETTES: Record<string, Palette> = {
  restaurant: { accent: "#F59E0B", cardBg: "rgba(245,158,11,0.10)" },
  medical:    { accent: "#3B82F6", cardBg: "rgba(59,130,246,0.10)" },
  retail:     { accent: "#EF4444", cardBg: "rgba(239,68,68,0.10)" },
  other:      { accent: "#6B7280", cardBg: "rgba(8,8,18,0.78)" },
};

export type InputProps = {
  businessName: string;
  rating: number;
  city?: string;
  country?: string;
  countryCode?: string;
  websiteUrl?: string;
  mapsUrl?: string;
  review?: { text: string; rating: number; author: string } | null;
  photoUrls: string[];
  mapImageUrl?: string;
  miniMapUrl?: string;
  musicUrl?: string;
  musicOffset?: number;
  industryVibe?: string;
  reviewStyle?: "classic" | "highlight";
  highlightPhrases?: string[];
  ttsUrl?: string;
  ttsDurationSeconds?: number | null;
  tagline?: string;
  titleFont?: string;
  sunBleach?: boolean;
  cards: {
    intro: { enabled: boolean };
    review: { enabled: boolean };
    map: { enabled: boolean };
    outro: { enabled: boolean; showQr: boolean; showWebsite: boolean };
  };
};

export const defaultProps: InputProps = {
  businessName: "Example Business",
  rating: 4.5,
  city: "Paris",
  country: "France",
  countryCode: "FR",
  websiteUrl: "www.example.com",
  mapsUrl: "https://maps.google.com",
  review: {
    text: "This is an amazing place! Highly recommended to everyone who loves great service.",
    rating: 5,
    author: "John D.",
  },
  photoUrls: [
    "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1080",
  ],
  mapImageUrl: "",
  musicUrl: "",
  musicOffset: 0,
  industryVibe: "other",
  reviewStyle: "highlight",
  highlightPhrases: [],
  ttsUrl: "",
  ttsDurationSeconds: null,
  tagline: "",
  titleFont: "PlayfairDisplay",
  sunBleach: false,
  cards: {
    intro: { enabled: true },
    review: { enabled: true },
    map: { enabled: false },
    outro: { enabled: true, showQr: true, showWebsite: true },
  },
};

const FPS = 30;
export const CROSSFADE = Math.round(0.5 * FPS); // 15 frames

const CARD_FRAMES = {
  intro: 2 * FPS,   // 60
  review: 4 * FPS,  // 120
  map: 3 * FPS,     // 90
  outro: 5 * FPS,   // 150
};

type CardEntry = { type: string; dur: number; from: number };

function reviewDurFrames(ttsDurationSeconds?: number | null): number {
  if (!ttsDurationSeconds) return CARD_FRAMES.review;
  // pad by 1.5s: 0.5s crossfade + 1s buffer for mp3 encoder silence and measurement imprecision
  return Math.ceil((ttsDurationSeconds + 1.5) * FPS);
}

function buildSequence(cards: InputProps["cards"], reviewDur: number = CARD_FRAMES.review): CardEntry[] {
  const active: { type: string; dur: number }[] = [];
  if (cards.intro.enabled) active.push({ type: "intro", dur: CARD_FRAMES.intro });
  if (cards.review.enabled) active.push({ type: "review", dur: reviewDur });
  if (cards.map.enabled) active.push({ type: "map", dur: CARD_FRAMES.map });
  if (cards.outro.enabled) active.push({ type: "outro", dur: CARD_FRAMES.outro });

  let cursor = 0;
  return active.map((c) => {
    const entry = { ...c, from: cursor };
    cursor += c.dur - CROSSFADE;
    return entry;
  });
}

export const calculateMetadata: CalculateMetadataFunction<InputProps> = ({
  props,
}) => {
  const reviewDur = reviewDurFrames(props.ttsDurationSeconds);
  const seq = buildSequence(props.cards, reviewDur);
  if (seq.length === 0) return { durationInFrames: FPS * 3, fps: FPS };
  const last = seq[seq.length - 1];
  const total = last.from + last.dur;
  return { durationInFrames: Math.max(total, 30), fps: FPS };
};

export const ReviewVideo: React.FC<InputProps> = (props) => {
  const {
    photoUrls,
    musicUrl,
    musicOffset = 0,
    cards,
    review,
    mapImageUrl,
    miniMapUrl,
    businessName,
    rating,
    city,
    country,
    countryCode,
    websiteUrl,
    mapsUrl,
    industryVibe,
    reviewStyle = "highlight",
    highlightPhrases = [],
    ttsUrl,
    ttsDurationSeconds,
    tagline,
    titleFont,
    sunBleach = false,
  } = props;

  const palette: Palette = PALETTES[industryVibe ?? "other"] ?? PALETTES["other"];

  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const FADE = 15;
  const globalOpacity = interpolate(
    frame,
    [0, FADE, durationInFrames - FADE, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const n = Math.min(photoUrls.length, 5);
  const photos = photoUrls.slice(0, n);

  const sequences = buildSequence(cards, reviewDurFrames(ttsDurationSeconds));
  const reviewSeq = sequences.find((s) => s.type === "review");
  const outroSeq = sequences.find((s) => s.type === "outro");

  // Photos stop when the outro begins so they don't bleed through the outro's fade-out.
  const photoEndFrame = outroSeq ? outroSeq.from : durationInFrames;
  const photoClipDur =
    n > 0
      ? Math.round((photoEndFrame + (n - 1) * CROSSFADE) / n)
      : photoEndFrame;

  const DUCK_FRAMES = 15;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity: globalOpacity }}>
      {/* Ken Burns photo backgrounds */}
      {photos.map((url, i) => (
        <Sequence
          key={`photo-${i}`}
          from={Math.round(i * (photoClipDur - CROSSFADE))}
          durationInFrames={photoClipDur}
          layout="none"
        >
          <KenBurnsPhoto url={url} isFirst={i === 0} sunBleach={sunBleach} />
        </Sequence>
      ))}

      {/* Card overlays */}
      {sequences.map((seq) => (
        <Sequence
          key={seq.type}
          from={seq.from}
          durationInFrames={seq.dur}
          layout="none"
        >
          {seq.type === "intro" && (
            <IntroCard
              businessName={businessName}
              rating={rating}
              city={city}
              country={country}
              countryCode={countryCode}
              palette={palette}
              tagline={tagline}
              titleFont={titleFont}
            />
          )}
          {seq.type === "review" && review && reviewStyle === "classic" && (
            <ReviewCard review={review} palette={palette} />
          )}
          {seq.type === "review" && review && reviewStyle === "highlight" && (
            <ReviewHighlight
              review={review}
              palette={palette}
              highlightPhrases={highlightPhrases}
            />
          )}
          {seq.type === "map" && mapImageUrl && (
            <MapCard
              mapImageUrl={mapImageUrl}
              businessName={businessName}
              city={city}
            />
          )}
          {seq.type === "outro" && (
            <OutroCard
              businessName={businessName}
              websiteUrl={websiteUrl}
              mapsUrl={mapsUrl}
              miniMapUrl={miniMapUrl}
              city={city}
              country={country}
              countryCode={countryCode}
              showQr={cards.outro.showQr}
              showWebsite={cards.outro.showWebsite}
              titleFont={titleFont}
            />
          )}
        </Sequence>
      ))}

      {/* Background music — ducks during review card when TTS is active */}
      {musicUrl && (
        <Sequence from={0} durationInFrames={durationInFrames} layout="none">
          <Audio
            src={musicUrl}
            trimBefore={Math.round(musicOffset * fps)}
            volume={(f) => {
              const base = interpolate(
                f,
                [0, FADE, durationInFrames - FADE, durationInFrames],
                [0, 1, 1, 0],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              if (!ttsUrl || !reviewSeq) return base;
              const duck = interpolate(
                f,
                [
                  reviewSeq.from,
                  reviewSeq.from + DUCK_FRAMES,
                  reviewSeq.from + reviewSeq.dur - DUCK_FRAMES,
                  reviewSeq.from + reviewSeq.dur,
                ],
                [1, 0.2, 0.2, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return base * duck;
            }}
          />
        </Sequence>
      )}

      {/* TTS voice — plays during review card */}
      {ttsUrl && reviewSeq && (
        <Sequence
          from={reviewSeq.from}
          durationInFrames={reviewSeq.dur}
          layout="none"
        >
          <Audio
            src={ttsUrl}
            volume={(f) =>
              interpolate(
                f,
                [0, FADE, reviewSeq.dur - FADE, reviewSeq.dur],
                [0, 1, 1, 0],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              )
            }
          />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
