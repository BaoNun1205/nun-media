import { useRef, useState } from 'react';
import { Captions, Download, Eraser, FileAudio, FileVideo2, Image as ImageIcon, Languages, Music2, Play, Plus, Settings2, Share2, Upload, Volume2 } from 'lucide-react';
import { CAPCUT_LANGUAGES, LANGUAGES, POCKET_LANGUAGES, SOURCE_LANGUAGES, formatDuration } from '../../lib/studio';
import { API_BASE, studioApi } from '../../services/api';
import type { Asset, ProjectAsset, ToolKey } from '../../types/studio';
import type { EditorController } from '../../hooks/useEditorController';
import { JobProgress } from '../common/JobProgress';
import { SliderNumericField } from './NumericField';

type AssetKind = 'video' | 'srt' | 'audio' | 'image';

const TOOLS: Array<[ToolKey, React.ComponentType<{ size?: number }>, string, string]> = [
  ['subtitles', Captions, 'Subtitles', 'Generate or import'],
  ['translate', Languages, 'Translate', 'Create translated SRT'],
  ['remove', Eraser, 'Remove / Hide', 'Clean source captions'],
  ['voiceover', Volume2, 'Voiceover', 'Generate and merge TTS'],
  ['audio', Music2, 'Audio', 'Source audio controls'],
  ['export', Share2, 'Export', 'Deliver versions and assets'],
];

function projectAssetPreviewUrl(asset: ProjectAsset) {
  if (asset.kind === 'video' && asset.sourceVideoId) return `${API_BASE}/videos/${asset.sourceVideoId}/thumbnail`;
  if (asset.kind === 'image') return `${API_BASE}/project-assets/${asset.id}/download?preview=1`;
  return '';
}

function assetDurationLabel(asset: ProjectAsset) {
  const durationMs = Number((asset.metadata || {}).duration_ms || 0);
  return durationMs > 0 ? formatDuration(durationMs) : asset.kind.toUpperCase();
}

function AssetRow({ asset, editor }: { asset: Asset; editor: EditorController }) {
  const Icon = asset.kind === 'srt' ? Captions : asset.kind === 'image' ? ImageIcon : asset.kind.includes('tts') || asset.kind.includes('audio') ? FileAudio : FileVideo2;
  const metadata = asset.metadata || {};
  const detail = [asset.kind.toUpperCase(), String(metadata.language || asset.engine || 'Local'), asset.createdAt?.slice(0, 10)].filter(Boolean).join(' · ');
  const previewUrl = asset.kind === 'image' || asset.kind.includes('video') ? `${API_BASE}/assets/${asset.id}/download?preview=1` : '';
  return <button draggable onDragStart={(event) => event.dataTransfer.setData('application/x-stitch-asset', JSON.stringify({ type: 'asset', id: asset.id, kind: asset.kind }))} className={`asset-card ${editor.selection.type === 'asset' && editor.selection.id === asset.id ? 'active' : ''}`} onClick={() => {
    editor.setSelection({ type: 'asset', id: asset.id });
    if (asset.kind === 'srt') { editor.loadSrt(asset.id); editor.setSelection({ type: 'subtitle-track', assetId: asset.id }); }
    if (asset.kind === 'tts_video') editor.setPreviewSource(`tts:${asset.id}`);
    else if (asset.kind.includes('video')) editor.setPreviewSource(`asset:${asset.id}`);
    else if (asset.kind === 'tts' || asset.kind.includes('audio')) new Audio(`${API_BASE}/assets/${asset.id}/download?preview=1`).play().catch(() => editor.setMessage('Unable to preview this audio asset.'));
  }}><span className={`asset-card-thumb ${asset.kind}`}>{previewUrl ? <img src={previewUrl} alt="" /> : <Icon size={22} />}</span><strong>{asset.name}</strong><small>{detail}</small><span className="asset-card-action"><Plus size={13} /></span></button>;
}

