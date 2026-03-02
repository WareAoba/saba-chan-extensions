"""Music extension — 바이너리 의존성 자동 설치 & 경로 관리.

사바쨩 익스텐션 시스템에서 음악 봇에 필요한 **바이너리/외부 도구**를
pip 으로 자동 설치하고, 설치 경로를 .deps-resolved.json 에 기록합니다.
daemon.startup 훅으로 실행됩니다.

의존성 구조:
  [Python pip — 이 파일이 관리]
    - imageio-ffmpeg : ffmpeg 바이너리 (pip 패키지에 포함)
    - yt-dlp         : YouTube 다운로더

  [Node.js npm — discord_bot/package.json 에서 관리]
    - @discordjs/voice, opusscript, play-dl, tweetnacl
    → Node.js 순수 JS 패키지는 이 파일이 관리하지 않습니다.

  [출력]
    extensions/music/.deps-resolved.json
    → music.js 가 시작 시 읽어 바이너리 경로를 설정합니다.

실제 음악 재생 로직은 discord_bot/extensions/music.js (Node.js) 에 있습니다.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("saba.ext.music")

# 이 파일이 위치한 extensions/music/ 디렉토리
_EXT_DIR = Path(__file__).resolve().parent

# pip 으로 설치할 패키지 목록
_PIP_PACKAGES = {
    "ffmpeg": "imageio-ffmpeg",
    "yt_dlp": "yt-dlp",
}


def check_dependencies(**_kwargs):
    """daemon.startup hook — ffmpeg / yt-dlp 자동 설치 & 경로 기록.

    pip 으로 바이너리 의존성을 설치하고 경로를
    ``.deps-resolved.json`` 에 기록합니다.
    music.js 가 이 파일을 읽어 바이너리 경로를 설정합니다.

    Returns:
        dict: 검사 결과. ``status`` 가 ``"ready"`` 이면 모든 의존성 확인됨.
    """
    results = {
        "ffmpeg": _ensure_ffmpeg(),
        "yt_dlp": _ensure_yt_dlp(),
    }

    all_ok = all(r["available"] for r in results.values())

    if all_ok:
        logger.info("Music binary dependencies OK: ffmpeg, yt-dlp all available")
    else:
        missing = [k for k, v in results.items() if not v["available"]]
        logger.warning("Music binary dependencies missing: %s", ", ".join(missing))

    # .deps-resolved.json 에 경로 기록 → music.js 가 읽어감
    _write_deps_resolved(results)

    return {
        "status": "ready" if all_ok else "degraded",
        "dependencies": results,
    }


# ──────────────────────────────────────────────────────────────
#  pip 설치 헬퍼
# ──────────────────────────────────────────────────────────────


def _pip_install(package: str) -> bool:
    """pip 으로 패키지를 설치합니다. 이미 설치돼 있으면 skip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", package],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("pip install %s — success", package)
            return True
        else:
            stderr = (result.stderr or "").strip()[:500]
            logger.error("pip install %s failed (exit %d): %s", package, result.returncode, stderr)
            return False
    except subprocess.TimeoutExpired:
        logger.error("pip install %s timed out (120s)", package)
        return False
    except Exception as exc:
        logger.error("pip install %s error: %s", package, exc)
        return False


# ──────────────────────────────────────────────────────────────
#  FFmpeg — imageio-ffmpeg (pip 패키지에 바이너리 포함)
# ──────────────────────────────────────────────────────────────


def _ensure_ffmpeg() -> dict:
    """ffmpeg 확인 → 없으면 imageio-ffmpeg 설치 → 경로 반환."""

    # 1. imageio-ffmpeg 가 이미 설치돼 있는지 확인
    ffmpeg_path = _get_imageio_ffmpeg_path()
    if ffmpeg_path:
        return _ffmpeg_result(ffmpeg_path)

    # 2. 시스템 PATH 에서 찾기
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return _ffmpeg_result(system_ffmpeg)

    # 3. pip install imageio-ffmpeg
    logger.info("ffmpeg not found — installing imageio-ffmpeg via pip...")
    if _pip_install("imageio-ffmpeg"):
        ffmpeg_path = _get_imageio_ffmpeg_path()
        if ffmpeg_path:
            return _ffmpeg_result(ffmpeg_path)

    return {"available": False, "error": "ffmpeg installation failed"}


