import React from "react";
import { AbsoluteFill, Audio, Sequence, useVideoConfig } from "remotion";
import { Overlays } from "./Overlays";
import { ShotLayer } from "./Shots";
import { Subtitles } from "./Subtitles";
import type { Brandbook, EditPlan } from "./types";

/**
 * Композиция ролика по edit-плану. Тот же документ, что рендерит встроенный
 * ffmpeg-композитор (src/lib/render/compositor.py), поэтому оба движка обязаны
 * давать один и тот же монтаж.
 */
export const Redshift: React.FC<{ plan: EditPlan; brandbook: Brandbook; audioSrc?: string }> = ({
  plan,
  brandbook,
  audioSrc,
}) => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: brandbook.colors.ink }}>
      {plan.shots.map((shot) => (
        <Sequence
          key={shot.index}
          from={Math.round(shot.start * fps)}
          durationInFrames={Math.max(1, Math.round(shot.duration * fps))}
        >
          <ShotLayer shot={shot} brandbook={brandbook} />
        </Sequence>
      ))}

      <Overlays overlays={plan.overlays} brandbook={brandbook} />

      {plan.shots
        .filter((shot) => shot.kind !== "fullscreen_text")
        .map((shot) => (
          <Sequence
            key={`sub-${shot.index}`}
            from={Math.round(shot.start * fps)}
            durationInFrames={Math.max(1, Math.round(shot.duration * fps))}
          >
            <Subtitles
              words={plan.subtitles}
              brandbook={brandbook}
              baselineY={plan.subtitle_style.baseline_y}
              mode={plan.subtitle_style.mode}
              hidden={false}
            />
          </Sequence>
        ))}

      {audioSrc ? <Audio src={audioSrc} /> : null}
    </AbsoluteFill>
  );
};
