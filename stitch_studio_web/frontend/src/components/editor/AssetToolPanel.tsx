import { useRef, useState } from 'react';
import { Captions, ChevronLeft, ChevronRight, Download, Eraser, FileAudio, FileVideo2, Image as ImageIcon, Languages, Music2, Play, Plus, Search, Settings2, Share2, Sparkles, Upload, Volume2, Trash2 } from 'lucide-react';
import { LANGUAGES, SOURCE_LANGUAGES, defaultTtsLanguage, formatDuration, getAssetGroup, isMediaFileAsset, ttsLanguageOptions } from '../../lib/studio';
import { API_BASE, studioApi } from '../../services/api';
import type { Asset, ProjectAsset, ToolKey } from '../../types/studio';
import type { EditorController } from '../../hooks/useEditorController';
import { JobProgress } from '../common/JobProgress';
import { SliderNumericField } from './NumericField';
import { VIDEO_EFFECT_CATEGORIES, VIDEO_EFFECTS } from '../../config/videoEffects';
import { EffectThumbnail } from './EffectThumbnail';

type AssetKind = 'video' | 'srt' | 'audio' | 'image';

const TOOLS: Array<[ToolKey, React.ComponentType<{ size?: number }>, string, string]> = [
  ['subtitles', Captions, 'Subtitles', 'Generate or import'],
  ['translate', Languages, 'Translate', 'Create translated SRT'],
  ['remove', Eraser, 'Remove / Hide', 'Clean source captions'],
  ['voiceover', Volume2, 'Voiceover', 'Generate and merge TTS'],
  ['audio', Music2, 'Audio', 'Source audio controls'],
  ['effects', Sparkles, 'Effects', 'Browse visual effects'],
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
  }}><span className={`asset-card-thumb ${asset.kind}`}>{previewUrl ? <img src={previewUrl} alt="" /> : <Icon size={22} />}</span><strong>{asset.name}</strong><small>{detail}</small>
    <div className="asset-actions">
      <span className="asset-card-action" onClick={(e) => {
        e.stopPropagation();
        studioApi.deleteAsset(asset.id).catch(() => {}).finally(() => editor.refresh());
      }} title="Delete"><Trash2 size={13} /></span>
    </div>
  </button>;
}

function ProjectAssetRow({ asset, editor }: { asset: ProjectAsset; editor: EditorController }) {
  const Icon = asset.kind === 'srt' ? Captions : asset.kind === 'audio' ? FileAudio : asset.kind === 'image' ? ImageIcon : FileVideo2;
  const detail = [asset.kind.toUpperCase(), asset.createdAt?.slice(0, 10)].filter(Boolean).join(' · ');
  const previewUrl = projectAssetPreviewUrl(asset);
  return <button draggable onDragStart={(event) => event.dataTransfer.setData('application/x-stitch-asset', JSON.stringify({ type: 'projectAsset', id: asset.id, kind: asset.kind, sourceVideoId: asset.sourceVideoId }))} className="asset-card" onClick={() => {
    void editor.addProjectAssetToTimeline(asset);
  }}><span className={`asset-card-thumb ${asset.kind}`}>{previewUrl ? <img src={previewUrl} alt="" /> : <Icon size={22} />}{asset.kind === 'video' && <em>{assetDurationLabel(asset)}</em>}</span><strong>{asset.name}</strong><small>{detail}</small>
    <div className="asset-actions">
      <span className="asset-card-action delete-action" onClick={(e) => {
        e.stopPropagation();
        studioApi.deleteProjectAsset(asset.id).catch(() => {}).finally(() => editor.refresh());
      }} title="Delete"><Trash2 size={13} /></span>
      <span className="asset-card-action add-action" title="Add to timeline"><Plus size={13} /></span>
    </div>
  </button>;
}

