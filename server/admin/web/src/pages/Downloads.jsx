import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { api, fmtTime } from '../lib/api.js';
import { Notice, Spinner } from '../components/ui.jsx';

// Channel choices. "main vs nightly" is inferred server-side (lib/releases.js):
// the prerelease flag, or the word "nightly" in the tag/name. Each row shows
// which channel it landed in, so a misclassified tag is visible rather than
// quietly folded into the wrong total.
const CHANNELS = [
  ['all', 'All channels'],
  ['main', 'Main'],
  ['nightly', 'Nightly'],
];

function Stat({ value, label, sub }) {
  return (
    <div className="dl-stat">
      <div className="dl-num">{Number(value || 0).toLocaleString()}</div>
      <div className="dl-lab">{label}</div>
      {sub ? <div className="dl-sub">{sub}</div> : null}
    </div>
  );
}

export default function Downloads() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [channel, setChannel] = useState('all');
  const [type, setType] = useState('all');

  const load = useCallback(async (force = false) => {
    setErr(''); setBusy(true);
    try {
      setData(await api.get(`/api/releases${force ? '?force=1' : ''}`));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Rows for the current filters. Assets are filtered by type, then releases
  // with nothing left are dropped — a release that has no .deb shouldn't show
  // as a zero row when you're looking at .deb downloads.
  const rows = useMemo(() => {
    if (!data) return [];
    return data.releases
      .filter((r) => channel === 'all' || r.channel === channel)
      .map((r) => {
        const assets = type === 'all' ? r.assets : r.assets.filter((a) => a.type === type);
        return { ...r, assets, total: assets.reduce((s, a) => s + a.downloads, 0) };
      })
      .filter((r) => r.assets.length > 0);
  }, [data, channel, type]);

  const shown = useMemo(() => rows.reduce((s, r) => s + r.total, 0), [rows]);
  const max = useMemo(() => Math.max(1, ...rows.map((r) => r.total)), [rows]);

  const scope = type === 'all' ? 'all installers' : `.${type} files`;
  const chanLabel = channel === 'all' ? '' : ` on ${channel}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Downloads</h1>
          <p>
            Release download counts per version, straight from the GitHub
            releases API{data ? ` for ${data.repo}` : ''}. Cached server-side, so
            an open page doesn’t burn the API rate limit.
          </p>
        </div>
        <button className="btn" onClick={() => load(true)} disabled={busy}>
          {busy ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <Notice kind="err" onClose={() => setErr('')}>{err}</Notice>

      {data?.stale && (
        <Notice kind="warn">
          Showing cached figures from {fmtTime(Math.floor(data.cached_at / 1000))}
          {data.error ? ` — ${data.error}` : ''}
        </Notice>
      )}

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="row" style={{ gap: 14, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label className="field" style={{ margin: 0 }}>
            <span>Channel</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {CHANNELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field" style={{ margin: 0 }}>
            <span>Asset type</span>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="all">All installers</option>
              {(data?.types || []).map((t) => (
                <option key={t} value={t}>.{t}</option>
              ))}
            </select>
          </label>
          {data?.cached_at ? (
            <span className="hint" style={{ marginLeft: 'auto' }}>
              fetched {fmtTime(Math.floor(data.cached_at / 1000))}
            </span>
          ) : null}
        </div>
      </div>

      {!data ? <Spinner /> : (
        <>
          <div className="dl-summary">
            <Stat value={shown} label={`downloads · ${scope}${chanLabel}`} />
            <Stat value={rows.length} label="releases with matching assets" />
            <Stat
              value={data.by_channel?.main?.downloads}
              label="main total"
              sub={data.by_channel?.main?.latest
                ? `latest ${data.by_channel.main.latest}` : 'no releases'}
            />
            <Stat
              value={data.by_channel?.nightly?.downloads}
              label="nightly total"
              sub={data.by_channel?.nightly?.latest
                ? `latest ${data.by_channel.nightly.latest}` : 'no releases'}
            />
          </div>

          <div className="panel">
            <div className="dl-thead">
              <span>Release</span>
              <span style={{ textAlign: 'right' }}>Downloads</span>
            </div>
            {rows.map((r) => (
              <div className="dl-row" key={`${r.channel}-${r.tag}`}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <a className="dl-tag" href={r.url} target="_blank" rel="noreferrer">
                      {r.tag}
                    </a>
                    <span className={`badge ${r.channel === 'nightly' ? 'badge-ext' : 'badge-edited'}`}>
                      {r.channel}
                    </span>
                    {r.prerelease && <span className="hint">pre-release</span>}
                    <span className="hint">
                      {r.published_at ? new Date(r.published_at).toLocaleDateString() : 'unpublished'}
                    </span>
                  </div>
                  <div className="dl-bar">
                    <div className="dl-fill" style={{ width: `${(r.total / max) * 100}%` }} />
                  </div>
                  {type === 'all' && r.assets.some((a) => a.downloads > 0) && (
                    <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                      {r.assets.filter((a) => a.downloads > 0).map((a) => (
                        <span key={a.id} className="dl-chip" title={a.name}>
                          .{a.type} · {a.downloads.toLocaleString()}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="dl-count">{r.total.toLocaleString()}</div>
              </div>
            ))}
            {rows.length === 0 && (
              <p className="empty">
                No {type === 'all' ? 'installer' : `.${type}`} assets
                {channel === 'all' ? '' : ` on ${channel}`}.
              </p>
            )}
          </div>
        </>
      )}
    </>
  );
}
