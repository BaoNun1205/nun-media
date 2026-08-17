import { Check, Download, Folder, FolderOpen, LoaderCircle, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { studioApi } from '../../services/api';
import type { EditorController } from '../../hooks/useEditorController';
import { JobProgress } from '../common/JobProgress';

type ExportState = 'CONFIG' | 'EXPORTING' | 'DONE' | 'ERROR';
type Resolution = '720p' | '1080p' | '1440p' | '4K';
type AspectRatio = 'project' | '16:9' | '9:16' | '1:1' | '4:3';

const RESOLUTIONS: Resolution[] = ['720p', '1080p', '1440p', '4K'];
const ASPECT_RATIOS: Array<[AspectRatio, string]> = [['project', 'Theo dự án'], ['16:9', '16:9'], ['9:16', '9:16'], ['1:1', '1:1'], ['4:3', '4:3']];
const FPS_OPTIONS = [24, 25, 30, 50, 60];

export function ExportVideoModal({ editor, open, onClose }: { editor: EditorController; open: boolean; onClose: () => void }) {
  const workspaceId = editor.project.workspaceId;
  const [state, setState] = useState<ExportState>('CONFIG');
  const [fileName, setFileName] = useState(editor.project.title || 'Untitled Video');
  const [outputDirectory, setOutputDirectory] = useState('');
  const [resolution, setResolution] = useState<Resolution>('1080p');
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('project');
  const [fps, setFps] = useState(30);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const job = useMemo(() => editor.jobs.find((item) => item.id === jobId), [editor.jobs, jobId]);
  const completedPath = String(job?.result?.outputPath || job?.result?.path || '');

  useEffect(() => {
    if (!open) return;
    setState('CONFIG');
    setError('');
    setJobId(null);
    setFileName(editor.project.title || 'Untitled Video');
    setResolution('1080p');
    setAspectRatio('project');
    setFps(30);
    const defaultsRequest = workspaceId ? studioApi.exportDefaults(workspaceId) : studioApi.videoExportDefaults(editor.project.id);
    defaultsRequest
      .then((defaults) => {
        setFileName(defaults.fileName || editor.project.title || 'Untitled Video');
        setOutputDirectory(defaults.outputDirectory || '');
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load export defaults'));
  }, [open, workspaceId, editor.project.id, editor.project.title]);

  useEffect(() => {
    if (!job || state !== 'EXPORTING') return;
    if (job.status === 'completed') setState('DONE');
    if (job.status === 'error' || job.status === 'cancelled') {
      setError(job.detail || 'Export failed');
      setState('ERROR');
    }
  }, [job?.status, job?.detail, state]);

  if (!open) return null;

  async function chooseFolder() {
    try {
      const result = await studioApi.selectExportFolder(outputDirectory);
      setOutputDirectory(result.path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to choose folder');
    }
  }

  async function startExport() {
    try {
      setError('');
      const result = workspaceId
        ? (
            await studioApi.saveWorkspaceTimeline(workspaceId, editor.timelineItems, editor.timelineState, editor.timelineScene),
            await studioApi.exportProject(workspaceId, {
              fileName,
              outputDirectory,
              resolution,
              aspectRatio,
              fps,
              timelineState: editor.timelineState,
              sceneState: editor.timelineScene,
            })
          )
        : await studioApi.exportVideo(editor.project.id, { fileName, outputDirectory, resolution, aspectRatio, fps, timelineState: editor.timelineState, sceneState: editor.timelineScene });
      setJobId(result.jobId);
      setState('EXPORTING');
      await editor.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start export');
      setState('ERROR');
    }
  }

  async function openFolder() {
    if (!completedPath) return;
    try {
      await studioApi.revealPath(completedPath);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to open folder');
      setState('ERROR');
    }
  }

  return (
    <div className="export-modal-backdrop" role="presentation">
      <section className="export-modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <header className="export-modal-header">
          <div>
            <h2 id="export-title">Export Video</h2>
            <p>{state === 'CONFIG' ? outputSizeLabel(resolution, aspectRatio, fps, editor.timelineState.canvas) : fileNameWithExtension(fileName)}</p>
          </div>
          <button className="icon-button" onClick={onClose} disabled={state === 'EXPORTING'} title="Close"><X size={17} /></button>
        </header>

        {state === 'CONFIG' && (
          <div className="export-modal-body">
            {error && <p className="export-inline-error">{error}</p>}
            <label>
              <span>Tên file</span>
              <div className="export-file-row"><input value={fileName} onChange={(event) => setFileName(event.target.value)} /><small>.mp4</small></div>
            </label>
            <label>
              <span>Vị trí lưu</span>
              <div className="export-path-row"><input value={outputDirectory} onChange={(event) => setOutputDirectory(event.target.value)} /><button type="button" onClick={chooseFolder}><Folder size={15} /> Chọn</button></div>
            </label>
            <label>
              <span>Độ phân giải</span>
              <select value={resolution} onChange={(event) => setResolution(event.target.value as Resolution)}>{RESOLUTIONS.map((item) => <option key={item} value={item}>{item}</option>)}</select>
            </label>
            <label>
              <span>Tỷ lệ khung hình</span>
              <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value as AspectRatio)}>{ASPECT_RATIOS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            </label>
            {aspectRatio !== 'project' && <p className="export-warning">Changing aspect ratio may change the composition.</p>}
            <label>
              <span>Tốc độ khung hình</span>
              <select value={fps} onChange={(event) => setFps(Number(event.target.value))}>{FPS_OPTIONS.map((item) => <option key={item} value={item}>{item} FPS</option>)}</select>
            </label>
          </div>
        )}

        {state === 'EXPORTING' && (
          <div className="export-modal-status">
            <LoaderCircle className="spin" size={30} />
            <h3>Exporting video...</h3>
            {job ? <JobProgress job={job} /> : <div className="job-progress"><div className="job-progress-title"><span>Preparing timeline...</span><strong>0%</strong></div><div className="progress-track"><i style={{ width: '0%' }} /></div></div>}
            <p>{fileNameWithExtension(fileName)}</p>
          </div>
        )}

        {state === 'DONE' && (
          <div className="export-modal-status done">
            <Check size={32} />
            <h3>Export completed</h3>
            <code>{completedPath}</code>
          </div>
        )}

        {state === 'ERROR' && (
          <div className="export-modal-status error">
            <h3>Export failed</h3>
            <p>{error}</p>
          </div>
        )}

        <footer className="export-modal-footer">
          {state === 'CONFIG' && <><button onClick={onClose}>Hủy</button><button className="primary" onClick={startExport}><Download size={16} /> Xuất video</button></>}
          {state === 'EXPORTING' && <button disabled>Rendering...</button>}
          {state === 'DONE' && <><button onClick={openFolder}><FolderOpen size={16} /> Mở thư mục</button><button className="primary" onClick={onClose}>Xong</button></>}
          {state === 'ERROR' && <><button onClick={() => setState('CONFIG')}>Retry</button><button className="primary" onClick={onClose}>Close</button></>}
        </footer>
      </section>
    </div>
  );
}

function fileNameWithExtension(value: string) {
  const trimmed = value.trim() || 'Untitled Video';
  return trimmed.toLowerCase().endsWith('.mp4') ? trimmed : `${trimmed}.mp4`;
}

function outputSizeLabel(resolution: Resolution, aspectRatio: AspectRatio, fps: number, canvas: { width: number; height: number }) {
  const height = resolution === '720p' ? 720 : resolution === '1080p' ? 1080 : resolution === '1440p' ? 1440 : 2160;
  const ratio = aspectRatio === 'project' ? canvas.width / canvas.height : aspectRatio === '16:9' ? 16 / 9 : aspectRatio === '9:16' ? 9 / 16 : aspectRatio === '4:3' ? 4 / 3 : 1;
  const width = ratio >= 1 ? Math.round(height * ratio) : height;
  const outHeight = ratio >= 1 ? height : Math.round(height / ratio);
  return `${even(width)} x ${even(outHeight)} @ ${fps} FPS`;
}

function even(value: number) {
  return value % 2 === 0 ? value : value + 1;
}
