import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brandbook, Overlay } from "./types";

const easeOutBack = (t: number) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};

/**
 * Слои графики поверх видеоряда. Порядок задан смыслом (§5): карточка источника
 * лежит под подсветкой, плашки — над ними, кнопка подписки — выше всего.
 */
export const Overlays: React.FC<{ overlays: Overlay[]; brandbook: Brandbook }> = ({
  overlays,
  brandbook,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const active = overlays.filter((o) => t >= o.start && t < o.end);
  const order = { source_card: 0, highlight: 1, text_behind_head: 2, plaque: 3, cta: 4 };

  return (
    <>
      {active
        .slice()
        .sort((a, b) => (order[a.type] ?? 9) - (order[b.type] ?? 9))
        .map((overlay, i) => {
          const progress = Math.min(1, Math.max(0, (t - overlay.start) / Math.max(overlay.end - overlay.start, 1e-6)));
          switch (overlay.type) {
            case "source_card":
              return <SourceCard key={i} overlay={overlay} brandbook={brandbook} progress={progress} />;
            case "plaque":
              return <Plaque key={i} overlay={overlay} brandbook={brandbook} progress={progress} />;
            case "cta":
              return <SubscribeButton key={i} brandbook={brandbook} elapsed={t - overlay.start} />;
            case "highlight":
              return <Highlight key={i} brandbook={brandbook} progress={progress} />;
            default:
              return null;
          }
        })}
    </>
  );
};

/** §5.6: домен и заголовок читаемы, карточка не мельче 60 % ширины кадра. */
const SourceCard: React.FC<{ overlay: Overlay; brandbook: Brandbook; progress: number }> = ({
  overlay,
  brandbook,
  progress,
}) => {
  const area = brandbook.safe_zones.work_area;
  const enter = interpolate(progress, [0, 0.25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: area.x_min,
          top: area.y_min + 160 - (1 - enter) * 120,
          width: area.x_max - area.x_min,
          background: brandbook.colors.bg_pure,
          borderRadius: 22,
          boxShadow: "0 10px 30px rgba(0,0,0,0.2)",
          overflow: "hidden",
          opacity: enter,
        }}
      >
        <div style={{ background: brandbook.colors.bg_light, padding: "18px 24px", display: "flex", gap: 12 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 26, color: brandbook.colors.ink }}>
            {overlay.params.domain}
          </span>
        </div>
        <div style={{ padding: "24px 36px 30px" }}>
          <div style={{ fontFamily: "Nunito, sans-serif", fontWeight: 800, fontSize: 46, color: brandbook.colors.ink }}>
            {overlay.params.title}
          </div>
          {overlay.params.snippet ? (
            <div style={{ marginTop: 12, fontFamily: "Nunito, sans-serif", fontSize: 30, color: brandbook.colors.muted }}>
              {overlay.params.snippet}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** §5.4: выезд 200–280 мс с overshoot 6–8 %, уход в ту же сторону. */
const Plaque: React.FC<{ overlay: Overlay; brandbook: Brandbook; progress: number }> = ({
  overlay,
  brandbook,
  progress,
}) => {
  const area = brandbook.safe_zones.work_area;
  const enter = easeOutBack(Math.min(1, progress / 0.15));
  const spec = brandbook.plaque;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: overlay.params.position === "top" ? area.y_min + 40 : area.y_max - 200,
        display: "flex",
        justifyContent: "center",
        transform: `translateX(${(1 - enter) * -60}%)`,
      }}
    >
      <div
        style={{
          background: brandbook.colors.bg_light,
          opacity: spec.bg_alpha,
          border: `${spec.border_px}px solid ${brandbook.colors.accent}`,
          borderRadius: spec.radius_px_default,
          padding: "26px 40px",
          textAlign: "center",
          fontFamily: "Nunito, sans-serif",
          fontWeight: 800,
          fontSize: 48,
          color: brandbook.colors.ink,
        }}
      >
        {overlay.params.text}
        {overlay.params.subtitle ? (
          <div style={{ fontSize: 30, color: brandbook.colors.muted, marginTop: 6 }}>
            {overlay.params.subtitle}
          </div>
        ) : null}
      </div>
    </div>
  );
};

/** §5.5: затемнение 70–85 % с вырезом вокруг цели. */
const Highlight: React.FC<{ brandbook: Brandbook; progress: number }> = ({ brandbook, progress }) => {
  const opacity = interpolate(progress, [0, 0.2], [0, brandbook.highlight.dim_opacity_default], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <AbsoluteFill style={{ backgroundColor: brandbook.colors.ink, opacity, mixBlendMode: "multiply" }} />;
};

/** §6, QC-16: кнопка подписки обязана быть в последние 2 сек. */
const SubscribeButton: React.FC<{ brandbook: Brandbook; elapsed: number }> = ({ brandbook, elapsed }) => {
  const area = brandbook.safe_zones.work_area;
  const pulse = 1 + 0.035 * Math.sin(elapsed * Math.PI * 2 * brandbook.cta.button_pulse_hz);
  const enter = easeOutBack(Math.min(1, elapsed * 4));
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: area.y_max - 120,
        display: "flex",
        justifyContent: "center",
        transform: `scale(${pulse * enter})`,
      }}
    >
      <div
        style={{
          background: brandbook.colors.accent,
          color: brandbook.colors.bg_pure,
          borderRadius: 999,
          padding: "30px 56px",
          fontFamily: "Oswald, sans-serif",
          fontWeight: 700,
          fontSize: 62,
        }}
      >
        ПОДПИСАТЬСЯ
      </div>
    </div>
  );
};
