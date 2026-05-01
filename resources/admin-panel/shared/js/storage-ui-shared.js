(function(global) {
  'use strict';

  function $(id, root) { return (root || document).getElementById(id); }
  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function safeJsonParse(text, fallback) {
    try { return JSON.parse(text); } catch { return fallback; }
  }
  function debounce(fn, wait) {
    let timer = null;
    return function(...args) {
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
      remove(key) { localStorage.removeItem(prefix + ':' + key); },
    };
  }
  function ensureToastWrap() {
    let wrap = document.getElementById('storageSharedToastWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'storageSharedToastWrap';
      wrap.style.cssText = 'position:fixed;top:16px;right:16px;z-index:12000;display:flex;flex-direction:column;gap:8px;max-width:420px;pointer-events:none';
      document.body.appendChild(wrap);
    }
    return wrap;
  }
  function showToast(message, type, timeout) {
    const wrap = ensureToastWrap();
    const el = document.createElement('div');
    const colors = {
      info: '#4f46e5',
      success: '#059669',
      warn: '#d97706',
      error: '#e11d48',
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
    let root = document.getElementById('storageSharedModalRoot');
    if (!root) {
      root = document.createElement('div');
      root.id = 'storageSharedModalRoot';
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
        '<div style="width:min(520px,100%);border-radius:22px;background:var(--bg-card,#fff);border:1px solid rgba(148,163,184,.18);box-shadow:0 25px 50px -12px rgba(0,0,0,.35);padding:24px;">' +
          '<div style="display:flex;align-items:flex-start;gap:14px;">' +
            '<div style="width:44px;height:44px;border-radius:16px;background:' + (tone === 'danger' ? '#ffe4e6' : '#e0e7ff') + ';color:' + (tone === 'danger' ? '#be123c' : '#4338ca') + ';display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;">!</div>' +
            '<div style="flex:1;min-width:0;">' +
              '<h3 style="margin:0;font-size:18px;font-weight:800;">' + escapeHtml(title) + '</h3>' +
              '<div style="margin-top:10px;color:var(--text-secondary,#64748b);font-size:14px;line-height:1.7;white-space:pre-wrap;">' + escapeHtml(text) + '</div>' +
            '</div>' +
          '</div>' +
          '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:22px;">' +
            '<button data-role="cancel" style="border:none;border-radius:12px;padding:9px 14px;background:rgba(148,163,184,.15);cursor:pointer;font-weight:700;">取消</button>' +
            '<button data-role="ok" style="border:none;border-radius:12px;padding:9px 14px;background:' + (tone === 'danger' ? '#e11d48' : '#4f46e5') + ';color:#fff;cursor:pointer;font-weight:700;">' + escapeHtml(okText) + '</button>' +
          '</div>' +
        '</div>';
      function done(value) {
        overlay.remove();
        resolve(!!value);
      }
      overlay.addEventListener('click', (event) => { if (event.target === overlay) done(false); });
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
      next() { revision += 1; return revision; },
      isCurrent(value) { return value === revision; },
      value() { return revision; },
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
  function renderClientShell(options) {
    const clients = options?.clients || [];
    const current = options?.current || clients[0]?.name || 'default';
    const tabsEl = options?.tabsEl;
    const selectEl = options?.selectEl;
    const onChange = options?.onChange;
    const showTabs = options?.showTabs === true;
    const multipleClients = clients.length > 1;
    if (selectEl) {
      selectEl.innerHTML = clients.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join('') || '<option value="default">default</option>';
      selectEl.value = current;
      selectEl.disabled = !multipleClients;
      selectEl.onchange = () => onChange?.(selectEl.value || 'default');
    }
    if (tabsEl) {
      if (!showTabs || !multipleClients) {
        tabsEl.innerHTML = '';
        tabsEl.style.display = 'none';
        return;
      }
      tabsEl.style.display = '';
      tabsEl.innerHTML = clients.map((item) => {
        const active = item.name === current;
        const slot = item.slot ? `<span class="storage-client-slot">${escapeHtml(item.slot)}</span>` : '';
        const showDefaultBadge = !!item.is_default && clients.length > 1;
        const badge = showDefaultBadge ? '<span class="storage-client-badge" aria-label="默认 client">默认</span>' : '';
        const titleParts = [item.name];
        if (item.is_default) titleParts.push('默认 client');
        if (item.backend_type) titleParts.push(item.backend_type);
        return `<button type="button" class="storage-client-tab${active ? ' active' : ''}" data-client="${escapeHtml(item.name)}" title="${escapeHtml(titleParts.join(' · '))}">${slot}<span class="storage-client-label">${escapeHtml(item.name)}</span>${badge}</button>`;
      }).join('');
      tabsEl.querySelectorAll('[data-client]').forEach((node) => {
        node.addEventListener('click', () => onChange?.(node.getAttribute('data-client') || 'default'));
      });
    }
  }
  function updateSegmentedTabs(container) {
    const root = container instanceof Element ? container : null;
    if (!root) return;
    let indicator = root.querySelector('.storage-workspace-indicator');
    if (!indicator) {
      indicator = document.createElement('div');
      indicator.className = 'storage-workspace-indicator';
      root.prepend(indicator);
    }
    const active = root.querySelector('.storage-workspace-tab.active');
    if (!active) {
      indicator.style.opacity = '0';
      indicator.style.width = '0';
      return;
    }
    const rootRect = root.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    indicator.style.opacity = '1';
    indicator.style.width = activeRect.width + 'px';
    indicator.style.transform = 'translateX(' + (activeRect.left - rootRect.left) + 'px)';
  }
  function initSegmentedTabs(root) {
    const host = root || document;
    const containers = Array.from(host.querySelectorAll('.storage-workspace-tabs'));
    containers.forEach((container) => {
      if (container.dataset.segmentedTabsReady === '1') {
        updateSegmentedTabs(container);
        return;
      }
      container.dataset.segmentedTabsReady = '1';
      updateSegmentedTabs(container);
      const observer = new MutationObserver(() => updateSegmentedTabs(container));
      observer.observe(container, { subtree: true, attributes: true, attributeFilter: ['class'] });
      if (typeof ResizeObserver === 'function') {
        const resizeObserver = new ResizeObserver(() => updateSegmentedTabs(container));
        resizeObserver.observe(container);
      } else {
        window.addEventListener('resize', () => updateSegmentedTabs(container));
      }
    });
    window.requestAnimationFrame(() => containers.forEach(updateSegmentedTabs));
  }
  function applyTheme(storageKey) {
    const parentDark = !!window.parent?.document?.documentElement?.classList?.contains('dark');
    const stored = localStorage.getItem(storageKey || 'storage-dark');
    const dark = stored == null ? parentDark : stored === '1';
    document.documentElement.classList.toggle('dark', dark);
    return dark;
  }
  function toggleTheme(storageKey) {
    const dark = !document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem(storageKey || 'storage-dark', dark ? '1' : '0');
    return dark;
  }
  function formatTTL(state, seconds) {
    if (state === 'persistent' || seconds == null) return '永久';
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    if (state === 'expired_or_missing') return '过期/缺失';
    if (value >= 86400) return Math.floor(value / 86400) + 'd ' + Math.floor((value % 86400) / 3600) + 'h';
    if (value >= 3600) return Math.floor(value / 3600) + 'h ' + Math.floor((value % 3600) / 60) + 'm';
    if (value >= 60) return Math.floor(value / 60) + 'm ' + (value % 60) + 's';
    return value + 's';
  }
  function ttlTone(state, seconds) {
    if (state === 'expired_or_missing') return 'pill-rose';
    if (state === 'persistent' || seconds == null) return 'pill-slate';
    if (seconds <= 60) return 'pill-rose';
    if (seconds <= 300) return 'pill-amber';
    return 'pill-emerald';
  }
  function ttlBadge(item) {
    return `<span class="pill ${ttlTone(item?.ttl_state, item?.ttl_seconds)}">${escapeHtml(formatTTL(item?.ttl_state, item?.ttl_seconds))}</span>`;
  }
  function jsonCode(node, payload) {
    if (!node) return;
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload ?? null, null, 2);
    node.textContent = text;
    if (global.hljs && typeof global.hljs.highlightElement === 'function') {
      try { global.hljs.highlightElement(node); } catch {}
    }
  }
  function downloadText(filename, content, mime) {
    const blob = new Blob([content], { type: mime || 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }
  function downloadJSON(filename, payload) {
    downloadText(filename, JSON.stringify(payload, null, 2), 'application/json;charset=utf-8');
  }
  function flattenValue(value) {
    if (value == null) return '';
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
    return JSON.stringify(value);
  }
  function flattenObject(record, prefix, output) {
    const source = record && typeof record === 'object' && !Array.isArray(record) ? record : { value: record };
    const target = output || {};
    Object.entries(source).forEach(([key, value]) => {
      const nextKey = prefix ? prefix + '.' + key : key;
      if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length) flattenObject(value, nextKey, target);
      else target[nextKey] = flattenValue(value);
    });
    return target;
  }
  function toTabularRows(records) {
    const rows = (records || []).map((item) => flattenObject(item, '', {}));
    const columns = [];
    rows.forEach((row) => Object.keys(row).forEach((key) => { if (!columns.includes(key)) columns.push(key); }));
    return { columns, rows };
  }
  function csvEscape(value) {
    const text = String(value ?? '');
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }
  function downloadCSV(filename, records) {
    const table = toTabularRows(records);
    const lines = [table.columns.map(csvEscape).join(',')];
    table.rows.forEach((row) => lines.push(table.columns.map((column) => csvEscape(row[column] ?? '')).join(',')));
    downloadText(filename, '\ufeff' + lines.join('\r\n'), 'text/csv;charset=utf-8');
  }
  function downloadExcel(filename, records, sheetName) {
    const table = toTabularRows(records);
    const header = table.columns.map((column) => '<th style="border:1px solid #cbd5e1;padding:6px 10px;background:#f8fafc">' + escapeHtml(column) + '</th>').join('');
    const body = table.rows.map((row) => '<tr>' + table.columns.map((column) => '<td style="border:1px solid #cbd5e1;padding:6px 10px;vertical-align:top">' + escapeHtml(row[column] ?? '') + '</td>').join('') + '</tr>').join('');
    const html = '<html><head><meta charset="UTF-8"></head><body><table><caption style="caption-side:top;text-align:left;font-weight:700;margin-bottom:8px">' + escapeHtml(sheetName || 'Sheet1') + '</caption><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table></body></html>';
    downloadText(filename, html, 'application/vnd.ms-excel;charset=utf-8');
  }
  function parseCSV(text) {
    const rows = [];
    let row = [];
    let value = '';
    let inQuotes = false;
    const pushValue = () => { row.push(value); value = ''; };
    const pushRow = () => {
      if (row.length || value) {
        pushValue();
        rows.push(row);
      }
      row = [];
    };
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      const next = text[i + 1];
      if (ch === '"') {
        if (inQuotes && next === '"') {
          value += '"';
          i += 1;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) pushValue();
      else if ((ch === '\n' || ch === '\r') && !inQuotes) {
        if (ch === '\r' && next === '\n') i += 1;
        pushRow();
      } else value += ch;
    }
    if (row.length || value) pushRow();
    if (!rows.length) return [];
    const [header, ...rest] = rows;
    return rest.filter((line) => line.some((cell) => String(cell || '').trim())).map((line) => {
      const record = {};
      header.forEach((key, index) => {
        if (!key) return;
        const raw = line[index] ?? '';
        const trimmed = String(raw).trim();
        if (!trimmed) {
          record[key] = '';
          return;
        }
        try { record[key] = JSON.parse(trimmed); }
        catch { record[key] = raw; }
      });
      return record;
    });
  }
  function unsupported(feature, backend) {
    const label = backend ? feature + '：当前 ' + backend + ' 后端暂不支持。' : feature + '：当前后端暂不支持。';
    showToast(label, 'warn', 3600);
    return false;
  }
  function sanitizeMarkdownHtml(html) {
    const div = document.createElement('div');
    div.innerHTML = String(html || '');
    div.querySelectorAll('script,iframe,object,embed,link,style').forEach((node) => node.remove());
    div.querySelectorAll('*').forEach((node) => {
      [...node.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const value = String(attr.value || '');
        if (name.startsWith('on')) node.removeAttribute(attr.name);
        if ((name === 'href' || name === 'src') && /^javascript:/i.test(value)) node.removeAttribute(attr.name);
      });
    });
    return div.innerHTML;
  }
  function initCollapsibles(root, keyPrefix) {
    const scope = root || document;
    const prefix = keyPrefix || 'storage:fold';
    scope.querySelectorAll('details[data-storage-fold]').forEach((node, index) => {
      const name = node.getAttribute('data-storage-fold') || String(index);
      const storageKey = `${prefix}:${name}`;
      try {
        const stored = localStorage.getItem(storageKey);
        if (stored === '0' || stored === '1') node.open = stored === '1';
      } catch {}
      node.addEventListener('toggle', () => {
        try { localStorage.setItem(storageKey, node.open ? '1' : '0'); } catch {}
      });
    });
  }
  global.StorageUI = {
    $, escapeHtml, safeJsonParse, debounce, persist, showToast, confirmDialog,
    createAbortHub, createLatestTracker, request, renderClientShell, applyTheme,
    toggleTheme, formatTTL, ttlTone, ttlBadge, jsonCode, downloadText, downloadJSON,
    flattenObject, toTabularRows, downloadCSV, downloadExcel, parseCSV, unsupported,
    sanitizeMarkdownHtml, initCollapsibles, initSegmentedTabs, updateSegmentedTabs,
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { initSegmentedTabs(document); }, { once: true });
  } else {
    initSegmentedTabs(document);
  }
})(window);
