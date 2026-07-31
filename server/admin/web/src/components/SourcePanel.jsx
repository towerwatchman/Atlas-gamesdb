import React, { useState, useEffect } from 'react';
import { api, fmtTime } from '../lib/api.js';
import Favicon from './Favicon.jsx';

// Which source tables the refresh queue's worker (atlas-worker) can actually
// handle, and the `source` key + id column it expects. dlsite/sxs have no
// agent.refresh_one yet, so they're deliberately absent here -- the button
// just doesn't appear for those tabs rather than queueing something the
// worker would reject.
const REFRESHABLE = {
  f95_zone: { source: 'f95', idCol: 'f95_id' },
  lewdcorner: { source: 'lc', idCol: 'lc_id' },
};

// Fields that are epoch seconds and should render as dates.
const TIME_FIELDS = new Set([
  'thread_updated', 'thread_publish_date', 'last_thread_comment',
  'last_record_update', 'register_date',
]);
// Long blobs that would blow out the panel; shown collapsed.
const BLOB_FIELDS = new Set([
  'tags', 'downloads', 'screens', 'patches', 'extras', 'translations',
  'banner_url', 'prefixes',
]);

function Value({ field, value }) {
  if (value === null || value === undefined || value === '') {
    return <span className="hint">—</span>;
  }
  if (TIME_FIELDS.has(field)) {
    return <span className="mono">{fmtTime(Number(value))}</span>;
  }
  const text = String(value);
  if (BLOB_FIELDS.has(field) || text.length > 120) {
    return (
      <details>
        <summary className="hint" style={{ cursor: 'pointer' }}>
          {text.length} chars
        </summary>
        <div className="wrap mono" style={{ fontSize: 11, maxHeight: 160, overflow: 'auto' }}>
          {text}
        </div>
      </details>
    );
  }
  return <span className="wrap">{text}</span>;
}

/**
 * The mapped-source panel shown beside the atlas fields (issue #286).
 *
 * Every source table declares `atlas_id UNIQUE`, so a game has at most one row
 * per source. "More than one mapping" therefore means more than one SOURCE is
 * mapped, and the switcher at the top switches between them (F95 / LewdCorner /
 * DLsite / SXS) rather than between several ids of one source.
 */
export default function SourcePanel({ detail }) {
  const list = detail || [];
  const [active, setActive] = useState(0);
  // Per-source refresh state, keyed by `${source}:${id}` so switching tabs
  // doesn't show a stale "queued" message from a different source.
  const [refreshState, setRefreshState] = useState({});

  // Keep the selection valid if the game's mappings change under us.
  useEffect(() => {
    if (active >= list.length) setActive(0);
  }, [list.length, active]);

  if (!list.length) {
    return (
      <div className="source-panel">
        <h3 style={{ fontSize: 14, margin: '0 0 4px', color: 'var(--muted)' }}>
          Mapped sources
        </h3>
        <p className="hint" style={{ margin: 0 }}>
          No source mappings. This game exists only in the atlas table — either it
          was added by hand, or its source rows were unlinked.
        </p>
      </div>
    );
  }

  const current = list[Math.min(active, list.length - 1)];
  const refreshable = REFRESHABLE[current.source];
  const refreshKey = refreshable ? `${refreshable.source}:${current.id}` : null;
  const rstate = refreshKey ? refreshState[refreshKey] : null;

  async function queueRefresh() {
    if (!refreshable || !current.id) return;
    setRefreshState((s) => ({ ...s, [refreshKey]: { busy: true } }));
    try {
      const res = await api.post('/api/f95-refresh', {
        f95Id: current.id, source: refreshable.source,
      });
      setRefreshState((s) => ({
        ...s,
        [refreshKey]: { busy: false, queued: true, reused: !!res.reused },
      }));
    } catch (e) {
      setRefreshState((s) => ({ ...s, [refreshKey]: { busy: false, error: e.message } }));
    }
  }

  return (
    <div className="source-panel">
      <h3 style={{ fontSize: 14, margin: '0 0 8px', color: 'var(--muted)' }}>
        Mapped sources{list.length > 1 ? ` (${list.length})` : ''}
      </h3>

      {/* Only show the switcher when there's something to switch between. */}
      {list.length > 1 && (
        <div className="row" style={{ gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          {list.map((s, i) => (
            <button
              key={`${s.source}-${s.id}`}
              className={`btn btn-sm ${i === active ? 'btn-primary' : ''}`}
              onClick={() => setActive(i)}
              title={s.site_url || ''}
            >
              <span className="row" style={{ gap: 6, alignItems: 'center' }}>
                <Favicon link={{ url: s.site_url }} size={14} />
                {s.source_label} {s.id}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="row" style={{ gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <Favicon link={{ url: current.site_url }} size={16} />
        <strong>{current.source_label}</strong>
        <span className="mono hint">{current.id_col} {current.id}</span>
        {current.site_url && (
          <a className="badge badge-ext" href={current.site_url} target="_blank" rel="noreferrer">
            open thread ↗
          </a>
        )}
        {refreshable && (
          <button
            className="btn btn-sm"
            style={{ marginLeft: 'auto' }}
            onClick={queueRefresh}
            disabled={rstate?.busy}
            title="Queue a re-scrape of this thread with the refresh worker"
          >
            {rstate?.busy ? 'Queueing…' : 'Queue refresh'}
          </button>
        )}
      </div>
      {rstate?.queued && (
        <p className="hint" style={{ margin: '0 0 8px' }}>
          {rstate.reused
            ? 'Already queued — a refresh for this is pending or in progress.'
            : 'Queued. The worker refreshes one item roughly every 10 seconds; see the F95 refresh page for status.'}
        </p>
      )}
      {rstate?.error && (
        <p className="hint" style={{ margin: '0 0 8px', color: 'var(--danger, #f88)' }}>
          {rstate.error}
        </p>
      )}

      <div className="table-wrap">
        <table>
          <tbody>
            {current.fields.map((f) => (
              <tr key={f.field}>
                <td className="mono" style={{ whiteSpace: 'nowrap', color: 'var(--muted)', width: 1 }}>
                  {f.field}
                </td>
                <td className="wrap"><Value field={f.field} value={f.value} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
