#!/usr/bin/env python3
"""
saba-chan-extensions: Build & Release Script
============================================

익스텐션 디렉토리를 스캔하여 manifest.json을 파싱하고,
registry.json을 생성한 뒤 각 익스텐션을 zip으로 압축합니다.

출력:
  dist/
    registry.json          — 본체가 참조하는 익스텐션 레지스트리
    extension-{id}.zip     — 각 익스텐션의 배포용 압축 파일
    RELEASE_BODY.md        — GitHub Release 본문
    summary_table.md       — Step Summary용 테이블 조각

GitHub Actions Outputs:
  should_release   — 릴리즈를 생성해야 하는지 (true/false)
  tag              — 릴리즈 태그 (extensions-YYYYMMDD-HHMMSS)
  release_name     — 릴리즈 이름
  extension_count  — 익스텐션 수
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────

REPO_ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parents[2]))
DIST_DIR = REPO_ROOT / "dist"

# GitHub 리포지토리 정보 (download_url 생성용)
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "WareAoba/saba-chan-extensions")

# zip 제외 대상
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", "node_modules", "__pypackages__"}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo"}
EXCLUDE_PREFIXES = ("test_",)
EXCLUDE_FILES = {"package-lock.json"}


# ── 유틸리티 ──────────────────────────────────────────────

def set_output(name: str, value: str) -> None:
    """GitHub Actions output 설정"""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            if "\n" in value:
                delimiter = uuid.uuid4().hex
                f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                f.write(f"{name}={value}\n")
    else:
        # 로컬 실행 시 콘솔 출력
        preview = value[:80] + "..." if len(value) > 80 else value
        print(f"  [OUTPUT] {name} = {preview}")


def sha256_file(path: Path) -> str:
    """파일의 SHA256 해시 계산"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 익스텐션 탐색 ────────────────────────────────────────

