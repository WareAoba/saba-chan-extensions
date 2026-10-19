"""SteamCMD 익스텐션 테스트.

네트워크와 실제 steamcmd 실행 없이 동작한다:
  - offline_steamcmd 픽스처가 포터블 경로를 tmp로 돌리고 다운로드를 차단한다.
  - 설치 흐름은 가짜 Popen으로 검증한다.
"""
import io
import json
import os
import tarfile
import zipfile
from unittest.mock import patch

import pytest

from extensions.steamcmd import SteamCMD
from extensions.steamcmd import steamcmd as steamcmd_mod

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "manifest.json")
_real_portable_dir = steamcmd_mod._portable_dir


@pytest.fixture(autouse=True)
def offline_steamcmd(tmp_path, monkeypatch):
    """시스템 SteamCMD 탐지와 Valve CDN 다운로드를 차단한다."""
    portable = tmp_path / "portable-steamcmd"
    monkeypatch.setattr(steamcmd_mod, "_portable_dir", lambda: portable)
    monkeypatch.setattr(steamcmd_mod, "_common_candidates", lambda: [])
    monkeypatch.setattr(steamcmd_mod.shutil, "which", lambda name: None)

    def _no_network(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(steamcmd_mod.urllib.request, "urlopen", _no_network)
    return portable


def test_package_exports_and_status_shape():
    """패키지 재노출 + status() 구조 (모듈이 in-process로 사용하는 API)."""
    from extensions.steamcmd.steamcmd import SteamCMD as Inner
    assert SteamCMD is Inner
    status = SteamCMD().status()
    assert status["available"] is False
    assert status["path"] is None
    assert "portable_dir" in status
    assert status["auto_bootstrap"] is True


def test_explicit_path_nonexistent():
    """Passing a nonexistent explicit path makes available=False."""
    steam = SteamCMD(explicit_path="/nonexistent/steamcmd")
    assert steam.available is False


def test_manifest_hooks_are_dispatchable():
    """매니페스트 훅은 데몬이 실제로 디스패치하는 이름만 쓰고, FUNCTIONS에 존재해야 한다."""
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["id"] == "steamcmd"
    assert manifest.get("dependencies") is not None
    assert set(manifest["hooks"]) == {"server.check_update"}
    for spec in manifest["hooks"].values():
        assert manifest["python_modules"][spec["module"]] == "steamcmd.py"
        assert callable(steamcmd_mod.FUNCTIONS[spec["function"]])
    assert "install" not in steamcmd_mod.FUNCTIONS
    assert "update" not in steamcmd_mod.FUNCTIONS

def test_get_local_buildid_missing_file():
    """get_local_buildid returns None when manifest doesn't exist."""
    from extensions.steamcmd.steamcmd import get_local_buildid
    result = get_local_buildid("/nonexistent/path", 2394010)
    assert result is None


def test_get_local_buildid_from_manifest(tmp_path):
    """get_local_buildid reads buildid from appmanifest file."""
    from extensions.steamcmd.steamcmd import get_local_buildid
    # SteamCMD stores manifests as steamapps/appmanifest_<appid>.acf
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest_file = steamapps / "appmanifest_2394010.acf"
    manifest_file.write_text('"AppState"\n{\n\t"appid"\t\t"2394010"\n\t"buildid"\t\t"12345678"\n\t"name"\t\t"Palworld Dedicated Server"\n}\n')
    result = get_local_buildid(str(tmp_path), 2394010)
    assert result == "12345678"


def test_get_local_buildid_no_buildid_key(tmp_path):
    """get_local_buildid returns None when buildid key is missing."""
    from extensions.steamcmd.steamcmd import get_local_buildid
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest_file = steamapps / "appmanifest_999.acf"
    manifest_file.write_text('"AppState"\n{\n\t"appid"\t\t"999"\n\t"name"\t\t"TestApp"\n}\n')
    result = get_local_buildid(str(tmp_path), 999)
    assert result is None


def test_get_local_buildid_steam_library_layout(tmp_path):
    """마이그레이션된 Steam 라이브러리 서버 지원: install_dir이
    <library>/steamapps/common/<Game>인 경우 manifest는 install_dir 내부가 아니라
    <library>/steamapps/appmanifest_<appid>.acf에 있다. 이 폴백이 없으면
    마이그레이션 인스턴스는 local buildid가 항상 None → 영구 '업데이트 필요' 오판."""
    from extensions.steamcmd.steamcmd import get_local_buildid
    steamapps = tmp_path / "steamapps"
    game_dir = steamapps / "common" / "PalServer"
    game_dir.mkdir(parents=True)
    manifest_file = steamapps / "appmanifest_2394010.acf"
    manifest_file.write_text('"AppState"\n{\n\t"appid"\t\t"2394010"\n\t"buildid"\t\t"87654321"\n}\n')
    result = get_local_buildid(str(game_dir), 2394010)
    assert result == "87654321"


def test_get_local_buildid_prefers_inner_manifest(tmp_path):
    """install_dir 내부 manifest(SteamCMD 설치)가 라이브러리 폴백보다 우선한다."""
    from extensions.steamcmd.steamcmd import get_local_buildid
    steamapps = tmp_path / "steamapps"
    game_dir = steamapps / "common" / "PalServer"
    inner_steamapps = game_dir / "steamapps"
    inner_steamapps.mkdir(parents=True)
    (inner_steamapps / "appmanifest_2394010.acf").write_text(
        '"AppState"\n{\n\t"buildid"\t\t"11111111"\n}\n')
    (steamapps / "appmanifest_2394010.acf").write_text(
        '"AppState"\n{\n\t"buildid"\t\t"22222222"\n}\n')
    result = get_local_buildid(str(game_dir), 2394010)
    assert result == "11111111"


def test_parse_remote_buildid():
    """parse_remote_buildid extracts buildid from SteamCMD app_info_print output."""
    from extensions.steamcmd.steamcmd import parse_remote_buildid
    # Simulated SteamCMD app_info_print output
    raw_output = '''
AppID : 2394010
 Common
   name: Palworld Dedicated Server
   type: Tool
 Depots
   branches
     public
       buildid: 99887766
       timeupdated: 1709300000
'''
    result = parse_remote_buildid(raw_output, branch="public")
    assert result == "99887766"


def test_parse_remote_buildid_beta_branch():
    """parse_remote_buildid can extract buildid from a beta branch."""
    from extensions.steamcmd.steamcmd import parse_remote_buildid
    raw_output = '''
 Depots
   branches
     public
       buildid: 11111111
     unstable
       buildid: 22222222
       timeupdated: 1709300000
'''
    result = parse_remote_buildid(raw_output, branch="unstable")
    assert result == "22222222"


def test_parse_remote_buildid_missing_branch():
    """parse_remote_buildid returns None when branch not found."""
    from extensions.steamcmd.steamcmd import parse_remote_buildid
    raw_output = '''
 Depots
   branches
     public
       buildid: 11111111
'''
    result = parse_remote_buildid(raw_output, branch="nonexistent")
    assert result is None


def test_check_update_result_structure():
    """_plugin_check_update returns expected dict structure."""
    from extensions.steamcmd.steamcmd import FUNCTIONS
    # This should work without actually running steamcmd (no install_dir)
    result = FUNCTIONS["check_update"]({
        "app_id": 2394010,
        "install_dir": "/nonexistent/dir",
    })
    assert isinstance(result, dict)
    assert "update_available" in result
    assert "local_buildid" in result
    # remote_buildid may be None if steamcmd not available
    assert "remote_buildid" in result
    assert "app_id" in result


# ── 업데이트 시나리오 시뮬레이션 tests ──


def test_simulate_update_available(tmp_path):
    """로컬 buildid를 조작하여 업데이트 상황을 시뮬레이션한다.

    실제 SteamCMD 없이 로컬 buildid != 원격 buildid 상황을 재현:
    - 가짜 appmanifest를 만들어 로컬 buildid를 "00000001"로 설정
    - check_update.remote_buildid를 모킹하여 "99999999"로 설정
    → update_available == True
    """
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD, get_local_buildid

    # 1) 가짜 로컬 appmanifest 생성
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"00000001"\n'
        '\t"name"\t\t"Palworld Dedicated Server"\n'
        '}\n'
    )

    # 로컬 buildid가 제대로 읽히는지 확인
    assert get_local_buildid(str(tmp_path), 2394010) == "00000001"

    # 2) 원격 buildid를 모킹 (SteamCMD 실행 없이)
    fake_remote_output = '''
AppID : 2394010
 Common
   name: Palworld Dedicated Server
 Depots
   branches
     public
       buildid: 99999999
       timeupdated: 1709300000
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote_output):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            result = steam.check_update(
                app_id=2394010,
                install_dir=str(tmp_path),
            )

    assert result["update_available"] is True
    assert result["local_buildid"] == "00000001"
    assert result["remote_buildid"] == "99999999"
    assert result["app_id"] == 2394010


def test_simulate_no_update_needed(tmp_path):
    """로컬과 원격 buildid가 동일할 때 update_available == False."""
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD

    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"12345678"\n'
        '}\n'
    )

    fake_remote_output = '''
 Depots
   branches
     public
       buildid: 12345678
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote_output):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            result = steam.check_update(
                app_id=2394010,
                install_dir=str(tmp_path),
            )

    assert result["update_available"] is False
    assert result["local_buildid"] == "12345678"
    assert result["remote_buildid"] == "12345678"


