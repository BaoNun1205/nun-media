import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Captions, Check, ChevronRight, Clipboard, Copy, Eye, EyeOff, FileAudio2, Film, Flag, Layers, Magnet, Minus, Music2, Plus, Redo2, Scissors, Trash2, Undo2, Volume2, VolumeX } from 'lucide-react';
import { formatClock, percent } from '../../lib/studio';
import { SliderNumericField } from './NumericField';
import type { EditorController } from '../../hooks/useEditorController';
import type { InspectorSelection, TimelineItem, TimelineTrack, TimelineTrackKind } from '../../types/studio';

type Marquee = { left: number; top: number; width: number; height: number };
type ContextMenuPoint = { x: number; y: number; videoId: number; timelineItemId?: string };
type ClipDragMode = 'move' | 'trim-start' | 'trim-end';
type ClipDragState = {
  pointerId: number;
  key: string;
  visualKeys: string[];
  clientX: number;
  durationAtStart: number;
  baseItems: TimelineItem[];
  nextItems: TimelineItem[];
  visualElements: HTMLElement[];
  snapCandidates: number[];
  canvasWidth: number;
  moved: boolean;
  mode: ClipDragMode;
};

export function Timeline({ editor }: { editor: EditorController }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const snapGuideRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ clientX: number; clientY: number; x: number; y: number; moved: boolean } | null>(null);
  const clipMoveRef = useRef<ClipDragState | null>(null);
  const scrubRef = useRef(false);
  const suppressClickRef = useRef(false);
  const [timelineViewportWidth, setTimelineViewportWidth] = useState(1200);
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuPoint | null>(null);
  const [dragDisplayDuration, setDragDisplayDuration] = useState<number | null>(null);
  const minimumWidth = Math.max(260, Math.round(Math.max(0, timelineViewportWidth - 145) / 3));
  const maximumWidth = Math.max(5000, minimumWidth);
  const selectedKeys = new Set(editor.selection.type === 'timeline-items' ? editor.selection.keys : []);
  const originalSegments = editor.srt.segments;
  const mergedVoiceAsset = editor.latestVoiceAsset;
  const stateTracks = editor.timelineState.tracks;
  const legacySingleVideo = !editor.project.workspaceId && !editor.isEmptyWorkspace;
  const hasBlurEffect = Boolean(editor.activeBlurEffect);
  const legacyEffectOperation = editor.project.processingState?.subtitleInserted ? 'insert' : editor.project.processingState?.subtitleHidden ? 'hide' : null;
  const visibleEffectOperation = hasBlurEffect ? 'blur' : legacyEffectOperation;
  const naturalDisplayDuration = Math.max(editor.duration, 30);
  const displayDuration = dragDisplayDuration ?? naturalDisplayDuration;
  const trackKeys: Record<string, string[]> = Object.fromEntries(stateTracks.map((track) => {
    const keys = editor.timelineItems.filter((item) => item.track === track.id).map((item) => item.id);
    if (track.id === 'V1' && legacySingleVideo) keys.unshift(`video:${editor.project.id}`);
    if (track.id === 'S1') keys.unshift(...originalSegments.map((segment) => `subtitle:${segment.index}`));
    if (track.id === 'A2' && mergedVoiceAsset) keys.unshift('voice:merged');
    return [track.id, keys];
  }));
  if (visibleEffectOperation) trackKeys.FX = [`effect:${visibleEffectOperation}`];

  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;
    const updateWidth = () => setTimelineViewportWidth(viewport.getBoundingClientRect().width);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [editor.bottomView]);
  useEffect(() => {
    if (editor.timelineWidth < minimumWidth) editor.setTimelineWidth(minimumWidth);
  }, [editor.timelineWidth, minimumWidth]);
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const closeOnKey = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    window.addEventListener('pointerdown', close);
    window.addEventListener('blur', close);
    window.addEventListener('keydown', closeOnKey);
    return () => {
      window.removeEventListener('pointerdown', close);
      window.removeEventListener('blur', close);
      window.removeEventListener('keydown', closeOnKey);
    };
  }, [contextMenu]);

  if (editor.bottomView === 'script') return <ScriptEditor editor={editor} />;

  const marks = Array.from({ length: 9 }, (_, index) => (displayDuration / 8) * index);
  const isTrackSelected = (track: string) => editor.selection.type === 'timeline-items' && editor.selection.track === track;
  const isItemSelected = (key: string) => {
    if (selectedKeys.has(key)) return true;
    if (key.startsWith('video:')) return editor.selection.type === 'video';
    if (key.startsWith('effect:')) return editor.selection.type === 'effect';
    if (key.startsWith('subtitle:') || key.startsWith('subtitle-translated:')) {
      return editor.selection.type === 'subtitle' && editor.selection.index === Number(key.split(':')[1]);
    }
    if (key === 'voice:merged') return selectedKeys.has(key);
    if (key.startsWith('voice:')) return editor.selection.type === 'voice' && editor.selection.index === Number(key.split(':')[1]);
    return false;
  };
  const currentSelectionKey = () => {
    if (editor.selection.type === 'video') return `video:${editor.selection.id}`;
    if (editor.selection.type === 'subtitle') return `subtitle:${editor.selection.index}`;
    if (editor.selection.type === 'voice') return `voice:${editor.selection.index}`;
    if (editor.selection.type === 'effect') return `effect:${editor.selection.operation}`;
    return '';
  };
  const selectTrack = (track: string) => editor.setSelection({ type: 'timeline-items', keys: trackKeys[track] || [], track });
  const trackAtClientY = (clientY: number) => {
    const rows = Array.from(canvasRef.current?.querySelectorAll<HTMLElement>('[data-track-row]') || []);
    return rows.find((row) => {
      const bounds = row.getBoundingClientRect();
      return clientY >= bounds.top && clientY <= bounds.bottom;
    })?.dataset.trackRow;
  };
  const timelineTimeFromClientX = (clientX: number) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) return 0;
    return Math.max(0, ((clientX - bounds.left) / Math.max(1, bounds.width)) * displayDuration);
  };
  const seekFromClientX = (clientX: number) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) return;
    editor.setPlayhead(Math.max(0, Math.min(editor.duration, ((clientX - bounds.left) / bounds.width) * displayDuration)));
  };
  const beginScrub = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    scrubRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    seekFromClientX(event.clientX);
  };
  const moveScrub = (event: React.PointerEvent<HTMLDivElement>) => {
    if (scrubRef.current) seekFromClientX(event.clientX);
  };
  const finishScrub = () => { scrubRef.current = false; };
  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData('application/x-stitch-asset');
    if (!raw) return;
    const placementOptions = { trackId: trackAtClientY(event.clientY), start: timelineTimeFromClientX(event.clientX) };
    try {
      const data = JSON.parse(raw) as { type?: string; id?: number; sourceVideoId?: number; kind?: string };
      if (data.type === 'projectAsset' && data.id) {
        const asset = (editor.project.projectAssets || []).find((item) => item.id === Number(data.id));
        if (asset) void editor.addProjectAssetToTimeline(asset, placementOptions);
      } else if (data.kind === 'video' && data.id) void editor.addVideoToTimeline(Number(data.id), placementOptions);
    } catch {
      editor.setMessage('Unable to add this asset to the timeline.');
    }
  };
  const deleteSelectedTimelineItem = (event: React.KeyboardEvent) => {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    if (editor.selection.type === 'timeline-items' && editor.selection.keys.includes('effect:blur')) {
      event.preventDefault();
      event.stopPropagation();
      void editor.deleteBlurEffect();
      return;
    }
    if (editor.selection.type !== 'timeline-items') return;
    const clipKeys = editor.selection.keys.filter((key) => editor.timelineItems.some((item) => item.id === key));
    if (clipKeys.length) {
      event.preventDefault();
      event.stopPropagation();
      void editor.deleteTimelineItems(clipKeys);
      return;
    }
    if (!editor.selection.keys.includes('voice:merged')) return;
    event.preventDefault();
    event.stopPropagation();
    void editor.deleteVoiceover();
  };
  const deleteVoiceoverFromClip = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    event.preventDefault();
    event.stopPropagation();
    void editor.deleteVoiceover();
  };
  const deleteBlurEffectFromClip = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    event.preventDefault();
    event.stopPropagation();
    void editor.deleteBlurEffect();
  };
  const selectItem = (event: React.MouseEvent | React.PointerEvent, key: string, singleSelection: InspectorSelection) => {
    event.stopPropagation();
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      const next = new Set(editor.selection.type === 'timeline-items' ? editor.selection.keys : []);
      const current = currentSelectionKey();
      if (current) next.add(current);
      if (next.has(key)) next.delete(key); else next.add(key);
      editor.setSelection(next.size ? { type: 'timeline-items', keys: [...next] } : { type: 'project' });
      return;
    }
    editor.setSelection(singleSelection);
  };
  const openVideoContextMenu = (event: React.MouseEvent, videoId: number, timelineItemId?: string) => {
    event.preventDefault();
    event.stopPropagation();
    editor.setSelection(timelineItemId ? { type: 'timeline-items', keys: [timelineItemId], track: 'V1' } : { type: 'video', id: videoId });
    setContextMenu({ x: event.clientX, y: event.clientY, videoId, timelineItemId });
  };
  const audioModeForVideo = (videoId: number) => {
    const source = editor.projects.find((item) => item.id === videoId) || (editor.project.id === videoId ? editor.project : undefined);
    return source?.audioMode || 'original';
  };
  const timelineClipById = (key?: string) => editor.timelineItems.find((item) => item.id === key);
  const clipHasExtractedAudio = (item?: TimelineItem) => Boolean(item && (
    item.sourceAudioMuted
    || editor.timelineItems.some((clip) =>
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
    )
  ));
  const timelineElementsForKeys = (keys: string[]) => {
    const keySet = new Set(keys);
    return Array.from(canvasRef.current?.querySelectorAll<HTMLElement>('[data-timeline-item]') || [])
      .filter((element) => keySet.has(element.dataset.timelineItem || ''));
  };
  const setClipDragVisual = (elements: HTMLElement[], dx = 0, active = true) => {
    elements.forEach((element) => {
      element.style.transform = active ? `translate3d(${dx}px, 0, 0)` : '';
      element.style.willChange = active ? 'transform' : '';
      element.classList.toggle('timeline-clip-dragging', active);
    });
  };
  const clearClipDragVisual = (elements: HTMLElement[]) => setClipDragVisual(elements, 0, false);
  const setClipShapeVisual = (elements: HTMLElement[], items: TimelineItem[], duration: number, active = true) => {
    const itemById = new Map(items.map((item) => [item.id, item]));
    elements.forEach((element) => {
      const item = itemById.get(element.dataset.timelineItem || '');
      element.style.willChange = active ? 'left, width' : '';
      element.classList.toggle('timeline-clip-dragging', active);
      if (!active || !item) {
        element.style.left = '';
        element.style.width = '';
        return;
      }
      element.style.left = percent(item.start, duration);
      element.style.width = `${Math.max(2, (item.duration / Math.max(duration, .01)) * 100)}%`;
    });
  };
  const clearClipShapeVisual = (elements: HTMLElement[]) => {
    elements.forEach((element) => {
      element.style.left = '';
      element.style.width = '';
      element.style.willChange = '';
      element.classList.remove('timeline-clip-dragging');
    });
  };
  const keepClipShapeVisualUntilNextPaint = (drag: ClipDragState, items: TimelineItem[]) => {
    window.requestAnimationFrame(() => {
      if (clipMoveRef.current !== drag || drag.mode === 'move') return;
      setClipShapeVisual(drag.visualElements, items, drag.durationAtStart, true);
    });
  };
  const linkedClipKeysFor = (item: TimelineItem, items: TimelineItem[]) => {
    const keys = new Set([item.id]);
    if (item.kind === 'video') {
      items
        .filter((clip) => clip.kind === 'audio' && clip.track === 'A1' && clip.linkedVideoItemId === item.id)
        .forEach((clip) => keys.add(clip.id));
    }
    return keys;
  };
  const timelineKeysForDrag = (event: React.PointerEvent, itemId: string, items: TimelineItem[]) => {
    if (!(event.ctrlKey || event.metaKey || event.shiftKey)) return [itemId];
    if (editor.selection.type !== 'timeline-items') return [itemId];
    const keys = new Set(editor.selection.keys.filter((key) => items.some((clip) => clip.id === key)));
    keys.add(itemId);
    return [...keys];
  };
  const sourceDurationForClip = (item: TimelineItem) => {
    if (item.sourceDuration) return item.sourceDuration;
    if (item.kind === 'image') return 0;
    if (item.sourceVideoId) {
      const source = editor.projects.find((project) => project.id === item.sourceVideoId);
      return Math.max(0, (source?.durationMs || 0) / 1000);
    }
    return 0;
  };
  const snapCandidates = (items: TimelineItem[], movingKeys: Set<string>) => {
    const values = [0];
    items.forEach((item) => {
      if (movingKeys.has(item.id)) return;
      if (item.kind === 'srt') return;
      values.push(item.start, item.start + item.duration);
    });
    return [...new Set(values.map((value) => Number(value.toFixed(3))))].filter((value) => value >= 0);
  };
  const nearestSnap = (
    anchors: Array<{ time: number; apply: (time: number) => number }>,
    candidates: number[],
    thresholdSeconds: number,
    disabled: boolean,
  ) => {
    if (disabled) return null;
    let best: { delta: number; candidate: number; distance: number } | null = null;
    anchors.forEach((anchor) => {
      candidates.forEach((candidate) => {
        const delta = anchor.apply(candidate);
        const distance = Math.abs(candidate - anchor.time);
        if (distance > thresholdSeconds) return;
        if (!best || distance < best.distance) best = { delta, candidate, distance };
      });
    });
    return best;
  };
  const showSnapGuide = (time?: number) => {
    const guide = snapGuideRef.current;
    if (!guide) return;
    if (typeof time !== 'number') {
      guide.hidden = true;
      return;
    }
    guide.hidden = false;
    guide.style.left = percent(time, displayDuration);
    const label = guide.querySelector('span');
    if (label) label.textContent = formatClock(time);
  };
  const beginClipMove = (event: React.PointerEvent<HTMLButtonElement>, item: TimelineItem, selection: InspectorSelection) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    selectItem(event, item.id, selection);
    const baseItems = editor.timelineItems.map((clip) => ({ ...clip }));
    const selectedTimelineKeys = timelineKeysForDrag(event, item.id, baseItems);
    const visualKeys = new Set(selectedTimelineKeys);
    selectedTimelineKeys.forEach((key) => {
      const selectedItem = baseItems.find((clip) => clip.id === key);
      if (selectedItem) linkedClipKeysFor(selectedItem, baseItems).forEach((clipKey) => visualKeys.add(clipKey));
    });
    const visualKeyList = [...visualKeys];
    const movingKeys = new Set(visualKeyList);
    const canvasWidth = canvasRef.current?.getBoundingClientRect().width || 1;
    setDragDisplayDuration(displayDuration);
    clipMoveRef.current = {
      pointerId: event.pointerId,
      key: item.id,
      visualKeys: visualKeyList,
      clientX: event.clientX,
      durationAtStart: displayDuration,
      baseItems,
      nextItems: baseItems.map((clip) => ({ ...clip })),
      visualElements: timelineElementsForKeys(visualKeyList),
      snapCandidates: snapCandidates(baseItems, movingKeys),
      canvasWidth,
      moved: false,
      mode: 'move',
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const beginClipTrim = (event: React.PointerEvent<HTMLElement>, item: TimelineItem, side: 'start' | 'end') => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    editor.setSelection({ type: 'timeline-items', keys: [item.id], track: item.track || 'V1' });
    const baseItems = editor.timelineItems.map((clip) => ({ ...clip }));
    const visualKeys = linkedClipKeysFor(item, baseItems);
    const visualKeyList = [...visualKeys];
    const canvasWidth = canvasRef.current?.getBoundingClientRect().width || 1;
    setDragDisplayDuration(displayDuration);
    clipMoveRef.current = {
      pointerId: event.pointerId,
      key: item.id,
      visualKeys: visualKeyList,
      clientX: event.clientX,
      durationAtStart: displayDuration,
      baseItems,
      nextItems: baseItems.map((clip) => ({ ...clip })),
      visualElements: timelineElementsForKeys(visualKeyList),
      snapCandidates: snapCandidates(baseItems, visualKeys),
      canvasWidth,
      moved: false,
      mode: side === 'start' ? 'trim-start' : 'trim-end',
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveClip = (event: React.PointerEvent<HTMLElement>) => {
    const drag = clipMoveRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const canvasWidth = Math.max(1, drag.canvasWidth);
    const deltaSeconds = ((event.clientX - drag.clientX) / canvasWidth) * drag.durationAtStart;
    drag.moved = drag.moved || Math.abs(event.clientX - drag.clientX) > 2;
    const target = drag.baseItems.find((item) => item.id === drag.key);
    if (!target) return;
    const movingKeys = new Set(drag.visualKeys);
    const candidates = drag.snapCandidates;
    const snapThresholdPixels = target.kind === 'image' && drag.mode !== 'move' ? 3 : 8;
    const thresholdSeconds = (snapThresholdPixels / canvasWidth) * drag.durationAtStart;
    const minDuration = 0.25;
    let linkedDelta = deltaSeconds;
    let snappedTime: number | undefined;
    let next = drag.baseItems.map((item) => ({ ...item }));
    if (drag.mode === 'move') {
      const movingItems = drag.baseItems.filter((item) => movingKeys.has(item.id));
      const earliestStart = Math.min(...movingItems.map((item) => item.start));
      const latestEnd = Math.max(...movingItems.map((item) => item.start + item.duration));
      linkedDelta = Math.max(-earliestStart, deltaSeconds);
      const currentStart = earliestStart + linkedDelta;
      const currentEnd = latestEnd + linkedDelta;
      const snap = nearestSnap(
        [
          { time: currentStart, apply: (candidate) => Math.max(-earliestStart, linkedDelta + candidate - currentStart) },
          { time: currentEnd, apply: (candidate) => Math.max(-earliestStart, linkedDelta + candidate - currentEnd) },
        ],
        candidates,
        thresholdSeconds,
        event.altKey || !editor.timelineState.options.snapping,
      );
      if (snap) {
        linkedDelta = snap.delta;
        snappedTime = snap.candidate;
      }
      next = drag.baseItems.map((item) => {
        if (movingKeys.has(item.id)) return { ...item, start: Math.max(0, item.start + linkedDelta) };
        return item;
      });
    } else if (drag.mode === 'trim-start') {
      const minLeftDelta = target.kind === 'image' ? -target.start : Math.max(-target.start, -(target.sourceStart || 0));
      linkedDelta = Math.max(minLeftDelta, Math.min(target.duration - minDuration, deltaSeconds));
      const currentStart = target.start + linkedDelta;
      const snap = nearestSnap(
        [{ time: currentStart, apply: (candidate) => Math.max(minLeftDelta, Math.min(target.duration - minDuration, linkedDelta + candidate - currentStart)) }],
        candidates,
        thresholdSeconds,
        event.altKey || !editor.timelineState.options.snapping,
      );
      if (snap) {
        linkedDelta = snap.delta;
        snappedTime = snap.candidate;
      }
      next = drag.baseItems.map((item) => {
        if (!movingKeys.has(item.id)) return item;
        return {
          ...item,
          start: Math.max(0, item.start + linkedDelta),
          duration: Math.max(minDuration, item.duration - linkedDelta),
          sourceStart: item.kind === 'image' ? item.sourceStart : Math.max(0, (item.sourceStart || 0) + linkedDelta),
        };
      });
    } else {
      const sourceDuration = sourceDurationForClip(target);
      const maxRightDelta = sourceDuration > 0
        ? Math.max(minDuration - target.duration, sourceDuration - (target.sourceStart || 0) - target.duration)
        : Number.POSITIVE_INFINITY;
      linkedDelta = Math.min(maxRightDelta, Math.max(minDuration - target.duration, deltaSeconds));
      const currentEnd = target.start + target.duration + linkedDelta;
      const snap = nearestSnap(
        [{ time: currentEnd, apply: (candidate) => Math.min(maxRightDelta, Math.max(minDuration - target.duration, linkedDelta + candidate - currentEnd)) }],
        candidates,
        thresholdSeconds,
        event.altKey || !editor.timelineState.options.snapping,
      );
      if (snap) {
        linkedDelta = snap.delta;
        snappedTime = snap.candidate;
      }
      next = drag.baseItems.map((item) => movingKeys.has(item.id)
        ? { ...item, duration: Math.max(minDuration, item.duration + linkedDelta) }
        : item);
    }
    const fps = Math.max(1, editor.timelineState.fps || 30);
    next = next.map((item) => movingKeys.has(item.id)
      ? { ...item, start: Math.round(item.start * fps) / fps, duration: Math.max(0.05, Math.round(item.duration * fps) / fps), sourceStart: Math.round((item.sourceStart || 0) * fps) / fps }
      : item);
    showSnapGuide(snappedTime);
    drag.nextItems = next;
    if (drag.moved && drag.mode === 'move') {
      const visualDx = (linkedDelta / Math.max(drag.durationAtStart, 0.01)) * canvasWidth;
      setClipDragVisual(drag.visualElements, visualDx, true);
    } else if (drag.moved) {
      setClipShapeVisual(drag.visualElements, next, drag.durationAtStart, true);
      keepClipShapeVisualUntilNextPaint(drag, next);
      const currentEnd = Math.max(...next.map((item) => item.start + item.duration));
      if (currentEnd > drag.durationAtStart && canvasRef.current) {
        const nextWidth = Math.ceil(drag.canvasWidth * (currentEnd / drag.durationAtStart));
        if (nextWidth > canvasRef.current.clientWidth) {
          canvasRef.current.style.width = `${nextWidth}px`;
        }
      }
    }
  };
  const finishClipMove = (event: React.PointerEvent<HTMLElement>) => {
    const drag = clipMoveRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    clipMoveRef.current = null;
    showSnapGuide();
    const clearVisuals = () => {
      if (drag.mode === 'move') clearClipDragVisual(drag.visualElements);
      else clearClipShapeVisual(drag.visualElements);
      setDragDisplayDuration(null);
    };
    if (drag.moved) {
      suppressClickRef.current = true;
      const movedTarget = drag.nextItems.find((item) => item.id === drag.key);
      if (movedTarget) editor.setPlayhead(movedTarget.start);
      const nextTimelineDuration = drag.nextItems.reduce((end, item) => Math.max(end, item.start + item.duration), 0);
      if (nextTimelineDuration > drag.durationAtStart + 0.01) {
        const nextWidth = Math.ceil(editor.timelineWidth * (nextTimelineDuration / Math.max(drag.durationAtStart, 0.01)));
        editor.setTimelineWidth(Math.min(maximumWidth, Math.max(editor.timelineWidth, nextWidth)));
      }
      clearVisuals();
      void editor.commitTimelineItems(drag.nextItems, drag.mode === 'move' ? 'Moved timeline clip.' : 'Resized timeline clip.', drag.baseItems);
      return;
    }
    clearVisuals();
  };
  const canvasPoint = (clientX: number, clientY: number) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) return { x: 0, y: 0 };
    return {
      x: Math.max(0, Math.min(bounds.width, clientX - bounds.left)),
      y: Math.max(0, Math.min(bounds.height, clientY - bounds.top)),
    };
  };
  const beginMarquee = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('[data-timeline-item]')) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.clientY < bounds.top + 26) return;
    const point = canvasPoint(event.clientX, event.clientY);
    dragRef.current = { clientX: event.clientX, clientY: event.clientY, x: point.x, y: point.y, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
    setMarquee({ left: point.x, top: point.y, width: 0, height: 0 });
  };
  const moveMarquee = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start) return;
    const point = canvasPoint(event.clientX, event.clientY);
    start.moved = start.moved || Math.abs(event.clientX - start.clientX) > 3 || Math.abs(event.clientY - start.clientY) > 3;
    setMarquee({
      left: Math.min(start.x, point.x),
      top: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x),
      height: Math.abs(point.y - start.y),
    });
  };
  const finishMarquee = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start) return;
    dragRef.current = null;
    if (start.moved) {
      const left = Math.min(start.clientX, event.clientX);
      const right = Math.max(start.clientX, event.clientX);
      const top = Math.min(start.clientY, event.clientY);
      const bottom = Math.max(start.clientY, event.clientY);
      const keys = Array.from(canvasRef.current?.querySelectorAll<HTMLElement>('[data-timeline-item]') || [])
        .filter((item) => {
          const bounds = item.getBoundingClientRect();
          return bounds.right >= left && bounds.left <= right && bounds.bottom >= top && bounds.top <= bottom;
        })
        .map((item) => item.dataset.timelineItem!)
        .filter(Boolean);
      editor.setSelection(keys.length ? { type: 'timeline-items', keys: [...new Set(keys)] } : { type: 'project' });
      suppressClickRef.current = true;
    }
    setMarquee(null);
  };

  const audioProgressRaw = Number(editor.activeAudioJob?.progress || 0);
  const audioProgress = Math.round(Math.max(0, Math.min(100, audioProgressRaw <= 1 ? audioProgressRaw * 100 : audioProgressRaw)));
  const audioModeLabel = editor.audioMode === 'remove_vocals' ? 'No vocals' : editor.audioMode === 'remove_music' ? 'No music' : 'Original';
  const trackIcon = (kind: TimelineTrackKind) => kind === 'audio' ? Music2 : kind === 'subtitle' || kind === 'text' ? Captions : kind === 'effect' ? Flag : Film;
  const renderTrackRow = (track: TimelineTrack) => {
    const rowItems = editor.timelineItems.filter((item) => item.track === track.id);
    const rowClass = `timeline-track ${track.kind}-track ${track.hidden ? 'track-hidden' : ''} ${track.muted ? 'track-muted' : ''} ${isTrackSelected(track.id) ? 'track-selected' : ''}`;
    if (track.kind === 'video') {
      const mediaItems = rowItems.filter((item) => item.kind === 'video' || item.kind === 'image');
      return <div key={track.id} data-track-row={track.id} className={`${rowClass} video-track`}>
        {track.id === 'V1' && !legacySingleVideo && !mediaItems.length ? <div className="timeline-drop-hint"><Plus size={14} /> Drop video or image here</div> : null}
        {track.id === 'V1' && legacySingleVideo && <button
          data-timeline-item={`video:${editor.project.id}`}
          className={`video-clip ${isItemSelected(`video:${editor.project.id}`) ? 'selected' : ''}`}
          onClick={(event) => selectItem(event, `video:${editor.project.id}`, { type: 'video', id: editor.project.id })}
          onContextMenu={(event) => openVideoContextMenu(event, editor.project.id)}
        >
          <span className="clip-thumbs">{Array.from({ length: 10 }, (_, index) => <i key={index} style={{ backgroundImage: `url(/api/videos/${editor.project.id}/thumbnail)`, backgroundPosition: `${index * 10}% center` }} />)}</span>
          <strong>{editor.project.title}</strong>
          <span className={`video-audio-mode ${editor.audioMode}`}>{audioModeLabel}</span>
          <small>{formatClock(editor.duration)}</small>
          {editor.activeAudioJob && <span className="audio-separation-progress"><i style={{ width: `${Math.max(2, audioProgress)}%` }} /><em>{audioProgress}%</em></span>}
        </button>}
        {mediaItems.map((item) => <TimelineMediaClip key={item.id} item={item} duration={displayDuration} selected={isItemSelected(item.id)} audioMode={item.kind === 'video' && item.sourceVideoId ? audioModeForVideo(item.sourceVideoId) : undefined} audioJob={item.kind === 'video' ? editor.audioJobForVideo(item.sourceVideoId) : undefined} onSelect={(event) => {
          selectItem(event, item.id, { type: 'timeline-items', keys: [item.id], track: track.id });
        }} onPointerDown={(event) => beginClipMove(event, item, { type: 'timeline-items', keys: [item.id], track: track.id })} onPointerMove={moveClip} onPointerUp={finishClipMove} onPointerCancel={finishClipMove} onTrimStart={(event) => beginClipTrim(event, item, 'start')} onTrimEnd={(event) => beginClipTrim(event, item, 'end')} onContextMenu={item.kind === 'video' && item.sourceVideoId ? (event) => openVideoContextMenu(event, item.sourceVideoId!, item.id) : undefined} />)}
      </div>;
    }
    if (track.kind === 'subtitle') {
      const srtJob = editor.activeJobs.find((job) => job.kind === 'srt');
      return <SubtitleTrack key={track.id} editor={editor} duration={displayDuration} selectedKeys={selectedKeys} trackSelected={isTrackSelected(track.id)} items={rowItems.filter((item) => item.kind === 'srt')} trackId={track.id} onSelect={selectItem} job={srtJob} />;
    }
    if (track.kind === 'audio') {
      return <div key={track.id} data-track-row={track.id} className={`${rowClass} audio-track voice-track`}>
        {track.id === 'A2' && mergedVoiceAsset && <button data-timeline-item="voice:merged" className={`voice-clip ready ${isItemSelected('voice:merged') ? 'selected' : ''}`} style={{ left: '0%', width: '100%' }} title="Select then press Delete or Backspace to remove voiceover" onKeyDown={deleteVoiceoverFromClip} onClick={(event) => { selectItem(event, 'voice:merged', { type: 'timeline-items', keys: ['voice:merged'], track: 'A2' }); }}><span>Voiceover</span></button>}
        {rowItems.filter((item) => item.kind === 'audio').map((item) => item.track === 'A1'
          ? <button key={item.id} data-timeline-item={item.id} className={`audio-clip ${isItemSelected(item.id) ? 'selected' : ''}`} style={{ left: percent(item.start, displayDuration), width: percent(item.duration, displayDuration) }} onPointerDown={(event) => beginClipMove(event, item, { type: 'timeline-items', keys: [item.id], track: track.id })} onPointerMove={moveClip} onPointerUp={finishClipMove} onPointerCancel={finishClipMove} onClick={(event) => selectItem(event, item.id, { type: 'timeline-items', keys: [item.id], track: track.id })}>{item.sourceVideoId && <img className="waveform-image" src={`/api/videos/${item.sourceVideoId}/waveform?audioMode=original`} alt="Extracted audio waveform" />}</button>
          : <TimelineAudioClip key={item.id} item={item} duration={displayDuration} selected={isItemSelected(item.id)} onPointerDown={(event) => beginClipMove(event, item, { type: 'timeline-items', keys: [item.id], track: track.id })} onPointerMove={moveClip} onPointerUp={finishClipMove} onPointerCancel={finishClipMove} onSelect={(event) => selectItem(event, item.id, { type: 'timeline-items', keys: [item.id], track: track.id })} />)}
        {track.id === 'A2' && editor.activeJobs.find((job) => ['tts', 'tts-segment', 'tts-mux'].includes(job.kind)) && <TimelineJob job={editor.activeJobs.find((job) => ['tts', 'tts-segment', 'tts-mux'].includes(job.kind))!} />}
      </div>;
    }
    return <div key={track.id} data-track-row={track.id} className={rowClass}>
      {rowItems.map((item) => <button key={item.id} data-timeline-item={item.id} className={`effect-clip ${isItemSelected(item.id) ? 'selected' : ''}`} style={{ left: percent(item.start, displayDuration), width: percent(item.duration, displayDuration) }} onClick={(event) => selectItem(event, item.id, { type: 'timeline-items', keys: [item.id], track: track.id })}>
        <Flag size={12} /> {item.name}
      </button>)}
    </div>;
  };

  return <><section className="timeline-panel" onKeyDown={deleteSelectedTimelineItem}>
    <header className="timeline-header">
      <div><button className="view-label active" onClick={() => editor.setBottomView('timeline')}>Timeline</button><button className="view-label" onClick={() => editor.setBottomView('script')}>Script</button><span className="timeline-history"><button aria-label="Undo subtitle edit" title="Undo (Ctrl/Cmd+Z)" disabled={!editor.canUndo} onClick={editor.undoDraft}><Undo2 size={14} /></button><button aria-label="Redo subtitle edit" title="Redo (Ctrl/Cmd+Shift+Z)" disabled={!editor.canRedo} onClick={editor.redoDraft}><Redo2 size={14} /></button></span></div>
      <div className="timeline-actions">
        <button aria-label="Split selected clips" title="Split selected clips (S)" onClick={() => void editor.splitSelectedTimelineItems()}><Scissors size={14} /></button>
        <button aria-label="Duplicate selected clips" title="Duplicate selected clips (Ctrl/Cmd+D)" onClick={() => void editor.duplicateSelectedTimelineItems()}><Copy size={14} /></button>
        <button aria-label="Copy selected clips" title="Copy selected clips (Ctrl/Cmd+C)" onClick={() => void editor.copyTimelineItems()}><Clipboard size={14} /></button>
        <button aria-label="Paste timeline clips" title="Paste timeline clips (Ctrl/Cmd+V)" onClick={() => void editor.pasteTimelineItemsAt()}><Plus size={14} /></button>
        <button className={editor.timelineState.options.snapping ? 'active' : ''} aria-label="Toggle snapping" title="Toggle snapping" onClick={() => void editor.setTimelineOption('snapping', !editor.timelineState.options.snapping)}><Magnet size={14} /></button>
        <button className={editor.timelineState.options.ripple ? 'active' : ''} aria-label="Toggle ripple edit" title="Toggle ripple edit" onClick={() => void editor.setTimelineOption('ripple', !editor.timelineState.options.ripple)}><Layers size={14} /></button>
        <button aria-label="Bookmark playhead" title="Bookmark playhead" onClick={() => void editor.toggleTimelineBookmark()}><Flag size={14} /></button>
      </div>
      <div>
        <button aria-label="Zoom timeline out" title="Zoom out" disabled={editor.timelineWidth <= minimumWidth} onClick={() => editor.setTimelineWidth(Math.max(minimumWidth, editor.timelineWidth - 200))}><Minus size={14} /></button>
        <SliderNumericField className="timeline-zoom-control" value={editor.timelineWidth} min={minimumWidth} max={maximumWidth} step={50} unit="px" onChange={editor.setTimelineWidth} ariaLabel="Timeline zoom" />
        <button aria-label="Zoom timeline in" title="Zoom in" disabled={editor.timelineWidth >= maximumWidth} onClick={() => editor.setTimelineWidth(Math.min(maximumWidth, editor.timelineWidth + 200))}><Plus size={14} /></button>
      </div>
    </header>
    <div className="timeline-scroll" ref={scrollRef}>
      <div className="track-labels">
        <div className="ruler-corner" />
        {stateTracks.map((track) => <TrackLabel
          key={track.id}
          icon={trackIcon(track.kind)}
          track={track}
          selected={isTrackSelected(track.id)}
          onSelect={() => selectTrack(track.id)}
          onMute={() => void editor.toggleTimelineTrackMute(track.id)}
          onHide={() => void editor.toggleTimelineTrackVisibility(track.id)}
          onRemove={() => void editor.removeTimelineTrack(track.id)}
        />)}
        {visibleEffectOperation && <TrackLabel icon={Flag} name="FX" detail="Subtitle Render" selected={isTrackSelected('FX')} onSelect={() => selectTrack('FX')} />}
        <div className="track-add-row">
          {(['video', 'audio', 'subtitle', 'text', 'effect'] as TimelineTrackKind[]).map((kind) => {
            const Icon = trackIcon(kind);
            return <button key={kind} aria-label={`Add ${kind} track`} title={`Add ${kind} track`} onClick={() => void editor.addTimelineTrack(kind)}><Icon size={13} /><Plus size={11} /></button>;
          })}
        </div>
      </div>
      <div
        className="tracks-canvas"
        style={{ width: editor.timelineWidth }}
        ref={canvasRef}
        onPointerDown={beginMarquee}
        onPointerMove={moveMarquee}
        onPointerUp={finishMarquee}
        onPointerCancel={() => { dragRef.current = null; setMarquee(null); }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        onClick={(event) => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false;
            return;
          }
          const rect = event.currentTarget.getBoundingClientRect();
          editor.setPlayhead(Math.max(0, Math.min(editor.duration, ((event.clientX - rect.left) / rect.width) * displayDuration)));
          if (!(event.target as HTMLElement).closest('[data-timeline-item]')) editor.setSelection({ type: 'project' });
        }}
      >
        <div className="timeline-ruler">{marks.map((mark) => <span key={mark} style={{ left: percent(mark, displayDuration) }}><i />{formatClock(mark)}</span>)}</div>
        <div className="timeline-bookmarks">
          {editor.timelineState.bookmarks.map((bookmark) => <button
            key={bookmark.id}
            data-timeline-bookmark={bookmark.id}
            style={{ left: percent(bookmark.time, displayDuration), ['--bookmark-color' as string]: bookmark.color || '#f59e0b' }}
            title={bookmark.note || formatClock(bookmark.time)}
            onClick={(event) => { event.stopPropagation(); editor.setPlayhead(bookmark.time); }}
          />)}
        </div>
        {stateTracks.map(renderTrackRow)}
        {visibleEffectOperation && <div className={`timeline-track fx-track ${isTrackSelected('FX') ? 'track-selected' : ''}`}>
          {hasBlurEffect ? <button
            data-timeline-item="effect:blur"
            className={`effect-clip ${isItemSelected('effect:blur') ? 'selected' : ''}`}
            style={{ width: '100%' }}
            title="Select then press Delete or Backspace to remove this effect"
            onKeyDown={deleteBlurEffectFromClip}
            onClick={(event) => selectItem(event, 'effect:blur', { type: 'effect', operation: 'blur' })}
          ><Flag size={12} /> Subtitle blur - {editor.activeBlurEffect?.mode === 'auto' ? 'Auto' : 'Manual'} effect</button>
            : legacyEffectOperation && <button
              data-timeline-item={`effect:${legacyEffectOperation}`}
              className={`effect-clip ${isItemSelected(`effect:${legacyEffectOperation}`) ? 'selected' : ''}`}
              style={{ width: '100%' }}
              onClick={(event) => selectItem(event, `effect:${legacyEffectOperation}`, { type: 'effect', operation: legacyEffectOperation })}
            ><Flag size={12} /> {legacyEffectOperation === 'insert' ? 'Rendered captions - version' : 'Original subtitle hidden - rendered version'}</button>}
        </div>}
        {!legacySingleVideo && !editor.timelineItems.length && <div className="timeline-empty-drop">
          <span><Film size={16} /> Drag media here to start editing</span>
          <button onClick={(event) => { event.stopPropagation(); editor.setAssetTab('assets'); editor.setMessage('Open the Download tab, then drag a video into V1.'); }}><Plus size={16} /> Add media to timeline</button>
        </div>}
        <div ref={snapGuideRef} className="timeline-snap-guide" hidden><span /></div>
        <div className="playhead" style={{ left: percent(editor.playhead, displayDuration) }} onPointerDown={beginScrub} onPointerMove={moveScrub} onPointerUp={finishScrub} onPointerCancel={finishScrub}><i /></div>
        {marquee && <div className="timeline-marquee" style={marquee} />}
      </div>
    </div>
  </section>
    {contextMenu && createPortal(
      <div
        className="video-audio-context-menu"
        style={{ left: Math.min(contextMenu.x, window.innerWidth - 248), top: Math.min(contextMenu.y, window.innerHeight - 166) }}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <span>Video clip</span>
        <div className="context-submenu">
          <button className="has-submenu">
            <Scissors size={14} /> <strong>Audio mode</strong><ChevronRight className="submenu-arrow" size={14} />
          </button>
          <div className="context-flyout">
            {([
              ['original', 'Original'],
              ['remove_vocals', 'Remove vocals'],
              ['remove_music', 'Keep vocals'],
            ] as const).map(([mode, label]) => <button key={mode} className={audioModeForVideo(contextMenu.videoId) === mode ? 'active' : ''} onClick={() => { setContextMenu(null); void editor.setTimelineVideoAudioMode(contextMenu.videoId, mode); }}>
              <Check size={14} /> <strong>{label}</strong>
            </button>)}
          </div>
        </div>
        <button onClick={() => {
          const item = timelineClipById(contextMenu.timelineItemId);
          setContextMenu(null);
          if (item) void editor.extractAudioFromTimelineClip(item);
          else editor.setMessage('Add this video to a workspace timeline before extracting audio.');
        }}>
          <FileAudio2 size={14} /> <strong>{clipHasExtractedAudio(timelineClipById(contextMenu.timelineItemId)) ? 'Restore audio' : 'Extract audio'}</strong>
        </button>
        <small>Extract audio moves the original sound to A1 and mutes the V1 clip. Restore removes that A1 item and turns the clip audio back on.</small>
      </div>,
      document.body,
    )}
  </>;
}

