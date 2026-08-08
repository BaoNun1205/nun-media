from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .models import AssetItem, ProjectAssetItem, ProjectItem, VideoItem, YoutubeChannelItem, YoutubePromptItem


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        journal_path = db_path.with_name(f"{db_path.name}-journal")
        if journal_path.exists() and db_path.stat().st_size == 0:
            journal_path.unlink()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=OFF")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL UNIQUE,
                media_type TEXT NOT NULL DEFAULT 'video',
                duration_ms INTEGER,
                size_bytes INTEGER,
                thumbnail TEXT,
                status TEXT NOT NULL DEFAULT 'downloaded',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                engine TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ready',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                primary_video_id INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(primary_video_id) REFERENCES videos(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS project_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                source_video_id INTEGER,
                source_asset_id INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(source_video_id) REFERENCES videos(id) ON DELETE SET NULL,
                FOREIGN KEY(source_asset_id) REFERENCES assets(id) ON DELETE SET NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_assets_source_video
            ON project_assets(project_id, source_video_id)
            WHERE source_video_id IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_assets_source_asset
            ON project_assets(project_id, source_asset_id)
            WHERE source_asset_id IS NOT NULL;
            
            CREATE TABLE IF NOT EXISTS youtube_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                avatar_path TEXT,
                references_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS youtube_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                references_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(channel_id) REFERENCES youtube_channels(id) ON DELETE CASCADE
            );
            """
        )
        try:
            self.conn.execute("ALTER TABLE youtube_channels ADD COLUMN references_json TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # Column already exists or table was just created
        
        self.conn.commit()
        # Project workspaces are now explicit. Downloads stay in the asset
        # library until the user creates a project and adds them.

    def upsert_video(
        self,
        *,
        title: str,
        source_url: str,
        source: str,
        path: Path,
        media_type: str,
        duration_ms: Optional[int],
        size_bytes: Optional[int],
        metadata: dict,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO videos (
                title, source_url, source, path, media_type, duration_ms,
                size_bytes, thumbnail, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title = excluded.title,
                source_url = excluded.source_url,
                source = excluded.source,
                media_type = excluded.media_type,
                duration_ms = excluded.duration_ms,
                size_bytes = excluded.size_bytes,
                thumbnail = excluded.thumbnail,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                title,
                source_url,
                source,
                str(path),
                media_type,
                duration_ms,
                size_bytes,
                metadata.get("thumbnail"),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = self.conn.execute("SELECT id FROM videos WHERE path = ?", (str(path),)).fetchone()
        return int(row["id"])

    def list_videos(self) -> list[VideoItem]:
        rows = self.conn.execute(
            """
            SELECT * FROM videos
            ORDER BY datetime(created_at) DESC, id DESC
            """
        ).fetchall()
        return [self._video_from_row(row) for row in rows]

    def get_video(self, video_id: int) -> Optional[VideoItem]:
        row = self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return self._video_from_row(row) if row else None

    def create_project(self, title: str, video_ids: Iterable[int] = ()) -> ProjectItem:
        video_ids = [int(item) for item in video_ids]
        primary_video_id = video_ids[0] if video_ids else None
        cur = self.conn.execute(
            """
            INSERT INTO projects (title, primary_video_id, metadata_json)
            VALUES (?, ?, ?)
            """,
            (title, primary_video_id, json.dumps({}, ensure_ascii=False)),
        )
        project_id = int(cur.lastrowid)
        self.conn.commit()
        for video_id in video_ids:
            self.attach_video_to_project(project_id, video_id)
        project = self.get_project(project_id)
        assert project is not None
        return project

    def list_projects(self) -> list[ProjectItem]:
        rows = self.conn.execute(
            """
            SELECT * FROM projects
            ORDER BY datetime(updated_at) DESC, id DESC
            """
        ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project(self, project_id: int) -> Optional[ProjectItem]:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def find_project_for_video(self, video_id: int) -> Optional[ProjectItem]:
        row = self.conn.execute(
            """
            SELECT p.* FROM projects p
            JOIN project_assets pa ON pa.project_id = p.id
            WHERE pa.source_video_id = ?
            ORDER BY datetime(p.updated_at) DESC, p.id DESC
            LIMIT 1
            """,
            (int(video_id),),
        ).fetchone()
        return self._project_from_row(row) if row else None

    def rename_workspace_project(self, project_id: int, title: str) -> None:
        self.conn.execute(
            "UPDATE projects SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, int(project_id)),
        )
        self.conn.commit()

    def update_project_metadata(self, project_id: int, metadata: dict) -> Optional[ProjectItem]:
        self.conn.execute(
            "UPDATE projects SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(metadata or {}, ensure_ascii=False), int(project_id)),
        )
        self.conn.commit()
        return self.get_project(project_id)

    def delete_workspace_project(self, project_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM projects WHERE id = ?", (int(project_id),))
        self.conn.commit()
        return cur.rowcount > 0

    def attach_video_to_project(self, project_id: int, video_id: int) -> Optional[ProjectAssetItem]:
        video = self.get_video(video_id)
        project = self.get_project(project_id)
        if not video or not project:
            return None
        metadata = {"source": "download-library", "duration_ms": video.duration_ms, "size_bytes": video.size_bytes}
        self.conn.execute(
            """
            INSERT INTO project_assets (
                project_id, kind, path, name, status, source_video_id, metadata_json
            )
            VALUES (?, 'video', ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_video_id) WHERE source_video_id IS NOT NULL DO UPDATE SET
                path = excluded.path,
                name = excluded.name,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(project_id),
                str(video.path),
                video.path.name,
                video.status,
                int(video_id),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        if project.primary_video_id is None:
            self.conn.execute(
                "UPDATE projects SET primary_video_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(video_id), int(project_id)),
            )
        else:
            self.conn.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(project_id),),
            )
        self.conn.commit()
        return self.project_asset_for_video(project_id, video_id)

    def project_asset_for_video(self, project_id: int, video_id: int) -> Optional[ProjectAssetItem]:
        row = self.conn.execute(
            "SELECT * FROM project_assets WHERE project_id = ? AND source_video_id = ?",
            (int(project_id), int(video_id)),
        ).fetchone()
        return self._project_asset_from_row(row) if row else None

    def project_asset_for_asset(self, project_id: int, asset_id: int) -> Optional[ProjectAssetItem]:
        row = self.conn.execute(
            "SELECT * FROM project_assets WHERE project_id = ? AND source_asset_id = ?",
            (int(project_id), int(asset_id)),
        ).fetchone()
        return self._project_asset_from_row(row) if row else None

    def project_video_reference_count(self, video_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM project_assets WHERE source_video_id = ?",
            (int(video_id),),
        ).fetchone()
        return int(row["count"] or 0) if row else 0

    def project_asset_reference_count(self, asset_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM project_assets WHERE source_asset_id = ?",
            (int(asset_id),),
        ).fetchone()
        return int(row["count"] or 0) if row else 0

    def get_youtube_channels(self) -> list[YoutubeChannelItem]:
        cur = self.conn.execute("SELECT * FROM youtube_channels ORDER BY updated_at DESC")
        return [YoutubeChannelItem(**dict(row)) for row in cur]

    def create_youtube_channel(self, name: str, avatar_path: Optional[str] = None) -> YoutubeChannelItem:
        cur = self.conn.execute(
            "INSERT INTO youtube_channels (name, avatar_path, references_json) VALUES (?, ?, '[]')",
            (name, avatar_path),
        )
        self.conn.commit()
        channel_id = cur.lastrowid
        cur = self.conn.execute("SELECT * FROM youtube_channels WHERE id = ?", (channel_id,))
        return YoutubeChannelItem(**dict(cur.fetchone()))

    def update_youtube_channel(self, channel_id: int, name: Optional[str] = None, references_json: Optional[str] = None) -> Optional[YoutubeChannelItem]:
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if references_json is not None:
            updates.append("references_json = ?")
            params.append(references_json)
        
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE youtube_channels SET {', '.join(updates)} WHERE id = ?"
            params.append(channel_id)
            cur = self.conn.execute(query, tuple(params))
            if cur.rowcount == 0:
                return None
            self.conn.commit()
            
        cur = self.conn.execute("SELECT * FROM youtube_channels WHERE id = ?", (channel_id,))
        row = cur.fetchone()
        return YoutubeChannelItem(**dict(row)) if row else None
        
    def delete_youtube_channel(self, channel_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM youtube_channels WHERE id = ?", (channel_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_youtube_prompts(self, channel_id: int) -> list[YoutubePromptItem]:
        cur = self.conn.execute("SELECT id, channel_id, name, content, created_at, updated_at FROM youtube_prompts WHERE channel_id = ? ORDER BY updated_at DESC", (channel_id,))
        return [YoutubePromptItem(**dict(row)) for row in cur]

    def create_youtube_prompt(self, channel_id: int, name: str, content: str) -> YoutubePromptItem:
        cur = self.conn.execute(
            "INSERT INTO youtube_prompts (channel_id, name, content) VALUES (?, ?, ?)",
            (channel_id, name, content),
        )
        self.conn.commit()
        prompt_id = cur.lastrowid
        cur = self.conn.execute("SELECT id, channel_id, name, content, created_at, updated_at FROM youtube_prompts WHERE id = ?", (prompt_id,))
        return YoutubePromptItem(**dict(cur.fetchone()))

    def update_youtube_prompt(self, prompt_id: int, name: str, content: str) -> Optional[YoutubePromptItem]:
        cur = self.conn.execute(
            "UPDATE youtube_prompts SET name = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (name, content, prompt_id),
        )
        if cur.rowcount == 0:
            return None
        self.conn.commit()
        cur = self.conn.execute("SELECT id, channel_id, name, content, created_at, updated_at FROM youtube_prompts WHERE id = ?", (prompt_id,))
        return YoutubePromptItem(**dict(cur.fetchone()))

    def delete_youtube_prompt(self, prompt_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM youtube_prompts WHERE id = ?", (prompt_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def add_project_asset(
        self,
        *,
        project_id: int,
        kind: str,
        path: Path,
        name: str | None = None,
        status: str = "ready",
        source_video_id: int | None = None,
        source_asset_id: int | None = None,
        metadata: Optional[dict] = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO project_assets (
                project_id, kind, path, name, status, source_video_id, source_asset_id, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(project_id),
                kind,
                str(path),
                name or path.name,
                status,
                source_video_id,
                source_asset_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(project_id),))
        self.conn.commit()
        return int(cur.lastrowid)

    def list_project_assets(self, project_id: int) -> list[ProjectAssetItem]:
        rows = self.conn.execute(
            """
            SELECT * FROM project_assets
            WHERE project_id = ?
            ORDER BY
                CASE kind WHEN 'video' THEN 0 WHEN 'srt' THEN 1 WHEN 'audio' THEN 2 ELSE 3 END,
                datetime(created_at) DESC,
                id DESC
            """,
            (int(project_id),),
        ).fetchall()
        return [self._project_asset_from_row(row) for row in rows]

    def get_project_asset(self, project_asset_id: int) -> Optional[ProjectAssetItem]:
        row = self.conn.execute("SELECT * FROM project_assets WHERE id = ?", (int(project_asset_id),)).fetchone()
        return self._project_asset_from_row(row) if row else None

    def delete_project_asset(self, project_asset_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM project_assets WHERE id = ?", (int(project_asset_id),))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_video_duration(self, video_id: int, duration_ms: int) -> None:
        self.conn.execute(
            "UPDATE videos SET duration_ms = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (max(1, int(duration_ms)), video_id),
        )
        self.conn.commit()

    def add_asset(
        self,
        *,
        video_id: int,
        kind: str,
        path: Path,
        engine: str,
        status: str = "ready",
        metadata: Optional[dict] = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO assets (video_id, kind, path, engine, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                kind,
                str(path),
                engine,
                status,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_assets(self, video_id: int) -> list[AssetItem]:
        rows = self.conn.execute(
            """
            SELECT * FROM assets
            WHERE video_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (video_id,),
        ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def get_asset(self, asset_id: int) -> Optional[AssetItem]:
        row = self.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return self._asset_from_row(row) if row else None

    def delete_asset(self, asset_id: int) -> bool:
        self.conn.execute("DELETE FROM project_assets WHERE source_asset_id = ?", (asset_id,))
        cursor = self.conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_asset_metadata(self, asset_id: int, metadata: dict) -> None:
        self.conn.execute(
            "UPDATE assets SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=False), asset_id),
        )
        self.conn.commit()

    def latest_asset(self, video_id: int, kind: str) -> Optional[AssetItem]:
        row = self.conn.execute(
            """
            SELECT * FROM assets
            WHERE video_id = ? AND kind = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
            """,
            (video_id, kind),
        ).fetchone()
        return self._asset_from_row(row) if row else None

    def delete_video(self, video_id: int) -> bool:
        self.conn.execute("DELETE FROM project_assets WHERE source_video_id = ?", (video_id,))
        self.conn.execute("DELETE FROM assets WHERE video_id = ?", (video_id,))
        cur = self.conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def rename_project(self, video_id: int, title: str) -> list[int]:
        video = self.get_video(video_id)
        if not video:
            return []
        project_id = self.project_id_for(video)
        matching_ids = [item.id for item in self.list_videos() if self.project_id_for(item) == project_id]
        if not matching_ids:
            return []
        placeholders = ",".join("?" for _ in matching_ids)
        self.conn.execute(
            f"UPDATE videos SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            (title, *matching_ids),
        )
        self.conn.commit()
        return matching_ids

    def update_video_metadata(self, video_id: int, metadata: dict) -> None:
        self.conn.execute(
            "UPDATE videos SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=False), video_id),
        )
        self.conn.commit()

    def project_id_for(self, video: VideoItem) -> int:
        current = video
        seen: set[int] = set()
        while current.id not in seen:
            seen.add(current.id)
            metadata = current.metadata or {}
            project_id = metadata.get("project_id")
            if project_id:
                return int(project_id)
            parent_id = metadata.get("source_video_id")
            if not parent_id:
                return current.id
            parent = self.get_video(int(parent_id))
            if not parent:
                return current.id
            current = parent
        return video.id

    def find_ancestor_without_state(self, video_id: int, state_key: str) -> Optional[VideoItem]:
        current = self.get_video(video_id)
        seen: set[int] = set()
        while current and current.id not in seen:
            seen.add(current.id)
            parent_id = (current.metadata or {}).get("source_video_id")
            if not parent_id:
                return None
            parent = self.get_video(int(parent_id))
            if not parent:
                return None
            parent_state = (parent.metadata or {}).get("processing_state") or {}
            if not parent_state.get(state_key, False):
                return parent
            current = parent
        return None

    def path_is_referenced(self, path: Path) -> bool:
        value = str(path)
        video = self.conn.execute("SELECT 1 FROM videos WHERE path = ? LIMIT 1", (value,)).fetchone()
        if video:
            return True
        asset = self.conn.execute("SELECT 1 FROM assets WHERE path = ? LIMIT 1", (value,)).fetchone()
        if asset:
            return True
        project_asset = self.conn.execute("SELECT 1 FROM project_assets WHERE path = ? LIMIT 1", (value,)).fetchone()
        return bool(project_asset)

    def import_local_files(self, paths: Iterable[Path]) -> list[int]:
        ids: list[int] = []
        for path in paths:
            if not path.exists() or not path.is_file():
                continue
            ids.append(
                self.upsert_video(
                    title=path.name,
                    source_url=str(path),
                    source="local",
                    path=path,
                    media_type=_guess_media_type(path),
                    duration_ms=None,
                    size_bytes=path.stat().st_size,
                    metadata={},
                )
            )
        return ids

    @staticmethod
    def _video_from_row(row: sqlite3.Row) -> VideoItem:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return VideoItem(
            id=int(row["id"]),
            title=row["title"],
            source_url=row["source_url"],
            source=row["source"],
            path=Path(row["path"]),
            media_type=row["media_type"],
            duration_ms=row["duration_ms"],
            size_bytes=row["size_bytes"],
            status=row["status"],
            created_at=row["created_at"],
            metadata=metadata,
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> AssetItem:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return AssetItem(
            id=int(row["id"]),
            video_id=int(row["video_id"]),
            kind=row["kind"],
            path=Path(row["path"]),
            engine=row["engine"],
            status=row["status"],
            created_at=row["created_at"],
            metadata=metadata,
        )

    def _ensure_legacy_projects(self) -> None:
        videos = [
            video
            for video in self.list_videos()
            if not (video.metadata or {}).get("hidden")
        ]
        existing = {
            int(row["source_video_id"])
            for row in self.conn.execute(
                "SELECT source_video_id FROM project_assets WHERE source_video_id IS NOT NULL"
            ).fetchall()
        }
        grouped: dict[int, list[VideoItem]] = {}
        for video in videos:
            if video.id in existing:
                continue
            grouped.setdefault(self.project_id_for(video), []).append(video)
        for group in grouped.values():
            ordered = sorted(group, key=lambda item: item.id, reverse=True)
            primary = ordered[0]
            cur = self.conn.execute(
                """
                INSERT INTO projects (title, primary_video_id, metadata_json)
                VALUES (?, ?, ?)
                """,
                (primary.title, primary.id, json.dumps({"migrated_from_video_id": primary.id}, ensure_ascii=False)),
            )
            project_id = int(cur.lastrowid)
            for video in ordered:
                self.conn.execute(
                    """
                    INSERT INTO project_assets (
                        project_id, kind, path, name, status, source_video_id, metadata_json
                    )
                    VALUES (?, 'video', ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        str(video.path),
                        video.path.name,
                        video.status,
                        video.id,
                        json.dumps({"source": "legacy-video-project", "duration_ms": video.duration_ms, "size_bytes": video.size_bytes}, ensure_ascii=False),
                    ),
                )
        if grouped:
            self.conn.commit()

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectItem:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return ProjectItem(
            id=int(row["id"]),
            title=row["title"],
            primary_video_id=int(row["primary_video_id"]) if row["primary_video_id"] is not None else None,
            created_at=row["created_at"],
            metadata=metadata,
        )

    @staticmethod
    def _project_asset_from_row(row: sqlite3.Row) -> ProjectAssetItem:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return ProjectAssetItem(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            kind=row["kind"],
            path=Path(row["path"]),
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            source_video_id=int(row["source_video_id"]) if row["source_video_id"] is not None else None,
            source_asset_id=int(row["source_asset_id"]) if row["source_asset_id"] is not None else None,
            metadata=metadata,
        )


def _guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
        return "audio"
    return "video"
