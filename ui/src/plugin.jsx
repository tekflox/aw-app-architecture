// Integrated-mode entrypoint — dynamic-imported by aw-workspace-ui's
// loadComponentPlugin() once this app is installed with "ui:code" +
// "ui:slots:core.nav.workspace" granted. Built by `npm run build` -> ui/dist/
// architecture.js, referenced from aw-app.json's contributes.frontend.bundle.
// Same register(host)/JSX-factory pattern as aw-app-presentations — every
// component is declared INSIDE register(host), closing over `host`, so JSX
// compiles against the ONE shared React instance (react/react-dom stay
// external, never bundled; see vite.config.js).
//
// THE MERGE. The monolith had two surfaces over one dataset:
//
//   Settings > Architecture (ArchitectureTab.jsx)  — components + health,
//       a flat table you clicked into for a detail page.
//   Workspace > Tests (TestsPanel.jsx)             — the traceability matrix,
//       the play button, the discovery rescan.
//
// They never referenced each other, so answering "is this component healthy,
// and which of its tests is red?" meant opening two different places and
// matching slugs by eye. Here the component list becomes the left rail and
// everything else is a tab on the right, scoped to whatever is selected —
// selection is the join the old UI made the user perform.
//
// The left rail is a TREE, not the old flat table: `component.parent_slug` was
// always in the schema (self-referencing FK) and the old table dropped it,
// which is why a 40-component catalog read as an undifferentiated list.
//
// ---------------------------------------------------------------------------
// SIZING IS INLINE, ON PURPOSE — do not "tidy" it back into Tailwind classes.
//
// An app bundle is loaded into the SPA at runtime; the SPA's CSS was compiled
// long before, from ITS OWN source. Tailwind only emits the arbitrary-value
// utilities it saw while scanning that source, so a class this file invents is
// simply absent at runtime. Verified against the built stylesheet: core uses
// (and therefore ships) `text-[10px]`, `text-[12px]`, `text-[13px]` and the
// `[var(--color-*)]` colour utilities, but nothing emits `text-[11.5px]`,
// `text-[12.5px]` or `w-[240px]`.
//
// The failure is silent and looks like a layout bug: `w-[240px] shrink-0` on
// the rail resolved to no width rule at all, so flex split the window ~50/50,
// and every `text-[10.5px]` label rendered at the inherited size. Everything
// dimensional therefore goes through `style={{…}}`, which cannot vanish.
// Structural utilities (flex, gap-2, px-2, overflow-auto) and the colour
// variables are safe — core uses them everywhere.
// ---------------------------------------------------------------------------

const SLUG = 'architecture';
const WINDOW_ID = 'architecture.main';

const RAIL_WIDTH = 240;

// Type scale, in px. Named so the intent survives being inline.
const FS = {
  title: 14,
  nav: 13,
  tab: 12,
  row: 11.5,
  mono: 11,
  label: 10,
};

const HEALTH_COLOR = {
  implemented: '#4ade80',
  passing: '#4ade80',
  running: '#58a6ff',
  partial: '#fbbf24',
  broken: '#f87171',
  fail: '#f87171',
  not_implemented: 'var(--color-text-muted)',
  planned: 'var(--color-text-muted)',
  unknown: 'var(--color-text-muted)',
};

const TABS = [
  { id: 'tests', label: 'Tests' },
  { id: 'requirements', label: 'Requirements' },
  { id: 'debt', label: 'Debt & Bugs' },
  { id: 'detail', label: 'Detail' },
];

const ICON = {
  // Unicode symbols (⟳ ▶ ⚑ ▾ ✕ ↗) render as tofu boxes here — the browser
  // container's font stack has no glyph for them. Inline SVG doesn't care
  // what fonts the image ships.
  refresh: 'M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10 M1 14l4.64 4.36A9 9 0 0 0 20.49 15',
  flag: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z M4 22v-7',
  close: 'M18 6L6 18M6 6l12 12',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 18l6-6-6-6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
};

