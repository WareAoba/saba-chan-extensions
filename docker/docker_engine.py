"""
saba-chan Docker Engine Extension
==================================
Portable Docker Engine management: auto-download static binaries,
manage a local ``dockerd`` daemon, and provide Docker Compose support
-- all without requiring Docker Desktop.

On **Windows**, Docker runs inside **WSL2** (Windows Subsystem for Linux)
because Linux game-server container images need a Linux kernel.

On **Linux**, Docker runs natively via downloaded static binaries.

Hooks (manifest.json):
    daemon.startup → ``startup`` (가벼운 확인만, 무거운 설치는 프로비저닝 때)

compose_manager.py가 같은 익스텐션 안에서 이 모듈을 import해 사용한다
(``ensure``, 경로·상태 파일, ``_run_cli`` 프로토콜 헬퍼).
"""

from __future__ import annotations

import json
import os
import platform
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Optional

# ── Force UTF-8 stdout/stderr on Windows ─────────────────────────
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── Constants ────────────────────────────────────────────────────

_SYSTEM = platform.system()  # "Windows", "Linux", "Darwin"

# Docker Engine static binaries (Linux -- used natively or via WSL2)
_DOCKER_ENGINE_URL = (
    "https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz"
)
_COMPOSE_URL = (
    "https://github.com/docker/compose/releases/download/"
    "v2.33.1/docker-compose-linux-x86_64"
)


def _get_docker_engine_url() -> str:
    """Return Docker Engine download URL for the current architecture."""
    arch = platform.machine()
    if arch == "aarch64":
        return "https://download.docker.com/linux/static/stable/aarch64/docker-27.5.1.tgz"
    return _DOCKER_ENGINE_URL  # x86_64 default


def _get_compose_url() -> str:
    """Return Docker Compose download URL for the current architecture."""
    arch = platform.machine()
    if arch == "aarch64":
        return (
            "https://github.com/docker/compose/releases/download/"
            "v2.33.1/docker-compose-linux-aarch64"
        )
    return _COMPOSE_URL  # x86_64 default

# WSL2 paths (Windows only)
_WSL2_DIR = "/opt/saba-chan/docker"
_WSL2_DATA = "/opt/saba-chan/docker/data"
_WSL2_LOG = "/opt/saba-chan/docker/dockerd.log"
_WSL2_PID = "/opt/saba-chan/docker/dockerd.pid"


# ── Helpers ──────────────────────────────────────────────────────

def _log(msg: str) -> None:
    """Write to stderr so it doesn't pollute stdout JSON."""
    print(f"[docker_engine] {msg}", file=sys.stderr, flush=True)


def _creation_flags() -> int:
    if _SYSTEM == "Windows":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0


def _progress(percent: int | None = None, message: str | None = None, **extra: Any) -> None:
    """PROGRESS 프로토콜로 진행률 보고 (stderr).

    *extra* 는 Rust ExtensionProgress의 확장 필드(step/total/label/steps)다.
    값이 None인 필드는 보내지 않는다.
    """
    info = {"percent": percent, "message": message, **extra}
    line = json.dumps({k: v for k, v in info.items() if v is not None}, ensure_ascii=True)
    print(f"PROGRESS:{line}", file=sys.stderr, flush=True)


