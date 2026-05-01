(function (global) {
  'use strict';

  const LANGS = ['zh-cn', 'zh-tw', 'en'];

  function parseBoolLike(value, fallback = null) {
    if (value == null || value === '') return fallback;
    if (value === true || value === '1' || value === 'true') return true;
    if (value === false || value === '0' || value === 'false') return false;
    return fallback;
  }

  function toUrl(input) {
    return new URL(input, global.location.origin);
  }

  function toRelative(url) {
    return url.pathname + url.search + url.hash;
  }

  function normalizeUiState(state) {
    const next = { dark: null, lang: null, controls: null };
    if (typeof state?.dark === 'boolean') next.dark = state.dark;
    if (LANGS.includes(state?.lang)) next.lang = state.lang;
    if (typeof state?.controls === 'boolean') next.controls = state.controls;
    return next;
  }

  function withUiState(input, state, options = {}) {
    const url = toUrl(input);
    const next = normalizeUiState(state);
    if (typeof next.dark === 'boolean') url.searchParams.set('dark', next.dark ? '1' : '0');
    else if (options.clearMissing) url.searchParams.delete('dark');
    if (next.lang) url.searchParams.set('lang', next.lang);
    else if (options.clearMissing) url.searchParams.delete('lang');
    if (typeof next.controls === 'boolean') url.searchParams.set('controls', next.controls ? '1' : '0');
    else if (options.clearMissing) url.searchParams.delete('controls');
    return options.absolute ? url.toString() : toRelative(url);
  }

  function readUiState(source) {
    const url = toUrl(source || global.location.href);
    const lang = url.searchParams.get('lang');
    return {
      dark: parseBoolLike(url.searchParams.get('dark'), null),
      controls: parseBoolLike(url.searchParams.get('controls'), null),
      lang: LANGS.includes(lang) ? lang : null,
    };
  }

  function readQueryState(keys, source) {
    const url = toUrl(source || global.location.href);
    const result = {};
    (keys || []).forEach((key) => {
      result[key] = url.searchParams.get(key);
    });
    return result;
  }

  function replaceQueryState(nextState, options = {}) {
    const url = toUrl(options.url || global.location.href);
    Object.entries(nextState || {}).forEach(([key, value]) => {
      if (value == null || value === '') url.searchParams.delete(key);
      else url.searchParams.set(key, String(value));
    });
    const output = options.absolute ? url.toString() : toRelative(url);
    if (options.commit && global.history?.replaceState) {
      global.history.replaceState(null, '', output);
    }
    return output;
  }

  global.ProjUrlStateSync = {
    parseBoolLike,
    withUiState,
    readUiState,
    readQueryState,
    replaceQueryState,
  };
})(window);