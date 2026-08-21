import type { SubtitleArea, SubtitleSegment } from '../types/studio';

export const LANGUAGES = [
  ['vi', 'Vietnamese'], ['en', 'English'], ['zh', 'Chinese'], ['ja', 'Japanese'],
  ['ko', 'Korean'], ['th', 'Thai'], ['id', 'Indonesian'], ['ms', 'Malay'],
  ['tl', 'Tagalog'], ['fr', 'French'], ['de', 'German'], ['es', 'Spanish'],
  ['pt', 'Portuguese'], ['ru', 'Russian'], ['ar', 'Arabic'], ['hi', 'Hindi'],
] as const;

export const SOURCE_LANGUAGES = [['auto', 'Auto detect'], ...LANGUAGES] as const;
export const CAPCUT_LANGUAGES = [
  ['vi-VN', 'Vietnamese'], ['en-US', 'English'], ['ja-JP', 'Japanese'],
  ['zh-CN', 'Chinese'], ['es-ES', 'Spanish'], ['th-TH', 'Thai'],
  ['id-ID', 'Indonesian'], ['pt-BR', 'Portuguese'], ['fr-FR', 'French'], ['de-DE', 'German'],
] as const;
export const POCKET_LANGUAGES = [
  ['english', 'English'], ['french_24l', 'French'], ['german', 'German'],
  ['portuguese', 'Portuguese'], ['italian', 'Italian'], ['spanish', 'Spanish'],
] as const;

export function ttsLanguageOptions(engine = 'vieneu'): readonly (readonly [string, string])[] {
  if (engine === 'capcut') return CAPCUT_LANGUAGES;
  if (engine === 'pocket') return POCKET_LANGUAGES;
  return [['vi-VN', 'Vietnamese']] as const;
}

export function defaultTtsLanguage(engine = 'vieneu'): string {
  return ttsLanguageOptions(engine)[0]?.[0] || 'vi-VN';
}

export function isTtsLanguageSupported(engine: string, language: string) {
  return ttsLanguageOptions(engine).some(([id]) => id === language);
}

export const DEFAULT_AREA: SubtitleArea = { xmin: .04, xmax: .96, ymin: .60, ymax: .98 };
export const TTS_FIT = {
  minWorkingSpeed: .7,
  preferredMaxLocalSpeed: 1.3,
  hardMaxLocalSpeed: 1.3,
  safetyGap: .12,
};

export function formatDuration(ms = 0) {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60) % 60;
  const seconds = total % 60;
  return hours
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function formatClock(seconds = 0) {
  return formatDuration(seconds * 1000);
}

export function formatSize(bytes = 0) {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function serializeSrt(segments: SubtitleSegment[], edits: Record<number, string>) {
  return segments.map((segment, position) =>
    `${position + 1}\n${segment.startLabel} --> ${segment.endLabel}\n${(edits[segment.index] ?? segment.text).trim()}\n`,
  ).join('\n');
}

export function isTranslatedAsset(assetOrEngine: string | { engine?: string; metadata?: Record<string, unknown> } = '') {
  const engine = typeof assetOrEngine === 'string' ? assetOrEngine : assetOrEngine.engine || '';
  const metadata = typeof assetOrEngine === 'string' ? {} : assetOrEngine.metadata || {};
  return metadata.role === 'translation' || engine.toLowerCase().startsWith('gemini-3.5-flash-lite:');
}

export function percent(value: number, duration: number) {
  return `${Math.max(0, Math.min(100, (value / Math.max(duration, .01)) * 100))}%`;
}

export function projectStatus(project: { processingState?: any; hasTranslatedSrt?: boolean; hasSrt?: boolean }) {
  if (project.processingState?.subtitleInserted) return 'Inserted';
  if (project.processingState?.subtitleHidden) return 'Hidden';
  if (project.hasTranslatedSrt) return 'Translated';
  if (project.hasSrt) return 'SRT ready';
  return 'Source';
}

export const ASSET_GROUPS = {
  media: ['video', 'image', 'audio', 'tts', 'tts_video'],
  subs: ['srt', 'subtitle'],
} as const;

export function getAssetGroup(kind: string): 'media' | 'subs' {
  if (kind === 'srt' || kind === 'subtitle') return 'subs';
  return 'media';
}

export function isMediaFileAsset(kind: string): boolean {
  return getAssetGroup(kind) === 'media';
}
