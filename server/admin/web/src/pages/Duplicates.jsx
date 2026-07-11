import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../lib/api.js';
import { SourceBadges, Notice, Modal, Spinner } from '../components/ui.jsx';

function MergeModal({ group, onClose, onDone }) {
  const [rows, setRows] = useState(null);
  const [survivor, setSurvivor] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ids = group.members.map((m) => m.atlas_id).join(',');
    api.get(`/api/duplicates/group?ids=${ids}`)
      .then((r) => {
        setRows(r);
        // Default survivor: prefer an f95-backed row (source of truth).
        const f95 = r.find((x) => x._owners.includes('f95_zone'));
        setSurvivor((f95 || r[0]).atlas_id);
      })
      .catch((e) => setErr(e.message));
  }, [group]);

  async function merge() {
    setErr(''); setBusy(true);
    try {
      const res = await api.post('/api/duplicates/merge', {
        survivorId: survivor,
        groupIds: group.members.map((m) => m.atlas_id),
      });
      onDone(res);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <Modal
      title="Merge duplicates"
      onClose={onClose}
      footer={rows && (
        <>
          <span className="hint" style={{ marginRight: 'auto' }}>Keeping #{survivor}</span>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={merge} disabled={busy || survivor == null}>
            {busy ? 'Merging…' : 'Merge into selected'}
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      {!rows ? <Spinner /> : (
        <>
          <p className="hint" style={{ marginBottom: 12 }}>
            Pick the row to keep. Sources on the other rows are repointed to it, then any
            row nothing references anymore is deleted. A row still owned by another source is kept.
          </p>
          {rows.map((r) => (
            <label key={r.atlas_id} className={`cand ${survivor === r.atlas_id ? 'chosen' : ''}`} style={{ display: 'block', cursor: 'pointer' }}>
              <div className="cand-top">
                <div className="row" style={{ gap: 8 }}>
                  <input
                    type="radio" name="survivor" style={{ width: 'auto' }}
                    checked={survivor === r.atlas_id}
                    onChange={() => setSurvivor(r.atlas_id)}
                  />
                  <span className="cand-title">#{r.atlas_id} · {r.title}</span>
                </div>
                <span>
                  {r._owners.length
                    ? r._owners.map((o) => <span key={o} className="badge badge-muted" style={{ marginLeft: 4 }}>{o}</span>)
                    : <span className="orphan">orphan (no source)</span>}
                </span>
              </div>
              <div className="kv">
                <span className="k">creator</span><span>{r.creator || '—'}</span>
                <span className="k">developer</span><span>{r.developer || '—'}</span>
                <span className="k">version</span><span>{r.version || '—'}</span>
                <span className="k">id_name</span><span className="mono">{r.id_name}</span>
                <span className="k">sources</span>
                <span>
                  {r._sources.f95_id != null && <span className="badge badge-f95">f95 {r._sources.f95_id}</span>}{' '}
                  {r._sources.lc_id != null && <span className="badge badge-lc">lc {r._sources.lc_id}</span>}
                </span>
              </div>
            </label>
          ))}
        </>
      )}
    </Modal>
  );
}

export default function Duplicates() {
  const [scope, setScope] = useState('all');
  const [floor, setFloor] = useState(0.90);
  const [kinds, setKinds] = useState({ exact: true, fuzzy: true });
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [merging, setMerging] = useState(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const k = Object.entries(kinds).filter(([, v]) => v).map(([x]) => x).join(',') || 'exact';
      const params = new URLSearchParams({ scope, floor, kinds: k });
      setData(await api.get(`/api/duplicates?${params}`));
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
  }, [scope, floor, kinds]);

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  function mergeResultMsg(res) {
    const parts = [];
    if (res.deleted.length) parts.push(`deleted ${res.deleted.length} duplicate row(s)`);
    if (res.relinked.length) parts.push(`repointed ${res.relinked.length} source link(s)`);
    if (res.kept.length) parts.push(`kept ${res.kept.length} still-owned row(s)`);
    if (res.conflicts.length) parts.push(`${res.conflicts.length} conflict(s) left for manual review`);
    return parts.length ? `Merged: ${parts.join(', ')}.` : 'Nothing to merge.';
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Duplicates</h1>
          <p>Distinct atlas rows that are almost certainly the same game. Merge them onto one surviving id.</p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="row">
          <div>
            <label>Scope</label>
            <select style={{ width: 'auto' }} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="all">All</option>
              <option value="f95">Touching F95</option>
              <option value="lc">Touching LewdCorner</option>
              <option value="cross">Cross-source (F95 + LC)</option>
            </select>
          </div>
          <div>
            <label>Fuzzy floor: {Number(floor).toFixed(2)}</label>
            <input type="range" min="0.5" max="1" step="0.01" value={floor} onChange={(e) => setFloor(e.target.value)} style={{ width: 160 }} />
          </div>
          <div>
            <label>Detectors</label>
            <div className="row">
              <label className="row" style={{ gap: 6 }}><input type="checkbox" style={{ width: 'auto' }} checked={kinds.exact} onChange={(e) => setKinds({ ...kinds, exact: e.target.checked })} /> Exact</label>
              <label className="row" style={{ gap: 6 }}><input type="checkbox" style={{ width: 'auto' }} checked={kinds.fuzzy} onChange={(e) => setKinds({ ...kinds, fuzzy: e.target.checked })} /> Fuzzy</label>
            </div>
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <button className="btn btn-primary" onClick={load} disabled={loading}>{loading ? 'Scanning…' : 'Scan'}</button>
          </div>
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

      {loading ? <Spinner label="Scanning atlas…" /> : !data ? null : (
        <>
          <p className="hint" style={{ marginBottom: 14 }}>
            {data.atlasCount} atlas rows · {data.exact} exact group(s) · {data.fuzzy} fuzzy group(s)
          </p>
          {data.groups.length === 0 ? (
            <div className="panel empty">No duplicate groups at these settings.</div>
          ) : data.groups.map((g) => (
            <div className="panel panel-pad group" key={g.members.map((m) => m.atlas_id).join('-')}>
              <div className="group-head">
                <span className={`badge badge-${g.kind}`}>{g.kind}</span>
                <span className="key">{g.key}</span>
                <span className="hint">{g.members.length} rows · {g.sources.join(' + ') || 'no source'}</span>
                <button className="btn btn-sm btn-primary" style={{ marginLeft: 'auto' }} onClick={() => setMerging(g)}>Review &amp; merge</button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>atlas_id</th><th className="wrap">Title</th><th>Creator</th><th>Version</th><th>Sources</th></tr></thead>
                  <tbody>
                    {g.members.map((m) => (
                      <tr key={m.atlas_id}>
                        <td className="mono">{m.atlas_id}</td>
                        <td className="wrap">{m.title}</td>
                        <td>{m.creator || '—'}</td>
                        <td>{m.version || '—'}</td>
                        <td><SourceBadges row={m} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </>
      )}

      {merging && (
        <MergeModal
          group={merging}
          onClose={() => setMerging(null)}
          onDone={(res) => { setMerging(null); setOk(mergeResultMsg(res)); load(); }}
        />
      )}
    </>
  );
}