def test_simulate_plugin_check_update_with_extension_data(tmp_path):
    """실제 daemon 호출 시나리오: extension_data에서 app_id를 가져오는 플러그인 프로토콜 테스트.

    Rust daemon이 보내는 context에는 extension_data.steamcmd_app_id가 있고,
    _plugin_check_update는 config["app_id"]를 기대한다.
    Rust 핸들러가 app_id를 top-level로 펼쳐서 보내야 한다.
    """
    from extensions.steamcmd.steamcmd import FUNCTIONS

    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"00000001"\n'
        '}\n'
    )

    # Rust 핸들러가 보내는 것과 동일한 구조 (fix 이후)
    config = {
        "instance_id": "test-instance-123",
        "instance_name": "Test Palworld",
        "module": "palworld",
        "instance_dir": str(tmp_path),
        "install_dir": str(tmp_path),         # Rust가 top-level로 펼침
        "app_id": 2394010,                    # Rust가 top-level로 펼침
        "extension_data": {
            "install_method_steamcmd": True,
            "steamcmd_app_id": 2394010,
            "steamcmd_anonymous": True,
        },
    }

    result = FUNCTIONS["check_update"](config)
    assert result["local_buildid"] == "00000001"
    assert result["app_id"] == 2394010
    # remote는 SteamCMD 미설치 환경에서 None일 수 있음
    assert "update_available" in result


