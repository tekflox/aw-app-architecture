const H = "architecture", L = "architecture.main", E = {
  implemented: "text-green-400",
  passing: "text-green-400",
  partial: "text-amber-400",
  broken: "text-red-400",
  fail: "text-red-400",
  not_implemented: "text-[var(--color-text-muted)]",
  planned: "text-[var(--color-text-muted)]",
  unknown: "text-[var(--color-text-muted)]"
}, U = [
  { id: "tests", label: "Tests" },
  { id: "requirements", label: "Requirements" },
  { id: "debt", label: "Debt & Bugs" },
  { id: "detail", label: "Detail" }
];
function j(e) {
  const { useState: p, useEffect: N, useCallback: _, useMemo: C } = e.React, T = (t, a) => e.sdk.api.fetch(`/api/apps/${H}${t}`, a), g = async (t) => {
    const a = await T(t);
    if (!a.ok) throw new Error(`HTTP ${a.status}`);
    return a.json();
  }, R = async (t, a) => {
    const l = await T(t, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(a || {})
    });
    if (!l.ok) throw new Error(`HTTP ${l.status}`);
    return l.json();
  };
  function y({ value: t }) {
    const a = t || "unknown";
    return /* @__PURE__ */ e.h("span", { className: `text-[10px] uppercase tracking-wide ${E[a] || E.unknown}` }, a.replace(/_/g, " "));
  }
  function u({ children: t }) {
    return /* @__PURE__ */ e.h("div", { className: "py-8 text-center text-xs text-[var(--color-text-muted)]" }, t);
  }
  function S(t) {
    const a = new Map(t.map((n) => [n.slug, { ...n, children: [] }])), l = [];
    for (const n of a.values()) {
      const r = n.parent_slug ? a.get(n.parent_slug) : null;
      r ? r.children.push(n) : l.push(n);
    }
    const i = (n) => (n.sort((r, c) => r.name.localeCompare(c.name)), n.forEach((r) => i(r.children)), n);
    return i(l);
  }
  function $({ node: t, depth: a, selected: l, onSelect: i }) {
    const [n, r] = p(!0), c = l === t.slug;
    return /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h(
      "div",
      {
        onClick: () => i(t.slug),
        style: { paddingLeft: `${8 + a * 12}px` },
        className: `flex items-center gap-1.5 py-1 pr-2 rounded cursor-pointer text-[12px] ${c ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]" : "hover:bg-white/5 text-[var(--color-text-primary)]"}`
      },
      t.children.length > 0 ? /* @__PURE__ */ e.h(
        "span",
        {
          onClick: (m) => {
            m.stopPropagation(), r(!n);
          },
          className: "w-3 shrink-0 text-[var(--color-text-muted)]"
        },
        n ? "▾" : "▸"
      ) : /* @__PURE__ */ e.h("span", { className: "w-3 shrink-0" }),
      /* @__PURE__ */ e.h("span", { className: "truncate flex-1" }, t.name),
      /* @__PURE__ */ e.h(y, { value: t.health })
    ), n && t.children.map((m) => /* @__PURE__ */ e.h($, { key: m.slug, node: m, depth: a + 1, selected: l, onSelect: i })));
  }
  function O({ slug: t, onBusy: a }) {
    const [l, i] = p(null), [n, r] = p(null), [c, m] = p({}), [b, f] = p(null), [x, w] = p(!1), v = _(() => {
      r(null), g(`/component-tests${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(i).catch((o) => r(o.message));
    }, [t]);
    N(v, [v]);
    const k = async (o) => {
      m((h) => ({ ...h, [o]: !0 })), f(null);
      try {
        const h = await R("/testcases/run", { file_path: o });
        f(h), v();
      } catch (h) {
        f({
          file_path: o,
          status: "unknown",
          output: `Could not read the result back (${h.message}). The run may still be going server-side — its recorded status will appear on refresh.`
        });
      } finally {
        m((h) => ({ ...h, [o]: !1 }));
      }
    }, s = async () => {
      a(!0);
      try {
        await R("/discovery/run"), v();
      } catch (o) {
        r(o.message);
      } finally {
        a(!1);
      }
    }, d = C(
      () => (l || []).filter((o) => !x || o.is_flaky),
      [l, x]
    );
    return n ? /* @__PURE__ */ e.h(u, null, "Couldn’t load tests — ", n) : l ? /* @__PURE__ */ e.h("div", { className: "flex flex-col h-full min-h-0" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2 mb-2 shrink-0" }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: s,
        className: "text-[10.5px] px-2.5 py-1 rounded border border-[var(--color-accent)]/40 text-[var(--color-accent)]"
      },
      "⟳ Rescan discovery"
    ), /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => w(!x),
        className: `text-[10.5px] px-2.5 py-1 rounded border border-[var(--color-border)] ${x ? "text-amber-400" : "text-[var(--color-text-muted)]"}`
      },
      "⚑ Flaky only"
    ), /* @__PURE__ */ e.h("span", { className: "ml-auto text-[10.5px] text-[var(--color-text-muted)]" }, d.length, " test", d.length === 1 ? "" : "s")), /* @__PURE__ */ e.h("div", { className: "overflow-auto min-h-0 flex-1" }, /* @__PURE__ */ e.h("table", { className: "w-full text-[11.5px]" }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", { className: "text-left text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] border-b border-[var(--color-border)]" }, /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2 w-6" }), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Test file"), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Kind"), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Component"), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Last run"))), /* @__PURE__ */ e.h("tbody", null, d.map((o) => /* @__PURE__ */ e.h("tr", { key: o.file_path, className: "border-b border-[var(--color-border)]/40" }, /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2" }, /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => k(o.file_path),
        disabled: c[o.file_path],
        title: "Run this test",
        className: "text-green-400 disabled:opacity-40"
      },
      c[o.file_path] ? "…" : "▶"
    )), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 font-mono text-[11px] text-[var(--color-text-primary)]" }, o.file_path, o.is_flaky && /* @__PURE__ */ e.h("span", { className: "ml-1.5 text-amber-400", title: o.flaky_note || "flaky" }, "⚑")), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 text-[var(--color-text-muted)]" }, o.kind), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 text-[var(--color-text-muted)]" }, o.component_slug || "—"), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2" }, /* @__PURE__ */ e.h(y, { value: o.last_run_status })))))), d.length === 0 && /* @__PURE__ */ e.h(u, null, x ? "No tests flagged flaky." : "No tests here yet. Set a component’s test_base_path, then Rescan discovery.")), b && /* @__PURE__ */ e.h("div", { className: "shrink-0 mt-2 border-t border-[var(--color-border)] pt-2" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2 text-[11px] mb-1" }, /* @__PURE__ */ e.h(y, { value: b.status }), /* @__PURE__ */ e.h("span", { className: "font-mono text-[10.5px] text-[var(--color-text-muted)]" }, b.file_path), /* @__PURE__ */ e.h("button", { onClick: () => f(null), className: "ml-auto text-[var(--color-text-muted)]" }, "✕")), /* @__PURE__ */ e.h("pre", { className: `text-[10px] leading-[1.45] max-h-40 overflow-auto whitespace-pre-wrap
                            text-[var(--color-text-muted)] font-mono` }, b.output))) : /* @__PURE__ */ e.h(u, null, "Loading…");
  }
  function q({ slug: t }) {
    const [a, l] = p(null), [i, n] = p(null);
    return N(() => {
      if (!t) {
        l([]);
        return;
      }
      l(null), n(null), g(`/components/${encodeURIComponent(t)}/requirements`).then(l).catch((r) => n(r.message));
    }, [t]), t ? i ? /* @__PURE__ */ e.h(u, null, "Couldn’t load requirements — ", i) : a ? a.length === 0 ? /* @__PURE__ */ e.h(u, null, "No requirements documented for this component.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full space-y-2.5" }, a.map((r) => /* @__PURE__ */ e.h("div", { key: r.id, className: "border border-[var(--color-border)] rounded-lg p-3" }, /* @__PURE__ */ e.h("div", { className: "flex items-start gap-2 mb-1.5" }, /* @__PURE__ */ e.h("span", { className: "text-[12.5px] text-[var(--color-text-primary)] flex-1" }, r.title), /* @__PURE__ */ e.h(y, { value: r.health })), /* @__PURE__ */ e.h("div", { className: "text-[11px] leading-relaxed text-[var(--color-text-muted)] space-y-0.5" }, /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { className: "text-[var(--color-text-primary)]" }, "Given"), " ", r.gherkin_given), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { className: "text-[var(--color-text-primary)]" }, "When"), " ", r.gherkin_when), /* @__PURE__ */ e.h("div", null, /* @__PURE__ */ e.h("b", { className: "text-[var(--color-text-primary)]" }, "Then"), " ", r.gherkin_then)), /* @__PURE__ */ e.h("div", { className: "mt-2 flex items-center gap-2 text-[10px] text-[var(--color-text-muted)]" }, /* @__PURE__ */ e.h("span", null, "intended: ", /* @__PURE__ */ e.h("code", null, r.intended_status)), r.kanban_url ? /* @__PURE__ */ e.h(
      "a",
      {
        href: r.kanban_url,
        target: "_blank",
        rel: "noreferrer",
        className: "text-[var(--color-accent)]"
      },
      "Kanban card ↗"
    ) : /* @__PURE__ */ e.h("span", { className: "text-amber-400/80" }, "no Kanban card linked"))))) : /* @__PURE__ */ e.h(u, null, "Loading…") : /* @__PURE__ */ e.h(u, null, "Select a component to see its requirements.");
  }
  function D({ slug: t }) {
    const [a, l] = p(null), [i, n] = p(null);
    return N(() => {
      l(null), n(null), g(`/debt${t ? `?component_slug=${encodeURIComponent(t)}` : ""}`).then(l).catch((r) => n(r.message));
    }, [t]), i ? /* @__PURE__ */ e.h(u, null, "Couldn’t load debt notes — ", i) : a ? a.length === 0 ? /* @__PURE__ */ e.h(u, null, "No open technical-debt notes.") : /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("table", { className: "w-full text-[11.5px]" }, /* @__PURE__ */ e.h("thead", null, /* @__PURE__ */ e.h("tr", { className: "text-left text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] border-b border-[var(--color-border)]" }, /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Noted"), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Component"), /* @__PURE__ */ e.h("th", { className: "py-1.5 px-2" }, "Description"))), /* @__PURE__ */ e.h("tbody", null, a.map((r) => /* @__PURE__ */ e.h("tr", { key: r.id, className: "border-b border-[var(--color-border)]/40" }, /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 text-[var(--color-text-muted)] whitespace-nowrap" }, (r.noted_at || "").slice(0, 10)), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 text-[var(--color-text-muted)]" }, r.component_slug || "—"), /* @__PURE__ */ e.h("td", { className: "py-1.5 px-2 text-[var(--color-text-primary)]" }, r.description)))))) : /* @__PURE__ */ e.h(u, null, "Loading…");
  }
  function A({ slug: t }) {
    const [a, l] = p(null), [i, n] = p(null);
    if (N(() => {
      if (!t) {
        l(null);
        return;
      }
      l(null), n(null), g(`/components/${encodeURIComponent(t)}`).then(l).catch((c) => n(c.message));
    }, [t]), !t) return /* @__PURE__ */ e.h(u, null, "Select a component.");
    if (i) return /* @__PURE__ */ e.h(u, null, "Couldn’t load component — ", i);
    if (!a) return /* @__PURE__ */ e.h(u, null, "Loading…");
    const r = ({ k: c, v: m }) => /* @__PURE__ */ e.h("div", { className: "flex gap-3 py-1 border-b border-[var(--color-border)]/40" }, /* @__PURE__ */ e.h("span", { className: "w-32 shrink-0 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] pt-0.5" }, c), /* @__PURE__ */ e.h("span", { className: "text-[11.5px] text-[var(--color-text-primary)]" }, m));
    return /* @__PURE__ */ e.h("div", { className: "overflow-auto h-full" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-2 mb-3" }, /* @__PURE__ */ e.h("span", { className: "text-[14px] text-[var(--color-text-primary)]" }, a.name), /* @__PURE__ */ e.h(y, { value: a.health })), /* @__PURE__ */ e.h(r, { k: "slug", v: /* @__PURE__ */ e.h("code", { className: "text-[11px]" }, a.slug) }), /* @__PURE__ */ e.h(r, { k: "repo", v: a.repo || "—" }), /* @__PURE__ */ e.h(r, { k: "layer", v: a.layer || "—" }), /* @__PURE__ */ e.h(r, { k: "technologies", v: (a.technologies || []).join(", ") || "—" }), /* @__PURE__ */ e.h(r, { k: "test_base_path", v: /* @__PURE__ */ e.h("code", { className: "text-[11px]" }, a.test_base_path || "—") }), /* @__PURE__ */ e.h(r, { k: "run_cmd", v: /* @__PURE__ */ e.h("code", { className: "text-[11px]" }, a.run_cmd || "—") }), /* @__PURE__ */ e.h(r, { k: "test_cmd", v: /* @__PURE__ */ e.h("code", { className: "text-[11px]" }, a.test_cmd || "—") }), a.description && /* @__PURE__ */ e.h("p", { className: "mt-3 text-[11.5px] leading-relaxed text-[var(--color-text-muted)] whitespace-pre-wrap" }, a.description), /* @__PURE__ */ e.h("div", { className: "mt-4" }, /* @__PURE__ */ e.h("div", { className: "text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] mb-1" }, "Connections"), (a.connections || []).length === 0 ? /* @__PURE__ */ e.h("div", { className: "text-[11.5px] text-[var(--color-text-muted)]" }, "none") : (a.connections || []).map((c) => /* @__PURE__ */ e.h("div", { key: c.id, className: "text-[11.5px] text-[var(--color-text-primary)]" }, /* @__PURE__ */ e.h("code", { className: "text-[10.5px] text-[var(--color-accent)]" }, c.kind), " → ", c.to_slug, c.description ? /* @__PURE__ */ e.h("span", { className: "text-[var(--color-text-muted)]" }, " — ", c.description) : null))), /* @__PURE__ */ e.h("div", { className: "mt-3" }, /* @__PURE__ */ e.h("div", { className: "text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] mb-1" }, "MCP tools"), (a.tools || []).length === 0 ? /* @__PURE__ */ e.h("div", { className: "text-[11.5px] text-[var(--color-text-muted)]" }, "none exposed") : (a.tools || []).map((c) => /* @__PURE__ */ e.h("div", { key: c.id, className: "text-[11.5px] font-mono text-[var(--color-text-primary)]" }, c.name))));
  }
  function I() {
    const [t, a] = p(null), [l, i] = p(null), [n, r] = p(null), [c, m] = p("tests"), [b, f] = p(!1), [x, w] = p(""), v = _(() => {
      i(null), g("/components").then(a).catch((s) => i(s.message));
    }, []);
    N(v, [v]);
    const k = C(() => {
      if (!t) return [];
      const s = x.trim().toLowerCase();
      return s ? t.filter((d) => d.slug.toLowerCase().includes(s) || d.name.toLowerCase().includes(s)).map((d) => ({ ...d, children: [] })).sort((d, o) => d.name.localeCompare(o.name)) : S(t);
    }, [t, x]);
    return /* @__PURE__ */ e.h("div", { className: "flex h-full min-h-0 text-[var(--color-text-primary)]" }, /* @__PURE__ */ e.h("div", { className: "w-[240px] shrink-0 border-r border-[var(--color-border)] flex flex-col min-h-0" }, /* @__PURE__ */ e.h("div", { className: "p-2 shrink-0" }, /* @__PURE__ */ e.h(
      "input",
      {
        value: x,
        onChange: (s) => w(s.target.value),
        placeholder: "Filter components…",
        className: `w-full bg-transparent border border-[var(--color-border)] rounded px-2 py-1
                         text-[11.5px] outline-none focus:border-[var(--color-accent)]/50`
      }
    )), /* @__PURE__ */ e.h("div", { className: "overflow-auto flex-1 min-h-0 px-1 pb-2" }, l && /* @__PURE__ */ e.h(u, null, "Couldn’t load — ", l), !t && !l && /* @__PURE__ */ e.h(u, null, "Loading…"), t && t.length === 0 && /* @__PURE__ */ e.h(u, null, "No components registered yet. The catalog is managed through the", /* @__PURE__ */ e.h("code", { className: "mx-1" }, "aw__architecture__*"), " MCP tools."), k.map((s) => /* @__PURE__ */ e.h($, { key: s.slug, node: s, depth: 0, selected: n, onSelect: r })))), /* @__PURE__ */ e.h("div", { className: "flex-1 flex flex-col min-w-0 min-h-0" }, /* @__PURE__ */ e.h("div", { className: "flex items-center gap-1 px-2 border-b border-[var(--color-border)] shrink-0" }, U.map((s) => /* @__PURE__ */ e.h(
      "button",
      {
        key: s.id,
        onClick: () => m(s.id),
        className: `px-3 py-2 text-[12px] border-b-2 ${c === s.id ? "border-[var(--color-accent)] text-[var(--color-text-primary)]" : "border-transparent text-[var(--color-text-muted)]"}`
      },
      s.label
    )), /* @__PURE__ */ e.h("span", { className: "ml-auto pr-1 text-[10.5px] text-[var(--color-text-muted)]" }, b ? "scanning…" : n || "all components")), /* @__PURE__ */ e.h("div", { className: "flex-1 min-h-0 p-3" }, c === "tests" && /* @__PURE__ */ e.h(O, { slug: n, onBusy: (s) => {
      f(s), s || v();
    } }), c === "requirements" && /* @__PURE__ */ e.h(q, { slug: n }), c === "debt" && /* @__PURE__ */ e.h(D, { slug: n }), c === "detail" && /* @__PURE__ */ e.h(A, { slug: n }))));
  }
  function W() {
    return /* @__PURE__ */ e.h(
      "button",
      {
        onClick: () => {
          var t;
          return (t = window.__awOpenAppWindow) == null ? void 0 : t.call(window, L, void 0, "Architecture");
        },
        className: "flex items-center gap-2 w-full px-3 py-1.5 hover:bg-white/5 text-left",
        title: "Components, requirements, test traceability"
      },
      /* @__PURE__ */ e.h("span", { className: "text-[13px]" }, "Architecture")
    );
  }
  e.registerWindow(L, I), e.registerSlot("core.nav", W);
}
export {
  j as default,
  j as register
};
