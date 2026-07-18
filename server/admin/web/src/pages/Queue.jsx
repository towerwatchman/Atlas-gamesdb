import React, { useEffect, useState, useCallback } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Modal, Spinner, Highlight, SourceUrlLink, SourceLinkList } from '../components/ui.jsx';

function ResolveModal({ lcId, onClose, onDone }) {
  const [data, setData] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/api/queue/${lcId}`).then(setData).catch((e) => setErr(e.message));
  }, [lcId]);

  async function act(fn, label) {
    setErr(''); setBusy(true);
    try { onDone(await fn(), label); } catch (e) { setErr(e.message); setBusy(false); }
  }

  const item = data?.item;
  return (
    <Modal
      title={`Resolve LewdCorner thread ${lcId}`}
      onClose={onClose}
      footer={data && (
        <>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn" disabled={busy} title="Move to the bottom of the queue for now"
            onClick={() => act(() => api.post(`/api/queue/${lcId}/defer`), 'Sent to bottom')}>Send to bottom</button>
          <button className="btn btn-danger" disabled={busy}
            onClick={() => act(() => api.post(`/api/queue/${lcId}/dismiss`), 'Dismissed')}>Dismiss</button>
          <button className="btn" disabled={busy}
            onClick={() => act(() => api.post(`/api/queue/${lcId}/new`), 'Created new game')}>Add as new game</button>
          <button className="btn btn-primary" disabled={busy || chosen == null}
            onClick={() => act(() => api.post(`/api/queue/${lcId}/link`, { atlasId: chosen }), 'Linked')}>
            Link to selected
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      {!data ? <Spinner /> : (
        <>
          <div className="cand" style={{ background: 'var(--panel)' }}>
            <div className="cand-title">{item.title}</div>
            <div className="kv">
              <span className="k">creator</span><span>{item.creator || '—'}</span>
              <span className="k">version</span><span>{item.version || '—'}</span>
              <span className="k">match</span><span><span className={`badge badge-${item.match_kind === 'fuzzy' ? 'fuzzy' : 'exact'}`}>{item.match_kind}</span></span>
              <span className="k">url</span><span><SourceUrlLink url={item.site_url} /></span>
            </div>
          </div>

          <h3 style={{ fontSize: 14, margin: '14px 0 8px', color: 'var(--muted)' }}>
            Candidate atlas games {data.candidates.length ? '' : '— none found'}
          </h3>
          {data.candidates.length === 0 ? (
            <p className="hint">No matching atlas rows. Add it as a new game, or dismiss.</p>
          ) : data.candidates.map((c) => (
            <label key={c.atlas_id} className={`cand ${chosen === c.atlas_id ? 'chosen' : ''}`} style={{ display: 'block', cursor: 'pointer' }}>
              <div className="cand-top">
                <div className="row" style={{ gap: 8 }}>
                  <input type="radio" name="cand" style={{ width: 'auto' }} checked={chosen === c.atlas_id} onChange={() => setChosen(c.atlas_id)} />
                  <span className="cand-title">#{c.atlas_id} · <Highlight text={c.title} reference={item.title} /></span>
                </div>
                <span>
                  {c._links && c._links.length
                    ? <SourceLinkList links={c._links} />
                    : c._owners.length
                      ? c._owners.map((o) => <span key={o} className="badge badge-muted" style={{ marginLeft: 4 }}>{o}</span>)
                      : <span className="orphan">orphan</span>}
                </span>
              </div>
              <div className="kv">
                <span className="k">creator</span><span><Highlight text={c.creator || '—'} reference={item.creator} /></span>
                <span className="k">version</span><span><Highlight text={c.version || '—'} reference={item.version} /></span>
                <span className="k">engine</span><span>{c.engine || '—'}</span>
                <span className="k">id_name</span><span className="mono">{c.id_name}</span>
              </div>
            </label>
          ))}
        </>
      )}
    </Modal>
  );
}

export default function Queue() {
  const [kind, setKind] = useState('');
  const [data, setData] = useState(null);
  const [resolving, setResolving] = useState(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');

  const load = useCallback(async () => {
    setErr('');
    try {
      const params = kind ? `?kind=${kind}` : '';
      setData(await api.get(`/api/queue${params}`));
    } catch (e) { setErr(e.message); }
  }, [kind]);

  useEffect(() => { load(); }, [load]);

  async function defer(lcId) {
    setErr(''); setOk('');
    try {
      await api.post(`/api/queue/${lcId}/defer`);
      setOk('Sent to bottom.');
      load();
    } catch (e) { setErr(e.message); }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p>LewdCorner threads the scraper couldn’t link automatically. Match each to a game, add it as new, or dismiss it.</p>
        </div>
        <div>
          <label>Kind</label>
          <select style={{ width: 'auto' }} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="multi">Multi-match</option>
            <option value="fuzzy">Fuzzy</option>
          </select>
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

      {!data ? <Spinner /> : data.items.length === 0 ? (
        <div className="panel empty">The review queue is empty.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>lc_id</th><th className="wrap">Title</th><th>Creator</th><th>Version</th><th>Kind</th><th>First seen</th><th></th></tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr key={it.lc_id} className={it.deferred_at ? 'row-deferred' : undefined}>
                  <td className="mono">{it.lc_id}</td>
                  <td className="wrap" style={{ minWidth: 200 }}>
                    {it.title}
                    {it.deferred_at ? <span className="badge badge-muted" style={{ marginLeft: 8 }}>deferred</span> : null}
                  </td>
                  <td>{it.creator || <span className="hint">—</span>}</td>
                  <td>{it.version || <span className="hint">—</span>}</td>
                  <td><span className={`badge badge-${it.match_kind === 'fuzzy' ? 'fuzzy' : 'exact'}`}>{it.match_kind}</span></td>
                  <td className="mono">{fmtTime(it.first_seen)}</td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                      <button className="btn btn-sm" title="Move to the bottom of the queue"
                        onClick={() => defer(it.lc_id)}>Send to bottom</button>
                      <button className="btn btn-sm btn-primary" onClick={() => setResolving(it.lc_id)}>Resolve</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resolving != null && (
        <ResolveModal
          lcId={resolving}
          onClose={() => setResolving(null)}
          onDone={(_res, label) => { setResolving(null); setOk(`${label}.`); load(); }}
        />
      )}
    </>
  );
}