def test_fix_local_buildid_corrects_manifest(tmp_path):
    """_fix_local_buildid가 appmanifest의 buildid를 원격 값으로 교정한다."""
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD, get_local_buildid

    # 가짜 appmanifest 생성 (잘못된 buildid)
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"00000001"\n'
        '\t"name"\t\t"Palworld Dedicated Server"\n'
        '}\n'
    )

    assert get_local_buildid(str(tmp_path), 2394010) == "00000001"

    # 원격 buildid 모킹
    fake_remote = '''
 Depots
   branches
     public
       buildid: 21879679
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            steam._fix_local_buildid(2394010, str(tmp_path))

    # buildid가 교정되었는지 확인
    assert get_local_buildid(str(tmp_path), 2394010) == "21879679"


def test_fix_local_buildid_skips_when_already_correct(tmp_path):
    """buildid가 이미 올바르면 _fix_local_buildid가 파일을 수정하지 않는다."""
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD

    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    original_content = (
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"21879679"\n'
        '}\n'
    )
    manifest.write_text(original_content)

    fake_remote = '''
 Depots
   branches
     public
       buildid: 21879679
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            steam._fix_local_buildid(2394010, str(tmp_path))

    # 내용이 변경되지 않아야 함
    assert manifest.read_text() == original_content


