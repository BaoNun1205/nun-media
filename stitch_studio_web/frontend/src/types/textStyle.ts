export type StaticTextEffect = 'none' | 'glitch' | 'duotone';

export interface TextStyle {
  presetId?: string;
  presetModified?: boolean;
  fontFamily?: string;
  fontSize?: number;
  color?: string;
  fontColor?: string;
  fontWeight?: number | string;
  fontStyle?: string;
  textDecoration?: 'none' | 'underline';
  textTransform?: 'none' | 'uppercase' | 'lowercase' | 'capitalize';
  outlineColor?: string;
  outlineWidth?: number;
  outline?: number;
  shadowColor?: string;
  shadowOffsetX?: number;
  shadowOffsetY?: number;
  shadowBlur?: number;
  backgroundEnabled?: boolean;
  background?: boolean;
  backgroundColor?: string;
  backgroundOpacity?: number;
  backgroundRadius?: number;
  backgroundPaddingX?: number;
  backgroundPaddingY?: number;
  glowEnabled?: boolean;
  glowColor?: string;
  glowBlur?: number;
  glowStrength?: number;
  letterSpacing?: number;
  lineHeight?: number;
  textAlign?: 'left' | 'center' | 'right';
  opacity?: number;
  secondaryOutlineColor?: string;
  secondaryOutlineWidth?: number;
  staticEffect?: StaticTextEffect;
}

export interface TextStylePreset {
  id: string;
  name: string;
  previewText: string;
  style: TextStyle;
  previewStyle?: TextStyle;
}