function ProjectAssetRow({ asset, editor }: { asset: ProjectAsset; editor: EditorController }) {
  const Icon = asset.kind === 'srt' ? Captions : asset.kind === 'audio' ? FileAudio : asset.kind === 'image' ? ImageIcon : FileVideo2;
  const detail = [asset.kind.toUpperCase(), asset.createdAt?.slice(0, 10)].filter(Boolean).join(' · ');
  const previewUrl = projectAssetPreviewUrl(asset);
  return <button draggable onDragStart={(event) => event.dataTransfer.setData('application/x-stitch-asset', JSON.stringify({ type: 'projectAsset', id: asset.id, kind: asset.kind, sourceVideoId: asset.sourceVideoId }))} className="asset-card" onClick={() => {
    void editor.addProjectAssetToTimeline(asset);
  }}><span className={`asset-card-thumb ${asset.kind}`}>{previewUrl ? <img src={previewUrl} alt="" /> : <Icon size={22} />}{asset.kind === 'video' && <em>{assetDurationLabel(asset)}</em>}</span><strong>{asset.name}</strong><small>{detail}</small><span className="asset-card-action"><Plus size={13} /></span></button>;
}

function AssetBin({ editor }: { editor: EditorController }) {
  const uploadRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<AssetKind>('video');
  const videoAssets = editor.project.assets.filter((asset) => asset.kind !== 'srt' && !asset.kind.includes('tts') && !asset.kind.includes('audio'));
  const audioAssets = editor.project.assets.filter((asset) => asset.kind.includes('tts') || asset.kind.includes('audio'));
  const projectAssets = editor.project.projectAssets || [];
  const projectKindAssets = projectAssets.filter((asset) => asset.kind === kind);
  const imageAssets = projectAssets.filter((asset) => asset.kind === 'image');
  const localKindAssets = editor.project.workspaceId ? [] : kind === 'video' ? videoAssets : kind === 'srt' ? editor.srtAssets : kind === 'audio' ? audioAssets : [];
  const hasMainVideo = kind === 'video' && !editor.project.workspaceId && !editor.isEmptyWorkspace;
  const visibleCount = kind === 'image'
      ? imageAssets.length
      : projectKindAssets.length + localKindAssets.length + (hasMainVideo ? 1 : 0);
  const accept = kind === 'video'
    ? 'video/mp4,video/quicktime,video/x-matroska,video/webm,.m4v,.avi'
    : kind === 'srt'
      ? '.srt,application/x-subrip,text/plain'
      : kind === 'image'
        ? 'image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp'
        : 'audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg';

  async function upload(files?: FileList | File[]) {
    const items = Array.from(files || []);
    if (!items.length) return;
    if (!editor.project.workspaceId) {
      editor.setMessage('Open this video from a project before adding project assets.');
      return;
    }
    try {
      for (const file of items) {
        await studioApi.uploadWorkspaceAsset(editor.project.workspaceId, file);
      }
      await editor.refresh();
      editor.setMessage(`Added ${items.length} project asset${items.length === 1 ? '' : 's'} to Assets.`);
    } catch (error) {
      editor.setMessage(error instanceof Error ? error.message : 'Unable to upload project asset');
    } finally {
      if (uploadRef.current) uploadRef.current.value = '';
    }
  }

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void upload(event.dataTransfer.files);
  }

  return <div className="asset-browser asset-bin">
    <div className="asset-kind-tabs">
      <button className={kind === 'video' ? 'active' : ''} onClick={() => setKind('video')}><FileVideo2 size={15} /> Video</button>
      <button className={kind === 'srt' ? 'active' : ''} onClick={() => setKind('srt')}><Captions size={15} /> Sub</button>
      <button className={kind === 'audio' ? 'active' : ''} onClick={() => setKind('audio')}><FileAudio size={15} /> Audio</button>
      <button className={kind === 'image' ? 'active' : ''} onClick={() => setKind('image')}><ImageIcon size={15} /> Image</button>
    </div>
    <div className="asset-kind-content">
      <input ref={uploadRef} className="visually-hidden" type="file" accept={accept} multiple onChange={(event) => upload(event.target.files || undefined)} />
      {visibleCount === 0
        ? <div className="asset-bin-list empty-asset-bin" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <div className="asset-bin-bar"><span>{kind === 'srt' ? 'Sub' : kind[0].toUpperCase() + kind.slice(1)}</span><button onClick={() => uploadRef.current?.click()}><Upload size={14} /> Import</button></div>
          <div className="asset-drop-zone" onClick={() => uploadRef.current?.click()}>
            <span><Plus size={18} /></span>
            <strong>Import media</strong>
            <small>Drag and drop {kind === 'srt' ? 'subtitle files' : `${kind} files`} here</small>
          </div>
        </div>
        : <div className="asset-bin-list" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <div className="asset-bin-bar"><span>{kind === 'srt' ? 'Sub' : kind[0].toUpperCase() + kind.slice(1)}</span><button onClick={() => uploadRef.current?.click()}><Upload size={14} /> Import</button></div>
          <div className="asset-card-grid">
            {hasMainVideo && <button className="asset-card active" onClick={() => editor.setSelection({ type: 'video', id: editor.project.id })}><span className="asset-card-thumb video"><img src={`${API_BASE}/videos/${editor.project.id}/thumbnail`} alt="" /><em>{formatDuration(editor.project.durationMs)}</em></span><strong>{editor.project.name}</strong><small>Main</small><span className="asset-card-action"><Play size={13} /></span></button>}
            {(kind === 'image' ? imageAssets : projectKindAssets).map((asset) => <ProjectAssetRow key={asset.id} asset={asset} editor={editor} />)}
            {localKindAssets.map((asset) => <AssetRow key={asset.id} asset={asset} editor={editor} />)}
          </div>
        </div>}
    </div>
  </div>;
}

