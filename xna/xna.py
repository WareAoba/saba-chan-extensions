"""
saba-chan XNA Framework 4.0 Extension
=====================================
Puts a pinned copy of Microsoft XNA Framework 4.0 Refresh next to a game server (Terraria's Windows
server needs it, and the server download does not include it). Nothing is installed on the PC: the
official redistributable MSI is downloaded once, checked against a pinned SHA-256, and only the files a
server needs are taken out of it. A runtime installed on the PC is never used, so every PC runs the
same version.

Usage (from a game module lifecycle.py):
    from extensions.xna import install, present, XnaError

    if not present(server_dir):
        install(server_dir)          # raises XnaError(code, message) on failure

Why not ``msiexec /a``: modules that are not in the signed catalog run in a Windows AppContainer,
which cannot reach the Windows Installer service (error 1601). The MSI (an OLE compound file holding
one MSZIP cabinet) is read in Python instead.
"""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import urllib.request
import zlib
from pathlib import Path

VERSION = "4.0-refresh"
# Microsoft XNA Framework Redistributable 4.0 Refresh
# https://www.microsoft.com/en-us/download/details.aspx?id=27598
# 7,059,456 bytes, Authenticode signed by Microsoft Corporation (checked 2026-10-25). Microsoft publishes
# no checksum, so the SHA-256 of the signature-checked file is pinned here.
MSI_URL = "https://download.microsoft.com/download/5/3/a/53a804c8-ec78-43cd-a0f0-2fb4d45603d3/xnafx40_redist.msi"
MSI_SHA256 = "2b03c130c4bb5f106b9619bea8150201f7e982709cfe9a0cc8bde75ff0a83b27"

# (cabinet entry in the MSI, file name, SHA-256). The four assemblies a server references and their
# native dependencies. Measured: a folder with only these files starts the Terraria Windows server.
FILES = (
    ("Microsoft_Xna_Framework_dll_GAC", "Microsoft.Xna.Framework.dll",
     "38e7093f52d7474bbc6256906519781a1210d7da50a1c667b52716fcf49ca130"),
    ("Microsoft_Xna_Framework_Game_dll_GAC", "Microsoft.Xna.Framework.Game.dll",
     "b5dffdd8125abef2a4507ba4e1d2f11062143f0a63d48fe4f298b95ad746a1f0"),
    ("Microsoft_Xna_Framework_Graphics_dll_GAC", "Microsoft.Xna.Framework.Graphics.dll",
     "560080fc39021c611ca9d076dcebed312faf6d7d1413c2dc523683ea635e9f55"),
    ("Microsoft_Xna_Framework_Xact_dll_GAC", "Microsoft.Xna.Framework.Xact.dll",
     "a14d5364dca7cf49fb90639e87ba04d52b59a700dc9198efa5707ce8eae28f0a"),
    ("XnaNative_dll_File", "XnaNative.dll",
     "2825f9e669d583ea989aa1197c529ccfd0ea7b556af8793e847bed1178ca8946"),
    ("F_CENTRAL_msvcr100_x86.DF495DFD_79F6_34DF_BB1E_E58DB5BDCF2C", "msvcr100.dll",
     "1221a09484964a6f38af5e34ee292b9afefccb3dc6e55435fd3aaf7c235d9067"),
    ("F_CENTRAL_msvcp100_x86.DF495DFD_79F6_34DF_BB1E_E58DB5BDCF2C", "msvcp100.dll",
     "a3ba6421991241bea9c8334b62c3088f8f131ab906c3cc52113945d05016a35f"),
)


