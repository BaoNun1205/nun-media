import type { TextStyle, TextStylePreset } from '../types/textStyle';
import { DEFAULT_FONT_FAMILY } from './fontRegistry';

export const DEFAULT_TEXT_STYLE: TextStyle = {
  fontFamily: DEFAULT_FONT_FAMILY,
  fontSize: 50,
  fontColor: '#ffffff',
  color: '#ffffff',
  fontWeight: 800,
  fontStyle: 'normal',
  textDecoration: 'none',
  textTransform: 'none',
  outlineColor: '#000000',
  outline: 2,
  outlineWidth: 2,
  shadowColor: '#000000',
  shadowOffsetX: 0,
  shadowOffsetY: 0,
  shadowBlur: 0,
  background: false,
  backgroundEnabled: false,
  backgroundColor: '#000000',
  backgroundOpacity: 0.55,
  backgroundRadius: 4,
  backgroundPaddingX: 8,
  backgroundPaddingY: 3,
  glowEnabled: false,
  glowColor: '#ffffff',
  glowBlur: 0,
  glowStrength: 0,
  letterSpacing: 0,
  lineHeight: 1.05,
  textAlign: 'center',
  verticalAlign: 'bottom',
  opacity: 1,
  staticEffect: 'none',
};

const base = (style: TextStyle): TextStyle => ({
  ...DEFAULT_TEXT_STYLE,
  ...style,
  color: style.color || style.fontColor || DEFAULT_TEXT_STYLE.fontColor,
  fontColor: style.fontColor || style.color || DEFAULT_TEXT_STYLE.fontColor,
  outline: style.outline ?? style.outlineWidth ?? DEFAULT_TEXT_STYLE.outline,
  outlineWidth: style.outlineWidth ?? style.outline ?? DEFAULT_TEXT_STYLE.outline,
});

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const previewStyleFor = (style: TextStyle): TextStyle => {
  const real = base(style);
  const outline = clamp(Number(real.outline ?? real.outlineWidth ?? 0), 0, real.backgroundEnabled ? 1.25 : 3.6);
  return {
    ...real,
    fontSize: 21,
    lineHeight: 1,
    outline,
    outlineWidth: outline,
    secondaryOutlineWidth: real.secondaryOutlineWidth ? clamp(Number(real.secondaryOutlineWidth), 0, 1.8) : 0,
    shadowOffsetX: clamp(Number(real.shadowOffsetX ?? 0), -2.2, 2.2),
    shadowOffsetY: clamp(Number(real.shadowOffsetY ?? 0), -1.8, 2.4),
    shadowBlur: clamp(Number(real.shadowBlur ?? 0), 0, 5),
    glowBlur: clamp(Number(real.glowBlur ?? 0), 0, 7),
    glowStrength: clamp(Number(real.glowStrength ?? 1), 0, 1),
    backgroundRadius: clamp(Number(real.backgroundRadius ?? 6), 5, 8),
    backgroundPaddingX: clamp(Number(real.backgroundPaddingX ?? 8), 7, 10),
    backgroundPaddingY: clamp(Number(real.backgroundPaddingY ?? 3), 3, 5),
    letterSpacing: clamp(Number(real.letterSpacing ?? 0), -0.5, 0.8),
  };
};

const preset = (id: string, name: string, style: TextStyle): TextStylePreset => ({
  id,
  name,
  previewText: 'Aa',
  style: base(style),
  previewStyle: previewStyleFor(style),
});

