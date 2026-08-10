import { useEffect, useState } from 'react';
import { LayoutTemplate, ChevronRight, Check } from 'lucide-react';
import { studioApi } from '../../services/api';
import type { TemplateSummary, WorkspaceProject, ProjectAsset } from '../../types/studio';

interface Props {
  template: TemplateSummary;
  projectId: number;
  onClose: () => void;
  onApplied: (projectId: number) => void;
}

export function TemplateSlotMappingModal({ template, projectId, onClose, onApplied }: Props) {
  const [project, setProject] = useState<WorkspaceProject | null>(null);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [slotMap, setSlotMap] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const p = await studioApi.workspaceProject(projectId);
        setProject(p);
        setAssets(p.assets || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load project');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [projectId]);

  const handleApply = async () => {
    if (Object.keys(slotMap).length < template.inputs.length) {
      setError('Please map all required slots before applying.');
      return;
    }
    
    try {
      setApplying(true);
      setError('');
      await studioApi.applyTemplate(projectId, template.id, slotMap);
      onApplied(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply template');
      setApplying(false);
    }
  };

  return (
    <div className="project-picker-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="project-picker-modal" role="dialog" aria-modal="true" onMouseDown={e => e.stopPropagation()}>
        <header className="project-picker-header">
          <div>
            <h2>Use Template: {template.name}</h2>
            <p>Map template inputs to media in Project {projectId}</p>
          </div>
          <button className="icon-button" onClick={onClose}>×</button>
        </header>

        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto', maxHeight: '50vh' }}>
          {error && <div className="connection-banner">{error}</div>}
          {loading ? (
            <div>Loading project assets...</div>
          ) : (
            template.inputs.map(input => {
              const matchingAssets = assets.filter(a => a.kind === input.kind);
              const mappedId = slotMap[input.slotId];
              
              return (
                <div key={input.slotId} style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--surface-sunken)', padding: '12px', borderRadius: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <strong>{input.label}</strong>
                    <span className="eyebrow">{input.kind}</span>
                  </div>
                  
                  {matchingAssets.length === 0 ? (
                    <div style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>
                      No {input.kind} assets found in project. Please add them first.
                    </div>
                  ) : (
                    <select 
                      value={mappedId || ''} 
                      onChange={e => setSlotMap(s => ({ ...s, [input.slotId]: parseInt(e.target.value) }))}
                      style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-strong)', background: 'var(--surface)' }}
                    >
                      <option value="" disabled>Select a {input.kind}...</option>
                      {matchingAssets.map(a => (
                        <option key={a.id} value={a.id}>{a.name}</option>
                      ))}
                    </select>
                  )}
                </div>
              );
            })
          )}
        </div>

        <footer className="project-picker-footer">
          <button className="button-text" onClick={onClose} disabled={applying}>Cancel</button>
          <button 
            className="button-primary" 
            onClick={handleApply} 
            disabled={loading || applying || Object.keys(slotMap).length < template.inputs.length}
          >
            {applying ? 'Applying...' : 'Apply Template'} <ChevronRight size={16} />
          </button>
        </footer>
      </section>
    </div>
  );
}