function TimelineMediaClip({ item, duration, selected, audioMode, audioJob, onSelect, onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onTrimStart, onTrimEnd, onContextMenu }: {
  item: TimelineItem;
  duration: number;
  selected: boolean;
  audioMode?: string;
  audioJob?: { progress?: number; detail?: string };
  onSelect: (event: React.MouseEvent) => void;
  onPointerDown?: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onPointerMove?: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerUp?: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerCancel?: (event: React.PointerEvent<HTMLElement>) => void;
  onTrimStart?: (event: React.PointerEvent<HTMLElement>) => void;
  onTrimEnd?: (event: React.PointerEvent<HTMLElement>) => void;
  onContextMenu?: (event: React.MouseEvent) => void;
}) {
  const width = `${Math.max(2, (item.duration / Math.max(duration, .01)) * 100)}%`;
  const isVideo = item.kind === 'video' && item.sourceVideoId;
  const imageUrl = item.kind === 'image' && item.projectAssetId ? `/api/project-assets/${item.projectAssetId}/download?preview=1` : '';
  const audioProgressRaw = Number(audioJob?.progress || 0);
  const audioProgress = Math.round(Math.max(0, Math.min(100, audioProgressRaw <= 1 ? audioProgressRaw * 100 : audioProgressRaw)));
  const audioModeLabel = audioMode === 'remove_vocals' ? 'No vocals' : audioMode === 'remove_music' ? 'No music' : 'Original';
  return <button
    data-timeline-item={item.id}
    className={`${item.kind === 'image' ? 'media-asset-clip' : 'video-clip'} ${selected ? 'selected' : ''}`}
    style={{ left: percent(item.start, duration), width }}
    title="Select then press Delete or Backspace to remove this clip"
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={onPointerUp}
    onPointerCancel={onPointerCancel}
    onClick={onSelect}
    onContextMenu={onContextMenu}
  >
    {isVideo && <span className="clip-thumbs">{Array.from({ length: 8 }, (_, index) => <i key={index} style={{ backgroundImage: `url(/api/videos/${item.sourceVideoId}/thumbnail)`, backgroundPosition: `${index * 12}% center` }} />)}</span>}
    {imageUrl && <span className="clip-thumbs image-thumbs">{Array.from({ length: 5 }, (_, index) => <i key={index} style={{ backgroundImage: `url(${imageUrl})` }} />)}</span>}
    <span className="timeline-trim-handle start" title="Trim start" onPointerDown={onTrimStart} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel} />
    <span className="timeline-trim-handle end" title="Trim end" onPointerDown={onTrimEnd} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel} />
    <strong>{item.name}</strong>
    {item.sourceAudioMuted ? <span className="video-audio-mode muted">Muted</span> : isVideo && audioMode && audioMode !== 'original' ? <span className={`video-audio-mode ${audioMode}`}>{audioModeLabel}</span> : null}
    <small>{formatClock(item.duration)}</small>
    {audioJob && <span className="audio-separation-progress"><i style={{ width: `${Math.max(2, audioProgress)}%` }} /><em>{audioProgress}%</em></span>}
  </button>;
}

