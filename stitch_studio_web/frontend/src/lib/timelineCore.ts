import type { Project, ProjectAsset, TimelineBookmark, TimelineItem, TimelineItemKind, TimelineState, TimelineTrack, TimelineTrackKind } from '../types/studio';

export const DEFAULT_FPS = 30;
export const DEFAULT_CANVAS = { width: 1920, height: 1080, mode: 'source' as const };
export const MIN_CLIP_DURATION = 0.05;
export const DEFAULT_IMAGE_DURATION = 10;
export const DEFAULT_AUDIO_DURATION = 10;
export const DEFAULT_SUBTITLE_DURATION = 5;
export const MAX_TIMELINE_HISTORY = 100;

export function cloneTimelineItems(items: TimelineItem[]) {
  return items.map((item) => ({ ...item, params: item.params ? { ...item.params } : undefined }));
}

export function cloneTimelineState(state: TimelineState): TimelineState {
  return {
    ...state,
    canvas: { ...state.canvas },
    tracks: state.tracks.map((track) => ({ ...track })),
    items: cloneTimelineItems(state.items),
    bookmarks: state.bookmarks.map((bookmark) => ({ ...bookmark })),
    view: { ...state.view },
    options: { ...state.options },
  };
}

export function makeTimelineId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function defaultTracks(): TimelineTrack[] {
  return [
    { id: 'V1', kind: 'video', name: 'V1 Main Video' },
    { id: 'S1', kind: 'subtitle', name: 'S1 Subtitles' },
    { id: 'A1', kind: 'audio', name: 'A1 Source Audio' },
    { id: 'A2', kind: 'audio', name: 'A2 Voiceover' },
  ];
}

export function defaultTimelineState(items: TimelineItem[] = []): TimelineState {
  const normalizedItems = normalizeTimelineItems(items);
  const visualLayout = enforceVisualTrackLayout(ensureTracksForItems(defaultTracks(), normalizedItems), normalizedItems);
  return {
    version: 2,
    fps: DEFAULT_FPS,
    canvas: DEFAULT_CANVAS,
    tracks: visualLayout.tracks,
    items: visualLayout.items,
    bookmarks: [],
    view: { zoomLevel: 1, scrollLeft: 0, scrollTop: 0, playheadTime: 0 },
    options: { snapping: true, ripple: false },
  };
}

export function timelineStateFromProject(project: Pick<Project, 'timelineState' | 'workspaceTimeline' | 'durationMs'>): TimelineState {
  const raw = project.timelineState;
  if (raw && raw.version === 2 && Array.isArray(raw.items) && Array.isArray(raw.tracks)) {
    return normalizeTimelineState(raw);
  }
  return defaultTimelineState(project.workspaceTimeline || []);
}

