import { createTranslator } from '/shared/i18n.js?v=20260429-2';
import { setSharedTheme } from '/shared/components.js?v=20260429-2';

const DEFAULT_LANG_KEY = 'eclass_lang';
const DEFAULT_THEME_KEY = 'eclass_theme';
const DEFAULT_TOKEN_KEY = 'eclass_token';
const DEFAULT_USER_KEY = 'eclass_user';
const DEFAULT_ROLE_KEY = 'eclass_role';

function setElementText(el, text) {
  const textNodes = Array.from(el.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
  if (textNodes.length) {
    textNodes.forEach((node) => {
      node.textContent = text;
    });
    return;
  }
  if (!el.children.length) {
    el.textContent = text;
  }
}

async function translateDocument(translator) {
  for (const el of document.querySelectorAll('[data-i18n]')) {
    const key = el.getAttribute('data-i18n');
    if (!key) continue;
    setElementText(el, await translator(key));
  }

  for (const el of document.querySelectorAll('[data-i18n-placeholder]')) {
    const key = el.getAttribute('data-i18n-placeholder');
    if (!key) continue;
    el.placeholder = await translator(key);
  }

  for (const el of document.querySelectorAll('[data-i18n-label]')) {
    const key = el.getAttribute('data-i18n-label');
    if (!key) continue;
    const text = await translator(key);
    if ('label' in el) el.label = text;
    el.setAttribute('label', text);
  }

  for (const el of document.querySelectorAll('[data-i18n-text]')) {
    const key = el.getAttribute('data-i18n-text');
    if (!key) continue;
    const text = await translator(key);
    if ('text' in el) el.text = text;
    el.setAttribute('text', text);
  }

  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    const key = el.getAttribute('data-i18n-title');
    if (!key) continue;
    const text = await translator(key);
    if ('title' in el) el.title = text;
    el.setAttribute('title', text);
  }

  for (const el of document.querySelectorAll('[data-i18n-subtitle]')) {
    const key = el.getAttribute('data-i18n-subtitle');
    if (!key) continue;
    const text = await translator(key);
    if ('subtitle' in el) el.subtitle = text;
    el.setAttribute('subtitle', text);
  }

  for (const el of document.querySelectorAll('[data-i18n-back-label]')) {
    const key = el.getAttribute('data-i18n-back-label');
    if (!key) continue;
    const text = await translator(key);
    if ('backLabel' in el) el.backLabel = text;
    el.setAttribute('back-label', text);
  }
}

