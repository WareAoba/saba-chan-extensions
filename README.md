<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/banner-ko-dark.png">
  <img src="docs/images/banner-ko-light.png" width="312" alt="사바쨩">
</picture>

### saba-chan-extensions

몇몇 게임 모듈이 기대는 기능을 따로 담은 익스텐션

[웹사이트](https://saba-chan.online/ko) · [사용 안내](https://saba-chan.online/ko/guide) · [사바쨩](https://github.com/WareAoba/saba-chan) · [모듈](https://github.com/WareAoba/saba-chan-modules)

[![License: MIT](https://img.shields.io/badge/license-MIT-7c3aed?style=flat-square)](LICENSE)

</div>

[사바쨩](https://saba-chan.online)에 기능을 더하는 익스텐션 모음이에요. 모든 게임에 필요하진 않지만 몇몇 게임 모듈이 기대는 기능들을 여기에 따로 두고, 필요한 것만 켜서 씁니다. 사바쨩 본체는 [WareAoba/saba-chan](https://github.com/WareAoba/saba-chan)에, 게임 모듈은 [saba-chan-modules](https://github.com/WareAoba/saba-chan-modules)에 있어요.

## 익스텐션 목록

| 익스텐션 (id) | 버전 | 하는 일 | 쓰는 모듈 |
|---|---|---|---|
| [steamcmd](steamcmd/) (`steamcmd`) | 0.1.8 | SteamCMD로 게임 서버를 설치하고 업데이트해요 | Palworld, Project Zomboid |
| [ue4_ini](ue4_ini/) (`ue4-ini`) | 0.1.9 | 언리얼 엔진 4 INI 파일의 `OptionSettings`를 읽고 써요 | Palworld |
| [xna](xna/) (`xna`) | 0.1.2 | Microsoft XNA Framework 4.0 Refresh를 PC에 설치하지 않고 게임 서버 옆에 둬요 | Terraria (Windows 서버) |
| [desktop_pet](desktop_pet/) (`desktop-pet`) | 0.1.0 | 바탕화면 구석에 서버 일에 반응하는 작은 사바쨩을 띄워요 (앱의 바탕화면 오버레이 창, Python 코드 없음) | 없음 |

버전은 각 폴더의 `manifest.json` `version`이 기준이에요. `steamcmd`·`xna`는 사바 코어(데몬) 0.1.11 이상에서 돌아가요.

## 설치하고 쓰기

- 보통은 따로 할 일이 없어요. 모듈을 설치하면 그 모듈이 쓰는 익스텐션도 같이 받고 켜져요.
- **앱**: 사바 스토리지의 익스텐션 탭에서 설치, 켜기·끄기, 설정, 제거를 해요.
- **CLI**: `saba-chan-cli extension available`로 받을 수 있는 것을 보고, `saba-chan-cli extension install <id>`, `enable <id>`, `disable <id>`로 다뤄요.
- 꺼 둔 익스텐션은 hook으로 불리지도, 모듈이 가져다 쓰지도 못해요. 그 익스텐션이 필요한 서버는 시작할 때 알려 줘요.

자세한 설명은 [익스텐션 문서](https://saba-chan.online/docs/extensions)에 있어요.

## 생김새

```
<이름>/
  manifest.json   id, 버전, 필요한 권한, 붙는 hook
  <이름>.py        hook 때 데몬이 부르거나 모듈이 가져다 쓰는 Python 코드
  gui/            (있으면) 앱 화면에 끼워 넣을 UMD 번들
```

`desktop_pet`의 번들(`gui/dist/desktop-pet.js`)은 `gui/src`와 `gui/sprites`를 `python desktop_pet/gui/build.py`로 묶은 것이에요. 고치면 다시 묶어서 함께 커밋해요(시험이 어긋남을 잡아요).

익스텐션은 두 가지로 쓰여요. 데몬이 정해진 시점(hook)에 함수를 부르기도 하고, 모듈이 `import extensions.steamcmd`처럼 가져다 쓰기도 해요. 화면이 있는 익스텐션은 앱이 정해진 자리(slot)에 그 화면을 끼워 넣고요. 자세한 계약은 사바쨩 저장소의 [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md)에 있어요.

## 검사와 발행

- 테스트는 저장소 루트에서 `pytest`로 돌려요. PR을 열면 `CI` 액션이 Windows에서 ruff 치명 규칙과 pytest를 돌리고, Actions 탭에서 직접 돌리면 Ubuntu까지 해요.
- 익스텐션을 고쳐서 내보낼 때는 `manifest.json`의 `version`을 올리고 `main`에 병합해요. 그 버전을 꼭 써야 하는 모듈은 `module.toml` `[module.dependencies]`에 `ext-<id> = ">=버전"`으로 적어요.
- 이 저장소에는 따로 발행하는 액션이 없어요. 사바쨩 앱을 발행할 때 사바쨩 저장소의 발행 액션이 이 저장소의 `main`을 받아 익스텐션마다 `ext-<id>.zip`을 만들고, 앱과 같은 릴리스 목록에 서명해서 올려요.

---

## English

Extensions for [Saba-chan](https://saba-chan.online): features that only some games need, kept separate and turned on when needed. `steamcmd` 0.1.8 installs and updates servers through SteamCMD (Palworld, Project Zomboid), `ue4-ini` 0.1.9 edits Unreal Engine 4 INI settings (Palworld), and `xna` 0.1.2 places a pinned XNA Framework 4.0 next to a Windows Terraria server without installing it system-wide. Installing a module also installs and turns on the extensions it needs; you can also manage them in the Extensions tab of Saba Storage or with `saba-chan-cli extension install|enable|disable <id>`. Each one is a `manifest.json` plus Python code that the daemon calls at hook points or that modules import, optionally with a `gui/` bundle the app slots into its screens. The contract is in [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md) (Korean). Run tests with `pytest`. Extensions ship with each Saba-chan app release: bump `version` in `manifest.json`, merge to `main`, and the app's release workflow packs and signs them.

## 日本語

[サバちゃん](https://saba-chan.online)の拡張機能です。一部のゲームだけが必要とする機能をここに分けて置き、必要なものだけオンにして使います。`steamcmd` 0.1.8 は SteamCMD でサーバーをインストール・更新し(Palworld、Project Zomboid)、`ue4-ini` 0.1.9 は Unreal Engine 4 の INI 設定を読み書きし(Palworld)、`xna` 0.1.2 は XNA Framework 4.0 を PC にインストールせず Windows の Terraria サーバーの隣に置きます。モジュールを入れると、そのモジュールが使う拡張機能も一緒に入ってオンになります。サバ ストレージの拡張機能タブや `saba-chan-cli extension install|enable|disable <id>` でも管理できます。それぞれ `manifest.json` と、デーモンが hook のタイミングで呼んだりモジュールが import したりする Python コードでできていて、画面を持つものはアプリが決まった場所(slot)に `gui/` のバンドルを差し込みます。約束ごとは [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md)(韓国語)にあります。テストは `pytest` で回します。拡張機能はサバちゃんアプリのリリースと一緒に配布されます。`manifest.json` の `version` を上げて `main` にマージすると、アプリのリリースワークフローがまとめて署名します。
