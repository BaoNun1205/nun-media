import {
  createAurora, createBubbles, createClouds, createConfetti, createDigitalRain,
  createFireflies, createFireworks, createGlitch, createHologram, createKaleidoscope,
  createLanterns, createLeaves, createLightning, createNeon, createPetals, createPlasma,
  createPollen, createRain, createSandstorm, createSmoke, createSnow, createStars,
  type Effect,
} from '@basmilius/sparkle';
import type { TimelineItem } from '../types/studio';

export const SPARKLE_EFFECT_CATEGORIES = ['Trending', 'Weather', 'Nature', 'Atmosphere', 'Light', 'Party', 'Abstract', 'Distortion'] as const;
export type SparkleEffectCategory = typeof SPARKLE_EFFECT_CATEGORIES[number];

export type SparkleEffectParameter = {
  key: string;
  configKey?: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
};

type SparkleFactory = (config: Record<string, unknown>) => Effect<Record<string, unknown>>;

export type SparkleEffectDefinition = {
  id: string;
  label: string;
  category: SparkleEffectCategory;
  description: string;
  factory: SparkleFactory;
  params: SparkleEffectParameter[];
  trigger?: 'burst';
};

const factory = (value: unknown) => value as SparkleFactory;
const number = (key: string, label: string, defaultValue: number, min: number, max: number, step: number, configKey?: string): SparkleEffectParameter => ({ key, configKey, label, default: defaultValue, min, max, step });

/**
 * The only visual-effect registry in Nun Media. Factories and inspector
 * parameters map directly to Sparkle's public configuration options.
 */
export const SPARKLE_EFFECTS: SparkleEffectDefinition[] = [
  { id: 'snow', label: 'Snow', category: 'Weather', description: 'Falling snow simulation', factory: factory(createSnow), params: [number('particles', 'Particles', 160, 20, 500, 10), number('speed', 'Speed', 1.2, .1, 4, .1), number('size', 'Size', 2, .5, 8, .1)] },
  { id: 'rain', label: 'Rain', category: 'Weather', description: 'Wind-driven rainfall', factory: factory(createRain), params: [number('drops', 'Drops', 180, 20, 500, 10), number('speed', 'Speed', 1.1, .1, 4, .1), number('wind', 'Wind', .2, -2, 2, .1)] },
  { id: 'lightning', label: 'Lightning', category: 'Weather', description: 'Branching lightning flashes', factory: factory(createLightning), params: [number('frequency', 'Frequency', .8, .1, 4, .1), number('scale', 'Scale', 1, .5, 3, .1)] },
  { id: 'sandstorm', label: 'Sandstorm', category: 'Weather', description: 'Wind and dusty haze', factory: factory(createSandstorm), params: [number('count', 'Particles', 180, 20, 500, 10), number('wind', 'Wind', 1, .1, 4, .1), number('turbulence', 'Turbulence', .5, 0, 2, .1)] },
  { id: 'leaves', label: 'Leaves', category: 'Nature', description: 'Drifting autumn leaves', factory: factory(createLeaves), params: [number('count', 'Count', 45, 5, 180, 5), number('speed', 'Speed', 1, .1, 4, .1), number('wind', 'Wind', .6, -2, 2, .1)] },
  { id: 'petals', label: 'Petals', category: 'Nature', description: 'Floating flower petals', factory: factory(createPetals), params: [number('count', 'Count', 55, 5, 200, 5), number('speed', 'Speed', .9, .1, 4, .1), number('wind', 'Wind', .5, -2, 2, .1)] },
  { id: 'pollen', label: 'Pollen', category: 'Nature', description: 'Glowing airborne pollen', factory: factory(createPollen), params: [number('count', 'Count', 90, 10, 300, 10), number('speed', 'Speed', .7, .1, 4, .1), number('size', 'Size', 2, .5, 8, .1)] },
  { id: 'fireflies', label: 'Fireflies', category: 'Nature', description: 'Warm wandering fireflies', factory: factory(createFireflies), params: [number('count', 'Count', 50, 5, 200, 5), number('speed', 'Speed', .8, .1, 4, .1), number('size', 'Size', 2, .5, 8, .1)] },
  { id: 'bubbles', label: 'Bubbles', category: 'Nature', description: 'Wobbling translucent bubbles', factory: factory(createBubbles), params: [number('count', 'Count', 35, 5, 160, 5), number('speed', 'Speed', .8, .1, 4, .1), number('wobbleAmount', 'Wobble', 1, 0, 4, .1)] },
  { id: 'smoke', label: 'Smoke', category: 'Atmosphere', description: 'Slow rolling smoke', factory: factory(createSmoke), params: [number('count', 'Particles', 28, 4, 100, 2), number('speed', 'Speed', .7, .1, 3, .1), number('spread', 'Spread', .6, .1, 2, .1)] },
  { id: 'clouds', label: 'Clouds', category: 'Atmosphere', description: 'Passing atmospheric clouds', factory: factory(createClouds), params: [number('count', 'Count', 8, 1, 30, 1), number('speed', 'Speed', .35, .05, 2, .05), number('opacity', 'Opacity', .5, .05, 1, .05)] },
  { id: 'aurora', label: 'Aurora', category: 'Atmosphere', description: 'Northern-light bands', factory: factory(createAurora), params: [number('bands', 'Bands', 4, 1, 10, 1), number('speed', 'Speed', .6, .05, 3, .05), number('intensity', 'Intensity', .8, .1, 2, .05)] },
  { id: 'stars', label: 'Stars', category: 'Atmosphere', description: 'Twinkling sky stars', factory: factory(createStars), params: [number('count', 'Count', 100, 10, 400, 10, 'starCount'), number('twinkleSpeed', 'Twinkle', .5, .05, 3, .05), number('scale', 'Scale', 1, .2, 3, .1)] },
  { id: 'lanterns', label: 'Lanterns', category: 'Light', description: 'Floating paper lanterns', factory: factory(createLanterns), params: [number('count', 'Count', 18, 2, 80, 2), number('speed', 'Speed', .7, .1, 3, .1), number('size', 'Size', 1, .4, 3, .1)] },
  { id: 'neon', label: 'Neon', category: 'Light', description: 'Animated neon glow', factory: factory(createNeon), params: [number('count', 'Count', 18, 2, 80, 2), number('speed', 'Speed', 1, .1, 4, .1), number('scale', 'Scale', 1, .4, 3, .1)] },
  { id: 'fireworks', label: 'Fireworks', category: 'Party', description: 'Automatic colourful fireworks', factory: factory(createFireworks), params: [number('scale', 'Scale', 1, .4, 3, .1)] },
  { id: 'confetti', label: 'Confetti', category: 'Party', description: 'Celebration confetti burst', factory: factory(createConfetti), params: [number('scale', 'Scale', 1, .4, 3, .1)], trigger: 'burst' },
  { id: 'glitch', label: 'Glitch', category: 'Distortion', description: 'RGB slices and digital noise', factory: factory(createGlitch), params: [number('intensity', 'Intensity', .5, .05, 2, .05), number('speed', 'Speed', 1, .1, 4, .1), number('rgbSplit', 'RGB Split', 4, 0, 20, 1)] },
  { id: 'hologram', label: 'Hologram', category: 'Distortion', description: 'Scanning holographic fragments', factory: factory(createHologram), params: [number('speed', 'Speed', 1, .1, 4, .1), number('scanlineSpacing', 'Scanlines', 4, 1, 16, 1), number('flickerIntensity', 'Flicker', .5, 0, 2, .05)] },
  { id: 'kaleidoscope', label: 'Kaleidoscope', category: 'Abstract', description: 'Colourful mirrored geometry', factory: factory(createKaleidoscope), params: [number('segments', 'Segments', 6, 2, 16, 1), number('speed', 'Speed', 1, .1, 4, .1), number('shapes', 'Shapes', 24, 4, 100, 2)] },
  { id: 'plasma', label: 'Plasma', category: 'Abstract', description: 'Flowing plasma field', factory: factory(createPlasma), params: [number('speed', 'Speed', 1, .1, 4, .1), number('scale', 'Scale', 1, .3, 3, .1)] },
  { id: 'digital_rain', label: 'Digital Rain', category: 'Abstract', description: 'Falling digital glyphs', factory: factory(createDigitalRain), params: [number('speed', 'Speed', 1, .1, 4, .1), number('columns', 'Columns', 40, 8, 120, 2), number('fontSize', 'Font Size', 16, 8, 40, 1)] },
];