function AssetBin({ editor }: { editor: EditorController }) {
  const uploadRef = useRef<HTMLInputElement>(null);
  const [assetGroup, setAssetGroup] = useState<'media' | 'subs'>('media');
  const [mediaFilter, setMediaFilter] = useState<'all' | 'video' | 'image' | 'audio'>('all');

  const videoAssets = editor.project.assets.filter((asset) => asset.kind !== 'srt' && !asset.kind.includes('tts') && !asset.kind.includes('audio'));
  const audioAssets = editor.project.assets.filter((asset) => asset.kind.includes('tts') || asset.kind.includes('audio'));
  const projectAssets = editor.project.projectAssets || [];
  
  const allProjectMediaAssets = projectAssets.filter((asset) => getAssetGroup(asset.kind) === 'media');
  const projectImageAssets = projectAssets.filter((asset) => asset.kind === 'image');
  const projectVideoAssets = projectAssets.filter((asset) => asset.kind === 'video');
  const projectAudioAssets = projectAssets.filter((asset) => asset.kind === 'audio' || asset.kind.includes('tts'));
  const projectSubsAssets = projectAssets.filter((asset) => getAssetGroup(asset.kind) === 'subs');

  const localVideoAssets = editor.project.workspaceId ? [] : videoAssets;
  const localAudioAssets = editor.project.workspaceId ? [] : audioAssets;
  const localSubsAssets = editor.project.workspaceId ? [] : editor.srtAssets;

  let visibleProjectAssets: ProjectAsset[] = [];
  let visibleLocalAssets: Asset[] = [];
  let showMainVideo = false;

  const hasMainVideo = !editor.project.workspaceId && !editor.isEmptyWorkspace;

  if (assetGroup === 'media') {
    if (mediaFilter === 'all') {
      visibleProjectAssets = allProjectMediaAssets;
      visibleLocalAssets = [...localVideoAssets, ...localAudioAssets];
      showMainVideo = hasMainVideo;
    } else if (mediaFilter === 'video') {
      visibleProjectAssets = projectVideoAssets;
      visibleLocalAssets = localVideoAssets;
      showMainVideo = hasMainVideo;
    } else if (mediaFilter === 'image') {
      visibleProjectAssets = projectImageAssets;
      visibleLocalAssets = [];
      showMainVideo = false;
    } else if (mediaFilter === 'audio') {
      visibleProjectAssets = projectAudioAssets;
      visibleLocalAssets = localAudioAssets;
      showMainVideo = false;
    }
  } else if (assetGroup === 'subs') {
    visibleProjectAssets = projectSubsAssets;
    visibleLocalAssets = localSubsAssets;
    showMainVideo = false;
  }

  const visibleCount = visibleProjectAssets.length + visibleLocalAssets.length + (showMainVideo ? 1 : 0);

  const accept = assetGroup === 'subs'
    ? '.srt,application/x-subrip,text/plain'
    : 'video/*,image/*,audio/*,.mp4,.quicktime,.mkv,.webm,.m4v,.avi,.jpg,.jpeg,.png,.webp,.gif,.bmp,.mp3,.wav,.m4a,.aac,.flac,.ogg';

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

  return <div className="asset-bin">
    <div className="asset-index">
      <button className={assetGroup === 'media' ? 'active' : ''} onClick={() => setAssetGroup('media')} title="Media Files">
        <span><FileVideo2 size={17} /></span>
        <span><strong>Media</strong></span>
      </button>
      <button className={assetGroup === 'subs' ? 'active' : ''} onClick={() => setAssetGroup('subs')} title="Subs">
        <span><Captions size={17} /></span>
        <span><strong>Subs</strong></span>
      </button>
    </div>
    <div className="asset-kind-content">
      <input ref={uploadRef} className="visually-hidden" type="file" accept={accept} multiple onChange={(event) => upload(event.target.files || undefined)} />
      {visibleCount === 0
        ? <div className="asset-bin-list empty-asset-bin" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <div className="asset-bin-bar"><span>{assetGroup === 'subs' ? 'Subs' : 'Media Files'}</span><button onClick={() => uploadRef.current?.click()}><Upload size={14} /> Import{assetGroup === 'subs' ? ' SRT' : ''}</button></div>
          {assetGroup === 'media' && (
            <div className="style-segmented" style={{ marginBottom: '12px' }}>
              <button className={mediaFilter === 'all' ? 'active' : ''} onClick={() => setMediaFilter('all')}><span>All</span></button>
              <button className={mediaFilter === 'video' ? 'active' : ''} onClick={() => setMediaFilter('video')}><span>Video</span></button>
              <button className={mediaFilter === 'image' ? 'active' : ''} onClick={() => setMediaFilter('image')}><span>Image</span></button>
              <button className={mediaFilter === 'audio' ? 'active' : ''} onClick={() => setMediaFilter('audio')}><span>Audio</span></button>
            </div>
          )}
          <div className="asset-drop-zone" onClick={() => uploadRef.current?.click()}>
            <span><Plus size={18} /></span>
            <strong>{assetGroup === 'subs' ? 'Import subtitles' : 'Import media'}</strong>
            <small>Drag and drop {assetGroup === 'subs' ? 'subtitle files' : 'media files'} here</small>
          </div>
        </div>
        : <div className="asset-bin-list" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <div className="asset-bin-bar"><span>{assetGroup === 'subs' ? 'Subs' : 'Media Files'}</span><button onClick={() => uploadRef.current?.click()}><Upload size={14} /> Import{assetGroup === 'subs' ? ' SRT' : ''}</button></div>
          {assetGroup === 'media' && (
            <div className="style-segmented" style={{ marginBottom: '12px' }}>
              <button className={mediaFilter === 'all' ? 'active' : ''} onClick={() => setMediaFilter('all')}><span>All</span></button>
              <button className={mediaFilter === 'video' ? 'active' : ''} onClick={() => setMediaFilter('video')}><span>Video</span></button>
              <button className={mediaFilter === 'image' ? 'active' : ''} onClick={() => setMediaFilter('image')}><span>Image</span></button>
              <button className={mediaFilter === 'audio' ? 'active' : ''} onClick={() => setMediaFilter('audio')}><span>Audio</span></button>
            </div>
          )}
          <div className="asset-card-grid">
            {showMainVideo && <button className="asset-card active" onClick={() => editor.setSelection({ type: 'video', id: editor.project.id })}><span className="asset-card-thumb video"><img src={`${API_BASE}/videos/${editor.project.id}/thumbnail`} alt="" /><em>{formatDuration(editor.project.durationMs)}</em></span><strong>{editor.project.name}</strong><small>Main</small><span className="asset-card-action"><Play size={13} /></span></button>}
            {visibleProjectAssets.map((asset) => <ProjectAssetRow key={asset.id} asset={asset} editor={editor} />)}
            {visibleLocalAssets.map((asset) => <AssetRow key={asset.id} asset={asset} editor={editor} />)}
          </div>
        </div>}
    </div>
  </div>;
}

