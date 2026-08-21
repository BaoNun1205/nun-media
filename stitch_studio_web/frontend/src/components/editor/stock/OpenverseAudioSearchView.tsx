import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Pause, Play, Plus, Search } from 'lucide-react';
import { formatDuration } from '../../../lib/studio';
import { studioApi } from '../../../services/api';
import type { OpenverseAudio, OpenverseLicenseFilter, ProjectAsset } from '../../../types/studio';

const QUICK_SEARCHES = ['Rain', 'Heavy Rain', 'Thunder', 'Thunderstorm', 'Wind', 'Forest Night', 'Footsteps', 'Door Creak', 'Heartbeat'] as const;

function emptyMessage(filter: OpenverseLicenseFilter) {
  return filter === 'public_domain' ? 'No CC0/Public Domain sounds found for this search.' : 'No matching sound effects found.';
}

function licenseLabel(license: string) {
  if (license === 'cc0') return 'CC0';
  if (license === 'pdm') return 'Public Domain';
  if (license === 'by') return 'CC BY';
  return license.toUpperCase() || 'Open license';
}

export function OpenverseAudioSearchView({ projectId, projectAssets, onImported, onMessage }: { projectId: number; projectAssets: ProjectAsset[]; onImported: () => Promise<void>; onMessage: (message: string) => void }) {
  const [query, setQuery] = useState('Heavy Rain');
  const [licenseFilter, setLicenseFilter] = useState<OpenverseLicenseFilter>('commercial');
  const [audio, setAudio] = useState<OpenverseAudio[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importingId, setImportingId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(() => new Set());
  const [playingId, setPlayingId] = useState<string | null>(null);
  const queryRef = useRef(query);
  const playerRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => playerRef.current?.pause(), []);
  useEffect(() => setAddedIds(new Set(projectAssets.filter((asset) => asset.kind === 'audio' && asset.metadata.stock_provider === 'openverse').map((asset) => String(asset.metadata.openverse_id || '')).filter(Boolean))), [projectAssets]);
  useEffect(() => {
    const activeQuery = query.trim();
    queryRef.current = activeQuery;
    if (!activeQuery) { setAudio([]); setLoading(false); setError(''); return undefined; }
    setLoading(true); setError('');
    const timer = window.setTimeout(() => void studioApi.searchOpenverseAudio(activeQuery, 1, licenseFilter)
      .then((result) => { if (queryRef.current === activeQuery) { setAudio(result.audio); setPage(result.page); setHasMore(result.hasMore); } })
      .catch((reason: unknown) => queryRef.current === activeQuery && setError(reason instanceof Error ? reason.message : 'Unable to search Openverse.'))
      .finally(() => queryRef.current === activeQuery && setLoading(false)), 400);
    return () => window.clearTimeout(timer);
  }, [query, licenseFilter]);

  function togglePreview(item: OpenverseAudio) {
    if (playingId === item.id) { playerRef.current?.pause(); setPlayingId(null); return; }
    playerRef.current?.pause();
    const player = new Audio(item.previewUrl);
    playerRef.current = player;
    player.onended = () => setPlayingId(null);
    player.onerror = () => { setPlayingId(null); setError('Unable to play this audio preview.'); };
    void player.play().then(() => setPlayingId(item.id)).catch(() => setError('Unable to play this audio preview.'));
  }

  async function add(item: OpenverseAudio) {
    if (!projectId) return onMessage('Open a workspace project before adding a sound effect.');
    if (importingId || addedIds.has(item.id)) return;
    setImportingId(item.id); setError('');
    try {
      const result = await studioApi.importOpenverseAudio(projectId, item.id);
      setAddedIds((current) => new Set(current).add(item.id));
      await onImported();
      onMessage(result.alreadyImported ? 'This sound effect is already in Assets.' : 'Sound effect added to Assets.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to import this sound effect.'); }
    finally { setImportingId(null); }
  }

  async function loadMore() {
    const activeQuery = query.trim();
    if (loading || !hasMore || !activeQuery) return;
    setLoading(true);
    try {
      const result = await studioApi.searchOpenverseAudio(activeQuery, page + 1, licenseFilter);
      if (queryRef.current === activeQuery) {
        setAudio((current) => [...current, ...result.audio.filter((item) => !current.some((known) => known.id === item.id))]);
        setPage(result.page); setHasMore(result.hasMore);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load more sounds.'); }
    finally { setLoading(false); }
  }

  return <section className="pexels-search-view">
    <label className="pexels-search-input"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search sound effects on Openverse..." /></label>
    <label className="stock-license-filter">License<select value={licenseFilter} onChange={(event) => setLicenseFilter(event.target.value as OpenverseLicenseFilter)}><option value="commercial">Commercial-friendly</option><option value="public_domain">CC0 / Public Domain</option><option value="all">All open licenses</option></select></label>
    <div className="pexels-search-chips">{QUICK_SEARCHES.map((item) => <button key={item} type="button" className={query === item ? 'active' : ''} onClick={() => setQuery(item)}>{item}</button>)}</div>
    {error && <p className="stock-search-error"><AlertCircle size={14} /> {error}</p>}
    {loading && !audio.length && <div className="stock-search-status"><LoaderCircle className="spin" size={18} /> Searching Openverse…</div>}
    {!loading && !error && !audio.length && <div className="stock-search-status">{emptyMessage(licenseFilter)}</div>}
    <div className="stock-audio-list">{audio.map((item) => <article key={item.id} className="stock-audio-row"><button type="button" className="stock-audio-play" onClick={() => togglePreview(item)} aria-label={`Preview ${item.title}`}>{playingId === item.id ? <Pause size={14} /> : <Play size={14} />}</button><div><strong>{item.title}</strong><span className="stock-audio-progress" /><small>{formatDuration(item.duration * 1000)} · {licenseLabel(item.license)} · {item.creator}</small></div><button type="button" className="stock-audio-add" disabled={addedIds.has(item.id) || importingId === item.id} onClick={() => void add(item)}>{importingId === item.id ? <LoaderCircle size={14} className="spin" /> : addedIds.has(item.id) ? 'Added' : <Plus size={15} />}</button></article>)}</div>
    {hasMore && <button type="button" className="stock-load-more" disabled={loading} onClick={() => void loadMore()}>{loading ? <><LoaderCircle className="spin" size={14} /> Loading</> : 'Load more'}</button>}
    <a className="pexels-attribution" href="https://openverse.org" target="_blank" rel="noreferrer">Sound effects provided by Openverse</a>
  </section>;
}
