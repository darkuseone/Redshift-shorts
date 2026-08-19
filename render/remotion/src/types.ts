/**
 * Типы edit-плана. Соответствуют тому, что пишет P11 (src/p11_assemble).
 * Формат общий для обоих движков рендера: §9.1 требует, чтобы по edit-плану
 * ролик пересобирался один в один без обращений к внешним API.
 */

export type ShotKind = "footage" | "avatar" | "split" | "fullscreen_text" | "meme";

export interface KenBurns {
  template: string;
  zoom?: [number, number];
  pan?: [number, number];
  anchor?: string;
  layers?: number;
}

export interface Transition {
  template: string;
  renderer: string;
  duration: number;
  params: Record<string, unknown>;
}

export interface Shot {
  index: number;
  start: number;
  end: number;
  duration: number;
  kind: ShotKind;
  block_id: string;
  role: string;
  mode: string;
  file?: string | null;
  asset_id?: string | null;
  source?: string;
  license?: string;
  content?: string;
  template?: string;
  invert?: boolean;
  accent_word?: string | null;
  kenburns?: KenBurns | null;
  transition?: Transition | null;
  avatar_offset_sec?: number | null;
  ai_generated?: boolean;
}

export interface Overlay {
  type: "source_card" | "highlight" | "plaque" | "cta" | "text_behind_head";
  start: number;
  end: number;
  template?: string;
  params: Record<string, any>;
  why?: string;
}

export interface SubtitleWord {
  display: string;
  start: number;
  end: number;
  emphasis: boolean;
  block_id: string;
}

export interface EditPlan {
  video_id: string;
  variant: string;
  fps: number;
  resolution: [number, number];
  duration_sec: number;
  audio: { mix: string; voice: string; music_bed: string; sfx_map: string };
  shots: Shot[];
  overlays: Overlay[];
  subtitles: SubtitleWord[];
  subtitle_style: { mode: "stroke" | "pill"; baseline_y: number };
  templates_used: string[];
  cta_window: [number, number];
}

export interface SubtitleSpec {
  color: string;
  stroke_color: string;
  stroke_px: [number, number];
  size_px_default: number;
  max_block_width_px: number;
  pill_radius_px: number;
  pill_padding_px: [number, number];
  baseline_y_default: number;
}

export interface FullscreenTextSpec {
  size_px: [number, number];
  words_max: number;
}

export interface PlaqueSpec {
  radius_px_default: number;
  bg_alpha: number;
  border_px: number;
  border_alpha: number;
}

export interface HighlightSpec {
  dim_opacity_default: number;
  cutout_radius_px: number;
}

export interface Brandbook {
  colors: Record<string, string>;
  safe_zones: { work_area: { x_min: number; x_max: number; y_min: number; y_max: number } };
  subtitles: SubtitleSpec;
  fullscreen_text: FullscreenTextSpec;
  plaque: PlaqueSpec;
  highlight: HighlightSpec;
  cta: { button_pulse_hz: number; tail_sec: number };
  easing: Record<string, [number, number, number, number]>;
}
