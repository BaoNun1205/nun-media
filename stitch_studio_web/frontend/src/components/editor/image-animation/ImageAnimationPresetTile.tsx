import { useEffect, useRef, useState } from 'react';
import type { TimelineItem } from '../../../types/studio';
import { evaluateImageAnimation, composeImageTransform } from '../../../utils/image-animation/evaluateImageAnimation';

interface Props {
  presetId: string | null;
  type: 'in' | 'out' | 'combo';
  isActive: boolean;
  onClick: () => void;
}

function formatLabel(id: string | null): string {
  if (!id) return 'None';
  return id.split('-').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

export function ImageAnimationPresetTile({ presetId, type, isActive, onClick }: Props) {
  const isNone = presetId === null;
  const imgRef = useRef<HTMLImageElement>(null);
  const reqRef = useRef<number | null>(null);
  
  const [isHovered, setIsHovered] = useState(false);
  const hoverStartTimeRef = useRef<number>(0);

  const duration = type === 'combo' ? 2.0 : 1.0;
  
  const getStaticTime = () => {
    if (type === 'in') return duration; // End of IN animation (fully visible)
    if (type === 'out') return 0; // Start of OUT animation (fully visible)
    if (type === 'combo') return duration / 2; // Middle of combo
    return 0;
  };

  const applyTransform = (localTime: number) => {
    if (!imgRef.current || isNone) return;

    const mockItem = {
      id: 'mock',
      type: 'image',
      duration: duration,
      params: {
        imageAnimation: {
          in: type === 'in' ? { presetId, duration } : undefined,
          out: type === 'out' ? { presetId, duration } : undefined,
          combo: type === 'combo' ? { presetId, timing: 'loop', cycleSeconds: duration, intensity: 1, loopMode: 'pingPong' } : undefined,
        }
      }
    } as unknown as TimelineItem;

    const delta = evaluateImageAnimation(mockItem, localTime);
    const base = { x: 0, y: 0, scale: 1 };
    const composed = composeImageTransform(base, delta);
    
    imgRef.current.style.transform = `translate(${composed.x * 100}%, ${composed.y * 100}%) scale(${composed.scale}) rotate(${composed.rotation}deg)`;
    imgRef.current.style.opacity = composed.opacity.toString();
    imgRef.current.style.filter = composed.blur > 0 ? `blur(${composed.blur}px)` : 'none';
  };

  useEffect(() => {
    if (!isHovered) {
      if (reqRef.current) cancelAnimationFrame(reqRef.current);
      applyTransform(getStaticTime());
      return;
    }

    hoverStartTimeRef.current = performance.now();
    
    const loop = (time: number) => {
      const elapsed = (time - hoverStartTimeRef.current) / 1000;
      applyTransform(type === 'combo' ? elapsed : Math.min(elapsed % (duration + .5), duration));
      reqRef.current = requestAnimationFrame(loop);
    };
    
    reqRef.current = requestAnimationFrame(loop);
    
    return () => {
      if (reqRef.current) cancelAnimationFrame(reqRef.current);
    };
  }, [isHovered, presetId, type]);

  const displayLabel = formatLabel(presetId);

  return (
    <button 
      className={`animation-preset-tile ${isActive ? 'active' : ''}`}
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocus={() => setIsHovered(true)}
      onBlur={() => setIsHovered(false)}
      title={displayLabel}
      aria-label={displayLabel}
    >
      <div className="animation-preset-preview">
        {isNone ? (
          <div className="preset-none-icon">
            <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" strokeWidth="1.5" fill="none">
              <circle cx="12" cy="12" r="10" />
              <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
            </svg>
          </div>
        ) : (
          <img 
            ref={imgRef}
            src="/assets/image-animation-preview.webp" 
            alt=""
            className="preset-preview-img"
          />
        )}
      </div>
      <div className="animation-preset-label">{displayLabel}</div>
    </button>
  );
}
