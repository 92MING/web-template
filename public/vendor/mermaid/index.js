const GLOBAL_NAME = "mermaid";
const SCRIPT_PATH = "/vendor/mermaid/mermaid.min.js";

function waitForMermaid() {
  if (window.mermaid?.render) return Promise.resolve(window.mermaid);
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      if (window.mermaid?.render) {
        clearInterval(timer);
        resolve(window.mermaid);
      } else if (Date.now() - started > 10000) {
        clearInterval(timer);
        reject(new Error("Mermaid library did not finish loading"));
      }
    }, 50);
  });
}

export default await new Promise(async (resolve, reject) => {
  if (window.mermaid?.render) {
    resolve(window.mermaid);
    return;
  }
  const s = document.createElement("script");
  s.src = SCRIPT_PATH;
  s.onload = () => waitForMermaid().then(resolve, reject);
  s.onerror = () => reject(new Error("Failed to load " + SCRIPT_PATH));
  document.head.appendChild(s);
});
