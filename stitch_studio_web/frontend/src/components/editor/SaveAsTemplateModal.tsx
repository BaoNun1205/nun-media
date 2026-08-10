import { useEffect, useState } from 'react';
import { LoaderCircle, X, Check } from 'lucide-react';
import { studioApi } from '../../services/api';
import type { EditorController } from '../../hooks/useEditorController';
import type { TemplateManifest } from '../../types/studio';

type SaveState = 'LOADING' | 'READY' | 'SAVING' | 'DONE' | 'ERROR';

export function SaveAsTemplateModal({ editor, open, onClose }: { editor: EditorController; open: boolean; onClose: () => void }) {
  const [state, setState] = useState<SaveState>('LOADING');
  const [manifest, setManifest] = useState<TemplateManifest | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) {
      setState('LOADING');
      setManifest(null);
      setName('');
      setError('');
      return;
    }
    
    // Always sync timeline state before analyzing
    const workspaceId = editor.project.workspaceId || editor.project.id;
    studioApi.saveWorkspaceTimeline(workspaceId, editor.timelineItems, editor.timelineState, editor.timelineScene)
      .then(() => studioApi.previewTemplate(workspaceId))
      .then((res) => {
        setManifest(res.manifest);
        setName(res.manifest.name);
        setState('READY');
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Could not analyze template');
        setState('ERROR');
      });
  }, [open, editor.project.workspaceId, editor.project.id, editor.timelineItems, editor.timelineState, editor.timelineScene]);

  async function handleSave() {
    if (!manifest) return;
    setState('SAVING');
    try {
      const workspaceId = editor.project.workspaceId || editor.project.id;
      await studioApi.saveTemplate(workspaceId, {
        name,
        manifest: { ...manifest, name }
      });
      setState('DONE');
      setTimeout(() => {
        onClose();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      setState('ERROR');
    }
  }

  if (!open) return null;

  return (
    <div className="export-modal-backdrop" role="presentation">
      <section className="export-modal" role="dialog" aria-modal="true" aria-labelledby="template-title" style={{ maxWidth: 450 }}>
        <header className="export-modal-header">
          <div>
            <h2 id="template-title">Save as Template</h2>
            <p>Create a reusable template from this project</p>
          </div>
          <button className="icon-button" onClick={onClose} disabled={state === 'SAVING'} title="Close"><X size={17} /></button>
        </header>

        {state === 'LOADING' && (
          <div className="export-modal-status">
            <LoaderCircle className="spin" size={30} />
            <h3>Analyzing project...</h3>
          </div>
        )}

        {(state === 'READY' || state === 'ERROR') && (
          <div className="export-modal-body">
            {error && <p className="export-inline-error">{error}</p>}
            
            <label>
              <span>Template Name</span>
              <div className="export-file-row">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Template" />
              </div>
            </label>

            {manifest && (
              <div className="template-inputs-preview" style={{ marginTop: 20 }}>
                <h3 style={{ fontSize: 13, marginBottom: 8 }}>Media inputs detected</h3>
                {manifest.inputs.length === 0 ? (
                  <p className="export-warning">No replaceable media detected.</p>
                ) : (
                  <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 16px 0', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {manifest.inputs.map((input) => (
                      <li key={input.slotId} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 8px', background: 'var(--bg-layer-2)', borderRadius: 4 }}>
                        <strong>{input.label}</strong>
                        <span style={{ color: 'var(--text-dim)' }}>Will be replaced</span>
                      </li>
                    ))}
                  </ul>
                )}

                <h3 style={{ fontSize: 13, marginBottom: 8 }}>Automatically preserved</h3>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {manifest.generated.some(g => g.kind === 'subtitle') && (
                    <li style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Check size={14} color="var(--success)" /> Subs from Audio
                    </li>
                  )}
                  <li style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Check size={14} color="var(--success)" /> Timeline structure</li>
                  <li style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Check size={14} color="var(--success)" /> Effects & animations</li>
                  {manifest.timelineTemplate.subtitleStyle && (
                    <li style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Check size={14} color="var(--success)" /> Subtitle style & position</li>
                  )}
                  <li style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Check size={14} color="var(--success)" /> Canvas & FPS</li>
                </ul>
              </div>
            )}
          </div>
        )}

        {state === 'SAVING' && (
          <div className="export-modal-status">
            <LoaderCircle className="spin" size={30} />
            <h3>Saving template...</h3>
          </div>
        )}

        {state === 'DONE' && (
          <div className="export-modal-status done">
            <Check size={32} />
            <h3>Template saved</h3>
          </div>
        )}

        {(state === 'READY' || state === 'ERROR') && (
          <footer className="export-modal-footer" style={{ padding: '16px 24px', display: 'flex', gap: 12, justifyContent: 'flex-end', borderTop: '1px solid var(--border-color)', marginTop: 24 }}>
            <button className="secondary" onClick={onClose}>Cancel</button>
            <button className="primary" disabled={!name.trim() || state === 'ERROR'} onClick={handleSave}>Save Template</button>
          </footer>
        )}
      </section>
    </div>
  );
}
