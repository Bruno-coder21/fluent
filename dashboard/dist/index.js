/* fluent dashboard tab: your agent's tree. Every adopted program grows a branch (its
   leaves are the options it knows), and every error caught before it ran becomes a fruit.
   Plain IIFE, no build step; React and UI parts come from the Hermes plugin SDK. */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var C = SDK.components;

  var PALETTE = ["#5eead4", "#fbbf24", "#f472b6", "#60a5fa", "#a78bfa", "#34d399",
                 "#fb923c", "#e879f9", "#38bdf8", "#facc15", "#4ade80", "#f87171"];
  var BARK = "#8b6b4a", FRUIT = "#ff5a4e";
  var RISK = { read: "#30D158", change: "#FFD60A", destroy: "#FF453A" };
  var W = 500, H = 320, BASE = 304, CX = W / 2;

  function fmt(n) { return Number(n || 0).toLocaleString("en-US"); }

  function seeded(str) { // small deterministic PRNG so each program's branch keeps its shape
    var s = 2166136261;
    for (var i = 0; i < str.length; i++) { s ^= str.charCodeAt(i); s = Math.imul(s, 16777619); }
    return function () {
      s = Math.imul(s ^ (s >>> 15), 2246822507); s = Math.imul(s ^ (s >>> 13), 3266489909);
      return ((s ^= s >>> 16) >>> 0) / 4294967296;
    };
  }

  function layout(programs) {
    var n = programs.length;
    var trunkTop = BASE - Math.min(236, 92 + 20 * n);
    var low = BASE - 74; // lowest branch
    // branch tips sit on the outline of a round crown, evenly spaced on each side, so
    // clusters never collide; older programs grow low, newer ones near the top
    var crownCy = trunkTop + 30;
    var rx = 96 + Math.min(54, 7 * n), ry = 76 + Math.min(46, 6 * n);
    var perSide = [Math.ceil(n / 2), Math.floor(n / 2)];
    var branches = programs.map(function (p, i) {
      var rnd = seeded(p.program);
      var side = i % 2 === 0 ? -1 : 1;
      var t = n > 1 ? i / (n - 1) : 0.5; // 0 = oldest/lowest, 1 = newest/top
      var y0 = low - t * (low - trunkTop - 14);
      var m = perSide[side < 0 ? 0 : 1], j = Math.floor(i / 2);
      var u = m > 1 ? j / (m - 1) : 0.5; // position along this side's arc
      var theta = (196 - 84 * u + (rnd() - 0.5) * 6) * Math.PI / 180; // 196° low-out → 112° high-in
      var x1 = Math.max(40, Math.min(W - 40, CX + side * Math.abs(rx * Math.cos(theta))));
      var y1 = Math.max(28, crownCy - ry * Math.sin(theta));
      var len = Math.hypot(x1 - CX, y1 - y0);
      var leafCount = Math.min(12, 4 + Math.round(Math.log2((p.options || 0) + 2)));
      var leaves = [];
      for (var k = 0; k < leafCount; k++) {
        var a = rnd() * Math.PI * 2, d = 3 + rnd() * 13;
        leaves.push({ x: x1 + Math.cos(a) * d, y: y1 + Math.sin(a) * d * 0.75, r: 4.5 + rnd() * 4 });
      }
      return { p: p, color: PALETTE[i % PALETTE.length], x0: CX, y0: y0, x1: x1, y1: y1,
               side: side, leaves: leaves, len: len, width: 5 - 2 * t, top: m >= 3 && u > 0.75 };
    });
    return { trunkTop: trunkTop, branches: branches };
  }

  function crown(g) { // soft canopy behind the branches, sized by what grew
    if (!g.branches.length) return [];
    var xs = g.branches.map(function (b) { return b.x1; }), ys = g.branches.map(function (b) { return b.y1; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var cx = (minX + maxX) / 2, cy = (minY + maxY) / 2 + 6;
    var rx = (maxX - minX) / 2 + 30, ry = (maxY - minY) / 2 + 34;
    return [[cx, cy, rx, ry]];
  }

  function Tree(props) {
    var programs = props.programs, caught = props.caught;
    var g = layout(programs);
    var grown = props.grown;
    var kids = [];
    kids.push(h("ellipse", { key: "ground", cx: CX, cy: BASE + 6, rx: 130, ry: 8, fill: "#ffffff",
                             opacity: 0.06 }));
    crown(g).forEach(function (e, k) {
      kids.push(h("ellipse", { key: "cr" + k, cx: e[0], cy: e[1], rx: e[2], ry: e[3], fill: "#34d399",
                               opacity: grown ? 0.1 : 0,
                               style: { transition: "opacity 900ms ease-out " + (400 + k * 120) + "ms" } }));
    });
    // tapered trunk with two small roots; grows up from the ground
    var tw = 8 + Math.min(5, programs.length * 0.5);
    kids.push(h("g", { key: "trunk", style: { transformBox: "fill-box", transformOrigin: "50% 100%",
                                               transform: grown ? "scaleY(1)" : "scaleY(0)",
                                               transition: "transform 700ms cubic-bezier(.2,.8,.2,1)" } },
      h("path", { d: "M" + (CX - tw) + " " + (BASE + 4) + " C" + (CX - tw * 0.55) + " " + (BASE - 60) + " " +
                     (CX - 3) + " " + (g.trunkTop + 40) + " " + (CX - 2.5) + " " + g.trunkTop +
                     " L" + (CX + 2.5) + " " + g.trunkTop + " C" + (CX + 3) + " " + (g.trunkTop + 40) + " " +
                     (CX + tw * 0.55) + " " + (BASE - 60) + " " + (CX + tw) + " " + (BASE + 4) + " Z",
                  fill: BARK }),
      h("path", { d: "M" + (CX - tw + 2) + " " + (BASE + 2) + " Q" + (CX - tw - 14) + " " + (BASE + 6) + " " + (CX - tw - 26) + " " + (BASE + 9),
                  stroke: BARK, strokeWidth: 3, strokeLinecap: "round", fill: "none" }),
      h("path", { d: "M" + (CX + tw - 2) + " " + (BASE + 2) + " Q" + (CX + tw + 14) + " " + (BASE + 6) + " " + (CX + tw + 24) + " " + (BASE + 9),
                  stroke: BARK, strokeWidth: 3, strokeLinecap: "round", fill: "none" })));
    g.branches.forEach(function (b, i) {
      var mx = b.x0 + (b.x1 - b.x0) * 0.45, my = b.y0 - (b.y0 - b.y1) * 0.1;
      var len = b.len + 24;
      var delay = 500 + i * 140;
      kids.push(h("path", { key: "br" + i, d: "M" + b.x0 + " " + b.y0 + " Q" + mx + " " + my + " " + b.x1 + " " + b.y1,
                            stroke: BARK, strokeWidth: b.width, strokeLinecap: "round", fill: "none",
                            strokeDasharray: len, strokeDashoffset: grown ? 0 : len,
                            style: { transition: "stroke-dashoffset 600ms ease-out " + delay + "ms" } }));
      b.leaves.forEach(function (l, k) {
        kids.push(h("circle", { key: "lf" + i + "_" + k, cx: l.x, cy: l.y, r: l.r, fill: b.color,
                                opacity: grown ? 0.9 : 0,
                                style: { transition: "opacity 500ms ease-out " + (delay + 450 + k * 30) + "ms" } }));
      });
      [0.5, 0.68].forEach(function (s, k) { // a few small leaves along the branch
        var bx = (1 - s) * (1 - s) * b.x0 + 2 * (1 - s) * s * mx + s * s * b.x1;
        var by = (1 - s) * (1 - s) * b.y0 + 2 * (1 - s) * s * my + s * s * b.y1;
        kids.push(h("circle", { key: "ml" + i + "_" + k, cx: bx + (k ? 4 : -3), cy: by - 5, r: k ? 3.5 : 3,
                                fill: b.color, opacity: grown ? 0.65 : 0,
                                style: { transition: "opacity 500ms ease-out " + (delay + 300) + "ms" } }));
      });
      kids.push(h("text", { key: "tx" + i, x: b.top ? b.x1 : b.x1 + b.side * 26,
                            y: b.top ? b.y1 - 22 : b.y1 + 4,
                            textAnchor: b.top ? "middle" : b.side < 0 ? "end" : "start",
                            fontSize: 12, fontWeight: 600,
                            fill: "currentColor", opacity: grown ? 0.9 : 0,
                            style: { transition: "opacity 400ms ease-out " + (delay + 600) + "ms" } },
                    b.p.program));
    });
    // fruits: one per error caught (up to 40), hanging among the leaves
    var all = [];
    g.branches.forEach(function (b) { b.leaves.forEach(function (l) { all.push(l); }); });
    var rnd = seeded("fruit");
    var shown = Math.min(caught, 40);
    for (var f = 0; f < shown && all.length; f++) {
      var leaf = all[Math.floor(rnd() * all.length)];
      kids.push(h("circle", { key: "fr" + f, cx: leaf.x + (rnd() - 0.5) * 6, cy: leaf.y + 3 + rnd() * 4,
                              r: 3.6, fill: FRUIT, stroke: "#ffd1cc", strokeWidth: 0.8,
                              opacity: grown ? 1 : 0,
                              style: { transition: "opacity 400ms ease-out " + (900 + programs.length * 140 + f * 60) + "ms" } }));
    }
    if (!programs.length) {
      kids.push(h("circle", { key: "bud", cx: CX, cy: g.trunkTop - 6, r: 7, fill: PALETTE[0], opacity: 0.8 }));
    }
    return h("svg", { width: "100%", viewBox: "0 -26 " + W + " " + (H + 40), role: "img",
                      style: { maxWidth: 500, display: "block" },
                      "aria-label": "Your agent's tree: " + programs.length + " branches, " + caught + " fruits" },
             kids);
  }

  function Stat(props) {
    return h("div", { style: { display: "flex", alignItems: "baseline", gap: 10, padding: "7px 0" } },
      h("span", { style: { fontSize: 18, width: 24, textAlign: "center" } }, props.icon),
      h("span", { style: { fontSize: 28, fontWeight: 600, lineHeight: 1 } }, props.value),
      h("span", { style: { fontSize: 14, opacity: 0.8 } }, props.label));
  }

  function RiskDots(p) {
    function dot(color, n, title) {
      return h("span", { title: title, style: { marginRight: 12, whiteSpace: "nowrap" } },
        h("span", { style: { display: "inline-block", width: 8, height: 8, borderRadius: 4,
                             background: color, marginRight: 5 } }), n);
    }
    if (!p.subcommands) return h("span", { style: { opacity: 0.5 } }, "—");
    return h("span", null,
      dot(RISK.read, p.read, "only read"),
      dot(RISK.change, p.change, "change things"),
      dot(RISK.destroy, p.destroy, "delete things: asks first"));
  }

  function ProgramRow(p) {
    var cell = { padding: "10px 12px", borderTop: "1px solid rgba(127,127,127,.18)" };
    return h("tr", null,
      h("td", { style: Object.assign({ fontWeight: 600 }, cell) },
        h("span", { style: { display: "inline-block", width: 10, height: 10, borderRadius: 5,
                             background: p.color, marginRight: 8 } }),
        p.program, h("span", { style: { opacity: 0.55, fontWeight: 400, marginLeft: 8 } }, p.version),
        p.needs_reread ? h("span", { style: { opacity: 0.7, fontWeight: 400, marginLeft: 8, fontSize: 12 } },
          "🔄 read again: /fluent adopt " + p.program) : null),
      h("td", { style: cell }, p.subcommands ? fmt(p.subcommands) : "—"),
      h("td", { style: cell }, fmt(p.options)),
      h("td", { style: cell }, h(RiskDots, p)),
      h("td", { style: Object.assign({ opacity: 0.6 }, cell) },
        p.learned_at ? SDK.utils.timeAgo(p.learned_at) : ""));
  }

  function FluentPage() {
    var st = useState(null), data = st[0], setData = st[1];
    var er = useState(null), error = er[0], setError = er[1];
    var gr = useState(false), grown = gr[0], setGrown = gr[1];

    useEffect(function () {
      var alive = true;
      function load() {
        SDK.fetchJSON("/api/plugins/fluent/summary")
          .then(function (d) { if (alive) { setData(d); setError(null); } })
          .catch(function (e) { if (alive) setError(String(e && e.message || e)); });
      }
      load();
      var t = setInterval(load, 5000);
      return function () { alive = false; clearInterval(t); };
    }, []);

    useEffect(function () {
      if (!data || grown) return;
      var t = setTimeout(function () { setGrown(true); }, 60);
      return function () { clearTimeout(t); };
    }, [data, grown]);

    if (error && !data) {
      return h(C.Card, null, h(C.CardContent, { style: { padding: 24 } },
        "fluent couldn't load its data: " + error));
    }
    if (!data) {
      return h(C.Card, null, h(C.CardContent, { style: { padding: 24, opacity: 0.6 } }, "Loading…"));
    }

    var programs = (data.programs || []).slice().sort(function (a, b) {
      return (a.learned_at || 0) - (b.learned_at || 0);
    });
    programs.forEach(function (p, i) { p.color = PALETTE[i % PALETTE.length]; });
    var c = data.counters || {};
    var leaves = programs.reduce(function (s, p) { return s + (p.options || 0); }, 0);
    var mode = (data.config && data.config.mode) || "block";
    var modeText = { block: "Guard on", warn: "Guard warns", off: "Guard paused" }[mode] || mode;

    var hero = h(C.Card, null,
      h(C.CardHeader, null,
        h("div", { style: { display: "flex", alignItems: "center", gap: 12 } },
          h(C.CardTitle, null, "Your agent's tree"),
          h(C.Badge, null, modeText)),
        h("p", { style: { fontSize: 14, opacity: 0.7, marginTop: 6 } },
          "Every program you adopt grows a branch. Every error caught before it ran becomes a fruit.")),
      h(C.CardContent, null,
        h("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 28 } },
          h("div", { style: { flex: "1 1 340px", maxWidth: 460 } },
            h(Tree, { programs: programs, caught: c.caught || 0, grown: grown })),
          h("div", { style: { flex: "1 1 240px" } },
            h(Stat, { icon: "🌿", value: fmt(programs.length),
                      label: programs.length === 1 ? "branch · program fluent" : "branches · programs fluent" }),
            h(Stat, { icon: "🍃", value: fmt(leaves), label: "leaves · options it knows" }),
            h(Stat, { icon: "🍎", value: fmt(c.caught || 0),
                      label: (c.caught === 1 ? "fruit · error" : "fruits · errors") + " caught before it ran" }),
            h(Stat, { icon: "⚡", value: "≈" + fmt(c.tokens_saved || 0), label: "tokens saved" }),
            programs.length === 0
              ? h("p", { style: { fontSize: 13, opacity: 0.7, marginTop: 10 } },
                  "Plant the first branch: in Chat, type /fluent adopt git")
              : null))));

    var list = h(C.Card, { style: { marginTop: 16 } },
      h(C.CardHeader, null, h(C.CardTitle, null, "Branches")),
      h(C.CardContent, null,
        programs.length === 0
          ? h("p", { style: { opacity: 0.7 } }, "Nothing yet. In Chat, type: /fluent adopt git")
          : h("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 14 } },
              h("thead", null, h("tr", { style: { textAlign: "left", opacity: 0.6 } },
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Program"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Commands"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Options"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Read · change · delete"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Planted"))),
              h("tbody", null, programs.map(function (p) {
                return h(ProgramRow, Object.assign({ key: p.program }, p));
              }))),
        h("p", { style: { fontSize: 12, opacity: 0.5, marginTop: 14 } },
          "Grow a branch: /fluent adopt <program> · Undo anything: /fluent undo")));

    return h("div", { style: { maxWidth: 980 } }, hero, list);
  }

  window.__HERMES_PLUGINS__.register("fluent", FluentPage);
})();
