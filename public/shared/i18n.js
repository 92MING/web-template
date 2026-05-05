const DEFAULT_LANG = "en";
const CATALOG_CACHE = new Map();

function currentLanguage() {
  const pathLang = languageFromPath();
  if (pathLang) return pathLang;
  const cookieLang = languageFromCookie();
  if (cookieLang) return cookieLang;
  const navigatorLang = languageFromNavigator();
  if (navigatorLang) return navigatorLang;
  if (typeof navigator !== "undefined" && navigator.language) {
    return normalizeLang(navigator.language);
  }
  if (typeof document !== "undefined" && document.documentElement && document.documentElement.lang) {
    return normalizeLang(document.documentElement.lang);
  }
  return DEFAULT_LANG;
}

function normalizeLang(lang) {
  return String(lang || DEFAULT_LANG).trim().toLowerCase().replaceAll("_", "-");
}

function languageFromPath() {
  if (typeof location === "undefined") return null;
  const first = String(location.pathname || "").split("/").filter(Boolean)[0];
  if (!first) return null;
  const normalized = normalizeLang(decodeURIComponent(first));
  return /^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/.test(normalized) ? normalized : null;
}

function languageFromCookie() {
  if (typeof document === "undefined" || !document.cookie) return null;
  const candidates = new Map(document.cookie.split(";").map((part) => {
    const [rawKey, ...rest] = part.split("=");
    return [decodeURIComponent(String(rawKey || "").trim()), decodeURIComponent(rest.join("=").trim())];
  }));
  for (const key of ["locale", "lang", "language"]) {
    const value = candidates.get(key);
    if (value) return normalizeLang(value);
  }
  return null;
}

function languageFromNavigator() {
  if (typeof navigator === "undefined") return null;
  const languages = Array.isArray(navigator.languages) ? navigator.languages : [];
  const first = languages.find((item) => item);
  return first ? normalizeLang(first) : null;
}

function resolveUrl(url) {
  const resolver = globalThis.__FRONTEND_CONFIG__ && globalThis.__FRONTEND_CONFIG__.resolveUrl;
  return typeof resolver === "function" ? resolver(url) : url;
}

function frontendI18nConfig() {
  const config = globalThis.__FRONTEND_CONFIG__;
  const i18n = config && typeof config === "object" ? config.i18n : null;
  return i18n && typeof i18n === "object" ? i18n : {};
}

function isCatalogObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isFlatCatalog(value) {
  if (!isCatalogObject(value)) return false;
  return Object.values(value).every((entry) => typeof entry === "string");
}

function isTranslationEntry(value) {
  return isCatalogObject(value) && Object.values(value).every((entry) => typeof entry === "string");
}

function isKeyFirstCatalog(value) {
  if (!isCatalogObject(value) || isFlatCatalog(value)) return false;
  const entries = Object.values(value);
  return entries.length > 0 && entries.every((entry) => isTranslationEntry(entry));
}

function cloneCatalog(catalog) {
  const next = {};
  for (const [key, value] of Object.entries(catalog || {})) {
    if (typeof value === "string") next[key] = value;
  }
  return next;
}

function findLanguageCatalog(payload, lang) {
  const normalized = normalizeLang(lang);
  for (const [key, value] of Object.entries(payload || {})) {
    if (normalizeLang(key) === normalized && isFlatCatalog(value)) {
      return value;
    }
  }
  return null;
}

function resolveTranslationEntry(entry, lang) {
  if (!isTranslationEntry(entry)) return null;
  const normalized = normalizeLang(lang);
  const baseLang = normalized.split("-", 1)[0] || DEFAULT_LANG;
  for (const [key, value] of Object.entries(entry)) {
    if (normalizeLang(key) === normalized) return value;
  }
  for (const [key, value] of Object.entries(entry)) {
    if (normalizeLang(key) === baseLang) return value;
  }
  for (const [key, value] of Object.entries(entry)) {
    if (normalizeLang(key) === DEFAULT_LANG) return value;
  }
  return Object.values(entry)[0] || null;
}

function resolveCatalogPayload(payload, lang) {
  if (isFlatCatalog(payload)) {
    return cloneCatalog(payload);
  }
  if (isKeyFirstCatalog(payload)) {
    const catalog = {};
    for (const [key, entry] of Object.entries(payload)) {
      const text = resolveTranslationEntry(entry, lang);
      if (typeof text === "string") catalog[key] = text;
    }
    return catalog;
  }
  if (!isCatalogObject(payload)) {
    return {};
  }
  const normalized = normalizeLang(lang);
  const baseLang = normalized.split("-", 1)[0] || DEFAULT_LANG;
  return Object.assign(
    {},
    cloneCatalog(findLanguageCatalog(payload, DEFAULT_LANG)),
    baseLang === DEFAULT_LANG ? {} : cloneCatalog(findLanguageCatalog(payload, baseLang)),
    cloneCatalog(findLanguageCatalog(payload, normalized)),
  );
}

function catalogOptions(options = {}) {
  return Object.assign({}, frontendI18nConfig(), options);
}

function resolveInlineCatalog(lang, options = {}) {
  const opts = catalogOptions(options);
  const payload = isCatalogObject(opts.catalogs)
    ? opts.catalogs
    : isCatalogObject(opts.catalog)
      ? opts.catalog
      : null;
  if (payload === null) return null;
  return resolveCatalogPayload(payload, lang);
}

function replaceLangToken(path, lang) {
  return String(path).replace(/\{lang\}/g, encodeURIComponent(lang));
}

