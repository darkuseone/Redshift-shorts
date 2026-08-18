import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brandbook, SubtitleWord } from "./types";

/**
 * Пословные субтитры §5.1: одно слово по центру кадра, pop-in 90–120 мс,
 * scale 0.92 → 1.0, без вращений.
 *
 * Акцентное слово красное со **светлой** обводкой: тёмно-красная обводка
 * (accent_deep) рассчитана на белый текст и по красному слову не читается.
 */
export const Subtitles: React.FC<{
  words: SubtitleWord[];
  brandbook: Brandbook;
  baselineY: number;
  mode: "stroke" | "pill";
  hidden: boolean;
}> = ({ words, brandbook, baselineY, mode, hidden }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  if (hidden) return null;
  const word = words.find((w) => t >= w.start && t < w.end);
  if (!word) return null;

  const spec = brandbook.subtitles;
  const popIn = interpolate(t - word.start, [0, 0.11], [0.92, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(t - word.start, [0, 0.05], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const color = word.emphasis ? brandbook.colors.accent : spec.color;
  const strokeColor = word.emphasis
    ? brandbook.colors.bg_pure
    : brandbook.colors[spec.stroke_color];
  const strokeWidth = spec.stroke_px[0];

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: baselineY,
        display: "flex",
        justifyContent: "center",
        transform: `translateY(-50%) scale(${popIn})`,
        opacity,
      }}
    >
      <span
        style={{
          fontFamily: "Nunito, sans-serif",
          fontWeight: 800,
          fontSize: spec.size_px_default,
          color,
          maxWidth: spec.max_block_width_px,
          textAlign: "center",
          ...(mode === "pill"
            ? {
                background: brandbook.colors.overlay_dim,
                borderRadius: spec.pill_radius_px,
                padding: `${spec.pill_padding_px[1]}px ${spec.pill_padding_px[0]}px`,
              }
            : {
                WebkitTextStroke: `${strokeWidth}px ${strokeColor}`,
                paintOrder: "stroke fill",
              }),
        }}
      >
        {word.display.replace(/[,.!?;:—–]+$/u, "")}
      </span>
    </div>
  );
};
