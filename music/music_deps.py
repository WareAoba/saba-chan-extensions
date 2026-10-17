"""Music extension — dependency checker & installer.

사바쨩 익스텐션 시스템에서 음악 봇에 필요한 외부 의존성을 검증하고,
Node.js npm 패키지가 미설치일 경우 자동 설치를 시도합니다.
daemon.startup 훅으로 실행됩니다.

의존성 구조:
  extensions/music/package.json   — npm 의존성 정의 (@discordjs/voice 등)
  extensions/music/node_modules/  — npm install 결과물
  포터블 바이너리                  — ffmpeg, yt-dlp (AppData/saba-chan 내)

실제 음악 재생 로직은 클라우드 릴레이 서버(server-chan/music-server)에서 제공합니다.
"""

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("saba.ext.music")

# 이 파일이 위치한 extensions/music/ 디렉토리
_EXT_DIR = Path(__file__).resolve().parent


def _get_saba_data_dir() -> Path:
    """사바쨩 AppData 디렉토리를 반환합니다."""
    saba_dir = os.environ.get("SABA_DATA_DIR")
    if saba_dir:
        return Path(saba_dir)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "saba-chan"
    return Path.home() / ".config" / "saba-chan"


def _get_portable_install_root() -> Path:
    """사바쨩 설치 루트 (실행 바이너리 기준)를 반환합니다."""
    # daemon이 호출할 때 sys.executable의 부모 디렉토리 체인에서 설치 루트를 추정
    # SABA_INSTALL_ROOT 환경변수가 있으면 우선 사용
    root = os.environ.get("SABA_INSTALL_ROOT")
    if root:
        return Path(root)
    return Path(sys.executable).resolve().parent


def _find_portable_npm() -> str | None:
    """사바쨩 포터블 Node.js 환경의 npm 경로를 탐색합니다."""
    data_dir = _get_saba_data_dir()
    install_root = _get_portable_install_root()

    candidates = []
    if sys.platform == "win32":
        candidates = [
            data_dir / "node-env" / "npm.cmd",
            install_root / "node-env" / "npm.cmd",
        ]
    else:
        candidates = [
            data_dir / "node-env" / "bin" / "npm",
            install_root / "node-env" / "bin" / "npm",
        ]

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _find_portable_ffmpeg() -> str | None:
    """사바쨩 포터블 ffmpeg 경로를 탐색합니다."""
    data_dir = _get_saba_data_dir()
    install_root = _get_portable_install_root()

    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates = [
        data_dir / "bin" / exe,
        data_dir / "ffmpeg" / exe,
        install_root / "ffmpeg" / exe,
        install_root / "bin" / exe,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def check_dependencies(**_kwargs):
    """daemon.startup hook — npm 패키지 + ffmpeg / yt-dlp / opus 의존성 검사.

    npm 의존성이 미설치이면 자동으로 ``npm install`` 을 시도합니다.

    Returns:
        dict: 검사 결과. ``status`` 가 ``"ready"`` 이면 모든 의존성 확인됨.
    """
    # 1. Node.js npm 의존성 확인 & 자동 설치
    npm_result = _ensure_npm_dependencies()

    # 2. 시스템 의존성 확인
    results = {
        "npm_packages": npm_result,
        "ffmpeg": _check_ffmpeg(),
        "yt_dlp": _check_yt_dlp(),
        "opus": _check_opus(),
    }

    all_ok = all(r["available"] for r in results.values())

    if all_ok:
        logger.info("Music dependencies OK: npm packages, ffmpeg, yt-dlp, opus all available")
    else:
        missing = [k for k, v in results.items() if not v["available"]]
        logger.warning("Music dependencies missing: %s", ", ".join(missing))

    # 3. 결과를 .deps-resolved.json 에 기록하여 Node.js 봇이 읽을 수 있게 한다
    _write_deps_resolved(results)

    return {
        "status": "ready" if all_ok else "degraded",
        "dependencies": results,
    }


# ──────────────────────────────────────────────────────────────
#  결과 영속화 (.deps-resolved.json)
# ──────────────────────────────────────────────────────────────


def _write_deps_resolved(results: dict):
    """의존성 검사 결과를 .deps-resolved.json 에 기록.

    Node.js 봇(music.js)이 이 파일을 읽어 ffmpeg/yt-dlp 실행 경로를 결정합니다.
    기록 위치:
      1. _EXT_DIR (이 스크립트가 위치한 디렉토리, Rust daemon이 호출할 때)
      2. SABA_EXTENSIONS_DIR/music/ (환경변수가 설정된 경우, 프로덕션)
    """
    targets = [_EXT_DIR / ".deps-resolved.json"]

    # SABA_EXTENSIONS_DIR 이 설정되어 있고 _EXT_DIR 과 다르면 추가로 기록
    saba_ext = os.environ.get("SABA_EXTENSIONS_DIR")
    if saba_ext:
        alt = Path(saba_ext) / "music" / ".deps-resolved.json"
        if alt.resolve() != targets[0].resolve():
            targets.append(alt)

    payload = json.dumps(results, indent=2, ensure_ascii=False)
    for out_path in targets:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload, encoding="utf-8")
            logger.info("Wrote dependency info to %s", out_path)
        except Exception as exc:
            logger.warning("Failed to write %s: %s", out_path, exc)


