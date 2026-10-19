"""
saba-chan UE4 INI Extension
============================
Parse and write Unreal Engine 4 INI files with OptionSettings format.

Used by game modules that run on UE4 (Palworld, ARK, etc.).

Usage:
    from extensions.ue4_ini import parse_option_settings, write_option_settings

    props = parse_option_settings("/path/to/PalWorldSettings.ini")
    props["Difficulty"] = "2"
    write_option_settings("/path/to/PalWorldSettings.ini", props,
                          section="/Script/Pal.PalGameWorldSettings")

라이브러리 전용 익스텐션이다 — 데몬 훅이 없고 모듈이 in-process로 import한다.
"""

import locale
import os
import re
import shutil


def _read_text(ini_path):
    """파일 내용과 그 인코딩. BOM으로 UTF-16·UTF-8을 가리고, 없으면 UTF-8 → cp949 → 시스템 로캘 순서로 읽는다
    (메모장 등으로 ANSI·UTF-16 저장한 파일). cp949가 로캘보다 먼저다: 영문 Windows의 cp1252는 거의 모든 바이트를
    받아 한글 파일을 깨진 글자로 읽는다. 어느 것도 아니면 latin-1로 바이트를 그대로 지킨다"""
    with open(ini_path, "rb") as f:
        raw = f.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ["utf-16"]
    elif raw.startswith(b"\xef\xbb\xbf"):
        candidates = ["utf-8-sig"]
    else:
        candidates = ["utf-8", "cp949", locale.getpreferredencoding(False)]
    for encoding in candidates + ["latin-1"]:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    raise AssertionError("latin-1 decodes any bytes")


def parse_option_settings(ini_path):
    """Parse UE4 INI OptionSettings into a dict.

    Handles the UE4 format:
      [/Script/Some.Settings]
      OptionSettings=(Key1=Val1,Key2=Val2,...)

    Supports:
    - Quoted string values with commas: Key="Value with, commas"
    - Backslash escapes inside quotes: Key="Say \\"hi\\""
    - Parenthesized values: CrossplayPlatforms=(Steam,Xbox)

    Args:
        ini_path: Path to the .ini file.

    Returns:
        dict of key-value pairs, or empty dict if file missing/unparseable.
    """
    if not os.path.isfile(ini_path):
        return {}
    try:
        content, _ = _read_text(ini_path)
        m = re.search(r'OptionSettings=\((.+)\)', content)
        if not m:
            return {}
        raw = m.group(1)

        props = {}
        i = 0
        while i < len(raw):
            eq = raw.find("=", i)
            if eq == -1:
                break
            key = raw[i:eq].strip()
            i = eq + 1
            if i < len(raw) and raw[i] == '"':
                # Quoted value — \" 와 \\ 이스케이프를 해제한다
                chars = []
                i += 1
                while i < len(raw) and raw[i] != '"':
                    if raw[i] == "\\" and i + 1 < len(raw):
                        i += 1
                    chars.append(raw[i])
                    i += 1
                value = "".join(chars)
                i += 1  # 닫는 따옴표
                if i < len(raw) and raw[i] == ',':
                    i += 1
            elif i < len(raw) and raw[i] == '(':
                # Parenthesized value like CrossplayPlatforms=(Steam,Xbox)
                start = i
                i = min(_group_end(raw, start), len(raw))
                value = raw[start:i]
                if i < len(raw) and raw[i] == ',':
                    i += 1
            else:
                comma = raw.find(",", i)
                if comma == -1:
                    value = raw[i:].strip()
                    i = len(raw)
                else:
                    value = raw[i:comma].strip()
                    i = comma + 1
            props[key] = value
        return props
    except OSError:
        return {}


def _is_group(value):
    """`(`로 열어 맨 끝의 `)`로 닫히는 값만 그룹이다 — "(KR) Friends"는 그룹이 아니다."""
    if not value.startswith("("):
        return False
    return _group_end(value, 0) == len(value)


