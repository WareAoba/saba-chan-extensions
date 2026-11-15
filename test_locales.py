"""모든 익스텐션의 locales: 언어 파일마다 같은 키와 같은 자리표시자 (사용자 문구는 10개 언어)."""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
LANGUAGES = ["ko", "en", "ja", "zh-CN", "zh-TW", "es", "pt-BR", "ru", "de", "fr"]


def _flat(tree, prefix=""):
    out = {}
    for key, value in tree.items():
        out.update(_flat(value, f"{prefix}{key}.") if isinstance(value, dict) else {prefix + key: value})
    return out


def _holders(text):
    return sorted(re.findall(r"\{\{(\w+)\}\}", text))


@pytest.mark.parametrize("locales", sorted(ROOT.glob("*/locales")), ids=lambda p: p.parent.name)
def test_every_language_has_the_same_lines_and_placeholders(locales):
    lines = {lang: _flat(json.loads((locales / f"{lang}.json").read_text(encoding="utf-8"))) for lang in LANGUAGES}
    base = lines["ko"]
    assert base
    for lang, found in lines.items():
        assert set(found) == set(base), lang
        for key, text in found.items():
            assert _holders(text) == _holders(base[key]), (lang, key)
