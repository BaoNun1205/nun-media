from __future__ import annotations

import ipaddress
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .providers.openverse import OpenverseProvider
from .providers.pexels import PexelsProvider
from .types import StockError


MAX_DOWNLOAD_BYTES = 700 * 1024 * 1024
_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


class _AllowedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ValidatedRedirects(HTTPRedirectHandler):
    def __init__(self, validator) -> None:
        super().__init__()
        self.validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    # Pexels currently serves video renditions directly and through Vimeo's
    # documented player URLs. Vimeo may redirect a signed URL to its CDN.
    allowed = (
        hostname.endswith(".pexels.com")
        or hostname.endswith(".vimeo.com")
        or hostname.endswith(".vimeocdn.com")
        or hostname == "vod-progressive.akamaized.net"
    )
    if parsed.scheme != "https" or not allowed:
        raise StockError("Pexels returned an unsupported video file URL.", 400)


def _validate_pexels_photo_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname.endswith(".pexels.com"):
        raise StockError("Pexels returned an unsupported photo file URL.", 400)


def _validate_public_https_url(url: str) -> None:
    """Allow Openverse's credited audio URLs while excluding local/private hosts."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme != "https" or not hostname:
        raise StockError("Openverse returned an unsupported audio file URL.", 400)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise StockError("Could not resolve the Openverse audio host.", 502) from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise StockError("Openverse returned a non-public audio host.", 400)


def _target_height(project: Any) -> int:
    state = (project.metadata or {}).get("timeline_state") or {}
    canvas = state.get("canvas") if isinstance(state, dict) else {}
    try:
        height = int((canvas or {}).get("height") or 1080)
    except (TypeError, ValueError):
        height = 1080
    return min(2160, max(360, height))


def _choose_file(raw_video: dict[str, Any], target_height: int) -> dict[str, Any]:
    candidates = [
        item for item in raw_video.get("video_files", [])
        if isinstance(item, dict)
        and str(item.get("file_type") or "").lower() == "video/mp4"
        and item.get("link")
        and int(item.get("height") or 0) > 0
    ]
    if not candidates:
        raise StockError("Pexels did not provide a downloadable MP4 rendition.", 502)

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        height = int(item.get("height") or 0)
        # Avoid escalating to 4K for a 720p/1080p timeline unless unavoidable.
        oversize_penalty = max(0, height - target_height) * 2
        return (abs(height - target_height) + oversize_penalty, abs(height - 1080), int(item.get("id") or 0))

    selected = min(candidates, key=score)
    _validate_download_url(str(selected["link"]))
    return selected


def search_pexels(provider: PexelsProvider, query: str, page: int, per_page: int) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise StockError("Enter a search term.", 400)
    if len(normalized) > 160:
        raise StockError("Search term is too long.", 400)
    page = max(1, min(page, 1000))
    per_page = max(20, min(per_page, 24))
    key = ("pexels-video", normalized.lower(), page, per_page)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    result = provider.search_videos(normalized, page, per_page)
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    return result


def search_pexels_photos(provider: PexelsProvider, query: str, page: int, per_page: int) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise StockError("Enter a search term.", 400)
    if len(normalized) > 160:
        raise StockError("Search term is too long.", 400)
    page = max(1, min(page, 1000))
    per_page = max(20, min(per_page, 24))
    key = ("pexels-photo", normalized.lower(), page, per_page)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    result = provider.search_photos(normalized, page, per_page)
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    return result


def search_openverse_audio(provider: OpenverseProvider, query: str, page: int, per_page: int, license_filter: str = "commercial") -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise StockError("Enter a search term.", 400)
    if len(normalized) > 160:
        raise StockError("Search term is too long.", 400)
    page = max(1, min(page, 1000))
    per_page = max(20, min(per_page, 50))
    selected_filter = license_filter if license_filter in {"commercial", "public_domain", "all"} else "commercial"
    key = ("openverse-audio", selected_filter, normalized.lower(), page, per_page)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    result = provider.search_audio(normalized, page, per_page, selected_filter)
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    return result


def download_pexels_video(provider: PexelsProvider, project: Any, video_id: int, destination: Path) -> dict[str, Any]:
    raw_video = provider.get_video(video_id)
    selected = _choose_file(raw_video, _target_height(project))
    download_url = str(selected["link"])
    request = Request(download_url, headers={"User-Agent": "Nun-Studio/1.0", "Accept": "video/mp4"})
    opener = build_opener(_AllowedRedirects())
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with opener.open(request, timeout=30) as response, destination.open("wb") as output:
            _validate_download_url(response.geturl())
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_DOWNLOAD_BYTES:
                raise StockError("The selected Pexels video is too large to import.", 413)
            bytes_written = 0
            while chunk := response.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_DOWNLOAD_BYTES:
                    raise StockError("The selected Pexels video is too large to import.", 413)
                output.write(chunk)
    except StockError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise StockError(f"Could not save the Pexels video: {exc}", 500) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise StockError("Pexels video download failed. Please try again.", 502) from exc
    if not destination.exists() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise StockError("Downloaded Pexels video is empty.", 502)
    metadata = PexelsProvider.normalize_video(raw_video).payload()
    metadata["selectedFile"] = {
        "id": int(selected.get("id") or 0),
        "width": int(selected.get("width") or 0),
        "height": int(selected.get("height") or 0),
        "quality": str(selected.get("quality") or ""),
    }
    return metadata


def _download_file(url: str, destination: Path, *, accept: str, validator, label: str, max_bytes: int = MAX_DOWNLOAD_BYTES) -> None:
    validator(url)
    request = Request(url, headers={"User-Agent": "Nun-Studio/1.0", "Accept": accept})
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        opener = build_opener(_ValidatedRedirects(validator))
        with opener.open(request, timeout=30) as response, destination.open("wb") as output:
            validator(response.geturl())
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > max_bytes:
                raise StockError(f"The selected {label} is too large to import.", 413)
            bytes_written = 0
            while chunk := response.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise StockError(f"The selected {label} is too large to import.", 413)
                output.write(chunk)
    except StockError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise StockError(f"Could not save the {label}: {exc}", 500) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise StockError(f"{label.capitalize()} download failed. Please try again.", 502) from exc
    if not destination.exists() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise StockError(f"Downloaded {label} is empty.", 502)


def download_pexels_photo(provider: PexelsProvider, photo_id: int, destination: Path) -> dict[str, Any]:
    raw_photo = provider.get_photo(photo_id)
    sources = raw_photo.get("src") if isinstance(raw_photo.get("src"), dict) else {}
    # "large" is a practical project rendition and avoids fetching Pexels' original by default.
    url = str(sources.get("large") or sources.get("medium") or sources.get("original") or "")
    if not url:
        raise StockError("Pexels did not provide a downloadable photo rendition.", 502)
    _download_file(url, destination, accept="image/*", validator=_validate_pexels_photo_url, label="Pexels photo", max_bytes=80 * 1024 * 1024)
    return PexelsProvider.normalize_photo(raw_photo)


def download_openverse_audio(provider: OpenverseProvider, audio_id: str, destination: Path) -> dict[str, Any]:
    if not audio_id:
        raise StockError("Invalid Openverse audio id.", 400)
    # Openverse exposes an item endpoint; do not accept arbitrary frontend URLs for downloads.
    raw = provider.get_audio(audio_id)
    audio = provider.normalize_audio(raw if isinstance(raw, dict) else {})
    if not audio or not audio["downloadUrl"]:
        raise StockError("Openverse did not provide a downloadable audio file.", 502)
    _download_file(audio["downloadUrl"], destination, accept="audio/*", validator=_validate_public_https_url, label="Openverse sound effect", max_bytes=150 * 1024 * 1024)
    return audio
