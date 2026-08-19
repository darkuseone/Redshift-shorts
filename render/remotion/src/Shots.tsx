import React from "react";
import { AbsoluteFill, Img, interpolate, OffthreadVideo, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brandbook, Shot } from "./types";

/** Ken Burns §3.6.4: масштаб 1.0 → 1.08…1.15 за 2.5–5 сек, ease-out cubic. */
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

export const ShotLayer: React.FC<{ shot: Shot; brandbook: Brandbook }> = ({ shot, brandbook }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = Math.min(1, Math.max(0, (frame / fps) / Math.max(shot.duration, 1e-6)));

  if (shot.kind === "fullscreen_text") {
    return <FullscreenText shot={shot} brandbook={brandbook} progress={local} />;
  }
  if (!shot.file) {
    return <AbsoluteFill style={{ backgroundColor: brandbook.colors.bg_light }} />;
  }

  const zoom = shot.kenburns?.zoom ?? [1, 1];
  const pan = shot.kenburns?.pan ?? [0, 0];
  const eased = easeOutCubic(local);
  const scale = zoom[0] + (zoom[1] - zoom[0]) * eased;
  const shiftX = pan[0] * eased * 50 * (1 - 1 / Math.max(scale, 1e-6));
  const shiftY = pan[1] * eased * 50 * (1 - 1 / Math.max(scale, 1e-6));

  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: brandbook.colors.ink }}>
      <OffthreadVideo
        src={shot.file}
        startFrom={Math.round((shot.avatar_offset_sec ?? 0) * fps)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translate(${shiftX}%, ${shiftY}%)`,
        }}
      />
    </AbsoluteFill>
  );
};

/** Полноэкранный текст §5.2: вход снизу 180–250 мс + приближение до 1.06. */
const FullscreenText: React.FC<{ shot: Shot; brandbook: Brandbook; progress: number }> = ({
  shot,
  brandbook,
  progress,
}) => {
  const enter = easeOutCubic(Math.min(1, progress / 0.18));
  const scale = 1 + 0.06 * progress;
  const invert = Boolean(shot.invert);
  const spec = brandbook.fullscreen_text;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: invert ? brandbook.colors.ink : brandbook.colors.bg_pure,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          fontFamily: "Oswald, sans-serif",
          fontWeight: 700,
          fontSize: spec.size_px[0],
          lineHeight: 0.94,
          color: invert ? brandbook.colors.bg_pure : brandbook.colors.ink,
          textAlign: "center",
          maxWidth: brandbook.safe_zones.work_area.x_max - brandbook.safe_zones.work_area.x_min,
          transform: `translateY(${(1 - enter) * 90}px) scale(${scale})`,
          opacity: enter,
          textTransform: "uppercase",
        }}
      >
        {shot.content}
      </div>
      {shot.template?.includes("impact-02") ? (
        <div
          style={{
            marginTop: 24,
            height: 12,
            width: `${Math.min(1, progress * 2.5) * 60}%`,
            borderRadius: 6,
            backgroundColor: brandbook.colors.accent,
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
