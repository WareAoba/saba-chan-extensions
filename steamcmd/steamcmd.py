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

Daemon hook (server.check_update):
    python steamcmd.py check_update < context.json
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import traceback
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
# 다시 돌려도 풀리지 않는 설치 실패 (종료 코드 8)
_PERMANENT_FAILURES = ("Disk write failure", "Not enough disk space", "Invalid platform", "No subscription")

# SteamCMD 자체를 받는 제한 시간 (처음 설치는 이것을 먼저 한다). 읽기 한 번은 _READ_TIMEOUT 안에 끝나야 해서
# 한도를 넘는 것은 그 한 번만큼이다
_BOOTSTRAP_TIMEOUT = 120
_READ_TIMEOUT = 30

# SteamCMD 받기와 설치를 합한 제한 시간. 데몬의 install_server 타임아웃(1800초)보다 짧게 잡아
# 데몬이 Python을 죽이기 전에 steamcmd를 직접 종료한다 (고아 프로세스 방지). 설치는 같은 객체의 받기가 실제로 쓴 시간만 뺀다
_INSTALL_BUDGET = 1740

# 설치 진행률 모니터링 주기 (초)
_POLL_INTERVAL = 2.0

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


def _disk_progress(added_bytes: int, total: int) -> tuple[Optional[int], str]:
    """디스크에 늘어난 크기로 어림한 진행률과 문구.

    늘어난 크기에는 받기 임시 파일(steamapps/downloading)과 SteamCMD가 미리 크기를 잡아 둔 파일도 들어가
    총량을 넘을 수 있다. 넘으면 진행률을 모르므로 None(직전 값 유지)과 총량 없는 문구를 준다
    (5547/5536 MB나 127MB 다음 99%처럼 보이지 않게).
    """
    added_mb = added_bytes / 1_048_576
    if 0 < added_bytes < total:
        return min(int(added_bytes * 99 / total), 99), f"Downloading: {added_mb:.0f}/{total / 1_048_576:.0f} MB"
    if added_mb > 1:
        return (None if total > 0 else 0), f"Downloading... ({added_mb:.0f} MB)"
    return 0, "Preparing server files..."


def _manifest_progress(install_dir: str, app_id: int, added_bytes: int = 0) -> Optional[tuple[int, str]]:
    """appmanifest의 BytesDownloaded/BytesToDownload로 읽은 받기 진행률. 받을 양을 모르면 None.

    SteamCMD는 받는 동안 BytesDownloaded를 거의 갱신하지 않는다(0에 머물다 끝에 한꺼번에).
    디스크에 늘어난 크기(*added_bytes*)가 받을 양 안이면 그만큼 받은 것으로 본다. 넘으면 미리 잡은 파일이라 믿지 않는다.
    """
    manifest = resolve_manifest_path(install_dir, app_id)
    if manifest is None:
        return None
    try:
        content = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    to_download = re.search(r'"BytesToDownload"\s+"(\d+)"', content)
    downloaded = re.search(r'"BytesDownloaded"\s+"(\d+)"', content)
    if not to_download or not downloaded or int(to_download.group(1)) <= 0:
        return None
    total, done = int(to_download.group(1)), min(int(downloaded.group(1)), int(to_download.group(1)))
    if done < added_bytes < total:
        done = added_bytes
    pct = min(int(done * 100 / total), 99)
    return pct, f"Downloading: {done / 1_048_576:.0f}/{total / 1_048_576:.0f} MB ({pct}%)"


