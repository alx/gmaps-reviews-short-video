const STAR_PATH =
  "M 12 2 L 15.09 8.26 L 22 9.27 L 17 14.14 L 18.18 21.02 L 12 17.77 L 5.82 21.02 L 7 14.14 L 2 9.27 L 8.91 8.26 Z";

export const StarRating: React.FC<{
  rating: number;
  size?: number;
  color?: string;
  emptyColor?: string;
}> = ({ rating, size = 40, color = "#F59E0B", emptyColor = "rgba(255,255,255,0.3)" }) => {
  return (
    <div style={{ display: "flex", gap: size * 0.12 }}>
      {Array.from({ length: 5 }, (_, i) => {
        const filled = i + 1 <= Math.round(rating);
        return (
          <svg key={i} width={size} height={size} viewBox="0 0 24 24">
            <path
              d={STAR_PATH}
              fill={filled ? color : "none"}
              stroke={filled ? color : emptyColor}
              strokeWidth={1.5}
              strokeLinejoin="round"
            />
          </svg>
        );
      })}
    </div>
  );
};
