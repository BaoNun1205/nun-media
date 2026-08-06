import { useEffect, useMemo, useRef, useState } from 'react';
import { Captions, ClipboardPaste, Download, Eraser, FolderOpen, FolderPlus, History, Play, RotateCw, Square, Trash2, Volume2, WandSparkles, X } from 'lucide-react';
import { JobProgress } from '../components/common/JobProgress';
import { ProjectPickerModal } from '../components/common/ProjectPickerModal';
import { CAPCUT_LANGUAGES, POCKET_LANGUAGES, TTS_FIT } from '../lib/studio';
import { API_BASE, request, studioApi } from '../services/api';
import type { Asset, Job, VoiceOption, WorkspaceProject } from '../types/studio';

interface EditableLine { index: number; startLabel: string; endLabel: string; text: string }

function parseSrt(content: string): EditableLine[] {
  return content.replace(/\r/g, '').split(/\n{2,}/).map((block, position) => {
    const lines = block.split('\n').filter(Boolean);
    const timeIndex = lines.findIndex((line) => line.includes('-->'));
    if (timeIndex < 0) return null;
    const [startLabel, endLabel] = lines[timeIndex].split('-->').map((value) => value.trim());
    return { index: /^\d+$/.test(lines[timeIndex - 1] || '') ? Number(lines[timeIndex - 1]) : position + 1, startLabel, endLabel, text: lines.slice(timeIndex + 1).join('\n') };
  }).filter(Boolean) as EditableLine[];
}

function serialize(lines: EditableLine[]) {
  return lines.map((line, index) => `${index + 1}\n${line.startLabel} --> ${line.endLabel}\n${line.text.trim()}\n`).join('\n');
}

const TTS_STATE_KEY = 'stitch_studio.standalone_tts.state.v1';
const MAX_TTS_HISTORY = 24;

interface StoredTtsState {
  content: string;
  mode: 'text' | 'srt';
  engine: string;
  language: string;
  voice: string;
  rate: string;
  jobId: number | null;
  message: string;
  output: Asset | null;
  history: Asset[];
}

const DEFAULT_TTS_STATE: StoredTtsState = {
  content: '',
  mode: 'text',
  engine: 'vieneu',
  language: 'vi-VN',
  voice: 'default',
  rate: '1.0',
  jobId: null,
  message: '',
  output: null,
  history: [],
};

function readStoredTtsState(): StoredTtsState {
  if (typeof window === 'undefined') return DEFAULT_TTS_STATE;
  try {
    const raw = window.localStorage.getItem(TTS_STATE_KEY);
    if (!raw) return DEFAULT_TTS_STATE;
    const parsed = JSON.parse(raw) as Partial<StoredTtsState>;
    return {
      ...DEFAULT_TTS_STATE,
      ...parsed,
      mode: parsed.mode === 'srt' ? 'srt' : 'text',
      jobId: typeof parsed.jobId === 'number' ? parsed.jobId : null,
      output: parsed.output && typeof parsed.output.id === 'number' ? parsed.output as Asset : null,
      history: Array.isArray(parsed.history) ? parsed.history.filter((item) => item && typeof item.id === 'number') as Asset[] : [],
    };
  } catch {
    return DEFAULT_TTS_STATE;
  }
}

function isGeneratedStandaloneJob(job: Job) {
  return job.kind === 'standalone-tts' && !/voice preview/i.test(job.title || '');
}

function latestJob(jobs: Job[]) {
  return [...jobs].sort((left, right) => {
    const leftTime = left.createdAt ? Date.parse(left.createdAt) : 0;
    const rightTime = right.createdAt ? Date.parse(right.createdAt) : 0;
    return rightTime - leftTime || right.id - left.id;
  })[0];
}

function formatAssetTime(asset: Asset) {
  if (!asset.createdAt) return 'Generated voice';
  const date = new Date(asset.createdAt);
  if (Number.isNaN(date.getTime())) return 'Generated voice';
  return date.toLocaleString();
}