export function normalizeTimelineState(state: TimelineState): TimelineState {
  const rawItems = normalizeTimelineItems(state.items || []);
  const normalizedTracks = (state.tracks || []).map(normalizeTrack).filter(Boolean) as TimelineTrack[];
  // SRT is a project-wide caption source, not an overlay clip. Older scene
  // payloads serialized an empty S1 as `text`, which made a later SRT import
  // create S2/S3 and leave phantom caption lanes behind. Restore the canonical
  // S1 lane and migrate those legacy SRT clips into it.
  const primarySubtitleTrack = normalizedTracks.find((track) => track.id === 'S1' && track.kind === 'subtitle')
    || normalizedTracks.find((track) => track.kind === 'subtitle')
    || { id: 'S1', kind: 'subtitle' as const, name: 'S1 Subtitles' };
  const items = rawItems.map((item) => item.kind === 'srt' ? { ...item, track: primarySubtitleTrack.id } : item);
  const tracks = ensureTracksForItems(normalizedTracks, items);
  const trackById = new Map(tracks.map((track) => [track.id, track]));
  const compatibleItems = items.map((item) => {
    const track = trackById.get(item.track);
    return track && canPlaceKindOnTrack(item.kind, track) ? item : { ...item, track: defaultTrackForKind(item.kind) };
  });
  const visualLayout = enforceVisualTrackLayout(tracks, compatibleItems);
  const finalTracks = pruneEmptyDynamicTracks(visualLayout.tracks, visualLayout.items);
  return {
    version: 2,
    fps: clampNumber(state.fps, 1, 240, DEFAULT_FPS),
    canvas: {
      width: Math.round(clampNumber(state.canvas?.width, 16, 16384, DEFAULT_CANVAS.width)),
      height: Math.round(clampNumber(state.canvas?.height, 16, 16384, DEFAULT_CANVAS.height)),
      mode: state.canvas?.mode || DEFAULT_CANVAS.mode,
    },
    tracks: finalTracks,
    items: visualLayout.items,
    bookmarks: normalizeBookmarks(state.bookmarks || []),
    view: {
      zoomLevel: clampNumber(state.view?.zoomLevel, 0.1, 100, 1),
      scrollLeft: Math.max(0, Number(state.view?.scrollLeft || 0)),
      scrollTop: Math.max(0, Number(state.view?.scrollTop || 0)),
      playheadTime: Math.max(0, Number(state.view?.playheadTime || 0)),
    },
    options: {
      snapping: state.options?.snapping !== false,
      ripple: Boolean(state.options?.ripple),
    },
  };
}

export function normalizeTimelineItems(items: TimelineItem[]) {
  return items
    .filter((item) => item && typeof item === 'object')
    .map((item, index) => {
      const kind = normalizeKind(item.kind);
      const track = item.track || defaultTrackForKind(kind);
      const start = Math.max(0, Number(item.start || 0));
      const duration = Math.max(MIN_CLIP_DURATION, Number(item.duration || MIN_CLIP_DURATION));
      return {
        ...item,
        id: String(item.id || makeTimelineId(`clip-${index + 1}`)),
        kind,
        track,
        name: String(item.name || kind.toUpperCase()),
        start,
        duration,
        sourceStart: Math.max(0, Number(item.sourceStart || 0)),
        sourceEnd: item.sourceEnd === undefined ? undefined : Math.max(0, Number(item.sourceEnd || 0)),
        sourceDuration: item.sourceDuration === undefined ? undefined : Math.max(0, Number(item.sourceDuration || 0)),
        speed: item.speed === undefined ? undefined : clampNumber(item.speed, 0.1, 80, 1),
        opacity: item.opacity === undefined ? undefined : clampNumber(item.opacity, 0, 1, 1),
        volumeDb: item.volumeDb === undefined ? undefined : clampNumber(item.volumeDb, -60, 20, 0),
      };
    });
}

export function flattenTimelineState(state: TimelineState) {
  return normalizeTimelineItems(state.items);
}

export function calculateTimelineDuration(items: TimelineItem[]) {
  return items.reduce((end, item) => Math.max(end, item.start + item.duration), 0);
}

export function endOfTrack(items: TimelineItem[], trackId: string) {
  return calculateTimelineDuration(items.filter((item) => item.track === trackId));
}

export function findTrack(state: TimelineState, trackId?: string) {
  return state.tracks.find((track) => track.id === trackId);
}

export function trackKindForItem(kind: TimelineItemKind): TimelineTrackKind {
  if (kind === 'audio') return 'audio';
  if (kind === 'srt') return 'subtitle';
  if (kind === 'text') return 'text';
  if (kind === 'effect') return 'effect';
  return 'video';
}

export function defaultTrackForKind(kind: TimelineItemKind) {
  if (kind === 'audio') return 'A2';
  if (kind === 'srt') return 'S1';
  if (kind === 'text') return 'T1';
  if (kind === 'effect') return 'FX1';
  return 'V1';
}

export function canPlaceKindOnTrack(kind: TimelineItemKind, track: TimelineTrack) {
  return track.kind === trackKindForItem(kind);
}

export function isVisualKind(kind: TimelineItemKind) {
  return kind === 'video' || kind === 'image';
}

