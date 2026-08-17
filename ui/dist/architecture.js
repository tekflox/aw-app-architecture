const J = "architecture", A = "architecture.main";
const s = {
  title: 14,
  nav: 13,
  tab: 12,
  row: 11.5,
  mono: 11,
  label: 10
}, H = {
  implemented: "#4ade80",
  passing: "#4ade80",
  running: "#58a6ff",
  partial: "#fbbf24",
  broken: "#f87171",
  fail: "#f87171",
  not_implemented: "var(--color-text-muted)",
  planned: "var(--color-text-muted)",
  unknown: "var(--color-text-muted)"
}, K = [
  { id: "tests", label: "Tests" },
  { id: "requirements", label: "Requirements" },
  { id: "debt", label: "Debt & Bugs" },
  { id: "detail", label: "Detail" }
], w = {
  // Unicode symbols (⟳ ▶ ⚑ ▾ ✕ ↗) render as tofu boxes here — the browser
  // container's font stack has no glyph for them. Inline SVG doesn't care
  // what fonts the image ships.
  refresh: "M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10 M1 14l4.64 4.36A9 9 0 0 0 20.49 15",
  flag: "M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z M4 22v-7",
  close: "M18 6L6 18M6 6l12 12",
  chevronDown: "M6 9l6 6 6-6",
  chevronRight: "M9 18l6-6-6-6",
  arrow: "M5 12h14M13 6l6 6-6 6"
}, o = {
  label: { fontSize: s.label, textTransform: "uppercase", letterSpacing: ".06em" },
  mono: { fontSize: s.mono, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  th: {
    fontSize: s.label,
    textTransform: "uppercase",
    letterSpacing: ".06em",
    fontWeight: 500,
    textAlign: "left",
    padding: "5px 8px",
    color: "var(--color-text-muted)",
    borderBottom: "1px solid var(--color-border)"
  },
  td: { fontSize: s.row, padding: "5px 8px", borderBottom: "1px solid var(--color-border)" },
  btn: {
    fontSize: s.label,
    padding: "3px 9px",
    borderRadius: 6,
    border: "1px solid var(--color-border)",
    color: "var(--color-text-muted)",
    background: "transparent",
    lineHeight: 1.6,
    whiteSpace: "nowrap",
    cursor: "pointer"
  }
};
function G(e) {
  const { useState: p, useEffect: _, useCallback: R, useMemo: L } = e.React, M = (t, n) => e.sdk.api.fetch(`/api/apps/${J}${t}`, n), k = async (t) => {
    const n = await M(t);
    if (!n.ok) throw new Error(`HTTP ${n.status}`);
    return n.json();
  }, B = async (t, n) => {
    const a = await M(t, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(n || {})
    });
    if (!a.ok) throw new Error(`HTTP ${a.status}`);
    return a.json();
  };
  function C({ value: t }) {
    const n = t || "unknown";
    return /* @__PURE__ */ e.h("span", { style: { ...o.label, color: H[n] || H.unknown, fontWeight: 700 } }, n.replace(/_/g, " "));
  }
  function v({ d: t, size: n = 12, color: a = "currentColor", fill: d = "none", style: l }) {
    return /* @__PURE__ */ e.h(
      "svg",
      {
        width: n,
        height: n,
        viewBox: "0 0 24 24",
        fill: d,
        stroke: a,
        strokeWidth: "2",
        strokeLinecap: "round",
        strokeLinejoin: "round",
        style: { flexShrink: 0, ...l }
      },
      /* @__PURE__ */ e.h("path", { d: t })
    );
  }
  function m({ children: t }) {
    return /* @__PURE__ */ e.h("div", { style: {
      padding: "28px 16px",
      textAlign: "center",
      fontSize: s.row,
      color: "var(--color-text-muted)",
      lineHeight: 1.6
    } }, t);
  }
  function O(t) {
    const n = new Map(t.map((l) => [l.slug, { ...l, children: [] }])), a = [];
    for (const l of n.values()) {
      const r = l.parent_slug ? n.get(l.parent_slug) : null;
      r ? r.children.push(l) : a.push(l);
    }
    const d = (l) => (l.sort((r, i) => r.name.localeCompare(i.name)), l.forEach((r) => d(r.children)), l);
    return d(a);
  }
  function I({ node: t, depth: n, selected: a, onSelect: d }) {
    const [l, r] = p(!0), i = a === t.slug;
    return /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h(
      "div",
      {
        onClick: () => d(t.slug),
        className: "flex items-center gap-1 cursor-pointer",
        style: {
          paddingLeft: 6 + n * 12,
          paddingRight: 6,
          paddingTop: 3,
          paddingBottom: 3,
          borderRadius: 5,
          fontSize: s.row,
          background: i ? "rgba(88,166,255,.14)" : "transparent",
          color: i ? "var(--color-accent)" : "var(--color-text-primary)"
        }
      },
      /* @__PURE__ */ e.h(
        "span",
        {
          onClick: (h) => {
            h.stopPropagation(), r(!l);
          },
          style: {
            width: 12,
            flexShrink: 0,
            display: "inline-flex",
            alignItems: "center",
            color: "var(--color-text-muted)"
          }
        },
        t.children.length > 0 ? /* @__PURE__ */ e.h(v, { d: l ? w.chevronDown : w.chevronRight, size: 11 }) : null
      ),
      /* @__PURE__ */ e.h("span", { className: "truncate", style: { flex: 1 } }, t.name),
      /* @__PURE__ */ e.h(C, { value: t.health })
    ), l && t.children.map((h) => /* @__PURE__ */ e.h(I, { key: h.slug, node: h, depth: n + 1, selected: a, onSelect: d })));
  }
  function q({ slug: t, onBusy: n }) {
    const [a, d] = p(null), [l, r] = p(null), [i, h] = p({}), [S, b] = p(null), [g, T] = p(!1), y = R(() => {
      r(null), k(`/component-tests${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(d).catch((c) => r(c.message));
    }, [t]);
    _(y, [y]);
    const z = async (c) => {
      h((x) => ({ ...x, [c]: !0 })), b({ file_path: c, status: "running", output: "starting…" });
      try {
        const x = await B("/testcases/run", { file_path: c });
        for (; ; ) {
          const N = await k(`/testcases/jobs/${x.id}`);
          if (N.status === "done") {
            b(N.error ? { file_path: c, status: "unknown", output: N.error } : N.result), y();
            break;
          }
          b({
            file_path: c,
            status: "running",
            output: N.status === "queued" ? "queued — another test is running" : "running…"
          }), await new Promise((U) => setTimeout(U, 1500));
        }
      } catch (x) {
        b({
          file_path: c,
          status: "unknown",
          output: `Lost track of the run (${x.message}). It may still be going server-side — its recorded status will appear on refresh.`
        });
      } finally {
        h((x) => ({ ...x, [c]: !1 }));
      }
    }, u = async () => {
      n(!0);
      try {
        await B("/discovery/run"), y();
      } catch (c) {
        r(c.message);
      } finally {
        n(!1);
      }
    }, f = L(
      () => (a || []).filter((c) => !g || c.is_flaky),
      [a, g]
    );
    return l ? /* @__PURE__ */ e.h(m, null, "Couldn’t load tests — ", l) : a ? /* @__PURE__ */ e.h("div", { className: "flex flex-col h-full min-h-0" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2 shrink-0", style: { marginBottom: 8 } }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: u,
        style: {
          ...o.btn,
          color: "var(--color-accent)",
          borderColor: "rgba(88,166,255,.4)",
          display: "inline-flex",
          alignItems: "center",
          gap: 5
        }
      },
      /* @__PURE__ */ e.h(v, { d: w.refresh, size: 11 }),
      " Rescan discovery"
    ), /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => T(!g),
        style: {
          ...o.btn,
          color: g ? "#fbbf24" : "var(--color-text-muted)",
          display: "inline-flex",
          alignItems: "center",
          gap: 5
        }
      },
      /* @__PURE__ */ e.h(v, { d: w.flag, size: 11 }),
      " Flaky only"
    ), /* @__PURE__ */ e.h("span", { style: { marginLeft: "auto", fontSize: s.label, color: "var(--color-text-muted)" } }, f.length, " test", f.length === 1 ? "" : "s")), /* @__PURE__ */ e.h("div", { className: "overflow-auto min-h-0 flex-1" }, /* @__PURE__ */ e.h("table", { style: { width: "100%", borderCollapse: "collapse", tableLayout: "fixed" } }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", null, /* @__PURE__ */ e.h("th", { style: { ...o.th, width: 26 } }), /* @__PURE__ */ e.h("th", { style: o.th }, "Test file"), /* @__PURE__ */ e.h("th", { style: { ...o.th, width: 78 } }, "Kind"), /* @__PURE__ */ e.h("th", { style: { ...o.th, width: 120 } }, "Component"), /* @__PURE__ */ e.h("th", { style: { ...o.th, width: 84 } }, "Last run"))), /* @__PURE__ */ e.h("tbody", null, f.map((c) => /* @__PURE__ */ e.h("tr", { key: c.file_path }, /* @__PURE__ */ e.h("td", { style: o.td }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => z(c.file_path),
        disabled: i[c.file_path],
        title: "Run this test",
        style: {
          color: "#4ade80",
          background: "none",
          border: 0,
          cursor: "pointer",
          padding: 0,
          lineHeight: 0
        }
      },
      i[c.file_path] ? /* @__PURE__ */ e.h("span", { style: { fontSize: s.label } }, "…") : /* @__PURE__ */ e.h(v, { d: "M8 5v14l11-7z", size: 12, fill: "currentColor", color: "none" })
    )), /* @__PURE__ */ e.h(
      "td",
      {
        style: {
          ...o.td,
          ...o.mono,
          color: "var(--color-text-primary)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap"
        },
        title: c.file_path
      },
      c.file_path,
      c.is_flaky && /* @__PURE__ */ e.h(
        v,
        {
          d: w.flag,
          size: 10,
          color: "#fbbf24",
          style: { marginLeft: 5, verticalAlign: "-1px" }
        }
      )
    ), /* @__PURE__ */ e.h("td", { style: {
      ...o.td,
      color: "var(--color-text-muted)",
      whiteSpace: "nowrap"
    } }, c.kind), /* @__PURE__ */ e.h(
      "td",
      {
        style: {
          ...o.td,
          color: "var(--color-text-muted)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap"
        },
        title: c.component_slug || ""
      },
      c.component_slug || "—"
    ), /* @__PURE__ */ e.h("td", { style: { ...o.td, whiteSpace: "nowrap" } }, /* @__PURE__ */ e.h(C, { value: c.last_run_status })))))), f.length === 0 && /* @__PURE__ */ e.h(m, null, g ? "No tests flagged flaky." : "No tests here yet. Set a component’s test_base_path, then Rescan discovery.")), S && /* @__PURE__ */ e.h("div", { className: "shrink-0", style: {
      marginTop: 8,
      paddingTop: 8,
      borderTop: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: { marginBottom: 4 } }, /* @__PURE__ */ e.h(C, { value: S.status }), /* @__PURE__ */ e.h("span", { style: { ...o.mono, color: "var(--color-text-muted)" } }, S.file_path), /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => b(null),
        style: {
          marginLeft: "auto",
          background: "none",
          border: 0,
          padding: 0,
          lineHeight: 0,
          color: "var(--color-text-muted)",
          cursor: "pointer"
        }
      },
      /* @__PURE__ */ e.h(v, { d: w.close, size: 11 })
    )), /* @__PURE__ */ e.h("pre", { style: {
      fontSize: s.label,
      lineHeight: 1.45,
      maxHeight: 160,
      overflow: "auto",
      whiteSpace: "pre-wrap",
      margin: 0,
      color: "var(--color-text-muted)",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    } }, S.output))) : /* @__PURE__ */ e.h(m, null, "Loading…");
  }
  function D({ slug: t }) {
    const [n, a] = p(null), [d, l] = p(null);
    return _(() => {
      if (!t) {
        a([]);
        return;
      }
      a(null), l(null), k(`/components/${encodeURIComponent(t)}/requirements`).then(a).catch((r) => l(r.message));
    }, [t]), t ? d ? /* @__PURE__ */ e.h(m, null, "Couldn’t load requirements — ", d) : n ? n.length === 0 ? /* @__PURE__ */ e.h(m, null, "No requirements documented for this component.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, n.map((r) => /* @__PURE__ */ e.h("div", { key: r.id, style: {
      border: "1px solid var(--color-border)",
      borderRadius: 8,
      padding: 10,
      marginBottom: 8
    } }, /* @__PURE__ */ e.h("div", { className: "flex items-start gap-2", style: { marginBottom: 6 } }, /* @__PURE__ */ e.h("span", { style: { fontSize: s.tab, flex: 1, color: "var(--color-text-primary)" } }, r.title), /* @__PURE__ */ e.h(C, { value: r.health })), /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, lineHeight: 1.65, color: "var(--color-text-muted)" } }, /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "Given"), " ", r.gherkin_given), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "When"), " ", r.gherkin_when), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "Then"), " ", r.gherkin_then)), /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: {
      marginTop: 8,
      fontSize: s.label,
      color: "var(--color-text-muted)"
    } }, /* @__PURE__ */ e.h("span", null, "intended: ", /* @__PURE__ */ e.h("code", { style: o.mono }, r.intended_status)), r.kanban_url ? /* @__PURE__ */ e.h(
      "a",
      {
        href: r.kanban_url,
        target: "_blank",
        rel: "noreferrer",
        style: { color: "var(--color-accent)" }
      },
      "Kanban card"
    ) : /* @__PURE__ */ e.h("span", { style: { color: "#fbbf24" } }, "no Kanban card linked"))))) : /* @__PURE__ */ e.h(m, null, "Loading…") : /* @__PURE__ */ e.h(m, null, "Select a component to see its requirements.");
  }
  function E({ slug: t }) {
    const [n, a] = p(null), [d, l] = p(null);
    return _(() => {
      a(null), l(null), k(`/debt${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(a).catch((r) => l(r.message));
    }, [t]), d ? /* @__PURE__ */ e.h(m, null, "Couldn’t load debt notes — ", d) : n ? n.length === 0 ? /* @__PURE__ */ e.h(m, null, "No open technical-debt notes.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("table", { style: { width: "100%", borderCollapse: "collapse" } }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", null, /* @__PURE__ */ e.h("th", { style: o.th }, "Noted"), /* @__PURE__ */ e.h("th", { style: o.th }, "Component"), /* @__PURE__ */ e.h("th", { style: o.th }, "Description"))), /* @__PURE__ */ e.h("tbody", null, n.map((r) => /* @__PURE__ */ e.h("tr", { key: r.id }, /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)", whiteSpace: "nowrap" } }, (r.noted_at || "").slice(0, 10)), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)" } }, r.component_slug || "—"), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-primary)" } }, r.description)))))) : /* @__PURE__ */ e.h(m, null, "Loading…");
  }
  function W({ slug: t }) {
    const [n, a] = p(null), [d, l] = p(null);
    if (_(() => {
      if (!t) {
        a(null);
        return;
      }
      a(null), l(null), k(`/components/${encodeURIComponent(t)}`).then(a).catch((i) => l(i.message));
    }, [t]), !t) return /* @__PURE__ */ e.h(m, null, "Select a component.");
    if (d) return /* @__PURE__ */ e.h(m, null, "Couldn’t load component — ", d);
    if (!n) return /* @__PURE__ */ e.h(m, null, "Loading…");
    const r = ({ k: i, v: h }) => /* @__PURE__ */ e.h("div", { className: "flex gap-3", style: {
      padding: "4px 0",
      borderBottom: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("span", { style: {
      ...o.label,
      width: 118,
      flexShrink: 0,
      color: "var(--color-text-muted)",
      paddingTop: 2
    } }, i), /* @__PURE__ */ e.h("span", { style: { fontSize: s.row, color: "var(--color-text-primary)" } }, h));
    return /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: { marginBottom: 10 } }, /* @__PURE__ */ e.h("span", { style: { fontSize: s.title, color: "var(--color-text-primary)" } }, n.name), /* @__PURE__ */ e.h(C, { value: n.health })), /* @__PURE__ */ e.h(r, { k: "slug", v: /* @__PURE__ */ e.h("code", { style: o.mono }, n.slug) }), /* @__PURE__ */ e.h(r, { k: "repo", v: n.repo || "—" }), /* @__PURE__ */ e.h(r, { k: "layer", v: n.layer || "—" }), /* @__PURE__ */ e.h(r, { k: "technologies", v: (n.technologies || []).join(", ") || "—" }), /* @__PURE__ */ e.h(r, { k: "test_base_path", v: /* @__PURE__ */ e.h("code", { style: o.mono }, n.test_base_path || "—") }), /* @__PURE__ */ e.h(r, { k: "run_cmd", v: /* @__PURE__ */ e.h("code", { style: o.mono }, n.run_cmd || "—") }), /* @__PURE__ */ e.h(r, { k: "test_cmd", v: /* @__PURE__ */ e.h("code", { style: o.mono }, n.test_cmd || "—") }), n.description && /* @__PURE__ */ e.h("p", { style: {
      marginTop: 12,
      fontSize: s.row,
      lineHeight: 1.6,
      color: "var(--color-text-muted)",
      whiteSpace: "pre-wrap"
    } }, n.description), /* @__PURE__ */ e.h("div", { style: { marginTop: 14 } }, /* @__PURE__ */ e.h("div", { style: { ...o.label, color: "var(--color-text-muted)", marginBottom: 4 } }, "Connections"), (n.connections || []).length === 0 ? /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, color: "var(--color-text-muted)" } }, "none") : (n.connections || []).map((i) => /* @__PURE__ */ e.h("div", { key: i.id, style: { fontSize: s.row, color: "var(--color-text-primary)" } }, /* @__PURE__ */ e.h("code", { style: { ...o.mono, color: "var(--color-accent)" } }, i.kind), /* @__PURE__ */ e.h(v, { d: w.arrow, size: 11, style: { margin: "0 4px", verticalAlign: "-2px" } }), i.to_slug, i.description ? /* @__PURE__ */ e.h("span", { style: { color: "var(--color-text-muted)" } }, " — ", i.description) : null))), /* @__PURE__ */ e.h("div", { style: { marginTop: 12 } }, /* @__PURE__ */ e.h("div", { style: { ...o.label, color: "var(--color-text-muted)", marginBottom: 4 } }, "MCP tools"), (n.tools || []).length === 0 ? /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, color: "var(--color-text-muted)" } }, "none exposed") : (n.tools || []).map((i) => /* @__PURE__ */ e.h("div", { key: i.id, style: { ...o.mono, color: "var(--color-text-primary)" } }, i.name))));
  }
  function $() {
    const [t, n] = p(null), [a, d] = p(null), [l, r] = p(null), [i, h] = p("tests"), [S, b] = p(!1), [g, T] = p(""), y = R(() => {
      d(null), k("/components").then(n).catch((u) => d(u.message));
    }, []);
    _(y, [y]);
    const z = L(() => {
      if (!t) return [];
      const u = g.trim().toLowerCase();
      return u ? t.filter((f) => f.slug.toLowerCase().includes(u) || f.name.toLowerCase().includes(u)).map((f) => ({ ...f, children: [] })).sort((f, c) => f.name.localeCompare(c.name)) : O(t);
    }, [t, g]);
    return /* @__PURE__ */ e.h("div", { className: "flex h-full min-h-0", style: { color: "var(--color-text-primary)" } }, /* @__PURE__ */ e.h("div", { className: "flex flex-col min-h-0", style: {
      width: 240,
      flexShrink: 0,
      borderRight: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("div", { className: "shrink-0", style: { padding: 8 } }, /* @__PURE__ */ e.h(
      "input",
      {
        value: g,
        onChange: (u) => T(u.target.value),
        placeholder: "Filter components…",
        style: {
          width: "100%",
          background: "transparent",
          outline: "none",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          padding: "4px 7px",
          fontSize: s.row,
          color: "var(--color-text-primary)"
        }
      }
    )), /* @__PURE__ */ e.h("div", { className: "overflow-auto flex-1 min-h-0", style: { padding: "0 6px 8px" } }, a && /* @__PURE__ */ e.h(m, null, "Couldn’t load — ", a), !t && !a && /* @__PURE__ */ e.h(m, null, "Loading…"), t && t.length === 0 && /* @__PURE__ */ e.h(m, null, "No components registered yet — the catalog is curated through the architecture MCP tools."), z.map((u) => /* @__PURE__ */ e.h(I, { key: u.slug, node: u, depth: 0, selected: l, onSelect: r })))), /* @__PURE__ */ e.h("div", { className: "flex flex-col min-w-0 min-h-0", style: { flex: 1 } }, /* @__PURE__ */ e.h("div", { className: "flex items-center shrink-0", style: {
      padding: "0 8px",
      borderBottom: "1px solid var(--color-border)"
    } }, K.map((u) => /* @__PURE__ */ e.h(
      "button",
      {
        key: u.id,
        onClick: () => h(u.id),
        style: {
          padding: "7px 11px",
          fontSize: s.tab,
          background: "none",
          cursor: "pointer",
          border: 0,
          borderBottom: "2px solid",
          borderBottomColor: i === u.id ? "var(--color-accent)" : "transparent",
          color: i === u.id ? "var(--color-text-primary)" : "var(--color-text-muted)"
        }
      },
      u.label
    )), /* @__PURE__ */ e.h("span", { style: {
      marginLeft: "auto",
      paddingRight: 4,
      fontSize: s.label,
      color: "var(--color-text-muted)"
    } }, S ? "scanning…" : l || "all components")), /* @__PURE__ */ e.h("div", { className: "flex-1 min-h-0", style: { padding: 10 } }, i === "tests" && /* @__PURE__ */ e.h(q, { slug: l, onBusy: (u) => {
      b(u), u || y();
    } }), i === "requirements" && /* @__PURE__ */ e.h(D, { slug: l }), i === "debt" && /* @__PURE__ */ e.h(E, { slug: l }), i === "detail" && /* @__PURE__ */ e.h(W, { slug: l }))));
  }
  function j() {
    return /* @__PURE__ */ e.h(
      "svg",
      {
        className: "w-3.5 h-3.5 shrink-0 text-[var(--color-text-muted)]",
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        strokeWidth: "2",
        strokeLinecap: "round",
        strokeLinejoin: "round"
      },
      /* @__PURE__ */ e.h("path", { d: "M12 2L2 7l10 5 10-5-10-5z" }),
      /* @__PURE__ */ e.h("path", { d: "M2 17l10 5 10-5" }),
      /* @__PURE__ */ e.h("path", { d: "M2 12l10 5 10-5" })
    );
  }
  function F() {
    return /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => {
          var t;
          return (t = window.__awOpenAppWindow) == null ? void 0 : t.call(window, A, void 0, "Architecture");
        },
        className: "w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.06] cursor-pointer text-left",
        title: "Components, requirements, test traceability"
      },
      /* @__PURE__ */ e.h(j, null),
      /* @__PURE__ */ e.h("span", { style: { fontSize: s.nav, color: "var(--color-text-primary)" } }, "Architecture")
    );
  }
  e.registerWindow(A, $), e.registerSlot("core.nav.workspace", F);
}
export {
  G as default,
  G as register
};
