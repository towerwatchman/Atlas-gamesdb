import React from 'react';

// ---------------------------------------------------------------------------
// Changelog rendering — shared by the Home activity feed and the full
// Changelog page. Turns a raw atlas_audit row into a readable line.
// ---------------------------------------------------------------------------

export const GROUP_LABEL = {
  edit: 'Edit', merge: 'Merge', queue: 'Queue',
  link: 'Link', auth: 'Auth', user: 'User', other: 'Other',
};

const GROUP_CLASS = {
  edit: 'cl-edit', merge: 'cl-merge', queue: 'cl-queue',
  link: 'cl-link', auth: 'cl-auth', user: 'cl-user', other: 'cl-other',
};

export function fmtWhen(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

// Human-readable description of a single entry. Falls back gracefully for any
// verb we don't special-case.
export function describe(entry) {
  const f = entry.field || '';
  const val = (s) => (s == null || s === '' ? '∅' : String(s));

  if (f.startsWith('atlas.')) {
    const col = f.slice('atlas.'.length);
    return <>changed <b>{col}</b> from <i>{val(entry.old_value)}</i> to <i>{val(entry.new_value)}</i></>;
  }
  if (f === 'manual_link.add')    return <>added external link — <i>{val(entry.new_value)}</i></>;
  if (f === 'manual_link.remove') return <>removed external link — <i>{val(entry.old_value)}</i></>;
  if (f === 'auth.login')  return <>signed in</>;
  if (f === 'auth.logout') return <>signed out</>;
  if (f === 'user.add')    return <>added admin user <b>{val(entry.new_value)}</b></>;
  if (f === 'user.remove') return <>removed admin user <b>{val(entry.old_value)}</b></>;

  // merge.* / lc.* / queue.* structural verbs: show verb + old→new when present
  const verb = f.replace(/^(merge|lc|queue)\./, (m) => m).replace('.', ' · ');
  if (entry.old_value || entry.new_value) {
    return <>{verb} <i>{val(entry.old_value)}</i>{entry.new_value ? <> → <i>{val(entry.new_value)}</i></> : null}</>;
  }
  return <>{verb}</>;
}

export function GroupTag({ group }) {
  return <span className={`cl-tag ${GROUP_CLASS[group] || 'cl-other'}`}>{GROUP_LABEL[group] || group}</span>;
}

// Reusable list. `onOpenGame` (optional) makes game entries clickable.
export function ChangelogList({ entries, onOpenGame, compact }) {
  if (!entries || !entries.length) {
    return <p className="hint">No activity to show.</p>;
  }
  return (
    <ul className={`changelog ${compact ? 'changelog-compact' : ''}`}>
      {entries.map((e) => {
        const game = e.atlas_id
          ? <span className={`cl-game ${onOpenGame ? 'cl-game-link' : ''}`}
              onClick={onOpenGame ? () => onOpenGame(e.atlas_id) : undefined}
              title={onOpenGame ? 'Open game' : undefined}>
              {e.atlas_title || `#${e.atlas_id}`}
            </span>
          : null;
        return (
          <li key={e.audit_id} className="cl-row">
            <GroupTag group={e.action_group} />
            <span className="cl-body">
              <b className="cl-user">{e.admin_user}</b> {describe(e)}
              {game ? <> · {game}</> : null}
            </span>
            <span className="cl-when">{fmtWhen(e.ts)}</span>
          </li>
        );
      })}
    </ul>
  );
}
