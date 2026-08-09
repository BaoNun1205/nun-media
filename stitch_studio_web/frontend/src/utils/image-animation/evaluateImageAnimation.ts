import type { TimelineItem } from '../../types/studio';
import { getPresetSpec, getDefaultAnimationDelta } from './presets';
import { applyEasing } from './easing';
import type { AnimationDelta, ImageAnimationPresetSpec, AnimationChannelSpec, ImageAnimationConfig } from './types';

// The base transform representation (what user edits directly via drag/sliders)
export interface BaseImageTransform {
  scale: number;
  x: number; // Percentage (0.0 to 1.0)
  y: number; // Percentage (0.0 to 1.0)
}

// The final composed transform that includes both base and animations
export interface ComposedImageTransform extends BaseImageTransform {
  rotation: number;
  opacity: number;
  blur: number;
}

/**
 * Interpolates a value on an AnimationChannelSpec given progress t [0..1]
 */
function evaluateChannel(channel: AnimationChannelSpec, t: number): number {
  const points = channel.points;
  if (!points || points.length === 0) return 0;
  if (points.length === 1) return points[0][1];

  // Apply easing to the progress t
  const easedT = applyEasing(t, channel.easing);

  // Find the segment containing easedT
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];

    if (easedT >= p1[0] && easedT <= p2[0]) {
      // Linear interpolation between the two points
      const segmentDelta = p2[0] - p1[0];
      if (segmentDelta === 0) return p2[1];
      
      const segmentProgress = (easedT - p1[0]) / segmentDelta;
      return p1[1] + (p2[1] - p1[1]) * segmentProgress;
    }
  }

  // Fallback to limits
  if (easedT <= points[0][0]) return points[0][1];
  return points[points.length - 1][1];
}

/**
 * Evaluates a single preset at progress t (0.0 to 1.0) and applies it to the delta.
 */
function applyPresetToDelta(spec: ImageAnimationPresetSpec, t: number, delta: AnimationDelta) {
  const c = spec.channels;
  if (c.scale) delta.scale *= evaluateChannel(c.scale, t);
  if (c.translateX) delta.translateX += evaluateChannel(c.translateX, t);
  if (c.translateY) delta.translateY += evaluateChannel(c.translateY, t);
  if (c.rotation) delta.rotation += evaluateChannel(c.rotation, t);
  if (c.opacity) delta.opacity *= evaluateChannel(c.opacity, t);
  if (c.blur) {
    const b = evaluateChannel(c.blur, t);
    if (b > delta.blur) delta.blur = b; // Max semantic for blur
  }
}

/**
 * Computes the AnimationDelta based on current clip timing and user configuration.
 */
export function evaluateImageAnimation(item: TimelineItem, localTime: number): AnimationDelta {
  const delta = getDefaultAnimationDelta();
  const config = item.params?.imageAnimation as ImageAnimationConfig | undefined;
  
  if (!config) return delta;

  const inSpec = getPresetSpec(config.in?.presetId, 'in');
  const outSpec = getPresetSpec(config.out?.presetId, 'out');
  const comboSpec = getPresetSpec(config.combo?.presetId, 'combo');

  const duration = Math.max(0.01, item.duration);
  const timeInClip = Math.max(0, localTime);

  // Combine safeScale if Pan/KenBurns/Rotate requires it
  let comboSafeScale = 1.0;
  
  // 1. Evaluate Combo
  if (comboSpec) {
    const progress = Math.max(0, Math.min(1, timeInClip / duration));
    applyPresetToDelta(comboSpec, progress, delta);
    if (comboSpec.safeScale) {
      comboSafeScale = Math.max(comboSafeScale, comboSpec.safeScale);
    }
  }

  // 2. Evaluate IN
  if (inSpec) {
    const inDur = Math.min(config.in?.duration || 0.5, duration);
    if (inDur > 0) {
      if (timeInClip <= inDur) {
        const progress = Math.max(0, Math.min(1, timeInClip / inDur));
        applyPresetToDelta(inSpec, progress, delta);
      } else {
        // Animation finished, apply final state (t=1.0)
        applyPresetToDelta(inSpec, 1.0, delta);
      }
      if (inSpec.safeScale) {
        comboSafeScale = Math.max(comboSafeScale, inSpec.safeScale);
      }
    }
  }

  // 3. Evaluate OUT
  if (outSpec) {
    const inDur = Math.min(config.in?.duration || 0, duration);
    const maxOutDur = Math.max(0, duration - inDur); // Clamp to avoid overlap
    const outDur = Math.min(config.out?.duration || 0.5, maxOutDur);
    
    if (outDur > 0) {
      const outStart = duration - outDur;
      if (timeInClip >= outStart) {
        const progress = Math.max(0, Math.min(1, (timeInClip - outStart) / outDur));
        applyPresetToDelta(outSpec, progress, delta);
      } else {
        // Animation not started, apply initial state (t=0.0)
        applyPresetToDelta(outSpec, 0.0, delta);
      }
      if (outSpec.safeScale) {
        comboSafeScale = Math.max(comboSafeScale, outSpec.safeScale);
      }
    }
  }

  delta.scale *= comboSafeScale;

  return delta;
}

/**
 * Composes the base user transform with the evaluated animation delta.
 */
export function composeImageTransform(base: BaseImageTransform, delta: AnimationDelta): ComposedImageTransform {
  return {
    // Translate is relative to the width/height (100% = 1.0), but in CSS we translate % of the element size.
    // However, in our system x, y is the base center. The delta is added to the base position.
    // delta.translateX is usually -100 to 100 representing %. We divide by 100 for normalization.
    x: base.x + (delta.translateX / 100),
    y: base.y + (delta.translateY / 100),
    scale: base.scale * delta.scale,
    rotation: delta.rotation,
    opacity: delta.opacity,
    blur: delta.blur,
  };
}
