const GLOBAL_NAME = "Plyr";
const SCRIPT_PATH = "/vendor/plyr/plyr.min.js";

export default await new Promise((resolve, reject) => {
  const g = window[GLOBAL_NAME];
  if (g) { resolve(g); return; }
  const s = document.createElement("script");
  s.src = SCRIPT_PATH;
  s.onload = () => resolve(window[GLOBAL_NAME]);
  s.onerror = () => reject(new Error("Failed to load " + SCRIPT_PATH));
  document.head.appendChild(s);
});
