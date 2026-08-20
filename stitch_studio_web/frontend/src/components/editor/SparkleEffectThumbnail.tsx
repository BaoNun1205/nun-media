import { useEffect, useRef } from 'react';
import { showcaseEffectParams, type SparkleEffectDefinition } from '../../config/sparkleEffects';
import { mountSparkleScene } from '../../effects/sparkleRuntime';

/** A real Sparkle animation composited over the shared library demo image. */
export function SparkleEffectThumbnail({ effect }: { effect: SparkleEffectDefinition }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const runtime = mountSparkleScene(canvas, [{ id: `thumb:${effect.id}`, kind: 'effect', name: effect.label, track: 'FX1', start: 0, duration: 1, sourceStart: 0, params: { effectId: effect.id, ...showcaseEffectParams(effect) } }], 20);
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) runtime.scene.start();
      else runtime.scene.pause();
    }, { threshold: .05 });
    observer.observe(canvas);
    return () => { observer.disconnect(); runtime.destroy(); };
  }, [effect]);
  return <>
    <img className="effect-thumbnail-demo" src="/assets/sparkle-effect-demo.png" alt="" />
    <canvas ref={canvasRef} className="effect-thumbnail-canvas" width="320" height="180" aria-hidden />
  </>;
}