export function trackHasOverlap(items: TimelineItem[], trackId: string, candidate: Pick<TimelineItem, 'id' | 'start' | 'duration'>) {
  const candidateStart = Math.max(0, candidate.start);
  const candidateEnd = candidateStart + Math.max(MIN_CLIP_DURATION, candidate.duration);
  return items.some((item) => {
    if (item.id === candidate.id || item.track !== trackId) return false;
    return candidateStart < item.start + item.duration && candidateEnd > item.start;
  });
}

export function resolvePlacement({
  state,
  kind,
  preferredTrackId,
  requestedStart,
  duration,
  allowNewTrack = true,
  preferHigherVisualTracks,
}: {
  state: TimelineState;
  kind: TimelineItemKind;
  preferredTrackId?: string;
  requestedStart?: number;
  duration: number;
  allowNewTrack?: boolean;
  preferHigherVisualTracks?: boolean;
}) {
  const trackKind = trackKindForItem(kind);
  const compatibleTracks = state.tracks.filter((track) => track.kind === trackKind && !track.locked);
  const preferred = preferredTrackId ? compatibleTracks.find((track) => track.id === preferredTrackId) : undefined;
  const start = Math.max(0, Number(requestedStart ?? NaN));
  const canUseRequestedStart = Number.isFinite(start);
  const preferredIndex = preferred ? compatibleTracks.findIndex((track) => track.id === preferred.id) : -1;
  const otherCandidates = preferred && isVisualKind(kind) && preferHigherVisualTracks !== false
    ? compatibleTracks.slice(preferredIndex + 1)
    : compatibleTracks.filter((track) => track.id !== preferred?.id);
  const candidates = preferred ? [preferred, ...otherCandidates] : compatibleTracks;

  for (const track of candidates) {
    const placedStart = canUseRequestedStart ? start : endOfTrack(state.items, track.id);
    if (!trackHasOverlap(state.items, track.id, { id: '__new__', start: placedStart, duration })) {
      return { trackId: track.id, start: placedStart, createdTrack: null as TimelineTrack | null };
    }
  }

  if (!allowNewTrack) {
    const track = candidates[0] || state.tracks.find((item) => item.kind === trackKind);
    return { trackId: track?.id || defaultTrackForKind(kind), start: canUseRequestedStart ? start : 0, createdTrack: null as TimelineTrack | null };
  }

  const createdTrack = buildTrack(trackKind, nextTrackName(state.tracks, trackKind));
  return { trackId: createdTrack.id, start: canUseRequestedStart ? start : 0, createdTrack };
}

export function addTrack(state: TimelineState, kind: TimelineTrackKind, name?: string, index?: number) {
  const track = buildTrack(kind, name || nextTrackName(state.tracks, kind));
  const tracks = index === undefined
    ? insertTimelineTrack(state.tracks, track)
    : (() => {
        const next = [...state.tracks];
        next.splice(Math.max(0, Math.min(index, next.length)), 0, track);
        return next;
      })();
  return { state: { ...state, tracks }, track };
}

/** Put automatically-created tracks where their layer order is obvious. */
export function insertTimelineTrack(tracks: TimelineTrack[], track: TimelineTrack) {
  const next = [...tracks];
  if (track.kind === 'video') {
    const firstNonVisual = next.findIndex((candidate) => candidate.kind !== 'video');
    next.splice(firstNonVisual < 0 ? next.length : firstNonVisual, 0, track);
    return next;
  }
  if (track.kind === 'subtitle') {
    const lastSubtitle = next.reduce((last, candidate, index) => candidate.kind === 'subtitle' ? index : last, -1);
    const firstAfterVisual = next.findIndex((candidate) => candidate.kind !== 'video');
    next.splice(lastSubtitle >= 0 ? lastSubtitle + 1 : (firstAfterVisual < 0 ? next.length : firstAfterVisual), 0, track);
    return next;
  }
  if (track.kind === 'audio') {
    const lastAudio = next.reduce((last, candidate, index) => candidate.kind === 'audio' ? index : last, -1);
    next.splice(lastAudio < 0 ? next.length : lastAudio + 1, 0, track);
    return next;
  }
  next.push(track);
  return next;
}

