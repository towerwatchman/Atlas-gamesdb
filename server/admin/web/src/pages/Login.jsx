import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api.js';
import { Notice } from '../components/ui.jsx';

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setErr(''); setOk(''); setBusy(true);
    try {
      if (mode === 'login') {
        const d = await api.post('/api/auth/login', { username, password });
        onLogin(d.username);
        navigate('/admin/home');
      } else {
        await api.post('/api/auth/register', { code: code.trim(), username, password });
        // auto-login right after successful registration
        const d = await api.post('/api/auth/login', { username, password });
        onLogin(d.username);
        navigate('/admin/home');
      }
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === 'register';

  return (
    <div className="login-wrap">
      <form className="panel panel-pad login-card" onSubmit={submit}>
        <div className="brand"><span className="mark" /> Atlas Admin</div>
        <p className="sub">{registering ? 'Create an account with an invite code.' : 'Sign in to edit the games database.'}</p>
        <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>
        <Notice kind="ok" onClose={() => setOk('')}>{ok}</Notice>

        {registering && (
          <div className="field">
            <label htmlFor="code">Invite code</label>
            <input id="code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus
              placeholder="xxxx-xxxx-xxxx" autoComplete="off" />
          </div>
        )}
        <div className="field">
          <label htmlFor="u">Username</label>
          <input id="u" value={username} onChange={(e) => setUsername(e.target.value)}
            autoFocus={!registering} autoComplete="username" />
        </div>
        <div className="field">
          <label htmlFor="p">Password{registering ? ' (min 8 characters)' : ''}</label>
          <input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={registering ? 'new-password' : 'current-password'} />
        </div>

        <button className="btn btn-primary" style={{ width: '100%' }}
          disabled={busy || (registering && (!code || password.length < 8))}>
          {busy ? (registering ? 'Creating…' : 'Signing in…') : (registering ? 'Create account' : 'Sign in')}
        </button>

        <p className="hint" style={{ textAlign: 'center', marginTop: 14 }}>
          {registering ? (
            <>Have an account?{' '}
              <a href="#" onClick={(e) => { e.preventDefault(); setMode('login'); setErr(''); }}>Sign in</a>
            </>
          ) : (
            <>Have an invite code?{' '}
              <a href="#" onClick={(e) => { e.preventDefault(); setMode('register'); setErr(''); }}>Create an account</a>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
