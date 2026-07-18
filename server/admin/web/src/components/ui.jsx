import React from 'react';
import { highlightSegments } from '../lib/highlight.js';

// Renders `text` with the parts that overlap `reference` wrapped in <mark>.
// Purely local (see lib/highlight.js). Used in the review queue so an admin can
// eyeball which candidate best matches the queued item (requirement 2).
export function Highlight({ text, reference }) {
  const segs = highlightSegments(text, reference);
  return (
    <>
      {segs.map((s, i) => (s.match
        ? <mark key={i} className="hl">{s.text}</mark>
        : <React.Fragment key={i}>{s.text}</React.Fragment>))}
    </>
  );
}

// A plain clickable source/thread URL. Truncates visually via CSS but the full
// url is the href + title. stopPropagation so it doesn't trigger a row click.
export function SourceUrlLink({ url, children }) {
  if (!url) return <span className="hint">—</span>;
  return (
    <a href={url} target="_blank" rel="noreferrer" title={url}
      onClick={(e) => e.stopPropagation()} style={{ wordBreak: 'break-all' }}>
      {children || url} ↗
    </a>
  );
}

// Renders admin-attached external links (Steam/GOG/Itch/custom). Each becomes a
// clickable badge when it has a url; otherwise it shows the id as plain text.
const EXT_LABEL = { steam: 'Steam', gog: 'GOG', itch: 'itch.io', custom: 'Link' };
export function ExternalLinkBadges({ links, onRemove }) {
  if (!links || !links.length) return null;
  const stop = (e) => e.stopPropagation();
  return (
    <span className="row" style={{ gap: 6 }}>
      {links.map((l) => {
        const name = l.kind === 'custom' ? (l.label || 'Link') : (EXT_LABEL[l.kind] || l.kind);
        const shown = l.ext_id ? `${name} ${l.ext_id}` : name;
        const inner = l.url
          ? <a className="badge badge-ext" href={l.url} target="_blank" rel="noreferrer" onClick={stop} title={l.url}>{shown} ↗</a>
          : <span className="badge badge-ext" title={l.ext_id || ''}>{shown}</span>;
        return (
          <span key={l.link_id} className="ext-chip">
            {inner}
            {onRemove && (
              <button className="ext-x" title="Remove link"
                onClick={(e) => { stop(e); onRemove(l); }} aria-label="Remove link">×</button>
            )}
          </span>
        );
      })}
    </span>
  );
}

// Renders f95 / lc source ids. When a site_url is available the id becomes a
// clickable link that opens the source thread in a new tab. `stopPropagation`
// keeps a click on the link from also triggering a row click.
export function SourceBadges({ row }) {
  const f95 = row.f95_id ?? (row._sources && row._sources.f95_id);
  const lc = row.lc_id ?? (row._sources && row._sources.lc_id);
  const f95Url = row.f95_url;
  const lcUrl = row.lc_url;
  const stop = (e) => e.stopPropagation();
  return (
    <span className="row" style={{ gap: 6 }}>
      {f95 != null && (f95Url
        ? <a className="badge badge-f95" href={f95Url} target="_blank" rel="noreferrer" onClick={stop} title="Open on F95zone">f95 {f95} ↗</a>
        : <span className="badge badge-f95">f95 {f95}</span>)}
      {lc != null && (lcUrl
        ? <a className="badge badge-lc" href={lcUrl} target="_blank" rel="noreferrer" onClick={stop} title="Open on LewdCorner">lc {lc} ↗</a>
        : <span className="badge badge-lc">lc {lc}</span>)}
      {f95 == null && lc == null && <span className="badge badge-muted">no source</span>}
    </span>
  );
}

// Renders detailed source links from a `_links` array (used in editor / merge).
export function SourceLinkList({ links }) {
  if (!links || !links.length) return <span className="hint">no sources</span>;
  const stop = (e) => e.stopPropagation();
  const cls = (t) => (t === 'f95_zone' ? 'badge-f95' : t === 'lewdcorner' ? 'badge-lc' : 'badge-muted');
  const label = (t) => (t === 'f95_zone' ? 'f95' : t === 'lewdcorner' ? 'lc' : t.replace('_zone', ''));
  return (
    <span className="row" style={{ gap: 6 }}>
      {links.map((l) => (l.site_url
        ? <a key={`${l.source}-${l.id}`} className={`badge ${cls(l.source)}`} href={l.site_url} target="_blank" rel="noreferrer" onClick={stop} title={`Open ${label(l.source)} ${l.id}`}>{label(l.source)} {l.id} ↗</a>
        : <span key={`${l.source}-${l.id}`} className={`badge ${cls(l.source)}`}>{label(l.source)} {l.id}</span>
      ))}
    </span>
  );
}

export function Notice({ kind, children, onClose }) {
  if (!children) return null;
  return (
    <div className={`notice ${kind === 'err' ? 'notice-err' : 'notice-ok'}`}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span>{children}</span>
        {onClose && <button className="x" onClick={onClose} aria-label="Dismiss">×</button>}
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children, footer }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="panel modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Spinner({ label = 'Loading…' }) {
  return <div className="spinner">{label}</div>;
}