export function AssetToolPanel({ editor, onOpenExport }: { editor: EditorController; onOpenExport: () => void }) {
  return (
    <aside className="editor-left-panel">
      <div className="left-panel-tabs"><button className={editor.assetTab === 'assets' ? 'active' : ''} onClick={() => editor.setAssetTab('assets')}>Assets</button><button className={editor.assetTab === 'tools' ? 'active' : ''} onClick={() => editor.setAssetTab('tools')}>Tools</button></div>
      {editor.assetTab === 'assets' ? <AssetBin editor={editor} /> : <div className="tool-browser">
        <div className="tool-index">{TOOLS.map(([key, Icon, label, help]) => <button key={key} className={editor.activeTool === key ? 'active' : ''} onClick={() => editor.openTool(key)}><span><Icon size={17} /></span><span><strong>{label}</strong><small>{help}</small></span></button>)}</div>
        <div className="tool-config"><ToolForm editor={editor} onOpenExport={onOpenExport} /></div>
      </div>}
    </aside>
  );
}

function EffectsBrowser({ editor, busy }: { editor: EditorController; busy: boolean }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<(typeof VIDEO_EFFECT_CATEGORIES)[number]>('Trending');
  const [selectedId, setSelectedId] = useState('');
  const categoryRailRef = useRef<HTMLDivElement>(null);
  const normalized = query.trim().toLowerCase();
  const trending = new Set(['film_grain', 'vhs', 'glow', 'rgb_split', 'block_glitch', 'color_grade']);
  const effects = VIDEO_EFFECTS.filter((effect) => {
    const categoryMatch = category === 'Trending' ? trending.has(effect.id) : effect.category === category;
    // Search intentionally spans every category; category chips are for browsing.
    return normalized
      ? `${effect.label} ${effect.description}`.toLowerCase().includes(normalized)
      : categoryMatch;
  });
  // A previous selection must not look like a search result after filtering.
  const selected = effects.find((effect) => effect.id === selectedId);
  const add = (effectId: string) => void editor.addTimelineEffect(effectId);
  const scrollCategories = (direction: -1 | 1) => categoryRailRef.current?.scrollBy({ left: direction * 150, behavior: 'smooth' });
  return <div className="effects-browser">
    <div className="effects-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search effects" aria-label="Search effects" /></div>
    <div className="effects-category-row"><button className="effects-category-nav" type="button" onClick={() => scrollCategories(-1)} aria-label="Show previous effect categories"><ChevronLeft size={13} /></button><div ref={categoryRailRef} className="effects-categories" onWheel={(event) => { if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) { event.currentTarget.scrollLeft += event.deltaY; event.preventDefault(); } }}>{VIDEO_EFFECT_CATEGORIES.map((item) => <button key={item} className={category === item ? 'active' : ''} onClick={() => setCategory(item)}>{item}</button>)}</div><button className="effects-category-nav" type="button" onClick={() => scrollCategories(1)} aria-label="Show more effect categories"><ChevronRight size={13} /></button></div>
    <div className="effects-grid">{effects.map((effect) => <button key={effect.id} className={`effect-tile ${selectedId === effect.id ? 'selected' : ''}`} disabled={busy || !editor.project.workspaceId} onClick={() => setSelectedId(effect.id)} onDoubleClick={() => add(effect.id)} title={`${effect.description} — double-click to add`}>
      <span className="effect-tile-image"><EffectThumbnail effect={effect} /><i className="effect-tile-add" onClick={(event) => { event.preventDefault(); event.stopPropagation(); add(effect.id); }} title={`Add ${effect.label}`}><Plus size={13} /></i></span><strong>{effect.label}</strong>
    </button>)}</div>
    {effects.length === 0 && <p className="effects-empty">No effects match “{query.trim() || category}”. Snow, Rain, and Fog are not in this library.</p>}
    {selected && <div className="effects-selection"><span><strong>{selected.label}</strong><small>{selected.description}</small></span><button className="primary" disabled={busy || !editor.project.workspaceId} onClick={() => add(selected.id)}><Plus size={14} /> Add</button></div>}
    {!editor.project.workspaceId && <p className="form-help">Open a workspace project to add effects to its timeline.</p>}
  </div>;
}

