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
import tempfile


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
        backup = _backup_path(ini_path)
        if not os.path.exists(ini_path) and os.path.isfile(backup):
            # 앞선 교체가 원래 파일을 백업 이름으로 옮긴 채 끝났다: 원래 파일(원래 ACL)부터 되돌린다
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
        lines = _merge_option_settings(lines, header, option_line)
        text = newline.join(lines) + newline
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            # 원래 인코딩에 없는 글자(예: latin-1 파일에 한글): BOM 붙은 UTF-8로 바꿔 쓴다
            data = text.encode("utf-8-sig")
        # 임시 파일에 쓴 뒤 바꾼다: 중간에 실패해도 원래 파일이 비지 않는다
        fd, tmp = tempfile.mkstemp(prefix=f"{os.path.basename(ini_path)}.", suffix=".saba-tmp", dir=os.path.dirname(ini_path) or ".")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            _replace_file(tmp, ini_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True
    except OSError:
        return False


# ReplaceFileW가 새 파일을 옮기지 못했다: 원래 파일은 백업 이름에, 새 내용은 임시 파일 이름에 남아 있다
_ERROR_UNABLE_TO_MOVE_REPLACEMENT_2 = 1177


def _replacefilew():
    import ctypes
    fn = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
    fn.restype = ctypes.c_int
    return fn


def _last_error():
    import ctypes
    return ctypes.get_last_error()


def _winerror(err):
    import ctypes
    return ctypes.WinError(err)


def _backup_path(path):
    return f"{path}.saba-bak"


def _replace_file(tmp, path):
    """임시 파일로 원래 파일을 바꾸되 원래 접근 권한을 지킨다 (비밀번호가 든 INI가 넓게 열리지 않게).
    Windows: ReplaceFileW는 원래 파일의 DACL 등을 옮긴다(learn.microsoft.com ReplaceFileW Remarks). 플래그 0이라
    ACL을 옮기지 못하면 실패한다. 백업 이름을 주면 어느 단계에서 실패해도 원래 파일이 남는다(Return value):
    임시 파일(부모 폴더의 상속 ACL)을 설정 파일 자리에 두지 않는다. POSIX: 권한 비트를 옮긴 뒤 os.replace"""
    if not os.path.isfile(path):
        if os.name != "nt":
            # mkstemp은 0600으로 만든다: 새 파일은 open()으로 만든 것과 같은 권한으로
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, path)
        return
    if os.name != "nt":
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
        return
    backup = _backup_path(path)
    if os.path.exists(backup):
        os.remove(backup)
    if _replacefilew()(path, tmp, backup, 0, None, None):
        try:
            os.remove(backup)
        except OSError:
            pass
        return
    err = _last_error()
    if err == _ERROR_UNABLE_TO_MOVE_REPLACEMENT_2 and not os.path.exists(path) and os.path.isfile(backup):
        # 원래 파일(원래 ACL)을 제자리로 되돌린다. 새 값은 쓰지 못한 것으로 알린다
        os.replace(backup, path)
    raise _winerror(err)
