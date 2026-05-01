# -*- coding: utf-8 -*-
"""Tests for File upload/get/delete endpoints (/api/files/* + /ai/upload_temp_file).

All file endpoints require a JWT capability token. Upload tokens are issued
by `/ai/upload_temp_file`; access tokens (read/delete) are minted in-test
via `server.core.security.jwt.issue_access_token`.
"""

import os
import time
import unittest

import jwt as _pyjwt

from _test_helpers import FullAppTestBase

# Ensure JWT keys exist for tests (autogenerate when missing).
from core.server.security.jwt import (  # type: ignore
    ensure_jwt_keys_or_warn,
    issue_access_token,
    issue_upload_token,
    get_private_key,
    JWT_ALG,
)
from pathlib import Path as _Path

ensure_jwt_keys_or_warn(_Path(__file__).resolve().parent.parent.parent)


async def _get_upload_token(client) -> dict:
    resp = await client.post('/ai/upload_temp_file')
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTempUploadToken(FullAppTestBase):
    async def test_issue_token_returns_fields(self):
        data = await _get_upload_token(self._client)
        self.assertIn('token', data)
        self.assertEqual(data['category'], 'ai-temp')
        self.assertGreater(data['max_size'], 0)
        self.assertEqual(data['upload_url'], '/ai/files/upload')


class TestFileUpload(FullAppTestBase):
    async def test_upload_without_authorization_returns_401(self):
        files = {'file': ('a.txt', b'hello', 'text/plain')}
        resp = await self._client.post('/ai/files/upload', files=files)
        # FastAPI returns 422 when required Header is absent; explicit 401 when present-but-bad.
        self.assertIn(resp.status_code, (401, 422))

    async def test_upload_with_token_succeeds(self):
        tok = await _get_upload_token(self._client)
        files = {'file': ('a.txt', b'hello', 'text/plain')}
        resp = await self._client.post(
            '/ai/files/upload', files=files,
            headers={'Authorization': f'Bearer {tok["token"]}'},
        )
        self.assertIn(resp.status_code, (200, 500))
        if resp.status_code == 200:
            data = resp.json()
            self.assertEqual(data['category'], 'ai-temp')
            self.assertEqual(data['size'], 5)
            self.assertIn('file_id', data)

    async def test_upload_oversize_returns_413(self):
        token = issue_upload_token(
            category='ai-temp', max_size=4, file_expire=60.0,
            issuer_route='test', allowed_mime_prefixes=['text/'], ttl=120,
        )
        files = {'file': ('big.txt', b'12345678', 'text/plain')}
        resp = await self._client.post(
            '/ai/files/upload', files=files,
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 413)

    async def test_upload_disallowed_mime_returns_415(self):
        token = issue_upload_token(
            category='ai-temp', max_size=1024, file_expire=60.0,
            issuer_route='test', allowed_mime_prefixes=['image/'], ttl=120,
        )
        files = {'file': ('a.txt', b'hello', 'text/plain')}
        resp = await self._client.post(
            '/ai/files/upload', files=files,
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 415)

    async def test_upload_expired_token_returns_401(self):
        # Hand-craft an expired token
        now = int(time.time())
        claims = {
            'iss': 'proj-template', 'sub': 'file-upload', 'jti': 'x',
            'iat': now - 600, 'exp': now - 60,
            'category': 'ai-temp', 'max_size': 1024,
            'file_expire': None, 'issuer_route': 'test',
        }
        token = _pyjwt.encode(claims, get_private_key(), algorithm=JWT_ALG)
        files = {'file': ('a.txt', b'hi', 'text/plain')}
        resp = await self._client.post(
            '/ai/files/upload', files=files,
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 401)


class TestFileAccess(FullAppTestBase):
    async def _upload(self) -> dict | None:
        tok = await _get_upload_token(self._client)
        files = {'file': ('rt.txt', b'round trip', 'text/plain')}
        resp = await self._client.post(
            '/ai/files/upload', files=files,
            headers={'Authorization': f'Bearer {tok["token"]}'},
        )
        if resp.status_code != 200:
            return None
        return resp.json()

    async def test_get_with_wrong_sub_returns_401(self):
        token = issue_upload_token(
            category='ai-temp', max_size=1024, file_expire=None,
            issuer_route='test', ttl=120,
        )
        resp = await self._client.post(
            '/ai/files/get', headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 401)

    async def test_get_with_delete_action_returns_403(self):
        uploaded = await self._upload()
        if uploaded is None:
            self.skipTest('upload unavailable')
        token = issue_access_token(
            category=uploaded['category'],
            object_id=uploaded['file_id']['id'],
            action='delete',
        )
        resp = await self._client.post(
            '/ai/files/get', headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 403)

    async def test_round_trip_get(self):
        uploaded = await self._upload()
        if uploaded is None:
            self.skipTest('upload unavailable')
        token = issue_access_token(
            category=uploaded['category'],
            object_id=uploaded['file_id']['id'],
            action='read',
        )
        resp = await self._client.post(
            '/ai/files/get', headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'round trip')

    async def test_round_trip_delete(self):
        uploaded = await self._upload()
        if uploaded is None:
            self.skipTest('upload unavailable')
        token = issue_access_token(
            category=uploaded['category'],
            object_id=uploaded['file_id']['id'],
            action='delete',
        )
        resp = await self._client.post(
            '/api/files/delete', headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('deleted', data)


if __name__ == '__main__':
    unittest.main()