def _get_imageio_ffmpeg_path() -> str | None:
    """imageio_ffmpeg 모듈에서 ffmpeg 실행 파일 경로를 가져옵니다."""
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).is_file():
            return path
    except (ImportError, Exception):
        pass
    return None


def _ffmpeg_result(path: str) -> dict:
    """ffmpeg 경로를 검증하고 결과 dict 를 반환합니다."""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_line = (result.stdout.split("\n")[0] if result.stdout else "unknown")
        return {"available": True, "path": path, "version": version_line}
    except Exception as exc:
        return {"available": True, "path": path, "version": f"(verify failed: {exc})"}


# ──────────────────────────────────────────────────────────────
#  yt-dlp (pip install yt-dlp)
# ──────────────────────────────────────────────────────────────


def _ensure_yt_dlp() -> dict:
    """yt-dlp 확인 → 없으면 pip install → 경로 반환."""

    # 1. PATH 에서 찾기
    yt_dlp_path = shutil.which("yt-dlp")
    if yt_dlp_path:
        return _yt_dlp_result(yt_dlp_path)

    # 2. pip 의 Scripts 폴더 (Windows)
    if sys.platform == "win32":
        for scripts_dir in _pip_scripts_dirs():
            candidate = scripts_dir / "yt-dlp.exe"
            if candidate.is_file():
                return _yt_dlp_result(str(candidate))

    # 3. pip install yt-dlp
    logger.info("yt-dlp not found — installing via pip...")
    if _pip_install("yt-dlp"):
        # 재탐색
        yt_dlp_path = shutil.which("yt-dlp")
        if yt_dlp_path:
            return _yt_dlp_result(yt_dlp_path)
        # Windows Scripts 폴더 재확인
        if sys.platform == "win32":
            for scripts_dir in _pip_scripts_dirs():
                candidate = scripts_dir / "yt-dlp.exe"
                if candidate.is_file():
                    return _yt_dlp_result(str(candidate))

    return {"available": False, "error": "yt-dlp installation failed"}


def _pip_scripts_dirs():
    """pip 이 바이너리를 설치하는 Scripts 경로 후보들."""
    import site
    dirs = []
    # --user 설치 (가장 흔함)
    user_base = site.getusersitepackages()
    if user_base:
        dirs.append(Path(user_base).parent / "Scripts")
    # 시스템/venv 설치
    dirs.append(Path(sys.prefix) / "Scripts")
    return dirs


def _yt_dlp_result(path: str) -> dict:
    """yt-dlp 경로를 검증하고 결과 dict 를 반환합니다."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = result.stdout.strip() if result.stdout else "unknown"
        return {"available": True, "path": path, "version": version}
    except Exception as exc:
        return {"available": True, "path": path, "version": f"(verify failed: {exc})"}


# ──────────────────────────────────────────────────────────────
#  .deps-resolved.json 기록
# ──────────────────────────────────────────────────────────────


def _write_deps_resolved(results: dict):
    """바이너리 의존성 경로를 JSON 파일에 기록합니다.

    music.js 가 시작 시 이 파일을 읽어 ffmpeg / yt-dlp 경로를 설정합니다.
    """
    out_path = _EXT_DIR / ".deps-resolved.json"
    try:
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Wrote dependency paths to %s", out_path)
    except Exception as exc:
        logger.error("Failed to write .deps-resolved.json: %s", exc)


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

    config_str = sys.stdin.read()
    try:
        config = json.loads(config_str) if config_str.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON config: {e}"}))
        sys.exit(1)

    result = func(**config)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
