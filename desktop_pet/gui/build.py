"""데스크톱 펫 GUI 번들 만들기: src/machine.js + 스프라이트 표(SPRITES) + src/pet.js → dist/desktop-pet.js

스프라이트 그림은 번들에 넣지 않는다. manifest `gui.assets`(gui/sprites)에 두고, 장면이 처음 나올 때 번들이
앱에서 받는다(`host.assetUrl`). 번들에는 장면마다 파일 이름과 칸 수만 싣는다.
빌드 도구 없이 이 스크립트 하나로 묶는다(React는 앱의 window.React). 스프라이트나 src를 고치면 다시 돌리고 dist를 함께 커밋한다:

    python desktop_pet/gui/build.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parent
OUT = GUI / "dist" / "desktop-pet.js"
# 스프라이트 폴더는 manifest `gui.assets` 한 곳에서 정한다
ASSETS = GUI.parent / json.loads((GUI.parent / "manifest.json").read_text(encoding="utf-8"))["gui"]["assets"]


def sprite_frames(name: str, width: int) -> int:
    """띠의 칸 수: machine.js SCENES의 frames와 맞아야 한다 (시험이 대조한다)"""
    return width // 192


def webp_width(data: bytes) -> int:
    """WebP 캔버스 너비 (VP8X 헤더)"""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or data[12:16] != b"VP8X":
        raise ValueError("expected an extended (VP8X) WebP with alpha")
    return int.from_bytes(data[24:27], "little") + 1


def build() -> str:
    sprites = {}
    for path in sorted(ASSETS.glob("*.webp")):
        data = path.read_bytes()
        sprites[path.stem] = {"file": path.name, "frames": sprite_frames(path.stem, webp_width(data))}
    machine = (GUI / "src" / "machine.js").read_text(encoding="utf-8")
    pet = (GUI / "src" / "pet.js").read_text(encoding="utf-8")
    return (
        "/* 데스크톱 펫 GUI 번들. 고치지 말고 gui/src·gui/sprites를 고친 뒤 gui/build.py로 다시 만든다 */\n"
        "(function () {\n'use strict';\n"
        "var module = { exports: {} };\n"
        f"{machine}\n"
        "var M = module.exports;\n"
        f"var SPRITES = {json.dumps(sprites, separators=(',', ':'))};\n"
        f"{pet}\n"
        "})();\n"
    )


def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    text = build()
    # 줄 끝을 LF로 고정한다 (Windows에서 만들어도 같은 바이트)
    OUT.write_bytes(re.sub(r"\r\n", "\n", text).encode("utf-8"))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
