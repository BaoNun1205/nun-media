import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { studioApi } from '../../services/api';
import type { TemplateSummary } from '../../types/studio';

interface Props {
  template: TemplateSummary;
  onClose: () => void;
  onCreated: (projectId: number) => void;
}

export function UseTemplateModal({ template, onClose, onCreated }: Props) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleFileChange = (slotId: string, file: File | null) => {
    setFiles(prev => ({ ...prev, [slotId]: file }));
  };

  const allRequiredFilled = template.inputs.every(input => files[input.slotId] != null);

  const handleCreate = async () => {
    if (!allRequiredFilled) return;
    
    try {
      setCreating(true);
      setError('');
      
      const formData = new FormData();
      
      const slotIdsToUpload: string[] = [];
      
      template.inputs.forEach(input => {
        const file = files[input.slotId];
        if (file) {
          slotIdsToUpload.push(input.slotId);
          formData.append('files', file);
        }
      });
      
      formData.append('slotIds', JSON.stringify(slotIdsToUpload));
      
      const res = await studioApi.instantiateTemplate(template.id, formData);
      onCreated(res.project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to instantiate template');
      setCreating(false);
    }
  };

  return (
    <div className="project-picker-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="project-picker-modal" role="dialog" aria-modal="true" onMouseDown={e => e.stopPropagation()}>
        <header className="project-picker-header">
          <div>
            <h2>Use Template: {template.name}</h2>
            <p>Select media files for this project</p>
          </div>
          <button className="icon-button" onClick={onClose} disabled={creating}>×</button>
        </header>

        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto', maxHeight: '50vh' }}>
          {error && <div className="connection-banner">{error}</div>}
          
          {template.inputs.map(input => {
            const acceptType = input.kind === 'image' ? 'image/*' : input.kind === 'video' ? 'video/*' : 'audio/*';
            
            return (
              <div key={input.slotId} style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--surface-sunken)', padding: '12px', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <strong>{input.label}</strong>
                  <span className="eyebrow">{input.kind}</span>
                </div>
                
                <input 
                  type="file" 
                  accept={acceptType} 
                  onChange={e => handleFileChange(input.slotId, e.target.files?.[0] || null)} 
                  disabled={creating}
                  style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-strong)', background: 'var(--surface)' }}
                />
              </div>
            );
          })}
          
          {creating && (
            <div style={{ textAlign: 'center', color: 'var(--text-dim)' }}>
              Creating project and uploading files...
            </div>
          )}
        </div>

        <footer className="project-picker-footer">
          <button className="button-text" onClick={onClose} disabled={creating}>Cancel</button>
          <button 
            className="button-primary" 
            onClick={handleCreate} 
            disabled={creating || !allRequiredFilled}
          >
            {creating ? 'Creating...' : 'Create Project'} <ChevronRight size={16} />
          </button>
        </footer>
      </section>
    </div>
  );
}
