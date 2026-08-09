import { useEffect, useRef, useState } from 'react';
import { Camera, Expand, Maximize2, Pause, Play, RotateCcw, SkipBack, SkipForward, Volume2 } from 'lucide-react';
import { API_BASE } from '../../services/api';
import { formatClock } from '../../lib/studio';
import { textStyleToCss } from '../../utils/textStyleToCss';
import type { EditorController } from '../../hooks/useEditorController';
import type { SubtitleArea, TimelineItem } from '../../types/studio';
import type { TextStyle } from '../../types/textStyle';

type DragMode = 'draw' | 'move' | 'tl' | 'tr' | 'bl' | 'br';
type FrameFormat = 'original' | '16:9' | '9:16' | '1:1' | '4:5';
type ImageTransform = { scale: number; x: number; y: number };
type ImageDragState = { pointerId: number; clientX: number; clientY: number; width: number; height: number; itemId: string; transform: ImageTransform; previousItems: TimelineItem[]; latestItems: TimelineItem[]; moved: boolean };

const FRAME_RATIOS: Record<Exclude<FrameFormat, 'original'>, number> = {
  '16:9': 16 / 9,
  '9:16': 9 / 16,
  '1:1': 1,
  '4:5': 4 / 5,
};

export function VideoPreview({ editor }: { editor: EditorController }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const voiceRef = useRef<HTMLAudioElement>(null);
  const sourceAudioRef = useRef<HTMLAudioElement>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioChainsRef = useRef(new WeakMap<HTMLMediaElement, { gain: GainNode; limiter: DynamicsCompressorNode }>());
  const canvasRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const startRef = useRef<{ x: number; y: number; mode: DragMode; area: SubtitleArea } | null>(null);
  const editableAreaRef = useRef<SubtitleArea>(editor.area);
  const subtitleMoveRef = useRef<{ clientX: number; clientY: number; width: number; height: number; area: SubtitleArea; moved: boolean } | null>(null);
  const suppressSubtitleClickRef = useRef(false);
  const dragAreaRef = useRef<SubtitleArea | null>(null);
  const liveSubtitleRef = useRef<HTMLButtonElement>(null);
  const safeAreaRef = useRef<HTMLDivElement>(null);
  const horizontalGuideRef = useRef<HTMLDivElement>(null);
  const verticalGuideRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef(editor.playhead);
  const imageDragRef = useRef<ImageDragState | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [frameFormat, setFrameFormat] = useState<FrameFormat>('original');
  const [videoSize, setVideoSize] = useState({ width: 16, height: 9 });
  const [viewportSize, setViewportSize] = useState({ width: 800, height: 450 });
  const originalAspect = videoSize.width / videoSize.height;
  const frameAspect = frameFormat === 'original' ? originalAspect : FRAME_RATIOS[frameFormat];
  const availableWidth = Math.max(1, viewportSize.width - 40);
  const availableHeight = Math.max(1, viewportSize.height - 26);
  const frameWidth = Math.min(availableWidth, availableHeight * frameAspect);
  const frameHeight = frameWidth / frameAspect;
  const hasWorkspaceTimeline = Boolean(editor.project.workspaceId);
  const trackById = new Map(editor.timelineState.tracks.map((track) => [track.id, track]));
  const itemEnabled = (item?: { track?: string; hidden?: boolean; muted?: boolean }) => {
    if (!item || item.hidden) return false;
    const track = trackById.get(item.track || '');
    return !track?.hidden;
  };
  const itemAudible = (item?: { track?: string; hidden?: boolean; muted?: boolean }) => {
    if (!itemEnabled(item) || item?.muted) return false;
    const track = trackById.get(item.track || '');
    return !track?.muted;
  };
  const activeVideoId = editor.activeTimelineVideoId;
  const activeVoiceAudioClip = editor.timelineItems.find((item) =>
    item.kind === 'audio'
    && item.track !== 'A1'
    && itemAudible(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const activeImageItem = editor.activeTimelineItem?.kind === 'image' && itemEnabled(editor.activeTimelineItem) ? editor.activeTimelineItem : undefined;
  const activeImageTransform = imageTransformValue(activeImageItem);
  const activeImageUrl = activeImageItem?.projectAssetId
    ? `${API_BASE}/project-assets/${activeImageItem.projectAssetId}/download?preview=1`
    : activeImageItem?.sourceAssetId
      ? `${API_BASE}/assets/${activeImageItem.sourceAssetId}/download?preview=1`
      : '';
  const sourceAudioMuted = Boolean(editor.activeTimelineItem?.kind === 'video' && (editor.activeTimelineItem.sourceAudioMuted || !itemAudible(editor.activeTimelineItem)));
  const activeSourceAudioClip = editor.timelineItems.find((item) =>
    item.kind === 'audio'
    && item.track === 'A1'
    && itemAudible(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const sourceAudioUrl = activeSourceAudioClip?.projectAssetId
    ? `${API_BASE}/project-assets/${activeSourceAudioClip.projectAssetId}/download?preview=1`
    : activeSourceAudioClip?.sourceAssetId
      ? `${API_BASE}/assets/${activeSourceAudioClip.sourceAssetId}/download?preview=1`
      : '';
  const posterUrl = activeVideoId ? `${API_BASE}/videos/${activeVideoId}/thumbnail` : '';
  const previewTime = editor.activeTimelineItem ? editor.activeTimelineLocalTime : editor.playhead;
  const activeSubtitle = editor.srt.segments.find((segment) => previewTime >= segment.start && previewTime <= segment.end);
  const activeTextItems = editor.timelineItems.filter((item) =>
    item.kind === 'text'
    && itemEnabled(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const editingOcrArea = editor.activeTool === 'subtitles' && editor.subtitleSource === 'hardsub' && editor.ocrAreaMode === 'custom';
  const activeImageSelected = Boolean(activeImageItem && editor.selection.type === 'timeline-items' && editor.selection.keys.length === 1 && editor.selection.keys[0] === activeImageItem.id);
  const canDragActiveImage = Boolean(activeImageItem && activeImageSelected && !editingOcrArea && !editor.editArea);
  const editableArea = editingOcrArea ? editor.ocrArea : editor.area;
  const setEditableArea = editingOcrArea ? editor.setOcrArea : editor.setArea;
  editableAreaRef.current = editableArea;
  const mergedVoice = editor.latestVoiceAsset;
  const timelineVoiceUrl = activeVoiceAudioClip?.projectAssetId
    ? `${API_BASE}/project-assets/${activeVoiceAudioClip.projectAssetId}/download?preview=1`
    : activeVoiceAudioClip?.sourceAssetId
      ? `${API_BASE}/assets/${activeVoiceAudioClip.sourceAssetId}/download?preview=1`
      : '';
  const mergedVoiceMuted = Boolean(trackById.get('A2')?.muted || trackById.get('A2')?.hidden);
  const voiceUrl = timelineVoiceUrl || (editor.previewSource.startsWith('tts:') && mergedVoice && !mergedVoiceMuted ? `${API_BASE}/assets/${mergedVoice.id}/download?preview=1` : '');
  const sourceUrl = editor.previewSource.startsWith('asset:')
    ? `${API_BASE}/assets/${editor.previewSource.slice(6)}/download?preview=1`
    : editor.previewSource.startsWith('tts:')
      ? activeVideoId ? `${API_BASE}/videos/${activeVideoId}/preview?audioMode=${editor.effectivePreviewAudioMode}` : ''
      : activeVideoId ? `${API_BASE}/videos/${activeVideoId}/${editor.previewSource}?audioMode=${editor.effectivePreviewAudioMode}` : '';
  const timelineClockPlayback = Boolean(activeImageUrl || !sourceUrl);

  function applyGainValue(media: HTMLMediaElement | null, gainValue: number, muted = false) {
    if (!media) return;
    const finalGain = muted ? 0 : Math.max(0, gainValue);
    try {
      const context = audioContextRef.current || new AudioContext();
      audioContextRef.current = context;
      let chain = audioChainsRef.current.get(media);
      if (!chain) {
        const source = context.createMediaElementSource(media);
        const gain = context.createGain();
        const limiter = context.createDynamicsCompressor();
        // Gain can be as high as +20 dB. Keep the output below 0 dBFS so
        // loud source material does not turn into digital clipping/distortion.
        limiter.threshold.value = -1;
        limiter.knee.value = 0;
        limiter.ratio.value = 20;
        limiter.attack.value = 0.003;
        limiter.release.value = 0.12;
        source.connect(gain).connect(limiter).connect(context.destination);
        chain = { gain, limiter };
        audioChainsRef.current.set(media, chain);
      }
      chain.gain.gain.setTargetAtTime(finalGain, context.currentTime, 0.01);
      media.volume = 1;
      media.muted = false;
    } catch {
      media.volume = Math.max(0, Math.min(1, finalGain));
      media.muted = muted || finalGain <= 0;
    }
  }
  function applyDbGain(media: HTMLMediaElement | null, db: number, muted = false) {
    applyGainValue(media, db <= -60 ? 0 : Math.pow(10, db / 20), muted);
  }
  function timelineAudioGain(item: TimelineItem | undefined, timelineTime: number, fallbackDb: number) {
    const db = item?.volumeDb ?? fallbackDb;
    const baseGain = db <= -60 ? 0 : Math.pow(10, db / 20);
    if (!item) return baseGain;
    const localTime = timelineTime - item.start;
    const duration = Math.max(0.05, item.duration || 0.05);
    const fadeIn = audioFadeValue(item, 'audioFadeIn');
    const fadeOut = audioFadeValue(item, 'audioFadeOut');
    const fadeInFactor = fadeIn > 0 ? clampNumber(localTime / fadeIn, 0, 1) : 1;
    const remaining = duration - localTime;
    const fadeOutFactor = fadeOut > 0 ? clampNumber(remaining / fadeOut, 0, 1) : 1;
    return baseGain * Math.min(fadeInFactor, fadeOutFactor);
  }
  function setRate(media: HTMLMediaElement | null, rate: number) {
    if (!media) return;
    try { media.playbackRate = rate; } catch { media.playbackRate = 1; }
  }
  function syncVoiceAt(timelineTime: number, shouldPlay = false) {
    const voice = voiceRef.current;
    if (!voiceUrl || !voice) return;
    const audioTime = activeVoiceAudioClip
      ? Math.max(0, timelineTime - activeVoiceAudioClip.start + (activeVoiceAudioClip.sourceStart || 0))
      : timelineTime;
    if (Math.abs(voice.currentTime - audioTime) > .18) voice.currentTime = audioTime;
    setRate(voice, activeVoiceAudioClip ? 1 : editor.voiceSpeed);
    applyGainValue(voice, timelineAudioGain(activeVoiceAudioClip, timelineTime, editor.voiceVolumeDb), editor.previewMuted || Boolean(activeVoiceAudioClip && !itemAudible(activeVoiceAudioClip)));
    if (shouldPlay) voice.play().catch(() => undefined);
  }
  function syncSourceAudioAt(timelineTime: number, shouldPlay = false) {
    const audio = sourceAudioRef.current;
    if (!sourceAudioUrl || !activeSourceAudioClip || !audio) return;
    const audioTime = Math.max(0, timelineTime - activeSourceAudioClip.start + (activeSourceAudioClip.sourceStart || 0));
    if (Math.abs(audio.currentTime - audioTime) > .18) audio.currentTime = audioTime;
    setRate(audio, editor.videoSpeed);
    applyGainValue(audio, timelineAudioGain(activeSourceAudioClip, timelineTime, editor.videoVolumeDb), editor.previewMuted || !itemAudible(activeSourceAudioClip));
    if (shouldPlay) audio.play().catch(() => undefined);
  }
  function videoTimelineTime(video: HTMLVideoElement) {
    const localTime = video.currentTime / editor.videoSpeed;
    return editor.activeTimelineItem ? editor.activeTimelineItem.start + localTime - (editor.activeTimelineItem.sourceStart || 0) : localTime;
  }
  function syncVoice(video: HTMLVideoElement, shouldPlay = false) {
    syncVoiceAt(videoTimelineTime(video), shouldPlay);
  }
  function syncSourceAudio(video: HTMLVideoElement, shouldPlay = false) {
    syncSourceAudioAt(videoTimelineTime(video), shouldPlay);
  }
  function togglePlayback() {
    if (editor.playhead >= editor.duration - 0.05) {
      editor.setPlayhead(0);
      if (videoRef.current) videoRef.current.currentTime = 0;
    }
    if (timelineClockPlayback) {
      setPlaying((current) => {
        const next = !current;
        if (next) {
          audioContextRef.current?.resume().catch(() => undefined);
          syncVoiceAt(editor.playhead, true);
          syncSourceAudioAt(editor.playhead, true);
        } else {
          voiceRef.current?.pause();
          sourceAudioRef.current?.pause();
        }
        return next;
      });
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch((e) => {
        console.error('Video play failed:', e);
        setPlaying(false);
      });
    } else {
      video.pause();
    }
  }

  useEffect(() => {
    const video = videoRef.current;
    const mediaTime = previewTime * editor.videoSpeed;
    if (video && Math.abs(video.currentTime - mediaTime) > .4) video.currentTime = mediaTime;
    if (video) { syncVoice(video); syncSourceAudio(video); }
    else { syncVoiceAt(editor.playhead); syncSourceAudioAt(editor.playhead); }
  }, [previewTime, editor.playhead, editor.videoSpeed, sourceAudioUrl, voiceUrl, activeVoiceAudioClip, activeSourceAudioClip]);
  useEffect(() => {
    playheadRef.current = editor.playhead;
  }, [editor.playhead]);
  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.code === 'Space') {
        event.preventDefault();
        togglePlayback();
      } else if (event.code === 'ArrowLeft') {
        event.preventDefault(); editor.setPlayhead(Math.max(0, editor.playhead - (event.shiftKey ? 5 : 1)));
      } else if (event.code === 'ArrowRight') {
        event.preventDefault(); editor.setPlayhead(Math.min(editor.duration, editor.playhead + (event.shiftKey ? 5 : 1)));
      } else if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
        event.preventDefault(); editor.saveSrt();
      }
    }
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, [editor.duration, editor.playhead, editor.videoSpeed, timelineClockPlayback]);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    applyDbGain(video, editor.videoVolumeDb, editor.previewMuted || sourceAudioMuted);
    setRate(video, editor.videoSpeed);
    syncVoice(video, !video.paused);
    syncSourceAudio(video, !video.paused);
  }, [editor.videoVolumeDb, editor.videoSpeed, editor.voiceVolumeDb, editor.voiceSpeed, editor.previewMuted, voiceUrl, sourceAudioUrl, sourceAudioMuted, activeVoiceAudioClip, activeSourceAudioClip]);
  useEffect(() => () => { voiceRef.current?.pause(); }, [voiceUrl]);
  useEffect(() => () => { sourceAudioRef.current?.pause(); }, [sourceAudioUrl]);
  useEffect(() => {
    if (!activeImageUrl) return;
    const image = imageRef.current;
    if (image?.complete && image.naturalWidth) {
      setVideoSize({ width: image.naturalWidth || 16, height: image.naturalHeight || 9 });
      setLoading(false);
      setError('');
    }
  }, [activeImageUrl]);
  useEffect(() => {
    if (!playing || !timelineClockPlayback) return;
    let frame = 0;
    let last = performance.now();
    let lastUiUpdate = 0;
    const tick = (now: number) => {
      const delta = Math.max(0, (now - last) / 1000);
      last = now;
      const voice = voiceRef.current;
      const sourceAudio = sourceAudioRef.current;
      const audioDrivenTime = voiceUrl && voice && !voice.paused
        ? activeVoiceAudioClip
          ? voice.currentTime - (activeVoiceAudioClip.sourceStart || 0) + activeVoiceAudioClip.start
          : voice.currentTime
        : sourceAudioUrl && sourceAudio && !sourceAudio.paused && activeSourceAudioClip
          ? sourceAudio.currentTime - (activeSourceAudioClip.sourceStart || 0) + activeSourceAudioClip.start
          : null;
      const next = Math.min(editor.duration, Math.max(0, audioDrivenTime ?? playheadRef.current + delta));
      playheadRef.current = next;
      if (now - lastUiUpdate > 33 || next >= editor.duration) {
        lastUiUpdate = now;
        editor.setPlayhead(next);
      }
      syncVoiceAt(next);
      syncSourceAudioAt(next);
      if (next >= editor.duration) {
        setPlaying(false);
        voiceRef.current?.pause();
        sourceAudioRef.current?.pause();
        return;
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, timelineClockPlayback, editor.duration, voiceUrl, sourceAudioUrl, activeVoiceAudioClip, activeSourceAudioClip]);
  useEffect(() => {
    if (subtitleMoveRef.current) return;
    if (liveSubtitleRef.current) liveSubtitleRef.current.style.transform = subtitleAnchorTransform;
    if (safeAreaRef.current) safeAreaRef.current.style.transform = '';
  }, [editor.area]);
  useEffect(() => {
    setError('');
    if (activeImageUrl) {
      const image = imageRef.current;
      setLoading(!(image?.complete && image.naturalWidth));
      return;
    }
    if (!sourceUrl) {
      setLoading(false);
      return;
    }
    setLoading(true);
  }, [sourceUrl, activeImageUrl]);
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !playing) return;
    video.play().catch(() => undefined);
  }, [sourceUrl, playing]);
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const updateSize = () => {
      const bounds = viewport.getBoundingClientRect();
      setViewportSize({ width: bounds.width, height: bounds.height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  function beginImageDrag(event: React.PointerEvent<HTMLImageElement>) {
    if (!activeImageItem || !canDragActiveImage) return;
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) return;
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    imageDragRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      width: bounds.width,
      height: bounds.height,
      itemId: activeImageItem.id,
      transform: activeImageTransform,
      previousItems: cloneTimelineItemsForPreview(editor.timelineItems),
      latestItems: editor.timelineItems,
      moved: false,
    };
  }
  function moveImageDrag(event: React.PointerEvent<HTMLImageElement>) {
    const drag = imageDragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    event.stopPropagation();
    event.preventDefault();
    const deltaX = (event.clientX - drag.clientX) / Math.max(1, drag.width);
    const deltaY = (event.clientY - drag.clientY) / Math.max(1, drag.height);
    let x = clampNumber(drag.transform.x + deltaX, 0, 1);
    let y = clampNumber(drag.transform.y + deltaY, 0, 1);
    const centeredX = Math.abs(x - 0.5) < 0.018;
    const centeredY = Math.abs(y - 0.5) < 0.018;
    if (centeredX) x = 0.5;
    if (centeredY) y = 0.5;
    drag.moved = drag.moved || Math.abs(event.clientX - drag.clientX) > 2 || Math.abs(event.clientY - drag.clientY) > 2;
    const nextTransform = { ...drag.transform, x, y };
    const nextItems = editor.timelineItems.map((item) => item.id === drag.itemId
      ? { ...item, params: { ...(item.params || {}), imageTransform: nextTransform } }
      : item);
    drag.latestItems = nextItems;
    editor.previewTimelineItems(nextItems);
    if (horizontalGuideRef.current) horizontalGuideRef.current.style.display = centeredY ? 'block' : 'none';
    if (verticalGuideRef.current) verticalGuideRef.current.style.display = centeredX ? 'block' : 'none';
  }
  function finishImageDrag(event: React.PointerEvent<HTMLImageElement>) {
    const drag = imageDragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    event.stopPropagation();
    event.preventDefault();
    imageDragRef.current = null;
    if (horizontalGuideRef.current) horizontalGuideRef.current.style.display = 'none';
    if (verticalGuideRef.current) verticalGuideRef.current.style.display = 'none';
    if (drag.moved) void editor.commitTimelineItems(drag.latestItems, 'Updated image position.', drag.previousItems);
  }

  function point(event: React.PointerEvent) {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const visualScale = Math.max(0.01, editor.videoScale || 1);
    const visualX = (event.clientX - rect.left) / rect.width;
    const visualY = (event.clientY - rect.top) / rect.height;
    return {
      x: Math.max(0, Math.min(1, .5 + (visualX - .5) / visualScale)),
      y: Math.max(0, Math.min(1, .5 + (visualY - .5) / visualScale)),
    };
  }
  function begin(event: React.PointerEvent) {
    if (!editor.editArea) return;
    const value = point(event);
    if (!value) return;
    const area = { ...editableArea };
    const corners: Array<[Exclude<DragMode, 'draw' | 'move'>, number, number]> = [
      ['tl', area.xmin, area.ymin], ['tr', area.xmax, area.ymin], ['bl', area.xmin, area.ymax], ['br', area.xmax, area.ymax],
    ];
    const corner = corners.find(([, x, y]) => Math.abs(value.x - x) < .035 && Math.abs(value.y - y) < .035);
    const inside = value.x >= area.xmin && value.x <= area.xmax && value.y >= area.ymin && value.y <= area.ymax;
    const mode: DragMode = corner?.[0] || (inside ? 'move' : 'draw');
    startRef.current = { ...value, mode, area };
    event.currentTarget.setPointerCapture(event.pointerId);
    if (mode === 'draw') {
      const nextArea = { xmin: value.x, xmax: value.x + .001, ymin: value.y, ymax: value.y + .001 };
      editableAreaRef.current = nextArea;
      setEditableArea(nextArea);
    }
  }
  function beginSubtitleMove(event: React.PointerEvent<HTMLButtonElement>) {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds || !activeSubtitle) return;
    event.stopPropagation();
    event.preventDefault();
    videoRef.current?.pause();
    subtitleMoveRef.current = { clientX: event.clientX, clientY: event.clientY, width: bounds.width, height: bounds.height, area: { ...editor.area }, moved: false };
    dragAreaRef.current = { ...editor.area };
    window.addEventListener('pointermove', moveSubtitleNative, { passive: true });
    window.addEventListener('pointerup', finishSubtitleMoveNative);
    window.addEventListener('pointercancel', finishSubtitleMoveNative);
  }
  function moveSubtitleNative(event: PointerEvent) {
    const start = subtitleMoveRef.current;
    if (!start) return;
    const visualScale = Math.max(0.01, editor.videoScale || 1);
    const events = typeof event.getCoalescedEvents === 'function' ? event.getCoalescedEvents() : [];
    const latest = events.at(-1) || event;
    const deltaX = (latest.clientX - start.clientX) / Math.max(1, start.width * visualScale);
    const deltaY = (latest.clientY - start.clientY) / Math.max(1, start.height * visualScale);
    const width = start.area.xmax - start.area.xmin;
    const height = start.area.ymax - start.area.ymin;
    let xmin = start.area.xmin + deltaX;
    let ymin = start.area.ymin + deltaY;
    let xmax = xmin + width;
    let ymax = ymin + height;
    const centeredX = Math.abs((xmin + xmax) / 2 - .5) < .025;
    const centeredY = Math.abs((ymin + ymax) / 2 - .5) < .025;
    if (centeredX) {
      xmin = .5 - width / 2;
      xmax = .5 + width / 2;
    }
    if (centeredY) {
      ymin = .5 - height / 2;
      ymax = .5 + height / 2;
    }
    start.moved = start.moved || Math.abs(latest.clientX - start.clientX) > 2 || Math.abs(latest.clientY - start.clientY) > 2;
    const nextArea = { ...start.area, xmin, xmax, ymin, ymax };
    dragAreaRef.current = nextArea;
    const translateX = (xmin - start.area.xmin) * start.width;
    const translateY = (ymin - start.area.ymin) * start.height;
    if (liveSubtitleRef.current) liveSubtitleRef.current.style.transform = `translate3d(${translateX}px, ${translateY}px, 0) ${subtitleAnchorTransform}`;
    if (safeAreaRef.current) safeAreaRef.current.style.transform = `translate3d(${translateX}px, ${translateY}px, 0)`;
    if (horizontalGuideRef.current) horizontalGuideRef.current.style.display = centeredY ? 'block' : 'none';
    if (verticalGuideRef.current) verticalGuideRef.current.style.display = centeredX ? 'block' : 'none';
  }
  function finishSubtitleMoveNative() {
    const moved = subtitleMoveRef.current?.moved;
    if (!subtitleMoveRef.current) return;
    subtitleMoveRef.current = null;
    window.removeEventListener('pointermove', moveSubtitleNative);
    window.removeEventListener('pointerup', finishSubtitleMoveNative);
    window.removeEventListener('pointercancel', finishSubtitleMoveNative);
    suppressSubtitleClickRef.current = Boolean(moved);
    if (dragAreaRef.current) void editor.saveSubtitleArea(dragAreaRef.current, false);
    dragAreaRef.current = null;
    if (horizontalGuideRef.current) horizontalGuideRef.current.style.display = 'none';
    if (verticalGuideRef.current) verticalGuideRef.current.style.display = 'none';
  }
  function move(event: React.PointerEvent) {
    const start = startRef.current;
    const value = point(event);
    if (!start || !value) return;
    if (start.mode === 'draw') {
      const nextArea = { xmin: Math.min(start.x, value.x), xmax: Math.max(start.x, value.x), ymin: Math.min(start.y, value.y), ymax: Math.max(start.y, value.y) };
      editableAreaRef.current = nextArea;
      setEditableArea(nextArea);
      return;
    }
    if (start.mode === 'move') {
      const width = start.area.xmax - start.area.xmin;
      const height = start.area.ymax - start.area.ymin;
      const xmin = Math.max(0, Math.min(1 - width, start.area.xmin + value.x - start.x));
      const ymin = Math.max(0, Math.min(1 - height, start.area.ymin + value.y - start.y));
      const nextArea = { xmin, xmax: xmin + width, ymin, ymax: ymin + height };
      editableAreaRef.current = nextArea;
      setEditableArea(nextArea);
      return;
    }
    const next = { ...start.area };
    if (start.mode.includes('l')) next.xmin = Math.min(value.x, next.xmax - .01);
    if (start.mode.includes('r')) next.xmax = Math.max(value.x, next.xmin + .01);
    if (start.mode.startsWith('t')) next.ymin = Math.min(value.y, next.ymax - .01);
    if (start.mode.startsWith('b')) next.ymax = Math.max(value.y, next.ymin + .01);
    editableAreaRef.current = next;
    setEditableArea(next);
  }
  const box = { left: `${editableArea.xmin * 100}%`, top: `${editableArea.ymin * 100}%`, width: `${(editableArea.xmax - editableArea.xmin) * 100}%`, height: `${(editableArea.ymax - editableArea.ymin) * 100}%` };
  const blurEffectBox = editor.activeBlurEffect?.area ? {
    left: `${editor.activeBlurEffect.area.xmin * 100}%`,
    top: `${editor.activeBlurEffect.area.ymin * 100}%`,
    width: `${(editor.activeBlurEffect.area.xmax - editor.activeBlurEffect.area.xmin) * 100}%`,
    height: `${(editor.activeBlurEffect.area.ymax - editor.activeBlurEffect.area.ymin) * 100}%`,
  } : undefined;
  const subtitleVerticalAlign = editor.style.verticalAlign || 'bottom';
  const subtitleTop = subtitleVerticalAlign === 'top'
    ? editor.area.ymin
    : subtitleVerticalAlign === 'middle'
      ? (editor.area.ymin + editor.area.ymax) / 2
      : editor.area.ymax;
  const subtitleAnchorTransform = subtitleVerticalAlign === 'top' ? 'translateY(0)' : subtitleVerticalAlign === 'middle' ? 'translateY(-50%)' : 'translateY(-100%)';
  const subtitlePosition = { left: `${editor.area.xmin * 100}%`, top: `${subtitleTop * 100}%`, width: `${(editor.area.xmax - editor.area.xmin) * 100}%`, transform: subtitleAnchorTransform };
  const sourcePixelHeight = videoSize.height > 120 ? videoSize.height : 1080;
  const previewTextScale = Math.max(0.2, Math.min(4, frameHeight / sourcePixelHeight));

  return <section className="preview-stage">
    <div className="preview-toolbar">
      <span>Program monitor</span>
      <div className="preview-toolbar-actions">
        <button className="preview-action-button" disabled={!activeVideoId} title="Capture current frame as image" onClick={editor.captureCurrentFrame}><Camera size={14} /> Capture frame</button>
        <label className="preview-format">
          <span>Frame</span>
          <select
            aria-label="Video frame format"
            value={frameFormat}
            onChange={(event) => {
              setFrameFormat(event.target.value as FrameFormat);
              editor.setFitMode('contain');
            }}
          >
            <option value="original">Original · {videoSize.width}×{videoSize.height}</option>
            <option value="16:9">Landscape · 16:9</option>
            <option value="9:16">Portrait · 9:16</option>
            <option value="1:1">Square · 1:1</option>
            <option value="4:5">Social · 4:5</option>
          </select>
        </label>
      </div>
    </div>
    <div className="preview-viewport" ref={viewportRef}>
      <div className="video-canvas" style={{ width: frameWidth, height: frameHeight, aspectRatio: frameAspect }} ref={canvasRef} onPointerDown={begin} onPointerMove={move} onPointerUp={() => { const wasEditingArea = Boolean(startRef.current && editor.editArea && !editingOcrArea); startRef.current = null; if (wasEditingArea) void editor.saveSubtitleArea(editableAreaRef.current); }} onPointerCancel={() => { startRef.current = null; }}>
        <div className={`preview-media-layer ${activeImageUrl ? 'image-mode' : 'video-mode'}`} style={activeImageUrl ? undefined : { transform: `scale(${editor.videoScale})` }}>
          {activeImageUrl ? <img
            ref={imageRef}
            className={`preview-image ${canDragActiveImage ? 'draggable' : ''} ${imageDragRef.current ? 'dragging' : ''}`}
            style={{
              objectFit: editor.fitMode,
              left: `${activeImageTransform.x * 100}%`,
              top: `${activeImageTransform.y * 100}%`,
              transform: `translate(-50%, -50%) scale(${activeImageTransform.scale})`,
            }}
            src={activeImageUrl}
            alt={editor.activeTimelineItem?.name || 'Timeline image'}
            onPointerDown={beginImageDrag}
            onPointerMove={moveImageDrag}
            onPointerUp={finishImageDrag}
            onPointerCancel={finishImageDrag}
            onLoad={(event) => {
              const image = event.currentTarget;
              setVideoSize({ width: image.naturalWidth || 16, height: image.naturalHeight || 9 });
              setLoading(false); setError('');
            }}
            onError={() => { setLoading(false); setError('This image cannot be loaded in the preview.'); }}
          /> : sourceUrl ? <video
            key={`${activeVideoId || editor.project.id}-${editor.previewSource}-${editor.effectivePreviewAudioMode}-${sourceAudioMuted ? 'muted-source' : 'source'}`}
            ref={videoRef}
            style={{ objectFit: editor.fitMode }}
            src={sourceUrl}
            poster={posterUrl}
            preload="auto"
            onLoadedMetadata={(event) => {
              const video = event.currentTarget;
              video.currentTime = Math.min(previewTime * editor.videoSpeed, Number.isFinite(video.duration) ? video.duration : editor.duration * editor.videoSpeed);
              if (video.videoWidth && video.videoHeight) setVideoSize({ width: video.videoWidth, height: video.videoHeight });
              applyDbGain(video, editor.videoVolumeDb, editor.previewMuted || sourceAudioMuted); setRate(video, editor.videoSpeed); syncVoice(video); syncSourceAudio(video);
            }}
            onLoadedData={() => { setLoading(false); setError(''); }}
            onTimeUpdate={(event) => {
              const localTime = event.currentTarget.currentTime / editor.videoSpeed;
              const timelineTime = editor.activeTimelineItem ? editor.activeTimelineItem.start + localTime - (editor.activeTimelineItem.sourceStart || 0) : localTime;
              syncSourceAudio(event.currentTarget);
              if (editor.activeTimelineItem && localTime >= editor.activeTimelineItem.duration) {
                editor.setPlayhead(Math.min(editor.duration, editor.activeTimelineItem.start + editor.activeTimelineItem.duration + 0.001));
                return;
              }
              editor.setPlayhead(Math.max(0, Math.min(editor.duration, timelineTime)));
            }}
            onPlay={(event) => { setPlaying(true); audioContextRef.current?.resume().catch(() => undefined); syncVoice(event.currentTarget, true); syncSourceAudio(event.currentTarget, true); }}
            onPause={() => { setPlaying(false); voiceRef.current?.pause(); sourceAudioRef.current?.pause(); }}
            onSeeking={(event) => { syncVoice(event.currentTarget); syncSourceAudio(event.currentTarget); }}
            onWaiting={() => setLoading(true)}
            onCanPlay={() => { setLoading(false); setError(''); }}
            onError={() => {
              if (editor.previewSource === 'preview') editor.setPreviewSource('media');
              else { setLoading(false); setError('This media cannot be played in the browser. Try the proxy or reveal the source file.'); }
            }}
          /> : <div className="preview-black-canvas" aria-label="No visual media at the playhead" />}
          {loading && posterUrl && !activeImageUrl && !error && <img className="preview-poster" src={posterUrl} alt="" />}
          {blurEffectBox && <div className="subtitle-blur-effect" style={blurEffectBox} aria-hidden="true" />}
          {(editor.activeTool === 'insert' || editor.editArea || editingOcrArea) && <div ref={safeAreaRef} className={`subtitle-safe-area ${editor.editArea ? 'editing' : ''} ${editingOcrArea ? 'ocr-area' : ''} ${editor.activeTool === 'insert' ? `mode-${editor.insertMode}` : ''}`} style={box}>
            <i className="handle tl" /><i className="handle tr" /><i className="handle bl" /><i className="handle br" />
          </div>}
          <div ref={horizontalGuideRef} className="subtitle-center-guide horizontal" aria-hidden="true" />
          <div ref={verticalGuideRef} className="subtitle-center-guide vertical" aria-hidden="true" />
          {activeSubtitle && <button ref={liveSubtitleRef} className={`live-subtitle effect-${editor.style.staticEffect || 'none'}`} data-text={editor.edits[activeSubtitle.index] ?? activeSubtitle.text} style={{
            ...subtitlePosition,
            ...textStyleToCss(editor.style, { previewScale: previewTextScale }),
          }} title="Drag to reposition subtitles" onPointerDown={beginSubtitleMove} onClick={(event) => { if (suppressSubtitleClickRef.current) { suppressSubtitleClickRef.current = false; return; } event.stopPropagation(); editor.setSelection({ type: 'subtitle', index: activeSubtitle.index }); }}>{editor.edits[activeSubtitle.index] ?? activeSubtitle.text}</button>}
          {activeTextItems.map((item, index) => {
            const itemStyle = (typeof item.params?.textStyle === 'object' && item.params.textStyle ? item.params.textStyle : {}) as TextStyle;
            const text = String(item.params?.text || item.name || 'Text');
            const position = textPositionValue(item, index);
            return <button
              key={item.id}
              className={`live-text-item effect-${itemStyle.staticEffect || 'none'}`}
              data-text={text}
              style={{
                left: `${position.x * 100}%`,
                top: `${position.y * 100}%`,
                ...textStyleToCss(itemStyle, { previewScale: previewTextScale }),
              }}
              onClick={(event) => { event.stopPropagation(); editor.setSelection({ type: 'timeline-items', keys: [item.id], track: item.track }); }}
            >{text}</button>;
          })}
        </div>
        {voiceUrl && <audio ref={voiceRef} src={voiceUrl} preload="auto" onCanPlay={() => { const video = videoRef.current; if (video) syncVoice(video, !video.paused); else syncVoiceAt(editor.playhead, playing); }} />}
        {sourceAudioUrl && <audio ref={sourceAudioRef} src={sourceAudioUrl} preload="auto" onCanPlay={() => { const video = videoRef.current; if (video) syncSourceAudio(video, !video.paused); else syncSourceAudioAt(editor.playhead, playing); }} />}
        {loading && (activeImageUrl || sourceUrl) && !posterUrl && !error && <div className="preview-loading"><i /> Preparing browser preview...</div>}
        {error && <div className="preview-error">{error}<button onClick={() => editor.setPreviewSource('preview')}>Retry proxy</button></div>}
        {editor.editArea && <button className="reset-area" onClick={(event) => {
          event.stopPropagation();
          const nextArea = { xmin: .04, xmax: .96, ymin: .60, ymax: .98 };
          editableAreaRef.current = nextArea;
          if (editingOcrArea) setEditableArea(nextArea);
          else void editor.saveSubtitleArea(nextArea);
        }}><RotateCcw size={13} /> Reset area</button>}
      </div>
    </div>
    <div className="playback-controls">
      <div><button onClick={() => editor.setPlayhead(Math.max(0, editor.playhead - 5))}><SkipBack size={17} /></button><button className="play-button" onClick={togglePlayback}>{playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}</button><button onClick={() => editor.setPlayhead(Math.min(editor.duration, editor.playhead + 5))}><SkipForward size={17} /></button><span>{formatClock(editor.playhead)} <i>/</i> {formatClock(editor.duration)}</span></div>
      <div><button className={editor.previewMuted ? 'active' : ''} title={editor.previewMuted ? 'Unmute' : 'Mute'} onClick={() => editor.setPreviewMuted(!editor.previewMuted)}><Volume2 size={16} /></button><input aria-label="Volume in decibels" type="range" min="-60" max="20" step=".1" value={editor.videoVolumeDb} onChange={(event) => editor.updateVideoVolumeDb(Number(event.target.value))} /><button title="Fullscreen" onClick={() => viewportRef.current?.requestFullscreen()}><Expand size={16} /></button></div>
    </div>
  </section>;
}

