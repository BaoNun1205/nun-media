import { useMemo, useState } from 'react';
import { AppSidebar } from './components/layout/AppSidebar';
import { EditorLayout } from './components/editor/EditorLayout';
import { useStudioData } from './hooks/useStudioData';
import { DownloadsPage } from './pages/DownloadsPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { SettingsPage } from './pages/SettingsPage';
import { StandaloneTTSPage } from './pages/StandaloneTTSPage';
import type { Project, ViewKey, WorkspaceProject } from './types/studio';

function emptyWorkspaceProject(workspace: WorkspaceProject): Project {
  return {
    id: -workspace.id,
    title: workspace.title,
    source: 'workspace',
    path: '',
    name: workspace.title,
    mediaType: 'workspace',
    durationMs: 0,
    sizeBytes: workspace.sizeBytes,
    status: 'empty',
    createdAt: workspace.createdAt,
    assets: [],
    hasSrt: false,
    hasTranslatedSrt: false,
    hasTts: false,
    projectId: workspace.projectId,
    workspaceId: workspace.id,
    workspaceTitle: workspace.title,
    projectAssets: workspace.assets,
    workspaceTimeline: workspace.timeline || [],
    timelineState: workspace.timelineState,
    sceneState: workspace.sceneState,
    processingState: {
      srtGenerated: false,
      srtTranslated: false,
      voiceoverGenerated: false,
      subtitleHidden: false,
      subtitleInserted: false,
    },
  };
}

export default function App() {
  const studio = useStudioData();
  const [view, setView] = useState<ViewKey>(() => {
    const requested = new URLSearchParams(window.location.search).get('view') as ViewKey | null;
    return requested && ['projects', 'downloads', 'tts', 'settings', 'editor'].includes(requested) ? requested : 'projects';
  });
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<number | null>(null);
  const activeJobs = studio.jobs.filter((job) => ['queued', 'running'].includes(job.status)).length;
  const selectedWorkspace = useMemo(
    () => selectedWorkspaceId ? studio.workspaceProjects.find((project) => project.id === selectedWorkspaceId) ?? null : null,
    [selectedWorkspaceId, studio.workspaceProjects],
  );
  const editorProject = selectedWorkspace
    ? selectedWorkspace.primaryVideoId
      ? {
          ...(studio.projects.find((project) => project.id === selectedWorkspace.primaryVideoId) ?? selectedWorkspace.primaryVideo ?? emptyWorkspaceProject(selectedWorkspace)),
          workspaceId: selectedWorkspace.id,
          workspaceTitle: selectedWorkspace.title,
          projectAssets: selectedWorkspace.assets,
          workspaceTimeline: selectedWorkspace.timeline || [],
          timelineState: selectedWorkspace.timelineState,
          sceneState: selectedWorkspace.sceneState,
        }
      : emptyWorkspaceProject(selectedWorkspace)
    : studio.selectedProject;

  function openEditor(id: number) {
    setSelectedWorkspaceId(null);
    studio.setSelectedId(id);
    setView('editor');
  }

  function openWorkspaceEditor(project: WorkspaceProject) {
    setSelectedWorkspaceId(project.id);
    if (project.primaryVideoId) studio.setSelectedId(project.primaryVideoId);
    setView('editor');
  }

  if (view === 'editor' && editorProject) {
    return <EditorLayout
      project={editorProject}
      projects={studio.projects}
      jobs={studio.jobs}
      voices={studio.voices}
      refresh={studio.refresh}
      loadVoices={studio.loadVoices}
      onBack={() => setView('projects')}
      onOpenVersion={openEditor}
    />;
  }

  return <div className="app-shell">
    <AppSidebar view={view} onNavigate={setView} activeJobs={activeJobs} />
    <main className="app-content">
      {studio.error && <div className="connection-banner">{studio.error}</div>}
      {view === 'projects' && <ProjectsPage projects={studio.workspaceProjects} onOpen={openWorkspaceEditor} onRefresh={studio.refresh} />}
      {view === 'downloads' && <DownloadsPage jobs={studio.jobs} projects={studio.projects} workspaceProjects={studio.workspaceProjects} onRefresh={studio.refresh} onOpenEditor={openEditor} onOpenWorkspace={openWorkspaceEditor} />}
      {view === 'tts' && <StandaloneTTSPage jobs={studio.jobs} workspaceProjects={studio.workspaceProjects} voices={studio.voices} loadVoices={studio.loadVoices} refresh={studio.refresh} />}
      {view === 'settings' && <SettingsPage />}
    </main>
  </div>;
}
