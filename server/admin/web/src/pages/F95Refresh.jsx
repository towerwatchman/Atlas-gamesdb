import React, { useEffect, useState, useCallback, useRef } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Spinner, SourceUrlLink } from '../components/ui.jsx';

const STATUS_BADGE = {
  pending: 'badge-muted',
  processing: 'badge-fuzzy',
  done: 'badge-edited',
  error: 'badge-exact',
};

function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_BADGE[status] || 'badge-muted'}`}>{status}</span>;
}

function fmtEta(seconds) {
  if (!seconds) return '—';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

const f95ThreadUrl = (id) => `https://f95zone.to/threads/${id}/`;

// This table now carries more than one source's rows (issue: LC refresh via
// SourcePanel's "Queue refresh" button). F95's thread URL is reconstructible
// from the numeric id alone; LewdCorner's isn't -- real LC URLs carry a
// title-slug the queue never stored (see fixtures: ".../threads/eternum.555/").
// So an LC row gets a label, not a guessed (and wrong) link; the real,
// correct link already lives on the game's Mapped sources panel.
const SOURCE_LABEL = { f95: 'F95zone', lc: 'LewdCorner' };
function sourceLabel(source) { return SOURCE_LABEL[source] || source || 'F95zone'; }
function sourceThreadUrl(it) {
  const source = it.source || 'f95';
  return source === 'f95' ? f95ThreadUrl(it.f95_id) : null;
}