function FilmPlaceholder() {
  return <div className="empty-preview-icon"><Play size={28} fill="currentColor" /></div>;
}

function clampNumber(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, Number.isFinite(value) ? value : minimum));
}

function audioFadeValue(item: TimelineItem, key: 'audioFadeIn' | 'audioFadeOut') {
  const value = Number(item.params?.[key] ?? 0);
  return clampNumber(value, 0, Math.max(0, item.duration || 0));
}

function imageTransformValue(item?: TimelineItem): ImageTransform {
  const raw = item?.params?.imageTransform;
  const transform = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  return {
    scale: clampNumber(Number(transform.scale ?? 1), 0.1, 5),
    x: clampNumber(Number(transform.x ?? 0.5), 0, 1),
    y: clampNumber(Number(transform.y ?? 0.5), 0, 1),
  };
}

function textPositionValue(item: TimelineItem, index: number) {
  const raw = item.params?.textPosition;
  const position = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  return {
    x: clampNumber(Number(position.x ?? 0.5 + index * 0.02), 0, 1),
    y: clampNumber(Number(position.y ?? 0.45 + index * 0.08), 0, 1),
  };
}

function cloneTimelineItemsForPreview(items: TimelineItem[]) {
  return items.map((item) => ({ ...item, params: item.params ? { ...item.params } : undefined }));
}
