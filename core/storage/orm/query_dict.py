"""Typed-dict definitions for the ORM filter dialect.

These types describe the *wire* representation accepted by every ORM client's
``search`` / ``search_one`` / ``selected_search`` / ``delete`` etc. when the
caller passes a plain dict instead of a :class:`QueryExpression`.

The shape is deliberately **MongoDB-compatible**: a top-level dict is implicitly
``$and`` of its entries; per-field values may be a literal (interpreted as
``$eq``), an operator dict (e.g. ``{"$gte": 1, "$lte": 9}``), or — for ``$and``
/ ``$or`` — a list of nested :class:`QueryDict`.

Operators currently accepted (see ``client_base._field_mapping_to_query_expression``):
``$eq, $ne, $gt, $gte, $lt, $lte, $in, $contains, $wildcard, $regex``. Boolean
composition uses ``$and`` / ``$or``.

These types are surfaced so FastAPI / Pydantic emit a precise OpenAPI schema for
``query`` request bodies instead of opaque ``additionalProperties: true``.

The dollar-prefixed Mongo operator names are not legal Python identifiers, so
``QueryOpDict`` / ``QueryAndDict`` / ``QueryOrDict`` are built with the
functional ``TypedDict(...)`` form.
"""
from __future__ import annotations

from typing import TypedDict


# ---- scalar / value level ---------------------------------------------------

# A literal value that can appear on the right-hand side of an `$eq` (or be
# used as the implicit value when no operator dict is provided). We deliberately
# stay at the wire layer (JSON-shaped) — anything richer should construct a
# :class:`QueryExpression` directly instead of a dict.
QueryScalar = str | int | float | bool | None
QueryValue = QueryScalar | list[QueryScalar]


# Per-field operator dict, e.g. ``{"$gte": 1, "$lte": 9}``. All fields are
# optional; combining several keys means *AND* on the same field.
QueryOpDict = TypedDict(
    'QueryOpDict',
    {
        '$eq': QueryValue,
        '$ne': QueryValue,
        '$gt': QueryScalar,
        '$gte': QueryScalar,
        '$lt': QueryScalar,
        '$lte': QueryScalar,
        '$in': list[QueryScalar],
        '$contains': str,
        '$wildcard': str,
        '$regex': str,
    },
    total=False,
)


# Per-field RHS: either a literal value or an operator dict.
QueryFieldValue = QueryValue | QueryOpDict


# ---- compound / top-level ---------------------------------------------------

# A leaf query: ``{field: literal | QueryOpDict, ...}`` — implicit AND across
# entries. The runtime rejects unknown operators (see
# ``_field_mapping_to_query_expression``), so explicit per-key validation here
# isn't worth the OpenAPI noise.
QueryLeafDict = dict[str, QueryFieldValue]


# Forward-referenced compound dicts. ``list['QueryDict']`` resolves below.
QueryAndDict = TypedDict('QueryAndDict', {'$and': "list[QueryDict]"})
"""Boolean conjunction: ``{"$and": [QueryDict, QueryDict, ...]}``."""

QueryOrDict = TypedDict('QueryOrDict', {'$or': "list[QueryDict]"})
"""Boolean disjunction: ``{"$or": [QueryDict, QueryDict, ...]}``."""


# Top-level query dict the wire accepts.
QueryDict = QueryLeafDict | QueryAndDict | QueryOrDict


__all__ = [
    'QueryScalar',
    'QueryValue',
    'QueryOpDict',
    'QueryFieldValue',
    'QueryLeafDict',
    'QueryAndDict',
    'QueryOrDict',
    'QueryDict',
]
