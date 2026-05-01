(function(global) {
  'use strict';

  const ICONS = {
    sun: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path>',
    moon: '<path d="M12 3a6 6 0 1 0 9 9 9 9 0 1 1-9-9z"></path>',
    refresh: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    broom: '<path d="m3 22 7-7"></path><path d="m14 7 3-3a2.12 2.12 0 1 1 3 3l-3 3"></path><path d="M9 11 4 6l3-3 5 5"></path><path d="m15 5 4 4"></path><path d="m12 8 4 4"></path>',
    play: '<polygon points="6 3 20 12 6 21 6 3"></polygon>',
    plus: '<path d="M12 5v14"></path><path d="M5 12h14"></path>',
    upload: '<path d="M12 16V4"></path><path d="m7 9 5-5 5 5"></path><path d="M20 16.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5"></path>',
    download: '<path d="M12 4v12"></path><path d="m7 11 5 5 5-5"></path><path d="M20 19.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 19.5"></path>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path>',
    edit: '<path d="M12 20h9"></path><path d="m16.5 3.5 4 4L7 21l-4 1 1-4 12.5-14.5z"></path>',
    trash: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>',
    checkCircle: '<path d="M9 12l2 2 4-4"></path><circle cx="12" cy="12" r="9"></circle>',
    xCircle: '<path d="M15 9l-6 6"></path><path d="m9 9 6 6"></path><circle cx="12" cy="12" r="9"></circle>',
    alertTriangle: '<path d="M12 3 2 21h20L12 3z"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V7z"></path>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
    fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 13h8"></path><path d="M8 17h8"></path><path d="M8 9h2"></path>',
    code: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="m10 13-2 2 2 2"></path><path d="m14 17 2-2-2-2"></path>',
    json: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M10 10c-1 0-2 .8-2 2v1c0 .8-.4 1.5-1 2 .6.5 1 1.2 1 2v1c0 1.2 1 2 2 2"></path><path d="M14 10c1 0 2 .8 2 2v1c0 .8.4 1.5 1 2-.6.5-1 1.2-1 2v1c0 1.2-1 2-2 2"></path>',
    yaml: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><circle cx="9" cy="11" r="1"></circle><circle cx="15" cy="15" r="1"></circle><circle cx="9" cy="19" r="1"></circle><path d="M9 12v6"></path><path d="M10 11h4"></path><path d="M10 19h4"></path>',
    python: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M9 10h4a2 2 0 0 1 2 2v1H9a2 2 0 0 0-2 2v1a2 2 0 0 0 2 2h4"></path><path d="M15 14h-4a2 2 0 0 1-2-2v-1h6a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-4"></path><circle cx="10" cy="9" r=".5"></circle><circle cx="14" cy="15" r=".5"></circle>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="m7 9 3 3-3 3"></path><path d="M12 15h5"></path>',
    binary: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><rect x="8" y="10" width="2.5" height="2.5" rx=".4"></rect><rect x="13.5" y="10" width="2.5" height="2.5" rx=".4"></rect><rect x="8" y="15.5" width="2.5" height="2.5" rx=".4"></rect><rect x="13.5" y="15.5" width="2.5" height="2.5" rx=".4"></rect>',
    pdf: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 17v-6h2a1.5 1.5 0 0 1 0 3H8"></path><path d="M13 11h1.5a2.5 2.5 0 0 1 0 5H13z"></path><path d="M18 11h-3"></path><path d="M15 14h2.5"></path>',
    word: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="m8 11 1.2 6 1.3-4 1.3 4 1.2-6"></path><path d="M16 11h2"></path><path d="M16 14h2"></path><path d="M16 17h2"></path>',
    sheet: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><rect x="8" y="10" width="8" height="8" rx="1"></rect><path d="M8 13h8"></path><path d="M11 10v8"></path><path d="M13.5 10v8"></path>',
    presentation: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><rect x="8" y="10" width="8" height="5" rx="1"></rect><path d="m11 11.5 3 1-3 1z"></path><path d="M10 18h4"></path>',
    paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><path d="m21 15-5-5L5 21"></path>',
    video: '<rect x="3" y="5" width="15" height="14" rx="2"></rect><path d="m18 10 4-3v10l-4-3z"></path>',
    audio: '<path d="M11 5 6 9H3v6h3l5 4V5z"></path><path d="M15.5 8.5a5 5 0 0 1 0 7"></path><path d="M18.5 6a9 9 0 0 1 0 12"></path>',
    search: '<circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path>',
    list: '<path d="M8 6h13"></path><path d="M8 12h13"></path><path d="M8 18h13"></path><path d="M3 6h.01"></path><path d="M3 12h.01"></path><path d="M3 18h.01"></path>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="3" y="14" width="7" height="7" rx="1"></rect><rect x="14" y="14" width="7" height="7" rx="1"></rect>',
    tree: '<path d="M12 3v6"></path><path d="M6 9h12"></path><path d="M6 9v12"></path><path d="M18 9v12"></path><path d="M4 21h4"></path><path d="M16 21h4"></path>',
    close: '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>',
    moreHorizontal: '<circle cx="6" cy="12" r="1.5"></circle><circle cx="12" cy="12" r="1.5"></circle><circle cx="18" cy="12" r="1.5"></circle>',
    chevronDown: '<path d="m6 9 6 6 6-6"></path>',
    chevronUp: '<path d="m18 15-6-6-6 6"></path>',
    chevronLeft: '<path d="m15 18-6-6 6-6"></path>',
    chevronRight: '<path d="m9 18 6-6-6-6"></path>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle>',
    move: '<path d="M5 9V5h4"></path><path d="M15 5h4v4"></path><path d="M19 15v4h-4"></path><path d="M9 19H5v-4"></path><path d="M5 5l14 14"></path>',
    tag: '<path d="M20 10 10 20 3 13V4h9l8 6z"></path><circle cx="7.5" cy="7.5" r="1.5"></circle>',
    archive: '<rect x="3" y="4" width="18" height="4" rx="1"></rect><path d="M5 8h14v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8z"></path><path d="M10 12h4"></path>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"></ellipse><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"></path><path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"></path>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7"></path><path d="M3 3v5h5"></path><path d="M12 7v5l3 3"></path>',
    filter: '<path d="M3 5h18"></path><path d="M6 12h12"></path><path d="M10 19h4"></path>',
    info: '<circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path>',
    wand: '<path d="m7 21 3-3"></path><path d="m14.5 3.5 6 6"></path><path d="M5 13 3 11"></path><path d="M7 6 5 4"></path><path d="m14 8 5-5"></path><path d="M9 3 8 8"></path><path d="m3 17 5-1"></path><path d="m21 14-5 1"></path><path d="M16 21l1-5"></path><path d="m19 8-8 8-4 1 1-4 8-8 3 3z"></path>'
  };

  function icon(name, size, cls) {
    const body = ICONS[name] || ICONS.info;
    const iconSize = size || 16;
    return '<svg class="storage-icon ' + (cls || '') + '" xmlns="http://www.w3.org/2000/svg" width="' + iconSize + '" height="' + iconSize + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }

  function normalizeExtension(value) {
    return String(value || '').replace(/^\./, '').toLowerCase();
  }

  function getFileMeta(meta) {
    const name = String(meta && (meta.name || meta.relative_path || meta.path) || '');
    const directExt = normalizeExtension(meta && meta.extension);
    const extension = directExt || normalizeExtension(name.split('.').pop());
    const contentType = String(meta && (meta.contentType || meta.content_type || meta.mimeType || meta.mime_type) || '').toLowerCase();
    const kind = meta && (meta.kind || (meta.is_dir ? 'folder' : 'file')) || 'file';
    return { name: name, extension: extension, contentType: contentType, kind: kind };
  }

  function iconNameForFile(meta) {
    const file = getFileMeta(meta);
    if (file.kind === 'folder') return 'folder';
    if (file.contentType.indexOf('image/') === 0 || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif'].indexOf(file.extension) >= 0) return 'image';
    if (file.contentType.indexOf('video/') === 0 || ['mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv'].indexOf(file.extension) >= 0) return 'video';
    if (file.contentType.indexOf('audio/') === 0 || ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'wma'].indexOf(file.extension) >= 0) return 'audio';
    if (file.extension === 'pdf' || file.contentType.indexOf('pdf') >= 0) return 'pdf';
    if (['doc', 'docx', 'odt', 'wps', 'pages', 'hwp', 'hwpx'].indexOf(file.extension) >= 0) return 'word';
    if (['xls', 'xlsx', 'xlsm', 'xltx', 'xltm', 'ods', 'csv', 'tsv', 'numbers'].indexOf(file.extension) >= 0) return 'sheet';
    if (['ppt', 'pptx', 'odp', 'key'].indexOf(file.extension) >= 0) return 'presentation';
    if (['json', 'jsonl', 'geojson'].indexOf(file.extension) >= 0 || file.contentType.indexOf('json') >= 0) return 'json';
    if (['yaml', 'yml'].indexOf(file.extension) >= 0 || file.contentType.indexOf('yaml') >= 0) return 'yaml';
    if (['py', 'pyi', 'ipynb'].indexOf(file.extension) >= 0) return 'python';
    if (['md', 'markdown', 'mdown'].indexOf(file.extension) >= 0) return 'fileText';
    if (['zip', 'tar', 'gz', 'bz2', '7z', 'rar', 'xz'].indexOf(file.extension) >= 0) return 'archive';
    if (['exe', 'msi', 'bat', 'cmd', 'com', 'ps1', 'sh', 'bash', 'zsh'].indexOf(file.extension) >= 0) return 'terminal';
    if (['bin', 'dll', 'so', 'dylib', 'a', 'lib', 'o', 'obj', 'dat', 'pak', 'wasm', 'class'].indexOf(file.extension) >= 0 || file.contentType === 'application/octet-stream') return 'binary';
    if (['js', 'ts', 'jsx', 'tsx', 'rb', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'css', 'html', 'htm', 'xml', 'toml', 'ini', 'cfg', 'conf', 'sql', 'graphql', 'proto', 'vue', 'svelte', 'scss', 'less', 'sass', 'lua', 'php', 'pl', 'r', 'swift', 'kt', 'kts', 'dart', 'erl', 'hrl', 'hs', 'scala', 'groovy'].indexOf(file.extension) >= 0) return 'code';
    if (file.contentType.indexOf('text/') === 0) return 'fileText';
    return 'file';
  }

  function iconForFile(meta, size, cls) {
    return icon(iconNameForFile(meta), size, cls);
  }

  function mount(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function(node) {
      const name = node.getAttribute('data-icon') || 'info';
      const size = Number(node.getAttribute('data-icon-size') || 16);
      node.innerHTML = icon(name, size, node.getAttribute('data-icon-class') || '');
      node.classList.add('storage-icon-slot');
    });
  }

  global.StorageIcons = {
    icon: icon,
    mount: mount,
    getFileMeta: getFileMeta,
    iconNameForFile: iconNameForFile,
    iconForFile: iconForFile,
  };
})(window);
