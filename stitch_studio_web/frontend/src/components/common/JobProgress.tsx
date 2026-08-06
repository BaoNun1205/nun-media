import { AlertCircle, Check, LoaderCircle, PauseCircle } from 'lucide-react';
import type { Job } from '../../types/studio';

export function JobProgress({ job, compact = false }: { job: Job; compact?: boolean }) {
  const rawProgress = Number(job.progress || 0);
  const progress = Math.max(0, Math.min(100, rawProgress <= 1 ? rawProgress * 100 : rawProgress));
  const Icon = job.status === 'completed' ? Check
    : job.status === 'error' ? AlertCircle
    : job.status === 'cancelled' ? PauseCircle : LoaderCircle;
  return (
    <div className={`job-progress ${compact ? 'compact' : ''} ${job.status}`}>
      <div className="job-progress-title">
        <Icon size={14} className={job.status === 'running' ? 'spin' : ''} />
        <span>{job.detail || job.title}</span>
        <strong>{Math.round(progress)}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
    </div>
  );
}