export function removeTrack(state: TimelineState, trackId: string) {
  const protectedTracks = new Set(['V1', 'S1', 'A1', 'A2']);
  if (protectedTracks.has(trackId)) return state;
  return {
    ...state,
    tracks: state.tracks.filter((track) => track.id !== trackId),
    items: state.items.filter((item) => item.track !== trackId),
  };
}

export function toggleTrackMute(state: TimelineState, trackId: string) {
  return { ...state, tracks: state.tracks.map((track) => track.id === trackId ? { ...track, muted: !track.muted } : track) };
}

export function toggleTrackVisibility(state: TimelineState, trackId: string) {
  return { ...state, tracks: state.tracks.map((track) => track.id === trackId ? { ...track, hidden: !track.hidden } : track) };
}

export function splitItemsAtTime(state: TimelineState, itemIds: string[], time: number, retain: 'both' | 'left' | 'right' = 'both') {
  const selected = new Set(itemIds);
  const created: TimelineItem[] = [];
  const items = state.items.flatMap((item) => {
    if (!selected.has(item.id) || time <= item.start || time >= item.start + item.duration) return [item];
    const leftDuration = time - item.start;
    const rightDuration = item.duration - leftDuration;
    const sourceSplit = (item.sourceStart || 0) + leftDuration;
    const left: TimelineItem = {
      ...item,
      duration: leftDuration,
      sourceEnd: sourceSplit,
      name: `${item.name} (left)`,
    };
    const right: TimelineItem = {
      ...item,
      id: makeTimelineId(`${item.kind}-split`),
      start: time,
      duration: rightDuration,
      sourceStart: item.kind === 'image' ? item.sourceStart : sourceSplit,
      splitParentId: item.splitParentId || item.id,
      name: `${item.name} (right)`,
    };
    created.push(right);
    if (retain === 'left') return [left];
    if (retain === 'right') return [right];
    return [left, right];
  });
  return { state: { ...state, items: normalizeTimelineItems(items) }, created };
}

export function duplicateItems(state: TimelineState, itemIds: string[], atTime?: number) {
  const selected = new Set(itemIds);
  const originals = state.items.filter((item) => selected.has(item.id));
  if (!originals.length) return { state, duplicated: [] as TimelineItem[] };
  const earliest = Math.min(...originals.map((item) => item.start));
  const offset = Math.max(0, atTime ?? Math.max(...originals.map((item) => item.start + item.duration))) - earliest;
  let working = cloneTimelineState(state);
  const duplicated: TimelineItem[] = [];
  for (const original of originals.sort((a, b) => a.start - b.start)) {
    const placement = resolvePlacement({
      state: working,
      kind: original.kind,
      preferredTrackId: original.track,
      requestedStart: Math.max(0, original.start + offset),
      duration: original.duration,
    });
    const copy = {
      ...original,
      id: makeTimelineId(`${original.kind}-copy`),
      track: placement.trackId,
      start: placement.start,
      name: `${original.name} copy`,
    };
    working = {
      ...working,
      tracks: placement.createdTrack ? insertTimelineTrack(working.tracks, placement.createdTrack) : working.tracks,
      items: [...working.items, copy],
    };
    duplicated.push(copy);
  }
  const normalized = normalizeTimelineState(working);
  return { state: normalized, duplicated: normalized.items.filter((item) => duplicated.some((copy) => copy.id === item.id)) };
}

