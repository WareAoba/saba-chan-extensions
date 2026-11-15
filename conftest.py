"""pytest conftest for saba-chan-extensions development environment.

Maps the saba-chan-extensions directory as 'extensions' package so that
imports like `from extensions.steamcmd.steamcmd import SteamCMD` work
without needing the Rust daemon's PYTHONPATH injection.
"""
import importlib.util
import os
import sys
import types

_ext_dir = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_ext_dir)

# 이 저장소 폴더를 'extensions' 패키지로 (런타임에는 데몬이 익스텐션 폴더의 부모를 PYTHONPATH로 준다)
if 'extensions' not in sys.modules:
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


# 플러그인은 불러올 때 SABA_LANG으로 문구 언어를 정한다. 문구를 보는 테스트가 실행한 사람의 환경을 따르지 않게 지운다
# (언어를 보는 테스트는 스스로 정한다)
os.environ.pop("SABA_LANG", None)
