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
import types

if 'extensions' not in sys.modules:
    # Create a namespace package for 'extensions'
    extensions_pkg = types.ModuleType('extensions')
    extensions_pkg.__path__ = [_ext_dir]
    extensions_pkg.__package__ = 'extensions'
    sys.modules['extensions'] = extensions_pkg
