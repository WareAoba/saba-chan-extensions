"""Docker extension — 계약 테스트 및 순수 함수 단위 테스트.

실제 Docker 데몬 없이 실행 가능한 부분만 다룬다:
  1. manifest.json 스키마/훅 계약 (훅 모듈/함수가 실제 존재하는지)
  2. 컨테이너 이름 규칙
  3. `docker compose ps --format json` 파서 (v2.0~v2.16 array, v2.17+ JSON-lines)
  4. `_check_log_for_fatal` fatal 패턴 감지
  5. `_win_to_wsl_path` 경로 변환
  6. `_compose_cmd` / `_docker_cli` 빌더 모드 전환
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import types
from pathlib import Path

import pytest


# ── 패키지 alias 확보 ─────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXT_DIR = os.path.dirname(_THIS_DIR)

# conftest.py가 'extensions' alias를 등록하지만, 'extensions.docker'는
# namespace package로 자동 잡혀야 한다. 보험으로 직접 주입.
if 'extensions' not in sys.modules:
    pkg = types.ModuleType('extensions')
    pkg.__path__ = [_EXT_DIR]
    sys.modules['extensions'] = pkg
if 'extensions.docker' not in sys.modules:
    subpkg = types.ModuleType('extensions.docker')
    subpkg.__path__ = [_THIS_DIR]
    sys.modules['extensions.docker'] = subpkg


# compose_manager / docker_engine 모듈을 file-path 로드 (`docker` 최상위 이름 회피 —
# 표준 라이브러리의 `docker`/PyPI `docker` 패키지와 충돌 가능).
def _load_module(name: str, file_name: str):
    full = f"extensions.docker.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_THIS_DIR, file_name),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


compose_manager = _load_module("compose_manager", "compose_manager.py")
docker_engine = _load_module("docker_engine", "docker_engine.py")
MANIFEST_PATH = os.path.join(_THIS_DIR, "manifest.json")


# ═══════════════════════════════════════════════════════════════
# 1. manifest.json 계약
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def test_manifest_has_required_top_level_fields(manifest):
    for key in ("id", "name", "version", "hooks", "python_modules"):
        assert key in manifest, f"manifest missing '{key}'"
    assert manifest["id"] == "docker"


def test_manifest_python_modules_point_to_existing_files(manifest):
    for mod, file_name in manifest["python_modules"].items():
        path = os.path.join(_THIS_DIR, file_name)
        assert os.path.exists(path), f"python_modules['{mod}'] → missing file: {file_name}"


def test_manifest_hooks_reference_real_modules_and_functions(manifest):
    """모든 훅의 module/function이 실제 코드의 디스패치 맵에 존재하는지 검증.

    데몬은 `python <module_path> <function_name>` 서브프로세스로 훅을 호출하고,
    각 모듈의 `__main__` 블록은 `FUNCTIONS` 또는 `_FUNCTIONS` 딕셔너리로 라우팅한다.
    따라서 계약은 '<function_name>이 해당 dict의 key로 존재하는가'이다.

    이 테스트가 실패하면 런타임에 "Unknown function: <name>" 에러를 뱉는다.
    """
    loaded = {
        "compose_manager": compose_manager,
        "docker_engine": docker_engine,
    }
    for hook_name, spec in manifest["hooks"].items():
        mod_name = spec["module"]
        fn_name = spec["function"]
        assert mod_name in loaded, f"hook '{hook_name}' → unknown module '{mod_name}'"
        mod = loaded[mod_name]
        dispatch = getattr(mod, "FUNCTIONS", None) or getattr(mod, "_FUNCTIONS", None)
        assert dispatch is not None, (
            f"hook '{hook_name}' → module '{mod_name}' has no FUNCTIONS/_FUNCTIONS dispatch table"
        )
        assert fn_name in dispatch, (
            f"hook '{hook_name}' → '{fn_name}' not in {mod_name}.FUNCTIONS "
            f"(available: {sorted(dispatch.keys())})"
        )
        assert callable(dispatch[fn_name]), (
            f"hook '{hook_name}' → {mod_name}.FUNCTIONS['{fn_name}'] is not callable"
        )


def test_manifest_hook_conditions_reference_known_fields(manifest):
    """condition 문자열이 instance.ext_data.docker_enabled 또는 null만 허용."""
    allowed_prefixes = ("instance.ext_data.",)
    for hook_name, spec in manifest["hooks"].items():
        cond = spec.get("condition")
        if cond is None:
            continue
        assert any(cond.startswith(p) for p in allowed_prefixes), (
            f"hook '{hook_name}' condition '{cond}' uses unknown scope"
        )


def test_manifest_instance_fields_declare_docker_enabled(manifest):
    # 훅 다수가 instance.ext_data.docker_enabled에 의존하므로 필드 선언 필수.
    fields = manifest.get("instance_fields", {})
    assert "docker_enabled" in fields
    assert fields["docker_enabled"]["type"] == "boolean"


def test_manifest_gui_slots_non_empty(manifest):
    # GUI 통합이 최소한 한 개 슬롯을 노출해야 한다.
    gui = manifest.get("gui", {})
    slots = gui.get("slots", {})
    assert len(slots) > 0, "manifest.gui.slots must declare at least one slot"


# ═══════════════════════════════════════════════════════════════
# 2. 컨테이너 이름 규칙
# ═══════════════════════════════════════════════════════════════

def test_container_name_rule():
    assert compose_manager._container_name("minecraft", "abcdef12345678") == "saba-minecraft-abcdef12"


def test_container_name_truncates_to_8_chars():
    # instance_id가 UUID 등 긴 값이어도 앞 8자만 사용.
    name = compose_manager._container_name("palworld", "a1b2c3d4e5f6g7h8")
    assert name == "saba-palworld-a1b2c3d4"


def test_container_name_short_instance_id_kept_as_is():
    assert compose_manager._container_name("zomboid", "abc") == "saba-zomboid-abc"


def test_instance_container_name_from_config_with_module_and_id():
    cfg = {"module": "minecraft", "instance_id": "12345678abcdef"}
    assert compose_manager._instance_container_name(cfg) == "saba-minecraft-12345678"


def test_instance_container_name_falls_back_to_instance_dir_basename():
    cfg = {"instance_dir": "/srv/saba/instances/my-server"}
    assert compose_manager._instance_container_name(cfg) == "my-server"


def test_instance_container_name_handles_trailing_separator():
    cfg = {"instance_dir": "C:/saba/instances/mc1/"}
    assert compose_manager._instance_container_name(cfg) == "mc1"


def test_instance_container_name_accepts_legacy_module_name_key():
    cfg = {"module_name": "zomboid", "instance_id": "deadbeef123"}
    assert compose_manager._instance_container_name(cfg) == "saba-zomboid-deadbeef"


# ═══════════════════════════════════════════════════════════════
# 3. docker compose ps 출력 파서
# ═══════════════════════════════════════════════════════════════

def test_parse_compose_ps_empty_input():
    assert compose_manager._parse_compose_ps("") == []
    assert compose_manager._parse_compose_ps("   \n  ") == []


def test_parse_compose_ps_json_array_v2_0():
    payload = json.dumps([
        {"Name": "saba-mc-aaa", "State": "running"},
        {"Name": "saba-mc-bbb", "State": "exited"},
    ])
    result = compose_manager._parse_compose_ps(payload)
    assert len(result) == 2
    assert result[0]["Name"] == "saba-mc-aaa"


def test_parse_compose_ps_json_lines_v2_17():
    payload = (
        '{"Name": "saba-mc-aaa", "State": "running"}\n'
        '{"Name": "saba-mc-bbb", "State": "exited"}\n'
    )
    result = compose_manager._parse_compose_ps(payload)
    assert len(result) == 2
    assert result[1]["State"] == "exited"


def test_parse_compose_ps_single_object():
    payload = '{"Name": "solo", "State": "running"}'
    result = compose_manager._parse_compose_ps(payload)
    assert result == [{"Name": "solo", "State": "running"}]


def test_parse_compose_ps_ignores_malformed_lines():
    payload = (
        '{"Name": "ok1", "State": "running"}\n'
        'NOT-JSON GARBAGE\n'
        '{"Name": "ok2", "State": "exited"}\n'
    )
    result = compose_manager._parse_compose_ps(payload)
    names = [c["Name"] for c in result]
    assert names == ["ok1", "ok2"]


def test_parse_compose_ps_discards_non_dict_items():
    payload = json.dumps(["string", 42, {"Name": "keep"}])
    result = compose_manager._parse_compose_ps(payload)
    assert result == [{"Name": "keep"}]


# ═══════════════════════════════════════════════════════════════
# 4. fatal 로그 감지
# ═══════════════════════════════════════════════════════════════

def test_check_log_for_fatal_detects_failed_to_start():
    log = (
        "time=... starting daemon\n"
        "time=... failed to start daemon: iptables not found\n"
    )
    result = docker_engine._check_log_for_fatal(log)
    assert result is not None
    assert "iptables" in result


def test_check_log_for_fatal_returns_none_for_clean_log():
    log = "line1\nline2\nready\n"
    assert docker_engine._check_log_for_fatal(log) is None


def test_check_log_for_fatal_only_scans_tail():
    # 이전 실행에서 실패 메시지가 있어도, 최근 15줄 내에 없으면 무시.
    head = "failed to start daemon: old error\n"
    tail = "\n".join(f"healthy {i}" for i in range(30))
    log = head + tail
    assert docker_engine._check_log_for_fatal(log) is None


# ═══════════════════════════════════════════════════════════════
# 5. Windows → WSL 경로 변환
# ═══════════════════════════════════════════════════════════════

def test_win_to_wsl_path_c_drive():
    p = Path("C:/Users/test/docker")
    got = docker_engine._win_to_wsl_path(p)
    assert got.startswith("/mnt/c/")
    assert got.lower().endswith("/users/test/docker")


def test_win_to_wsl_path_preserves_case_of_drive_letter_lowercase():
    p = Path("D:/foo")
    got = docker_engine._win_to_wsl_path(p)
    # 드라이브 문자는 반드시 소문자.
    assert got[:7] == "/mnt/d/"


# ═══════════════════════════════════════════════════════════════
# 6. CLI 빌더: WSL2 vs 네이티브 모드
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def wsl2_mode_toggle():
    """_wsl2_mode 전역을 테스트 내에서만 오버라이드."""
    original = compose_manager._wsl2_mode
    yield compose_manager._set_wsl2_mode
    compose_manager._set_wsl2_mode(original)


def test_docker_cli_wsl2_mode(wsl2_mode_toggle):
    wsl2_mode_toggle(True)
    cli = compose_manager._docker_cli()
    assert cli[0] == "wsl"
    assert "-u" in cli and "root" in cli
    assert cli[-1].endswith("/docker")


def test_docker_cli_native_mode(wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    cli = compose_manager._docker_cli()
    assert cli == ["docker"]


def test_compose_cmd_wsl2_uses_relative_compose_file(wsl2_mode_toggle):
    wsl2_mode_toggle(True)
    cmd = compose_manager._compose_cmd("/opt/instances/mc1")
    # WSL2 모드: -f 뒤에 절대 host 경로 대신 relative file name
    assert "-f" in cmd
    f_idx = cmd.index("-f")
    assert cmd[f_idx + 1] == "docker-compose.yml"


def test_compose_cmd_native_uses_absolute_compose_file(wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    cmd = compose_manager._compose_cmd("/opt/instances/mc1")
    # 네이티브 모드: -f 뒤에 instance_dir + 파일명 join 결과
    assert "-f" in cmd
    f_idx = cmd.index("-f")
    assert cmd[f_idx + 1].endswith("docker-compose.yml")
    # 경로 구분자가 혼재되지 않도록 os.path.join 결과여야 한다.
    expected = os.path.join("/opt/instances/mc1", "docker-compose.yml")
    assert cmd[f_idx + 1] == expected


# ═══════════════════════════════════════════════════════════════
# 7. 훅 계약 — 데몬이 실제로 디스패치하는 훅만 선언
# ═══════════════════════════════════════════════════════════════

# saba-chan/src 에서 dispatch_hook*로 호출되는 훅 이름
DAEMON_DISPATCHED_HOOKS = {
    "daemon.startup", "daemon.shutdown", "server.pre_start", "server.post_stop",
    "server.status", "server.pre_delete", "server.settings_changed",
    "server.check_update", "server.list_enrich", "server.post_create",
}


def test_manifest_declares_only_dispatched_hooks(manifest):
    assert set(manifest["hooks"]) <= DAEMON_DISPATCHED_HOOKS
    assert manifest["hooks"]["daemon.startup"]["function"] == "startup"


def test_undispatched_functions_removed():
    for name in ("pre_create", "container_stats", "get_logs"):
        assert name not in compose_manager._FUNCTIONS
    for name in ("_get_wsl_total_memory_mb", "_parse_memory_to_mb", "_ensure_docker_daemon_legacy"):
        assert not hasattr(compose_manager, name)
    for name in ("_plugin_start_daemon", "_plugin_stop_daemon", "_plugin_status", "_plugin_info"):
        assert not hasattr(docker_engine, name)
    assert not hasattr(docker_engine.DockerEngine, "_try_spawn_dockerd_elevated")


def test_compose_manager_reuses_docker_engine_module():
    """compose_manager는 같은 docker_engine 모듈 객체를 쓴다 (import 경로 하나)."""
    assert compose_manager.docker_engine is docker_engine


# ═══════════════════════════════════════════════════════════════
# 8. 템플릿 치환 / compose 생성
# ═══════════════════════════════════════════════════════════════

ZOMBOID_DOCKER = {
    "image": "saba/zomboid:latest",
    "ports": ["{port}:{port}/udp", "{direct_port}:{direct_port}/udp", "{rcon_port}:{rcon_port}/tcp"],
    "volumes": ["./server:/server"],
    "environment": {"PORT": "{port}"},
}


def test_resolve_template_direct_port_defaults_to_port_plus_one():
    assert compose_manager._resolve_template("{direct_port}", {"port": 16261}) == "16262"


def test_resolve_template_direct_port_from_module_settings():
    ctx = {"port": 16261, "module_settings": {"direct_port": 17000}}
    assert compose_manager._resolve_template("{direct_port}/udp", ctx) == "17000/udp"


def test_resolve_template_unresolved_placeholder_raises():
    with pytest.raises(ValueError, match="direct_port"):
        compose_manager._resolve_template("{direct_port}", {})


def test_resolve_template_leaves_shell_variables():
    assert compose_manager._resolve_template("echo ${HOME} {port}", {"port": 1}) == "echo ${HOME} 1"


def test_generate_compose_yaml_resolves_all_ports(wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    instance = {"id": "abcdef1234", "name": "pz", "module_name": "zomboid", "port": 16261, "rcon_port": 27015}
    yaml = compose_manager._generate_compose_yaml(ZOMBOID_DOCKER, instance)
    assert "{" not in yaml
    assert '- "16262:16262/udp"' in yaml
    assert '- "27015:27015/tcp"' in yaml
    assert "container_name: saba-zomboid-abcdef12" in yaml
    assert 'PORT: "16261"' in yaml


def test_regenerate_compose_preserves_provisioned_java_version(tmp_path, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    docker_cfg = {"image": "eclipse-temurin:{java_version}-jre"}
    instance = {"id": "abcdef1234", "name": "mc", "module_name": "minecraft", "port": 25565}
    yaml = compose_manager._generate_compose_yaml(docker_cfg, instance, extra_ctx={"java_version": "17"})
    (tmp_path / "docker-compose.yml").write_text(yaml, encoding="utf-8")

    result = compose_manager.regenerate_compose({
        "instance_dir": str(tmp_path),
        "instance": instance,
        "module_extensions": {"docker": docker_cfg},
    })
    assert result["success"] is True
    assert "image: eclipse-temurin:17-jre" in (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")


def test_regenerate_compose_reports_unresolved_placeholder(tmp_path, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    result = compose_manager.regenerate_compose({
        "instance_dir": str(tmp_path),
        "instance": {"id": "x", "module_name": "m"},
        "module_extensions": {"docker": {"image": "img", "ports": ["{direct_port}:1"]}},
    })
    assert result["success"] is False
    assert "direct_port" in result["error"]
    assert not (tmp_path / "docker-compose.yml").exists()


# ═══════════════════════════════════════════════════════════════
# 9. WSL2 모드 — ensure 결과를 따른다
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def portable_dir(tmp_path, monkeypatch):
    path = tmp_path / "portable-docker"
    monkeypatch.setattr(docker_engine, "_portable_dir", lambda: path)
    return path


def test_wsl2_mode_follows_saved_engine_state(portable_dir, wsl2_mode_toggle):
    wsl2_mode_toggle(None)  # 미결정 → 상태 파일에서 읽는다
    docker_engine.save_engine_state({"wsl_mode": False})
    assert compose_manager._is_wsl2_mode() is False
    wsl2_mode_toggle(None)
    docker_engine.save_engine_state({"wsl_mode": True})
    assert compose_manager._is_wsl2_mode() is True


def test_wsl2_mode_without_state_uses_platform_default(portable_dir, wsl2_mode_toggle):
    wsl2_mode_toggle(None)
    assert compose_manager._is_wsl2_mode() is (docker_engine._SYSTEM == "Windows")


def test_ensure_saves_wsl_mode_from_result(portable_dir, monkeypatch):
    monkeypatch.setattr(docker_engine, "_ensure", lambda config: {"success": True, "daemon_ready": True, "wsl_mode": False})
    docker_engine.ensure({})
    assert docker_engine.load_engine_state() == {"wsl_mode": False}


def test_ensure_docker_daemon_honors_ensure_wsl_mode(monkeypatch, wsl2_mode_toggle):
    wsl2_mode_toggle(True)
    monkeypatch.setattr(compose_manager, "_docker_daemon_running", lambda: False)
    monkeypatch.setattr(docker_engine, "ensure", lambda config: {"success": True, "daemon_ready": True, "wsl_mode": False})
    assert compose_manager._ensure_docker_daemon() is None
    assert compose_manager._is_wsl2_mode() is False


def test_ensure_docker_daemon_reports_failure(monkeypatch, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    monkeypatch.setattr(compose_manager, "_docker_daemon_running", lambda: False)
    monkeypatch.setattr(docker_engine, "ensure", lambda config: {"success": False, "daemon_ready": False, "message": "no wsl"})
    err = compose_manager._ensure_docker_daemon()
    assert err["handled"] is True and err["success"] is False
    assert "no wsl" in err["error"]


# ═══════════════════════════════════════════════════════════════
# 10. 네이티브(Linux) 모드 — 포터블 바이너리 하나의 디렉터리
# ═══════════════════════════════════════════════════════════════

def test_native_cli_prefers_portable_binaries(portable_dir, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    portable_dir.mkdir(parents=True)
    (portable_dir / "docker").write_text("")
    (portable_dir / "docker-compose").write_text("")
    assert compose_manager._docker_cli() == [str(portable_dir / "docker")]
    assert compose_manager._compose_cli() == [str(portable_dir / "docker-compose")]


def test_native_cli_falls_back_to_system_docker(portable_dir, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    assert compose_manager._docker_cli() == ["docker"]
    assert compose_manager._compose_cli() == ["docker", "compose"]


# ═══════════════════════════════════════════════════════════════
# 11. 훅 동작
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def recorded_cmds(monkeypatch):
    calls = []

    def fake_run_cmd(cmd, cwd=None, timeout=120):
        calls.append({"cmd": cmd, "cwd": cwd})
        return True, "", ""

    monkeypatch.setattr(compose_manager, "_run_cmd", fake_run_cmd)
    return calls


def test_cleanup_uses_instance_dir_from_context(tmp_path, recorded_cmds, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    result = compose_manager.cleanup({"instance_id": "id1", "instance_dir": str(tmp_path)})
    assert result["handled"] is True and result["success"] is True
    assert recorded_cmds[0]["cwd"] == str(tmp_path)
    assert recorded_cmds[0]["cmd"][-1] == "down"


def test_cleanup_derives_instance_dir_from_instance_id(tmp_path, monkeypatch, recorded_cmds, wsl2_mode_toggle):
    """현재 데몬의 server.pre_delete context에는 instance_dir이 없다 → instance_id로 찾는다."""
    wsl2_mode_toggle(False)
    monkeypatch.setenv("SABA_INSTANCES_PATH", str(tmp_path))
    inst_dir = tmp_path / "id1"
    inst_dir.mkdir()
    (inst_dir / "docker-compose.yml").write_text("services: {}\n")
    result = compose_manager.cleanup({"instance_id": "id1", "module": "minecraft"})
    assert result["success"] is True
    assert recorded_cmds[0]["cwd"] == str(inst_dir)


def test_cleanup_rejects_path_like_instance_id(tmp_path, monkeypatch, recorded_cmds):
    monkeypatch.setenv("SABA_INSTANCES_PATH", str(tmp_path))
    result = compose_manager.cleanup({"instance_id": "../evil"})
    assert result["handled"] is False
    assert recorded_cmds == []


def test_cleanup_without_compose_file_is_noop(tmp_path, recorded_cmds):
    result = compose_manager.cleanup({"instance_id": "id1", "instance_dir": str(tmp_path)})
    assert result["success"] is True
    assert recorded_cmds == []


def test_status_and_enrich_share_container_lookup(tmp_path, monkeypatch, wsl2_mode_toggle):
    wsl2_mode_toggle(False)
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    ps = json.dumps([{"Name": "saba-mc-1", "State": "running"}])

    def fake_run_cmd(cmd, cwd=None, timeout=120):
        if "ps" in cmd:
            return True, ps, ""
        if "top" in cmd:
            return True, "UID PID CMD\nroot 1 java -jar server.jar\n", ""
        if "stats" in cmd:
            return True, "803MiB / 16GiB@@5.00%@@12.50%\n", ""
        return True, "", ""

    monkeypatch.setattr(compose_manager, "_run_cmd", fake_run_cmd)
    cfg = {"instance_dir": str(tmp_path), "process_patterns": ["server.jar"],
           "extension_data": {"docker_enabled": True}}
    status = compose_manager.status(cfg)
    assert status["status"] == "running" and status["container_name"] == "saba-mc-1"
    enriched = compose_manager.enrich_server_info(cfg)
    assert enriched["status"] == "running"
    assert enriched["memory_usage"] == "803MiB"
    assert enriched["cpu_percent"] == 12.5


def test_run_cmd_hides_console_window(monkeypatch):
    seen = {}

    class R:
        returncode = 0
        stdout = b"ok"
        stderr = b""

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return R()

    monkeypatch.setattr(compose_manager.subprocess, "run", fake_run)
    assert compose_manager._run_cmd(["docker", "info"]) == (True, "ok", "")
    assert seen["creationflags"] == docker_engine._creation_flags()


# ═══════════════════════════════════════════════════════════════
# 12. daemon.startup — 도커 인스턴스가 없으면 무거운 작업 없음
# ═══════════════════════════════════════════════════════════════

def _write_instance(root, inst_id, ext_data):
    d = root / inst_id
    d.mkdir(parents=True)
    (d / "instance.json").write_text(json.dumps({"id": inst_id, "extension_data": ext_data}), encoding="utf-8")


def test_startup_skips_engine_without_docker_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("SABA_INSTANCES_PATH", str(tmp_path))
    _write_instance(tmp_path, "a", {"docker_enabled": False})
    monkeypatch.setattr(docker_engine, "ensure", lambda config: pytest.fail("ensure must not run"))
    result = docker_engine.startup({})
    assert result["success"] is True


def test_startup_checks_engine_without_download_when_docker_used(tmp_path, monkeypatch):
    monkeypatch.setenv("SABA_INSTANCES_PATH", str(tmp_path))
    _write_instance(tmp_path, "a", {"docker_enabled": True})
    seen = {}
    monkeypatch.setattr(docker_engine, "ensure", lambda config: seen.update(config) or {"success": True})
    docker_engine.startup({})
    assert seen["allow_download"] is False


# ═══════════════════════════════════════════════════════════════
# 13. tar 추출 가드 / CLI 오류 형식
# ═══════════════════════════════════════════════════════════════

def _make_tgz(path, members):
    import io
    import tarfile
    with tarfile.open(path, "w:gz") as tf:
        for name, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tf.addfile(info)
            else:
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))


def test_extract_engine_tar_strips_prefix(tmp_path):
    archive = tmp_path / "docker.tgz"
    _make_tgz(archive, [("docker/dockerd", "file"), ("docker/docker", "file"), ("other/x", "file")])
    dest = tmp_path / "out"
    dest.mkdir()
    docker_engine._extract_engine_tar(archive, dest)
    assert (dest / "dockerd").exists() and (dest / "docker").exists()
    assert not (dest / "other").exists()


@pytest.mark.parametrize("member", [("docker/../../evil", "file"), ("docker/link", "symlink")])
def test_extract_engine_tar_rejects_unsafe_members(tmp_path, member):
    archive = tmp_path / "docker.tgz"
    _make_tgz(archive, [member])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError):
        docker_engine._extract_engine_tar(archive, dest)
    assert not (tmp_path / "evil").exists()


def test_compose_cli_errors_are_json_handled_exit_zero(capsys, monkeypatch):
    """KeyError 등 예외도 traceback 대신 JSON 1개로 보고한다 (데몬은 exit≠0을 Err로 처리)."""
    import io
    monkeypatch.setattr(compose_manager, "_ensure_docker_daemon", lambda: None)
    code = compose_manager.main(["compose_manager.py", "start"], io.StringIO("{}"))
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["success"] is False and out["handled"] is True
    assert "instance_dir" in out["error"]


def test_compose_cli_list_enrich_errors_are_not_handled(capsys, monkeypatch):
    import io

    def boom(config):
        raise RuntimeError("x")

    monkeypatch.setitem(compose_manager._FUNCTIONS, "enrich_server_info", boom)
    compose_manager.main(["compose_manager.py", "enrich_server_info"], io.StringIO("{}"))
    out = json.loads(capsys.readouterr().out)
    assert out["handled"] is False