function TimelineAudioClip({ item, duration, selected, onSelect, onPointerDown, onPointerMove, onPointerUp, onPointerCancel }: {
  item: TimelineItem;
  duration: number;
  selected: boolean;
  onSelect: (event: React.MouseEvent) => void;
  onPointerDown?: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onPointerMove?: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onPointerUp?: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onPointerCancel?: (event: React.PointerEvent<HTMLButtonElement>) => void;
}) {
  const width = `${Math.max(2, (item.duration / Math.max(duration, .01)) * 100)}%`;
  return <button
    data-timeline-item={item.id}
    className={`voice-clip ready ${selected ? 'selected' : ''}`}
    style={{ left: percent(item.start, duration), width }}
    title="Select then press Delete or Backspace to remove this audio clip"
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={onPointerUp}
    onPointerCancel={onPointerCancel}
    onClick={onSelect}
  ><span>{item.name}</span></button>;
}

function TimelineJob({ job }: { job: { progress?: number; detail?: string } }) {
  const raw = Number(job.progress || 0);
  const progress = raw <= 1 ? raw * 100 : raw;
  return <div className="timeline-job"><i style={{ width: `${Math.max(2, Math.min(100, progress))}%` }} /><span>{job.detail || 'Processing...'}</span></div>;
}

function TrackLabel({
  icon: Icon,
  track,
  name,
  detail,
  selected,
  onSelect,
  onMute,
  onHide,
  onRemove,
}: {
  icon: React.ComponentType<{ size?: number }>;
  track?: TimelineTrack;
  name?: string;
  detail?: string;
  selected: boolean;
  onSelect: () => void;
  onMute?: () => void;
  onHide?: () => void;
  onRemove?: () => void;
}) {
  const label = track?.id || name || 'Track';
  const helper = detail || track?.name || track?.kind || '';
  return <div className={`track-label ${selected ? 'selected' : ''}`}>
    <button className="track-select-button" aria-label={`Select all items on ${label} track`} aria-pressed={selected} title={`Select all on ${label}`} onClick={onSelect}>
      <Icon size={14} />
      <span><strong>{label}</strong><small>{helper}</small></span>
    </button>
    {track && <span className="track-actions">
      <button aria-label={`Mute ${label}`} title={track.muted ? `Unmute ${label}` : `Mute ${label}`} onClick={onMute}>{track.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}</button>
      <button aria-label={`Hide ${label}`} title={track.hidden ? `Show ${label}` : `Hide ${label}`} onClick={onHide}>{track.hidden ? <EyeOff size={11} /> : <Eye size={11} />}</button>
      <button aria-label={`Remove ${label}`} title={`Remove ${label}`} onClick={onRemove}><Trash2 size={11} /></button>
    </span>}
  </div>;
}

