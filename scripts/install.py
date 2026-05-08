"""
FastAPI Web Backend Template - 安装脚本
========================================
1. 确认当前 Python 环境
2. pip install -r requirements.txt
3. 检查 LibreOffice (legacy doc/ppt 低保真转换)
4. 下载 / 更新 GeoLite2 City 数据库
2-12. 基础依赖与本地测试组件会先集中探测/确认，再按依赖分批并行安装

支持参数:
-y, --yes    默认同意所有询问
"""

import os
import sys
import shutil
import platform
import subprocess
import urllib.request
import threading
import queue
import re
import time

# 确保 Windows 终端以 UTF-8 输出，避免 GBK 编码报错
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
# ── 颜色辅助 ────────────────────────────────────────────────────
_IS_WIN = os.name == "nt"
_ASSUME_YES = any(arg in ("-y", "--yes") for arg in sys.argv[1:])
_REDIS_MIN_VERSION = (8, 0, 0)
_REDIS_DOCKER_IMAGE = "redis:8"
_ATLAS_CLI_WINGET_ID = "MongoDB.MongoDBAtlasCLI"
_ATLAS_CLI_CHOCO_PACKAGE = "mongodb-atlas"
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# ANSI: 支持 Windows Terminal (WT_SESSION) 和非 Windows
def _color(text: str, code: str) -> str:
    if _IS_WIN and not os.environ.get("WT_SESSION") and not os.environ.get("TERM"):
        return text  # 传统 cmd 不支持 ANSI
    return f"\033[{code}m{text}\033[0m"

def green(t: str)  -> str: return _color(t, "32")
def yellow(t: str) -> str: return _color(t, "33")
def red(t: str)    -> str: return _color(t, "31")
def cyan(t: str)   -> str: return _color(t, "36")
def bold(t: str)   -> str: return _color(t, "1")

# ── 工具函数 ────────────────────────────────────────────────────
_print_lock = threading.Lock()

def tprint(*args, **kwargs):
    """线程安全的 print。"""
    with _print_lock:
        print(*args, **kwargs)

def ask_yn(prompt: str, default_yes: bool = True, require_explicit: bool = False) -> bool:
    if _ASSUME_YES:
        print(f"{prompt} [auto-yes]")
        return True
    hint = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            ans = input(f"{prompt} {hint}: ").strip().lower()
        except EOFError:
            # stdin 已关闭（管道/重定向），使用默认值
            print(f"{'y' if default_yes else 'n'} (stdin EOF，使用默认值)")
            return default_yes
        if ans == "":
            if require_explicit:
                print("  请输入 y 或 n；这里回车不会自动跳过。")
                continue
            return default_yes
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  请输入 y 或 n。")

