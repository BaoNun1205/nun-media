import { useCallback, useEffect, useMemo, useState } from 'react';
import { studioApi } from '../services/api';
import type { Job, Project, VoiceOption, WorkspaceProject } from '../types/studio';

export function useStudioData() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaceProjects, setWorkspaceProjects] = useState<WorkspaceProject[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([{ id: 'default', label: 'Default' }]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [nextProjects, nextWorkspaceProjects, nextJobs] = await Promise.all([studioApi.projects(), studioApi.workspaceProjects(), studioApi.jobs()]);
      setProjects(nextProjects);
      setWorkspaceProjects(nextWorkspaceProjects);
      setJobs(nextJobs);
      setSelectedId((current) =>
        current && nextProjects.some((project) => project.id === current) ? current : nextProjects[0]?.id ?? null,
      );
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load Studio data');
    }
  }, []);

  const loadVoices = useCallback(async (engine = 'vieneu', language = 'vi-VN') => {
    const next = await studioApi.voices(engine, language);
    setVoices(next.length ? next : [{ id: 'default', label: 'Default' }]);
    return next;
  }, []);

  useEffect(() => {
    refresh();
    loadVoices().catch(() => undefined);
    const timer = window.setInterval(refresh, 1800);
    return () => window.clearInterval(timer);
  }, [refresh, loadVoices]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedId) ?? projects[0] ?? null,
    [projects, selectedId],
  );

  return { projects, workspaceProjects, jobs, voices, selectedId, setSelectedId, selectedProject, refresh, loadVoices, error };
}
