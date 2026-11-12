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

        /** 마우스를 올렸다: 점프 (자고 있었으면 깬다). 바쁜 장면에서는 그대로 */
        function hover() {
            var t = now();
            var base = currentBase();
            if (base === 'sleeping') {
                activity();
                return tick();
            }
            st.lastActivity = t;
            if (BUSY.indexOf(base) >= 0 || t - st.lastHover < HOVER_GAP) return;
            if (st.once && st.once.scene !== 'blink' && st.once.scene !== 'sweeping') return;
            st.lastHover = t;
            play('jump');
        }

        /** 눌렀다: 쓰러진 것은 일으킨다(앱은 셸이 연다). 말풍선은 닫기 버튼으로만 닫는다 */
        function click() {
            st.collapsed = {};
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
