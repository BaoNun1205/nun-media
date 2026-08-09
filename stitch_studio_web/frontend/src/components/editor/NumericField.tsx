import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

type NumericFieldProps = {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  precision?: number;
  disabled?: boolean;
  onCommit?: (value: number) => void;
  prefix?: ReactNode;
  suffix?: ReactNode;
  compact?: boolean;
  className?: string;
  ariaLabel?: string;
};

type SliderNumericFieldProps = NumericFieldProps & {
  rangeAriaLabel?: string;
};

export function NumericField({
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
  precision,
  disabled,
  onCommit,
  prefix,
  suffix,
  compact,
  className = '',
  ariaLabel,
}: NumericFieldProps) {
  const [draft, setDraft] = useState(() => formatNumber(value, precision ?? precisionFromStep(step)));
  const focusedRef = useRef(false);
  const cancelBlurRef = useRef(false);
  const resolvedPrecision = precision ?? precisionFromStep(step);

  useEffect(() => {
    if (!focusedRef.current) setDraft(formatNumber(value, resolvedPrecision));
  }, [resolvedPrecision, value]);

  const numericClassName = useMemo(() => [
    'numeric-field',
    compact ? 'numeric-field--compact' : '',
    prefix ? 'numeric-field--with-prefix' : '',
    className,
  ].filter(Boolean).join(' '), [className, compact, prefix]);

  const commit = (fallback = value) => {
    const parsed = parseDraft(draft);
    const next = clampNumber(parsed ?? fallback, min, max);
    setDraft(formatNumber(next, resolvedPrecision));
    onChange(next);
    onCommit?.(next);
  };

  const stepValue = (direction: 1 | -1) => {
    const parsed = parseDraft(draft);
    const base = parsed ?? value;
    const next = clampNumber(roundToPrecision(base + direction * step, resolvedPrecision), min, max);
    setDraft(formatNumber(next, resolvedPrecision));
    onChange(next);
    onCommit?.(next);
  };

  return (
    <label className={numericClassName}>
      {prefix && <span className="numeric-field-prefix">{prefix}</span>}
      <input
        aria-label={ariaLabel || (unit ? `Numeric value in ${unit}` : 'Numeric value')}
        type="text"
        inputMode="decimal"
        disabled={disabled}
        value={draft}
        onFocus={() => { focusedRef.current = true; }}
        onChange={(event) => {
          const nextDraft = event.target.value;
          setDraft(nextDraft);
          const parsed = parseDraft(nextDraft);
          if (parsed !== null) onChange(parsed);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.currentTarget.blur();
          } else if (event.key === 'Escape') {
            cancelBlurRef.current = true;
            setDraft(formatNumber(value, resolvedPrecision));
            event.currentTarget.blur();
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            stepValue(1);
          } else if (event.key === 'ArrowDown') {
            event.preventDefault();
            stepValue(-1);
          }
        }}
        onBlur={() => {
          focusedRef.current = false;
          if (cancelBlurRef.current) {
            cancelBlurRef.current = false;
            setDraft(formatNumber(value, resolvedPrecision));
            return;
          }
          commit();
        }}
      />
      {(unit || suffix) && <span className="numeric-field-unit">{suffix || unit}</span>}
    </label>
  );
}

export function SliderNumericField({
  value,
  onChange,
  onCommit,
  min = 0,
  max = 100,
  step = 1,
  unit,
  precision,
  disabled,
  prefix,
  suffix,
  compact = true,
  className = '',
  ariaLabel,
  rangeAriaLabel,
}: SliderNumericFieldProps) {
  const normalized = clampNumber(value, min, max);
  const commit = (next: number) => onCommit?.(clampNumber(next, min, max));
  return (
    <div className={`slider-numeric-field ${className}`.trim()}>
      <input
        aria-label={rangeAriaLabel || ariaLabel || (unit ? `Value in ${unit}` : 'Numeric slider')}
        type="range"
        min={min}
        max={max}
        step={step}
        value={normalized}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerUp={(event) => commit(Number(event.currentTarget.value))}
        onKeyUp={(event) => {
          if (event.key === 'Enter') commit(Number(event.currentTarget.value));
        }}
        onBlur={(event) => commit(Number(event.currentTarget.value))}
      />
      <NumericField
        value={normalized}
        onChange={onChange}
        onCommit={onCommit}
        min={min}
        max={max}
        step={step}
        unit={unit}
        precision={precision}
        disabled={disabled}
        prefix={prefix}
        suffix={suffix}
        compact={compact}
        ariaLabel={ariaLabel}
      />
    </div>
  );
}

function parseDraft(draft: string) {
  const value = draft.trim();
  if (!value || value === '-' || value === '+' || value === '.' || value === '-.' || value === '+.') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clampNumber(value: number, min?: number, max?: number) {
  const minimum = min ?? -Infinity;
  const maximum = max ?? Infinity;
  return Math.max(minimum, Math.min(maximum, Number.isFinite(value) ? value : minimum));
}

function precisionFromStep(step: number) {
  if (!Number.isFinite(step)) return 0;
  const text = String(step);
  if (text.includes('e-')) return Number(text.split('e-')[1]) || 0;
  return text.includes('.') ? text.split('.')[1].length : 0;
}

function roundToPrecision(value: number, precision: number) {
  const factor = 10 ** precision;
  return Math.round(value * factor) / factor;
}

function formatNumber(value: number, precision: number) {
  if (!Number.isFinite(value)) return '';
  return precision > 0 ? value.toFixed(precision) : String(Math.round(value));
}
