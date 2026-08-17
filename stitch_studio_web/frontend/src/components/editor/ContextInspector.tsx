import { useMemo, useRef, useState, type ReactNode } from 'react';
import { AlignCenter, AlignLeft, AlignRight, Bold, Copy, Download, FolderOpen, Gauge, Image as ImageIcon, Info, Italic, Languages, MoveHorizontal, Play, RotateCcw, Save, SkipBack, SkipForward, Trash2, Underline, Volume2, VolumeX, WandSparkles } from 'lucide-react';
import { formatClock, formatDuration, formatSize } from '../../lib/studio';
import { API_BASE, copyText, studioApi } from '../../services/api';
import { DEFAULT_FONT_FAMILY, FONT_CATEGORIES, FONT_REGISTRY, fontByFamily, fontStack } from '../../config/fontRegistry';
import { TextStylePresetGrid } from './text-style/TextStylePresetGrid';
import { NumericField as NumericControl, SliderNumericField } from './NumericField';
import { ImageAnimationControls } from './ImageAnimationControls';
import type { EditorController } from '../../hooks/useEditorController';
import type { SubtitleStyle, TimelineItem } from '../../types/studio';

export function ContextInspector({ editor }: { editor: EditorController }) {
  return <aside className="context-inspector">
    <header><span>{inspectorTitle(editor)}</span><small>{selectionName(editor)}</small></header>
    <div className="inspector-body">{editor.activeTool === 'voiceover' ? <VoiceLinesInspector editor={editor} />
      : editor.selection.type === 'subtitle' && editor.currentSegment ? <SubtitleInspector editor={editor} />
      : editor.selection.type === 'voice' && editor.currentVoice ? <VoiceInspector editor={editor} />
      : editor.selection.type === 'timeline-items' && isMergedVoiceSelection(editor) ? <VoiceoverInspector editor={editor} />
      : editor.selection.type === 'timeline-items' && editor.selectedTimelineAudioItem ? <AudioClipInspector editor={editor} item={editor.selectedTimelineAudioItem} />
      : editor.selection.type === 'timeline-items' && editor.selectedTimelineImageItem ? <ImageClipInspector editor={editor} item={editor.selectedTimelineImageItem} />
      : editor.selection.type === 'timeline-items' ? <MultiSelectionInspector editor={editor} />
      : editor.selection.type === 'video' ? <VideoInspectorControls editor={editor} />
      : editor.selection.type === 'subtitle-track' ? <TrackInspector editor={editor} />
      : editor.selection.type === 'effect' ? <EffectInspector editor={editor} />
      : editor.selection.type === 'asset' ? <AssetInspector editor={editor} />
      : <ProjectInspector editor={editor} />}</div>
  </aside>;
}

function inspectorTitle(editor: EditorController) {
  if (editor.activeTool === 'voiceover') return 'Voice review';
  return 'Properties';
}

function selectionName(editor: EditorController) {
  const value = editor.selection;
  if (editor.activeTool === 'voiceover') return 'Voice lines';
  if (isMergedVoiceSelection(editor)) return 'Voiceover';
  if (value.type === 'subtitle') return `Subtitle #${value.index}`;
  if (value.type === 'voice') return `Voice #${value.index}`;
  if (value.type === 'subtitle-track') return 'Subtitle track';
  if (value.type === 'timeline-items') return value.track ? `${value.track} track` : `${value.keys.length} selected`;
  if (value.type === 'effect') return value.operation === 'blur' ? 'Blur effect' : 'Rendered operation';
  return value.type === 'project' ? 'Project' : value.type;
}

function isMergedVoiceSelection(editor: EditorController) {
  return editor.selection.type === 'timeline-items' && editor.selection.keys.length === 1 && editor.selection.keys[0] === 'voice:merged';
}

function MultiSelectionInspector({ editor }: { editor: EditorController }) {
  const selection = editor.selection.type === 'timeline-items' ? editor.selection : { keys: [], track: undefined };
  const subtitleKeys = selection.keys.filter((key) => key.startsWith('subtitle:') || key.startsWith('subtitle-translated:'));
  const subtitles = new Set(subtitleKeys.map((key) => Number(key.split(':')[1])).filter(Number.isFinite)).size;
  const hasSrtClip = selection.keys.some((key) => editor.timelineItems.some((item) => item.id === key && item.kind === 'srt'));
  const hasTextClip = editor.selectedTextItems.length > 0;
  const voices = selection.keys.filter((key) => key.startsWith('voice:')).length;
  const heading = selection.track ? selection.track + ' selected' : selection.keys.length + ' items selected';
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{heading}</h2><p>{selection.track ? 'Entire timeline track' : 'Marquee selection'}</p></div></div><Section title="Selection"><Field label="Total items" value={selection.keys.length} />{subtitles > 0 && <Field label="Subtitles" value={subtitles} />}{hasTextClip && <Field label="Text clips" value={editor.selectedTextItems.length} />}{voices > 0 && <Field label="Voice clips" value={voices} />}</Section>{(subtitles > 0 || hasSrtClip || selection.track === 'S1') && <SubtitleStyleControls editor={editor} />}{hasTextClip && <TimelineTextStyleControls editor={editor} />}{subtitles > 0 && <><Section title="Position on preview"><p className="inspector-help">Drag the subtitle text up or down directly in the video preview. When it reaches the center, a cyan guide appears and snaps it into place.</p></Section><button className="danger full" onClick={() => editor.deleteSelectedSubtitles()}><Trash2 size={14} /> Delete selected subtitles</button></>}<p className="inspector-help">Drag on an empty timeline area to replace this selection. Hold Ctrl, Cmd, or Shift while clicking clips to add or remove individual items. Use Delete or Backspace to remove selected subtitles.</p>{selection.track === 'S1' && <div className="inspector-buttons column"><button onClick={editor.copySrt}><Copy size={14} /> Copy full SRT</button><button onClick={editor.replaceWithTranslated} disabled={!editor.hasLoadedTranslation} title={editor.hasLoadedTranslation ? 'Replace the active draft text with the translated SRT' : 'Waiting for translated SRT to load'}><Languages size={14} /> Replace with translated SRT</button></div>}</>;
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="inspector-section"><h3>{title}</h3>{children}</section>;
}
function Field({ label, value }: { label: string; value: ReactNode }) {
  return <div className="inspector-field"><span>{label}</span><strong>{value}</strong></div>;
}

