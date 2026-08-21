import {
  defaultTracks,
  defaultTimelineState,
  normalizeTimelineItems,
  normalizeTimelineState,
  timelineStateFromProject,
} from '../lib/timelineCore';
import type { Project, TimelineItem, TimelineItemKind, TimelineState, TimelineTrack, TimelineTrackKind } from '../types/studio';
import type { CoreElementKind, CoreTimelineElement, CoreTimelineScene, CoreTimelineTrack, CoreTrackGroup, CoreTrackKind } from './types';

const DEFAULT_MAIN_TRACK_ID = 'V1';

export function timelineTrackKindToCore(kind: TimelineTrackKind): CoreTrackKind {
  if (kind === 'audio') return 'audio';
  if (kind === 'text' || kind === 'subtitle') return 'text';
  if (kind === 'effect') return 'effect';
  return 'video';
}

export function timelineItemKindToCore(kind: TimelineItemKind): CoreElementKind {
  if (kind === 'srt') return 'subtitle';
  return kind;
}

export function coreElementKindToTimeline(kind: CoreElementKind): TimelineItemKind {
  if (kind === 'subtitle') return 'srt';
  return kind;
}

export function trackGroupForTimelineTrack(track: TimelineTrack, mainTrackId = DEFAULT_MAIN_TRACK_ID): CoreTrackGroup {
  if (track.kind === 'audio') return 'audio';
  if (track.kind === 'video' && track.id === mainTrackId) return 'main';
  return 'overlay';
}

export function isCoreTimelineScene(value: unknown): value is CoreTimelineScene {
  const scene = value as CoreTimelineScene | undefined;
  return Boolean(scene && typeof scene === 'object' && scene.version === 1 && scene.tracks?.main && Array.isArray(scene.tracks.overlay) && Array.isArray(scene.tracks.audio));
}

export function timelineStateToScene(state: TimelineState, options: { sceneId?: string } = {}): CoreTimelineScene {
  const normalized = normalizeTimelineState(state);
  const mainTrack = normalized.tracks.find((track) => track.id === DEFAULT_MAIN_TRACK_ID && track.kind === 'video')
    || normalized.tracks.find((track) => track.kind === 'video')
    || defaultTracks().find((track) => track.id === DEFAULT_MAIN_TRACK_ID)!;
  const tracks = normalized.tracks.some((track) => track.id === mainTrack.id)
    ? normalized.tracks
    : [mainTrack, ...normalized.tracks];
  const elementsByTrack = new Map<string, CoreTimelineElement[]>();
  for (const item of normalized.items) {
    const track = tracks.find((candidate) => candidate.id === item.track) || mainTrack;
    const group = trackGroupForTimelineTrack(track, mainTrack.id);
    const element = timelineItemToCoreElement(item, track, group);
    const bucket = elementsByTrack.get(track.id) || [];
    bucket.push(element);
    elementsByTrack.set(track.id, bucket);
  }
  const coreTracks = tracks.map((track) => timelineTrackToCoreTrack(track, mainTrack.id, elementsByTrack.get(track.id) || []));
  return {
    id: options.sceneId || `scene-${Date.now()}`,
    version: 1,
    fps: normalized.fps,
    canvas: { ...normalized.canvas },
    tracks: {
      overlay: coreTracks.filter((track) => track.group === 'overlay'),
      main: coreTracks.find((track) => track.id === mainTrack.id) || timelineTrackToCoreTrack(mainTrack, mainTrack.id, []),
      audio: coreTracks.filter((track) => track.group === 'audio'),
    },
    bookmarks: normalized.bookmarks.map((bookmark) => ({ ...bookmark })),
    view: { ...normalized.view },
    options: { ...normalized.options },
    metadata: {
      timelineStateVersion: normalized.version,
      timelineTrackOrder: tracks.map((track) => track.id),
    },
  };
}

export function sceneToTimelineState(scene: CoreTimelineScene): TimelineState {
  const rawTracks = [
    ...scene.tracks.overlay,
    scene.tracks.main,
    ...scene.tracks.audio,
  ];
  const trackOrder = Array.isArray(scene.metadata?.timelineTrackOrder)
    ? scene.metadata.timelineTrackOrder.map(String)
    : rawTracks.map((track) => track.id);
  const tracks = rawTracks
    .map(coreTrackToTimelineTrack)
    .sort((a, b) => {
      const aIndex = trackOrder.indexOf(a.id);
      const bIndex = trackOrder.indexOf(b.id);
      return (aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex) - (bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex);
    });
  const items = rawTracks.flatMap((track) => track.elements.map((element) => coreElementToTimelineItem(element, track)));
  return normalizeTimelineState({
    version: 2,
    fps: scene.fps,
    canvas: { ...scene.canvas },
    tracks,
    items: normalizeTimelineItems(items),
    bookmarks: scene.bookmarks.map((bookmark) => ({ ...bookmark })),
    view: { ...scene.view },
    options: { ...scene.options },
  });
}

export function sceneFromProject(project: Pick<Project, 'projectId' | 'title' | 'timelineState' | 'workspaceTimeline' | 'durationMs' | 'sceneState'>): CoreTimelineScene {
  if (isCoreTimelineScene(project.sceneState)) {
    return project.sceneState;
  }
  return timelineStateToScene(timelineStateFromProject(project), { sceneId: `${project.projectId || project.title || 'project'}-scene` });
}

