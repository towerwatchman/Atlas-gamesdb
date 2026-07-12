import React, { useEffect, useState } from 'react';
import { Routes, Route, NavLink, Navigate, useNavigate } from 'react-router-dom';
import { api } from './lib/api.js';
import Login from './pages/Login.jsx';
import Home from './pages/Home.jsx';
import AtlasList from './pages/AtlasList.jsx';
import Duplicates from './pages/Duplicates.jsx';
import Queue from './pages/Queue.jsx';
import Admins from './pages/Admins.jsx';
import { Spinner } from './components/ui.jsx';

function TopBar({ user, onLogout }) {
  const tabs = [
    ['/home', 'Home'],
    ['/atlas', 'Games'],
    ['/duplicates', 'Duplicates'],
    ['/queue', 'Review queue'],
    ['/admins', 'Admins'],
  ];
  return (
    <div className="topbar">
      <div className="brand"><span className="mark" /> Atlas Admin</div>
      <nav className="tabs">
        {tabs.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="topbar-right">
        <span>{user}</span>
        <button className="btn btn-sm" onClick={onLogout}>Sign out</button>
      </div>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = loading
  const navigate = useNavigate();

  useEffect(() => {
    api.get('/api/auth/me')
      .then((d) => setUser(d.username))
      .catch(() => setUser(null));
  }, []);

  async function logout() {
    try { await api.post('/api/auth/logout'); } catch { /* ignore */ }
    setUser(null);
    navigate('/login');
  }

  if (user === undefined) return <div className="app"><Spinner label="Starting…" /></div>;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLogin={setUser} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="app">
      <TopBar user={user} onLogout={logout} />
      <div className="content">
        <Routes>
          <Route path="/home" element={<Home user={user} />} />
          <Route path="/atlas" element={<AtlasList />} />
          <Route path="/duplicates" element={<Duplicates />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/admins" element={<Admins me={user} />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </div>
    </div>
  );
}