def _download(url: str, dest: Path, *, timeout: int = 300, label: str = "") -> None:
    """Download a file from *url* to *dest* with progress reporting."""
    _log(f"Downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "saba-chan/1.0"})
    downloaded = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        last_pct = -1
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = min(int(downloaded * 100 / total), 100)
                if pct != last_pct:
                    sizes = f"{downloaded / 1_048_576:.1f}/{total / 1_048_576:.1f} MB"
                    _progress(pct, f"{label}: {sizes}" if label else sizes)
                    last_pct = pct
    _log(f"Downloaded {downloaded / 1_048_576:.1f} MB -> {dest.name}")


def _extract_engine_tar(archive: Path, dest: Path) -> None:
    """Docker static tgz의 ``docker/`` 하위 파일을 *dest* 에 푼다.

    경로가 *dest* 밖을 가리키는 항목, 링크·장치 파일은 거부한다 (tar-slip 방지).
    """
    dest = dest.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        selected = []
        for member in tf.getmembers():
            if not member.name.startswith("docker/"):
                continue
            member.name = member.name[len("docker/"):]
            if not member.name:
                continue
            target = (dest / member.name).resolve()
            if dest not in target.parents:
                raise ValueError(f"Archive member escapes target directory: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported archive member type: {member.name}")
            selected.append(member)
        tf.extractall(dest, members=selected)


def _check_log_for_fatal(text: str) -> Optional[str]:
    """Return the first fatal-error line found in *text*, or ``None``."""
    for line in text.splitlines()[-15:]:
        if "failed to start daemon" in line.lower():
            return line.strip()
    return None


def _win_to_wsl_path(win_path: Path) -> str:
    """Convert ``C:\\foo\\bar`` to ``/mnt/c/foo/bar``."""
    s = str(win_path.resolve()).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s


# ── WSL2 helpers (Windows only) ──────────────────────────────────

def _wsl_run(
    args: list[str],
    *,
    timeout: int = 30,
    root: bool = False,
) -> subprocess.CompletedProcess:
    """Run *args* inside the default WSL2 distro."""
    cmd: list[str] = ["wsl"]
    if root:
        cmd += ["-u", "root"]
    cmd += ["--"]
    cmd += args
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout,
        creationflags=_creation_flags(),
    )