# ──────────────────────────────────────────────────────────────
#  npm 의존성 관리
# ──────────────────────────────────────────────────────────────


def _ensure_npm_dependencies():
    """extensions/music/node_modules 확인 & 필요 시 npm install 실행.

    package.json은 이미 extensions/music/ 에 존재한다고 가정합니다.
    """
    node_modules = _EXT_DIR / "node_modules"
    package_json = _EXT_DIR / "package.json"

    if not package_json.exists():
        return {
            "available": False,
            "error": "package.json not found in extensions/music/",
        }

    # 핵심 보조 패키지 존재 여부로 설치 상태 판단
    # (@discordjs/voice 는 봇 본체에 있으므로 opusscript 를 마커로 사용)
    marker = node_modules / "opusscript" / "package.json"
    if marker.exists():
        return {"available": True, "installed": True}

    # 미설치 → npm install 시도 (포터블 npm 우선)
    logger.info("Music npm dependencies not found, running npm install...")
    npm_cmd = _find_portable_npm()
    if not npm_cmd:
        # 개발 모드에서만 시스템 npm 허용
        if os.environ.get("SABA_DEV_MODE") == "1":
            npm_cmd = shutil.which("npm")
        if not npm_cmd:
            return {
                "available": False,
                "error": "Portable npm not found — install Node.js via saba-chan installer",
            }

    try:
        result = subprocess.run(
            [npm_cmd, "install", "--omit=dev", "--no-fund", "--no-audit"],
            cwd=str(_EXT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Music npm dependencies installed successfully")
            return {"available": True, "installed": True, "auto_installed": True}
        else:
            stderr = result.stderr.strip()[:500] if result.stderr else ""
            logger.error("npm install failed (exit %d): %s", result.returncode, stderr)
            return {
                "available": False,
                "error": f"npm install failed (exit {result.returncode})",
                "stderr": stderr,
            }
    except subprocess.TimeoutExpired:
        logger.error("npm install timed out (120s)")
        return {"available": False, "error": "npm install timed out"}
    except Exception as exc:
        logger.error("npm install error: %s", exc)
        return {"available": False, "error": str(exc)}


# ──────────────────────────────────────────────────────────────
#  개별 시스템 의존성 검사
# ──────────────────────────────────────────────────────────────


def _check_ffmpeg():
    """ffmpeg 사용 가능 여부 확인 (포터블 바이너리 우선)."""
    # 1. 사바쨩 포터블 ffmpeg 탐색
    path = _find_portable_ffmpeg()
    # 2. 개발 모드에서만 시스템 PATH fallback 허용
    if not path and os.environ.get("SABA_DEV_MODE") == "1":
        path = shutil.which("ffmpeg")
    if path:
        try:
            result = subprocess.run(
                [path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version_line = (
                result.stdout.split("\n")[0] if result.stdout else "unknown"
            )
            return {"available": True, "path": path, "version": version_line}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    return {"available": False, "error": "Portable ffmpeg not found — install via saba-chan installer"}


def _find_yt_dlp() -> str | None:
    """yt-dlp 실행 파일 경로를 탐색합니다 (포터블 우선)."""
    # 1. 사바쨩 포터블 경로 탐색
    data_dir = _get_saba_data_dir()
    install_root = _get_portable_install_root()
    exe = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    for base in [data_dir / "bin", install_root / "bin", data_dir / "yt-dlp"]:
        candidate = base / exe
        if candidate.exists():
            return str(candidate)

    # 2. 현재 Python 의 Scripts/bin 디렉토리 탐색 (포터블 venv)
    scripts_dir = Path(sys.executable).parent
    candidate = scripts_dir / exe
    if candidate.exists():
        return str(candidate)

    # 3. 개발 모드에서만 시스템 PATH fallback
    if os.environ.get("SABA_DEV_MODE") == "1":
        found = shutil.which("yt-dlp")
        if found:
            return found

    return None


def _check_yt_dlp():
    """yt-dlp 사용 가능 여부 확인 & 자동 설치.

    시스템 PATH 및 현재 Python 환경의 Scripts 디렉토리에서 탐색합니다.
    찾지 못하면 ``pip install yt-dlp`` 로 자동 설치를 시도합니다.
    """
    found = _find_yt_dlp()

    # 미설치 → 포터블 Python의 pip으로만 설치 시도 (시스템 pip 사용 금지)
    if not found:
        # 현재 실행 중인 Python이 포터블 환경인지 확인
        is_portable_python = (
            str(_get_saba_data_dir()) in str(Path(sys.executable).resolve())
            or str(_get_portable_install_root()) in str(Path(sys.executable).resolve())
            or os.environ.get("SABA_DEV_MODE") == "1"
        )
        if not is_portable_python:
            logger.warning("yt-dlp not found and system pip install is not allowed (portable principle)")
        else:
            logger.info("yt-dlp not found, attempting pip install in portable env...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "yt-dlp"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    logger.info("yt-dlp installed via pip (portable)")
                    found = _find_yt_dlp()
                else:
                    stderr = result.stderr.strip()[:500] if result.stderr else ""
                    logger.error("pip install yt-dlp failed (exit %d): %s", result.returncode, stderr)
            except subprocess.TimeoutExpired:
                logger.error("pip install yt-dlp timed out (120s)")
            except Exception as exc:
                logger.error("pip install yt-dlp error: %s", exc)

    if found:
        try:
            result = subprocess.run(
                [found, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip() if result.stdout else "unknown"
            return {"available": True, "path": found, "version": version}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    return {
        "available": False,
        "error": "yt-dlp not found in portable environment. Install via saba-chan installer.",
    }


def _check_opus():
    """Opus 라이브러리 사용 가능 여부 확인.

    시스템 공유 라이브러리를 탐색합니다.
    찾지 못해도 Node.js 의 opusscript (WASM) 가 대체 가능하므로
    ``available: True`` (fallback) 로 반환합니다.
    """
    if sys.platform == "win32":
        lib_names = ["opus", "libopus-0", "libopus"]
    elif sys.platform == "darwin":
        lib_names = ["libopus.dylib", "libopus.0.dylib"]
    else:
        lib_names = ["libopus.so", "libopus.so.0"]

    for name in lib_names:
        try:
            ctypes.cdll.LoadLibrary(name)
            return {"available": True, "library": name}
        except OSError:
            continue

    # 시스템 opus 가 없어도 Node.js opusscript(WASM) 가 대체 가능
    return {
        "available": True,
        "library": "opusscript (Node.js fallback)",
        "note": "System opus not found — Node.js opusscript/wasm should work",
    }


# ──────────────────────────────────────────────────────────────
#  Plugin runner entry-point
# ──────────────────────────────────────────────────────────────

_FUNCTIONS = {
    "check_dependencies": check_dependencies,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No function specified"}))
        sys.exit(1)

    func_name = sys.argv[1]
    func = _FUNCTIONS.get(func_name)
    if not func:
        print(json.dumps({"error": f"Unknown function: {func_name}"}))
        sys.exit(1)

    config_str = sys.stdin.read().strip()
    # BOM 제거 (PowerShell 등에서 echo 시 UTF-8 BOM 포함 가능)
    config_str = config_str.lstrip("\ufeff")
    try:
        config = json.loads(config_str) if config_str else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON config: {e}"}))
        sys.exit(1)

    result = func(**config)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