function resolveCatalogUrl(lang, options = {}) {
  const normalized = normalizeLang(lang);
  const opts = catalogOptions(options);
  if (typeof opts.resolveCatalogUrl === "function") {
    const resolved = opts.resolveCatalogUrl(normalized, opts);
    return typeof resolved === "string" && resolved ? resolveUrl(resolved) : null;
  }
  const path = [opts.path, opts.catalogPath, opts.dictPath, opts.url].find(
    (value) => typeof value === "string" && value.trim(),
  );
  if (!path) {
    return resolveUrl(`/i18n/${encodeURIComponent(normalized)}`);
  }
  return resolveUrl(replaceLangToken(path, normalized));
}

function catalogCacheKey(url, lang) {
  return `${url || "inline"}::${normalizeLang(lang)}`;
}

async function fetchCatalog(lang, options = {}) {
  const normalized = normalizeLang(lang);
  const opts = catalogOptions(options);
  const inlineCatalog = resolveInlineCatalog(normalized, opts);
  if (inlineCatalog !== null) {
    return inlineCatalog;
  }
  const url = resolveCatalogUrl(normalized, opts);
  const cacheKey = catalogCacheKey(url, normalized);
  if (opts.cache !== false && CATALOG_CACHE.has(cacheKey)) {
    return CATALOG_CACHE.get(cacheKey);
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load i18n catalog for "${normalized}": HTTP ${response.status}`);
  }
  const payload = await response.json();
  const catalog = resolveCatalogPayload(payload, normalized);
  if (opts.cache !== false) {
    CATALOG_CACHE.set(cacheKey, catalog);
  }
  return catalog;
}

function translate(key, catalog, values) {
  let text = catalog && typeof catalog[key] === "string" ? catalog[key] : String(key);
  if (values && typeof values === "object") {
    text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
    ));
  }
  return text;
}

export async function loadI18n(lang, options = {}) {
  const catalog = await fetchCatalog(lang, options);
  return {
    lang: normalizeLang(lang),
    catalog,
    t(key, values) {
      return translate(key, catalog, values);
    },
  };
}

export function createTranslator(options = {}) {
  const opts = Object.assign({ cache: true, fallbackToKey: true }, frontendI18nConfig(), options);
  let _catalog = null;
  let _lang = normalizeLang(opts.lang) || currentLanguage();

  const ensureCatalog = async () => {
    if (_catalog === null) {
      _catalog = await fetchCatalog(_lang, opts);
    }
    return _catalog;
  };

  const translator = async function t(key, values = undefined) {
    try {
      const catalog = await ensureCatalog();
      return translate(key, catalog, values);
    } catch (error) {
      if (!opts.fallbackToKey) throw error;
      return translate(key, null, values);
    }
  };

  translator.setLang = async function (lang) {
    _lang = normalizeLang(lang) || currentLanguage();
    _catalog = null;
    if (opts.cache) {
      const catalog = await fetchCatalog(_lang, opts);
      _catalog = catalog;
    }
  };

  translator.setCatalog = function (catalog) {
    _catalog = resolveCatalogPayload(catalog, _lang);
  };

  translator.lang = () => _lang;
  return translator;
}

export async function requestTranslation(key, options = {}) {
  const opts = typeof options === "string" ? { lang: options } : Object.assign({}, options);
  const i18n = await loadI18n(opts.lang || currentLanguage(), opts);
  return i18n.t(key, opts.values);
}

export async function requestTranslations(options = {}) {
  const opts = typeof options === "string" ? { lang: options } : Object.assign({}, options);
  return fetchCatalog(opts.lang || currentLanguage(), opts);
}

export function useTranslations(category = null, lang = null, options = {}) {
  let resolvedCategory = category;
  let resolvedLang = lang;
  let opts = options;
  if (category && typeof category === "object") {
    opts = category;
    resolvedCategory = opts.category || null;
    resolvedLang = opts.lang || lang;
  }
  const normalized = normalizeLang(resolvedLang || currentLanguage());
  const encodedLang = encodeURIComponent(normalized);
  const path = resolvedCategory
    ? `/locales/${encodeURIComponent(String(resolvedCategory))}/${encodedLang}.json`
    : `/locales/${encodedLang}.json`;
  const loadOptions = Object.assign({}, opts, { path });
  let catalog = {};
  let activeLang = normalized;
  const t = function (key, values = undefined) {
    return translate(key, catalog, values);
  };
  t.ready = fetchCatalog(activeLang, loadOptions).then((nextCatalog) => {
    catalog = nextCatalog;
    return t;
  });
  t.setLang = async function (nextLang) {
    activeLang = normalizeLang(nextLang || currentLanguage());
    const nextPath = resolvedCategory
      ? `/locales/${encodeURIComponent(String(resolvedCategory))}/${encodeURIComponent(activeLang)}.json`
      : `/locales/${encodeURIComponent(activeLang)}.json`;
    catalog = await fetchCatalog(activeLang, Object.assign({}, loadOptions, { path: nextPath }));
    return t;
  };
  t.setCatalog = function (nextCatalog) {
    catalog = resolveCatalogPayload(nextCatalog, activeLang);
  };
  t.lang = () => activeLang;
  t.catalog = () => Object.assign({}, catalog);
  return t;
}

const api = {
  loadI18n,
  createTranslator,
  requestTranslation,
  requestTranslations,
  useTranslations,
  currentLanguage,
  normalizeLang,
  resolveCatalogUrl,
};

globalThis.ProjectI18n = Object.assign({}, globalThis.ProjectI18n || {}, api);
globalThis.requestTranslation = globalThis.requestTranslation || requestTranslation;
globalThis.useTranslations = globalThis.useTranslations || useTranslations;
