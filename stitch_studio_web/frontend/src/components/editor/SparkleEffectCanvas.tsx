import { useEffect, useRef } from 'react';
import { mountSparkleScene } from '../../effects/sparkleRuntime';
import type { TimelineItem } from '../../types/studio';

/** Transparent Sparkle canvas composited above the Program Monitor media. */
export function SparkleEffectCanvas({ effects }: { effects: TimelineItem[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const effectKey = effects.map((effect) => `${effect.id}:${JSON.stringify(effect.params)}`).join('|');
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !effects.length) return;
    const runtime = mountSparkleScene(canvas, effects);
    return () => runtime.destroy();
  }, [effectKey]);
  if (!effects.length) return null;
  return <canvas ref={canvasRef} className="preview-sparkle-effects" aria-label="Sparkle effect preview" />;
}
