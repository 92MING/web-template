/**
 * page-controls.js
 * ─────────────────────────────────────────────────────────
 * Shared dark-mode + language switching for ALL  pages.
 *
 * Features:
 *   • Dark mode toggle  (html.dark class)
 *   • Language switch    (zh-cn / zh-tw / en)
 *   • Floating buttons   (bottom-right, visibility controllable)
 *   • Query-param init   (?dark=0|1  &lang=zh-cn|zh-tw|en  &controls=0|1)
 *   • postMessage API    (parent / panel can control child pages)
 *
 * Usage in each HTML page:
 *   <script src="/html-assets/js/page-controls.js"></script>
 *
 * Optional per-page translations:
 *   <script>
 *     window.I18N = {
 *       'page-title': { 'zh-cn':'系统概览', 'zh-tw':'系統概覽', en:'System Overview' },
 *       ...
 *     };
 *   </script>
 *   Then on elements: <h1 data-i18n="page-title">系统概览</h1>
 */
(function () {
  'use strict';

  /* ── Constants ─────────────────────────────────────────── */
  const LS_DARK = 'proj-dark';
  const LS_LANG = 'proj-lang';
  const LANGS = ['zh-cn', 'zh-tw', 'en'];
  const LANG_LABELS = { 'zh-cn': '简', 'zh-tw': '繁', en: 'EN' };
  const DEFAULT_LANG = 'zh-cn';
  const THEME_STYLE_ID = 'proj-theme-bridge-style';

  /* ── Simplified ↔ Traditional mapping (common chars) ──── */
  const S2T_MAP = '万与专业丛东丝丢两严丧个丰临为丽举么义乌乐乱书买乱了予争事亏云互亚产亩亲亿仅从仓仪们价众优伙会伟传伤伦伪伞伟体余佣侠侣侥侦侧侨债值倾假偿傲储催億兰关冲决况冻净凑凭几凤处凿刘划别刮制剂刹剧劝办务动势包化币师帅归当录形彻影征径待很御复循微志忆应忍志态怒总恋恒恳恶悬惊惯惫惯慎慨庆广应库彙从復征心忆态惊惧惩愿应恋恳悬悭总惯忧懂怀恐恶惠愤慎庆亿戏户并广应归录彻影态恳惧惊惫扑执扩扫扬扰找承担择揽搜摇摆撑撤撰操擦放效斗无时昼显晓暂暗书曲术机杂权条来极构标栏样桥档检权欢武残毕毡气汇汉污决沈沟没权争为华变让讨论记讲许证识询语诗诚误说谈请负贝贞贡责贫贱贵贺赏赐贫购赠超赵趋跃践踪蹋径辈达还远连迟连适选遥邮释鉴银键闪闻问闭间关阳阴阶际陈陆陕队阵陈限随隐隶难零雾静韩非页顶项须颗额颤风饪驶驾验骑骗髦鬥鬧鱼鸟黑默齿龙';
  const T2S_MAP = '萬與專業叢東絲丟兩嚴喪個豐臨為麗舉麼義烏樂亂書買亂了予爭事虧雲互亞產畝親億僅從倉儀們價眾優夥會偉傳傷倫偽傘偉體餘傭俠侶僥偵側僑債值傾假償傲儲催億蘭關衝決況凍淨湊憑幾鳳處鑿劉劃別刮製劑剎劇勸辦務動勢包化幣師帥歸當錄形徹影徵徑待很禦復循微誌憶應忍誌態怒總戀恆懇惡懸驚慣憊慣慎慨慶廣應庫彙從復徵心憶態驚懼懲願應戀懇懸慳總慣憂懂懷恐惡惠憤慎慶億戲戶並廣應歸錄徹影態懇懼驚憊撲執擴掃揚擾找承擔擇攬搜搖擺撐撤撰操擦放效鬥無時晝顯曉暫暗書曲術機雜權條來極構標欄樣橋檔檢權歡武殘畢氈氣匯漢汙決瀋溝沒權爭為華變讓討論記講許證識詢語詩誠誤說談請負貝貞貢責貧賤貴賀賞賜貧購贈超趙趨躍踐蹤蹋徑輩達還遠連遲連適選遙郵釋鑑銀鍵閃聞問閉間關陽陰階際陳陸陝隊陣陳限隨隱隸難零霧靜韓非頁頂項須顆額顫風飪駛駕驗騎騙髦鬥鬧魚鳥黑默齒龍';
  let _s2tDict = null;
  let _t2sDict = null;
  function _buildDicts() {
    if (_s2tDict) return;
    _s2tDict = {};
    _t2sDict = {};
    for (let i = 0; i < S2T_MAP.length; i++) {
      const s = S2T_MAP[i], t = T2S_MAP[i];
      if (s !== t) { _s2tDict[s] = t; _t2sDict[t] = s; }
    }
  }
  function toTraditional(text) {
    _buildDicts();
    let out = '';
    for (const ch of text) out += (_s2tDict[ch] || ch);
    return out;
  }
  function toSimplified(text) {
    _buildDicts();
    let out = '';
    for (const ch of text) out += (_t2sDict[ch] || ch);
    return out;
  }

  /* ── State ─────────────────────────────────────────────── */
  const params = new URLSearchParams(window.location.search);
  let _dark = (() => {
    const q = params.get('dark');
    if (q === '1' || q === 'true') return true;
    if (q === '0' || q === 'false') return false;
    const stored = localStorage.getItem(LS_DARK);
    if (stored === 'true') return true;
    if (stored === 'false') return false;
    // Detect from parent class (when loaded in iframe)
    try { if (window.parent !== window && window.parent.document.documentElement.classList.contains('dark')) return true; } catch {}
    return false;
  })();
  let _lang = (() => {
    const q = params.get('lang');
    if (LANGS.includes(q)) return q;
    const stored = localStorage.getItem(LS_LANG);
    if (LANGS.includes(stored)) return stored;
    return DEFAULT_LANG;
  })();
  let _controlsVisible = (() => {
    const q = params.get('controls');
    if (q === '0' || q === 'false') return false;
    if (q === '1' || q === 'true') return true;
    // Default: hidden when inside an iframe, visible otherwise
    return window.self === window.top;
  })();
  const _embedded = window.self !== window.top;

  /* ── Apply dark mode ───────────────────────────────────── */
  function ensureThemeBridgeStyle() {
    if (document.getElementById(THEME_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = THEME_STYLE_ID;
    style.textContent = `
      :root {
        color-scheme: light;
        --proj-page-bg: #f4f7fb;
        --proj-page-surface: rgba(255,255,255,.92);
        --proj-page-surface-strong: #ffffff;
        --proj-page-text: #0f172a;
        --proj-page-muted: #64748b;
        --proj-page-border: rgba(148,163,184,.28);
        --proj-page-input: #ffffff;
        --proj-page-hover: rgba(226,232,240,.7);
        --proj-page-shadow: 0 14px 30px rgba(15,23,42,.08);
      }
      html.dark {
        color-scheme: dark;
        --proj-page-bg: #020617;
        --proj-page-surface: rgba(15,23,42,.82);
        --proj-page-surface-strong: rgba(2,6,23,.92);
        --proj-page-text: #e2e8f0;
        --proj-page-muted: #94a3b8;
        --proj-page-border: rgba(148,163,184,.22);
        --proj-page-input: rgba(15,23,42,.82);
        --proj-page-hover: rgba(51,65,85,.72);
        --proj-page-shadow: 0 18px 40px rgba(2,6,23,.38);
      }
      html,
      body {
        min-height: 100%;
      }
      body {
        margin: 0;
        background: var(--proj-page-bg) !important;
        color: var(--proj-page-text) !important;
        transition: background-color .18s ease, color .18s ease;
      }
      body > main:first-of-type {
        box-sizing: border-box;
        /* Use viewport units so the rule works even when <body> has no
           explicit height (percentage min-heights would resolve to 0). */
        min-height: 100vh;
        min-height: 100dvh;
      }
      html.dark .glass,
      html.dark .card,
      html.dark .hero,
      html.dark .detail-box,
      html.dark .metric-chip,
      html.dark .status-chip,
      html.dark .preview-box,
      html.dark .chart-shell,
      html.dark .chart-state,
      html.dark .cache-stat,
      html.dark .bg-white,
      html.dark [class~="bg-white"] {
        background: var(--proj-page-surface) !important;
        color: var(--proj-page-text) !important;
        border-color: var(--proj-page-border) !important;
        box-shadow: var(--proj-page-shadow) !important;
      }
      html:not(.dark) .glass,
      html:not(.dark) .metric-chip,
      html:not(.dark) .status-chip,
      html:not(.dark) .preview-box,
      html:not(.dark) .chart-shell,
      html:not(.dark) .field,
      html:not(.dark) .chart-state {
        background: var(--proj-page-surface) !important;
        color: var(--proj-page-text) !important;
        border-color: var(--proj-page-border) !important;
        box-shadow: var(--proj-page-shadow) !important;
      }
      html.dark .bg-slate-950,
      html.dark .bg-slate-950\/45,
      html.dark .bg-slate-950\/50,
      html.dark .bg-slate-950\/60,
      html.dark .bg-slate-950\/90,
      html.dark .bg-slate-900,
      html.dark .bg-slate-900\/70,
      html.dark .bg-slate-900\/80,
      html.dark .bg-slate-900\/90,
      html.dark .bg-gray-900,
      html.dark .bg-gray-950,
      html.dark .bg-slate-800,
      html.dark .bg-gray-800,
      html.dark .bg-gray-100,
      html.dark .bg-gray-50,
      html.dark .bg-slate-100,
      html.dark .bg-slate-50,
      html.dark .bg-indigo-50,
      html.dark .bg-sky-50,
      html.dark .bg-red-50,
      html.dark .bg-emerald-50,
      html.dark .bg-amber-50 {
        background: var(--proj-page-surface-strong) !important;
        border-color: var(--proj-page-border) !important;
      }
      html.dark .field,
      html.dark .input,
      html.dark .select,
      html.dark input:not([type="checkbox"]):not([type="radio"]),
      html.dark textarea,
      html.dark select {
        background: var(--proj-page-input) !important;
        color: var(--proj-page-text) !important;
        border-color: var(--proj-page-border) !important;
      }
      html:not(.dark) .btn {
        background: #ffffff !important;
        color: #0f172a !important;
        border-color: var(--proj-page-border) !important;
      }
      html:not(.dark) .text-white,
      html:not(.dark) .text-slate-100,
      html:not(.dark) .text-slate-200,
      html:not(.dark) .text-slate-300,
      html:not(.dark) .text-gray-900,
      html:not(.dark) .text-slate-900,
      html:not(.dark) .text-gray-800,
      html:not(.dark) .text-slate-800 {
        color: #0f172a !important;
      }
      html:not(.dark) .text-slate-400,
      html:not(.dark) .text-slate-500,
      html:not(.dark) .text-slate-600,
      html:not(.dark) .text-gray-400,
      html:not(.dark) .text-gray-500,
      html:not(.dark) .text-gray-600 {
        color: var(--proj-page-muted) !important;
      }
      html:not(.dark) .border-white\/5,
      html:not(.dark) .border-white\/10,
      html:not(.dark) .border-white\/20 {
        border-color: var(--proj-page-border) !important;
      }
      html:not(.dark) .bg-slate-950,
      html:not(.dark) .bg-slate-950\/45,
      html:not(.dark) .bg-slate-950\/50,
      html:not(.dark) .bg-slate-950\/60,
      html:not(.dark) .bg-slate-950\/90,
      html:not(.dark) .bg-slate-900,
      html:not(.dark) .bg-slate-900\/70,
      html:not(.dark) .bg-slate-900\/80,
      html:not(.dark) .bg-slate-900\/90,
      html:not(.dark) .bg-gray-900,
      html:not(.dark) .bg-gray-950,
      html:not(.dark) .bg-slate-800,
      html:not(.dark) .bg-gray-800 {
        background: rgba(241,245,249,.92) !important;
        border-color: var(--proj-page-border) !important;
      }
      html.dark .btn,
      html.dark .tab-btn:not(.active),
      html.dark .pager-btn {
        background: rgba(30,41,59,.88) !important;
        color: var(--proj-page-text) !important;
        border-color: var(--proj-page-border) !important;
      }
      html:not(.dark) .table-row:hover,
      html:not(.dark) .tb tr:hover td {
        background: var(--proj-page-hover) !important;
      }
      html.dark .table-row:hover,
      html.dark .tb tr:hover td {
        background: rgba(51,65,85,.52) !important;
      }
      html.dark .text-black,
      html.dark .text-gray-900,
      html.dark .text-slate-900,
      html.dark .text-gray-800,
      html.dark .text-slate-800,
      html.dark .text-gray-700,
      html.dark .text-slate-700 {
        color: var(--proj-page-text) !important;
      }
      html.dark .text-gray-600,
      html.dark .text-slate-600,
      html.dark .text-gray-500,
      html.dark .text-slate-500,
      html.dark .text-gray-400,
      html.dark .text-slate-400,
      html.dark .text-gray-300,
      html.dark .text-slate-300 {
        color: var(--proj-page-muted) !important;
      }
      html.dark .border-gray-100,
      html.dark .border-gray-200,
      html.dark .border-gray-300,
      html.dark .border-slate-100,
      html.dark .border-slate-200,
      html.dark .border-slate-300,
      html.dark .border-white\/5,
      html.dark .border-white\/10,
      html.dark .border-white\/20 {
        border-color: var(--proj-page-border) !important;
      }
      html.dark .shadow-sm,
      html.dark .shadow,
      html.dark .shadow-lg,
      html.dark .shadow-xl {
        box-shadow: var(--proj-page-shadow) !important;
      }
      body[data-proj-compact="1"] .metric-card { padding: 12px !important; }
      body[data-proj-compact="1"] .card { border-radius: 14px !important; }

      /* ── Functional Icons (mask-image, color via currentColor) */
      .proj-icon { display:inline-block; width:1em; height:1em; vertical-align:-0.125em; background-color:currentColor; -webkit-mask-repeat:no-repeat; mask-repeat:no-repeat; -webkit-mask-position:center; mask-position:center; -webkit-mask-size:contain; mask-size:contain; flex-shrink:0; }
      .proj-icon-check { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M16.704 5.29a1 1 0 0 1 .006 1.414l-7.5 7.6a1 1 0 0 1-1.42.006l-3.5-3.5a1 1 0 1 1 1.414-1.414l2.79 2.79 6.793-6.89a1 1 0 0 1 1.417-.006z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M16.704 5.29a1 1 0 0 1 .006 1.414l-7.5 7.6a1 1 0 0 1-1.42.006l-3.5-3.5a1 1 0 1 1 1.414-1.414l2.79 2.79 6.793-6.89a1 1 0 0 1 1.417-.006z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-x, .proj-icon-cross { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M4.293 4.293a1 1 0 0 1 1.414 0L10 8.586l4.293-4.293a1 1 0 1 1 1.414 1.414L11.414 10l4.293 4.293a1 1 0 0 1-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 0 1-1.414-1.414L8.586 10 4.293 5.707a1 1 0 0 1 0-1.414z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M4.293 4.293a1 1 0 0 1 1.414 0L10 8.586l4.293-4.293a1 1 0 1 1 1.414 1.414L11.414 10l4.293 4.293a1 1 0 0 1-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 0 1-1.414-1.414L8.586 10 4.293 5.707a1 1 0 0 1 0-1.414z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-warn { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a1 1 0 0 1 1 1v3a1 1 0 0 1-2 0V7a1 1 0 0 1 1-1zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a1 1 0 0 1 1 1v3a1 1 0 0 1-2 0V7a1 1 0 0 1 1-1zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-chevron-down { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.168l3.71-3.938a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.168l3.71-3.938a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-pencil { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path d='M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828z'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path d='M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828z'/></svg>"); }
      .proj-icon-flag { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M3 3.5A1.5 1.5 0 0 1 4.5 2h11a.5.5 0 0 1 .404.79l-2.667 3.71 2.667 3.71A.5.5 0 0 1 15.5 11h-11v6a1 1 0 1 1-2 0V3.5a.5.5 0 0 1 .5-.5z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M3 3.5A1.5 1.5 0 0 1 4.5 2h11a.5.5 0 0 1 .404.79l-2.667 3.71 2.667 3.71A.5.5 0 0 1 15.5 11h-11v6a1 1 0 1 1-2 0V3.5a.5.5 0 0 1 .5-.5z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-arrows-lr { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M7.78 5.22a.75.75 0 0 1 0 1.06L5.06 9h11.19a.75.75 0 0 1 0 1.5H5.06l2.72 2.72a.75.75 0 1 1-1.06 1.06l-4-4a.75.75 0 0 1 0-1.06l4-4a.75.75 0 0 1 1.06 0z' clip-rule='evenodd'/><path fill-rule='evenodd' d='M12.22 14.78a.75.75 0 0 1 0-1.06L14.94 11H3.75a.75.75 0 0 1 0-1.5h11.19l-2.72-2.72a.75.75 0 1 1 1.06-1.06l4 4a.75.75 0 0 1 0 1.06l-4 4a.75.75 0 0 1-1.06 0z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M7.78 5.22a.75.75 0 0 1 0 1.06L5.06 9h11.19a.75.75 0 0 1 0 1.5H5.06l2.72 2.72a.75.75 0 1 1-1.06 1.06l-4-4a.75.75 0 0 1 0-1.06l4-4a.75.75 0 0 1 1.06 0z' clip-rule='evenodd'/><path fill-rule='evenodd' d='M12.22 14.78a.75.75 0 0 1 0-1.06L14.94 11H3.75a.75.75 0 0 1 0-1.5h11.19l-2.72-2.72a.75.75 0 1 1 1.06-1.06l4 4a.75.75 0 0 1 0 1.06l-4 4a.75.75 0 0 1-1.06 0z' clip-rule='evenodd'/></svg>"); }
      .proj-icon-bolt { -webkit-mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M11.983 1.907a.75.75 0 0 0-1.292-.657l-8.5 9.5A.75.75 0 0 0 2.75 12h6.572l-1.305 6.093a.75.75 0 0 0 1.292.657l8.5-9.5A.75.75 0 0 0 17.25 8h-6.572l1.305-6.093z' clip-rule='evenodd'/></svg>"); mask-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='currentColor'><path fill-rule='evenodd' d='M11.983 1.907a.75.75 0 0 0-1.292-.657l-8.5 9.5A.75.75 0 0 0 2.75 12h6.572l-1.305 6.093a.75.75 0 0 0 1.292.657l8.5-9.5A.75.75 0 0 0 17.25 8h-6.572l1.305-6.093z' clip-rule='evenodd'/></svg>"); }
    `;
    document.head.appendChild(style);
  }

  function emitStateChange() {
    try {
      window.dispatchEvent(new CustomEvent('proj-theme-change', { detail: { dark: _dark, lang: _lang } }));
    } catch {}
  }

  function emitLanguageChange() {
    try {
      window.dispatchEvent(new CustomEvent('proj-language-change', { detail: { lang: _lang, dark: _dark } }));
    } catch {}
  }

  function applyDark() {
    document.documentElement.classList.toggle('dark', _dark);
    document.documentElement.dataset.projTheme = _dark ? 'dark' : 'light';
    document.documentElement.dataset.projEmbedded = _embedded ? '1' : '0';
    if (document.body) {
      document.body.dataset.projTheme = _dark ? 'dark' : 'light';
      document.body.dataset.projCompact = '1';
      document.body.dataset.projEmbedded = _embedded ? '1' : '0';
    }
    localStorage.setItem(LS_DARK, _dark);
    const btn = document.getElementById('proj-ctrl-dark');
    if (btn) {
      btn.innerHTML = _dark
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
      btn.title = _dark ? 'Light Mode' : 'Dark Mode';
    }
    emitStateChange();
  }

  /* ── Apply language ────────────────────────────────────── */
  function applyLang() {
    localStorage.setItem(LS_LANG, _lang);
    document.documentElement.lang = _lang === 'zh-tw' ? 'zh-TW' : _lang === 'en' ? 'en' : 'zh-CN';
    document.documentElement.dataset.projLang = _lang;
    // Update button label
    const btn = document.getElementById('proj-ctrl-lang');
    if (btn) btn.textContent = LANG_LABELS[_lang] || _lang;
    // Apply data-i18n
    const dict = window.I18N || {};
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const entry = dict[key];
      if (!entry) return;
      if (entry[_lang] !== undefined) {
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') el.placeholder = entry[_lang];
        else el.textContent = entry[_lang];
      } else if (_lang === 'zh-tw' && entry['zh-cn']) {
        const converted = toTraditional(entry['zh-cn']);
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') el.placeholder = converted;
        else el.textContent = converted;
      }
    });
    // Fallback: if lang=zh-tw and no explicit translations, convert all visible text via TreeWalker
    // (We only apply simple→traditional conversion for non-i18n text nodes when switching to zh-tw)
    emitLanguageChange();
    emitStateChange();
  }

  /* ── Floating controls ─────────────────────────────────── */
  function buildControls() {
    if (document.getElementById('page-controls')) return;
    const wrap = document.createElement('div');
    wrap.id = 'page-controls';
    wrap.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:99999;display:flex;gap:6px;';
    if (!_controlsVisible) wrap.style.display = 'none';
    // Dark toggle
    const darkBtn = document.createElement('button');
    darkBtn.id = 'proj-ctrl-dark';
    darkBtn.type = 'button';
    darkBtn.style.cssText = 'width:36px;height:36px;border-radius:50%;border:1px solid rgba(148,163,184,.35);display:flex;align-items:center;justify-content:center;cursor:pointer;background:rgba(255,255,255,.92);color:#334155;box-shadow:0 2px 8px rgba(0,0,0,.10);transition:all .15s;';
    darkBtn.addEventListener('click', () => {
      _dark = !_dark;
      applyDark();
      // Notify parent if in iframe
      try { if (window.parent !== window) window.parent.postMessage({ type: 'proj-dark-changed', value: _dark }, '*'); } catch {}
    });
    wrap.appendChild(darkBtn);
    // Lang toggle
    const langBtn = document.createElement('button');
    langBtn.id = 'proj-ctrl-lang';
    langBtn.type = 'button';
    langBtn.style.cssText = 'min-width:36px;height:36px;border-radius:18px;border:1px solid rgba(148,163,184,.35);padding:0 10px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:12px;font-weight:700;background:rgba(255,255,255,.92);color:#334155;box-shadow:0 2px 8px rgba(0,0,0,.10);transition:all .15s;';
    langBtn.addEventListener('click', () => {
      const idx = LANGS.indexOf(_lang);
      _lang = LANGS[(idx + 1) % LANGS.length];
      applyLang();
      try { if (window.parent !== window) window.parent.postMessage({ type: 'proj-lang-changed', value: _lang }, '*'); } catch {}
    });
    wrap.appendChild(langBtn);
    document.body.appendChild(wrap);
    // Dark mode adaptive styling for buttons
    const style = document.createElement('style');
    style.textContent = `
      html.dark #page-controls button {
        background: rgba(15,23,42,.88) !important;
        color: #e2e8f0 !important;
        border-color: rgba(148,163,184,.25) !important;
      }
      #page-controls button:hover { opacity:.85; transform:scale(1.06); }
    `;
    document.head.appendChild(style);
  }

  /* ── postMessage listener ──────────────────────────────── */
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (!d || typeof d !== 'object') return;
    switch (d.type) {
      case 'proj-set-dark':
        _dark = !!d.value;
        applyDark();
        break;
      case 'proj-set-lang':
        if (LANGS.includes(d.value)) { _lang = d.value; applyLang(); }
        break;
      case 'proj-set-controls':
        _controlsVisible = !!d.value;
        const wrap = document.getElementById('page-controls');
        if (wrap) wrap.style.display = _controlsVisible ? 'flex' : 'none';
        break;
      case 'proj-sync':
        // Bulk sync from panel: { type:'proj-sync', dark:bool, lang:string }
        if (typeof d.dark === 'boolean') { _dark = d.dark; applyDark(); }
        if (LANGS.includes(d.lang)) { _lang = d.lang; applyLang(); }
        break;
    }
  });

  /* ── Init on DOM ready ─────────────────────────────────── */
  function init() {
    ensureThemeBridgeStyle();
    buildControls();
    applyDark();
    applyLang();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ── Public API (optional) ─────────────────────────────── */
  window.PageControls = window.PageControls || {};
  window.PageControls.setDark = (v) => { _dark = !!v; applyDark(); };
  window.PageControls.setLang = (v) => { if (LANGS.includes(v)) { _lang = v; applyLang(); } };
  window.PageControls.getDark = () => _dark;
  window.PageControls.getLang = () => _lang;
  window.PageControls.setControlsVisible = (v) => {
    _controlsVisible = !!v;
    const wrap = document.getElementById('page-controls');
    if (wrap) wrap.style.display = _controlsVisible ? 'flex' : 'none';
  };
  window.PageControls.LANGS = LANGS;
  window.PageControls.LANG_LABELS = LANG_LABELS;
  window.PageControls.toTraditional = toTraditional;
  window.PageControls.toSimplified = toSimplified;
  window.PageControls.emitLanguageChange = emitLanguageChange;
})();
