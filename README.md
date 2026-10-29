# saba-chan-extensions

[사바쨩](https://github.com/WareAoba/saba-chan)에 기능을 더하는 익스텐션 모음이에요. 모든 게임에 필요하진 않지만 몇몇 게임 모듈이 기대는 기능들을 여기에 따로 두고, 필요한 것만 켜서 씁니다. 모듈을 설치하면 그 모듈이 쓰는 익스텐션도 같이 설치되고 켜져요.

| 익스텐션 | 하는 일 |
|---|---|
| [steamcmd](steamcmd/) | SteamCMD로 게임 서버를 설치하고 업데이트해요 (Palworld, Project Zomboid) |
| [ue4_ini](ue4_ini/) | 언리얼 엔진 4 INI 파일의 `OptionSettings`를 읽고 써요 (Palworld) |
| [xna](xna/) | Microsoft XNA Framework 4.0 Refresh를 PC에 설치하지 않고 게임 서버 옆에 둬요 (Terraria) |

## 생김새

```
<이름>/
  manifest.json   이름, 버전, 필요한 권한, 붙는 hook
  <이름>.py        hook 때 데몬이 부르거나 모듈이 가져다 쓰는 Python 코드
  gui/            (있으면) 앱 화면에 끼워 넣을 UMD 번들
```

익스텐션은 두 가지로 쓰여요. 데몬이 정해진 시점(hook)에 함수를 부르기도 하고, 모듈이 `import extensions.steamcmd`처럼 가져다 쓰기도 해요. 화면이 있는 익스텐션은 앱이 정해진 자리(slot)에 그 화면을 끼워 넣고요. 꺼 둔 익스텐션은 hook으로 불리지도, 모듈이 가져다 쓰지도 못해요. 자세한 계약은 사바쨩 저장소의 [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md)에 있어요.

테스트는 저장소 루트에서 `pytest`로 돌려요.

---

## English

Extensions for [Saba-chan](https://github.com/WareAoba/saba-chan): features that only some games need, kept separate and turned on when needed. Installing a module also installs and turns on the extensions it needs. `steamcmd` installs and updates servers through SteamCMD, `ue4_ini` edits Unreal Engine 4 INI settings, and `xna` places a pinned XNA Framework 4.0 next to a server without installing it system-wide. Each one is a `manifest.json` plus Python code that the daemon calls at hook points or that modules import, optionally with a `gui/` bundle the app slots into its screens. The contract is in [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md) (Korean). Run tests with `pytest`.

## 日本語

[サバちゃん](https://github.com/WareAoba/saba-chan)の拡張機能です。一部のゲームだけが必要とする機能をここに分けて置き、必要なものだけオンにして使います。モジュールを入れると、そのモジュールが使う拡張機能も一緒に入ってオンになります。`steamcmd` は SteamCMD でサーバーをインストール・更新し、`ue4_ini` は Unreal Engine 4 の INI 設定を読み書きし、`xna` は XNA Framework 4.0 を PC にインストールせずサーバーの隣に置きます。それぞれ `manifest.json` と、デーモンが hook のタイミングで呼んだりモジュールが import したりする Python コードでできていて、画面を持つものはアプリが決まった場所(slot)に `gui/` のバンドルを差し込みます。約束ごとは [03-extensions.md](https://github.com/WareAoba/saba-chan/blob/main/docs/architecture/03-extensions.md)(韓国語)にあります。テストは `pytest` で回します。