export function pasteItems(state: TimelineState, items: TimelineItem[], playhead: number) {
  if (!items.length) return { state, pasted: [] as TimelineItem[] };
  const earliest = Math.min(...items.map((item) => item.start));
  let working = cloneTimelineState(state);
  const pasted: TimelineItem[] = [];
  for (const item of items.sort((a, b) => a.start - b.start)) {
    const placement = resolvePlacement({
      state: working,
      kind: item.kind,
      preferredTrackId: item.track,
      requestedStart: playhead + item.start - earliest,
      duration: item.duration,
      allowNewTrack: true,
    });
    const pastedItem = {
      ...item,
      id: makeTimelineId(`${item.kind}-paste`),
      track: placement.trackId,
      start: placement.start,
    };
    working = {
      ...working,
      tracks: placement.createdTrack ? insertTimelineTrack(working.tracks, placement.createdTrack) : working.tracks,
      items: [...working.items, pastedItem],
    };
    pasted.push(pastedItem);
  }
  const normalized = normalizeTimelineState(working);
  return { state: normalized, pasted: normalized.items.filter((item) => pasted.some((copy) => copy.id === item.id)) };
}

export function buildSnapCandidates(items: TimelineItem[], movingIds: Set<string>, bookmarks: TimelineBookmark[] = [], playhead?: number) {
  const values = [0];
  for (const item of items) {
    if (movingIds.has(item.id) || item.kind === 'srt') continue;
    values.push(item.start, item.start + item.duration);
  }
  for (const bookmark of bookmarks) {
    values.push(bookmark.time);
    if (bookmark.duration) values.push(bookmark.time + bookmark.duration);
  }
  if (typeof playhead === 'number') values.push(playhead);
  return [...new Set(values.map((value) => Number(value.toFixed(3))))].filter((value) => value >= 0);
}

export function nearestSnap(
  anchors: Array<{ time: number; apply: (candidate: number) => number }>,
  candidates: number[],
  thresholdSeconds: number,
  disabled: boolean,
) {
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
}

export function frameRound(value: number, fps: number) {
  const safeFps = clampNumber(fps, 1, 240, DEFAULT_FPS);
  return Math.round(value * safeFps) / safeFps;
}

export function rippleAfterEdit(previous: TimelineItem[], next: TimelineItem[], editedIds: Set<string>) {
  const result = cloneTimelineItems(next);
  for (const before of previous) {
    if (!editedIds.has(before.id)) continue;
    const after = next.find((item) => item.id === before.id);
    if (!after || before.track !== after.track) continue;
    const deltaEnd = (after.start + after.duration) - (before.start + before.duration);
    if (Math.abs(deltaEnd) < 0.001) continue;
    for (const item of result) {
      if (item.id === after.id || item.track !== after.track) continue;
      if (item.start >= before.start + before.duration - 0.001) {
        item.start = Math.max(0, item.start + deltaEnd);
      }
    }
  }
  return normalizeTimelineItems(result);
}

export function serializeClipboardItems(state: TimelineState, itemIds: string[]) {
  const selected = new Set(itemIds);
  return JSON.stringify({
    kind: 'stitch-timeline-items',
    version: 2,
    items: state.items.filter((item) => selected.has(item.id)),
  });
}

export function parseClipboardItems(raw: string): TimelineItem[] {
  try {
    const payload = JSON.parse(raw);
    if (payload?.kind !== 'stitch-timeline-items' || !Array.isArray(payload.items)) return [];
    return normalizeTimelineItems(payload.items);
  } catch {
    return [];
  }
}

export function createItemFromProjectAsset(asset: ProjectAsset, state: TimelineState, srtDuration = 0): { state: TimelineState; item: TimelineItem } {
  const kind: TimelineItemKind = asset.kind === 'image' ? 'image' : asset.kind === 'audio' ? 'audio' : asset.kind === 'srt' ? 'srt' : 'video';
  const sourceDuration = projectAssetDurationSeconds(asset);
  const duration = kind === 'image'
    ? DEFAULT_IMAGE_DURATION
    : kind === 'srt'
      ? Math.max(DEFAULT_SUBTITLE_DURATION, srtDuration)
      : Math.max(MIN_CLIP_DURATION, sourceDuration || (kind === 'audio' ? DEFAULT_AUDIO_DURATION : MIN_CLIP_DURATION));
  const placement = resolvePlacement({ state, kind, duration });
  const tracks = placement.createdTrack ? insertTimelineTrack(state.tracks, placement.createdTrack) : state.tracks;
  const item: TimelineItem = {
    id: makeTimelineId(kind),
    kind,
    track: placement.trackId,
    name: asset.name,
    start: placement.start,
    duration,
    sourceStart: 0,
    sourceDuration: sourceDuration || undefined,
    projectAssetId: asset.id,
    sourceAssetId: asset.sourceAssetId,
    sourceVideoId: asset.sourceVideoId,
  };
  return { state: { ...state, tracks, items: normalizeTimelineItems([...state.items, item]) }, item };
}

