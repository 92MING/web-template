const SCRIPT_PATH = "/vendor/diff2html/diff.min.js";
export default await new Promise((resolve, reject) => {
  if (window.Diff) { resolve(window.Diff); return; }
  const s = document.createElement("script");
  s.src = SCRIPT_PATH;
  s.onload = () => resolve(window.Diff);
  s.onerror = () => reject(new Error("Failed to load diff"));
  document.head.appendChild(s);
});
