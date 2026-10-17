"""UE4 INI 익스텐션 테스트.

모듈(palworld 등)은 parse_option_settings / write_option_settings를 in-process로 import한다.
"""
import json
import os
import tempfile

from extensions.ue4_ini import parse_option_settings, write_option_settings


def test_package_reexports_inner_module():
    from extensions.ue4_ini import ue4_ini
    assert parse_option_settings is ue4_ini.parse_option_settings
    assert write_option_settings is ue4_ini.write_option_settings


def test_manifest_declares_no_hooks():
    """함수는 ini_path를 받는 라이브러리 API다. 데몬 훅으로 디스패치될 수 없으므로 훅을 선언하지 않는다."""
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["id"] == "ue4-ini"
    assert manifest.get("dependencies") is not None
    assert not manifest.get("hooks")
    assert not manifest.get("python_modules")


# ── Original functional tests (via new import path) ──────────

def test_parse_simple_key_values():
    """Basic key=value parsing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write("[/Script/Pal.PalGameWorldSettings]\n")
        f.write("OptionSettings=(Difficulty=2,DayTimeSpeedRate=1.000000,NightTimeSpeedRate=1.000000)\n")
        path = f.name
    try:
        props = parse_option_settings(path)
        assert props["Difficulty"] == "2"
        assert props["DayTimeSpeedRate"] == "1.000000"
        assert props["NightTimeSpeedRate"] == "1.000000"
    finally:
        os.unlink(path)


def test_parse_quoted_values():
    """Values with commas inside quotes."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write("[/Script/Pal.PalGameWorldSettings]\n")
        f.write('OptionSettings=(ServerName="My Server, The Best",Port=8211)\n')
        path = f.name
    try:
        props = parse_option_settings(path)
        assert props["ServerName"] == "My Server, The Best"
        assert props["Port"] == "8211"
    finally:
        os.unlink(path)


def test_parse_parenthesized_values():
    """Values with nested parentheses."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write("[/Script/Pal.PalGameWorldSettings]\n")
        f.write("OptionSettings=(Platforms=(Steam,Xbox),Port=8211)\n")
        path = f.name
    try:
        props = parse_option_settings(path)
        assert props["Platforms"] == "(Steam,Xbox)"
        assert props["Port"] == "8211"
    finally:
        os.unlink(path)


def test_parse_missing_file():
    """Non-existent file returns empty dict."""
    props = parse_option_settings("/nonexistent/file.ini")
    assert props == {}


def test_parse_no_option_settings():
    """File without OptionSettings."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write("[SomeSection]\nKey=Value\n")
        path = f.name
    try:
        props = parse_option_settings(path)
        assert props == {}
    finally:
        os.unlink(path)


def test_write_and_read_roundtrip():
    """Write then read preserves key-value pairs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sub", "PalWorldSettings.ini")
        original = {"Difficulty": "2", "ServerName": "Test", "Port": "8211"}

        ok = write_option_settings(path, original)
        assert ok is True
        assert os.path.isfile(path)

        result = parse_option_settings(path)
        assert result["Difficulty"] == "2"
        assert result["ServerName"] == "Test"
        assert result["Port"] == "8211"


def test_write_quoted_values():
    """Values with special chars get quoted on write."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "settings.ini")
        props = {"ServerName": "My Server, The Best", "Port": "8211"}

        write_option_settings(path, props)

        with open(path, 'r') as f:
            content = f.read()
        assert 'ServerName="My Server, The Best"' in content


def test_write_custom_section():
    """Custom section header is used."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "settings.ini")
        props = {"Key": "Value"}

        write_option_settings(path, props, section="[/Custom/Section]")

        with open(path, 'r') as f:
            content = f.read()
        assert "[/Custom/Section]" in content


def test_write_password_quoted():
    """String values like passwords are always quoted, even without spaces/commas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "settings.ini")
        props = {
            "RESTAPIEnabled": "True",
            "AdminPassword": "PDfsZyRKFzS3R6qj",
            "ServerPassword": "",
            "Port": "8211",
        }

        write_option_settings(path, props)

        with open(path, 'r') as f:
            content = f.read()
        # String values must be quoted
        assert 'AdminPassword="PDfsZyRKFzS3R6qj"' in content
        assert 'ServerPassword=""' in content
        # Booleans and numbers must NOT be quoted
        assert 'RESTAPIEnabled=True' in content
        assert 'Port=8211' in content

        # Roundtrip: parsed values should match originals
        result = parse_option_settings(path)
        assert result["AdminPassword"] == "PDfsZyRKFzS3R6qj"
        assert result["ServerPassword"] == ""
        assert result["RESTAPIEnabled"] == "True"
        assert result["Port"] == "8211"


def test_parse_boolean_values():
    """Boolean-like values preserved as strings."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write("[/Script/Pal.PalGameWorldSettings]\n")
        f.write("OptionSettings=(RESTAPIEnabled=True,RCONEnabled=False,bIsMultiplay=True)\n")
        path = f.name
    try:
        props = parse_option_settings(path)
        assert props["RESTAPIEnabled"] == "True"
        assert props["RCONEnabled"] == "False"
        assert props["bIsMultiplay"] == "True"
    finally:
        os.unlink(path)




def test_write_preserves_other_sections_and_comments(tmp_path):
    path = tmp_path / "PalWorldSettings.ini"
    path.write_text(
        "; header comment\n"
        "[/Script/Engine.Game]\n"
        "bUseFoo=True\n"
        "\n"
        "[/Script/Pal.PalGameWorldSettings]\n"
        "; keep me\n"
        "OptionSettings=(Difficulty=1,ServerName=\"Old\")\n"
        "Other=1\n",
        encoding="utf-8",
    )
    assert write_option_settings(str(path), {"Difficulty": "2", "ServerName": "New"}) is True
    content = path.read_text(encoding="utf-8")
    assert "; header comment" in content
    assert "[/Script/Engine.Game]\nbUseFoo=True" in content
    assert "; keep me" in content
    assert "Other=1" in content
    assert 'OptionSettings=(Difficulty=2,ServerName="New")' in content
    assert "Old" not in content
    assert content.count("OptionSettings=") == 1


def test_write_appends_missing_section_without_dropping_content(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("[Other]\nKey=Value\n", encoding="utf-8")
    write_option_settings(str(path), {"Port": "8211"}, section="/Script/Pal.PalGameWorldSettings")
    content = path.read_text(encoding="utf-8")
    assert content.startswith("[Other]\nKey=Value\n")
    assert "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(Port=8211)\n" in content


def test_write_inserts_option_settings_into_existing_section(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("[/Script/Pal.PalGameWorldSettings]\n; comment\n[Next]\nA=1\n", encoding="utf-8")
    write_option_settings(str(path), {"Port": "8211"})
    content = path.read_text(encoding="utf-8")
    assert content == "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(Port=8211)\n; comment\n[Next]\nA=1\n"


def test_write_escapes_quotes_and_roundtrips(tmp_path):
    path = tmp_path / "settings.ini"
    props = {"ServerName": 'My "Best" Server, \\o/', "Port": "8211"}
    write_option_settings(str(path), props)
    content = path.read_text(encoding="utf-8")
    assert 'ServerName="My \\"Best\\" Server, \\\\o/"' in content
    assert parse_option_settings(str(path)) == props
