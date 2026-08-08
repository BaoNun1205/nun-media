import { Ban } from 'lucide-react';
import { TEXT_STYLE_PRESETS } from '../../../config/textStylePresets';
import { textStyleToCss } from '../../../utils/textStyleToCss';

type Props = {
  activePresetId?: string;
  onSelect: (presetId: string) => void;
  onReset: () => void;
};

export function TextStylePresetGrid({ activePresetId, onSelect, onReset }: Props) {
  return (
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
        return (
          <button
            type="button"
            key={preset.id}
            className={`text-style-preset-tile ${activePresetId === preset.id ? 'active' : ''}`}
            title={preset.name}
            aria-label={preset.name}
            onClick={() => onSelect(preset.id)}
          >
            <span
              className={`preset-preview-letter effect-${effect}`}
              data-text={preset.previewText}
              style={textStyleToCss(style, { previewScale: 1.15 })}
            >
              {preset.previewText}
            </span>
          </button>
        );
      })}
    </div>
  );
}
