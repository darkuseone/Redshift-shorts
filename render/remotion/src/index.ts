import { Composition, registerRoot } from "remotion";
import React from "react";
import { Redshift } from "./Redshift";
import type { Brandbook, EditPlan } from "./types";

/**
 * Точка входа Remotion. План и брендбук приходят через входные пропсы, чтобы
 * один и тот же проект рендерил любую версию любого ролика:
 *
 *   npx remotion render src/index.ts Redshift out/A.mp4 \
 *     --props=../../output/redshift_0042/edit_plan_A.json
 */
const Root: React.FC = () => {
  return React.createElement(Composition, {
    id: "Redshift",
    component: Redshift as never,
    durationInFrames: 1500,
    fps: 30,
    width: 1080,
    height: 1920,
    defaultProps: {
      plan: {} as EditPlan,
      brandbook: {} as Brandbook,
    },
    calculateMetadata: ({ props }: { props: { plan: EditPlan } }) => ({
      durationInFrames: Math.round((props.plan?.duration_sec ?? 50) * (props.plan?.fps ?? 30)),
      fps: props.plan?.fps ?? 30,
      width: props.plan?.resolution?.[0] ?? 1080,
      height: props.plan?.resolution?.[1] ?? 1920,
    }),
  });
};

registerRoot(Root);