export function projectAssetDurationSeconds(asset?: ProjectAsset | null): number {
  if (!asset) return 0;
  const metadata = asset.metadata || {};
  const durationMs = Number(metadata.duration_ms || metadata.durationMs || metadata.audio_duration_ms || 0);
  if (durationMs > 0) return durationMs / 1000;
  const durationSeconds = Number(metadata.duration_seconds || metadata.duration || 0);
  if (durationSeconds > 0) return durationSeconds;
  if (asset.asset) {
    const linkedMeta = asset.asset.metadata || {};
    const linkedMs = Number(linkedMeta.duration_ms || linkedMeta.durationMs || linkedMeta.audio_duration_ms || 0);
    if (linkedMs > 0) return linkedMs / 1000;
    const linkedSec = Number(linkedMeta.duration_seconds || linkedMeta.duration || 0);
    if (linkedSec > 0) return linkedSec;
  }
  const videoDurationMs = Number(asset.video?.durationMs || 0);
  if (videoDurationMs > 0) return videoDurationMs / 1000;
  return 0;
}

/**
 * A visual lane is a single editorial sequence: video and image clips never
 * overlap within it. Existing/legacy invalid layouts are repaired by moving
 * only the later conflicting clip to an available higher visual lane, keeping
 * its requested time intact. This is also the final invariant before saving.
 */
export function enforceVisualTrackLayout(
  tracks: TimelineTrack[],
  items: TimelineItem[],
  options: { pinnedItemIds?: Set<string>; preferHigherTracksForIds?: Set<string> } = {},
) {
  let nextTracks = [...tracks];
  const nextItems = cloneTimelineItems(items);
  const visualTrackIndex = () => new Map(nextTracks.map((track, index) => [track.id, index]));
  const occupied = new Map<string, TimelineItem[]>();
  const visualItems = nextItems
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => isVisualKind(item.kind))
    .sort((a, b) => {
      const pinnedDelta = Number(Boolean(options.pinnedItemIds?.has(b.item.id))) - Number(Boolean(options.pinnedItemIds?.has(a.item.id)));
      if (pinnedDelta) return pinnedDelta;
      const positions = visualTrackIndex();
      const trackDelta = (positions.get(a.item.track) ?? Number.MAX_SAFE_INTEGER) - (positions.get(b.item.track) ?? Number.MAX_SAFE_INTEGER);
      return trackDelta || a.item.start - b.item.start || a.index - b.index;
    });

  for (const { item } of visualItems) {
    const track = nextTracks.find((candidate) => candidate.id === item.track && candidate.kind === 'video');
    const sourceTrackId = track?.id || 'V1';
    if (!track) item.track = sourceTrackId;
    const fits = (trackId: string) => !(occupied.get(trackId) || []).some((other) =>
      item.start < other.start + other.duration && item.start + item.duration > other.start,
    );
    let targetTrackId = sourceTrackId;
    if (!fits(targetTrackId)) {
      const visualTracks = nextTracks.filter((candidate) => candidate.kind === 'video' && !candidate.locked);
      const sourceIndex = Math.max(0, visualTracks.findIndex((candidate) => candidate.id === sourceTrackId));
      const candidates = options.preferHigherTracksForIds?.has(item.id)
        ? visualTracks.slice(sourceIndex + 1)
        : [...visualTracks.slice(sourceIndex + 1), ...visualTracks.slice(0, sourceIndex)];
      targetTrackId = candidates.find((candidate) => fits(candidate.id))?.id || '';
      if (!targetTrackId) {
        const created = buildTrack('video', nextTrackName(nextTracks, 'video'));
        nextTracks = insertTimelineTrack(nextTracks, created);
        targetTrackId = created.id;
      }
      item.track = targetTrackId;
    }
    const onTrack = occupied.get(item.track) || [];
    onTrack.push(item);
    occupied.set(item.track, onTrack);
  }
  return { tracks: nextTracks, items: nextItems };
}

