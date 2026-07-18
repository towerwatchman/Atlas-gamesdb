import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api.js';
import { Notice, Spinner } from '../components/ui.jsx';
import { ChangelogList } from '../components/changelog.jsx';

function Stat({ label, value, sub, accent, onClick }) {
  const n = value == null ? '—' : value.toLocaleString();
  return (
    <div className={`panel stat ${onClick ? 'stat-click' : ''}`} onClick={onClick} role={onClick ? 'button' : undefined}>
      <div className="stat-value" style={accent ? { color: accent } : undefined}>{n}</div>
      <div className="stat-label">{label}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

export default function Home({ user }) {
  const [data, setData] = useState(null);
  const [recent, setRecent] = useState(null);
  const [err, setErr] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    api.get('/api/stats').then(setData).catch((e) => setErr(e.message));
    api.get('/api/changelog?limit=8').then((d) => setRecent(d.entries)).catch(() => setRecent([]));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Welcome back, {user}</h1>
          <p>Snapshot of the Atlas database and everything being scraped into it.</p>
        </div>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>

      {!data ? <Spinner label="Loading stats…" /> : (
        <>
          <div className="stat-grid">
            <Stat label="Games in Atlas" value={data.atlas} accent="var(--teal-bright)"
              sub="master catalog" onClick={() => navigate('/atlas')} />
            <Stat label="F95zone games" value={data.sources.f95}
              sub={data.floating.f95 != null ? `${data.floating.f95} floating` : 'source table'} />
            <Stat label="LewdCorner games" value={data.sources.lc}
              sub={data.floating.lc != null ? `${data.floating.lc} floating` : 'source table'} />
            <Stat label="LC review queue" value={data.queue} accent="var(--amber)"
              sub="awaiting a decision" onClick={() => navigate('/queue')} />
          </div>

          <div className="panel panel-pad" style={{ marginTop: 18 }}>
            <h3 style={{ fontSize: 15, marginBottom: 8 }}>Totals</h3>
            <p className="hint">
              {data.atlas != null && data.sources.f95 != null && data.sources.lc != null ? (
                <>Atlas holds <strong>{data.atlas.toLocaleString()}</strong> games, aggregated from{' '}
                <strong>{(data.sources.f95 + data.sources.lc).toLocaleString()}</strong> source rows
                across F95zone and LewdCorner
                {data.queue ? <>, with <strong>{data.queue.toLocaleString()}</strong> LewdCorner threads still in the review queue</> : null}.</>
              ) : 'Some counts are unavailable — check that the source tables exist.'}
            </p>
          </div>

          <div className="panel panel-pad" style={{ marginTop: 18 }}>
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h3 style={{ fontSize: 15, margin: 0 }}>Recent activity</h3>
              <button className="btn btn-sm" onClick={() => navigate('/changelog')}>View all</button>
            </div>
            {recent === null
              ? <Spinner label="Loading activity…" />
              : <ChangelogList entries={recent} compact onOpenGame={(id) => navigate(`/atlas?focus=${id}`)} />}
          </div>
        </>
      )}
    </>
  );
}