function ProjectInspector({ editor }: { editor: EditorController }) {
  const p = editor.project;
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{p.title}</h2><p>Project {p.projectId}</p></div></div><Section title="Project"><Field label="Original file" value={p.name} /><Field label="Duration" value={formatDuration(p.durationMs)} /><Field label="Media" value={p.mediaType || 'Video'} /><Field label="Current version" value={`#${p.id}`} /><Field label="Assets" value={p.assets.length} /><Field label="Size" value={formatSize(p.sizeBytes)} /></Section><Section title="Pipeline"><div className="inspector-status-list"><span className={p.hasSrt ? 'ready' : ''}>SRT {p.hasSrt ? 'Ready' : 'Missing'}</span><span className={p.hasTranslatedSrt ? 'ready' : ''}>Translation {p.hasTranslatedSrt ? 'Ready' : 'Missing'}</span><span className={p.hasTts ? 'ready' : ''}>Voiceover {p.hasTts ? 'Ready' : 'Missing'}</span></div></Section>{editor.jobs[0] && <Section title="Latest job"><Field label={editor.jobs[0].kind} value={editor.jobs[0].status} /></Section>}</>;
}

function VideoInspector({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Play size={18} /></span><div><h2>{editor.project.title}</h2><p>Main video clip</p></div></div><Section title="Timing"><Field label="Timeline start" value="00:00:00" /><Field label="Source in" value="00:00:00" /><Field label="Source out" value={formatClock(editor.duration)} /><Field label="Duration" value={formatClock(editor.duration)} /></Section><Section title="Preview speed"><label className="stack-label">Playback speed<select value={editor.playbackRate} onChange={(event) => editor.setPlaybackRate(Number(event.target.value))}><option value=".5">0.5×</option><option value=".75">0.75×</option><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><span className="pending-label"><Gauge size={12} /> Preview only · export retiming unavailable</span></Section><Section title="Preview audio"><label className="stack-label">Volume<SliderNumericField value={editor.previewVolume} min={0} max={1} step={0.05} precision={2} onChange={editor.setPreviewVolume} ariaLabel="Preview volume" /></label><label className="check-line"><input type="checkbox" checked={editor.previewMuted} onChange={(event) => editor.setPreviewMuted(event.target.checked)} /> Mute source audio</label></Section><button className="full" onClick={() => studioApi.revealProject(editor.project.id)}><FolderOpen size={15} /> Reveal source file</button></>;
}

function VideoInspectorControls({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Play size={18} /></span><div><h2>{editor.project.title}</h2><p>Main video clip</p></div></div><Section title="Tỉ lệ"><ClipRangeControl value={editor.videoScale} min={.1} max={5} step={.01} suffix="×" onChange={editor.updateVideoScale} /></Section><Section title="Âm thanh"><DbControl value={editor.videoVolumeDb} onChange={editor.updateVideoVolumeDb} /></Section><Section title="Tốc độ"><ClipRangeControl value={editor.videoSpeed} min={.1} max={80} step={.1} suffix="×" onChange={editor.updateVideoSpeed} /></Section><Section title="Timing"><Field label="Timeline start" value="00:00:00" /><Field label="Duration" value={formatClock(editor.duration)} /></Section><button className="full" onClick={() => studioApi.revealProject(editor.project.id)}><FolderOpen size={15} /> Reveal source file</button></>;
}

function VoiceoverInspector({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Volume2 size={18} /></span><div><h2>Voiceover</h2><p>Merged clip on A2</p></div></div><Section title="Âm thanh"><DbControl value={editor.voiceVolumeDb} onChange={editor.updateVoiceVolumeDb} /></Section><Section title="Tốc độ"><ClipRangeControl value={editor.voiceSpeed} min={.1} max={80} step={.1} suffix="×" onChange={editor.updateVoiceSpeed} /></Section><p className="inspector-help">The voice settings are saved with this video version and apply in the preview.</p></>;
}

function VoiceLinesInspector({ editor }: { editor: EditorController }) {
  const manualSpeedLimit = 3;
  const issueByIndex = new Map(editor.timelineIssues.map((issue) => [issue.index, issue]));
  const busy = editor.activeJobs.some((job) => ['tts', 'tts-segment', 'tts-mux'].includes(job.kind));
  const [speedByIndex, setSpeedByIndex] = useState<Record<number, number>>({});
  const [pendingSpeedIndex, setPendingSpeedIndex] = useState<number | null>(null);
  const speedValueForLine = (index: number, appliedSpeed?: number, physicalSpeed?: number, issueSpeed?: number) => {
    const stored = speedByIndex[index];
    if (Number.isFinite(stored) && stored > 0) return stored;
    const source = appliedSpeed && appliedSpeed > 0 ? appliedSpeed : physicalSpeed && physicalSpeed > 1 ? physicalSpeed : issueSpeed && issueSpeed > 1 ? issueSpeed : 1.0;
    return Number(source.toFixed(2));
  };
  const applyVoiceSpeed = async (index: number, targetSpeed: number, currentAppliedSpeed: number) => {
    const target = Number(targetSpeed.toFixed(2));
    const current = Math.max(1, currentAppliedSpeed);
    if (pendingSpeedIndex !== null || !Number.isFinite(target)) return;
    if (target <= current + 0.0005) {
      setSpeedByIndex((values) => {
        const next = { ...values };
        delete next[index];
        return next;
      });
      return;
    }
    setPendingSpeedIndex(index);
    try {
      await editor.speedUpVoice(index, target / current, target);
    } finally {
      setPendingSpeedIndex((value) => value === index ? null : value);
      setSpeedByIndex((values) => {
        const next = { ...values };
        delete next[index];
        return next;
      });
    }
  };
  const readyCount = editor.voiceSegments.filter((voice) => voice.audioUrl).length;
  const activeIssueCount = editor.srt.segments.filter((segment) => {
    const issue = issueByIndex.get(segment.index);
    const currentText = editor.edits[segment.index] ?? segment.text;
    return Boolean(issue && currentText.trim() === issue.text.trim());
  }).length;
  return <>
    <div className="inspector-hero"><span><Volume2 size={18} /></span><div><h2>Voice lines</h2><p>{readyCount}/{editor.srt.segments.length} ready{activeIssueCount ? ` - ${activeIssueCount} needs review` : ''}</p></div></div>
    {editor.dirty && <button className="full" disabled={busy} onClick={editor.saveSrt}><Save size={14} /> Save subtitle edits</button>}
    <Section title="Subtitle Lines">
      <div className="voice-line-list">
        {editor.srt.segments.map((segment) => {
          const currentText = editor.edits[segment.index] ?? segment.text;
          const voice = editor.voiceByIndex[segment.index];
          const issue = issueByIndex.get(segment.index);
          const activeIssue = issue && currentText.trim() === issue.text.trim()
            ? issue
            : voice?.timingStatus === 'TEXT_TOO_LONG'
              ? {
                  index: segment.index,
                  status: 'TEXT_TOO_LONG',
                  text: currentText,
                  startLabel: segment.startLabel,
                  endLabel: segment.endLabel,
                  ttsDuration: voice.duration,
                  availableDuration: voice.availableDuration || voice.subtitleDuration,
                  requiredLocalSpeed: voice.requiredLocalSpeed,
                  needsReview: true,
                }
              : undefined;
          const currentAppliedSpeed = voice?.appliedLocalSpeed || voice?.speedMultiplier || 1;
          const minSpeed = Number(Math.max(1, currentAppliedSpeed).toFixed(2));
          const maxSpeed = Math.max(manualSpeedLimit, minSpeed);
          const speed = Math.min(maxSpeed, Math.max(minSpeed, speedValueForLine(segment.index, voice?.appliedLocalSpeed, voice?.speedMultiplier, activeIssue?.requiredLocalSpeed || voice?.requiredLocalSpeed)));
          const ready = Boolean(voice?.audioUrl && !activeIssue);
          const timing = activeIssue
            ? [
                activeIssue.ttsDuration ? `${activeIssue.ttsDuration.toFixed(2)}s voice` : '',
                activeIssue.availableDuration ? `${activeIssue.availableDuration.toFixed(2)}s slot` : '',
                activeIssue.requiredLocalSpeed ? `${activeIssue.requiredLocalSpeed.toFixed(2)}x` : '',
              ].filter(Boolean).join(' - ')
            : voice?.duration && voice.subtitleDuration ? `${voice.duration.toFixed(2)}s voice - ${voice.subtitleDuration.toFixed(2)}s slot` : '';
          return <div className={`voice-line-row ${activeIssue ? 'needs-review' : ready ? 'ready' : ''}`} key={segment.index}>
            <div className="voice-line-meta">
              <strong>#{segment.index} {segment.startLabel} - {segment.endLabel}</strong>
              <span>{voice?.appliedLocalSpeed && voice.appliedLocalSpeed > 1 ? `${voice.appliedLocalSpeed.toFixed(2)}x applied` : voice?.speedMultiplier && voice.speedMultiplier > 1 ? `${voice.speedMultiplier.toFixed(2)}x applied` : timing}</span>
            </div>
            <textarea value={currentText} onChange={(event) => editor.setEdits({ ...editor.edits, [segment.index]: event.target.value })} />
            <div className="voice-line-status">
              <span className={activeIssue ? 'error' : ready ? 'ready' : ''}>{activeIssue ? 'Too long' : ready ? 'Ready' : 'Not rendered'}</span>
              {timing && <small>{timing}</small>}
            </div>
            <div className="voice-line-actions">
              <NumericControl
                ariaLabel={`Voice speed for line ${segment.index}`}
                className="voice-speed-stepper"
                compact
                disabled={busy || pendingSpeedIndex !== null || !voice?.audioUrl}
                max={maxSpeed}
                min={minSpeed}
                onChange={(value) => setSpeedByIndex((current) => ({ ...current, [segment.index]: value }))}
                onCommit={(value) => void applyVoiceSpeed(segment.index, value, currentAppliedSpeed)}
                precision={2}
                step={0.01}
                unit="x"
                value={speed}
              />
              <button title="Play voice line" disabled={!voice?.audioUrl} onClick={() => editor.playVoice(voice)}><Play size={13} /></button>
              <button title="Tạo voice" disabled={busy} onClick={() => editor.generateVoice(segment.index)}><WandSparkles size={13} /> Tạo voice</button>
              <button title="Dịch lại" disabled={busy || !editor.originalSrtAssets.length} onClick={() => { editor.openTool('translate'); void editor.translate(); }}><Languages size={13} /> Dịch lại</button>
            </div>
          </div>;
        })}
        {!editor.srt.segments.length && <p className="inspector-help">Select or generate an SRT before creating voice lines.</p>}
      </div>
    </Section>
  </>;
}

function AudioClipInspector({ editor, item }: { editor: EditorController; item: TimelineItem }) {
  const commit = useTimelineItemDraft(editor, 'Updated audio clip settings.');
  const fadeIn = audioFadeValue(item, 'audioFadeIn');
  const fadeOut = audioFadeValue(item, 'audioFadeOut');
  const duration = Math.max(0.1, item.duration || 0.1);
  const update = (updates: { volumeDb?: number; audioFadeIn?: number; audioFadeOut?: number }, finish = false) => {
    const nextFadeIn = updates.audioFadeIn === undefined ? fadeIn : clampNumber(updates.audioFadeIn, 0, Math.max(0, duration - (updates.audioFadeOut ?? fadeOut)));
    const nextFadeOut = updates.audioFadeOut === undefined ? fadeOut : clampNumber(updates.audioFadeOut, 0, Math.max(0, duration - nextFadeIn));
    commit.update(item.id, (clip) => ({
      ...clip,
      volumeDb: updates.volumeDb === undefined ? item.volumeDb ?? 0 : clampNumber(updates.volumeDb, -60, 20),
      params: {
        ...(clip.params || {}),
        audioFadeIn: nextFadeIn,
        audioFadeOut: nextFadeOut,
      },
    }), finish);
  };
  return <>
    <div className="inspector-hero"><span><Volume2 size={18} /></span><div><h2>{item.name}</h2><p>{item.track || 'Audio'} clip</p></div></div>
    <Section title="Basic">
      <InspectorRangeField label="Volume" value={item.volumeDb ?? 0} min={-60} max={20} step={0.1} suffix="dB" mutedAtMin onChange={(value, finish) => update({ volumeDb: value }, finish)} />
      <InspectorRangeField label="Fade In" value={fadeIn} min={0} max={Math.max(0, duration - fadeOut)} step={0.1} suffix="s" onChange={(value, finish) => update({ audioFadeIn: value }, finish)} />
      <InspectorRangeField label="Fade Out" value={fadeOut} min={0} max={Math.max(0, duration - fadeIn)} step={0.1} suffix="s" onChange={(value, finish) => update({ audioFadeOut: value }, finish)} />
      <button className="inspector-reset-button" type="button" onClick={() => update({ volumeDb: 0, audioFadeIn: 0, audioFadeOut: 0 }, true)}><RotateCcw size={14} /> Reset</button>
    </Section>
  </>;
}

function ImageClipInspector({ editor, item }: { editor: EditorController; item: TimelineItem }) {
  const commit = useTimelineItemDraft(editor, 'Updated image transform.');
  const transform = imageTransformValue(item);
  const update = (updates: Partial<{ scale: number; x: number; y: number }>, finish = false) => {
    const nextTransform = {
      scale: clampNumber(updates.scale ?? transform.scale, 0.1, 5),
      x: clampNumber(updates.x ?? transform.x, 0, 1),
      y: clampNumber(updates.y ?? transform.y, 0, 1),
    };
    commit.update(item.id, (clip) => ({
      ...clip,
      params: {
        ...(clip.params || {}),
        imageTransform: nextTransform,
      },
    }), finish);
  };
  return <>
    <div className="inspector-hero"><span><ImageIcon size={18} /></span><div><h2>{item.name}</h2><p>{item.track || 'Image'} clip</p></div></div>
    
    <Section title="Transform">
      <InspectorRangeField label="Scale" value={Math.round(transform.scale * 100)} min={10} max={500} step={1} suffix="%" onChange={(value, finish) => update({ scale: value / 100 }, finish)} />
      <InspectorRangeField label="Position X" value={Math.round(transform.x * 100)} min={0} max={100} step={1} suffix="%" onChange={(value, finish) => update({ x: value / 100 }, finish)} />
      <InspectorRangeField label="Position Y" value={Math.round(transform.y * 100)} min={0} max={100} step={1} suffix="%" onChange={(value, finish) => update({ y: value / 100 }, finish)} />
      <button className="inspector-reset-button" type="button" onClick={() => update({ scale: 1, x: 0.5, y: 0.5 }, true)}><RotateCcw size={14} /> Reset Transform</button>
    </Section>

    <Section title="Animation">
      <ImageAnimationControls editor={editor} item={item} />
    </Section>
  </>;
}

export function useTimelineItemDraft(editor: EditorController, message: string) {
  const previousRef = useRef<TimelineItem[] | null>(null);
  const latestRef = useRef<TimelineItem[] | null>(null);
  const cloneItems = (items: TimelineItem[]) => items.map((clip) => ({ ...clip, params: clip.params ? { ...clip.params } : undefined }));
  const finish = () => {
    const previous = previousRef.current;
    const latest = latestRef.current;
    if (!previous || !latest) return;
    previousRef.current = null;
    latestRef.current = null;
    void editor.commitTimelineItems(latest, message, previous);
  };
  return {
    update(id: string, updater: (item: TimelineItem) => TimelineItem, shouldFinish = false) {
      if (!previousRef.current) previousRef.current = cloneItems(editor.timelineItems);
      const next = editor.timelineItems.map((clip) => clip.id === id ? updater(clip) : clip);
      latestRef.current = next;
      editor.previewTimelineItems(next);
      if (shouldFinish) finish();
    },
  };
}

export function InspectorRangeField({ label, value, min, max, step, suffix, mutedAtMin, onChange }: { label: string; value: number; min: number; max: number; step: number; suffix: string; mutedAtMin?: boolean; onChange: (value: number, finish: boolean) => void }) {
  const normalized = clampNumber(value, min, max);
  const muted = Boolean(mutedAtMin && normalized <= min);
  return (
    <FieldRow label={label}>
      <SliderNumericField
        className={`style-range-field inspector-range-field ${muted ? 'is-muted' : ''}`}
        value={normalized}
        min={min}
        max={max}
        step={step}
        unit={suffix}
        prefix={muted ? <VolumeX size={13} /> : undefined}
        onChange={(nextValue) => onChange(nextValue, false)}
        onCommit={(nextValue) => onChange(nextValue, true)}
        ariaLabel={`${label} value`}
      />
    </FieldRow>
  );
}

function DbControl({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const muted = value <= -60;
  return <SliderNumericField className={`clip-control ${muted ? 'is-muted' : ''}`} value={value} min={-60} max={20} step={0.1} unit="dB" prefix={muted ? <VolumeX size={15} /> : undefined} onChange={onChange} ariaLabel="Volume in decibels" />;
}

function ClipRangeControl({ value, min, max, step, suffix, onChange }: { value: number; min: number; max: number; step: number; suffix: string; onChange: (value: number) => void }) {
  const normalized = Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
  return <SliderNumericField className="clip-control" value={normalized} min={min} max={max} step={step} unit={suffix} onChange={onChange} ariaLabel={`Value in ${suffix}`} />;
}

function SubtitleInspector({ editor }: { editor: EditorController }) {
  const segment = editor.currentSegment!;
  const index = editor.srt.segments.findIndex((item) => item.index === segment.index);
  const source = editor.sourceSrt.segments[index];
  return <><div className="inspector-nav"><button disabled={index <= 0} onClick={() => { const previous = editor.srt.segments[index - 1]; editor.setSelection({ type: 'subtitle', index: previous.index }); editor.setPlayhead(previous.start); }}><SkipBack size={15} /> Previous</button><strong>#{segment.index}</strong><button disabled={index >= editor.srt.segments.length - 1} onClick={() => { const next = editor.srt.segments[index + 1]; editor.setSelection({ type: 'subtitle', index: next.index }); editor.setPlayhead(next.start); }}>Next <SkipForward size={15} /></button></div><Section title="Timing"><div className="time-grid"><label>Start<input value={segment.startLabel} onChange={(event) => editor.updateSegmentTime(segment.index, 'startLabel', event.target.value)} /></label><label>End<input value={segment.endLabel} onChange={(event) => editor.updateSegmentTime(segment.index, 'endLabel', event.target.value)} /></label></div><Field label="Duration" value={`${Math.max(0, segment.end - segment.start).toFixed(2)}s`} /><div className="inspector-buttons"><button onClick={() => editor.moveSubtitleSegments([segment.index], -.1)}><MoveHorizontal size={14} /> −0.1s</button><button onClick={() => editor.moveSubtitleSegments([segment.index], .1)}><MoveHorizontal size={14} /> +0.1s</button></div></Section>{source && source.text !== segment.text && <Section title="Original"><p className="source-copy">{source.text}</p></Section>}<Section title={source ? 'Translation' : 'Subtitle text'}><textarea className="inspector-textarea" value={editor.edits[segment.index] ?? segment.text} onChange={(event) => editor.setEdits({ ...editor.edits, [segment.index]: event.target.value })} /><div className="inspector-buttons"><button onClick={() => copyText(editor.edits[segment.index] ?? segment.text)}><Copy size={14} /> Copy</button><button className="primary" onClick={editor.saveSrt} disabled={!editor.dirty}><Save size={14} /> Save</button></div></Section><SubtitleStyleControls editor={editor} /><Section title="Voice line"><div className="inspector-buttons"><button onClick={() => editor.playVoice(editor.voiceByIndex[segment.index])} disabled={!editor.voiceByIndex[segment.index]?.audioUrl}><Play size={14} /> Listen</button><button onClick={() => editor.generateVoice(segment.index)}><WandSparkles size={14} /> {editor.voiceByIndex[segment.index]?.audioUrl ? 'Regenerate' : 'Generate'}</button></div></Section><button className="danger full" onClick={() => editor.deleteSegment(segment.index)}><Trash2 size={14} /> Delete segment</button></>;
}

function VoiceInspector({ editor }: { editor: EditorController }) {
  const voice = editor.currentVoice!;
  const subtitle = editor.srt.segments.find((item) => item.index === voice.index);
  const issue = editor.timelineIssues.find((item) => item.index === voice.index);
  return <><div className="inspector-hero"><span><Volume2 size={18} /></span><div><h2>Voice segment #{voice.index}</h2><p>{voice.status || 'Rendered line'}</p></div></div><Section title="Linked subtitle"><p className="source-copy">{subtitle ? editor.edits[subtitle.index] ?? subtitle.text : 'Missing subtitle link'}</p></Section><Section title="Voice"><Field label="Engine" value={editor.ttsEngine} /><Field label="Voice" value={editor.ttsVoice} /><Field label="Language" value={editor.ttsLanguage} /><Field label="Rate" value={`${editor.ttsRate}×`} /></Section><Section title="Timing"><Field label="Audio duration" value={voice.duration ? `${voice.duration.toFixed(2)}s` : '—'} /><Field label="Subtitle duration" value={voice.subtitleDuration ? `${voice.subtitleDuration.toFixed(2)}s` : '—'} /><Field label="Local speed" value={voice.requiredLocalSpeed ? `${voice.requiredLocalSpeed.toFixed(2)}×` : 'Fit'} />{issue && <div className="issue-detail"><strong>{issue.status}</strong><p>{issue.detail || 'This line does not fit its subtitle time slot.'}</p></div>}</Section><div className="inspector-buttons column"><button onClick={() => editor.playVoice(voice)} disabled={!voice.audioUrl}><Play size={14} /> Listen</button><button className="primary" onClick={() => editor.generateVoice(voice.index)}><RotateCcw size={14} /> Regenerate line</button>{voice.audioUrl && <a className="button" href={`${API_BASE}${voice.audioUrl}`}><Download size={14} /> Download segment</a>}</div></>;
}

function TrackInspector({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{editor.srt.asset?.name || 'Subtitle track'}</h2><p>{editor.srt.asset && (editor.srt.asset.engine || 'Imported')}</p></div></div><Section title="Track"><Field label="Language" value="Auto / asset metadata" /><Field label="Source type" value={editor.srt.asset && (editor.srt.asset.engine || 'Imported')} /><Field label="Segments" value={editor.srt.segments.length} /></Section><SubtitleStyleControls editor={editor} /><div className="inspector-buttons column"><button onClick={editor.copySrt}><Copy size={14} /> Copy full SRT</button><button onClick={editor.pasteSrt}>Paste full SRT</button><button onClick={() => editor.openTool('translate')}>Translate this SRT</button><button onClick={() => editor.openTool('voiceover')}>Generate voiceover</button>{editor.srt.asset && <a className="button" href={`${API_BASE}/assets/${editor.srt.asset.id}/download`}><Download size={14} /> Export SRT</a>}</div></>;
}

function EffectInspector({ editor }: { editor: EditorController }) {
  const operation = editor.selection.type === 'effect' ? editor.selection.operation : 'hide';
  if (operation === 'blur') {
    const effect = editor.activeBlurEffect;
    if (!effect) return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>Subtitle blur</h2><p>Non-destructive effect</p></div></div><Section title="Effect"><Field label="Status" value="Not added" /></Section><p className="inspector-help">Choose Auto or Manual in Tools, then add the effect to the FX track.</p><button className="primary full" onClick={() => editor.openTool('remove')}>Open effect settings</button></>;
    const area = effect.area;
    return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>Subtitle blur</h2><p>Non-destructive FX clip</p></div></div><Section title="Effect"><Field label="Mode" value={effect.mode === 'auto' ? 'Automatic' : 'Manual'} /><Field label="Detection" value={effect.source === 'ocr-longest-srt-line' ? 'OCR longest SRT line' : effect.source === 'fallback' ? 'Default subtitle area' : 'User-defined area'} /><Field label="Area" value={`${Math.round((area.xmax - area.xmin) * 100)}% × ${Math.round((area.ymax - area.ymin) * 100)}%`} /><Field label="Status" value="Active on export" /></Section>{effect.longest_segment_text && <Section title="OCR reference"><Field label="SRT line" value={`#${effect.longest_segment_index}`} /><p className="source-copy">{effect.longest_segment_text}</p></Section>}<p className="inspector-help">The source video remains unchanged. Select this FX clip and press Delete or Backspace to remove it.</p><button className="primary full" onClick={() => editor.openTool('remove')}>Edit effect settings</button></>;
  }
  const completed = operation === 'insert'
    ? editor.project.processingState.subtitleInserted
    : editor.project.processingState.subtitleHidden;
  const legacyInsert = operation === 'insert';
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{legacyInsert ? 'Rendered captions' : 'Remove / Hide'}</h2><p>{completed ? 'Rendered backend operation' : 'Operation setup'}</p></div></div><Section title="Operation"><Field label="Mode" value={legacyInsert ? editor.project.processingState.insertMode || editor.insertMode : editor.project.processingState.hideMode || editor.removeMode} /><Field label="Version" value={`#${editor.project.id}`} /><Field label="Status" value={completed ? 'Completed' : 'Not rendered'} /></Section><p className="inspector-help">{legacyInsert ? 'This timeline item visualizes an existing rendered version. The creation UI for this operation has been removed.' : completed ? 'This timeline item visualizes the existing version operation; it is not a frontend-only effect.' : 'Configure and run this operation in Tools. No video version has been changed yet.'}</p>{completed ? <button className="full" onClick={() => editor.undo(operation)}><RotateCcw size={14} /> Undo to ancestor version</button> : !legacyInsert && <button className="primary full" onClick={() => editor.openTool('remove')}>Open operation settings</button>}</>;
}

function AssetInspector({ editor }: { editor: EditorController }) {
  const id = editor.selection.type === 'asset' ? editor.selection.id : 0;
  const asset = editor.project.assets.find((item) => item.id === id);
  if (!asset) return <ProjectInspector editor={editor} />;
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{asset.name}</h2><p>{asset.kind.toUpperCase()}</p></div></div><Section title="Asset"><Field label="Engine" value={asset.engine || 'Local'} /><Field label="Status" value={asset.status} /><Field label="Created" value={asset.createdAt?.slice(0, 16)} /></Section><a className="button primary full" href={`${API_BASE}/assets/${asset.id}/download`}><Download size={14} /> Download asset</a></>;
}

function SubtitleStyleControls({ editor }: { editor: EditorController }) {
  return <TextStyleControls
    title="Style (Global)"
    style={editor.style}
    onUpdate={editor.updateSubtitleStyle}
    onPreset={editor.applySubtitleStylePreset}
    onReset={editor.resetSubtitleStylePreset}
    canDistribute={editor.selectedTextItems.length >= 3}
    onDistribute={editor.distributeTimelineTextItems}
  />;
}

function TimelineTextStyleControls({ editor }: { editor: EditorController }) {
  return <TextStyleControls
    title="Text Style"
    style={editor.selectedTextStyle}
    onUpdate={editor.updateTimelineTextStyle}
    onPreset={editor.applyTimelineTextStylePreset}
    onReset={editor.resetTimelineTextStylePreset}
    canDistribute={editor.selectedTextItems.length >= 3}
    onDistribute={editor.distributeTimelineTextItems}
  />;
}

function TextStyleControls({
  title,
  style,
  onUpdate,
  onPreset,
  onReset,
  canDistribute,
  onDistribute,
}: {
  title: string;
  style: SubtitleStyle;
  onUpdate: (updates: Partial<SubtitleStyle>) => void;
  onPreset: (presetId: string) => void;
  onReset: () => void;
  canDistribute: boolean;
  onDistribute: (axis: 'horizontal' | 'vertical') => void;
}) {
  const backgroundEnabled = Boolean(style.backgroundEnabled ?? style.background);
  const weightActive = style.fontWeight === 'bold' || Number(style.fontWeight) >= 700;
  return (
    <Section title={title}>
      <TextStylePresetGrid activePresetId={style.presetId} onSelect={onPreset} onReset={onReset} />
      <div className="style-controls-panel">
        <StyleGroup title="Font">
          <FontPicker value={style.fontFamily} onChange={(fontFamily) => onUpdate({ fontFamily })} />
          <NumericSliderField label="Size" className="size-slider-field" value={(style.fontSize ?? 50) / 10} min={1} max={10} step={1} suffix="" onChange={(fontSize) => onUpdate({ fontSize: fontSize * 10 })} />
        </StyleGroup>

        <StyleGroup title="Style">
          <FieldRow label="Weight">
            <SegmentedControl
              options={[
                { id: 'bold', label: 'Bold', icon: <Bold size={14} />, active: weightActive, onClick: () => onUpdate({ fontWeight: weightActive ? 'normal' : 'bold' }) },
                { id: 'underline', label: 'Underline', icon: <Underline size={14} />, active: style.textDecoration === 'underline', onClick: () => onUpdate({ textDecoration: style.textDecoration === 'underline' ? 'none' : 'underline' }) },
                { id: 'italic', label: 'Italic', icon: <Italic size={14} />, active: style.fontStyle === 'italic', onClick: () => onUpdate({ fontStyle: style.fontStyle === 'italic' ? 'normal' : 'italic' }) },
              ]}
            />
          </FieldRow>
          <FieldRow label="Case">
            <SegmentedControl
              options={[
                { id: 'none', label: 'Aa', active: !style.textTransform || style.textTransform === 'none', onClick: () => onUpdate({ textTransform: 'none' }) },
                { id: 'uppercase', label: 'AA', active: style.textTransform === 'uppercase', onClick: () => onUpdate({ textTransform: 'uppercase' }) },
                { id: 'lowercase', label: 'aa', active: style.textTransform === 'lowercase', onClick: () => onUpdate({ textTransform: 'lowercase' }) },
                { id: 'capitalize', label: 'Tt', active: style.textTransform === 'capitalize', onClick: () => onUpdate({ textTransform: 'capitalize' }) },
              ]}
            />
          </FieldRow>
          <FieldRow label="Align">
            <AlignToolbar
              horizontal={style.textAlign || 'center'}
              vertical={style.verticalAlign || 'bottom'}
              canDistribute={canDistribute}
              onUpdate={onUpdate}
              onDistribute={onDistribute}
            />
          </FieldRow>
        </StyleGroup>

        <StyleGroup title="Color & outline">
          <div className="style-two-col">
            <ColorField label="Text" value={style.fontColor || style.color || '#ffffff'} onChange={(fontColor) => onUpdate({ fontColor, color: fontColor })} />
            <ColorField label="Outline" value={style.outlineColor || '#000000'} onChange={(outlineColor) => onUpdate({ outlineColor })} />
          </div>
          <NumericSliderField label="Outline" value={style.outline ?? style.outlineWidth ?? 0} min={0} max={12} step={0.5} suffix="px" onChange={(outline) => onUpdate({ outline, outlineWidth: outline })} />
        </StyleGroup>

        <StyleGroup title="Spacing">
          <NumericSliderField label="Letter" value={style.letterSpacing || 0} min={-8} max={24} step={0.5} suffix="px" onChange={(letterSpacing) => onUpdate({ letterSpacing })} />
          <NumericSliderField label="Line" value={style.lineHeight || 1.05} min={0.7} max={2.2} step={0.05} suffix="x" onChange={(lineHeight) => onUpdate({ lineHeight })} />
        </StyleGroup>

        <ToggleSection title="Background" checked={backgroundEnabled} onChange={(enabled) => onUpdate({ background: enabled, backgroundEnabled: enabled })}>
          <div className="style-two-col">
            <ColorField label="Fill" value={style.backgroundColor || '#000000'} onChange={(backgroundColor) => onUpdate({ backgroundColor })} />
            <NumericField label="Opacity" value={style.backgroundOpacity ?? 0.55} min={0} max={1} step={0.05} onChange={(backgroundOpacity) => onUpdate({ backgroundOpacity })} />
          </div>
          <div className="style-two-col">
            <NumericField label="Radius" value={style.backgroundRadius ?? 4} min={0} max={24} step={1} onChange={(backgroundRadius) => onUpdate({ backgroundRadius })} />
            <NumericField label="Padding" value={style.backgroundPaddingX ?? 8} min={0} max={32} step={1} onChange={(backgroundPaddingX) => onUpdate({ backgroundPaddingX, backgroundPaddingY: Math.max(0, Math.round(backgroundPaddingX / 2)) })} />
          </div>
        </ToggleSection>

        <StyleGroup title="Shadow">
          <div className="style-two-col">
            <ColorField label="Color" value={style.shadowColor || '#000000'} onChange={(shadowColor) => onUpdate({ shadowColor })} />
            <NumericField label="Blur" value={style.shadowBlur || 0} min={0} max={24} step={0.5} onChange={(shadowBlur) => onUpdate({ shadowBlur })} />
          </div>
          <div className="style-two-col">
            <NumericField label="X" value={style.shadowOffsetX || 0} min={-24} max={24} step={0.5} onChange={(shadowOffsetX) => onUpdate({ shadowOffsetX })} />
            <NumericField label="Y" value={style.shadowOffsetY || 0} min={-24} max={24} step={0.5} onChange={(shadowOffsetY) => onUpdate({ shadowOffsetY })} />
          </div>
        </StyleGroup>

        <ToggleSection title="Glow" checked={Boolean(style.glowEnabled)} onChange={(glowEnabled) => onUpdate({ glowEnabled })}>
          <div className="style-two-col">
            <ColorField label="Color" value={style.glowColor || '#ffffff'} onChange={(glowColor) => onUpdate({ glowColor })} />
            <NumericField label="Blur" value={style.glowBlur || 0} min={0} max={32} step={0.5} onChange={(glowBlur) => onUpdate({ glowBlur })} />
          </div>
          <NumericSliderField label="Power" value={style.glowStrength || 1} min={0} max={2} step={0.05} suffix="x" onChange={(glowStrength) => onUpdate({ glowStrength })} />
        </ToggleSection>
      </div>
    </Section>
  );
}

function StyleGroup({ title, children }: { title: string; children: ReactNode }) {
  return <div className="style-control-group"><h4>{title}</h4><div className="style-control-stack">{children}</div></div>;
}

export function FieldRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <div className="style-field-row"><span>{label}</span><div>{children}</div></div>;
}

function ToggleSection({ title, checked, onChange, children }: { title: string; checked: boolean; onChange: (checked: boolean) => void; children: ReactNode }) {
  return (
    <div className={`style-control-group toggle ${checked ? 'enabled' : ''}`}>
      <button type="button" className="style-toggle-head" onClick={() => onChange(!checked)} aria-pressed={checked}>
        <span>{title}</span>
        <i>{checked ? 'On' : 'Off'}</i>
      </button>
      {checked && <div className="style-control-stack">{children}</div>}
    </div>
  );
}

function FontPicker({ value, onChange }: { value?: string; onChange: (family: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selected = fontByFamily(value) || fontByFamily(DEFAULT_FONT_FAMILY)!;
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = useMemo(() => FONT_REGISTRY.filter((font) => {
    if (!normalizedQuery) return true;
    return `${font.label} ${font.category}`.toLowerCase().includes(normalizedQuery);
  }), [normalizedQuery]);

  return (
    <div className="font-picker">
      <button type="button" className="font-picker-trigger" onClick={() => setOpen((current) => !current)}>
        <span style={{ fontFamily: fontStack(selected.family) }}>{selected.label}</span>
        <small>{selected.category}</small>
      </button>
      {open && <div className="font-picker-popover">
        <input
          value={query}
          autoFocus
          placeholder="Search fonts"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && filtered[0]) {
              onChange(filtered[0].family);
              setOpen(false);
              setQuery('');
            }
            if (event.key === 'Escape') setOpen(false);
          }}
        />
        <div className="font-picker-list">
          {FONT_CATEGORIES.map((category) => {
            const fonts = filtered.filter((font) => font.category === category);
            if (!fonts.length) return null;
            return <div className="font-picker-category" key={category}><strong>{category}</strong>{fonts.map((font) => (
              <button
                type="button"
                key={font.id}
                className={font.family === selected.family ? 'active' : ''}
                onClick={() => {
                  onChange(font.family);
                  setOpen(false);
                  setQuery('');
                }}
              >
                <span style={{ fontFamily: fontStack(font.family) }}>{font.label}</span>
                <small>{font.weights.join('/')}</small>
              </button>
            ))}</div>;
          })}
        </div>
      </div>}
    </div>
  );
}

function SegmentedControl({ options }: { options: Array<{ id: string; label: string; icon?: ReactNode; active: boolean; onClick: () => void }> }) {
  return <div className="style-segmented">{options.map((option) => (
    <button type="button" key={option.id} className={option.active ? 'active' : ''} title={option.label} onClick={option.onClick}>
      {option.icon || <span>{option.label}</span>}
    </button>
  ))}</div>;
}

function AlignToolbar({ horizontal, vertical, canDistribute, onUpdate, onDistribute }: { horizontal: 'left' | 'center' | 'right'; vertical: 'top' | 'middle' | 'bottom'; canDistribute: boolean; onUpdate: (updates: Partial<SubtitleStyle>) => void; onDistribute: (axis: 'horizontal' | 'vertical') => void }) {
  return (
    <div className="align-toolbar" role="toolbar" aria-label="Text alignment">
      <button type="button" className={horizontal === 'left' ? 'active' : ''} title="Align left" onClick={() => onUpdate({ textAlign: 'left' })}><AlignLeft size={15} /></button>
      <button type="button" className={horizontal === 'center' ? 'active' : ''} title="Align horizontal center" onClick={() => onUpdate({ textAlign: 'center' })}><AlignCenter size={15} /></button>
      <button type="button" className={horizontal === 'right' ? 'active' : ''} title="Align right" onClick={() => onUpdate({ textAlign: 'right' })}><AlignRight size={15} /></button>
      <i aria-hidden="true" />
      <button type="button" className={vertical === 'top' ? 'active' : ''} title="Align top" onClick={() => onUpdate({ verticalAlign: 'top' })}><AlignTopIcon /></button>
      <button type="button" className={vertical === 'middle' ? 'active' : ''} title="Align vertical center" onClick={() => onUpdate({ verticalAlign: 'middle' })}><AlignMiddleIcon /></button>
      <button type="button" className={vertical === 'bottom' ? 'active' : ''} title="Align bottom" onClick={() => onUpdate({ verticalAlign: 'bottom' })}><AlignBottomIcon /></button>
      <i aria-hidden="true" />
      <button type="button" disabled={!canDistribute} title={canDistribute ? 'Distribute horizontally' : 'Select at least 3 text clips to distribute horizontally'} onClick={() => onDistribute('horizontal')}><DistributeHorizontalIcon /></button>
      <button type="button" disabled={!canDistribute} title={canDistribute ? 'Distribute vertically' : 'Select at least 3 text clips to distribute vertically'} onClick={() => onDistribute('vertical')}><DistributeVerticalIcon /></button>
    </div>
  );
}

function AlignTopIcon() {
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3h10M5 6h6M6 9h4M7 12h2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
}

function AlignMiddleIcon() {
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M5 4h6M5 12h6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
}

function AlignBottomIcon() {
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 13h10M5 10h6M6 7h4M7 4h2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
}

function DistributeHorizontalIcon() {
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3v10M13 3v10M6 5h4M5 8h6M6 11h4" fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" /></svg>;
}

function DistributeVerticalIcon() {
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3h10M3 13h10M5 6v4M8 5v6M11 6v4" fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" /></svg>;
}

function NumericSliderField({ label, value, min, max, step, suffix, className, onChange }: { label: string; value: number; min: number; max: number; step: number; suffix: string; className?: string; onChange: (value: number) => void }) {
  const normalized = clampNumber(value, min, max);
  return (
    <FieldRow label={label}>
      <SliderNumericField className={`style-range-field ${className || ''}`.trim()} value={normalized} min={min} max={max} step={step} unit={suffix} onChange={onChange} ariaLabel={`${label} value`} />
    </FieldRow>
  );
}

function NumericField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return <div className="style-mini-field"><span>{label}</span><NumericControl value={clampNumber(value, min, max)} min={min} max={max} step={step} onChange={onChange} compact ariaLabel={`${label} value`} /></div>;
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="style-color-field">
      <span>{label}</span>
      <input type="color" value={value} onChange={(event) => onChange(event.target.value)} />
      <code>{value.toUpperCase()}</code>
    </label>
  );
}

function audioFadeValue(item: TimelineItem, key: 'audioFadeIn' | 'audioFadeOut') {
  const value = Number(item.params?.[key] ?? 0);
  return clampNumber(value, 0, Math.max(0, item.duration || 0));
}

function imageTransformValue(item: TimelineItem) {
  const raw = item.params?.imageTransform;
  const transform = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  return {
    scale: clampNumber(Number(transform.scale ?? 1), 0.1, 5),
    x: clampNumber(Number(transform.x ?? 0.5), 0, 1),
    y: clampNumber(Number(transform.y ?? 0.5), 0, 1),
  };
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}
