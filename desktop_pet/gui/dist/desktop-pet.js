/* 데스크톱 펫 GUI 번들. 고치지 말고 gui/src·gui/sprites를 고친 뒤 gui/build.py로 다시 만든다 */
(function () {
'use strict';
var module = { exports: {} };
/*
 * 데스크톱 펫 상태 기계: 데몬 이벤트·마우스·시간 → 지금 그릴 장면과 말풍선.
 * 화면(pet.js)과 따로 둬서 node로 시험한다 (test_desktop_pet.py). 시계와 난수는 밖에서 넣는다.
 *
 * 사용자 지정 (2026-11-11): 평시 평상 스프라이트 / 10분 이상 대기면 가끔 빗자루질 / 3시간 이상 대기면 잠 / 마우스를 올리면 점프.
 * 나머지(서버 고장·설치·준비 등)는 데몬 이벤트에 맞춰 정했다.
 */
(function (root) {
    'use strict';

    var MIN = 60 * 1000;
    var SWEEP_AFTER = 10 * MIN; // 이만큼 아무 일이 없으면 가끔 빗자루질
    var SLEEP_AFTER = 3 * 60 * MIN; // 이만큼 아무 일이 없으면 잠
    var SWEEP_GAP = [90 * 1000, 240 * 1000]; // 빗자루질 사이 간격 (무작위)
    var BLINK_GAP = [15 * 1000, 40 * 1000]; // 평상시 눈 깜빡임 간격 (무작위)
    var HOVER_GAP = 3 * 1000; // 점프는 이만큼에 한 번
    var REPAIR_GRACE = 3 * MIN; // 다시 켜기 대기 + 이만큼이 지나도 결과가 없으면 고치기를 그만둔다
    var COOK_STALE = 30 * MIN; // 설치 진행이 이만큼 끊기면 요리를 그만둔다
    /** 단순한 일(켜기·끄기·다시 켜기·예고) 말풍선은 금방 지운다. 오래 기다린 일(설치)·실패는 사용자가 닫을 때까지 둔다 (사용자 11-11) */
    var BUBBLE_MS = 4000;
    var STICKY_KEYS = ['bubble.provision_done'];
    /** 들고 있는 말풍선 수 (넘치면 끝난 일 중 오래된 것부터 뺀다). 화면에는 앞의 몇 개만 겹쳐 보인다 */
    var MAX_BUBBLES = 8;

    function pp(a, b) {
        // a..b..a+1 (왕복)
        var out = [];
        for (var i = a; i <= b; i++) out.push(i);
        for (var j = b - 1; j > a; j--) out.push(j);
        return out;
    }
    function range(a, b) {
        var out = [];
        for (var i = a; i <= b; i++) out.push(i);
        return out;
    }
    function repeat(seq, n) {
        var out = [];
        for (var i = 0; i < n; i++) out = out.concat(seq);
        return out;
    }

    /*
     * 장면: frames = 스프라이트 띠의 칸 수, intro = 한 번만 도는 칸, loop = 되풀이하는 칸, ms = 한 칸 시간.
     * once 장면은 intro만 돌고 끝난다(그 뒤 기본 장면으로). 수리·빗자루질만 빠르게, 나머지는 느리게 (사용자 11-11)
     */
    var SCENES = {
        // 대기 줄의 2~4번 칸은 눈을 감는다: 대기는 뜬 눈 칸(0·1)만 천천히 오가고, 깜빡임은 가끔 blink로
        idle: { frames: 6, intro: [], loop: [0, 0, 0, 0, 1, 1, 1, 1], ms: 400 },
        blink: { frames: 8, intro: range(0, 7), loop: null, ms: 110 },
        jump: { frames: 5, intro: range(0, 4), loop: null, ms: 120 },
        wave: { frames: 4, intro: repeat(pp(0, 3), 2), loop: null, ms: 200 },
        clasp: { frames: 6, intro: repeat(pp(0, 5), 2), loop: null, ms: 220 },
        think: { frames: 6, intro: repeat(pp(0, 5), 2), loop: null, ms: 260 },
        scratch: { frames: 6, intro: repeat(pp(0, 5), 2), loop: null, ms: 220 },
        collapse: { frames: 12, intro: range(0, 8), loop: pp(9, 11), ms: 260, loopMs: 420 },
        repair: { frames: 12, intro: [], loop: pp(0, 11), ms: 150 },
        cooking: { frames: 12, intro: [], loop: pp(0, 11), ms: 280 },
        served: { frames: 12, intro: repeat(pp(0, 11), 2), loop: null, ms: 300 },
        sleeping: { frames: 12, intro: [], loop: pp(0, 11), ms: 420 },
        waking: { frames: 12, intro: range(0, 8).concat(pp(9, 11)), loop: null, ms: 280 },
        sweeping: { frames: 12, intro: repeat(pp(0, 11), 2), loop: null, ms: 130 },
    };

    /** 장면이 시작한 뒤 elapsed ms에 그릴 칸. once 장면이 끝났으면 -1 */
    function frameAt(name, elapsed) {
        var s = SCENES[name];
        var introMs = s.intro.length * s.ms;
        if (elapsed < introMs) return s.intro[Math.floor(elapsed / s.ms)];
        if (!s.loop) return -1;
        var step = s.loopMs || s.ms;
        return s.loop[Math.floor((elapsed - introMs) / step) % s.loop.length];
    }

    /** 다음 칸으로 넘어갈 때까지 남은 ms (once 장면이 끝났으면 Infinity) */
    function nextFrameIn(name, elapsed) {
        var s = SCENES[name];
        var introMs = s.intro.length * s.ms;
        if (elapsed < introMs) return s.ms - (elapsed % s.ms);
        if (!s.loop) return Infinity;
        var step = s.loopMs || s.ms;
        return step - ((elapsed - introMs) % step);
    }

    /** once 장면의 길이 (되풀이 장면은 Infinity) */
    function sceneLength(name) {
        var s = SCENES[name];
        return s.loop ? Infinity : s.intro.length * s.ms;
    }

    /** 켜고 끈 일은 어디서 시켰든 말풍선으로 알린다(앱 안에서 누른 것도). 자동 재시작은 '복구 완료'가 따로 알린다 */
    var SILENT_SOURCES = ['restart'];

    /** 바쁜 장면: 이 동안에는 마우스·사소한 일로 장면을 바꾸지 않는다 */
    var BUSY = ['collapse', 'repair', 'cooking'];

    function between(random, pair) {
        return pair[0] + random() * (pair[1] - pair[0]);
    }

    function createMachine(opts) {
        var now = (opts && opts.now) || Date.now;
        var random = (opts && opts.random) || Math.random;
        var t0 = now();
        var st = {
            lastActivity: t0,
            collapsed: {}, // instanceId → true
            repairing: {}, // instanceId → 그만둘 시각
            cooking: {}, // instance → 마지막 진행 시각
            once: null, // {scene, at}
            base: 'idle',
            baseAt: t0,
            nextSweep: t0 + SWEEP_AFTER + between(random, SWEEP_GAP),
            nextBlink: t0 + between(random, BLINK_GAP),
            lastHover: -Infinity,
            bubbles: [], // 작업마다 하나, 말한 순서: {id, key, vars, state, at, until, during}
        };

        function any(map) {
            for (var k in map) if (Object.prototype.hasOwnProperty.call(map, k)) return true;
            return false;
        }

        function play(scene, force) {
            if (!force && BUSY.indexOf(currentBase()) >= 0) return;
            st.once = { scene: scene, at: now() };
        }

        /**
         * 말풍선: 대사가 아니라 할 일·한 일의 짧은 요약. 작업(id)마다 하나를 두고 같은 작업은 제자리에서 바뀐다.
         * state는 done(마친 일)·working(하는 중·할 일)·failed. during([표, 키])을 주면 그 일(수리·요리)이 이어지는 동안 남는다.
         * from은 하는 중인 일이 떠나는 상태(점 색): stopped(회색)·running(초록)·recovering(노랑, 잠깐 끊김) — 앱 전체 규칙.
         * target은 누르면 열 앱 화면: 서버(`server:<id>`), 설치한 서버 이름(`provision:<이름>`, 화면이 id를 찾는다), 설정(`settings`)
         */
        function targetOf(id) {
            var at = id.indexOf(':');
            var kind = at < 0 ? id : id.slice(0, at);
            var rest = at < 0 ? '' : id.slice(at + 1);
            if (kind === 'prov') return 'provision:' + rest;
            if (kind === 'update') return 'settings';
            return rest ? 'server:' + rest : null;
        }

        function say(id, key, vars, state, during, from) {
            var t = now();
            st.bubbles = st.bubbles.filter(function (b) {
                return b.id !== id;
            });
            st.bubbles.push({
                id: id,
                key: key,
                vars: vars || {},
                state: state,
                at: t,
                until: during || state === 'failed' || STICKY_KEYS.indexOf(key) >= 0 ? Infinity : t + BUBBLE_MS,
                during: during || null,
                target: targetOf(id),
                from: state === 'working' ? from || 'stopped' : null,
            });
            // 넘치면 끝난 일 중 오래된 것부터 뺀다 (하는 중인 일은 끝날 때까지 둔다)
            while (st.bubbles.length > MAX_BUBBLES) {
                var drop = 0;
                for (var i = 0; i < st.bubbles.length; i++) {
                    if (st.bubbles[i].state !== 'working') {
                        drop = i;
                        break;
                    }
                }
                st.bubbles.splice(drop, 1);
            }
        }

        /** 일이 있었다. 자고 있었으면 깬다 */
        function activity() {
            var asleep = currentBase() === 'sleeping';
            st.lastActivity = now();
            st.nextSweep = st.lastActivity + SWEEP_AFTER + between(random, SWEEP_GAP);
            if (asleep) play('waking', true);
        }

        function expire() {
            var t = now();
            for (var id in st.repairing) if (st.repairing[id] <= t) delete st.repairing[id];
            for (var key in st.cooking) if (st.cooking[key] + COOK_STALE <= t) delete st.cooking[key];
            st.bubbles = st.bubbles.filter(function (b) {
                if (b.during) return Object.prototype.hasOwnProperty.call(st[b.during[0]], b.during[1]);
                return b.until > t;
            });
            if (st.once && now() - st.once.at >= sceneLength(st.once.scene)) st.once = null;
        }

        /** 이어지는 상태로 정한 장면 (한 번 도는 장면 아래에 깔린다) */
        function currentBase() {
            var t = now();
            if (any(st.collapsed)) return 'collapse';
            if (any(st.repairing)) return 'repair';
            if (any(st.cooking)) return 'cooking';
            var quiet = t - st.lastActivity;
            if (quiet >= SLEEP_AFTER) return 'sleeping';
            return 'idle';
        }

        function tick() {
            expire();
            var t = now();
            var base = currentBase();
            if (base !== st.base) {
                st.base = base;
                st.baseAt = t;
            }
            if (st.once || base !== 'idle') return;
            // 10분 넘게 조용하면 가끔 빗자루질, 아니면 가끔 눈 깜빡임
            if (t - st.lastActivity >= SWEEP_AFTER && t >= st.nextSweep) {
                st.nextSweep = t + between(random, SWEEP_GAP);
                play('sweeping');
            } else if (t >= st.nextBlink) {
                st.nextBlink = t + between(random, BLINK_GAP);
                play('blink');
            }
        }

        function event(type, data) {
            data = data || {};
            var id = data.instanceId;
            var name = data.instance || '';
            // 시킨 쪽: 출처, 이름(디스코드 표시 이름·원격 PC 이름), 장소(디스코드 서버 이름)
            var who = { source: data.source };
            if (data.userName) who.user = data.userName;
            if (data.guildName) who.place = data.guildName;
            var told = SILENT_SOURCES.indexOf(data.source) < 0;
            switch (type) {
                case 'instance.started':
                    activity();
                    delete st.collapsed[id];
                    delete st.repairing[id];
                    if (told) say('srv:' + id, 'bubble.started', { server: name, who: who }, 'done');
                    play('think');
                    break;
                case 'instance.ready':
                    activity();
                    play(data.ok === false ? 'scratch' : 'wave');
                    if (data.ok === false) say('srv:' + id, 'bubble.not_ready', { server: name }, 'failed');
                    break;
                case 'instance.stopped':
                    activity();
                    delete st.collapsed[id];
                    delete st.repairing[id];
                    if (told) say('srv:' + id, 'bubble.stopped', { server: name, who: who }, 'done');
                    play('clasp');
                    break;
                case 'instance.exit':
                    if (data.kind !== 'crash' && data.kind !== 'unknown_exit' && data.kind !== 'start_failed') break;
                    activity();
                    st.once = null;
                    if (typeof data.restartInSecs === 'number') {
                        st.repairing[id] = now() + data.restartInSecs * 1000 + REPAIR_GRACE;
                        say('srv:' + id, 'bubble.restarting', { server: name }, 'working', ['repairing', id], 'recovering');
                    } else {
                        st.collapsed[id] = true;
                        say('srv:' + id, data.kind === 'start_failed' ? 'bubble.start_failed' : 'bubble.crash', { server: name }, 'failed');
                    }
                    break;
                case 'instance.restarted':
                    activity();
                    delete st.repairing[id];
                    say('srv:' + id, 'bubble.restarted', { server: name }, 'done');
                    play('wave', true);
                    break;
                case 'instance.restart_failed':
                    activity();
                    delete st.repairing[id];
                    st.collapsed[id] = true;
                    st.once = null;
                    say('srv:' + id, 'bubble.restart_failed', { server: name }, 'failed');
                    break;
                case 'instance.restart_cancelled':
                    delete st.repairing[id];
                    break;
                case 'provision.progress': {
                    var key = data.instance;
                    if (!key) break;
                    activity();
                    if (data.done) {
                        var wasCooking = Object.prototype.hasOwnProperty.call(st.cooking, key);
                        delete st.cooking[key];
                        if (data.error) {
                            say('prov:' + key, 'bubble.provision_failed', { server: key }, 'failed');
                            play('scratch', true);
                        } else if (wasCooking) {
                            say('prov:' + key, 'bubble.provision_done', { server: key }, 'done');
                            play('served', true);
                        }
                    } else {
                        st.cooking[key] = now();
                        say('prov:' + key, 'bubble.installing', { server: key }, 'working', ['cooking', key], 'stopped');
                    }
                    break;
                }
                case 'backup.done':
                    if (data.ok === false) {
                        activity();
                        say('backup:' + id, 'bubble.backup_failed', { server: name }, 'failed');
                        play('scratch');
                    }
                    break;
                case 'schedule.warn':
                    activity();
                    say('schedule:' + id, 'bubble.schedule_' + (['restart', 'stop', 'update'].indexOf(data.action) >= 0 ? data.action : 'other'), {
                        server: name,
                        minutes: data.minutesLeft,
                    }, 'working', null, 'running');
                    play('think');
                    break;
                case 'update.available':
                    say('update', 'bubble.update_available', {}, 'done');
                    play('clasp');
                    break;
                default:
                    break;
            }
            tick();
        }

        /** 마우스를 올렸다: 점프. 자는 중·빗자루질 중에는 그대로 둔다(눌러야 깨거나 멈춘다). 바쁜 장면에서도 그대로 */
        function hover() {
            var t = now();
            var base = currentBase();
            if (base === 'sleeping' || (st.once && st.once.scene === 'sweeping')) return;
            st.lastActivity = t;
            if (BUSY.indexOf(base) >= 0 || t - st.lastHover < HOVER_GAP) return;
            if (st.once && st.once.scene !== 'blink') return;
            st.lastHover = t;
            play('jump');
        }

        /** 눌렀다: 쓰러진 것은 일으키고, 자면 깨우고, 빗자루질은 멈춘다(앱은 셸이 연다). 말풍선은 닫기 버튼으로만 닫는다 */
        function click() {
            st.collapsed = {};
            if (st.once && st.once.scene === 'sweeping') st.once = null;
            activity();
            tick();
        }

        /** 말풍선 하나를 닫았다 (닫기 버튼, 또는 눌러서 그 화면으로 갔다) */
        function dismiss(id) {
            st.bubbles = st.bubbles.filter(function (b) {
                return b.id !== id;
            });
        }

        /** 지금 그릴 것: 장면 이름, 그 장면이 시작한 시각, 말풍선 */
        function view() {
            expire();
            // 끝난 일(마침·실패)을 위로, 하는 중인 일을 아래로. 같은 쪽에서는 새것이 위
            // st.bubbles는 말한 순서라 뒤집으면 새것이 앞이다 (같은 때 말한 것도)
            var b = st.bubbles
                .slice()
                .reverse()
                .sort(function (x, y) {
                    return (x.state === 'working' ? 1 : 0) - (y.state === 'working' ? 1 : 0);
                })
                .map(function (x) {
                    return { id: x.id, key: x.key, vars: x.vars, state: x.state, at: x.at, target: x.target, from: x.from };
                });
            if (st.once) return { scene: st.once.scene, at: st.once.at, bubbles: b };
            return { scene: st.base, at: st.baseAt, bubbles: b };
        }

        tick();
        return { event: event, hover: hover, click: click, dismiss: dismiss, tick: tick, view: view };
    }

    var api = {
        SCENES: SCENES,
        frameAt: frameAt,
        nextFrameIn: nextFrameIn,
        sceneLength: sceneLength,
        createMachine: createMachine,
        SWEEP_AFTER: SWEEP_AFTER,
        SLEEP_AFTER: SLEEP_AFTER,
        BLINK_GAP: BLINK_GAP,
    };
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SabaPetMachine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

var M = module.exports;
var SPRITES = {"blink":{"file":"blink.webp","frames":8},"clasp":{"file":"clasp.webp","frames":6},"collapse":{"file":"collapse.webp","frames":12},"cooking":{"file":"cooking.webp","frames":12},"idle":{"file":"idle.webp","frames":6},"jump":{"file":"jump.webp","frames":5},"repair":{"file":"repair.webp","frames":12},"scratch":{"file":"scratch.webp","frames":6},"served":{"file":"served.webp","frames":12},"sleeping":{"file":"sleeping.webp","frames":12},"sweeping":{"file":"sweeping.webp","frames":12},"think":{"file":"think.webp","frames":6},"waking":{"file":"waking.webp","frames":12},"wave":{"file":"wave.webp","frames":4}};
/*
 * 데스크톱 펫 화면 (slot `Desktop.overlay`). build.py가 machine.js(M)·스프라이트 표(SPRITES)와 한 파일로 묶는다.
 * React는 앱이 건넨 window.React(19)를 쓴다. 창 일(누르면 앱 열기·끌기·우클릭 메뉴)은 앱의 오버레이 창이 맡는다.
 */
/* global M, SPRITES */
var React = window.React;
var h = React.createElement;

/** 그리는 크기: 원본 칸(192×208)의 2/3. 화면 배율 150%에서 원본 그대로 찍힌다 */
var CELL_W = 192;
var CELL_H = 208;
var SCALE = 2 / 3;
/** 말풍선 높이와, 여러 개를 겹쳐 쌓을 때 뒤 말풍선이 삐져나오는 거리·줄어드는 비율 (pet.css와 맞춘다) */
var BUBBLE_H = 42;
var BUBBLE_STEP = 6;
var BUBBLE_SHRINK = 0.06;
/** 칸이 바뀌지 않아도 이만큼에 한 번은 상태 기계를 돌린다 (시간으로 바뀌는 잠·빗자루질·말풍선) */
var TICK_MS = 250;

/** 말한 시각 (시스템 시간 형식) */
function clock(at) {
    try {
        return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (_e) {
        return '';
    }
}

/** 움직임을 줄이라고 한 시스템이면 말풍선 움직임을 뺀다 */
function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

/** 사라지는 말풍선을 이만큼 더 그려 둔다 (pet.css saba-pet-leave와 맞춘다) */
var LEAVE_MS = 420;
/** 겹쳐 보이는 말풍선 수 (나머지는 앞의 것을 닫으면 올라온다) */
var SHOWN_BUBBLES = 3;
/** 누른 채 이만큼 움직였으면 누르기가 아니라 끌기 (셸 DesktopOverlay와 같다, px) */
var DRAG_THRESHOLD = 4;

/**
 * 말풍선 두 줄. 첫 줄: 한 일(선명)과 시킨 사람(흐림, 이름이 없으면 출처).
 * 둘째 줄(작고 흐림): 시각, 이름이 있으면 출처, 장소(디스코드 서버 이름).
 * 움직임: 나타날 때 아래에서 튀어 오르고, 같은 작업의 내용이 바뀌면 너비가 늘거나 줄며 글자가 갈아 끼워지고,
 * 끝나거나 실패하면 한 번 통 튀며 점에서 물결이 퍼진다. 자리를 바꾸면 튕기듯 미끄러지고, 사라질 때는 위로 흩어진다.
 * 맨 앞 말풍선: 올리면 오른쪽 위에 닫기 버튼, 누르면 앱의 그 화면으로 간다(셸의 "누르면 앱 열기" 대신)
 */
function Bubble(props) {
    var t = props.t;
    var bubble = props.bubble;
    var ref = React.useRef(null);
    var last = React.useRef(null);
    var who = bubble.vars.who;
    var source = who ? t('source.' + (who.source || 'external'), { defaultValue: who.source || '' }) : '';
    var by = who ? who.user || source : '';
    var meta = [clock(bubble.at)];
    if (who && who.user && source) meta.push(source);
    if (who && who.place) meta.push(who.place);
    var front = props.index === 0 && !props.leaving;
    var sig = bubble.key + '|' + bubble.state + '|' + (front ? 'front' : 'back');

    React.useLayoutEffect(
        function () {
            var el = ref.current;
            if (!el || props.leaving) return;
            var prev = last.current;
            el.style.width = '';
            var natural = el.getBoundingClientRect().width;
            if (front && prev && prev.front && !reducedMotion() && typeof el.animate === 'function') {
                // 같은 작업의 내용이 바뀌었다: 너비를 이어서 바꾸고, 끝났거나 실패했으면 한 번 튄다
                if (Math.abs(prev.width - natural) > 1) {
                    el.animate([{ width: prev.width + 'px' }, { width: natural + 'px' }], {
                        duration: 420,
                        easing: 'cubic-bezier(0.34, 1.4, 0.64, 1)',
                    });
                }
                if (prev.state !== bubble.state && bubble.state !== 'working') {
                    el.animate([{ scale: '1' }, { scale: '1.08' }, { scale: '0.98' }, { scale: '1' }], {
                        duration: 520,
                        easing: 'ease-out',
                    });
                }
            }
            last.current = { width: natural, state: bubble.state, front: front };
            if (front && props.onWidth) props.onWidth(bubble.id, natural);
        },
        [sig],
    );

    var style = {
        transform: 'translateY(' + props.index * BUBBLE_STEP + 'px) scale(' + (1 - props.index * BUBBLE_SHRINK) + ')',
        zIndex: props.leaving ? 0 : props.count - props.index,
    };
    // 사라지는 맨 앞 말풍선은 마지막 너비 그대로 가운데에 둔다
    if (props.leaving && props.width) {
        style.width = props.width + 'px';
        style.left = '50%';
        style.right = 'auto';
        style.marginLeft = -props.width / 2 + 'px';
    }
    var content = bubble.key + '|' + bubble.state;
    var press = React.useRef(null);
    var events = {};
    if (front) {
        events = {
            onPointerDown: function (e) {
                press.current = e.button === 0 ? { x: e.screenX, y: e.screenY } : null;
            },
            onPointerUp: function (e) {
                var p = press.current;
                press.current = null;
                if (!p || e.button !== 0) return;
                if (Math.hypot(e.screenX - p.x, e.screenY - p.y) >= DRAG_THRESHOLD) return;
                e.stopPropagation();
                props.onOpen(bubble);
            },
        };
    }
    var stop = function (e) {
        e.stopPropagation();
    };
    return h(
        'div',
        {
            ref: ref,
            className: 'saba-pet-bubble',
            'data-state': bubble.state,
            'data-from': bubble.from || undefined,
            'data-behind': front ? undefined : 'true',
            'data-leaving': props.leaving ? (props.index === 0 ? 'front' : 'back') : undefined,
            'aria-hidden': front ? undefined : true,
            style: style,
            onPointerDown: events.onPointerDown,
            onPointerUp: events.onPointerUp,
        },
        // 상태가 바뀌면 점을 새로 그려 스며들게, 글자는 새로 그려 아래에서 올라오게 한다
        h('span', { key: 'dot-' + bubble.state, className: 'saba-pet-dot', 'aria-hidden': true }),
        h(
            'span',
            { key: 'line-' + content, className: 'saba-pet-line' },
            h('span', { className: 'saba-pet-text' }, t(bubble.key, bubble.vars)),
            by ? h('span', { className: 'saba-pet-by' }, by) : null,
        ),
        h('span', { key: 'meta-' + content, className: 'saba-pet-meta' }, meta.filter(Boolean).join(' · ')),
        front
            ? h(
                  'button',
                  {
                      key: 'close',
                      type: 'button',
                      className: 'saba-pet-close',
                      'aria-label': t('close'),
                      title: t('close'),
                      // 끌기·앱 열기로 번지지 않게. 닫기는 click으로: 마우스와 키보드(Enter·Space) 모두
                      onPointerDown: stop,
                      onPointerUp: stop,
                      onClick: function (e) {
                          e.stopPropagation();
                          props.onClose(bubble.id);
                      },
                  },
                  h(
                      'svg',
                      { viewBox: '0 0 10 10', width: 8, height: 8, 'aria-hidden': true },
                      h('path', { d: 'M1.5 1.5l7 7M8.5 1.5l-7 7', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' }),
                  ),
              )
            : null,
    );
}

/** 말풍선 더미: 지금 말풍선과, 막 사라져 흩어지는 중인 말풍선 */
function Bubbles(props) {
    var shown = React.useRef({}); // id → {bubble, index}
    var leaving = React.useRef({}); // id → {bubble, index, since}
    var widths = React.useRef({});
    var now = Date.now();
    var current = {};
    var bubbles = props.bubbles.slice(0, SHOWN_BUBBLES);
    bubbles.forEach(function (b, i) {
        current[b.id] = { bubble: b, index: i };
    });
    var id;
    for (id in shown.current) {
        if (!current[id] && !leaving.current[id]) {
            leaving.current[id] = { bubble: shown.current[id].bubble, index: shown.current[id].index, since: now };
        }
    }
    for (id in leaving.current) {
        if (current[id] || now - leaving.current[id].since >= LEAVE_MS || reducedMotion()) delete leaving.current[id];
    }
    shown.current = current;

    var gone = Object.keys(leaving.current).map(function (k) {
        return leaving.current[k];
    });
    if (!bubbles.length && !gone.length) return null;
    var count = bubbles.length;
    var onWidth = function (bid, w) {
        widths.current[bid] = w;
    };
    return h(
        'div',
        {
            className: 'saba-pet-bubbles',
            role: 'status',
            style: {
                height: count ? BUBBLE_H + (count - 1) * BUBBLE_STEP + 'px' : BUBBLE_H + 'px',
                minWidth: !count && gone.length ? (widths.current[gone[0].bubble.id] || 0) + 'px' : undefined,
            },
        },
        bubbles
            .map(function (b, i) {
                return h(Bubble, {
                    key: b.id,
                    t: props.t,
                    bubble: b,
                    index: i,
                    count: count,
                    onWidth: onWidth,
                    onOpen: props.onOpen,
                    onClose: props.onClose,
                });
            })
            .concat(
                gone.map(function (g) {
                    return h(Bubble, {
                        key: g.bubble.id,
                        t: props.t,
                        bubble: g.bubble,
                        index: g.index,
                        count: count,
                        leaving: true,
                        width: widths.current[g.bubble.id],
                    });
                }),
            ),
    );
}

/** 받지 못한 그림을 다시 받기까지 */
var SHEET_RETRY_MS = 5000;
/** 장면 → 그릴 수 있게 받아 풀어 둔 그림 띠 URL */
var sheets = {};
/** 장면 → 그림을 받기 시작한 때 (받지 못했으면 SHEET_RETRY_MS 뒤에 다시) */
var asked = {};

/**
 * 장면의 그림 띠(manifest `gui.assets`)는 그 장면이 처음 나올 때 앱에서 받는다(host.assetUrl).
 * 다 풀린 뒤에 그려 빈 칸이 보이지 않게 한다
 */
function loadSheet(host, scene, onReady) {
    var sprite = SPRITES[scene];
    if (!sprite || sheets[scene] || Date.now() - (asked[scene] || 0) < SHEET_RETRY_MS) return;
    asked[scene] = Date.now();
    host.assetUrl(sprite.file).then(
        function (url) {
            if (!url) return;
            var ready = function () {
                sheets[scene] = url;
                onReady();
            };
            var img = new Image();
            img.src = url;
            if (typeof img.decode === 'function') img.decode().then(ready, ready);
            else img.onload = img.onerror = ready;
        },
        function () {},
    );
}

function Sprite(props) {
    var sheet = SPRITES[props.scene];
    var url = sheets[props.scene];
    if (!sheet || !url || props.frame < 0) return null;
    var w = CELL_W * SCALE;
    var hgt = CELL_H * SCALE;
    return h('div', {
        className: 'saba-pet-sprite',
        'data-scene': props.scene,
        style: {
            width: w + 'px',
            height: hgt + 'px',
            backgroundImage: 'url(' + url + ')',
            backgroundSize: sheet.frames * w + 'px ' + hgt + 'px',
            backgroundPosition: -props.frame * w + 'px 0',
        },
    });
}

function Pet(props) {
    var host = props.host;
    var t = host.t;
    var machineRef = React.useRef(null);
    if (!machineRef.current) machineRef.current = M.createMachine();
    var machine = machineRef.current;
    var _a = React.useState(0);
    var setNow = _a[1];
    /** 마지막으로 그린 장면과 칸: 새 장면의 그림을 받는 동안 그대로 둔다 */
    var drawn = React.useRef(null);

    var view = machine.view();
    var elapsed = Date.now() - view.at;
    var frame = M.frameAt(view.scene, elapsed);
    // 다음 칸이 바뀌는 때에 맞춰 다시 그린다 (늘 떠 있는 창이라 매 화면 그리기 대신)
    // 한 번 도는 장면이 끝났으면 곧바로 다음 장면을 고른다
    var delay = frame < 0 ? 16 : Math.max(16, Math.min(TICK_MS, M.nextFrameIn(view.scene, elapsed)));
    React.useEffect(function () {
        var timer = setTimeout(function () {
            machine.tick();
            setNow(Date.now());
        }, delay);
        return function () {
            clearTimeout(timer);
        };
    });

    // 지금 장면의 그림을 아직 받지 않았으면 받는다
    React.useEffect(function () {
        loadSheet(host, view.scene, function () {
            setNow(Date.now());
        });
    });

    // 데몬 이벤트
    React.useEffect(
        function () {
            return host.on('*', function (data, type) {
                machine.event(type, data);
                setNow(Date.now());
            });
        },
        [host, machine],
    );

    // 한 번 도는 장면이 막 끝났으면 다음 장면을 고르기 전까지 그 마지막 칸을 둔다
    if (frame < 0) {
        var s = M.SCENES[view.scene];
        frame = s.intro[s.intro.length - 1];
    }
    if (sheets[view.scene]) drawn.current = { scene: view.scene, frame: frame };
    var shown = drawn.current;

    return h(
        'div',
        {
            className: 'saba-pet',
            onMouseEnter: function () {
                machine.hover();
                setNow(Date.now());
            },
            onClick: function () {
                machine.click();
                setNow(Date.now());
            },
        },
        h(Bubbles, {
            t: t,
            bubbles: view.bubbles,
            // 누르면 앱의 그 화면으로 가고 그 말풍선은 닫는다. 설치한 서버는 이름으로 id를 찾는다
            onOpen: function (bubble) {
                var route = bubble.target || 'servers';
                if (route.indexOf('provision:') === 0) {
                    var name = route.slice('provision:'.length);
                    var server = (host.servers() || []).filter(function (x) {
                        return x.name === name;
                    })[0];
                    route = server ? 'server:' + server.id : 'servers';
                }
                host.openApp(route);
                machine.dismiss(bubble.id);
                setNow(Date.now());
            },
            onClose: function (id) {
                machine.dismiss(id);
                setNow(Date.now());
            },
        }),
        shown ? h(Sprite, { scene: shown.scene, frame: shown.frame }) : null,
    );
}

window.SabaExtDesktopPet = {
    registerSlots: function () {
        return { 'Desktop.overlay': Pet };
    },
};

})();