export function timelineStateFromSceneOrProject(project: Pick<Project, 'timelineState' | 'workspaceTimeline' | 'durationMs' | 'sceneState'>): TimelineState {
  if (isCoreTimelineScene(project.sceneState)) {
    return sceneToTimelineState(project.sceneState);
  }
  return timelineStateFromProject(project);
}

function timelineTrackToCoreTrack(track: TimelineTrack, mainTrackId: string, elements: CoreTimelineElement[]): CoreTimelineTrack {
  const group = trackGroupForTimelineTrack(track, mainTrackId);
  return {
    id: track.id,
    kind: timelineTrackKindToCore(track.kind),
    group,
    name: track.name,
    elements: elements.map((element) => ({ ...element, trackGroup: group })),
    muted: track.muted,
    hidden: track.hidden,
    locked: track.locked,
    height: track.height,
    legacyTrackId: track.id,
  };
}

function coreTrackToTimelineTrack(track: CoreTimelineTrack): TimelineTrack {
  return {
    id: track.legacyTrackId || track.id,
    kind: coreTrackKindToTimeline(track),
    name: track.name || track.id,
    muted: track.muted,
    hidden: track.hidden,
    locked: track.locked,
    height: track.height,
  };
}

function timelineItemToCoreElement(item: TimelineItem, track: TimelineTrack, group: CoreTrackGroup): CoreTimelineElement {
  return {
    id: item.id,
    kind: timelineItemKindToCore(item.kind),
    name: item.name,
    trackId: track.id,
    trackGroup: group,
    start: item.start,
    duration: item.duration,
    sourceStart: item.sourceStart || 0,
    sourceEnd: item.sourceEnd,
    sourceDuration: item.sourceDuration,
    media: {
      projectAssetId: item.projectAssetId,
      sourceAssetId: item.sourceAssetId,
      sourceVideoId: item.sourceVideoId,
      name: item.name,
    },
    muted: item.muted,
    hidden: item.hidden,
    volumeDb: item.volumeDb,
    speed: item.speed,
    opacity: item.opacity,
    params: item.params ? { ...item.params } : undefined,
    effects: item.effects ? item.effects.map((effect) => ({ ...effect })) : undefined,
    masks: item.masks ? item.masks.map((mask) => ({ ...mask })) : undefined,
    animations: item.animations ? { ...item.animations } : undefined,
    sourceAudioMuted: item.sourceAudioMuted,
    linkedElementId: item.linkedVideoItemId,
    splitParentId: item.splitParentId,
    legacy: {
      timelineItemId: item.id,
      timelineItemKind: item.kind,
      timelineTrackId: track.id,
    },
  };
}

function coreElementToTimelineItem(element: CoreTimelineElement, track: CoreTimelineTrack): TimelineItem {
  const kind = normalizeLegacyKind(element.legacy?.timelineItemKind) || coreElementKindToTimeline(element.kind);
  return {
    id: element.legacy?.timelineItemId || element.id,
    kind,
    track: element.legacy?.timelineTrackId || track.legacyTrackId || element.trackId || track.id,
    name: element.name,
    start: element.start,
    duration: element.duration,
    sourceStart: element.sourceStart,
    sourceEnd: element.sourceEnd,
    sourceDuration: element.sourceDuration,
    sourceVideoId: element.media?.sourceVideoId,
    projectAssetId: element.media?.projectAssetId,
    sourceAssetId: element.media?.sourceAssetId,
    sourceAudioMuted: element.sourceAudioMuted,
    linkedVideoItemId: element.linkedElementId,
    muted: element.muted,
    hidden: element.hidden,
    volumeDb: element.volumeDb,
    speed: element.speed,
    opacity: element.opacity,
    params: element.params ? { ...element.params } : undefined,
    effects: element.effects ? element.effects.map((effect) => ({ ...effect })) : undefined,
    masks: element.masks ? element.masks.map((mask) => ({ ...mask })) : undefined,
    animations: element.animations ? { ...element.animations } : undefined,
    splitParentId: element.splitParentId,
  };
}

function coreTrackKindToTimeline(track: CoreTimelineTrack): TimelineTrackKind {
  if (track.kind === 'audio') return 'audio';
  if (track.kind === 'text') {
    // The core scene uses `text` for both text and subtitle lanes. Preserve
    // the canonical empty S1 subtitle lane as well, otherwise an import made
    // after reopening a project creates a new S2/S3 lane.
    const canonicalSubtitleLane = (track.legacyTrackId || track.id) === 'S1' && /subtitle/i.test(track.name || '');
    return canonicalSubtitleLane || track.elements.some((element) => element.kind === 'subtitle' || element.legacy?.timelineItemKind === 'srt') ? 'subtitle' : 'text';
  }
  if (track.kind === 'effect') return 'effect';
  return 'video';
}

function normalizeLegacyKind(kind?: string): TimelineItemKind | undefined {
  return kind && ['video', 'image', 'audio', 'srt', 'text', 'effect'].includes(kind) ? kind as TimelineItemKind : undefined;
}

export function emptyScene(): CoreTimelineScene {
  return timelineStateToScene(defaultTimelineState());
}