def _wsl_available() -> bool:
    """Return ``True`` if WSL2 is installed and a default distro responds."""
    if _SYSTEM != "Windows":
        return False
    try:
        r = subprocess.run(
            ["wsl", "echo", "OK"],
            capture_output=True, timeout=15,
            creationflags=_creation_flags(),
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wsl_docker_installed() -> bool:
    """Return ``True`` if our Docker binaries exist inside WSL2."""
    try:
        r = _wsl_run(["test", "-x", f"{_WSL2_DIR}/dockerd"], root=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _wsl_daemon_running() -> bool:
    """Return ``True`` if dockerd inside WSL2 is responding."""
    try:
        r = _wsl_run(
            [f"{_WSL2_DIR}/docker", "-H", "unix:///var/run/docker.sock", "info"],
            root=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _wsl_compose_installed() -> bool:
    try:
        r = _wsl_run(["test", "-x", f"{_WSL2_DIR}/docker-compose"], root=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _wsl_read_log_tail(lines: int = 20) -> str:
    try:
        r = _wsl_run(["tail", f"-{lines}", _WSL2_LOG], root=True, timeout=5)
        return r.stdout.decode(errors="replace")
    except Exception:
        return ""


# ── 데이터 경로 (데몬 updater constants와 같은 규칙) ─────────────

def _data_dir() -> Path:
    """saba-chan 데이터 디렉터리: SABA_DATA_DIR → %APPDATA%/saba-chan → ~/.config/saba-chan."""
    override = os.environ.get("SABA_DATA_DIR", "")
    if override:
        return Path(override)
    if _SYSTEM == "Windows" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "saba-chan"
    if os.environ.get("HOME"):
        return Path(os.environ["HOME"]) / ".config" / "saba-chan"
    return Path(".") / "saba-chan"


def _instances_dir() -> Path:
    """인스턴스 저장 디렉터리: SABA_INSTANCES_PATH → <data_dir>/instances."""
    override = os.environ.get("SABA_INSTANCES_PATH", "")
    return Path(override) if override else _data_dir() / "instances"


def _has_docker_instances() -> bool:
    """docker_enabled 인스턴스가 하나라도 있는지 instance.json으로 확인한다."""
    root = _instances_dir()
    if not root.is_dir():
        return False
    for meta in root.glob("*/instance.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (data.get("extension_data") or {}).get("docker_enabled"):
            return True
    return False


# ── Portable directory ───────────────────────────────────────────

def _portable_dir() -> Path:
    """Directory for saba-chan's portable Docker Engine metadata.

    On Windows this only stores local state; actual Docker binaries
    live inside WSL2 at ``/opt/saba-chan/docker/``.
    """
    exe_dir = os.environ.get("SABA_EXE_DIR", "")
    if exe_dir:
        return Path(exe_dir) / "docker"
    script_parent = Path(__file__).resolve().parent.parent
    if (script_parent / "saba-core.exe").exists() or (script_parent / "saba-core").exists():
        return script_parent / "docker"
    return _data_dir() / "docker"


_STATE_FILE = "engine-state.json"


def load_engine_state() -> dict[str, Any]:
    """마지막 ensure 결과(wsl_mode 등). 없거나 깨졌으면 빈 dict."""
    try:
        return json.loads((_portable_dir() / _STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_engine_state(state: dict[str, Any]) -> None:
    """ensure 결과를 저장한다. compose_manager는 별도 프로세스이므로 이 파일로 모드를 공유한다."""
    path = _portable_dir() / _STATE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        _log(f"Failed to save engine state: {e}")


# ── Core Class ───────────────────────────────────────────────────

class DockerEngine:
    """Manages a portable Docker Engine for saba-chan.

    On Windows every ``dockerd`` interaction goes through WSL2.
    On Linux the static binaries run natively.
    """

    def __init__(self, base_dir: Optional[str | Path] = None) -> None:
        self.wsl_mode: bool = (_SYSTEM == "Windows")
        self._dir = Path(base_dir) if base_dir else _portable_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pid_file = self._dir / "dockerd.pid"

    # ── Paths (native Linux) ─────────────────────────────────

    @property
    def docker_exe(self) -> Path:
        return self._dir / "docker"

    @property
    def dockerd_exe(self) -> Path:
        return self._dir / "dockerd"

    @property
    def compose_exe(self) -> Path:
        return self._dir / "docker-compose"

    @property
    def data_root(self) -> Path:
        return self._dir / "data"

    @property
    def log_file(self) -> Path:
        return self._dir / "dockerd.log"

    # ── Detection ────────────────────────────────────────────

    @property
    def binaries_ready(self) -> bool:
        if self.wsl_mode:
            return _wsl_docker_installed()
        return self.docker_exe.exists() and self.dockerd_exe.exists()

    @property
    def compose_ready(self) -> bool:
        if self.wsl_mode:
            return _wsl_compose_installed()
        return self.compose_exe.exists()

    def _system_docker_running(self) -> bool:
        """Check if *any* (system/Docker Desktop) daemon is accessible."""
        try:
            r = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=10,
                creationflags=_creation_flags(),
            )
            return r.returncode == 0
        except Exception:
            return False

    def _daemon_running(self) -> bool:
        """Check if our portable daemon is responding."""
        if self.wsl_mode:
            return _wsl_daemon_running()
        docker = str(self.docker_exe) if self.docker_exe.exists() else "docker"
        try:
            r = subprocess.run(
                [docker, "info"],
                capture_output=True, timeout=15,
                creationflags=_creation_flags(),
            )
            return r.returncode == 0
        except Exception:
            return False

    # ── Prerequisites ────────────────────────────────────────

    def check_prerequisites(self) -> Optional[str]:
        """Return an error string if prerequisites are missing, else ``None``."""
        if not self.wsl_mode:
            return None  # Linux: no special requirements
        if not _wsl_available():
            return (
                "WSL2_REQUIRED: Docker mode requires WSL2.\n"
                "Install it with an admin PowerShell:\n"
                "  wsl --install\n"
                "A reboot will be required after installation."
            )
        # Ensure iptables is available (dockerd needs it for bridge networking)
        self._wsl_ensure_iptables()
        return None

    def _wsl_ensure_iptables(self) -> None:
        """Install iptables inside WSL2 if missing (needed by dockerd)."""
        r = _wsl_run(["which", "iptables"], root=True, timeout=5)
        if r.returncode == 0:
            return  # already installed
        _log("iptables not found in WSL2, installing...")
        r = _wsl_run(
            ["sh", "-c",
             "apt-get update -qq && apt-get install -y -qq iptables 2>&1 | tail -3"],
            root=True, timeout=120,
        )
        if r.returncode != 0:
            _log("WARNING: iptables installation may have failed (non-fatal)")
        else:
            _log("iptables installed in WSL2")

    # ── Download ─────────────────────────────────────────────

    def ensure_available(self, *, timeout: int = 300) -> None:
        if not self.binaries_ready:
            self._download_engine(timeout=timeout)
        if not self.compose_ready:
            self._download_compose(timeout=timeout)
        # saba-docker-io: bidirectional stdin/stdout bridge for containers
        self._deploy_io_bridge()

    # -- IO Bridge --

    def _deploy_io_bridge(self) -> None:
        """Deploy saba-docker-io binary to Docker runtime directory.
        
        On WSL2 mode, copies from the extension build directory to /opt/saba-chan/docker/.
        On native Linux, the binary is found next to this extension file.
        """
        dest_name = "saba-docker-io"
        # Check if already deployed
        if self.wsl_mode:
            r = _wsl_run(["test", "-x", f"{_WSL2_DIR}/{dest_name}"], root=True, timeout=5)
            if r.returncode == 0:
                return  # Already installed
        else:
            native_dest = self._dir / dest_name
            if native_dest.exists():
                return

        # Find the built binary
        ext_dir = Path(__file__).resolve().parent
        # Look for pre-built binary in known locations
        # Go build outputs directly to the project dir (no target/ subdirectory)
        candidates = [
            ext_dir / dest_name / dest_name,       # Go build output (same dir as go.mod)
            ext_dir / "bin" / dest_name,            # manual placement
        ]
        source = None
        for c in candidates:
            if c.exists():
                source = c
                break

        if source is None:
            _log(f"saba-docker-io binary not found (checked {len(candidates)} locations), "
                 "stdin bridging to Docker containers will not be available")
            return

        if self.wsl_mode:
            wsl_tmp = _win_to_wsl_path(source)
            _wsl_run(["cp", wsl_tmp, f"{_WSL2_DIR}/{dest_name}"], root=True)
            _wsl_run(["chmod", "+x", f"{_WSL2_DIR}/{dest_name}"], root=True)
            _log(f"saba-docker-io deployed to WSL2 ({_WSL2_DIR}/{dest_name})")
        else:
            import shutil
            shutil.copy2(source, self._dir / dest_name)
            dest = self._dir / dest_name
            dest.chmod(dest.stat().st_mode | 0o755)
            _log(f"saba-docker-io deployed to {dest}")

    # -- Engine --

    def _download_engine(self, *, timeout: int = 300) -> None:
        if self.wsl_mode:
            return self._wsl_download_engine(timeout=timeout)
        self._native_download_engine(timeout=timeout)

    def _native_download_engine(self, *, timeout: int = 300) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        archive = self._dir / "docker.tgz"
        _download(_get_docker_engine_url(), archive, timeout=timeout, label="Docker Engine")
        _log(f"Extracting to {self._dir}")
        try:
            _extract_engine_tar(archive, self._dir)
        finally:
            archive.unlink(missing_ok=True)
        for exe in [self.docker_exe, self.dockerd_exe]:
            if exe.exists():
                exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not self.dockerd_exe.exists():
            raise FileNotFoundError(f"dockerd not found after extraction in {self._dir}")
        _log(f"Docker Engine ready at {self._dir}")

    def _wsl_download_engine(self, *, timeout: int = 300) -> None:
        _log("Downloading Docker Engine for WSL2...")
        tmp = Path(os.environ.get("TEMP", ".")) / "saba-docker-linux.tgz"
        _download(_get_docker_engine_url(), tmp, timeout=timeout, label="Docker Engine")
        wsl_tmp = _win_to_wsl_path(tmp)
        _wsl_run(["mkdir", "-p", _WSL2_DIR], root=True)
        _wsl_run(["mkdir", "-p", _WSL2_DATA], root=True)
        _log(f"Extracting into WSL2 at {_WSL2_DIR}...")
        r = _wsl_run(
            ["tar", "xzf", wsl_tmp, "-C", _WSL2_DIR, "--strip-components=1"],
            root=True, timeout=120,
        )
        tmp.unlink(missing_ok=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"Failed to extract Docker in WSL2 (exit {r.returncode}): "
                + r.stderr.decode(errors="replace")[:300]
            )
        if not _wsl_docker_installed():
            raise FileNotFoundError("dockerd not found in WSL2 after extraction")
        _log("Docker Engine binaries installed in WSL2")

    # -- Compose --

    def _download_compose(self, *, timeout: int = 300) -> None:
        if self.wsl_mode:
            return self._wsl_download_compose(timeout=timeout)
        self._native_download_compose(timeout=timeout)

    def _native_download_compose(self, *, timeout: int = 300) -> None:
        _download(_get_compose_url(), self.compose_exe, timeout=timeout, label="Docker Compose")
        self.compose_exe.chmod(
            self.compose_exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        _log(f"Docker Compose ready at {self.compose_exe}")

    def _wsl_download_compose(self, *, timeout: int = 300) -> None:
        _log("Downloading Docker Compose for WSL2...")
        tmp = Path(os.environ.get("TEMP", ".")) / "docker-compose-linux"
        _download(_get_compose_url(), tmp, timeout=timeout, label="Docker Compose")
        wsl_tmp = _win_to_wsl_path(tmp)
        wsl_dest = f"{_WSL2_DIR}/docker-compose"
        _wsl_run(["cp", wsl_tmp, wsl_dest], root=True)
        _wsl_run(["chmod", "+x", wsl_dest], root=True)
        # Symlink as CLI plugin so `docker compose` (space) also works
        _wsl_run(["mkdir", "-p", "/root/.docker/cli-plugins"], root=True)
        _wsl_run(["ln", "-sf", wsl_dest, "/root/.docker/cli-plugins/docker-compose"], root=True)
        tmp.unlink(missing_ok=True)
        _log("Docker Compose installed in WSL2")

    # ── Daemon Management ────────────────────────────────────

    def start_daemon(self) -> dict[str, Any]:
        if self.wsl_mode:
            return self._wsl_start_daemon()
        return self._native_start_daemon()

    def _native_start_daemon(self) -> dict[str, Any]:
        if self._daemon_running():
            _log("Docker daemon is already running")
            return {"started": False, "reason": "already_running", "pid": self._read_pid()}
        if not self.dockerd_exe.exists():
            raise FileNotFoundError(f"dockerd not found at {self.dockerd_exe}")
        self.data_root.mkdir(parents=True, exist_ok=True)

        result = self._try_spawn_dockerd()
        if result["started"]:
            # 빠른 활성 체크 — 3초 내 fatal 로그 감지
            time.sleep(3)
            if self._daemon_running():
                return result
            if self.log_file.exists():
                fatal = _check_log_for_fatal(self.log_file.read_text(errors="replace"))
                if fatal:
                    return {"started": False, "reason": "daemon_fatal", "error": fatal}
        return result

    def _try_spawn_dockerd(self) -> dict[str, Any]:
        """일반 권한으로 dockerd를 직접 Popen 스폰."""
        args = [str(self.dockerd_exe), "--data-root", str(self.data_root)]
        _log(f"Spawning: {' '.join(args)}")
        # log_fh는 자식 프로세스가 자신의 fd 복사본을 갖게 되므로 부모는
        # Popen 호출 직후 close 해야 한다. close 하지 않으면 dockerd 재시작 때마다
        # 데몬 프로세스의 fd가 계속 누적되어 OS 한도에 도달할 수 있다.
        log_fh = open(self.log_file, "a")
        try:
            kwargs: dict[str, Any] = {
                "stdout": log_fh, "stderr": log_fh,
                "start_new_session": True,
            }
            proc = subprocess.Popen(args, creationflags=_creation_flags(), **kwargs)
        finally:
            log_fh.close()
        self._pid_file.write_text(str(proc.pid))
        _log(f"dockerd spawned (PID {proc.pid})")
        return {"started": True, "pid": proc.pid}

    def _wsl_start_daemon(self) -> dict[str, Any]:
        if _wsl_daemon_running():
            _log("WSL2 Docker daemon is already running")
            return {"started": False, "reason": "already_running", "pid": self._wsl_read_pid()}
        # Clear old log
        _wsl_run(["sh", "-c", f"> {_WSL2_LOG}"], root=True)

        # Write a launcher script *inside* WSL so it persists across sessions.
        launcher = f"""\
#!/bin/sh
export PATH="{_WSL2_DIR}:$PATH"
# Start containerd if not running
if ! pgrep -x containerd > /dev/null 2>&1; then
    {_WSL2_DIR}/containerd > /dev/null 2>&1 &
    sleep 2
fi
# Start dockerd (foreground -- the WSL session keeps it alive)
exec {_WSL2_DIR}/dockerd \\
  -H unix:///var/run/docker.sock \\
  --data-root {_WSL2_DATA} \\
  --userland-proxy-path {_WSL2_DIR}/docker-proxy \\
  >> {_WSL2_LOG} 2>&1
"""
        launcher_path = f"{_WSL2_DIR}/start-dockerd.sh"
        # Write launcher via Popen stdin pipe (heredoc breaks on Windows)
        write_proc = subprocess.Popen(
            ["wsl", "-u", "root", "--", "sh", "-c",
             f"cat > {launcher_path} && chmod +x {launcher_path}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_creation_flags(),
        )
        _, write_err = write_proc.communicate(input=launcher.encode("utf-8"), timeout=10)
        if write_proc.returncode != 0:
            _log(f"Failed to write launcher script: {write_err.decode(errors='replace')[:200]}")
            return {"started": False, "reason": "launcher_write_failed"}

        # Launch the script via Popen so the WSL session stays alive.
        # The subprocess keeps running after we return; dockerd lives
        # as long as this WSL session lives.
        _log("Starting WSL2 Docker daemon (Popen)...")
        wsl_proc = subprocess.Popen(
            ["wsl", "-u", "root", "--", launcher_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(),
        )
        # wsl_proc.pid is the Windows-side PID of the `wsl` wrapper process
        # Save it so we can kill it later to stop the whole tree
        pid = wsl_proc.pid
        _wsl_run(["sh", "-c", f"echo {pid} > {_WSL2_PID}"], root=True, timeout=5)

        # Also store the Windows PID on the host side for stop_daemon
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(pid))

        _log(f"WSL2 dockerd session started (WSL wrapper PID {pid})")
        return {"started": True, "pid": pid}

    def wait_for_ready(self, timeout_secs: int = 120) -> bool:
        if self.wsl_mode:
            return self._wsl_wait_for_ready(timeout_secs)
        return self._native_wait_for_ready(timeout_secs)

    def _native_wait_for_ready(self, timeout_secs: int = 120) -> bool:
        docker = str(self.docker_exe) if self.docker_exe.exists() else "docker"
        _log(f"Waiting up to {timeout_secs}s for Docker daemon...")
        deadline = time.monotonic() + timeout_secs
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                r = subprocess.run(
                    [docker, "info"], capture_output=True, timeout=10,
                    creationflags=_creation_flags(),
                )
                if r.returncode == 0:
                    _log(f"Docker daemon ready (attempt {attempt})")
                    return True
            except Exception:
                pass
            if attempt % 3 == 0 and self.log_file.exists():
                text = self.log_file.read_text(errors="replace")
                fatal = _check_log_for_fatal(text)
                if fatal:
                    _log(f"dockerd fatal: {fatal}")
                    return False
            remaining = int(deadline - time.monotonic())
            if attempt % 5 == 0:
                _log(f"Still waiting... ({remaining}s remaining)")
            time.sleep(3)
        return False

    def _wsl_wait_for_ready(self, timeout_secs: int = 120) -> bool:
        _log(f"Waiting up to {timeout_secs}s for WSL2 Docker daemon...")
        deadline = time.monotonic() + timeout_secs
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            if _wsl_daemon_running():
                _log(f"WSL2 Docker daemon ready (attempt {attempt})")
                return True
            if attempt % 3 == 0:
                log_tail = _wsl_read_log_tail(10)
                fatal = _check_log_for_fatal(log_tail)
                if fatal:
                    _log(f"dockerd fatal: {fatal}")
                    return False
            remaining = int(deadline - time.monotonic())
            if attempt % 5 == 0:
                _log(f"Still waiting for WSL2 dockerd... ({remaining}s remaining)")
            time.sleep(3)
        return False

    # ── PID helpers ──────────────────────────────────────────

    def _read_pid(self) -> Optional[int]:
        if self._pid_file.exists():
            try:
                return int(self._pid_file.read_text().strip())
            except ValueError:
                pass
        return None

    def _wsl_read_pid(self) -> Optional[int]:
        try:
            r = _wsl_run(["cat", _WSL2_PID], root=True, timeout=5)
            if r.returncode == 0:
                return int(r.stdout.decode(errors="replace").strip())
        except Exception:
            pass
        return None

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        if self.wsl_mode:
            return {
                "wsl_mode": True,
                "binaries_ready": self.binaries_ready,
                "compose_ready": self.compose_ready,
                "daemon_running": _wsl_daemon_running(),
                "system_docker": self._system_docker_running(),
                "portable_dir": _WSL2_DIR,
                "docker_exe": f"{_WSL2_DIR}/docker",
                "compose_exe": f"{_WSL2_DIR}/docker-compose",
                "pid": self._wsl_read_pid(),
            }
        return {
            "wsl_mode": False,
            "binaries_ready": self.binaries_ready,
            "compose_ready": self.compose_ready,
            "daemon_running": self._daemon_running(),
            "system_docker": self._system_docker_running(),
            "portable_dir": str(self._dir),
            "docker_exe": str(self.docker_exe) if self.docker_exe.exists() else None,
            "compose_exe": str(self.compose_exe) if self.compose_exe.exists() else None,
            "pid": self._read_pid(),
        }

# ── Plugin Runner Interface ──────────────────────────────────────

def ensure(config: dict) -> dict:
    """Docker 데몬을 사용할 수 있게 만든다 (필요 시 다운로드 → 시작 → 대기).

    config:
      base_dir        포터블 디렉터리 (기본: _portable_dir())
      allow_download  False면 바이너리가 없을 때 다운로드하지 않고 실패로 보고한다
      timeout / wait_timeout  다운로드·준비 대기 제한 시간(초)

    결과의 ``wsl_mode`` 는 상태 파일에 저장된다. compose_manager는 이 값으로 CLI를 고른다.
    """
    result = _ensure(config)
    if result.get("daemon_ready"):
        save_engine_state({"wsl_mode": bool(result.get("wsl_mode"))})
    return result


def _ensure(config: dict) -> dict:
    engine = DockerEngine(config.get("base_dir"))

    # 0. Check if system Docker (Docker Desktop etc.) is already running
    if engine._system_docker_running():
        return {
            "success": True,
            "message": "System Docker is already running",
            "daemon_ready": True,
            "wsl_mode": False,
        }

    # 1. Our portable daemon already running?
    if engine.binaries_ready and engine._daemon_running():
        return {
            "success": True,
            "message": "Portable Docker daemon is running",
            "daemon_ready": True,
            "wsl_mode": engine.wsl_mode,
        }

    # 2. Prerequisites
    prereq_err = engine.check_prerequisites()
    if prereq_err:
        tag = prereq_err.split(":")[0] if ":" in prereq_err[:20] else ""
        display_msg = prereq_err.split(": ", 1)[-1] if tag else prereq_err
        return {
            "success": False,
            "message": display_msg,
            "error": display_msg,
            "daemon_ready": False,
            "needs_reboot": "REBOOT" in tag,
            "wsl_mode": engine.wsl_mode,
        }

    # 3. Download if needed
    if not engine.binaries_ready:
        if not config.get("allow_download", True):
            message = "Docker Engine is not installed yet; it will be installed when a Docker server is provisioned or started"
            return {
                "success": True,
                "message": message,
                "daemon_ready": False,
                "deferred": True,
                "wsl_mode": engine.wsl_mode,
            }
        engine.ensure_available(timeout=config.get("timeout", 300))

    # 4. Start daemon
    engine.start_daemon()

    # 5. Wait for readiness
    ready = engine.wait_for_ready(timeout_secs=config.get("wait_timeout", 120))

    # 6. Build result
    if engine.wsl_mode:
        log_tail = _wsl_read_log_tail(20)
    else:
        log_tail = ""
        if engine.log_file.exists():
            try:
                log_tail = engine.log_file.read_text(errors="replace")
            except OSError:
                pass

    fatal = _check_log_for_fatal(log_tail) if not ready else None
    if ready:
        message = "Docker Engine ready"
    elif fatal:
        message = f"Docker daemon start failed: {fatal}"
    else:
        message = "dockerd started but did not respond in time"

    result: dict[str, Any] = {
        "success": ready,
        "message": message,
        "daemon_ready": ready,
        **engine.status(),
    }
    if not ready:
        result["error"] = message
        if log_tail:
            result["dockerd_log_tail"] = "\n".join(log_tail.splitlines()[-20:])
    return result


def startup(config: dict) -> dict:
    """daemon.startup — 가벼운 확인만 한다.

    docker_enabled 인스턴스가 없으면 아무것도 하지 않는다. 있으면 이미 설치된 엔진만
    시작하고, 엔진 다운로드는 server.post_create(provision)·server.pre_start(start)로 미룬다.
    """
    if not _has_docker_instances():
        return {"success": True, "message": "No Docker instances; Docker Engine check skipped"}
    return ensure({**config, "allow_download": False})


FUNCTIONS = {
    "startup": startup,
    # 수동 진단용
    "ensure": ensure,
}


def _error_result(message: str) -> dict:
    return {"success": False, "error": message, "message": message}


def _run_cli(functions: dict, argv: list[str], stdin, *, error_extra: dict | None = None) -> int:
    """플러그인 프로토콜 실행: ``<script> <function>`` + stdin JSON → stdout JSON 1개.

    데몬은 0이 아닌 종료 코드를 Err로 처리하고 stdout을 버린다. 따라서 실패도
    ``{"success": false, "error", "message"}`` (+ *error_extra*) 로 출력하고 0으로 종료한다.
    traceback은 stderr로 보낸다 (데몬 debug 로그).
    """
    if len(argv) < 2:
        result = {**_error_result("No function specified"), **(error_extra or {})}
    elif argv[1] not in functions:
        result = {**_error_result(f"Unknown function: {argv[1]}"), **(error_extra or {})}
    else:
        try:
            raw = stdin.read().lstrip("﻿")  # PowerShell BOM 제거
            config = json.loads(raw) if raw.strip() else {}
            result = functions[argv[1]](config)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            result = {**_error_result(str(e) or type(e).__name__), **(error_extra or {})}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli(FUNCTIONS, sys.argv, sys.stdin))
