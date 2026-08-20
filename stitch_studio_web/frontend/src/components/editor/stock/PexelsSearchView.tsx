import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Plus, Search } from 'lucide-react';
import { formatDuration } from '../../../lib/studio';
import { studioApi } from '../../../services/api';
import type { PexelsVideo, ProjectAsset } from '../../../types/studio';

const QUICK_SEARCHES = [
  ['Dark Forest', 'dark foggy forest cinematic'],
  ['Heavy Rain', 'heavy rain dark cinematic'],
  ['Storm Clouds', 'dark storm clouds timelapse'],
  ['Fog', 'fog cinematic'],
  ['Night Road', 'night road rain'],
  ['Lightning', 'lightning storm night'],
  ['Abandoned House', 'abandoned house dark'],
  ['Rainy Window', 'rain window night'],
  ['Dark Ocean', 'dark ocean waves'],
  ['Full Moon', 'full moon clouds night'],
  ['Cemetery', 'cemetery fog night'],
  ['Dark City', 'dark city rain night'],
] as const;

function asDuration(seconds: number) {
  return formatDuration(Math.max(0, seconds) * 1000);
}

function PexelsVideoCard({ video, added, importing, onAdd }: {
  video: PexelsVideo;
  added: boolean;
  importing: boolean;
  onAdd: () => void;
}) {
  const creator = video.creator?.name || 'Pexels creator';
  return <article className={`stock-video-card ${added ? 'added' : ''}`} title={`By ${creator} on Pexels`}>
    <div className="stock-video-thumb">
      {video.thumbnailUrl ? <img src={video.thumbnailUrl} alt="" loading="lazy" /> : <span>Video</span>}
      <em>{asDuration(video.duration)}</em>
      <button
        type="button"
        className="stock-video-add"
        disabled={added || importing}
        onClick={onAdd}
        aria-label={added ? `${video.title} added` : `Add ${video.title}`}
      >
        {importing ? <LoaderCircle size={14} className="spin" /> : added ? 'Added' : <Plus size={15} />}
      </button>
    </div>
    <strong>{video.title}</strong>
    <small>{creator}</small>
  </article>;
}

export function PexelsSearchView({ projectId, projectAssets, onImported, onMessage }: {
  projectId: number;
  projectAssets: ProjectAsset[];
  onImported: () => Promise<void>;
  onMessage: (message: string) => void;
}) {
  const [query, setQuery] = useState('dark foggy forest cinematic');
  const [videos, setVideos] = useState<PexelsVideo[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importingId, setImportingId] = useState<number | null>(null);
  const [addedIds, setAddedIds] = useState<Set<number>>(() => new Set());
  const queryRef = useRef(query);

  useEffect(() => {
    const known = new Set<number>();
    projectAssets.forEach((asset) => {
      if (asset.metadata.stock_provider !== 'pexels') return;
      const id = Number(asset.metadata.stock_video_id || 0);
      if (id > 0) known.add(id);
    });
    setAddedIds(known);
  }, [projectAssets]);

  useEffect(() => {
    const nextQuery = query.trim();
    queryRef.current = nextQuery;
    if (!nextQuery) {
      setVideos([]);
      setLoading(false);
      setError('');
      return undefined;
    }
    setLoading(true);
    setError('');
    const timer = window.setTimeout(() => {
      void studioApi.searchPexelsVideos(nextQuery, 1)
        .then((result) => {
          if (queryRef.current !== nextQuery) return;
          setVideos(result.videos);
          setPage(result.page);
          setHasMore(result.hasMore);
        })
        .catch((reason: unknown) => {
          if (queryRef.current === nextQuery) setError(reason instanceof Error ? reason.message : 'Unable to search Pexels.');
        })
        .finally(() => {
          if (queryRef.current === nextQuery) setLoading(false);
        });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [query]);

  async function add(video: PexelsVideo) {
    if (!projectId) {
      onMessage('Open a workspace project before adding a Pexels video.');
      return;
    }
    if (importingId || addedIds.has(video.id)) return;
    setImportingId(video.id);
    setError('');
    try {
      const result = await studioApi.importPexelsVideo(projectId, video.id);
      setAddedIds((current) => new Set(current).add(video.id));
      await onImported();
      onMessage(result.alreadyImported ? 'This Pexels video is already in Assets.' : 'Pexels video added to Assets.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to import this Pexels video.');
    } finally {
      setImportingId(null);
    }
  }

  async function loadMore() {
    const activeQuery = query.trim();
    if (loading || !hasMore || !activeQuery) return;
    setLoading(true);
    setError('');
    try {
      const result = await studioApi.searchPexelsVideos(activeQuery, page + 1);
      if (queryRef.current !== activeQuery) return;
      setVideos((current) => [...current, ...result.videos.filter((video) => !current.some((item) => item.id === video.id))]);
      setPage(result.page);
      setHasMore(result.hasMore);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load more Pexels videos.');
    } finally {
      setLoading(false);
    }
  }

  return <section className="pexels-search-view">
    <label className="pexels-search-input"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search videos on Pexels..." /></label>
    <div className="pexels-search-chips">{QUICK_SEARCHES.map(([label, value]) => <button key={label} type="button" className={query === value ? 'active' : ''} onClick={() => setQuery(value)}>{label}</button>)}</div>
    {error && <p className="stock-search-error"><AlertCircle size={14} /> {error}</p>}
    {loading && videos.length === 0 ? <div className="stock-search-status"><LoaderCircle className="spin" size={18} /> Searching Pexels…</div> : null}
    {!loading && !error && videos.length === 0 ? <div className="stock-search-status">No Pexels videos found. Try a different search.</div> : null}
    <div className="stock-video-grid">{videos.map((video) => <PexelsVideoCard key={video.id} video={video} added={addedIds.has(video.id)} importing={importingId === video.id} onAdd={() => void add(video)} />)}</div>
    {hasMore && <button type="button" className="stock-load-more" disabled={loading} onClick={() => void loadMore()}>{loading ? <><LoaderCircle className="spin" size={14} /> Loading</> : 'Load more'}</button>}
    <a className="pexels-attribution" href="https://www.pexels.com" target="_blank" rel="noreferrer">Videos provided by Pexels</a>
  </section>;
}
