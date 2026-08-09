import type { CSSProperties } from 'react';
import { DEFAULT_TEXT_STYLE } from '../config/textStylePresets';
import { fontStack } from '../config/fontRegistry';
import type { TextStyle } from '../types/textStyle';

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, Number.isFinite(value) ? value : minimum));
}

function hexToRgba(color = '#000000', opacity = 1) {
  const match = color.trim().match(/^#?([0-9a-fA-F]{6})$/);
  if (!match) return color;
  const hex = match[1];
  const red = parseInt(hex.slice(0, 2), 16);
  const green = parseInt(hex.slice(2, 4), 16);
  const blue = parseInt(hex.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${clamp(opacity, 0, 1)})`;
}

function px(value: unknown, fallback = 0) {
  const number = Number(value ?? fallback);
  return Number.isFinite(number) ? number : fallback;
}

export function normalizeTextStyle(style?: TextStyle): TextStyle {
  const next = { ...DEFAULT_TEXT_STYLE, ...(style || {}) };
  const color = next.fontColor || next.color || DEFAULT_TEXT_STYLE.fontColor;
  const outline = next.outline ?? next.outlineWidth ?? DEFAULT_TEXT_STYLE.outline;
  const backgroundEnabled = next.backgroundEnabled ?? next.background ?? false;
  return {
    ...next,
    color,
    fontColor: color,
    outline,
    outlineWidth: outline,
    background: backgroundEnabled,
    backgroundEnabled,
  };
}

export function textStyleToCss(style?: TextStyle, options: { previewScale?: number } = {}): CSSProperties {
  const resolved = normalizeTextStyle(style);
  const scale = options.previewScale ?? 1;
  const outline = Math.max(0, px(resolved.outlineWidth ?? resolved.outline) * scale);
  const secondaryOutline = Math.max(0, px(resolved.secondaryOutlineWidth) * scale);
  const shadowX = px(resolved.shadowOffsetX) * scale;
  const shadowY = px(resolved.shadowOffsetY) * scale;
  const shadowBlur = Math.max(0, px(resolved.shadowBlur) * scale);
  const glowBlur = Math.max(0, px(resolved.glowBlur) * scale);
  const glowStrength = Math.max(0, px(resolved.glowStrength, 1));
  const shadows: string[] = [];

  if (secondaryOutline > 0 && resolved.secondaryOutlineColor) {
    shadows.push(`0 0 ${secondaryOutline}px ${resolved.secondaryOutlineColor}`);
  }
  if (shadowBlur > 0 || shadowX || shadowY) {
    shadows.push(`${shadowX}px ${shadowY}px ${shadowBlur}px ${resolved.shadowColor || '#000000'}`);
  }
  if (resolved.glowEnabled && glowBlur > 0) {
    const glow = resolved.glowColor || resolved.shadowColor || resolved.fontColor || '#ffffff';
    shadows.push(`0 0 ${glowBlur * 0.45}px ${glow}`, `0 0 ${glowBlur}px ${glow}`, `0 0 ${glowBlur * 1.8}px ${hexToRgba(glow, Math.min(1, 0.72 * glowStrength))}`);
  }

  return {
    color: resolved.fontColor,
    opacity: resolved.opacity ?? 1,
    fontFamily: fontStack(resolved.fontFamily),
    fontSize: resolved.fontSize ? `${resolved.fontSize * scale}px` : undefined,
    fontWeight: resolved.fontWeight || 800,
    fontStyle: resolved.fontStyle || 'normal',
    textDecoration: resolved.textDecoration || 'none',
    textTransform: resolved.textTransform || 'none',
    letterSpacing: resolved.letterSpacing ? `${resolved.letterSpacing * scale}px` : 0,
    lineHeight: resolved.lineHeight || 1.05,
    textAlign: resolved.textAlign || 'center',
    WebkitTextStroke: outline > 0 ? `${outline}px ${resolved.outlineColor || '#000000'}` : undefined,
    paintOrder: 'stroke fill',
    textShadow: shadows.length ? shadows.join(', ') : undefined,
    background: resolved.backgroundEnabled ? hexToRgba(resolved.backgroundColor || '#000000', resolved.backgroundOpacity ?? 0.55) : 'transparent',
    borderRadius: resolved.backgroundEnabled ? `${px(resolved.backgroundRadius, 4) * scale}px` : undefined,
    padding: resolved.backgroundEnabled
      ? `${px(resolved.backgroundPaddingY, 3) * scale}px ${px(resolved.backgroundPaddingX, 8) * scale}px`
      : undefined,
  };
}
