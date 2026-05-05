const _MODULE_PROMISES = new Map();
const _STYLE_IDS = new Set();

export function ensureStyle(href, id = href) {
  if (_STYLE_IDS.has(id) || document.getElementById(id)) {
    _STYLE_IDS.add(id);
    return;
  }
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
  _STYLE_IDS.add(id);
}

export function ensureScript(src, globalName = "") {
  if (globalName && window[globalName]) {
    return Promise.resolve(window[globalName]);
  }
  if (_MODULE_PROMISES.has(src)) {
    return _MODULE_PROMISES.get(src);
  }
  const promise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve(globalName ? window[globalName] : existing), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve(globalName ? window[globalName] : script);
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
  _MODULE_PROMISES.set(src, promise);
  return promise;
}

export function ensureModule(path) {
  if (_MODULE_PROMISES.has(path)) {
    return _MODULE_PROMISES.get(path);
  }
  const promise = import(path);
  _MODULE_PROMISES.set(path, promise);
  return promise;
}

export async function ensureShoelace() {
  ensureStyle("/vendor/shoelace/themes/light.css", "builtin-shoelace-light-theme");
  const shoelace = await ensureModule("../../vendor/shoelace/shoelace.js");
  shoelace.setBasePath?.("/vendor/shoelace");
  return shoelace;
}

export async function ensureVendor(name, options = {}) {
  if (options.css) {
    for (const href of Array.isArray(options.css) ? options.css : [options.css]) {
      ensureStyle(href, `builtin-vendor-css-${href}`);
    }
  }
  if (options.module) {
    const module = await ensureModule(options.module);
    return options.exportName ? module[options.exportName] : module.default ?? module;
  }
  if (options.script) {
    return ensureScript(options.script, options.globalName || "");
  }
  return ensureModule(`/vendor/${name}/index.js`).then((module) => module.default ?? module);
}