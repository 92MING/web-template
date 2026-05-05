const SCRIPT_PATH = "/vendor/highlight/highlight.js";

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

export default await new Promise(async (resolve, reject) => {
  if (window.hljs) {
    resolve(window.hljs);
    return;
  }
  try {
    await loadScript(SCRIPT_PATH);
    resolve(window.hljs);
  } catch (e) {
    reject(e);
  }
});
