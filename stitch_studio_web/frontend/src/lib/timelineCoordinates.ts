/**
 * Unified timeline coordinate system.
 *
 * Everything on the timeline (clips, playhead, ruler, snap guides, marquee,
 * ghost previews) operates on a single conversion metric: pixelsPerSecond.
 *
 * x = timeSeconds * pixelsPerSecond
 * width = durationSeconds * pixelsPerSecond
 */

// At the lowest zoom the full timeline should fit the viewport even for a
// long-form project. 2 px/s still makes a 30+ minute edit several screens
// wide, so permit a true overview scale.
export const MIN_PIXELS_PER_SECOND = 0.1;
export const MAX_PIXELS_PER_SECOND = 120;
export const DEFAULT_PIXELS_PER_SECOND = 20;

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return DEFAULT_PIXELS_PER_SECOND;
  return Math.max(MIN_PIXELS_PER_SECOND, Math.min(MAX_PIXELS_PER_SECOND, Math.round(zoom * 10) / 10));
}

export function timeToPx(seconds: number, pixelsPerSecond: number): number {
  return Math.max(0, seconds) * Math.max(MIN_PIXELS_PER_SECOND, pixelsPerSecond);
}

export function pxToTime(px: number, pixelsPerSecond: number): number {
  return Math.max(0, px) / Math.max(MIN_PIXELS_PER_SECOND, pixelsPerSecond);
}

export function durationToPx(duration: number, pixelsPerSecond: number): number {
  return Math.max(0, duration) * Math.max(MIN_PIXELS_PER_SECOND, pixelsPerSecond);
}

const CANDIDATE_INTERVALS = [
  0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600,
];

/**
 * Choose a ruler interval where major ticks are spaced roughly 60px to 140px apart.
 */
export function getRulerTickInterval(pixelsPerSecond: number): number {
  const pps = Math.max(MIN_PIXELS_PER_SECOND, pixelsPerSecond);
  for (const interval of CANDIDATE_INTERVALS) {
    if (interval * pps >= 55) {
      return interval;
    }
  }
  return 3600;
}

export interface RulerTick {
  time: number;
  label: string;
  isMajor: boolean;
}

export function generateRulerTicks(totalDuration: number, pixelsPerSecond: number): RulerTick[] {
  const pps = Math.max(MIN_PIXELS_PER_SECOND, pixelsPerSecond);
  const majorInterval = getRulerTickInterval(pps);
  const duration = Math.max(0, totalDuration);
  const count = Math.ceil(duration / majorInterval) + 1;
  const ticks: RulerTick[] = [];

  for (let i = 0; i <= count; i++) {
    const time = Math.round(i * majorInterval * 1000) / 1000;
    ticks.push({
      time,
      label: formatRulerTime(time),
      isMajor: true,
    });
  }
  return ticks;
}

export function formatRulerTime(seconds: number): string {
  const safeSeconds = Math.max(0, seconds);
  const totalMs = Math.round(safeSeconds * 1000);
  const mins = Math.floor(totalMs / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;

  if (ms > 0) {
    return `${mins}:${String(secs).padStart(2, '0')}.${Math.floor(ms / 100)}`;
  }
  if (mins > 0) {
    return `${mins}:${String(secs).padStart(2, '0')}`;
  }
  return `${secs}s`;
}
