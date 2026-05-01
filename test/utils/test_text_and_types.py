

import asyncio
import os
import re
import sys
import tempfile
import unittest

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from annotated_types import Ge, MaxLen
from pydantic import BaseModel, Field
from pydantic.v1 import BaseModel as BaseModelV1, Field as FieldV1

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.embedding import EmbeddingClient, EmbeddingService
from core.utils.text_utils import split_text_by_word_count, word_count
from core.utils.type_utils import create_type_default_instance


WIKI_FIXTURE = _PROJECT_ROOT / 'resources' / 'test' / 'text_split_python_wiki_dump.txt'
MIXED_FIXTURE = _PROJECT_ROOT / 'resources' / 'test' / 'text_split_mixed_formats.txt'
_WORDISH_CHAR_PAT = re.compile(r'[A-Za-z0-9_\u3400-\u4DBF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]')


class Palette(Enum):
    RED = 'red'
    BLUE = 'blue'


class _NeedsArg:
    def __init__(self, value: int):
        self.value = value


class NestedModel(BaseModel):
    code: str = Field(max_length=2)
    count: int = Field(ge=1)


class ExampleModel(BaseModel):
    example_text: str = Field(examples=['demo'])
    title: str = Field(max_length=5)
    tags: list[str] = Field(default_factory=list)
    mapping: dict[str, int]
    nested: NestedModel
    palette: Palette
    literal_value: Literal['x', 'y']


class LegacyModel(BaseModelV1):
    example_text: str = FieldV1(..., example='legacy')
    name: str = FieldV1(..., max_length=4)
    count: int = FieldV1(..., ge=1)


@dataclass
class NestedData:
    code: Annotated[str, MaxLen(3)]
    quantity: Annotated[int, Ge(2)]


@dataclass
class ExampleData:
    heading: str = field(metadata={'alias': 'caption'})
    nested: NestedData = field()
    labels: list[str] = field(default_factory=list)
    fixed: str = 'preset'


class DummyEmbeddingClient(EmbeddingClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.call_count = 0

    async def _embedding_impl(self, inputs, **kwargs):
        self.call_count += 1
        vectors = []
        for item in inputs:
            if isinstance(item, str):
                wc = float(word_count(item))
                vectors.append([wc, float(len(item) % 97 + 1)])
            else:
                vectors.append([1.0, 1.0])
        return vectors


class TestCreateTypeDefaultInstance(unittest.TestCase):
    def test_creates_pydantic_v2_default_instance(self):
        result = create_type_default_instance(ExampleModel)

        self.assertIsInstance(result, ExampleModel)
        self.assertEqual(result.example_text, 'demo')
        self.assertEqual(result.title, 'title')
        self.assertEqual(result.tags, [])
        self.assertEqual(result.mapping, {'': 0})
        self.assertIsInstance(result.nested, NestedModel)
        self.assertEqual(result.nested.code, 'co')
        self.assertEqual(result.nested.count, 1)
        self.assertIs(result.palette, Palette.RED)
        self.assertEqual(result.literal_value, 'x')

    def test_creates_pydantic_v1_default_instance(self):
        result = create_type_default_instance(LegacyModel)

        self.assertIsInstance(result, LegacyModel)
        self.assertEqual(result.example_text, 'legacy')
        self.assertEqual(result.name, 'name')
        self.assertEqual(result.count, 1)

    def test_creates_dataclass_default_instance(self):
        result = create_type_default_instance(ExampleData)

        self.assertIsInstance(result, ExampleData)
        self.assertEqual(result.heading, 'caption')
        self.assertEqual(result.fixed, 'preset')
        self.assertEqual(result.labels, [])
        self.assertIsInstance(result.nested, NestedData)
        self.assertEqual(result.nested.code, 'cod')
        self.assertEqual(result.nested.quantity, 2)

    def test_creates_union_enum_literal_and_containers(self):
        self.assertEqual(create_type_default_instance(int | None), 0)
        self.assertEqual(create_type_default_instance(_NeedsArg | int), 0)
        self.assertIs(create_type_default_instance(Palette), Palette.RED)
        self.assertEqual(create_type_default_instance(Literal['a', 'b']), 'a')
        self.assertEqual(create_type_default_instance(list[int]), [0])
        self.assertEqual(create_type_default_instance(dict[str, int]), {'': 0})
        self.assertEqual(create_type_default_instance(tuple[int, ...]), (0,))
        self.assertEqual(create_type_default_instance(tuple[int, str]), (0, ''))

    def test_raises_when_no_default_instance_can_be_created(self):
        with self.assertRaises(TypeError):
            create_type_default_instance(_NeedsArg)


class TestTextSplit(unittest.TestCase):

    def _load_fixture(self, path: Path) -> str:
        return path.read_text(encoding='utf-8')

    def _assert_chunks_basic(self, text: str, chunks: list[dict], max_word_count: int, min_reasonable_words: int) -> None:
        self.assertTrue(chunks)
        self.assertTrue(all(chunk['word_count'] <= max_word_count for chunk in chunks))
        self.assertTrue(all(chunk['offset'] >= 0 for chunk in chunks))

        for idx, chunk in enumerate(chunks):
            original_slice = text[chunk['offset']:chunk['offset'] + len(chunk['text'])]
            self.assertEqual(original_slice, chunk['text'])
            if idx < len(chunks) - 1:
                self.assertGreaterEqual(chunk['word_count'], min_reasonable_words)

        for left, _right in zip(chunks, chunks[1:]):
            left_end = left['offset'] + len(left['text'])
            while left_end < len(text) and text[left_end].isspace():
                left_end += 1
            if left_end >= len(text):
                continue
            prev_char = text[left_end - 1]
            next_char = text[left_end]
            self.assertFalse(
                bool(_WORDISH_CHAR_PAT.match(prev_char)) and bool(_WORDISH_CHAR_PAT.match(next_char)),
                msg=f'Unexpected token-internal split near: {text[max(0, left_end - 20):left_end + 20]!r}',
            )

    def test_wiki_fixture_chunk_distribution(self):
        text = self._load_fixture(WIKI_FIXTURE)
        chunks = split_text_by_word_count(text, max_word_count=120)
        counts = [chunk['word_count'] for chunk in chunks]

        self.assertGreaterEqual(len(chunks), 5)
        self.assertTrue(any('## Summary table' in chunk['text'] for chunk in chunks))
        self._assert_chunks_basic(text, chunks, max_word_count=120, min_reasonable_words=30)
        self.assertLessEqual(max(counts) - min(counts), 90)

    def test_mixed_fixture_chunk_distribution(self):
        text = self._load_fixture(MIXED_FIXTURE)
        chunks = split_text_by_word_count(text, max_word_count=120)
        counts = [chunk['word_count'] for chunk in chunks]

        self.assertGreaterEqual(len(chunks), 4)
        self.assertTrue(any('```python' in chunk['text'] for chunk in chunks))
        self.assertTrue(any('| component | role | notes |' in chunk['text'] for chunk in chunks))
        self._assert_chunks_basic(text, chunks, max_word_count=120, min_reasonable_words=35)
        self.assertLessEqual(max(counts) - min(counts), 70)

    def test_balanced_hard_split_avoids_tiny_tail(self):
        text = ' '.join(f'token{chr(97 + (i % 26))}{chr(97 + ((i // 26) % 26))}' for i in range(53))
        chunks = split_text_by_word_count(text, max_word_count=20)
        counts = [chunk['word_count'] for chunk in chunks]

        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(15 <= count <= 20 for count in counts))
        self._assert_chunks_basic(text, chunks, max_word_count=20, min_reasonable_words=15)


