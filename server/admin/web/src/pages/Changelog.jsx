import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api.js';
import { Notice, Spinner } from '../components/ui.jsx';
import { ChangelogList, GROUP_LABEL } from '../components/changelog.jsx';

const GROUPS = ['edit', 'revert', 'merge', 'queue', 'link', 'auth', 'user', 'other'];
const PAGE = 50;

// local date (yyyy-mm-dd) -> epoch seconds at start/end of that day
function dayStart(str) { if (!str) return ''; return Math.floor(new Date(`${str}T00:00:00`).getTime() / 1000); }
function dayEnd(str) { if (!str) return ''; return Math.floor(new Date(`${str}T23:59:59`).getTime() / 1000); }

export default function Changelog() {
  const [entries, setEntries] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  // filters
  const [fUser, setFUser] = useState('');
  const [fGroup, setFGroup] = useState('');
  const [fFrom, setFFrom] = useState('');
  const [fTo, setFTo] = useState('');

  useEffect(() => {
    api.get('/api/changelog/users').then(setUsers).catch(() => {});
  }, []);

  const load = useCallback((nextOffset = 0) => {
    setBusy(true); setErr('');
    const params = new URLSearchParams();
    params.set('limit', String(PAGE));
    params.set('offset', String(nextOffset));
    if (fUser) params.set('user', fUser);
    if (fGroup) params.set('group', fGroup);
    if (fFrom) params.set('since', String(dayStart(fFrom)));
    if (fTo) params.set('until', String(dayEnd(fTo)));
    return api.get(`/api/changelog?${params.toString()}`)
      .then((d) => { setEntries(d.entries); setTotal(d.total); setOffset(nextOffset); })
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false));
  }, [fUser, fGroup, fFrom, fTo]);

  // reload from the first page whenever a filter changes
  useEffect(() => { load(0); }, [load]);

  function clearFilters() { setFUser(''); setFGroup(''); setFFrom(''); setFTo(''); }
  const hasFilters = fUser || fGroup || fFrom || fTo;
  const page = Math.floor(offset / PAGE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Changelog</h1>
          <p>Every change made through the admin portal, newest first.</p>
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>

      <div className="panel panel-pad filters">
        <div className="field">
          <label>Admin</label>
          <select value={fUser} onChange={(e) => setFUser(e.target.value)} style={{ width: 'auto' }}>
            <option value="">All admins</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Action</label>
          <select value={fGroup} onChange={(e) => setFGroup(e.target.value)} style={{ width: 'auto' }}>
            <option value="">All actions</option>
            {GROUPS.map((g) => <option key={g} value={g}>{GROUP_LABEL[g]}</option>)}
          </select>
        </div>
        <div className="field">
          <label>From</label>
          <input type="date" value={fFrom} onChange={(e) => setFFrom(e.target.value)} style={{ width: 'auto' }} />
        </div>
        <div className="field">
          <label>To</label>
          <input type="date" value={fTo} onChange={(e) => setFTo(e.target.value)} style={{ width: 'auto' }} />
        </div>
        {hasFilters ? <button className="btn btn-sm" onClick={clearFilters} style={{ alignSelf: 'flex-end' }}>Clear</button> : null}
      </div>

      {entries === null ? <Spinner label="Loading changelog…" /> : (
        <div className="panel panel-pad" style={{ marginTop: 16 }}>
          <div className="cl-meta">
            <span className="hint">{total.toLocaleString()} {total === 1 ? 'entry' : 'entries'}{hasFilters ? ' (filtered)' : ''}</span>
          </div>
          <ChangelogList entries={entries} onOpenGame={(id) => navigate(`/admin/atlas?focus=${id}`)} />

          {pages > 1 && (
            <div className="pager">
              <button className="btn btn-sm" disabled={busy || offset === 0} onClick={() => load(Math.max(0, offset - PAGE))}>Prev</button>
              <span className="hint">Page {page} of {pages}</span>
              <button className="btn btn-sm" disabled={busy || offset + PAGE >= total} onClick={() => load(offset + PAGE)}>Next</button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
