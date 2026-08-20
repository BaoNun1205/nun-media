from __future__ import annotations

import json
import logging
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..types import StockError, StockVideo

logger = logging.getLogger(__name__)


class PexelsProvider:
    """Small wrapper around the official Pexels video endpoints."""

    API_ROOT = "https://api.pexels.com/v1/videos"
    # Pexels currently sits behind Cloudflare. urllib's default Python user
    # agent is rejected there with Cloudflare 1010, even for a valid key.
    BROWSER_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self, api_key: str, timeout_seconds: int = 15) -> None:
        self.api_key = self.normalize_api_key(api_key)
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def normalize_api_key(value: str | None) -> str:
        """Store and send Pexels' raw key, even if a header was pasted by mistake."""
        key = (value or "").strip()
        lowered = key.lower()
        if lowered.startswith("authorization:"):
            key = key.split(":", 1)[1].strip()
            lowered = key.lower()
        if lowered.startswith("bearer "):
            key = key[7:].strip()
        return key

    def _safe_request_context(self, url: str) -> dict[str, Any]:
        key = self.api_key
        return {
            "endpoint": url,
            "key_present": bool(key),
            "key_length": len(key),
            "key_prefix": key[:4],
            "key_suffix": key[-4:] if key else "",
        }

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise StockError("Pexels is not configured. Set PEXELS_API_KEY on the backend.", 503)
        url = f"{self.API_ROOT}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": self.BROWSER_USER_AGENT,
            },
        )
        context = self._safe_request_context(url)
        logger.debug("Pexels request: %s", context)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed Pexels API root
                body = response.read().decode("utf-8")
                logger.debug("Pexels response: endpoint=%s status=%s", url, response.status)
                return json.loads(body)
        except HTTPError as exc:
            # Consume the body so urllib can release its connection. Do not pass
            # it to clients: provider responses can be inconsistent and do not
            # add actionable detail beyond the stable status below.
            body = exc.read().decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")[:1000]
            logger.warning("Pexels HTTP error: status=%s context=%s response_body=%s", exc.code, context, body)
            if exc.code == 401:
                raise StockError("Pexels rejected the configured API key (401). Check the key in Settings.", 401) from exc
            if exc.code == 403:
                if "browser_signature_banned" in body or "error 1010" in body.lower():
                    raise StockError("Pexels/Cloudflare blocked this request signature (403/1010), not the API key. Please update the backend and try again.", 403) from exc
                raise StockError("Pexels denied this API key (403). Nun Media sent the raw key in the Authorization header; verify the key is active in the Pexels dashboard.", 403) from exc
            if exc.code == 429:
                raise StockError("Pexels rate limit reached. Please try again shortly.", 429) from exc
            raise StockError(f"Pexels request failed ({exc.code}).", 502) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            logger.warning("Pexels network error: context=%s error=%s", context, exc)
            raise StockError("Pexels is unavailable or timed out. Please try again.", 504) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Pexels invalid response: context=%s error=%s", context, exc)
            raise StockError("Pexels returned an invalid response.", 502) from exc

    @staticmethod
    def normalize_video(raw: dict[str, Any]) -> StockVideo:
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        video_id = int(raw.get("id") or 0)
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
        duration = int(raw.get("duration") or 0)
        title = str(raw.get("url") or "Pexels video").rstrip("/").split("/")[-1].replace("-", " ").strip()
        return StockVideo(
            provider="pexels",
            provider_video_id=video_id,
            title=(title.title() or "Pexels video")[:120],
            duration_seconds=max(0, duration),
            width=max(0, width),
            height=max(0, height),
            thumbnail_url=str(raw.get("image") or ""),
            page_url=str(raw.get("url") or ""),
            creator_name=str(user.get("name") or "Pexels creator"),
            creator_url=str(user.get("url") or ""),
        )

    def search_videos(self, query: str, page: int, per_page: int) -> dict[str, Any]:
        payload = self._request_json("/search", {
            "query": query,
            "orientation": "landscape",
            "size": "medium",
            "locale": "vi-VN",
            "page": page,
            "per_page": per_page,
        })
        videos = [self.normalize_video(item).payload() for item in payload.get("videos", []) if isinstance(item, dict)]
        return {
            "videos": videos,
            "page": int(payload.get("page") or page),
            "perPage": int(payload.get("per_page") or per_page),
            "totalResults": int(payload.get("total_results") or 0),
            "hasMore": bool(payload.get("next_page")),
        }

    def get_video(self, video_id: int) -> dict[str, Any]:
        if video_id <= 0:
            raise StockError("Invalid Pexels video id.", 400)
        return self._request_json(f"/videos/{video_id}")
