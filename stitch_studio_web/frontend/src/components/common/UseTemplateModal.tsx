import { useState, useRef, useEffect } from 'react';
import { ChevronRight, X, FileAudio, FileVideo, Image as ImageIcon } from 'lucide-react';
import { studioApi } from '../../services/api';
import type { TemplateSummary, WorkspaceProject } from '../../types/studio';

interface Props {
  template: TemplateSummary;
  onClose: () => void;
  onCreated: (project: WorkspaceProject) => void;
}

export function UseTemplateModal({ template, onClose, onCreated }: Props) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [projectName, setProjectName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const allRequiredFilled = template.inputs.every(input => files[input.slotId] != null);

  const handleFileChange = (slotId: string, file: File | null) => {
    setFiles(prev => ({ ...prev, [slotId]: file }));
    if (file && !projectName) {
      setProjectName(file.name.replace(/\.[^/.]+$/, ""));
    }
  };

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
      if (projectName) {
        formData.append('projectName', projectName);
      }
      const res = await studioApi.instantiateTemplate(template.id, formData);
      onCreated(res.project);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to instantiate template');
      setCreating(false);
    }
  };

  return (
    <div className="project-picker-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="project-picker-modal" role="dialog" aria-modal="true" onMouseDown={e => e.stopPropagation()} style={{ width: '520px', maxWidth: '90vw' }}>
        <header className="project-picker-header">
          <div>
            <h2>Use Template</h2>
            <p>{template.name} · {template.inputs.length} media file(s) required</p>
          </div>
          <button className="icon-button" onClick={onClose} disabled={creating}><X size={20} /></button>
        </header>

        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto', maxHeight: '65vh' }}>
          {error && <div className="connection-banner">{error}</div>}
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>PROJECT NAME</label>
            <input 
              type="text" 
              className="studio-input" 
              placeholder={`${template.name} - New Project`}
              value={projectName}
              onChange={e => setProjectName(e.target.value)}
              disabled={creating}
              style={{ width: '100%', padding: '10px 12px', background: 'var(--surface-sunken)', border: '1px solid var(--border-strong)', borderRadius: '6px', color: 'var(--text-normal)' }}
            />
          </div>

          <div style={{ width: '100%', height: '1px', background: 'var(--border-strong)', margin: '4px 0' }} />

          {template.inputs.map(input => (
            <MediaSlotCard 
              key={input.slotId} 
              input={input} 
              file={files[input.slotId] || null} 
              onChange={file => handleFileChange(input.slotId, file)} 
              disabled={creating} 
            />
          ))}
          
          {creating && (
            <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '12px', background: 'var(--surface-sunken)', borderRadius: '8px' }}>
              <div style={{ marginBottom: '8px' }}>Creating project and uploading media...</div>
              <div style={{ fontSize: '12px' }}>This may take a moment depending on file sizes.</div>
            </div>
          )}
        </div>

        <footer className="project-picker-footer" style={{ borderTop: '1px solid var(--border-strong)', padding: '16px 20px', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button className="button-text" onClick={onClose} disabled={creating}>Cancel</button>
          <button 
            className="button-primary" 
            onClick={handleCreate} 
            disabled={creating || !allRequiredFilled}
          >
            {creating ? 'Creating...' : 'Create Project'} <ChevronRight size={16} style={{ marginLeft: '4px' }} />
          </button>
        </footer>
      </section>
    </div>
  );
}

function MediaSlotCard({ input, file, onChange, disabled }: { input: any, file: File | null, onChange: (f: File | null) => void, disabled: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (file && input.kind === 'image') {
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
      return () => URL.revokeObjectURL(url);
    } else {
      setPreviewUrl(null);
    }
  }, [file, input.kind]);

  const acceptType = input.kind === 'image' ? 'image/*' : input.kind === 'video' ? 'video/*' : 'audio/*';
  
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      if (droppedFile.type.startsWith(input.kind)) {
        onChange(droppedFile);
      } else {
        // Just ignore invalid files silently as per native behavior, or keep it simple.
      }
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (file) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>{input.label}</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', background: 'var(--surface-sunken)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-strong)' }}>
          <div style={{ width: '48px', height: '48px', borderRadius: '4px', overflow: 'hidden', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            {previewUrl ? (
              <img src={previewUrl} alt="Preview" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            ) : input.kind === 'audio' ? (
              <FileAudio size={24} color="var(--text-dim)" />
            ) : (
              <FileVideo size={24} color="var(--text-dim)" />
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{file.name}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '4px' }}>{formatSize(file.size)}</div>
          </div>
          <button 
            className="button-text" 
            style={{ padding: '6px 12px', fontSize: '13px' }}
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
          >
            Replace
          </button>
          <button 
            className="icon-button" 
            onClick={() => onChange(null)}
            disabled={disabled}
          >
            <X size={16} />
          </button>
          <input type="file" ref={inputRef} hidden accept={acceptType} onChange={e => { if (e.target.files?.[0]) onChange(e.target.files[0]); }} />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>{input.label}</label>
      <div 
        onClick={() => !disabled && inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        style={{ 
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', 
          padding: '24px', borderRadius: '8px', cursor: disabled ? 'default' : 'pointer',
          background: dragOver ? 'var(--surface)' : 'var(--surface-sunken)',
          border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border-strong)'}`,
          transition: 'all 0.2s ease',
          opacity: disabled ? 0.5 : 1
        }}
      >
        <div style={{ color: 'var(--text-dim)' }}>
          {input.kind === 'image' ? <ImageIcon size={32} /> : input.kind === 'audio' ? <FileAudio size={32} /> : <FileVideo size={32} />}
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontWeight: 500 }}>Drop an {input.kind} here</div>
          <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '4px' }}>or click to Choose File</div>
        </div>
        <input type="file" ref={inputRef} hidden accept={acceptType} onChange={e => { if (e.target.files?.[0]) onChange(e.target.files[0]); }} />
      </div>
    </div>
  );
}