def find_extensions() -> list[Path]:
    """manifest.json이 있는 디렉토리를 찾아 반환 (_, . 접두사 제외)"""
    extensions = []
    for entry in sorted(REPO_ROOT.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            if (entry / "manifest.json").exists():
                extensions.append(entry)
    return extensions


def parse_manifest(manifest_path: Path) -> dict:
    """manifest.json 파싱 → 메타데이터 딕셔너리 반환"""
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    return {
        "id": data.get("id", manifest_path.parent.name),
        "name": data.get("name", manifest_path.parent.name),
        "version": data.get("version", "0.0.0"),
        "description": data.get("description", ""),
        "author": data.get("author", ""),
        "min_app_version": data.get("min_app_version", "0.0.0"),
        "dependencies": data.get("dependencies", []),
        "has_gui": bool(data.get("gui", {}).get("slots")),
        "has_i18n": data.get("i18n_dir") is not None,
    }


# ── 압축 ─────────────────────────────────────────────────

def should_exclude(file_path: Path, base_dir: Path) -> bool:
    """zip에서 제외할 파일인지 판단"""
    rel = file_path.relative_to(base_dir)

    # 제외 디렉토리 하위
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True

    # 제외 확장자
    if file_path.suffix in EXCLUDE_EXTENSIONS:
        return True

    # 테스트 파일
    if file_path.name.startswith(EXCLUDE_PREFIXES):
        return True

    # 특정 파일 제외
    if file_path.name in EXCLUDE_FILES:
        return True

    return False


def create_extension_zip(ext_dir: Path, output_path: Path) -> tuple[str, int, int]:
    """
    익스텐션 디렉토리를 zip으로 압축.
    Returns: (sha256, file_count, zip_size_bytes)
    """
    file_count = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(ext_dir.rglob("*")):
            if file_path.is_file() and not should_exclude(file_path, ext_dir):
                arcname = str(file_path.relative_to(ext_dir))
                zf.write(file_path, arcname)
                file_count += 1

    sha256 = sha256_file(output_path)
    zip_size = output_path.stat().st_size
    return sha256, file_count, zip_size


# ── 레지스트리 ────────────────────────────────────────────

def load_previous_registry() -> dict | None:
    """이전 릴리즈의 registry.json 로드 (환경변수 PREV_REGISTRY 경로)"""
    prev_path = os.environ.get("PREV_REGISTRY", "")
    if prev_path:
        p = Path(prev_path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


def detect_changes(
    current: dict[str, dict],
    previous: dict | None,
) -> list[str]:
    """현재 익스텐션 vs 이전 레지스트리 비교 → 변경 사항 목록"""
    changes: list[str] = []

    if previous is None:
        # 첫 릴리즈
        for info in current.values():
            changes.append(f"✨ 새 익스텐션: {info['name']} v{info['version']}")
        return changes

    prev_extensions = previous.get("extensions", {})

    for ext_id, info in current.items():
        prev = prev_extensions.get(ext_id)
        if prev is None:
            changes.append(f"✨ 새 익스텐션: {info['name']} v{info['version']}")
        elif prev.get("version") != info["version"]:
            changes.append(
                f"⬆️ {info['name']}: {prev['version']} → {info['version']}"
            )
        elif prev.get("sha256") != info.get("sha256"):
            changes.append(
                f"🔄 {info['name']}: 내용 변경 (버전 동일: v{info['version']})"
            )

    for ext_id in prev_extensions:
        if ext_id not in current:
            display = prev_extensions[ext_id].get("name", ext_id)
            changes.append(f"🗑️ 익스텐션 제거: {display}")

    return changes


# ── 릴리즈 본문 생성 ─────────────────────────────────────

def build_release_body(
    extensions: dict[str, dict],
    changes: list[str],
    generated_at: str,
) -> str:
    """GitHub Release 본문 Markdown 생성"""
    lines: list[str] = []

    # 익스텐션 버전 테이블
    lines.append("## 📦 Extension Versions\n")
    lines.append("| Extension | Description | Version | Asset |")
    lines.append("|-----------|------------|---------|-------|")
    for ext_id, m in extensions.items():
        lines.append(
            f"| **{m['name']}** | {m['description']} "
            f"| `v{m['version']}` | `{m['asset']}` |"
        )

    # 변경 사항
    if changes:
        lines.append("\n## 📝 Changes\n")
        for c in changes:
            lines.append(f"- {c}")

    # 사용법 안내
    lines.append("\n## 🔧 Usage\n")
    lines.append("```")
    lines.append("# registry.json을 다운로드하여 익스텐션 버전 확인")
    lines.append(
        f"gh release download --repo {GITHUB_REPO} "
        "--pattern 'registry.json'"
    )
    lines.append("")
    lines.append("# 특정 익스텐션만 다운로드")
    lines.append(
        f"gh release download --repo {GITHUB_REPO} "
        "--pattern 'extension-docker.zip'"
    )
    lines.append("```")

    lines.append(f"\n---\n*Generated at {generated_at}*")
    return "\n".join(lines)


# ── 메인 ─────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  saba-chan Extension Builder")
    print("=" * 60)

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 익스텐션 탐색 ──────────────────────────────
    extensions = find_extensions()
    if not extensions:
        print("\n⚠️  익스텐션을 찾을 수 없습니다!")
        set_output("should_release", "false")
        sys.exit(0)

    print(f"\n📦 {len(extensions)}개 익스텐션 발견:")
    for e in extensions:
        print(f"   └─ {e.name}/")

    # ── 2. 파싱 + 압축 + 레지스트리 데이터 수집 ──────
    registry_extensions: dict[str, dict] = {}
    summary_rows: list[str] = []

    for ext_dir in extensions:
        manifest_path = ext_dir / "manifest.json"
        meta = parse_manifest(manifest_path)
        ext_id = meta["id"]

        print(f"\n🔍 {meta['name']} (v{meta['version']})")

        # zip 생성
        asset_name = f"extension-{ext_id}.zip"
        zip_path = DIST_DIR / asset_name
        sha256, file_count, zip_size = create_extension_zip(ext_dir, zip_path)

        print(f"   📦 {asset_name}  ({file_count} files, {zip_size:,} bytes)")
        print(f"   🔒 SHA256: {sha256[:16]}...")

        registry_extensions[ext_id] = {
            "name": meta["name"],
            "version": meta["version"],
            "description": meta["description"],
            "author": meta["author"],
            "min_app_version": meta["min_app_version"],
            "dependencies": meta["dependencies"],
            "asset": asset_name,
            "sha256": sha256,
            "install_dir": f"extensions/{ext_id}",
            "download_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/{asset_name}",
            "has_gui": meta["has_gui"],
            "has_i18n": meta["has_i18n"],
        }

        summary_rows.append(f"| **{meta['name']}** | `v{meta['version']}` |")

    # ── 3. registry.json 생성 ─────────────────────────
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()

    registry = {
        "schema_version": 1,
        "generated_at": generated_at,
        "extensions": registry_extensions,
    }

    registry_path = DIST_DIR / "registry.json"
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    print(f"\n📋 registry.json 생성 완료")

    # ── 4. 변경 사항 감지 ─────────────────────────────
    prev_registry = load_previous_registry()
    changes = detect_changes(registry_extensions, prev_registry)
    force = os.environ.get("FORCE_RELEASE", "false").lower() == "true"

    should_release = len(changes) > 0 or force

    if not should_release:
        print("\n⏭️  변경 사항 없음 — 릴리즈 건너뜀")
        set_output("should_release", "false")
        return

    print(f"\n📝 변경 사항 {len(changes)}건:")
    for c in changes:
        print(f"   {c}")

    # ── 5. 릴리즈 정보 생성 ───────────────────────────
    tag = now.strftime("extensions-%Y%m%d-%H%M%S")

    # 릴리즈 이름: 각 익스텐션 버전 요약
    version_parts = [
        f"{m['name']} v{m['version']}" for m in registry_extensions.values()
    ]
    release_name = f"Extensions — {', '.join(version_parts)}"

    # 릴리즈 본문
    release_body = build_release_body(registry_extensions, changes, generated_at)
    body_path = DIST_DIR / "RELEASE_BODY.md"
    with open(body_path, "w", encoding="utf-8") as f:
        f.write(release_body)

    # Step summary용 테이블
    table_path = DIST_DIR / "summary_table.md"
    with open(table_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_rows))

    # ── 6. GitHub Actions Outputs ─────────────────────
    set_output("should_release", "true")
    set_output("tag", tag)
    set_output("release_name", release_name)
    set_output("extension_count", str(len(registry_extensions)))

    print(f"\n{'=' * 60}")
    print(f"  ✅ 빌드 완료!")
    print(f"  🏷️  태그: {tag}")
    print(f"  📦 익스텐션: {len(registry_extensions)}개")
    print(f"  📝 변경: {len(changes)}건")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
