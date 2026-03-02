"""
saba-chan SteamCMD Extension
=============================
Portable SteamCMD management: auto-detect, auto-download, install & update
game dedicated servers via Valve's SteamCMD CLI.

This extension is used by game modules whose ``module.toml`` specifies
``method = "steamcmd"`` in the ``[install]`` section.

Usage (from a game module lifecycle.py):
    from extensions.steamcmd import SteamCMD

    steam = SteamCMD()                      # auto-detects or bootstraps
    steam.ensure_available()                 # downloads from Valve CDN if needed
    steam.install(app_id=2394010,            # Palworld dedicated server
                  install_dir="/srv/palworld/server",
                  anonymous=True)

Standalone CLI check:
    python -m extensions.steamcmd            # prints JSON status blob
"""

from __future__ import annotations

import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Optional

# ── Constants ────────────────────────────────────────────────────

_SYSTEM = platform.system()  # "Windows", "Linux", "Darwin"

_STEAMCMD_URLS: dict[str, str] = {
    "Windows": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip",
    "Linux": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
    "Darwin": "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz",
}

_EXE_NAME = "steamcmd.exe" if _SYSTEM == "Windows" else "steamcmd.sh"

_PORTABLE_SUBDIR = "steamcmd"

# Approximate download sizes (bytes) for common dedicated server app IDs.
# Used to estimate download progress when SteamCMD stdout is buffered.
# Values are rough estimates and will be refined as more data is available.
_KNOWN_APP_SIZES: dict[int, int] = {
    # Game Server name                    # Approx download (bytes)
    90:      3_200_000_000,   # Half-Life Dedicated Server
    232250:  27_000_000_000,  # Team Fortress 2 DS
    232330:  35_000_000_000,  # Counter-Strike 2 DS
    258550:  3_000_000_000,   # Rust DS
    376030:  12_000_000_000,  # ARK: Survival Evolved DS
    380870:  6_300_000_000,   # Project Zomboid DS
    443030:  6_000_000_000,   # Conan Exiles DS
    530870:  900_000_000,     # Factorio Headless
    896660:  2_500_000_000,   # Valheim DS
    1007820: 8_000_000_000,   # Satisfactory DS
    1026340: 4_200_000_000,   # Enshrouded DS
    1218040: 2_500_000_000,   # Necesse DS
    1690800: 3_000_000_000,   # Abiotic Factor DS
    1829350: 6_000_000_000,   # V Rising DS
    2278520: 5_000_000_000,   # Core Keeper DS
    2394010: 5_700_000_000,   # Palworld DS
    2430930: 800_000_000,     # Soulmask DS
}


# ── Helpers ──────────────────────────────────────────────────────