const S = {
  label: { fontSize: FS.label, textTransform: 'uppercase', letterSpacing: '.06em' },
  mono: { fontSize: FS.mono, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
  th: {
    fontSize: FS.label, textTransform: 'uppercase', letterSpacing: '.06em',
    fontWeight: 500, textAlign: 'left', padding: '5px 8px',
    color: 'var(--color-text-muted)',
    borderBottom: '1px solid var(--color-border)',
  },
  td: { fontSize: FS.row, padding: '5px 8px', borderBottom: '1px solid var(--color-border)' },
  btn: {
    fontSize: FS.label, padding: '3px 9px', borderRadius: 6,
    border: '1px solid var(--color-border)', color: 'var(--color-text-muted)',
    background: 'transparent', lineHeight: 1.6, whiteSpace: 'nowrap', cursor: 'pointer',
  },
};

export function register(host) {
  const { useState, useEffect, useCallback, useMemo } = host.React;
  const api = (sub, init) => host.sdk.api.fetch(`/api/apps/${SLUG}${sub}`, init);

  const getJson = async (sub) => {
    const r = await api(sub);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };
  const postJson = async (sub, body) => {
    const r = await api(sub, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };

  // -- small shared bits --------------------------------------------------

  function Health({ value }) {
    const v = value || 'unknown';
    return (
      <span style={{ ...S.label, color: HEALTH_COLOR[v] || HEALTH_COLOR.unknown, fontWeight: 700 }}>
        {v.replace(/_/g, ' ')}
      </span>
    );
  }

  function Icon({ d, size = 12, color = 'currentColor', fill = 'none', style }) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
           strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
           style={{ flexShrink: 0, ...style }}>
        <path d={d} />
      </svg>
    );
  }

  function Empty({ children }) {
    return (
      <div style={{
        padding: '28px 16px', textAlign: 'center', fontSize: FS.row,
        color: 'var(--color-text-muted)', lineHeight: 1.6,
      }}>{children}</div>
    );
  }

  // -- left rail: the component tree --------------------------------------

  // Built from parent_slug rather than requested pre-nested: /components is a
  // flat list (it always was), and nesting in the client keeps the endpoint
  // usable by everything else that just wants "every component".
  function buildTree(components) {
    const bySlug = new Map(components.map((c) => [c.slug, { ...c, children: [] }]));
    const roots = [];
    for (const node of bySlug.values()) {
      const parent = node.parent_slug ? bySlug.get(node.parent_slug) : null;
      // A parent_slug pointing at a component that isn't in the current filter
      // (or was deleted with ON DELETE SET NULL mid-flight) must not vanish the
      // child — orphans surface at root rather than disappearing.
      if (parent) parent.children.push(node);
      else roots.push(node);
    }
    const sortRec = (nodes) => {
      nodes.sort((a, b) => a.name.localeCompare(b.name));
      nodes.forEach((n) => sortRec(n.children));
      return nodes;
    };
    return sortRec(roots);
  }

  function TreeNode({ node, depth, selected, onSelect }) {
    const [open, setOpen] = useState(true);
    const isSel = selected === node.slug;
    return (
      <div>
        <div
          onClick={() => onSelect(node.slug)}
          className="flex items-center gap-1 cursor-pointer"
          style={{
            paddingLeft: 6 + depth * 12, paddingRight: 6,
            paddingTop: 3, paddingBottom: 3, borderRadius: 5,
            fontSize: FS.row,
            background: isSel ? 'rgba(88,166,255,.14)' : 'transparent',
            color: isSel ? 'var(--color-accent)' : 'var(--color-text-primary)',
          }}
        >
          <span
            onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
            style={{ width: 12, flexShrink: 0, display: 'inline-flex',
                     alignItems: 'center', color: 'var(--color-text-muted)' }}
          >{node.children.length > 0
              ? <Icon d={open ? ICON.chevronDown : ICON.chevronRight} size={11} />
              : null}</span>
          <span className="truncate" style={{ flex: 1 }}>{node.name}</span>
          <Health value={node.health} />
        </div>
        {open && node.children.map((c) => (
          <TreeNode key={c.slug} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}
      </div>
    );
  }

  // -- right pane: tabs ---------------------------------------------------

  function TestsTab({ slug, onBusy }) {
    const [rows, setRows] = useState(null);
    const [error, setError] = useState(null);
    const [running, setRunning] = useState({});
    const [output, setOutput] = useState(null);
    const [flakyOnly, setFlakyOnly] = useState(false);

    const load = useCallback(() => {
      setError(null);
      getJson(`/component-tests${slug ? `?component_slug=${encodeURIComponent(slug)}` : ''}`)
        .then(setRows).catch((e) => setError(e.message));
    }, [slug]);

    useEffect(load, [load]);

    // Start the run, then poll the job. The request used to stay open for the
    // whole suite, which the tunnel edge cuts at ~30s — a slow pass came back
    // as "502 workspace offline" and there was no way to tell it from a dead
    // workspace. Now the only long-lived thing is the poll, and each poll is
    // a normal short request.
    const runOne = async (filePath) => {
      setRunning((r) => ({ ...r, [filePath]: true }));
      setOutput({ file_path: filePath, status: 'running', output: 'starting…' });
      try {
        const job = await postJson('/testcases/run', { file_path: filePath });
        for (;;) {
          const j = await getJson(`/testcases/jobs/${job.id}`);
          if (j.status === 'done') {
            setOutput(j.error
              ? { file_path: filePath, status: 'unknown', output: j.error }
              : j.result);
            load();
            break;
          }
          setOutput({
            file_path: filePath, status: 'running',
            output: j.status === 'queued'
              ? 'queued — another test is running'
              : 'running…',
          });
          await new Promise((r) => setTimeout(r, 1500));
        }
      } catch (e) {
        // A failed poll says nothing about the test: the run lives in the
        // workspace either way, and its recorded status appears on refresh.
        setOutput({
          file_path: filePath, status: 'unknown',
          output: `Lost track of the run (${e.message}). It may still be going `
                + `server-side — its recorded status will appear on refresh.`,
        });
      } finally {
        setRunning((r) => ({ ...r, [filePath]: false }));
      }
    };

    const rescan = async () => {
      onBusy(true);
      try { await postJson('/discovery/run'); load(); }
      catch (e) { setError(e.message); }
      finally { onBusy(false); }
    };

    const shown = useMemo(
      () => (rows || []).filter((r) => !flakyOnly || r.is_flaky),
      [rows, flakyOnly],
    );

    if (error) return <Empty>Couldn’t load tests — {error}</Empty>;
    if (!rows) return <Empty>Loading…</Empty>;

    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="flex items-center gap-2 shrink-0" style={{ marginBottom: 8 }}>
          <button onClick={rescan}
            style={{ ...S.btn, color: 'var(--color-accent)', borderColor: 'rgba(88,166,255,.4)',
                     display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <Icon d={ICON.refresh} size={11} /> Rescan discovery
          </button>
          <button onClick={() => setFlakyOnly(!flakyOnly)}
            style={{ ...S.btn, color: flakyOnly ? '#fbbf24' : 'var(--color-text-muted)',
                     display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <Icon d={ICON.flag} size={11} /> Flaky only
          </button>
          <span style={{ marginLeft: 'auto', fontSize: FS.label, color: 'var(--color-text-muted)' }}>
            {shown.length} test{shown.length === 1 ? '' : 's'}
          </span>
        </div>

        <div className="overflow-auto min-h-0 flex-1">
          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <thead>
              <tr>
                <th style={{ ...S.th, width: 26 }} />
                <th style={S.th}>Test file</th>
                <th style={{ ...S.th, width: 78 }}>Kind</th>
                <th style={{ ...S.th, width: 120 }}>Component</th>
                <th style={{ ...S.th, width: 84 }}>Last run</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.file_path}>
                  <td style={S.td}>
                    <button onClick={() => runOne(t.file_path)} disabled={running[t.file_path]}
                      title="Run this test"
                      style={{ color: '#4ade80', background: 'none', border: 0,
                               cursor: 'pointer', padding: 0, lineHeight: 0 }}>
                      {running[t.file_path]
                        ? <span style={{ fontSize: FS.label }}>…</span>
                        : <Icon d="M8 5v14l11-7z" size={12} fill="currentColor" color="none" />}
                    </button>
                  </td>
                  <td style={{ ...S.td, ...S.mono, color: 'var(--color-text-primary)',
                               overflow: 'hidden', textOverflow: 'ellipsis',
                               whiteSpace: 'nowrap' }}
                      title={t.file_path}>
                    {t.file_path}
                    {t.is_flaky && (
                      <Icon d={ICON.flag} size={10} color="#fbbf24"
                            style={{ marginLeft: 5, verticalAlign: '-1px' }} />
                    )}
                  </td>
                  <td style={{ ...S.td, color: 'var(--color-text-muted)',
                               whiteSpace: 'nowrap' }}>{t.kind}</td>
                  <td style={{ ...S.td, color: 'var(--color-text-muted)', overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={t.component_slug || ''}>{t.component_slug || '—'}</td>
                  <td style={{ ...S.td, whiteSpace: 'nowrap' }}>
                    <Health value={t.last_run_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <Empty>
              {flakyOnly ? 'No tests flagged flaky.'
                : 'No tests here yet. Set a component’s test_base_path, then Rescan discovery.'}
            </Empty>
          )}
        </div>

        {output && (
          <div className="shrink-0" style={{
            marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--color-border)',
          }}>
            <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
              <Health value={output.status} />
              <span style={{ ...S.mono, color: 'var(--color-text-muted)' }}>{output.file_path}</span>
              <button onClick={() => setOutput(null)}
                style={{ marginLeft: 'auto', background: 'none', border: 0, padding: 0,
                         lineHeight: 0, color: 'var(--color-text-muted)', cursor: 'pointer' }}>
                <Icon d={ICON.close} size={11} /></button>
            </div>
            <pre style={{
              fontSize: FS.label, lineHeight: 1.45, maxHeight: 160, overflow: 'auto',
              whiteSpace: 'pre-wrap', margin: 0,
              color: 'var(--color-text-muted)',
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            }}>{output.output}</pre>
          </div>
        )}
      </div>
    );
  }

  function RequirementsTab({ slug }) {
    const [rows, setRows] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
      if (!slug) { setRows([]); return; }
      setRows(null); setError(null);
      getJson(`/components/${encodeURIComponent(slug)}/requirements`)
        .then(setRows).catch((e) => setError(e.message));
    }, [slug]);

    if (!slug) return <Empty>Select a component to see its requirements.</Empty>;
    if (error) return <Empty>Couldn’t load requirements — {error}</Empty>;
    if (!rows) return <Empty>Loading…</Empty>;
    if (rows.length === 0) return <Empty>No requirements documented for this component.</Empty>;

    return (
      <div className="overflow-auto h-full">
        {rows.map((r) => (
          <div key={r.id} style={{
            border: '1px solid var(--color-border)', borderRadius: 8,
            padding: 10, marginBottom: 8,
          }}>
            <div className="flex items-start gap-2" style={{ marginBottom: 6 }}>
              <span style={{ fontSize: FS.tab, flex: 1, color: 'var(--color-text-primary)' }}>{r.title}</span>
              <Health value={r.health} />
            </div>
            <div style={{ fontSize: FS.row, lineHeight: 1.65, color: 'var(--color-text-muted)' }}>
              <div><b style={{ color: 'var(--color-text-primary)' }}>Given</b> {r.gherkin_given}</div>
              <div><b style={{ color: 'var(--color-text-primary)' }}>When</b> {r.gherkin_when}</div>
              <div><b style={{ color: 'var(--color-text-primary)' }}>Then</b> {r.gherkin_then}</div>
            </div>
            <div className="flex items-center gap-2" style={{
              marginTop: 8, fontSize: FS.label, color: 'var(--color-text-muted)',
            }}>
              <span>intended: <code style={S.mono}>{r.intended_status}</code></span>
              {r.kanban_url
                ? <a href={r.kanban_url} target="_blank" rel="noreferrer"
                     style={{ color: 'var(--color-accent)' }}>Kanban card</a>
                /* set_requirement_status refuses to move a requirement to
                   'implemented' without a card, so a missing link on an
                   implemented row is worth showing, not hiding. */
                : <span style={{ color: '#fbbf24' }}>no Kanban card linked</span>}
            </div>
          </div>
        ))}
      </div>
    );
  }

  function DebtTab({ slug }) {
    const [debt, setDebt] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
      setDebt(null); setError(null);
      getJson(`/debt${slug ? `?component_slug=${encodeURIComponent(slug)}` : ''}`)
        .then(setDebt).catch((e) => setError(e.message));
    }, [slug]);

    if (error) return <Empty>Couldn’t load debt notes — {error}</Empty>;
    if (!debt) return <Empty>Loading…</Empty>;
    if (debt.length === 0) return <Empty>No open technical-debt notes.</Empty>;

    return (
      <div className="overflow-auto h-full">
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={S.th}>Noted</th>
              <th style={S.th}>Component</th>
              <th style={S.th}>Description</th>
            </tr>
          </thead>
          <tbody>
            {debt.map((d) => (
              <tr key={d.id}>
                <td style={{ ...S.td, color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                  {(d.noted_at || '').slice(0, 10)}
                </td>
                <td style={{ ...S.td, color: 'var(--color-text-muted)' }}>{d.component_slug || '—'}</td>
                <td style={{ ...S.td, color: 'var(--color-text-primary)' }}>{d.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function DetailTab({ slug }) {
    const [c, setC] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
      if (!slug) { setC(null); return; }
      setC(null); setError(null);
      getJson(`/components/${encodeURIComponent(slug)}`)
        .then(setC).catch((e) => setError(e.message));
    }, [slug]);

    if (!slug) return <Empty>Select a component.</Empty>;
    if (error) return <Empty>Couldn’t load component — {error}</Empty>;
    if (!c) return <Empty>Loading…</Empty>;

    const Row = ({ k, v }) => (
      <div className="flex gap-3" style={{
        padding: '4px 0', borderBottom: '1px solid var(--color-border)',
      }}>
        <span style={{
          ...S.label, width: 118, flexShrink: 0,
          color: 'var(--color-text-muted)', paddingTop: 2,
        }}>{k}</span>
        <span style={{ fontSize: FS.row, color: 'var(--color-text-primary)' }}>{v}</span>
      </div>
    );

    return (
      <div className="overflow-auto h-full">
        <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
          <span style={{ fontSize: FS.title, color: 'var(--color-text-primary)' }}>{c.name}</span>
          <Health value={c.health} />
        </div>
        <Row k="slug" v={<code style={S.mono}>{c.slug}</code>} />
        <Row k="repo" v={c.repo || '—'} />
        <Row k="layer" v={c.layer || '—'} />
        <Row k="technologies" v={(c.technologies || []).join(', ') || '—'} />
        <Row k="test_base_path" v={<code style={S.mono}>{c.test_base_path || '—'}</code>} />
        <Row k="run_cmd" v={<code style={S.mono}>{c.run_cmd || '—'}</code>} />
        <Row k="test_cmd" v={<code style={S.mono}>{c.test_cmd || '—'}</code>} />
        {c.description && (
          <p style={{
            marginTop: 12, fontSize: FS.row, lineHeight: 1.6,
            color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap',
          }}>{c.description}</p>
        )}
        <div style={{ marginTop: 14 }}>
          <div style={{ ...S.label, color: 'var(--color-text-muted)', marginBottom: 4 }}>Connections</div>
          {(c.connections || []).length === 0
            ? <div style={{ fontSize: FS.row, color: 'var(--color-text-muted)' }}>none</div>
            : (c.connections || []).map((k) => (
                <div key={k.id} style={{ fontSize: FS.row, color: 'var(--color-text-primary)' }}>
                  <code style={{ ...S.mono, color: 'var(--color-accent)' }}>{k.kind}</code>
                  <Icon d={ICON.arrow} size={11} style={{ margin: '0 4px', verticalAlign: '-2px' }} />
                  {k.to_slug}
                  {k.description
                    ? <span style={{ color: 'var(--color-text-muted)' }}> — {k.description}</span>
                    : null}
                </div>
              ))}
        </div>
        <div style={{ marginTop: 12 }}>
          <div style={{ ...S.label, color: 'var(--color-text-muted)', marginBottom: 4 }}>MCP tools</div>
          {(c.tools || []).length === 0
            ? <div style={{ fontSize: FS.row, color: 'var(--color-text-muted)' }}>none exposed</div>
            : (c.tools || []).map((t) => (
                <div key={t.id} style={{ ...S.mono, color: 'var(--color-text-primary)' }}>{t.name}</div>
              ))}
        </div>
      </div>
    );
  }

  // -- the window ---------------------------------------------------------

  function ArchitectureWindow() {
    const [components, setComponents] = useState(null);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState(null);
    const [tab, setTab] = useState('tests');
    const [busy, setBusy] = useState(false);
    const [filter, setFilter] = useState('');

    const load = useCallback(() => {
      setError(null);
      getJson('/components').then(setComponents).catch((e) => setError(e.message));
    }, []);
    useEffect(load, [load]);

    const tree = useMemo(() => {
      if (!components) return [];
      const q = filter.trim().toLowerCase();
      // Filtering flattens deliberately: a matching child whose parent doesn't
      // match would otherwise be unreachable behind a hidden branch.
      if (q) {
        return components
          .filter((c) => c.slug.toLowerCase().includes(q) || c.name.toLowerCase().includes(q))
          .map((c) => ({ ...c, children: [] }))
          .sort((a, b) => a.name.localeCompare(b.name));
      }
      return buildTree(components);
    }, [components, filter]);

    return (
      <div className="flex h-full min-h-0" style={{ color: 'var(--color-text-primary)' }}>
        <div className="flex flex-col min-h-0" style={{
          width: RAIL_WIDTH, flexShrink: 0, borderRight: '1px solid var(--color-border)',
        }}>
          <div className="shrink-0" style={{ padding: 8 }}>
            <input
              value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter components…"
              style={{
                width: '100%', background: 'transparent', outline: 'none',
                border: '1px solid var(--color-border)', borderRadius: 6,
                padding: '4px 7px', fontSize: FS.row, color: 'var(--color-text-primary)',
              }}
            />
          </div>
          <div className="overflow-auto flex-1 min-h-0" style={{ padding: '0 6px 8px' }}>
            {error && <Empty>Couldn’t load — {error}</Empty>}
            {!components && !error && <Empty>Loading…</Empty>}
            {components && components.length === 0 && (
              <Empty>No components registered yet — the catalog is curated
                     through the architecture MCP tools.</Empty>
            )}
            {tree.map((n) => (
              <TreeNode key={n.slug} node={n} depth={0} selected={selected} onSelect={setSelected} />
            ))}
          </div>
        </div>

        <div className="flex flex-col min-w-0 min-h-0" style={{ flex: 1 }}>
          <div className="flex items-center shrink-0" style={{
            padding: '0 8px', borderBottom: '1px solid var(--color-border)',
          }}>
            {TABS.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                style={{
                  padding: '7px 11px', fontSize: FS.tab, background: 'none', cursor: 'pointer',
                  border: 0, borderBottom: '2px solid',
                  borderBottomColor: tab === t.id ? 'var(--color-accent)' : 'transparent',
                  color: tab === t.id ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                }}>
                {t.label}
              </button>
            ))}
            <span style={{
              marginLeft: 'auto', paddingRight: 4, fontSize: FS.label,
              color: 'var(--color-text-muted)',
            }}>
              {busy ? 'scanning…' : (selected || 'all components')}
            </span>
          </div>
          <div className="flex-1 min-h-0" style={{ padding: 10 }}>
            {tab === 'tests' && <TestsTab slug={selected} onBusy={(b) => { setBusy(b); if (!b) load(); }} />}
            {tab === 'requirements' && <RequirementsTab slug={selected} />}
            {tab === 'debt' && <DebtTab slug={selected} />}
            {tab === 'detail' && <DetailTab slug={selected} />}
          </div>
        </div>
      </div>
    );
  }

  // The same 3.5×3.5 muted stroke icon every other row in the Workspace
  // popover uses (see aw-workspace-ui's WorkspaceNav.jsx) — a row without one
  // sits an icon-width left of its neighbours and reads as unfinished. These
  // three Tailwind classes are ones core itself ships, so they resolve.
  // Stacked layers: the component tree is what this window is about.
  function ArchitectureIcon() {
    return (
      <svg className="w-3.5 h-3.5 shrink-0 text-[var(--color-text-muted)]"
           viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    );
  }

  function ArchitectureNavEntry() {
    return (
      <button
        onClick={() => window.__awOpenAppWindow?.(WINDOW_ID, undefined, 'Architecture')}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.06] cursor-pointer text-left"
        title="Components, requirements, test traceability"
      >
        <ArchitectureIcon />
        {/* Core's own rows write this as `text-[13px]`, and that class does
            exist in the compiled CSS today — but only because core happens to
            use it. Inline keeps this row's size independent of that. */}
        <span style={{ fontSize: FS.nav, color: 'var(--color-text-primary)' }}>Architecture</span>
      </button>
    );
  }

  host.registerWindow(WINDOW_ID, ArchitectureWindow);
  // core.nav.workspace — the Workspace popover, which is exactly where the old
  // "Tests" row lived. Putting Architecture there means the entry the user
  // reaches for is in the place muscle memory already points at, and the
  // manifest's contributes.windows entry is what makes __awOpenAppWindow
  // resolve architecture.main at all (without it the button opens nothing —
  // the window body slot has nothing registered to mount into).
  host.registerSlot('core.nav.workspace', ArchitectureNavEntry);
}

export default register;
