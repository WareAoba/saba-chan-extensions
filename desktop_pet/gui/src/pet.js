/*
 * 데스크톱 펫 화면 (slot `Desktop.overlay`). build.py가 machine.js(M)·스프라이트(SPRITES)와 한 파일로 묶는다.
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

function Sprite(props) {
    var sheet = SPRITES[props.scene];
    if (!sheet || props.frame < 0) return null;
    var w = CELL_W * SCALE;
    var hgt = CELL_H * SCALE;
    return h('div', {
        className: 'saba-pet-sprite',
        'data-scene': props.scene,
        style: {
            width: w + 'px',
            height: hgt + 'px',
            backgroundImage: 'url(' + sheet.url + ')',
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
        h(Sprite, { scene: view.scene, frame: frame }),
    );
}

window.SabaExtDesktopPet = {
    registerSlots: function () {
        return { 'Desktop.overlay': Pet };
    },
};
