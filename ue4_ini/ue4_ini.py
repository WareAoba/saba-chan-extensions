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

import os
import re


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
        with open(ini_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
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
    try:
        os.makedirs(os.path.dirname(ini_path) or ".", exist_ok=True)
        lines = []
        encoding = "utf-8"
        newline = "\n"
        if os.path.isfile(ini_path):
            with open(ini_path, "rb") as f:
                raw = f.read()
            # BOM이 있으면 떼고 읽어야 첫 줄 헤더가 맞는다. 쓸 때는 BOM을 되살린다
            if raw.startswith(b"\xef\xbb\xbf"):
                encoding = "utf-8-sig"
            # 줄바꿈도 원래 파일을 따른다 (새 파일은 LF)
            if b"\r\n" in raw:
                newline = "\r\n"
            lines = raw.decode(encoding).splitlines()
        lines = _merge_option_settings(lines, header, option_line)
        with open(ini_path, "w", encoding=encoding, newline="") as f:
            f.write(newline.join(lines) + newline)
        return True
    except OSError:
        return False
