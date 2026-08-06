from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class VideoItem:
    id: int
    title: str
    source_url: str
    source: str
    path: Path
    media_type: str
    duration_ms: Optional[int]
    size_bytes: Optional[int]
    status: str
    created_at: str
    metadata: dict[str, Any] | None = None


@dataclass
class AssetItem:
    id: int
    video_id: int
    kind: str
    path: Path
    engine: str
    status: str
    created_at: str
    metadata: dict[str, Any] | None = None


@dataclass
class ProjectItem:
    id: int
    title: str
    primary_video_id: Optional[int]
    created_at: str
    metadata: dict[str, Any] | None = None


@dataclass
class ProjectAssetItem:
    id: int
    project_id: int
    kind: str
    path: Path
    name: str
    status: str
    created_at: str
    source_video_id: Optional[int] = None
    source_asset_id: Optional[int] = None
    metadata: dict[str, Any] | None = None


@dataclass
class SubtitleSegment:
    index: int
    start: float
    end: float
    text: str
