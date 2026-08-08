import { useEffect, useMemo, useState } from 'react';
import { ClipboardPaste, Download, ExternalLink, FolderOpen, Link2, Play, Trash2 } from 'lucide-react';
import { JobProgress } from '../components/common/JobProgress';
import { ProjectPickerModal } from '../components/common/ProjectPickerModal';
import { request, studioApi } from '../services/api';
import type { Job, Project, WorkspaceProject } from '../types/studio';

const DOWNLOAD_HISTORY_KEY = 'stitch_studio.download_history.v1';
const MAX_DOWNLOAD_HISTORY = 50;
const DOWNLOADER_SOURCES = new Set(['downloaded video', 'lazy-downloader', 'douyin-downloader', 'lux', 'f2', 'yt-dlp']);

function downloadVideoIds(job: Job) {
  return Array.isArray(job.result) ? job.result.map(Number)
    : Array.isArray(job.result?.videoIds) ? job.result.videoIds.map(Number)
    : job.result?.videoId ? [Number(job.result.videoId)] : [];
}

function jobCreatedTime(job: Job) {
  const value = job.createdAt;
  if (typeof value === 'number') {
    return value < 1e11 ? value * 1000 : value;
  }
  let strValue = String(value);
  if (strValue.length === 19 && strValue.includes(' ')) {
    strValue = strValue.replace(' ', 'T') + 'Z';
  }
  const parsed = value ? Date.parse(strValue) : Number.NaN;
  return Number.isNaN(parsed) ? (job.id < 0 ? -job.id * 1000 : job.id) : parsed;
}

function readDownloadHistory(): Job[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(DOWNLOAD_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((job) => job?.kind === 'download' && job.status === 'completed') as Job[] : [];
  } catch {
    return [];
  }
}

function mergeDownloadHistory(current: Job[], incoming: Job[]) {
  const merged = new Map<string, Job>();
  [...current, ...incoming].forEach((job) => {
    const ids = downloadVideoIds(job);
    if (!ids.length || job.status !== 'completed') return;
    merged.set(ids.join(','), job);
  });
  return [...merged.values()].sort((left, right) => jobCreatedTime(right) - jobCreatedTime(left)).slice(0, MAX_DOWNLOAD_HISTORY);
}

function projectToDownloadJob(project: Project): Job {
  return {
    id: -project.id,
    kind: 'download',
    videoId: project.id,
    title: project.title,
    status: 'completed',
    progress: 1,
    detail: 'Downloaded',
    result: { videoId: project.id },
    createdAt: project.createdAt,
  };
}

function workspaceVideosToDownloadJobs(workspaceProjects: WorkspaceProject[]) {
  const byId = new Map<number, Project>();
  workspaceProjects.forEach((workspace) => {
    workspace.videos.forEach((video) => {
      if (video?.id && video.mediaType === 'video') byId.set(video.id, video);
    });
  });
  return [...byId.values()].map(projectToDownloadJob);
}

