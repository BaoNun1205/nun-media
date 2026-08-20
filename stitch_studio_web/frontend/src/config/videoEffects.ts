import rawEffects from './videoEffects.json';
import type { TimelineItem } from '../types/studio';

export type VideoEffectParameter = {
  key: string;
  label: string;
  type: 'number';
  default: number;
  min: number;
  max: number;
  step: number;
};

export type VideoEffectDefinition = {
  id: string;
  label: string;
  category: VideoEffectCategory;
  gpuKind: number;
  description: string;
  params: VideoEffectParameter[];
};

export const VIDEO_EFFECT_CATEGORIES = ['Trending', 'Basic', 'Film', 'Retro', 'Glitch', 'Distortion', 'Lens', 'Light', 'Color'] as const;
export type VideoEffectCategory = typeof VIDEO_EFFECT_CATEGORIES[number];

export const VIDEO_EFFECTS = rawEffects as VideoEffectDefinition[];
export const VIDEO_EFFECT_BY_ID = new Map(VIDEO_EFFECTS.map((effect) => [effect.id, effect]));

export function effectIdForItem(item?: TimelineItem) {
  return String(item?.params?.effectId || item?.params?.id || '').toLowerCase();
}

export function effectDefinitionForItem(item?: TimelineItem) {
  return VIDEO_EFFECT_BY_ID.get(effectIdForItem(item));
}

export function defaultEffectParams(effect: VideoEffectDefinition) {
  return Object.fromEntries(effect.params.map((parameter) => [parameter.key, parameter.default]));
}

/** Strong but bounded values for thumbnail cards, adapted from FreeCut's effect-preview strategy. */
export function showcaseEffectParams(effect: VideoEffectDefinition) {
  return Object.fromEntries(effect.params.map((parameter) => {
    const base = parameter.default;
    const value = base === parameter.min
      ? parameter.min + (parameter.max - parameter.min) * .55
      : Math.max(parameter.min, Math.min(parameter.max, base + (parameter.max - base) * .4));
    return [parameter.key, value];
  }));
}

export function clampEffectParam(effect: VideoEffectDefinition, key: string, value: unknown) {
  const parameter = effect.params.find((item) => item.key === key);
  if (!parameter) return value;
  const number = Number(value);
  const normalized = Number.isFinite(number) ? number : parameter.default;
  return Math.max(parameter.min, Math.min(parameter.max, normalized));
}

export function activeVideoEffects(items: TimelineItem[], time: number) {
  return items.filter((item) => item.kind === 'effect' && !item.hidden && time >= item.start && time < item.start + item.duration && effectDefinitionForItem(item));
}
