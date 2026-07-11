import React from 'react';

export function SourceBadges({ row }) {
  const f95 = row.f95_id ?? (row._sources && row._sources.f95_id);
  const lc = row.lc_id ?? (row._sources && row._sources.lc_id);
  return (
    <span className="row" style={{ gap: 6 }}>
      {f95 != null && <span className="badge badge-f95">f95 {f95}</span>}
      {lc != null && <span className="badge badge-lc">lc {lc}</span>}
      {f95 == null && lc == null && <span className="badge badge-muted">no source</span>}
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
