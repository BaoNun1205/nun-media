import { ArrowLeft, ChevronLeft, ChevronRight, FolderOpen, Pencil, Redo2, Save, Share2, Undo2 } from 'lucide-react';
import { formatClock } from '../../lib/studio';
import { studioApi } from '../../services/api';
import type { Project } from '../../types/studio';
import type { EditorController } from '../../hooks/useEditorController';

export function EditorTopBar({ editor, versions, onBack, onOpenVersion }: {
  editor: EditorController; versions: Project[]; onBack: () => void; onOpenVersion: (id: number) => void;
}) {
  const { project } = editor;
  const currentIndex = versions.findIndex((item) => item.id === project.id);
  const timelineEmpty = editor.isEmptyWorkspace && !editor.timelineItems.length;
  const openSafely = (id: number) => {
    if (editor.dirty && !window.confirm('You have unsaved subtitle changes. Discard them and switch version?')) return;
    onOpenVersion(id);
  };
  const backSafely = () => {
    if (editor.dirty && !window.confirm('You have unsaved subtitle changes. Discard them and return to Projects?')) return;
    onBack();
  };
  async function renameProject() {
    const title = window.prompt('Project name', project.title)?.trim();
    if (!title || title === project.title) return;
    try {
      if (project.workspaceId) await studioApi.renameWorkspaceProject(project.workspaceId, title);
      else await studioApi.renameProject(project.id, title);
      await editor.refresh();
    } catch (error) {
      editor.setMessage(error instanceof Error ? error.message : 'Unable to rename project');
    }
  }
  const exportDisabled = timelineEmpty || Boolean(project.workspaceId) || (editor.audioMode !== 'original' && !editor.audioSeparationReady);
  return (
    <header className="editor-topbar">
      <div className="editor-top-left">
        <button className="icon-button" onClick={backSafely} title="Back to Projects"><ArrowLeft size={18} /></button>
        <span className="topbar-divider" />
        <div className="editor-project-name">
          <strong>{project.title}</strong>
          <small>{project.projectId}</small>
        </div>
        <button className="rename-inline" onClick={renameProject} title="Rename project"><Pencil size={12} /></button>
        <select className="version-select" value={project.id} disabled={timelineEmpty || !versions.length} onChange={(event) => openSafely(Number(event.target.value))} aria-label="Video version">
          {editor.isEmptyWorkspace && <option value={project.id}>Empty timeline</option>}
          {versions.map((version, index) => <option key={version.id} value={version.id}>v{versions.length - index} · {version.processingState?.lastOperation || (index ? 'Edit' : 'Original')} · #{version.id}</option>)}
        </select>
        <div className="mini-status">
          {timelineEmpty && <span>Empty timeline</span>}
          {project.hasSrt && <span>SRT Ready</span>}
          {project.hasTranslatedSrt && <span>Translated</span>}
          {project.processingState?.subtitleHidden && <span>Subtitle Hidden</span>}
          {project.processingState?.subtitleInserted && <span>Subtitle Inserted</span>}
          {project.hasTts && <span>Voice Ready</span>}
        </div>
      </div>
      <div className="editor-history">
        <button className="icon-button" disabled={timelineEmpty || currentIndex >= versions.length - 1} title="Undo to previous rendered version" onClick={() => versions[currentIndex + 1] && openSafely(versions[currentIndex + 1].id)}><Undo2 size={16} /></button>
        <button className="icon-button" disabled={timelineEmpty || currentIndex <= 0} title="Redo to newer rendered version" onClick={() => versions[currentIndex - 1] && openSafely(versions[currentIndex - 1].id)}><Redo2 size={16} /></button>
        <button className="icon-button" disabled={timelineEmpty || currentIndex >= versions.length - 1} title="Previous version" onClick={() => versions[currentIndex + 1] && openSafely(versions[currentIndex + 1].id)}><ChevronLeft size={17} /></button>
        <span className="time-readout">{formatClock(editor.playhead)} <i>/</i> {formatClock(timelineEmpty ? 0 : editor.duration)}</span>
        <button className="icon-button" disabled={timelineEmpty || currentIndex <= 0} title="Next version" onClick={() => versions[currentIndex - 1] && openSafely(versions[currentIndex - 1].id)}><ChevronRight size={17} /></button>
        <button className={`autosave ${editor.dirty ? 'dirty' : ''}`} onClick={editor.saveSrt} disabled={!editor.dirty}>
          <Save size={13} /> {editor.dirty ? 'Unsaved changes · Save' : 'Saved'}
        </button>
      </div>
      <div className="editor-top-actions">
        {editor.activeJobs.length > 0 && <span className="global-job"><i /> {editor.activeJobs.length} running</span>}
        <button className="icon-button" disabled={timelineEmpty} onClick={() => studioApi.revealProject(project.id)} title="Open project folder"><FolderOpen size={17} /></button>
        <a
          className={`button primary export-button ${exportDisabled ? 'disabled' : ''}`}
          aria-disabled={exportDisabled}
          href={`/api/videos/${project.id}/media?audioMode=${editor.audioMode}&renderEffects=true`}
          onClick={(event) => { if (exportDisabled) event.preventDefault(); }}
        ><Share2 size={16} /> Export</a>
      </div>
    </header>
  );
}
