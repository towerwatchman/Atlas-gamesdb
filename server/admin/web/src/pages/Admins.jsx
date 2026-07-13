import React, { useEffect, useState } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Spinner } from '../components/ui.jsx';

export default function Admins({ me }) {
  const [list, setList] = useState(null);
  const [invites, setInvites] = useState(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newCode, setNewCode] = useState(null); // raw code shown once
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    setErr('');
    try {
      const [u, inv] = await Promise.all([
        api.get('/api/auth/users'),
        api.get('/api/auth/invites'),
      ]);
      setList(u); setInvites(inv);
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    setErr(''); setOk(''); setBusy(true);
    try {
      await api.post('/api/auth/users', { username, password });
      setOk(`Added ${username}.`);
      setUsername(''); setPassword('');
      load();
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  }

  async function remove(id, name) {
    if (!window.confirm(`Remove admin "${name}"? They will no longer be able to sign in.`)) return;
    setErr(''); setOk('');
    try { await api.del(`/api/auth/users/${id}`); setOk(`Removed ${name}.`); load(); }
    catch (e) { setErr(e.message); }
  }

  async function generate() {
    setErr(''); setOk(''); setNewCode(null); setBusy(true);
    try {
      const res = await api.post('/api/auth/invites');
      setNewCode(res.code);
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function revoke(id) {
    if (!window.confirm('Revoke this invite code? It can no longer be used.')) return;
    setErr(''); setOk('');
    try { await api.del(`/api/auth/invites/${id}`); setOk('Invite revoked.'); load(); }
    catch (e) { setErr(e.message); }
  }

  function inviteStatus(inv) {
    if (inv.used_at) return <span className="badge badge-muted">used by {inv.used_by}</span>;
    if (inv.expires_at * 1000 < Date.now()) return <span className="badge badge-muted">expired</span>;
    return <span className="badge badge-edited">active</span>;
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Admins</h1>
          <p>People who can sign in and edit the database. Passwords are stored hashed.</p>
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
      <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

      {newCode && (
        <div className="panel panel-pad" style={{ marginBottom: 16, borderColor: 'var(--teal)' }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>New invite code — copy it now</h3>
          <p className="hint" style={{ marginBottom: 10 }}>
            This is shown only once. Share it with the person you're inviting; they enter it on the
            login page's “Create an account” form. It expires in 7 days and works once.
          </p>
          <div className="row" style={{ gap: 10, alignItems: 'center' }}>
            <code className="mono" style={{ fontSize: 16, padding: '8px 12px', background: 'var(--panel-2)', borderRadius: 8 }}>{newCode}</code>
            <button className="btn btn-sm" onClick={() => { navigator.clipboard?.writeText(newCode); setOk('Copied.'); }}>Copy</button>
            <button className="btn btn-sm" onClick={() => setNewCode(null)}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="row" style={{ alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
        <div className="panel panel-pad" style={{ flex: '1 1 380px', maxWidth: 460 }}>
          <h3 style={{ fontSize: 15, marginBottom: 12 }}>Add an admin directly</h3>
          <form onSubmit={add}>
            <div className="field">
              <label>Username</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
            </div>
            <div className="field">
              <label>Password (min 8 characters)</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <button className="btn btn-primary" disabled={busy || !username || password.length < 8}>
              {busy ? 'Adding…' : 'Add admin'}
            </button>
          </form>
        </div>

        <div className="panel panel-pad" style={{ flex: '1 1 380px', maxWidth: 460 }}>
          <h3 style={{ fontSize: 15, marginBottom: 12 }}>Invite by code</h3>
          <p className="hint" style={{ marginBottom: 12 }}>
            Generate a one-time code so someone can create their own account. Codes expire in 7 days.
          </p>
          <button className="btn btn-primary" onClick={generate} disabled={busy}>
            {busy ? 'Generating…' : 'Generate invite code'}
          </button>
        </div>
      </div>

      <h3 style={{ fontSize: 15, margin: '22px 0 10px' }}>Admins</h3>
      {!list ? <Spinner /> : (
        <div className="table-wrap" style={{ maxWidth: 720 }}>
          <table>
            <thead><tr><th>Username</th><th>Created</th><th>Last sign-in</th><th></th></tr></thead>
            <tbody>
              {list.map((u) => (
                <tr key={u.user_id}>
                  <td>{u.username}{u.username === me ? <span className="badge badge-muted" style={{ marginLeft: 8 }}>you</span> : null}</td>
                  <td className="mono">{fmtTime(u.created_at)}</td>
                  <td className="mono">{fmtTime(u.last_login)}</td>
                  <td>
                    {u.username !== me && (
                      <button className="btn btn-sm btn-danger" onClick={() => remove(u.user_id, u.username)}>Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ fontSize: 15, margin: '22px 0 10px' }}>Invite codes</h3>
      {!invites ? <Spinner /> : invites.length === 0 ? (
        <div className="panel empty">No invite codes yet.</div>
      ) : (
        <div className="table-wrap" style={{ maxWidth: 720 }}>
          <table>
            <thead><tr><th>Status</th><th>Created by</th><th>Created</th><th>Expires</th><th></th></tr></thead>
            <tbody>
              {invites.map((inv) => {
                const active = !inv.used_at && inv.expires_at * 1000 >= Date.now();
                return (
                  <tr key={inv.invite_id}>
                    <td>{inviteStatus(inv)}</td>
                    <td>{inv.created_by}</td>
                    <td className="mono">{fmtTime(inv.created_at)}</td>
                    <td className="mono">{fmtTime(inv.expires_at)}</td>
                    <td>{active && <button className="btn btn-sm btn-danger" onClick={() => revoke(inv.invite_id)}>Revoke</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
