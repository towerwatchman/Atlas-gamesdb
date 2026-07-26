import React, { useEffect, useState, useCallback } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Spinner, Modal } from '../components/ui.jsx';

// Column order and display names. `auth` sits last because it isn't work.
const COLUMNS = [
  ['edit', 'Edits'],
  ['addition', 'Additions'],
  ['deletion', 'Deletions'],
  ['merge', 'Merges'],
  ['queue', 'Queue'],
  ['link', 'Links'],
  ['refresh', 'Refresh'],
  ['user', 'Users'],
  ['auth', 'Logins'],
  ['other', 'Other'],
];

const RANGES = [
  ['7', 'Last 7 days'],
  ['30', 'Last 30 days'],
  ['90', 'Last 90 days'],
  ['all', 'All time'],
];

function Bar({ value, max }) {
  if (!value) return <span className="hint">—</span>;
  const pct = max > 0 ? Math.max(3, Math.round((value / max) * 100)) : 0;
  return (
    <span className="row" style={{ gap: 6, alignItems: 'center' }}>
      <span style={{
        display: 'inline-block', height: 8, width: `${pct}%`, minWidth: 3,
        background: 'var(--teal-bright)', borderRadius: 4,
      }}
      />
      <span className="mono">{value}</span>
    </span>
  );
}

function RecentModal({ user, onClose }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let live = true;
    api.get(`/api/admin-activity/${encodeURIComponent(user)}/recent?limit=100`)
      .then((r) => { if (live) setRows(r); })
      .catch((e) => setErr(e.message));
    return () => { live = false; };
  }, [user]);

  return (
    <Modal title={`Recent activity — ${user}`} onClose={onClose}>
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      {!rows ? <Spinner /> : rows.length === 0 ? (
        <p className="hint">Nothing recorded for this admin.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>When</th><th>Action</th><th>Game</th><th>From</th><th>To</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.audit_id}>
                  <td className="mono" style={{ whiteSpace: 'nowrap' }}>{fmtTime(r.ts)}</td>
                  <td className="mono">{r.field}</td>
                  <td className="wrap">
                    {r.atlas_id
                      ? <a href={`/admin/atlas?focus=${r.atlas_id}`}>{r.title || `#${r.atlas_id}`}</a>
                      : <span className="hint">—</span>}
                  </td>
                  <td className="wrap" style={{ maxWidth: 160, color: 'var(--muted)' }}>{r.old_value ?? '—'}</td>
                  <td className="wrap" style={{ maxWidth: 160 }}>{r.new_value ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

/**
 * Per-admin activity (issue #271).
 *
 * Read straight off atlas_audit, which already stamps every action with the
 * admin who did it — so this shows the full history rather than starting from
 * zero the day it shipped.
 */
export default function AdminActivity() {
  const [days, setDays] = useState('30');
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [drill, setDrill] = useState(null);

  const load = useCallback(async () => {
    setErr(''); setData(null);
    try {
      setData(await api.get(`/api/admin-activity?days=${days}`));
    } catch (e) { setErr(e.message); }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const max = data ? Math.max(1, ...data.admins.map((a) => a.total)) : 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Admin activity</h1>
          <p>
            Who changed what. Counted from the audit log, so it covers everything
            ever recorded — not just since this page existed.
          </p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <select style={{ width: 'auto' }} value={days} onChange={(e) => setDays(e.target.value)}>
            {RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button className="btn btn-sm" onClick={load}>Refresh</button>
          {data?.bounds?.first_ts ? (
            <span className="hint">
              Audit log covers {fmtTime(data.bounds.first_ts)} → {fmtTime(data.bounds.last_ts)}
              {' '}({data.bounds.n} entries)
            </span>
          ) : null}
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>

      {!data ? <Spinner /> : data.admins.length === 0 ? (
        <div className="panel empty">No activity recorded in this window.</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Admin</th>
                  <th style={{ minWidth: 140 }}>Actions</th>
                  {COLUMNS.map(([k, label]) => <th key={k}>{label}</th>)}
                  <th>Last seen</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.admins.map((a) => (
                  <tr key={a.admin_user}>
                    <td><strong>{a.admin_user}</strong></td>
                    <td><Bar value={a.total} max={max} /></td>
                    {COLUMNS.map(([k]) => (
                      <td key={k} className="mono">
                        {a.counts[k] ? a.counts[k] : <span className="hint">—</span>}
                      </td>
                    ))}
                    <td className="mono" style={{ whiteSpace: 'nowrap' }}>{fmtTime(a.last_ts)}</td>
                    <td>
                      <button className="btn btn-sm" onClick={() => setDrill(a.admin_user)}>
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
                <tr>
                  <td><strong>Total</strong></td>
                  <td className="mono"><strong>{data.grand_total}</strong></td>
                  {COLUMNS.map(([k]) => (
                    <td key={k} className="mono"><strong>{data.totals[k] || 0}</strong></td>
                  ))}
                  <td /><td />
                </tr>
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            “Actions” excludes logins — signing in a lot is not the same as doing a
            lot, and counting it would just rank whoever’s session expires most.
          </p>
        </>
      )}

      {drill && <RecentModal user={drill} onClose={() => setDrill(null)} />}
    </>
  );
}
