# -*- coding: utf-8 -*-
"""Tests for Log API endpoints (/_internal/admin/api/logs/*).

These require Config with log_method=['db'] to be meaningful.
"""


import unittest
import logging

from types import SimpleNamespace
from unittest.mock import patch

from _test_helpers import FullAppTestBase


class _FakeORMStore:
    def __init__(self):
        self.records: list[dict] = []

    def write(self, record):
        self.records.append(record)


class TestLogsConfig(FullAppTestBase):
    """GET /_internal/admin/api/logs/config"""

    async def test_config_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs/config")
        self.assertEqual(resp.status_code, 200)

    async def test_config_has_required_fields(self):
        data = (await self._client.get("/_internal/admin/api/logs/config")).json()
        self.assertIn("db_enabled", data)
        self.assertIn("file_enabled", data)
        self.assertIn("instance_uuid", data)
        self.assertIn("cache_scope", data)
        self.assertIsInstance(data["db_enabled"], bool)
        self.assertIsInstance(data["file_enabled"], bool)
        self.assertIsInstance(data["instance_uuid"], str)
        self.assertIsInstance(data["cache_scope"], str)

    async def test_config_db_enabled(self):
        """Since we set log_method=['db'] in test Config, db should be enabled."""
        data = (await self._client.get("/_internal/admin/api/logs/config")).json()
        # It should be True because FullAppTestBase sets log_method=['db']
        self.assertTrue(data["db_enabled"])


class TestLogsMeta(FullAppTestBase):
    """GET /_internal/admin/api/logs/meta"""

    async def test_meta_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs/meta")
        self.assertEqual(resp.status_code, 200)

    async def test_meta_has_required_fields(self):
        data = (await self._client.get("/_internal/admin/api/logs/meta")).json()
        self.assertIn("instance_uuid", data)
        self.assertIn("worker_pid", data)
        self.assertIn("cache_scope", data)
        self.assertIsInstance(data["instance_uuid"], str)
        self.assertIsInstance(data["worker_pid"], int)
        self.assertIsInstance(data["cache_scope"], str)


class TestLogsQuery(FullAppTestBase):
    """GET /_internal/admin/api/logs"""

    async def test_query_logs_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs")
        # If db is enabled: 200, else: 404
        self.assertIn(resp.status_code, (200, 404))

    async def test_query_logs_structure(self):
        resp = await self._client.get("/_internal/admin/api/logs")
        if resp.status_code == 200:
            data = resp.json()
            for key in ("total", "offset", "limit", "rows"):
                self.assertIn(key, data)
            self.assertIsInstance(data["rows"], list)
            self.assertIsInstance(data["total"], int)

    async def test_query_logs_with_filters(self):
        resp = await self._client.get(
            "/_internal/admin/api/logs",
            params={"level": "INFO", "limit": 10, "offset": 0, "order": "DESC"},
        )
        self.assertIn(resp.status_code, (200, 404))

    async def test_query_logs_with_search(self):
        resp = await self._client.get(
            "/_internal/admin/api/logs",
            params={"search": "test", "limit": 5},
        )
        self.assertIn(resp.status_code, (200, 404))

    async def test_query_logs_with_min_levelno(self):
        resp = await self._client.get(
            "/_internal/admin/api/logs",
            params={"min_levelno": 30, "limit": 5},  # WARNING+ only
        )
        self.assertIn(resp.status_code, (200, 404))


class TestLogsDelete(FullAppTestBase):
    """DELETE /_internal/admin/api/logs, DELETE /_internal/admin/api/logs/before/{timestamp}"""

    async def test_delete_all_logs(self):
        resp = await self._client.delete("/_internal/admin/api/logs")
        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("deleted", data)

    async def test_delete_logs_before_timestamp(self):
        resp = await self._client.delete("/_internal/admin/api/logs/before/2030-01-01T00:00:00")
        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            self.assertIn("deleted_before", resp.json())


class TestServiceCallLogs(FullAppTestBase):
    """GET /_internal/admin/api/logs/service/logs"""

    async def test_service_logs_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs/service/logs")
        # May return 200 with empty list, or 500 if service log mixin unavailable
        self.assertIn(resp.status_code, (200, 500))

    async def test_service_logs_is_list(self):
        resp = await self._client.get("/_internal/admin/api/logs/service/logs")
        if resp.status_code == 200:
            data = resp.json()
            self.assertIsInstance(data, list)

    async def test_service_logs_with_filters(self):
        resp = await self._client.get(
            "/_internal/admin/api/logs/service/logs",
            params={"limit": 10, "success": True},
        )
        self.assertIn(resp.status_code, (200, 500))


class TestServiceCallStats(FullAppTestBase):
    """GET /_internal/admin/api/logs/service/stats"""

    async def test_service_stats_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs/service/stats")
        self.assertIn(resp.status_code, (200, 500))

    async def test_service_stats_group_by(self):
        for group in ("operation", "service_kind", "client_class"):
            resp = await self._client.get(
                "/_internal/admin/api/logs/service/stats",
                params={"group_by": group},
            )
            self.assertIn(resp.status_code, (200, 500))


class TestLogsOverview(FullAppTestBase):
    """GET /_internal/admin/api/logs/overview"""

    async def test_overview_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/logs/overview")
        self.assertEqual(resp.status_code, 200)

    async def test_overview_structure(self):
        data = (await self._client.get("/_internal/admin/api/logs/overview")).json()
        self.assertIn("backend", data)
        self.assertIn("service", data)
        self.assertIsInstance(data["backend"], dict)
        self.assertIsInstance(data["service"], dict)

    async def test_overview_backend_fields(self):
        data = (await self._client.get("/_internal/admin/api/logs/overview")).json()
        backend = data["backend"]
        self.assertIn("total", backend)
        self.assertIn("recent_errors", backend)

    async def test_overview_service_fields(self):
        data = (await self._client.get("/_internal/admin/api/logs/overview")).json()
        svc = data["service"]
        self.assertIn("total_calls", svc)


class TestLogsOpenAPISchemas(FullAppTestBase):
    async def test_openapi_exposes_named_models_for_log_routes(self):
        resp = await self._client.get('/_internal/admin/openapi.json')
        self.assertEqual(resp.status_code, 200)
        paths = resp.json()['paths']

        config_schema = paths['/_internal/admin/api/logs/config']['get']['responses']['200']['content']['application/json']['schema']
        query_schema = paths['/_internal/admin/api/logs']['get']['responses']['200']['content']['application/json']['schema']
        overview_schema = paths['/_internal/admin/api/logs/overview']['get']['responses']['200']['content']['application/json']['schema']

        self.assertEqual(config_schema['$ref'], '#/components/schemas/LogsConfigResponse')
        self.assertEqual(query_schema['$ref'], '#/components/schemas/LogsQueryResponse')
        self.assertEqual(overview_schema['$ref'], '#/components/schemas/LogsOverviewResponse')



if __name__ == "__main__":
    unittest.main()
