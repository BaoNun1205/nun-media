import { useEffect, useState } from 'react';
import { LayoutTemplate, Play, Trash2, Box, Image, Video, FileAudio, FileText } from 'lucide-react';
import { studioApi } from '../services/api';
import type { TemplateSummary } from '../types/studio';
import { UseTemplateModal } from '../components/common/UseTemplateModal';

export function TemplatesPage({ onOpenWorkspace }: { onOpenWorkspace?: (project: any) => void }) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const fetchTemplates = async () => {
    try {
      setLoading(true);
      const res = await studioApi.templates();
      setTemplates(res.templates);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load templates');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  async function removeTemplate(template: TemplateSummary) {
    try {
      await studioApi.deleteTemplate(template.id);
      setMessage(`Deleted template "${template.name}".`);
      await fetchTemplates();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to delete template');
    }
  }
  const [activeTemplate, setActiveTemplate] = useState<TemplateSummary | null>(null);

  return (
    <section className="page projects-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Workspace</span>
          <h1>Templates</h1>
          <p>Reusable editing setups created from your projects.</p>
        </div>
      </header>
      
      {error && <div className="connection-banner">{error}</div>}
      {message && <div className="inline-notice">{message}</div>}

      <div className="project-collection grid">
        {loading && !templates.length ? (
          <div className="empty-state">Loading templates...</div>
        ) : templates.length === 0 ? (
          <div className="empty-state">
            <LayoutTemplate size={28} />
            <strong>No templates yet</strong>
            <span>Build a project, then use "Save as Template" from the editor to create a reusable setup.</span>
          </div>
        ) : (
          templates.map((template) => (
            <article className="project-card" key={template.id}>
              <div className="project-thumb" style={{ background: 'var(--surface-sunken)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <LayoutTemplate size={48} color="var(--border-strong)" />
              </div>
              <div className="project-card-body">
                <div className="project-title-row">
                  <div>
                    <h2>{template.name}</h2>
                    <p>
                      {template.inputCount} media input{template.inputCount !== 1 ? 's' : ''}
                      {template.sourceProjectId ? ` · From Project ${template.sourceProjectId}` : ''}
                    </p>
                  </div>
                </div>
                
                <div className="status-chips" style={{ flexWrap: 'wrap' }}>
                  {template.inputs.map((input, idx) => (
                    <span key={idx} className="ready">
                      {input.kind === 'image' && <Image size={12} />}
                      {input.kind === 'video' && <Video size={12} />}
                      {input.kind === 'audio' && <FileAudio size={12} />}
                      {` ${input.label}`}
                    </span>
                  ))}
                  {template.generatedSummary.map((gen, idx) => (
                    <span key={`gen-${idx}`} className="voice" style={{ background: 'var(--brand-alpha)' }}>
                      <FileText size={12} />
                      {gen.source?.type === 'srt-from-audio' ? ' Auto Subs' : ` Auto ${gen.kind}`}
                    </span>
                  ))}
                </div>

                <div className="project-meta">
                  <span>
                    {template.canvas ? `${template.canvas.width}x${template.canvas.height}` : 'Unknown Canvas'} 
                    {template.fps ? ` · ${template.fps} FPS` : ''}
                  </span>
                  <span>{new Date(template.createdAt).toLocaleDateString()}</span>
                </div>
                
                <div className="project-actions" style={{ justifyContent: 'flex-end', gap: '8px' }}>
                  <button className="button-primary" style={{ padding: '6px 12px' }} onClick={() => setActiveTemplate(template)}>
                    Use Template
                  </button>
                  <div style={{ flex: 1 }} /> 
                  <button className="icon-button danger" onClick={() => removeTemplate(template)} title="Delete Template">
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </article>
          ))
        )}
      </div>

      {activeTemplate && (
        <UseTemplateModal
          template={activeTemplate}
          onClose={() => setActiveTemplate(null)}
          onCreated={(project) => {
            setActiveTemplate(null);
            if (onOpenWorkspace) {
              onOpenWorkspace(project);
            }
          }}
        />
      )}
    </section>
  );
}
