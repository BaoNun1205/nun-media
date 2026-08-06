export type CoreTrackKind = 'video' | 'audio' | 'text' | 'effect';
export type CoreElementKind = 'video' | 'image' | 'audio' | 'subtitle' | 'text' | 'effect';
export type CoreTrackGroup = 'overlay' | 'main' | 'audio';

export interface CoreCanvas {
  width: number;
  height: number;
  mode?: 'preset' | 'custom' | 'source';
}

export interface CoreMediaRef {
  projectAssetId?: number;
  sourceAssetId?: number;
  sourceVideoId?: number;
  path?: string;
  name?: string;
}

export interface CoreTimelineElement {
  id: string;
  kind: CoreElementKind;
  name: string;
  trackId: string;
  trackGroup: CoreTrackGroup;
  start: number;
  duration: number;
  sourceStart: number;
  sourceEnd?: number;
  sourceDuration?: number;
  media?: CoreMediaRef;
  muted?: boolean;
  hidden?: boolean;
  volumeDb?: number;
  speed?: number;
  opacity?: number;
  params?: Record<string, unknown>;
  effects?: Array<Record<string, unknown>>;
  masks?: Array<Record<string, unknown>>;
  animations?: Record<string, unknown>;
  sourceAudioMuted?: boolean;
  linkedElementId?: string;
  splitParentId?: string;
  legacy?: {
    timelineItemId?: string;
    timelineItemKind?: string;
    timelineTrackId?: string;
  };
}

export interface CoreTimelineTrack {
  id: string;
  kind: CoreTrackKind;
  group: CoreTrackGroup;
  name: string;
  elements: CoreTimelineElement[];
  muted?: boolean;
  hidden?: boolean;
  locked?: boolean;
  height?: number;
  legacyTrackId?: string;
}

export interface CoreTimelineBookmark {
  id: string;
  time: number;
  duration?: number;
  note?: string;
  color?: string;
}

export interface CoreTimelineViewState {
  zoomLevel: number;
  scrollLeft: number;
  scrollTop: number;
  playheadTime: number;
}

export interface CoreTimelineOptions {
  snapping: boolean;
  ripple: boolean;
}

export interface CoreTimelineScene {
  id: string;
  version: 1;
  fps: number;
  canvas: CoreCanvas;
  tracks: {
    overlay: CoreTimelineTrack[];
    main: CoreTimelineTrack;
    audio: CoreTimelineTrack[];
  };
  bookmarks: CoreTimelineBookmark[];
  view: CoreTimelineViewState;
  options: CoreTimelineOptions;
  metadata?: Record<string, unknown>;
}

export interface CoreEditorProject {
  id: string;
  title: string;
  scene: CoreTimelineScene;
  media: CoreMediaRef[];
}
