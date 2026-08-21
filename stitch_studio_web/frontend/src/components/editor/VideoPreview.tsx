import { useEffect, useRef, useState } from 'react';
import { Camera, Expand, Maximize2, Pause, Play, RotateCcw, SkipBack, SkipForward, Volume2 } from 'lucide-react';
import { API_BASE } from '../../services/api';
import { formatClock } from '../../lib/studio';
import { textStyleToCss } from '../../utils/textStyleToCss';
import { SliderNumericField } from './NumericField';
import type { EditorController } from '../../hooks/useEditorController';
import type { SubtitleArea, TimelineItem } from '../../types/studio';
import type { TextStyle } from '../../types/textStyle';
import { evaluateImageAnimation, composeImageTransform, type BaseImageTransform } from '../../utils/image-animation/evaluateImageAnimation';
import { getDefaultAnimationDelta } from '../../utils/image-animation/presets';
import { activeSparkleEffects, effectIdForItem } from '../../config/sparkleEffects';
import { SparkleEffectCanvas } from './SparkleEffectCanvas';

type DragMode = 'draw' | 'move' | 'tl' | 'tr' | 'bl' | 'br';
type FrameFormat = 'original' | '16:9' | '9:16' | '1:1' | '4:5';
type ImageTransform = BaseImageTransform;
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
  const visualVideoRefs = useRef(new Map<string, HTMLVideoElement>());
  const voiceRef = useRef<HTMLAudioElement>(null);
  const sourceAudioRef = useRef<HTMLAudioElement>(null);
  const extraAudioRefs = useRef(new Map<string, HTMLAudioElement>());
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
  // A browser video element pauses when its own source reaches its end. In a
  // timeline that can simply mean "move to the next clip", not "stop edit".
  const continuingTimelineRef = useRef(false);
  const resumeNextVisualRef = useRef(false);
  const [imageDrag, setImageDrag] = useState<ImageDragState | null>(null);
  const imageDragRef = useRef<ImageDragState | null>(null);
  useEffect(() => { imageDragRef.current = imageDrag; }, [imageDrag]);
  const [playing, setPlaying] = useState(false);
  const [forceTimelineClock, setForceTimelineClock] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [frameFormat, setFrameFormat] = useState<FrameFormat>('original');
  const [videoSize, setVideoSize] = useState({ width: 16, height: 9 });
  const [viewportSize, setViewportSize] = useState({ width: 800, height: 450 });
  const originalAspect = videoSize.width / videoSize.height;
  const frameAspect = frameFormat === 'original' ? originalAspect : FRAME_RATIOS[frameFormat];
  const availableWidth = Math.max(1, viewportSize.width - 32);
  const availableHeight = Math.max(1, viewportSize.height - 24);
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
  const activeVisualItems = editor.timelineItems
    .filter((item) => (item.kind === 'video' || item.kind === 'image') && itemEnabled(item) && editor.playhead >= item.start && editor.playhead < item.start + Math.max(0.05, item.duration))
    // The first visual row is the foreground row in the timeline UI. Paint
    // lower rows first so V1, then V2, etc. appear over rows beneath them.
    .sort((a, b) => (editor.timelineState.tracks.findIndex((track) => track.id === b.track) - editor.timelineState.tracks.findIndex((track) => track.id === a.track)));
  const activeVideoIndex = activeVisualItems.map((item) => item.kind).lastIndexOf('video');
  const activeVideoItem = activeVideoIndex >= 0 ? activeVisualItems[activeVideoIndex] : undefined;
  const activeVideoItems = activeVisualItems.filter((item) => item.kind === 'video');
  const preloadVideoItems = editor.timelineItems.filter((item) =>
    item.kind === 'video'
    && itemEnabled(item)
    && item.id !== activeVideoItem?.id
    && item.start > editor.playhead
    && item.start - editor.playhead <= 1.5
  );
  // Paint every active visual item in UI layer order. This deliberately
  // includes images and video together, so an image on V1 can overlay video
  // on V2/V3 exactly as it does in the timeline.
  const activeImageItems = activeVisualItems.filter((item) => item.kind === 'image');
  const activeVideoId = activeVideoItem?.sourceVideoId ?? (!hasWorkspaceTimeline ? editor.activeTimelineVideoId : undefined);
  const activeVoiceAudioClip = editor.timelineItems.find((item) =>
    item.kind === 'audio'
    && item.track !== 'A1'
    && itemAudible(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const activeImageItem = activeImageItems.at(-1);
  const activeImageBaseTransform = imageTransformValue(activeImageItem);
  const activeImageLocalTime = activeImageItem ? editor.playhead - activeImageItem.start : 0;
  const activeImageAnimationDelta = activeImageItem ? evaluateImageAnimation(activeImageItem, activeImageLocalTime) : getDefaultAnimationDelta();
  const activeImageTransform = composeImageTransform(activeImageBaseTransform, activeImageAnimationDelta);
  const activeImageUrl = activeImageItem?.projectAssetId
    ? `${API_BASE}/project-assets/${activeImageItem.projectAssetId}/download?preview=1`
    : activeImageItem?.sourceAssetId
      ? `${API_BASE}/assets/${activeImageItem.sourceAssetId}/download?preview=1`
      : '';
  const sourceAudioMuted = Boolean(activeVideoItem && (activeVideoItem.sourceAudioMuted || !itemAudible(activeVideoItem)));
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
  const activeExtraAudioClips = editor.timelineItems.filter((item) =>
    item.kind === 'audio'
    && item.id !== activeVoiceAudioClip?.id
    && item.id !== activeSourceAudioClip?.id
    && itemAudible(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const activeExtraAudioClipKey = activeExtraAudioClips.map((item) => item.id).join('|');
  const audioClipUrl = (item: TimelineItem) => item.projectAssetId
    ? `${API_BASE}/project-assets/${item.projectAssetId}/download?preview=1`
    : item.sourceAssetId ? `${API_BASE}/assets/${item.sourceAssetId}/download?preview=1` : '';
  const posterUrl = activeVideoId ? `${API_BASE}/videos/${activeVideoId}/thumbnail` : '';
  const activePlaybackItem = activeVideoItem || activeImageItem || editor.activeTimelineItem;
  const previewTime = activePlaybackItem ? Math.max(0, editor.playhead - activePlaybackItem.start + (activePlaybackItem.sourceStart || 0)) : editor.playhead;
  // SRT on a workspace timeline is authored against the timeline, not against
  // the source time of whichever video clip happens to be active. Using
  // previewTime here restarted captions at 0 whenever the next clip began.
  const subtitleTime = hasWorkspaceTimeline ? editor.playhead : previewTime;
  const activeSubtitle = editor.srt.segments.find((segment) => subtitleTime >= segment.start && subtitleTime <= segment.end);
  const activeTextItems = editor.timelineItems.filter((item) =>
    item.kind === 'text'
    && itemEnabled(item)
    && editor.playhead >= item.start
    && editor.playhead < item.start + Math.max(0.05, item.duration)
  );
  const activeEffects = activeSparkleEffects(editor.timelineItems, editor.playhead);
  const previewEffects = editor.previewedEffect && !activeEffects.some((item) => effectIdForItem(item) === effectIdForItem(editor.previewedEffect))
    ? [...activeEffects, editor.previewedEffect]
    : activeEffects;
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
  // Uploaded and stock clips are ordinary ProjectAssets and deliberately do
  // not need a hidden library Video record. Preview them from that same asset.
  const activeProjectVideoUrl = activeVideoItem?.projectAssetId && !activeVideoItem.sourceVideoId
    ? `${API_BASE}/project-assets/${activeVideoItem.projectAssetId}/download?preview=1`
    : '';
  const sourceUrl = editor.previewSource.startsWith('asset:')
    ? `${API_BASE}/assets/${editor.previewSource.slice(6)}/download?preview=1`
    : editor.previewSource.startsWith('tts:')
      ? activeVideoId ? `${API_BASE}/videos/${activeVideoId}/preview?audioMode=${editor.effectivePreviewAudioMode}` : ''
      : activeProjectVideoUrl || (activeVideoId ? `${API_BASE}/videos/${activeVideoId}/${editor.previewSource}?audioMode=${editor.effectivePreviewAudioMode}` : '');
  const videoUrlForItem = (item: TimelineItem) => {
    if (item.id === activeVideoItem?.id) return sourceUrl;
    if (item.projectAssetId && !item.sourceVideoId) return `${API_BASE}/project-assets/${item.projectAssetId}/download?preview=1`;
    if (item.sourceVideoId) return `${API_BASE}/videos/${item.sourceVideoId}/${editor.previewSource}?audioMode=${editor.effectivePreviewAudioMode}`;
    return item.sourceAssetId ? `${API_BASE}/assets/${item.sourceAssetId}/download?preview=1` : '';
  };
  const timelineClockPlayback = Boolean(forceTimelineClock || !sourceUrl);

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
  function syncExtraAudioAt(timelineTime: number, shouldPlay = false) {
    activeExtraAudioClips.forEach((item) => {
      const audio = extraAudioRefs.current.get(item.id);
      if (!audio) return;
      const audioTime = Math.max(0, timelineTime - item.start + (item.sourceStart || 0));
      if (Math.abs(audio.currentTime - audioTime) > .18) audio.currentTime = audioTime;
      setRate(audio, item.speed || 1);
      const fallbackDb = item.track === 'A1' ? editor.videoVolumeDb : editor.voiceVolumeDb;
      applyGainValue(audio, timelineAudioGain(item, timelineTime, fallbackDb), editor.previewMuted || !itemAudible(item));
      if (shouldPlay) audio.play().catch(() => undefined);
    });
  }
  function pauseExtraAudio() {
    extraAudioRefs.current.forEach((audio) => audio.pause());
  }
  function syncAdditionalVisualVideos(timelineTime: number, shouldPlay = false) {
    activeVideoItems.forEach((item) => {
      if (item.id === activeVideoItem?.id) return;
      const video = visualVideoRefs.current.get(item.id);
      if (!video) return;
      const rate = item.speed || editor.videoSpeed;
      const localTime = Math.max(0, (timelineTime - item.start) * rate + (item.sourceStart || 0));
      // Once an overlay is already playing, let its media clock run smoothly.
      // Constantly snapping it to the top video's sparse timeupdate events was
      // visible as stutter on added stock clips.
      const seekThreshold = shouldPlay && !video.paused ? .5 : .04;
      if (Math.abs(video.currentTime - localTime) > seekThreshold) video.currentTime = localTime;
      setRate(video, rate);
      // The normal audio tracks are mixed separately. Keep lower visual media
      // muted so a video layer does not unexpectedly duplicate its sound.
      applyDbGain(video, 0, true);
      if (shouldPlay) video.play().catch(() => undefined);
    });
  }
  function pauseAdditionalVisualVideos() {
    visualVideoRefs.current.forEach((video) => video.pause());
  }
  function videoTimelineTime(video: HTMLVideoElement) {
    const localTime = video.currentTime / editor.videoSpeed;
    return activePlaybackItem ? activePlaybackItem.start + localTime - (activePlaybackItem.sourceStart || 0) : localTime;
  }
  function syncVoice(video: HTMLVideoElement, shouldPlay = false) {
    syncVoiceAt(videoTimelineTime(video), shouldPlay);
    syncExtraAudioAt(videoTimelineTime(video), shouldPlay);
    syncAdditionalVisualVideos(videoTimelineTime(video), shouldPlay);
  }
  function syncSourceAudio(video: HTMLVideoElement, shouldPlay = false) {
    syncSourceAudioAt(videoTimelineTime(video), shouldPlay);
  }
  function continueAfterVisualClip(item: TimelineItem) {
    const nextTime = Math.min(editor.duration, item.start + item.duration);
    if (nextTime >= editor.duration - 0.001) return false;
    // Switch to the timeline clock before the outgoing <video> emits pause.
    // It keeps the playhead moving through the next clip (or any intentional
    // gap) and lets the newly active layer seek to the same timeline time.
    continuingTimelineRef.current = true;
    resumeNextVisualRef.current = true;
    setForceTimelineClock(true);
    setPlaying(true);
    playheadRef.current = nextTime;
    editor.setPlayhead(nextTime);
    audioContextRef.current?.resume().catch(() => undefined);
    syncVoiceAt(nextTime, true);
    syncSourceAudioAt(nextTime, true);
    syncExtraAudioAt(nextTime, true);
    syncAdditionalVisualVideos(nextTime, true);
    return true;
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
          syncExtraAudioAt(editor.playhead, true);
          syncAdditionalVisualVideos(editor.playhead, true);
        } else {
          voiceRef.current?.pause();
          sourceAudioRef.current?.pause();
          pauseExtraAudio();
          pauseAdditionalVisualVideos();
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
        if (hasWorkspaceTimeline) {
          setForceTimelineClock(true);
          setPlaying(true);
          audioContextRef.current?.resume().catch(() => undefined);
          syncVoiceAt(editor.playhead, true);
          syncSourceAudioAt(editor.playhead, true);
          syncExtraAudioAt(editor.playhead, true);
          syncAdditionalVisualVideos(editor.playhead, true);
        } else {
          setPlaying(false);
        }
      });
    } else {
      video.pause();
    }
  }

  useEffect(() => {
    const video = videoRef.current;
    const mediaTime = previewTime * editor.videoSpeed;
    // While a browser source is being swapped at a cut, keep the paused
    // element close to the timeline clock. Once it resumes normally, allow a
    // small drift instead of repeatedly seeking it (which caused visible
    // frame jumps at every edit point).
    const seekThreshold = video?.paused ? .04 : .5;
    if (video && Math.abs(video.currentTime - mediaTime) > seekThreshold) video.currentTime = mediaTime;
    if (video) { syncVoice(video); syncSourceAudio(video); }
    else { syncVoiceAt(editor.playhead); syncSourceAudioAt(editor.playhead); syncExtraAudioAt(editor.playhead); }
    syncAdditionalVisualVideos(editor.playhead, playing && !timelineClockPlayback);
  }, [previewTime, editor.playhead, editor.videoSpeed, sourceAudioUrl, voiceUrl, activeVoiceAudioClip, activeSourceAudioClip, activeExtraAudioClipKey, activeVideoItems, activeVideoItem, playing, timelineClockPlayback]);
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
  useEffect(() => () => { pauseExtraAudio(); }, [activeExtraAudioClipKey]);
  useEffect(() => {
    if (!activeImageUrl || sourceUrl) return;
    const image = imageRef.current;
    if (image?.complete && image.naturalWidth) {
      setVideoSize({ width: image.naturalWidth || 16, height: image.naturalHeight || 9 });
      setLoading(false);
      setError('');
    }
  }, [activeImageUrl, sourceUrl]);
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
        syncExtraAudioAt(next);
        syncAdditionalVisualVideos(next, true);
        if (next >= editor.duration) {
        setPlaying(false);
        voiceRef.current?.pause();
        sourceAudioRef.current?.pause();
          pauseExtraAudio();
          pauseAdditionalVisualVideos();
        return;
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, timelineClockPlayback, editor.duration, voiceUrl, sourceAudioUrl, activeVoiceAudioClip, activeSourceAudioClip, activeExtraAudioClipKey, activeVideoItems, activeVideoItem]);
  useEffect(() => {
    if (subtitleMoveRef.current) return;
    if (liveSubtitleRef.current) liveSubtitleRef.current.style.transform = subtitleAnchorTransform;
    if (safeAreaRef.current) safeAreaRef.current.style.transform = '';
  }, [editor.area]);
  useEffect(() => {
    setError('');
    setForceTimelineClock(false);
    if (!sourceUrl && activeImageUrl) {
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
    const viewport = viewportRef.current?.getBoundingClientRect();
    if (!viewport) return;
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setImageDrag({
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      width: viewport.width,
      height: viewport.height,
      itemId: activeImageItem.id,
      transform: activeImageBaseTransform,
      previousItems: editor.timelineItems.map((clip) => ({ ...clip, params: clip.params ? { ...clip.params } : undefined })),
      latestItems: editor.timelineItems.map((clip) => ({ ...clip, params: clip.params ? { ...clip.params } : undefined })),
      moved: false,
    });
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
        <div className="preview-media-layer video-mode" style={{ transform: `scale(${editor.videoScale})` }}>
          {activeVideoItems.length ? activeVideoItems.map((item) => {
            const isTopVideo = item.id === activeVideoItem?.id;
            const itemUrl = videoUrlForItem(item);
            if (!itemUrl) return null;
            const layerIndex = activeVisualItems.findIndex((candidate) => candidate.id === item.id);
            const itemRate = item.speed || editor.videoSpeed;
            const itemPreviewTime = Math.max(0, (editor.playhead - item.start) * itemRate + (item.sourceStart || 0));
            return <video
              key={`${item.id}-${itemUrl}-${isTopVideo ? 'top' : 'layer'}`}
              ref={(node) => {
                if (isTopVideo) (videoRef as React.MutableRefObject<HTMLVideoElement | null>).current = node;
                if (node) visualVideoRefs.current.set(item.id, node);
                else visualVideoRefs.current.delete(item.id);
              }}
              className="preview-video-layer"
              style={{ objectFit: editor.fitMode, zIndex: layerIndex + 1 }}
              src={itemUrl}
              poster={isTopVideo ? posterUrl : undefined}
              preload="auto"
              muted={!isTopVideo}
              onLoadedMetadata={(event) => {
                const video = event.currentTarget;
                video.currentTime = Math.min(itemPreviewTime, Number.isFinite(video.duration) ? video.duration : itemPreviewTime);
                setRate(video, itemRate);
                if (isTopVideo) {
                  if (video.videoWidth && video.videoHeight) setVideoSize({ width: video.videoWidth, height: video.videoHeight });
                  applyDbGain(video, editor.videoVolumeDb, editor.previewMuted || sourceAudioMuted);
                  syncVoice(video); syncSourceAudio(video);
                  if (resumeNextVisualRef.current) {
                    resumeNextVisualRef.current = false;
                    video.play().catch(() => undefined);
                  }
                } else {
                  applyDbGain(video, 0, true);
                  if (playing && !timelineClockPlayback) video.play().catch(() => undefined);
                }
              }}
              onLoadedData={() => { if (isTopVideo) { setLoading(false); setError(''); } }}
              onTimeUpdate={(event) => {
                if (!isTopVideo) return;
                const localTime = event.currentTarget.currentTime / itemRate;
                const timelineTime = item.start + localTime - (item.sourceStart || 0);
                syncSourceAudio(event.currentTarget);
                syncAdditionalVisualVideos(timelineTime, true);
                if (localTime >= item.duration) {
                  if (!continueAfterVisualClip(item)) editor.setPlayhead(Math.min(editor.duration, item.start + item.duration));
                  return;
                }
                editor.setPlayhead(Math.max(0, Math.min(editor.duration, timelineTime)));
              }}
              onEnded={() => {
                if (!isTopVideo) return;
                if (!continueAfterVisualClip(item)) {
                  setPlaying(false);
                  voiceRef.current?.pause(); sourceAudioRef.current?.pause(); pauseExtraAudio(); pauseAdditionalVisualVideos();
                }
              }}
              onPlay={(event) => {
                if (!isTopVideo) return;
                // The currently playing HTML video is the smoothest clock. The
                // RAF timeline clock is only a bridge while changing sources
                // or when the browser cannot decode a source.
                setForceTimelineClock(false);
                setPlaying(true); audioContextRef.current?.resume().catch(() => undefined); syncVoice(event.currentTarget, true); syncSourceAudio(event.currentTarget, true);
              }}
              onPause={() => {
                if (!isTopVideo) return;
                if (continuingTimelineRef.current) {
                  continuingTimelineRef.current = false;
                  return;
                }
                setPlaying(false); voiceRef.current?.pause(); sourceAudioRef.current?.pause(); pauseExtraAudio(); pauseAdditionalVisualVideos();
              }}
              onSeeking={(event) => { if (isTopVideo) { syncVoice(event.currentTarget); syncSourceAudio(event.currentTarget); } }}
              onWaiting={() => { if (isTopVideo) setLoading(true); }}
              onCanPlay={(event) => {
                if (!isTopVideo) return;
                setLoading(false); setError('');
                if (resumeNextVisualRef.current) {
                  resumeNextVisualRef.current = false;
                  event.currentTarget.play().catch(() => undefined);
                }
              }}
              onError={() => {
                if (!isTopVideo) return;
                if (editor.previewSource === 'preview') editor.setPreviewSource('media');
                else {
                  setForceTimelineClock(hasWorkspaceTimeline);
                  setLoading(false);
                  setError(hasWorkspaceTimeline ? '' : 'This media cannot be played in the browser. Try the proxy or reveal the source file.');
                }
              }}
            />;
          }) : <div className="preview-black-canvas" aria-label="No visual media at the playhead" />}
          {preloadVideoItems.map((item) => {
            const itemUrl = videoUrlForItem(item);
            return itemUrl ? <video key={`preload-${item.id}`} className="preview-video-preload" src={itemUrl} preload="auto" muted aria-hidden="true" /> : null;
          })}
          {activeImageItems.map((item, index) => {
            const isTopImage = index === activeImageItems.length - 1;
            const baseTransform = imageTransformValue(item);
            const animation = evaluateImageAnimation(item, editor.playhead - item.start);
            const transform = isTopImage ? activeImageTransform : composeImageTransform(baseTransform, animation);
            const imageUrl = item.projectAssetId
              ? `${API_BASE}/project-assets/${item.projectAssetId}/download?preview=1`
              : item.sourceAssetId ? `${API_BASE}/assets/${item.sourceAssetId}/download?preview=1` : '';
            if (!imageUrl) return null;
            return <img
              key={item.id}
              ref={isTopImage ? imageRef : undefined}
              className={`preview-image ${isTopImage && canDragActiveImage ? 'draggable' : ''} ${isTopImage && imageDragRef.current ? 'dragging' : ''}`}
              style={{
                zIndex: activeVisualItems.findIndex((candidate) => candidate.id === item.id) + 1,
                objectFit: editor.fitMode,
                left: `${transform.x * 100}%`,
                top: `${transform.y * 100}%`,
                transform: `translate(-50%, -50%) scale(${transform.scale}) rotate(${transform.rotation}deg)`,
                opacity: transform.opacity,
                filter: transform.blur > 0 ? `blur(${transform.blur}px)` : undefined,
              }}
              src={imageUrl}
              alt={item.name || 'Timeline image'}
              onPointerDown={isTopImage ? beginImageDrag : undefined}
              onPointerMove={isTopImage ? moveImageDrag : undefined}
              onPointerUp={isTopImage ? finishImageDrag : undefined}
              onPointerCancel={isTopImage ? finishImageDrag : undefined}
              onLoad={(event) => {
                if (!sourceUrl && isTopImage) setVideoSize({ width: event.currentTarget.naturalWidth || 16, height: event.currentTarget.naturalHeight || 9 });
                setLoading(false); setError('');
              }}
              onError={() => {
                setLoading(false);
                if (!sourceUrl && isTopImage) setError('This image cannot be loaded in the preview.');
              }}
            />;
          })}
          <SparkleEffectCanvas effects={previewEffects} />
          {loading && posterUrl && !activeImageItems.length && !error && <img className="preview-poster" src={posterUrl} alt="" />}
          {blurEffectBox && <div className="subtitle-blur-effect" style={blurEffectBox} aria-hidden="true" />}
          {(editor.editArea || editingOcrArea) && <div ref={safeAreaRef} className={`subtitle-safe-area ${editor.editArea ? 'editing' : ''} ${editingOcrArea ? 'ocr-area' : ''}`} style={box}>
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
        {activeExtraAudioClips.map((item) => {
          const url = audioClipUrl(item);
          if (!url) return null;
          return <audio
            key={item.id}
            ref={(node) => {
              if (node) extraAudioRefs.current.set(item.id, node);
              else extraAudioRefs.current.delete(item.id);
            }}
            src={url}
            preload="auto"
            onCanPlay={() => syncExtraAudioAt(editor.playhead, playing)}
          />;
        })}
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
      <div><button className={editor.previewMuted ? 'active' : ''} title={editor.previewMuted ? 'Unmute' : 'Mute'} onClick={() => editor.setPreviewMuted(!editor.previewMuted)}><Volume2 size={16} /></button><SliderNumericField className="playback-volume-control" value={editor.videoVolumeDb} min={-60} max={20} step={0.1} unit="dB" onChange={editor.updateVideoVolumeDb} ariaLabel="Volume in decibels" /><button title="Fullscreen" onClick={() => viewportRef.current?.requestFullscreen()}><Expand size={16} /></button></div>
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
