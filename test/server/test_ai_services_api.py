# -*- coding: utf-8 -*-
"""Tests for AI Services API endpoints (/ai/*).

Most AI endpoints require external services (LLM, TTS, STT, embedding).
Tests here focus on service discovery and error-handling for invalid requests.
"""


import unittest

from _test_helpers import FullAppTestBase


class TestAIServiceDiscovery(FullAppTestBase):
    """GET /ai/services"""

    async def test_services_returns_200(self):
        resp = await self._client.get("/ai/services")
        self.assertEqual(resp.status_code, 200)

    async def test_services_returns_list(self):
        data = (await self._client.get("/ai/services")).json()
        self.assertIsInstance(data, list)

    async def test_services_have_required_fields(self):
        data = (await self._client.get("/ai/services")).json()
        for svc in data:
            self.assertIn("kind", svc)
            self.assertIn("instances", svc)
            self.assertIn("clients", svc)
            self.assertIsInstance(svc["kind"], str)
            self.assertIsInstance(svc["instances"], dict)
            self.assertIsInstance(svc["clients"], dict)

    async def test_services_all_four_kinds(self):
        data = (await self._client.get("/ai/services")).json()
        kinds = {s["kind"] for s in data}
        self.assertEqual(kinds, {"completion", "s2t", "t2s", "embedding"})

    async def test_get_service_by_kind(self):
        resp = await self._client.get("/ai/services/completion")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["kind"], "completion")

    async def test_get_service_unknown_kind_422(self):
        resp = await self._client.get("/ai/services/foobar")
        self.assertEqual(resp.status_code, 422)

    async def test_get_unknown_instance_404(self):
        resp = await self._client.get("/ai/services/completion/instances/__nope__")
        self.assertEqual(resp.status_code, 404)

    async def test_get_unknown_client_404(self):
        resp = await self._client.get("/ai/services/completion/clients/__nope__")
        self.assertEqual(resp.status_code, 404)


class TestAIEmbedding(FullAppTestBase):
    """POST /ai/embedding — error handling."""

    async def test_embedding_missing_text_returns_error(self):
        resp = await self._client.post(
            "/ai/embedding",
            json={"text": None, "texts": None},
        )
        # 400 from our validation or 503 from service unavailable
        self.assertIn(resp.status_code, (400, 422, 503))

    async def test_embedding_empty_text_returns_error(self):
        resp = await self._client.post(
            "/ai/embedding",
            json={"text": "   ", "texts": None},
        )
        # Whitespace-only text — should error or return service unavailable
        self.assertIn(resp.status_code, (400, 500, 503))

    async def test_embedding_empty_texts_list_returns_error(self):
        resp = await self._client.post(
            "/ai/embedding",
            json={"text": None, "texts": []},
        )
        self.assertIn(resp.status_code, (400, 422, 503))


class TestAIComplete(FullAppTestBase):
    """POST /ai/complete — error handling."""

    async def test_complete_missing_messages_returns_422(self):
        resp = await self._client.post(
            "/ai/complete",
            json={},
        )
        self.assertEqual(resp.status_code, 422)

    async def test_complete_invalid_message_format_returns_422(self):
        resp = await self._client.post(
            "/ai/complete",
            json={"messages": [{"no_role": True}]},
        )
        self.assertEqual(resp.status_code, 422)

    async def test_complete_valid_request_returns_error_or_result(self):
        """Valid request structure but service may not be available."""
        resp = await self._client.post(
            "/ai/complete",
            json={
                "messages": [{"role": "user", "content": "Say hello"}],
                "max_tokens": 10,
                "stream": False,
            },
        )
        # 200 if service available, 503 if not
        self.assertIn(resp.status_code, (200, 500, 503))

    async def test_complete_message_without_content_returns_422(self):
        resp = await self._client.post(
            "/ai/complete",
            json={"messages": [{"role": "user"}]},
        )
        self.assertEqual(resp.status_code, 422)


@unittest.skip("Translate service may block in test env")
class TestAITranslate(FullAppTestBase):
    """POST /ai/translate — error handling."""

    async def test_translate_service_unavailable(self):
        resp = await self._client.post(
            "/ai/translate",
            json={"text": "Hello", "target_language": "zh-tw"},
        )
        # 200 if service available, 500/503 if not
        self.assertIn(resp.status_code, (200, 500, 503))


@unittest.skip("Detect-language service may block in test env")
class TestAIDetectLanguage(FullAppTestBase):
    """POST /ai/detect-language"""

    async def test_detect_language_service_response(self):
        resp = await self._client.post(
            "/ai/detect-language",
            json={"text": "This is English text"},
        )
        self.assertIn(resp.status_code, (200, 500, 503))
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("language", data)


@unittest.skip("Summarize service may block in test env")
class TestAISummarize(FullAppTestBase):
    """POST /ai/summarize"""

    async def test_summarize_service_response(self):
        resp = await self._client.post(
            "/ai/summarize",
            json={"text": "A long article about machine learning...", "stream": False},
        )
        self.assertIn(resp.status_code, (200, 500, 503))


if __name__ == "__main__":
    unittest.main()
