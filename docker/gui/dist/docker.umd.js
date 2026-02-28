var SabaExtDocker = (() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __commonJS = (cb, mod) => function __require() {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // ../../saba-chan-extensions/docker/gui/dist/_shims/react.js
  var require_react = __commonJS({
    "../../saba-chan-extensions/docker/gui/dist/_shims/react.js"(exports, module) {
      module.exports = window.React;
    }
  });

  // ../../saba-chan-extensions/docker/gui/src/index.js
  var index_exports = {};
  __export(index_exports, {
    DockerBadge: () => DockerBadge,
    DockerMiniGauge: () => DockerMiniGauge,
    DockerProvision: () => DockerProvision,
    DockerStatsRow: () => DockerStatsRow,
    DockerTab: () => DockerTab,
    DockerToggle: () => DockerToggle,
    MemoryGauge: () => MemoryGauge,
    registerSlots: () => registerSlots
  });

  // ../../saba-chan-extensions/docker/gui/src/DockerBadge.js
  var import_react = __toESM(require_react());
  var DOCKER_SVG = /* @__PURE__ */ import_react.default.createElement("svg", { xmlns: "http://www.w3.org/2000/svg", viewBox: "0 0 512 512", width: "14", height: "14" }, /* @__PURE__ */ import_react.default.createElement("path", { fill: "currentColor", d: "M507 211.16c-1.42-1.19-14.25-10.94-41.79-10.94a132.55 132.55 0 00-21.61 1.9c-5.22-36.4-35.38-54-36.57-55l-7.36-4.28-4.75 6.9a101.65 101.65 0 00-13.06 30.45c-5 20.7-1.9 40.2 8.55 56.85-12.59 7.14-33 8.8-37.28 9H15.94A15.93 15.93 0 000 262.07a241.25 241.25 0 0014.75 86.83C26.39 379.35 43.72 402 66 415.74 91.22 431.2 132.3 440 178.6 440a344.23 344.23 0 0062.45-5.71 257.44 257.44 0 0081.69-29.73 223.55 223.55 0 0055.57-45.67c26.83-30.21 42.74-64 54.38-94h4.75c29.21 0 47.26-11.66 57.23-21.65a63.31 63.31 0 0015.2-22.36l2.14-6.18z" }), /* @__PURE__ */ import_react.default.createElement("path", { fill: "currentColor", d: "M47.29 236.37H92.4a4 4 0 004-4v-40.48a4 4 0 00-4-4H47.29a4 4 0 00-4 4v40.44a4.16 4.16 0 004 4M109.5 236.37h45.12a4 4 0 004-4v-40.48a4 4 0 00-4-4H109.5a4 4 0 00-4 4v40.44a4.16 4.16 0 004 4M172.9 236.37H218a4 4 0 004-4v-40.48a4 4 0 00-4-4h-45.1a4 4 0 00-4 4v40.44a3.87 3.87 0 004 4M235.36 236.37h45.12a4 4 0 004-4v-40.48a4 4 0 00-4-4h-45.12a4 4 0 00-4 4v40.44a4 4 0 004 4M109.5 178.57h45.12a4.16 4.16 0 004-4v-40.48a4 4 0 00-4-4H109.5a4 4 0 00-4 4v40.44a4.34 4.34 0 004 4M172.9 178.57H218a4.16 4.16 0 004-4v-40.48a4 4 0 00-4-4h-45.1a4 4 0 00-4 4v40.44a4 4 0 004 4M235.36 178.57h45.12a4.16 4.16 0 004-4v-40.48a4.16 4.16 0 00-4-4h-45.12a4 4 0 00-4 4v40.44a4.16 4.16 0 004 4M235.36 120.53h45.12a4 4 0 004-4V76a4.16 4.16 0 00-4-4h-45.12a4 4 0 00-4 4v40.44a4.17 4.17 0 004 4M298.28 236.37h45.12a4 4 0 004-4v-40.48a4 4 0 00-4-4h-45.12a4 4 0 00-4 4v40.44a4.16 4.16 0 004 4" }));
  function DockerBadge({ server }) {
    const isDocker = server?.extension_data?.docker_enabled;
    if (!isDocker) return null;
    return /* @__PURE__ */ import_react.default.createElement("span", { className: "docker-badge", title: "Docker", style: {
      position: "absolute",
      bottom: "-3px",
      right: "-3px",
      width: "18px",
      height: "18px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--bg-card, #1e1e2e)",
      borderRadius: "50%",
      border: "1.5px solid var(--border-subtle, rgba(255,255,255,0.08))",
      zIndex: 2,
      color: "var(--docker-badge-color, #2496ed)"
    } }, DOCKER_SVG);
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerMiniGauge.js
  var import_react3 = __toESM(require_react());

  // ../../saba-chan-extensions/docker/gui/src/MemoryGauge.js
  var import_react2 = __toESM(require_react());
  function MemoryGauge({ percent = 0, usage, size = 100, compact = false }) {
    const pct = Math.min(100, Math.max(0, percent));
    const sweepDeg = 240;
    const startDeg = 180 + (360 - sweepDeg) / 2;
    const toRad = (d) => d * Math.PI / 180;
    const strokeW = compact ? size * 0.08 : size * 0.055;
    const pad = compact ? 2 : 4;
    const radius = size / 2 - strokeW - pad;
    const cx = size / 2;
    const cy = size / 2;
    const angleAt = (p) => startDeg + sweepDeg * p / 100;
    const polar = (deg, r) => ({
      x: cx + r * Math.cos(toRad(deg - 90)),
      y: cy + r * Math.sin(toRad(deg - 90))
    });
    const color = pct < 60 ? "#4caf50" : pct < 85 ? "#ff9800" : "#f44336";
    const arcPath = (from, to, r) => {
      const s = polar(from, r);
      const e = polar(to, r);
      const large = to - from > 180 ? 1 : 0;
      return `M ${s.x} ${s.y} A ${r} ${r} 0 ${large} 1 ${e.x} ${e.y}`;
    };
    const bgArc = arcPath(angleAt(0), angleAt(100), radius);
    const valArc = pct > 0 ? arcPath(angleAt(0), angleAt(pct), radius) : "";
    const ticks = [];
    const majorCount = compact ? 5 : 10;
    const minorPer = compact ? 1 : 4;
    const majorLen = compact ? size * 0.1 : size * 0.11;
    const minorLen = compact ? size * 0.05 : size * 0.055;
    const majorW = compact ? 1 : 1.5;
    const minorW = 0.7;
    for (let i = 0; i <= majorCount; i++) {
      const p = i / majorCount * 100;
      const deg = angleAt(p);
      const outer = polar(deg, radius - strokeW / 2 - 1);
      const inner = polar(deg, radius - strokeW / 2 - 1 - majorLen);
      const tickCol = p >= 80 ? "rgba(244,67,54,0.7)" : "rgba(255,255,255,0.35)";
      ticks.push(
        /* @__PURE__ */ import_react2.default.createElement(
          "line",
          {
            key: `M${i}`,
            x1: outer.x,
            y1: outer.y,
            x2: inner.x,
            y2: inner.y,
            stroke: tickCol,
            strokeWidth: majorW,
            strokeLinecap: "round"
          }
        )
      );
      if (i < majorCount) {
        for (let j = 1; j <= minorPer; j++) {
          const mp = p + j / (minorPer + 1) * (100 / majorCount);
          const md = angleAt(mp);
          const mo = polar(md, radius - strokeW / 2 - 1);
          const mi = polar(md, radius - strokeW / 2 - 1 - minorLen);
          ticks.push(
            /* @__PURE__ */ import_react2.default.createElement(
              "line",
              {
                key: `m${i}_${j}`,
                x1: mo.x,
                y1: mo.y,
                x2: mi.x,
                y2: mi.y,
                stroke: "rgba(255,255,255,0.15)",
                strokeWidth: minorW,
                strokeLinecap: "round"
              }
            )
          );
        }
      }
    }
    const needleDeg = angleAt(pct);
    const needleLen = radius - strokeW / 2 - majorLen - (compact ? 1 : 4);
    const needleTip = polar(needleDeg, needleLen);
    const needleTail = polar(needleDeg + 180, compact ? 3 : size * 0.06);
    const needleW = compact ? 1.2 : 2;
    const pivotR = compact ? 2 : size * 0.04;
    const labels = [];
    if (!compact) {
      const labelR = radius - strokeW / 2 - majorLen - size * 0.1;
      const labelSize = Math.max(7, size * 0.095);
      for (let i = 0; i <= majorCount; i++) {
        const p = i / majorCount * 100;
        const deg = angleAt(p);
        const pos = polar(deg, labelR);
        labels.push(
          /* @__PURE__ */ import_react2.default.createElement(
            "text",
            {
              key: `L${i}`,
              x: pos.x,
              y: pos.y,
              textAnchor: "middle",
              dominantBaseline: "central",
              fill: p >= 80 ? "rgba(244,67,54,0.8)" : "rgba(255,255,255,0.45)",
              fontSize: labelSize,
              fontWeight: p % 20 === 0 ? "600" : "400",
              fontFamily: "inherit"
            },
            Math.round(p)
          )
        );
      }
    }
    let usedLabel = "";
    let totalLabel = "";
    if (usage) {
      const parts = usage.split("/").map((s) => s.trim());
      if (parts.length === 2) {
        usedLabel = parts[0].replace("iB", "").replace("B", "");
        totalLabel = parts[1].replace("iB", "").replace("B", "");
      }
    }
    if (compact) {
      return /* @__PURE__ */ import_react2.default.createElement(
        "div",
        {
          className: "memory-gauge memory-gauge-compact",
          style: { width: size, height: size, position: "relative", flexShrink: 0, marginLeft: "6px", marginRight: "2px", opacity: 0.9 }
        },
        /* @__PURE__ */ import_react2.default.createElement("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}` }, /* @__PURE__ */ import_react2.default.createElement(
          "path",
          {
            d: bgArc,
            fill: "none",
            stroke: "rgba(255,255,255,0.10)",
            strokeWidth: strokeW,
            strokeLinecap: "round"
          }
        ), pct > 0 && /* @__PURE__ */ import_react2.default.createElement(
          "path",
          {
            d: valArc,
            fill: "none",
            stroke: color,
            strokeWidth: strokeW,
            strokeLinecap: "round",
            style: { transition: "all 0.5s ease" }
          }
        ), ticks, /* @__PURE__ */ import_react2.default.createElement(
          "line",
          {
            x1: needleTail.x,
            y1: needleTail.y,
            x2: needleTip.x,
            y2: needleTip.y,
            stroke: "rgba(255,255,255,0.85)",
            strokeWidth: needleW,
            strokeLinecap: "round",
            style: { transition: "all 0.5s ease" }
          }
        ), /* @__PURE__ */ import_react2.default.createElement("circle", { cx, cy, r: pivotR, fill: "rgba(255,255,255,0.6)" }))
      );
    }
    const pctFontSize = Math.max(12, size * 0.18);
    const subFontSize = Math.max(8, size * 0.085);
    const pctY = cy + size * 0.16;
    const subY = pctY + pctFontSize * 0.85;
    const unitY = cy - size * 0.05;
    const uid = `gauge-glow-${Math.random().toString(36).slice(2, 8)}`;
    return /* @__PURE__ */ import_react2.default.createElement("div", { className: "memory-gauge", style: { width: size, height: size, position: "relative" } }, /* @__PURE__ */ import_react2.default.createElement("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}` }, /* @__PURE__ */ import_react2.default.createElement("defs", null, /* @__PURE__ */ import_react2.default.createElement("filter", { id: uid, x: "-20%", y: "-20%", width: "140%", height: "140%" }, /* @__PURE__ */ import_react2.default.createElement("feGaussianBlur", { in: "SourceGraphic", stdDeviation: "2.5" }))), /* @__PURE__ */ import_react2.default.createElement(
      "path",
      {
        d: bgArc,
        fill: "none",
        stroke: "rgba(255,255,255,0.08)",
        strokeWidth: strokeW,
        strokeLinecap: "round"
      }
    ), pct > 0 && /* @__PURE__ */ import_react2.default.createElement(
      "path",
      {
        d: valArc,
        fill: "none",
        stroke: color,
        strokeWidth: strokeW * 2.5,
        strokeLinecap: "round",
        opacity: "0.2",
        filter: `url(#${uid})`,
        style: { transition: "all 0.6s ease" }
      }
    ), pct > 0 && /* @__PURE__ */ import_react2.default.createElement(
      "path",
      {
        d: valArc,
        fill: "none",
        stroke: color,
        strokeWidth: strokeW,
        strokeLinecap: "round",
        style: { transition: "all 0.6s ease" }
      }
    ), ticks, labels, /* @__PURE__ */ import_react2.default.createElement(
      "text",
      {
        x: cx,
        y: unitY,
        textAnchor: "middle",
        dominantBaseline: "central",
        fill: "rgba(255,255,255,0.25)",
        fontSize: subFontSize,
        fontWeight: "600",
        letterSpacing: "1.5",
        fontFamily: "inherit"
      },
      "MEM"
    ), /* @__PURE__ */ import_react2.default.createElement(
      "line",
      {
        x1: needleTail.x,
        y1: needleTail.y,
        x2: needleTip.x,
        y2: needleTip.y,
        stroke: color,
        strokeWidth: needleW + 3,
        strokeLinecap: "round",
        opacity: "0.25",
        filter: `url(#${uid})`,
        style: { transition: "all 0.6s ease" }
      }
    ), /* @__PURE__ */ import_react2.default.createElement(
      "line",
      {
        x1: needleTail.x,
        y1: needleTail.y,
        x2: needleTip.x,
        y2: needleTip.y,
        stroke: "rgba(255,255,255,0.92)",
        strokeWidth: needleW,
        strokeLinecap: "round",
        style: { transition: "all 0.6s ease" }
      }
    ), /* @__PURE__ */ import_react2.default.createElement("circle", { cx, cy, r: pivotR + 1, fill: "rgba(255,255,255,0.08)" }), /* @__PURE__ */ import_react2.default.createElement("circle", { cx, cy, r: pivotR, fill: "rgba(255,255,255,0.55)" }), /* @__PURE__ */ import_react2.default.createElement(
      "circle",
      {
        cx,
        cy,
        r: pivotR * 0.45,
        fill: color,
        style: { transition: "fill 0.6s ease" }
      }
    ), /* @__PURE__ */ import_react2.default.createElement(
      "text",
      {
        x: cx,
        y: pctY,
        textAnchor: "middle",
        dominantBaseline: "central",
        fill: color,
        fontSize: pctFontSize,
        fontWeight: "700",
        fontFamily: "inherit",
        style: { transition: "fill 0.6s ease" }
      },
      Math.round(pct),
      "%"
    ), usedLabel && /* @__PURE__ */ import_react2.default.createElement(
      "text",
      {
        x: cx,
        y: subY,
        textAnchor: "middle",
        dominantBaseline: "central",
        fill: "rgba(255,255,255,0.4)",
        fontSize: subFontSize,
        fontFamily: "inherit"
      },
      usedLabel,
      " / ",
      totalLabel
    )));
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerMiniGauge.js
  function DockerMiniGauge({ server }) {
    const isDocker = server?.extension_data?.docker_enabled;
    if (!isDocker) return null;
    if (server.provisioning) return null;
    if (server.status !== "running") return null;
    const memPct = server.extension_status?.docker?.memory_percent;
    if (memPct == null) return null;
    return /* @__PURE__ */ import_react3.default.createElement(
      MemoryGauge,
      {
        percent: memPct,
        size: 44,
        compact: true,
        title: server.extension_status?.docker?.memory_usage || `${Math.round(memPct)}%`
      }
    );
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerStatsRow.js
  var import_react4 = __toESM(require_react());
  function DockerStatsRow({ server }) {
    const isDocker = server?.extension_data?.docker_enabled;
    if (!isDocker) return null;
    if (server.status !== "running") return null;
    const dockerStats = server.extension_status?.docker;
    if (dockerStats?.memory_percent == null) return null;
    return /* @__PURE__ */ import_react4.default.createElement("div", { className: "docker-stats-row", style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "8px 0",
      borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
      marginBottom: "6px"
    } }, /* @__PURE__ */ import_react4.default.createElement(
      MemoryGauge,
      {
        percent: dockerStats.memory_percent,
        usage: dockerStats.memory_usage,
        size: 130
      }
    ), dockerStats.cpu_percent != null && /* @__PURE__ */ import_react4.default.createElement("div", { style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "2px"
    } }, /* @__PURE__ */ import_react4.default.createElement("span", { style: {
      fontSize: "10px",
      color: "var(--text-tertiary, #888)",
      textTransform: "uppercase",
      fontWeight: 600,
      letterSpacing: "0.5px"
    } }, "CPU"), /* @__PURE__ */ import_react4.default.createElement("span", { style: {
      fontSize: "16px",
      fontWeight: 700,
      color: "var(--text-primary, #fff)"
    } }, dockerStats.cpu_percent.toFixed(1), "%")));
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerProvision.js
  var import_react5 = __toESM(require_react());
  var CHECK_ICON = /* @__PURE__ */ import_react5.default.createElement("svg", { viewBox: "0 0 24 24", width: "12", height: "12", fill: "none", stroke: "currentColor", strokeWidth: "3", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ import_react5.default.createElement("polyline", { points: "20 6 9 17 4 12" }));
  var SPINNER_ICON = /* @__PURE__ */ import_react5.default.createElement("svg", { viewBox: "0 0 24 24", width: "12", height: "12", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", className: "spin" }, /* @__PURE__ */ import_react5.default.createElement("path", { d: "M21 12a9 9 0 1 1-6.219-8.56" }));
  var ALERT_ICON = /* @__PURE__ */ import_react5.default.createElement("svg", { viewBox: "0 0 24 24", width: "12", height: "12", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ import_react5.default.createElement("circle", { cx: "12", cy: "12", r: "10" }), /* @__PURE__ */ import_react5.default.createElement("line", { x1: "12", y1: "8", x2: "12", y2: "12" }), /* @__PURE__ */ import_react5.default.createElement("line", { x1: "12", y1: "16", x2: "12.01", y2: "16" }));
  var DEFAULT_STEPS = ["docker_engine", "steamcmd", "compose"];
  function DockerProvision({ server, provisionProgress, onDismiss, t }) {
    const isDocker = server?.extension_data?.docker_enabled;
    if (!isDocker) return null;
    if (!server.provisioning) return null;
    const translate = t || ((key, opts) => opts?.defaultValue || key);
    const steps = provisionProgress?.steps || DEFAULT_STEPS;
    return /* @__PURE__ */ import_react5.default.createElement("div", { className: "sc-provision-wrap" }, /* @__PURE__ */ import_react5.default.createElement("div", { className: "as-provision-steps" }, steps.map((stepLabel, idx) => {
      const currentStep = provisionProgress?.step ?? -1;
      const isDone = provisionProgress?.done && !provisionProgress?.error;
      let stepClass = "pending";
      if (isDone || idx < currentStep) stepClass = "completed";
      else if (idx === currentStep) stepClass = provisionProgress?.error ? "error" : "active";
      const label = translate(`add_server_modal.step_${stepLabel}`, { defaultValue: stepLabel });
      return /* @__PURE__ */ import_react5.default.createElement("div", { key: stepLabel, className: `as-step ${stepClass}` }, /* @__PURE__ */ import_react5.default.createElement("div", { className: "as-step-icon" }, stepClass === "completed" ? CHECK_ICON : stepClass === "active" ? SPINNER_ICON : stepClass === "error" ? ALERT_ICON : /* @__PURE__ */ import_react5.default.createElement("span", { className: "as-step-num" }, idx + 1)), /* @__PURE__ */ import_react5.default.createElement("span", { className: "as-step-label" }, label));
    })), /* @__PURE__ */ import_react5.default.createElement("div", { className: "as-provision-bar" }, provisionProgress?.percent != null && !provisionProgress?.done && !provisionProgress?.error ? /* @__PURE__ */ import_react5.default.createElement("div", { className: "as-provision-bar-fill determinate", style: { width: `${provisionProgress.percent}%` } }) : /* @__PURE__ */ import_react5.default.createElement("div", { className: `as-provision-bar-fill ${provisionProgress?.error ? "error" : provisionProgress?.done ? "done" : "indeterminate"}` })), provisionProgress?.message && /* @__PURE__ */ import_react5.default.createElement("p", { className: "as-provision-message" }, provisionProgress.message, provisionProgress?.percent != null && !provisionProgress?.done && !provisionProgress?.error && /* @__PURE__ */ import_react5.default.createElement("span", { className: "as-provision-pct" }, " (", provisionProgress.percent, "%)")), provisionProgress?.error && /* @__PURE__ */ import_react5.default.createElement("div", { className: "as-provision-error-row" }, /* @__PURE__ */ import_react5.default.createElement("p", { className: "as-provision-error" }, provisionProgress.error), /* @__PURE__ */ import_react5.default.createElement("button", { className: "as-provision-dismiss", onClick: onDismiss }, translate("common.dismiss", { defaultValue: "Dismiss" }))));
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerTab.js
  var import_react6 = __toESM(require_react());
  var DOCKER_ICON = /* @__PURE__ */ import_react6.default.createElement("svg", { xmlns: "http://www.w3.org/2000/svg", viewBox: "0 0 512 512", width: "16", height: "16", style: { verticalAlign: "middle" } }, /* @__PURE__ */ import_react6.default.createElement("path", { fill: "currentColor", d: "M507 211.16c-1.42-1.19-14.25-10.94-41.79-10.94a132.55 132.55 0 00-21.61 1.9c-5.22-36.4-35.38-54-36.57-55l-7.36-4.28-4.75 6.9a101.65 101.65 0 00-13.06 30.45c-5 20.7-1.9 40.2 8.55 56.85-12.59 7.14-33 8.8-37.28 9H15.94A15.93 15.93 0 000 262.07a241.25 241.25 0 0014.75 86.83C26.39 379.35 43.72 402 66 415.74 91.22 431.2 132.3 440 178.6 440a344.23 344.23 0 0062.45-5.71 257.44 257.44 0 0081.69-29.73 223.55 223.55 0 0055.57-45.67c26.83-30.21 42.74-64 54.38-94h4.75c29.21 0 47.26-11.66 57.23-21.65a63.31 63.31 0 0015.2-22.36l2.14-6.18z" }));
  var LIGHTBULB_ICON = /* @__PURE__ */ import_react6.default.createElement("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "currentColor", style: { verticalAlign: "middle" } }, /* @__PURE__ */ import_react6.default.createElement("path", { d: "M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7zM9 21v-1h6v1a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1z" }));
  function DockerTab({ server, activeTab, setActiveTab, settings, onSettingsChange, t }) {
    const isDocker = server?.extension_data?.docker_enabled;
    if (!isDocker) return null;
    const translate = t || ((key, opts) => opts?.defaultValue || key);
    const extData = settings?._extension_data || {};
    const cpuLimit = extData.docker_cpu_limit != null ? String(extData.docker_cpu_limit) : "";
    const memLimit = extData.docker_memory_limit || "";
    const updateExtData = (key, value) => {
      onSettingsChange("_extension_data", { ...extData, [key]: value });
    };
    return /* @__PURE__ */ import_react6.default.createElement(import_react6.default.Fragment, null, /* @__PURE__ */ import_react6.default.createElement(
      "button",
      {
        className: `settings-tab ${activeTab === "docker" ? "active" : ""}`,
        onClick: () => setActiveTab("docker")
      },
      DOCKER_ICON,
      " ",
      translate("server_settings.docker_tab", { defaultValue: "Docker" })
    ), activeTab === "docker" && /* @__PURE__ */ import_react6.default.createElement("div", { className: "settings-form", style: { position: "absolute", top: 0, left: 0, right: 0 } }, /* @__PURE__ */ import_react6.default.createElement("div", { className: "settings-group" }, /* @__PURE__ */ import_react6.default.createElement("h4", { className: "settings-group-title" }, DOCKER_ICON, " ", translate("server_settings.docker_resources_title", { defaultValue: "Resource Limits" })), /* @__PURE__ */ import_react6.default.createElement("p", { className: "protocol-mode-description" }, translate("server_settings.docker_resources_desc", { defaultValue: "Configure CPU and memory limits for this Docker container. Changes will regenerate docker-compose.yml." })), /* @__PURE__ */ import_react6.default.createElement("div", { className: "settings-field" }, /* @__PURE__ */ import_react6.default.createElement("label", null, translate("server_settings.docker_cpu_limit_label", { defaultValue: "CPU Limit (cores)" })), /* @__PURE__ */ import_react6.default.createElement(
      "input",
      {
        type: "number",
        min: "0.25",
        max: "128",
        step: "0.25",
        value: cpuLimit,
        onChange: (e) => updateExtData("docker_cpu_limit", e.target.value ? Number(e.target.value) : null),
        placeholder: translate("server_settings.docker_cpu_limit_placeholder", { defaultValue: "e.g., 2.0 (no limit if empty)" })
      }
    ), /* @__PURE__ */ import_react6.default.createElement("small", { className: "field-description" }, translate("server_settings.docker_cpu_limit_desc", { defaultValue: "Number of CPU cores to allocate. Leave empty for no limit." }))), /* @__PURE__ */ import_react6.default.createElement("div", { className: "settings-field" }, /* @__PURE__ */ import_react6.default.createElement("label", null, translate("server_settings.docker_memory_limit_label", { defaultValue: "Memory Limit" })), /* @__PURE__ */ import_react6.default.createElement(
      "input",
      {
        type: "text",
        value: memLimit,
        onChange: (e) => updateExtData("docker_memory_limit", e.target.value || null),
        placeholder: translate("server_settings.docker_memory_limit_placeholder", { defaultValue: "e.g., 4g, 512m (no limit if empty)" })
      }
    ), /* @__PURE__ */ import_react6.default.createElement("small", { className: "field-description" }, translate("server_settings.docker_memory_limit_desc", { defaultValue: "Memory limit with unit (e.g., 512m, 2g, 4g). Leave empty for no limit." })))), /* @__PURE__ */ import_react6.default.createElement("div", { className: "protocol-mode-section protocol-mode-info", style: { marginTop: "16px" } }, /* @__PURE__ */ import_react6.default.createElement("p", { className: "protocol-mode-hint" }, /* @__PURE__ */ import_react6.default.createElement("span", { className: "hint-icon" }, LIGHTBULB_ICON), translate("server_settings.docker_restart_hint", { defaultValue: "Resource limit changes take effect after restarting the server." })))));
  }

  // ../../saba-chan-extensions/docker/gui/src/DockerToggle.js
  var import_react7 = __toESM(require_react());
  var PACKAGE_ICON = /* @__PURE__ */ import_react7.default.createElement("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "2", style: { verticalAlign: "middle" } }, /* @__PURE__ */ import_react7.default.createElement("path", { d: "M16.5 9.4l-9-5.19M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" }), /* @__PURE__ */ import_react7.default.createElement("polyline", { points: "3.27 6.96 12 12.01 20.73 6.96" }), /* @__PURE__ */ import_react7.default.createElement("line", { x1: "12", y1: "22.08", x2: "12", y2: "12" }));
  function DockerToggle({ options, onOptionsChange, t }) {
    const translate = t || ((key, opts) => opts?.defaultValue || key);
    const useContainer = options?.use_container || false;
    return /* @__PURE__ */ import_react7.default.createElement("div", { className: "as-section as-docker-row", style: { marginBottom: "12px" } }, /* @__PURE__ */ import_react7.default.createElement("div", { className: "as-toggle-row", style: {
      display: "flex",
      alignItems: "flex-start",
      gap: "12px",
      padding: "12px 14px",
      borderRadius: "8px",
      background: "var(--bg-surface-tertiary)",
      transition: "background 0.15s"
    } }, /* @__PURE__ */ import_react7.default.createElement("label", { className: "as-toggle-switch", style: {
      position: "relative",
      display: "inline-flex",
      flexShrink: 0,
      marginTop: "2px"
    } }, /* @__PURE__ */ import_react7.default.createElement(
      "input",
      {
        type: "checkbox",
        checked: useContainer,
        onChange: (e) => onOptionsChange({ ...options, use_container: e.target.checked }),
        style: { opacity: 0, width: 0, height: 0, position: "absolute" }
      }
    ), /* @__PURE__ */ import_react7.default.createElement("span", { className: "as-toggle-track" })), /* @__PURE__ */ import_react7.default.createElement("div", { className: "as-toggle-info" }, /* @__PURE__ */ import_react7.default.createElement("span", { className: "as-toggle-title" }, PACKAGE_ICON, " ", translate("add_server_modal.docker_isolation", { defaultValue: "Docker Isolation" })), /* @__PURE__ */ import_react7.default.createElement("span", { className: "as-toggle-desc" }, useContainer ? translate("add_server_modal.docker_isolation_hint_on", { defaultValue: "Server will run inside a Docker container for isolation." }) : translate("add_server_modal.docker_isolation_hint_off", { defaultValue: "Server will run natively on the host system." })))));
  }

  // ../../saba-chan-extensions/docker/gui/src/index.js
  function registerSlots() {
    return {
      "ServerCard.badge": [DockerBadge],
      "ServerCard.headerGauge": [DockerMiniGauge],
      "ServerCard.expandedStats": [DockerStatsRow],
      "ServerCard.provision": [DockerProvision],
      "ServerSettings.tab": [DockerTab],
      "AddServer.options": [DockerToggle]
    };
  }
  return __toCommonJS(index_exports);
})();
if(typeof window!==undefined){window.SabaExtDocker=SabaExtDocker;}
