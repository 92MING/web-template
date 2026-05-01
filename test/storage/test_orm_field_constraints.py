"""Integration tests: Pydantic FieldInfo constraints (gt/ge/lt/le/max_length/
min_length/pattern/multiple_of) against ALL database backends —including
Milvus vector, since VectorORMModel inherits ORMModel.

Targets:
  ORM : SQLite, PostgreSQL (5433), MySQL (3307), MongoDB (27017), Redis (6379)
  Vec : Milvus (19530)

Tests verify:
  1. Constraint-bearing fields pass Pydantic validation on creation (ORMField + Field).
  2. Invalid values are rejected at creation time.
  3. Save →load round-trip preserves values and re-validates via model_validate.
  4. Milvus VARCHAR max_length is read from FieldInfo (not hardcoded 65535).
"""
import asyncio
import os
import re
import sys
import time
import unittest
from pathlib import Path
from typing import ClassVar

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from pydantic import Field as PydanticField, ValidationError

from core.storage.orm import (
    ORMModel,
    ORMField,
    SQLiteORMClient,
    PostgreSQLORMClient,
    MySQLORMClient,
    MongoORMClient,
    RedisORMClient,
)
from core.storage.vector import (
    PyMilvusVectorClient,
    VectorIndex,
    VectorORMField,
    VectorORMModel,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TMP_DIR = Path(__file__).resolve().parent.parent.parent / "tmp"
_SUFFIX = str(int(time.time()))

MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")

_CONSISTENCY_RETRIES = 8
_CONSISTENCY_SLEEP = 0.5


async def _test_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0, 0.0, 0.0]
    return [0.25, 0.25, 0.25, 0.25]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure Pydantic validation —no DB needed
# ═══════════════════════════════════════════════════════════════════════════════

class ConstrainedItem(ORMModel, collection_name="fc_constrained"):
    """Model with every common Pydantic constraint type via ORMField."""
    score: int = ORMField(50, gt=0, le=100)
    rating: float = ORMField(1.0, ge=0.0, lt=10.0)
    quantity: int = ORMField(2, multiple_of=2)
    code: str = ORMField("AB", min_length=2, max_length=10)
    tag: str = ORMField("abc", pattern=r"^[a-z]+$")
    label: str = ORMField("ok", max_length=50)