function SubtitleTrack({ editor, duration, selectedKeys, trackSelected, items, trackId, onSelect, job }: {
  editor: EditorController;
  duration: number;
  selectedKeys: Set<string>;
  trackSelected: boolean;
  items: TimelineItem[];
  trackId: string;
  onSelect: (event: React.MouseEvent, key: string, selection: InspectorSelection) => void;
  job?: { kind: string; progress?: number; detail?: string };
}) {
  const projectAssetsById = new Map((editor.project.projectAssets || []).map((asset) => [asset.id, asset]));
  const currentSrtAssetId = editor.srt.asset?.id;
  const srtAssetIdForItem = (item: TimelineItem) => {
    if (item.sourceAssetId) return item.sourceAssetId;
    const projectAsset = item.projectAssetId ? projectAssetsById.get(item.projectAssetId) : undefined;
    return projectAsset?.sourceAssetId || item.projectAssetId;
  };
  const hasCurrentSrtItem = Boolean(currentSrtAssetId && items.some((item) => srtAssetIdForItem(item) === currentSrtAssetId));
  const source = editor.project.workspaceId
    ? (hasCurrentSrtItem ? editor.srt.segments : [])
    : (trackId === 'S1' ? editor.srt.segments : []);
  const deleteSrtItem = (event: React.KeyboardEvent<HTMLButtonElement>, itemId: string) => {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return;
    event.preventDefault();
    event.stopPropagation();
    void editor.deleteTimelineItems([itemId]);
  };
  return <div data-track-row={trackId} className={`timeline-track subtitle-track ${trackSelected ? 'track-selected' : ''}`}>{source.map((segment) => {
    const width = Math.max(1.4, ((segment.end - segment.start) / duration) * 100);
    const key = `subtitle:${segment.index}`;
    const selected = selectedKeys.has(key) || (editor.selection.type === 'subtitle' && editor.selection.index === segment.index);
    const text = editor.edits[segment.index] ?? segment.text;
    return <button key={segment.index} data-timeline-item={key} className={selected ? 'selected' : ''} style={{ left: percent(segment.start, duration), width: `${width}%` }} title={text} onClick={(event) => { onSelect(event, key, { type: 'subtitle', index: segment.index }); }}>{text}</button>;
  })}{items.filter((item) => !(hasCurrentSrtItem && source.length > 0 && srtAssetIdForItem(item) === currentSrtAssetId)).map((item) => {
    const width = `${Math.max(2, (item.duration / Math.max(duration, .01)) * 100)}%`;
    return <button key={item.id} data-timeline-item={item.id} className={`subtitle-asset-clip ${selectedKeys.has(item.id) ? 'selected' : ''}`} style={{ left: percent(item.start, duration), width }} title="Select then press Delete or Backspace to remove this SRT clip" onKeyDown={(event) => deleteSrtItem(event, item.id)} onClick={(event) => onSelect(event, item.id, { type: 'timeline-items', keys: [item.id], track: trackId })}>{item.name}</button>;
  })}
  {job && <TimelineJob job={job} />}
  </div>;
}

