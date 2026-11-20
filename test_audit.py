"""모든 익스텐션의 코드 검사 (모듈 저장소 적합성 시험의 `test_sdk_minimum_covers_imports`·`test_code_uses_only_declared_permissions`와 같은 관문).
검사기는 데몬이 공용 파일로 배포하는 `saba_audit.py`다. 익스텐션은 `min_app_version`이 SDK 최소 버전 선언이다."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent


def _audit_script():
    for runtime in (os.environ.get("SABA_RUNTIME_DIR"), ROOT.parent / "saba-chan" / "modules"):
        if runtime and (pathlib.Path(runtime) / "saba_audit.py").is_file():
            return pathlib.Path(runtime) / "saba_audit.py"
    pytest.skip("saba_audit.py 없음 (SABA_RUNTIME_DIR 또는 ../saba-chan/modules)")


@pytest.fixture(params=sorted(p.parent for p in ROOT.glob("*/manifest.json")), ids=lambda p: p.name)
def extension(request):
    return request.param


@pytest.fixture
def findings(extension):
    out = subprocess.run([sys.executable, "-I", str(_audit_script()), str(extension)], capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    result = json.loads(out.stdout)
    assert result["success"], result
    return result["findings"]


def test_min_app_version_covers_sdk_imports(findings):
    missing = [f"{f['file']}:{f['line']} {f['detail']}" for f in findings if f["permission"] == "sdk_version"]
    assert not missing, "min_app_version이 쓴 SDK 이름보다 낮다:\n" + "\n".join(missing)


def test_code_uses_only_declared_permissions(extension, findings):
    """익스텐션 코드가 쓰는 능력(네트워크, 프로세스 실행 등)은 manifest `permissions`에 선언한다"""
    declared = json.loads((extension / "manifest.json").read_text(encoding="utf-8-sig")).get("permissions", {})
    missing = [f"{f['permission']} {f['file']}:{f['line']} {f['detail']}"
               for f in findings if f["permission"] != "sdk_version" and declared.get(f["permission"]) is not True]
    assert not missing, "manifest permissions에 선언하지 않은 능력을 쓴다:\n" + "\n".join(missing)
