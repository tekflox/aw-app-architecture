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

const SLUG = 'architecture';
const WINDOW_ID = 'architecture.main';

const HEALTH_COLOR = {
  implemented: 'text-green-400',
  passing: 'text-green-400',
  partial: 'text-amber-400',
  broken: 'text-red-400',
  fail: 'text-red-400',
  not_implemented: 'text-[var(--color-text-muted)]',
  planned: 'text-[var(--color-text-muted)]',
  unknown: 'text-[var(--color-text-muted)]',
};

const TABS = [
  { id: 'tests', label: 'Tests' },
  { id: 'requirements', label: 'Requirements' },
  { id: 'debt', label: 'Debt & Bugs' },
  { id: 'detail', label: 'Detail' },
];

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
      <span className={`text-[10px] uppercase tracking-wide ${HEALTH_COLOR[v] || HEALTH_COLOR.unknown}`}>
        {v.replace(/_/g, ' ')}
      </span>
    );
  }

  function Empty({ children }) {
    return (
      <div className="py-8 text-center text-xs text-[var(--color-text-muted)]">{children}</div>
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
      // A parent_slug pointing at a component that isn't in the current
      // filter (or was deleted with ON DELETE SET NULL mid-flight) must not
      // vanish the child — orphans surface at root rather than disappearing.
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
          style={{ paddingLeft: `${8 + depth * 12}px` }}
          className={`flex items-center gap-1.5 py-1 pr-2 rounded cursor-pointer text-[12px] ${
            isSel ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                  : 'hover:bg-white/5 text-[var(--color-text-primary)]'}`}
        >
          {node.children.length > 0 ? (
            <span
              onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
              className="w-3 shrink-0 text-[var(--color-text-muted)]"
            >{open ? '▾' : '▸'}</span>
          ) : <span className="w-3 shrink-0" />}
          <span className="truncate flex-1">{node.name}</span>
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

    const runOne = async (filePath) => {
      setRunning((r) => ({ ...r, [filePath]: true }));
      setOutput(null);
      try {
        const res = await postJson('/testcases/run', { file_path: filePath });
        setOutput(res);
        load();
      } catch (e) {
        // The tunnel edge cuts at ~30s, so a slow suite fails the FETCH while
        // the run completes server-side and records its status. Saying "test
        // failed" here would be a lie about a test that may well have passed.
        setOutput({
          file_path: filePath, status: 'unknown',
          output: `Could not read the result back (${e.message}). The run may still `
                + `be going server-side — its recorded status will appear on refresh.`,
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
        <div className="flex items-center gap-2 mb-2 shrink-0">
          <button onClick={rescan}
            className="text-[10.5px] px-2.5 py-1 rounded border border-[var(--color-accent)]/40 text-[var(--color-accent)]">
            ⟳ Rescan discovery
          </button>
          <button onClick={() => setFlakyOnly(!flakyOnly)}
            className={`text-[10.5px] px-2.5 py-1 rounded border border-[var(--color-border)] ${
              flakyOnly ? 'text-amber-400' : 'text-[var(--color-text-muted)]'}`}>
            ⚑ Flaky only
          </button>
          <span className="ml-auto text-[10.5px] text-[var(--color-text-muted)]">
            {shown.length} test{shown.length === 1 ? '' : 's'}
          </span>
        </div>

        <div className="overflow-auto min-h-0 flex-1">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
                <th className="py-1.5 px-2 w-6" />
                <th className="py-1.5 px-2">Test file</th>
                <th className="py-1.5 px-2">Kind</th>
                <th className="py-1.5 px-2">Component</th>
                <th className="py-1.5 px-2">Last run</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.file_path} className="border-b border-[var(--color-border)]/40">
                  <td className="py-1.5 px-2">
                    <button onClick={() => runOne(t.file_path)} disabled={running[t.file_path]}
                      title="Run this test" className="text-green-400 disabled:opacity-40">
                      {running[t.file_path] ? '…' : '▶'}
                    </button>
                  </td>
                  <td className="py-1.5 px-2 font-mono text-[11px] text-[var(--color-text-primary)]">
                    {t.file_path}
                    {t.is_flaky && <span className="ml-1.5 text-amber-400" title={t.flaky_note || 'flaky'}>⚑</span>}
                  </td>
                  <td className="py-1.5 px-2 text-[var(--color-text-muted)]">{t.kind}</td>
                  <td className="py-1.5 px-2 text-[var(--color-text-muted)]">{t.component_slug || '—'}</td>
                  <td className="py-1.5 px-2"><Health value={t.last_run_status} /></td>
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
          <div className="shrink-0 mt-2 border-t border-[var(--color-border)] pt-2">
            <div className="flex items-center gap-2 text-[11px] mb-1">
              <Health value={output.status} />
              <span className="font-mono text-[10.5px] text-[var(--color-text-muted)]">{output.file_path}</span>
              <button onClick={() => setOutput(null)} className="ml-auto text-[var(--color-text-muted)]">✕</button>
            </div>
            <pre className="text-[10px] leading-[1.45] max-h-40 overflow-auto whitespace-pre-wrap
                            text-[var(--color-text-muted)] font-mono">{output.output}</pre>
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
      <div className="overflow-auto h-full space-y-2.5">
        {rows.map((r) => (
          <div key={r.id} className="border border-[var(--color-border)] rounded-lg p-3">
            <div className="flex items-start gap-2 mb-1.5">
              <span className="text-[12.5px] text-[var(--color-text-primary)] flex-1">{r.title}</span>
              <Health value={r.health} />
            </div>
            <div className="text-[11px] leading-relaxed text-[var(--color-text-muted)] space-y-0.5">
              <div><b className="text-[var(--color-text-primary)]">Given</b> {r.gherkin_given}</div>
              <div><b className="text-[var(--color-text-primary)]">When</b> {r.gherkin_when}</div>
              <div><b className="text-[var(--color-text-primary)]">Then</b> {r.gherkin_then}</div>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10px] text-[var(--color-text-muted)]">
              <span>intended: <code>{r.intended_status}</code></span>
              {r.kanban_url
                ? <a href={r.kanban_url} target="_blank" rel="noreferrer"
                     className="text-[var(--color-accent)]">Kanban card ↗</a>
                /* set_requirement_status refuses to move a requirement to
                   'implemented' without a card, so a missing link on an
                   implemented row is worth showing, not hiding. */
                : <span className="text-amber-400/80">no Kanban card linked</span>}
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
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
              <th className="py-1.5 px-2">Noted</th>
              <th className="py-1.5 px-2">Component</th>
              <th className="py-1.5 px-2">Description</th>
            </tr>
          </thead>
          <tbody>
            {debt.map((d) => (
              <tr key={d.id} className="border-b border-[var(--color-border)]/40">
                <td className="py-1.5 px-2 text-[var(--color-text-muted)] whitespace-nowrap">
                  {(d.noted_at || '').slice(0, 10)}
                </td>
                <td className="py-1.5 px-2 text-[var(--color-text-muted)]">{d.component_slug || '—'}</td>
                <td className="py-1.5 px-2 text-[var(--color-text-primary)]">{d.description}</td>
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
      <div className="flex gap-3 py-1 border-b border-[var(--color-border)]/40">
        <span className="w-32 shrink-0 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] pt-0.5">{k}</span>
        <span className="text-[11.5px] text-[var(--color-text-primary)]">{v}</span>
      </div>
    );

    return (
      <div className="overflow-auto h-full">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[14px] text-[var(--color-text-primary)]">{c.name}</span>
          <Health value={c.health} />
        </div>
        <Row k="slug" v={<code className="text-[11px]">{c.slug}</code>} />
        <Row k="repo" v={c.repo || '—'} />
        <Row k="layer" v={c.layer || '—'} />
        <Row k="technologies" v={(c.technologies || []).join(', ') || '—'} />
        <Row k="test_base_path" v={<code className="text-[11px]">{c.test_base_path || '—'}</code>} />
        <Row k="run_cmd" v={<code className="text-[11px]">{c.run_cmd || '—'}</code>} />
        <Row k="test_cmd" v={<code className="text-[11px]">{c.test_cmd || '—'}</code>} />
        {c.description && (
          <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--color-text-muted)] whitespace-pre-wrap">
            {c.description}
          </p>
        )}
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] mb-1">Connections</div>
          {(c.connections || []).length === 0
            ? <div className="text-[11.5px] text-[var(--color-text-muted)]">none</div>
            : (c.connections || []).map((k) => (
                <div key={k.id} className="text-[11.5px] text-[var(--color-text-primary)]">
                  <code className="text-[10.5px] text-[var(--color-accent)]">{k.kind}</code> → {k.to_slug}
                  {k.description ? <span className="text-[var(--color-text-muted)]"> — {k.description}</span> : null}
                </div>
              ))}
        </div>
        <div className="mt-3">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)] mb-1">MCP tools</div>
          {(c.tools || []).length === 0
            ? <div className="text-[11.5px] text-[var(--color-text-muted)]">none exposed</div>
            : (c.tools || []).map((t) => (
                <div key={t.id} className="text-[11.5px] font-mono text-[var(--color-text-primary)]">{t.name}</div>
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
      <div className="flex h-full min-h-0 text-[var(--color-text-primary)]">
        <div className="w-[240px] shrink-0 border-r border-[var(--color-border)] flex flex-col min-h-0">
          <div className="p-2 shrink-0">
            <input
              value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter components…"
              className="w-full bg-transparent border border-[var(--color-border)] rounded px-2 py-1
                         text-[11.5px] outline-none focus:border-[var(--color-accent)]/50"
            />
          </div>
          <div className="overflow-auto flex-1 min-h-0 px-1 pb-2">
            {error && <Empty>Couldn’t load — {error}</Empty>}
            {!components && !error && <Empty>Loading…</Empty>}
            {components && components.length === 0 && (
              <Empty>No components registered yet. The catalog is managed through the
                     <code className="mx-1">aw__architecture__*</code> MCP tools.</Empty>
            )}
            {tree.map((n) => (
              <TreeNode key={n.slug} node={n} depth={0} selected={selected} onSelect={setSelected} />
            ))}
          </div>
        </div>

        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <div className="flex items-center gap-1 px-2 border-b border-[var(--color-border)] shrink-0">
            {TABS.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`px-3 py-2 text-[12px] border-b-2 ${
                  tab === t.id ? 'border-[var(--color-accent)] text-[var(--color-text-primary)]'
                               : 'border-transparent text-[var(--color-text-muted)]'}`}>
                {t.label}
              </button>
            ))}
            <span className="ml-auto pr-1 text-[10.5px] text-[var(--color-text-muted)]">
              {busy ? 'scanning…' : (selected || 'all components')}
            </span>
          </div>
          <div className="flex-1 min-h-0 p-3">
            {tab === 'tests' && <TestsTab slug={selected} onBusy={(b) => { setBusy(b); if (!b) load(); }} />}
            {tab === 'requirements' && <RequirementsTab slug={selected} />}
            {tab === 'debt' && <DebtTab slug={selected} />}
            {tab === 'detail' && <DetailTab slug={selected} />}
          </div>
        </div>
      </div>
    );
  }

  function ArchitectureNavEntry() {
    return (
      <button
        onClick={() => window.__awOpenAppWindow?.(WINDOW_ID, undefined, 'Architecture')}
        className="flex items-center gap-2 w-full px-3 py-1.5 hover:bg-white/5 text-left"
        title="Components, requirements, test traceability"
      >
        <span className="text-[13px]">Architecture</span>
      </button>
    );
  }

  host.registerWindow(WINDOW_ID, ArchitectureWindow);
  // core.nav.workspace — the Workspace popover, which is exactly where the
  // old "Tests" row lived. Putting Architecture there means the entry the user
  // reaches for is in the place muscle memory already points at, and the
  // manifest's contributes.windows entry is what makes __awOpenAppWindow
  // resolve architecture.main at all (without it the button opens nothing —
  // the window body slot has nothing registered to mount into).
  host.registerSlot('core.nav.workspace', ArchitectureNavEntry);
}

export default register;