def _portable_dir() -> Path:
    """Return the directory used by saba-chan's portable SteamCMD.

    데몬이 준 ``SABA_EXTENSION_DATA_ROOT/steamcmd`` (격리된 실행은 구성요소마다 다른 뿌리를 받는다).
    없으면 (옛 데몬):

    Windows : ``%APPDATA%/saba-chan/steamcmd``
    Linux   : ``~/.config/saba-chan/steamcmd``
    macOS   : ``~/.config/saba-chan/steamcmd``
    """
    root = os.environ.get("SABA_EXTENSION_DATA_ROOT", "")
    if root:
        return Path(root) / _PORTABLE_SUBDIR
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
        # ensure_available이 SteamCMD를 받는 데 쓴 시간 (설치 한도에서 뺀다)
        self._bootstrap_secs = 0.0

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

        # 데몬이 뿌리를 주면 그 아래 사본만 쓴다 (격리 실행은 시스템 사본을 스스로 업데이트할 수 없다)
        if os.environ.get("SABA_EXTENSION_DATA_ROOT"):
            return None

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

    def ensure_available(self, *, timeout: int = _BOOTSTRAP_TIMEOUT) -> None:
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

        started = time.monotonic()
        try:
            data = _download_bytes(url, timeout=timeout)
        finally:
            self._bootstrap_secs += time.monotonic() - started
        _log(f"Downloaded {len(data) / 1_048_576:.1f} MB, extracting …")
        _extract_archive(data, url, portable)

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
        timeout: Optional[float] = _INSTALL_BUDGET,
    ) -> dict[str, Any]:
        """Run ``steamcmd +app_update`` to install or update a game server.

        *timeout* 는 재시도와 이 객체의 SteamCMD 받기를 포함한 전체 제한 시간(초)이다. 넘기면 steamcmd를
        종료하고 실패를 반환한다. ``None`` 이면 제한하지 않는다.

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
        # 옵션과 값은 별도 argv 토큰이어야 steamcmd가 인식한다
        if beta:
            args += ["-beta", beta]
            if beta_password:
                args += ["-betapassword", beta_password]
        if validate:
            args.append("validate")

        args.append("+quit")

        pct_pattern = re.compile(r"progress:\s*([\d.]+)\s*\((\d+)\s*/\s*(\d+)\)")
        if timeout is not None:
            timeout = max(0.0, timeout - self._bootstrap_secs)
        deadline = time.monotonic() + timeout if timeout is not None else None

        # SteamCMD commonly exits with code 7 on first run (self-update).
        # Retry up to 3 times to handle this.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            _log(f"Running (attempt {attempt}/{max_attempts}): {' '.join(args)}")

            # 설치 전 디렉터리 초기 크기 측정 (install_dir + steamcmd 캐시)
            steamcmd_cache = self._path.parent / "steamapps"
            initial_size = _dir_size(install_dir)
            if steamcmd_cache.exists():
                initial_size += _dir_size(steamcmd_cache)

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
                    for raw in iter(proc.stdout.readline, b""):
                        line = raw.decode("utf-8", errors="replace")
                        stdout_lines.append(line)
                        m = pct_pattern.search(line.strip())
                        if m:
                            parsed_pct[0] = min(int(float(m.group(1))), 100)
                            parsed_total[0] = int(m.group(3))
                            dl_mb = int(m.group(2)) / 1_048_576
                            total_mb = parsed_total[0] / 1_048_576
                            parsed_msg[0] = f"Downloading: {dl_mb:.0f}/{total_mb:.0f} MB ({parsed_pct[0]}%)"
                except Exception:
                    pass

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            # ── 디스크 사용량 기반 프로그레스 모니터링 (메인 스레드) ──
            # SteamCMD stdout이 버퍼링되어도 디스크 사용량은 실시간으로 변함.
            _progress(0, "Connecting to Steam...")
            last_msg = ""
            last_pct = -1
            heartbeat_counter = 0
            estimated_total = _KNOWN_APP_SIZES.get(app_id, 0)
            timed_out = False

            while proc.poll() is None:
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(_POLL_INTERVAL)
                heartbeat_counter += 1

                # stdout 파싱 결과가 있으면 우선 사용 (SteamCMD가 flush한 경우)
                if parsed_pct[0] > 0:
                    pct = parsed_pct[0]
                    msg = parsed_msg[0]
                else:
                    # 디스크 사용량 (install_dir + steamcmd 캐시)
                    current_size = _dir_size(install_dir)
                    if steamcmd_cache.exists() and steamcmd_cache.parent != install_dir:
                        current_size += _dir_size(steamcmd_cache)
                    added = current_size - initial_size
                    manifest_progress = _manifest_progress(str(install_dir), app_id, added)
                    if manifest_progress is not None:
                        # appmanifest의 받을 바이트를 총량으로
                        pct, msg = manifest_progress
                    else:
                        # total 결정: stdout 파싱 > 알려진 앱 크기 > 없음
                        pct, msg = _disk_progress(added, parsed_total[0] or estimated_total)
                        if pct is None:
                            pct = max(last_pct, 0)
                # 어림의 근거가 바뀌어도(디스크 → appmanifest) 진행률은 뒤로 가지 않는다
                pct = max(pct, last_pct)

                # 메시지 또는 퍼센티지가 변할 때마다 보고 + 10사이클(20초)마다 heartbeat
                if msg != last_msg or pct != last_pct or heartbeat_counter >= 10:
                    _progress(pct, msg)
                    last_msg = msg
                    last_pct = pct
                    heartbeat_counter = 0

            if timed_out:
                _kill_tree(proc)
                proc.wait(timeout=10)
                _log(f"SteamCMD timed out after {timeout} s for app {app_id}; process killed")
                return {
                    "success": False,
                    "message": f"SteamCMD timed out after {timeout} s",
                    "install_dir": None,
                    "app_id": app_id,
                }

            # 프로세스 종료 — reader 스레드 합류
            reader_thread.join(timeout=10)
            stdout = "".join(stdout_lines)
            returncode = proc.returncode

            if returncode == 0 or "Success! App" in stdout:
                _progress(100, "Server files installed successfully")
                _log(f"SteamCMD install completed for app {app_id}")

                # SteamCMD validate는 파일 검증만 하고 appmanifest의 buildid를
                # 교정하지 않을 수 있음. 설치한 브랜치의 원격 buildid로 manifest를 갱신.
                self._fix_local_buildid(app_id, install_dir, branch=beta or "public")

                return {
                    "success": True,
                    "message": f"Successfully installed app {app_id} to {install_dir}",
                    "install_dir": str(install_dir),
                    "app_id": app_id,
                }

            # Exit code 7: SteamCMD self-updated or transient failure -- retry.
            # Exit code 8: 첫 실행의 'Missing configuration' 등은 다시 돌리면 풀린다 (영구 원인은 빼고)
            permanent = any(reason in stdout for reason in _PERMANENT_FAILURES)
            if (returncode == 7 or (returncode == 8 and not permanent)) and attempt < max_attempts:
                _log(f"SteamCMD exited with code {returncode} (attempt {attempt}) -- retrying...")
                time.sleep(3)
                continue

            # 앞부분은 배너라 원인이 잘린다: 마지막 ERROR! 줄을 보이고, 없으면 끝부분을 보인다
            errors = [line.strip() for line in stdout.splitlines() if line.strip().upper().startswith("ERROR!")]
            detail = errors[-1] if errors else stdout[-2000:]
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
        원격 ``app_info_print``에서 *branch* 의 buildid를 가져와 manifest에 기록한다.

        서버 설치 디렉터리 내부(``<install_dir>/steamapps``)의 manifest만 고친다.
        Steam 클라이언트 라이브러리의 manifest는 Steam 클라이언트 소유이므로 건드리지 않는다.
        """
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
                _log(f"Cannot fix buildid: manifest not found for app {app_id} under {install_dir}")
                return

            content = manifest_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r'"buildid"\s+"(\d+)"', content)
            local_buildid = match.group(1) if match else None

            if local_buildid == remote_buildid:
                return  # 이미 올바름

            # buildid 교체
            new_content = re.sub(
                r'("buildid"\s+")(\d+)(")',
                rf'\g<1>{remote_buildid}\3',
                content,
            )
            # 다 쓴 뒤 바꾼다: 쓰다 끊겨도 manifest가 잘린 채 남지 않게
            tmp_path = manifest_path.with_name(f"{manifest_path.name}.{os.getpid()}.saba-tmp")
            try:
                tmp_path.write_text(new_content, encoding="utf-8")
                os.replace(tmp_path, manifest_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
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
        local_branch = get_local_branch(str(install_dir), app_id)
        remote: Optional[str] = None

        if self.available:
            try:
                raw = self._app_info_print(app_id)
                if raw:
                    remote = parse_remote_buildid(raw, branch=branch)
            except Exception as e:
                _log(f"Failed to query remote buildid for app {app_id}: {e}")

        update_available = False
        if local and remote and local_branch is not None and local_branch != branch:
            # 다른 브랜치로 바꾸면 buildid의 크고 작음과 상관없이 받아야 한다
            update_available = local != remote
        elif local and remote:
            # buildid는 단조 증가하는 숫자다. 단순 != 비교는 사용자가 Steam
            # 클라이언트로 먼저 업데이트해 로컬이 더 최신이 된 경우(steamcmd의
            # app_info 캐시가 낡은 경우)에도 "업데이트 필요"로 오판한다.
            try:
                update_available = int(remote) > int(local)
            except ValueError:
                update_available = local != remote
        elif local is None and remote is not None:
            # No local manifest — consider as needing update (fresh install)
            update_available = True

        return {
            "update_available": update_available,
            "local_branch": local_branch,
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
            # steamcmd 출력은 UTF-8이다 — 로케일(cp949 등) 디코딩은 실패할 수 있다
            result = subprocess.run(
                args,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
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


def resolve_manifest_path(install_dir: str, app_id: int) -> Optional[Path]:
    """Locate ``appmanifest_<appid>.acf`` for *install_dir*.

    Two layouts are supported (checked in order):

    1. **SteamCMD standalone install** (``force_install_dir``)::

           <install_dir>/steamapps/appmanifest_<appid>.acf

    2. **Steam library install** (migrated servers) — the game folder lives
       inside a Steam library at ``<library>/steamapps/common/<Game>`` and the
       manifest is at the *library* level::

           <library>/steamapps/appmanifest_<appid>.acf
           (== <install_dir>/../../appmanifest_<appid>.acf)

    Returns the first existing manifest path, or ``None``.
    """
    install_path = Path(install_dir)
    candidates = [install_path / "steamapps" / f"appmanifest_{app_id}.acf"]

    # Steam 라이브러리 레이아웃 폴백: .../steamapps/common/<Game> 형태인 경우
    # 라이브러리 레벨(steamapps/)의 manifest를 조회한다.
    parts = [p.lower() for p in install_path.parts]
    if len(parts) >= 3 and parts[-2] == "common" and parts[-3] == "steamapps":
        candidates.append(install_path.parent.parent / f"appmanifest_{app_id}.acf")

    for manifest_path in candidates:
        if manifest_path.exists():
            return manifest_path
    return None


def get_local_buildid(install_dir: str, app_id: int) -> Optional[str]:
    """Read the local buildid from the app manifest for *install_dir*.

    See :func:`resolve_manifest_path` for the supported layouts.
    Returns the buildid string, or ``None`` if no manifest can be found
    or parsed.
    """
    manifest_path = resolve_manifest_path(install_dir, app_id)
    if manifest_path is None:
        return None
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        # Simple Valve KeyValues parser — extract "buildid" value
        match = re.search(r'"buildid"\s+"(\d+)"', content)
        if match:
            return match.group(1)
    except Exception:
        return None
    return None


def get_local_branch(install_dir: str, app_id: int) -> Optional[str]:
    """설치된 브랜치를 app manifest의 ``BetaKey`` 에서 읽는다. 없으면 ``"public"``.

    manifest를 찾거나 읽을 수 없으면 ``None``.
    """
    manifest_path = resolve_manifest_path(install_dir, app_id)
    if manifest_path is None:
        return None
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    # MountedConfig(실제로 받은 것)가 UserConfig(요청한 것)보다 정확하다
    for block in ("MountedConfig", "UserConfig"):
        m = re.search(rf'"{block}"\s*\{{([^}}]*)\}}', content)
        if m:
            key = re.search(r'"BetaKey"\s+"([^"]*)"', m.group(1))
            if key:
                return key.group(1) or "public"
    return "public"


def parse_remote_buildid(raw_output: str, *, branch: str = "public") -> Optional[str]:
    """Extract the buildid for *branch* from ``steamcmd +app_info_print`` output.

    The output uses Valve's indented KeyValues format.  We look for::

        branches
          <branch>
            buildid: <number>   OR   "buildid"  "<number>"

    Returns the buildid string, or ``None`` if not found.
    """
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
            m = re.search(r'"buildid"\s+"(\d+)"', stripped)
            if m:
                return m.group(1)
            # Format 2: buildid: 12345678
            m = re.search(r'buildid[:\s]+(\d+)', stripped)
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


def _children_map() -> dict[int, list[int]]:
    """부모 pid → 자식 pid. Linux는 /proc에서 바로 읽고, 없으면(macOS) ps를 쓴다."""
    pairs: list[tuple[int, int]] = []
    if os.path.isdir("/proc"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as f:
                    # comm에 공백·괄호가 들어갈 수 있어 마지막 ')' 뒤에서 읽는다: state ppid ...
                    ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            pairs.append((ppid, int(entry)))
    else:
        try:
            out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                pairs.append((int(parts[1]), int(parts[0])))
    children: dict[int, list[int]] = {}
    for ppid, pid in pairs:
        children.setdefault(ppid, []).append(pid)
    return children


def _descendants(pid: int) -> list[int]:
    """*pid* 아래 모든 자손 pid (POSIX)."""
    children = _children_map()
    found: list[int] = []
    queue = [pid]
    while queue:
        kids = children.get(queue.pop(), [])
        found.extend(kids)
        queue.extend(kids)
    return found


def _kill_tree(proc: subprocess.Popen) -> None:
    """steamcmd와 그 자손을 모두 끝낸다.

    Linux/macOS의 steamcmd.sh는 실제 steamcmd를 자식으로 띄우므로 직계 자식만 죽이면
    손자가 남아 install_dir에 계속 쓴다. 데몬의 프로세스 그룹 종료가 닿도록 새 세션은 만들지 않는다.
    """
    if _SYSTEM == "Windows":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10, creationflags=_creation_flags())
        except (OSError, subprocess.SubprocessError):
            pass
        proc.kill()
        return
    descendants = _descendants(proc.pid)
    proc.kill()
    for pid in descendants:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _download_bytes(url: str, *, timeout: int) -> bytes:
    """*url* 을 메모리로 내려받는다. 진행률은 0~2% 범위로 보고한다.

    SteamCMD 자체 다운로드는 전체 프로비저닝의 극히 일부이므로
    install() 진행률과 혼동하지 않도록 범위를 제한한다.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "saba-chan/1.0"})
    # urlopen의 timeout은 읽기 한 번의 한도라서, 느리게 이어지는 받기도 전체로 timeout 안에 끊는다
    deadline = time.monotonic() + timeout
    with urllib.request.urlopen(req, timeout=min(timeout, _READ_TIMEOUT)) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        chunks: list[bytes] = []
        downloaded = 0
        last_pct = -1
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"SteamCMD download did not finish within {timeout}s")
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if total > 0:
                raw_pct = min(int(downloaded * 100 / total), 100)
                if raw_pct != last_pct:
                    _progress(raw_pct * 2 // 100, f"SteamCMD: {downloaded / 1_048_576:.1f}/{total / 1_048_576:.1f} MB")
                    last_pct = raw_pct
    return b"".join(chunks)


def _safe_member_path(dest: Path, name: str) -> Path:
    """아카이브 항목이 *dest* 밖을 가리키면 ValueError (zip-slip 방지)."""
    target = (dest / name).resolve()
    if target != dest and dest not in target.parents:
        raise ValueError(f"Archive member escapes target directory: {name}")
    return target


def _extract_archive(data: bytes, name: str, dest: Path) -> None:
    """zip 또는 tar.gz 아카이브를 *dest* 에 안전하게 푼다.

    모든 항목 경로를 먼저 검사한다. 하나라도 *dest* 밖을 가리키면 아무것도 풀지 않는다.
    tar의 링크·장치 파일은 거부한다.
    """
    dest = Path(dest).resolve()
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                _safe_member_path(dest, member)
            zf.extractall(dest)
        return
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            _safe_member_path(dest, member.name)
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported archive member type: {member.name}")
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(dest, members=members, **extra)


# ── Plugin runner interface ──────────────────────────────────────
# Called when the Rust daemon executes:
#   python extensions/steamcmd/steamcmd.py <function> < context.json


def install_for_module(
    module_dir: str | Path,
    install_dir: str | Path,
    *,
    beta: Optional[str] = None,
    timeout: Optional[float] = _INSTALL_BUDGET,
) -> dict[str, Any]:
    """모듈 module.toml ``[install]``(``method = "steamcmd"``, ``app_id``, ``anonymous``, ``beta``)대로
    게임 서버를 설치·업데이트한다. 앱 ID를 모듈 코드에 다시 적지 않게 한다 (선언은 module.toml 한 곳).

    SteamCMD가 없으면 받아 온다. 반환은 :meth:`SteamCMD.install` 과 같다.
    ``[install]``에 steamcmd 앱 ID가 없으면 ``ValueError``.
    """
    import tomllib

    raw = (Path(module_dir) / "module.toml").read_bytes()
    section = tomllib.loads(raw.decode("utf-8-sig")).get("install", {})
    app_id = section.get("app_id")
    if section.get("method") != "steamcmd" or not isinstance(app_id, int) or app_id <= 0:
        raise ValueError("module.toml [install] needs method = \"steamcmd\" and a positive app_id")
    steam = SteamCMD()
    steam.ensure_available()
    return steam.install(
        app_id,
        install_dir,
        anonymous=bool(section.get("anonymous", True)),
        beta=beta or section.get("beta"),
        timeout=timeout,
    )


def _plugin_ensure(config: dict) -> dict:
    steam = SteamCMD(config.get("explicit_path"))
    steam.ensure_available(timeout=config.get("timeout", 120))
    return steam.status()


def _plugin_status(config: dict) -> dict:
    steam = SteamCMD(config.get("explicit_path"))
    return steam.status()


def _plugin_check_update(config: dict) -> dict:
    """server.check_update — buildid 비교로 업데이트 여부를 확인한다.

    브랜치 우선순위: config.branch → extension_data.steamcmd_beta → "public".
    """
    steam = SteamCMD(config.get("explicit_path"))
    app_id = config.get("app_id")
    install_dir = config.get("install_dir", "")
    ext_data = config.get("extension_data") or {}
    branch = config.get("branch") or ext_data.get("steamcmd_beta") or "public"

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
    "check_update": _plugin_check_update,
    # 수동 진단용
    "ensure": _plugin_ensure,
    "status": _plugin_status,
}


def _error_result(message: str) -> dict:
    return {"success": False, "error": message, "message": message}


def _run_cli(functions: dict, argv: list[str], stdin) -> int:
    """플러그인 프로토콜 실행: ``<script> <function>`` + stdin JSON → stdout JSON 1개.

    데몬은 0이 아닌 종료 코드를 Err로 처리하고 stdout을 버린다. 따라서 실패도
    ``{"success": false, "error", "message"}`` 로 출력하고 0으로 종료한다.
    traceback은 stderr로 보낸다 (데몬 debug 로그).
    """
    if len(argv) < 2:
        result = _error_result("No function specified")
    elif argv[1] not in functions:
        result = _error_result(f"Unknown function: {argv[1]}")
    else:
        try:
            raw = stdin.read().lstrip("﻿")  # PowerShell BOM 제거
            config = json.loads(raw) if raw.strip() else {}
            result = functions[argv[1]](config)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            result = _error_result(str(e) or type(e).__name__)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli(FUNCTIONS, sys.argv, sys.stdin))