class XnaError(Exception):
    """``code``: download_failed / checksum_mismatch / bad_installer / write_failed"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matches(path: Path, digest: str) -> bool:
    try:
        return _sha256(path.read_bytes()) == digest
    except OSError:
        return False


def present(target_dir) -> bool:
    """``target_dir`` has every pinned file with the pinned contents"""
    target = Path(target_dir)
    return all(_matches(target / name, digest) for _, name, digest in FILES)


def _cache_dir() -> Path | None:
    """Verified files are kept in this extension's data folder so the next server does not download again.
    Sandboxed runs get their own data root from the daemon (``SABA_EXTENSION_DATA_ROOT``)."""
    root = os.environ.get("SABA_EXTENSION_DATA_ROOT")
    return Path(root) / "xna" / VERSION if root else None


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "saba-chan"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def _msi_cabinet(data: bytes) -> bytes:
    """The cabinet stream of an MSI (OLE compound file). It is large, so it is in the FAT chain, not the mini stream"""
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("not an MSI file")
    size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    fat_count, dir_start = struct.unpack_from("<II", data, 0x2C)
    cutoff = struct.unpack_from("<I", data, 0x38)[0]
    difat_start, difat_count = struct.unpack_from("<II", data, 0x44)
    difat = list(struct.unpack_from("<109I", data, 0x4C))
    for _ in range(difat_count):
        entries = struct.unpack_from(f"<{size // 4}I", data, size + difat_start * size)
        difat += entries[:-1]
        difat_start = entries[-1]
    fat = []
    for sector in difat[:fat_count]:
        fat += struct.unpack_from(f"<{size // 4}I", data, size + sector * size)

    def read(sector, length):
        out = bytearray()
        while sector < 0xFFFFFFFA and len(out) < length:
            out += data[size + sector * size:size + (sector + 1) * size]
            sector = fat[sector]
        return bytes(out[:length])
    directory = read(dir_start, len(data))
    for i in range(0, len(directory) - 127, 128):
        if directory[i + 66] != 2:  # streams only
            continue
        start, length = struct.unpack_from("<IQ", directory, i + 116)
        if length >= cutoff:
            stream = read(start, length)
            if stream[:4] == b"MSCF":
                return stream
    raise ValueError("no cabinet in MSI")


def _cab_files(cab: bytes) -> dict[str, bytes]:
    """Cabinet with one MSZIP folder → {entry name: bytes}. Each MSZIP block uses the previous block's output as its dictionary"""
    cab_size, files_at = struct.unpack_from("<I4xI", cab, 8)
    folders, count, flags = struct.unpack_from("<HHH", cab, 26)
    if flags or folders != 1 or cab_size > len(cab):
        raise ValueError("unsupported cabinet")
    data_at, blocks, kind = struct.unpack_from("<IHH", cab, 36)
    if kind & 0xF != 1:
        raise ValueError("unsupported cabinet compression")
    body, prev, pos = bytearray(), b"", data_at
    for _ in range(blocks):
        packed, plain = struct.unpack_from("<4xHH", cab, pos)
        block = cab[pos + 8:pos + 8 + packed]
        pos += 8 + packed
        if block[:2] != b"CK":
            raise ValueError("broken cabinet block")
        inflate = zlib.decompressobj(-15, zdict=prev) if prev else zlib.decompressobj(-15)
        prev = inflate.decompress(block[2:]) + inflate.flush()
        if len(prev) != plain:
            raise ValueError("broken cabinet block")
        body += prev
    files, pos = {}, files_at
    for _ in range(count):
        length, offset = struct.unpack_from("<II", cab, pos)
        end = cab.index(b"\0", pos + 16)
        files[cab[pos + 16:end].decode("ascii")] = bytes(body[offset:offset + length])
        pos = end + 1
    return files


def files_from_msi(data: bytes) -> dict[str, bytes]:
    """{file name: bytes} of FILES taken out of the MSI"""
    try:
        files = _cab_files(_msi_cabinet(data))
        return {name: files[key] for key, name, _ in FILES}
    except (ValueError, struct.error, KeyError, IndexError, zlib.error) as e:
        raise XnaError("bad_installer", f"XNA installer could not be read: {e!r}") from None


def _fetch(work_dir: Path) -> dict[str, bytes]:
    """Download the MSI into ``work_dir`` (a temporary file that is always removed) and take the files out.
    ``tempfile.mkstemp``, not ``mkdtemp``: a sandboxed run cannot write in a folder that mkdtemp makes."""
    try:
        fd, msi = tempfile.mkstemp(prefix=".xna-", suffix=".download", dir=work_dir)
        os.close(fd)
    except OSError as e:
        raise XnaError("write_failed", f"Could not write a temporary file in {work_dir}: {e}") from None
    try:
        try:
            _download(MSI_URL, msi)
        except OSError as e:
            raise XnaError("download_failed", f"XNA download failed: {e}") from None
        try:
            data = Path(msi).read_bytes()
        except OSError as e:
            raise XnaError("write_failed", f"Could not read the downloaded XNA installer: {e}") from None
    finally:
        try:
            os.remove(msi)
        except OSError:
            pass
    if _sha256(data) != MSI_SHA256:
        raise XnaError("checksum_mismatch", "The downloaded XNA installer is not the official file")
    files = files_from_msi(data)
    for _, name, digest in FILES:
        if _sha256(files[name]) != digest:
            raise XnaError("checksum_mismatch", f"{name} in the XNA installer is not the expected file")
    return files


def _write(path: Path, data: bytes) -> None:
    """Write through a temporary file in the same folder so a half-written DLL is never left"""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def install(target_dir) -> list[str]:
    """Put every pinned file in ``target_dir`` and return their names. Files already there with the pinned
    contents are kept. Uses the verified cache when it is complete, otherwise downloads once."""
    target = Path(target_dir)
    cache = _cache_dir()
    files: dict[str, bytes] = {}
    if cache is not None and all(_matches(cache / name, digest) for _, name, digest in FILES):
        files = {name: (cache / name).read_bytes() for _, name, _ in FILES}
    else:
        files = _fetch(target)
        if cache is not None:
            try:
                cache.mkdir(parents=True, exist_ok=True)
                for name, data in files.items():
                    _write(cache / name, data)
            except OSError:
                pass  # the cache only saves a download next time
    try:
        for _, name, digest in FILES:
            if not _matches(target / name, digest):
                _write(target / name, files[name])
    except OSError as e:
        raise XnaError("write_failed", f"Could not write XNA files to {target}: {e}") from None
    return [name for _, name, _ in FILES]
