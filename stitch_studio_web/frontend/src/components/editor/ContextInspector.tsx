import { Copy, Download, FolderOpen, Gauge, Info, Languages, MoveHorizontal, Play, RotateCcw, Save, SkipBack, SkipForward, Trash2, Volume2, VolumeX, WandSparkles } from 'lucide-react';
import { formatClock, formatDuration, formatSize } from '../../lib/studio';
import { API_BASE, copyText, studioApi } from '../../services/api';
import type { EditorController } from '../../hooks/useEditorController';

export function ContextInspector({ editor }: { editor: EditorController }) {
  return <aside className="context-inspector">
    <header><span>Inspector</span><small>{selectionName(editor)}</small></header>
    <div className="inspector-body">{editor.selection.type === 'subtitle' && editor.currentSegment ? <SubtitleInspector editor={editor} />
      : editor.selection.type === 'voice' && editor.currentVoice ? <VoiceInspector editor={editor} />
      : editor.selection.type === 'timeline-items' && isMergedVoiceSelection(editor) ? <VoiceoverInspector editor={editor} />
      : editor.selection.type === 'timeline-items' ? <MultiSelectionInspector editor={editor} />
      : editor.selection.type === 'video' ? <VideoInspectorControls editor={editor} />
      : editor.selection.type === 'subtitle-track' ? <TrackInspector editor={editor} />
      : editor.selection.type === 'effect' ? <EffectInspector editor={editor} />
      : editor.selection.type === 'asset' ? <AssetInspector editor={editor} />
      : <ProjectInspector editor={editor} />}</div>
  </aside>;
}

function selectionName(editor: EditorController) {
  const value = editor.selection;
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
  const voices = selection.keys.filter((key) => key.startsWith('voice:')).length;
  const heading = selection.track ? selection.track + ' selected' : selection.keys.length + ' items selected';
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{heading}</h2><p>{selection.track ? 'Entire timeline track' : 'Marquee selection'}</p></div></div><Section title="Selection"><Field label="Total items" value={selection.keys.length} />{subtitles > 0 && <Field label="Subtitles" value={subtitles} />}{voices > 0 && <Field label="Voice clips" value={voices} />}</Section>{subtitles > 0 && <SubtitleStyleControls editor={editor} />}{subtitles > 0 && <><Section title="Position on preview"><p className="inspector-help">Drag the subtitle text up or down directly in the video preview. When it reaches the center, a cyan guide appears and snaps it into place.</p></Section><button className="danger full" onClick={() => editor.deleteSelectedSubtitles()}><Trash2 size={14} /> Delete selected subtitles</button></>}<p className="inspector-help">Drag on an empty timeline area to replace this selection. Hold Ctrl, Cmd, or Shift while clicking clips to add or remove individual items. Use Delete or Backspace to remove selected subtitles.</p>{selection.track === 'S1' && <div className="inspector-buttons column"><button onClick={() => editor.setBottomView('script')}>Open Script Editor</button><button onClick={editor.copySrt}><Copy size={14} /> Copy full SRT</button><button onClick={editor.replaceWithTranslated} disabled={!editor.hasLoadedTranslation} title={editor.hasLoadedTranslation ? 'Replace the active draft text with the translated SRT' : 'Waiting for translated SRT to load'}><Languages size={14} /> Replace with translated SRT</button></div>}</>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="inspector-section"><h3>{title}</h3>{children}</section>;
}
function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="inspector-field"><span>{label}</span><strong>{value}</strong></div>;
}

function ProjectInspector({ editor }: { editor: EditorController }) {
  const p = editor.project;
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{p.title}</h2><p>Project {p.projectId}</p></div></div><Section title="Project"><Field label="Original file" value={p.name} /><Field label="Duration" value={formatDuration(p.durationMs)} /><Field label="Media" value={p.mediaType || 'Video'} /><Field label="Current version" value={`#${p.id}`} /><Field label="Assets" value={p.assets.length} /><Field label="Size" value={formatSize(p.sizeBytes)} /></Section><Section title="Pipeline"><div className="inspector-status-list"><span className={p.hasSrt ? 'ready' : ''}>SRT {p.hasSrt ? 'Ready' : 'Missing'}</span><span className={p.hasTranslatedSrt ? 'ready' : ''}>Translation {p.hasTranslatedSrt ? 'Ready' : 'Missing'}</span><span className={p.hasTts ? 'ready' : ''}>Voiceover {p.hasTts ? 'Ready' : 'Missing'}</span></div></Section>{editor.jobs[0] && <Section title="Latest job"><Field label={editor.jobs[0].kind} value={editor.jobs[0].status} /></Section>}</>;
}

