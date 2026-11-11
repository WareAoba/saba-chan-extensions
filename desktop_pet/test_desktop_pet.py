"""데스크톱 펫: manifest·번역·번들이 맞물리는지, 상태 기계가 사용자 지정대로 움직이는지.

상태 기계(gui/src/machine.js)는 node로 돌린다. node가 없으면 그 시험만 건너뛴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GUI = HERE / "gui"
LOCALES = ["ko", "en", "ja", "zh-CN", "zh-TW", "es", "pt-BR", "ru", "de", "fr"]

sys.path.insert(0, str(GUI))
import build  # noqa: E402

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def manifest() -> dict:
    return json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


def flat(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def test_the_manifest_declares_only_the_desktop_overlay_slot_and_its_files_exist():
    m = manifest()
    assert m["schema_version"] == 1
    assert m["id"] == "desktop-pet" and HERE.name == m["id"].replace("-", "_")
    assert list(m["gui"]["slots"]) == ["Desktop.overlay"]
    assert (HERE / m["gui"]["bundle"]).is_file()
    assert (HERE / m["gui"]["styles"]).is_file()
    assert set(m["descriptions"]) == set(LOCALES) - {"en"}
    assert (HERE / "icon.png").is_file()


def test_every_language_has_the_same_lines_and_placeholders():
    base = flat(json.loads((HERE / "locales" / "ko.json").read_text(encoding="utf-8")))
    holders = lambda s: sorted(re.findall(r"\{\{(\w+)\}\}", s))  # noqa: E731
    for lang in LOCALES:
        lines = flat(json.loads((HERE / "locales" / f"{lang}.json").read_text(encoding="utf-8")))
        assert set(lines) == set(base), lang
        for key, text in lines.items():
            assert holders(text) == holders(base[key]), (lang, key)


def test_every_bubble_the_machine_says_has_a_line():
    machine = (GUI / "src" / "machine.js").read_text(encoding="utf-8")
    keys = {k for k in re.findall(r"'(bubble\.[a-z_]+)'", machine) if not k.endswith("_")}
    keys |= {f"bubble.schedule_{a}" for a in ("restart", "stop", "update", "other")}
    lines = flat(json.loads((HERE / "locales" / "ko.json").read_text(encoding="utf-8")))
    assert keys and keys <= set(lines), keys - set(lines)


def test_the_committed_bundle_is_up_to_date():
    assert (GUI / "dist" / "desktop-pet.js").read_text(encoding="utf-8") == build.build(), "run python desktop_pet/gui/build.py"


def run_node(script: str):
    prelude = f"const M = require({json.dumps(str(GUI / 'src' / 'machine.js'))});\n"
    out = subprocess.run([NODE, "-e", prelude + textwrap.dedent(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_every_sprite_strip_matches_its_scene():
    scenes = run_node("console.log(JSON.stringify(Object.fromEntries(Object.entries(M.SCENES).map(([k, s]) => [k, s.frames]))))")
    strips = {p.stem: build.sprite_frames(p.stem, build.webp_width(p.read_bytes())) for p in (GUI / "sprites").glob("*.webp")}
    assert strips == scenes


@needs_node
def test_frames_are_slow_except_repair_and_sweeping():
    ms = run_node("console.log(JSON.stringify(Object.fromEntries(Object.entries(M.SCENES).map(([k, s]) => [k, s.ms]))))")
    # 사용자 11-11: 한 칸 시간을 훨씬 느리게, 수리·빗자루질은 빼고 (그 전 시안: 쓰러짐 170, 요리 150, 완성 160, 잠 220, 깸 170)
    assert ms["repair"] == 150 and ms["sweeping"] == 130
    # 사용자 11-11: 대기도 더 느리게 (그 전 240)
    assert ms["idle"] >= 360
    for name, before in {"collapse": 170, "cooking": 150, "served": 160, "sleeping": 220, "waking": 170}.items():
        assert ms[name] >= before * 1.5, name


SCENARIO = """
let t = 0;
const pet = M.createMachine({ now: () => t, random: () => 0.5 });
const seen = [];
const step = (ms, every = 250) => { for (let i = 0; i < ms; i += every) { t += every; pet.tick(); seen.push(pet.view().scene); } };
const at = () => pet.view();
const top = () => at().bubbles[0];
"""


@needs_node
def test_quiet_desk_sweeps_now_and_then_after_ten_minutes_and_sleeps_after_three_hours():
    r = run_node(
        SCENARIO
        + """
        step(M.SWEEP_AFTER - 1000, 1000);
        const before = seen.includes('sweeping');
        seen.length = 0;
        step(5 * 60 * 1000, 1000);
        const after = seen.includes('sweeping');
        t = M.SLEEP_AFTER + 1; pet.tick();
        const asleep = at().scene;
        pet.hover();
        const woke = at().scene;
        step(10000);
        console.log(JSON.stringify({ before, after, asleep, woke, then: at().scene }));
        """
    )
    assert r == {"before": False, "after": True, "asleep": "sleeping", "woke": "waking", "then": "idle"}


@needs_node
def test_hover_jumps_but_not_again_right_away():
    r = run_node(
        SCENARIO
        + """
        pet.hover(); const first = at().scene;
        step(1000); pet.hover(); const again = at().scene;
        step(5000); pet.hover(); const later = at().scene;
        console.log(JSON.stringify({ first, again, later }));
        """
    )
    assert r == {"first": "jump", "again": "idle", "later": "jump"}


@needs_node
def test_a_crash_with_auto_restart_is_repaired_and_one_without_collapses_until_clicked():
    r = run_node(
        SCENARIO
        + """
        pet.event('instance.exit', { instanceId: 'a', instance: '야생', kind: 'crash', restartInSecs: 30 });
        const repairing = at().scene, bubble = [top().key, top().state];
        pet.hover(); const hovered = at().scene;
        step(25000);
        const working = [top().key, top().state];
        pet.event('instance.restarted', { instanceId: 'a', instance: '야생' });
        const fixed = at().scene, done = [top().key, top().state];
        step(5000);
        const back = at().scene;
        pet.event('instance.exit', { instanceId: 'b', instance: '팰', kind: 'crash', restartInSecs: null });
        const down = at().scene;
        step(60000);
        const still = at().scene;
        pet.click();
        const up = at().scene === 'collapse' ? 'collapse' : 'up';
        pet.event('instance.exit', { instanceId: 'c', kind: 'crash', restartInSecs: 3 });
        pet.event('instance.restart_failed', { instanceId: 'c' });
        const failed = at().scene;
        const failedBubble = [top().key, top().state];
        pet.event('instance.exit', { instanceId: 'd', kind: 'user_stop' });
        console.log(JSON.stringify({ repairing, bubble, hovered, working, fixed, done, back, down, still, up, failed, failedBubble }));
        """
    )
    assert r == {
        "repairing": "repair",
        "bubble": ["bubble.restarting", "working"],
        "hovered": "repair",
        "working": ["bubble.restarting", "working"],
        "fixed": "wave",
        "done": ["bubble.restarted", "done"],
        "back": "idle",
        "down": "collapse",
        "still": "collapse",
        "up": "up",
        "failed": "collapse",
        "failedBubble": ["bubble.restart_failed", "failed"],
    }


@needs_node
def test_installing_cooks_and_then_serves_or_scratches_its_head():
    r = run_node(
        SCENARIO
        + """
        pet.event('provision.progress', { instance: 'new', step: 0, total: 3, done: false });
        const cooking = at().scene;
        step(60000);
        const installing = { key: top().key, state: top().state, vars: top().vars };
        pet.event('provision.progress', { instance: 'new', done: true });
        const served = at().scene, ok = [top().key, top().state];
        step(20000);
        pet.event('provision.progress', { instance: 'two', done: false });
        pet.event('provision.progress', { instance: 'two', done: true, error: 'boom' });
        const failed = at().scene, bad = [top().key, top().state];
        console.log(JSON.stringify({ cooking, installing, served, ok, failed, bad }));
        """
    )
    assert r == {
        "cooking": "cooking",
        "installing": {"key": "bubble.installing", "state": "working", "vars": {"server": "new"}},
        "served": "served",
        "ok": ["bubble.provision_done", "done"],
        "failed": "scratch",
        "bad": ["bubble.provision_failed", "failed"],
    }


def test_bubbles_are_short_task_summaries_not_lines():
    # 사용자 11-11: 대사가 아니라 할/한 일 요약만 (느낌표·말줄임표 없이)
    lines = flat(json.loads((HERE / "locales" / "ko.json").read_text(encoding="utf-8")))
    for key, text in lines.items():
        if key.startswith("bubble."):
            assert not re.search(r"[!…?]|요\b|어요|게요", text), (key, text)


@needs_node
def test_only_things_done_from_outside_the_app_get_a_bubble():
    r = run_node(
        SCENARIO
        + """
        pet.event('instance.started', { instanceId: 'a', instance: '야생', source: 'gui' });
        const app = at().bubbles;
        t = 5000;
        pet.event('instance.started', { instanceId: 'a', instance: '야생', source: 'discord', userName: '주인님', guildName: '사바쨩 서버' });
        const discord = top();
        console.log(JSON.stringify({ app, discord }));
        """
    )
    assert r["app"] == []
    assert r["discord"]["key"] == "bubble.started"
    assert r["discord"]["state"] == "done"
    # 사용자 11-11: 첫 줄 한 일과 시킨 사람, 둘째 줄 시각과 장소(디스코드 서버) → 시킨 쪽과 말한 시각을 싣는다
    assert r["discord"]["vars"] == {"server": "야생", "who": {"user": "주인님", "source": "discord", "place": "사바쨩 서버"}}
    assert r["discord"]["at"] == 5000


@needs_node
def test_tasks_at_the_same_time_stack_with_finished_ones_on_top():
    # 사용자 11-11: 여러 작업이 동시에 돌면 겹쳐 쌓고, 끝난 작업을 위로 끌어올린다
    r = run_node(
        SCENARIO
        + """
        const list = () => at().bubbles.map((b) => b.key + ':' + b.vars.server);
        pet.event('instance.exit', { instanceId: 'a', instance: '야생', kind: 'crash', restartInSecs: 30 });
        pet.event('provision.progress', { instance: '팰', done: false });
        const both = list();
        step(1000);
        pet.event('instance.restarted', { instanceId: 'a', instance: '야생' });
        const one = list();
        step(1000);
        pet.event('provision.progress', { instance: '팰', done: true });
        const two = list();
        step(60000);
        console.log(JSON.stringify({ both, one, two, later: list() }));
        """
    )
    assert r == {
        "both": ["bubble.installing:팰", "bubble.restarting:야생"],
        "one": ["bubble.restarted:야생", "bubble.installing:팰"],
        "two": ["bubble.provision_done:팰", "bubble.restarted:야생"],
        # 설치처럼 오래 기다린 일은 닫을 때까지 남는다
        "later": ["bubble.provision_done:팰"],
    }


@needs_node
def test_idle_is_mostly_still_and_blinks_only_now_and_then():
    # 사용자 11-11: 대기 중 눈을 너무 자주 깜빡인다. 정적인 칸 반복을 늘린다 (대기 줄의 2~4번 칸이 눈 감는 칸)
    r = run_node("console.log(JSON.stringify({ loop: M.SCENES.idle.loop, gap: M.BLINK_GAP }))")
    assert not {2, 3, 4} & set(r["loop"])
    assert r["gap"][0] >= 15000


@needs_node
def test_quick_results_fade_fast_and_long_waits_or_failures_stay_until_closed():
    # 사용자 11-11: 단순 명령 완료는 금방 지우고, 설치 완료처럼 오래 기다린 일은 사용자가 지울 때까지 둔다.
    # 말풍선을 누르면 앱의 그 화면으로 간다 (target)
    r = run_node(
        SCENARIO
        + """
        const list = () => at().bubbles.map((b) => b.key);
        pet.event('instance.started', { instanceId: 'a', instance: '야생', source: 'discord', userName: '주인님' });
        const quick = at().bubbles[0].target;
        step(5000);
        const afterQuick = list();
        pet.event('provision.progress', { instance: '팰', done: false });
        pet.event('provision.progress', { instance: '팰', done: true });
        pet.event('instance.exit', { instanceId: 'b', instance: '테라', kind: 'crash', restartInSecs: null });
        const targets = at().bubbles.map((b) => b.target);
        step(30 * 60 * 1000, 10000);
        const longAfter = list();
        pet.click();
        const afterPetClick = list();
        pet.dismiss('srv:b');
        const afterClose = list();
        console.log(JSON.stringify({ quick, afterQuick, targets, longAfter, afterPetClick, afterClose }));
        """
    )
    assert r == {
        "quick": "server:a",
        "afterQuick": [],
        "targets": ["server:b", "provision:팰"],
        "longAfter": ["bubble.crash", "bubble.provision_done"],
        "afterPetClick": ["bubble.crash", "bubble.provision_done"],
        "afterClose": ["bubble.provision_done"],
    }


@needs_node
def test_working_dots_blink_in_the_colour_of_the_state_being_left():
    # 사용자 11-11 (앱 전체 규칙): 진행 중 점은 떠나는 상태의 색으로 깜빡인다. 정지에서 시작 = 회색, 켜진 것을 끄기 = 초록,
    # 복구(크래시 뒤 다시 켜기 등 잠깐 끊김) = 노랑
    r = run_node(
        SCENARIO
        + """
        const from = () => [at().bubbles[0].key, at().bubbles[0].from];
        pet.event('instance.exit', { instanceId: 'a', instance: '야생', kind: 'crash', restartInSecs: 30 });
        const repair = from();
        pet.event('provision.progress', { instance: '팰', done: false });
        const install = from();
        pet.event('schedule.warn', { instanceId: 'c', instance: '테라', action: 'stop', minutesLeft: 5 });
        const scheduled = from();
        console.log(JSON.stringify({ repair, install, scheduled }));
        """
    )
    assert r == {
        "repair": ["bubble.restarting", "recovering"],
        "install": ["bubble.installing", "stopped"],
        "scheduled": ["bubble.schedule_stop", "running"],
    }