def test_fix_local_buildid_steam_library_layout(tmp_path):
    """Steam 클라이언트 라이브러리의 appmanifest는 Steam 클라이언트 소유다.

    install_dir이 <library>/steamapps/common/<Game>이어도 _fix_local_buildid는
    라이브러리 레벨 manifest를 다시 쓰지 않는다 (서버 설치 디렉터리 내부만 교정).
    """
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD, get_local_buildid

    library = tmp_path / "SteamLibrary"
    game_dir = library / "steamapps" / "common" / "PalServer"
    game_dir.mkdir(parents=True)
    manifest = library / "steamapps" / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"00000001"\n'
        '}\n'
    )

    fake_remote = '''
 Depots
   branches
     public
       buildid: 21879679
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            steam._fix_local_buildid(2394010, str(game_dir))

    assert get_local_buildid(str(game_dir), 2394010) == "00000001"


def test_check_update_local_newer_than_remote(tmp_path):
    """로컬 buildid가 원격보다 최신이면(예: Steam 클라이언트로 먼저 업데이트,
    steamcmd 캐시가 낡음) 업데이트 필요로 오판하지 않아야 한다."""
    from unittest.mock import patch
    from extensions.steamcmd.steamcmd import SteamCMD

    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(
        '"AppState"\n'
        '{\n'
        '\t"appid"\t\t"2394010"\n'
        '\t"buildid"\t\t"99999999"\n'
        '}\n'
    )

    fake_remote = '''
 Depots
   branches
     public
       buildid: 12345678
