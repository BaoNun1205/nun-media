import { useEffect, useState } from 'react';
import { CheckCircle2, Cpu, FolderCog, KeyRound, Save, Trash2 } from 'lucide-react';
import { studioApi } from '../services/api';
import type { StudioSettings } from '../types/studio';

export function SettingsPage() {
  const [settings, setSettings] = useState<StudioSettings>({ hasDouyinCookie: false, douyinCookieLength: 0 });
  const [cookie, setCookie] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [message, setMessage] = useState('');
  const [defaults, setDefaults] = useState(() => {
    try {
      return { whisperModel: 'small', device: 'auto', ttsEngine: 'vieneu', exportPreset: 'source', maxWordsPerLine: 0, ...JSON.parse(localStorage.getItem('stitch-editor-defaults') || '{}') };
    } catch {
      return { whisperModel: 'small', device: 'auto', ttsEngine: 'vieneu', exportPreset: 'source', maxWordsPerLine: 0 };
    }
  });
  useEffect(() => { studioApi.settings().then(setSettings).catch((error) => setMessage(error.message)); }, []);
  
  async function saveCookie(value: string) {
    try {
      const data = await studioApi.saveSettings({ douyinCookie: value });
      setSettings(data); setCookie(''); setMessage(value ? 'Cookie header saved.' : 'Cookie header cleared.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Unable to save'); }
  }

  async function saveGeminiKey(value: string) {
    try {
      const data = await studioApi.saveSettings({ geminiApiKey: value });
      setSettings(data); setGeminiKey(''); setMessage(value ? 'Gemini API key saved.' : 'Gemini API key cleared.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Unable to save'); }
  }

  function saveDefaults() {
    localStorage.setItem('stitch-editor-defaults', JSON.stringify(defaults));
    setMessage('Editor defaults saved locally and will apply when an editor is opened.');
  }
  return (
    <section className="page settings-page">
      <header className="page-header"><div><span className="eyebrow">Preferences</span><h1>Settings</h1><p>Connection details and defaults for new editing jobs.</p></div></header>
      <div className="settings-grid">
        <section className="settings-card wide"><div className="settings-card-title"><KeyRound size={18} /><div><h2>Douyin cookie</h2><p>Used by the existing downloader pipeline.</p></div><span className={`status-pill ${settings.hasDouyinCookie ? 'completed' : ''}`}>{settings.hasDouyinCookie ? <><CheckCircle2 size={13} /> Stored</> : 'Not configured'}</span></div><textarea value={cookie} onChange={(event) => setCookie(event.target.value)} placeholder="Paste the full Cookie request header…" /><div className="settings-actions"><button className="primary" disabled={!cookie.trim()} onClick={() => saveCookie(cookie)}><Save size={15} /> Save cookie</button><button className="danger" disabled={!settings.hasDouyinCookie} onClick={() => saveCookie('')}><Trash2 size={15} /> Clear</button><span>{message}</span></div></section>
        
        <section className="settings-card wide"><div className="settings-card-title"><KeyRound size={18} /><div><h2>Gemini API Key</h2><p>Used for context-aware SRT translation and timing optimization (Gemini 3.5 Flash-Lite).</p></div><span className={`status-pill ${settings.hasGeminiApiKey ? 'completed' : ''}`}>{settings.hasGeminiApiKey ? <><CheckCircle2 size={13} /> Stored</> : 'Not configured'}</span></div><input type="password" style={{ display: 'block', width: '100%', marginBottom: '16px', background: 'var(--surface-sunken)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', color: 'var(--text)', fontSize: '13px' }} value={geminiKey} onChange={(event) => setGeminiKey(event.target.value)} placeholder="Enter Gemini API Key..." /><div className="settings-actions"><button className="primary" disabled={!geminiKey.trim()} onClick={() => saveGeminiKey(geminiKey)}><Save size={15} /> Save API Key</button><button className="danger" disabled={!settings.hasGeminiApiKey} onClick={() => saveGeminiKey('')}><Trash2 size={15} /> Clear</button><span>{message}</span></div></section>

        <section className="settings-card"><div className="settings-card-title"><Cpu size={18} /><div><h2>Editor defaults</h2><p>Stored locally and used to initialize editor sessions.</p></div></div><label>Whisper model<select value={defaults.whisperModel} onChange={(event) => setDefaults({ ...defaults, whisperModel: event.target.value })}>{['tiny', 'base', 'small', 'medium', 'large-v3'].map((item) => <option key={item}>{item}</option>)}</select></label><label>Compute device<select value={defaults.device} onChange={(event) => setDefaults({ ...defaults, device: event.target.value })}><option value="auto">Auto</option><option value="cpu">CPU</option><option value="cuda">CUDA</option></select></label><label>Words per line (Max)<select value={defaults.maxWordsPerLine ?? 0} onChange={(event) => setDefaults({ ...defaults, maxWordsPerLine: Number(event.target.value) || 0 })}><option value={0}>Auto (Whisper default)</option><option value={6}>6 words</option><option value={8}>8 words (Compact)</option><option value={10}>10 words (Standard)</option><option value={12}>12 words</option><option value={15}>15 words</option><option value={20}>20 words</option></select></label><label>TTS engine<select value={defaults.ttsEngine} onChange={(event) => setDefaults({ ...defaults, ttsEngine: event.target.value })}><option value="vieneu">VieNeu</option><option value="capcut">CapCut</option><option value="pocket">Pocket TTS</option></select></label><label>Export preset<select value={defaults.exportPreset} onChange={(event) => setDefaults({ ...defaults, exportPreset: event.target.value })}><option value="source">Match source</option><option value="web">Web optimized</option><option value="audio">Audio only</option></select></label><button className="primary" onClick={saveDefaults}><Save size={15} /> Save defaults</button><small className="pending-label">Export preset is stored but backend presets are not available yet</small></section>
        <section className="settings-card"><div className="settings-card-title"><FolderCog size={18} /><div><h2>Application paths</h2><p>Runtime locations reported by the app.</p></div></div><dl><dt>Backend</dt><dd>{settings.backendPath || '/api · port 8008'}</dd><dt>Frontend</dt><dd>{settings.frontendPath || 'http://127.0.0.1:5173'}</dd></dl></section>
      </div>
    </section>
  );
}
