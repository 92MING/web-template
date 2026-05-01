(function (global) {
  'use strict';

  function byId(id, root) {
    return (root || document).getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeJsonParse(text, fallback) {
    try {
      return JSON.parse(text);
    } catch {
      return fallback;
    }
  }

  function debounce(fn, wait) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait || 200);
    };
  }

  function persist(prefix) {
    return {
      get(key, fallback) {
        const raw = localStorage.getItem(prefix + ':' + key);
        if (raw == null) return fallback;
        try { return JSON.parse(raw); } catch { return raw; }
      },
      set(key, value) {
        if (value === undefined) localStorage.removeItem(prefix + ':' + key);
        else localStorage.setItem(prefix + ':' + key, typeof value === 'string' ? value : JSON.stringify(value));
      },
      remove(key) {
        localStorage.removeItem(prefix + ':' + key);
      },
    };
  }

  function ensureToastWrap() {
    let wrap = byId('projCoreToastWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'projCoreToastWrap';
      wrap.style.cssText = 'position:fixed;top:16px;right:16px;z-index:12000;display:flex;flex-direction:column;gap:8px;max-width:420px;pointer-events:none';
      document.body.appendChild(wrap);
    }
    return wrap;
  }

  function showToast(message, type, timeout) {
    const wrap = ensureToastWrap();
    const el = document.createElement('div');
    const colors = {
      info: '#2563eb',
      success: '#059669',
      warn: '#d97706',
      error: '#dc2626',
    };
    el.style.cssText = 'pointer-events:auto;padding:12px 14px;border-radius:14px;color:#fff;font-size:13px;box-shadow:0 16px 30px rgba(0,0,0,.15);transform:translateY(-6px);opacity:0;transition:transform .18s ease,opacity .18s ease';
    el.style.background = colors[type || 'info'] || colors.info;
    el.textContent = message;
    wrap.appendChild(el);
    requestAnimationFrame(() => {
      el.style.transform = 'translateY(0)';
      el.style.opacity = '1';
    });
    setTimeout(() => {
      el.style.transform = 'translateX(24px)';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 180);
    }, timeout || (type === 'error' ? 4200 : 2600));
  }

  function ensureModalRoot() {
    let root = byId('projCoreModalRoot');
    if (!root) {
      root = document.createElement('div');
      root.id = 'projCoreModalRoot';
      document.body.appendChild(root);
    }
    return root;
  }

  function confirmDialog(options) {
    const root = ensureModalRoot();
    const title = options?.title || '请确认';
    const text = options?.text || '';
    const okText = options?.okText || '确认';
    const tone = options?.tone || 'danger';
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(2,6,23,.45);display:flex;align-items:center;justify-content:center;padding:20px;z-index:11500';
      overlay.innerHTML = '' +
        '<div style="width:min(520px,100%);border-radius:22px;background:var(--proj-page-surface-strong,#fff);border:1px solid rgba(148,163,184,.18);box-shadow:0 25px 50px -12px rgba(0,0,0,.35);padding:24px;">' +
          '<div style="display:flex;align-items:flex-start;gap:14px;">' +
            '<div style="width:44px;height:44px;border-radius:16px;background:' + (tone === 'danger' ? '#ffe4e6' : '#dbeafe') + ';color:' + (tone === 'danger' ? '#be123c' : '#1d4ed8') + ';display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;">!</div>' +
            '<div style="flex:1;min-width:0;">' +
              '<h3 style="margin:0;font-size:18px;font-weight:800;">' + escapeHtml(title) + '</h3>' +
              '<div style="margin-top:10px;color:var(--proj-page-muted,#64748b);font-size:14px;line-height:1.7;white-space:pre-wrap;">' + escapeHtml(text) + '</div>' +
            '</div>' +
          '</div>' +
          '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:22px;">' +
            '<button data-role="cancel" style="border:none;border-radius:12px;padding:9px 14px;background:rgba(148,163,184,.15);cursor:pointer;font-weight:700;">取消</button>' +
            '<button data-role="ok" style="border:none;border-radius:12px;padding:9px 14px;background:' + (tone === 'danger' ? '#dc2626' : '#2563eb') + ';color:#fff;cursor:pointer;font-weight:700;">' + escapeHtml(okText) + '</button>' +
          '</div>' +
        '</div>';

      function done(value) {
        overlay.remove();
        resolve(!!value);
      }

      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) done(false);
      });
      overlay.querySelector('[data-role="cancel"]').onclick = () => done(false);
      overlay.querySelector('[data-role="ok"]').onclick = () => done(true);
      root.appendChild(overlay);
      overlay.querySelector('[data-role="ok"]').focus();
    });
  }

  function createAbortHub() {
    const controllers = new Map();
    return {
      next(scope, mode) {
        const key = scope || 'default';
        const behavior = mode || 'replace';
        if (behavior === 'replace') {
          const prev = controllers.get(key);
          if (prev) prev.abort();
        }
        const controller = new AbortController();
        controllers.set(key, controller);
        return controller;
      },
      clear(scope) {
        const key = scope || 'default';
        const controller = controllers.get(key);
        if (controller) controller.abort();
        controllers.delete(key);
      },
      clearAll() {
        for (const controller of controllers.values()) controller.abort();
        controllers.clear();
      },
    };
  }

  function createLatestTracker() {
    let revision = 0;
    return {
      next() {
        revision += 1;
        return revision;
      },
      isCurrent(value) {
        return value === revision;
      },
      value() {
        return revision;
      },
    };
  }

  async function request(url, options, hub, scope) {
    const controller = hub ? hub.next(scope || 'default') : null;
    const init = {
      ...options,
      headers: { ...(options?.headers || {}) },
      signal: options?.signal || controller?.signal,
    };
    if (init.body && !init.headers['Content-Type'] && !(init.body instanceof FormData)) {
      init.headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(url, init);
    if (!resp.ok) {
      let message = 'HTTP ' + resp.status;
      try {
        const payload = await resp.json();
        message = payload.detail || payload.message || JSON.stringify(payload);
      } catch {
        try { message = await resp.text(); } catch {}
      }
      const error = new Error(message || ('HTTP ' + resp.status));
      error.status = resp.status;
      throw error;
    }
    const type = resp.headers.get('content-type') || '';
    if (type.includes('application/json')) return resp.json();
    return resp;
  }

  global.ProjUtils = {
    $: byId,
    byId,
    escapeHtml,
    safeJsonParse,
    debounce,
    persist,
    showToast,
    confirmDialog,
    createAbortHub,
    createLatestTracker,
    request,
  };
})(window);