def _dir_size(path: Path) -> int:
    """Return total size of all files under *path* in bytes."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(str(path)):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _portable_dir() -> Path:
    """Return the directory used by saba-chan's portable SteamCMD.

    Windows : ``%APPDATA%/saba-chan/steamcmd``
    Linux   : ``~/.config/saba-chan/steamcmd``
    macOS   : ``~/.config/saba-chan/steamcmd``
    """
    if _SYSTEM == "Windows":
        base = os.environ.get("APPDATA", "")
        if not base:
            raise EnvironmentError("APPDATA environment variable not set")
        return Path(base) / "saba-chan" / _PORTABLE_SUBDIR
    else:
        home = os.environ.get("HOME", "")
        if not home:
            raise EnvironmentError("HOME environment variable not set")
        return Path(home) / ".config" / "saba-chan" / _PORTABLE_SUBDIR


def _common_candidates() -> list[Path]:
    """Well-known SteamCMD installation locations per platform."""
    candidates: list[Path] = []
    if _SYSTEM == "Windows":
        candidates.append(Path(r"C:\SteamCMD\steamcmd.exe"))
        candidates.append(Path(r"C:\steamcmd\steamcmd.exe"))
        pf = os.environ.get("ProgramFiles", "")
        if pf:
            candidates.append(Path(pf) / "SteamCMD" / "steamcmd.exe")
        pf86 = os.environ.get("ProgramFiles(x86)", "")
        if pf86:
            candidates.append(Path(pf86) / "SteamCMD" / "steamcmd.exe")
            candidates.append(Path(pf86) / "Steam" / "steamcmd.exe")
    else:
        home = os.environ.get("HOME", "")
        if home:
            candidates.append(Path(home) / "steamcmd" / "steamcmd.sh")
            candidates.append(Path(home) / "Steam" / "steamcmd.sh")
        candidates.append(Path("/usr/games/steamcmd"))
        candidates.append(Path("/usr/local/bin/steamcmd"))
    return candidates


# ── Core Class ───────────────────────────────────────────────────

class SteamCMD:
    """Manages a SteamCMD installation for saba-chan.

    Calling :meth:`ensure_available` guarantees that a working ``steamcmd``
    binary is present — downloading a fresh portable copy from Valve if
    necessary.
    """

    def __init__(self, explicit_path: Optional[str | Path] = None) -> None:
        if explicit_path is not None:
            self._path: Optional[Path] = Path(explicit_path)
        else:
            self._path = self._detect()

    # ── Properties ───────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._path is not None and self._path.exists()

    @property
    def path(self) -> Optional[Path]:
        return self._path

    # ── Detection ────────────────────────────────────────────

    @staticmethod
    def _detect() -> Optional[Path]:
        """Try to find an existing SteamCMD binary on this system."""
        # 1) Our own portable copy
        try:
            portable_exe = _portable_dir() / _EXE_NAME
            if portable_exe.exists():
                return portable_exe
        except EnvironmentError:
            pass

        # 2) Common install locations
        for candidate in _common_candidates():
            if candidate.exists():
                return candidate

        # 3) System PATH
        found = shutil.which(_EXE_NAME.replace(".exe", "") if _SYSTEM != "Windows" else _EXE_NAME)
        if found:
            return Path(found)

        return None

    # ── Auto-bootstrap ───────────────────────────────────────

    def ensure_available(self, *, timeout: int = 120) -> None:
        """Download and extract a portable SteamCMD if not already present.

        After this call :attr:`available` is guaranteed to be ``True`` (or
        an exception was raised).
        """
        if self.available:
            return

        portable = _portable_dir()
        exe_path = portable / _EXE_NAME

        # Perhaps downloaded in a previous session
        if exe_path.exists():
            self._path = exe_path
            return

        url = _STEAMCMD_URLS.get(_SYSTEM)
        if url is None:
            raise RuntimeError(f"No SteamCMD download URL for platform: {_SYSTEM}")

        _log(f"SteamCMD not found — downloading from Valve CDN ({url}) …")

        portable.mkdir(parents=True, exist_ok=True)

        # Download
        req = urllib.request.Request(url, headers={"User-Agent": "saba-chan/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            if total > 0:
                chunks: list[bytes] = []
                downloaded = 0
                chunk_size = 64 * 1024
                last_pct = -1
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    pct = min(int(downloaded * 100 / total), 100)
                    if pct != last_pct:
                        dl_mb = downloaded / 1_048_576
                        total_mb = total / 1_048_576
                        _progress(pct, f"SteamCMD: {dl_mb:.1f}/{total_mb:.1f} MB")
                        last_pct = pct
                data = b"".join(chunks)
            else:
                data = resp.read()

        size_mb = len(data) / 1_048_576
        _log(f"Downloaded {size_mb:.1f} MB, extracting …")

        # Extract
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(portable)
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                tf.extractall(portable)

        if not exe_path.exists():
            raise FileNotFoundError(
                f"Archive extracted but {_EXE_NAME} not found in {portable}"
            )

        # Make executable on Unix
        if _SYSTEM != "Windows":
            exe_path.chmod(exe_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        _log(f"Portable SteamCMD ready at {exe_path}")
        self._path = exe_path

    # ── Install / Update ─────────────────────────────────────

    def install(
        self,
        app_id: int,
        install_dir: str | Path,
        *,
        anonymous: bool = True,
        beta: Optional[str] = None,
        beta_password: Optional[str] = None,
        platform_override: Optional[str] = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Run ``steamcmd +app_update`` to install or update a game server.

        Returns a dict with ``success``, ``message``, ``install_dir``,
        ``app_id`` keys.
        """
        if not self.available:
            raise RuntimeError(
                "SteamCMD is not available. Call ensure_available() first."
            )

        install_dir = Path(install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)

        args: list[str] = [str(self._path)]

        # ── Login 전에 설정해야 하는 옵션들 ──

        # Platform override (반드시 login 전)
        if platform_override:
            args += ["+@sSteamCmdForcePlatformType", platform_override]

        # Install directory (반드시 login 전)
        args += ["+force_install_dir", str(install_dir)]

        # Login
        if anonymous:
            args += ["+login", "anonymous"]
        else:
            raise NotImplementedError(
                "Non-anonymous SteamCMD login is not yet supported."
            )

        # App update
        args += ["+app_update", str(app_id)]
        if beta:
            args += [f"-beta {beta}"]
            if beta_password:
                args += [f"-betapassword {beta_password}"]
        if validate:
            args.append("validate")

        args.append("+quit")

        import re as _re
        import threading as _threading
        import time as _time

        pct_pattern = _re.compile(r"progress:\s*([\d.]+)\s*\((\d+)\s*/\s*(\d+)\)")

        # SteamCMD commonly exits with code 7 on first run (self-update).
        # Retry up to 3 times to handle this.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            _log(f"Running (attempt {attempt}/{max_attempts}): {' '.join(args)}")

            try:
                # 설치 전 디렉터리 초기 크기 측정
                initial_size = _dir_size(install_dir)

                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=_creation_flags(),
                )

                # ── SteamCMD stdout을 별도 스레드에서 읽기 ──
                # SteamCMD는 파이프에 full buffering을 사용하여 readline()이
                # 프로세스 종료까지 블록됨. 별도 스레드로 분리.
                stdout_lines: list[str] = []
                parsed_pct = [0]  # mutable from thread
                parsed_total = [0]  # total bytes from progress line
                parsed_msg = ["Connecting to Steam..."]

                def _reader():
                    try:
                        while True:
                            raw = proc.stdout.readline()
                            if not raw:
                                break
                            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                            stdout_lines.append(line)
                            stripped = line.strip()
                            if not stripped:
                                continue
                            m = pct_pattern.search(stripped)
                            if m:
                                parsed_pct[0] = min(int(float(m.group(1))), 100)
                                parsed_total[0] = int(m.group(3))
                                dl_mb = int(m.group(2)) / 1_048_576
                                total_mb = parsed_total[0] / 1_048_576
                                parsed_msg[0] = f"Downloading: {dl_mb:.0f}/{total_mb:.0f} MB ({parsed_pct[0]}%)"
                    except Exception:
                        pass

                reader_thread = _threading.Thread(target=_reader, daemon=True)
                reader_thread.start()

                # ── 디스크 사용량 기반 프로그레스 모니터링 (메인 스레드) ──
                # SteamCMD stdout이 버퍼링되어도 디스크 사용량은 실시간으로 변함.
                _progress(0, "Connecting to Steam...")
                last_msg = ""
                estimated_total = _KNOWN_APP_SIZES.get(app_id, 0)

                while proc.poll() is None:
                    _time.sleep(2.0)

                    # stdout 파싱 결과가 있으면 우선 사용 (SteamCMD가 flush한 경우)
                    if parsed_pct[0] > 0:
                        pct = parsed_pct[0]
                        msg = parsed_msg[0]
                    else:
                        # 디스크 사용량 기반 추정
                        current_size = _dir_size(install_dir)
                        added_bytes = current_size - initial_size
                        added_mb = added_bytes / 1_048_576

                        # total 결정: stdout 파싱 > 알려진 앱 크기 > 없음
                        total = parsed_total[0] or estimated_total

                        if total > 0 and added_bytes > 0:
                            pct = min(int(added_bytes * 99 / total), 99)
                            total_mb = total / 1_048_576
                            msg = f"Downloading: {added_mb:.0f}/{total_mb:.0f} MB"
                        elif added_mb > 1:
                            pct = 0
                            msg = f"Downloading... ({added_mb:.0f} MB)"
                        else:
                            pct = 0
                            msg = "Preparing server files..."

                    # 매 사이클마다 보고 — 메시지나 pct가 변할 때
                    if msg != last_msg:
                        _progress(pct, msg)
                        last_msg = msg

                # 프로세스 종료 — reader 스레드 합류
                reader_thread.join(timeout=10)
                stdout = "".join(stdout_lines)
                returncode = proc.returncode

            except subprocess.TimeoutExpired:
                proc.kill()
                return {
                    "success": False,
                    "message": "SteamCMD timed out after 600 s",
                    "install_dir": str(install_dir),
                    "app_id": app_id,
                }

            if returncode == 0 or "Success! App" in stdout:
                _progress(100, "Server files installed successfully")
                _log(f"SteamCMD install completed for app {app_id}")

                # SteamCMD validate는 파일 검증만 하고 appmanifest의 buildid를
                # 교정하지 않을 수 있음. 원격 buildid를 조회하여 manifest를 갱신.
                self._fix_local_buildid(app_id, install_dir)

                return {
                    "success": True,
                    "message": f"Successfully installed app {app_id} to {install_dir}",
                    "install_dir": str(install_dir),
                    "app_id": app_id,
                }

            # Exit code 7: SteamCMD self-updated or transient failure -- retry
            if returncode == 7 and attempt < max_attempts:
                _log(f"SteamCMD exited with code 7 (attempt {attempt}) -- retrying...")
                _time.sleep(3)
                continue

            detail = stdout[:2000]
            _log(f"SteamCMD failed for app {app_id}: {detail}")
            return {
                "success": False,
                "message": f"SteamCMD failed (exit code {returncode}): {detail}",
                "install_dir": None,
                "app_id": app_id,
            }

        # Should not reach here, but just in case
        return {
            "success": False,
            "message": "SteamCMD failed after all attempts",
            "install_dir": None,
            "app_id": app_id,
        }

    def update(
        self,
        app_id: int,
        install_dir: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Alias for :meth:`install` — SteamCMD handles incremental updates."""
        return self.install(app_id, install_dir, **kwargs)

    # ── Buildid Fixup ────────────────────────────────────────

    def _fix_local_buildid(
        self,
        app_id: int,
        install_dir: str | Path,
        *,
        branch: str = "public",
    ) -> None:
        """Install/update 성공 후 appmanifest의 buildid를 원격 값으로 교정.

        SteamCMD ``+app_update validate``는 파일 무결성만 확인하고
        appmanifest의 ``buildid`` 필드를 교정하지 않는 경우가 있다.
        원격 ``app_info_print``에서 최신 buildid를 가져와 manifest에 기록한다.
        """
        import re as _re

        try:
            raw = self._app_info_print(app_id)
            if not raw:
                _log(f"Cannot fix buildid: app_info_print returned no data for {app_id}")
                return

            remote_buildid = parse_remote_buildid(raw, branch=branch)
            if not remote_buildid:
                _log(f"Cannot fix buildid: remote buildid not found for app {app_id}")
                return

            manifest_path = Path(install_dir) / "steamapps" / f"appmanifest_{app_id}.acf"
            if not manifest_path.exists():
                _log(f"Cannot fix buildid: manifest not found at {manifest_path}")
                return

            content = manifest_path.read_text(encoding="utf-8", errors="replace")
            local_buildid = get_local_buildid(str(install_dir), app_id)

            if local_buildid == remote_buildid:
                return  # 이미 올바름

            # buildid 교체
            new_content = _re.sub(
                r'("buildid"\s+")(\d+)(")',
                rf'\g<1>{remote_buildid}\3',
                content,
            )
            manifest_path.write_text(new_content, encoding="utf-8")
            _log(f"Fixed buildid for app {app_id}: {local_buildid} → {remote_buildid}")

        except Exception as e:
            _log(f"Failed to fix buildid for app {app_id}: {e}")

    # ── Update Check (buildid comparison) ────────────────────

    def check_update(
        self,
        app_id: int,
        install_dir: str | Path,
        *,
        branch: str = "public",
    ) -> dict[str, Any]:
        """Check if a Steam game server has an update available.

        Compares the local ``buildid`` (from ``steamapps/appmanifest_<appid>.acf``)
        against the remote ``buildid`` obtained via ``steamcmd +app_info_print``.

        Returns a dict with:
        - ``update_available``: bool
        - ``local_buildid``: str | None
        - ``remote_buildid``: str | None
        - ``app_id``: int
        """
        local = get_local_buildid(str(install_dir), app_id)
        remote: Optional[str] = None

        if self.available:
            try:
                raw = self._app_info_print(app_id)
                if raw:
                    remote = parse_remote_buildid(raw, branch=branch)
            except Exception as e:
                _log(f"Failed to query remote buildid for app {app_id}: {e}")

        update_available = False
        if local and remote:
            update_available = local != remote
        elif local is None and remote is not None:
            # No local manifest — consider as needing update (fresh install)
            update_available = True

        return {
            "update_available": update_available,
            "local_buildid": local,
            "remote_buildid": remote,
            "app_id": app_id,
        }

    def _app_info_print(self, app_id: int) -> Optional[str]:
        """Run ``steamcmd +app_info_update 1 +app_info_print <appid> +quit``.

        Returns the raw stdout text, or None on failure.
        """
        if not self.available:
            return None

        args = [
            str(self._path),
            "+login", "anonymous",
            "+app_info_update", "1",
            "+app_info_print", str(app_id),
            "+quit",
        ]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=_creation_flags(),
            )
            return result.stdout
        except Exception as e:
            _log(f"app_info_print failed: {e}")
            return None

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """JSON-serialisable status blob for API responses."""
        portable = None
        try:
            portable = str(_portable_dir())
        except EnvironmentError:
            pass

        return {
            "available": self.available,
            "path": str(self._path) if self._path else None,
            "portable_dir": portable,
            "auto_bootstrap": True,
        }


# ── Utilities ────────────────────────────────────────────────────


def get_local_buildid(install_dir: str, app_id: int) -> Optional[str]:
    """Read the local buildid from ``steamapps/appmanifest_<appid>.acf``.

    SteamCMD stores app manifests in Valve's KeyValues format inside the
    ``steamapps/`` subdirectory of the install root.  The file contains a
    ``"buildid"`` key whose value is the currently installed build number.

    Returns the buildid string, or ``None`` if the manifest does not exist
    or cannot be parsed.
    """
    manifest_path = Path(install_dir) / "steamapps" / f"appmanifest_{app_id}.acf"
    if not manifest_path.exists():
        return None

    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        # Simple Valve KeyValues parser — extract "buildid" value
        import re as _re
        match = _re.search(r'"buildid"\s+"(\d+)"', content)
        return match.group(1) if match else None
    except Exception:
        return None


def parse_remote_buildid(raw_output: str, *, branch: str = "public") -> Optional[str]:
    """Extract the buildid for *branch* from ``steamcmd +app_info_print`` output.

    The output uses Valve's indented KeyValues format.  We look for::

        branches
          <branch>
            buildid: <number>   OR   "buildid"  "<number>"

    Returns the buildid string, or ``None`` if not found.
    """
    import re as _re

    # Strategy: find the branch section, then extract its buildid.
    # SteamCMD output can use either colon-separated or KV-quoted format.
    lines = raw_output.splitlines()
    in_branches = False
    in_target_branch = False
    branch_indent = -1

    for line in lines:
        stripped = line.strip()

        # Detect "branches" section
        if stripped in ('"branches"', 'branches'):
            in_branches = True
            continue

        if in_branches and not in_target_branch:
            # Look for our target branch name
            if stripped.strip('"') == branch:
                in_target_branch = True
                branch_indent = len(line) - len(line.lstrip())
                continue

        if in_target_branch:
            current_indent = len(line) - len(line.lstrip())
            # If we've de-indented back to branch level or above, we've left the section
            if current_indent <= branch_indent and stripped and stripped not in ('{', '}'):
                # Check if this is the opening brace of the branch block
                if stripped == '{':
                    continue
                break

            # Look for buildid in various formats
            # Format 1: "buildid"		"12345678"
            m = _re.search(r'"buildid"\s+"(\d+)"', stripped)
            if m:
                return m.group(1)
            # Format 2: buildid: 12345678
            m = _re.search(r'buildid[:\s]+(\d+)', stripped)
            if m:
                return m.group(1)

    return None


def _log(msg: str) -> None:
    """Write to stderr so it does not pollute stdout JSON."""
    print(f"[steamcmd] {msg}", file=sys.stderr, flush=True)


def _progress(percent: int, message: str) -> None:
    """Emit a structured progress line on stderr for the Rust daemon to parse."""
    line = json.dumps({"percent": percent, "message": message}, ensure_ascii=True)
    print(f"PROGRESS:{line}", file=sys.stderr, flush=True)


def _creation_flags() -> int:
    """Return subprocess creation flags (Windows: hide console window)."""
    if _SYSTEM == "Windows":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0


# ── CLI entry-point ──────────────────────────────────────────────

def _cli() -> None:
    """``python -m extensions.steamcmd`` — print status JSON."""
    steam = SteamCMD()
    print(json.dumps(steam.status(), indent=2))


# ── Plugin runner interface ──────────────────────────────────────
# Called when the Rust daemon executes:
#   python extensions/steamcmd.py <function> < config.json

def _plugin_ensure(config: dict) -> dict:
    steam = SteamCMD(config.get("explicit_path"))
    steam.ensure_available(timeout=config.get("timeout", 120))
    return steam.status()


def _plugin_install(config: dict) -> dict:
    steam = SteamCMD(config.get("explicit_path"))
    steam.ensure_available()
    return steam.install(
        app_id=config["app_id"],
        install_dir=config["install_dir"],
        anonymous=config.get("anonymous", True),
        beta=config.get("beta"),
        beta_password=config.get("beta_password"),
        platform_override=config.get("platform"),
        validate=config.get("validate", True),
    )


def _plugin_status(config: dict) -> dict:
    steam = SteamCMD(config.get("explicit_path"))
    return steam.status()


def _plugin_check_update(config: dict) -> dict:
    """Check if a game server has an update available via buildid comparison."""
    steam = SteamCMD(config.get("explicit_path"))
    app_id = config.get("app_id")
    install_dir = config.get("install_dir", "")
    branch = config.get("branch", "public")

    if not app_id:
        return {
            "update_available": False,
            "local_buildid": None,
            "remote_buildid": None,
            "app_id": None,
            "error": "app_id is required",
        }

    # Even if SteamCMD isn't available, we can still report local buildid
    try:
        steam.ensure_available()
    except Exception as e:
        _log(f"SteamCMD bootstrap failed: {e}")

    return steam.check_update(
        app_id=int(app_id),
        install_dir=install_dir,
        branch=branch,
    )


FUNCTIONS = {
    "ensure": _plugin_ensure,
    "install": _plugin_install,
    "update": _plugin_install,    # SteamCMD update == install
    "status": _plugin_status,
    "check_update": _plugin_check_update,
}


if __name__ == "__main__":
    # Plugin runner protocol: extensions/steamcmd.py <function>
    # Config JSON on stdin.
    if len(sys.argv) < 2:
        _cli()
        sys.exit(0)

    function_name = sys.argv[1]
    fn = FUNCTIONS.get(function_name)
    if fn is None:
        result = {"success": False, "message": f"Unknown function: {function_name}"}
    else:
        try:
            input_data = sys.stdin.read()
            config_data = json.loads(input_data) if input_data.strip() else {}
            result = fn(config_data)
        except Exception as e:
            result = {"success": False, "message": str(e)}

    json.dump(result, sys.stdout)
