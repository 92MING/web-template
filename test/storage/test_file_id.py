

import asyncio
import base64
import tempfile

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest import TestCase

from core.utils.data_structs import PlainText
from core.utils.data_structs.files.base import FileID


class _MemoryFileStorage:
    def __init__(self, data: bytes):
        self._data = data

    async def get_file(self, object_id: str, *, chunk_size: int = 65536):
        for index in range(0, len(self._data), max(1, chunk_size)):
            yield self._data[index:index + max(1, chunk_size)]

    async def put_file(
        self,
        data: bytes,
        category: str,
        expire: float | None,
        type: str | None = None,
        *,
        object_name: str | None = None,
    ) -> str:
        return f'{category}:{type or "raw"}:{len(data)}'

    async def delete_file(self, object_id: str) -> bool:
        return True


async def _collect_chunks(stream) -> bytes:
    chunks: list[bytes] = []
    async for chunk in stream:
        chunks.append(bytes(chunk))
    return b''.join(chunks)


class TestFileID(TestCase):
    def test_file_id_model_fields(self):
        file_id = FileID(id='123', category='cache', type='plaintext')

        self.assertEqual(file_id.id, '123')
        self.assertEqual(file_id.category, 'cache')
        self.assertEqual(file_id.type, 'plaintext')
        self.assertEqual(str(file_id), '123')

    def test_file_id_instance_resolves_in_document_load(self):
        original_protocols = dict(FileID._protocols)
        try:
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(b'hello from file id'))

            document = PlainText.Load(FileID(id='doc-1', category='unit-test', type='plaintext'))

            self.assertEqual(document.to_bytes(), b'hello from file id')
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)

    def test_getdata_streams_chunks(self):
        original_protocols = dict(FileID._protocols)
        try:
            payload = b'abcdefghijklmnopqrstuvwxyz'
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(payload))

            streamed = asyncio.run(
                _collect_chunks(FileID.GetData(FileID(id='doc-1', category='unit-test', type='plaintext'), chunk_size=5))
            )

            self.assertEqual(streamed, payload)
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)

    def test_get_returns_deferred_file(self):
        original_protocols = dict(FileID._protocols)
        try:
            payload = b'hello from file id'
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(payload))

            file_obj = FileID.Get(FileID(id='doc-1', category='unit-test', type='plaintext'))

            self.assertIsInstance(file_obj, PlainText)
            self.assertEqual(getattr(file_obj, '_bytes_cache', None), None)
            self.assertEqual(file_obj.to_bytes(), payload)
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)

    def test_getbytes_and_peek(self):
        original_protocols = dict(FileID._protocols)
        try:
            payload = b'hello from stream'
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(payload))
            file_id = FileID(id='doc-2', category='unit-test', type='plaintext')

            data = asyncio.run(FileID.GetBytes(file_id, chunk_size=4))
            head = asyncio.run(FileID.Peek(file_id, size=5, chunk_size=4))

            self.assertEqual(data, payload)
            self.assertEqual(head, b'hello')
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)

    def test_getdata_rejects_plain_dict_payload(self):
        with self.assertRaises(TypeError):
            FileID.GetData({'id': 'doc-1', 'category': 'unit-test'})

    def test_create_supports_multiple_input_sources(self):
        original_protocols = dict(FileID._protocols)
        try:
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(b''))
            payload = b'plain text payload'
            payload_b64 = base64.b64encode(payload).decode('ascii')

            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'sample.txt'
                path.write_bytes(payload)

                sources = [
                    ('bytes', payload, None, 'plaintext'),
                    ('base64', payload_b64, None, 'plaintext'),
                    ('bytesio', BytesIO(payload), None, 'plaintext'),
                    ('byte-generator', (chunk for chunk in (payload[:5], payload[5:])), None, 'plaintext'),
                    ('path', path, 'sample.txt', 'txt'),
                    ('path-string', str(path), 'sample.txt', 'txt'),
                ]

                for label, source, expected_filename, expected_type in sources:
                    with self.subTest(label=label):
                        file_id = asyncio.run(FileID.Create(source, category='unit-test'))
                        self.assertEqual(file_id.category, 'unit-test')
                        self.assertEqual(file_id.type, expected_type)
                        self.assertEqual(file_id.filename, expected_filename)
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)

    def test_create_uses_explicit_type_and_filename(self):
        original_protocols = dict(FileID._protocols)
        try:
            FileID._protocols.clear()
            FileID.AddProtocol('unit-test', _MemoryFileStorage(b''))

            file_id = asyncio.run(
                FileID.Create(
                    b'raw custom payload',
                    category='unit-test',
                    type='plaintext',
                    filename='custom-name.txt',
                )
            )

            self.assertEqual(file_id.type, 'plaintext')
            self.assertEqual(file_id.filename, 'custom-name.txt')
        finally:
            FileID._protocols.clear()
            FileID._protocols.update(original_protocols)