import { useState } from 'react';
import type { EditorController } from '../../hooks/useEditorController';
import type { TimelineItem } from '../../types/studio';
import { Section, InspectorRangeField, useTimelineItemDraft } from './ContextInspector';
import { IN_PRESETS, OUT_PRESETS, COMBO_PRESETS } from '../../utils/image-animation/presets';
import type { ImageAnimationConfig } from '../../utils/image-animation/types';
import { ImageAnimationPresetTile } from './image-animation/ImageAnimationPresetTile';

export function ImageAnimationControls({ editor, item }: { editor: EditorController; item: TimelineItem }) {
  const [activeTab, setActiveTab] = useState<'in' | 'out' | 'combo'>('in');
  const commit = useTimelineItemDraft(editor, 'Updated image animation.');
  
  const config: ImageAnimationConfig = (item.params?.imageAnimation as ImageAnimationConfig) || {};
  const duration = item.duration || 1.0;

  const updateConfig = (updates: Partial<ImageAnimationConfig>, finish = false) => {
    commit.update(item.id, (clip) => ({
      ...clip,
      params: {
        ...(clip.params || {}),
        imageAnimation: {
          ...(clip.params?.imageAnimation as object || {}),
          ...updates,
        }
      },
    }), finish);
  };

  const currentIn = config.in?.presetId || null;
  const currentOut = config.out?.presetId || null;
  const currentCombo = config.combo?.presetId || null;
  
  const inDur = config.in?.duration ?? 0.5;
  const outDur = config.out?.duration ?? 0.5;

  return (
    <div className="animation-inspector">
      <div className="inspector-tabs-segmented">
        <div className="tab-indicator" data-tab={activeTab} />
        <button className={activeTab === 'in' ? 'active' : ''} onClick={() => setActiveTab('in')}>In</button>
        <button className={activeTab === 'out' ? 'active' : ''} onClick={() => setActiveTab('out')}>Out</button>
        <button className={activeTab === 'combo' ? 'active' : ''} onClick={() => setActiveTab('combo')}>Combo</button>
      </div>
      
      <div className="animation-tab-content">
        {activeTab === 'in' && (
          <>
            <div className="preset-grid">
              <ImageAnimationPresetTile
                presetId={null}
                type="in"
                isActive={currentIn === null}
                onClick={() => updateConfig({ in: { ...config.in, presetId: null, duration: inDur } }, true)}
              />
              {IN_PRESETS.map(p => (
                <ImageAnimationPresetTile
                  key={p.id}
                  presetId={p.id}
                  type="in"
                  isActive={currentIn === p.id}
                  onClick={() => updateConfig({ in: { ...config.in, presetId: p.id, duration: inDur } }, true)}
                />
              ))}
            </div>
            {currentIn && (
              <Section title="Duration">
                <InspectorRangeField 
                  label="Duration" 
                  value={inDur} 
                  min={0.1} 
                  max={Math.max(0.1, duration - (currentOut ? outDur : 0))} 
                  step={0.1} 
                  suffix="s" 
                  onChange={(v, finish) => updateConfig({ in: { presetId: currentIn, duration: v } }, finish)} 
                />
              </Section>
            )}
          </>
        )}
        
        {activeTab === 'out' && (
          <>
            <div className="preset-grid">
              <ImageAnimationPresetTile
                presetId={null}
                type="out"
                isActive={currentOut === null}
                onClick={() => updateConfig({ out: { ...config.out, presetId: null, duration: outDur } }, true)}
              />
              {OUT_PRESETS.map(p => (
                <ImageAnimationPresetTile
                  key={p.id}
                  presetId={p.id}
                  type="out"
                  isActive={currentOut === p.id}
                  onClick={() => updateConfig({ out: { ...config.out, presetId: p.id, duration: outDur } }, true)}
                />
              ))}
            </div>
            {currentOut && (
              <Section title="Duration">
                <InspectorRangeField 
                  label="Duration" 
                  value={outDur} 
                  min={0.1} 
                  max={Math.max(0.1, duration - (currentIn ? inDur : 0))} 
                  step={0.1} 
                  suffix="s" 
                  onChange={(v, finish) => updateConfig({ out: { presetId: currentOut, duration: v } }, finish)} 
                />
              </Section>
            )}
          </>
        )}
        
        {activeTab === 'combo' && (
          <div className="preset-grid">
            <ImageAnimationPresetTile
              presetId={null}
              type="combo"
              isActive={currentCombo === null}
              onClick={() => updateConfig({ combo: { presetId: null } }, true)}
            />
            {COMBO_PRESETS.map(p => (
              <ImageAnimationPresetTile
                key={p.id}
                presetId={p.id}
                type="combo"
                isActive={currentCombo === p.id}
                onClick={() => updateConfig({ combo: { presetId: p.id } }, true)}
              />
            ))}
          </div>
        )}
      </div>
      
      <style>{`
        .inspector-tabs-segmented {
          position: relative;
          display: flex;
          background: rgba(0, 0, 0, 0.3);
          padding: 3px;
          border-radius: 8px;
          margin-bottom: 12px;
          box-shadow: inset 0 1px 3px rgba(0,0,0,0.2);
        }
        .inspector-tabs-segmented button {
          flex: 1;
          position: relative;
          z-index: 1;
          background: transparent;
          border: none;
          color: var(--text-muted);
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: color 0.2s;
        }
        .inspector-tabs-segmented button:hover {
          color: var(--text-normal);
        }
        .inspector-tabs-segmented button.active {
          color: white;
          text-shadow: 0 1px 2px rgba(0,0,0,0.8);
        }
        .tab-indicator {
          position: absolute;
          top: 3px;
          bottom: 3px;
          left: 3px;
          width: calc((100% - 6px) / 3);
          background: rgba(255, 255, 255, 0.12);
          border-radius: 6px;
          transition: transform 0.25s cubic-bezier(0.4, 0.0, 0.2, 1);
          z-index: 0;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2), inset 0 1px 1px rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .tab-indicator[data-tab="in"] { transform: translateX(0); }
        .tab-indicator[data-tab="out"] { transform: translateX(100%); }
        .tab-indicator[data-tab="combo"] { transform: translateX(200%); }
        
        .animation-tab-content {
          padding: 8px 0;
        }
        
        .preset-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
          gap: 10px;
          margin-bottom: 16px;
        }
        
        .animation-preset-tile {
          display: flex;
          flex-direction: column;
          background: transparent;
          border: 1.5px solid transparent;
          border-radius: 8px;
          padding: 4px;
          cursor: pointer;
          transition: all 0.2s;
          align-items: center;
          outline: none;
        }
        .animation-preset-tile:hover {
          background: var(--bg-modifier-hover);
        }
        .animation-preset-tile.active {
          border-color: var(--interactive-accent);
          background: rgba(45, 212, 191, 0.05); /* very light cyan tint */
        }
        
        .animation-preset-preview {
          width: 100%;
          aspect-ratio: 1;
          background: #1a1a1a;
          border-radius: 4px;
          overflow: hidden;
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          margin-bottom: 6px;
          /* To prevent hover issues on children */
          pointer-events: none;
        }
        
        .preset-preview-img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
          /* Ensure transform origin is center for accurate scale/rotate */
          transform-origin: center;
          will-change: transform, opacity, filter;
        }
        
        .preset-none-icon {
          color: var(--text-muted);
          display: flex;
          align-items: center;
          justify-content: center;
        }
        
        .animation-preset-label {
          font-size: 11px;
          color: var(--text-muted);
          text-align: center;
          width: 100%;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          line-height: 1.2;
        }
        .animation-preset-tile:hover .animation-preset-label,
        .animation-preset-tile.active .animation-preset-label {
          color: var(--text-normal);
        }
      `}</style>
    </div>
  );
}

