from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class StockError(RuntimeError):
    """A safe, user-facing error from a stock provider."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StockVideo:
    provider: str
    provider_video_id: int
    title: str
    duration_seconds: int
    width: int
    height: int
    thumbnail_url: str
    page_url: str
    creator_name: str
    creator_url: str

    def payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "id": self.provider_video_id,
            "title": self.title,
            "duration": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "thumbnailUrl": self.thumbnail_url,
            "pageUrl": self.page_url,
            "creator": {"name": self.creator_name, "url": self.creator_url},
        }
