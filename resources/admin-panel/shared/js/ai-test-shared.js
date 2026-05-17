(function (global) {
	'use strict';

	const STORAGE_PREFIX = 'proj_ai_test_';
	const FALLBACK_LANG = 'zh-cn';
	const LANG_TO_LOCALE = {
		'zh-cn': 'zh-CN',
		'zh-tw': 'zh-TW',
		en: 'en-US',
	};
	let aiApiBasePromise = null;

	function normalizeApiBase(value) {
		let text = String(value || '').trim();
		if (!text) return '';
		if (!text.startsWith('/')) text = '/' + text;
		return text.replace(/\/+/g, '/').replace(/\/$/, '') || '/ai';
	}

	function configuredAiApiBase() {
		const explicitBase = normalizeApiBase(global.__AI_API_BASE__ || global.__FRONTEND_CONFIG__?.ai_api_base);
		return explicitBase || '';
	}

	async function resolveAiApiBase() {
		const configuredBase = configuredAiApiBase();
		if (configuredBase) return configuredBase;
		if (!aiApiBasePromise) {
			aiApiBasePromise = (async () => {
				try {
					const resp = await fetch('/api/server/config', { cache: 'no-store' });
					if (resp.ok) {
						const cfg = await resp.json();
						const internalPrefix = normalizeApiBase(cfg?.internal_path_prefix);
						if (internalPrefix) return normalizeApiBase(`${internalPrefix}/ai`);
					}
				} catch {}
				return '/ai';
			})();
		}
		return aiApiBasePromise;
	}

	async function aiApiPath(path) {
		const base = await resolveAiApiBase();
		const suffix = String(path || '').trim().replace(/^\/ai(?=\/|$)/, '').replace(/^\/+/, '');
		return suffix ? `${base}/${suffix}` : base;
	}

	async function fetchAi(path, options) {
		return fetch(await aiApiPath(path), options);
	}

	function escapeHtml(value) {
		return String(value ?? '')
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}

	function prettyJson(value) {
		if (value == null || value === '') return '';
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return String(value);
		}
	}

	function safeParse(text, fallback = null) {
		try {
			return JSON.parse(text);
		} catch {
			return fallback;
		}
	}

	function formatDuration(ms) {
		if (ms == null || Number.isNaN(Number(ms))) return '—';
		const value = Number(ms);
		if (value < 1000) return `${Math.round(value)} ms`;
		return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} s`;
	}

	function nowIso() {
		return new Date().toISOString();
	}

	function getCurrentLang() {
		try {
			if (global.PageControls && typeof global.PageControls.getLang === 'function') {
				return global.PageControls.getLang() || FALLBACK_LANG;
			}
		} catch {}
		return document?.documentElement?.dataset?.projLang || FALLBACK_LANG;
	}

	function resolveI18n(entry, lang = getCurrentLang()) {
		if (entry == null) return '';
		if (typeof entry === 'string') return entry;
		if (typeof entry !== 'object') return String(entry);
		if (entry[lang] !== undefined) return entry[lang];
		if (lang === 'zh-tw' && entry['zh-cn'] && global.PageControls && typeof global.PageControls.toTraditional === 'function') {
			return global.PageControls.toTraditional(entry['zh-cn']);
		}
		return entry['zh-cn'] ?? entry.en ?? Object.values(entry)[0] ?? '';
	}

	function mergeI18n(dict) {
		if (!dict || typeof dict !== 'object') return global.I18N || {};
		global.I18N = Object.assign(global.I18N || {}, dict);
		return global.I18N;
	}

	function t(key, fallback = '') {
		const dict = global.I18N || {};
		const value = resolveI18n(dict[key], getCurrentLang());
		return value || fallback || key;
	}

	function applyI18n(root = document) {
		if (!root || !root.querySelectorAll) return;
		const dict = global.I18N || {};
		const lang = getCurrentLang();
		root.querySelectorAll('[data-i18n]').forEach((node) => {
			const key = node.getAttribute('data-i18n');
			const value = resolveI18n(dict[key], lang);
			if (!value) return;
			node.textContent = value;
		});
		root.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
			const key = node.getAttribute('data-i18n-placeholder');
			const value = resolveI18n(dict[key], lang);
			if (!value) return;
			node.setAttribute('placeholder', value);
		});
		root.querySelectorAll('[data-i18n-title]').forEach((node) => {
			const key = node.getAttribute('data-i18n-title');
			const value = resolveI18n(dict[key], lang);
			if (!value) return;
			node.setAttribute('title', value);
		});
	}

	function wireI18n(dict, onChange) {
		mergeI18n(dict);
		const apply = () => {
			applyI18n(document);
			if (typeof onChange === 'function') {
				onChange(getCurrentLang());
			}
		};
		window.addEventListener('proj-language-change', apply);
		if (document.readyState === 'loading') {
			document.addEventListener('DOMContentLoaded', apply, { once: true });
		} else {
			apply();
		}
		return apply;
	}

	function toLocaleTime(ts) {
		try {
			return new Date(ts).toLocaleString(LANG_TO_LOCALE[getCurrentLang()] || LANG_TO_LOCALE[FALLBACK_LANG], {
				hour12: false,
				year: 'numeric',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return String(ts || '');
		}
	}

	function copyText(text, okText) {
		return navigator.clipboard.writeText(String(text ?? '')).then(() => okText || '已复制');
	}

	async function parseErrorResponse(resp) {
		const raw = await resp.text();
		const parsed = safeParse(raw, null);
		const detail = parsed?.detail;
		const message = typeof detail === 'string'
			? detail
			: (typeof parsed?.error === 'string' ? parsed.error : raw || `HTTP ${resp.status}`);
		return {
			status: resp.status,
			statusText: resp.statusText,
			message,
			raw,
			parsed,
		};
	}

	function createHistoryStore(key, limit = 20) {
		const storageKey = STORAGE_PREFIX + key;

		function load() {
			try {
				const raw = localStorage.getItem(storageKey);
				const parsed = raw ? JSON.parse(raw) : [];
				return Array.isArray(parsed) ? parsed : [];
			} catch {
				return [];
			}
		}

		function save(items) {
			try {
				localStorage.setItem(storageKey, JSON.stringify(Array.isArray(items) ? items.slice(0, limit) : []));
			} catch {}
		}

		function push(entry) {
			const items = load();
			items.unshift({ id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, ts: nowIso(), ...entry });
			save(items.slice(0, limit));
			return load();
		}

		function clear() {
			try { localStorage.removeItem(storageKey); } catch {}
			return [];
		}

		return { key: storageKey, load, save, push, clear };
	}

	function bindFormState(key, fields) {
		const storageKey = STORAGE_PREFIX + key + '_form';
		let state = {};
		try { state = safeParse(localStorage.getItem(storageKey) || '{}', {}) || {}; } catch {}

		fields.forEach((field) => {
			const el = document.getElementById(field.id);
			if (!el) return;
			if (Object.prototype.hasOwnProperty.call(state, field.id)) {
				if (field.type === 'checkbox') el.checked = !!state[field.id];
				else el.value = state[field.id] ?? '';
			}
			const eventName = field.eventName || (field.type === 'checkbox' ? 'change' : 'input');
			el.addEventListener(eventName, () => {
				const nextState = {};
				fields.forEach((f) => {
					const node = document.getElementById(f.id);
					if (!node) return;
					nextState[f.id] = f.type === 'checkbox' ? !!node.checked : node.value;
				});
				try { localStorage.setItem(storageKey, JSON.stringify(nextState)); } catch {}
			});
		});
	}

	function setInspector(rootId, payload) {
		const root = document.getElementById(rootId);
		if (!root) return;
		const mapping = {
			request: root.querySelector('[data-kind="request"]'),
			response: root.querySelector('[data-kind="response"]'),
			error: root.querySelector('[data-kind="error"]'),
			timing: root.querySelector('[data-kind="timing"]'),
		};
		if (mapping.request) mapping.request.textContent = prettyJson(payload?.request || '') || '—';
		if (mapping.response) mapping.response.textContent = prettyJson(payload?.response || '') || '—';
		if (mapping.error) mapping.error.textContent = prettyJson(payload?.error || '') || '—';
		if (mapping.timing) mapping.timing.textContent = prettyJson(payload?.timing || '') || '—';
	}

	function renderHistoryList(container, items, renderItem) {
		if (!container) return;
		if (!items.length) {
			container.innerHTML = `<div class="ai-empty">${escapeHtml(t('common.emptyHistory', '暂无历史记录'))}</div>`;
			return;
		}
		container.innerHTML = items.map(renderItem).join('');
	}

	async function fetchServiceInfo(kind) {
		const resp = await fetchAi(`services/${encodeURIComponent(String(kind || '').trim())}`, { cache: 'no-store' });
		if (!resp.ok) {
			throw new Error(`load service info failed: ${resp.status}`);
		}
		return resp.json();
	}

	function _sortedKeys(keys, includeDefault) {
		const unique = Array.from(new Set((keys || []).map((item) => String(item || '').trim()).filter(Boolean)));
		if (includeDefault && !unique.includes('default')) unique.unshift('default');
		return unique.sort((a, b) => {
			if (a === 'default') return -1;
			if (b === 'default') return 1;
			return a.localeCompare(b, 'zh-CN');
		});
	}

	function _normalizeTargetValue(value, data) {
		const text = String(value || '').trim();
		if (text === 'client') return 'client';
		if (text && text !== 'service' && text.startsWith('client:')) return 'client';
		if (text && text !== 'service' && data && data.clients && Object.prototype.hasOwnProperty.call(data.clients, text)) {
			return 'client';
		}
		return 'service';
	}

	function _resolveTargetKeys(data, targetValue, includeDefault) {
		const normalizedTarget = _normalizeTargetValue(targetValue, data);
		if (normalizedTarget === 'client') {
			return _sortedKeys(Object.keys((data && data.clients) || {}), false);
		}
		return _sortedKeys(Object.keys((data && data.instances) || {}), includeDefault);
	}

	async function initServiceTargetControls(kind, targetSelectOrId, instanceSelectOrId, options = {}) {
		const targetSelect = typeof targetSelectOrId === 'string' ? document.getElementById(targetSelectOrId) : targetSelectOrId;
		const instanceSelect = typeof instanceSelectOrId === 'string' ? document.getElementById(instanceSelectOrId) : instanceSelectOrId;
		const includeDefault = options.includeDefault !== false;
		const serviceLabel = String(options.serviceLabel || 'service');
		let data = null;

		const getSelection = () => {
			const targetValue = _normalizeTargetValue(targetSelect?.value, data);
			const targetKey = String(instanceSelect?.value || '').trim();
			const clientKey = targetValue === 'client' ? (targetKey || null) : null;
			const serviceKey = targetValue === 'service' ? (targetKey || 'default') : null;
			return {
				kind: String(kind || '').trim(),
				target_value: targetValue,
				target_type: clientKey ? 'client' : 'service',
				target_key: clientKey || serviceKey || null,
				service_key: serviceKey,
				client_key: clientKey,
			};
		};

		const notifyChange = () => {
			if (typeof options.onSelectionChange === 'function') {
				options.onSelectionChange(getSelection());
			}
		};

		const renderTargetOptions = (preferredTargetValue) => {
			if (!targetSelect) return 'service';
			const clientKeys = _sortedKeys(Object.keys((data && data.clients) || {}), false);
			targetSelect.innerHTML = [
				`<option value="service">${escapeHtml(serviceLabel)}</option>`,
				...(clientKeys.length ? [`<option value="client">client</option>`] : []),
			].join('');
			const nextTargetValue = _normalizeTargetValue(preferredTargetValue, data);
			targetSelect.value = nextTargetValue;
			return nextTargetValue;
		};

		const renderInstanceOptions = (targetValue, preferredInstanceValue) => {
			const keys = _resolveTargetKeys(data, targetValue, includeDefault);
			if (instanceSelect) {
				instanceSelect.innerHTML = keys.map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(key)}</option>`).join('');
				const defaultValue = _normalizeTargetValue(targetValue, data) === 'service' ? 'default' : '';
				const nextValue = String(preferredInstanceValue || instanceSelect.value || defaultValue).trim() || defaultValue;
				instanceSelect.value = keys.includes(nextValue) ? nextValue : (keys[0] || '');
				instanceSelect.disabled = keys.length <= 1;
			}
			notifyChange();
			return keys;
		};

		const refresh = async () => {
			data = await fetchServiceInfo(kind);
			const selectedTargetValue = options.selectedTargetValue ?? targetSelect?.value ?? 'service';
			const selectedInstanceValue = options.selectedKeyValue ?? options.selectedInstanceValue ?? instanceSelect?.value ?? 'default';
			const targetValue = renderTargetOptions(selectedTargetValue);
			renderInstanceOptions(targetValue, selectedInstanceValue);
			return data;
		};

		if (targetSelect && !targetSelect.dataset.aiTargetBound) {
			targetSelect.dataset.aiTargetBound = '1';
			targetSelect.addEventListener('change', () => {
				const targetValue = _normalizeTargetValue(targetSelect.value, data);
				renderInstanceOptions(targetValue, instanceSelect?.value || 'default');
			});
		}
		if (instanceSelect && !instanceSelect.dataset.aiTargetBound) {
			instanceSelect.dataset.aiTargetBound = '1';
			instanceSelect.addEventListener('change', () => {
				notifyChange();
			});
		}

		await refresh();

		return {
			kind: String(kind || '').trim(),
			getData: () => data,
			getSelection,
			getRequestFields() {
				const selection = getSelection();
				const fields = {};
				if (selection.service_key) fields.service_key = selection.service_key;
				if (selection.client_key) fields.client_key = selection.client_key;
				return fields;
			},
			buildPath(operation) {
				return buildTargetPath(getSelection(), operation);
			},
			applyTo(payload) {
				const fields = this.getRequestFields();
				if (payload instanceof FormData) {
					Object.entries(fields).forEach(([key, value]) => {
						payload.delete(key);
						payload.append(key, value);
					});
					return payload;
				}
				return Object.assign(payload || {}, fields);
			},
			refresh,
		};
	}

	function buildTargetPath(selection, operation) {
		const kind = encodeURIComponent(String(selection?.kind || '').trim());
		const targetType = selection?.target_type === 'client' ? 'client' : 'service';
		const targetKey = targetType === 'client' ? selection?.client_key : selection?.service_key;
		const key = encodeURIComponent(String(targetKey || 'default').trim() || 'default');
		const suffix = String(operation || '').trim().replace(/^\/+/, '');
		return suffix ? `${kind}/${targetType}/${key}/${suffix}` : `${kind}/${targetType}/${key}`;
	}

	async function loadServiceInstances(kind, selectOrId, options = {}) {
		const select = typeof selectOrId === 'string' ? document.getElementById(selectOrId) : selectOrId;
		const includeDefault = options.includeDefault !== false;
		const selectedValue = String(options.selectedValue ?? select?.value ?? 'default').trim() || 'default';
		let keys = [];
		try {
			const resp = await fetchAi(`services/${encodeURIComponent(String(kind || '').trim())}`, { cache: 'no-store' });
			if (resp.ok) {
				const data = await resp.json();
				const instances = data && typeof data.instances === 'object' ? Object.keys(data.instances) : [];
				keys = instances.map((item) => String(item || '').trim()).filter(Boolean);
			}
		} catch {}
		if (includeDefault && !keys.includes('default')) keys.unshift('default');
		keys = Array.from(new Set(keys)).sort((a, b) => {
			if (a === 'default') return -1;
			if (b === 'default') return 1;
			return a.localeCompare(b, 'zh-CN');
		});
		if (select) {
			select.innerHTML = keys.map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(key)}</option>`).join('');
			select.value = keys.includes(selectedValue) ? selectedValue : (keys[0] || '');
		}
		if (typeof options.onLoaded === 'function') {
			options.onLoaded(keys, select?.value || '');
		}
		return keys;
	}

	global.AITestShared = {
		STORAGE_PREFIX,
		aiApiPath,
		applyI18n,
		bindFormState,
		buildTargetPath,
		copyText,
		createHistoryStore,
		escapeHtml,
		formatDuration,
		fetchAi,
		fetchServiceInfo,
		getCurrentLang,
		initServiceTargetControls,
		mergeI18n,
		nowIso,
		resolveAiApiBase,
		loadServiceInstances,
		parseErrorResponse,
		prettyJson,
		renderHistoryList,
		resolveI18n,
		safeParse,
		setInspector,
		t,
		toLocaleTime,
		wireI18n,
	};
})(window);