def run_cmd(cmd: list[str], label: str = "", **kwargs) -> subprocess.CompletedProcess:
    """运行外部命令并线程安全地打印输出。"""
    prefix = f"[{label}] " if label else ""
    tprint(f"  {prefix}> {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)

# ── Windows: 静默安装辅助 ───────────────────────────────────────
def _winget_install(pkg_id: str, label: str = "") -> bool:
    """通过 winget 静默安装，自动接受协议，不弹 UAC 窗口提示（依赖已提权）。"""
    winget = shutil.which("winget")
    if not winget:
        return False
    r = run_cmd([
        winget, "install", "--id", pkg_id, "-e",
        "--accept-source-agreements", "--accept-package-agreements",
        "--silent",  # 不弹 GUI 安装向导
    ], label=label)
    return r.returncode == 0


# ── Linux: 统一 sudo 管理 ───────────────────────────────────────
_SUDO_PREFIX: list[str] = []
_SUDO_INITIALIZED = False

def _init_sudo_linux():
    """在所有安装开始前一次性获取 sudo 凭证，避免后续反复弹出密码提示。"""
    global _SUDO_PREFIX, _SUDO_INITIALIZED
    if _SUDO_INITIALIZED:
        return
    _SUDO_INITIALIZED = True
    if _IS_WIN or sys.platform == "darwin":
        return
    if not shutil.which("sudo"):
        return
    # sudo -v 刷新凭证缓存
    print()
    print(bold("  [Linux] 以下安装步骤需要 sudo 权限，请一次性输入密码："))
    result = subprocess.run(["sudo", "-v"])
    if result.returncode == 0:
        _SUDO_PREFIX = ["sudo"]
        print(green("  sudo 凭证已获取，后续安装将不再要求密码。"))
    else:
        _SUDO_PREFIX = []
        print(yellow("  sudo 凭证获取失败，将以当前权限尝试安装。"))

def sudo() -> list[str]:
    """返回当前平台适用的 sudo 前缀。"""
    if _IS_WIN or sys.platform == "darwin":
        return []
    return _SUDO_PREFIX

def which(name: str) -> str | None:
    """仅按 PATH 查找可执行文件。"""
    return shutil.which(name)


def _version_text(version: tuple[int, int, int] | None) -> str:
    if version is None:
        return "未知版本"
    return ".".join(str(part) for part in version)


def _parse_semver(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _redis_version_from_exe(redis_exe: str) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [redis_exe, "-v"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    output = f"{result.stdout}\n{result.stderr}"
    return _parse_semver(output)


def _redis_version_supported(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version >= _REDIS_MIN_VERSION


def _redis_status() -> dict[str, object]:
    candidates: list[str] = []
    for candidate in (
        which("redis-server"),
    ):
        if candidate and os.path.isfile(candidate):
            candidates.append(candidate)
    if _IS_WIN:
        import glob

        candidates.extend(glob.glob(r"C:\Program Files\Redis*\redis-server.exe"))

    best_path: str | None = None
    best_version: tuple[int, int, int] | None = None
    seen: set[str] = set()
    for candidate in candidates:
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        version = _redis_version_from_exe(candidate)
        if best_path is None:
            best_path = candidate
            best_version = version
            continue
        current = version or (-1, -1, -1)
        best = best_version or (-1, -1, -1)
        if current > best:
            best_path = candidate
            best_version = version

    return {
        "path": best_path,
        "version": best_version,
        "supported": _redis_version_supported(best_version),
    }


def _install_redis_linux_repo(label: str) -> bool:
    if not shutil.which("apt"):
        return False
    commands = [
        sudo() + ["apt-get", "install", "-y", "lsb-release", "curl", "gpg"],
        [
            "bash",
            "-lc",
            "curl -fsSL https://packages.redis.io/gpg | "
            + ("sudo " if sudo() else "")
            + "gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg",
        ],
        sudo() + ["chmod", "644", "/usr/share/keyrings/redis-archive-keyring.gpg"],
        [
            "bash",
            "-lc",
            "echo \"deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main\" | "
            + ("sudo " if sudo() else "")
            + "tee /etc/apt/sources.list.d/redis.list >/dev/null",
        ],
        sudo() + ["apt-get", "update"],
        sudo() + ["apt-get", "install", "-y", "redis", "redis-server", "redis-tools"],
    ]
    for command in commands:
        result = run_cmd(command, label=label)
        if result.returncode != 0:
            return False
    if shutil.which("systemctl"):
        run_cmd(sudo() + ["systemctl", "disable", "redis-server"], label=label)
    return True


def _requirements_include_playwright(req_file: str) -> bool:
    with open(req_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            package_name = line.split(";", 1)[0].strip()
            if not package_name:
                continue
            package_name = package_name.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0]
            package_name = package_name.split("~=", 1)[0].split("!=", 1)[0].split("<", 1)[0].split(">", 1)[0]
            if package_name.strip().lower() == "playwright":
                return True
    return False

# ── Step 1: 确认 Python 环境 ────────────────────────────────────
def step_confirm_env() -> bool:
    print()
    print(bold("=" * 60))
    print(bold("  FastAPI Web Backend Template 安装脚本"))
    print(bold("=" * 60))
    print()
    print(f"  Python:      {cyan(sys.version.split()[0])}")
    print(f"  Executable:  {cyan(sys.executable)}")
    print(f"  Platform:    {cyan(platform.platform())}")
    # 如果处于虚拟环境 / conda 环境则显示
    venv = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_DEFAULT_ENV")
    if venv:
        print(f"  虚拟环境:    {cyan(venv)}")
    print()
    return ask_yn("是否在以上 Python 环境中安装 pip 依赖 (requirements.txt)?", default_yes=True)

# ── Step 2: 安装 pip 依赖 ───────────────────────────────────────
def step_install_requirements() -> bool:
    req_file = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    req_file = os.path.normpath(req_file)

    if not os.path.isfile(req_file):
        print(red(f"  找不到 {req_file}"))
        return False

    print()
    print(bold("[Step 2] 安装 pip 依赖..."))
    print(f"  requirements.txt 路径: {req_file}")
    print()
    if not ask_yn("是否立即安装 requirements.txt 中的 pip 依赖?", default_yes=True):
        print(yellow("  跳过 pip 依赖安装。"))
        return True

    result = run_cmd([sys.executable, "-m", "pip", "install", "-r", req_file])
    if result.returncode != 0:
        print(red("  pip install 失败，请检查以上输出。"))
        return False

    if _requirements_include_playwright(req_file):
        print()
        print(bold("[Step 2.1] 安装 Playwright 浏览器..."))
        result = run_cmd([sys.executable, "-m", "playwright", "install"])
        if result.returncode != 0:
            print(yellow("  playwright install 失败，跳过并继续后续步骤。"))

    print(green("  pip 依赖安装完成。"))
    return True

# ── Step 3: 检查 LibreOffice / soffice ─────────────────────────
def _detect_soffice() -> str | None:
    env_path = os.environ.get("SOFFICE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    for candidate in ("soffice", "libreoffice"):
        found = which(candidate)
        if found:
            return found
    if _IS_WIN:
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    return None

def _install_libreoffice_windows() -> bool:
    choco = shutil.which("choco")

    if _winget_install("TheDocumentFoundation.LibreOffice"):
        return True

    if choco:
        r = run_cmd(["choco", "install", "libreoffice-fresh", "-y"])
        return r.returncode == 0

    print(yellow("  未检测到 winget/choco，无法自动安装 LibreOffice。"))
    print("  请手动安装: https://www.libreoffice.org/download/download-libreoffice/")
    return False

def _install_libreoffice_linux() -> bool:
    has_apt = shutil.which("apt") is not None
    has_sudo = shutil.which("sudo") is not None
    if has_apt:
        prefix = ["sudo"] if has_sudo else []
        r = run_cmd(prefix + ["apt", "update"])
        if r.returncode != 0:
            return False
        r = run_cmd(prefix + ["apt", "install", "-y", "libreoffice"])
        return r.returncode == 0
    print(yellow("  当前 Linux 环境未检测到 apt，无法自动安装 LibreOffice。"))
    return False

def _install_libreoffice_macos() -> bool:
    brew = shutil.which("brew")
    if not brew:
        print(yellow("  未检测到 Homebrew，无法自动安装 LibreOffice。"))
        return False
    r = run_cmd([brew, "install", "--cask", "libreoffice"])
    return r.returncode == 0

def step_check_libreoffice() -> bool:
    print()
    print(bold("[Step 3] 检查 LibreOffice / soffice..."))
    soffice = _detect_soffice()
    if soffice:
        print(f"  {green('✓')} soffice -> {soffice}")
        print(green("  Legacy .doc/.ppt 低保真转换后端已就绪。"))
        return True

    print(f"  {yellow('!')} 未检测到 soffice。")
    print("  这不会影响常规功能，但会降低 `.doc/.ppt` 旧格式的转换效果。")
    print("  Windows 若已安装 Office，也可设置 ENABLE_OFFICE_COM=1 启用 COM 转换。")
    if not ask_yn("是否现在安装 LibreOffice?", default_yes=False, require_explicit=True):
        return True

    if _IS_WIN:
        ok = _install_libreoffice_windows()
    elif sys.platform == "darwin":
        ok = _install_libreoffice_macos()
    else:
        ok = _install_libreoffice_linux()

    if ok:
        soffice = _detect_soffice()
        if soffice:
            print(green(f"  LibreOffice 安装完成: {soffice}"))
        return True

    print(yellow("  LibreOffice 未自动安装成功，可后续手动安装。"))
    return True

# ── Step 4: 检查 / 安装 ffmpeg ──────────────────────────────────
def _ffmpeg_downloader_dir() -> str | None:
    """返回 ffmpeg-downloader 管理的 bin 目录（如已安装该包）。"""
    try:
        import ffmpeg_downloader as ffdl
        d = getattr(ffdl, "ffmpeg_dir", None)
        if d and os.path.isdir(d):
            return d
    except ImportError:
        pass
    return None


def _which_ffmpeg(name: str) -> str | None:
    """先用 PATH 查，再去 ffmpeg-downloader 目录找。"""
    found = which(name)
    if found:
        return found
    extra = _ffmpeg_downloader_dir()
    if extra:
        exe = os.path.join(extra, name + (".exe" if _IS_WIN else ""))
        if os.path.isfile(exe):
            return exe
    return None


def _detect_ffmpeg_tools() -> dict[str, str | None]:
    return {
        "ffmpeg": _which_ffmpeg("ffmpeg"),
        "ffprobe": _which_ffmpeg("ffprobe"),
        "ffplay": _which_ffmpeg("ffplay"),
    }


def _ffmpeg_tools_ready(status: dict[str, str | None]) -> bool:
    return all(status.get(name) for name in ("ffmpeg", "ffprobe", "ffplay"))


def _ffmpeg_downloader_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("ffmpeg_downloader") is not None


def _ensure_ffmpeg_downloader() -> tuple[bool, str]:
    result = run_cmd(
        [sys.executable, "-m", "pip", "install", "ffmpeg-downloader"],
        label="ffmpeg-downloader",
    )
    if result.returncode == 0:
        return True, "完成"
    return False, "失败，请手动执行: python -m pip install ffmpeg-downloader"


def _parallel_probe(probes: dict[str, object]) -> dict[str, object]:
    result_q: queue.Queue[tuple[str, object]] = queue.Queue()
    threads: list[threading.Thread] = []

    def _worker(name: str, fn) -> None:
        try:
            result = fn()
        except Exception as e:
            result = e
        result_q.put((name, result))

    for name, fn in probes.items():
        t = threading.Thread(target=_worker, args=(name, fn), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    results: dict[str, object] = {}
    while not result_q.empty():
        name, result = result_q.get_nowait()
        if isinstance(result, Exception):
            tprint(yellow(f"  ! {name} 检测异常，按未安装处理: {result}"))
            results[name] = None
        else:
            results[name] = result
    return results


def _docker_server_ready(docker_exe) -> bool:
    try:
        r = subprocess.run(
            [docker_exe, "version", "--format", "{{.Server.Version}}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _detect_docker_image(docker_exe: str, image: str) -> bool:
    try:
        r = subprocess.run(
            [docker_exe, "images", "-q", image],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _detect_milvus_image(docker_exe) -> bool:
    return _detect_docker_image(docker_exe, _MILVUS_IMAGE)
    
def _detect_redis_docker_image(docker_exe: str) -> bool:
    return _detect_docker_image(docker_exe, _REDIS_DOCKER_IMAGE)

def _pull_docker_image(label: str, docker_exe: str, image: str) -> bool:
    return run_cmd([docker_exe, "pull", image], label=label).returncode == 0


def step_install_ffmpeg() -> bool:
    print()
    print(bold("[Step 5] 检查 ffmpeg / ffprobe / ffplay..."))

    ffmpeg = _which_ffmpeg("ffmpeg")
    ffprobe = _which_ffmpeg("ffprobe")
    ffplay = _which_ffmpeg("ffplay")

    if ffmpeg and ffprobe and ffplay:
        print(f"  {green('✓')} ffmpeg  -> {ffmpeg}")
        print(f"  {green('✓')} ffprobe -> {ffprobe}")
        print(f"  {green('✓')} ffplay  -> {ffplay}")
        print(green("  ffmpeg 工具链已就绪。"))
        return True

    for name, path in [("ffmpeg", ffmpeg), ("ffprobe", ffprobe), ("ffplay", ffplay)]:
        tag = green("✓") if path else red("✗")
        loc = path or "未找到"
        print(f"  {tag} {name:12s} -> {loc}")

    print()
    print(yellow("  部分 ffmpeg 工具缺失。音频/视频处理功能需要 ffmpeg。"))
    if not ask_yn("是否通过 ffmpeg-downloader 安装 ffmpeg?", default_yes=True, require_explicit=True):
        print("  跳过 ffmpeg 安装。")
        return True

    try:
        run_cmd([sys.executable, "-m", "pip", "install", "ffmpeg-downloader"])
    except Exception:
        print(red("  安装 ffmpeg-downloader 失败。"))
        return False

    try:
        from argparse import Namespace
        import ffmpeg_downloader.__main__ as ffdl_main

        args = Namespace(
            add_path=True,
            force=False,
            version=None,
            proxy=None,
            retries=3,
            timeout=30,
            no_cache_dir=False,
            y=True,
            dst=None,
            set_env=['name=ffmpeg', 'name=ffprobe', 'name=ffplay'],
            no_simlinks=False,
            presets=None,
            upgrade=False,
            reset_env=False,
        )
        ffdl_main.install(args)
        print(green("  ffmpeg 安装完成。"))
        return True
    except Exception as e:
        print(red(f"  ffmpeg 下载失败: {e}"))
        print("  请手动安装 ffmpeg: https://ffmpeg.org/download.html")
        return False


# ── Step 6: MongoDB ────────────────────────────────────────────
# ── Step 6: MongoDB ────────────────────────────────────────────
def _detect_mongod() -> str | None:
    p = which("mongod")
    if p:
        return p
    if _IS_WIN:
        import glob
        hits = glob.glob(r"C:\Program Files\MongoDB\Server\*\bin\mongod.exe")
        if hits:
            return sorted(hits)[-1]
    return None


def _detect_atlas_cli() -> str | None:
    p = which("atlas")
    if p:
        return p
    if _IS_WIN:
        import glob

        patterns = [
            r"C:\Program Files\MongoDB Atlas CLI\atlas.exe",
            r"C:\Program Files\MongoDB\Atlas CLI\atlas.exe",
        ]
        for pattern in patterns:
            hits = glob.glob(pattern)
            if hits:
                return sorted(hits)[-1]
    return None


# ── Step 7: PostgreSQL ──────────────────────────────────────────
def _detect_postgres() -> str | None:
    p = which("psql") or which("pg_ctl")
    if p:
        return p
    if _IS_WIN:
        import glob
        hits = glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe")
        if hits:
            return sorted(hits)[-1]
    return None


# ── Step 8: MySQL ───────────────────────────────────────────────
def _detect_mysql() -> str | None:
    p = which("mysqld") or which("mysql")
    if p:
        return p
    if _IS_WIN:
        import glob
        hits = glob.glob(r"C:\Program Files\MySQL\MySQL Server *\bin\mysqld.exe")
        if hits:
            return sorted(hits)[-1]
    return None


# ── Step 9: Docker ──────────────────────────────────────────────
def _detect_docker() -> str | None:
    p = shutil.which("docker")
    if p:
        return p
    if _IS_WIN:
        dd = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
        if os.path.isfile(dd):
            return dd
    return None


# ── Step 10: Redis ──────────────────────────────────────────────
def _detect_redis() -> str | None:
    status = _redis_status()
    if status.get("supported"):
        return status.get("path")  # type: ignore[return-value]
    return None


# ── Step 11: WSL2 (Windows only) ────────────────────────────────
def _decode_windows_text(data: bytes) -> str:
    if not data:
        return ""
    if b"\x00" in data:
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8", errors="replace")


def _windows_optional_feature_state(feature_name: str) -> int | None:
    if not _IS_WIN:
        return None
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return None
    command = (
        "$v = Get-CimInstance Win32_OptionalFeature | "
        f"Where-Object {{ $_.Name -eq '{feature_name}' }} | "
        "Select-Object -ExpandProperty InstallState; "
        "if ($null -eq $v) { '' } else { [string]$v }"
    )
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-Command", command],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        if r.returncode != 0:
            return None
        text = (r.stdout or "").strip()
        return int(text) if text.isdigit() else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _detect_wsl2_state() -> str:
    """返回 WSL2 状态: ready / installed_pending / missing。"""
    if not _IS_WIN:
        return "ready"
    wsl = shutil.which("wsl")
    if not wsl:
        return "missing"

    wsl_feature_state = _windows_optional_feature_state("Microsoft-Windows-Subsystem-Linux")
    vmp_feature_state = _windows_optional_feature_state("VirtualMachinePlatform")
    features_enabled = wsl_feature_state == 1 and vmp_feature_state == 1

    try:
        # wsl.exe 输出 UTF-16 LE；用二进制接收再手动解码，避免 GBK 乱码
        # stdin=DEVNULL: 防止 wsl.exe 继承控制台 stdin
        r = subprocess.run(
            [wsl, "--list", "--quiet"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=8,
        )
        text = _decode_windows_text(r.stdout).strip()
        if text:
            return "ready"
    except (subprocess.TimeoutExpired, OSError):
        pass

    # 新版 Windows 上 WSL2 可能作为独立组件安装（非 Optional Feature），
    # 此时即使无发行版，wsl --version 仍可正常返回版本信息。
    try:
        r2 = subprocess.run(
            [wsl, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=8,
        )
        ver_text = _decode_windows_text(r2.stdout).strip()
        if r2.returncode == 0 and ver_text:
            return "ready"
    except (subprocess.TimeoutExpired, OSError):
        pass

    return "installed_pending" if features_enabled else "missing"


def _detect_wsl2() -> bool:
    return _detect_wsl2_state() == "ready"


# ── Step 12: Milvus Standalone ──────────────────────────────────
_MILVUS_IMAGE = "milvusdb/milvus:v2.4.15"


# ════════════════════════════════════════════════════════════════
# 并行安装实现：每个组件一个 worker 函数
# ════════════════════════════════════════════════════════════════

def _worker_requirements(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    req_file = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    req_file = os.path.normpath(req_file)
    try:
        if not os.path.isfile(req_file):
            msg = f"失败，找不到 {req_file}"
        else:
            r = run_cmd([sys.executable, "-m", "pip", "install", "-r", req_file], label=label)
            ok = r.returncode == 0
            if ok and _requirements_include_playwright(req_file):
                r2 = run_cmd([sys.executable, "-m", "playwright", "install"], label=label)
                if r2.returncode != 0:
                    msg = "requirements 完成；playwright install 失败，已跳过"
                else:
                    msg = "完成"
            else:
                msg = "完成" if ok else "失败，请检查 pip 输出"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_libreoffice(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _install_libreoffice_windows()
        elif sys.platform == "darwin":
            ok = _install_libreoffice_macos()
        else:
            ok = _install_libreoffice_linux()
        msg = "完成" if ok else "失败，请手动安装 LibreOffice"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_geolite2_city(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    try:
        from core.utils.network_utils.helper_funcs import GEOLITE2_CITY_DB_PATH, ensure_geolite2_city_db

        ok = ensure_geolite2_city_db(force=True, timeout=120.0)
        msg = f"已更新: {GEOLITE2_CITY_DB_PATH}" if ok else "更新失败"
        result_q.put((label, ok, msg))
    except Exception as e:
        result_q.put((label, False, f"异常: {e}"))


def _worker_ffmpeg(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        from argparse import Namespace
        import ffmpeg_downloader.__main__ as ffdl_main

        args = Namespace(
            add_path=True,
            force=False,
            version=None,
            proxy=None,
            retries=3,
            timeout=30,
            no_cache_dir=False,
            y=True,
            dst=None,
            set_env=['name=ffmpeg', 'name=ffprobe', 'name=ffplay'],
            no_simlinks=False,
            presets=None,
            upgrade=False,
            reset_env=False,
        )
        ffdl_main.install(args)
        ok = _ffmpeg_tools_ready(_detect_ffmpeg_tools())
        msg = "完成" if ok else "失败，安装后仍未检测到完整 ffmpeg 工具链"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))

def _worker_mongodb(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _winget_install("MongoDB.Server", label)
            if not ok:
                choco = shutil.which("choco")
                if choco:
                    ok = run_cmd(["choco", "install", "mongodb", "-y"], label=label).returncode == 0
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                run_cmd([brew, "tap", "mongodb/brew"], label=label)
                ok = run_cmd([brew, "install", "mongodb-community"], label=label).returncode == 0
        else:
            if shutil.which("apt"):
                run_cmd(sudo() + ["apt", "update"], label=label)
                ok = run_cmd(sudo() + ["apt", "install", "-y", "mongodb"], label=label).returncode == 0
        msg = "完成" if ok else "失败，请手动安装: https://www.mongodb.com/try/download/community"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_atlas_cli(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _winget_install(_ATLAS_CLI_WINGET_ID, label)
            if not ok:
                choco = shutil.which("choco")
                if choco:
                    ok = run_cmd(["choco", "install", _ATLAS_CLI_CHOCO_PACKAGE, "-y"], label=label).returncode == 0
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "mongodb-atlas"], label=label).returncode == 0
        else:
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "mongodb-atlas"], label=label).returncode == 0
        if ok:
            msg = "完成。Mongo vector 本地测试请继续运行: atlas deployments setup --type local"
        else:
            msg = "失败，请手动安装 Atlas CLI: https://www.mongodb.com/docs/atlas/cli/current/install-atlas-cli/"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_postgresql(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _winget_install("PostgreSQL.PostgreSQL.17", label)
            if not ok:
                choco = shutil.which("choco")
                if choco:
                    ok = run_cmd(["choco", "install", "postgresql", "-y"], label=label).returncode == 0
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "postgresql@17"], label=label).returncode == 0
        else:
            if shutil.which("apt"):
                run_cmd(sudo() + ["apt", "update"], label=label)
                ok = run_cmd(sudo() + ["apt", "install", "-y", "postgresql"], label=label).returncode == 0
        msg = "完成" if ok else "失败，请手动安装: https://www.postgresql.org/download/"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_mysql(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _winget_install("Oracle.MySQL", label)
            if not ok:
                choco = shutil.which("choco")
                if choco:
                    ok = run_cmd(["choco", "install", "mysql", "-y"], label=label).returncode == 0
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "mysql"], label=label).returncode == 0
        else:
            if shutil.which("apt"):
                run_cmd(sudo() + ["apt", "update"], label=label)
                ok = run_cmd(sudo() + ["apt", "install", "-y", "mysql-server"], label=label).returncode == 0
        msg = "完成" if ok else "失败，请手动安装: https://dev.mysql.com/downloads/"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_docker(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            ok = _winget_install("Docker.DockerDesktop", label)
            if ok:
                msg = "完成。请重启系统后启动 Docker Desktop。"
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "--cask", "docker"], label=label).returncode == 0
                if ok:
                    msg = "完成。请启动 Docker Desktop 应用。"
        else:
            if shutil.which("apt"):
                run_cmd(sudo() + ["apt", "update"], label=label)
                ok = run_cmd(sudo() + ["apt", "install", "-y", "docker.io"], label=label).returncode == 0
                if ok:
                    # 将当前用户加入 docker 组（非 root 时）
                    user = os.environ.get("USER", "")
                    if user:
                        run_cmd(sudo() + ["usermod", "-aG", "docker", user], label=label)
                    msg = "完成。可能需要重新登录使 docker 组生效。"
        if not msg:
            msg = "失败，请手动安装: https://docs.docker.com/engine/install/"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_redis(label: str, result_q: "queue.Queue[tuple[str,bool,str]]", docker_exe: str | None = None) -> None:
    ok = False
    msg = ""
    try:
        if _IS_WIN:
            if not docker_exe:
                msg = f"未拉取。Windows 上 Redis 仅通过 Docker image 提供；请在 Docker 就绪后重新运行脚本拉取 {_REDIS_DOCKER_IMAGE}。"
            else:
                ok = _pull_docker_image(label, docker_exe, _REDIS_DOCKER_IMAGE)
                msg = f"完成。已拉取 Redis Docker image: {_REDIS_DOCKER_IMAGE}" if ok else f"失败，请手动执行: docker pull {_REDIS_DOCKER_IMAGE}"
        elif sys.platform == "darwin":
            brew = shutil.which("brew")
            if brew:
                ok = run_cmd([brew, "install", "redis"], label=label).returncode == 0
            msg = "完成" if ok else "失败，请手动安装: brew install redis"
        else:
            ok = _install_redis_linux_repo(label)
            msg = "完成。已通过官方 packages.redis.io APT 源安装 Redis 8.x，并关闭开机自启。" if ok else "失败，请手动安装官方 Redis APT 源中的 Redis 8.x"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_wsl2(label: str, result_q: "queue.Queue[tuple[str,bool,str]]") -> None:
    """安装 WSL2（仅 Windows，串行，因为需要系统重启）。"""
    ok = False
    msg = ""
    try:
        # wsl --install 包含启用所需 Windows 功能并安装默认 Ubuntu 发行版
        r = run_cmd(
            ["wsl", "--install", "--no-launch"],  # --no-launch: 不立即启动 Linux shell
            label=label,
        )
        if r.returncode == 0:
            ok = True
            msg = "完成。请重启系统后 WSL2 将自动初始化。"
        else:
            # 尝试只启用组件（不下载发行版），兼容离线场景
            r2 = run_cmd(
                ["wsl", "--install", "--no-distribution"],
                label=label,
            )
            ok = r2.returncode == 0
            msg = "完成（无发行版模式）。请重启系统。" if ok else "失败，请手动运行: wsl --install"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


def _worker_milvus(label: str, result_q: "queue.Queue[tuple[str,bool,str]]", docker_exe: str) -> None:
    ok = False
    msg = ""
    try:
        r = run_cmd([docker_exe, "pull", _MILVUS_IMAGE], label=label)
        ok = r.returncode == 0
        msg = "完成" if ok else f"失败，请手动执行: docker pull {_MILVUS_IMAGE}"
    except Exception as e:
        msg = f"异常: {e}"
    result_q.put((label, ok, msg))


# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════

def main():
    # ── Step 1: 显示环境信息，询问是否安装 pip 依赖 ─────────────
    print(bold("\n[Step 1] 确认 Python 环境"))
    run_pip = step_confirm_env()  # False = 跳过 pip，但继续后续步骤

    print()
    print(bold("[检测] 并发检查基础依赖与可选组件..."))
    detected = _parallel_probe({
        "soffice": _detect_soffice,
        "ffmpeg": _detect_ffmpeg_tools,
        "mongod": _detect_mongod,
        "atlas_cli": _detect_atlas_cli,
        "postgres": _detect_postgres,
        "mysql": _detect_mysql,
        "docker": _detect_docker,
        "redis": _redis_status,
        "wsl2": _detect_wsl2_state,
    })

    soffice_path = detected.get("soffice")
    ffmpeg_status = detected.get("ffmpeg") or {"ffmpeg": None, "ffprobe": None, "ffplay": None}
    mongod_path = detected.get("mongod")
    atlas_cli_path = detected.get("atlas_cli")
    pg_path = detected.get("postgres")
    mysql_path = detected.get("mysql")
    docker_path = detected.get("docker")
    redis_status = detected.get("redis") or {"path": None, "version": None, "supported": False}
    if not isinstance(redis_status, dict):
        redis_status = {"path": None, "version": None, "supported": False}
    redis_detected_path = redis_status.get("path")
    redis_detected_version = redis_status.get("version")
    redis_supported = bool(redis_status.get("supported"))
    redis_path = redis_detected_path if redis_supported else None
    wsl2_state = detected.get("wsl2") if _IS_WIN else "ready"
    if wsl2_state not in ("ready", "installed_pending", "missing"):
        wsl2_state = "missing" if _IS_WIN else "ready"
    
    docker_ready = False
    milvus_exists = False
    redis_image_exists = False
    if docker_path:
        docker_ready = _docker_server_ready(docker_path)
        if docker_ready:
            milvus_exists = _detect_milvus_image(docker_path)
            if _IS_WIN:
                redis_image_exists = _detect_redis_docker_image(docker_path)    # type: ignore[assignment]
    if _IS_WIN:
        redis_supported = redis_image_exists
        redis_path = _REDIS_DOCKER_IMAGE if redis_image_exists else None

    print()
    print(bold("[Step 2] pip 依赖"))
    if run_pip:
        print(cyan("  已确认：本轮会安装 requirements.txt。"))
    else:
        print(yellow("  已确认：本轮跳过 requirements.txt。"))

    print()
    print(bold("[Step 3] 检查 LibreOffice / soffice..."))
    if soffice_path:
        print(f"  {green('✓')} soffice -> {soffice_path}")
        print(green("  Legacy .doc/.ppt 低保真转换后端已就绪。"))
    else:
        print(f"  {yellow('!')} 未检测到 soffice。")
        print("  这不会影响常规功能，但会降低 `.doc/.ppt` 旧格式的转换效果。")
        print("  Windows 若已安装 Office，也可设置 ENABLE_OFFICE_COM=1 启用 COM 转换。")

    print()
    print(bold("[Step 4] GeoLite2 City 数据库"))
    print("  将下载/更新 resources/common/GeoLite2-City.mmdb，用于 IP 来源地理信息解析。")

    print()
    print(bold("[Step 5] 检查 ffmpeg / ffprobe / ffplay..."))
    for name, path in ffmpeg_status.items():    # type: ignore[assignment]
        tag = green("✓") if path else red("✗")
        loc = path or "未找到"
        print(f"  {tag} {name:12s} -> {loc}")
    if _ffmpeg_tools_ready(ffmpeg_status):  # type: ignore[assignment]
        print(green("  ffmpeg 工具链已就绪。"))
    else:
        print(yellow("  部分 ffmpeg 工具缺失。音频/视频处理功能需要 ffmpeg。"))

    install_libreoffice = False
    if not soffice_path:
        install_libreoffice = ask_yn("[Step 3] 是否现在安装 LibreOffice?", default_yes=False, require_explicit=True)

    install_ffmpeg = False
    if not _ffmpeg_tools_ready(ffmpeg_status):  # type: ignore[assignment]
        install_ffmpeg = ask_yn("[Step 5] 是否通过 ffmpeg-downloader 安装 ffmpeg?", default_yes=True, require_explicit=True)

    print()
    print(bold("=" * 60))
    print(bold("  可选组件安装（主要用于本地测试）"))
    print(bold("=" * 60))
    print("  以下组件全部可选。请逐项确认，之后将按依赖关系" + bold("分批并行") + "安装。在绝大多数情况下, 这些套件只针对测试storage相关功能有帮助，非必要无需安装。")
    print()

    def _already(name: str, path) -> None:
        if path:
            tprint(f"  {green('✓')} {name} 已安装: {path}")

    _already("MongoDB", mongod_path)
    _already("Atlas CLI", atlas_cli_path)
    _already("PostgreSQL", pg_path)
    _already("MySQL", mysql_path)
    _already("Docker", docker_path)
    if mongod_path and not atlas_cli_path:
        tprint(yellow("  ! MongoDB >=8.2 仅满足版本门槛；普通 mongod / 官方 mongo image 仍可能缺少 Atlas Search 组件，导致 SearchNotEnabled。Mongo vector 本地测试建议安装 Atlas CLI 并创建 local deployment。"))
    elif atlas_cli_path:
        tprint(cyan("  Atlas CLI 已安装；如需本地 Mongo vector search，请运行: atlas deployments setup --type local"))
    if _IS_WIN:
        if redis_image_exists:
            tprint(f"  {green('✓')} Redis Docker 镜像已存在: {_REDIS_DOCKER_IMAGE}")
        elif redis_detected_path:
            redis_version = redis_detected_version if isinstance(redis_detected_version, tuple) else None
            tprint(yellow(f"  ! 检测到本地 Redis 可执行文件: {_version_text(redis_version)} @ {redis_detected_path}；Windows 模式现改为 Docker image({_REDIS_DOCKER_IMAGE})，本地 Redis 不再由安装脚本管理。"))
    else:
        _already("Redis", redis_path)
    if (not _IS_WIN) and redis_detected_path and not redis_supported:
        redis_version = redis_detected_version if isinstance(redis_detected_version, tuple) else None
        tprint(yellow(f"  ! Redis 版本过旧: {_version_text(redis_version)} @ {redis_detected_path}；要求 >= {_version_text(_REDIS_MIN_VERSION)}，将视为未安装。"))
    if _IS_WIN and wsl2_state == "ready":
        tprint(f"  {green('✓')} WSL2 已就绪")
    elif _IS_WIN and wsl2_state == "installed_pending":
        tprint(yellow("  ! WSL2 组件已安装，但当前未完全就绪；如果刚安装，请先重启系统。"))
    if docker_path and docker_ready and milvus_exists:
        tprint(f"  {green('✓')} Milvus 镜像已存在: {_MILVUS_IMAGE}")
    elif docker_path and not docker_ready:
        tprint(yellow("  ! Docker CLI 已存在，但当前引擎未就绪。"))
    print()

    expand_db_install = ask_yn(
        "[Step 6-12] 是否展开数据库/存储相关安装询问?",
        default_yes=False,
        require_explicit=True,
    )
    install_mongo = False
    install_atlas_cli = False
    install_pg = False
    install_mysql = False
    install_docker = False
    if expand_db_install:
        install_mongo = False if mongod_path else ask_yn("[Step 6]  是否安装 MongoDB?", default_yes=False, require_explicit=True)
        install_atlas_cli = False if atlas_cli_path else ask_yn("[Step 6A] 是否安装 Atlas CLI?（Mongo vector 本地测试推荐）", default_yes=False, require_explicit=True)
        install_pg = False if pg_path else ask_yn("[Step 7]  是否安装 PostgreSQL?", default_yes=False, require_explicit=True)
        install_mysql = False if mysql_path else ask_yn("[Step 8]  是否安装 MySQL?", default_yes=False, require_explicit=True)
        install_docker = False if docker_path else ask_yn("[Step 9]  是否安装 Docker?", default_yes=False, require_explicit=True)
    else:
        print(yellow("  已跳过数据库/存储相关安装询问。"))
    install_redis = False
    if expand_db_install:
        if _IS_WIN:
            if docker_path or install_docker:
                if not redis_image_exists:
                    install_redis = ask_yn(
                        f"[Step 10] 是否拉取 Redis Docker 镜像 ({_REDIS_DOCKER_IMAGE})?",
                        default_yes=False,
                        require_explicit=True,
                    )
            else:
                print(yellow(f"  [Step 10] Windows 上 Redis 已改为 Docker image({_REDIS_DOCKER_IMAGE})；当前未检测到 Docker，本轮不会安装本地 Redis。"))
        else:
            install_redis = False if redis_supported else ask_yn("[Step 10] 是否安装 Redis?", default_yes=False, require_explicit=True)

    need_wsl2_check = _IS_WIN and (install_docker or (docker_path is not None))
    install_wsl2 = False
    if expand_db_install and need_wsl2_check and wsl2_state == "missing":
        install_wsl2 = ask_yn(
            "[Step 11] 检测到需要 WSL2（Docker 依赖）且未安装，是否安装 WSL2?",
            default_yes=True,
            require_explicit=True,
        )
    elif expand_db_install and need_wsl2_check and wsl2_state == "installed_pending":
        print(yellow("  [Step 11] WSL2 组件已安装，但当前未完全就绪；请先重启。若重启后仍未就绪，请检查 BIOS/UEFI 虚拟化是否启用。"))

    install_milvus = False
    if expand_db_install and docker_path and docker_ready:
        if not milvus_exists:
            install_milvus = ask_yn(
                f"[Step 12] 是否拉取 Milvus 镜像 ({_MILVUS_IMAGE})?",
                default_yes=False,
                require_explicit=True,
            )
    elif expand_db_install and install_docker:
        print(yellow("  [Step 12] Docker 为本轮新安装组件，Milvus 镜像请在 Docker 就绪后再拉取。"))
    elif expand_db_install and docker_path and not docker_ready:
        print(yellow("  [Step 12] Docker 引擎当前未就绪，本轮跳过 Milvus 镜像拉取。"))

    needs_sudo = any([
        install_libreoffice,
        install_mongo,
        install_atlas_cli,
        install_pg,
        install_mysql,
        install_docker,
        install_redis,
    ])
    if not _IS_WIN and sys.platform != "darwin" and needs_sudo:
        _init_sudo_linux()

    pre_results: list[tuple[str, bool, str]] = []
    if install_ffmpeg and not _ffmpeg_downloader_installed():
        print()
        print(bold("[前置准备] 安装 ffmpeg-downloader..."))
        ok, msg = _ensure_ffmpeg_downloader()
        pre_results.append(("ffmpeg-downloader", ok, msg))
        if not ok:
            install_ffmpeg = False

    if _IS_WIN and any([
        install_libreoffice,
        install_mongo,
        install_atlas_cli,
        install_pg,
        install_mysql,
        install_docker,
        install_redis,
        install_wsl2,
    ]):
        print()
        print(cyan("  [Windows] winget 安装项会尽量使用 --silent 静默安装。"))
        if install_redis:
            print(cyan(f"  Redis 将通过 Docker 拉取镜像: {_REDIS_DOCKER_IMAGE}。"))
        print(cyan("  安装过程中仍可能出现一次 UAC 提示，请确认。"))
        print()

    result_q: queue.Queue[tuple[str, bool, str]] = queue.Queue()
    threads: list[threading.Thread] = []

    def _add(worker, label, *args):
        t = threading.Thread(target=worker, args=(label, result_q, *args), daemon=True)
        threads.append(t)

    if run_pip: _add(_worker_requirements, "pip")
    if install_libreoffice: _add(_worker_libreoffice, "LibreOffice")
    _add(_worker_geolite2_city, "GeoLite2 City")
    if install_ffmpeg: _add(_worker_ffmpeg, "ffmpeg")
    if install_mongo: _add(_worker_mongodb, "MongoDB")
    if install_atlas_cli: _add(_worker_atlas_cli, "Atlas CLI")
    if install_pg: _add(_worker_postgresql, "PostgreSQL")
    if install_mysql: _add(_worker_mysql, "MySQL")
    if install_docker: _add(_worker_docker, "Docker")
    if install_redis:
        if _IS_WIN:
            if docker_path and docker_ready:
                _add(_worker_redis, "Redis", docker_path)
            else:
                pre_results.append(("Redis", False, f"未拉取。Windows 上 Redis 仅通过 Docker image 提供；请在 Docker 就绪后重新运行脚本拉取 {_REDIS_DOCKER_IMAGE}。"))
        else:
            _add(_worker_redis, "Redis")
    if install_milvus and docker_path: _add(_worker_milvus, "Milvus", docker_path)

    results: list[tuple[str, bool, str]] = list(pre_results)
    if threads:
        print()
        print(bold(f"  开始并行安装 {len(threads)} 个项目..."))
        print()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        while not result_q.empty():
            results.append(result_q.get_nowait())

    if install_wsl2:
        print()
        print(bold("  WSL2 将单独串行安装..."))
        print()
        serial_q: queue.Queue[tuple[str, bool, str]] = queue.Queue()
        _worker_wsl2("WSL2", serial_q)
        if not serial_q.empty():
            results.append(serial_q.get_nowait())

    need_reboot = False
    if results:
        print()
        print(bold("─" * 60))
        print(bold("  安装结果汇总"))
        print(bold("─" * 60))
        results.sort(key=lambda x: x[0])
        for label, ok, msg in results:
            icon = green("✓") if ok else yellow("!")
            tprint(f"  {icon} {label}: {msg}")
            if ok and _IS_WIN and label in ("Docker", "WSL2"):
                need_reboot = True
        print()
    else:
        tprint("  未选择任何安装项，脚本仅完成检测。")

    # ── 重启提醒（Windows：Docker / WSL2 安装后必须重启）──────
    if need_reboot:
        print()
        print(bold("!" * 60))
        print(yellow(bold("  ⚠  需要重启系统  ⚠")))
        print(bold("!" * 60))
        print()
        print(yellow("  Docker Desktop（以及 WSL2）安装完成后需要重启系统才能生效。"))
        print(yellow("  重启后请手动启动 Docker Desktop，等待引擎就绪再使用相关功能。"))
        print()
        print(bold("!" * 60))
        print()

    # ── 完成 ──────────────────────────────────────────────────
    print()
    print(bold("=" * 60))
    print(green(bold("  安装完成！")))
    print(bold("=" * 60))
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        import traceback as _tb
        # 取最后一帧，告知用户在哪里被中断
        frames = _tb.extract_stack()
        # 过滤掉本文件顶层和 Python 内部帧
        relevant = [f for f in frames if f.filename == __file__ and f.name not in ("<module>",)]
        if relevant:
            last = relevant[-1]
            loc = f" (位于 {last.name}(), 第 {last.lineno} 行)"
        else:
            loc = ""
        print(f"\n{yellow(bold('  安装已退出' + loc))}")
        sys.exit(130)
