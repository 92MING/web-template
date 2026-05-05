const XTERM_PATH = "/vendor/xterm/xterm.min.js";
const FIT_PATH = "/vendor/xterm/xterm-addon-fit.min.js";

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
  if (window.Terminal && window.FitAddon) {
    resolve({ Terminal: window.Terminal, FitAddon: window.FitAddon });
    return;
  }
  try {
    await loadScript(XTERM_PATH);
    await loadScript(FIT_PATH);
    resolve({ Terminal: window.Terminal, FitAddon: window.FitAddon });
  } catch (e) {
    reject(e);
  }
});
