export interface ImageAnimationConfig {
  in?: { presetId: string | null; duration: number };
  out?: { presetId: string | null; duration: number };
  combo?: {
    presetId: string | null;
    timing?: 'fit' | 'loop';
    cycleSeconds?: number;
    intensity?: number;
    loopMode?: 'repeat' | 'pingPong';
  };
}

export interface AnimationDelta {
  translateX: number; // Percentage relative to width
  translateY: number; // Percentage relative to height
  scale: number;      // Multiplier (1.0 = base scale)
  rotation: number;   // Degrees offset
  opacity: number;    // Multiplier (1.0 = base opacity)
  blur: number;       // Blur radius delta
}

export type EasingType = 'linear' | 'easeInSine' | 'easeOutSine' | 'easeInOutSine' | 'easeOutCubic' | 'easeOutBack';

export interface KeyframePoint {
  t: number; // Normalized time 0.0 to 1.0
  v: number; // Value at time t
}

export interface AnimationChannelSpec {
  type: 'keyframes';
  easing?: EasingType; // Default is linear if not specified
  points: [number, number][]; // [t, v] arrays for compactness
}

export interface ImageAnimationPresetSpec {
  id: string;
  group: 'in' | 'out' | 'combo';
  safeScale?: number; // Overscan multiplier to avoid black edges (e.g., 1.15 for Pan)
  channels: {
    scale?: AnimationChannelSpec;
    translateX?: AnimationChannelSpec;
    translateY?: AnimationChannelSpec;
    rotation?: AnimationChannelSpec;
    opacity?: AnimationChannelSpec;
    blur?: AnimationChannelSpec;
  };
}
