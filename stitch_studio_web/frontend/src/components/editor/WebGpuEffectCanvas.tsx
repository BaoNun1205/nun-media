import { useEffect, useRef } from 'react';
import type { TimelineItem } from '../../types/studio';
import { NunWebGpuEffects } from '../../effects/webgpuRuntime';

/** Renders the active timeline effect stack with Nun Media's WebGPU runtime. */
export function WebGpuEffectCanvas({
  effects,
  time,
  getSource,
  fitMode,
}: {
  effects: TimelineItem[];
  time: number;
  getSource: () => HTMLVideoElement | HTMLImageElement | null;
  fitMode: 'contain' | 'cover';
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeRef = useRef<NunWebGpuEffects | null>(null);
  const aliveRef = useRef(true);
  const timeRef = useRef(time);
  const effectsRef = useRef(effects);
  const getSourceRef = useRef(getSource);
  timeRef.current = time;
  effectsRef.current = effects;
  getSourceRef.current = getSource;
  const effectKey = effects.map((effect) => `${effect.id}:${JSON.stringify(effect.params)}`).join('|');

  useEffect(() => {
    aliveRef.current = true;
    let frame = 0;
    let lastFallbackDraw = 0;
    void NunWebGpuEffects.create().then((runtime) => {
      if (!runtime || !aliveRef.current) return;
      runtimeRef.current = runtime;
      const draw = () => {
        const source = getSourceRef.current();
        const canvas = canvasRef.current;
        // Pixel fallback is intentionally capped to 15 fps; WebGPU continues
        // at the browser's animation cadence.
        const now = performance.now();
        if (source && canvas && (!runtime.isFallback || now - lastFallbackDraw >= 66)) {
          runtime.render(source, canvas, effectsRef.current, timeRef.current);
          lastFallbackDraw = now;
        }
        frame = requestAnimationFrame(draw);
      };
      draw();
    });
    return () => { aliveRef.current = false; cancelAnimationFrame(frame); };
  }, [effectKey]);

  if (!effects.length) return null;
  return <canvas ref={canvasRef} className="preview-webgpu-effects" style={{ objectFit: fitMode }} aria-label="WebGPU effect preview" />;
}
