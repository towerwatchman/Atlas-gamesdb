import React from 'react';

// ---------------------------------------------------------------------------
// Date fields and per-field locks for the atlas editor.
//
// Dates are stored as epoch seconds. Before this they rendered as plain text
// inputs, so setting one meant typing "1768953600" by hand. `datetime-local`
// gives a picker while keeping the stored value an epoch.
//
// Locks mark a field as human-owned; the scraper skips locked columns on its
// next crawl (scraper/utils/db.py::updateAtlasById). Editing a field locks it
// automatically — the toggle is for handing a field back.
// ---------------------------------------------------------------------------

/** epoch seconds -> the "YYYY-MM-DDTHH:mm" a datetime-local input wants. */
export function epochToLocalInput(epoch) {
  if (epoch === '' || epoch === null || epoch === undefined) return '';
  const n = Number(epoch);
  if (!Number.isFinite(n) || n <= 0) return '';
  const d = new Date(n * 1000);
  if (Number.isNaN(d.getTime())) return '';
  // Shift by the offset so toISOString (UTC) yields local wall-clock time.
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

/** "YYYY-MM-DDTHH:mm" (local) -> epoch seconds, or '' when cleared. */
export function localInputToEpoch(value) {
  if (!value) return '';
  const ms = new Date(value).getTime();
  if (Number.isNaN(ms)) return '';
  return String(Math.floor(ms / 1000));
}

export function DateField({ id, value, onChange, disabled }) {
  return (
    <div className="row" style={{ gap: 8, alignItems: 'center' }}>
      <input
        id={id}
        type="datetime-local"
        value={epochToLocalInput(value)}
        disabled={disabled}
        onChange={(e) => onChange(localInputToEpoch(e.target.value))}
        style={{ flex: '1 1 auto' }}
      />
      {value ? (
        <>
          <span className="mono hint" title="stored value">{value}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => onChange('')}
            disabled={disabled}
            title="Clear the date"
          >
            clear
          </button>
        </>
      ) : <span className="hint">not set</span>}
    </div>
  );
}

/**
 * Lock toggle shown beside a field label.
 *
 * `lockable` is false for last_record_update: it drives the delta packager, so
 * a lock would keep the row out of every future package.
 */
export function LockToggle({ field, locked, lockable, busy, onToggle }) {
  if (!lockable) return null;
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={() => onToggle(field, !locked)}
      disabled={busy}
      title={locked
        ? 'Locked: the scraper will not overwrite this field. Click to hand it back.'
        : 'Unlocked: the next crawl may overwrite this. Click to keep your value.'}
      style={{
        padding: '0 6px',
        opacity: locked ? 1 : 0.45,
        borderColor: locked ? 'var(--teal-bright)' : undefined,
      }}
      aria-label={locked ? `Unlock ${field}` : `Lock ${field}`}
    >
      {locked ? '🔒' : '🔓'}
    </button>
  );
}

/** The warning shown under last_record_update. */
export function ExportStampWarning() {
  return (
    <p className="hint" style={{ color: 'var(--warn, #c80)', margin: '2px 0 0' }}>
      This is the export timestamp the delta packager uses to decide what
      changed. Setting it <strong>backwards</strong> drops this game out of the
      next incremental package, so its changes will not reach clients until
      something bumps it again. It cannot be locked — the scraper has to stay
      free to update it.
    </p>
  );
}