class TestEmbeddingService(unittest.TestCase):

    def test_testing_input_disables_cache(self):
        probe = DummyEmbeddingClient.TestingInput()
        self.assertFalse(probe['kwargs']['use_cache'])
        self.assertFalse(probe['kwargs']['save_cache'])

    def test_single_input_returns_single_vector_and_cache_flags_work(self):
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.environ['EMBEDDING_CACHE_DB'] = str(Path(tmp_dir) / 'embedding_cache.sqlite3')
                try:
                    client = DummyEmbeddingClient(max_tokens=5)
                    service = EmbeddingService(client)
                    await service.cache_clear()

                    single_vector = await service.embedding(
                        'alpha beta gamma delta epsilon zeta eta theta',
                        on_overflow='chunk',
                        use_cache=False,
                        save_cache=False,
                    )
                    self.assertIsInstance(single_vector, list)
                    self.assertTrue(single_vector)
                    self.assertTrue(all(isinstance(v, float) for v in single_vector))

                    batch_vectors = await service.embedding(
                        ['alpha beta gamma delta epsilon zeta eta theta', 'short text'],
                        on_overflow='chunk',
                        use_cache=False,
                        save_cache=False,
                    )
                    self.assertEqual(len(batch_vectors), 2)
                    self.assertTrue(all(isinstance(vec, list) for vec in batch_vectors))

                    uncached_before = client.call_count
                    await service.embedding('cache validation text', use_cache=False, save_cache=False)
                    await service.embedding('cache validation text', use_cache=False, save_cache=False)
                    uncached_after = client.call_count
                    self.assertGreaterEqual(uncached_after - uncached_before, 2)

                    cached_before = client.call_count
                    await service.embedding('cache validation text', use_cache=True, save_cache=True)
                    # Allow background cache-save thread to flush the queue
                    await asyncio.sleep(0.5)
                    cached_mid = client.call_count
                    await service.embedding('cache validation text', use_cache=True, save_cache=True)
                    cached_after = client.call_count
                    self.assertEqual(cached_mid, cached_after)
                    self.assertGreaterEqual(cached_mid, cached_before)
                    service.cache_close()
                finally:
                    os.environ.pop('EMBEDDING_CACHE_DB', None)

        asyncio.run(_run())


if __name__ == '__main__':
    unittest.main()