function mergeAssetHistory(current: Asset[], incoming: Asset[]) {
  const byId = new Map<number, Asset>();
  [...incoming, ...current].forEach((asset) => {
    if (asset?.id) byId.set(asset.id, asset);
  });
  return [...byId.values()].sort((left, right) => {
    const leftTime = left.createdAt ? Date.parse(left.createdAt) : 0;
    const rightTime = right.createdAt ? Date.parse(right.createdAt) : 0;
    return rightTime - leftTime || right.id - left.id;
  }).slice(0, MAX_TTS_HISTORY);
}

export function StandaloneTTSPage({ jobs, workspaceProjects, voices, loadVoices, refresh }: {
  jobs: Job[]; workspaceProjects: WorkspaceProject[]; voices: VoiceOption[]; loadVoices: (engine?: string, language?: string) => Promise<VoiceOption[]>; refresh: () => Promise<void>;
}) {
  const initialStateRef = useRef<StoredTtsState | null>(null);
  if (!initialStateRef.current) initialStateRef.current = readStoredTtsState();
  const initialState = initialStateRef.current;
  const [content, setContent] = useState(initialState.content);
  const [mode, setMode] = useState<'text' | 'srt'>(initialState.mode);
  const [engine, setEngine] = useState(initialState.engine);
  const [language, setLanguage] = useState(initialState.language);
  const [voice, setVoice] = useState(initialState.voice);
  const [rate, setRate] = useState(initialState.rate);
  const [jobId, setJobId] = useState<number | null>(initialState.jobId);
  const [message, setMessage] = useState(initialState.message);
  const [output, setOutput] = useState<Asset | null>(initialState.output);
  const [history, setHistory] = useState<Asset[]>(initialState.history);
  const [runMode, setRunMode] = useState<'generate' | 'preview'>('generate');
  const [pendingAssetId, setPendingAssetId] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const lines = useMemo(() => parseSrt(content), [content]);
  const effectiveMode = lines.length ? 'srt' : mode;
  const job = jobs.find((item) => item.id === jobId);
  const busy = job && ['queued', 'running'].includes(job.status);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const generatedRun = runMode === 'generate';
    window.localStorage.setItem(TTS_STATE_KEY, JSON.stringify({
      content,
      mode,
      engine,
      language,
      voice,
      rate,
      jobId: generatedRun ? jobId : null,
      message: generatedRun ? message : '',
      output: generatedRun ? output : null,
      history,
    }));
  }, [content, mode, engine, language, voice, rate, jobId, message, output, history, runMode]);

  useEffect(() => {
    request<{ assets: Asset[] }>('/tts/history?limit=50')
      .then((result) => setHistory((current) => mergeAssetHistory(current, result.assets || [])))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (jobId && job) return;
    const activeJob = latestJob(jobs.filter((item) => isGeneratedStandaloneJob(item) && ['queued', 'running'].includes(item.status)));
    if (activeJob) {
      setRunMode('generate');
      setJobId(activeJob.id);
      setMessage(`Restored TTS job #${activeJob.id}.`);
    }
  }, [jobs, job, jobId]);

  useEffect(() => { loadVoices(engine, language).catch(() => undefined); }, [engine, language, loadVoices]);
  useEffect(() => {
    if (job?.status === 'completed' && job.result?.asset) {
      const asset = job.result.asset as Asset;
      setOutput(asset);
      if (runMode === 'generate') {
        setHistory((current) => mergeAssetHistory(current, [asset]));
      }
      setMessage(runMode === 'preview' ? 'Preview audio is ready.' : 'Voice audio is ready.');
    }
    if (job?.status === 'error') setMessage(job.detail || 'Voice generation failed.');
  }, [job?.status, job?.detail, job?.result?.asset?.id, runMode]);
  useEffect(() => { if (!voices.some((item) => item.id === voice)) setVoice(voices[0]?.id || 'default'); }, [voices, voice]);

  function changeEngine(next: string) {
    setEngine(next); setVoice('default'); setRate('1.0');
    setLanguage(next === 'capcut' ? 'en-US' : next === 'pocket' ? 'english' : 'vi-VN');
  }

  function clearTts() {
    setContent('');
    setMode('text');
    setJobId(null);
    setMessage('');
    setOutput(null);
    setRunMode('generate');
  }

  async function generate(preview = false) {
    const value = preview ? (engine === 'vieneu' ? 'Xin chào, đây là bản nghe thử giọng đọc.' : 'Hello, this is a voice preview.') : content.trim();
    if (!value || busy) return;
    try {
      const result = await request<{ jobId: number }>('/tts', { method: 'POST', body: JSON.stringify({
        title: preview ? 'Voice Preview' : effectiveMode === 'srt' ? `SRT TTS (${lines.length} lines)` : 'Text To Speech',
        content: value, inputMode: preview ? 'text' : effectiveMode, voice, engine, language,
        rate: engine === 'vieneu' ? rate : '1.0', timingMode: preview || effectiveMode === 'text' ? 'plain' : 'srt_slot', ...TTS_FIT,
      }) });
      setRunMode(preview ? 'preview' : 'generate'); setJobId(result.jobId); setMessage(`Queued TTS job #${result.jobId}.`); setOutput(null); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Unable to generate voice'); }
  }

  async function stop() {
    if (!job?.id) return;
    await request(`/jobs/${job.id}/cancel`, { method: 'POST' }); setMessage(`Stopping job #${job.id}…`); await refresh();
  }

  async function addOutputToProjects(projectIds: number[]) {
    if (!pendingAssetId) return;
    await Promise.all(projectIds.map((projectId) => studioApi.attachWorkspaceAssets(projectId, [pendingAssetId])));
    setPendingAssetId(null);
    setMessage(`Added voice audio to ${projectIds.length} project${projectIds.length === 1 ? '' : 's'}.`);
    await refresh();
  }

  function openAddProject(assetId: number) {
    setPendingAssetId(assetId);
    setHistoryOpen(false);
  }

  async function revealAsset(assetId: number) {
    await request(`/assets/${assetId}/reveal`, { method: 'POST' });
  }

  async function deleteHistoryAsset(assetId: number) {
    const result = await request<{ deletedAssetIds: number[] }>(`/assets/${assetId}`, { method: 'DELETE' });
    const deleted = new Set(result.deletedAssetIds || [assetId]);
    setHistory((current) => current.filter((asset) => !deleted.has(asset.id)));
    if (output && deleted.has(output.id)) setOutput(null);
    setMessage('Deleted voice audio.');
    await refresh();
  }

  function updateLine(index: number, text: string) {
    setContent(serialize(lines.map((line) => line.index === index ? { ...line, text } : line)));
  }

  return (
    <section className="page tts-page">
      <header className="page-header"><div><span className="eyebrow">Voice lab</span><h1>Text to Speech</h1><p>Create a standalone WAV from plain text or a timed subtitle script.</p></div><div className="header-actions"><button className="quiet" disabled={Boolean(busy)} onClick={clearTts}><Eraser size={16} /> Clear</button><button className="quiet" onClick={async () => { const text = await navigator.clipboard.readText(); setContent(text); setMode(parseSrt(text).length ? 'srt' : 'text'); }}><ClipboardPaste size={16} /> Paste</button>{busy && <button className="danger" onClick={stop}><Square size={14} /> Stop</button>}<button className="primary" disabled={!content.trim() || Boolean(busy)} onClick={() => generate()}><WandSparkles size={16} /> Generate WAV</button></div></header>
      <div className="tts-layout">
        <section className="editor-card">
          <div className="card-bar"><div className="segmented"><button className={effectiveMode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>Plain text</button><button className={effectiveMode === 'srt' ? 'active' : ''} onClick={() => setMode('srt')}><Captions size={14} /> Timed SRT</button></div><span>{effectiveMode === 'srt' ? `${lines.length} lines` : `${content.trim().split(/\s+/).filter(Boolean).length} words`}</span></div>
          <textarea className="script-input" value={content} onChange={(event) => { setContent(event.target.value); if (parseSrt(event.target.value).length) setMode('srt'); }} placeholder={effectiveMode === 'srt' ? '1\n00:00:00,000 --> 00:00:03,000\nPaste SRT here' : 'Write or paste the text you want to hear…'} />
          {effectiveMode === 'srt' && <div className="srt-edit-list">{lines.map((line) => <div className="srt-edit-row" key={line.index}><span><strong>#{line.index}</strong><small>{line.startLabel}<br />{line.endLabel}</small></span><textarea value={line.text} onChange={(event) => updateLine(line.index, event.target.value)} /></div>)}</div>}
        </section>
        <aside className="voice-card">
          <div className="voice-card-heading"><Volume2 size={19} /><div><h2>Voice model</h2><p>Uses the current TTS backend.</p></div></div>
          <label>Engine<select value={engine} onChange={(event) => changeEngine(event.target.value)}><option value="vieneu">VieNeu Vietnamese</option><option value="capcut">CapCut Multi-language</option><option value="pocket">Pocket TTS</option></select></label>
          <label>Language<select value={language} onChange={(event) => setLanguage(event.target.value)}>{engine === 'capcut' ? CAPCUT_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>) : engine === 'pocket' ? POCKET_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>) : <option value="vi-VN">Vietnamese</option>}</select></label>
          <label>Voice<select value={voice} onChange={(event) => setVoice(event.target.value)}>{voices.map((item) => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}</select></label>
          {engine === 'vieneu' && <label>Speaking rate<select value={rate} onChange={(event) => setRate(event.target.value)}><option value=".9">0.9×</option><option value="1.0">1.0×</option><option value="1.1">1.1×</option></select></label>}
          <div className="voice-buttons"><button onClick={() => loadVoices(engine, language)}><RotateCw size={15} /> Refresh</button><button onClick={() => generate(true)} disabled={Boolean(busy)}><Play size={15} /> Preview</button></div>
          {job && <JobProgress job={job} />}
          {message && <p className="tool-message">{message}</p>}
          {output && <div className="audio-output">
            <strong>{output.name}</strong>
            <audio ref={audioRef} controls src={`${API_BASE}/assets/${output.id}/download?preview=${output.id}`} />
            {runMode === 'generate' && <div className="tts-history-actions tts-output-actions">
              <button onClick={() => openAddProject(output.id)}><FolderPlus size={15} /> Add Project</button>
              <a className="button primary" href={`${API_BASE}/assets/${output.id}/download`} download={output.name}><Download size={15} /> Download WAV</a>
              <button onClick={() => revealAsset(output.id)}><FolderOpen size={15} /> Open Folder</button>
            </div>}
          </div>}
          <button className="button full tts-history-button" onClick={() => setHistoryOpen(true)}><History size={15} /> History <span>{history.length}</span></button>
        </aside>
      </div>
      {historyOpen && <div className="project-picker-backdrop" role="presentation" onMouseDown={() => setHistoryOpen(false)}>
        <section className="tts-history-modal" role="dialog" aria-modal="true" aria-label="TTS history" onMouseDown={(event) => event.stopPropagation()}>
          <header className="project-picker-header">
            <div><h2>TTS history</h2><p>{history.length} generated WAV files</p></div>
            <button className="icon-button" onClick={() => setHistoryOpen(false)} aria-label="Close"><X size={17} /></button>
          </header>
          <div className="tts-history-list modal-list">
            {history.map((asset) => <div className="tts-history-item" key={asset.id}>
              <span><strong>{asset.name}</strong><small>{formatAssetTime(asset)}</small></span>
              <audio controls src={`${API_BASE}/assets/${asset.id}/download?preview=${asset.id}`} />
              <div className="tts-history-actions history-modal-actions">
                <button onClick={() => openAddProject(asset.id)}><FolderPlus size={15} /> Add Project</button>
                <a className="button primary" href={`${API_BASE}/assets/${asset.id}/download`} download={asset.name}><Download size={15} /> Download WAV</a>
                <button onClick={() => revealAsset(asset.id)}><FolderOpen size={15} /> Open Folder</button>
                <button className="danger" onClick={() => deleteHistoryAsset(asset.id)}><Trash2 size={15} /> Delete</button>
              </div>
            </div>)}
            {!history.length && <div className="tts-history-empty">No generated WAV yet.</div>}
          </div>
        </section>
      </div>}
      <ProjectPickerModal
        open={pendingAssetId !== null}
        projects={workspaceProjects}
        title="Add voice audio"
        description="Choose the project that should use this generated WAV."
        confirmLabel="Add Project"
        onClose={() => setPendingAssetId(null)}
        onConfirm={addOutputToProjects}
      />
    </section>
  );
}
