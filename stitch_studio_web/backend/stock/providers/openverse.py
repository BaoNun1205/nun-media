from __future__ import annotations

import json
import logging
import socket
from collections import Counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..types import StockError
from ..openverse_token import OpenverseTokenManager

logger = logging.getLogger(__name__)


class OpenverseProvider:
    """Openverse Audio API client; OAuth lifecycle is delegated to the token manager."""

    API_ROOT = "https://api.openverse.org/v1/audio/"
    LICENSE_FILTERS = {
        "commercial": ("cc0", "pdm", "by"),
        "public_domain": ("cc0", "pdm"),
        "all": (),
    }
    LICENSE_SCORES = {"cc0": 300, "pdm": 250, "by": 200}
    SOUND_SOURCES = {"freesound", "wikimedia", "jamendo", "internet_archive"}

    def __init__(self, token_manager: OpenverseTokenManager, timeout_seconds: int = 15) -> None:
        self._token_manager = token_manager
        self._timeout_seconds = timeout_seconds

    def _request_once(self, url: str, token: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "Nun-Studio/1.0"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310 - fixed Openverse API root
                logger.info("Openverse API response: status=%s", getattr(response, "status", 200))
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise StockError("Openverse is unavailable or timed out. Please try again.", 504) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StockError("Openverse returned an invalid response.", 502) from exc

    def _request_url_json(self, url: str) -> dict[str, Any]:
        token = self._token_manager.get_access_token()
        try:
            return self._request_once(url, token)
        except HTTPError as exc:
            if exc.code != 401:
                if exc.code == 429:
                    raise StockError("Openverse rate limit reached. Please try again shortly.", 429) from exc
                raise StockError(f"Openverse search failed ({exc.code}).", 502) from exc
        # The access token may have been revoked early. Refresh once only.
        logger.info("Openverse audio request returned 401; refreshing token once")
        try:
            refreshed_token = self._token_manager.get_access_token(force_refresh=True, rejected_token=token)
            return self._request_once(url, refreshed_token)
        except HTTPError as retry_exc:
            if retry_exc.code == 429:
                raise StockError("Openverse rate limit reached. Please try again shortly.", 429) from retry_exc
            logger.warning("Openverse audio request failed after one token refresh: status=%s", retry_exc.code)
            raise StockError("Openverse authorization failed after refreshing the access token.", 502) from retry_exc

    def _request_json(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._request_url_json(f"{self.API_ROOT}?{urlencode(params)}")

    @staticmethod
    def _license_slug(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "")

    @staticmethod
    def _tag_names(raw: dict[str, Any]) -> list[str]:
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        return [str(tag.get("name") or "").strip() for tag in tags if isinstance(tag, dict) and str(tag.get("name") or "").strip()]

    @staticmethod
    def _has_playable_url(url: str) -> bool:
        return url.startswith("https://")

    @classmethod
    def _rank_audio(cls, raw: dict[str, Any], query_terms: set[str]) -> int:
        license_slug = cls._license_slug(raw.get("license"))
        category = str(raw.get("category") or "").strip().lower()
        provider = str(raw.get("provider") or raw.get("source") or "").strip().lower()
        title = str(raw.get("title") or "").lower()
        description = str(raw.get("description") or "").lower()
        tags = " ".join(cls._tag_names(raw)).lower()
        haystack = f"{title} {tags} {description}"
        score = cls.LICENSE_SCORES.get(license_slug, 0)
        if category == "sound_effect":
            score += 80
        if provider in cls.SOUND_SOURCES:
            score += 30
        score += sum(20 if term in title else 8 if term in tags else 3 if term in description else 0 for term in query_terms)
        try:
            duration_seconds = float(raw.get("duration") or 0) / 1000.0
        except (TypeError, ValueError):
            duration_seconds = 0
        if 0.25 <= duration_seconds <= 900:
            score += 10
        elif duration_seconds > 0:
            score += 2
        return score

    @classmethod
    def normalize_audio(cls, raw: dict[str, Any], query_terms: set[str] | None = None) -> dict[str, Any] | None:
        audio_set = raw.get("audio_set") if isinstance(raw.get("audio_set"), dict) else {}
        files = audio_set.get("files") if isinstance(audio_set.get("files"), list) else []
        download_url = str(raw.get("url") or "") or next((str(item.get("url") or "") for item in files if isinstance(item, dict) and item.get("url")), "")
        if not cls._has_playable_url(download_url):
            return None
        try:
            duration_seconds = max(0, float(raw.get("duration") or 0) / 1000.0)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        return {
            "provider": "openverse",
            "id": str(raw.get("id") or ""),
            "title": str(raw.get("title") or "Untitled sound effect")[:160],
            # Openverse's audio duration field is milliseconds; the frontend
            # and project metadata use seconds for provider result values.
            "duration": duration_seconds,
            "creator": str(raw.get("creator") or "Openverse creator"),
            "license": cls._license_slug(raw.get("license")),
            "licenseUrl": str(raw.get("license_url") or ""),
            "pageUrl": str(raw.get("foreign_landing_url") or raw.get("url") or ""),
            "previewUrl": download_url,
            "downloadUrl": download_url,
            "attribution": str(raw.get("attribution") or ""),
            "category": str(raw.get("category") or "").strip().lower(),
            "source": str(raw.get("source") or raw.get("provider") or ""),
            "rank": cls._rank_audio(raw, query_terms or set()),
        }

    def search_audio(self, query: str, page: int, page_size: int, license_filter: str = "commercial") -> dict[str, Any]:
        selected_filter = license_filter if license_filter in self.LICENSE_FILTERS else "commercial"
        params: dict[str, Any] = {
            "q": query,
            "page": page,
            "page_size": page_size,
        }
        allowed_licenses = self.LICENSE_FILTERS[selected_filter]
        if allowed_licenses:
            # Openverse accepts comma-separated slugs. Category is deliberately
            # not sent: live responses often use null/none for sound effects.
            params["license"] = ",".join(allowed_licenses)
        logger.info("Openverse audio search request: params=%s", params)
        payload = self._request_json(params)
        raw_results = [item for item in payload.get("results", []) if isinstance(item, dict)]
        before_licenses = Counter(self._license_slug(item.get("license")) or "unknown" for item in raw_results)
        before_categories = Counter(str(item.get("category") or "none").strip().lower() or "none" for item in raw_results)
        query_terms = {term.lower() for term in query.replace("_", " ").split() if term.strip()}
        results = [self.normalize_audio(item, query_terms) for item in raw_results]
        results = [item for item in results if item is not None]
        if allowed_licenses:
            allowed = set(allowed_licenses)
            results = [item for item in results if item["license"] in allowed]
        results.sort(key=lambda item: (-int(item["rank"]), item["title"].lower(), item["id"]))
        logger.info(
            "Openverse audio search counts: api_total=%s raw=%s licenses=%s categories=%s normalized=%s",
            payload.get("result_count", 0), len(raw_results), dict(before_licenses), dict(before_categories), len(results),
        )
        return {
            "audio": results,
            "page": page,
            "perPage": page_size,
            "totalResults": int(payload.get("result_count") or 0),
            "hasMore": bool(payload.get("next")),
            "licenseFilter": selected_filter,
        }

    def get_audio(self, audio_id: str) -> dict[str, Any]:
        if not audio_id or len(audio_id) > 120:
            raise StockError("Invalid Openverse audio id.", 400)
        return self._request_url_json(f"{self.API_ROOT}{audio_id}/")
