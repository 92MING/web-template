// Classic-worker shim for @ffmpeg/ffmpeg 0.12.10 so importScripts(coreURL)
// works with the UMD ffmpeg-core.js bundle without needing COOP/COEP.
//
// This file is loaded as a classic worker (no { type: "module" }), so it can
// use importScripts() and cannot use ESM imports. Constants and error messages
// from const.js / errors.js are inlined.

const FFMessageType = {
  LOAD: "LOAD",
  EXEC: "EXEC",
  WRITE_FILE: "WRITE_FILE",
  READ_FILE: "READ_FILE",
  DELETE_FILE: "DELETE_FILE",
  RENAME: "RENAME",
  CREATE_DIR: "CREATE_DIR",
  LIST_DIR: "LIST_DIR",
  DELETE_DIR: "DELETE_DIR",
  ERROR: "ERROR",
  DOWNLOAD: "DOWNLOAD",
  PROGRESS: "PROGRESS",
  LOG: "LOG",
  MOUNT: "MOUNT",
  UNMOUNT: "UNMOUNT",
};
const ERROR_UNKNOWN_MESSAGE_TYPE = new Error("unknown message type");
const ERROR_NOT_LOADED = new Error("ffmpeg is not loaded, call `await ffmpeg.load()` first");
const ERROR_IMPORT_FAILURE = new Error("failed to import ffmpeg-core.js");

let ffmpeg;

const load = async ({ coreURL, wasmURL, workerURL }) => {
  const first = !ffmpeg;
  if (!coreURL) throw ERROR_IMPORT_FAILURE;
  importScripts(coreURL);
  if (typeof self.createFFmpegCore !== "function") throw ERROR_IMPORT_FAILURE;
  const _wasmURL = wasmURL || coreURL.replace(/\.js$/g, ".wasm");
  const _workerURL = workerURL || coreURL.replace(/\.js$/g, ".worker.js");
  ffmpeg = await self.createFFmpegCore({
    mainScriptUrlOrBlob: `${coreURL}#${btoa(JSON.stringify({ wasmURL: _wasmURL, workerURL: _workerURL }))}`,
  });
  ffmpeg.setLogger((data) => self.postMessage({ type: FFMessageType.LOG, data }));
  ffmpeg.setProgress((data) => self.postMessage({ type: FFMessageType.PROGRESS, data }));
  return first;
};

const exec = ({ args, timeout = -1 }) => {
  ffmpeg.setTimeout(timeout);
  ffmpeg.exec(...args);
  const ret = ffmpeg.ret;
  ffmpeg.reset();
  return ret;
};
const writeFile = ({ path, data }) => { ffmpeg.FS.writeFile(path, data); return true; };
const readFile = ({ path, encoding }) => ffmpeg.FS.readFile(path, { encoding });
const deleteFile = ({ path }) => { ffmpeg.FS.unlink(path); return true; };
const rename = ({ oldPath, newPath }) => { ffmpeg.FS.rename(oldPath, newPath); return true; };
const createDir = ({ path }) => { ffmpeg.FS.mkdir(path); return true; };
const listDir = ({ path }) => {
  const names = ffmpeg.FS.readdir(path);
  const nodes = [];
  for (const name of names) {
    const stat = ffmpeg.FS.stat(`${path}/${name}`);
    nodes.push({ name, isDir: ffmpeg.FS.isDir(stat.mode) });
  }
  return nodes;
};
const deleteDir = ({ path }) => { ffmpeg.FS.rmdir(path); return true; };
const mount = ({ fsType, options, mountPoint }) => {
  const fs = ffmpeg.FS.filesystems[fsType];
  if (!fs) return false;
  ffmpeg.FS.mount(fs, options, mountPoint);
  return true;
};
const unmount = ({ mountPoint }) => { ffmpeg.FS.unmount(mountPoint); return true; };

self.onmessage = async ({ data: { id, type, data: _data } }) => {
  const trans = [];
  let data;
  try {
    if (type !== FFMessageType.LOAD && !ffmpeg) throw ERROR_NOT_LOADED;
    switch (type) {
      case FFMessageType.LOAD:        data = await load(_data); break;
      case FFMessageType.EXEC:        data = exec(_data); break;
      case FFMessageType.WRITE_FILE:  data = writeFile(_data); break;
      case FFMessageType.READ_FILE:   data = readFile(_data); break;
      case FFMessageType.DELETE_FILE: data = deleteFile(_data); break;
      case FFMessageType.RENAME:      data = rename(_data); break;
      case FFMessageType.CREATE_DIR:  data = createDir(_data); break;
      case FFMessageType.LIST_DIR:    data = listDir(_data); break;
      case FFMessageType.DELETE_DIR:  data = deleteDir(_data); break;
      case FFMessageType.MOUNT:       data = mount(_data); break;
      case FFMessageType.UNMOUNT:     data = unmount(_data); break;
      default: throw ERROR_UNKNOWN_MESSAGE_TYPE;
    }
  } catch (e) {
    self.postMessage({ id, type: FFMessageType.ERROR, data: e.toString() });
    return;
  }
  if (data instanceof Uint8Array) trans.push(data.buffer);
  self.postMessage({ id, type, data }, trans);
};
