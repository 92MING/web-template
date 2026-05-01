// Shared utilities for e-Shop frontend
import { createTranslator } from '/shared/i18n.js';
import { setSharedTheme, BuiltinToast, BuiltinConfirm } from '/shared/components.js';

export { BuiltinToast, BuiltinConfirm };

const STORAGE_LANG_KEY = 'eshop_lang';
const STORAGE_THEME_KEY = 'eshop_theme';
const STORAGE_USER_KEY = 'eshop_user';
const STORAGE_TOKEN_KEY = 'eshop_token';
const STORAGE_ROLE_KEY = 'eshop_role';

const storedLang = localStorage.getItem(STORAGE_LANG_KEY);
const docLang = document.documentElement.lang;
const initialLang = storedLang || (docLang && docLang.toLowerCase().startsWith('en') ? 'en' : 'zh-cn');

export const t = createTranslator({ lang: initialLang });
export const USER_ID = localStorage.getItem(STORAGE_USER_KEY) || 'demo';
export const TOKEN = localStorage.getItem(STORAGE_TOKEN_KEY) || '';

export function getRole() {
  return localStorage.getItem(STORAGE_ROLE_KEY) || 'customer';
}

export function isLoggedIn() {
  return !!localStorage.getItem(STORAGE_USER_KEY) && !!localStorage.getItem(STORAGE_TOKEN_KEY);
}

export function isMerchant() {
  return getRole() === 'merchant' || getRole() === 'admin';
}

export function isAdmin() {
  return getRole() === 'admin';
}

export function requireAuth() {
  if (!isLoggedIn()) {
    location.href = 'login.html';
    return false;
  }
  return true;
}

export function logout() {
  localStorage.removeItem(STORAGE_USER_KEY);
  localStorage.removeItem(STORAGE_TOKEN_KEY);
  localStorage.removeItem(STORAGE_ROLE_KEY);
  location.href = 'login.html';
}

export async function switchLang(lang) {
  localStorage.setItem(STORAGE_LANG_KEY, lang);
  await t.setLang(lang);
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
  await applyI18n();
  document.querySelectorAll('builtin-lang-switcher').forEach(el => {
    el.current = lang;
  });
}

export async function applyI18n() {
  const texts = await Promise.all(
    Array.from(document.querySelectorAll('[data-i18n]')).map(async el => {
      const key = el.getAttribute('data-i18n');
      if (!key) return null;
      return { el, key, text: await t(key) };
    })
  );
  texts.forEach(item => {
    if (!item) return;
    const { el, text } = item;
    const textNodes = Array.from(el.childNodes).filter(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
    if (textNodes.length) {
      textNodes.forEach(n => n.textContent = text);
    } else if (el.tagName === 'BUILTIN-ALERT' || el.tagName === 'BUILTIN-BADGE') {
      el.textContent = text;
    }
  });

  const placeholders = await Promise.all(
    Array.from(document.querySelectorAll('[data-i18n-placeholder]')).map(async el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (!key) return null;
      return { el, text: await t(key) };
    })
  );
  placeholders.forEach(item => {
    if (!item) return;
    item.el.setAttribute('placeholder', item.text);
  });

  const labels = await Promise.all(
    Array.from(document.querySelectorAll('[data-i18n-label]')).map(async el => {
      const key = el.getAttribute('data-i18n-label');
      if (!key) return null;
      return { el, text: await t(key) };
    })
  );
  labels.forEach(item => {
    if (!item) return;
    if ('label' in item.el) item.el.label = item.text;
    item.el.setAttribute('label', item.text);
  });

  const titles = await Promise.all(
    Array.from(document.querySelectorAll('[data-i18n-title]')).map(async el => {
      const key = el.getAttribute('data-i18n-title');
      if (!key) return null;
      return { el, text: await t(key) };
    })
  );
  titles.forEach(item => {
    if (!item) return;
    if ('title' in item.el) item.el.title = item.text;
    item.el.setAttribute('title', item.text);
  });

  const subtitles = await Promise.all(
    Array.from(document.querySelectorAll('[data-i18n-subtitle]')).map(async el => {
      const key = el.getAttribute('data-i18n-subtitle');
      if (!key) return null;
      return { el, text: await t(key) };
    })
  );
  subtitles.forEach(item => {
    if (!item) return;
    if ('subtitle' in item.el) item.el.subtitle = item.text;
    item.el.setAttribute('subtitle', item.text);
  });
}

export function initTheme() {
  const isDark = localStorage.getItem(STORAGE_THEME_KEY) === 'dark';
  setSharedTheme(isDark);
}

export function setupThemeToggle() {
  initTheme();
  document.querySelectorAll('builtin-theme-toggle').forEach(el => {
    el.addEventListener('click', () => {
      const dark = document.documentElement.getAttribute('data-builtin-theme') === 'dark';
      setSharedTheme(!dark);
      localStorage.setItem(STORAGE_THEME_KEY, !dark ? 'dark' : 'light');
    });
  });
}

export async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const currentToken = localStorage.getItem(STORAGE_TOKEN_KEY) || TOKEN;
  if (currentToken) headers['Authorization'] = `Bearer ${currentToken}`;
  const r = await fetch('/api' + path, { ...opts, headers });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    throw new Error(`HTTP ${r.status}: ${text}`);
  }
  const payload = await r.json();
  if (payload?.ok === false && (payload?.error_code === 'not_logged_in' || payload?.error === 'Not logged in')) {
    localStorage.removeItem(STORAGE_USER_KEY);
    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_ROLE_KEY);
    if (!location.pathname.endsWith('/login.html') && !location.pathname.endsWith('login.html')) {
      location.replace('login.html');
    }
  }
  return payload;
}

export function formatPrice(price) {
  return '¥' + price;
}

export function formatDate(ts) {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
}

export function setupLangSwitcher() {
  document.querySelectorAll('builtin-lang-switcher').forEach(el => {
    el.current = t.lang();
    el.addEventListener('lang-change', (e) => switchLang(e.detail.lang));
  });
}

export function bindLogout(buttonId = 'btn-logout') {
  const btn = document.getElementById(buttonId);
  if (btn) btn.addEventListener('click', logout);
}

export async function initEshop() {
  initTheme();
  await applyI18n();
  setupLangSwitcher();
  setupThemeToggle();
  requestAnimationFrame(() => {
    applyI18n();
  });
}
