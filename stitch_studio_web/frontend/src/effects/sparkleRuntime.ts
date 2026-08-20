import { createScene } from '@basmilius/sparkle';
import { effectDefinitionForItem, sparkleConfig } from '../config/sparkleEffects';
import type { TimelineItem } from '../types/studio';

/** Builds one native Sparkle Scene so overlapping FX clips become ordered canvas layers. */
export function mountSparkleScene(canvas: HTMLCanvasElement, effects: TimelineItem[], frameRate = 30) {
  const scene = createScene(frameRate).mount(canvas);
  const triggered: Array<{ burst?: (config: Record<string, unknown>) => void }> = [];
  for (const item of effects) {
    const definition = effectDefinitionForItem(item);
    if (!definition) continue;
    const layer = definition.factory(sparkleConfig(definition, item.params || {}));
    scene.layer(layer);
    if (definition.trigger === 'burst') triggered.push(layer as { burst?: (config: Record<string, unknown>) => void });
  }
  scene.start();
  // Sparkle's confetti needs the scene dimensions initialized by the runner.
  const timer = window.setTimeout(() => triggered.forEach((layer) => layer.burst?.({ particles: 140, spread: 90 })), 120);
  return { scene, destroy: () => { window.clearTimeout(timer); scene.destroy(); } };
}