export const TEXT_STYLE_PRESETS: TextStylePreset[] = [
  preset('white-black-outline', 'White / Black Outline', { fontColor: '#ffffff', outlineColor: '#000000', outline: 7, fontWeight: 900 }),
  preset('black-white-outline', 'Black / White Outline', { fontColor: '#080808', outlineColor: '#ffffff', outline: 6, fontWeight: 900 }),
  preset('white-double-dark-outline', 'White / Double Dark Outline', { fontColor: '#ffffff', outlineColor: '#000000', outline: 6, secondaryOutlineColor: '#ffffff', secondaryOutlineWidth: 1.5, fontWeight: 900 }),
  preset('white-soft-black-shadow', 'White / Soft Black Shadow', { fontColor: '#ffffff', outlineColor: '#000000', outline: 3, shadowColor: '#000000', shadowOffsetX: 2, shadowOffsetY: 3, shadowBlur: 3, fontWeight: 900 }),
  preset('white-heavy-black-shadow', 'White / Heavy Black Shadow', { fontColor: '#ffffff', outlineColor: '#000000', outline: 4, shadowColor: '#000000', shadowOffsetX: 4, shadowOffsetY: 5, shadowBlur: 5, fontWeight: 900 }),
  preset('yellow-black-outline', 'Yellow / Black Outline', { fontColor: '#fff000', outlineColor: '#000000', outline: 7, fontWeight: 900 }),
  preset('red-white-outline', 'Red / White Outline', { fontColor: '#ff3338', outlineColor: '#ffffff', outline: 6, shadowColor: '#171717', shadowOffsetX: 1, shadowOffsetY: 1, shadowBlur: 1, fontWeight: 900 }),
  preset('orange-white-outline', 'Orange / White Outline', { fontColor: '#ff7a18', outlineColor: '#ffffff', outline: 6, fontWeight: 900 }),
  preset('blue-white-outline', 'Blue / White Outline', { fontColor: '#168fff', outlineColor: '#ffffff', outline: 6, fontWeight: 900 }),
  preset('green-black-outline', 'Green / Black Outline', { fontColor: '#00f53a', outlineColor: '#000000', outline: 7, fontWeight: 900 }),
  preset('black-light-gray-bg', 'Black / Light Gray Background', { fontColor: '#050505', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#cfcfcf', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('white-gray-bg', 'White / Gray Background', { fontColor: '#ffffff', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#9c9c9c', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('black-yellow-bg', 'Black / Yellow Background', { fontColor: '#000000', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#ffd900', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('white-purple-bg', 'White / Purple Background', { fontColor: '#ffffff', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#8c00ff', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('purple-white-bg', 'Purple / White Background', { fontColor: '#8c20ff', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#ffffff', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('black-white-bg', 'Black / White Background', { fontColor: '#000000', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#ffffff', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('white-black-bg', 'White / Black Background', { fontColor: '#ffffff', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#000000', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('green-black-bg', 'Green / Black Background', { fontColor: '#00f53a', outline: 0, background: true, backgroundEnabled: true, backgroundColor: '#000000', backgroundOpacity: 1, backgroundRadius: 7, backgroundPaddingX: 9, backgroundPaddingY: 4, fontWeight: 900 }),
  preset('green-glitch', 'Green Glitch', { fontColor: '#00ff48', outlineColor: '#020202', outline: 2, shadowColor: '#111111', shadowOffsetX: 2, shadowOffsetY: 2, shadowBlur: 0, staticEffect: 'glitch', secondaryOutlineColor: '#ff1f7a', secondaryOutlineWidth: 2, fontWeight: 900 }),
  preset('orange-red-duotone', 'Orange / Red Duotone', { fontColor: '#ffd21a', outlineColor: '#e02a34', outline: 2, shadowColor: '#e02a34', shadowOffsetX: 4, shadowOffsetY: 2, shadowBlur: 0, staticEffect: 'duotone', secondaryOutlineColor: '#e02a34', secondaryOutlineWidth: 3, fontWeight: 900 }),
  preset('pink-red-glow', 'Pink / Red Glow', { fontColor: '#ffffff', outlineColor: '#ff2d6f', outline: 1, glowEnabled: true, glowColor: '#ff1f67', glowBlur: 10, glowStrength: 1.15, shadowColor: '#ff1f67', shadowBlur: 8, fontWeight: 900 }),
  preset('yellow-glow', 'Yellow Glow', { fontColor: '#fff9c8', outlineColor: '#ffe600', outline: 1, glowEnabled: true, glowColor: '#ffe600', glowBlur: 11, glowStrength: 1.2, shadowColor: '#ffe600', shadowBlur: 8, fontWeight: 900 }),
  preset('green-glow', 'Green Glow', { fontColor: '#efffff', outlineColor: '#35ff4d', outline: 1, glowEnabled: true, glowColor: '#35ff4d', glowBlur: 11, glowStrength: 1.2, shadowColor: '#35ff4d', shadowBlur: 8, fontWeight: 900 }),
  preset('cyan-blue-glow', 'Cyan / Blue Glow', { fontColor: '#effcff', outlineColor: '#17dcff', outline: 1, glowEnabled: true, glowColor: '#17cfff', glowBlur: 11, glowStrength: 1.2, shadowColor: '#178bff', shadowBlur: 8, fontWeight: 900 }),
];

export function textStylePresetById(id?: string) {
  return TEXT_STYLE_PRESETS.find((preset) => preset.id === id);
}
