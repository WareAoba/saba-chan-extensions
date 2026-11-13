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
import sys

from daemon_rcon import atomic_write


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
        body = _option_settings_body(content)
        if body is None:
            return {}
        return {key: value for key, (value, _) in _split_option_settings(body).items()}
    except OSError:
        return {}


def _option_settings_body(text):
    """`OptionSettings=(...)` 줄의 바깥 괄호 안쪽. 괄호·따옴표를 따라 제대로 닫힌 경우만 받고,
    닫는 괄호가 없거나 짝이 안 맞으면 None (읽을 수 없음 — 일부만 읽어 손상을 놓치지 않는다)."""
    m = re.search(r"OptionSettings=\(", text)
    if not m:
        return None
    start = m.end() - 1
    line_end = text.find("\n", start)
    line = (text[:line_end] if line_end != -1 else text).rstrip("\r")
    end = _group_end(line, start)
    if end > len(line):
        return None
    return line[start + 1:end - 1]


def _split_option_settings(raw):
    """OptionSettings 괄호 안을 {키: (값, 원문 토큰)}으로 나눈다. 원문은 쓰기에서 손대지 않은 값을 그대로 두는 데 쓴다."""
    props = {}
    i = 0
    while i < len(raw):
        eq = raw.find("=", i)
        if eq == -1:
            break
        key = raw[i:eq].strip()
        i = eq + 1
        if i < len(raw) and raw[i] == '"':
            # Quoted value — \" 와 \\ 만 이스케이프다. 그 밖의 \n·C:\Saves 등은 백슬래시를 남긴다
            start = i
            chars = []
            i += 1
            while i < len(raw) and raw[i] != '"':
                if raw[i] == "\\" and i + 1 < len(raw):
                    i += 1
                    if raw[i] not in ('"', "\\"):
                        chars.append("\\")
                chars.append(raw[i])
                i += 1
            value = "".join(chars)
            i += 1  # 닫는 따옴표
            token = raw[start:i]
            if i < len(raw) and raw[i] == ',':
                i += 1
        elif i < len(raw) and raw[i] == '(':
            # Parenthesized value like CrossplayPlatforms=(Steam,Xbox)
            start = i
            i = min(_group_end(raw, start), len(raw))
            value = token = raw[start:i]
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
            token = value
        props[key] = (value, token)
    return props


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


_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


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
    # float()로 가리면 nan·inf·"1_0"·" 12 "도 숫자가 된다: 글자 모양만 숫자로 본다
    return not _NUMBER.fullmatch(value)


def _quote(value):
    """따옴표 값 안의 \\ 와 " 를 이스케이프한다 (UE4 FParse::QuotedString 규칙)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_option_settings(props, quoted_keys=(), bare_keys=(), original=None):
    """original: 파일에 있던 {키: (값, 원문 토큰)}. 값이 그대로인 따옴표 값은 원문을 다시 쓴다 (사용자가 쓴 이스케이프를 지킨다)."""
    original = original or {}
    parts = []
    for key, value in props.items():
        # UE4 INI: string values must be quoted; booleans, numbers,
        # and parenthesized groups (e.g. CrossplayPlatforms=(Steam,Xbox))
        # stay unquoted. 호출한 모듈이 형식을 아는 키는 값 모양과 상관없이 따른다.
        if key in bare_keys:
            parts.append(f"{key}={value}")
        elif isinstance(value, str) and (key in quoted_keys or _should_quote(value)):
            old_value, old_token = original.get(key, (None, ""))
            token = old_token if old_value == value and old_token.startswith('"') else _quote(value)
            parts.append(f"{key}={token}")
        else:
            parts.append(f"{key}={value}")
    return f"OptionSettings=({','.join(parts)})"


def _find_option_line(lines, header):
    """(*header* 줄 위치, 그 섹션의 OptionSettings 줄 위치). 섹션이 없으면 (None, None), 줄이 없으면 (헤더, None)."""
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        return None, None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
        len(lines),
    )
    return start, next((i for i in range(start + 1, end) if lines[i].lstrip().startswith("OptionSettings=")), None)


def _merge_option_settings(lines, header, option_line):
    """*header* 섹션의 OptionSettings 줄만 교체한다. 다른 섹션·주석·키는 유지한다.

    섹션이 없으면 끝에 추가하고, 섹션에 OptionSettings가 없으면 헤더 바로 뒤에 넣는다.
    """
    start, found = _find_option_line(lines, header)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        return lines + [header, option_line]
    if found is not None:
        lines[found] = option_line
        return lines
    lines.insert(start + 1, option_line)
    return lines


def write_option_settings(ini_path, props, section="[/Script/Pal.PalGameWorldSettings]", quoted_keys=(), bare_keys=()):
    """Write dict back to UE4 INI OptionSettings format.

    기존 파일이 있으면 해당 섹션의 OptionSettings 줄만 바꾼다.
    다른 섹션, 주석, 키는 그대로 둔다.

    Args:
        ini_path: Path to the .ini file.
        props: dict of key-value pairs.
        section: INI section header, with or without brackets (default: Palworld settings).
        quoted_keys: 값이 숫자·nan처럼 보여도 항상 따옴표로 쓸 문자열 키 (비밀번호, 서버 이름 등).
        bare_keys: 항상 따옴표 없이 쓸 키 (열거형 Difficulty=None, 빈 목록 등).

    Returns:
        True on success, False on OSError or a value with a line break (it would cut the OptionSettings line).
    """
    if any(isinstance(v, str) and ("\n" in v or "\r" in v) for v in props.values()):
        print("[ue4_ini] write refused: value with a line break", file=sys.stderr)
        return False
    header = section if section.startswith("[") else f"[{section}]"
    # 링크면 가리키는 파일을 고친다 (교체가 링크를 일반 파일로 바꾸지 않게)
    ini_path = os.path.realpath(ini_path)
    try:
        backup = f"{ini_path}.saba-bak"
        if not os.path.exists(ini_path) and os.path.isfile(backup):
            # 예전 판(0.1.9까지)의 교체가 원래 파일을 이 백업 이름으로 옮긴 채 끝났다: 원래 파일(원래 ACL)부터 되돌린다
            os.replace(backup, ini_path)
        lines = []
        encoding = "utf-8"
        newline = "\n"
        if os.path.isfile(ini_path):
            # 원래 인코딩(BOM 포함)과 줄바꿈을 따른다 (새 파일은 UTF-8, LF)
            content, encoding = _read_text(ini_path)
            if "\r\n" in content:
                newline = "\r\n"
            lines = content.splitlines()
        original = {}
        _, found = _find_option_line(lines, header)
        body = _option_settings_body(lines[found]) if found is not None else None
        if body is not None:
            original = _split_option_settings(body)
        option_line = _format_option_settings(props, quoted_keys, bare_keys, original)
        lines = _merge_option_settings(lines, header, option_line)
        text = newline.join(lines) + newline
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            # 원래 인코딩에 없는 글자(예: latin-1 파일에 한글): BOM 붙은 UTF-8로 바꿔 쓴다
            data = text.encode("utf-8-sig")
        # 같은 폴더 임시 파일에 쓰고 원래 권한을 지켜 바꾼다 (폴더가 없으면 만든다)
        atomic_write(ini_path, data)
        return True
    except OSError as e:
        # 경로 없이 까닭(오류 번호)만 남긴다: 호출한 모듈은 실패만 알린다
        print(f"[ue4_ini] write failed: errno={e.errno} winerror={getattr(e, 'winerror', None)}", file=sys.stderr)
        return False

