import { useEffect, useRef } from 'react';
import { showcaseEffectParams, type VideoEffectDefinition } from '../../config/videoEffects';
import { NunWebGpuEffects, thumbnailSample } from '../../effects/webgpuRuntime';

/** A cached WebGPU poster frame using the same shader runtime as Program Monitor. */
export function EffectThumbnail({ effect }: { effect: VideoEffectDefinition }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    void NunWebGpuEffects.create().then((runtime) => {
      const canvas = canvasRef.current;
      if (cancelled || !runtime || !canvas) return;
      runtime.render(thumbnailSample(), canvas, [{
        id: `thumbnail-${effect.id}`,
        kind: 'effect', name: effect.label, start: 0, duration: 1, sourceStart: 0,
        params: { effectId: effect.id, ...showcaseEffectParams(effect) },
      }], 1.25);
    });
    return () => { cancelled = true; };
  }, [effect]);
  return <canvas ref={canvasRef} className="effect-thumbnail-canvas" width="320" height="180" aria-hidden />;
}