export function AssetToolPanel({ editor }: { editor: EditorController }) {
  return (
    <aside className="editor-left-panel">
      <div className="left-panel-tabs"><button className={editor.assetTab === 'assets' ? 'active' : ''} onClick={() => editor.setAssetTab('assets')}>Assets</button><button className={editor.assetTab === 'tools' ? 'active' : ''} onClick={() => editor.setAssetTab('tools')}>Tools</button></div>
      {editor.assetTab === 'assets' ? <AssetBin editor={editor} /> : <div className="tool-browser">
        <div className="tool-index">{TOOLS.map(([key, Icon, label, help]) => <button key={key} className={editor.activeTool === key ? 'active' : ''} onClick={() => editor.openTool(key)}><span><Icon size={17} /></span><span><strong>{label}</strong><small>{help}</small></span></button>)}</div>
        <div className="tool-config"><ToolForm editor={editor} /></div>
      </div>}
    </aside>
  );
}

function ToolForm({ editor }: { editor: EditorController }) {
  const importSrtRef = useRef<HTMLInputElement>(null);
  const busy = editor.activeJobs.length > 0;
  const jobKinds: Partial<Record<ToolKey, string[]>> = {
    subtitles: ['srt'],
    translate: ['translate'],
    remove: ['remove'],
    voiceover: ['tts', 'tts-segment', 'tts-mux'],
    audio: ['audio-separate'],
    export: [],
  };
  const activeJob = editor.activeJobs.find((job) => (jobKinds[editor.activeTool] || []).includes(job.kind));
  const title = TOOLS.find(([key]) => key === editor.activeTool)?.[2];
  return <div className="tool-form">
    <div className="tool-form-heading"><span className="eyebrow">Tool</span><h2>{title}</h2></div>
    {editor.activeTool === 'subtitles' && <>
      <label>Source<select value={editor.subtitleSource} onChange={(e) => { editor.setSubtitleSource(e.target.value); editor.setEditArea(false); }}><option value="audio">{editor.project.workspaceId ? 'Timeline audio - Whisper' : 'Audio speech - Whisper'}</option><option value="hardsub">Hard subtitle - OCR</option></select></label>
      {editor.subtitleSource === 'audio' ? <><label>Model<select value={editor.model} onChange={(e) => editor.setModel(e.target.value)}>{['tiny', 'base', 'small', 'medium', 'large-v3'].map((item) => <option key={item}>{item}</option>)}</select></label><label>Spoken language<select value={editor.language} onChange={(e) => editor.setLanguage(e.target.value)}>{SOURCE_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label></> : <><label>Subtitle language<select value={editor.language === 'auto' ? 'vi' : editor.language} onChange={(e) => editor.setLanguage(e.target.value)}>{LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>OCR mode<select value={editor.hardsubMode} onChange={(event) => editor.setHardsubMode(event.target.value)}><option value="fast">Fast</option><option value="auto">Auto</option><option value="accurate">Accurate</option></select></label><label>OCR scan area<div className="segmented two"><button className={editor.ocrAreaMode === 'default' ? 'active' : ''} onClick={() => { editor.setOcrAreaMode('default'); editor.setEditArea(false); }}>Bottom area</button><button className={editor.ocrAreaMode === 'custom' ? 'active' : ''} onClick={() => editor.setOcrAreaMode('custom')}>Custom</button></div></label>{editor.ocrAreaMode === 'custom' && <><div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}><button onClick={() => editor.setEditArea(!editor.editArea)}><Settings2 size={15} /> {editor.editArea ? 'Finish OCR area' : 'Adjust OCR area on preview'}</button><button onClick={() => editor.setOcrArea({ xmin: .04, xmax: .96, ymin: .60, ymax: .98 })}>Reset bottom area</button></div><p className="form-help">Only content inside the selected rectangle is sent to VideoSubFinder and OCR.</p></>}</>}
      <label>Compute<select value={editor.device} onChange={(e) => editor.setDevice(e.target.value)}><option>cpu</option><option>cuda</option><option>auto</option></select></label>
      <button className="primary full" disabled={busy} onClick={editor.generateSrt}><Captions size={16} /> {editor.srt.asset ? 'Generate replacement SRT' : 'Create subtitles'}</button>
      <input ref={importSrtRef} className="visually-hidden" type="file" accept=".srt,application/x-subrip,text/plain" onChange={(event) => { editor.importSrt(event.target.files?.[0]); event.currentTarget.value = ''; }} />
      <button className="full" disabled={busy} onClick={() => importSrtRef.current?.click()}><Upload size={15} /> Import & replace SRT</button>
    </>}
    {editor.activeTool === 'translate' && <>
      <label>Source SRT<select value={editor.srt.asset?.id || ''} onChange={(e) => editor.loadSrt(Number(e.target.value))}>{editor.srtAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
      <label>Source language<select value={editor.translationSourceLanguage} onChange={(event) => editor.setTranslationSourceLanguage(event.target.value)}>{SOURCE_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label>Target language<select value={editor.targetLanguage} onChange={(e) => editor.setTargetLanguage(e.target.value)}>{LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label>Engine<select><option>MADLAD-400 local</option></select></label>
      <label>Compute<select value={editor.translationDevice} onChange={(event) => editor.setTranslationDevice(event.target.value)}><option value="cpu">CPU</option><option value="cuda">CUDA</option></select></label>
      <button className="primary full" disabled={!editor.srt.asset || busy} onClick={editor.translate}><Languages size={16} /> Translate & replace active SRT</button>
    </>}
    {editor.activeTool === 'remove' && <>
      {editor.activeBlurEffect && <div className="operation-done"><Eraser size={18} /><strong>Blur effect is on FX</strong><p>Select the FX clip and press Delete or Backspace to remove it. The source video is unchanged.</p></div>}
      <label>Workflow<div className="segmented two"><button className={editor.removeMethod === 'auto' ? 'active' : ''} onClick={() => editor.setRemoveMethod('auto')}>Auto from SRT</button><button className={editor.removeMethod === 'manual' ? 'active' : ''} onClick={() => editor.setRemoveMethod('manual')}>Manual area</button></div></label>
      {editor.removeMethod === 'auto'
        ? <><label>Active SRT<input value={editor.srt.asset?.name || 'No active SRT'} readOnly /></label><p className="form-help">The longest line in the active SRT is sampled once with OCR. Its text box becomes the blur area for the whole video.</p></>
       : <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}><button onClick={() => editor.setEditArea(!editor.editArea)}><Settings2 size={15} /> {editor.editArea ? 'Finish area' : 'Adjust blur area on preview'}</button><button onClick={() => void editor.saveSubtitleArea({ xmin: .04, xmax: .96, ymin: .60, ymax: .98 })}>Reset bottom area</button></div>}
      <button className="primary full" disabled={busy || (editor.removeMethod === 'auto' && !editor.srt.asset)} onClick={editor.remove}><Eraser size={16} /> {editor.activeBlurEffect ? 'Update blur effect' : 'Add blur effect'}</button>
    </>}
    {editor.activeTool === 'voiceover' && <>
      <label>Source SRT<select value={editor.srt.asset?.id || ''} onChange={(e) => editor.loadSrt(Number(e.target.value))}>{editor.srtAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
      <label>Engine<select value={editor.ttsEngine} onChange={(e) => { const next = e.target.value; editor.setTtsEngine(next); editor.setTtsLanguage(next === 'capcut' ? 'en-US' : next === 'pocket' ? 'english' : 'vi-VN'); }}><option value="vieneu">VieNeu Vietnamese</option><option value="capcut">CapCut Multi-language</option><option value="pocket">Pocket TTS</option></select></label>
      <label>Language<select value={editor.ttsLanguage} onChange={(e) => editor.setTtsLanguage(e.target.value)}>{editor.ttsEngine === 'capcut' ? CAPCUT_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>) : editor.ttsEngine === 'pocket' ? POCKET_LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>) : <option value="vi-VN">Vietnamese</option>}</select></label>
      <label>Voice<select value={editor.ttsVoice} onChange={(e) => editor.setTtsVoice(e.target.value)}>{editor.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label || voice.id}</option>)}</select></label>
      {editor.ttsEngine === 'vieneu' && <label>Rate<select value={editor.ttsRate} onChange={(e) => editor.setTtsRate(e.target.value)}><option>.9</option><option>1.0</option><option>1.1</option></select></label>}
      <button className="primary full" disabled={!editor.srt.asset || busy} onClick={() => editor.generateVoice()}><Volume2 size={16} /> Generate voiceover</button>
      <p className="form-help">Voiceover is automatically merged into one clip on A2 and added to the preview.</p>
    </>}
    {editor.activeTool === 'audio' && <><div className="operation-done"><Music2 size={18} /><strong>{editor.audioMode === 'remove_vocals' ? 'Removing vocals' : editor.audioMode === 'remove_music' ? 'Removing music' : 'Original audio'}</strong><p>Right-click the video on the timeline to change audio mode. Model: UVR-MDX-NET Inst HQ 3 · instrumental 95% + original audio 5%.</p></div><label>Video volume<SliderNumericField value={editor.videoVolumeDb} min={-60} max={20} step={0.1} unit="dB" onChange={editor.updateVideoVolumeDb} ariaLabel="Video volume in decibels" /></label><label className="check-line"><input type="checkbox" checked={editor.previewMuted} onChange={(event) => editor.setPreviewMuted(event.target.checked)} /> Mute preview</label></>}
    {editor.activeTool === 'export' && <><a className={`button primary full ${editor.audioMode !== 'original' && !editor.audioSeparationReady ? 'disabled' : ''}`} aria-disabled={editor.audioMode !== 'original' && !editor.audioSeparationReady} href={`${API_BASE}/videos/${editor.project.id}/media?audioMode=${editor.audioMode}&renderEffects=true`} onClick={(event) => { if (editor.audioMode !== 'original' && !editor.audioSeparationReady) event.preventDefault(); }}><Download size={16} /> Export current video</a>{editor.srt.asset && <a className="button full" href={`${API_BASE}/assets/${editor.srt.asset.id}/download`}><Download size={16} /> Export selected SRT</a>}<p className="form-help">The exported video uses the audio mode selected on the timeline and renders active FX clips.</p></>}
    {activeJob && <><JobProgress job={activeJob} /><button className="danger full cancel-job" onClick={() => editor.cancelJob(activeJob.id)}>Cancel job #{activeJob.id}</button></>}
    {editor.message && <p className="tool-message">{editor.message}</p>}
  </div>;
}
