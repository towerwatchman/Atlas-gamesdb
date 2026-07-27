import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, fmtTime } from '../lib/api.js';
import { SourceBadges, SourceLinkList, Notice, Modal, Spinner } from '../components/ui.jsx';
import LinkEditor from '../components/LinkEditor.jsx';
import SourcePanel from '../components/SourcePanel.jsx';

// Fields shown as a wide textarea rather than a single-line input.
const LONG_FIELDS = new Set(['overview', 'tags', 'genre', 'previews', 'translations']);

/**
 * Create a new atlas game (requirement 1).
 *
 * atlas_id is assigned by AUTO_INCREMENT once saved, so the form never asks for
 * one. id_name / short_name are derived server-side using the SAME rule the
 * scraper uses -- they're previewed live here because a clash with an existing
 * row means the game is already in the atlas, and adding it again would create
 * the duplicate the key exists to prevent.
 */
/**
 * Undo one audit entry.
 *
 * Previews first (a GET that writes nothing) because an entry may be part of a
 * batch: undoing a merge restores the deleted game AND moves its source rows
 * back, and the admin should see that before committing. Anything the server
 * says can't be undone shows the reason instead of a button.
 */
function RevertButton({ entry, onDone, onError }) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!entry.revertible) {
    return (
      <span className="hint" title={entry.reason || ''}>
        {entry.reverted_at ? `reverted by ${entry.reverted_by}` : '—'}
      </span>
    );
  }

  async function open() {
    onError(''); setBusy(true);
    try {
      setPreview(await api.get(`/api/revert/${entry.audit_id}`));
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  async function confirm() {
    onError(''); setBusy(true);
    try {
      const res = await api.post(`/api/revert/${entry.audit_id}`, {});
      setPreview(null);
      onDone(res);
    } catch (e) { onError(e.message); setPreview(null); } finally { setBusy(false); }
  }

  return (
    <>
      <button className="btn btn-sm" onClick={open} disabled={busy}>Revert</button>
      {preview && (
        <Modal
          title="Revert this change?"
          onClose={() => setPreview(null)}
          footer={(
            <>
              <button className="btn" onClick={() => setPreview(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={confirm} disabled={busy || !preview.revertible}>
                {busy ? 'Reverting…' : `Revert ${preview.entries.length} change${preview.entries.length === 1 ? '' : 's'}`}
              </button>
            </>
          )}
        >
          {preview.entries.length > 1 && (
            <p className="hint">
              This was part of one operation, so all {preview.entries.length} steps
              are undone together — undoing only part of a merge would leave source
              rows pointing at a game that no longer exists.
            </p>
          )}
          <div className="table-wrap">
            <table>
              <thead><tr><th>Action</th><th>From</th><th>To</th><th /></tr></thead>
              <tbody>
                {preview.entries.map((e) => (
                  <tr key={e.audit_id}>
                    <td className="mono">{e.field}</td>
                    <td className="wrap" style={{ maxWidth: 200 }}>{e.new_value ?? '—'}</td>
                    <td className="wrap" style={{ maxWidth: 200 }}>{e.old_value ?? '—'}</td>
                    <td>
                      {e.revertible
                        ? <span className="hint">ok</span>
                        : <span className="hint" style={{ color: 'var(--danger, #f88)' }}>{e.reason}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            The columns read “From” (the value now) and “To” (what it will become).
            The revert is itself recorded in the history.
          </p>
        </Modal>
      )}
    </>
  );
}

function CreateModal({ onClose, onCreated }) {
  const [cols, setCols] = useState([]);
  const [draft, setDraft] = useState({ title: '', creator: '' });
  const [identity, setIdentity] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    api.get('/api/atlas/editable-columns').then(setCols).catch((e) => setErr(e.message));
  }, []);

  // Preview the derived keys as the admin types, debounced so we aren't firing a
  // request per keystroke.
  useEffect(() => {
    if (!draft.title.trim()) { setIdentity(null); return undefined; }
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ title: draft.title, creator: draft.creator || '' });
      api.get(`/api/atlas/preview-identity?${qs}`).then(setIdentity).catch(() => setIdentity(null));
    }, 250);
    return () => clearTimeout(t);
  }, [draft.title, draft.creator]);

  async function save() {
    setErr(''); setBusy(true);
    try {
      const fields = {};
      Object.entries(draft).forEach(([k, v]) => { if (String(v).trim() !== '') fields[k] = v; });
      const created = await api.post('/api/atlas', { fields });
      onCreated(created);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const clash = identity?.clash;
  const primary = ['title', 'creator', 'developer', 'version', 'engine', 'status', 'category'];
  const rest = cols.filter((c) => !primary.includes(c));

  return (
    <Modal
      title="Add a new game"
      onClose={onClose}
      className="modal-wide"
      footer={(
        <>
          <span className="hint" style={{ marginRight: 'auto' }}>
            atlas_id is assigned when you save.
          </span>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button
            className="btn btn-primary"
            onClick={save}
            disabled={busy || !draft.title.trim() || !!clash}
          >
            {busy ? 'Creating…' : 'Create game'}
          </button>
        </>
      )}
    >
      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>

      <div className="grid-2">
        {primary.map((c) => (
          <div className="field" key={c}>
            <label htmlFor={`c-${c}`}>{c}{c === 'title' ? ' *' : ''}</label>
            <input
              id={`c-${c}`}
              value={draft[c] ?? ''}
              onChange={(e) => setDraft({ ...draft, [c]: e.target.value })}
            />
          </div>
        ))}
      </div>

      <div className="panel panel-pad" style={{ marginTop: 12, background: 'var(--panel-2)' }}>
        <h3 style={{ fontSize: 14, margin: '0 0 6px', color: 'var(--muted)' }}>
          Identity keys (derived)
        </h3>
        {!identity ? (
          <p className="hint" style={{ margin: 0 }}>Enter a title to see the keys.</p>
        ) : (
          <>
            <div className="kv">
              <span className="k">id_name</span><span className="mono">{identity.id_name}</span>
              <span className="k">short_name</span><span className="mono">{identity.short_name}</span>
            </div>
            {clash ? (
              <p className="hint" style={{ color: 'var(--danger, #f88)', marginBottom: 0 }}>
                Already used by <a href={`/admin/atlas?focus=${clash.atlas_id}`}>#{clash.atlas_id} {clash.title}</a>.
                That is the same game as far as the scraper is concerned — edit it
                instead, or change the title/creator.
              </p>
            ) : (
              <p className="hint" style={{ marginBottom: 0 }}>
                Computed the same way the scraper does, so a later crawl of this
                game will match this row instead of adding a duplicate.
              </p>
            )}
          </>
        )}
      </div>

      <button className="btn btn-sm" style={{ marginTop: 12 }} onClick={() => setShowAll(!showAll)}>
        {showAll ? 'Hide' : 'Show'} the other {rest.length} fields
      </button>
      {showAll && (
        <div className="grid-2" style={{ marginTop: 10 }}>
          {rest.map((c) => (
            <div className="field" key={c} style={LONG_FIELDS.has(c) ? { gridColumn: '1 / -1' } : undefined}>
              <label htmlFor={`c-${c}`}>{c}</label>
              {LONG_FIELDS.has(c) ? (
                <textarea id={`c-${c}`} value={draft[c] ?? ''} onChange={(e) => setDraft({ ...draft, [c]: e.target.value })} />
              ) : (
                <input id={`c-${c}`} value={draft[c] ?? ''} onChange={(e) => setDraft({ ...draft, [c]: e.target.value })} />
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function EditModal({ atlasId, onClose, onSaved }) {
  const [row, setRow] = useState(null);
  const [cols, setCols] = useState([]);
  const [draft, setDraft] = useState({});
  const [audit, setAudit] = useState([]);
  const [manualLinks, setManualLinks] = useState([]);
  const [sourceDetail, setSourceDetail] = useState([]);
  const [scrapedLinks, setScrapedLinks] = useState([]);
  const [parentOptions, setParentOptions] = useState({ manual: [], sources: [] });
  const [notice, setNotice] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  // Pulled out of the effect so a revert can pull fresh data -- undoing a change
  // rewrites the row, the links and the history all at once.
  const reload = useCallback(async ({ resetDraft = true } = {}) => {
    const [r, c, a] = await Promise.all([
      api.get(`/api/atlas/${atlasId}`),
      api.get('/api/atlas/editable-columns'),
      api.get(`/api/atlas/${atlasId}/audit`),
    ]);
    setRow(r); setCols(c); setAudit(a);
    setManualLinks(r._manual_links || []);
    setSourceDetail(r._source_detail || []);
    setScrapedLinks(r._scraped_links || []);
    setParentOptions(r._parent_options || { manual: [], sources: [] });
    if (resetDraft) {
      const d = {};
      c.forEach((col) => { d[col] = r[col] ?? ''; });
      setDraft(d);
    }
    return r;
  }, [atlasId]);

  useEffect(() => {
    let live = true;
    reload().catch((e) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [reload]);

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
      className="modal-wide"
      bodyClassName={row ? 'modal-body-split' : ''}
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
      <Notice kind="ok" onClose={() => setNotice('')}>{notice}</Notice>
      {!row ? <Spinner /> : (
        <>
          <div className="edit-split">
          <div className="edit-main">
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

          <LinkEditor
            atlasId={atlasId}
            links={manualLinks}
            setLinks={setManualLinks}
            options={parentOptions}
            setOptions={setParentOptions}
            onError={setErr}
            onNotice={setNotice}
            scrapedLinks={scrapedLinks}
          />
          <h3 style={{ fontSize: 14, margin: '14px 0 8px', color: 'var(--muted)' }}>Edit history</h3>
          {audit.length === 0 ? (
            <p className="hint">No edits recorded for this row yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>When</th><th>Field</th><th>From</th><th>To</th><th>By</th><th /></tr></thead>
                <tbody>
                  {audit.map((a) => (
                    <tr key={a.audit_id}>
                      <td className="mono">{fmtTime(a.ts)}</td>
                      <td className="mono">{a.field}</td>
                      <td className="wrap" style={{ maxWidth: 160, color: 'var(--muted)' }}>{a.old_value ?? '—'}</td>
                      <td className="wrap" style={{ maxWidth: 160 }}>{a.new_value ?? '—'}</td>
                      <td>{a.admin_user}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <RevertButton
                          entry={a}
                          onError={setErr}
                          onDone={(res) => {
                            setNotice(`Reverted ${res.reverted} change${res.reverted === 1 ? '' : 's'}.`);
                            reload().catch((e) => setErr(e.message));
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          </div>
          <aside className="edit-aside">
            <SourcePanel detail={sourceDetail} />
          </aside>
          </div>
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
  const [creating, setCreating] = useState(false);
  const [ok, setOk] = useState('');
  const [err, setErr] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const limit = 50;

  // Deep-link: /atlas?focus=<id> opens that game's editor (used by the changelog).
  useEffect(() => {
    const focus = searchParams.get('focus');
    if (focus) {
      setEditing(Number(focus));
      searchParams.delete('focus');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

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
        <button className="btn btn-primary" onClick={() => setCreating(true)}>Add a game</button>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <form className="row" onSubmit={(e) => { e.preventDefault(); load(0); }}>
          <div style={{ flex: '1 1 240px' }}>
            <input placeholder="Search title, creator, developer, id_name, or paste an id…" value={search} onChange={(e) => setSearch(e.target.value)} />
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

      {creating && (
        <CreateModal
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false);
            setOk(`Created atlas #${created.atlas_id} (${created.id_name}).`);
            setEditing(created.atlas_id);
            load(offset);
          }}
        />
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
