from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .types import StockError

logger = logging.getLogger(__name__)


class OpenverseTokenManager:
    """Thread-safe in-memory OAuth client-credentials token cache."""

    TOKEN_URL = "https://api.openverse.org/v1/auth_tokens/token/"
    REFRESH_SKEW_SECONDS = 60

    def __init__(self, client_id: str | None, client_secret: str | None, timeout_seconds: int = 15) -> None:
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._timeout_seconds = timeout_seconds
        self._access_token = ""
        self._expires_at = 0.0
        self._refresh_at = 0.0
        self._refresh_lock = threading.Lock()

    def _token_is_usable(self) -> bool:
        return bool(self._access_token) and time.monotonic() < self._refresh_at

    def configure(self, client_id: str | None, client_secret: str | None) -> None:
        """Replace credentials and discard the previous in-memory token."""
        with self._refresh_lock:
            self._client_id = (client_id or "").strip()
            self._client_secret = (client_secret or "").strip()
            self._access_token = ""
            self._expires_at = 0.0
            self._refresh_at = 0.0

    @staticmethod
    def _safe_response_body(value: str) -> str:
        cleaned = value.replace("\r", " ").replace("\n", " ")[:500]
        cleaned = re.sub(r"(?i)(client_secret|access_token)\s*[:=]\s*[^,\s&]+", r"\1=[redacted]", cleaned)
        return cleaned

    def get_access_token(self, *, force_refresh: bool = False, rejected_token: str = "") -> str:
        if not self._client_id or not self._client_secret:
            raise StockError("Openverse credentials are not configured.", 503)
        if not force_refresh and self._token_is_usable():
            return self._access_token
        # A second check inside the lock prevents a thundering herd at expiry.
        with self._refresh_lock:
            if not force_refresh and self._token_is_usable():
                return self._access_token
            # A different request may already have refreshed the token that
            # produced this 401 while this request waited for the lock.
            if force_refresh and rejected_token and self._access_token != rejected_token and self._token_is_usable():
                return self._access_token
            if force_refresh:
                self._access_token = ""
                self._expires_at = 0.0
                self._refresh_at = 0.0
            return self._request_token()

    def _request_token(self) -> str:
        body = urlencode({
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }).encode("utf-8")
        request = Request(self.TOKEN_URL, data=body, headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Nun-Studio/1.0",
        })
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310 - fixed Openverse OAuth endpoint
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            response_body = self._safe_response_body(exc.read().decode("utf-8", errors="replace"))
            logger.warning("Openverse token request failed: status=%s response=%s", exc.code, response_body)
            if exc.code in {400, 401}:
                raise StockError("Openverse rejected the configured credentials.", 401) from exc
            raise StockError(f"Openverse token request failed ({exc.code}).", 502) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            logger.warning("Openverse token request timed out or failed: %s", exc)
            raise StockError("Openverse token request timed out. Please try again.", 504) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Openverse token response was invalid: %s", exc)
            raise StockError("Openverse returned an invalid token response.", 502) from exc
        token = str(payload.get("access_token") or "")
        if not token:
            logger.warning("Openverse token response did not contain an access token")
            raise StockError("Openverse did not return an access token.", 502)
        try:
            expires_in = int(payload.get("expires_in") or 300)
        except (TypeError, ValueError):
            expires_in = 300
        self._access_token = token
        self._expires_at = time.monotonic() + max(1, expires_in)
        self._refresh_at = time.monotonic() + max(1, expires_in - min(self.REFRESH_SKEW_SECONDS, expires_in / 2))
        return token
