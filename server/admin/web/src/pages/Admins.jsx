import React, { useEffect, useState } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Spinner } from '../components/ui.jsx';

export default function Admins({ me }) {
  const [list, setList] = useState(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    setErr('');
    try { setList(await api.get('/api/auth/users')); } catch (e) { setErr(e.message); }
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

      <div className="panel panel-pad" style={{ marginBottom: 16, maxWidth: 460 }}>
        <h3 style={{ fontSize: 15, marginBottom: 12 }}>Add an admin</h3>
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

      {!list ? <Spinner /> : (
        <div className="table-wrap" style={{ maxWidth: 640 }}>
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
    </>
  );
}