'''
    steam = SteamCMD(explicit_path="/fake/steamcmd")
    with patch.object(steam, '_app_info_print', return_value=fake_remote):
        with patch.object(type(steam), 'available', new_callable=lambda: property(lambda self: True)):
            result = steam.check_update(app_id=2394010, install_dir=str(tmp_path))

    assert result["update_available"] is False
    assert result["local_buildid"] == "99999999"
    assert result["remote_buildid"] == "12345678"


def test_resolve_manifest_path_layouts(tmp_path):
    """resolve_manifest_path: standalone 레이아웃 우선, 라이브러리 레이아웃 폴백."""
    from extensions.steamcmd.steamcmd import resolve_manifest_path

    # 아무것도 없으면 None
    assert resolve_manifest_path(str(tmp_path / "nope"), 111) is None

    # standalone: <install_dir>/steamapps/appmanifest_<id>.acf
    standalone = tmp_path / "server"
    (standalone / "steamapps").mkdir(parents=True)
    inner = standalone / "steamapps" / "appmanifest_111.acf"
    inner.write_text('"buildid" "1"')
    assert resolve_manifest_path(str(standalone), 111) == inner

    # library: <library>/steamapps/common/<Game> → <library>/steamapps/appmanifest
    library = tmp_path / "lib"
    game = library / "steamapps" / "common" / "Game"
    game.mkdir(parents=True)
    outer = library / "steamapps" / "appmanifest_222.acf"
    outer.write_text('"buildid" "2"')
    assert resolve_manifest_path(str(game), 222) == outer


def test_check_update_uses_beta_branch_from_extension_data(tmp_path):
    """데몬 context의 extension_data.steamcmd_beta가 원격 buildid 브랜치가 된다."""
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    (steamapps / "appmanifest_380870.acf").write_text('"AppState"\n{\n\t"buildid"\t\t"100"\n}\n')
    raw = """
   branches
     public
       buildid: 100
     unstable
       buildid: 200
"""
    exe = tmp_path / "steamcmd.exe"
    exe.write_text("")
    with patch.object(SteamCMD, "_app_info_print", return_value=raw):
        result = steamcmd_mod.FUNCTIONS["check_update"]({
            "app_id": 380870,
            "install_dir": str(tmp_path),
            "explicit_path": str(exe),
            "extension_data": {"steamcmd_beta": "unstable"},
        })
    assert result["remote_buildid"] == "200"
    assert result["update_available"] is True


def test_check_update_offline_reports_local_only(tmp_path):
    """SteamCMD가 없고 다운로드도 실패하면 로컬 buildid만 보고한다 (네트워크 없음)."""
    result = steamcmd_mod.FUNCTIONS["check_update"]({"app_id": 1, "install_dir": str(tmp_path)})
    assert result["remote_buildid"] is None
    assert result["update_available"] is False


def test_fix_local_buildid_uses_requested_branch(tmp_path):
    """베타 설치는 public이 아니라 해당 브랜치 buildid로 manifest를 교정한다."""
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    manifest = steamapps / "appmanifest_380870.acf"
    manifest.write_text('"AppState"\n{\n\t"buildid"\t\t"1"\n}\n')
    raw = """
   branches
     public
       buildid: 100
     unstable
       buildid: 200
"""
    steam = SteamCMD(explicit_path=str(tmp_path / "steamcmd.exe"))
    with patch.object(steam, "_app_info_print", return_value=raw):
        steam._fix_local_buildid(380870, tmp_path, branch="unstable")
    assert steamcmd_mod.get_local_buildid(str(tmp_path), 380870) == "200"


class _FakeProc:
    """steamcmd 프로세스 대역. finish_after회 poll 후 종료한다 (None이면 종료 안 함)."""

    def __init__(self, output=b"", returncode=0, finish_after=1):
        self.stdout = io.BytesIO(output)
        self._returncode = returncode
        self._polls_left = finish_after
        self.returncode = None
        self.killed = False
        self.pid = 4242424

    def poll(self):
        if self.killed:
            return self.returncode
        if self._polls_left is None:
            return None
        if self._polls_left <= 0:
            self.returncode = self._returncode
            return self.returncode
        self._polls_left -= 1
        return None

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def fake_steamcmd(tmp_path, monkeypatch):
    exe = tmp_path / "steamcmd.exe"
    exe.write_text("")
    monkeypatch.setattr(steamcmd_mod, "_POLL_INTERVAL", 0)
    # 실제 프로세스 트리 종료는 test_timeout_kill_reaches_grandchildren이 본다
    monkeypatch.setattr(steamcmd_mod, "_kill_tree", lambda proc: proc.kill())
    calls = []

    def install_with(proc, **kwargs):
        def fake_popen(args, **popen_kwargs):
            calls.append((args, popen_kwargs))
            return proc
        monkeypatch.setattr(steamcmd_mod.subprocess, "Popen", fake_popen)
        steam = SteamCMD(explicit_path=str(exe))
        with patch.object(SteamCMD, "_fix_local_buildid") as fix:
            result = steam.install(380870, tmp_path / "server", **kwargs)
        return result, fix

    return install_with, calls


def test_install_passes_beta_as_separate_argv_tokens(fake_steamcmd):
    install_with, calls = fake_steamcmd
    proc = _FakeProc(b"Success! App '380870' fully installed.\n")
    result, fix = install_with(proc, beta="unstable", beta_password="pw")
    assert result["success"] is True
    args = calls[0][0]
    i = args.index("+app_update")
    assert args[i:i + 6] == ["+app_update", "380870", "-beta", "unstable", "-betapassword", "pw"]
    assert not any(a.startswith("-beta ") for a in args)
    # 베타 설치의 buildid 교정은 해당 브랜치 기준
    assert fix.call_args.kwargs["branch"] == "unstable"


def test_install_uses_no_window_creation_flags(fake_steamcmd):
    install_with, calls = fake_steamcmd
    install_with(_FakeProc(b"Success! App\n"))
    assert calls[0][1]["creationflags"] == steamcmd_mod._creation_flags()


def test_install_kills_steamcmd_on_timeout(fake_steamcmd):
    install_with, _ = fake_steamcmd
    proc = _FakeProc(finish_after=None)
    result, fix = install_with(proc, timeout=0)
    assert proc.killed is True
    assert result["success"] is False
    assert "timed out" in result["message"]
    fix.assert_not_called()


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="Linux 프로세스 트리(/proc)")
def test_timeout_kill_reaches_grandchildren(tmp_path):
    """steamcmd.sh가 띄운 실제 steamcmd(손자)까지 끝낸다."""
    import subprocess
    import time
    pidfile = tmp_path / "pid"
    proc = subprocess.Popen(["sh", "-c", f"sleep 30 & echo $! > {pidfile}; wait"])
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    grandchild = int(pidfile.read_text())
    steamcmd_mod._kill_tree(proc)
    proc.wait(timeout=5)
    for _ in range(100):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        if open(f"/proc/{grandchild}/stat").read().split()[2] == "Z":
            break
        time.sleep(0.05)
    else:
        pytest.fail("grandchild still running")


def test_app_info_print_decodes_utf8_with_replace(tmp_path, monkeypatch):
    exe = tmp_path / "steamcmd.exe"
    exe.write_text("")
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)

        class R:
            stdout = "ok"
        return R()

    monkeypatch.setattr(steamcmd_mod.subprocess, "run", fake_run)
    assert SteamCMD(explicit_path=str(exe))._app_info_print(1) == "ok"
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"
    assert seen["creationflags"] == steamcmd_mod._creation_flags()


def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _tar_bytes(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("builder,name", [(_zip_bytes, "x.zip"), (_tar_bytes, "x.tar.gz")])
def test_extract_archive_rejects_path_traversal(tmp_path, builder, name):
    data = builder({"ok.txt": b"1", "../evil.txt": b"2"})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError):
        steamcmd_mod._extract_archive(data, name, dest)
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.parametrize("builder,name", [(_zip_bytes, "x.zip"), (_tar_bytes, "x.tar.gz")])
def test_extract_archive_extracts_safe_members(tmp_path, builder, name):
    data = builder({"steamcmd.exe": b"bin", "sub/file.txt": b"x"})
    steamcmd_mod._extract_archive(data, name, tmp_path)
    assert (tmp_path / "steamcmd.exe").read_bytes() == b"bin"
    assert (tmp_path / "sub" / "file.txt").read_bytes() == b"x"


def test_cli_reports_errors_as_json_with_exit_zero(capsys):
    """데몬은 비정상 종료 코드를 Err로 처리하므로 실패도 exit 0 + JSON으로 보고한다."""
    def boom(config):
        raise RuntimeError("kaput")

    code = steamcmd_mod._run_cli({"boom": boom}, ["prog", "boom"], io.StringIO("{}"))
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out == {"success": False, "error": "kaput", "message": "kaput"}

    code = steamcmd_mod._run_cli({}, ["prog", "nope"], io.StringIO(""))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["success"] is False and "nope" in out["error"]


def test_check_update_flags_a_branch_switch_even_to_an_older_build(tmp_path):
    """설치된 브랜치와 대상 브랜치가 다르면 buildid가 더 작아도 업데이트로 본다."""
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    (steamapps / "appmanifest_380870.acf").write_text(
        '"AppState"\n{\n\t"buildid"\t\t"200"\n'
        '\t"MountedConfig"\n\t{\n\t\t"BetaKey"\t\t"unstable"\n\t}\n}\n'
    )
    raw = """
   branches
     public
       buildid: 100
     unstable
       buildid: 200
"""
    exe = tmp_path / "steamcmd.exe"
    exe.write_text("")
    with patch.object(SteamCMD, "_app_info_print", return_value=raw):
        result = steamcmd_mod.FUNCTIONS["check_update"]({
            "app_id": 380870, "install_dir": str(tmp_path), "explicit_path": str(exe),
        })
    assert result["local_branch"] == "unstable"
    assert result["update_available"] is True


def test_portable_dir_follows_the_daemon_extension_data_root(tmp_path, monkeypatch):
    """데몬이 준 뿌리(SABA_EXTENSION_DATA_ROOT) 아래에 받는다.
    격리된 모듈은 공용 폴더에 쓸 수 없어 설치가 막혔다 (팰월드: 스팀 폴더 액세스 거부)."""
    monkeypatch.setenv("SABA_EXTENSION_DATA_ROOT", str(tmp_path / "root"))
    assert _real_portable_dir() == tmp_path / "root" / "steamcmd"
    monkeypatch.delenv("SABA_EXTENSION_DATA_ROOT")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert _real_portable_dir().name == "steamcmd"
