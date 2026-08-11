import type { CoreTimelineScene } from '../editor-core/types';
import type { TextStyle } from './textStyle';
import type { ImageAnimationConfig } from '../utils/image-animation/types';

export type ViewKey = 'projects' | 'templates' | 'downloads' | 'tts' | 'settings' | 'editor' | 'youtube';
export type ToolKey = 'subtitles' | 'translate' | 'remove' | 'insert' | 'voiceover' | 'audio' | 'export';
export type AudioMode = 'original' | 'remove_vocals' | 'remove_music';
export type InspectorSelection =
  | { type: 'project' }
  | { type: 'video'; id: number }
  | { type: 'asset'; id: number }
  | { type: 'subtitle-track'; assetId?: number }
  | { type: 'subtitle'; index: number }
  | { type: 'voice'; index: number }
  | { type: 'timeline-items'; keys: string[]; track?: string }
  | { type: 'effect'; operation: 'blur' | 'hide' | 'insert' };

export interface SubtitleArea {
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
}

export interface SubtitleStyle extends TextStyle {
  fontFamily: string;
  fontSize: number;
  fontColor: string;
  outlineColor: string;
  outline: number;
  background: boolean;
  fontWeight?: 'normal' | 'bold';
  fontStyle?: 'normal' | 'italic';
  textDecoration?: 'none' | 'underline';
  textTransform?: 'none' | 'uppercase' | 'lowercase' | 'capitalize';
  letterSpacing?: number;
  lineHeight?: number;
  textAlign?: 'left' | 'center' | 'right';
  verticalAlign?: 'top' | 'middle' | 'bottom';
}