function normalizeTrack(track: TimelineTrack): TimelineTrack | null {
  if (!track || typeof track !== 'object') return null;
  const id = String(track.id || nextTrackName([], normalizeTrackKind(track.kind)));
  const name = String(track.name || track.id || id);
  // Core scenes represent subtitle tracks as `text`. Retain the intended
  // timeline kind even when that lane happens to have no subtitle elements.
  const kind = id === 'S1' && normalizeTrackKind(track.kind) === 'text' && /subtitle/i.test(name)
    ? 'subtitle'
    : normalizeTrackKind(track.kind);
  return {
    id,
    kind,
    name,
    muted: Boolean(track.muted),
    hidden: Boolean(track.hidden),
    locked: Boolean(track.locked),
    height: track.height === undefined ? undefined : clampNumber(track.height, 24, 180, 42),
  };
}

function pruneEmptyDynamicTracks(tracks: TimelineTrack[], items: TimelineItem[]) {
  const protectedTrackIds = new Set(['V1', 'S1', 'A1', 'A2']);
  const occupied = new Set(items.map((item) => item.track));
  return tracks.filter((track) => protectedTrackIds.has(track.id) || occupied.has(track.id));
}

function ensureTracksForItems(tracks: TimelineTrack[], items: TimelineItem[]) {
  const next = tracks.length ? [...tracks] : defaultTracks();
  for (const item of items) {
    if (next.some((track) => track.id === item.track)) continue;
    // Missing dynamic tracks must keep the same visual stack ordering as
    // tracks created interactively. In particular V3 cannot be appended
    // underneath audio/subtitle lanes after a save/load cycle.
    const kind = trackKindForItem(item.kind);
    next.splice(0, next.length, ...insertTimelineTrack(next, buildTrack(kind, item.track || nextTrackName(next, kind))));
  }
  for (const fallback of defaultTracks()) {
    if (!next.some((track) => track.id === fallback.id)) next.splice(0, next.length, ...insertTimelineTrack(next, fallback));
  }
  return next;
}

function normalizeBookmarks(bookmarks: TimelineBookmark[]) {
  return bookmarks.map((bookmark) => ({
    id: String(bookmark.id || makeTimelineId('bookmark')),
    time: Math.max(0, Number(bookmark.time || 0)),
    duration: bookmark.duration === undefined ? undefined : Math.max(0, Number(bookmark.duration || 0)),
    note: bookmark.note ? String(bookmark.note) : undefined,
    color: bookmark.color ? String(bookmark.color) : undefined,
  }));
}

function buildTrack(kind: TimelineTrackKind, name: string): TimelineTrack {
  return { id: name.split(/\s+/)[0] || makeTimelineId(kind), kind, name };
}

function nextTrackName(tracks: TimelineTrack[], kind: TimelineTrackKind) {
  const prefix = kind === 'video' ? 'V' : kind === 'audio' ? 'A' : kind === 'subtitle' ? 'S' : kind === 'text' ? 'T' : 'FX';
  let index = 1;
  while (tracks.some((track) => track.id === `${prefix}${index}`)) index += 1;
  return `${prefix}${index}`;
}

function normalizeKind(kind: TimelineItemKind): TimelineItemKind {
  return ['video', 'image', 'audio', 'srt', 'text', 'effect'].includes(kind) ? kind : 'video';
}

function normalizeTrackKind(kind: TimelineTrackKind): TimelineTrackKind {
  return ['video', 'subtitle', 'audio', 'text', 'effect'].includes(kind) ? kind : 'video';
}

function clampNumber(value: unknown, min: number, max: number, fallback: number) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}
