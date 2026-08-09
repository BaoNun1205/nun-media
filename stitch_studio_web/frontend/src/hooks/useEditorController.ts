import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DEFAULT_AREA, TTS_FIT, isTranslatedAsset, serializeSrt } from '../lib/studio';
import { DEFAULT_TEXT_STYLE, textStylePresetById } from '../config/textStylePresets';
import { sceneFromProject, timelineStateFromSceneOrProject, timelineStateToScene } from '../editor-core/adapters';
import {
  addTrack as addTrackToTimelineState,
  cloneTimelineItems,
  cloneTimelineState,
  createItemFromProjectAsset,
  defaultTrackForKind,
  duplicateItems,
  frameRound,
  normalizeTimelineState,
  pasteItems,
  parseClipboardItems,
  removeTrack as removeTrackFromTimelineState,
  resolvePlacement,
  rippleAfterEdit,
  serializeClipboardItems,
  splitItemsAtTime,
  timelineStateFromProject,
  toggleTrackMute as toggleTimelineTrackMuteInState,
  toggleTrackVisibility as toggleTimelineTrackVisibilityInState,
} from '../lib/timelineCore';
import { API_BASE, request, studioApi } from '../services/api';
import type { CoreTimelineScene } from '../editor-core/types';
import type { AudioMode, InspectorSelection, Job, Project, ProjectAsset, SrtDocument, SubtitleArea, SubtitleSegment, SubtitleStyle, TimelineIssue, TimelineItem, TimelineState, TimelineTrackKind, ToolKey, VoiceOption, VoiceSegment } from '../types/studio';
import type { TextStyle } from '../types/textStyle';

const EMPTY_SRT: SrtDocument = { asset: null, content: '', segments: [] };
const DEFAULT_STYLE: SubtitleStyle = DEFAULT_TEXT_STYLE as SubtitleStyle;
const MAX_DRAFT_HISTORY = 60;

type DraftSnapshot = { srt: SrtDocument; edits: Record<number, string> };
type DraftHistory = { past: DraftSnapshot[]; future: DraftSnapshot[] };
type TimelineHistory = { past: TimelineState[]; future: TimelineState[] };

function cloneSrt(document: SrtDocument): SrtDocument {
  return { ...document, segments: document.segments.map((segment) => ({ ...segment })) };
}

function snapshotDraft(document: SrtDocument, edits: Record<number, string>): DraftSnapshot {
  return { srt: cloneSrt(document), edits: { ...edits } };
}

function formatSrtTimestamp(seconds: number) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000));
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor(milliseconds / 60_000) % 60;
  const remainingSeconds = Math.floor(milliseconds / 1000) % 60;
  const remainder = milliseconds % 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')},${String(remainder).padStart(3, '0')}`;
}

function endOfTimeline(items: TimelineItem[]) {
  return items.reduce((end, item) => Math.max(end, item.start + item.duration), 0);
}

function endOfTrack(items: TimelineItem[], track: TimelineItem['track']) {
  return endOfTimeline(items.filter((item) => item.track === track));
}

function cloneTimeline(items: TimelineItem[]) {
  return items.map((item) => ({ ...item }));
}

