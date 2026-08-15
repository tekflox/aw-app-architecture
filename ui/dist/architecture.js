const D = "architecture", B = "architecture.main";
const s = {
  title: 14,
  tab: 12,
  row: 11.5,
  mono: 11,
  label: 10
}, H = {
  implemented: "#4ade80",
  passing: "#4ade80",
  partial: "#fbbf24",
  broken: "#f87171",
  fail: "#f87171",
  not_implemented: "var(--color-text-muted)",
  planned: "var(--color-text-muted)",
  unknown: "var(--color-text-muted)"
}, F = [
  { id: "tests", label: "Tests" },
  { id: "requirements", label: "Requirements" },
  { id: "debt", label: "Debt & Bugs" },
  { id: "detail", label: "Detail" }
], o = {
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
function j(e) {
  const { useState: p, useEffect: w, useCallback: N, useMemo: T } = e.React, R = (t, r) => e.sdk.api.fetch(`/api/apps/${D}${t}`, r), k = async (t) => {
    const r = await R(t);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }, z = async (t, r) => {
    const a = await R(t, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(r || {})
    });
    if (!a.ok) throw new Error(`HTTP ${a.status}`);
    return a.json();
  };
  function S({ value: t }) {
    const r = t || "unknown";
    return /* @__PURE__ */ e.h("span", { style: { ...o.label, color: H[r] || H.unknown, fontWeight: 700 } }, r.replace(/_/g, " "));
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
  function A(t) {
    const r = new Map(t.map((l) => [l.slug, { ...l, children: [] }])), a = [];
    for (const l of r.values()) {
      const n = l.parent_slug ? r.get(l.parent_slug) : null;
      n ? n.children.push(l) : a.push(l);
    }
    const u = (l) => (l.sort((n, i) => n.name.localeCompare(i.name)), l.forEach((n) => u(n.children)), l);
    return u(a);
  }
  function L({ node: t, depth: r, selected: a, onSelect: u }) {
    const [l, n] = p(!0), i = a === t.slug;
    return /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h(
      "div",
      {
        onClick: () => u(t.slug),
        className: "flex items-center gap-1 cursor-pointer",
        style: {
          paddingLeft: 6 + r * 12,
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
          onClick: (f) => {
            f.stopPropagation(), n(!l);
          },
          style: { width: 11, flexShrink: 0, color: "var(--color-text-muted)", fontSize: s.label }
        },
        t.children.length > 0 ? l ? "▾" : "▸" : ""
      ),
      /* @__PURE__ */ e.h("span", { className: "truncate", style: { flex: 1 } }, t.name),
      /* @__PURE__ */ e.h(S, { value: t.health })
    ), l && t.children.map((f) => /* @__PURE__ */ e.h(L, { key: f.slug, node: f, depth: r + 1, selected: a, onSelect: u })));
  }
  function E({ slug: t, onBusy: r }) {
    const [a, u] = p(null), [l, n] = p(null), [i, f] = p({}), [b, x] = p(null), [y, _] = p(!1), g = N(() => {
      n(null), k(`/component-tests${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(u).catch((c) => n(c.message));
    }, [t]);
    w(g, [g]);
    const C = async (c) => {
      f((v) => ({ ...v, [c]: !0 })), x(null);
      try {
        const v = await z("/testcases/run", { file_path: c });
        x(v), g();
      } catch (v) {
        x({
          file_path: c,
          status: "unknown",
          output: `Could not read the result back (${v.message}). The run may still be going server-side — its recorded status will appear on refresh.`
        });
      } finally {
        f((v) => ({ ...v, [c]: !1 }));
      }
    }, d = async () => {
      r(!0);
      try {
        await z("/discovery/run"), g();
      } catch (c) {
        n(c.message);
      } finally {
        r(!1);
      }
    }, h = T(
      () => (a || []).filter((c) => !y || c.is_flaky),
      [a, y]
    );
    return l ? /* @__PURE__ */ e.h(m, null, "Couldn’t load tests — ", l) : a ? /* @__PURE__ */ e.h("div", { className: "flex flex-col h-full min-h-0" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2 shrink-0", style: { marginBottom: 8 } }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: d,
        style: { ...o.btn, color: "var(--color-accent)", borderColor: "rgba(88,166,255,.4)" }
      },
      "⟳ Rescan discovery"
    ), /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => _(!y),
        style: { ...o.btn, color: y ? "#fbbf24" : "var(--color-text-muted)" }
      },
      "⚑ Flaky only"
    ), /* @__PURE__ */ e.h("span", { style: { marginLeft: "auto", fontSize: s.label, color: "var(--color-text-muted)" } }, h.length, " test", h.length === 1 ? "" : "s")), /* @__PURE__ */ e.h("div", { className: "overflow-auto min-h-0 flex-1" }, /* @__PURE__ */ e.h("table", { style: { width: "100%", borderCollapse: "collapse" } }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", null, /* @__PURE__ */ e.h("th", { style: { ...o.th, width: 26 } }), /* @__PURE__ */ e.h("th", { style: o.th }, "Test file"), /* @__PURE__ */ e.h("th", { style: o.th }, "Kind"), /* @__PURE__ */ e.h("th", { style: o.th }, "Component"), /* @__PURE__ */ e.h("th", { style: o.th }, "Last run"))), /* @__PURE__ */ e.h("tbody", null, h.map((c) => /* @__PURE__ */ e.h("tr", { key: c.file_path }, /* @__PURE__ */ e.h("td", { style: o.td }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => C(c.file_path),
        disabled: i[c.file_path],
        title: "Run this test",
        style: { color: "#4ade80", background: "none", border: 0, cursor: "pointer" }
      },
      i[c.file_path] ? "…" : "▶"
    )), /* @__PURE__ */ e.h("td", { style: { ...o.td, ...o.mono, color: "var(--color-text-primary)" } }, c.file_path, c.is_flaky && /* @__PURE__ */ e.h("span", { style: { marginLeft: 6, color: "#fbbf24" }, title: c.flaky_note || "flaky" }, "⚑")), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)" } }, c.kind), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)" } }, c.component_slug || "—"), /* @__PURE__ */ e.h("td", { style: o.td }, /* @__PURE__ */ e.h(S, { value: c.last_run_status })))))), h.length === 0 && /* @__PURE__ */ e.h(m, null, y ? "No tests flagged flaky." : "No tests here yet. Set a component’s test_base_path, then Rescan discovery.")), b && /* @__PURE__ */ e.h("div", { className: "shrink-0", style: {
      marginTop: 8,
      paddingTop: 8,
      borderTop: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: { marginBottom: 4 } }, /* @__PURE__ */ e.h(S, { value: b.status }), /* @__PURE__ */ e.h("span", { style: { ...o.mono, color: "var(--color-text-muted)" } }, b.file_path), /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => x(null),
        style: {
          marginLeft: "auto",
          background: "none",
          border: 0,
          color: "var(--color-text-muted)",
          cursor: "pointer"
        }
      },
      "✕"
    )), /* @__PURE__ */ e.h("pre", { style: {
      fontSize: s.label,
      lineHeight: 1.45,
      maxHeight: 160,
      overflow: "auto",
      whiteSpace: "pre-wrap",
      margin: 0,
      color: "var(--color-text-muted)",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    } }, b.output))) : /* @__PURE__ */ e.h(m, null, "Loading…");
  }
  function I({ slug: t }) {
    const [r, a] = p(null), [u, l] = p(null);
    return w(() => {
      if (!t) {
        a([]);
        return;
      }
      a(null), l(null), k(`/components/${encodeURIComponent(t)}/requirements`).then(a).catch((n) => l(n.message));
    }, [t]), t ? u ? /* @__PURE__ */ e.h(m, null, "Couldn’t load requirements — ", u) : r ? r.length === 0 ? /* @__PURE__ */ e.h(m, null, "No requirements documented for this component.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, r.map((n) => /* @__PURE__ */ e.h("div", { key: n.id, style: {
      border: "1px solid var(--color-border)",
      borderRadius: 8,
      padding: 10,
      marginBottom: 8
    } }, /* @__PURE__ */ e.h("div", { className: "flex items-start gap-2", style: { marginBottom: 6 } }, /* @__PURE__ */ e.h("span", { style: { fontSize: s.tab, flex: 1, color: "var(--color-text-primary)" } }, n.title), /* @__PURE__ */ e.h(S, { value: n.health })), /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, lineHeight: 1.65, color: "var(--color-text-muted)" } }, /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "Given"), " ", n.gherkin_given), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "When"), " ", n.gherkin_when), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { style: { color: "var(--color-text-primary)" } }, "Then"), " ", n.gherkin_then)), /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: {
      marginTop: 8,
      fontSize: s.label,
      color: "var(--color-text-muted)"
    } }, /* @__PURE__ */ e.h("span", null, "intended: ", /* @__PURE__ */ e.h("code", { style: o.mono }, n.intended_status)), n.kanban_url ? /* @__PURE__ */ e.h(
      "a",
      {
        href: n.kanban_url,
        target: "_blank",
        rel: "noreferrer",
        style: { color: "var(--color-accent)" }
      },
      "Kanban card ↗"
    ) : /* @__PURE__ */ e.h("span", { style: { color: "#fbbf24" } }, "no Kanban card linked"))))) : /* @__PURE__ */ e.h(m, null, "Loading…") : /* @__PURE__ */ e.h(m, null, "Select a component to see its requirements.");
  }
  function M({ slug: t }) {
    const [r, a] = p(null), [u, l] = p(null);
    return w(() => {
      a(null), l(null), k(`/debt${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(a).catch((n) => l(n.message));
    }, [t]), u ? /* @__PURE__ */ e.h(m, null, "Couldn’t load debt notes — ", u) : r ? r.length === 0 ? /* @__PURE__ */ e.h(m, null, "No open technical-debt notes.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("table", { style: { width: "100%", borderCollapse: "collapse" } }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", null, /* @__PURE__ */ e.h("th", { style: o.th }, "Noted"), /* @__PURE__ */ e.h("th", { style: o.th }, "Component"), /* @__PURE__ */ e.h("th", { style: o.th }, "Description"))), /* @__PURE__ */ e.h("tbody", null, r.map((n) => /* @__PURE__ */ e.h("tr", { key: n.id }, /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)", whiteSpace: "nowrap" } }, (n.noted_at || "").slice(0, 10)), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-muted)" } }, n.component_slug || "—"), /* @__PURE__ */ e.h("td", { style: { ...o.td, color: "var(--color-text-primary)" } }, n.description)))))) : /* @__PURE__ */ e.h(m, null, "Loading…");
  }
  function O({ slug: t }) {
    const [r, a] = p(null), [u, l] = p(null);
    if (w(() => {
      if (!t) {
        a(null);
        return;
      }
      a(null), l(null), k(`/components/${encodeURIComponent(t)}`).then(a).catch((i) => l(i.message));
    }, [t]), !t) return /* @__PURE__ */ e.h(m, null, "Select a component.");
    if (u) return /* @__PURE__ */ e.h(m, null, "Couldn’t load component — ", u);
    if (!r) return /* @__PURE__ */ e.h(m, null, "Loading…");
    const n = ({ k: i, v: f }) => /* @__PURE__ */ e.h("div", { className: "flex gap-3", style: {
      padding: "4px 0",
      borderBottom: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("span", { style: {
      ...o.label,
      width: 118,
      flexShrink: 0,
      color: "var(--color-text-muted)",
      paddingTop: 2
    } }, i), /* @__PURE__ */ e.h("span", { style: { fontSize: s.row, color: "var(--color-text-primary)" } }, f));
    return /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2", style: { marginBottom: 10 } }, /* @__PURE__ */ e.h("span", { style: { fontSize: s.title, color: "var(--color-text-primary)" } }, r.name), /* @__PURE__ */ e.h(S, { value: r.health })), /* @__PURE__ */ e.h(n, { k: "slug", v: /* @__PURE__ */ e.h("code", { style: o.mono }, r.slug) }), /* @__PURE__ */ e.h(n, { k: "repo", v: r.repo || "—" }), /* @__PURE__ */ e.h(n, { k: "layer", v: r.layer || "—" }), /* @__PURE__ */ e.h(n, { k: "technologies", v: (r.technologies || []).join(", ") || "—" }), /* @__PURE__ */ e.h(n, { k: "test_base_path", v: /* @__PURE__ */ e.h("code", { style: o.mono }, r.test_base_path || "—") }), /* @__PURE__ */ e.h(n, { k: "run_cmd", v: /* @__PURE__ */ e.h("code", { style: o.mono }, r.run_cmd || "—") }), /* @__PURE__ */ e.h(n, { k: "test_cmd", v: /* @__PURE__ */ e.h("code", { style: o.mono }, r.test_cmd || "—") }), r.description && /* @__PURE__ */ e.h("p", { style: {
      marginTop: 12,
      fontSize: s.row,
      lineHeight: 1.6,
      color: "var(--color-text-muted)",
      whiteSpace: "pre-wrap"
    } }, r.description), /* @__PURE__ */ e.h("div", { style: { marginTop: 14 } }, /* @__PURE__ */ e.h("div", { style: { ...o.label, color: "var(--color-text-muted)", marginBottom: 4 } }, "Connections"), (r.connections || []).length === 0 ? /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, color: "var(--color-text-muted)" } }, "none") : (r.connections || []).map((i) => /* @__PURE__ */ e.h("div", { key: i.id, style: { fontSize: s.row, color: "var(--color-text-primary)" } }, /* @__PURE__ */ e.h("code", { style: { ...o.mono, color: "var(--color-accent)" } }, i.kind), " → ", i.to_slug, i.description ? /* @__PURE__ */ e.h("span", { style: { color: "var(--color-text-muted)" } }, " — ", i.description) : null))), /* @__PURE__ */ e.h("div", { style: { marginTop: 12 } }, /* @__PURE__ */ e.h("div", { style: { ...o.label, color: "var(--color-text-muted)", marginBottom: 4 } }, "MCP tools"), (r.tools || []).length === 0 ? /* @__PURE__ */ e.h("div", { style: { fontSize: s.row, color: "var(--color-text-muted)" } }, "none exposed") : (r.tools || []).map((i) => /* @__PURE__ */ e.h("div", { key: i.id, style: { ...o.mono, color: "var(--color-text-primary)" } }, i.name))));
  }
  function W() {
    const [t, r] = p(null), [a, u] = p(null), [l, n] = p(null), [i, f] = p("tests"), [b, x] = p(!1), [y, _] = p(""), g = N(() => {
      u(null), k("/components").then(r).catch((d) => u(d.message));
    }, []);
    w(g, [g]);
    const C = T(() => {
      if (!t) return [];
      const d = y.trim().toLowerCase();
      return d ? t.filter((h) => h.slug.toLowerCase().includes(d) || h.name.toLowerCase().includes(d)).map((h) => ({ ...h, children: [] })).sort((h, c) => h.name.localeCompare(c.name)) : A(t);
    }, [t, y]);
    return /* @__PURE__ */ e.h("div", { className: "flex h-full min-h-0", style: { color: "var(--color-text-primary)" } }, /* @__PURE__ */ e.h("div", { className: "flex flex-col min-h-0", style: {
      width: 240,
      flexShrink: 0,
      borderRight: "1px solid var(--color-border)"
    } }, /* @__PURE__ */ e.h("div", { className: "shrink-0", style: { padding: 8 } }, /* @__PURE__ */ e.h(
      "input",
      {
        value: y,
        onChange: (d) => _(d.target.value),
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
    )), /* @__PURE__ */ e.h("div", { className: "overflow-auto flex-1 min-h-0", style: { padding: "0 6px 8px" } }, a && /* @__PURE__ */ e.h(m, null, "Couldn’t load — ", a), !t && !a && /* @__PURE__ */ e.h(m, null, "Loading…"), t && t.length === 0 && /* @__PURE__ */ e.h(m, null, "No components registered yet — the catalog is curated through the architecture MCP tools."), C.map((d) => /* @__PURE__ */ e.h(L, { key: d.slug, node: d, depth: 0, selected: l, onSelect: n })))), /* @__PURE__ */ e.h("div", { className: "flex flex-col min-w-0 min-h-0", style: { flex: 1 } }, /* @__PURE__ */ e.h("div", { className: "flex items-center shrink-0", style: {
      padding: "0 8px",
      borderBottom: "1px solid var(--color-border)"
    } }, F.map((d) => /* @__PURE__ */ e.h(
      "button",
      {
        key: d.id,
        onClick: () => f(d.id),
        style: {
          padding: "7px 11px",
          fontSize: s.tab,
          background: "none",
          cursor: "pointer",
          border: 0,
          borderBottom: "2px solid",
          borderBottomColor: i === d.id ? "var(--color-accent)" : "transparent",
          color: i === d.id ? "var(--color-text-primary)" : "var(--color-text-muted)"
        }
      },
      d.label
    )), /* @__PURE__ */ e.h("span", { style: {
      marginLeft: "auto",
      paddingRight: 4,
      fontSize: s.label,
      color: "var(--color-text-muted)"
    } }, b ? "scanning…" : l || "all components")), /* @__PURE__ */ e.h("div", { className: "flex-1 min-h-0", style: { padding: 10 } }, i === "tests" && /* @__PURE__ */ e.h(E, { slug: l, onBusy: (d) => {
      x(d), d || g();
    } }), i === "requirements" && /* @__PURE__ */ e.h(I, { slug: l }), i === "debt" && /* @__PURE__ */ e.h(M, { slug: l }), i === "detail" && /* @__PURE__ */ e.h(O, { slug: l }))));
  }
  function $() {
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
  function q() {
    return /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => {
          var t;
          return (t = window.__awOpenAppWindow) == null ? void 0 : t.call(window, B, void 0, "Architecture");
        },
        className: "w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.06] cursor-pointer text-left",
        title: "Components, requirements, test traceability"
      },
      /* @__PURE__ */ e.h($, null),
      /* @__PURE__ */ e.h("span", { className: "text-[13px] text-[var(--color-text-primary)]" }, "Architecture")
    );
  }
  e.registerWindow(B, W), e.registerSlot("core.nav.workspace", q);
}
export {
  j as default,
  j as register
};
