import type { CoreTimelineScene } from '../editor-core/types';
import type { Asset, AudioMode, Job, Project, SrtDocument, StudioSettings, SubtitleArea, Template, TemplateSummary, TemplateManifest, TimelineItem, TimelineState, VoiceOption, WorkspaceProject, YoutubeChannel, YoutubePrompt } from '../types/studio';

export const API_BASE = import.meta.env.VITE_API_URL || '/api';

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error(`Cannot reach the Stitch API at ${API_BASE}.`);
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const studioApi = {
  workspaceProjects: () => request<WorkspaceProject[]>('/projects'),
  createWorkspaceProject: (title: string, videoIds: number[]) =>
    request<{ project: WorkspaceProject }>('/projects', { method: 'POST', body: JSON.stringify({ title, videoIds }) }),
  renameWorkspaceProject: (id: number, title: string) =>
    request<{ project: WorkspaceProject }>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteWorkspaceProject: (id: number) => request<{ deleted: boolean; deletedFiles: number }>(`/projects/${id}`, { method: 'DELETE' }),
  revealProjectLibrary: () => request<{ status: string; path: string }>('/projects/reveal-library', { method: 'POST' }),
  attachWorkspaceVideos: (id: number, videoIds: number[]) =>
    request<{ project: WorkspaceProject }>(`/projects/${id}/videos`, { method: 'POST', body: JSON.stringify({ videoIds }) }),
  attachWorkspaceAssets: (id: number, assetIds: number[]) =>
    request<{ project: WorkspaceProject }>(`/projects/${id}/assets/attach`, { method: 'POST', body: JSON.stringify({ assetIds }) }),
  saveWorkspaceTimeline: (id: number, items: TimelineItem[], timelineState?: TimelineState, sceneState?: CoreTimelineScene) =>
    request<{ project: WorkspaceProject }>(`/projects/${id}/timeline`, { method: 'PUT', body: JSON.stringify({ items, timelineState, sceneState }) }),
  exportDefaults: (id: number) =>
    request<{ fileName: string; outputDirectory: string; resolution: string; aspectRatio: string; fps: number }>(`/projects/${id}/export/defaults`),
  selectExportFolder: (initialDirectory?: string) =>
    request<{ path: string }>('/projects/export/select-folder', { method: 'POST', body: JSON.stringify({ initialDirectory }) }),
  exportProject: (id: number, payload: { fileName: string; outputDirectory: string; resolution: string; aspectRatio: string; fps: number }) =>
    request<{ jobId: number; alreadyRunning?: boolean }>(`/projects/${id}/export`, { method: 'POST', body: JSON.stringify(payload) }),
  videoExportDefaults: (id: number) =>
    request<{ fileName: string; outputDirectory: string; resolution: string; aspectRatio: string; fps: number }>(`/videos/${id}/export/defaults`),
  exportVideo: (id: number, payload: { fileName: string; outputDirectory: string; resolution: string; aspectRatio: string; fps: number; timelineState?: TimelineState; sceneState?: CoreTimelineScene }) =>
    request<{ jobId: number; alreadyRunning?: boolean }>(`/videos/${id}/export`, { method: 'POST', body: JSON.stringify(payload) }),
  previewTemplate: (id: number) =>
    request<{ manifest: TemplateManifest }>(`/projects/${id}/template-preview`),
  saveTemplate: (id: number, payload: { name: string; manifest: TemplateManifest }) =>
    request<{ template: Template }>(`/projects/${id}/templates`, { method: 'POST', body: JSON.stringify(payload) }),
  templates: () => request<{ templates: TemplateSummary[] }>('/templates'),
  getTemplate: (id: number) => request<{ template: Template }>(`/templates/${id}`),
  deleteTemplate: (id: number) => request<{ success: boolean }>(`/templates/${id}`, { method: 'DELETE' }),
  revealPath: (path: string) => request<{ status: string; path: string }>('/files/reveal', { method: 'POST', body: JSON.stringify({ path }) }),
  uploadWorkspaceAsset: (id: number, file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<{ project: WorkspaceProject }>(`/projects/${id}/assets`, { method: 'POST', body });
  },
  projects: () => request<Project[]>('/videos'),
  jobs: () => request<Job[]>('/jobs'),
  settings: () => request<StudioSettings>('/settings'),
  saveSettings: (payload: { douyinCookie?: string; geminiApiKey?: string }) =>
    request<StudioSettings>('/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  renameProject: (id: number, title: string) =>
    request<Project>(`/videos/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteProject: (id: number) => request<{ deletedFiles: number }>(`/videos/${id}`, { method: 'DELETE' }),
  deleteAsset: (id: number) => request<{ deletedAssetIds: number[] }>(`/assets/${id}`, { method: 'DELETE' }),
  deleteProjectAsset: (id: number) => request<{ deletedProjectAssetId: number }>(`/project-assets/${id}`, { method: 'DELETE' }),
  saveClipSettings: (id: number, settings: Partial<NonNullable<Project['clipSettings']>>) =>
    request<{ clipSettings: Project['clipSettings'] }>(`/videos/${id}/clip-settings`, { method: 'PUT', body: JSON.stringify(settings) }),
  saveSubtitleArea: (id: number, area: SubtitleArea, options?: { blurEffectArea?: SubtitleArea; style?: any }) =>
    request<{ subtitleArea: SubtitleArea; subtitleBlurEffect?: Project['subtitleBlurEffect'] | null; subtitleStyle?: any }>(
      `/videos/${id}/subtitle-settings`,
      { method: 'PUT', body: JSON.stringify({ area, ...options }) },
    ),
  saveWorkspaceSubtitleArea: (projectId: number, area: SubtitleArea, options?: { style?: any }) =>
    request<{ subtitleArea: SubtitleArea; subtitleStyle?: any }>(
      `/projects/${projectId}/subtitle-settings`,
      { method: 'PUT', body: JSON.stringify({ area, ...options }) },
    ),
  revealProject: (id: number) => request(`/videos/${id}/reveal`, { method: 'POST' }),
  setAudioMode: (id: number, mode: AudioMode) =>
    request<{ mode: AudioMode; ready: boolean; jobId?: number; alreadyRunning?: boolean; reused?: boolean }>(
      `/videos/${id}/audio-mode`,
      { method: 'POST', body: JSON.stringify({ mode }) },
    ),
  extractAudio: (id: number) =>
    request<{ asset: Asset; reused?: boolean }>(`/videos/${id}/audio/extract`, { method: 'POST' }),
  srt: (videoId: number) => request<SrtDocument>(`/videos/${videoId}/srt/latest`),
  srtAsset: (assetId: number) => request<SrtDocument>(`/assets/${assetId}/srt`),
  saveSrtAsset: (assetId: number, content: string) =>
    request(`/assets/${assetId}/srt`, { method: 'PUT', body: JSON.stringify({ content }) }),
  voices: async (engine = 'vieneu', language = 'vi-VN') => {
    const data = await request<{ voices: Array<string | VoiceOption> }>(`/voices?${new URLSearchParams({ engine, language })}`);
    return (data.voices || []).map((voice) => typeof voice === 'string' ? { id: voice, label: voice } : voice);
  },
  importVideo: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<{ video: Project }>('/import/video', { method: 'POST', body });
  },
  importSrt: (videoId: number, file: File, replaceAssetId?: number) => {
    const body = new FormData();
    body.append('file', file);
    if (replaceAssetId) body.append('replaceAssetId', String(replaceAssetId));
    return request<{ asset: unknown }>(`/videos/${videoId}/srt/import`, { method: 'POST', body });
  },
  youtube: {
    channels: () => request<YoutubeChannel[]>('/youtube/channels'),
    createChannel: (name: string, file?: File) => {
      const body = new FormData();
      body.append('name', name);
      if (file) body.append('avatar', file);
      return request<YoutubeChannel>('/youtube/channels', { method: 'POST', body });
    },
    updateChannel: (channelId: number, name?: string, references_json?: string) => 
      request<YoutubeChannel>(`/youtube/channels/${channelId}`, {
        method: 'PUT',
        body: JSON.stringify({ name, references_json })
      }),
    deleteChannel: (id: number) => request<{ deleted: boolean }>(`/youtube/channels/${id}`, { method: 'DELETE' }),
    prompts: (channelId: number) => request<YoutubePrompt[]>(`/youtube/channels/${channelId}/prompts`),
    createPrompt: (channelId: number, name: string, content: string) =>
      request<YoutubePrompt>(`/youtube/channels/${channelId}/prompts`, {
        method: 'POST',
        body: JSON.stringify({ name, content }),
      }),
    updatePrompt: (promptId: number, name: string, content: string) =>
      request<YoutubePrompt>(`/youtube/prompts/${promptId}`, {
        method: 'PUT',
        body: JSON.stringify({ name, content }),
      }),
    deletePrompt: (promptId: number) => request<{ deleted: boolean }>(`/youtube/prompts/${promptId}`, { method: 'DELETE' }),
  },
  applyTemplate: (projectId: number, templateId: number, slotMap: Record<string, number>) =>
    request<{ success: boolean; needsSrt: boolean }>(`/projects/${projectId}/templates/${templateId}/apply`, {
      method: 'POST',
      body: JSON.stringify({ slotMap })
    }),
  instantiateTemplate: (templateId: number, payload: FormData) =>
    request<{ project: WorkspaceProject; srtJobId: number | null }>(`/templates/${templateId}/instantiate`, {
      method: 'POST',
      body: payload
    }),
};

export async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}
