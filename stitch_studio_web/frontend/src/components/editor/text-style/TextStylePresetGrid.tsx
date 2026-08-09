import { Ban } from 'lucide-react';
import type { CSSProperties } from 'react';
import { TEXT_STYLE_PRESETS } from '../../../config/textStylePresets';
import { textStyleToCss } from '../../../utils/textStyleToCss';
import type { TextStyle } from '../../../types/textStyle';

type Props = {
  activePresetId?: string;
  onSelect: (presetId: string) => void;
  onReset: () => void;
};

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

function previewTileFill(style: TextStyle): CSSProperties | undefined {
  if (!(style.backgroundEnabled ?? style.background)) return undefined;
  return {
    '--preset-tile-fill': hexToRgba(style.backgroundColor || '#000000', style.backgroundOpacity ?? 1),
  } as CSSProperties;
}

function previewLetterStyle(style: TextStyle): TextStyle {
  if (!(style.backgroundEnabled ?? style.background)) return style;
  return {
    ...style,
    background: false,
    backgroundEnabled: false,
  };
}

export function TextStylePresetGrid({ activePresetId, onSelect, onReset }: Props) {
  return (
    <div className="text-style-preset-block">
      <div className="text-style-preset-head">
        <span>Presets</span>
        <small>{TEXT_STYLE_PRESETS.length} styles</small>
      </div>
      <div className="text-style-preset-grid" aria-label="Default text style presets">
      <button
        type="button"
        className={`text-style-preset-tile no-style ${!activePresetId ? 'active' : ''}`}
        title="No Style"
        aria-label="No Style"
        onClick={onReset}
      >
        <Ban size={28} />
      </button>
      {TEXT_STYLE_PRESETS.map((preset) => {
        const style = preset.previewStyle || preset.style;
        const effect = style.staticEffect || 'none';
        const hasFill = Boolean(style.backgroundEnabled ?? style.background);
        return (
          <button
            type="button"
            key={preset.id}
            className={`text-style-preset-tile ${hasFill ? 'has-fill' : ''} ${activePresetId === preset.id ? 'active' : ''}`}
            style={previewTileFill(style)}
            title={preset.name}
            aria-label={preset.name}
            onClick={() => onSelect(preset.id)}
          >
            <span className="preset-preview-canvas" aria-hidden="true">
              <span className="preset-preview-fit">
                <span
                  className={`preset-preview-letter effect-${effect}`}
                  data-text={preset.previewText}
                  style={textStyleToCss(previewLetterStyle(style))}
                >
                  {preset.previewText}
                </span>
              </span>
            </span>
          </button>
        );
      })}
      </div>
    </div>
  );
}
