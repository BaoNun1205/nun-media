import { useEffect, useMemo, useState } from 'react';
import { Captions, FileAudio, FileVideo2, Play, X } from 'lucide-react';
import { formatDuration } from '../../lib/studio';
import type { WorkspaceProject } from '../../types/studio';

interface ProjectPickerModalProps {
  open: boolean;
  projects: WorkspaceProject[];
  title: string;
  description: string;
  confirmLabel?: string;
  onClose: () => void;
  onConfirm: (projectIds: number[]) => void | Promise<void>;
}

export function ProjectPickerModal({ open, projects, title, description, confirmLabel = 'Add selected', onClose, onConfirm }: ProjectPickerModalProps) {
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  useEffect(() => {
    if (open) setSelectedIds([]);
  }, [open]);

  if (!open) return null;

  function toggle(projectId: number) {
    setSelectedIds((current) => current.includes(projectId) ? current.filter((id) => id !== projectId) : [...current, projectId]);
  }

  async function confirm() {
    if (!selectedIds.length) return;
    await onConfirm(selectedIds);
  }

  return <div className="project-picker-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="project-picker-modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
      <header className="project-picker-header">
        <div><h2>{title}</h2><p>{description}</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Close"><X size={17} /></button>
      </header>
      <div className="project-picker-grid">
        {projects.map((project) => {
          const active = selected.has(project.id);
          return <button key={project.id} className={`project-picker-card ${active ? 'selected' : ''}`} onClick={() => toggle(project.id)}>
            <span className="project-picker-thumb">
              {project.primaryVideoId && <img src={`/api/videos/${project.primaryVideoId}/thumbnail`} loading="lazy" alt="" />}
              <i><Play size={15} fill="currentColor" /></i>
              <em>{formatDuration(project.durationMs)}</em>
            </span>
            <span className="project-picker-name">{project.title}</span>
            <span className="project-picker-id">{project.projectId}</span>
            <span className="project-picker-stats">
              <small><FileVideo2 size={11} /> {project.videos.length}</small>
              <small><Captions size={11} /> {project.assets.filter((asset) => asset.kind === 'srt').length}</small>
              <small><FileAudio size={11} /> {project.assets.filter((asset) => asset.kind === 'audio').length}</small>
            </span>
            <span className="project-picker-check">{active ? 'Selected' : 'Select'}</span>
          </button>;
        })}
        {!projects.length && <div className="project-picker-empty">Create a project first, then add media to it.</div>}
      </div>
      <footer className="project-picker-footer">
        <span>{selectedIds.length} selected</span>
        <div><button onClick={onClose}>Cancel</button><button className="primary" disabled={!selectedIds.length} onClick={confirm}>{confirmLabel}</button></div>
      </footer>
    </section>
  </div>;
}
