import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../lib/api.js';
import { SourceBadges, SourceLinkList, Notice, Modal, Spinner } from '../components/ui.jsx';

// Prompt shown when a relink leaves an atlas row orphaned.
function OrphanPrompt({ atlasId, onKeep, onDelete, busy }) {
  return (
    <Modal
      title={`Atlas #${atlasId} is now orphaned`}
      onClose={onKeep}
      footer={(
        <>
          <button className="btn" onClick={onKeep} disabled={busy}>Keep it</button>
          <button className="btn btn-danger" onClick={onDelete} disabled={busy}>
            {busy ? 'Deleting…' : `Delete atlas #${atlasId}`}
          </button>
        </>
      )}
    >
      <p>
        Nothing points at atlas row <strong>#{atlasId}</strong> anymore. You can delete it,
        or keep it as an empty atlas entry. Source rows were not affected.
      </p>
    </Modal>
  );
}

// Relink/float a single source row. `fromAtlasId` is the atlas row this source
// currently sits on, shown in the confirm step's #from → #to arrow.
// Every move now goes through a confirmation screen (requirement 5) so the
// admin sees exactly where the source is headed before it happens.
function RelinkModal({ link, fromAtlasId, onClose, onDone }) {
  const [target, setTarget] = useState('');
  const [pending, setPending] = useState(null); // { action, atlasId } awaiting confirm
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const label = link.source === 'f95_zone' ? 'F95zone' : link.source === 'lewdcorner' ? 'LewdCorner' : link.source;
  const shortSrc = link.source === 'f95_zone' ? 'f95' : link.source === 'lewdcorner' ? 'lc' : link.source;

  async function commit() {
    if (!pending) return;
    setErr(''); setBusy(true);
    try {
      const res = await api.post('/api/duplicates/relink-source', {
        table: link.source, sourceId: link.id, action: pending.action,
        atlasId: pending.action === 'link' ? Number(pending.atlasId) : undefined,
      });
      onDone(res, pending.action);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  // ---- confirmation view ----
  if (pending) {
    const isFloat = pending.action === 'float';
    return (
      <Modal
        title="Confirm move"
        onClose={() => !busy && setPending(null)}
        footer={(
          <>
            <button className="btn" onClick={() => setPending(null)} disabled={busy}>Back</button>
            <button className={`btn ${isFloat ? '' : 'btn-primary'}`} onClick={commit} disabled={busy}>
              {busy ? 'Moving…' : 'Yes, move it'}
            </button>
          </>
        )}
      >
        <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
        <p className="hint" style={{ marginBottom: 14 }}>
          Move <span className="badge badge-f95" style={{ margin: '0 2px' }}>{shortSrc} {link.id}</span>
          {isFloat
            ? ' so it is linked to no atlas game?'
            : ' to a different atlas game?'}
        </p>
        <div className="move-flow">
          <span className="move-node">#{fromAtlasId ?? '—'}</span>
          <span className="move-arrow">→</span>
          <span className={`move-node ${isFloat ? 'move-float' : 'move-target'}`}>
            {isFloat ? 'floating' : `#${pending.atlasId}`}
          </span>
        </div>
        <p className="hint" style={{ marginTop: 14 }}>
          The source row itself is never deleted. {link.site_url && (
            <a href={link.site_url} target="_blank" rel="noreferrer">Open the source thread ↗</a>
          )}
        </p>
      </Modal>
    );
  }

  // ---- picker view ----
  return (
    <Modal
      title={`Move ${label} source ${link.id}`}
      onClose={onClose}
      footer={(
        <>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn" onClick={() => setPending({ action: 'float' })} disabled={busy} title="Unlink from any atlas game">
            Set floating
          </button>
          <button className="btn btn-primary" onClick={() => setPending({ action: 'link', atlasId: Number(target) })} disabled={busy || !Number(target) || Number(target) === fromAtlasId}>
            Continue
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <p className="hint" style={{ marginBottom: 12 }}>
        This source row is never deleted. You can point it at a different atlas game,
        or set it floating (linked to no game). {link.site_url && (
          <a href={link.site_url} target="_blank" rel="noreferrer">Open the source thread ↗</a>
        )}
      </p>
      <div className="field">
        <label>Link to atlas id {fromAtlasId != null ? `(currently on #${fromAtlasId})` : ''}</label>
        <input inputMode="numeric" placeholder="e.g. 4821" value={target}
          onChange={(e) => setTarget(e.target.value.replace(/[^0-9]/g, ''))} />
        {Number(target) === fromAtlasId && target !== '' && (
          <span className="hint" style={{ color: 'var(--amber)' }}>That's the atlas it's already on.</span>
        )}
      </div>
    </Modal>
  );
}

function MergeModal({ group, onClose, onDone, onRelinkDone }) {
  const [rows, setRows] = useState(null);
  const [survivor, setSurvivor] = useState(null);
  const [relink, setRelink] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const loadRows = useCallback(() => {
    const ids = group.members.map((m) => m.atlas_id).join(',');
    return api.get(`/api/duplicates/group?ids=${ids}`).then((r) => {
      setRows(r);
      setSurvivor((prev) => {
        if (prev != null && r.some((x) => x.atlas_id === prev)) return prev;
        const f95 = r.find((x) => x._owners.includes('f95_zone'));
        return (f95 || r[0]).atlas_id;
      });
    }).catch((e) => setErr(e.message));
  }, [group]);

  useEffect(() => { loadRows(); }, [loadRows]);

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
      title="Resolve duplicate atlas rows"
      onClose={onClose}
      footer={rows && (
        <>
          <span className="hint" style={{ marginRight: 'auto' }}>Keeping #{survivor}</span>
          <button className="btn" onClick={onClose} disabled={busy}>Close</button>
          <button className="btn btn-primary" onClick={merge} disabled={busy || survivor == null}>
            {busy ? 'Merging…' : 'Merge — keep selected, delete others'}
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      {!rows ? <Spinner /> : (
        <>
          <p className="hint" style={{ marginBottom: 12 }}>
            These are duplicate <strong>atlas</strong> rows for the same game. Pick the one to keep —
            all source rows are repointed to it and the other atlas rows are deleted. To instead move a
            single source elsewhere or float it, use its <em>Move</em> button (that never deletes the source).
          </p>
          {rows.map((r) => (
            <div key={r.atlas_id} className={`cand ${survivor === r.atlas_id ? 'chosen' : ''}`}>
              <div className="cand-top">
                <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                  <input type="radio" name="survivor" style={{ width: 'auto' }}
                    checked={survivor === r.atlas_id} onChange={() => setSurvivor(r.atlas_id)} />
                  <span className="cand-title">#{r.atlas_id} · {r.title}</span>
                </label>
                {r._owners.length === 0 && <span className="orphan">orphan</span>}
              </div>
              <div className="kv">
                <span className="k">creator</span><span>{r.creator || '—'}</span>
                <span className="k">engine</span><span>{r.engine || '—'}</span>
                <span className="k">version</span><span>{r.version || '—'}</span>
                <span className="k">id_name</span><span className="mono">{r.id_name}</span>
                <span className="k">sources</span><span><SourceLinkList links={r._links} /></span>
              </div>
              {r._links && r._links.length > 0 && (
                <div className="row" style={{ marginTop: 8, gap: 6 }}>
                  {r._links.map((l) => (
                    <button key={`${l.source}-${l.id}`} className="btn btn-sm"
                      onClick={() => setRelink({ ...l, _fromAtlasId: r.atlas_id })}>
                      Move {l.source === 'f95_zone' ? 'f95' : 'lc'} {l.id}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {relink && (
        <RelinkModal
          link={relink}
          fromAtlasId={relink._fromAtlasId}
          onClose={() => setRelink(null)}
          onDone={(res, action) => {
            setRelink(null);
            loadRows();
            onRelinkDone(res, action);
          }}
        />
      )}
    </Modal>
  );
}

export default function Duplicates() {
  const [scope, setScope] = useState('all');
  const [floor, setFloor] = useState(0.90);
  const [kinds, setKinds] = useState({ exact: true, fuzzy: false });
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [merging, setMerging] = useState(null);
  const [orphan, setOrphan] = useState(null);
  const [orphanBusy, setOrphanBusy] = useState(false);
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

  function mergeMsg(res) {
    const parts = [];
    if (res.deleted?.length) parts.push(`deleted ${res.deleted.length} duplicate atlas row(s)`);
    if (res.relinked?.length) parts.push(`repointed ${res.relinked.length} source link(s)`);
    return parts.length ? `Merged: ${parts.join(', ')}.` : 'Nothing to merge.';
  }

  function handleRelinkDone(res, action) {
    setOk(action === 'float' ? 'Source set floating.' : 'Source relinked.');
    if (res.orphaned != null) setOrphan(res.orphaned);
  }

  async function deleteOrphan() {
    setOrphanBusy(true);
    try {
      await api.post('/api/duplicates/delete-orphan', { atlasId: orphan });
      setOk(`Deleted orphaned atlas #${orphan}.`);
      setOrphan(null);
      if (merging) load();
    } catch (e) { setErr(e.message); } finally { setOrphanBusy(false); }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Duplicates</h1>
          <p>Find duplicate atlas rows and merge them. Move or float individual source rows without deleting them.</p>
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
            <div className="panel empty">No duplicate atlas rows at these settings.</div>
          ) : data.groups.map((g) => (
            <div className="panel panel-pad group" key={g.members.map((m) => m.atlas_id).join('-')}>
              <div className="group-head">
                <span className={`badge badge-${g.kind}`}>{g.kind}</span>
                <span className="key">{g.key}</span>
                <span className="hint">{g.members.length} rows · {g.sources.join(' + ') || 'no source'}</span>
                <button className="btn btn-sm btn-primary" style={{ marginLeft: 'auto' }} onClick={() => setMerging(g)}>Review &amp; resolve</button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>atlas_id</th><th className="wrap">Title</th><th>Creator</th><th>Engine</th><th>Version</th><th>Sources</th></tr></thead>
                  <tbody>
                    {g.members.map((m) => (
                      <tr key={m.atlas_id}>
                        <td className="mono">{m.atlas_id}</td>
                        <td className="wrap">{m.title}</td>
                        <td>{m.creator || '—'}</td>
                        <td>{m.engine || '—'}</td>
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
          onDone={(res) => { setMerging(null); setOk(mergeMsg(res)); load(); }}
          onRelinkDone={handleRelinkDone}
        />
      )}

      {orphan != null && (
        <OrphanPrompt
          atlasId={orphan}
          busy={orphanBusy}
          onKeep={() => setOrphan(null)}
          onDelete={deleteOrphan}
        />
      )}
    </>
  );
}
