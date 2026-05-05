# -*- coding: utf-8 -*-
"""Global translation registry — public API for runtime i18n."""

import re

from collections.abc import Sequence

from core.utils.text_utils.language import Language


class _TranslationEntry:
    __slots__ = ("key", "translations", "aliases")

    def __init__(
        self,
        key: str,
        translations: dict[str, str] | None = None,
        aliases: list[str] | None = None,
    ):
        self.key = key
        self.translations = translations or {}
        self.aliases = aliases or []


class TranslationLanguage:
    EN = "en"
    ZH_CN = "zh-cn"
    ZH_TW = "zh-tw"


DEFAULT_LANGUAGE = TranslationLanguage.EN
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", re.IGNORECASE)

# In-memory registry.  Persist if you need durability; for a template
# this is usually enough because translations are added at startup.
_registry: dict[str, dict[str, _TranslationEntry]] = {}
_internal_registry: dict[str, _TranslationEntry] = {}


def _category_name(category: str | None) -> str:
    text = str(category or "default").strip().lower()
    return text or "default"


def normalize_language(lang: str | Language | None) -> str:
    found = Language.Find(lang) if lang is not None else None
    if found is not None:
        return str(found.code).strip().lower().replace("_", "-")
    text = str(lang or DEFAULT_LANGUAGE).strip().lower().replace("_", "-")
    return text or DEFAULT_LANGUAGE


def is_language_code(value: str | None) -> bool:
    return bool(value and _LANGUAGE_RE.match(normalize_language(value)))


def _normalize_aliases(aliases: str | Sequence[str] | None) -> list[str] | None:
    if aliases is None:
        return None
    if isinstance(aliases, str):
        values = [aliases]
    else:
        values = [str(item) for item in aliases]
    return [item for item in dict.fromkeys(value.strip() for value in values) if item]


def register_translation(
    key: str,
    lang: str | Language,
    text: str,
    *,
    aliases: str | Sequence[str] | None = None,
    category: str | None = None,
) -> None:
    """Register or update a public category translation."""
    bucket = _registry.setdefault(_category_name(category), {})
    _register_translation_to(bucket, key, lang, text, aliases=aliases)


def _register_internal_translation(
    key: str,
    lang: str | Language,
    text: str,
    *,
    aliases: str | Sequence[str] | None = None,
) -> None:
    """Register an admin/internal UI translation."""
    _register_translation_to(_internal_registry, key, lang, text, aliases=aliases)


def _register_translation_to(
    registry: dict[str, _TranslationEntry],
    key: str,
    lang: str | Language,
    text: str,
    *,
    aliases: str | Sequence[str] | None = None,
) -> None:
    key = str(key or "").strip()
    language = normalize_language(lang)
    if not key or not language:
        return
    entry = registry.get(key)
    if entry is None:
        entry = _TranslationEntry(key=key)
        registry[key] = entry
    entry.translations[language] = str(text)
    normalized_aliases = _normalize_aliases(aliases)
    if normalized_aliases:
        entry.aliases = list(dict.fromkeys([*entry.aliases, *normalized_aliases]))
    for alias in (normalized_aliases or []):
        if alias and alias != key and alias not in registry:
            registry[alias] = entry


def _canonical_entries(registry: dict[str, _TranslationEntry]) -> dict[str, _TranslationEntry]:
    return {
        entry.key: entry
        for entry in dict.fromkeys(registry.values())
    }


def _lookup_translation(registry: dict[str, _TranslationEntry], key: str, lang: str | None = None) -> str:
    """Return the translated text for *key* in *lang*, or *key* itself if missing."""
    entry = registry.get(key)
    if entry is None:
        return key
    language = normalize_language(lang)
    base_language = language.split("-", 1)[0]
    return (
        entry.translations.get(language)
        or entry.translations.get(base_language)
        or entry.translations.get(DEFAULT_LANGUAGE)
        or next(iter(entry.translations.values()), key)
    )


def get_public_translation(category: str, key: str, lang: str | None = None) -> str:
    return _lookup_translation(_registry.get(_category_name(category), {}), key, lang)


def get_internal_translation(key: str, lang: str | None = None) -> str:
    return _lookup_translation(_internal_registry, key, lang)


def get_all_public_translations(category: str, lang: str | None = None) -> dict[str, str]:
    registry = _registry.get(_category_name(category), {})
    return {key: _lookup_translation(registry, key, lang) for key in _canonical_entries(registry)}


def get_all_internal_translations(lang: str | None = None) -> dict[str, str]:
    """Return every canonical key → translated text mapping."""
    return {key: get_internal_translation(key, lang) for key in _canonical_entries(_internal_registry)}


def get_public_translation_catalog(category: str | None = None) -> dict[str, dict[str, str]]:
    """Return language → canonical key → text."""
    categories = [_category_name(category)] if category else list(_registry)
    catalog: dict[str, dict[str, str]] = {}
    for category_name in categories:
        for key, entry in _canonical_entries(_registry.get(category_name, {})).items():
            for lang, text in entry.translations.items():
                catalog.setdefault(lang, {})[key] = text
    return catalog


def get_internal_translation_catalog() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for key, entry in _canonical_entries(_internal_registry).items():
        for lang, text in entry.translations.items():
            catalog.setdefault(lang, {})[key] = text
    return catalog


def get_public_categories() -> set[str]:
    return set(_registry)


def get_registered_languages() -> set[str]:
    languages: set[str] = set()
    for registry in [*_registry.values(), _internal_registry]:
        for entry in _canonical_entries(registry).values():
            languages.update(entry.translations)
    return languages


__all__ = [
    "DEFAULT_LANGUAGE",
    "TranslationLanguage",
    "normalize_language",
    "is_language_code",
    "register_translation",
    "_register_internal_translation",
    "get_public_translation",
    "get_internal_translation",
    "get_all_public_translations",
    "get_all_internal_translations",
    "get_public_translation_catalog",
    "get_internal_translation_catalog",
    "get_public_categories",
    "get_registered_languages",
]
