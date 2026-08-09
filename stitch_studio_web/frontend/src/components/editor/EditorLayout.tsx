import { useMemo, useState } from 'react';
import { AssetToolPanel } from './AssetToolPanel';
import { ContextInspector } from './ContextInspector';
import { EditorTopBar } from './EditorTopBar';
import { ExportVideoModal } from './ExportVideoModal';
import { Timeline } from './Timeline';
import { VideoPreview } from './VideoPreview';
import { useEditorController } from '../../hooks/useEditorController';
import type { Job, Project, VoiceOption } from '../../types/studio';

export function EditorLayout({ project, projects, jobs, voices, refresh, loadVoices, onBack, onOpenVersion }: {
  project: Project; projects: Project[]; jobs: Job[]; voices: VoiceOption[];
  refresh: () => Promise<void>; loadVoices: (engine?: string, language?: string) => Promise<VoiceOption[]>;
  onBack: () => void; onOpenVersion: (id: number) => void;
}) {
  const editor = useEditorController({ project, projects, jobs, voices, refresh, loadVoices, onOpenVersion });
  const [timelineHeight, setTimelineHeight] = useState(310);
  const [exportOpen, setExportOpen] = useState(false);
  const versions = useMemo(() => projects.filter((item) => item.projectId === project.projectId).sort((a, b) => b.id - a.id), [projects, project.projectId]);
  function resizeTimeline(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const update = (clientY: number) => setTimelineHeight(Math.max(210, Math.min(520, window.innerHeight - clientY)));
    update(event.clientY);
    const move = (next: PointerEvent) => update(next.clientY);
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  }
  return <div className="editor-layout" style={{ gridTemplateRows: `54px minmax(260px, 1fr) 5px ${timelineHeight}px` }}>
    <EditorTopBar editor={editor} versions={versions} onBack={onBack} onOpenVersion={onOpenVersion} onOpenExport={() => setExportOpen(true)} />
    {editor.message && <div className="editor-status-toast" role="status">{editor.message}</div>}
    <div className="editor-workspace">
      <AssetToolPanel editor={editor} onOpenExport={() => setExportOpen(true)} />
      <VideoPreview editor={editor} />
      <ContextInspector editor={editor} />
    </div>
    <div className="timeline-resizer" onPointerDown={resizeTimeline} />
    <Timeline editor={editor} />
    <ExportVideoModal editor={editor} open={exportOpen} onClose={() => setExportOpen(false)} />
  </div>;
}
