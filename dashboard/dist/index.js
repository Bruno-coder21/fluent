/* fluent dashboard tab: three rings that only go up, and the programs your agent is
   fluent in. Plain IIFE, no build step; React and UI parts come from the Hermes SDK. */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var C = SDK.components;

  var COLORS = { programs: "#30D158", caught: "#0A84FF", tokens: "#BF5AF2",
                 read: "#30D158", change: "#FFD60A", destroy: "#FF453A" };
  var COUNT_GOALS = [1, 3, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000];
  var TOKEN_GOALS = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000,
                     250000, 500000, 1000000];

  function goalFor(value, goals) {
    for (var i = 0; i < goals.length; i++) if (goals[i] >= Math.max(value, 1)) return goals[i];
    return goals[goals.length - 1];
  }

  function fmt(n) { return Number(n || 0).toLocaleString("en-US"); }

  function Ring(props) {
    var r = props.radius, c = 2 * Math.PI * r;
    var frac = Math.max(0, Math.min(1, props.value / props.goal));
    return h("g", null,
      h("circle", { cx: 90, cy: 90, r: r, fill: "none", stroke: props.color,
                    strokeOpacity: 0.18, strokeWidth: 14 }),
      h("circle", { cx: 90, cy: 90, r: r, fill: "none", stroke: props.color, strokeWidth: 14,
                    strokeLinecap: "round", strokeDasharray: c,
                    strokeDashoffset: c * (1 - frac), transform: "rotate(-90 90 90)",
                    style: { transition: "stroke-dashoffset 900ms cubic-bezier(.2,.8,.2,1)" } }));
  }

  function Legend(props) {
    return h("div", { style: { display: "flex", alignItems: "baseline", gap: 10, padding: "6px 0" } },
      h("span", { style: { width: 10, height: 10, borderRadius: 5, background: props.color,
                           display: "inline-block", flex: "none" } }),
      h("span", { style: { fontSize: 26, fontWeight: 600, lineHeight: 1 } }, props.value),
      h("span", { style: { fontSize: 14, opacity: 0.85 } }, props.label),
      h("span", { style: { fontSize: 12, opacity: 0.5, marginLeft: "auto" } }, props.goal));
  }

  function RiskDots(p) {
    function dot(color, n, title) {
      return h("span", { title: title, style: { marginRight: 12, whiteSpace: "nowrap" } },
        h("span", { style: { display: "inline-block", width: 8, height: 8, borderRadius: 4,
                             background: color, marginRight: 5 } }), n);
    }
    if (!p.subcommands) return h("span", { style: { opacity: 0.5 } }, "—");
    return h("span", null,
      dot(COLORS.read, p.read, "only read"),
      dot(COLORS.change, p.change, "change things"),
      dot(COLORS.destroy, p.destroy, "delete things: asks first"));
  }

  function ProgramRow(p) {
    var cell = { padding: "10px 12px", borderTop: "1px solid rgba(127,127,127,.18)" };
    return h("tr", null,
      h("td", { style: Object.assign({ fontWeight: 600 }, cell) },
        p.program, h("span", { style: { opacity: 0.55, fontWeight: 400, marginLeft: 8 } }, p.version)),
      h("td", { style: cell }, p.subcommands ? fmt(p.subcommands) : "—"),
      h("td", { style: cell }, fmt(p.options)),
      h("td", { style: cell }, h(RiskDots, p)),
      h("td", { style: Object.assign({ opacity: 0.6 }, cell) },
        p.learned_at ? SDK.utils.timeAgo(p.learned_at) : ""));
  }

  function FluentPage() {
    var st = useState(null), data = st[0], setData = st[1];
    var er = useState(null), error = er[0], setError = er[1];

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

    if (error && !data) {
      return h(C.Card, null, h(C.CardContent, { style: { padding: 24 } },
        "fluent couldn't load its data: " + error));
    }
    if (!data) {
      return h(C.Card, null, h(C.CardContent, { style: { padding: 24, opacity: 0.6 } }, "Loading…"));
    }

    var programs = data.programs || [];
    var c = data.counters || {};
    var nProg = programs.length, gProg = goalFor(nProg, COUNT_GOALS);
    var nCaught = c.caught || 0, gCaught = goalFor(nCaught, COUNT_GOALS);
    var nTok = c.tokens_saved || 0, gTok = goalFor(nTok, TOKEN_GOALS);
    var mode = (data.config && data.config.mode) || "block";
    var modeText = { block: "Guard on", warn: "Guard warns", off: "Guard paused" }[mode] || mode;

    var rings = h(C.Card, null,
      h(C.CardHeader, null,
        h("div", { style: { display: "flex", alignItems: "center", gap: 12 } },
          h(C.CardTitle, null, "fluent"),
          h(C.Badge, null, modeText)),
        h("p", { style: { fontSize: 14, opacity: 0.7, marginTop: 6 } },
          "Every terminal command your agent runs is checked against the real help of the program installed here.")),
      h(C.CardContent, null,
        h("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 32 } },
          h("svg", { width: 180, height: 180, viewBox: "0 0 180 180", role: "img",
                     "aria-label": "fluent progress rings" },
            h(Ring, { radius: 74, value: nProg, goal: gProg, color: COLORS.programs }),
            h(Ring, { radius: 56, value: nCaught, goal: gCaught, color: COLORS.caught }),
            h(Ring, { radius: 38, value: nTok, goal: gTok, color: COLORS.tokens })),
          h("div", { style: { minWidth: 260, flex: 1 } },
            h(Legend, { color: COLORS.programs, value: fmt(nProg),
                        label: nProg === 1 ? "program fluent" : "programs fluent",
                        goal: nProg >= gProg ? "ring closed" : "next ring at " + fmt(gProg) }),
            h(Legend, { color: COLORS.caught, value: fmt(nCaught),
                        label: nCaught === 1 ? "error caught before it ran" : "errors caught before they ran",
                        goal: nCaught >= gCaught ? "ring closed" : "next ring at " + fmt(gCaught) }),
            h(Legend, { color: COLORS.tokens, value: "≈" + fmt(nTok),
                        label: "tokens saved", goal: nTok >= gTok ? "ring closed" : "next ring at " + fmt(gTok) })))));

    var list = h(C.Card, { style: { marginTop: 16 } },
      h(C.CardHeader, null, h(C.CardTitle, null, "Programs your agent is fluent in")),
      h(C.CardContent, null,
        nProg === 0
          ? h("p", { style: { opacity: 0.7 } }, "Nothing yet. In Chat, type: /fluent adopt git")
          : h("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 14 } },
              h("thead", null, h("tr", { style: { textAlign: "left", opacity: 0.6 } },
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Program"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Commands"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Options"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Read · change · delete"),
                h("th", { style: { padding: "6px 12px", fontWeight: 500 } }, "Learned"))),
              h("tbody", null, programs.map(function (p) {
                return h(ProgramRow, Object.assign({ key: p.program }, p));
              }))),
        h("p", { style: { fontSize: 12, opacity: 0.5, marginTop: 14 } },
          "Add a program: /fluent adopt <program> · Undo anything: /fluent undo")));

    return h("div", { style: { maxWidth: 980 } }, rings, list);
  }

  window.__HERMES_PLUGINS__.register("fluent", FluentPage);
})();
