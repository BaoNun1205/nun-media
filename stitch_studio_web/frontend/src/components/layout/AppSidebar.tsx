import { Download, FolderKanban, LayoutTemplate, Settings, Sparkles, Volume2, Youtube } from 'lucide-react';
import type { ViewKey } from '../../types/studio';

interface Props {
  view: ViewKey;
  onNavigate: (view: ViewKey) => void;
  activeJobs: number;
}

export function AppSidebar({ view, onNavigate, activeJobs }: Props) {
  const items = [
    ['projects', FolderKanban, 'Projects'],
    ['templates', LayoutTemplate, 'Templates'],
    ['downloads', Download, 'Downloads'],
    ['tts', Volume2, 'Text to Speech'],
    ['youtube', Youtube, 'Youtube'],
    ['settings', Settings, 'Settings'],
  ] as const;
  return (
    <aside className="app-sidebar">
      <button className="studio-brand" onClick={() => onNavigate('projects')}>
        <span className="brand-mark"><Sparkles size={17} /></span>
        <span><strong>Nun Studio</strong><small>AI video editor</small></span>
      </button>
      <nav aria-label="Primary navigation">
        {items.map(([key, Icon, label]) => (
          <button
            key={key}
            className={view === key ? 'active' : ''}
            onClick={() => onNavigate(key)}
            aria-current={view === key ? 'page' : undefined}
          >
            <Icon size={18} /><span>{label}</span>
            {key === 'downloads' && activeJobs > 0 && <em>{activeJobs}</em>}
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span className="online-dot" /> Backend connected
        <small>Desktop workspace</small>
      </div>
    </aside>
  );
}