export function createPageBootstrap(options = {}) {
  const {
    translationPath = '/translate.json?v=20260429-2',
    pageTitleKey,
    langKey = DEFAULT_LANG_KEY,
    themeKey = DEFAULT_THEME_KEY,
    tokenKey = DEFAULT_TOKEN_KEY,
    userKey = DEFAULT_USER_KEY,
    roleKey = DEFAULT_ROLE_KEY,
    requireUser = true,
    loginPath = 'login.html',
    authPath = '/auth?action=me',
    validateRole,
    getInvalidRoleRedirect,
    fallbackProfileName,
    profileNameId = 'profile-name',
    onApplyI18n,
    onReady,
    onProfile,
  } = options;

  const token = localStorage.getItem(tokenKey);
  const role = localStorage.getItem(roleKey);
  let leaving = false;
  let lang = localStorage.getItem(langKey) || 'zh-cn';
  const dark = localStorage.getItem(themeKey) === 'dark';
  const $ = (id) => document.getElementById(id);
  const t = createTranslator({ lang, path: translationPath, cache: false });

  function redirectTo(path) {
    leaving = true;
    location.replace(path);
  }

  function clearSession() {
    localStorage.removeItem(userKey);
    localStorage.removeItem(roleKey);
    localStorage.removeItem(tokenKey);
  }

  function syncLanguageControls() {
    for (const control of document.querySelectorAll('builtin-lang-switcher')) {
      control.current = lang;
    }
    const pageHeader = $('page-header');
    if (pageHeader && 'currentLang' in pageHeader) {
      pageHeader.currentLang = lang;
    }
    const appShell = $('app-shell');
    if (appShell && 'currentLang' in appShell) {
      appShell.currentLang = lang;
    }
  }

  function applyTheme() {
    setSharedTheme(dark);
    localStorage.setItem(themeKey, dark ? 'dark' : 'light');
  }

  async function applyI18n() {
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    if (pageTitleKey) {
      document.title = `${await t(pageTitleKey)} - ${await t('eclass.title')}`;
    }
    await translateDocument(t);
    syncLanguageControls();
    if (onApplyI18n) {
      await onApplyI18n({ $, t, lang });
    }
  }

  async function api(path, opts = {}) {
    if (leaving) return null;
    try {
      const headers = { Authorization: `Bearer ${token}`, ...(opts.headers || {}) };
      if (!(opts.body instanceof FormData) && !('Content-Type' in headers)) {
        headers['Content-Type'] = 'application/json';
      }
      const response = await fetch('/api' + path, { ...opts, headers });
      const payload = response.ok ? await response.json() : null;
      if (payload && payload.ok === false && payload.error === '未登录') {
        clearSession();
        redirectTo(loginPath);
        return null;
      }
      return payload;
    } catch (_error) {
      if (!leaving) {
        clearSession();
        redirectTo(loginPath);
      }
      return null;
    }
  }

  async function switchLang(nextLang) {
    lang = nextLang;
    localStorage.setItem(langKey, lang);
    await t.setLang(lang);
    await applyI18n();
  }

  function bindControls() {
    const directLangSwitcher = $('lang-switcher');
    if (directLangSwitcher) {
      directLangSwitcher.addEventListener('lang-change', (e) => {
        switchLang(e.detail.lang);
      });
    }

    document.addEventListener('builtin-lang-change', (e) => {
      if (e.detail?.lang) {
        switchLang(e.detail.lang);
      }
    });

    document.addEventListener('builtin-user-action', (e) => {
      if (e.detail?.action === 'logout') {
        clearSession();
        redirectTo(loginPath);
      }
    });

    document.addEventListener('builtin-theme-change', (e) => {
      localStorage.setItem(themeKey, e.detail.dark ? 'dark' : 'light');
    });

    const logoutButton = $('btn-logout');
    if (logoutButton) {
      logoutButton.addEventListener('click', () => {
        clearSession();
        redirectTo(loginPath);
      });
    }
  }

  function ensureLocalSession() {
    if (!token) {
      clearSession();
      redirectTo(loginPath);
      return false;
    }
    if (requireUser && !localStorage.getItem(userKey)) {
      clearSession();
      redirectTo(loginPath);
      return false;
    }
    if (validateRole && !validateRole(role)) {
      const redirectPath = getInvalidRoleRedirect?.(role);
      if (redirectPath) redirectTo(redirectPath);
      return false;
    }
    return true;
  }

  async function ensureServerSession() {
    const session = await api(authPath);
    if (!session || !session.ok) {
      clearSession();
      redirectTo(loginPath);
      return null;
    }
    if (profileNameId && fallbackProfileName) {
      const profileName = $(profileNameId);
      if (profileName) {
        profileName.textContent = session.user.nickname || session.user.name || session.user.email || fallbackProfileName;
      }
    }
    const appShell = $('app-shell');
    if (appShell) {
      appShell.userName = session.user.nickname || session.user.name || session.user.email || '';
      appShell.userEmail = session.user.email || '';
      appShell.userAvatar = session.user.avatar || '';
    }
    if (onProfile) {
      await onProfile({ $, api, t, lang, session });
    }
    return session;
  }

  async function init() {
    if (!ensureLocalSession()) return false;
    bindControls();
    applyTheme();
    await applyI18n();
    const session = await ensureServerSession();
    if (!session || leaving) return false;
    if (onReady) {
      await onReady({ $, api, t, lang, session, redirectTo, clearSession });
    }
    return true;
  }

  return {
    init,
    api,
    applyI18n,
    switchLang,
    redirectTo,
    clearSession,
    $,
    t,
  };
}
