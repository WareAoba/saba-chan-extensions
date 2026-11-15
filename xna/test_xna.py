"""XNA 익스텐션 테스트 (네트워크 없이)."""
import os

import pytest

from extensions.xna import xna as xna_mod


@pytest.mark.parametrize("lang, expected", [
    ("ko", "XNA 내려받기 실패: Connection refused"),
    (None, "XNA download failed: Connection refused"),
])
def test_install_failure_is_in_the_app_language(tmp_path, monkeypatch, lang, expected):
    from i18n import I18n
    if lang:
        monkeypatch.setenv("SABA_LANG", lang)
    else:
        monkeypatch.delenv("SABA_LANG", raising=False)
    monkeypatch.setattr(xna_mod, "i18n", I18n(os.path.dirname(xna_mod.__file__)))
    monkeypatch.setenv("SABA_EXTENSION_DATA_ROOT", str(tmp_path / "data"))

    def refused(*args, **kwargs):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(xna_mod, "download", refused)
    server = tmp_path / "server"
    server.mkdir()
    with pytest.raises(xna_mod.XnaError) as failure:
        xna_mod.install(server)
    assert failure.value.code == "download_failed"
    assert str(failure.value) == expected
    assert list(server.iterdir()) == []
