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
  description: string;
  params: VideoEffectParameter[];
};

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

/** A deliberately lightweight browser approximation; the renderer remains FFmpeg-native. */
export function previewFilterForEffects(effects: TimelineItem[]) {
  let brightness = 1;
  let contrast = 1;
  let saturate = 1;
  let blur = 0;
  for (const item of effects) {
    const id = effectIdForItem(item);
    const intensity = Number(item.params?.intensity ?? item.params?.amount ?? 0.3);
    if (id === 'vhs' || id === 'glitch') { contrast += intensity * .12; saturate += intensity * .12; }
    if (id === 'dust') { brightness += intensity * .05; saturate -= intensity * .12; }
    if (id === 'glow') { brightness += intensity * .09; blur += Number(item.params?.radius ?? .3) * intensity * .25; }
  }
  return `brightness(${brightness}) contrast(${contrast}) saturate(${Math.max(.1, saturate)})${blur ? ` blur(${blur}px)` : ''}`;
}
