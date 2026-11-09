"""pytest conftest for saba-chan-extensions development environment.

Maps the saba-chan-extensions directory as 'extensions' package so that
imports like `from extensions.steamcmd.steamcmd import SteamCMD` work
without needing the Rust daemon's PYTHONPATH injection.
"""
import sys
import os

# saba-chan-extensions/ 디렉토리의 부모를 sys.path에 추가
# → 'saba-chan-extensions' 디렉토리가 있지만 'extensions'가 없으므로
#   모듈 alias를 설정합니다.
_ext_dir = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_ext_dir)

# parent에 'extensions' 심볼이 없으면 sys.modules 트릭 사용
if _parent not in sys.path:
    sys.path.insert(0, _parent)

# 'extensions' 패키지로 매핑: saba-chan-extensions → extensions
import importlib
import importlib.util
import types

if 'extensions' not in sys.modules:
    # Create a namespace package for 'extensions'
    extensions_pkg = types.ModuleType('extensions')
    extensions_pkg.__path__ = [_ext_dir]
    extensions_pkg.__package__ = 'extensions'
    sys.modules['extensions'] = extensions_pkg

# 공용 런타임(daemon_rcon.py): 런타임에는 데몬이 PYTHONPATH로 넣는다. 테스트는 SABA_RUNTIME_DIR → 형제 레포
# ../saba-chan/modules 순서로 같은 실제 파일을 찾는다 (saba-chan-modules conftest와 같은 규칙)
if importlib.util.find_spec('daemon_rcon') is None:
    for _runtime in (os.environ.get('SABA_RUNTIME_DIR'), os.path.join(_parent, 'saba-chan', 'modules')):
        if _runtime and os.path.isfile(os.path.join(_runtime, 'daemon_rcon.py')):
            sys.path.insert(0, _runtime)
            break