function ToolForm({ editor, onOpenExport }: { editor: EditorController; onOpenExport: () => void }) {
  const importSrtRef = useRef<HTMLInputElement>(null);
  const busy = editor.activeJobs.length > 0;
  const jobKinds: Partial<Record<ToolKey, string[]>> = {
    subtitles: ['srt'],
    translate: ['translate'],
    remove: ['remove'],
    voiceover: ['tts', 'tts-segment', 'tts-mux'],
    audio: ['audio-separate'],
    effects: [],
    export: ['project-export'],
  };
  const currentJobKinds = jobKinds[editor.activeTool] || [];
  const toolJobs = [...editor.jobs].filter((job) => currentJobKinds.includes(job.kind)).sort((a, b) => b.id - a.id);
  const activeJob = editor.activeJobs.find((job) => currentJobKinds.includes(job.kind));
  const displayJob = activeJob || toolJobs.find((job) => job.status === 'error' || job.status === 'cancelled');
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
    {editor.activeTool === 'effects' && <EffectsBrowser editor={editor} busy={busy} />}
    {editor.activeTool === 'voiceover' && <>
      <label>Source SRT<select value={editor.srt.asset?.id || ''} onChange={(e) => editor.loadSrt(Number(e.target.value))}>{editor.srtAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
      <label>Engine<select value={editor.ttsEngine} onChange={(e) => { const next = e.target.value; editor.setTtsEngine(next); editor.setTtsLanguage(defaultTtsLanguage(next)); }}><option value="vieneu">VieNeu Vietnamese</option><option value="capcut">CapCut Multi-language</option><option value="pocket">Pocket TTS</option></select></label>
      <label>Language<select value={editor.ttsLanguage} onChange={(e) => editor.setTtsLanguage(e.target.value)}>{ttsLanguageOptions(editor.ttsEngine).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label>Voice<select value={editor.ttsVoice} onChange={(e) => editor.setTtsVoice(e.target.value)}>{editor.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label || voice.id}</option>)}</select></label>
      {editor.ttsEngine === 'vieneu' && <label>Rate<select value={editor.ttsRate} onChange={(e) => editor.setTtsRate(e.target.value)}><option>.9</option><option>1.0</option><option>1.1</option></select></label>}
      <button className="primary full" disabled={!editor.srt.asset || busy} onClick={() => editor.generateVoice()}><Volume2 size={16} /> Generate voiceover</button>
      <p className="form-help">Voiceover is automatically merged into one clip on A2 and added to the preview.</p>
    </>}
    {editor.activeTool === 'audio' && <><div className="operation-done"><Music2 size={18} /><strong>{editor.audioMode === 'remove_vocals' ? 'Removing vocals' : editor.audioMode === 'remove_music' ? 'Removing music' : 'Original audio'}</strong><p>Right-click the video on the timeline to change audio mode. Model: UVR-MDX-NET Inst HQ 3 · instrumental 95% + original audio 5%.</p></div><label>Video volume<SliderNumericField value={editor.videoVolumeDb} min={-60} max={20} step={0.1} unit="dB" onChange={editor.updateVideoVolumeDb} ariaLabel="Video volume in decibels" /></label><label className="check-line"><input type="checkbox" checked={editor.previewMuted} onChange={(event) => editor.setPreviewMuted(event.target.checked)} /> Mute preview</label></>}
    {editor.activeTool === 'export' && <><button className="primary full" disabled={editor.audioMode !== 'original' && !editor.audioSeparationReady} onClick={onOpenExport}><Download size={16} /> Export final video</button>{editor.srt.asset && <a className="button full" href={`${API_BASE}/assets/${editor.srt.asset.id}/download`}><Download size={16} /> Export selected SRT</a>}<p className="form-help">Final video export renders the current timeline into one MP4.</p></>}
    {displayJob && <><JobProgress job={displayJob} />{activeJob && <button className="danger full cancel-job" onClick={() => editor.cancelJob(activeJob.id)}>Cancel job #{activeJob.id}</button>}</>}
    {editor.message && <p className="tool-message">{editor.message}</p>}
  </div>;
}
