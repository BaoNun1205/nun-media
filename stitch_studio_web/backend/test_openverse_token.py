from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend.stock.openverse_token import OpenverseTokenManager
from backend.stock.providers.openverse import OpenverseProvider
from backend.stock.types import StockError


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class OpenverseTokenManagerTests(unittest.TestCase):
    def test_requires_environment_credentials(self) -> None:
        with self.assertRaisesRegex(StockError, "Openverse credentials are not configured"):
            OpenverseTokenManager("  ", "").get_access_token()

    def test_reuses_a_cached_token(self) -> None:
        calls = 0

        def fake_urlopen(_request, timeout):
            nonlocal calls
            calls += 1
            self.assertEqual(timeout, 15)
            return _Response({"access_token": "test-token", "expires_in": 3600})

        manager = OpenverseTokenManager(" id ", " secret ")
        with patch("backend.stock.openverse_token.urlopen", fake_urlopen):
            self.assertEqual(manager.get_access_token(), "test-token")
            self.assertEqual(manager.get_access_token(), "test-token")
        self.assertEqual(calls, 1)

    def test_audio_401_refreshes_once_then_retries(self) -> None:
        class TokenManager:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def get_access_token(self, **kwargs) -> str:
                self.calls.append(kwargs)
                return "fresh-token" if kwargs else "stale-token"

        token_manager = TokenManager()
        calls = 0

        def fake_urlopen(request, timeout):
            nonlocal calls
            calls += 1
            self.assertEqual(timeout, 15)
            if calls == 1:
                raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"expired"}'))
            return _Response({"results": []})

        provider = OpenverseProvider(token_manager)  # type: ignore[arg-type]
        with patch("backend.stock.providers.openverse.urlopen", fake_urlopen):
            self.assertEqual(provider.search_audio("rain", 1, 20)["audio"], [])
        self.assertEqual(calls, 2)
        self.assertEqual(token_manager.calls, [{}, {"force_refresh": True, "rejected_token": "stale-token"}])

    def test_normalizes_cc0_audio_without_category_or_thumbnail(self) -> None:
        raw = {
            "id": "sound-1", "title": "Rain on roof", "license": "CC0", "duration": 42000,
            "url": "https://example.test/rain.mp3", "category": None, "thumbnail": None,
            "tags": [{"name": "rain"}], "provider": "freesound",
        }
        normalized = OpenverseProvider.normalize_audio(raw, {"rain"})
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["license"], "cc0")
        self.assertGreater(normalized["rank"], 0)


if __name__ == "__main__":
    unittest.main()
