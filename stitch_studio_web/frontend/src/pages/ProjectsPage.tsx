import { useMemo, useState } from 'react';
import { Captions, FileAudio, FileVideo2, FolderOpen, Grid2X2, List, LoaderCircle, Pencil, Play, Plus, Search, Trash2 } from 'lucide-react';
import { formatDuration, formatSize, projectStatus } from '../lib/studio';
import { studioApi } from '../services/api';
import type { Job, WorkspaceProject } from '../types/studio';

interface Props {
  projects: WorkspaceProject[];
  jobs: Job[];
  onOpen: (project: WorkspaceProject) => void;
  onRefresh: () => Promise<void>;
}

export function ProjectsPage({ projects, jobs, onOpen, onRefresh }: Props) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState<'recent' | 'name' | 'duration'>('recent');
  const [layout, setLayout] = useState<'grid' | 'list'>('grid');
  const [message, setMessage] = useState('');
  const [creating, setCreating] = useState(false);
  const [openingLibrary, setOpeningLibrary] = useState(false);

  const visible = useMemo(() => projects.filter((project) => {
    const matchesQuery = `${project.title} ${project.projectId}`.toLowerCase().includes(query.toLowerCase());
    const primaryStatus = project.primaryVideo ? projectStatus(project.primaryVideo).toLowerCase() : '';
    const assetKinds = project.assets.map((asset) => asset.kind).join(' ');
    return matchesQuery && (filter === 'all' || primaryStatus.includes(filter) || assetKinds.includes(filter));
  }).sort((a, b) => sort === 'name'
    ? a.title.localeCompare(b.title)
    : sort === 'duration'
      ? b.durationMs - a.durationMs
      : String(b.createdAt || '').localeCompare(String(a.createdAt || ''))), [projects, query, filter, sort]);

  async function rename(project: WorkspaceProject) {
    const title = window.prompt('Project name', project.title)?.trim();
    if (!title || title === project.title) return;
    await studioApi.renameWorkspaceProject(project.id, title);
    setMessage(`Renamed to "${title}".`);
    await onRefresh();
  }

  async function remove(project: WorkspaceProject) {
    const count = project.videos.length + project.assets.filter((asset) => asset.kind !== 'video').length;
    if (!window.confirm(`Delete "${project.title}" and its files?\n\nThis removes the project plus ${count} video/subtitle/audio item(s) managed by the app.`)) return;
    const result = await studioApi.deleteWorkspaceProject(project.id);
    setMessage(`Deleted "${project.title}" and ${result.deletedFiles || 0} file(s).`);
    await onRefresh();
  }

  async function reveal(project: WorkspaceProject) {
    if (!project.primaryVideoId) return;
    await studioApi.revealProject(project.primaryVideoId);
    setMessage(`Opened the folder for "${project.title}".`);
  }

  async function openLibraryFolder() {
    setOpeningLibrary(true);
    try {
      const result = await studioApi.revealProjectLibrary();
      setMessage(`Clean folder: ${result.path}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to open app media folder');
    } finally {
      setOpeningLibrary(false);
    }
  }

  async function createProject() {
    if (creating) return;
    setCreating(true);
    try {
      const title = window.prompt('Project name', `Project ${new Date().toLocaleDateString()}`)?.trim();
      if (!title) return;
      const result = await studioApi.createWorkspaceProject(title, []);
      setMessage(`Created "${result.project.title}".`);
      await onRefresh();
      onOpen(result.project);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to create project');
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="page projects-page">
      <header className="page-header">
        <div><span className="eyebrow">Workspace</span><h1>Projects</h1><p>Build with videos, subtitles, and audio as reusable assets.</p></div>
        <div className="header-actions">
          <button onClick={openLibraryFolder} disabled={openingLibrary}><FolderOpen size={16} /> {openingLibrary ? 'Opening...' : 'Clean'}</button>
          <button className="primary" onClick={createProject} disabled={creating}><Plus size={16} /> {creating ? 'Creating...' : 'New Project'}</button>
        </div>
      </header>
      <div className="project-toolbar">
        <label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search projects" /></label>
        <select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter projects">
          <option value="all">All assets</option><option value="video">Video</option><option value="srt">SRT</option><option value="audio">Audio</option>
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} aria-label="Sort projects"><option value="recent">Recently updated</option><option value="name">Name A-Z</option><option value="duration">Longest first</option></select>
        <div className="view-toggle"><button className={layout === 'grid' ? 'active' : ''} onClick={() => setLayout('grid')} aria-label="Grid view"><Grid2X2 size={16} /></button><button className={layout === 'list' ? 'active' : ''} onClick={() => setLayout('list')} aria-label="List view"><List size={17} /></button></div>
      </div>
      {message && <div className="inline-notice">{message}</div>}
      <div className={`project-collection ${layout}`}>
        {visible.map((project) => {
          const exportJob = jobs.find((job) => job.kind === 'project-export' && job.videoId === -project.id && ['queued', 'running'].includes(job.status));
          const exportProgress = exportJob ? progressPercent(exportJob.progress) : 0;

          return <article className="project-card" key={project.id}>
            <button className="project-thumb" onClick={() => onOpen(project)}>
              {project.primaryVideoId && <img src={`/api/videos/${project.primaryVideoId}/thumbnail`} loading="lazy" alt="" />}
              <span className="thumb-shade" />
              <span className="play-orb"><Play size={17} fill="currentColor" /></span>
              <time>{formatDuration(project.durationMs)}</time>
            </button>
            <div className="project-card-body">
              <div className="project-title-row"><div><h2>{project.title}</h2><p>{project.projectId} · {project.videos.length} video(s)</p></div></div>
              <div className="status-chips">
                <span className={project.videos.length ? 'ready' : ''}><FileVideo2 size={12} /> {project.videos.length} Video</span>
                <span className={project.assets.some((asset) => asset.kind === 'srt') ? 'ready' : ''}><Captions size={12} /> {project.assets.filter((asset) => asset.kind === 'srt').length} SRT</span>
                <span className={project.assets.some((asset) => asset.kind === 'audio') ? 'voice' : ''}><FileAudio size={12} /> {project.assets.filter((asset) => asset.kind === 'audio').length} Audio</span>
              </div>
              {exportJob && <div className="project-export-progress" title={exportJob.detail || 'Exporting video'}>
                <div><span><LoaderCircle className="spin" size={13} /> {exportJob.status === 'queued' ? 'Chờ xuất video' : 'Đang xuất video'}</span><strong>{exportProgress}%</strong></div>
                <i style={{ width: `${Math.max(2, exportProgress)}%` }} />
              </div>}
              <div className="project-meta"><span>{formatSize(project.sizeBytes)}</span><span>{project.createdAt?.slice(0, 10) || 'Local'}</span></div>
              <div className="project-actions">
                <button className="primary" onClick={() => onOpen(project)}><Play size={15} /> Open editor</button>
                <button className="icon-button" onClick={() => rename(project)} title="Rename"><Pencil size={15} /></button>
                <button className="icon-button" disabled={!project.primaryVideoId} onClick={() => reveal(project)} title="Reveal folder"><FolderOpen size={15} /></button>
                <button className="icon-button danger" onClick={() => remove(project)} title="Delete project and files"><Trash2 size={15} /></button>
              </div>
            </div>
          </article>
        })}
        {!visible.length && <div className="empty-state"><Captions size={28} /><strong>No matching projects</strong><span>Create a project, then add video, subtitle, and audio assets inside the editor.</span></div>}
      </div>
    </section>
  );
}

function progressPercent(progress?: number) {
  const value = Number(progress || 0);
  return Math.round(Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)));
}