export function DownloadsPage({ jobs, projects, workspaceProjects, onRefresh, onOpenEditor, onOpenWorkspace }: { jobs: Job[]; projects: Project[]; workspaceProjects: WorkspaceProject[]; onRefresh: () => Promise<void>; onOpenEditor: (id: number) => void; onOpenWorkspace?: (project: WorkspaceProject) => void }) {
  const [url, setUrl] = useState('');
  const [preview, setPreview] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingVideoId, setPendingVideoId] = useState<number | null>(null);
  const [downloadHistory, setDownloadHistory] = useState<Job[]>(readDownloadHistory);
  const downloadJobs = useMemo(() => jobs.filter((job) => job.kind === 'download'), [jobs]);
  const activeDownloadJobs = useMemo(() => downloadJobs.filter((job) => ['queued', 'running'].includes(job.status)), [downloadJobs]);
  const completedDownloadJobs = useMemo(() => downloadJobs.filter((job) => job.status === 'completed' && downloadVideoIds(job).length), [downloadJobs]);
  const storageDownloadJobs = useMemo(() => projects.filter((project) => DOWNLOADER_SOURCES.has(project.source)).map(projectToDownloadJob), [projects]);
  const workspaceDownloadJobs = useMemo(() => workspaceVideosToDownloadJobs(workspaceProjects), [workspaceProjects]);
  const historicalDownloadJobs = useMemo(() => mergeDownloadHistory(downloadHistory, [...workspaceDownloadJobs, ...storageDownloadJobs, ...completedDownloadJobs]), [downloadHistory, workspaceDownloadJobs, storageDownloadJobs, completedDownloadJobs]);

  useEffect(() => {
    if (completedDownloadJobs.length) {
      setDownloadHistory((current) => mergeDownloadHistory(current, completedDownloadJobs));
    }
  }, [completedDownloadJobs]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(DOWNLOAD_HISTORY_KEY, JSON.stringify(downloadHistory));
  }, [downloadHistory]);

  async function queue() {
    if (!url.trim() || busy) return;
    setBusy(true);
    try {
      const detected = await request<{ url: string }>('/download/preview', { method: 'POST', body: JSON.stringify({ url: url.trim() }) });
      setPreview(detected.url);
      const result = await request<{ jobId: number }>('/download', { method: 'POST', body: JSON.stringify({ url: url.trim() }) });
      setMessage(`Download #${result.jobId} was added to the queue.`);
      setUrl('');
      await onRefresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Unable to queue download');
    } finally { setBusy(false); }
  }

  async function createAndOpenProject(videoId: number, jobTitle: string) {
    if (!onOpenWorkspace) return;
    try {
      setBusy(true);
      const title = window.prompt('Project name', jobTitle) || jobTitle;
      try { await request(`/videos/${videoId}/subtitle/effect`, { method: 'DELETE' }); } catch (e) { /* ignore */ }
      const result = await studioApi.createWorkspaceProject(title, []);
      await studioApi.attachWorkspaceVideos(result.project.id, [videoId]);
      await onRefresh();
      onOpenWorkspace(result.project);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to create project');
    } finally {
      setBusy(false);
    }
  }

  async function addToProjects(videoId: number, projectIds: number[]) {
    if (!projectIds.length) {
      setMessage('Create a project first, then add this video.');
      return;
    }
    try {
      for (const projectId of projectIds) await studioApi.attachWorkspaceVideos(projectId, [videoId]);
      await onRefresh();
      setPendingVideoId(null);
      setMessage(`Added video to ${projectIds.length} project${projectIds.length === 1 ? '' : 's'}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to add video to project');
    }
  }

  async function handleDeleteVideo(videoId: number) {
    if (!window.confirm('Are you sure you want to delete this video and its files?')) return;
    try {
      setBusy(true);
      await request(`/videos/${videoId}`, { method: 'DELETE' });
      await onRefresh();
      setDownloadHistory(current => current.filter(j => !downloadVideoIds(j).includes(videoId)));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete video');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page downloads-page">
      <header className="page-header"><div><span className="eyebrow">Acquire</span><h1>Downloads</h1><p>Paste a link, verify the source, then follow every job in one place.</p></div><button className="danger" disabled={!downloadJobs.some((job) => job.status === 'error')} onClick={async () => { await request('/jobs/failed', { method: 'DELETE' }); await onRefresh(); }}><Trash2 size={16} /> Clear failed</button></header>
      <div className="download-composer">
        <div className="composer-icon"><Link2 size={22} /></div>
        <div><label>Video URL</label><input value={url} onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && queue()} placeholder="Paste a TikTok, Douyin, or direct video URL…" /></div>
        <button className="quiet" onClick={async () => setUrl((await navigator.clipboard.readText()).trim())}><ClipboardPaste size={16} /> Paste</button>
        <button className="primary" onClick={queue} disabled={!url.trim() || busy}><Download size={16} /> {busy ? 'Checking…' : 'Download'}</button>
      </div>
      {(preview || message) && <div className="inline-notice">{preview && <span><ExternalLink size={14} /> Detected: {preview}</span>} {message}</div>}
      <div className="jobs-panel">
        <div className="section-heading"><div><h2>Active downloads</h2><p>{activeDownloadJobs.length} jobs</p></div></div>
        {activeDownloadJobs.map((job) => {
          const ids = downloadVideoIds(job);
          return <article className="job-row" key={job.id}>
            <div className="job-kind"><Download size={17} /><span><strong>{job.title}</strong><small>Job #{job.id}</small></span></div>
            <JobProgress job={job} />
            <span className={`status-pill ${job.status}`}>{job.status}</span>
            <div className="row-actions">
              {['queued', 'running'].includes(job.status) && <button className="danger" onClick={async () => { await request(`/jobs/${job.id}/cancel`, { method: 'POST' }); await onRefresh(); }}>Cancel</button>}
              {ids[0] && <button onClick={() => setPendingVideoId(ids[0])}>Add</button>}
              {ids[0] && <button className="primary" onClick={() => createAndOpenProject(ids[0], job.title)} disabled={busy}><Play size={15} /> Open Editor</button>}
              {ids[0] && <button onClick={() => studioApi.revealProject(ids[0])}><FolderOpen size={15} /> Open Folder</button>}
              {ids[0] && <button className="danger icon-button" style={{ padding: '0 8px' }} onClick={() => handleDeleteVideo(ids[0])} disabled={busy} title="Delete"><Trash2 size={15} /></button>}
            </div>
          </article>;
        })}
        {!activeDownloadJobs.length && <div className="empty-row">No active downloads.</div>}
      </div>
      <div className="jobs-panel">
        <div className="section-heading"><div><h2>Download history</h2><p>{historicalDownloadJobs.length} items</p></div></div>
        {historicalDownloadJobs.map((job) => {
          const ids = downloadVideoIds(job);
          return <article className="job-row" key={`${job.id}-${ids.join('-')}`}>
            <div className="job-kind"><Download size={17} /><span><strong>{job.title}</strong><small>Job #{job.id}</small></span></div>
            <JobProgress job={job} />
            <span className={`status-pill ${job.status}`}>{job.status}</span>
            <div className="row-actions">
              {ids[0] && <button onClick={() => setPendingVideoId(ids[0])}>Add</button>}
              {ids[0] && <button className="primary" onClick={() => createAndOpenProject(ids[0], job.title)} disabled={busy}><Play size={15} /> Open Editor</button>}
              {ids[0] && <button onClick={() => studioApi.revealProject(ids[0])}><FolderOpen size={15} /> Open Folder</button>}
              {ids[0] && <button className="danger icon-button" style={{ padding: '0 8px' }} onClick={() => handleDeleteVideo(ids[0])} disabled={busy} title="Delete"><Trash2 size={15} /></button>}
            </div>
          </article>;
        })}
        {!historicalDownloadJobs.length && <div className="empty-row">No completed downloads yet.</div>}
      </div>
      <ProjectPickerModal
        open={pendingVideoId !== null}
        projects={workspaceProjects}
        title="Add video to project"
        description="Choose one or more projects that should receive this downloaded video."
        confirmLabel="Add video"
        onClose={() => setPendingVideoId(null)}
        onConfirm={(projectIds) => pendingVideoId ? addToProjects(pendingVideoId, projectIds) : undefined}
      />
    </section>
  );
}
