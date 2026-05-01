# -*- coding: utf-8 -*-
"""Global translation registry — public API for runtime i18n."""

import re


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
_registry: dict[str, _TranslationEntry] = {}


def normalize_language(lang: str | None) -> str:
    text = str(lang or DEFAULT_LANGUAGE).strip().lower().replace("_", "-")
    return text or DEFAULT_LANGUAGE


def is_language_code(value: str | None) -> bool:
    return bool(value and _LANGUAGE_RE.match(normalize_language(value)))


def register_translation(
    key: str,
    lang: str,
    text: str,
    *,
    aliases: list[str] | None = None,
) -> None:
    """Register or update a translation for any BCP-47-like language code."""
    key = str(key or "").strip()
    language = normalize_language(lang)
    if not key or not language:
        return
    entry = _registry.get(key)
    if entry is None:
        entry = _TranslationEntry(key=key)
        _registry[key] = entry
    entry.translations[language] = str(text)
    if aliases:
        entry.aliases = list(dict.fromkeys([*entry.aliases, *aliases]))
    for alias in (aliases or []):
        if alias and alias != key and alias not in _registry:
            _registry[alias] = entry


def _canonical_entries() -> dict[str, _TranslationEntry]:
    return {
        entry.key: entry
        for entry in dict.fromkeys(_registry.values())
    }


def get_global_translation(key: str, lang: str | None = None) -> str:
    """Return the translated text for *key* in *lang*, or *key* itself if missing."""
    entry = _registry.get(key)
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


def get_all_global_translations(lang: str | None = None) -> dict[str, str]:
    """Return every canonical key → translated text mapping."""
    return {key: get_global_translation(key, lang) for key in _canonical_entries()}


def get_translation_catalog() -> dict[str, dict[str, str]]:
    """Return language → canonical key → text."""
    catalog: dict[str, dict[str, str]] = {}
    for key, entry in _canonical_entries().items():
        for lang, text in entry.translations.items():
            catalog.setdefault(lang, {})[key] = text
    return catalog


def get_registered_languages() -> set[str]:
    languages: set[str] = set()
    for entry in _canonical_entries().values():
        languages.update(entry.translations)
    return languages


__all__ = [
    "DEFAULT_LANGUAGE",
    "TranslationLanguage",
    "normalize_language",
    "is_language_code",
    "register_translation",
    "get_global_translation",
    "get_all_global_translations",
    "get_translation_catalog",
    "get_registered_languages",
]