function VideoInspector({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Play size={18} /></span><div><h2>{editor.project.title}</h2><p>Main video clip</p></div></div><Section title="Timing"><Field label="Timeline start" value="00:00:00" /><Field label="Source in" value="00:00:00" /><Field label="Source out" value={formatClock(editor.duration)} /><Field label="Duration" value={formatClock(editor.duration)} /></Section><Section title="Preview speed"><label className="stack-label">Playback speed<select value={editor.playbackRate} onChange={(event) => editor.setPlaybackRate(Number(event.target.value))}><option value=".5">0.5×</option><option value=".75">0.75×</option><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><span className="pending-label"><Gauge size={12} /> Preview only · export retiming unavailable</span></Section><Section title="Preview audio"><label className="stack-label">Volume<input type="range" min="0" max="1" step=".05" value={editor.previewVolume} onChange={(event) => editor.setPreviewVolume(Number(event.target.value))} /></label><label className="check-line"><input type="checkbox" checked={editor.previewMuted} onChange={(event) => editor.setPreviewMuted(event.target.checked)} /> Mute source audio</label></Section><button className="full" onClick={() => studioApi.revealProject(editor.project.id)}><FolderOpen size={15} /> Reveal source file</button></>;
}

function VideoInspectorControls({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Play size={18} /></span><div><h2>{editor.project.title}</h2><p>Main video clip</p></div></div><Section title="Tỉ lệ"><ClipRangeControl value={editor.videoScale} min={.1} max={5} step={.01} suffix="×" onChange={editor.updateVideoScale} /></Section><Section title="Âm thanh"><DbControl value={editor.videoVolumeDb} onChange={editor.updateVideoVolumeDb} /></Section><Section title="Tốc độ"><ClipRangeControl value={editor.videoSpeed} min={.1} max={80} step={.1} suffix="×" onChange={editor.updateVideoSpeed} /></Section><Section title="Timing"><Field label="Timeline start" value="00:00:00" /><Field label="Duration" value={formatClock(editor.duration)} /></Section><button className="full" onClick={() => studioApi.revealProject(editor.project.id)}><FolderOpen size={15} /> Reveal source file</button></>;
}

function VoiceoverInspector({ editor }: { editor: EditorController }) {
  return <><div className="inspector-hero"><span><Volume2 size={18} /></span><div><h2>Voiceover</h2><p>Merged clip on A2</p></div></div><Section title="Âm thanh"><DbControl value={editor.voiceVolumeDb} onChange={editor.updateVoiceVolumeDb} /></Section><Section title="Tốc độ"><ClipRangeControl value={editor.voiceSpeed} min={.1} max={80} step={.1} suffix="×" onChange={editor.updateVoiceSpeed} /></Section><p className="inspector-help">The voice settings are saved with this video version and apply in the preview.</p></>;
}

function DbControl({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const muted = value <= -60;
  return <div className="clip-control"><input aria-label="Volume in decibels" type="range" min="-60" max="20" step=".1" value={value} onChange={(event) => onChange(Number(event.target.value))} /><label className={`clip-value ${muted ? 'muted' : ''}`}>{muted ? <VolumeX size={15} /> : null}<input type="number" min="-60" max="20" step=".1" value={value} onChange={(event) => onChange(Number(event.target.value))} /><span>{muted ? '−∞ dB' : 'dB'}</span></label></div>;
}

function ClipRangeControl({ value, min, max, step, suffix, onChange }: { value: number; min: number; max: number; step: number; suffix: string; onChange: (value: number) => void }) {
  const normalized = Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
  return <div className="clip-control"><input aria-label={`Value in ${suffix}`} type="range" min={min} max={max} step={step} value={normalized} onChange={(event) => onChange(Number(event.target.value))} /><label className="clip-value"><input type="number" min={min} max={max} step={step} value={normalized} onChange={(event) => onChange(Number(event.target.value))} /><span>{suffix}</span></label></div>;
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
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{editor.srt.asset?.name || 'Subtitle track'}</h2><p>{editor.srt.asset && (editor.srt.asset.engine || 'Imported')}</p></div></div><Section title="Track"><Field label="Language" value="Auto / asset metadata" /><Field label="Source type" value={editor.srt.asset && (editor.srt.asset.engine || 'Imported')} /><Field label="Segments" value={editor.srt.segments.length} /></Section><div className="inspector-buttons column"><button onClick={() => editor.setBottomView('script')}>Open Script Editor</button><button onClick={editor.copySrt}><Copy size={14} /> Copy full SRT</button><button onClick={editor.pasteSrt}>Paste full SRT</button><button onClick={() => editor.openTool('translate')}>Translate this SRT</button><button onClick={() => editor.openTool('voiceover')}>Generate voiceover</button><button onClick={() => editor.openTool('insert')}>Use for subtitle insertion</button>{editor.srt.asset && <a className="button" href={`${API_BASE}/assets/${editor.srt.asset.id}/download`}><Download size={14} /> Export SRT</a>}</div></>;
}

function EffectInspector({ editor }: { editor: EditorController }) {
  const operation = editor.selection.type === 'effect' ? editor.selection.operation : 'hide';
  if (operation === 'blur') {
    const effect = editor.activeBlurEffect;
    if (!effect) return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>Subtitle blur</h2><p>Non-destructive effect</p></div></div><Section title="Effect"><Field label="Status" value="Not added" /></Section><p className="inspector-help">Choose Auto or Manual in AI Tools, then add the effect to the FX track.</p><button className="primary full" onClick={() => editor.openTool('remove')}>Open effect settings</button></>;
    const area = effect.area;
    return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>Subtitle blur</h2><p>Non-destructive FX clip</p></div></div><Section title="Effect"><Field label="Mode" value={effect.mode === 'auto' ? 'Automatic' : 'Manual'} /><Field label="Detection" value={effect.source === 'ocr-longest-srt-line' ? 'OCR longest SRT line' : effect.source === 'fallback' ? 'Default subtitle area' : 'User-defined area'} /><Field label="Area" value={`${Math.round((area.xmax - area.xmin) * 100)}% × ${Math.round((area.ymax - area.ymin) * 100)}%`} /><Field label="Status" value="Active on export" /></Section>{effect.longest_segment_text && <Section title="OCR reference"><Field label="SRT line" value={`#${effect.longest_segment_index}`} /><p className="source-copy">{effect.longest_segment_text}</p></Section>}<p className="inspector-help">The source video remains unchanged. Select this FX clip and press Delete or Backspace to remove it.</p><button className="primary full" onClick={() => editor.openTool('remove')}>Edit effect settings</button></>;
  }
  const completed = operation === 'insert'
    ? editor.project.processingState.subtitleInserted
    : editor.project.processingState.subtitleHidden;
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{operation === 'insert' ? 'Insert subtitles' : 'Remove / Hide'}</h2><p>{completed ? 'Rendered backend operation' : 'Operation setup'}</p></div></div><Section title="Operation"><Field label="Mode" value={operation === 'insert' ? editor.project.processingState.insertMode || editor.insertMode : editor.project.processingState.hideMode || editor.removeMode} /><Field label="Version" value={`#${editor.project.id}`} /><Field label="Status" value={completed ? 'Completed' : 'Not rendered'} /></Section><p className="inspector-help">{completed ? 'This timeline item visualizes the existing version operation; it is not a frontend-only effect.' : 'Configure and run this operation in AI Tools. No video version has been changed yet.'}</p>{completed ? <button className="full" onClick={() => editor.undo(operation)}><RotateCcw size={14} /> Undo to ancestor version</button> : <button className="primary full" onClick={() => editor.openTool(operation === 'insert' ? 'insert' : 'remove')}>Open operation settings</button>}</>;
}

function AssetInspector({ editor }: { editor: EditorController }) {
  const id = editor.selection.type === 'asset' ? editor.selection.id : 0;
  const asset = editor.project.assets.find((item) => item.id === id);
  if (!asset) return <ProjectInspector editor={editor} />;
  return <><div className="inspector-hero"><span><Info size={18} /></span><div><h2>{asset.name}</h2><p>{asset.kind.toUpperCase()}</p></div></div><Section title="Asset"><Field label="Engine" value={asset.engine || 'Local'} /><Field label="Status" value={asset.status} /><Field label="Created" value={asset.createdAt?.slice(0, 16)} /></Section><a className="button primary full" href={`${API_BASE}/assets/${asset.id}/download`}><Download size={14} /> Download asset</a></>;
}

function SubtitleStyleControls({ editor }: { editor: EditorController }) {
  const { style, updateSubtitleStyle } = editor;
  return (
    <Section title="Style (Global)">
      <div className="style-controls">
        <div className="style-row">
          <span>Phông chữ</span>
          <select value={style.fontFamily || 'Hệ thống'} onChange={(e) => updateSubtitleStyle({ fontFamily: e.target.value })}>
            <option value="Hệ thống">Hệ thống</option>
            <option value="Arial">Arial</option>
            <option value="Roboto">Roboto</option>
            <option value="Inter">Inter</option>
            <option value="Outfit">Outfit</option>
          </select>
        </div>
        <div className="style-row dual">
          <span>Cỡ chữ</span>
          <input type="range" min="1" max="100" value={style.fontSize || 6} onChange={(e) => updateSubtitleStyle({ fontSize: Number(e.target.value) })} />
          <input type="number" min="1" max="100" value={style.fontSize || 6} onChange={(e) => updateSubtitleStyle({ fontSize: Number(e.target.value) })} className="number-box" />
        </div>
        <div className="style-row">
          <span>Hoa văn</span>
          <div className="button-group">
            <button className={style.fontWeight === 'bold' ? 'active' : ''} onClick={() => updateSubtitleStyle({ fontWeight: style.fontWeight === 'bold' ? 'normal' : 'bold' })}><b>B</b></button>
            <button className={style.textDecoration === 'underline' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textDecoration: style.textDecoration === 'underline' ? 'none' : 'underline' })}><u>U</u></button>
            <button className={style.fontStyle === 'italic' ? 'active' : ''} onClick={() => updateSubtitleStyle({ fontStyle: style.fontStyle === 'italic' ? 'normal' : 'italic' })}><i>I</i></button>
          </div>
        </div>
        <div className="style-row">
          <span>Chữ hoa/thường</span>
          <div className="button-group">
            <button className={style.textTransform === 'uppercase' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textTransform: style.textTransform === 'uppercase' ? 'none' : 'uppercase' })}>TT</button>
            <button className={style.textTransform === 'lowercase' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textTransform: style.textTransform === 'lowercase' ? 'none' : 'lowercase' })}>tt</button>
            <button className={style.textTransform === 'capitalize' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textTransform: style.textTransform === 'capitalize' ? 'none' : 'capitalize' })}>Tt</button>
          </div>
        </div>
        <div className="style-row">
          <span>Màu sắc</span>
          <input type="color" value={style.fontColor || '#ffffff'} onChange={(e) => updateSubtitleStyle({ fontColor: e.target.value })} />
        </div>
        <div className="style-row dual">
          <span>Ký tự</span>
          <input type="number" value={style.letterSpacing || 0} onChange={(e) => updateSubtitleStyle({ letterSpacing: Number(e.target.value) })} className="number-box" />
          <span>Đường nét</span>
          <input type="number" value={style.lineHeight || 0} onChange={(e) => updateSubtitleStyle({ lineHeight: Number(e.target.value) })} className="number-box" />
        </div>
        <div className="style-row">
          <span>Căn chỉnh</span>
          <div className="button-group">
            <button className={style.textAlign === 'left' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textAlign: 'left' })}>⫷</button>
            <button className={style.textAlign === 'center' || !style.textAlign ? 'active' : ''} onClick={() => updateSubtitleStyle({ textAlign: 'center' })}>≣</button>
            <button className={style.textAlign === 'right' ? 'active' : ''} onClick={() => updateSubtitleStyle({ textAlign: 'right' })}>⫸</button>
          </div>
        </div>
      </div>
    </Section>
  );
}