export const SPARKLE_EFFECT_BY_ID = new Map(SPARKLE_EFFECTS.map((effect) => [effect.id, effect]));

export function effectIdForItem(item?: TimelineItem) { return String(item?.params?.effectId || '').toLowerCase(); }
export function effectDefinitionForItem(item?: TimelineItem) { return SPARKLE_EFFECT_BY_ID.get(effectIdForItem(item)); }
export function defaultEffectParams(effect: SparkleEffectDefinition) { return Object.fromEntries(effect.params.map((parameter) => [parameter.key, parameter.default])); }
export function showcaseEffectParams(effect: SparkleEffectDefinition) { return Object.fromEntries(effect.params.map((parameter) => [parameter.key, Math.max(parameter.min, Math.min(parameter.max, parameter.default + (parameter.max - parameter.default) * .25))])); }
export function clampEffectParam(effect: SparkleEffectDefinition, key: string, value: unknown) { const parameter = effect.params.find((item) => item.key === key); if (!parameter) return value; const numberValue = Number(value); return Math.max(parameter.min, Math.min(parameter.max, Number.isFinite(numberValue) ? numberValue : parameter.default)); }
export function activeSparkleEffects(items: TimelineItem[], time: number) { return items.filter((item) => item.kind === 'effect' && !item.hidden && time >= item.start && time < item.start + item.duration && effectDefinitionForItem(item)); }
export function sparkleConfig(effect: SparkleEffectDefinition, params: Record<string, unknown>) { return Object.fromEntries(effect.params.map((parameter) => [parameter.configKey || parameter.key, clampEffectParam(effect, parameter.key, params[parameter.key])])) as Record<string, unknown>; }
