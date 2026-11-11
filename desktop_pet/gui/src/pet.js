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

/**
 * 말풍선 두 줄. 첫 줄: 한 일(선명)과 시킨 사람(흐림, 이름이 없으면 출처).
 * 둘째 줄(작고 흐림): 시각, 이름이 있으면 출처, 장소(디스코드 서버 이름)
 */
function Bubble(props) {
    var t = props.t;
    var bubble = props.bubble;
    var who = bubble.vars.who;
    var source = who ? t('source.' + (who.source || 'external'), { defaultValue: who.source || '' }) : '';
    var by = who ? who.user || source : '';
    var meta = [clock(bubble.at)];
    if (who && who.user && source) meta.push(source);
    if (who && who.place) meta.push(who.place);
    return h(
        'div',
        {
            className: 'saba-pet-bubble',
            'data-state': bubble.state,
            'data-behind': props.index > 0 ? 'true' : undefined,
            'aria-hidden': props.index > 0 ? true : undefined,
            style: {
                transform: 'translateY(' + props.index * BUBBLE_STEP + 'px) scale(' + (1 - props.index * BUBBLE_SHRINK) + ')',
                zIndex: props.count - props.index,
            },
        },
        h('span', { className: 'saba-pet-dot', 'aria-hidden': true }),
        h(
            'span',
            { className: 'saba-pet-line' },
            h('span', { className: 'saba-pet-text' }, t(bubble.key, bubble.vars)),
            by ? h('span', { className: 'saba-pet-by' }, by) : null,
        ),
        h(
            'span',
            { className: 'saba-pet-meta' },
            meta.filter(Boolean).join(' · '),
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
        view.bubbles.length
            ? h(
                  'div',
                  {
                      className: 'saba-pet-bubbles',
                      role: 'status',
                      style: { height: BUBBLE_H + (view.bubbles.length - 1) * BUBBLE_STEP + 'px' },
                  },
                  view.bubbles.map(function (b, i) {
                      return h(Bubble, { key: b.id, t: t, bubble: b, index: i, count: view.bubbles.length });
                  }),
              )
            : null,
        h(Sprite, { scene: view.scene, frame: frame }),
    );
}

window.SabaExtDesktopPet = {
    registerSlots: function () {
        return { 'Desktop.overlay': Pet };
    },
};