function nextTimelineClipId(kind: string, sourceId?: number) {
  return `${kind}-${sourceId || 'asset'}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function editorTimeInsideItem(time: number, item: TimelineItem) {
  return time >= item.start && time < item.start + Math.max(0.05, item.duration);
}

function metadataDurationSeconds(metadata?: Record<string, unknown>) {
  const data = metadata || {};
  const durationMs = Number(data.duration_ms || data.durationMs || data.audio_duration_ms || 0);
  if (durationMs > 0) return durationMs / 1000;
  const durationSeconds = Number(data.duration_seconds || data.duration || 0);
  return durationSeconds > 0 ? durationSeconds : 0;
}

function projectAssetDurationSeconds(asset: ProjectAsset) {
  return metadataDurationSeconds(asset.metadata)
    || metadataDurationSeconds(asset.asset?.metadata)
    || ((asset.video?.durationMs || 0) / 1000);
}

const BASE_TEXT_PROPERTIES: (keyof TextStyle)[] = [
  'fontFamily', 'fontSize', 'textAlign', 'textTransform', 
  'lineHeight', 'letterSpacing', 'fontStyle', 'textDecoration'
];

function resolvedPresetStyle(presetId: string | undefined, currentStyle: Partial<TextStyle>): SubtitleStyle | null {
  const baseProperties: Partial<TextStyle> = {};
  for (const prop of BASE_TEXT_PROPERTIES) {
    if (currentStyle[prop] !== undefined) {
      (baseProperties as any)[prop] = currentStyle[prop];
    }
  }
  if (!presetId) {
    return { ...DEFAULT_STYLE, ...baseProperties, presetId: undefined, presetModified: false } as SubtitleStyle;
  }
  const preset = textStylePresetById(presetId);
  return preset ? { ...DEFAULT_STYLE, ...preset.style, ...baseProperties, presetId: preset.id, presetModified: false } as SubtitleStyle : null;
}

export interface EditorControllerOptions {
  project: Project;
  projects: Project[];
  jobs: Job[];
  voices: VoiceOption[];
  refresh: () => Promise<void>;
  loadVoices: (engine?: string, language?: string) => Promise<VoiceOption[]>;
  onOpenVersion: (id: number) => void;
}

export function useEditorController({ project, projects, jobs, voices, refresh, loadVoices, onOpenVersion }: EditorControllerOptions) {
  const defaults = useMemo(() => {
    try { return JSON.parse(localStorage.getItem('stitch-editor-defaults') || '{}'); } catch { return {}; }
  }, []);
  const initialVoiceAsset = project.assets.filter((asset) => asset.kind === 'tts').at(-1);
  const [srt, setSrt] = useState<SrtDocument>(EMPTY_SRT);
  const [sourceSrt, setSourceSrt] = useState<SrtDocument>(EMPTY_SRT);
  const [translatedSrt, setTranslatedSrt] = useState<SrtDocument>(EMPTY_SRT);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [draftHistory, setDraftHistory] = useState<DraftHistory>({ past: [], future: [] });
  const [baselineSrt, setBaselineSrt] = useState('');
  const [voiceSegments, setVoiceSegments] = useState<VoiceSegment[]>([]);
  const [timelineIssues, setTimelineIssues] = useState<TimelineIssue[]>([]);
  const [selection, setSelection] = useState<InspectorSelection>({ type: 'project' });
  const [removedVoiceAssetIds, setRemovedVoiceAssetIds] = useState<number[]>([]);
  const [blurEffectHidden, setBlurEffectHidden] = useState(false);
  const [subtitleBlurEffect, setSubtitleBlurEffect] = useState<Project['subtitleBlurEffect']>(project.subtitleBlurEffect);
  const [activeTool, setActiveTool] = useState<ToolKey>('subtitles');
  const [assetTab, setAssetTab] = useState<'assets' | 'tools'>('assets');
  const [bottomView, setBottomView] = useState<'timeline' | 'script'>('timeline');
  const [playhead, setPlayhead] = useState(0);
  const [previewSource, setPreviewSource] = useState(initialVoiceAsset ? `tts:${initialVoiceAsset.id}` : 'preview');
  const [fitMode, setFitMode] = useState<'contain' | 'cover'>('contain');
  const [previewVolume, setPreviewVolume] = useState(1);
  const [previewMuted, setPreviewMuted] = useState(false);
  const [audioMode, setAudioModeState] = useState<AudioMode>(project.audioMode || 'original');
  const [playbackRate, setPlaybackRate] = useState(1);
  const [videoScale, setVideoScale] = useState(project.clipSettings?.videoScale ?? 1);
  const [videoVolumeDb, setVideoVolumeDb] = useState(project.clipSettings?.videoVolumeDb ?? 0);
  const [videoSpeed, setVideoSpeed] = useState(project.clipSettings?.videoSpeed ?? 1);
  const [voiceVolumeDb, setVoiceVolumeDb] = useState(project.clipSettings?.voiceVolumeDb ?? 0);
  const [voiceSpeed, setVoiceSpeed] = useState(project.clipSettings?.voiceSpeed ?? 1);
  const [timelineWidth, setTimelineWidth] = useState(1200);
  const [timelineState, setTimelineState] = useState<TimelineState>(() => timelineStateFromSceneOrProject(project));
  const timelineStateRef = useRef(timelineState);
  useEffect(() => { timelineStateRef.current = timelineState; }, [timelineState]);
  const [timelineItems, setTimelineItems] = useState<TimelineItem[]>(() => timelineStateFromSceneOrProject(project).items);
  const [timelineScene, setTimelineScene] = useState<CoreTimelineScene>(() => sceneFromProject(project));
  const [timelineHistory, setTimelineHistory] = useState<TimelineHistory>({ past: [], future: [] });
  const [message, setMessage] = useState('');
  const [editArea, setEditArea] = useState(false);
  const [area, setArea] = useState<SubtitleArea>(project.subtitleArea || DEFAULT_AREA);
  const [style, setStyle] = useState<SubtitleStyle>({ ...DEFAULT_STYLE, ...project.subtitleStyle });
  const [subtitleSource, setSubtitleSource] = useState('audio');
  const [hardsubMode, setHardsubMode] = useState('fast');
  const [ocrAreaMode, setOcrAreaMode] = useState<'default' | 'custom'>('default');
  const [ocrArea, setOcrArea] = useState<SubtitleArea>(DEFAULT_AREA);
  const [model, setModel] = useState(defaults.whisperModel || 'small');
  const [device, setDevice] = useState(defaults.device || 'auto');
  const [language, setLanguage] = useState('auto');
  const [targetLanguage, setTargetLanguage] = useState('vi');
  const [translationSourceLanguage, setTranslationSourceLanguage] = useState('auto');
  const [translationDevice, setTranslationDevice] = useState(defaults.device === 'cuda' ? 'cuda' : 'cpu');
  const [removeMethod, setRemoveMethod] = useState<'auto' | 'manual'>('auto');
  const [removeMode, setRemoveMode] = useState('blur');
  const [autoSrtAssetId, setAutoSrtAssetId] = useState<number | null>(null);
  const [insertMode, setInsertMode] = useState('none');
  const [ttsEngine, setTtsEngine] = useState(defaults.ttsEngine || 'vieneu');
  const [ttsLanguage, setTtsLanguage] = useState('vi-VN');
  const [ttsVoice, setTtsVoice] = useState('default');
  const [ttsRate, setTtsRate] = useState('1.0');
  const autoMuxTtsJobRef = useRef<number | null>(null);
  const handledSrtJobRef = useRef<number | null>(null);
  const isEmptyWorkspace = project.id < 0 || project.mediaType === 'workspace';

  const videoJobs = useMemo(() => jobs.filter((job) => job.videoId === project.id || (project.workspaceId && job.videoId === -project.workspaceId) || (job.videoId === -project.id)), [jobs, project.id, project.workspaceId]);
  const activeJobs = videoJobs.filter((job) => ['queued', 'running'].includes(job.status));
  const activeAudioJob = activeJobs.find((job) => job.kind === 'audio-separate');
  const audioSeparationReady = Boolean(project.audioSeparation?.ready);
  const effectiveAudioMode: AudioMode = audioMode !== 'original' && !audioSeparationReady ? 'original' : audioMode;
  const latestVoiceAsset = project.assets.filter((asset) => asset.kind === 'tts' && !removedVoiceAssetIds.includes(asset.id)).at(-1);
  const activeBlurEffect = blurEffectHidden ? undefined : subtitleBlurEffect;
  const workspaceSrtAssets = (project.projectAssets || [])
    .filter((asset) => asset.kind === 'srt' && asset.sourceAssetId)
    .map((asset) => ({
      id: asset.sourceAssetId!,
      videoId: project.id,
      kind: 'srt',
      path: asset.path,
      name: asset.name,
      engine: String(asset.metadata?.engine || 'workspace'),
      status: asset.status,
      createdAt: asset.createdAt,
      metadata: asset.metadata || {},
    }));
  const srtAssets = [...project.assets, ...workspaceSrtAssets]
    .filter((asset, index, assets) => asset.kind === 'srt' && !isTranslatedAsset(asset.engine) && assets.findIndex((candidate) => candidate.id === asset.id) === index);
  const originalSrtAssets = srtAssets;
  const translatedSrtAssets = srtAssets.filter((asset) => isTranslatedAsset(asset.engine));
  const srtAssetIdForTimelineItem = useCallback((item: TimelineItem) => {
    if (item.kind !== 'srt') return undefined;
    if (item.sourceAssetId) return item.sourceAssetId;
    const projectAsset = item.projectAssetId
      ? (project.projectAssets || []).find((asset) => asset.id === item.projectAssetId)
      : undefined;
    return projectAsset?.sourceAssetId || item.projectAssetId;
  }, [project.projectAssets]);
  const currentSegment = selection.type === 'subtitle' ? srt.segments.find((item) => item.index === selection.index) : undefined;
  const currentVoice = selection.type === 'voice' ? voiceSegments.find((item) => item.index === selection.index) : undefined;
  const voiceByIndex = useMemo(() => Object.fromEntries(voiceSegments.map((item) => [item.index, item])), [voiceSegments]);
  const selectedTextItems = useMemo(() => {
    if (selection.type !== 'timeline-items') return [];
    const selected = new Set(selection.keys);
    return timelineItems.filter((item) => item.kind === 'text' && selected.has(item.id));
  }, [selection, timelineItems]);
  const selectedTextStyle = useMemo(() => {
    const item = selectedTextItems[0];
    const textStyle = item?.params?.textStyle;
    return { ...DEFAULT_STYLE, ...(typeof textStyle === 'object' && textStyle ? textStyle as TextStyle : {}) } as SubtitleStyle;
  }, [selectedTextItems]);
  const selectedTimelineAudioItem = useMemo(() => {
    if (selection.type !== 'timeline-items' || selection.keys.length !== 1) return undefined;
    return timelineItems.find((item) => item.id === selection.keys[0] && item.kind === 'audio');
  }, [selection, timelineItems]);
  const selectedTimelineImageItem = useMemo(() => {
    if (selection.type !== 'timeline-items' || selection.keys.length !== 1) return undefined;
    return timelineItems.find((item) => item.id === selection.keys[0] && item.kind === 'image');
  }, [selection, timelineItems]);
  const timelineDuration = endOfTimeline(timelineItems);
  const hasWorkspaceTimeline = Boolean(project.workspaceId);
  const timelineTrackById = useMemo(() => new Map(timelineState.tracks.map((track, index) => [track.id, { ...track, index }])), [timelineState.tracks]);
  const activeTimelineItem = timelineItems
    .filter((item) => (item.kind === 'video' || item.kind === 'image') && !item.hidden && !timelineTrackById.get(item.track || '')?.hidden && editorTimeInsideItem(playhead, item))
    .sort((a, b) => (timelineTrackById.get(b.track || '')?.index ?? 0) - (timelineTrackById.get(a.track || '')?.index ?? 0))[0];
  const activeTimelineVideoId = activeTimelineItem?.sourceVideoId ?? (!hasWorkspaceTimeline && !isEmptyWorkspace ? project.id : undefined);
  const activeTimelineLocalTime = activeTimelineItem ? Math.max(0, playhead - activeTimelineItem.start + (activeTimelineItem.sourceStart || 0)) : playhead;
  const activeTimelineProject = activeTimelineVideoId
    ? projects.find((item) => item.id === activeTimelineVideoId) || (project.id === activeTimelineVideoId ? project : undefined)
    : undefined;
  const activeTimelineAudioMode: AudioMode = activeTimelineProject?.audioMode || (project.id === activeTimelineVideoId ? audioMode : 'original');
  const activeTimelineAudioReady = Boolean(activeTimelineProject?.audioSeparation?.ready);
  const effectivePreviewAudioMode: AudioMode = activeTimelineAudioMode !== 'original' && !activeTimelineAudioReady ? 'original' : activeTimelineAudioMode;
  const duration = hasWorkspaceTimeline
    ? Math.max(timelineDuration, srt.segments.at(-1)?.end || 0, 1)
    : Math.max(((project.durationMs || 0) / 1000) / Math.max(.1, videoSpeed), srt.segments.at(-1)?.end || 0, 1);
  const latestJob = [...videoJobs].sort((a, b) => b.id - a.id)[0];
  const dirty = useMemo(() => Boolean(srt.asset) && serializeSrt(srt.segments, edits) !== baselineSrt, [srt.asset, srt.segments, edits, baselineSrt]);

  const commitDraft = useCallback((nextSrt: SrtDocument, nextEdits: Record<number, string>, nextMessage?: string) => {
    const previous = snapshotDraft(srt, edits);
    setSrt(cloneSrt(nextSrt));
    setEdits({ ...nextEdits });
    setDraftHistory((current) => ({ past: [...current.past, previous].slice(-MAX_DRAFT_HISTORY), future: [] }));
    if (nextMessage) setMessage(nextMessage);
  }, [srt, edits]);
  const updateEdits = useCallback((nextEdits: Record<number, string>) => {
    if (Object.keys(nextEdits).every((key) => nextEdits[Number(key)] === edits[Number(key)]) && Object.keys(edits).length === Object.keys(nextEdits).length) return;
    commitDraft(srt, nextEdits);
  }, [commitDraft, edits, srt]);
  const undoDraft = useCallback(() => {
    setDraftHistory((current) => {
      const previous = current.past.at(-1);
      if (!previous) return current;
      const present = snapshotDraft(srt, edits);
      setSrt(cloneSrt(previous.srt));
      setEdits({ ...previous.edits });
      setMessage('Undid subtitle edit.');
      return { past: current.past.slice(0, -1), future: [present, ...current.future].slice(0, MAX_DRAFT_HISTORY) };
    });
  }, [srt, edits]);
  const redoDraft = useCallback(() => {
    setDraftHistory((current) => {
      const next = current.future[0];
      if (!next) return current;
      const present = snapshotDraft(srt, edits);
      setSrt(cloneSrt(next.srt));
      setEdits({ ...next.edits });
      setMessage('Redid subtitle edit.');
      return { past: [...current.past, present].slice(-MAX_DRAFT_HISTORY), future: current.future.slice(1) };
    });
  }, [srt, edits]);

  const loadSrt = useCallback(async (assetId?: number) => {
    if (isEmptyWorkspace && !assetId) {
      setSrt(EMPTY_SRT); setEdits({}); setBaselineSrt(''); setDraftHistory({ past: [], future: [] }); return EMPTY_SRT;
    }
    try {
      const targetId = assetId ?? autoSrtAssetId;
      const data = targetId ? await studioApi.srtAsset(targetId) : await studioApi.srt(project.id);
      if (assetId !== undefined && assetId !== autoSrtAssetId) setAutoSrtAssetId(assetId);
      setSrt(data);
      setEdits(Object.fromEntries((data.segments || []).map((segment) => [segment.index, segment.text])));
      setBaselineSrt(serializeSrt(data.segments || [], {}));
      setDraftHistory({ past: [], future: [] });
      return data;
    } catch {
      setSrt(EMPTY_SRT); setEdits({}); setBaselineSrt(''); setDraftHistory({ past: [], future: [] }); return EMPTY_SRT;
    }
  }, [project.id, isEmptyWorkspace, autoSrtAssetId]);

  const loadSegments = useCallback(async () => {
    if (!srt.asset?.id) { setVoiceSegments([]); return; }
    try {
      const query = new URLSearchParams({ srtAssetId: String(srt.asset.id), engine: ttsEngine, voice: ttsVoice, language: ttsLanguage, rate: ttsEngine === 'vieneu' ? ttsRate : '1.0' });
      const data = await request<{ segments: VoiceSegment[] }>(`/videos/${project.id}/tts/segments?${query}`);
      setVoiceSegments(data.segments || []);
    } catch { setVoiceSegments([]); }
  }, [project.id, srt.asset?.id, ttsEngine, ttsVoice, ttsLanguage, ttsRate]);
  const loadTimelineIssues = useCallback(async () => {
    try {
      const data = await request<{ issues: TimelineIssue[] }>(`/videos/${project.id}/tts/timeline/issues`);
      setTimelineIssues(data.issues || []);
    } catch (error) {
      setTimelineIssues([]);
      setMessage(error instanceof Error ? error.message : 'Unable to load timing issues');
    }
  }, [project.id]);

  useEffect(() => {
    setRemovedVoiceAssetIds([]);
    setBlurEffectHidden(false);
    setSubtitleBlurEffect(project.subtitleBlurEffect);
    setOcrAreaMode('default');
    setOcrArea(DEFAULT_AREA);
    const nextTimelineState = timelineStateFromSceneOrProject(project);
    setTimelineState(nextTimelineState);
    setTimelineItems(nextTimelineState.items);
    setTimelineScene(sceneFromProject(project));
    setTimelineHistory({ past: [], future: [] });
  }, [project.id]);
  useEffect(() => {
    const nextTimelineState = timelineStateFromSceneOrProject(project);
    setTimelineState(nextTimelineState);
    setTimelineItems(nextTimelineState.items);
    setTimelineScene(sceneFromProject(project));
  }, [project.id, JSON.stringify(project.sceneState || project.timelineState || project.workspaceTimeline || [])]);
  useEffect(() => {
    if (!project.workspaceId || !timelineItems.length) return;
    const assetsById = new Map((project.projectAssets || []).map((asset) => [asset.id, asset]));
    let changed = false;
    const next = timelineItems.map((item) => {
      if (item.kind !== 'audio' || !item.projectAssetId || item.duration > 10.1 || (item.sourceStart || 0) > 0) return item;
      const asset = assetsById.get(item.projectAssetId);
      if (!asset) return item;
      const sourceDuration = projectAssetDurationSeconds(asset);
      if (sourceDuration <= item.duration + 1) return item;
      changed = true;
      return { ...item, duration: sourceDuration };
    });
    if (changed) void commitTimelineItems(next, 'Updated audio clip durations from source files.', timelineItems);
  }, [project.workspaceId, project.projectAssets, timelineItems]);
  useEffect(() => {
    setSubtitleBlurEffect(project.subtitleBlurEffect);
  }, [project.id, project.subtitleBlurEffect?.updated_at]);
  useEffect(() => {
    setArea(project.subtitleArea || DEFAULT_AREA);
    setStyle({ ...DEFAULT_STYLE, ...project.subtitleStyle });
    setAudioModeState(project.audioMode || 'original');
    setVideoScale(project.clipSettings?.videoScale ?? 1);
    setVideoVolumeDb(project.clipSettings?.videoVolumeDb ?? 0);
    setVideoSpeed(project.clipSettings?.videoSpeed ?? 1);
    setVoiceVolumeDb(project.clipSettings?.voiceVolumeDb ?? 0);
    setVoiceSpeed(project.clipSettings?.voiceSpeed ?? 1);
    setPreviewSource(latestVoiceAsset ? `tts:${latestVoiceAsset.id}` : 'preview');
    setSelection({ type: 'project' }); setPlayhead(0); loadSrt();
  }, [project.id, latestVoiceAsset?.id, loadSrt]);
  useEffect(() => {
    setAudioModeState(project.audioMode || 'original');
  }, [project.audioMode]);

  useEffect(() => {
    const original = originalSrtAssets[0];
    if (original) studioApi.srtAsset(original.id).then(setSourceSrt).catch(() => setSourceSrt(EMPTY_SRT));
    else setSourceSrt(EMPTY_SRT);
  }, [project.id, originalSrtAssets.map((item) => item.id).join(',')]);
  useEffect(() => {
    const translated = translatedSrtAssets.at(-1);
    if (translated) studioApi.srtAsset(translated.id).then(setTranslatedSrt).catch(() => setTranslatedSrt(EMPTY_SRT));
    else setTranslatedSrt(EMPTY_SRT);
  }, [project.id, translatedSrtAssets.map((item) => item.id).join(',')]);
  useEffect(() => {
    setAutoSrtAssetId((current) =>
      current && originalSrtAssets.some((asset) => asset.id === current)
        ? current
        : originalSrtAssets[0]?.id ?? null,
    );
  }, [project.id, originalSrtAssets.map((item) => item.id).join(',')]);
  useEffect(() => {
    function warnBeforeLeave(event: BeforeUnloadEvent) {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    }
    window.addEventListener('beforeunload', warnBeforeLeave);
    return () => window.removeEventListener('beforeunload', warnBeforeLeave);
  }, [dirty]);
  useEffect(() => { loadSegments(); }, [loadSegments]);
  useEffect(() => { if (project.hasTts) loadTimelineIssues(); else setTimelineIssues([]); }, [project.id, project.hasTts, loadTimelineIssues]);
  useEffect(() => { loadVoices(ttsEngine, ttsLanguage).catch(() => undefined); }, [ttsEngine, ttsLanguage, loadVoices]);
  useEffect(() => { if (!voices.some((voice) => voice.id === ttsVoice)) setTtsVoice(voices[0]?.id || 'default'); }, [voices, ttsVoice]);
  useEffect(() => {
    if (!latestJob || latestJob.status !== 'completed') return;
    if (['srt', 'translate'].includes(latestJob.kind) && handledSrtJobRef.current !== latestJob.id) {
      handledSrtJobRef.current = latestJob.id;
      const resultAssetId = Number(latestJob.result?.assetId || latestJob.result?.sourceAssetId || 0);
      attachSrtToTimeline(resultAssetId).catch(() => undefined);
    }
    if (['tts', 'tts-segment'].includes(latestJob.kind)) { loadSegments(); loadTimelineIssues(); }
    if (latestJob.kind === 'remove') setBlurEffectHidden(false);
    if (latestJob.kind === 'tts' && autoMuxTtsJobRef.current !== latestJob.id) {
      autoMuxTtsJobRef.current = latestJob.id;
      queue(`/videos/${project.id}/tts/mux-video`, undefined, 'Voice preview').catch(() => undefined);
    }
    if (['remove', 'replace'].includes(latestJob.kind) && latestJob.result?.videoId) onOpenVersion(Number(latestJob.result.videoId));
    if (latestJob.kind === 'audio-separate' && audioMode !== 'original') setMessage('Audio separation is ready. You can switch modes instantly.');
    refresh().catch(() => undefined);
  }, [latestJob?.id, latestJob?.status]);

  useEffect(() => {
    if (latestJob?.kind === 'tts-mux' && latestJob.status === 'completed' && latestVoiceAsset) {
      setPreviewSource(`tts:${latestVoiceAsset.id}`);
      setMessage('Voiceover is ready in the timeline and preview.');
    }
  }, [latestJob?.id, latestJob?.status, latestVoiceAsset?.id]);

  function openTool(tool: ToolKey) {
    setActiveTool(tool); setAssetTab('tools');
    if (tool === 'remove' || tool === 'insert') setSelection({ type: 'effect', operation: tool === 'remove' ? 'blur' : 'insert' });
  }

  async function queue(path: string, body?: unknown, label = 'Job') {
    if (isEmptyWorkspace) {
      setMessage('Add a video to the timeline before running this tool.');
      return null;
    }
    try {
      const result = await request<{ jobId: number; alreadyRunning?: boolean }>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
      setMessage(`${result.alreadyRunning ? 'Using active' : 'Queued'} ${label.toLowerCase()} #${result.jobId}.`);
      window.setTimeout(refresh, 500);
      return result;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${label} failed to start`);
      return null;
    }
  }

  function previewTimelineItems(next: TimelineItem[]) {
    const cleanState = normalizeTimelineState({ ...timelineState, items: cloneTimelineItems(next) });
    setTimelineState(cleanState);
    setTimelineItems(cleanState.items);
    setTimelineScene(timelineStateToScene(cleanState, { sceneId: timelineScene.id }));
  }

  async function commitTimelineState(nextState: TimelineState, messageText = 'Timeline updated.', previousState: TimelineState = timelineState) {
    if (!project.workspaceId) {
      setMessage('Open a workspace project before changing the timeline.');
      return false;
    }
    const previous = cloneTimelineState(previousState);
    const cleanNext = normalizeTimelineState(nextState);
    const previousScene = timelineScene;
    const nextScene = timelineStateToScene(cleanNext, { sceneId: previousScene.id });
    setTimelineHistory((current) => ({ past: [...current.past, previous].slice(-MAX_DRAFT_HISTORY), future: [] }));
    setTimelineState(cleanNext);
    setTimelineItems(cleanNext.items);
    setTimelineScene(nextScene);
    try {
      await studioApi.saveWorkspaceTimeline(project.workspaceId, cleanNext.items, cleanNext, nextScene);
      await refresh();
      setMessage(messageText);
      return true;
    } catch (error) {
      setTimelineState(previous);
      setTimelineItems(previous.items);
      setTimelineScene(previousScene);
      setTimelineHistory((current) => ({ past: current.past.slice(0, -1), future: current.future }));
      setMessage(error instanceof Error ? error.message : 'Unable to save timeline');
      return false;
    }
  }

  async function attachSrtToTimeline(assetId: number) {
    if (!project.workspaceId || !assetId) return;

    const loadedData = await loadSrt(assetId);
    const currentTimeline = timelineStateRef.current;
    
    const nextItems = currentTimeline.items.filter((item) => !(item.track === 'S1' && item.kind === 'srt'));
    const durationBase = loadedData?.segments?.at(-1)?.end || 10;
    
    const track = 'S1';
    
    const item: TimelineItem = {
      id: nextTimelineClipId('srt', assetId),
      kind: 'srt',
      name: loadedData?.asset?.name || 'Subtitles',
      sourceStart: 0,
      sourceDuration: durationBase,
      sourceAssetId: assetId,
      track,
      start: 0,
      duration: frameRound(durationBase, currentTimeline.fps),
    };
    
    const nextState = normalizeTimelineState({
      ...currentTimeline,
      items: [...nextItems, item]
    });
    
    await commitTimelineState(nextState, 'Attached generated SRT', currentTimeline);
  }

  async function commitTimelineItems(next: TimelineItem[], messageText = 'Timeline updated.', previousItems: TimelineItem[] = timelineItems) {
    const previous = normalizeTimelineState({ ...timelineState, items: cloneTimelineItems(previousItems) });
    const editedIds = new Set(next.filter((item) => {
      const before = previousItems.find((candidate) => candidate.id === item.id);
      return before && (
        Math.abs(before.start - item.start) > 0.001
        || Math.abs(before.duration - item.duration) > 0.001
        || before.track !== item.track
      );
    }).map((item) => item.id));
    const cleanNext = cloneTimeline(timelineState.options.ripple && editedIds.size ? rippleAfterEdit(previousItems, next, editedIds) : next)
      .map((item) => ({ ...item, start: Math.max(0, item.start), duration: Math.max(0.05, item.duration) }));
    return commitTimelineState(normalizeTimelineState({ ...timelineState, items: cleanNext }), messageText, previous);
  }

  async function undoTimeline() {
    if (!project.workspaceId || !timelineHistory.past.length) return false;
    const previous = timelineHistory.past.at(-1)!;
    const present = cloneTimelineState(timelineState);
    const next = cloneTimelineState(previous);
    const presentScene = timelineScene;
    const nextScene = timelineStateToScene(next, { sceneId: presentScene.id });
    setTimelineHistory((current) => ({ past: current.past.slice(0, -1), future: [present, ...current.future].slice(0, MAX_DRAFT_HISTORY) }));
    setTimelineState(next);
    setTimelineItems(next.items);
    setTimelineScene(nextScene);
    try {
      await studioApi.saveWorkspaceTimeline(project.workspaceId, next.items, next, nextScene);
      await refresh();
      setMessage('Undid timeline edit.');
      return true;
    } catch (error) {
      setTimelineState(present);
      setTimelineItems(present.items);
      setTimelineScene(presentScene);
      setMessage(error instanceof Error ? error.message : 'Unable to undo timeline edit');
      return false;
    }
  }

  async function redoTimeline() {
    if (!project.workspaceId || !timelineHistory.future.length) return false;
    const nextSnapshot = timelineHistory.future[0];
    const present = cloneTimelineState(timelineState);
    const next = cloneTimelineState(nextSnapshot);
    const presentScene = timelineScene;
    const nextScene = timelineStateToScene(next, { sceneId: presentScene.id });
    setTimelineHistory((current) => ({ past: [...current.past, present].slice(-MAX_DRAFT_HISTORY), future: current.future.slice(1) }));
    setTimelineState(next);
    setTimelineItems(next.items);
    setTimelineScene(nextScene);
    try {
      await studioApi.saveWorkspaceTimeline(project.workspaceId, next.items, next, nextScene);
      await refresh();
      setMessage('Redid timeline edit.');
      return true;
    } catch (error) {
      setTimelineState(present);
      setTimelineItems(present.items);
      setTimelineScene(presentScene);
      setMessage(error instanceof Error ? error.message : 'Unable to redo timeline edit');
      return false;
    }
  }

  function undoEditorAction() {
    if (project.workspaceId && timelineHistory.past.length) {
      void undoTimeline();
      return;
    }
    undoDraft();
  }

  function redoEditorAction() {
    if (project.workspaceId && timelineHistory.future.length) {
      void redoTimeline();
      return;
    }
    redoDraft();
  }

  async function addVideoToTimeline(videoId: number, placementOptions?: { trackId?: string; start?: number }) {
    if (!project.workspaceId) {
      setMessage('Open a workspace project before adding timeline clips.');
      return;
    }
    const source = projects.find((item) => item.id === videoId);
    const projectAsset = (project.projectAssets || []).find((item) => item.sourceVideoId === videoId);
    try {
      await studioApi.attachWorkspaceVideos(project.workspaceId, [videoId]);
      const durationMs = source?.durationMs || Number(projectAsset?.metadata?.duration_ms || 0);
      const clipDuration = Math.max(0.5, (durationMs / 1000) || 5);
      const previous = cloneTimelineState(timelineState);
      const placement = resolvePlacement({
        state: timelineState,
        kind: 'video',
        preferredTrackId: placementOptions?.trackId,
        requestedStart: placementOptions?.start,
        duration: clipDuration,
      });
      const item: TimelineItem = {
        id: nextTimelineClipId('video', videoId),
        kind: 'video',
        track: placement.trackId,
        name: projectAsset?.name || source?.name || source?.title || `Video ${videoId}`,
        start: frameRound(placement.start, timelineState.fps),
        duration: frameRound(clipDuration, timelineState.fps),
        sourceStart: 0,
        sourceDuration: clipDuration,
        sourceVideoId: videoId,
      };
      const nextState = normalizeTimelineState({
        ...timelineState,
        tracks: placement.createdTrack ? [...timelineState.tracks, placement.createdTrack] : timelineState.tracks,
        items: [...timelineState.items, item],
      });
      if (await commitTimelineState(nextState, `Added video clip to ${placement.trackId}.`, previous)) {
        setSelection({ type: 'timeline-items', keys: [item.id], track: placement.trackId });
        setPlayhead(item.start);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to add video to timeline');
    }
  }

  async function addProjectAssetToTimeline(asset: ProjectAsset, placementOptions?: { trackId?: string; start?: number }) {
    if (asset.kind === 'video' && asset.sourceVideoId) {
      await addVideoToTimeline(asset.sourceVideoId, placementOptions);
      return;
    }
    if (!project.workspaceId) {
      setMessage('Open a workspace project before adding timeline clips.');
      return;
    }
    const kind = asset.kind === 'image' ? 'image' : asset.kind === 'audio' ? 'audio' : asset.kind === 'srt' ? 'srt' : null;
    if (!kind) {
      setMessage('This asset type cannot be placed on the timeline yet.');
      return;
    }
    let durationBase = srt.segments.at(-1)?.end || 0;
    if (asset.kind === 'srt') {
      try {
        const loaded = await loadSrt(asset.sourceAssetId || asset.id);
        if (loaded && loaded.segments && loaded.segments.length > 0) {
          durationBase = loaded.segments.at(-1)?.end || durationBase;
        }
      } catch (e) {
        // ignore
      }
    }
    const previous = cloneTimelineState(timelineState);
    const created = createItemFromProjectAsset(asset, timelineState, durationBase);
    const baseItem = created.item;
    const placement = placementOptions
      ? resolvePlacement({
          state: timelineState,
          kind: baseItem.kind,
          preferredTrackId: placementOptions.trackId,
          requestedStart: placementOptions.start,
          duration: baseItem.duration,
        })
      : { trackId: baseItem.track, start: baseItem.start, createdTrack: null };
    const track = placement.trackId || defaultTrackForKind(baseItem.kind);
    const item: TimelineItem = {
      ...baseItem,
      id: nextTimelineClipId(kind, asset.id),
      track,
      start: frameRound(placement.start, timelineState.fps),
      duration: frameRound(baseItem.duration, timelineState.fps),
    };
    const nextTracks = [
      ...timelineState.tracks,
      ...(created.state.tracks.filter((candidate) => !timelineState.tracks.some((track) => track.id === candidate.id))),
      ...(placement.createdTrack ? [placement.createdTrack] : []),
    ];
    const nextState = normalizeTimelineState({ ...timelineState, tracks: nextTracks, items: [...timelineState.items, item] });
    try {
      if (await commitTimelineState(nextState, `${asset.kind.toUpperCase()} asset was placed on ${track}.`, previous)) {
        setSelection({ type: 'timeline-items', keys: [item.id], track });
        setPlayhead(item.start);
      }
    } catch (error) {
      const fallback = timelineStateFromProject(project);
      setTimelineState(fallback);
      setTimelineItems(fallback.items);
      setMessage(error instanceof Error ? error.message : 'Unable to add asset to timeline');
    }
  }

  async function deleteTimelineItems(keys: string[]) {
    if (!project.workspaceId) return;
    const remove = new Set(keys);
    if (!remove.size) return;
    const previous = cloneTimeline(timelineItems);
    const removedItems = timelineItems.filter((item) => remove.has(item.id));
    const removedSrtAssetIds = new Set(removedItems.map(srtAssetIdForTimelineItem).filter((id): id is number => typeof id === 'number'));
    const next = timelineItems.filter((item) => !remove.has(item.id) && !(item.kind === 'audio' && item.linkedVideoItemId && remove.has(item.linkedVideoItemId)))
      .map((item) => item.kind === 'video' && keys.some((key) => timelineItems.some((clip) => clip.id === key && clip.kind === 'audio' && clip.linkedVideoItemId === item.id))
        ? { ...item, sourceAudioMuted: false }
        : item);
    const remainingSrtAssetIds = new Set(next.map(srtAssetIdForTimelineItem).filter((id): id is number => typeof id === 'number'));
    const shouldClearLoadedSrt = Boolean(srt.asset?.id && removedSrtAssetIds.has(srt.asset.id) && !remainingSrtAssetIds.has(srt.asset.id));
    setSelection({ type: 'project' });
    setPlayhead(Math.min(playhead, Math.max(0, endOfTimeline(next))));
    const saved = await commitTimelineItems(next, `Deleted ${timelineItems.length - next.length} timeline clip${timelineItems.length - next.length === 1 ? '' : 's'}.`, previous);
    if (saved && shouldClearLoadedSrt) {
      setSrt(EMPTY_SRT);
      setEdits({});
      setBaselineSrt('');
      setDraftHistory({ past: [], future: [] });
      setVoiceSegments([]);
    }
  }

  function selectedTimelineClipKeys() {
    return selection.type === 'timeline-items'
      ? selection.keys.filter((key) => timelineItems.some((item) => item.id === key))
      : [];
  }

  async function splitSelectedTimelineItems(retain: 'both' | 'left' | 'right' = 'both') {
    const keys = selectedTimelineClipKeys();
    if (!keys.length) {
      setMessage('Select a timeline clip before splitting.');
      return false;
    }
    const previous = cloneTimelineState(timelineState);
    const { state, created } = splitItemsAtTime(timelineState, keys, frameRound(playhead, timelineState.fps), retain);
    if (!created.length && retain === 'both') {
      setMessage('Move the playhead inside the selected clip before splitting.');
      return false;
    }
    const ok = await commitTimelineState(state, created.length ? `Split ${keys.length} clip${keys.length === 1 ? '' : 's'}.` : 'Timeline split updated.', previous);
    if (ok && created.length) {
      setSelection({ type: 'timeline-items', keys: [...keys, ...created.map((item) => item.id)], track: created[0].track });
    }
    return ok;
  }

  async function duplicateSelectedTimelineItems() {
    const keys = selectedTimelineClipKeys();
    if (!keys.length) {
      setMessage('Select timeline clips to duplicate.');
      return false;
    }
    const previous = cloneTimelineState(timelineState);
    const { state, duplicated } = duplicateItems(timelineState, keys);
    const ok = await commitTimelineState(state, `Duplicated ${duplicated.length} clip${duplicated.length === 1 ? '' : 's'}.`, previous);
    if (ok && duplicated.length) {
      setSelection({ type: 'timeline-items', keys: duplicated.map((item) => item.id), track: duplicated[0].track });
      setPlayhead(duplicated[0].start);
    }
    return ok;
  }

  async function copyTimelineItems() {
    const keys = selectedTimelineClipKeys();
    if (!keys.length) {
      setMessage('Select timeline clips to copy.');
      return false;
    }
    try {
      await navigator.clipboard.writeText(serializeClipboardItems(timelineState, keys));
      setMessage(`Copied ${keys.length} timeline clip${keys.length === 1 ? '' : 's'}.`);
      return true;
    } catch {
      setMessage('Clipboard access is unavailable.');
      return false;
    }
  }

  async function pasteTimelineItemsAt(time = playhead) {
    try {
      const raw = await navigator.clipboard.readText();
      const clips = parseClipboardItems(raw);
      if (!clips.length) {
        setMessage('Clipboard does not contain timeline clips.');
        return false;
      }
      const previous = cloneTimelineState(timelineState);
      const { state, pasted } = pasteItems(timelineState, clips, frameRound(time, timelineState.fps));
      const ok = await commitTimelineState(state, `Pasted ${pasted.length} timeline clip${pasted.length === 1 ? '' : 's'}.`, previous);
      if (ok && pasted.length) {
        setSelection({ type: 'timeline-items', keys: pasted.map((item) => item.id), track: pasted[0].track });
        setPlayhead(pasted[0].start);
      }
      return ok;
    } catch {
      setMessage('Clipboard access is unavailable.');
      return false;
    }
  }

  async function addTimelineTrack(kind: TimelineTrackKind) {
    const previous = cloneTimelineState(timelineState);
    const { state, track } = addTrackToTimelineState(timelineState, kind);
    return commitTimelineState(state, `Added ${track.id}.`, previous);
  }

  async function removeTimelineTrack(trackId: string) {
    const previous = cloneTimelineState(timelineState);
    const state = removeTrackFromTimelineState(timelineState, trackId);
    if (state === timelineState) {
      setMessage('Default tracks cannot be removed.');
      return false;
    }
    if (timelineState.items.some((item) => item.track === trackId)) {
      setSelection({ type: 'project' });
    }
    return commitTimelineState(state, `Removed ${trackId}.`, previous);
  }

  async function toggleTimelineTrackMute(trackId: string) {
    return commitTimelineState(toggleTimelineTrackMuteInState(timelineState, trackId), `Toggled mute for ${trackId}.`, cloneTimelineState(timelineState));
  }

  async function toggleTimelineTrackVisibility(trackId: string) {
    return commitTimelineState(toggleTimelineTrackVisibilityInState(timelineState, trackId), `Toggled visibility for ${trackId}.`, cloneTimelineState(timelineState));
  }

  async function setTimelineOption(option: 'snapping' | 'ripple', enabled: boolean) {
    const next = normalizeTimelineState({ ...timelineState, options: { ...timelineState.options, [option]: enabled } });
    return commitTimelineState(next, `${option === 'snapping' ? 'Snapping' : 'Ripple'} ${enabled ? 'enabled' : 'disabled'}.`, cloneTimelineState(timelineState));
  }

  async function toggleTimelineBookmark(time = playhead) {
    const at = frameRound(time, timelineState.fps);
    const existing = timelineState.bookmarks.find((bookmark) => Math.abs(bookmark.time - at) < 0.02);
    const bookmarks = existing
      ? timelineState.bookmarks.filter((bookmark) => bookmark.id !== existing.id)
      : [...timelineState.bookmarks, { id: nextTimelineClipId('bookmark'), time: at, color: '#f59e0b' }];
    const next = normalizeTimelineState({ ...timelineState, bookmarks });
    return commitTimelineState(next, existing ? 'Removed bookmark.' : 'Added bookmark.', cloneTimelineState(timelineState));
  }

  async function captureCurrentFrame() {
    const videoId = activeTimelineVideoId;
    if (!videoId) {
      setMessage('Move the playhead onto a video clip before capturing a frame.');
      return;
    }
    try {
      const result = await request<{ asset?: { id: number; name?: string } }>(
        `/videos/${videoId}/frame?timeSeconds=${encodeURIComponent(activeTimelineLocalTime.toFixed(3))}`,
        { method: 'POST' },
      );
      const assetId = Number(result.asset?.id || 0);
      if (project.workspaceId && assetId) {
        await studioApi.attachWorkspaceAssets(project.workspaceId, [assetId]);
      }
      await refresh();
      setAssetTab('assets');
      setMessage(`Captured frame${result.asset?.name ? `: ${result.asset.name}` : ''}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to capture current frame');
    }
  }

  async function extractAudioFromTimelineClip(item: TimelineItem) {
    if (!project.workspaceId) {
      setMessage('Open a workspace project before extracting audio to A1.');
      return;
    }
    if (item.kind !== 'video' || !item.sourceVideoId) {
      setMessage('Right-click a video clip to extract its source audio.');
      return;
    }
    const linkedAudio = timelineItems.find((clip) =>
      clip.kind === 'audio'
      && clip.track === 'A1'
      && (
        clip.linkedVideoItemId === item.id
        || (
          !clip.linkedVideoItemId
          && clip.sourceVideoId === item.sourceVideoId
          && Math.abs(clip.start - item.start) < 0.01
          && Math.abs(clip.duration - item.duration) < 0.01
        )
      )
    );
    if (linkedAudio || item.sourceAudioMuted) {
      const previous = cloneTimeline(timelineItems);
      const next = timelineItems
        .filter((clip) => clip.id !== linkedAudio?.id)
        .map((clip) => clip.id === item.id ? { ...clip, sourceAudioMuted: false } : clip);
      if (await commitTimelineItems(next, 'Khôi phục âm thanh gốc cho clip video.', previous)) {
        setSelection({ type: 'timeline-items', keys: [item.id], track: 'V1' });
        setPlayhead(item.start);
      }
      return;
    }
    try {
      setMessage('Extracting source audio...');
      const extracted = await studioApi.extractAudio(item.sourceVideoId);
      const attached = await studioApi.attachWorkspaceAssets(project.workspaceId, [extracted.asset.id]);
      const projectAsset = attached.project.assets.find((asset) => asset.sourceAssetId === extracted.asset.id);
      const previous = cloneTimeline(timelineItems);
      const audioClip: TimelineItem = {
        id: nextTimelineClipId('audio-source', item.sourceVideoId),
        kind: 'audio',
        track: 'A1',
        name: `${item.name} audio`,
        start: item.start,
        duration: item.duration,
        sourceStart: item.sourceStart || 0,
        sourceVideoId: item.sourceVideoId,
        sourceAssetId: extracted.asset.id,
        projectAssetId: projectAsset?.id,
        linkedVideoItemId: item.id,
      };
      const next = timelineItems.map((clip) => clip.id === item.id ? { ...clip, sourceAudioMuted: true } : clip).concat(audioClip);
      if (await commitTimelineItems(next, extracted.reused ? 'Tách âm thanh gốc sang A1.' : 'Đã trích xuất âm thanh gốc sang A1.', previous)) {
        setSelection({ type: 'timeline-items', keys: [audioClip.id], track: 'A1' });
        setPlayhead(item.start);
      }
    } catch (error) {
      const fallback = timelineStateFromProject(project);
      setTimelineState(fallback);
      setTimelineItems(fallback.items);
      setMessage(error instanceof Error ? error.message : 'Unable to extract source audio');
    }
  }

  async function setAudioMode(mode: AudioMode) {
    const previous = audioMode;
    setAudioModeState(mode);
    try {
      const result = await studioApi.setAudioMode(project.id, mode);
      if (mode === 'original') {
        setMessage('Restored the original audio.');
      } else if (result.ready) {
        setMessage(mode === 'remove_vocals' ? 'Using instrumental audio.' : 'Using vocal audio.');
      } else {
        setMessage(`${result.alreadyRunning ? 'Using active' : 'Queued'} audio separation${result.jobId ? ` #${result.jobId}` : ''}.`);
      }
      window.setTimeout(refresh, result.ready ? 100 : 400);
    } catch (error) {
      setAudioModeState(previous);
      setMessage(error instanceof Error ? error.message : 'Unable to change the audio mode');
    }
  }

  async function setTimelineVideoAudioMode(videoId: number, mode: AudioMode) {
    const current = projects.find((item) => item.id === videoId) || (project.id === videoId ? project : undefined);
    const wasCurrentProject = project.id === videoId;
    const previous = audioMode;
    if (wasCurrentProject) setAudioModeState(mode);
    try {
      const result = await studioApi.setAudioMode(videoId, mode);
      if (mode === 'original') {
        setMessage('Giữ nguyên âm thanh gốc cho clip này.');
      } else if (result.ready) {
        setMessage(mode === 'remove_vocals' ? 'Đã chọn Bỏ lời cho clip này.' : 'Đã chọn Giữ lời cho clip này.');
      } else {
        setMessage(`${result.alreadyRunning ? 'Đang dùng job hiện có' : 'Đã tạo job'} tách giọng nói${result.jobId ? ` #${result.jobId}` : ''}.`);
      }
      window.setTimeout(refresh, result.ready ? 100 : 400);
    } catch (error) {
      if (wasCurrentProject) setAudioModeState(previous);
      setMessage(error instanceof Error ? error.message : `Unable to change audio mode${current ? ` for ${current.title}` : ''}`);
    }
  }

  async function saveSrt() {
    if (!srt.asset?.id) return;
    await studioApi.saveSrtAsset(srt.asset.id, serializeSrt(srt.segments, edits));
    await loadSrt(srt.asset.id); setMessage('Subtitle changes saved.');
  }
  async function copySrt() {
    if (!srt.segments.length) {
      setMessage('No subtitle content to copy.');
      return;
    }
    try {
      await navigator.clipboard.writeText(serializeSrt(srt.segments, edits));
      setMessage(`Copied ${srt.segments.length} subtitle lines.`);
    } catch {
      setMessage('Clipboard access is unavailable.');
    }
  }
  async function pasteSrt() {
    if (!srt.segments.length) {
      setMessage('Select a subtitle track before pasting.');
      return;
    }
    try {
      const content = await navigator.clipboard.readText();
      const blocks = content.replace(/\r/g, '').split(/\n{2,}/);
      const parsed = blocks.map((block, position) => {
        const lines = block.split('\n').filter((line) => line.trim());
        const timeIndex = lines.findIndex((line) => line.includes('-->'));
        if (timeIndex < 0) return null;
        const explicitIndex = timeIndex > 0 && /^\d+$/.test(lines[timeIndex - 1].trim()) ? Number(lines[timeIndex - 1]) : null;
        return { index: explicitIndex, position, text: lines.slice(timeIndex + 1).join('\n').trim() };
      }).filter(Boolean) as Array<{ index: number | null; position: number; text: string }>;
      if (!parsed.length) {
        setMessage('Clipboard does not contain readable SRT.');
        return;
      }
      const byIndex = new Map(parsed.filter((item) => item.index !== null).map((item) => [item.index, item.text]));
      const next = { ...edits };
      let count = 0;
      srt.segments.forEach((segment, position) => {
        const text = byIndex.get(segment.index) ?? parsed[position]?.text;
        if (text !== undefined) { next[segment.index] = text; count++; }
      });
      commitDraft(srt, next, `Pasted ${count} subtitle lines. Review and save the script.`);
    } catch {
      setMessage('Clipboard access is unavailable.');
    }
  }
  function updateSegmentTime(index: number, field: 'startLabel' | 'endLabel', label: string) {
    const match = label.match(/^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$/);
    const seconds = match ? Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4]) / 1000 : null;
    const nextSrt = { ...srt, segments: srt.segments.map((segment) => segment.index === index ? {
      ...segment,
      [field]: label,
      ...(seconds === null ? {} : field === 'startLabel' ? { start: seconds } : { end: seconds }),
    } : segment) };
    commitDraft(nextSrt, edits);
  }
  function deleteSegment(index: number) {
    deleteSegments([index]);
  }
  function selectedSubtitleIndexes() {
    if (selection.type === 'subtitle') return [selection.index];
    if (selection.type !== 'timeline-items') return [];
    return [...new Set(selection.keys
      .filter((key) => key.startsWith('subtitle:') || key.startsWith('subtitle-translated:'))
      .map((key) => Number(key.split(':')[1]))
      .filter(Number.isFinite))];
  }
  function deleteSegments(indexes: number[]) {
    const selected = new Set(indexes);
    if (!selected.size) return;
    const removed = srt.segments.filter((segment) => selected.has(segment.index)).length;
    if (!removed) return;
    
    const remaining = srt.segments.filter((segment) => !selected.has(segment.index));
    if (remaining.length === 0 && srt.asset?.id) {
      void studioApi.deleteAsset(srt.asset.id).then(() => {
        setSrt(EMPTY_SRT);
        setEdits({});
        setBaselineSrt('');
        setDraftHistory({ past: [], future: [] });
        void refresh();
        setSelection({ type: 'project' });
      });
      return;
    }

    const nextEdits = { ...edits };
    selected.forEach((index) => delete nextEdits[index]);
    commitDraft({ ...srt, segments: remaining }, nextEdits, `Removed ${removed} subtitle ${removed === 1 ? 'line' : 'lines'} from the draft. Press Undo to restore.`);
    setSelection({ type: 'subtitle-track', assetId: srt.asset?.id });
  }
  function deleteSelectedSubtitles() {
    deleteSegments(selectedSubtitleIndexes());
  }
  function moveSubtitleSegments(indexes: number[], verticalDelta: number) {
    if (!indexes.length || !Number.isFinite(verticalDelta) || Math.abs(verticalDelta) < .001) return;
    const height = area.ymax - area.ymin;
    const ymin = Math.max(0, Math.min(1 - height, area.ymin + verticalDelta));
    void saveSubtitleArea({ ...area, ymin, ymax: ymin + height }, false);
    setMessage(`Moved subtitle position ${verticalDelta > 0 ? 'down' : 'up'} in the preview.`);
  }
  async function saveSubtitleArea(nextArea: SubtitleArea, moveBlurEffect?: boolean) {
    setArea(nextArea);
    const updateBlurEffect = moveBlurEffect ?? (activeTool === 'remove' && removeMethod === 'manual' && Boolean(activeBlurEffect));
    if (updateBlurEffect && activeBlurEffect) {
      setSubtitleBlurEffect({ ...activeBlurEffect, area: nextArea, mode: 'manual', source: 'manual-editor' });
    }
    try {
      const result = await studioApi.saveSubtitleArea(
        project.id,
        nextArea,
        updateBlurEffect ? { blurEffectArea: nextArea } : undefined,
      );
      if (result.subtitleArea) setArea(result.subtitleArea);
      if (result.subtitleBlurEffect) setSubtitleBlurEffect(result.subtitleBlurEffect);
      setMessage('Subtitle position saved.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save subtitle position');
    }
  }

  async function saveSubtitleStyle(nextStyle: SubtitleStyle, messageText?: string) {
    setStyle(nextStyle);
    try {
      const result = await studioApi.saveSubtitleArea(
        project.id,
        area,
        { style: nextStyle }
      );
      if (result.subtitleStyle) setStyle(result.subtitleStyle);
      if (messageText) setMessage(messageText);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save subtitle style');
    }
  }

  async function updateSubtitleStyle(updates: Partial<SubtitleStyle>) {
    const presetChanged = Object.prototype.hasOwnProperty.call(updates, 'presetId');
    const nextStyle = {
      ...style,
      ...updates,
      presetModified: presetChanged ? updates.presetModified : (style.presetId ? true : style.presetModified),
    } as SubtitleStyle;
    await saveSubtitleStyle(nextStyle);
  }

  async function applySubtitleStylePreset(presetId: string) {
    const nextStyle = resolvedPresetStyle(presetId, style);
    if (!nextStyle) return;
    await saveSubtitleStyle(nextStyle, `Applied ${textStylePresetById(presetId)?.name || 'text preset'} to subtitles.`);
  }

  async function resetSubtitleStylePreset() {
    const nextStyle = resolvedPresetStyle(undefined, style);
    if (nextStyle) {
      await saveSubtitleStyle(nextStyle, 'Subtitle style reset.');
    }
  }

  async function updateTimelineTextStyle(updates: Partial<TextStyle>) {
    if (!project.workspaceId || !selectedTextItems.length) return;
    const selected = new Set(selectedTextItems.map((item) => item.id));
    const previous = cloneTimeline(timelineItems);
    const next = timelineItems.map((item) => {
      if (!selected.has(item.id)) return item;
      const existing = typeof item.params?.textStyle === 'object' && item.params.textStyle ? item.params.textStyle as TextStyle : {};
      return {
        ...item,
        params: {
          ...(item.params || {}),
          textStyle: {
            ...DEFAULT_STYLE,
            ...existing,
            ...updates,
            presetModified: Object.prototype.hasOwnProperty.call(updates, 'presetId') ? updates.presetModified : (existing.presetId ? true : existing.presetModified),
          },
        },
      };
    });
    await commitTimelineItems(next, 'Updated text style.', previous);
  }

  async function applyTimelineTextStylePreset(presetId: string) {
    if (!project.workspaceId || !selectedTextItems.length) return;
    const selected = new Set(selectedTextItems.map((item) => item.id));
    const previous = cloneTimeline(timelineItems);
    let changed = false;
    const next = timelineItems.map((item) => {
      if (!selected.has(item.id)) return item;
      const existing = typeof item.params?.textStyle === 'object' && item.params.textStyle ? item.params.textStyle as TextStyle : {};
      const nextStyle = resolvedPresetStyle(presetId, existing);
      if (!nextStyle) return item;
      changed = true;
      return {
        ...item,
        params: {
          ...(item.params || {}),
          textStyle: nextStyle,
        },
      };
    });
    if (changed) {
      await commitTimelineItems(next, `Applied ${textStylePresetById(presetId)?.name || 'text preset'}`, previous);
    }
  }

  async function resetTimelineTextStylePreset() {
    if (!project.workspaceId || !selectedTextItems.length) return;
    const selected = new Set(selectedTextItems.map((item) => item.id));
    const previous = cloneTimeline(timelineItems);
    let changed = false;
    const next = timelineItems.map((item) => {
      if (!selected.has(item.id)) return item;
      const existing = typeof item.params?.textStyle === 'object' && item.params.textStyle ? item.params.textStyle as TextStyle : {};
      const nextStyle = resolvedPresetStyle(undefined, existing);
      if (!nextStyle) return item;
      changed = true;
      return {
        ...item,
        params: {
          ...(item.params || {}),
          textStyle: nextStyle,
        },
      };
    });
    if (changed) {
      await commitTimelineItems(next, 'Reset text style', previous);
    }
  }

  async function distributeTimelineTextItems(axis: 'horizontal' | 'vertical') {
    if (!project.workspaceId || selectedTextItems.length < 3) return;
    const selected = [...selectedTextItems].sort((a, b) => {
      const aPos = textItemPosition(a, timelineItems.indexOf(a));
      const bPos = textItemPosition(b, timelineItems.indexOf(b));
      return axis === 'horizontal' ? aPos.x - bPos.x : aPos.y - bPos.y;
    });
    const first = textItemPosition(selected[0], timelineItems.indexOf(selected[0]));
    const last = textItemPosition(selected[selected.length - 1], timelineItems.indexOf(selected[selected.length - 1]));
    const previous = cloneTimeline(timelineItems);
    const positions = new Map<string, { x: number; y: number }>();
    selected.forEach((item, index) => {
      const current = textItemPosition(item, timelineItems.indexOf(item));
      const ratio = index / Math.max(1, selected.length - 1);
      positions.set(item.id, {
        x: axis === 'horizontal' ? first.x + (last.x - first.x) * ratio : current.x,
        y: axis === 'vertical' ? first.y + (last.y - first.y) * ratio : current.y,
      });
    });
    const next = timelineItems.map((item) => {
      const position = positions.get(item.id);
      if (!position) return item;
      return {
        ...item,
        params: {
          ...(item.params || {}),
          textPosition: {
            x: clampClipValue(position.x, 0, 1),
            y: clampClipValue(position.y, 0, 1),
          },
        },
      };
    });
    await commitTimelineItems(next, axis === 'horizontal' ? 'Distributed text clips horizontally.' : 'Distributed text clips vertically.', previous);
  }

  function textItemPosition(item: TimelineItem, index: number) {
    const raw = item.params?.textPosition;
    const position = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    const fallbackX = 0.5 + Math.max(0, index) * 0.02;
    const fallbackY = 0.45 + Math.max(0, index) * 0.08;
    return {
      x: clampClipValue(Number(position.x ?? fallbackX), 0, 1),
      y: clampClipValue(Number(position.y ?? fallbackY), 0, 1),
    };
  }

  function moveSelectedSubtitles(deltaSeconds: number) {
    moveSubtitleSegments(selectedSubtitleIndexes(), deltaSeconds);
  }
  async function replaceWithTranslated() {
    const asset = translatedSrtAssets.at(-1);
    if (!asset) { setMessage('Create a translated SRT before replacing the original subtitles.'); return; }
    if (translatedSrt.asset?.id !== asset.id) { setMessage('The translated SRT is still loading. Try again in a moment.'); return; }
    const translatedByIndex = new Map(translatedSrt.segments.map((segment) => [segment.index, segment.text]));
    const nextEdits = { ...edits };
    let replaced = 0;
    srt.segments.forEach((segment) => {
      const translatedText = translatedByIndex.get(segment.index);
      if (translatedText !== undefined && translatedText !== (edits[segment.index] ?? segment.text)) {
        nextEdits[segment.index] = translatedText;
        replaced++;
      }
    });
    if (!replaced) { setMessage('The selected SRT already matches the translated subtitles.'); return; }
    commitDraft(srt, nextEdits, `Replaced ${replaced} subtitle ${replaced === 1 ? 'line' : 'lines'} with translated text. Save the script to persist it.`);
  }

  async function generateSrt() {
    const body = {
      source: project.workspaceId ? 'audio' : subtitleSource,
      model,
      device,
      language,
      hardsubMode,
      ocrArea: subtitleSource === 'hardsub' && ocrAreaMode === 'custom' ? ocrArea : null,
      timelineSpeed: videoSpeed,
    };
    if (!project.workspaceId) {
      await queue(`/videos/${project.id}/srt/generate`, body, 'Subtitle job');
      return;
    }
    try {
      const result = await request<{ jobId: number; alreadyRunning?: boolean }>(
        `/projects/${project.workspaceId}/srt/generate`,
        { method: 'POST', body: JSON.stringify(body) },
      );
      setMessage(`${result.alreadyRunning ? 'Using active' : 'Queued'} timeline subtitle job #${result.jobId}.`);
      window.setTimeout(refresh, 500);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Subtitle job failed to start');
    }
  }
  async function importSrt(file?: File) {
    if (!file) return;
    try {
      const result = await studioApi.importSrt(project.id, file, srt.asset?.id);
      const assetId = Number((result.asset as { id?: number })?.id || 0);
      await refresh();
      await loadSrt(assetId || undefined);
      setSelection({ type: 'subtitle-track', assetId: assetId || undefined });
      setMessage('Imported SRT replaced the active subtitle track. The previous version is saved in history.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to import SRT');
    }
  }
  async function translate() {
    await saveSrt();
    await queue(`/videos/${project.id}/srt/translate`, { srtAssetId: srt.asset?.id, sourceLanguage: translationSourceLanguage, targetLanguage, engine: 'madlad400-ct2', device: translationDevice }, 'Translation job');
  }
  async function remove() {
    setBlurEffectHidden(false);
    await queue(`/videos/${project.id}/subtitle/remove`, { mode: removeMethod, area, srtAssetId: removeMethod === 'auto' ? srt.asset?.id : null }, 'Blur effect');
  }
  async function deleteBlurEffect() {
    if (!activeBlurEffect) return;
    setBlurEffectHidden(true);
    setSelection({ type: 'project' });
    try {
      await request(`/videos/${project.id}/subtitle/effect`, { method: 'DELETE' });
      setSubtitleBlurEffect(undefined);
      await refresh();
      setMessage('Subtitle blur effect was removed from FX.');
    } catch (error) {
      setBlurEffectHidden(false);
      setMessage(error instanceof Error ? error.message : 'Unable to remove subtitle blur effect');
    }
  }
  async function insert() {
    await saveSrt();
    await queue(`/videos/${project.id}/subtitle/replace`, { srtAssetId: srt.asset?.id, mode: insertMode, area, style }, 'Insert job');
  }
  async function undo(operation: 'hide' | 'insert') {
    try {
      const result = await request<{ videoId: number }>(`/videos/${project.id}/subtitle/undo`, { method: 'POST', body: JSON.stringify({ operation }) });
      await refresh(); onOpenVersion(result.videoId); setMessage(`Returned to ancestor version #${result.videoId}.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Undo failed'); }
  }
  function saveClipSetting(setting: 'videoScale' | 'videoVolumeDb' | 'videoSpeed' | 'voiceVolumeDb' | 'voiceSpeed', value: number) {
    studioApi.saveClipSettings(project.id, { [setting]: value }).catch((error) => {
      setMessage(error instanceof Error ? error.message : 'Unable to save clip setting');
    });
  }
  function clampClipValue(value: number, minimum: number, maximum: number) {
    return Math.max(minimum, Math.min(maximum, Number.isFinite(value) ? value : minimum));
  }
  function updateVideoScale(value: number) {
    const next = clampClipValue(value, .1, 5);
    setVideoScale(next); saveClipSetting('videoScale', next);
  }
  function updateVideoVolumeDb(value: number) {
    const next = clampClipValue(value, -60, 20);
    setVideoVolumeDb(next);
    setPreviewVolume(Math.max(0, Math.min(1, Math.pow(10, next / 20))));
    saveClipSetting('videoVolumeDb', next);
  }
  function updateVideoSpeed(value: number) {
    const next = clampClipValue(value, .1, 80);
    setVideoSpeed(next); setPlaybackRate(next); saveClipSetting('videoSpeed', next);
  }
  function updateVoiceVolumeDb(value: number) {
    const next = clampClipValue(value, -60, 20);
    setVoiceVolumeDb(next); saveClipSetting('voiceVolumeDb', next);
  }
  function updateVoiceSpeed(value: number) {
    const next = clampClipValue(value, .1, 80);
    setVoiceSpeed(next); saveClipSetting('voiceSpeed', next);
  }
  const ttsPayload = () => ({ voice: ttsVoice, srtAssetId: srt.asset?.id, engine: ttsEngine, language: ttsLanguage, rate: ttsEngine === 'vieneu' ? ttsRate : '1.0', timingMode: 'srt_slot', ...TTS_FIT });
  async function generateVoice(index?: number) {
    await saveSrt();
    const path = index ? `/videos/${project.id}/tts/segments/${index}` : `/videos/${project.id}/tts`;
    await queue(path, ttsPayload(), index ? `Voice line ${index}` : 'Voiceover job');
  }
  async function mergeVoice() {
    await saveSrt(); await queue(`/videos/${project.id}/tts/segments/merge`, ttsPayload(), 'Voice merge');
  }
  async function muxVoice() {
    await queue(`/videos/${project.id}/tts/mux-video`, undefined, 'Voice insert');
  }
  async function deleteVoiceover() {
    const voiceover = latestVoiceAsset;
    if (!voiceover) return;
    const voiceoverIds = project.assets.filter((asset) => asset.kind === 'tts').map((asset) => asset.id);
    // Hide A2 immediately. This also covers stale TTS records from earlier
    // regenerations while the backend removes their files and database rows.
    setRemovedVoiceAssetIds((current) => [...new Set([...current, ...voiceoverIds])]);
    if (previewSource.startsWith('tts:')) setPreviewSource('preview');
    setSelection({ type: 'project' });
    try {
      const result = await studioApi.deleteAsset(voiceover.id);
      setRemovedVoiceAssetIds((current) => [...new Set([...current, ...result.deletedAssetIds])]);
      await refresh();
      setMessage('Voiceover was removed from A2 and the preview.');
    } catch (error) {
      setRemovedVoiceAssetIds((current) => current.filter((id) => !voiceoverIds.includes(id)));
      setMessage(error instanceof Error ? error.message : 'Unable to remove voiceover');
    }
  }
  async function remapTimeline() {
    await queue(`/videos/${project.id}/tts/remap-timeline`, { srtAssetId: srt.asset?.id, ...TTS_FIT }, 'Timeline remap');
  }
  async function copyTimelineIssues() {
    if (!timelineIssues.length) {
      setMessage('No timeline issues to copy.');
      return;
    }
    const text = [
      'Rewrite these subtitle lines shorter while keeping the same line numbers and meaning:',
      '',
      ...timelineIssues.map((issue) => `#${issue.index} [${issue.startLabel || ''} --> ${issue.endLabel || ''}] ${issue.status}\n${issue.text}`),
    ].join('\n\n');
    try {
      await navigator.clipboard.writeText(text);
      setMessage(`Copied ${timelineIssues.length} timing issue(s).`);
    } catch {
      setMessage('Clipboard access is unavailable.');
    }
  }
  async function playVoice(segment?: VoiceSegment) {
    if (segment?.audioUrl) await new Audio(`${API_BASE}${segment.audioUrl}&preview=${Date.now()}`).play();
  }
  async function cancelJob(jobId: number) {
    try {
      await request(`/jobs/${jobId}/cancel`, { method: 'POST' });
      setMessage(`Stopping job #${jobId}…`);
      window.setTimeout(refresh, 250);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to cancel job');
    }
  }
  useEffect(() => {
    const isEditable = (target: EventTarget | null) => {
      const element = target as HTMLElement | null;
      return Boolean(element?.closest('input, textarea, select, [contenteditable="true"]'));
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditable(event.target)) return;
      const command = event.ctrlKey || event.metaKey;
        if (command && event.key.toLowerCase() === 'z') {
          event.preventDefault();
          if (event.shiftKey) redoEditorAction(); else undoEditorAction();
          return;
        }
        if (command && event.key.toLowerCase() === 'y') {
          event.preventDefault();
          redoEditorAction();
          return;
        }
        if (command && event.key.toLowerCase() === 'c' && selectedTimelineClipKeys().length) {
          event.preventDefault();
          void copyTimelineItems();
          return;
        }
        if (command && event.key.toLowerCase() === 'v') {
          event.preventDefault();
          void pasteTimelineItemsAt();
          return;
        }
        if (command && event.key.toLowerCase() === 'd' && selectedTimelineClipKeys().length) {
          event.preventDefault();
          void duplicateSelectedTimelineItems();
          return;
        }
        if (event.key.toLowerCase() === 's' && selectedTimelineClipKeys().length) {
          event.preventDefault();
          void splitSelectedTimelineItems();
          return;
        }
      if (event.key === 'Delete' || event.key === 'Backspace' || event.code === 'Delete') {
        const deletingBlurEffect = (selection.type === 'effect' && selection.operation === 'blur')
          || (selection.type === 'timeline-items' && selection.keys.includes('effect:blur'));
        if (deletingBlurEffect) {
          event.preventDefault();
          event.stopPropagation();
          void deleteBlurEffect();
          return;
        }
        const deletingVoiceover = selection.type === 'timeline-items' && selection.keys.includes('voice:merged');
        if (deletingVoiceover) {
          event.preventDefault();
          event.stopPropagation();
          void deleteVoiceover();
          return;
        }
        const timelineClipKeys = selection.type === 'timeline-items'
          ? selection.keys.filter((key) => timelineItems.some((item) => item.id === key))
          : [];
        if (timelineClipKeys.length) {
          event.preventDefault();
          event.stopPropagation();
          void deleteTimelineItems(timelineClipKeys);
          return;
        }
        const indexes = selectedSubtitleIndexes();
        if (!indexes.length) return;
        event.preventDefault();
        deleteSegments(indexes);
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [deleteBlurEffect, deleteSegments, deleteTimelineItems, deleteVoiceover, redoEditorAction, selectedSubtitleIndexes, selection, timelineItems, undoEditorAction]);

  return {
    project, projects, isEmptyWorkspace, jobs: videoJobs, activeJobs, srt, sourceSrt, translatedSrt, edits, setEdits: updateEdits, dirty, voiceSegments, voiceByIndex, timelineIssues, latestVoiceAsset, activeBlurEffect,
    selectedTextItems, selectedTimelineAudioItem, selectedTimelineImageItem,
    selection, setSelection, currentSegment, currentVoice, activeTool, openTool, assetTab, setAssetTab,
    bottomView, setBottomView, playhead, setPlayhead, duration, message, setMessage, editArea, setEditArea, timelineState, timelineScene, timelineItems, timelineDuration, activeTimelineItem, activeTimelineVideoId, activeTimelineLocalTime,
    previewSource, setPreviewSource, fitMode, setFitMode, previewVolume, setPreviewVolume,
    previewMuted, setPreviewMuted, playbackRate, setPlaybackRate, videoScale, videoVolumeDb, videoSpeed, voiceVolumeDb, voiceSpeed, updateVideoScale, updateVideoVolumeDb, updateVideoSpeed, updateVoiceVolumeDb, updateVoiceSpeed, timelineWidth, setTimelineWidth,
    audioMode, effectiveAudioMode, effectivePreviewAudioMode, setAudioMode, setTimelineVideoAudioMode, extractAudioFromTimelineClip, audioSeparationReady, activeAudioJob,
    area, setArea, saveSubtitleArea, style, setStyle, updateSubtitleStyle, applySubtitleStylePreset, resetSubtitleStylePreset, selectedTextStyle, updateTimelineTextStyle, applyTimelineTextStylePreset, resetTimelineTextStylePreset, distributeTimelineTextItems, srtAssets, originalSrtAssets, translatedSrtAssets, hasLoadedTranslation: Boolean(translatedSrt.asset?.id), canUndo: draftHistory.past.length > 0 || timelineHistory.past.length > 0, canRedo: draftHistory.future.length > 0 || timelineHistory.future.length > 0,
    subtitleSource, setSubtitleSource, hardsubMode, setHardsubMode, ocrAreaMode, setOcrAreaMode, ocrArea, setOcrArea, model, setModel, device, setDevice, language, setLanguage,
    targetLanguage, setTargetLanguage, translationSourceLanguage, setTranslationSourceLanguage,
    translationDevice, setTranslationDevice, removeMethod, setRemoveMethod, removeMode, setRemoveMode,
    autoSrtAssetId, setAutoSrtAssetId,
    insertMode, setInsertMode, ttsEngine, setTtsEngine, ttsLanguage, setTtsLanguage,
    ttsVoice, setTtsVoice, ttsRate, setTtsRate, voices,
    loadSrt, loadSegments, loadTimelineIssues, saveSrt, copySrt, pasteSrt, updateSegmentTime, deleteSegment, deleteSelectedSubtitles, moveSubtitleSegments, moveSelectedSubtitles, replaceWithTranslated, undoDraft: undoEditorAction, redoDraft: redoEditorAction, importSrt, generateSrt, translate, remove, deleteBlurEffect, insert, undo,
    generateVoice, mergeVoice, muxVoice, deleteVoiceover, remapTimeline, copyTimelineIssues, playVoice, cancelJob, refresh, openProjectVideo: onOpenVersion, addVideoToTimeline, addProjectAssetToTimeline, deleteTimelineItems, previewTimelineItems, commitTimelineItems, commitTimelineState,
    splitSelectedTimelineItems, duplicateSelectedTimelineItems, copyTimelineItems, pasteTimelineItemsAt, addTimelineTrack, removeTimelineTrack, toggleTimelineTrackMute, toggleTimelineTrackVisibility, setTimelineOption, toggleTimelineBookmark, captureCurrentFrame,
  };
}

export type EditorController = ReturnType<typeof useEditorController>;