export interface Asset {
  id: number;
  videoId: number;
  kind: string;
  path: string;
  name: string;
  engine: string;
  status: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface ProjectAsset {
  id: number;
  projectId: number;
  kind: string;
  path: string;
  name: string;
  status: string;
  createdAt: string;
  sourceVideoId?: number;
  sourceAssetId?: number;
  metadata: Record<string, unknown>;
  video?: Project;
  asset?: Asset;
}

export type TimelineItemKind = 'video' | 'image' | 'audio' | 'srt' | 'text' | 'effect';
export type TimelineTrackKind = 'video' | 'subtitle' | 'audio' | 'text' | 'effect';

export interface TimelineItem {
  id: string;
  kind: TimelineItemKind;
  track?: string;
  name: string;
  start: number;
  duration: number;
  sourceStart?: number;
  sourceEnd?: number;
  sourceDuration?: number;
  sourceVideoId?: number;
  projectAssetId?: number;
  sourceAssetId?: number;
  sourceAudioMuted?: boolean;
  linkedVideoItemId?: string;
  muted?: boolean;
  hidden?: boolean;
  volumeDb?: number;
  speed?: number;
  opacity?: number;
  params?: Record<string, unknown> & { imageAnimation?: ImageAnimationConfig };
  effects?: Array<Record<string, unknown>>;
  masks?: Array<Record<string, unknown>>;
  animations?: Record<string, unknown>;
  splitParentId?: string;
}

export interface TimelineTrack {
  id: string;
  kind: TimelineTrackKind;
  name: string;
  muted?: boolean;
  hidden?: boolean;
  locked?: boolean;
  height?: number;
}

export interface TimelineBookmark {
  id: string;
  time: number;
  duration?: number;
  note?: string;
  color?: string;
}

export interface TimelineViewState {
  zoomLevel: number;
  scrollLeft: number;
  scrollTop: number;
  playheadTime: number;
}

export interface TimelineState {
  version: 2;
  fps: number;
  canvas: {
    width: number;
    height: number;
    mode?: 'preset' | 'custom' | 'source';
  };
  tracks: TimelineTrack[];
  items: TimelineItem[];
  bookmarks: TimelineBookmark[];
  view: TimelineViewState;
  options: {
    snapping: boolean;
    ripple: boolean;
  };
}

export interface ProcessingState {
  srtGenerated: boolean;
  srtTranslated: boolean;
  voiceoverGenerated: boolean;
  subtitleHidden: boolean;
  subtitleInserted: boolean;
  lastOperation?: string;
  hideMode?: string;
  insertMode?: string;
}

export interface Project {
  id: number;
  title: string;
  sourceUrl?: string;
  source: string;
  path: string;
  name: string;
  mediaType: string;
  durationMs: number;
  sizeBytes: number;
  status: string;
  createdAt: string;
  assets: Asset[];
  hasSrt: boolean;
  hasTranslatedSrt: boolean;
  hasTts: boolean;
  audioMode?: AudioMode;
  audioSeparation?: {
    ready: boolean;
    model: string;
    vocalsAssetId?: number;
    instrumentalAssetId?: number;
  };
  projectId: string;
  workspaceId?: number;
  workspaceTitle?: string;
  projectAssets?: ProjectAsset[];
  workspaceTimeline?: TimelineItem[];
  timelineState?: TimelineState;
  sceneState?: CoreTimelineScene;
  parentVideoId?: number;
  subtitleArea?: SubtitleArea;
  subtitleStyle?: SubtitleStyle;
  subtitleBlurEffect?: {
    enabled: boolean;
    kind: 'subtitle_blur';
    mode: 'auto' | 'manual';
    area: SubtitleArea;
    source?: string;
    srt_asset_id?: number;
    longest_segment_index?: number;
    longest_segment_text?: string;
    updated_at?: number;
  };
  clipSettings?: {
    videoScale?: number;
    videoVolumeDb?: number;
    videoSpeed?: number;
    voiceVolumeDb?: number;
    voiceSpeed?: number;
  };
  processingState: ProcessingState;
  ttsTimeline?: {
    counts?: Record<string, number>;
    final_validation_status?: string;
  };
}

export interface WorkspaceProject {
  id: number;
  title: string;
  projectId: string;
  primaryVideoId?: number;
  primaryVideo?: Project | null;
  createdAt: string;
  durationMs: number;
  sizeBytes: number;
  videos: Project[];
  assets: ProjectAsset[];
  timeline: TimelineItem[];
  timelineState?: TimelineState;
  sceneState?: CoreTimelineScene;
  metadata: Record<string, unknown>;
}

export interface SubtitleSegment {
  index: number;
  start: number;
  end: number;
  startLabel: string;
  endLabel: string;
  text: string;
}

export interface SrtDocument {
  asset: Asset | null;
  content: string;
  segments: SubtitleSegment[];
}

export interface VoiceSegment {
  index: number;
  status?: string;
  audioUrl?: string;
  duration?: number;
  subtitleDuration?: number;
  requiredLocalSpeed?: number;
  detail?: string;
}

export interface TimelineIssue {
  index: number;
  status: string;
  text: string;
  startLabel?: string;
  endLabel?: string;
  ttsDuration?: number;
  availableDuration?: number;
  requiredLocalSpeed?: number;
  hardMaxLocalSpeed?: number;
  needsReview?: boolean;
  detail?: string;
}

export interface Job {
  id: number;
  kind: string;
  videoId?: number;
  title: string;
  status: 'queued' | 'running' | 'completed' | 'error' | 'cancelled';
  progress?: number;
  detail?: string;
  result?: any;
  createdAt?: string;
}

export interface VoiceOption {
  id: string;
  label?: string;
}

export interface StudioSettings {
  hasDouyinCookie: boolean;
  douyinCookieLength: number;
  hasGeminiApiKey?: boolean;
  geminiApiKeyLength?: number;
  backendPath?: string;
  frontendPath?: string;
}

export interface YoutubeChannel {
  id: number;
  name: string;
  avatar_path?: string;
  references_json: string;
  created_at: string;
  updated_at: string;
}

export interface YoutubeReference {
  url: string;
  title?: string;
}

export interface YoutubePrompt {
  id: number;
  channel_id: number;
  name: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface TemplateInputSlot {
  slotId: string;
  kind: 'image' | 'video' | 'audio';
  label: string;
  required: boolean;
  behavior: string;
  sourceProjectAssetId?: number;
}

export interface TemplateManifest {
  version: number;
  name: string;
  sourceProjectId: number;
  inputs: TemplateInputSlot[];
  generated: {
    kind: string;
    source: {
      type: string;
      slotId?: string;
    };
  }[];
  timelineTemplate: {
    items: any[];
    timelineState?: any;
    sceneState?: any;
    subtitleStyle?: any;
    subtitleArea?: any;
  };
}

export interface Template {
  id: number;
  name: string;
  sourceProjectId?: number;
  createdAt?: string;
  updatedAt?: string;
  manifest: TemplateManifest;
}

export interface TemplateSummary {
  id: number;
  name: string;
  version: number;
  sourceProjectId?: number;
  createdAt: string;
  updatedAt: string;
  inputCount: number;
  inputs: TemplateInputSlot[];
  generatedSummary: any[];
  canvas?: { width: number; height: number };
  fps?: number;
}