// One queue row's action buttons, shared by the desktop table and mobile cards.
function RowActions({ it, busy, onRetry, onCancel }) {
  const finished = it.status === 'done' || it.status === 'error';
  return (
    <div className="row" style={{ gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
      {finished && (
        <button className="btn btn-sm" disabled={busy}
          onClick={() => onRetry(it.queue_id)}>Retry</button>
      )}
      {it.status === 'pending' && (
        <button className="btn btn-sm btn-danger" disabled={busy}
          onClick={() => onCancel(it.queue_id)}>Cancel</button>
      )}
      {finished && (
        <button className="btn btn-sm" disabled={busy}
          onClick={() => onCancel(it.queue_id)}>Remove</button>
      )}
    </div>
  );
}

export default function F95Refresh() {
  const [summary, setSummary] = useState(null);
  const [data, setData] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [sources, setSources] = useState(['f95', 'lc']); // sane default before the fetch resolves
  const [idInput, setIdInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const timer = useRef(null);

  const load = useCallback(async (showSpinner = false) => {
    if (showSpinner) setData(null);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (sourceFilter) params.set('source', sourceFilter);
      const qs = params.toString();
      const [s, d] = await Promise.all([
        api.get('/api/f95-refresh/summary'),
        api.get(`/api/f95-refresh${qs ? `?${qs}` : ''}`),
      ]);
      setSummary(s);
      setData(d);
    } catch (e) { setErr(e.message); }
  }, [statusFilter, sourceFilter]);

  useEffect(() => { load(true); }, [load]);

  // Which sources this build's worker supports, so the filter dropdown grows
  // automatically if a third source is ever added (see docs/ATLAS_WORKER.md).
  useEffect(() => {
    api.get('/api/f95-refresh/sources').then((d) => {
      if (Array.isArray(d.sources) && d.sources.length) setSources(d.sources);
    }).catch(() => {}); // keep the sane default above on failure
  }, []);

  // Poll every 5s while auto-refresh is on and there's active work worth
  // watching (or always, so a newly-added job shows up promptly).
  useEffect(() => {
    if (!autoRefresh) { if (timer.current) clearInterval(timer.current); return undefined; }
    timer.current = setInterval(() => load(false), 5000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [autoRefresh, load]);

  function parseIds(text) {
    // Accept comma / space / newline separated ids; keep only numeric ones.
    return Array.from(new Set(
      text.split(/[\s,]+/).map((s) => s.trim()).filter((s) => /^\d+$/.test(s)),
    ));
  }

  async function enqueue() {
    setErr(''); setOk('');
    const ids = parseIds(idInput);
    if (!ids.length) { setErr('Enter one or more numeric F95 thread ids.'); return; }
    setBusy(true);
    try {
      if (ids.length === 1) {
        const r = await api.post('/api/f95-refresh', { f95Id: ids[0] });
        setOk(r.reused ? `f95_id ${ids[0]} was already queued.` : `Queued f95_id ${ids[0]}.`);
      } else {
        const r = await api.post('/api/f95-refresh', { f95Ids: ids });
        const added = (r.results || []).filter((x) => x.queued && !x.reused).length;
        const reused = (r.results || []).filter((x) => x.reused).length;
        setOk(`Queued ${added} game(s)${reused ? `, ${reused} already pending` : ''}.`);
      }
      setIdInput('');
      load(false);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function retry(queueId) {
    setErr(''); setOk(''); setBusy(true);
    try { await api.post(`/api/f95-refresh/${queueId}/retry`); setOk('Requeued.'); load(false); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function cancel(queueId) {
    setErr(''); setOk(''); setBusy(true);
    try { await api.del(`/api/f95-refresh/${queueId}`); load(false); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function clearFinished() {
    setErr(''); setOk(''); setBusy(true);
    try {
      const r = await api.post('/api/f95-refresh/clear-finished');
      setOk(`Cleared ${r.cleared} finished item(s).`);
      load(false);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Refresh queue</h1>
          <p>
            Queue a game to be re-scraped. A background worker processes one
            item every ~10&nbsp;seconds and rewrites its data from the source
            page. This box queues an F95zone thread by id; to queue a
            LewdCorner refresh, use the "Queue refresh" button on that game's
            Mapped sources panel instead (an lc_id alone can't be turned into
            a working thread link here).
          </p>
        </div>
      </div>

      {/* summary cards */}
      {summary && (
        <div className="stat-grid" style={{ marginBottom: 16 }}>
          <div className="panel stat"><div className="stat-value">{summary.pending}</div><div className="stat-label">Pending</div></div>
          <div className="panel stat"><div className="stat-value">{summary.processing}</div><div className="stat-label">Processing</div></div>
          <div className="panel stat"><div className="stat-value">{summary.done}</div><div className="stat-label">Done</div></div>
          <div className="panel stat"><div className="stat-value">{summary.error}</div><div className="stat-label">Error</div></div>
        </div>
      )}
      {summary?.by_source && Object.values(summary.by_source).some((n) => n > 0) && (
        <p className="hint" style={{ marginTop: -10, marginBottom: 14 }}>
          Pending/processing by source: {Object.entries(summary.by_source)
            .filter(([, n]) => n > 0)
            .map(([s, n]) => `${sourceLabel(s)} ${n}`)
            .join(' · ')}
        </p>
      )}
      {summary && (summary.pending + summary.processing) > 0 && (
        <p className="hint" style={{ marginTop: -6, marginBottom: 14 }}>
          ~{fmtEta(summary.eta_seconds)} to drain the backlog at 1 game / 10s.
        </p>
      )}

      {/* enqueue form */}
      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <label>Add F95 thread id(s) to refresh</label>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <input
            style={{ flex: '1 1 240px', minWidth: 0 }}
            placeholder="e.g. 12345  or  12345, 67890 24680"
            value={idInput}
            onChange={(e) => setIdInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') enqueue(); }}
          />
          <button className="btn btn-primary" disabled={busy} onClick={enqueue}>
            Queue refresh
          </button>
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          Separate multiple ids with spaces, commas, or new lines. Non-numeric entries are ignored.
        </p>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

      {/* controls */}
      <div className="row" style={{ gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
          <label>Status</label>
          <select style={{ width: 'auto' }} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="done">Done</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div>
          <label>Source</label>
          <select style={{ width: 'auto' }} value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">All</option>
            {sources.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
          </select>
        </div>
        <label className="row" style={{ gap: 6, marginTop: 18 }}>
          <input type="checkbox" style={{ width: 'auto' }} checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          Auto-refresh
        </label>
        <div style={{ flex: 1 }} />
        <button className="btn btn-sm" style={{ marginTop: 18 }} disabled={busy} onClick={() => load(false)}>Refresh now</button>
        <button className="btn btn-sm" style={{ marginTop: 18 }} disabled={busy} onClick={clearFinished}>Clear finished</button>
      </div>

      {!data ? <Spinner /> : data.rows.length === 0 ? (
        <div className="panel empty">Nothing in the queue{statusFilter ? ` with status “${statusFilter}”` : ''}.</div>
      ) : (
        <>
          {/* desktop table */}
          <div className="table-wrap f95q-desktop">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Source</th><th>id</th><th>Status</th><th>Requested by</th>
                  <th>Requested</th><th>Finished</th><th>Tries</th><th className="wrap">Last error</th><th></th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((it) => {
                  const url = sourceThreadUrl(it);
                  return (
                  <tr key={it.queue_id}>
                    <td className="mono">{it.queue_id}</td>
                    <td>{sourceLabel(it.source)}</td>
                    <td className="mono">
                      {url ? <SourceUrlLink url={url}>{it.f95_id}</SourceUrlLink> : it.f95_id}
                    </td>
                    <td><StatusBadge status={it.status} /></td>
                    <td>{it.requested_by || <span className="hint">—</span>}</td>
                    <td className="mono">{fmtTime(it.requested_at)}</td>
                    <td className="mono">{it.finished_at ? fmtTime(it.finished_at) : <span className="hint">—</span>}</td>
                    <td className="mono">{it.attempts}</td>
                    <td className="wrap" style={{ maxWidth: 240, color: 'var(--danger)' }}>
                      {it.last_error || <span className="hint">—</span>}
                    </td>
                    <td><RowActions it={it} busy={busy} onRetry={retry} onCancel={cancel} /></td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* mobile cards */}
          <div className="f95q-mobile">
            {data.rows.map((it) => {
              const url = sourceThreadUrl(it);
              const label = <span className="mono" style={{ fontWeight: 600 }}>{sourceLabel(it.source)} {it.f95_id}</span>;
              return (
              <div key={it.queue_id} className="panel panel-pad" style={{ marginBottom: 10 }}>
                <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                  {url ? <SourceUrlLink url={url}>{label}</SourceUrlLink> : label}
                  <StatusBadge status={it.status} />
                </div>
                <div className="kv" style={{ marginTop: 8 }}>
                  <span className="k">queue #</span><span className="mono">{it.queue_id}</span>
                  <span className="k">by</span><span>{it.requested_by || '—'}</span>
                  <span className="k">requested</span><span className="mono">{fmtTime(it.requested_at)}</span>
                  {it.finished_at ? (<><span className="k">finished</span><span className="mono">{fmtTime(it.finished_at)}</span></>) : null}
                  <span className="k">tries</span><span className="mono">{it.attempts}</span>
                  {it.last_error ? (<><span className="k">error</span><span style={{ color: 'var(--danger)' }}>{it.last_error}</span></>) : null}
                </div>
                <div style={{ marginTop: 10 }}>
                  <RowActions it={it} busy={busy} onRetry={retry} onCancel={cancel} />
                </div>
              </div>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
