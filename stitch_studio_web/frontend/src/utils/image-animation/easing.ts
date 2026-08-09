import type { EasingType } from './types';

// Standard Penner easing functions
export function linear(t: number): number {
  return t;
}

export function easeInSine(t: number): number {
  return 1 - Math.cos((t * Math.PI) / 2);
}

export function easeOutSine(t: number): number {
  return Math.sin((t * Math.PI) / 2);
}

export function easeInOutSine(t: number): number {
  return -(Math.cos(Math.PI * t) - 1) / 2;
}

export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

export function easeOutBack(t: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

export function applyEasing(t: number, easing: EasingType = 'linear'): number {
  // Clamp t to [0, 1] for safety
  const clampedT = Math.max(0, Math.min(1, t));
  
  switch (easing) {
    case 'linear': return linear(clampedT);
    case 'easeInSine': return easeInSine(clampedT);
    case 'easeOutSine': return easeOutSine(clampedT);
    case 'easeInOutSine': return easeInOutSine(clampedT);
    case 'easeOutCubic': return easeOutCubic(clampedT);
    case 'easeOutBack': return easeOutBack(clampedT);
    default: return linear(clampedT);
  }
}