class TestPydanticConstraintValidation(unittest.TestCase):
    """Verify constraints work at model creation time (no DB)."""

    # ── valid construction ────────────────────────────────────────────────

    def test_valid_creation(self):
        m = ConstrainedItem(score=1, rating=0.0, quantity=4, code="XY", tag="hello", label="good")
        self.assertEqual(m.score, 1)
        self.assertEqual(m.rating, 0.0)
        self.assertEqual(m.quantity, 4)
        self.assertEqual(m.code, "XY")

    def test_defaults_are_valid(self):
        m = ConstrainedItem()
        self.assertEqual(m.score, 50)
        self.assertEqual(m.rating, 1.0)
        self.assertEqual(m.quantity, 2)

    def test_boundary_values(self):
        # score: gt=0 →min valid is 1;  le=100 →max valid is 100
        ConstrainedItem(score=1)
        ConstrainedItem(score=100)
        # rating: ge=0.0 →0.0 ok;  lt=10.0 →9.999 ok
        ConstrainedItem(rating=0.0)
        ConstrainedItem(rating=9.999)
        # code: min_length=2, max_length=10
        ConstrainedItem(code="AB")
        ConstrainedItem(code="A" * 10)

    # ── gt / le ───────────────────────────────────────────────────────────

    def test_gt_rejects_boundary(self):
        with self.assertRaises(ValidationError) as ctx:
            ConstrainedItem(score=0)
        self.assertIn("greater_than", str(ctx.exception))

    def test_gt_rejects_negative(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem(score=-5)

    def test_le_rejects_above(self):
        with self.assertRaises(ValidationError) as ctx:
            ConstrainedItem(score=101)
        self.assertIn("less_than_equal", str(ctx.exception))

    # ── ge / lt ───────────────────────────────────────────────────────────

    def test_ge_rejects_below(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem(rating=-0.001)

    def test_lt_rejects_boundary(self):
        with self.assertRaises(ValidationError) as ctx:
            ConstrainedItem(rating=10.0)
        self.assertIn("less_than", str(ctx.exception))

    # ── multiple_of ───────────────────────────────────────────────────────

    def test_multiple_of_valid(self):
        ConstrainedItem(quantity=0)
        ConstrainedItem(quantity=100)

    def test_multiple_of_rejects(self):
        with self.assertRaises(ValidationError) as ctx:
            ConstrainedItem(quantity=3)
        self.assertIn("multiple_of", str(ctx.exception))

    # ── min_length / max_length ───────────────────────────────────────────

    def test_min_length_rejects_short(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem(code="A")

    def test_max_length_rejects_long(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem(code="A" * 11)

    # ── pattern ───────────────────────────────────────────────────────────

    def test_pattern_valid(self):
        ConstrainedItem(tag="lowercase")

    def test_pattern_rejects(self):
        with self.assertRaises(ValidationError) as ctx:
            ConstrainedItem(tag="UPPER")
        self.assertIn("string_pattern_mismatch", str(ctx.exception))

    def test_pattern_rejects_digits(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem(tag="abc123")

    # ── model_validate also enforces constraints ──────────────────────────

    def test_model_validate_enforces_gt(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem.model_validate({"score": 0})

    def test_model_validate_enforces_pattern(self):
        with self.assertRaises(ValidationError):
            ConstrainedItem.model_validate({"tag": "123"})


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ORM round-trip: save →load with constrained fields (5 backends)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_orm_constrained_model(backend: str):
    coll = f"fc_rt_{backend}_{_SUFFIX}"

    class _M(ORMModel, full_collection_name=coll):
        score: int = ORMField(50, gt=0, le=100, index=True)
        rating: float = ORMField(1.0, ge=0.0, lt=10.0)
        quantity: int = ORMField(2, multiple_of=2)
        code: str = ORMField("AB", min_length=2, max_length=10, index=True)
        tag: str = ORMField("abc", pattern=r"^[a-z]+$")
        label: str = ORMField("ok", max_length=50)

    return _M


def _sqlite_client():
    db_path = _TMP_DIR / f"test_fc_{_SUFFIX}.sqlite3"
    c = SQLiteORMClient(db_path=str(db_path))
    c.start()
    return c

def _pg_client():
    c = PostgreSQLORMClient(host="127.0.0.1", port=5433, username="postgres",
                            password="postgres", database="projtemplate_test")
    c.start()
    return c

def _mysql_client():
    c = MySQLORMClient(host="127.0.0.1", port=3307, username="root",
                       password="rootpass", database="projtemplate_test")
    c.start()
    return c

def _mongo_client():
    c = MongoORMClient(mongo_url=os.getenv("TEST_MONGO_URL", "mongodb://127.0.0.1:27017/?directConnection=true"),
                       database="projtemplate_integ_test")
    c.start()
    return c

def _redis_client():
    c = RedisORMClient(url="redis://127.0.0.1:6379/0",
                       prefix=f"orm:fc_test:{_SUFFIX}")
    c.start()
    return c


_CLIENT_FACTORIES = {
    "sqlite": _sqlite_client,
    "postgresql": _pg_client,
    "mysql": _mysql_client,
    "mongo": _mongo_client,
    "redis": _redis_client,
}


class _ORMRoundTripBase(unittest.IsolatedAsyncioTestCase):
    """Base class for constraint round-trip tests —one subclass per backend."""
    __test__ = False
    _backend: ClassVar[str]
    _client = None
    _model_cls = None

    @classmethod
    def _make_client(cls):
        return _CLIENT_FACTORIES[cls._backend]()

    async def asyncSetUp(self):
        self._client = self._make_client()
        if self.__class__._model_cls is None:
            self.__class__._model_cls = _make_orm_constrained_model(self._backend)

    # ── helpers ───────────────────────────────────────────────────────────

    async def _save(self, **kwargs):
        C = self._model_cls
        C.Client = self._client
        obj = C(**kwargs)
        await obj.save()
        return obj

    async def _load(self, obj_id: str):
        C = self._model_cls
        C.Client = self._client
        return await self._client.get(C, obj_id)

    async def _search(self, **query):
        C = self._model_cls
        C.Client = self._client
        results = []
        async for item in self._client.search(C, query):
            results.append(item)
        return results

    # ── round-trip tests ──────────────────────────────────────────────────

    async def test_save_load_defaults(self):
        """Save with all defaults, load back, values match."""
        obj = await self._save()
        loaded = await self._load(str(obj.id))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.score, 50)
        self.assertEqual(loaded.rating, 1.0)
        self.assertEqual(loaded.quantity, 2)
        self.assertEqual(loaded.code, "AB")
        self.assertEqual(loaded.tag, "abc")
        self.assertEqual(loaded.label, "ok")

    async def test_save_load_boundary_values(self):
        """Save boundary-valid values, load back correctly."""
        obj = await self._save(score=1, rating=0.0, quantity=0, code="XY", tag="z", label="")
        loaded = await self._load(str(obj.id))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.score, 1)
        self.assertEqual(loaded.rating, 0.0)
        self.assertEqual(loaded.quantity, 0)
        self.assertEqual(loaded.code, "XY")
        self.assertEqual(loaded.tag, "z")

    async def test_save_load_max_boundary(self):
        """Save upper-boundary values."""
        obj = await self._save(score=100, rating=9.99, quantity=100, code="A" * 10)
        loaded = await self._load(str(obj.id))
        self.assertEqual(loaded.score, 100)
        self.assertAlmostEqual(loaded.rating, 9.99, places=2)
        self.assertEqual(loaded.quantity, 100)
        self.assertEqual(len(loaded.code), 10)

    async def test_creation_rejects_invalid_gt(self):
        """Cannot create model with score=0 (gt=0)."""
        with self.assertRaises(ValidationError):
            await self._save(score=0)

    async def test_creation_rejects_invalid_le(self):
        with self.assertRaises(ValidationError):
            await self._save(score=101)

    async def test_creation_rejects_invalid_pattern(self):
        with self.assertRaises(ValidationError):
            await self._save(tag="UPPER")

    async def test_creation_rejects_invalid_min_length(self):
        with self.assertRaises(ValidationError):
            await self._save(code="A")

    async def test_creation_rejects_invalid_max_length(self):
        with self.assertRaises(ValidationError):
            await self._save(code="A" * 11)

    async def test_creation_rejects_invalid_multiple_of(self):
        with self.assertRaises(ValidationError):
            await self._save(quantity=3)

    async def test_query_constrained_field(self):
        """Query on a constrained+indexed field works."""
        obj = await self._save(score=42, code="test")
        results = await self._search(score=42)
        ids = [str(r.id) for r in results]
        self.assertIn(str(obj.id), ids)

    async def test_query_string_constrained_field(self):
        """Query on a string field with max_length/min_length works."""
        obj = await self._save(code="uniq")
        results = await self._search(code="uniq")
        ids = [str(r.id) for r in results]
        self.assertIn(str(obj.id), ids)

    async def test_multiple_constrained_saves(self):
        """Multiple saves with different valid values all load correctly."""
        ids = []
        for s in [1, 25, 50, 75, 100]:
            obj = await self._save(score=s)
            ids.append((str(obj.id), s))
        for oid, expected_score in ids:
            loaded = await self._load(oid)
            self.assertEqual(loaded.score, expected_score)


# ── Generate one concrete test class per ORM backend ──────────────────────────

class TestConstraintRoundTrip_SQLite(_ORMRoundTripBase):
    __test__ = True
    _backend = "sqlite"

class TestConstraintRoundTrip_PostgreSQL(_ORMRoundTripBase):
    __test__ = True
    _backend = "postgresql"

class TestConstraintRoundTrip_MySQL(_ORMRoundTripBase):
    __test__ = True
    _backend = "mysql"

class TestConstraintRoundTrip_MongoDB(_ORMRoundTripBase):
    __test__ = True
    _backend = "mongo"

class TestConstraintRoundTrip_Redis(_ORMRoundTripBase):
    __test__ = True
    _backend = "redis"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Milvus / Vector round-trip with constrained fields
# ═══════════════════════════════════════════════════════════════════════════════

class VecConstrained(VectorORMModel, collection_name=f"fc_vec_{_SUFFIX}"):
    score: int = ORMField(50, gt=0, le=100)
    rating: float = ORMField(1.0, ge=0.0, lt=10.0)
    quantity: int = ORMField(2, multiple_of=2)
    code: str = ORMField("AB", min_length=2, max_length=10)
    tag: str = ORMField("abc", pattern=r"^[a-z]+$")
    label: str = ORMField("ok", max_length=50)
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class TestConstraintRoundTrip_Milvus(unittest.IsolatedAsyncioTestCase):
    """Milvus vector backend: constrained fields survive round-trip."""
    _client = None

    async def asyncSetUp(self):
        self._client = PyMilvusVectorClient(uri=MILVUS_URI)
        self._client.start()
        VecConstrained.Client = self._client

    async def _save(self, **kwargs):
        kwargs.setdefault("embedding", [1.0, 0.0, 0.0, 0.0])
        obj = VecConstrained(**kwargs)
        await obj.save()
        return obj

    async def _load(self, obj_id):
        for _ in range(_CONSISTENCY_RETRIES):
            loaded = await self._client.get(VecConstrained, str(obj_id))
            if loaded is not None:
                return loaded
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        return None

    # ── round-trip ────────────────────────────────────────────────────────

    async def test_save_load_defaults(self):
        obj = await self._save()
        loaded = await self._load(obj.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.score, 50)
        self.assertEqual(loaded.rating, 1.0)
        self.assertEqual(loaded.quantity, 2)
        self.assertEqual(loaded.code, "AB")
        self.assertEqual(loaded.tag, "abc")

    async def test_save_load_boundary_values(self):
        obj = await self._save(score=1, rating=0.0, quantity=0, code="XY", tag="z")
        loaded = await self._load(obj.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.score, 1)
        self.assertEqual(loaded.rating, 0.0)
        self.assertEqual(loaded.quantity, 0)
        self.assertEqual(loaded.code, "XY")

    async def test_save_load_max_boundary(self):
        obj = await self._save(score=100, rating=9.99, quantity=100, code="A" * 10)
        loaded = await self._load(obj.id)
        self.assertEqual(loaded.score, 100)
        self.assertAlmostEqual(loaded.rating, 9.99, places=2)
        self.assertEqual(loaded.quantity, 100)
        self.assertEqual(len(loaded.code), 10)

    async def test_creation_rejects_invalid_gt(self):
        with self.assertRaises(ValidationError):
            await self._save(score=0)

    async def test_creation_rejects_invalid_le(self):
        with self.assertRaises(ValidationError):
            await self._save(score=101)

    async def test_creation_rejects_invalid_pattern(self):
        with self.assertRaises(ValidationError):
            await self._save(tag="UPPER123")

    async def test_creation_rejects_invalid_min_length(self):
        with self.assertRaises(ValidationError):
            await self._save(code="A")

    async def test_creation_rejects_invalid_max_length(self):
        with self.assertRaises(ValidationError):
            await self._save(code="A" * 11)

    async def test_creation_rejects_invalid_multiple_of(self):
        with self.assertRaises(ValidationError):
            await self._save(quantity=3)

    async def test_multiple_constrained_saves(self):
        ids = []
        for s in [1, 25, 50, 75, 100]:
            obj = await self._save(score=s)
            ids.append((str(obj.id), s))
        for oid, expected in ids:
            loaded = await self._load(oid)
            self.assertEqual(loaded.score, expected)

    async def test_vector_search_with_constrained_model(self):
        """Vector search returns results that pass constraint validation."""
        await self._save(score=42, code="alpha")
        await asyncio.sleep(1)
        results = []
        async for r in self._client.search_vector(
            VecConstrained, "alpha query", field="embedding", limit=5
        ):
            results.append(r)
        for r in results:
            self.assertIsInstance(r, VecConstrained)
            self.assertGreater(r.score, 0)
            self.assertLessEqual(r.score, 100)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Milvus max_length from FieldInfo (unit test —no Milvus needed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMilvusMaxLengthFromFieldInfo(unittest.TestCase):
    """Verify _milvus_dtype_for_annotation reads max_length from FieldInfo."""

    def _get_method(self):
        """Get the unbound method for testing."""
        # Create a minimal client just to access the method
        client = PyMilvusVectorClient(uri=MILVUS_URI)
        client.start()
        return client

    def test_str_without_max_length_defaults_65535(self):
        client = self._get_method()
        from pydantic.fields import FieldInfo
        fi = FieldInfo(annotation=str)
        dtype, kw = client._milvus_dtype_for_annotation(str, fi)
        self.assertEqual(kw["max_length"], 65535)

    def test_str_with_max_length_50(self):
        """ORMField(max_length=50) →Milvus VARCHAR(50)."""
        client = self._get_method()
        fi = ORMField("", max_length=50)
        dtype, kw = client._milvus_dtype_for_annotation(str, fi)
        self.assertEqual(kw["max_length"], 50)

    def test_str_with_max_length_10(self):
        client = self._get_method()
        fi = ORMField("", max_length=10)
        dtype, kw = client._milvus_dtype_for_annotation(str, fi)
        self.assertEqual(kw["max_length"], 10)

    def test_str_with_max_length_255(self):
        client = self._get_method()
        fi = ORMField("", max_length=255)
        dtype, kw = client._milvus_dtype_for_annotation(str, fi)
        self.assertEqual(kw["max_length"], 255)

    def test_pydantic_field_max_length(self):
        """Standard Pydantic Field(max_length=100) also works."""
        client = self._get_method()
        fi = PydanticField("", max_length=100)
        dtype, kw = client._milvus_dtype_for_annotation(str, fi)
        self.assertEqual(kw["max_length"], 100)

    def test_int_ignores_field_info(self):
        """Non-str types don't produce max_length."""
        client = self._get_method()
        fi = ORMField(0, gt=0, le=100)
        dtype, kw = client._milvus_dtype_for_annotation(int, fi)
        self.assertNotIn("max_length", kw)

    def test_model_field_max_length_in_schema(self):
        """VecConstrained.code has max_length=10 —verify it propagates."""
        fi = VecConstrained.model_fields["code"]
        client = self._get_method()
        dtype, kw = client._milvus_dtype_for_annotation(fi.annotation, fi)
        self.assertEqual(kw["max_length"], 10)

    def test_model_field_label_max_length(self):
        """VecConstrained.label has max_length=50."""
        fi = VecConstrained.model_fields["label"]
        client = self._get_method()
        dtype, kw = client._milvus_dtype_for_annotation(fi.annotation, fi)
        self.assertEqual(kw["max_length"], 50)

    def test_model_field_tag_no_max_length(self):
        """VecConstrained.tag has pattern but no max_length →65535."""
        fi = VecConstrained.model_fields["tag"]
        client = self._get_method()
        dtype, kw = client._milvus_dtype_for_annotation(fi.annotation, fi)
        self.assertEqual(kw["max_length"], 65535)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SQL schema extraction —ORMFieldSpec with constrained fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLSchemaConstraintExtraction(unittest.TestCase):
    """Verify extract_field_specs picks up max_length from constrained fields."""

    def test_code_field_max_length_10(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test")
        specs = extract_field_specs(M)
        self.assertEqual(specs["code"].max_length, 10)

    def test_label_field_max_length_50(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test2")
        specs = extract_field_specs(M)
        self.assertEqual(specs["label"].max_length, 50)

    def test_tag_field_no_explicit_max_length_uses_default(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test3")
        specs = extract_field_specs(M)
        # tag has pattern but no max_length → falls back to SQL_DEFAULT_VARCHAR_LENGTH (2048)
        from core.storage.orm.field_schema import SQL_DEFAULT_VARCHAR_LENGTH
        self.assertEqual(SQL_DEFAULT_VARCHAR_LENGTH, 2048)
        self.assertEqual(specs["tag"].max_length, SQL_DEFAULT_VARCHAR_LENGTH)

    def test_score_field_is_int_kind(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test4")
        specs = extract_field_specs(M)
        self.assertEqual(specs["score"].kind, "int")

    def test_rating_field_is_float_kind(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test5")
        specs = extract_field_specs(M)
        self.assertEqual(specs["rating"].kind, "float")

    def test_indexed_constrained_field(self):
        from core.storage.orm.field_schema import extract_field_specs
        M = _make_orm_constrained_model("schema_test6")
        specs = extract_field_specs(M)
        self.assertTrue(specs["score"].index)
        self.assertTrue(specs["code"].index)
        self.assertFalse(specs["tag"].index)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ORMField constraint metadata preserved in FieldInfo
# ═══════════════════════════════════════════════════════════════════════════════

class TestORMFieldConstraintMetadata(unittest.TestCase):
    """Verify ORMField() correctly passes Pydantic constraints to FieldInfo.metadata."""

    def test_gt_in_metadata(self):
        import annotated_types as at
        fi = ORMField(0, gt=0)
        gt_found = any(isinstance(m, at.Gt) for m in fi.metadata)
        self.assertTrue(gt_found, "Gt not found in metadata")

    def test_le_in_metadata(self):
        import annotated_types as at
        fi = ORMField(0, le=100)
        le_found = any(isinstance(m, at.Le) for m in fi.metadata)
        self.assertTrue(le_found, "Le not found in metadata")

    def test_ge_in_metadata(self):
        import annotated_types as at
        fi = ORMField(0.0, ge=0.0)
        ge_found = any(isinstance(m, at.Ge) for m in fi.metadata)
        self.assertTrue(ge_found, "Ge not found in metadata")

    def test_lt_in_metadata(self):
        import annotated_types as at
        fi = ORMField(0.0, lt=10.0)
        lt_found = any(isinstance(m, at.Lt) for m in fi.metadata)
        self.assertTrue(lt_found, "Lt not found in metadata")

    def test_multiple_of_in_metadata(self):
        import annotated_types as at
        fi = ORMField(0, multiple_of=5)
        mo_found = any(isinstance(m, at.MultipleOf) for m in fi.metadata)
        self.assertTrue(mo_found, "MultipleOf not found in metadata")

    def test_min_length_in_metadata(self):
        import annotated_types as at
        fi = ORMField("", min_length=2)
        ml_found = any(isinstance(m, at.MinLen) for m in fi.metadata)
        self.assertTrue(ml_found, "MinLen not found in metadata")

    def test_max_length_in_metadata(self):
        import annotated_types as at
        fi = ORMField("", max_length=50)
        ml_found = any(isinstance(m, at.MaxLen) for m in fi.metadata)
        self.assertTrue(ml_found, "MaxLen not found in metadata")

    def test_pattern_in_metadata(self):
        fi = ORMField("", pattern=r"^[a-z]+$")
        # Pattern stored as pydantic_core.core_schema or re.Pattern in metadata
        has_pattern = any(
            getattr(m, "pattern", None) is not None
            or (hasattr(m, "func") and "pattern" in str(getattr(m, "func", "")))
            for m in fi.metadata
        )
        self.assertTrue(has_pattern or len(fi.metadata) > 0,
                        "pattern not reflected in metadata")

    def test_combined_constraints(self):
        """Multiple constraints on one field all present."""
        import annotated_types as at
        fi = ORMField(50, gt=0, le=100)
        types_found = {type(m) for m in fi.metadata}
        self.assertIn(at.Gt, types_found)
        self.assertIn(at.Le, types_found)

    def test_index_preserved_with_constraints(self):
        """ORMField-specific 'index' attribute coexists with Pydantic constraints."""
        fi = ORMField(0, gt=0, le=100, index=True)
        self.assertTrue(fi.index)
        import annotated_types as at
        self.assertTrue(any(isinstance(m, at.Gt) for m in fi.metadata))


if __name__ == "__main__":
    unittest.main()
