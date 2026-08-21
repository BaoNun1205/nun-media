import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Plus, Search } from 'lucide-react';
import { studioApi } from '../../../services/api';
import type { PexelsPhoto, ProjectAsset } from '../../../types/studio';

const QUICK_SEARCHES = [['Dark Forest', 'dark foggy forest'], ['Abandoned House', 'abandoned house'], ['Foggy Road', 'foggy road'], ['Storm Clouds', 'storm clouds'], ['Rainy Window', 'rainy window'], ['Cemetery', 'cemetery night'], ['Full Moon', 'full moon night'], ['Dark Room', 'dark room'], ['Old Hallway', 'old hallway'], ['Night City', 'night city']] as const;

export function PexelsImageSearchView({ projectId, projectAssets, onImported, onMessage }: { projectId: number; projectAssets: ProjectAsset[]; onImported: () => Promise<void>; onMessage: (message: string) => void }) {
  const [query, setQuery] = useState('dark foggy forest');
  const [photos, setPhotos] = useState<PexelsPhoto[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importingId, setImportingId] = useState<number | null>(null);
  const [addedIds, setAddedIds] = useState<Set<number>>(() => new Set());
  const queryRef = useRef(query);

  useEffect(() => setAddedIds(new Set(projectAssets.filter((asset) => asset.kind === 'image' && asset.metadata.stock_provider === 'pexels').map((asset) => Number(asset.metadata.stock_photo_id || 0)).filter(Boolean))), [projectAssets]);
  useEffect(() => {
    const activeQuery = query.trim(); queryRef.current = activeQuery;
    if (!activeQuery) { setPhotos([]); setLoading(false); setError(''); return undefined; }
    setLoading(true); setError('');
    const timer = window.setTimeout(() => void studioApi.searchPexelsPhotos(activeQuery).then((result) => {
      if (queryRef.current === activeQuery) { setPhotos(result.photos); setPage(result.page); setHasMore(result.hasMore); }
    }).catch((reason: unknown) => queryRef.current === activeQuery && setError(reason instanceof Error ? reason.message : 'Unable to search Pexels.')).finally(() => queryRef.current === activeQuery && setLoading(false)), 400);
    return () => window.clearTimeout(timer);
  }, [query]);
  async function add(photo: PexelsPhoto) {
    if (!projectId) return onMessage('Open a workspace project before adding a Pexels photo.');
    if (importingId || addedIds.has(photo.id)) return;
    setImportingId(photo.id); setError('');
    try { const result = await studioApi.importPexelsPhoto(projectId, photo.id); setAddedIds((current) => new Set(current).add(photo.id)); await onImported(); onMessage(result.alreadyImported ? 'This Pexels photo is already in Assets.' : 'Pexels photo added to Assets.'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to import this Pexels photo.'); }
    finally { setImportingId(null); }
  }
  async function loadMore() {
    const activeQuery = query.trim(); if (loading || !hasMore || !activeQuery) return;
    setLoading(true); setError('');
    try { const result = await studioApi.searchPexelsPhotos(activeQuery, page + 1); if (queryRef.current === activeQuery) { setPhotos((current) => [...current, ...result.photos.filter((photo) => !current.some((item) => item.id === photo.id))]); setPage(result.page); setHasMore(result.hasMore); } }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load more Pexels photos.'); }
    finally { setLoading(false); }
  }
  return <section className="pexels-search-view">
    <label className="pexels-search-input"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search photos on Pexels..." /></label>
    <div className="pexels-search-chips">{QUICK_SEARCHES.map(([label, value]) => <button key={label} type="button" className={query === value ? 'active' : ''} onClick={() => setQuery(value)}>{label}</button>)}</div>
    {error && <p className="stock-search-error"><AlertCircle size={14} /> {error}</p>}
    {loading && !photos.length && <div className="stock-search-status"><LoaderCircle className="spin" size={18} /> Searching Pexels…</div>}
    {!loading && !error && !photos.length && <div className="stock-search-status">No Pexels photos found. Try a different search.</div>}
    <div className="stock-image-grid">{photos.map((photo) => <article key={photo.id} className="stock-image-card"><div className="stock-image-thumb">{photo.thumbnailUrl ? <img src={photo.thumbnailUrl} alt="" loading="lazy" /> : <span>Image</span>}<button type="button" className="stock-video-add" disabled={addedIds.has(photo.id) || importingId === photo.id} onClick={() => void add(photo)}>{importingId === photo.id ? <LoaderCircle size={14} className="spin" /> : addedIds.has(photo.id) ? 'Added' : <Plus size={15} />}</button></div><strong>{photo.title}</strong><small>{photo.creator?.name || 'Pexels creator'}</small></article>)}</div>
    {hasMore && <button type="button" className="stock-load-more" disabled={loading} onClick={() => void loadMore()}>{loading ? <><LoaderCircle className="spin" size={14} /> Loading</> : 'Load more'}</button>}
    <a className="pexels-attribution" href="https://www.pexels.com" target="_blank" rel="noreferrer">Photos provided by Pexels</a>
  </section>;
}
