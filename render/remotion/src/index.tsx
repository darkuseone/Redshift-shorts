import React from "react";
import { Composition, registerRoot } from "remotion";
import { Redshift } from "./Redshift";
import type { Brandbook, EditPlan } from "./types";

/**
 * Точка входа Remotion. План и брендбук приходят входными пропсами, чтобы один
 * и тот же проект рендерил любую версию любого ролика:
 *
 *   npx remotion render src/index.tsx Redshift out/A.mp4 \
 *     --props=../../output/redshift_0042/edit_plan_A.json
 *
 * Размер и длительность композиции берутся из плана: они уже посчитаны в P5/P11
 * и должны совпадать с тем, что рендерит встроенный композитор.
 */
const EMPTY_PLAN = {
  duration_sec: 50,
  fps: 30,
  resolution: [1080, 1920],
  shots: [],
  overlays: [],
  subtitles: [],
  subtitle_style: { mode: "stroke", baseline_y: 975 },
} as unknown as EditPlan;

const Root: React.FC = () => (
  <Composition
    id="Redshift"
    component={Redshift}
    durationInFrames={1500}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={{ plan: EMPTY_PLAN, brandbook: {} as Brandbook }}
    calculateMetadata={({ props }) => {
      const plan = props.plan ?? EMPTY_PLAN;
      return {
        durationInFrames: Math.round(plan.duration_sec * plan.fps),
        fps: plan.fps,
        width: plan.resolution[0],
        height: plan.resolution[1],
      };
    }}
  />
);

registerRoot(Root);