def _group_end(raw, start):
    """raw[start]의 `(`와 짝인 `)` 바로 뒤 위치. 따옴표 안의 괄호와 이스케이프는 세지 않는다 (짝이 없으면 len(raw) + 1)."""
    depth = 0
    quoted = False
    i = start
    while i < len(raw):
        ch = raw[i]
        if quoted:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(raw) + 1


def _should_quote(value):
    """Determine if a value needs quoting in UE4 INI OptionSettings.

    Unquoted: True/False, numeric literals, parenthesized groups.
    Quoted:   everything else (strings, passwords, URLs, etc.).
    """
    if not isinstance(value, str):
        return False
    if _is_group(value):
        return False
    if value in ("True", "False"):
        return False
    try:
        float(value)
        return False
    except ValueError:
        pass
    return True


def _quote(value):
    """따옴표 값 안의 \\ 와 " 를 이스케이프한다 (UE4 FParse::QuotedString 규칙)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_option_settings(props):
    parts = []
    for key, value in props.items():
        # UE4 INI: string values must be quoted; booleans, numbers,
        # and parenthesized groups (e.g. CrossplayPlatforms=(Steam,Xbox))
        # stay unquoted.
        if isinstance(value, str) and _should_quote(value):
            parts.append(f"{key}={_quote(value)}")
        else:
            parts.append(f"{key}={value}")
    return f"OptionSettings=({','.join(parts)})"


def _merge_option_settings(lines, header, option_line):
    """*header* 섹션의 OptionSettings 줄만 교체한다. 다른 섹션·주석·키는 유지한다.

    섹션이 없으면 끝에 추가하고, 섹션에 OptionSettings가 없으면 헤더 바로 뒤에 넣는다.
    """
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        if lines and lines[-1].strip():
            lines.append("")
        return lines + [header, option_line]

    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
        len(lines),
    )
    for i in range(start + 1, end):
        if lines[i].lstrip().startswith("OptionSettings="):
            lines[i] = option_line
            return lines
    lines.insert(start + 1, option_line)
    return lines


def write_option_settings(ini_path, props, section="[/Script/Pal.PalGameWorldSettings]"):
    """Write dict back to UE4 INI OptionSettings format.

    기존 파일이 있으면 해당 섹션의 OptionSettings 줄만 바꾼다.
    다른 섹션, 주석, 키는 그대로 둔다.

    Args:
        ini_path: Path to the .ini file.
        props: dict of key-value pairs.
        section: INI section header, with or without brackets (default: Palworld settings).

    Returns:
        True on success, False on OSError.
    """
    header = section if section.startswith("[") else f"[{section}]"
    option_line = _format_option_settings(props)
    # 링크면 가리키는 파일을 고친다 (교체가 링크를 일반 파일로 바꾸지 않게)
    ini_path = os.path.realpath(ini_path)
    try:
        os.makedirs(os.path.dirname(ini_path) or ".", exist_ok=True)
        lines = []
        encoding = "utf-8"
        newline = "\n"
        if os.path.isfile(ini_path):
            # 원래 인코딩(BOM 포함)과 줄바꿈을 따른다 (새 파일은 UTF-8, LF)
            content, encoding = _read_text(ini_path)
            if "\r\n" in content:
                newline = "\r\n"
            lines = content.splitlines()
        lines = _merge_option_settings(lines, header, option_line)
        text = newline.join(lines) + newline
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            # 원래 인코딩에 없는 글자(예: latin-1 파일에 한글): BOM 붙은 UTF-8로 바꿔 쓴다
            data = text.encode("utf-8-sig")
        # 임시 파일에 쓴 뒤 바꾼다: 중간에 실패해도 원래 파일이 비지 않는다
        tmp = f"{ini_path}.saba-tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            # 원래 권한(비밀번호가 든 파일의 0600 등)을 지킨다
            if os.path.isfile(ini_path):
                shutil.copymode(ini_path, tmp)
            os.replace(tmp, ini_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True
    except OSError:
        return False
