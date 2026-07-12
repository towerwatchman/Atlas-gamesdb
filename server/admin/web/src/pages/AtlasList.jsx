import React, { useEffect, useState, useCallback } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { SourceBadges, SourceLinkList, Notice, Modal, Spinner } from '../components/ui.jsx';

// Fields shown as a wide textarea rather than a single-line input.
const LONG_FIELDS = new Set(['overview', 'tags', 'genre', 'previews', 'translations']);

function EditModal({ atlasId, onClose, onSaved }) {
  const [row, setRow] = useState(null);
  const [cols, setCols] = useState([]);
  const [draft, setDraft] = useState({});
  const [audit, setAudit] = useState([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([
      api.get(`/api/atlas/${atlasId}`),
      api.get('/api/atlas/editable-columns'),
      api.get(`/api/atlas/${atlasId}/audit`),
    ]).then(([r, c, a]) => {
      if (!live) return;
      setRow(r); setCols(c); setAudit(a);
      const d = {};
      c.forEach((col) => { d[col] = r[col] ?? ''; });
      setDraft(d);
    }).catch((e) => setErr(e.message));
    return () => { live = false; };
  }, [atlasId]);

  const changed = row ? cols.filter((c) => String(row[c] ?? '') !== String(draft[c] ?? '')) : [];

  async function save() {
    setErr(''); setBusy(true);
    try {
      const changes = {};
      changed.forEach((c) => { changes[c] = draft[c]; });
      const res = await api.patch(`/api/atlas/${atlasId}`, { changes });
      onSaved(res.changed?.length || 0);
    } catch (e) {
      setErr(e.message); setBusy(false);
    }
  }

  return (
    <Modal
      title={row ? `Edit atlas #${atlasId}` : `Atlas #${atlasId}`}
      onClose={onClose}
      footer={row && (
        <>
          <span className="hint" style={{ marginRight: 'auto' }}>
            {changed.length ? `${changed.length} field${changed.length > 1 ? 's' : ''} changed` : 'No changes yet'}
          </span>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !changed.length}>
            {busy ? 'Saving…' : 'Save changes'}
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      {!row ? <Spinner /> : (
        <>
          <div style={{ marginBottom: 8 }}>
            <SourceLinkList links={row._links} />
            {row.edited ? (
              <span className="badge badge-edited" style={{ marginLeft: 8 }}>
                edited by {row.edited_by} · {fmtTime(row.edited_at)}
              </span>
            ) : null}
          </div>
          <div className="grid-2">
            {cols.map((c) => (
              <div className="field" key={c} style={LONG_FIELDS.has(c) ? { gridColumn: '1 / -1' } : undefined}>
                <label htmlFor={`f-${c}`}>
                  {c}{changed.includes(c) ? <span style={{ color: 'var(--teal-bright)' }}> ●</span> : null}
                </label>
                {LONG_FIELDS.has(c) ? (
                  <textarea id={`f-${c}`} value={draft[c] ?? ''} onChange={(e) => setDraft({ ...draft, [c]: e.target.value })} />
                ) : (
                  <input id={`f-${c}`} value={draft[c] ?? ''} onChange={(e) => setDraft({ ...draft, [c]: e.target.value })} />
                )}
              </div>
            ))}
          </div>

          <h3 style={{ fontSize: 14, margin: '10px 0 8px', color: 'var(--muted)' }}>Edit history</h3>
          {audit.length === 0 ? (
            <p className="hint">No edits recorded for this row yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>When</th><th>Field</th><th>From</th><th>To</th><th>By</th></tr></thead>
                <tbody>
                  {audit.map((a) => (
                    <tr key={a.audit_id}>
                      <td className="mono">{fmtTime(a.ts)}</td>
                      <td className="mono">{a.field}</td>
                      <td className="wrap" style={{ maxWidth: 160, color: 'var(--muted)' }}>{a.old_value ?? '—'}</td>
                      <td className="wrap" style={{ maxWidth: 160 }}>{a.new_value ?? '—'}</td>
                      <td>{a.admin_user}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

export default function AtlasList() {
  const [search, setSearch] = useState('');
  const [edited, setEdited] = useState('');
  const [data, setData] = useState(null);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState(null);
  const [ok, setOk] = useState('');
  const [err, setErr] = useState('');
  const limit = 50;

  const load = useCallback(async (off = 0) => {
    setErr('');
    try {
      const params = new URLSearchParams({ limit, offset: off });
      if (search) params.set('search', search);
      if (edited !== '') params.set('edited', edited);
      setData(await api.get(`/api/atlas?${params}`));
      setOffset(off);
    } catch (e) { setErr(e.message); }
  }, [search, edited]);

  useEffect(() => { load(0); }, [load]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Games</h1>
          <p>Search the atlas table and edit any game. Edited rows are flagged and every change is logged.</p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <form className="row" onSubmit={(e) => { e.preventDefault(); load(0); }}>
          <div style={{ flex: '1 1 240px' }}>
            <input placeholder="Search title, creator, developer, id_name…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <select style={{ width: 'auto' }} value={edited} onChange={(e) => setEdited(e.target.value)}>
            <option value="">All rows</option>
            <option value="1">Edited only</option>
            <option value="0">Not edited</option>
          </select>
          <button className="btn btn-primary" type="submit">Search</button>
        </form>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

      {!data ? <Spinner /> : data.rows.length === 0 ? (
        <div className="panel empty">No games match that search.</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>atlas_id</th><th className="wrap">Title</th><th>Creator</th>
                  <th>Version</th><th>Sources</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.atlas_id} className="row-click" onClick={() => setEditing(r.atlas_id)}>
                    <td className="mono">{r.atlas_id}</td>
                    <td className="wrap" style={{ minWidth: 200 }}>
                      {r.title}
                      {r.edited ? <span className="badge badge-edited" style={{ marginLeft: 8 }}>edited</span> : null}
                    </td>
                    <td>{r.creator || <span className="hint">—</span>}</td>
                    <td>{r.version || <span className="hint">—</span>}</td>
                    <td><SourceBadges row={r} /></td>
                    <td>{r.status || <span className="hint">—</span>}</td>
                    <td><button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); setEditing(r.atlas_id); }}>Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="row" style={{ justifyContent: 'space-between', marginTop: 14 }}>
            <span className="hint">
              {offset + 1}–{Math.min(offset + limit, data.total)} of {data.total}
            </span>
            <div className="row">
              <button className="btn btn-sm" disabled={offset === 0} onClick={() => load(Math.max(0, offset - limit))}>Previous</button>
              <button className="btn btn-sm" disabled={offset + limit >= data.total} onClick={() => load(offset + limit)}>Next</button>
            </div>
          </div>
        </>
      )}

      {editing != null && (
        <EditModal
          atlasId={editing}
          onClose={() => setEditing(null)}
          onSaved={(n) => { setEditing(null); setOk(n ? `Saved ${n} field${n > 1 ? 's' : ''}.` : 'No changes to save.'); load(offset); }}
        />
      )}
    </>
  );
}