function ScriptEditor({ editor }: { editor: EditorController }) {
  const issueByIndex = new Map(editor.timelineIssues.map((issue) => [issue.index, issue]));
  return <section className="timeline-panel script-panel">
    <header className="timeline-header"><div><button className="view-label" onClick={() => editor.setBottomView('timeline')}>Timeline</button><button className="view-label active">Script</button><span className="timeline-history"><button aria-label="Undo subtitle edit" title="Undo (Ctrl/Cmd+Z)" disabled={!editor.canUndo} onClick={editor.undoDraft}><Undo2 size={14} /></button><button aria-label="Redo subtitle edit" title="Redo (Ctrl/Cmd+Shift+Z)" disabled={!editor.canRedo} onClick={editor.redoDraft}><Redo2 size={14} /></button></span></div><div><span>{editor.srt.segments.length} subtitle lines</span><button className="view-label" onClick={editor.copySrt}>Copy SRT</button><button className="view-label" onClick={editor.pasteSrt}>Paste SRT</button><button className="primary view-label" onClick={editor.saveSrt} disabled={!editor.dirty}>Save script</button></div></header>
    <div className="script-table"><div className="script-head"><span>Timecode</span><span>Current text</span><span>Active subtitle text</span><span>Voice</span><span>Issue</span></div>{editor.srt.segments.map((segment, index) => {
      const source = editor.sourceSrt.segments[index];
      const voice = editor.voiceByIndex[segment.index];
      const currentText = editor.edits[segment.index] ?? segment.text;
      const issue = issueByIndex.get(segment.index);
      const activeIssue = issue && currentText.trim() === issue.text.trim() ? issue : undefined;
      const timingDetail = activeIssue
        ? [
            activeIssue.ttsDuration ? `Voice: ${activeIssue.ttsDuration.toFixed(2)}s` : '',
            activeIssue.availableDuration ? `Available: ${activeIssue.availableDuration.toFixed(2)}s` : '',
            activeIssue.requiredLocalSpeed ? `Required: ${activeIssue.requiredLocalSpeed.toFixed(2)}x` : '',
          ].filter(Boolean).join(' · ')
        : '';
      return <button className={`script-row ${activeIssue ? 'needs-review' : ''} ${editor.selection.type === 'subtitle' && editor.selection.index === segment.index ? 'active' : ''}`} key={segment.index} onClick={() => { editor.setSelection({ type: 'subtitle', index: segment.index }); editor.setPlayhead(segment.start); }}><span><strong>#{segment.index}</strong><small>{segment.startLabel}<br />{segment.endLabel}</small></span><span>{source?.text || segment.text}</span><textarea value={currentText} onClick={(event) => event.stopPropagation()} onChange={(event) => editor.setEdits({ ...editor.edits, [segment.index]: event.target.value })} /><span className={`voice-dot ${voice?.status || ''}`}>{voice?.audioUrl ? 'Ready' : 'Not rendered'}</span><span className={activeIssue ? 'script-issue error' : 'script-issue'}>{activeIssue ? <><strong>{activeIssue.needsReview ? 'Needs Review' : 'Too long for 1.30x'}</strong>{timingDetail && <small>{timingDetail}</small>}</> : '-'}</span></button>;
    })}{!editor.srt.segments.length && <div className="empty-row">Generate or select an SRT to open Script View.</div>}</div>
  </section>;
}
